# Mac Studio (mac-jms-01) serving bake-off

Aggregate results only. Prompts and responses stay in the gitignored
`tools/ai-eval/corpus/` and `results/` (spec: eval corpus). Plan:
`docs/superpowers/plans/2026-10-19-phase2-bakeoff.md`.

## Production baselines (2026-10-19)

Corpus snapshot `2026-10-19`: ai-tap captures from 2026-10-14 to 10-19.
Only Hindsight has traffic so far. atuin routes through the tap but sent
nothing, HA isn't repointed yet, and argus is disabled.

### hindsight: gpt-oss-20b (llama-swap, prod)

Replayed against production at c=5, 200 sampled requests, seed 1.

| consumer | n | error_rate | empty_rate | structured_valid_rate | tool_valid_rate | fact_recall_mean | ttft_ms_p50 | ttft_ms_p95 | latency_ms_p50 | latency_ms_p95 | decode_tps_median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hindsight | 200 | 0.0 | 0.095 | 0.889 | 1.0 | 0.675 | 6486 | 36037 | 46325 | 157649 | 39.1 |

How to read this:
- `fact_recall_mean` here compares production with itself, so 0.675 is the run-to-run noise ceiling. A candidate at around 0.67 is matching production, not losing 33%.
- `empty_rate` 0.095 means production returns no answer on almost 1 in 10 requests (probably the reasoning budget spent before any output). That's the bar to beat, not a harness fault.
- p95 latency is 158s, over Omniroute's 120s `maxWaitMs` cap. This confirms why Hindsight bypasses Omniroute, and it's evidence for the gateway evaluation's "no cap below 600s" requirement.

### ha: GPT-5.5 baseline

Dropped (2026-10-19): HA is being torn down and rebuilt (#764), so there's no HA baseline.
