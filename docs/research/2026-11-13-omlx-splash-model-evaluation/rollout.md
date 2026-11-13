# Rollout, tuning and operations

Companion to [README.md](README.md) and [evaluation.md](evaluation.md). Applied 2026-11-13 through oMLX's admin API (no manual file edits, no restart), after a backup of the three oMLX settings files.

## What changed in oMLX

| Setting | Before | After |
|---|---|---|
| Qwen3.8-27B oQ4e record: engine | native | **Splash** |
| Qwen3.8-27B oQ8e record: engine | native | **Splash** |
| Qwen3.6-35B-A3B 4-bit record: engine | native | native (unchanged) |
| Both `long` profiles: max output tokens | 6144 | **16384** |
| Both `long` profiles: thinking budget | 1536 | **4096** (enabled) |
| Both `long` profiles: preserved thinking | unset | **on** |
| Both `long` profiles: window | 131072 | 131072 (unchanged by decision) |
| `daily` profiles: window / output / thinking | 32768 / 6144 / 1536 | unchanged |
| Q8 `daily` profile: `mtp_enabled` | off | **on** (reload trigger, see below) |
| Global `splash_ssd_cache_gb` | unset (volume-limited, observed ~106 GiB per model) | **16** |
| Global `splash_kv_format`, `splash_ane_prefill`, `splash_max_memory_gb` | int8 / on / unset | unchanged |
| oMLX memory guard | custom 80 GiB ceiling | unchanged |

The Q4 record mirrored its `long` profile exactly, so the profile was re-applied to the record to keep them in sync. The Q8 record keeps its 32768 window (it behaves like its `daily` profile). Engine choice is per model record, so changing the Q8 engine also moved `local-quality:daily` and plain `local-quality` onto Splash.

Backup of the settings files was taken before the change and kept alongside the live oMLX settings (`~/.omlx/backup-pre-splash-<timestamp>/`).

## Why daily and long differ in `mtp_enabled`

On Splash the context window is fixed when the process starts. oMLX reloads an engine on a profile switch only when its runtime signature changes, and that signature does not include the Splash context window (the window feeds only a conditional YaRN factor). Consequences observed:

- Q4 switched correctly from `:daily` to `:long` only because its daily profile already had `mtp_enabled` on while `long` had it off.
- Q8 daily and long had identical signatures, so a Q8 process started by `:daily` stayed at 32K and then served `:long` requests.
- Setting `mtp_enabled` on the Q8 daily profile fixed it. Splash ignores the flag: oMLX forwards only KV format, memory, context window, cache and ANE settings to Splash.

This is a fragile workaround for an oMLX gap. If anyone aligns the MTP flags between a model's daily and long profiles, 128K requests can silently run on a 32K process. Re-test `:daily` then `:long` after any profile edit or oMLX upgrade. Rolling Q8 back to the native engine also means reverting that flag; with MTP on, the Q8 daily profile no longer matches the configuration it was originally qualified with.

## Context window sizing

| Alias / profile | Window | Process after load |
|---|---:|---|
| `*:long`, plain `local-coding` | 131072 | Splash at 128K |
| `*:daily`, plain `local-quality` | 32768 | Splash at 32K |
| `local-fast:daily` | 32768 | native |

- Usable input is window minus output: with 16384 output the long profile leaves about 115K tokens of input.
- Tested: retrieval and structured output to ~98K input (evaluation), a 45,021-token prompt on live Q8 `:long`. Untested: 192K and 256K (the model's native maximum and oMLX's cap).
- KV cost is small relative to weights. The Q8 config has 16 full-attention layers, 4 KV heads and head dimension 256, so int8 KV is roughly 32 KiB per token, about 4 GiB at 128K and 8 GiB at 256K (an estimate from the config, assuming the Q4 checkpoint matches). Latency is the real cost: cold prefill of 98K took 53 s (Q4) and 66 s (Q8).
- Cached prefixes return the first token in about 0.1 s, so the 16 GiB per-model SSD cache matters for long agent sessions with repeated prefixes. Very long histories may evict sooner than before the quota was set.
- Qwen3.6 stays native at 32K. On Splash it failed a 64K retrieval replay in the long-context stage (see evaluation.md), so it is not a candidate for a long profile.

## Tuning available (and what was not applied)

**Through oMLX (installed 0.7.3, Splash integration):**

| Control | Scope | State |
|---|---|---|
| Engine per model record | per model | Splash for both Qwen3.8 records |
| Model context window | per profile | 32K daily / 128K long |
| Per-request sampling, effort, thinking budget, preserved thinking, response format | per request / profile | set per profile as above |
| Splash KV format (int8 / bf16) | global | int8 |
| Splash memory limit | global | unset (auto-sized for one context window, under the guard) |
| Splash SSD cache quota | global (applied per model) | 16 GiB |
| Splash ANE prefill | global | on |

oMLX's own acceleration switches (native MTP, DFlash, TurboQuant, ANE prefill, SpecPrefill) do not apply to Splash.

**Native Splash only (not forwarded by oMLX 0.7.3, not applied):** `--activations auto|bf16`, `--state-format fp32|bf16`, `--decode-share`, `--queue-size`, `--max-cache-disk-writes`, `--verify-rows auto|all`, `--language-only`, and expert/PLE/sparse-KV memory flags. Nothing in the results called for them. They are reasonable follow-up experiments through a temporary directly-served Splash instance if needed (for example BF16 precision parity checks need a fresh cache directory, BF16 KV with BF16 activations and ANE disabled to be strict). Direct serving would bypass oMLX's alias, memory-guard and cache coordination, so keep it to isolated experiments and give each process its own memory budget.

## Incidents and lessons

1. **Splash lacks `/tokenize`.** The first smoke attempt stopped on it. Splash prompt counting uses `/v1/messages/count_tokens`.
2. **Resume identity gap.** The harness's `--resume` originally identified weights by file name and size and ignored runtime and scoring-harness versions. Fixed with full-content hashes (cached), runtime identity (oMLX app and Splash binary) and a harness hash, with regression tests.
3. **Silent 32K process for `:long`.** Described above; found by testing the Q8 daily-then-long order, not by the first smoke, which loaded `:long` first. Always test both orders.
4. **Manual Q8 unload stall.** An admin unload of the Q8 Splash model (while Q4 was also loaded) stalled about 4 min 20 s with no server log activity beyond Splash status polling. Splash only logged "Stopping" at the end, then the oMLX server restarted; for several minutes the API refused connections. Cause not established (possibly the app's watchdog restarting an unresponsive server). The Q4 manual unload (under a second) and the automatic reload-on-profile-switch unloads (about 0.25 s) were fine. Avoid manually unloading the Q8 Splash model until root-caused.
5. **Unrelated rejected-key noise.** Some other client was sending an invalid API key to oMLX during the session, producing 401s and a 429 rate limit. It was not part of this work.

## Rollback

1. Set the engine field back to native on the two Qwen3.8 records (admin settings API or UI).
2. Revert the two `long` profiles to 6144 output and 1536 thinking, or restore the three oMLX settings files from the pre-change backup while the server is stopped.
3. Revert the Q8 daily profile's `mtp_enabled` to off (only valid once the engine is native).
4. Clear the Splash SSD quota (set it back to unset) if the old behaviour is wanted.

Measured native baselines for comparison: Q8 ~27 tok/s decode; in the first pilot, Q4 on Splash was about 3.4x faster per correct task than Q4 native.

## Open items

- Probe 192K and 256K windows on the coding model (cold, cached and concurrent cases) before raising any window.
- Run tool-heavy and concurrent traffic against the final aliases and re-measure live tok/s.
- Root-cause the Q8 manual unload stall; test long-to-daily-to-long switching for both models.
- Evaluate the other Splash-supported models (Ornith, Flint, Flash-Next and the GGUF checkpoints already in oMLX) if a quality or speed gap remains. They were not run in this evaluation.
- Ask upstream oMLX to include the Splash context window in the reload signature, which would remove the MTP workaround.
