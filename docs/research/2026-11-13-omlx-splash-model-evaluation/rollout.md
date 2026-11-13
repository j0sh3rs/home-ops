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
| `daily` profiles: window / output / thinking | 32768 / 6144 / 1536 | unchanged at the time; the Q4 `daily` profile was deleted on 2026-11-13 |
| Q8 `daily` profile: `mtp_enabled` | off | **on** (reload trigger, see below) |
| Global `splash_ssd_cache_gb` | unset (volume-limited, observed ~106 GiB per model) | **16** |
| Global `splash_kv_format`, `splash_ane_prefill`, `splash_max_memory_gb` | int8 / on / unset | unchanged |
| oMLX memory guard | custom 80 GiB ceiling | unchanged |

The Q4 record mirrored its `long` profile exactly, so the profile was re-applied to the record to keep them in sync. The Q8 record keeps its 32768 window (it behaves like its `daily` profile). Engine choice is per model record, so changing the Q8 engine also moved `local-quality:daily` and plain `local-quality` onto Splash.

**Update, 2026-11-13 (later):** the Q8 and Qwen3.6 aliases were then retired: the Q8 record is hidden with its alias cleared and both profiles unexposed, and the served set is now only `local-coding`, `local-coding:daily` and `local-coding:long`. The Q8 weights stay on disk. The Qwen3.6 record could not be edited because its weights link is dangling. Client configuration that referenced `local-quality` was updated the same day. oMLX settings were backed up before the change.

Backup of the settings files was taken before the change and kept alongside the live oMLX settings (`~/.omlx/backup-pre-splash-<timestamp>/`).

## Why daily and long differ in `mtp_enabled`

On Splash the context window is fixed when the process starts. oMLX reloads an engine on a profile switch only when its runtime signature changes, and that signature does not include the Splash context window (the window feeds only a conditional YaRN factor). Consequences observed:

- Q4 switched correctly from `:daily` to `:long` only because its daily profile already had `mtp_enabled` on while `long` had it off.
- Q8 daily and long had identical signatures, so a Q8 process started by `:daily` stayed at 32K and then served `:long` requests.
- Setting `mtp_enabled` on the Q8 daily profile fixed it. Splash ignores the flag: oMLX forwards only KV format, memory, context window, cache and ANE settings to Splash.

This is a fragile workaround for an oMLX gap. If anyone aligns the MTP flags between a model's daily and long profiles, 128K requests can silently run on a 32K process. Re-test `:daily` then `:long` after any profile edit or oMLX upgrade. Rolling Q8 back to the native engine also means reverting that flag; with MTP on, the Q8 daily profile no longer matches the configuration it was originally qualified with.

## Final decisions and cleanup (2026-11-13)

**Decisions**
- The 32K coding option is dropped: the Q4 `daily` profile is deleted and `local-coding:daily` is no longer served. Served coding aliases are `local-coding` and `local-coding:long`, both 128K. This also makes the `mtp_enabled` reload-trigger workaround below moot: with a single profile there is no daily-to-long switch to get wrong. OMP's `models.yml` was updated to match (the base `local-coding` window is now 131072; its `maxTokens` of 6144 is unchanged).
- Home Assistant conversation: **gemma-4-E4B (8-bit)**. Speech-to-text: **Whisper large-v3-turbo (fp16 `-asr-fp16` repo)**. Text-to-speech: Kokoro-82M (recommended). Hindsight: gpt-oss-20b on oMLX once its cutover is done. None of these except the coding change is wired into consumers yet.

**Swap pressure.** The test session grew system swapouts by about 613,000 pages (roughly 9 to 10 GiB) most likely because several fast models stayed resident next to the Splash coding models, and the oMLX log shows a Qwen3-30B replay (40K to 60K-token prompts, 5-way concurrency) growing its pooled Metal buffers to about 64 GB with requeued requests. I did not isolate which event caused the swapouts. Residual swap (about 3.6 of 5 GB in use) stays until those pages are touched again or the machine reboots. What reduces it: (1) idle TTLs so evaluation-class models unload on their own (applied, 900 s on the fast LLMs and speech models); (2) a deterministic resident set of about 50 GB (Q4 about 25, gpt-oss about 12, E4B about 9, Whisper about 2, Kokoro under 1) instead of whatever happened to be loaded; (3) removing rejected models so they cannot be loaded by accident; (4) running evaluations one candidate at a time with an unload between; (5) bounding concurrency for long-prompt consumers such as Hindsight; (6) once the voice stack goes live, pinning E4B, Whisper and Kokoro (about 11.5 GB) so they are not cold-loaded on the first utterance; (7) consider lowering the oMLX memory ceiling from 80 to about 70 GiB so oMLX throttles before macOS swaps (not applied: it is your existing setting).

**Model inventory cleanup (disk).** Deleted through the oMLX delete endpoint: Qwen3-30B-A3B-Instruct-2507 4-bit (17 GB; failed HA at 0.64 and trailed on Hindsight recall), Qwen3-TTS-12Hz-0.6B-CustomVoice 8-bit (1.9 GB; intermittent runaway audio), and the plain `whisper-large-v3-turbo` repo (1.6 GB; cannot load in oMLX, superseded by the `-asr-fp16` repo). About 20 GB freed. Kept on purpose: Qwen3.8 oQ4e and its draft (in use), Qwen3.8 oQ8e (disk only), gpt-oss-20b (Hindsight), gemma-4-E4B, Whisper fp16 and Kokoro (chosen), gemma-4-26B-A4B and parakeet (fallbacks, 15 GB and 2.4 GB), the Qwen3.6 UD-Q2_K_XL GGUF and its DFlash2 draft (never evaluated), and the Flash-Next GGUFs and draft (never evaluated, 141 GB, cannot co-reside with Q4 under the guard).

## Context window sizing

| Alias / profile | Window | Process after load |
|---|---:|---|
| `*:long`, plain `local-coding` | 131072 | Splash at 128K |
| ~~`*:daily`, plain `local-quality`, `local-fast:daily`~~ | retired / dropped 2026-11-13 | not served |

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
| Model context window | per profile | 128K (the 32K coding profile was dropped) |
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
