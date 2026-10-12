# ai-eval

Replay and grading harness for the Mac Studio bake-off
(`docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md`).
Captures come from `ai-tap` (`kubernetes/apps/ai/ai-tap/`).

**Captured prompts are personal data.** `corpus/` and `results/` are
gitignored. Keep them on-cluster (HolyClaude `/workspace`) or on the Mac.
Only aggregate tables go to `docs/ai-history/mac-studio.md`.

## Setup

    pip install --break-system-packages -r requirements.txt
    python3 -m pytest tests -q -p no:cacheprovider

## Pull a corpus snapshot

    snap=corpus/$(date +%F)
    mkdir -p "$snap"
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

## Synthetic load (`vllm bench serve`)

For TTFT at fixed 0/8K/32K prefixes and concurrency sweeps, independent of
the corpus. Run it on the Mac where vllm-metal is installed:

    vllm bench serve --backend openai-chat --base-url http://127.0.0.1:<port> \
      --endpoint /v1/chat/completions --model <model> --dataset-name random \
      --random-input-len 8192 --random-output-len 256 --num-prompts 50 --max-concurrency 5

## Metrics

| Metric | Meaning |
|---|---|
| error_rate | transport or HTTP failure |
| empty_rate | 200 response with no text and no tool call (e.g. a server that ignored `stream`, or a thinking model that spent its budget on reasoning); excluded from latency stats |
| structured_valid_rate | answer parses and meets the request's `response_format` (errors count as invalid) |
| fact_recall_mean | share of production's JSON facts matched by the candidate (token Jaccard ≥ 0.5) |
| tool_valid_rate | candidate tool calls name an offered tool and their args validate against its `parameters` schema (errors count as invalid when tools were offered) |
| ha_agreement_rate | same tool calls (name + normalised args) as GPT-5.5 on the intent set; errored or empty answers disagree. Two text-only answers agree regardless of wording — check state-query intents by hand |
| ttft / latency / decode_tps | measured on streaming replay; decode = completion tokens ÷ (latency − TTFT) |

## Retention

Delete `corpus/`, `results/`, the `ai-tap` app and its PVC after the last
consumer cuts over (Phase 3).
