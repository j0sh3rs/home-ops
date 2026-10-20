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

## Engine bake-off ledger

### Models (2026-10-19)

Both are MLX 4-bit (`bits: 4, group_size: 64, mode: affine` in `config.json`). oMLX reads them from `/opt/ai/models.noindex/`, as APFS clones (`cp -c`) owned by `_omlx`. The clones' shard sizes match the sources byte for byte, and `_omlx` can read them.

| Model | HF repo | Revision | Size | Source copy |
|---|---|---|---|---|
| Qwen3.6-35B-A3B | `lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit` | `0c4a20a6437ae5985ddc9eb1a3f122ee6c151c3b` | 19G (4 shards) | `~/bakeoff/models/` |
| Qwen3.8-27B | `lmstudio-community/Qwen3.8-27B-MLX-4bit` | unknown (downloaded by LM Studio, no HF metadata) | 15G (3 shards) | `~/.lmstudio/models/` |

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
