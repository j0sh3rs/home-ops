# oMLX + Splash local model evaluation (2026-11-13)

**Status:** Applied and smoke-verified on the Mac inference host. **Hardware:** Apple M5 Ultra, 80-core GPU, 96 GB unified memory, oMLX memory guard at 80 GiB. **Software:** oMLX 0.7.3 (build 3574), Splash 1.6.1, Qwen3.8-27B and Qwen3.6-35B-A3B checkpoints (MLX affine quantisations), Splash DFlash2 draft models.

Companion documents: [evaluation.md](evaluation.md) (every test scenario and outcome) and [rollout.md](rollout.md) (what was changed, live verification, incidents, rollback).

## Executive summary

### Final configuration

| Alias | Checkpoint | Engine | Context window | Max output | Thinking budget | Enabled features | Key evidence |
|---|---|---|---:|---:|---:|---|---|
| `local-coding:long` (and plain `local-coding`) | Qwen3.8-27B oQ4e | **Splash** | 131072 | 16384 | 4096 (effort medium) | Splash DFlash2 drafting, int8 KV, ANE prefill, 16 GiB SSD prefix cache, preserved thinking | 32/42 graded coding tasks; ~2.2 correct tasks/min (3.4x the native engine in the first pilot); 150-180 tok/s decode; 36/36 long-context checks to 98K input |
| `local-quality:long` | Qwen3.8-27B oQ8e | **Splash** | 131072 | 16384 | 4096 (effort medium) | Same as above | 34/42 (tied best); ~1.5 correct tasks/min; 115-130 tok/s decode (native engine: ~27); 36/36 long-context checks to 98K; deep thinking (8K) gave no accuracy gain for ~3x the time |
| `local-coding:daily` | Qwen3.8-27B oQ4e | Splash | 32768 | 6144 | 1536 (effort medium) | Splash engine features (DFlash2, int8 KV, ANE prefill, SSD cache); no preserved thinking; `mtp_enabled` on (inert on Splash, see note) | Unchanged limits; reloads the Splash process when switching to or from `:long` |
| `local-quality:daily`, plain `local-quality` | Qwen3.8-27B oQ8e | Splash | 32768 | 6144 | 1536 (effort medium) | Same as `local-coding:daily` (`mtp_enabled` on in the daily profile, see note) | Same as above |
| `local-fast:daily` | Qwen3.6-35B-A3B 4-bit | Native (unchanged) | 32768 | 6144 | 1536 | None of the Splash features | Fastest decode (380-455 tok/s on Splash, 210 native) but only 19/42 tasks and 3 tool errors on Splash; not recommended for correctness-sensitive work, left alone |

Global Splash settings: KV format `int8`, ANE prefill `on`, memory limit `unset` (auto-sized per model under the guard), SSD cache quota `16 GiB` per model (was unset, which allowed ~100+ GiB per model).

**Note on `mtp_enabled`:** oMLX does not include the Splash context window in its engine reload signature. A model whose daily and long profiles differ only in window size would keep the first-loaded size (a 32K process serving `:long`). Daily and long profiles therefore differ in `mtp_enabled` (on in daily, off in long). Splash ignores the flag, but it forces a reload on profile switch. Verified on both models (details in [rollout.md](rollout.md)). Do not align these flags.

### Evidence at a glance

| Question | Result |
|---|---|
| Engine: Splash vs native oMLX, same Q8 weights | 4.3x decode (≈120 vs ≈27 tok/s); 32K cached replay 0.1 s vs 2.3 s; 4-way mixed decode wave 37 s vs 285 s |
| Quality: best configuration | q8-splash-balanced and q8-splash-deep tied at 34/42; q4-splash-balanced 32/42; native Q8 32/42; Qwen3.6-35B-A3B 19/42 |
| Speed per correct task | q4-splash-balanced ~2.2/min, q8-splash-balanced ~1.5/min, q8-splash-deep ~0.55/min, q8-native-deep ~0.23/min |
| Long-context capacity | All Qwen3.8 candidates passed retrieval at ~32K, 64K, 98K and 160-record structured output; cold 98K prefill 53 s (Q4), 66 s (Q8) on Splash |
| Useful long-context *coding* | **Not established for the chosen profiles** (see caveat below) |
| Concurrency | 2x32K, 2x64K, 4x32K and a mixed prefill/decode wave all passed on every candidate with zero new swapouts; both 27B models resident together used ~54 GB actual |
| Context sizing | 131072 tested on live aliases (45K-token prompt served on Q8 `:long` after a `:daily` load); 192K/256K untested |

**Caveats that affect how far to trust this:**

1. **Small samples.** The Q8-vs-Q4 gap (34 vs 32 of 42) is two tasks. Treat accuracy as a tie. The robust findings are the large speed gaps and Splash vs native.
2. **Long-context coding gate not met.** The pre-registered gate (≥3 of 4 attempts pass at a tier, and each task passes at least one seed) was not met by the balanced profiles at 32K, 64K or 98K. One task (`infra-02`) failed at every length including unpadded, so the shortfall is task difficulty, not context length. Only `q8-splash-deep` met the gate, at 98K only (4/4), with 2/4 at 32K and 1/4 at 64K, which looks like noise rather than a length effect. Capacity (retrieval and structured output to 98K) is demonstrated; patch quality at long length is not.
3. **Only the Qwen3.8 27B and Qwen3.6 35B-A3B checkpoints were exercised.** Other models listed below were never run.
4. **Final live configuration was only smoke-tested** (short prompts, one 45K-token prompt). No tool-heavy, long-running or concurrent test ran against the final aliases.

### Recommendations

1. Use `local-coding:long` for agent and tool-heavy work, `local-quality:long` for hard review/design work, and the `:daily` profiles for short chats.
2. Keep the 4K-thinking "balanced" profile. The 8K "deep" profile gave no measurable gain on Q8 for roughly 3x the time.
3. Keep window sizes as they are (128K long, 32K daily). Probe 192K/256K on the coding model before raising them: prefill latency is the cost (cold 98K already takes about a minute).
4. Avoid manually unloading the Q8 Splash model (one manual unload stalled ~4 minutes and the server restarted; cause unknown).
5. Do not switch `local-fast` to Splash without a quality reason: it would be faster but failed most hidden-grader tasks in this evaluation.

### Not covered

- Ornith, Flint and Ternary Bonsai Splash models were not downloaded or tested.
- Three GGUF checkpoints present in oMLX (Qwen3.6 UD-Q2_K_XL, Flash-Next Q2_0 and IQ3_S) were not run. The Flash-Next IQ3_S quant is listed upstream at ~86 GB and is unlikely to fit under the 80 GiB guard with long-context state.
- Native Splash tuning flags (`--activations`, `--state-format`, `--decode-share`, BF16 KV, and so on) were not applied. Installed oMLX 0.7.3 does not forward them, and nothing in the results called for them.

## Why Splash through oMLX (not Splash directly)

oMLX's Splash integration keeps one endpoint and alias namespace for clients, owns load/unload and memory admission under the guard, forwards per-request sampling, effort, thinking budget and preserved reasoning, and applies per-model SSD cache quotas. Every measured gain in this evaluation already used that integration, so direct serving is an unbenchmarked alternative, not a known improvement. Direct serving is only worth using for temporary experiments with Splash-only flags.

## Sources

- Splash project documentation (server, models, tuning): https://github.com/incoai/splash
- oMLX Splash integration guide: https://github.com/jundot/omlx/blob/main/docs/Splash.md
- Splash-published benchmark figures were treated as vendor claims and were not mixed with local measurements.
