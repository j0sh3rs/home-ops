# Evaluation: scenarios and outcomes

Companion to [README.md](README.md). All runs happened on 2026-11-12 (evaluation) and 2026-11-13 (live rollout checks) on one Apple M5 Ultra / 96 GB host. Receipts (raw requests, streamed responses, grader output, resource samples) were kept in a private, git-ignored results folder; only aggregate outcomes are recorded here. No prompts or personal data are included.

## Method

**Isolation.** Every live stage ran the installed oMLX build in a private instance on loopback, with a separate base path, fresh credentials, read-only links to existing weights and a private cache. Only one candidate was resident at a time. The runner refused to start if the production server was busy or had models loaded, never called production unload or configuration endpoints, and stopped only the processes it owned. A stage aborted if new system swapouts exceeded 64 MiB (none did).

**Coding agent and grading.** Synthetic coding tasks (Go, Python, TypeScript) ran through a constrained tool loop (list/read/write files, run the visible tests). Hidden checks ran afterwards in pinned, network-disabled containers (read-only root, project-only write access, 2 CPUs, 2 GiB, 128 pids). Whole-task limits: 12 assistant turns, 420 s of agent work, 65,536 completion tokens. Scoring `quality-v2`: only a completed attempt with a passing hidden grade counts; turn, token, time or missing-usage exhaustion is a failure. Elapsed time includes failures and hidden grading.

**Sampling.** Qwen3.8: temperature 1.0, top-p 0.95, top-k 20, min-p 0, no penalties, thinking enabled and preserved, reasoning effort per profile. Qwen3.6: temperature 0.6, effort omitted (unsupported). Window 131072 for every candidate. Native MTP, DFlash, TurboQuant and ANE-prefill switches were off for native rows. Splash rows used Splash's own DFlash2 drafting, ANE prefill, int8 KV, auto memory and a 16 GiB private SSD cache.

### Candidates

| ID | Checkpoint | Engine | Max output | Thinking budget | Effort | Temp |
|---|---|---|---:|---:|---|---:|
| q4-splash-balanced | Qwen3.8-27B oQ4e | Splash | 16384 | 4096 | medium | 1.0 |
| q8-native-deep | Qwen3.8-27B oQ8e | native | 32768 | 8192 | xhigh | 1.0 |
| q8-splash-balanced | Qwen3.8-27B oQ8e | Splash | 16384 | 4096 | medium | 1.0 |
| q8-splash-deep | Qwen3.8-27B oQ8e | Splash | 32768 | 8192 | xhigh | 1.0 |
| q36-native-balanced | Qwen3.6-35B-A3B 4-bit | native | 16384 | 4096 | omitted | 0.6 |
| q36-splash-balanced | same | Splash | 16384 | 4096 | omitted | 0.6 |
| q36-splash-deep | same | Splash | 32768 | 8192 | omitted | 0.6 |

Engine-only comparisons used identical weights, templates and prompts: q8-native-deep vs q8-splash-deep, q36-native-balanced vs q36-splash-balanced. "Balanced vs deep" changes output, thinking budget and effort together, so it is a profile comparison, not a single-variable experiment.

## Scenario 0: offline preparation and harness proof

| Check | Outcome |
|---|---|
| Unit suite (candidate selection, per-family sampling and draft, unsupported-effort omission, budget boundaries, ownership/cleanup, isolation) | 77 tests pass |
| Grader proof: each of the 12 legacy and 6 fresh fixtures, plus 4 seed-specific long-context variants, with a correct reference and a broken implementation | Reference passes and broken fails in the isolated containers; a seed-17 reference fails the seed-29 hidden checks (seeds are not interchangeable) |
| `--resume` identity (added after review) | Fingerprint now includes full content hashes of weight files (cached by path, size, mtime), oMLX app and Splash binary identity, and a hash of the scoring harness. Regression tests confirm same-size replacement weights, a Splash build change or a harness change each invalidate reuse. Results produced before this change are not resumable |

## Scenario 1: smoke and compatibility

Checks per admitted candidate: advertised alias/window and actual loaded engine and target; exact answer; strict native-schema JSON; structured tool arguments; tool-result continuation; preserved reasoning across a second tool turn; token counting of the full rendered prompt; usage accounting.

| Run | Outcome |
|---|---|
| First pilot smoke (6 candidates) | First attempt stopped: Splash does not implement `/tokenize`. Fixed by counting Splash prompts via `/v1/messages/count_tokens` (native keeps `/tokenize`). Rerun: 30/30 checks pass |
| Seven-candidate smoke | 7/7 candidates pass |

## Scenario 2: first pilot (Q4 coding profiles, Q8 quality profiles)

Four coding tasks (`infra-01`, `infra-05`, `code-01`, `code-06`) x seeds 17 and 29 = 8 attempts per candidate, scoring `quality-v1`.

| Candidate | Engine | Output / thinking | Passed | Elapsed |
|---|---|---|---|---:|
| coding-baseline (Q4) | native | 6144 / 1536 | 7/8 | 422 s |
| coding-output (Q4) | native | 16384 / 1536 | 7/8 | 421 s |
| coding-tuned (Q4) | native | 16384 / 4096 | 7/8 | 408 s |
| **coding-splash (Q4)** | **Splash** | 16384 / 4096 | **8/8** | **137 s** |
| quality-baseline (Q8) | native | 6144 / 1536 | 7/8 | 498 s |
| quality-tuned (Q8) | native | 32768 / 8192 | 8/8 | 1255 s |

Raising output length alone did not change accuracy on Q4. Splash on identical Q4 weights was about 3.4x faster per correct task. Two simultaneous 32K requests: native 27.3 s / 44.2 s, Splash 14.0 s / 27.1 s. Long retrieval to ~98K passed on all candidates (36/36 across candidates). These receipts are `quality-v1` and kept as historical evidence only.

## Scenario 3: calibration screen

The four calibration tasks, seed 17, all seven candidates (28 attempts), to choose finalists.

| Candidate | Passed | Elapsed | Correct tasks/min | Tool errors |
|---|---|---:|---:|---:|
| q4-splash-balanced | 4/4 | 75 s | 3.18 | 0 |
| q8-native-deep | 4/4 | 963 s | 0.25 | 0 |
| q8-splash-balanced | 4/4 | 66 s | 3.63 | 0 |
| q8-splash-deep | 4/4 | 178 s | 1.35 | 0 |
| q36-native-balanced | 3/4 | 33 s | 5.39 | 0 |
| q36-splash-balanced | 4/4 | 22 s | 10.99 | 2 |
| q36-splash-deep | 3/4 | 27 s | 6.64 | 0 |

Four tasks is only enough to rank configurations for follow-up, not to claim superiority. Finalists carried forward: q8-native-deep, q8-splash-deep, q36-splash-balanced, then q4-splash-balanced and q8-splash-balanced as additional challengers.

## Scenario 4: legacy qualification (12 tasks x seeds 17 and 29)

24 attempts per finalist (4 reused from the screen after fingerprint match), including test-generation grading against a correct implementation and four semantic mutants. These tasks were also used for calibration, so they are regression evidence, not untouched evaluation data.

| Candidate | Passed | Elapsed | Correct tasks/min | Tool errors |
|---|---|---:|---:|---:|
| q8-native-deep | 23/24 | 4351 s | 0.32 | 0 |
| q8-splash-deep | 22/24 | 1836 s | 0.72 | 0 |
| q8-splash-balanced | 21/24 | 656 s | 1.92 | 0 |
| q4-splash-balanced | 20/24 | 405 s | 2.96 | 0 |
| q36-splash-balanced | 14/24 | 235 s | 3.58 | 3 |

## Scenario 5: fresh holdout (6 new tasks x seeds 17, 29, 43)

18 attempts per finalist, frozen after calibration. Task, fixture and grader hashes were fixed before candidates ran. Hidden checks derive answers independently of any implementation.

| Task | Behaviour tested |
|---|---|
| `splash-infra-01` | Go reconcile loop: idempotence, stale/duplicate events, transient-failure retry, no real clock or network |
| `splash-infra-02` | Python configuration overlay: precedence, explicit deletion, nested merge, no mutation of input |
| `splash-infra-03` | Python rollout availability: missing/stale status, zero desired replicas, contradictory counts |
| `splash-code-01` | Python incremental record parser: records split at every boundary, escaping, malformed input |
| `splash-code-02` | Python multi-module cache refactor: API compatibility, invalidation after writes, error preservation |
| `splash-code-03` | Go bounded worker shutdown: cancellation, queued work, error propagation, deterministic channel coordination |

| Candidate | Passed | Elapsed | Correct tasks/min |
|---|---|---:|---:|
| q8-splash-balanced | 13/18 | 676 s | 1.15 |
| q4-splash-balanced | 12/18 | 451 s | 1.60 |
| q8-splash-deep | 12/18 | 1870 s | 0.38 |
| q8-native-deep | 9/18 | 3852 s | 0.14 |
| q36-splash-balanced | 5/18 | 399 s | 0.75 |

Six tasks are not eighteen independent tasks; repeated seeds measure repeatability. No statistical claim is made.

### Combined (legacy + holdout, 42 attempts)

| Candidate | Passed /42 | Correct tasks/min |
|---|---:|---:|
| q8-splash-balanced | 34 | 1.53 |
| q8-splash-deep | 34 | 0.55 |
| q4-splash-balanced | 32 | 2.24 |
| q8-native-deep | 32 | 0.23 |
| q36-splash-balanced | 19 | 1.80 |

Reading: Q8 balanced and Q8 deep tie on accuracy, so the cheaper profile wins. Q4 loses two tasks against Q8 and is about 1.5x faster per correct task. Qwen3.6 is fast but fails many hidden checks. Native Q8 is slowest and no more accurate.

## Scenario 6: long-context capacity (`long` stage)

Independent JSON retrieval at ~32K, ~64K and ~98K tokens (cold, then exact replay), plus three 160-record structured-output checks (~2K output tokens, full array validated). The full output allowance plus 256 sizing tokens was reserved inside the 131072 window.

| Candidate | Retrieval 32K/64K/98K | 160-record output | Cold 98K first token | Records-160 time |
|---|---|---|---:|---:|
| q4-splash-balanced | pass | 3/3 | 52.8 s | ~12 s |
| q8-splash-balanced | pass | 3/3 | 66.1 s | ~17 s |
| q8-splash-deep | pass | 3/3 | 66.4 s | 28-41 s |
| q8-native-deep | pass | 3/3 | 77.4 s | 250-306 s |
| q36-splash-balanced | 32K pass; **64K replay failed (fenced JSON answer)** | not reached | n/a | n/a |

Cached replays returned the first token in 0.1-0.2 s on Splash. The Qwen3.6 failure stopped that candidate's stage and excluded it from the next one.

## Scenario 7: long-context coding (`long-coding` stage)

Two tasks (`splash-infra-02`, `splash-code-01`) with generated repository and history context at ~32K, ~64K and ~98K tokens, seeds 17 and 29 (4 attempts per tier). Required behaviour facts were split across the start, middle and end, with plausible stale instructions marked superseded; hidden tests were kept out of the context. Gate for "useful context": at least 3 of 4 attempts pass and each task passes on at least one seed.

| Candidate | 32K | 64K | 98K | Gate met |
|---|---:|---:|---:|---|
| q4-splash-balanced | 2/4 | 2/4 | 2/4 | no |
| q8-splash-balanced | 2/4 | 2/4 | 2/4 | no |
| q8-splash-deep | 2/4 | 1/4 | **4/4** | 98K only |
| q8-native-deep | 2/4 | 1/4 | 0/4 | no |

`splash-code-01` passed at every length on both balanced profiles; `splash-infra-02` failed at every length, including the unpadded task, so the balanced profiles' 2/4 is task difficulty rather than context. The non-monotonic q8-splash-deep row (1/4 then 4/4) is consistent with small-sample noise. Conclusion: capacity to 98K is established, long-context patch quality is not.

## Scenario 8: speed reference

Fixed code-oriented text at ~1K, 8K, 16K and 32K tokens, five cold-prefix/exact-replay pairs per length, 1,024-token output cap, thinking on. Order was repeated ABBA across invocations to control drift. A replay counts as a cache hit only when cached tokens were reported. Rows whose reasoning exhausted the cap were kept as timing-only. Decode rate is client-derived (completion tokens over time after first token); medians, with min-max in parentheses where five samples exist.

| Candidate | Decode tok/s (all lengths) | Cold 8K / 16K / 32K first token | Cached replay first token |
|---|---|---|---:|
| q4-splash-balanced | 145-180 (137-196) | 2.8 / 5.9 / 12.9 s | ~0.1 s |
| q8-splash-balanced | 116-129 (108-140) | 3.9 / 8.3 / 17.7 s | ~0.1 s |
| q8-splash-deep | 102-124 (96-126) | 4.1 / 8.3 / 17.6 s | ~0.1 s |
| q8-native-deep | 26-27 | 4.8 / 9.8 / 20.7 s | 0.4-2.3 s |
| q36-splash-balanced | 380-456 (single samples) | 0.6 / 1.3 / n/a | ~0.0-0.1 s |
| q36-native-balanced | 210 (single sample, 8K) | 0.8 s at 8K | 0.3 s |

Qwen3.6 rows have one sample per cell (the stage stopped early for that candidate); treat as indicative. Splash-published numbers for other Macs were not mixed into these.

## Scenario 9: concurrency

Waves with independently checkable answers: 2 simultaneous 32K, 2 simultaneous 64K, 4 simultaneous 32K, and a mixed wave (a fresh long prefill arriving during a substantial ongoing decode). Slowest request per wave shown. All requests in every wave passed with zero new swapouts.

| Candidate | 2x32K | 2x64K | 4x32K | Mixed prefill | Mixed decode |
|---|---:|---:|---:|---:|---:|
| q4-splash-balanced | 26.7 s | 61.8 s | 28.1 s | 21.0 s | 25.7 s |
| q8-splash-balanced | 36.5 s | 80.8 s | 38.5 s | 32.0 s | 37.2 s |
| q8-splash-deep | 37.2 s | 81.9 s | 39.4 s | 32.4 s | 44.1 s |
| q8-native-deep | 54.8 s | 85.3 s | 92.3 s | 44.3 s | 284.7 s |
| q36-splash-balanced | 9.9 s | 19.1 s | 11.7 s | 7.0 s | 18.0 s |
| q36-native-balanced | 17.9 s | 22.5 s | 24.1 s | 20.4 s | 44.7 s |

In the 4x32K waves on Splash, the first two requests finished in about 2-3 s, which indicates the shared 32K prefix was already cached by the earlier 2x32K wave; the slowest request is the better guide to cold behaviour. Splash overlapped requests; the native Q8 engine's mixed decode wave stalled to 285 s.

## Scenario 10: live rollout verification (2026-11-13)

| Check | Outcome |
|---|---|
| `local-coding:long` and `local-quality:long`, short prompt after applying the config | Both answered correctly through Splash; Splash logs show `context 128K` for each |
| Both models resident | Planned ~24.6 GB (Q4) and ~36.2 GB (Q8) at 128K; actual ~21 GB + ~33 GB; guard 80 GiB; swap use 4 MB afterwards |
| Q4: `:daily` first, then `:long` | `Ready ... context 32K`, then the pool logged "Runtime settings variant changed ... unloading before reload" and `Ready ... context 128K` (~10 s) |
| Q8: `:daily` first, then `:long` (before fix) | **Failed**: stayed at `context 32K`; `:long` answered in 0.2 s with no reload |
| Q8 after setting `mtp_enabled` on its daily profile | `:daily` reloaded at 32K; `:long` with a 45,021-token prompt reloaded to `context 128K` and answered correctly (38.9 s including reload and a cold 45K prefill) |
| Manual unload of the Q8 Splash model | Stalled ~4 min 20 s, then the oMLX server restarted (connection dropped, then refused for several minutes). Cause not established; Q4 unload and automatic reload unloads took under a second |

Details and the config diff are in [rollout.md](rollout.md).
