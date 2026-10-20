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
- p95 latency is 158s. ~~This is over Omniroute's 120s `maxWaitMs` cap.~~ The 2026-10-20 forced-length test refuted this: `maxWaitMs` doesn't cut generations (see Gateway evidence). The "no cap below 600s" requirement still stands.

### ha: GPT-5.5 baseline

Dropped (2026-10-19): HA is being torn down and rebuilt (#764), so there's no HA baseline.

## Engine bake-off ledger

### Models (2026-10-19)

Both are MLX 4-bit (`bits: 4, group_size: 64, mode: affine` in `config.json`). oMLX reads them from `/opt/ai/models.noindex/`, as APFS clones (`cp -c`) owned by `_omlx`. The clones' shard sizes match the sources byte for byte, and `_omlx` can read them.

| Model | HF repo | Revision | Size | Source copy |
|---|---|---|---|---|
| Qwen3.6-35B-A3B | `lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit` | `0c4a20a6437ae5985ddc9eb1a3f122ee6c151c3b` | 19G (4 shards) | `~/bakeoff/models/` |
| Qwen3.8-27B | `lmstudio-community/Qwen3.8-27B-MLX-4bit` | unknown (downloaded by LM Studio, no HF metadata) | 15G (3 shards) | `~/.lmstudio/models/` |

### Thinking mode (methodology, 2026-10-20)

Qwen3.6/3.8 MLX builds think by default (oMLX reports `thinking_default: true`), and Hindsight's production requests carry no reasoning control. The first oMLX Qwen3.6-35B replay therefore benchmarked thinking. Across 51 requests at c=5, reasoning averaged about 15.7K characters per 2K-character answer (median), with latency p50 178 s, p95 283 s and max 1013 s. That pass was stopped and kept as `hindsight-omlx-q36-35b-think-c5-partial.jsonl`, outside git. All engine passes from here on send `chat_template_kwargs: {"enable_thinking": false}` via `replay.py --extra-body`, since Hindsight consumes only `content`. Labels end in `-nt`.

### oMLX v0.7.0

Speed benchmark: Qwen3.6-35B-A3B. Thinking on, which doesn't affect token rate. Cold load 6.2 s.

| prefix | c | phase | ttft_ms p50 | decode tok/s p50 | aggregate tok/s | errors |
|---|---|---|---|---|---|---|
| 0 | 1 | cold | 376 | 171.2 | 171.2 | 0 |
| 0 | 1 | warm | 72 | 170.7 | 170.7 | 0 |
| 0 | 5 | cold | 377 | 94.4 | 465.1 | 0 |
| 0 | 5 | warm | 140 | 96.6 | 483.9 | 0 |
| 8192 | 1 | cold | 2499 | 154.4 | 154.4 | 0 |
| 8192 | 1 | warm | 178 | 155.3 | 155.3 | 0 |
| 8192 | 5 | cold | 7293 | 80.5 | 370.0 | 0 |
| 8192 | 5 | warm | 497 | 69.1 | 344.1 | 0 |
| 32768 | 1 | cold | 4079 | 139.1 | 139.1 | 0 |
| 32768 | 1 | warm | 401 | 139.5 | 139.5 | 0 |
| 32768 | 5 | cold | 22205 | 45.2 | 221.8 | 0 |
| 32768 | 5 | warm | 1231 | 39.2 | 198.2 | 0 |

Hindsight replay: Qwen3.6-35B-A3B, thinking off, c=5, 200 requests, seed 1. The production row is repeated for comparison.

| run | n | error_rate | empty_rate | structured_valid_rate | tool_valid_rate | fact_recall_mean | ttft_ms_p50 | ttft_ms_p95 | latency_ms_p50 | latency_ms_p95 | decode_tps_median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| prod gpt-oss-20b | 200 | 0.0 | 0.095 | 0.889 | 1.0 | 0.675 | 6486 | 36037 | 46325 | 157649 | 39.1 |
| omlx-q36-35b-nt | 200 | 0.005 | 0.0 | 0.889 | 0.8 | 0.559 | 1447 | 7718 | 26284 | 66405 | 34.3 |

`tool_valid_rate` 0.8 = 16 of 20 tool-offering requests, and all 4 failures had `tool_choice: required`:
1. Prose answer, no call. The engine didn't enforce `required`.
2. The one error: oMLX stream error "Model output contains an unrecoverable tool call".
3. The correct call plus a call to a tool that wasn't offered.
4. The call written as plain text (`search_observations(query=…)`), not parsed.

Failures 1 and 4 come from how the engine enforces and parses tool calls. Comparing the same model on LM Studio/llmster separates engine from model. n=20 is small, so treat the gap as indicative.

`fact_recall_mean` 0.559 against the 0.675 noise ceiling is a real but moderate content drift, and a model-bake-off question, not an engine one.

## Gateway evidence (2026-10-20)

### Omniroute 3.8.51 probes (in-cluster, HolyClaude key)

| Check | Result |
|---|---|
| `/metrics` | 404, no Prometheus endpoint |
| `/api/metrics` | 401 without a key, 403 with a consumer key |
| `/v1/messages`, `/v1/chat/completions` without a key | 401 `AUTH_002`. The old unauthenticated-`/v1/messages` defect is fixed. |
| Per-key model allowlist | Works: HolyClaude's key is limited to its combos, and other models return 403 `permission_denied` |
| `omniroute_cost_report` (week) | 0 requests, empty `byProvider`, so attribution isn't recorded or isn't reported |
| Route definitions | DB only (combos), not in git |
| Combos that mix Claude into local fallback chains | `coding-deep` = claude-sonnet-5 → gpt-5.5 → llamaswap/coder-large; `debugging` = claude-sonnet-5 → coder-large. Both break "Claude only by explicit model name". |
| Long-request cap, natural stop | `coding-fast`, 5–6K tokens: 81 s streamed, 101 s non-streamed, both 200 |
| Long-request cap, forced to `max_tokens` 12000 (`ignore_eos`) | Streamed 189 s, 200, `finish_reason: length`. Non-streamed 254 s to first byte, 200, `finish_reason: length`. |

The forced-length test refutes the earlier inference that Omniroute's 120 s `maxWaitMs` would cut Hindsight's >130 s requests. Requests over 250 s complete through the `coding-fast` combo to llama-swap. `maxWaitMs` isn't a generation timeout on this path.

Prompt token counts differ by mode. Non-streamed `prompt_tokens` came back about 480 tokens larger than streamed for the same prompt, in both runs (585 vs 102, 565 vs 82). Something adds content to non-streamed requests. Not yet investigated.

### Bifrost (docs only, Context7 `/maximhq/bifrost`)

- `config_store.enabled: false` makes config.json the only source of truth. UI and API edits are disabled, and changes need a restart.
- Custom providers take `custom_provider_config.base_provider_type: openai` plus `network_config.base_url`, with `default_request_timeout_in_seconds` set per provider.
- Virtual keys can be declared in config.json under `governance.virtual_keys[].provider_configs[].allowed_models`. The key is read from `x-bf-vk`, `Authorization: Bearer`, `x-api-key` or `api-key`.
- The Anthropic drop-in is at `/anthropic/v1/messages`.
- `GET /metrics` is native Prometheus, labelled by virtual key.
