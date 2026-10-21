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

Added for the model bake-off (2026-10-21) and downloaded with `hf download --revision` to `~/bakeoff/omlx-models/`. None of them is in `/opt/ai/models.noindex` yet.

| Model | HF repo | Revision | Size |
|---|---|---|---|
| gpt-oss-20b | `mlx-community/gpt-oss-20b-MXFP4-Q8` | `773a7da7` | 12.1 GB |
| Qwen3-Coder-Next | `lmstudio-community/Qwen3-Coder-Next-MLX-4bit` | `03cba260` | 44.8 GB |
| gpt-oss-120b | `mlx-community/gpt-oss-120b-MXFP4-Q8` | `81e5ac3a` | 63.4 GB |

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

Reading: LM Studio is more correct, with schema enforcement and no fences. Its synthetic throughput is also higher. On the real c=5 replay, though, its TTFT p50 is 5.8× oMLX's (8.4 s against 1.4 s) and its latency p50 is 18% worse. The model was loaded with Max Concurrent Predictions = 4, but a slot cap does not explain the gap. With 4 slots at c=5 most requests would start fast, leaving a long tail. Instead, the whole TTFT distribution shifts: p10/p50/p90 are 3.0/8.4/16.6 s against oMLX's 0.4/1.4/7.2 s. TTFT is also 4.4× worse at c=1 (0.78 s against 0.16 s), where no slot cap applies. The probable cause is weaker prefix-cache reuse on the shared Hindsight system prompts; the synthetic bench uses fresh prefixes, so it does not hit that path. That is an inference, not confirmed from engine logs. These Bionic runs used the `mlx-llm … nax-advsimd@1.13.1` runtime, which is Bionic's selection in `~/.lmstudio/apps/bionic/.internal/backend-preferences-v1.json`.

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

### llmster 0.0.25 (headless LM Studio, 2026-10-21)

llmster is the production form of LM Studio (ruling R2). It runs as a daemon, shares `~/.lmstudio` (models, edited templates, runtimes) with Bionic, and loads with `lms load qwen3.6-35b-a3b-mlx -c 262144 --parallel 4 --gpu max -y` and serves with `lms server start -p 1235 --bind 127.0.0.1`. The model is Qwen3.6-35B-A3B, thinking off.

Runtime pin: llmster picks the plain `mlx-llm-mac-arm64-apple-metal-advsimd@1.13.1` runtime by default, while Bionic's preferences select the `-nax-` build. The first llmster run used the plain runtime and lost badly on prefill (cold-32K TTFT 11.2 s against 4.5 s at c=1, 36 s against 15 s at c=5) and on the replay (TTFT p50 14.8 s, latency p50 43 s at c=5). Production must run `lms runtime select mlx-llm-mac-arm64-apple-metal-nax-advsimd@1.13.1` before loading. The numbers below are from the nax runtime.

| prefix | c | phase | ttft_ms p50 | decode tok/s p50 | aggregate tok/s | errors |
|---|---|---|---|---|---|---|
| 0 | 1 | cold | 75 | 151.5 | 151.5 | 0 |
| 0 | 5 | warm | 188 | 104.9 | 566.3 | 0 |
| 8192 | 5 | cold | 3821 | 58.9 | 360.6 | 0 |
| 8192 | 5 | warm | 429 | 69.4 | 413.2 | 0 |
| 32768 | 1 | cold | 4498 | 125.0 | 125.0 | 0 |
| 32768 | 5 | cold | 14888 | 18.7 | 185.5 | 0 |
| 32768 | 5 | warm | 1169 | 42.6 | 275.4 | 0 |

Hindsight replay with `--json-object-as text`:

| run | n | error_rate | structured_valid_rate | tool_valid_rate | fact_recall_mean | ttft_ms_p50 | ttft_ms_p95 | latency_ms_p50 | latency_ms_p95 | decode_tps_median |
|---|---|---|---|---|---|---|---|---|---|---|
| llmster-nax c=5 | 200 | 0.0 | 1.0 | 0.9 | 0.555 | 8705 | 18504 | 29347 | 71744 | 36.2 |
| llmster-plain c=5 | 200 | 0.0 | 0.994 | 0.9 | 0.557 | 14819 | 30736 | 43162 | 94046 | 28.9 |
| llmster-nax c=1 | 50 | 0.0 | 1.0 | 1.0 | 0.531 | 775 | 4532 | 7150 | 12963 | 136.1 |

The nax run is within noise of Bionic on every row. Free memory stayed at or above 47% (peak RSS 23.6 GB). Headless serving costs nothing, and the remaining gap to oMLX on replay TTFT (8.7 s against 1.4 s at c=5) belongs to LM Studio's engine, not to the app.

### Splash 1.3.0 (Inco AI, 2026-10-21)

Splash is Inco AI's Qwen-specific Apple Silicon engine (`github.com/incoai/splash`, also `brew install incoai/tap/splash`). For this run it was launched from the runtime that LM Studio bundles (`splash-mac-arm64-apple-metal-advsimd@1.3.0`, behind LM Studio's `splashEngine` experiment flag) with the `splash_engine` launcher, on :1236, using `--default-reasoning-effort none`. Splash does not load MLX or GGUF checkpoints directly. It needs its own package: `incoai/Qwen3.6-35B-A3B-Splash` (20.9 GB) holds the `mlx-community/Qwen3.6-35B-A3B-4bit` target (the same 4-bit weights as the other runs), a six-layer DFlash 2 speculative draft that the target verifies (speed only, the output distribution is unchanged), the vision encoder and the tokenizer. Two differences from the other engines: the KV cache defaults to int8, and `json_object` is supported natively, so the replay ran without `--json-object-as text`, like oMLX.

Uncapped run (default `--max-memory auto`):

| prefix | c | phase | ttft_ms p50 | decode tok/s p50 | aggregate tok/s | errors |
|---|---|---|---|---|---|---|
| 0 | 1 | cold | 57 | 192.9 | 192.9 | 0 |
| 0 | 1 | warm | 43 | 194.1 | 194.1 | 0 |
| 0 | 5 | cold | 112 | 115.7 | 655.4 | 0 |
| 0 | 5 | warm | 97 | 115.5 | 655.0 | 0 |
| 8192 | 1 | cold | 854 | 196.8 | 196.8 | 0 |
| 8192 | 1 | warm | 45 | 196.0 | 196.0 | 0 |
| 8192 | 5 | cold | 3113 | 74.9 | 466.3 | 0 |
| 8192 | 5 | warm | 107 | 111.2 | 648.1 | 0 |
| 32768 | 1 | cold | 4109 | 190.2 | 190.2 | 0 |
| 32768 | 1 | warm | 46 | 190.3 | 190.3 | 0 |
| 32768 | 5 | cold | 14584 | 28.9 | 259.2 | 0 |
| 32768 | 5 | warm | 129 | 94.1 | 563.8 | 0 |

| run | n | error_rate | empty_rate | structured_valid_rate | tool_valid_rate | fact_recall_mean | ttft_ms_p50 | ttft_ms_p95 | latency_ms_p50 | latency_ms_p95 | decode_tps_median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| splash c=5 | 200 | 0.0 | 0.01 | 0.989 | 0.95 | 0.587 | 6450 | 14260 | 18537 | 58547 | 120.7 |
| splash c=1 | 50 | 0.0 | 0.0 | 1.0 | 1.0 | 0.594 | 57 | 104 | 3662 | 18651 | 303.5 |

Compared with llmster-nax: the c=5 aggregate is +16% short, +57% at warm 8K and +105% at warm 32K. c=1 decode is +27% (193 against 152), and warm TTFT is about 45 ms at every prefix length. Cold-32K TTFT is about equal. On the c=5 replay, latency p50 is 37% lower than llmster (18.5 s against 29.3 s) and 29% lower than oMLX (26.3 s), and the replay decode median is 3.3× higher (121 against 36 tok/s). Structured validity (0.989) matches LM Studio. Splash also has the best fact recall of any Qwen3.6 run (0.587). The c=1 replay TTFT of 57 ms reflects prefix-cache hits on prompts the c=5 pass had just served (the serve log shows about 99% cached input). Every engine replays in the same order, so the comparison is fair, but it is not a cold-cache figure.

Memory failure (uncapped): Splash wires memory up to its automatic budget and keeps it. Engine RSS rose from 20 GB to 53.5 GB, free memory was at or below 10% for 553 of 1,378 samples (minimum 4%), and macOS was swapping (2.7 GB used). At idle after the run, the engine still held 47 GB with 6% free. Nothing failed, but on a host that also runs other services this default is not acceptable. Production needs `--max-memory`, and the capped rerun below is the configuration being scored.

Capped rerun (`--max-memory 32G --no-webui`, otherwise identical, label `splash-mm32`). The bench numbers are within noise of the uncapped run on every row (c=5 aggregate 654, warm-8K c=5 617, warm-32K c=5 553, cold-32K c=1 4.1 s, cold-32K c=5 13.1 s, c=1 decode 193–206).

| run | n | error_rate | empty_rate | structured_valid_rate | tool_valid_rate | fact_recall_mean | ttft_ms_p50 | ttft_ms_p95 | latency_ms_p50 | latency_ms_p95 | decode_tps_median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| splash-mm32 c=5 | 200 | 0.0 | 0.005 | 0.994 | 1.0 | 0.578 | 6354 | 14150 | 18811 | 62967 | 121.9 |
| splash-mm32 c=1 | 50 | 0.0 | 0.0 | 1.0 | 1.0 | 0.556 | 698 | 4017 | 6181 | 15993 | 309.2 |

The cap fixes the memory behaviour at no measurable cost to speed or quality: peak engine RSS was 28.1 GB and free memory never dropped below 56%. The c=1 replay TTFT (698 ms) is now comparable to llmster's 775 ms, because the smaller budget evicts the prefix cache that the c=5 pass had filled. That makes this the fairer c=1 figure. On the c=5 replay Splash keeps its lead: latency p50 18.8 s against 26.3 s (oMLX) and 29.3 s (llmster), with a TTFT p50 of 6.4 s that sits between oMLX (1.4 s) and llmster (8.7 s). Splash is the only engine with no tool-call failures at c=5.

Splash supports three model families: `install/families.py` in 1.4.0 lists Qwen3.8-27B, Qwen3.6-35B-A3B and Qwen3.8-Flash-Next, each with its own DFlash2 draft. gpt-oss and Qwen3-Coder-Next will not run on it.

### vllm-metal 0.32.0 (2026-10-21)

The upstream installer (`install.sh`) creates `~/.venv-vllm-metal`. Brew is not used on this host, so its steps were reproduced by hand in `~/bakeoff/vllm-metal`, pinned to the latest stable release:

```
uv venv --python <nix python3.12.14> ~/bakeoff/vllm-metal/.venv
uv pip install https://github.com/vllm-project/vllm/releases/download/v0.32.0/vllm-0.32.0%2Bcpu-cp38-abi3-macosx_11_0_arm64.whl
uv pip install https://github.com/vllm-project/vllm-metal/releases/download/v0.32.0/vllm_metal-0.32.0-cp312-cp312-macosx_15_0_arm64.whl
vllm serve ~/bakeoff/models/Qwen3.6-35B-A3B-MLX-4bit --served-model-name qwen3.6-35b-a3b \
  --host 127.0.0.1 --port 1237 --max-model-len 65536 --gpu-memory-utilization 0.5 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3
```

The installed stack is mlx 0.32.2, mlx-lm 0.32.0, torch 2.13.0 and transformers 5.19.0. vllm-metal lists Qwen3.5/3.6/3.8 as ✅. It loaded the text-only backbone with M5 NAX prefill kernels, a 1,015,333-token KV pool and 1,056-token attention blocks (forced by the GDN/Mamba state page size). `json_object` is enforced natively and thinking is off via `chat_template_kwargs`.

| prefix | c | phase | ttft_ms p50 | decode tok/s p50 | aggregate tok/s | errors |
|---|---|---|---|---|---|---|
| 0 | 1 | cold | 104 | 108.9 | 108.9 | 0 |
| 0 | 1 | warm | 40 | 107.8 | 107.8 | 0 |
| 0 | 5 | cold | 120 | 79.6 | 397.9 | 0 |
| 0 | 5 | warm | 101 | 79.9 | 399.3 | 0 |
| 8192 | 1 | cold | 1415 | 94.8 | 94.8 | 0 |
| 8192 | 1 | warm | 173 | 95.9 | 95.9 | 0 |
| 8192 | 5 | cold | 4422 | 55.5 | 259.9 | 0 |
| 8192 | 5 | warm | 619 | 58.1 | 290.5 | 0 |
| 32768 | 1 | cold | 5035 | 74.2 | 74.2 | 0 |
| 32768 | 1 | warm | 173 | 74.3 | 74.3 | 0 |
| 32768 | 5 | cold | 17033 | 22.7 | 139.3 | 0 |
| 32768 | 5 | warm | 403 | 56.6 | 282.8 | 0 |

| run | n | error_rate | empty_rate | structured_valid_rate | tool_valid_rate | fact_recall_mean | ttft_ms_p50 | ttft_ms_p95 | latency_ms_p50 | latency_ms_p95 | decode_tps_median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| vllm-metal c=5 | 200 | 0.0 | 0.0 | 0.983 | 0.85 | 0.614 | 2432 | 6154 | 42777 | 97439 | 22.6 |
| vllm-metal c=1 | 50 | 0.0 | 0.0 | 1.0 | 1.0 | 0.604 | 835 | 5129 | 16055 | 46052 | 67.7 |

Decode is the slowest of the four engines: 109 tok/s at c=1 against 151–193 elsewhere, and a c=5 aggregate of 399 against 484–655. Replay latency p50 at c=5 is the worst (42.8 s). Its strengths are second-best replay TTFT (2.4 s), the best fact recall of any Qwen3.6 run (0.614, likely noise at n=200) and calm memory (peak RSS 42 GB, never below 45% free). The serve log's prefix-cache hit rate was only 19%. The 1,056-token block size the hybrid model forces limits reuse of shorter shared prefixes.

## Engine ruling (2026-10-21)

Qwen3.6-35B-A3B, 4-bit, thinking off. Each metric is scored as a ratio to the best engine (higher-is-better: value / best; lower-is-better: best / value) and weighted as the plan requires. Inputs: c=5 aggregate at prefix 0 (warm), c=5 warm-8K TTFT, c=5 cold-32K TTFT, c=5 replay structured validity, and ops simplicity (LaunchDaemon-able, nix-installable, pinned, auth, metrics).

| engine | c=5 agg (30%) | warm-8K TTFT (25%) | cold-32K TTFT (15%) | structured (20%) | ops (10%) | total |
|---|---|---|---|---|---|---|
| oMLX 0.7.0 | 484 → 0.74 | 497 ms → 0.22 | 22.2 s → 0.59 | 0.889 → 0.89 | 1.0: already a nix LaunchDaemon with keys and an exporter | 0.64 |
| llmster 0.0.25 (nax) | 566 → 0.86 | 429 ms → 0.25 | 14.9 s → 0.88 | 1.0 → 1.00 | 0.5: user-account installer, runtime pin is manual state, no metrics | 0.70 |
| Splash 1.3.0 (32G cap) | 655 → 1.00 | 107 ms → 1.00 | 13.1 s → 1.00 | 0.994 → 0.99 | 0.6: sha-pinned tarball, `--api-key`, no nix, metrics unverified | 0.96 |
| vllm-metal 0.32.0 | 399 → 0.61 | 619 ms → 0.17 | 17.0 s → 0.77 | 0.983 → 0.98 | 0.8: uv-pinned, `--api-key`, native Prometheus `/metrics`, not nix | 0.62 |

The warm-8K column decides most of the gap, because Splash's 107 ms against 429–619 ms makes the ratio steep. Without that column (weights renormalised) the totals are Splash 0.94, llmster 0.85, oMLX 0.79 and vllm-metal 0.79. The order is unchanged.

Ruling, under the spec's two-tier rule (foundation engine plus optional fast lanes behind the front door):

1. **Splash is not eligible as the foundation.** The spec says "Splash supports two models only — never the foundation; a fast lane at most", and 1.4.0 still covers only three Qwen families. That excludes gpt-oss-120b and Qwen3-Coder-Next from the model bake-off.
2. **Foundation: oMLX stays.** Among the general engines, llmster leads (0.70), and oMLX (0.64, −9%) and vllm-metal (0.62, −12%) are both within 15% of it. The rule picks the simplest, and oMLX is the only one that is already nix-packaged, running as a LaunchDaemon with keys and metrics. llmster's real advantages (`json_schema` enforcement, higher throughput) are not enough to break the tie, and moving to it would add a runtime pin that drifts silently, as the first llmster run showed. Known oMLX gaps carry into the model bake-off: `response_format` and `tool_choice: required` are not enforced.
3. **Splash fast lane for Hindsight: not yet.** The ≥1.5× bar is met on the synthetic lanes that model Hindsight's shared prefixes (warm-8K TTFT 4.6×, warm-32K c=5 aggregate 2.8× over oMLX), but not on the real replay. There, latency p50 is 1.40× (18.8 s against 26.3 s), p95 is about 1.05×, and TTFT p50 is worse (6.4 s against 1.4 s). Its quality edge on Hindsight (tool validity 1.0 against 0.8, structured 0.994 against 0.889) is not something the 1.5× rule counts. Revisit if the model bake-off keeps a Qwen family Splash supports. The deciding test would be a soak at c=5 against oMLX on the chosen model.

No soak was run at the engine stage: oMLX is the foundation by the simplicity rule, not by a close numeric margin. Plan step 4 soaks the finalist engine × model pairs in the model bake-off instead.

## Model bake-off on oMLX (2026-10-21)

### Method

Production oMLX reads models only from `/opt/ai/models.noindex`, which needs sudo to write. So the bake-off ran on a second, user-owned oMLX instead:
- Built from production's own `pyproject.toml` and `uv.lock` with `uv sync --frozen` (tag `v0.7.2`; the package reports `0.7.1`). The "oMLX v0.7.0" heading above predates the current pin.
- Served on `127.0.0.1:8003` with production's flags (`--memory-guard-gb 80`, a paged SSD cache), its own API key, and models in `~/bakeoff/omlx-models`.
- Production oMLX stayed up, with no model loaded (93% free memory before each run).

Every model went through `run_engine.sh`: cold load, `prefix_bench` (0/8K/32K × c=1/5, which includes the fit check at 32K c=5), Hindsight replay at c=5 (200 requests, seed 1), then c=1 (50 requests). Models ran one at a time, unloaded between them.

- **Qwen models:** thinking off (`enable_thinking: false`).
- **gpt-oss models:** run at the default reasoning effort, because production Hindsight sends no reasoning control. That keeps the gpt-oss-20b control directly comparable with production. oMLX honours `reasoning_effort` and splits harmony reasoning from content.

Two caveats:
- **Download overlap:** the Qwen3.6-35B pass overlapped the other models' downloads, which lowers its free-memory figure.
- **Process RSS undercounts:** for the larger models, memsample's process RSS is below the weight size (41 GB for gpt-oss-120b). So the memory columns use oMLX's own load figure and the system-wide free-memory minimum.

| Model | HF repo | Revision | Resident weights |
|---|---|---|---|
| Qwen3.6-35B-A3B | `lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit` | `0c4a20a6` | 19.0 GB |
| Qwen3-Coder-Next 80B-A3B | `lmstudio-community/Qwen3-Coder-Next-MLX-4bit` | `03cba260` | 41.9 GB |
| gpt-oss-120b | `mlx-community/gpt-oss-120b-MXFP4-Q8` | `81e5ac3a` | 59.6 GB |
| gpt-oss-20b (control) | `mlx-community/gpt-oss-20b-MXFP4-Q8` | `773a7da7` | 11.6 GB |

Qwen3.8-27B was not rerun. Its engine-stage oMLX pass (above) already shows it is about 4× slower than Qwen3.6-35B, and its c=5 replay tripped the 80 GB memory guard.

### Speed and fit

| Model | cold load s | c=1 decode tok/s (prefix 0) | c=5 agg tok/s (prefix 0, warm) | warm-8K c=5 TTFT ms | cold-32K c=5 TTFT ms | c=5 agg tok/s at 32K warm | min free % | fit (≤ 80 GB, no guard trip) |
|---|---|---|---|---|---|---|---|---|
| Qwen3.6-35B-A3B | 5.5 | 232 | 449 | 410 | 19955 | 190 | 45 | yes |
| Qwen3-Coder-Next | 6.7 | 115 | 383 | 604 | 31120 | 256 | 32 | yes |
| gpt-oss-120b | 17.2 | 123 | 329 | 1045 | 45392 | 172 | 12 | yes, tight |
| gpt-oss-20b | 0.1¹ | 202 | 518 | 860 | 25933 | 261 | 61 | yes |

¹ A warm page cache from the probe request just before.

Qwen3.6-35B on this instance decodes at 232 tok/s at c=1, against 171 in the engine-stage oMLX run. Its quality numbers match that run (structured 0.833–0.889, recall 0.56–0.58), so the two instances give comparable results.

### Hindsight replay (reasoner role)

The grades below are lenient (`--lenient-json`), matching production's fence-stripping. The production baseline grades 0.889 / 0.675 in both modes, so the gate is unchanged. Strict grades differ only for gpt-oss-20b (structured 0.911, recall 0.576).

| run | n | error_rate | empty_rate | structured_valid | tool_valid | fact_recall | ttft_ms_p50 | ttft_ms_p95 | latency_ms_p50 | latency_ms_p95 | decode_tps_median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| prod gpt-oss-20b (llama-swap) | 200 | 0.0 | 0.095 | 0.889 | 1.0 | 0.675 | 6486 | 36037 | 46325 | 157649 | 39.1 |
| gpt-oss-20b c=5 | 200 | 0.0 | 0.025 | 0.972 | 0.75 | 0.618 | 3058 | 7495 | 27794 | 178932 | 48.1 |
| Qwen3-Coder-Next c=5 | 200 | 0.0 | 0.0 | 0.978 | 0.65 | 0.588 | 4763 | 15099 | 26907 | 69303 | 36.7 |
| Qwen3.6-35B-A3B c=5 | 200 | 0.0 | 0.0 | 0.833 | 0.95 | 0.577 | 3031 | 8399 | 28425 | 78195 | 31.4 |
| gpt-oss-120b c=5 | 200 | 0.0 | 0.01 | 1.0 | 0.7 | 0.566 | 6096 | 19007 | 55969 | 135176 | 29.2 |
| gpt-oss-20b c=1 | 50 | 0.0 | 0.02 | 0.979 | 1.0 (n=2) | 0.632 | 259 | 496 | 6184 | 57196 | 168.7 |
| Qwen3-Coder-Next c=1 | 50 | 0.0 | 0.0 | 0.979 | 0.0 (n=2) | 0.558 | 199 | 483 | 8458 | 24965 | 107.4 |
| Qwen3.6-35B-A3B c=1 | 50 | 0.0 | 0.0 | 0.833 | 1.0 (n=2) | 0.539 | 154 | 233 | 3747 | 11329 | 237.6 |
| gpt-oss-120b c=1 | 50 | 0.0 | 0.0 | 1.0 | 1.0 (n=2) | 0.567 | 366 | 558 | 11064 | 35338 | 109.3 |

Tool calls at c=5, out of the 20 requests that offered tools:

| Model | correct | prose despite `tool_choice: required` | called a tool not offered at that step |
|---|---|---|---|
| Qwen3.6-35B-A3B | 19 | 1 | 0 |
| gpt-oss-20b | 15 | 0 | 5 (`search_observations` ×4, `search_mental_models`) |
| gpt-oss-120b | 14 | 3 | 3 (`search_observations`) |
| Qwen3-Coder-Next | 13 | 5 | 2 (`read` ×3, `recall`; one response held both) |

The "not offered" calls are real Hindsight tools that its reflect loop offered at an earlier step and then dropped. The prose answers come from oMLX not enforcing `required` (an engine gap, as in the engine stage). n=20, so treat these rates as indicative.

### Gate reading

The plan's gate is structured_valid and fact_recall ≥ `hindsight-prod`.
- **Structured:** gpt-oss-20b, Coder-Next and gpt-oss-120b pass. Qwen3.6-35B does not (0.833); its misses are schema violations, not fences.
- **Recall:** no model passes, including the control. The 0.675 figure is production replayed against its own recordings on its own engine, so it is the noise ceiling. The same gpt-oss-20b weights on oMLX reach 0.618, so moving engine and quantization (llama.cpp GGUF to MLX MXFP4) costs about 8% recall by itself.
- **Recall gate as applied:** recall is judged against the on-Mac control (0.618). Coder-Next is 5% below it, Qwen3.6-35B 7% and gpt-oss-120b 8%. None of them beats the control on recall.

### Agent/coder role (atuin, argus)

No corpus. The 2026-10-19 snapshot holds only Hindsight captures (atuin sent nothing and argus is disabled), so the gate is deferred to the Phase 3 live shadow. The only tool-call signal is the Hindsight replay's tool_valid above, where Qwen3.6-35B leads (0.95).

### GLM-5.3 / GLM-5.3-Flash (excluded, checked on HF 2026-10-21)

Neither fits under the 80 GB guard at a quality worth evaluating, so neither was benchmarked.

| Variant | Architecture | Size | Fits? |
|---|---|---|---|
| GLM-5.3 (`zai-org/GLM-5.3`) | `glm_moe_dsa`, 78 layers, 256 experts top-8 | 756 GB BF16, ~418 GB MLX 4-bit | no |
| GLM-5.3-Flash (MIT) | `glm5_next`, 320B total / 18B active, hybrid linear + sparse attention, MTP | 328 GB BF16, 182–204 GB MLX 4-bit, ~110 GB MLX 2-bit | no |
| GLM-5.3-Flash REAP50 (50% experts pruned), MLX 4/8-bit mix | as above | 96.3 GB | no: over the guard before any KV, and perplexity rises from 3.57 to 6.08 (ΔNLL +0.56) |
| GLM-5.3-Flash REAP50 GGUF IQ3_M / Q3_K_M | as above | 72 / 78.8 GB | llama.cpp only (not oMLX), no headroom for co-residents, and stacks pruning on 3-bit quantization |

The Flash variant would decode at an estimated 35–45 tok/s at c=1 (18B active), with about 25 s cold-32K TTFT. Even if it fitted, it would be slower than every candidate above. Revisit if a ≥128 GB host arrives or a smaller distilled GLM ships.

### Role → model

| Role | Pick | Why |
|---|---|---|
| Reasoner (Hindsight) | **gpt-oss-20b** | Best recall of any Mac candidate (0.618), structured 0.972 ≥ prod, the highest c=5 aggregate (518 tok/s), the smallest (11.6 GB), and the same model production runs, so the cutover changes only the engine. It beats production on p50 latency (28 s vs 46 s) and empty rate (0.025 vs 0.095). Its p95 (179 s) is worse than production's (158 s) and the other candidates', but under the 600 s cap requirement (it reached 252 s in one soak pass). Passed the 60-minute zero-error soak (below). |
| Agent / chat / tool use (provisional) | **Qwen3.6-35B-A3B** | Best tool-call behaviour (19/20, the only model that never calls a stale tool), fastest single-stream (232 tok/s c=1, TTFT p50 154 ms), 19 GB. Its structured miss rules it out for Hindsight, not for agents. Confirm in the Phase 3 live shadow. |
| Coder (provisional) | **Qwen3-Coder-Next**, on demand | Purpose-built coder, structured 0.978, best p95 of the candidates (69 s). Its weaker tool_valid (0.65) is mostly the unenforced `required`. With no atuin/argus corpus it is not yet justified as resident. |
| Dropped | gpt-oss-120b | No recall gain over the 20b (0.566 vs 0.618), 2× the latency p50 (56 s), and 59.6 GB, so it cannot co-reside with anything but the 20b. Its only edge is structured 1.0 against 0.972. |
| Dropped | Qwen3.8-27B | About 4× slower, and tripped the memory guard at c=5 in the engine stage. |

### Soak: gpt-oss-20b on oMLX

This is plan Task 4 Step 4, which the engine ruling deferred to the model bake-off. `mb_soak.sh` looped `replay.py` at c=5, 200 requests, with new seeds until 60 minutes had elapsed. That came to two passes, 400 requests and 108 minutes, 2026-10-21 20:11–21:58 UTC. Lenient grades:

| pass | n | error_rate | empty_rate | structured_valid | tool_valid | fact_recall | ttft_ms_p50 | ttft_ms_p95 | latency_ms_p50 | latency_ms_p95 | decode_tps_median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| seed 2 | 200 | 0.0 | 0.035 | 0.956 | 0.824 | 0.612 | 3163 | 8349 | 28245 | 170475 | 48.5 |
| seed 3 | 200 | 0.0 | 0.025 | 0.949 | 0.773 | 0.634 | 2309 | 6985 | 29207 | 251592 | 48.7 |

**Result: pass.**
- No request errors in either pass, and the serve log shows no 4xx/5xx responses or memory-guard trips.
- Free memory never went below 61%.
- Across seeds 1–3, structured validity holds at 0.95–0.97 (above prod's 0.889), and recall stays at 0.61–0.63, the on-Mac control band.
- p95 latency varies with the seed's mix of long reflect requests (170–252 s). It stays under the 600 s requirement, but it is the figure to watch in the Phase 3 shadow.
- **Tail: runaway reasoning.** 13 of 400 requests (3.3%) ran past 600 s, with a maximum of 775 s.
  - **What happens:** in every one, gpt-oss used all 32,768 completion tokens on reasoning (about 32,765 reasoning tokens at about 43 tok/s) and returned no content. These are the soak's empty responses.
  - **Cause:** 265 of the 400 Hindsight requests send no `max_tokens` and no `reasoning_effort`, so oMLX's 32,768-token default applies. The other 135 send `max_tokens: 16000, reasoning_effort: low`.
  - **Implications:**
    - A gateway with a hard 600 s cap would turn these into errors rather than empty answers.
    - The production empty rate of 0.095 is plausibly the same failure, at llama.cpp's 39 tok/s.
  - **Phase 3 follow-up:** cap the uncapped requests, either per route at the gateway or in Hindsight's config, at about 8–16K `max_tokens`. Re-check the empty rate and p95 in the shadow.

### Resident set and memory budget

oMLX's memory guard is 80 GB; the iogpu wired cap is 84 GB.

| Set | Weights | Headroom under 80 GB for KV cache and spikes |
|---|---|---|
| Resident: gpt-oss-20b + Qwen3.6-35B-A3B | 30.6 GB | ~49 GB |
| Plus Qwen3-Coder-Next on demand | 72.5 GB | ~7 GB. Too tight for c=5 long-prompt traffic: at 32K c=5, Coder-Next alone took the Mac down to 32% free. |

When Coder-Next is requested, oMLX's LRU unloads the least recently used resident model rather than holding all three. This set has not been tested concurrently; the Phase 3 shadow should load the pair and confirm free memory stays above about 25% under mixed traffic.

### Splash fast lane (follow-up to the engine ruling)

Moot for Hindsight. The reasoner pick is gpt-oss-20b, which Splash doesn't support, so the Hindsight fast-lane soak isn't needed. A Splash lane remains possible only for the Qwen3.6-35B agent/chat role, and only if the Phase 3 shadow shows that role is latency-bound.

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

## Gateway verdict (2026-10-21): keep Omniroute

The operator ruled to keep Omniroute and shelve the gateway evaluation (plan Task 6). Steps 2–4 (candidate list, scoring, PoC) were not run. Why:

- The probes above remove the main reason to replace it. The 120 s `maxWaitMs` cap does not cut generation (a 254 s non-streamed request completed), and unauthenticated `/v1/messages` is fixed. A router change is no longer on the critical path to retiring bigboi.
- Omniroute is what exposes the Claude subscriptions (cliproxyapi) and OpenAI/Codex to consumers. A replacement would have to keep both, or move them to cliproxyapi as a standalone upstream. That is work with no current payoff.

Accepted limits, carried into Phase 3:

| Limit | Handling |
|---|---|
| No Prometheus `/metrics`; `cost_report` shows no per-key attribution | Accepted. Engine-side metrics (oMLX exporter) cover the Mac. |
| Routes, combos and keys live in its DB, not git | Accepted. Record the Mac-facing connections and combos in a repo runbook when Phase 3 repoints them. |
| `coding-deep` and `debugging` combos fall back between Claude and local models | Accepted for now. Fix if a consumer needs strict "Claude only by explicit model name". |
| Request-length cap unproven past 254 s | Hindsight stays direct to the Mac (spec architecture), so the 600 s rule only matters for the gpt-oss runaway tail. That tail is fixed by capping `max_tokens` in Hindsight's config, not at a gateway. |

Revisit triggers: Omniroute regresses on any probe above, a consumer needs per-key attribution or Prometheus metrics, or the Claude/OpenAI subscriptions are dropped (Omniroute's remaining reason to exist then goes away). Bifrost is the documented first candidate if that happens.
