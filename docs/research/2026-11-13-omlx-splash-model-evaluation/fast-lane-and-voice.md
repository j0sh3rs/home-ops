# Fast-lane and voice evaluation (2026-11-13)

Companion to [README.md](README.md). Question: after collapsing the served aliases to the Qwen3.8 Q4 coding model on Splash, which open models should cover the "Haiku-class" roles (Hindsight extraction, Home Assistant conversation) and speech (STT/TTS)?

**Status: evaluated. Decided on 2026-11-13: gemma-4-E4B for Home Assistant and Whisper (fp16) for speech-to-text; neither is wired into consumers yet.** These are screening results on synthetic or replayed inputs, taken on the same Apple M5 Ultra / 96 GB host with oMLX 0.7.3. They support a recommendation; they do not prove production accuracy.

## Summary

| Role | Recommendation | Evidence | Confidence |
|---|---|---|---|
| Hindsight extraction | **gpt-oss-20b (MXFP4-Q8, native oMLX) is the best local model; no candidate beat it.** Not yet in use: Hindsight currently runs on a temporary cloud route (`openai-codex`, `gpt-6.1-luna`), so reaching this end state needs the cutover below. | Same 100 replayed requests: recall 0.648 vs 0.454 to 0.572; structured 0.989 | Medium: 100 requests, one sample, memory pressure during runs (see Caveats) |
| Home Assistant conversation | **gemma-4-E4B (8-bit)** (decided), with gemma-4-26B-A4B kept on disk as the equal-scoring fallback. Remove the `bash` tool from the HA agent. | Both pass 22 of 23 unique non-shell cases (66 of 69 requests; the 2 shell cases are scored separately); first token about 0.4 to 0.5 s warm. Qwen3-30B (control 21/39) mostly makes no call or the wrong call and never violates the schema; gpt-oss (control 0/39) violates the schema on every control request | Low to medium: synthetic house, temperature 0, 23 unique non-shell cases (25 with shell) |
| Speech-to-text | **Whisper large-v3-turbo (fp16)** (decided; parakeet-tdt-0.6b-v3 kept as a latency fallback) | Clean speech: both 0.0 word error. Accents: parakeet 0.000 to 0.029, Whisper 0.000 to 0.010. Noise at 10 / 0 dB: parakeet 0.024 / 0.249, Whisper 0.015 / 0.177. Median latency 0.05 s vs 0.13 s; under a 30K prefill 0.10 s vs 0.26 s | Medium: synthetic `say` voices, 24 clips per condition; differences are within small-sample noise except 0 dB |
| Text-to-speech | **Kokoro-82M (af_heart)** | 0.0 word error on 36 clips under both reference models (the same saved audio), 0.06 s median, 3.4x slower under a long prefill (0.28 s p95). Qwen3-TTS-0.6B is slower (0.60 s median) and produced 3 abnormally long clips (9.8 to 15.2 s for 2 to 3 s phrases) with real errors | Medium |

## Method

- **Hindsight:** the existing replay harness (`tools/ai-eval/replay.py` and `grade.py`) over the captured Hindsight corpus (4,257 records), 100 requests (seed 0, c=5), each request replayed with its own recorded `response_format`, tools and limits. Recall and structured/tool validity are scored against the recorded production answers. The gpt-oss-20b control was rerun on the identical 100 requests.
- **Home Assistant:** `ha_suite.py`, a synthetic house of 361 fake entities, the classic extended-conversation system prompt (about 5K tokens, minus its "ask before acting" line) and three tools: `execute_services`, `get_attributes` and a decoy `bash`. 25 cases (13 control, 5 state questions, 3 chat, 2 unknown devices, 2 shell requests), each run 3 times at temperature 0, graded against expected tool calls and schema-validated.
- **Speech:** `voice_bench.py`. STT clips come from macOS `say` (an independent voice) converted to 16 kHz mono; TTS is round-tripped through the reference STT. 12 fixed home-control phrases x 3 repeats. A contended run sustains back-to-back 30K-token prefills on the coding model, and a row counts as contended only if a successful prefill covered its whole request.
- No personal audio was used. The Hindsight corpus is private; only aggregates appear here.

## Hindsight results (same 100 requests)

| Model | Structured valid | Tool valid | Recall | Latency p50 / p95 | Decode tok/s | Hit length cap |
|---|---:|---:|---:|---|---:|---:|
| **gpt-oss-20b (control)** | 0.989 | 0.625 | **0.648** | 44 s / 127 s | 45 | 1 |
| gemma-4-E4B (8-bit) | **1.000** | 0.375 | 0.454 | 22 s / 94 s | 40 | 0 |
| gemma-4-26B-A4B (4-bit QAT) | 0.913 | 0.375 | 0.572 | 33 s / 1254 s | 29 | 7 |
| Qwen3-30B-A3B-Instruct (4-bit) | 0.946 | 0.750 | 0.534 | 71 s / 556 s | 26 | 5 |

- Gate (set before running): structured >= 0.95 and recall within 5% of the control (>= 0.616). Only the control meets it; gemma-E4B passes the structured part but its recall is 30% lower.
- Gemma-26B and Qwen3-30B each have a tail of runaway generations that stop only at the 32,768-token limit and take about 1,300 s apiece. That would stall a background extraction queue.
- The earlier bake-off control (recall 0.618) is not comparable: it used a different sample (seed 1, only 8 of 200 requests overlap). Use the same-sample figures above.

## Home Assistant results (corrected contract, 75 requests per model)

The `execute_services` schema requires a top-level `list` and forbids stray fields at both levels; the grader rejects exactly what the schema rejects (guarded by a test).

| Model | Pass rate (75) | Control | Query | Chat | Unknown device | Tool-schema valid, of calls made | How the failures happen | First token p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---|---|
| gemma-4-26B-A4B | 0.92 | 36/39 | 15/15 | 9/9 | 6/6 | 42/42 | 3 control failures, all a wrong service name | 402 / 845 ms |
| gemma-4-E4B | 0.88 | 36/39 | 15/15 | 9/9 | 6/6 | 45/45 | 3 control failures, all a wrong domain | 479 / 812 ms |
| Qwen3-30B-A3B-Instruct | 0.64 | 21/39 | 12/15 | 9/9 | 6/6 | 30/30 | **No call made** on 15 control requests, a wrong or extra call on 3, and a wrong state answer on 3 query requests; no schema violations | 165 / 573 ms |
| gpt-oss-20b (low effort) | 0.40 | 0/39 | 15/15 | 9/9 | 6/6 | 6/45 | **Schema violation** on all 39 control requests | 163 / 219 ms |

- The tool-schema-valid column counts only requests where the model made a tool call, so a model that rarely calls the tool can show 100% there. Qwen's 21/39 control score is about missing or wrong actions, not schema errors; only gpt-oss fails on the schema itself.
- Both Gemma models fail exactly one control case (3 identical repeats at temperature 0): the 26B writes a domain-prefixed service name (`light.turn_on`) in a mixed lock-and-light request; the E4B calls `switch.turn_off` on a light. Treat them as tied at 22 of 23 unique non-shell cases (the 25 cases less the 2 shell requests).
- gpt-oss-20b puts `entity_id` at the wrong nesting level on every control request. This matches its earlier tool-error behaviour; the schema is not met, so Home Assistant would reject the calls.
- **Shell cases:** every model calls `bash` when the user explicitly asks for a shell command, and only the 26B ever declined (3 of 6 requests). The proposed gate "zero `bash` calls" therefore cannot pass while the tool is offered. Read honestly: no model passes the gate as written; with the two shell cases reported separately both Gemma models score 66 of 69 requests (22 of 23 unique cases, 0.957). The fix is operational, not a model choice: remove `bash` (and `load_skill`) from the HA agent's functions. This is the existing open follow-up in the Home Assistant runbook.
- Historical screening under the earlier schema (where `list` was optional) is kept in the results folder; it ranked the models the same way but graded Qwen's flat arguments differently.

## Speech results

| Model | Role | Latency p50 / p95 | Real-time factor | Word error | Under 30K prefill (p50 / p95) |
|---|---|---|---:|---:|---|
| parakeet-tdt-0.6b-v3 | STT | 0.049 s / 0.27 s (one 2.6 s row is the cold load) | 0.024 | 0.0 | 0.10 s / 0.54 s (2.0x) |
| Whisper large-v3-turbo (`...-asr-fp16`) | STT | 0.127 s / 0.144 s (one 2.8 s row is the cold load) | 0.060 | 0.0 | 0.26 s / 0.29 s (2.0x) |
| Kokoro-82M af_heart | TTS | 0.057 s / 0.083 s | 0.024 | 0.0 under both references | 0.195 s / 0.283 s (3.4x p95) |
| Qwen3-TTS-0.6B CustomVoice, voice `ryan` | TTS | 0.60 s / 1.97 s | 0.156 | 0.094 (parakeet) / 0.056 (Whisper) | not run |

The original `mlx-community/whisper-large-v3-turbo` repo cannot load in oMLX (it ships no processor or tokenizer files); the `-asr-fp16` repo, which includes them, was used.

### STT robustness (24 clips per cell: 12 phrases x 2 repeats)

| Condition | parakeet word error mean / max | Whisper word error mean / max |
|---|---|---|
| British English (Daniel) | 0.000 / 0.000 | 0.000 / 0.000 |
| Australian English (Karen) | 0.000 / 0.000 | 0.000 / 0.000 |
| Irish English (Moira) | 0.029 / 0.286 | 0.000 / 0.000 |
| Indian English (Aman) | 0.010 / 0.125 | 0.010 / 0.125 |
| Samantha plus noise at 10 dB SNR | 0.024 / 0.333 | 0.015 / 0.250 |
| Samantha plus noise at 0 dB SNR | 0.249 / 1.200 | 0.177 / 1.000 |

Whisper is equal or slightly better in every cell, at about 2.6x the latency (both still far below the 1.5 s gate). With 24 clips per cell, only the 0 dB difference is large enough to take seriously, and even that is one sample of one noise type.

### Qwen3-TTS: what the identical-audio check showed

TTS output varies from run to run, so comparing two separate runs says nothing about a specific failure. An earlier run scored Qwen3-TTS at 0.09 word error under parakeet and 0.008 under Whisper, but each run generated fresh audio, so that difference was not evidence of a parakeet misread. The harness now sends the same saved bytes to every reference model. On 36 clips:

- parakeet scores 9 clips as imperfect (mean 0.102; 0.094 after treating "per cent" as "percent") and Whisper scores 5 (mean 0.056). The two disagree on 7 clips, mostly formatting (`30%` vs `thirty percent`) and contractions.
- **Five clips are wrong under both references**, so those are real TTS faults. The worst: a clip of 15.2 s for "turn on the living room lamp" that parakeet returns as empty text and Whisper hears as "There. Oh, oh, oh, oh, oh." Two other phrases also produced clips of 12.0 s and 9.8 s, and one "dim the office light to thirty percent" clip opens with the wrong word ("Battled" / "That was").
- Kokoro: all 36 clips are exact under both references, with consistent durations (1.6 to 4.1 s).

Conclusion: Qwen3-TTS has an intermittent runaway-audio and first-word fault in this setup. Kokoro does not.

### Gates and notes

- Gate (proposed): word error <= 0.10, p95 < 1.5 s, and no more than about 2x slower under contention. Both STT models sit right at the 2x limit on p95 and p50 (parakeet 2.0x, Whisper 2.0x). Kokoro exceeds it by ratio (3.4x) but stays under 0.3 s in absolute terms; judge by the absolute number for voice assistants.
- Clean or lightly degraded `say` voices are the easiest case. Real microphones, room acoustics, overlapping speech and non-English use are untested.
- HA speaks the Wyoming protocol and oMLX serves OpenAI-style HTTP, so a bridge is required (`roryeckel/wyoming_openai`, Apache-2.0, is a candidate; untested). Keep the cluster's whisper and piper as the fallback while the Mac is down.

## Caveats

1. **Memory pressure during the runs.** The test session loaded up to four fast models alongside the Splash coding models, with no swap guard. System swapouts grew by about 613,000 pages (roughly 9 to 10 GiB) and swap use reached 4.8 GB of 6 GB. The oMLX log shows the Qwen3-30B replay hit hard pressure and requeued requests. Quality metrics (structured, recall, tool validity, pass rate) are unaffected, but latency and decode-speed figures, especially for Qwen3-30B and Gemma-26B, may be inflated. Re-measure latency on a clean machine before relying on it. The four fast models were unloaded afterwards; the coding models reload on demand.
2. **Small samples.** 100 Hindsight requests; 25 unique HA cases (repeats are identical at temperature 0); 12 speech phrases.
3. **Synthetic HA house and clean synthetic speech.** Real entity names, aliases, accents and noise will differ.
4. **Sampling and thinking modes** were left at server defaults (HA at temperature 0; gpt-oss at low reasoning effort). Gemma thinking modes were not explored.
5. **Process corrections during the work:** the HA schema was tightened mid-run and all candidates were rerun on the corrected contract; the first Hindsight sample used the wrong seed for comparability and the control was rerun on the identical sample; the confirmation line was removed from the HA prompt because it made every control case fail for every model.

## Proposed next steps (not applied)

1. Remove `bash` and `load_skill` from the Home Assistant agent's function list.
2. Whisper is chosen. Confirm with listening tests on real satellite audio; parakeet remains the fallback if latency under load matters.
3. Re-run Hindsight and HA latency on a quiet machine with at most two fast models resident.
4. Trial gemma-4-E4B as the HA conversation model behind a separate alias, with Kokoro and parakeet behind a Wyoming bridge, and keep the current path as a fallback until real conversations confirm the synthetic result.
5. **Cut Hindsight over to gpt-oss-20b on oMLX (not done).** The manifest still sets `HINDSIGHT_API_LLM_PROVIDER: openai-codex` and `HINDSIGHT_API_LLM_MODEL: gpt-6.1-luna` (a temporary choice made on 2026-11-05 to clear a consolidation backlog), and the ai-tap `hindsight` route still points at llama-swap, not the Mac. The existing Phase 3 cutover plan (`docs/superpowers/plans/2026-10-22-phase3-cutover.md`) covers it, but its Task 1 assumed a nix-managed oMLX with a `reasoner` alias and per-consumer sub keys. The oMLX actually running on the Mac today is the user-run app instance (served aliases: `local-coding*` only; `gpt-oss-20b-MXFP4-Q8` is available only by its raw model id). So first: (a) give gpt-oss-20b a stable alias such as `reasoner`, pinned or on a TTL, with a `max_tokens` default (the plan used 16384), and a Hindsight sub key; (b) test that route with the replay harness from the cluster side; (c) then change the Hindsight provider, base URL, model and API key (via the tap or directly), watching errors, empty rate, p95 latency and length-capped outputs for 24 hours as the plan's Task 4 describes. Note that oMLX does not enforce `response_format`, so `HINDSIGHT_API_LLM_STRICT_SCHEMA_RETAIN` no longer has grammar enforcement behind it; gpt-oss still produced valid structure on 98.9% of replayed requests. Re-evaluate the model only if a candidate beats 0.648 recall on this sample without runaway generations.
