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

#### Lenient JSON grading

oMLX does not enforce `response_format`, so a model can wrap valid JSON in ```` ```json ```` fences. Production Hindsight strips those fences for every provider: upstream #646 added it, `parse_llm_json` in 0.8.5 hardened it, and the cluster runs 0.10.1. `grade.py --lenient-json` grades the same way, so lenient scores are the production-relevant ones. Strict stays the default so earlier rows remain comparable.

Qwen3.6-35B-A3B scores identically under both modes. Its failures are schema violations (e.g. `"knowledge": null`), not fences.

#### Qwen3.8-27B (dense)

Speed benchmark, thinking off. Cold load 16.0 s.

| prefix | c | phase | ttft_ms p50 | decode tok/s p50 | aggregate tok/s | errors |
|---|---|---|---|---|---|---|
| 0 | 1 | cold | 304 | 46.1 | 46.1 | 0 |
| 0 | 1 | warm | 216 | 46.0 | 46.0 | 0 |
| 0 | 5 | cold | 394 | 35.5 | 176.7 | 0 |
| 0 | 5 | warm | 361 | 35.4 | 176.7 | 0 |
| 8192 | 1 | cold | 4245 | 44.9 | 44.9 | 0 |
| 8192 | 1 | warm | 311 | 45.1 | 45.1 | 0 |
| 8192 | 5 | cold | 28058 | 27.4 | 123.2 | 0 |
| 8192 | 5 | warm | 944 | 25.1 | 125.9 | 0 |
| 32768 | 1 | cold | 18263 | 40.0 | 40.0 | 0 |
| 32768 | 1 | warm | 729 | 40.2 | 40.2 | 0 |
| 32768 | 5 | cold | 99056 | 13.7 | 67.4 | 0 |
| 32768 | 5 | warm | 1756 | 13.7 | 68.7 | 0 |

Compared with Qwen3.6-35B-A3B, it is about 3.7× slower at c=1 decode and 2.7× slower at c=5 warm-8K aggregate. Cold-32K TTFT is 4.5× worse. That is the expected dense-vs-MoE gap (27B active parameters vs 3B).

c=5 replay: the memory guard tripped. At about request 102, oMLX's `--memory-guard-gb 80` limit was hit (81.1 GB). oMLX aborted 4 requests mid-prefill, returned one HTTP 507, and then rejected 84 requests with HTTP 409 "busy… unload pending" until the in-flight work drained. Overall error_rate is 0.445. The guard behaves safely (it shed load and recovered without crashing), but at c=5 with long Hindsight prompts the dense 27B's KV cache doesn't fit under an 80 GB guard. A clean c=5 run needs a higher guard (an operator/sudo change to the LaunchDaemon) or lower concurrency.

Only the first 102 requests are pre-guard and comparable. Both models, same 102 requests:

| first 102 | structured_valid strict | structured_valid lenient | tool_valid | fact_recall strict | fact_recall lenient | latency_ms_p50 | decode_tps_median |
|---|---|---|---|---|---|---|---|
| omlx-q38-27b-nt | 0.573 | 0.958 | 0.667 | 0.293 | 0.566 | 97423 | 10.1 |
| omlx-q36-35b-nt | 0.833 | 0.833 | 0.5 | 0.524 | 0.524 | ~25000 | 37.2 |

Qwen3.8-27B's 41 strict failures were 37 fenced JSON and 4 prose. With fences stripped it has the better structure and recall, but its latency is about 4× worse.

c=1 replays (n=50, same seed). No memory pressure at c=1. Free memory got as low as 5% during the 27B c=5 run, against 45% for 35B at c=5.

| run | n | error_rate | structured_valid strict | structured_valid lenient | tool_valid | fact_recall strict | fact_recall lenient | ttft_ms_p50 | latency_ms_p50 | latency_ms_p95 | decode_tps_median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| omlx-q38-27b-nt c=1 | 50 | 0.0 | 0.583 | 0.938 | 1.0 (n=2) | 0.27 | 0.55 | 583 | 20098 | 54572 | 43.6 |
| omlx-q36-35b-nt c=1 | 50 | 0.0 | 0.854 | 0.854 | 0.5 (n=2) | 0.509 | 0.509 | 157 | 6273 | 15087 | 148.7 |

oMLX engine notes for scoring:
- `response_format` is not enforced.
- `tool_choice: required` is not enforced.
- Tool-call parsing misses some text-form calls.
- The memory guard sheds load safely (409 until drained) rather than crashing.

### LM Studio (Bionic 1.1.8)

Bionic is the LM Studio desktop app, serving on :1235 and reading models from `~/.lmstudio/models`. The weights are byte-identical copies of the oMLX models, MLX 4-bit.

Thinking: Bionic ignores `chat_template_kwargs`, `enable_thinking`, `reasoning_effort` and `/no_think`, and has no binary toggle in its UI. The fix is `{%- set enable_thinking = false %}` added as the first line of each Bionic copy's `chat_template.jinja`, with the originals kept as `.orig`. After that, reasoning tokens drop to 0. This is the same template branch the oMLX runs reached through the API flag.

Speed benchmark: Qwen3.6-35B-A3B, thinking off. The model was already loaded, so there is no cold-load figure.

| prefix | c | phase | ttft_ms p50 | decode tok/s p50 | aggregate tok/s | errors |
|---|---|---|---|---|---|---|
| 0 | 1 | cold | 77 | 148.1 | 148.1 | 0 |
| 0 | 1 | warm | 63 | 148.7 | 148.7 | 0 |
| 0 | 5 | cold | 272 | 102.1 | 555.9 | 0 |
| 0 | 5 | warm | 189 | 103.7 | 561.6 | 0 |
| 8192 | 1 | cold | 978 | 139.4 | 139.4 | 0 |
| 8192 | 1 | warm | 148 | 140.4 | 140.4 | 0 |
| 8192 | 5 | cold | 3870 | 57.8 | 354.1 | 0 |
| 8192 | 5 | warm | 483 | 69.4 | 414.6 | 0 |
| 32768 | 1 | cold | 4540 | 125.9 | 125.9 | 0 |
| 32768 | 1 | warm | 342 | 126.8 | 126.8 | 0 |
| 32768 | 5 | cold | 14957 | 18.4 | 183.9 | 0 |
| 32768 | 5 | warm | 1185 | 42.5 | 272.4 | 0 |

Compared with oMLX on the same model, the c=5 aggregate is +16% short, +21% at warm 8K and +37% at warm 32K. Cold-32K TTFT is about equal at c=1 (4.5 s against 4.1 s) and 33% better at c=5 (15 s against 22 s). c=1 decode is 13% lower (148 against 171).

`json_object` is rejected. LM Studio answers `response_format: {"type":"json_object"}` with HTTP 400 ("must be 'json_schema' or 'text'"). Production Hindsight runs `provider: openai` with only `HINDSIGHT_API_LLM_STRICT_SCHEMA_RETAIN=true`, so reflect and consolidation calls send `json_object`. Those were 114 of 200 corpus requests (57% errors) in the first pass. Hindsight 0.10.1 offers two fixes. `HINDSIGHT_API_LLM_STRICT_SCHEMA=true` moves every operation to `json_schema` strict, which LM Studio grammar-enforces. `provider: lmstudio` drops `response_format` entirely. `replay.py --json-object-as text` reproduces the second, so it is the conservative case.

On the 86 `json_schema` requests both engines served at c=5, LM Studio's structured validity was 0.985 against oMLX's 0.712. LM Studio enforces the schema; oMLX does not.

Hindsight replay, thinking off, with `--json-object-as text`:

| run | n | error_rate | structured_valid_rate | tool_valid_rate | fact_recall_mean | ttft_ms_p50 | ttft_ms_p95 | latency_ms_p50 | latency_ms_p95 | decode_tps_median |
|---|---|---|---|---|---|---|---|---|---|---|
| prod gpt-oss-20b | 200 | 0.0 | 0.889 | 1.0 | 0.675 | 6486 | 36037 | 46325 | 157649 | 39.1 |
| omlx-q36-35b-nt c=5 | 200 | 0.005 | 0.889 | 0.8 | 0.559 | 1447 | 7718 | 26284 | 66405 | 34.3 |
| lms-q36-35b-nt c=5 | 200 | 0.0 | 0.989 | 0.8 | 0.542 | 8414 | 20060 | 30934 | 67152 | 35.7 |
| omlx-q36-35b-nt c=1 | 50 | 0.0 | 0.854 | 0.5 (n=2) | 0.509 | 157 | 258 | 6273 | 15087 | 148.7 |
| lms-q36-35b-nt c=1 | 50 | 0.0 | 1.0 | 1.0 (n=2) | 0.568 | 778 | 4570 | 7326 | 16736 | 132.5 |

Lenient and strict grades are identical for LM Studio, since it produced no fences. Free memory never went below 43% (peak engine RSS 24 GB).

Reading: LM Studio is more correct, with schema enforcement and no fences. Its synthetic throughput is also higher. On the real c=5 replay, though, its TTFT p50 is 5.8× oMLX's (8.4 s against 1.4 s) and its latency p50 is 18% worse. The likely cause is queueing behind a parallel-slot limit or weaker prefix reuse on long, varied Hindsight prompts. That has not been verified. Check LM Studio's max-concurrent-predictions setting before the llmster confirming run.

#### LM Studio: Qwen3.8-27B (dense)

Speed benchmark, thinking off (template edit):

| prefix | c | phase | ttft_ms p50 | decode tok/s p50 | aggregate tok/s | errors |
|---|---|---|---|---|---|---|
| 0 | 1 | cold | 164 | 55.7 | 55.7 | 0 |
| 0 | 1 | warm | 152 | 55.7 | 55.7 | 0 |
| 0 | 5 | cold | 471 | 41.9 | 221.9 | 0 |
| 0 | 5 | warm | 457 | 41.9 | 221.9 | 0 |
| 8192 | 1 | cold | 4713 | 53.1 | 53.1 | 0 |
| 8192 | 1 | warm | 315 | 53.3 | 53.3 | 0 |
| 8192 | 5 | cold | 18884 | 18.6 | 118.7 | 0 |
| 8192 | 5 | warm | 1043 | 26.7 | 159.0 | 0 |
| 32768 | 1 | cold | 20344 | 46.9 | 46.9 | 0 |
| 32768 | 1 | warm | 709 | 47.2 | 47.2 | 0 |
| 32768 | 5 | cold | 66802 | 4.9 | 60.1 | 0 |
| 32768 | 5 | warm | 3027 | 15.4 | 99.4 | 0 |

Compared with oMLX: c=1 decode is +21% (55.7 against 46.0), c=5 aggregate is +26% short and +26% at warm 8K, and +45% at warm 32K. Cold-32K TTFT at c=5 is 33% better (67 s against 99 s), but 11% worse at c=1 (20 s against 18 s).

Hindsight replay with `--json-object-as text`:

| run | n | error_rate | structured_valid lenient | tool_valid | fact_recall lenient | ttft_ms_p50 | latency_ms_p50 | latency_ms_p95 | decode_tps_median |
|---|---|---|---|---|---|---|---|---|---|
| lms-q38-27b-nt c=5 | 200 | 0.06 | 0.933 | 0.95 | 0.505 | 27365 | 87718 | 182293 | 11.6 |
| lms-q38-27b-nt c=5, first 102 | 102 | 0.0 | 1.0 | 1.0 | 0.525 | 24886 | 77604 | 182293 | 12.7 |
| omlx-q38-27b-nt c=5, first 102 | 102 | 0.0 | 0.958 | 0.667 | 0.566 | 14342 | 97423 | 211837 | 10.1 |
| lms-q38-27b-nt c=1 | 50 | 0.0 | 1.0 | 1.0 | 0.494 | 4024 | 17484 | 54035 | 50.6 |
| omlx-q38-27b-nt c=1 | 50 | 0.0 | 0.938 | 1.0 | 0.55 | 583 | 20098 | 54572 | 43.6 |

Memory failure: LM Studio has no memory guard. Free memory fell to 2% (64 samples at ≤5%), and requests 187–199 failed: 7 with HTTP 500 and 5 with stream error "The model has crashed without additional information". The model reloaded by itself, and the c=1 pass ran clean afterwards. oMLX's guard shed load earlier (from request ~102) but kept the process alive. So the dense 27B at c=5 over-commits memory on both engines. It is not a viable c=5 Hindsight model on a 96 GB host shared with other services unless its context or concurrency is capped.

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
