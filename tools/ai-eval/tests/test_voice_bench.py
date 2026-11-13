import io
import json
import re
import shutil
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import voice_bench as v


def wav_bytes(seconds=1.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def test_wer_handles_substitution_deletion_insertion_and_normalisation():
    assert v.wer("turn on the lamp", "Turn on the lamp.") == 0
    assert v.wer("turn on the lamp", "turn off the lamp") == 0.25
    assert v.wer("turn on the lamp", "turn the lamp") == 0.25
    assert v.wer("turn on the lamp", "please turn on the lamp") == 0.25
    assert v.wer("one two", "") == 1.0
    # numerals and symbols must not count as errors against spelled-out phrases
    assert v.wer("set it to sixty eight degrees", "Set it to 68°.") == 0
    assert v.wer("dim to thirty percent", "dim to 30%") == 0
    assert v.wer("dim to thirty percent", "Dim to thirty per cent.") == 0  # a British spelling is not an error
    with pytest.raises(ValueError):
        v.wer("", "anything")


def test_multipart_body_carries_fields_and_binary_payload_intact():
    payload = bytes(range(256)) * 4
    body, ctype = v.multipart({"model": "m", "language": "en"}, "clip.wav", payload)
    boundary = ctype.split("boundary=")[1]
    assert body.endswith(f"--{boundary}--\r\n".encode())
    assert b'name="model"\r\n\r\nm\r\n' in body and b'name="language"\r\n\r\nen\r\n' in body
    assert b'name="file"; filename="clip.wav"' in body
    assert payload in body


def test_wav_seconds_reads_duration():
    assert v.wav_seconds(wav_bytes(1.5)) == pytest.approx(1.5)


class FakeAudio(BaseHTTPRequestHandler):
    transcript = "turn on the lamp"
    mode = "ok"
    chat_delay = 0.0
    chat_status = 200
    uploads = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        FakeAudio.last = (self.path, self.headers["Content-Type"], body, self.headers.get("Authorization"))
        if FakeAudio.mode == "http500":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"model not loaded")
            return
        if self.path.endswith("/audio/transcriptions"):
            boundary = self.headers["Content-Type"].split("boundary=")[1].encode()
            model = re.search(rb'name="model"\r\n\r\n([^\r]+)', body).group(1).decode()
            audio = body.split(b"Content-Type: audio/wav\r\n\r\n", 1)[1].split(b"\r\n--" + boundary)[0]
            FakeAudio.uploads.append((model, audio))
            out = b"not json" if FakeAudio.mode == "badjson" else json.dumps({"text": FakeAudio.transcript}).encode()
            ctype = "application/json"
        elif self.path.endswith("/audio/speech"):
            out = b"RIFFnotawav" if FakeAudio.mode == "badwav" else wav_bytes(2.0)
            ctype = "audio/wav"
        else:  # chat completions (contention)
            time.sleep(FakeAudio.chat_delay)
            if FakeAudio.chat_status != 200:
                self.send_response(FakeAudio.chat_status)
                self.end_headers()
                self.wfile.write(b"overloaded")
                return
            out, ctype = json.dumps({"choices": []}).encode(), "application/json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


@pytest.fixture()
def server():
    FakeAudio.mode, FakeAudio.transcript = "ok", "turn on the lamp"
    FakeAudio.chat_delay, FakeAudio.chat_status = 0.0, 200
    FakeAudio.uploads = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeAudio)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_transcribe_success_sends_model_audio_and_key(server):
    r = v.transcribe(server, "parakeet", wav_bytes(), api_key="k")
    assert r["error"] is None and r["text"] == "turn on the lamp"
    path, ctype, body, auth = FakeAudio.last
    assert path == "/v1/audio/transcriptions" and auth == "Bearer k" and ctype.startswith("multipart/form-data")
    assert b'name="model"\r\n\r\nparakeet' in body


@pytest.mark.parametrize("mode,fragment", [("http500", "model not loaded"), ("badjson", "bad transcription response")])
def test_transcribe_failures_are_rows_not_exceptions(server, mode, fragment):
    FakeAudio.mode = mode
    r = v.transcribe(server, "m", wav_bytes())
    assert r["text"] is None and fragment in r["error"]


def test_speak_returns_valid_audio_or_a_clear_error(server):
    r = v.speak(server, "kokoro", "hello there", "af_heart")
    assert r["error"] is None and r["audio_seconds"] == pytest.approx(2.0)
    assert json.loads(FakeAudio.last[2]) == {"model": "kokoro", "input": "hello there", "response_format": "wav", "voice": "af_heart"}
    FakeAudio.mode = "badwav"
    assert "not a WAV" in v.speak(server, "kokoro", "hi", None)["error"]
    FakeAudio.mode = "http500"
    assert "model not loaded" in v.speak(server, "kokoro", "hi", None)["error"]


def test_tts_roundtrip_scores_the_reference_transcript(server, tmp_path):
    out = tmp_path / "o.jsonl"
    FakeAudio.transcript = "turn off the lamp"  # reference STT mishears one word of the first phrase
    args = ["tts", "--base-url", server, "--model", "kokoro", "--stt-model", "whisper", "--repeat", "1", "--out", str(out)]
    v.main(args)
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == len(v.PHRASES) and all(r["error"] is None for r in rows)
    first = rows[0]
    assert first["phrase"] == "turn on the living room lamp" and first["wer"] == pytest.approx(v.wer(first["phrase"], "turn off the lamp")) and first["wer"] > 0
    assert first["audio_seconds"] == pytest.approx(2.0)


def test_summary_ignores_failed_rows_for_latency_and_reports_rtf_and_wer():
    rows = [{"error": None, "seconds": 0.5, "audio_seconds": 2.0, "wer": 0.0},
            {"error": None, "seconds": 1.0, "audio_seconds": 2.0, "wer": 0.2},
            {"error": "boom", "seconds": 99.0, "audio_seconds": None, "wer": None}]
    s = v.summarize(rows)
    assert s["error_rate"] == 0.333 and s["latency_s_p95"] == 1.0
    assert s["rtf_median"] == 0.375 and s["wer_mean"] == 0.1 and s["wer_max"] == 0.2


def test_contention_sends_cache_busted_long_prompts_back_to_back_until_stopped(server):
    FakeAudio.chat_delay = 0.05
    seen = []
    orig = FakeAudio.do_POST

    def spy(self):
        orig(self)
        if self.path.endswith("/chat/completions"):
            seen.append(json.loads(FakeAudio.last[2]))

    FakeAudio.do_POST = spy
    try:
        c = v.Contention(server, "local-coding:long", 400).start()
        time.sleep(0.4)
        c.stop()
    finally:
        FakeAudio.do_POST = orig
    assert len(seen) >= 3 and all(s["model"] == "local-coding:long" for s in seen)
    nonces = {re.search(r"nonce-([0-9a-f]{32})", s["messages"][0]["content"]).group(1) for s in seen}
    assert len(nonces) == len(seen)  # every prefill is cache-busted
    assert len(seen[0]["messages"][0]["content"].split()) > 300
    assert c.errors == [] and all(ok for _, _, ok in c.intervals)


def test_covers_requires_a_successful_prefill_in_flight_for_the_whole_request():
    c = v.Contention("http://x/v1", "m", 4)
    c.intervals = [(10.0, 20.0, True), (20.1, 30.0, True), (40.0, 50.0, False), (60.0, 61.0, True)]
    assert c.covers(12.0, 13.0)
    assert c.covers(19.5, 20.5)  # bridged by back-to-back requests (gap 0.1 s)
    assert not c.covers(29.5, 30.5)  # prefill finished mid-request
    assert not c.covers(5.0, 11.0)  # prefill had not started
    assert not c.covers(41.0, 42.0)  # the only overlapping prefill failed
    assert not c.covers(70.0, 71.0)  # early completion: nothing in flight afterwards
    c.intervals.append((30.5, 35.0, True))  # a 0.5 s gap is not bridged
    assert not c.covers(29.8, 31.0)


def test_contended_run_labels_rows_by_real_overlap_and_excludes_the_rest(server, tmp_path, capsys):
    FakeAudio.chat_delay = 0.6  # each prefill outlasts the fast fake TTS requests
    out = tmp_path / "o.jsonl"
    v.main(["tts", "--base-url", server, "--model", "kokoro", "--repeat", "1", "--out", str(out), "--contend", "big"])
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert rows and all(r["contended"] for r in rows)
    printed = capsys.readouterr().out
    assert f"Contended rows: {len(rows)} of {len(rows)}" in printed and "contended" in printed


def test_failing_prefill_never_labels_rows_contended_and_invalidates_the_run(server, tmp_path, capsys):
    FakeAudio.chat_status = 503
    out = tmp_path / "o.jsonl"
    with pytest.raises(SystemExit, match="invalid"):
        v.main(["tts", "--base-url", server, "--model", "kokoro", "--repeat", "1", "--out", str(out), "--contend", "big"])
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert rows and not any(r["contended"] for r in rows)  # rows are kept, clearly unlabeled
    assert "CONTENTION ERROR" in capsys.readouterr().err


@pytest.mark.skipif(not shutil.which("say") or not shutil.which("afconvert"), reason="needs macOS say/afconvert")
def test_make_clip_yields_16khz_mono_wav():
    wav = v.make_clip("turn on the lamp")
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert w.getnframes() / 16000 > 0.5


def _tone(seconds=0.5, rate=16000, amp=8000):
    import math
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(int(amp * math.sin(2 * math.pi * 440 * i / rate)).to_bytes(2, "little", signed=True)
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


def _samples(wav):
    import array
    with wave.open(io.BytesIO(wav)) as w:
        a = array.array("h")
        a.frombytes(w.readframes(w.getnframes()))
    return a


def test_add_noise_hits_the_requested_snr_is_deterministic_and_keeps_the_format():
    import math
    clean = _tone()
    noisy = v.add_noise(clean, 10, seed=1)
    assert noisy == v.add_noise(clean, 10, seed=1) and noisy != v.add_noise(clean, 10, seed=2)
    a, b = _samples(clean), _samples(noisy)
    assert len(a) == len(b)
    signal = math.sqrt(sum(x * x for x in a) / len(a))
    noise = math.sqrt(sum((y - x) ** 2 for x, y in zip(a, b)) / len(a))
    assert 20 * math.log10(signal / noise) == pytest.approx(10, abs=0.5)
    with wave.open(io.BytesIO(noisy)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
    quieter = v.add_noise(clean, 0, seed=1)  # 0 dB is much noisier than 20 dB
    assert sum((y - x) ** 2 for x, y in zip(a, _samples(quieter))) > 50 * sum((y - x) ** 2 for x, y in zip(a, _samples(v.add_noise(clean, 20, seed=1))))


def test_add_noise_leaves_silence_silent():
    silent = io.BytesIO()
    with wave.open(silent, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)
    assert set(_samples(v.add_noise(silent.getvalue(), 5))) == {0}


def test_every_reference_model_transcribes_the_identical_saved_audio(server, tmp_path):
    out, audio_dir = tmp_path / "o.jsonl", tmp_path / "audio"
    v.main(["tts", "--base-url", server, "--model", "kokoro", "--stt-model", "ref-a,ref-b", "--repeat", "1",
            "--save-audio", str(audio_dir), "--out", str(out)])
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == len(v.PHRASES) and all(set(r["roundtrips"]) == {"ref-a", "ref-b"} for r in rows)
    for i, row in enumerate(rows):
        saved = open(row["audio_file"], "rb").read()
        sent = {m: a for m, a in FakeAudio.uploads[2 * i:2 * i + 2]}
        assert sent["ref-a"] == sent["ref-b"] == saved  # same bytes, not regenerated audio
        assert row["wer"] == row["roundtrips"]["ref-a"]["wer"]  # the first reference drives the summary

