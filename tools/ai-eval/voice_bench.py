"""Speech smoke benchmark for oMLX's OpenAI-compatible audio endpoints.

No personal audio: inputs are fixed home-control phrases. STT clips come from macOS `say` (an
independent voice, so a TTS model is never graded on its own output) converted to 16 kHz mono WAV.
TTS output is checked for valid WAV, real-time factor, and a round trip: the audio is transcribed
by a reference STT model and scored against the input text. `--contend` sustains long chat prefills on
another model, to see what speech latency does while the coding model is busy; each row is labelled
contended only if a successful prefill was in flight for its whole request.

  python3 voice_bench.py stt --base-url http://127.0.0.1:8000/v1 --model parakeet-tdt-0.6b-v3 --out results/stt-parakeet.jsonl
  python3 voice_bench.py tts --base-url http://127.0.0.1:8000/v1 --model Kokoro-82M-bf16 --voice af_heart \
      --stt-model whisper-large-v3-turbo --out results/tts-kokoro.jsonl
"""

import argparse
import array
import io
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import wave

PHRASES = [
    "turn on the living room lamp",
    "set the bedroom thermostat to sixty eight degrees",
    "is the front door locked",
    "lock the back door and turn off the kitchen lights",
    "what time is it",
    "close the garage door",
    "dim the office light to thirty percent",
    "how warm is it in the bedroom",
    "start the robot vacuum in the hallway",
    "tell me whether the washer is finished",
    "turn off everything downstairs and arm the alarm for the night",
    "remind me to take the trash out when I get home tomorrow evening",
]

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _number_words(n):
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (" " + _ONES[ones] if ones else "")


def normalize(text):
    """Lower-case, spell out integers under 100, drop punctuation, collapse whitespace."""
    text = re.sub(r"\b(\d{1,2})\b", lambda m: _number_words(int(m.group(1))), text.lower())
    text = text.replace("%", " percent").replace("°", " degrees")
    text = re.sub(r"\bper cent\b", "percent", text)
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())


def wer(reference, hypothesis):
    """Word error rate of hypothesis against reference after normalisation."""
    ref, hyp = normalize(reference).split(), normalize(hypothesis).split()
    if not ref:
        raise ValueError("empty reference")
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1] / len(ref)


def wav_seconds(data):
    with wave.open(io.BytesIO(data)) as w:
        return w.getnframes() / w.getframerate()


def make_clip(text, voice="Samantha"):
    """16 kHz mono 16-bit WAV bytes of `text` spoken by macOS `say`."""
    with tempfile.TemporaryDirectory() as tmp:
        aiff, wav = os.path.join(tmp, "c.aiff"), os.path.join(tmp, "c.wav")
        subprocess.run(["say", "-v", voice, "-o", aiff, text], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
        with open(wav, "rb") as f:
            return f.read()


def add_noise(wav, snr_db, seed=0):
    """Mix deterministic Gaussian noise into a 16-bit mono WAV at the given SNR (dB, vs. the clip's RMS).
    shortcut: assumes a little-endian host (true for Apple silicon); swap bytes before porting."""
    with wave.open(io.BytesIO(wav)) as w:
        params, frames = w.getparams(), w.readframes(w.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0
    sigma = rms / (10 ** (snr_db / 20))
    rng = random.Random(seed)
    noisy = array.array("h", (max(-32768, min(32767, int(s + rng.gauss(0, sigma)))) for s in samples))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setparams(params)
        w.writeframes(noisy.tobytes())
    return buf.getvalue()


def multipart(fields, filename, payload, content_type="audio/wav"):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                  f"Content-Type: {content_type}\r\n\r\n").encode() + payload + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _post(base_url, path, body, content_type, api_key, timeout):
    headers = {"Content-Type": content_type}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base_url.rstrip("/") + path, data=body, headers=headers, method="POST")
    started = time.monotonic()
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            data = resp.read()
        error = None
    except Exception as exc:  # one bad request is one failed row, never a failed run
        detail = getattr(exc, "read", lambda: b"")()[:300].decode("utf-8", "replace")
        data, error = b"", f"{type(exc).__name__}: {exc} {detail}".strip()
    ended = time.monotonic()
    return {"error": error, "seconds": ended - started, "body": data, "t0": started, "t1": ended}


def transcribe(base_url, model, wav, api_key=None, timeout=120, language="en"):
    body, ctype = multipart({"model": model, "language": language, "response_format": "json"}, "clip.wav", wav)
    r = _post(base_url, "/audio/transcriptions", body, ctype, api_key, timeout)
    base = {"seconds": r["seconds"], "t0": r["t0"], "t1": r["t1"]}
    if r["error"]:
        return {**base, "error": r["error"], "text": None}
    try:
        return {**base, "error": None, "text": json.loads(r["body"])["text"]}
    except (ValueError, KeyError, TypeError) as exc:
        return {**base, "error": f"bad transcription response: {exc}", "text": None}


def speak(base_url, model, text, voice, api_key=None, timeout=120):
    payload = {"model": model, "input": text, "response_format": "wav"}
    if voice:
        payload["voice"] = voice
    r = _post(base_url, "/audio/speech", json.dumps(payload).encode(), "application/json", api_key, timeout)
    base = {"seconds": r["seconds"], "t0": r["t0"], "t1": r["t1"], "audio": None, "audio_seconds": None}
    if r["error"]:
        return {**base, "error": r["error"]}
    try:
        return {**base, "error": None, "audio": r["body"], "audio_seconds": wav_seconds(r["body"])}
    except (wave.Error, EOFError) as exc:
        return {**base, "error": f"response is not a WAV: {exc}"}


class Contention:
    """Sustained load: back-to-back long cache-busted chat prefills on another model.

    Every request's in-flight window and outcome is recorded. A speech row counts as contended only if
    a *successful* prefill (or a run of them with gaps under `tol`) was in flight for the row's whole
    request, so an early finish, a failure, or a gap never labels a row as loaded.
    """

    def __init__(self, base_url, model, words, api_key=None, timeout=900):
        self.base_url, self.model, self.words, self.api_key, self.timeout = base_url, model, words, api_key, timeout
        self.intervals = []  # (t0, t1, ok)
        self.errors = []
        self.started = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self):
        while not self._stop.is_set():
            filler = f"nonce-{uuid.uuid4().hex} " + "alpha beta gamma delta. " * (self.words // 4)
            body = json.dumps({"model": self.model, "max_tokens": 32, "stream": False,
                               "messages": [{"role": "user", "content": filler + "\nReply with OK."}]}).encode()
            self.started.set()
            r = _post(self.base_url, "/chat/completions", body, "application/json", self.api_key, self.timeout)
            self.intervals.append((r["t0"], r["t1"], r["error"] is None))
            if r["error"]:
                self.errors.append(r["error"])
                self._stop.wait(1.0)  # do not spin on a failing endpoint

    def start(self):
        self._thread.start()
        self.started.wait(10)
        return self

    def stop(self):
        self._stop.set()
        self._thread.join(self.timeout + 5)

    def covers(self, t0, t1, tol=0.25):
        merged = []
        for a, b in sorted((a, b) for a, b, ok in self.intervals if ok):
            if merged and a - merged[-1][1] <= tol:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        return any(a - tol <= t0 and t1 <= b for a, b in merged)


def _pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def summarize(rows):
    ok = [r for r in rows if r["error"] is None]
    out = {"n": len(rows), "error_rate": round(1 - len(ok) / len(rows), 3) if rows else None,
           "latency_s_p50": _pct([r["seconds"] for r in ok], 0.5), "latency_s_p95": _pct([r["seconds"] for r in ok], 0.95)}
    rtf = [r["seconds"] / r["audio_seconds"] for r in ok if r.get("audio_seconds")]
    out["rtf_median"] = round(statistics.median(rtf), 3) if rtf else None  # <1 = faster than real time
    wers = [r["wer"] for r in ok if r.get("wer") is not None]
    out["wer_mean"] = round(statistics.mean(wers), 3) if wers else None
    out["wer_max"] = round(max(wers), 3) if wers else None
    return out


def run_stt(args, api_key):
    rows = []
    for rep in range(args.repeat):
        for phrase in PHRASES:
            wav = make_clip(phrase, args.voice)
            if args.snr_db is not None:
                wav = add_noise(wav, args.snr_db, seed=rep * 1000 + PHRASES.index(phrase))
            r = transcribe(args.base_url, args.model, wav, api_key, args.timeout)
            rows.append({"kind": "stt", "model": args.model, "phrase": phrase, "rep": rep, "voice": args.voice,
                         "snr_db": args.snr_db, "audio_seconds": wav_seconds(wav),
                         "error": r["error"], "seconds": r["seconds"], "t0": r["t0"], "t1": r["t1"], "text": r["text"],
                         "wer": None if r["error"] else wer(phrase, r["text"])})
    return rows


def run_tts(args, api_key):
    rows = []
    refs = [m for m in (args.stt_model or "").split(",") if m]
    if args.save_audio:
        os.makedirs(args.save_audio, exist_ok=True)
    for rep in range(args.repeat):
        for i, phrase in enumerate(PHRASES):
            r = speak(args.base_url, args.model, phrase, args.voice, api_key, args.timeout)
            row = {"kind": "tts", "model": args.model, "phrase": phrase, "rep": rep, "error": r["error"],
                   "seconds": r["seconds"], "t0": r["t0"], "t1": r["t1"], "audio_seconds": r["audio_seconds"], "wer": None}
            if not r["error"] and args.save_audio:
                row["audio_file"] = os.path.join(args.save_audio, f"{args.model}-rep{rep}-p{i:02d}.wav")
                with open(row["audio_file"], "wb") as f:
                    f.write(r["audio"])
            if not r["error"] and refs:
                # The same bytes go to every reference model, so their transcripts are comparable per clip.
                row["roundtrips"] = {}
                for ref in refs:
                    back = transcribe(args.base_url, ref, r["audio"], api_key, args.timeout)
                    row["roundtrips"][ref] = ({"error": back["error"]} if back["error"]
                                              else {"text": back["text"], "wer": wer(phrase, back["text"])})
                first = row["roundtrips"][refs[0]]
                if "error" in first:
                    row["error"] = "roundtrip: " + first["error"]
                else:
                    row["wer"], row["roundtrip_text"] = first["wer"], first["text"]
            rows.append(row)
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["stt", "tts"])
    p.add_argument("--base-url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--voice", help="stt: macOS say voice (default Samantha; try Daniel, Karen, Moira, Aman for accents); tts: model voice id")
    p.add_argument("--snr-db", type=float, help="stt: mix in Gaussian noise at this signal-to-noise ratio (deterministic per clip)")
    p.add_argument("--stt-model", help="tts: reference STT model(s) for the round-trip WER check, comma-separated; every reference transcribes the same audio, the first one drives the summary")
    p.add_argument("--save-audio", metavar="DIR", help="tts: keep each generated clip so a failed one can be re-checked")
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("--contend", metavar="CHAT_MODEL", help="run a long chat prefill on this model during the test")
    p.add_argument("--contend-words", type=int, default=24000, help="filler words for the contending prefill (~1.3 tokens each)")
    p.add_argument("--api-key-env", default="EVAL_API_KEY")
    p.add_argument("--label")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    if args.mode == "stt" and not args.voice:
        args.voice = "Samantha"
    api_key = os.environ.get(args.api_key_env)
    contention = Contention(args.base_url, args.contend, args.contend_words, api_key).start() if args.contend else None
    try:
        rows = (run_stt if args.mode == "stt" else run_tts)(args, api_key)
    finally:
        if contention:
            contention.stop()
    for row in rows:
        row["contended"] = bool(contention and contention.covers(row["t0"], row["t1"]))
    with open(args.out, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    measured = [r for r in rows if r["contended"]] if contention else rows
    summary = summarize(measured)
    print(f"### {args.label or args.model} ({args.mode}{', contended' if contention else ''})\n")
    if contention:
        print(f"Contended rows: {len(measured)} of {len(rows)} (the rest overlapped no successful prefill and are excluded)\n")
    print("| " + " | ".join(summary) + " |\n|" + "---|" * len(summary))
    print("| " + " | ".join("–" if v is None else str(v) for v in summary.values()) + " |")
    for r in rows:
        if r["error"]:
            print(f"ERROR {r['phrase']!r}: {r['error']}", file=sys.stderr)
    if contention:
        for e in contention.errors[:3]:
            print(f"CONTENTION ERROR: {e}", file=sys.stderr)
        if not measured:
            raise SystemExit("no speech request overlapped a successful prefill: this contended run is invalid")


if __name__ == "__main__":
    main()
