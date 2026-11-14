# ai-eval

Replay and grading harness for the Mac Studio bake-off
(`docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md`).
Captures come from `ai-tap` (`kubernetes/apps/ai/ai-tap/`).

**Captured prompts are personal data.** `corpus/` and `results/` are
gitignored. Keep them on-cluster (HolyClaude `/workspace`) or on the Mac.
Only aggregate tables go to `docs/ai-history/mac-studio.md`.

## Setup

Run everything from `tools/ai-eval/` (the paths below are relative to it).
`corpus/` and `results/` are gitignored there and at the repo root as a
safety net; never `git add -f` them.

    cd tools/ai-eval
    pip install --break-system-packages -r requirements.txt
    python3 -m pytest tests -q -p no:cacheprovider

## Pull a corpus snapshot

    snap=corpus/$(date +%F)
    mkdir -p "$snap" results
    kubectl -n ai exec deploy/ai-tap -- tar -C /data -cf - . | tar -C "$snap" -xf -

## Replay and grade

    # Hindsight: production model alias via the tap's upstream (sanity baseline)
    python3 replay.py --corpus "$snap" --consumer hindsight \
      --base-url http://llama-swap.ai.svc.cluster.local:8080/v1 --model reasoner \
      --concurrency 5 --limit 200 --out results/hindsight-prod.jsonl
    python3 grade.py results/hindsight-prod.jsonl --markdown --label "hindsight: gpt-oss-20b (llama-swap)"

    # HA intent set: GPT-5.5 baseline once, then each candidate
    export EVAL_API_KEY=<HA's Omniroute key, from omniroute-secret.sops.yaml via task sops:view>
    python3 replay.py --corpus "$snap" --consumer ha --ha-intents corpus/ha_intents.yaml \
      --base-url http://omniroute.ai.svc.cluster.local:20128/v1 --model cliproxyapi/gpt-5.5 \
      --out results/ha-gpt55.jsonl
    python3 replay.py --corpus "$snap" --consumer ha --ha-intents corpus/ha_intents.yaml \
      --base-url http://<mac>:<port>/v1 --model <candidate> --out results/ha-<candidate>.jsonl
    python3 grade.py results/ha-<candidate>.jsonl --ha-baseline results/ha-gpt55.jsonl --markdown --label "ha: <candidate>"

Use `--concurrency 1` for c=1 numbers and `--concurrency 5` for c=5. Run one
engine at a time on an idle Mac (spec).

## Bake-off on the Mac

Engines are measured from the Mac against `127.0.0.1`, so nothing on trial
needs exposing. Plan: `docs/superpowers/plans/2026-10-19-phase2-bakeoff.md`.

    ssh -F ~/.claude/ssh/config mac-jms-01 'mkdir -p ~/bakeoff/ai-eval && chmod 700 ~/bakeoff'
    tar -C tools/ai-eval --exclude=__pycache__ --exclude=results -cf - . | ssh -F ~/.claude/ssh/config mac-jms-01 'tar -C ~/bakeoff/ai-eval -xf -'

Synthetic probe (cold vs cache-hit TTFT at fixed prefixes, decode at c=1/c=5;
no vllm needed):

    python3 prefix_bench.py --base-url http://127.0.0.1:<port>/v1 --model <model> \
      --prefix-tokens 0,8192,32768 --concurrency 1,5 --label "<engine> <model>" \
      --out results/bench-<label>.jsonl

Peak memory: `./memsample.sh <engine pid> > results/mem-<label>.csv` during the
run; peak is the max `rss_mb`. RSS can undercount Metal memory, so cross-check
`mem_free_pct`.

## Synthetic load (`vllm bench serve`)

For TTFT at fixed 0/8K/32K prefixes and concurrency sweeps, independent of
the corpus. Run it on the Mac where vllm-metal is installed:

    vllm bench serve --backend openai-chat --base-url http://127.0.0.1:<port> \
      --endpoint /v1/chat/completions --model <model> --dataset-name random \
      --random-input-len 8192 --random-output-len 256 --num-prompts 50 --max-concurrency 5

## Metrics

| Metric | Meaning |
|---|---|
| error_rate | transport or HTTP failure, a malformed SSE line, a mid-stream error event, or a stream that ended with neither `finish_reason` nor `[DONE]` (truncated) |
| empty_rate | 200 response with no text and no tool call (e.g. a server that ignored `stream`, or a thinking model that spent its budget on reasoning); excluded from latency stats |
| structured_valid_rate | answer parses and meets the request's `response_format` (errors count as invalid) |
| fact_recall_mean | share of production's JSON facts (production answers that were truncated or errored in capture have no reference and are not scored) matched by the candidate (token Jaccard ≥ 0.5) |
| tool_valid_rate | candidate tool calls name an offered tool and their args validate against its `parameters` schema (errors count as invalid when tools were offered) |
| ha_agreement_rate | same tool calls (name + normalised args) as GPT-5.5 on the intent set; errored or empty answers disagree. Two text-only answers agree regardless of wording — check state-query intents by hand |
| ttft / latency / decode_tps | measured on streaming replay; decode = completion tokens ÷ (latency − TTFT) |

## Fast-lane and voice candidates (oMLX, 2026-11)

Evaluates open "Haiku-class" models for Hindsight and Home Assistant, and speech models for
Assist. Plan and rationale: `docs/research/2026-11-13-omlx-splash-model-evaluation/`.
Run on a quiet Mac against `127.0.0.1:8000`; oMLX loads a candidate on first request, so the
first row of each run includes cold load. `EVAL_API_KEY` is the oMLX API key. Use one candidate
per run and one concurrency setting at a time.

    export EVAL_API_KEY=...   # oMLX key; never commit it
    M=gemma-4-26B-A4B-it-QAT-MLX-4bit            # the model id oMLX lists in /v1/models
    NOTHINK='{"chat_template_kwargs":{"enable_thinking":false}}'   # for models whose template supports it

    # Hindsight: same 200-request sample (seed 0) as the 2026-10 bake-off, so the on-Mac
    # gpt-oss-20b rows in results/ are the control (structured 0.97, recall 0.618 at c=5).
    python3 replay.py --corpus corpus/2026-10-19 --consumer hindsight --base-url http://127.0.0.1:8000/v1 \
      --model "$M" --concurrency 5 --limit 200 --out results/hindsight-$M-c5.jsonl
    python3 grade.py results/hindsight-$M-c5.jsonl --markdown --label "hindsight: $M"

    # Home Assistant: synthetic house, graded against expected tool calls (no captured HA traffic or cloud
    # baseline needed). --repeat 3 gives warm-cache latency; thinking models usually need --extra-body.
    python3 ha_suite.py --base-url http://127.0.0.1:8000/v1 --model "$M" --repeat 3 \
      --extra-body "$NOTHINK" --out results/ha-suite-$M.jsonl --label "ha-suite: $M"

    # Same suite against a live Home Assistant agent's exact prompt template and tool schema (export its
    # conversation subentry's `prompt` and `functions` to JSON; needs jinja2; includes vague/ambiguous requests):
    python3 ha_suite.py --base-url http://127.0.0.1:8000/v1 --model local-ha --repeat 3 \
      --live-config live-config.json --out results/ha-live-local-ha.jsonl

    # Speech: STT uses macOS `say` clips (independent of the TTS models); TTS is round-tripped through
    # a reference STT model. --contend sustains back-to-back ~30K-token prefills on the coding model; only rows that fully overlapped a successful prefill count (the rest are listed as excluded), and the run fails if none did.
    python3 voice_bench.py stt --base-url http://127.0.0.1:8000/v1 --model parakeet-tdt-0.6b-v3 --out results/stt-parakeet.jsonl
    # use the -asr-fp16 repo: the plain whisper-large-v3-turbo repo ships no processor/tokenizer files and cannot load in oMLX
    python3 voice_bench.py stt --base-url http://127.0.0.1:8000/v1 --model whisper-large-v3-turbo-asr-fp16 --out results/stt-whisper.jsonl
    # robustness: --voice Daniel|Karen|Moira|Aman for accents, --snr-db 10 / 0 for added noise
    python3 voice_bench.py stt --base-url http://127.0.0.1:8000/v1 --model parakeet-tdt-0.6b-v3 --snr-db 0 --out results/stt-parakeet-snr0.jsonl
    # several reference models transcribe the identical saved audio, so their disagreements are comparable
    python3 voice_bench.py tts --base-url http://127.0.0.1:8000/v1 --model Kokoro-82M-bf16 --voice af_heart \
      --stt-model parakeet-tdt-0.6b-v3,whisper-large-v3-turbo-asr-fp16 --save-audio results/audio-kokoro --out results/tts-kokoro.jsonl
    python3 voice_bench.py stt --base-url http://127.0.0.1:8000/v1 --model parakeet-tdt-0.6b-v3 \
      --contend local-coding:long --out results/stt-parakeet-contended.jsonl

Gates (proposed; set before looking at results): Hindsight structured_valid >= 0.95 and recall
within 5% of the 0.618 control; HA suite pass_rate >= 0.9 with zero `bash` calls and tool_valid 1.0,
warm ttft p50 < 1 s; STT mean WER <= 0.10 on the clip set and short-command latency p95 < 1.5 s,
unchanged by more than ~2x under `--contend`. The HA suite is synthetic and the speech clips are
short synthetic phrases: they screen candidates, they do not prove production accuracy.

## Retention

Delete `corpus/`, `results/`, the `ai-tap` app and its PVC after the last
consumer cuts over (Phase 3).
