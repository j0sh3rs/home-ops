# UPGRADE-PLANNING: Local Model Slate for RX 7900 XTX (24 GB RDNA3) — and the XT (20 GB) Delta

**Date:** 2026-06-08 · **Status:** Future-upgrade research (NOT current hardware) · **Companion to:** `2026-06-08-llm-model-selection-6900xt.md` (the deployed card)

**Target:** AMD RX 7900 XTX (gfx1100, RDNA3, 24 GiB, 96 CU, ~960 GB/s, WMMA coopmat) — upgrade from RX 6900 XT (gfx1030, RDNA2, 16 GB, no matrix cores). Engine: llama.cpp **Vulkan** (RADV, wave64, KHR_coopmat) via llama-swap, GGUF. Single GPU, Talos node `bigboi-jms-01`. Resident set (embed+rerank+router) stays loaded; chat/coder/reasoning/vision hot-swap **exclusively** in the remaining budget.

> Produced by a multi-agent research workflow (9 slot categories × researcher + adversarial verifier against the HuggingFace Hub + llama.cpp issue tracker, 29 agents). The adversarial verifiers repeatedly caught over-budget quant claims and unverified RDNA3-kernel assumptions; those corrections are applied inline and override the first-pass research.

> **Budget math used throughout.** XTX exclusive swap budget ≈ **22 GiB** after resident set; XT ≈ **18 GiB**. A pick "fits" only if weights + q8_0 KV at a usable context + ~1–1.5 GiB compute buffers stays under that. Where the per-category research over-claimed a quant, the **adversarial verdict's corrected number wins**.

---

## 1. TL;DR Table

| Slot | Old 16 GB pick | **Recommended on 24 GB XTX** | Quant | Est VRAM (weights+KV) | Est decode tok/s | Fits 20 GB XT? | Confidence |
|------|----------------|------------------------------|-------|----------------------|------------------|----------------|------------|
| **Agentic coder (primary, #1)** | Qwen2.5-Coder-7B Q4 / forced Q3 30B | **Qwen3-Coder-30B-A3B-Instruct** | **Q4_K_M** (~18.6 GB) | ~20.5 GB @ 32K | ~50–70 (3B active) | XT: **Q4_K_S/IQ4_XS only** (~16.7–17.5 GB), tight | High (caveat: quant corrected) |
| **Frontier GDN coder (NEW slot)** | None (impossible on RDNA2) | **Qwen3.6-27B** (dense GDN hybrid) | Q4_K_M / UD-Q4_K_XL (16.8–17.6 GB) | ~20–21 GB @ 32–64K | ~12–18 (dense); 47–75 w/ MTP | XT: **marginal**, Q4_K_S / evict resident | Medium (pending direct gfx1100 GDN bench) |
| **FIM autocomplete** | Qwen2.5-Coder-3B Q4 (hot-swap) | **Qwen2.5-Coder-3B (base)** → **RESIDENT** | Q6_K (~2.5 GB) | ~3.2 GB @ 16K | ~90–130 | Yes, trivially | High |
| **General chat (default)** | Qwen3-4B Q4 | **Qwen3.5-27B** GDN hybrid (non-thinking) | Q5_K_M (XTX) / Q4_K_M (XT) | ~20–21 GB @ 24–32K | ~21 (GDN recurrence-bound) | XT: **Q4_K_M only** | High (caveat: build pin + non-thinking) |
| **Deep reasoning / heavy local** | Qwen3-14B Q4 @ 8K (starved) | **Qwen3.6-27B** (dense GDN) | UD-Q4_K_XL (~17.6 GB) | ~20 GB @ 32–64K | ~25–40 (MTP higher) | XT: Q4_K_M @ 16–32K | High (caveat: GDN build pin) |
| ↳ deploy-day safe fallback | — | **Qwen3-32B** (classic dense) | Q4_K_M (~19.8 GB) | ~22 GB @ **16–24K only** | ~22–30 | **XT: NO** (weights alone ~20 GB) | High (caveat: ctx-starved) |
| **Fast router (front-door)** | Qwen3-1.7B Q5 (hot-swap) | **Qwen3-1.7B** → **RESIDENT**, non-thinking | Q5_K_M (~1.4 GB) | <2 GB @ 8K | ~120–150 | Yes, trivially | High |
| **RAG embeddings (resident)** | nomic-embed Q4 | **Qwen3-Embedding-0.6B** (keep) | Q8_0 (~0.7 GB) | ~0.7 GB | n/a (single-pass) | Yes | High (4B rejected — see §3) |
| **RAG reranker (resident)** | bge-reranker-v2-m3 Q4 | **Qwen3-Reranker-0.6B** | Q8_0 (~0.7 GB) | ~0.7 GB | n/a | Yes | High |
| **Vision / VLM (hot-swap)** | None (research: VL-8B) | **Qwen3-VL-30B-A3B-Instruct** + mmproj | Q4_K_M (~17.5 GB) | ~22 GB @ 16–24K | ~100–116 text | **XT: NO** (use VL-8B Q6) | High (caveat: Vulkan vision path) |

**Resident set total:** embed (0.7) + rerank (0.7) + router (1.4) + FIM (2.5) ≈ **5.3 GB**, leaving ~18.7 GB for the hot-swap occupant on the XTX. This is the single most consequential layout decision — see §3 FIM/router.

---

## 2. The Headline Change: Matrix Cores + 24 GB

The 6900 XT's RDNA2 silicon had **no cooperative-matrix (coopmat) units**. On llama.cpp Vulkan that forced the entire 2026 **GatedDeltaNet (GDN) / hybrid-SSM generation** (Qwen3.5, Qwen3.6, Qwen3-Next) into CPU fallback — which on RDNA2 produced **garbage output**, not just slow output. The gfx1100's **WMMA / KHR_coopmat** units change this categorically. Four distinct things unlock:

### (a) The GatedDeltaNet generation becomes runnable — and these are the new winners

The GDN Vulkan kernel is **merged and verified on RDNA3**, with hardware-specific evidence:

- **PR #20334** added `GGML_OP_GATED_DELTA_NET` (the recurrence op for Qwen3.5/3.6/Qwen3-Next), merged 2026-03-12 by 0cc4m.
- **PR #20377 / commit bf13638** added the chunked VK_KHR_cooperative_matrix output path.
- **Critical RDNA3 evidence:** a tester fixed **two RDNA3-specific shader bugs** (a shared-memory race + a missing `memoryBarrierBuffer`) and got coopmat-chunked GDN producing **CORRECT, lossless output** on an **RX 7800 XT (gfx1101, RADV NAVI32, wave64)**: 238 tok/s PP / 21.4 tok/s TG running Qwen3.5-27B IQ3_M with TQ3_0 KV at **200K context**. The 7900 XTX (gfx1100) is the same RDNA3 family/wave64/KHR_coopmat class.

This makes **Qwen3.6-27B (dense GDN hybrid)** the new winner for both the deep-reasoning slot and the frontier-coder slot, and **Qwen3.5-27B / Qwen3.6-35B-A3B** the contenders for general chat. **One honest caveat the verdicts flagged repeatedly:** the direct, named **gfx1100** bench is *inferred* from gfx1101 (same ISA), not yet published. So GDN picks carry `vulkanRdna3Confirmed = pending direct gfx1100 verification` — you **MUST** pin a post-March-2026 llama.cpp build (b8317+, ideally April-2026+ with the chunked-coopmat fixes) and run a sanity-gen + short perplexity check on `bigboi-jms-01` before trusting any GDN model in prod. An old llama-swap image will silently emit garbage on RDNA3.

### (b) 32B dense at Q4 now fits

Qwen3-32B Q4_K_M weights = **19.76–19.8 GB** (confirmed file size). This **could not load on 16 GB at any useful quant**. On the XTX it fits — but the verdict correction is load-bearing: at ~22 GB peak it is **context-starved to ~16–24K**, not the ≥32K the slot wants, and **does not fit the 20 GB XT at all** at Q4. It is the *deploy-day safe fallback* (zero GDN-build risk), not the headline reasoning pick.

### (c) Higher quant on the 30B MoEs (Q3 → Q4/Q5)

The 16 GB card forced **Q3_K_S** on Qwen3-Coder-30B-A3B and Qwen3-30B-A3B-Thinking — measurably degraded. The 24 GB card runs them at honest **Q4_K_M**. Note the verdict correction here too: the candidate research proposed **Q5_K_M** for the coder on the XTX, but the adversarial recompute showed Q5_K_M (~21.7 GB weights) leaves only ~0.8 GB for KV → fits only at ~4–8K ctx, defeating the agentic-coding ≥32K requirement. **Q4_K_M is the corrected XTX pick** (MoE is exceptionally quant-tolerant — only ~0.15 PPL Q4→Q8, so this costs almost nothing).

### (d) ~2x dense decode from bandwidth

960 GB/s vs the 6900 XT's 512 GB/s roughly doubles dense decode throughput. **Important nuance the verdicts caught:** this 2x applies to **dense/standard-attention** models. It does **NOT** apply to **GDN decode**, which is **recurrence-bound** (autoregressive op uses ~2 workgroups, leaves ~94 of 96 CUs idle), benching ~21 tok/s regardless of bandwidth. So GDN models are *quality/context* wins, not *speed* wins.

---

## 3. Per-Category Deep Dive

### Agentic coder (primary — operator's #1) — see §4 for extra depth

- **Top pick:** **Qwen3-Coder-30B-A3B-Instruct** — `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` (imatrix, 1.9M dl, Apache-2.0). Arch `qwen3_moe` (standard MoE + GQA, **NOT** GDN → zero coopmat risk on gfx1100).
- **Quant (verdict-corrected):** **XTX = Q4_K_M (~18.6 GB)** → ~20.5 GB total at 32K q8_0 KV, headroom toward 64K. (Candidate research's Q5_K_M is over-budget — rejected.) **XT = Q4_K_S (~17.5 GB) or IQ4_XS (~16.7 GB)** — Q4_K_M (~18.6 GB) + 1.3 GB resident leaves nothing for KV, so it does **not** fit the XT cleanly.
- **Why it wins on RDNA3/24 GB:** full GPU offload (no CPU-MoE spill), 3.3B active → ~50–70 tok/s decode, native tool-call format for Cline/Claude Code/OpenHands/Qwen Code, 256K native ctx, SWE-bench Verified 50.3%.
- **Runner-up:** **Devstral-Small-2507** (24B dense, `bartowski/mistralai_Devstral-Small-2507-GGUF`, Q4_K_M ~14.3 GB) — the materially *safer* primary: fully GPU-resident with huge ctx headroom, plain attention (zero arch risk), agent-scaffold-tuned. The verdict explicitly calls it "the materially safer primary local coder for THIS hardware." Cross-family hedge against Qwen.
- **VRAM math:** XTX Q4_K_M 18.6 + ~1.6 KV(32K) + ~1.3 buffers ≈ **21.5 GB / 22 budget** ✓. XT Q4_K_S 17.5 + KV + buffers ≈ **19.5 GB / 18 budget** ✗ at 32K → drop ctx to 16–24K or use IQ4_XS.
- **Delta vs 16 GB:** jumps from Qwen2.5-Coder-7B-dense / Q3-crippled-30B to a **clean Q4_K_M 30B-A3B** at usable context — the largest SWE-bench + instruction-following step the upgrade buys on the top-priority slot.

### Frontier GatedDeltaNet coder (NEW slot)

- **Top pick:** **Qwen3.6-27B** (dense GDN+GatedAttention hybrid) — `unsloth/Qwen3.6-27B-GGUF`. Confirmed file sizes: Q4_K_M **16.8 GB**, UD-Q4_K_XL **17.6 GB**. Apache-2.0, arch `qwen3_5`, 64 layers (16×(3× GDN→FFN + 1× GatedAttn→FFN)).
- **Why it wins:** **SWE-bench Verified 77.2** (beats its own 397B-A17B MoE at 76.2), Terminal-Bench 2.0 59.3 (= Claude Opus 4.5 class), within ~4 pts of Opus 4.5 on SWE-bench. The GDN hybrid's **tiny KV** (~64 MB/1K vs ~256 MB/1K dense) means 64–128K context fits on a single 24 GB card — impossible for a same-VRAM dense 32B.
- **GDN kernel evidence:** PR #20334 + #20377/bf13638 merged; lossless on gfx1101 RDNA3. `vulkanRdna3Confirmed = false` *pending direct gfx1100 bench* — the recurrence kernel is a plain compute shader (not a coopmat matmul), so "coopmat-benched on RDNA3" doesn't directly substantiate the GDN op on gfx1100. **Treat as a swap-in experiment**, validate output correctness before trusting.
- **Runner-up:** **Qwen3.6-35B-A3B** (GDN MoE) at **IQ3_M (~15–16 GB)** — verdict = **confirmed**, XTX-only. Pick only if interactive TG (3B active → ~22–26 tok/s) outranks peak coding quality (SWE-bench 73.4 < 27B's 77.2). Does **not** fit XT at Q4; IQ3_XXS (13.2 GB) only.
- **VRAM math:** XTX UD-Q4_K_XL 17.6 + ~1.0 KV(32K, tiny GDN cache) + 1.3 resident + ~1.2 buffers ≈ **21.1 GB / 22** ✓ (even 64K ≈ 21.4 GB ✓). XT: 16.8 + 1.3 + KV + buffers ≈ **20.1 GB / 18** ✗ → Q4_K_S or evict resident embed/rerank during heavy use.
- **Delta vs 16 GB:** this slot was **architecturally impossible** on RDNA2. Net-new frontier capability.
- **Real wart:** GDN decode ~12–18 tok/s (dense 27B) — slow for interactive agent loops; and **long-context prefill is the GDN weak spot** (autoregressive kernel doesn't scale with CU count). Bench p16384/p32768 before relying on it for 100K+ repo prompts.

### FIM / inline autocomplete

- **Top pick:** **Qwen2.5-Coder-3B (BASE, not Instruct)** — `bartowski/Qwen2.5-Coder-3B-GGUF` or `ggml-org/Qwen2.5-Coder-3B-Q8_0-GGUF`. **Promoted to RESIDENT.** Verdict = **confirmed, high**.
- **Why it wins:** latency-bound slot; plain `qwen2` dense (runs on the *old* RDNA2 card already → gfx1100 is a strict superset). 24 GB lets it go **resident** (~3.2 GB at Q6_K + 16K KV), so autocomplete **never swaps** — the single biggest UX win. Also steps Q4→Q6_K for cleaner infills, free.
- **Quant:** **Q6_K (~2.5 GB)**, serve via llama-server `/infill` with `qwenMultifileFimTemplate` (`<|fim_prefix/suffix/middle|>`, auto-detected by PR #9798).
- **Runner-up:** **Qwen2.5-Coder-1.5B (base) Q8_0** (~1.7 GB) — absolute latency floor (~150–200 tok/s), only if sub-200ms is a hard requirement.
- **Delta vs 16 GB:** hot-swap-with-load-penalty → **always-resident, always-instant**, at higher quant. **Do NOT** chase a GDN/MoE model here — load time + routing kills the typing loop; GDN's long-ctx-prefill advantage is never exercised by FIM.
- Expected ~90–130 tok/s, sub-100ms prefill on short windows.

### General instruct chat (default Open WebUI)

- **Top pick:** **Qwen3.5-27B** (GDN hybrid, run **non-thinking**) — `unsloth/Qwen3.5-27B-GGUF`. Verdict = **caveat, high** (GGUF + benchmarks confirmed; arch is GDN hybrid, not "dense" as the candidate mislabeled).
- **Quant:** **XTX Q5_K_M** (~18–19 GB weights + small GDN KV + 1.3 resident ≈ 20–21 GB, tight, run 24–32K ctx); for 64K+ drop to Q4_K_M. **XT: Q5_K_M does NOT fit → Q4_K_M only.**
- **Why:** IFEval/MultiChallenge/BFCL best-in-class instruction following, 262K native ctx, ties GPT-5-mini on SWE-bench 72.4. GDN tiny-KV holds long context cheaply.
- **HARD requirements (verdict caveats):** (1) **non-thinking mode** — Qwen3.5 dropped the `/nothink` soft switch and thinks by default; set `enable_thinking:false` or chat latency is wrecked. (2) **Pin post-March-2026 llama.cpp** or GDN falls back to CPU (~12 tok/s) / garbage. (3) **AVOID IQ-quants on RDNA3 Vulkan** — IQ4_XS crashes llama-server during batch PP (issue #20916); stick to K-quants. (4) TG is recurrence-bound ~21 tok/s — the "2x decode" does **not** apply.
- **Runner-up (safe fallback):** **Gemma-3-12B-it Q5_K_M** (~8.4 GB) — `unsloth/gemma-3-12b-it-GGUF`. Verdict = **confirmed**. Pure-attention, no GDN build trap, no thinking trap. **Two real caveats:** use **f16 KV not q8_0** (Gemma3 q8_0 KV bug pushes compute to CPU); model is **gated on HF** (init container needs token, or use `bartowski`/`ggml-org` ungated mirror). Under-uses 24 GB but bulletproof.
- **Delta vs 16 GB:** Qwen3-4B Q4 → 27B-class GDN at Q5 with 262K ctx — generational jump.

### Deep reasoning / heavy local tier

- **Top pick:** **Qwen3.6-27B** (same model as the frontier-coder slot — it doubles as the best reasoning model that fits) — UD-Q4_K_XL (~17.6 GB) or bartowski Q4_K_M (16.8 GB). Verdict = **caveat, high** (all claims check out; GDN-on-RDNA3 path recently stabilized, not battle-worn). AIME26 94.1, GPQA-D 87.8.
- **VRAM math (verdict recompute):** 16.8 weights + ~1.0 KV(32K) + 1.3 resident + ~1.2 buffers ≈ **20.3 GB / 22** ✓; 64K ≈ 21.4 GB ✓. Only 16 of 64 layers carry growing KV (the GatedAttn quarter), the 48 GDN layers hold fixed recurrent state — this is *why* it runs long context where a dense 32B cannot. **XT marginal** (~20.1 GB at 32K) → cap ctx 16–32K or evict resident.
- **Runner-up (deploy-day safe):** **Qwen3-32B** classic dense — `bartowski/Qwen_Qwen3-32B-GGUF` Q4_K_M (19.76 GB). Verdict = **caveat, high**. Zero GDN risk (mature Vulkan/coopmat path). But **context-starved to ~16–24K on XTX** (RTX-3090 24 GB recipe confirms ~22 GB peak, Q5 does NOT fit), and **HARD FAIL on the 20 GB XT** (weights alone ~20 GB → must drop to UD-Q3_K_XL ~16.4 GB / IQ3_XS ~17.7 GB). Use while validating the GDN build.
- **Universal fallback (both cards):** **gpt-oss-20b** MXFP4 (~13 GB) — fits XTX and XT with huge ctx headroom, fast (3.6B active), reasoning_effort control. Under-uses 24 GB but is the safe high-ctx tier.
- **Throughput:** GDN ~25–40 tok/s plain on the dGPU; community MTP build shows **47–75 tok/s** on Qwen3.6-27B on a 7900 XTX — use `unsloth/Qwen3.6-27B-MTP-GGUF` for speculative decode if llama-swap supports the MTP draft path.
- **Delta vs 16 GB:** Qwen3-14B Q4 @ 8K (starved) → frontier 27B GDN at 32–64K, plus 32B-dense now physically possible.

### Fast routing / classification (front-door)

- **Top pick:** **KEEP Qwen3-1.7B Q5_K_M** (~1.4 GB) — `Qwen/Qwen3-1.7B-GGUF`. **Promote to RESIDENT.** Verdict = **confirmed, high**.
- **Why the upgrade does NOT change the pick:** routing is speed/footprint-bound, not smarts-bound. The *only* change: 24 GB lets it stay **permanently resident at zero marginal cost** (on 16 GB it competed for the hot-swap model's KV budget). Run **non-thinking** (`/no_think`), ctx 8192. ~120–150 tok/s → sub-300ms classification.
- **Runner-up:** **Qwen3-0.6B Q8_0** (~0.8 GB) — latency floor only if router accuracy is non-critical; weaker intent detection.
- **Do NOT** swap to **Qwen3.5-2B (GDN)** here: GDN TG ~20 tok/s is 5–7x slower than dense 1.7B for short-message routing. Wrong tool.
- Optional optimization the verdict flags: with free VRAM you *could* promote the already-deployed Qwen3-4B-2507 as a stronger front-door at near-zero latency cost — but "keep 1.7B" is the low-risk default.

### RAG embeddings (resident)

- **Recommended pick (verdict-corrected):** **KEEP Qwen3-Embedding-0.6B Q8_0** (~0.7 GB) — `Qwen/Qwen3-Embedding-0.6B-GGUF`. Verdict = **confirmed**.
- **The 4B was REJECTED by the adversarial verdict** (verdict = **caveat**, recommends *against* it). The candidate research's top pick was Qwen3-Embedding-**4B** Q8_0 (~4.5 GB resident) for +5 MTEB. But: as an **always-on resident** model, 4B alone is ~3.5x the entire stated embed+rerank budget, shrinking the top-priority coding hot-swap window from ~22 → ~18 GB (XTX) / ~18 → ~14 GB (XT). The verdict's judgment: "the Q8_0-resident-4B pick optimizes the wrong axis" on a single-GPU box where autonomous coding is #1. Embedding quality is near-saturated at 0.6B for homelab RAG.
  - **If you do want 4B:** run it **Q4_K_M (~2.4 GB)** not Q8_0, or treat embedding as a hot-swapped (not resident) call. But the conservative 0.6B is the recommendation.
- `--embeddings --pooling last` (Qwen3-Embedding REQUIRES last-token pooling — wrong pooling silently tanks recall). Beats deployed nomic-embed (MTEB ~62 → 64.33, stronger code retrieval). 1024-dim keeps pgvector lean.
- **No XT delta** — sub-1 GB either way.

### RAG reranking / cross-encoder (resident)

- **Top pick:** **Qwen3-Reranker-0.6B Q8_0** (~0.7 GB) — `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` (maintainer-blessed; **avoid older community GGUFs** mis-converted per issue #16407). Verdict = **confirmed, high**.
- **Why:** best LOCAL reranker for a **code-heavy** RAG — CoIR code-retrieval **65.18 vs bge's 36.28** (huge edge for an autonomous-coding stack). Pairs with Qwen3-Embedding family. `--reranking`, default KV (do NOT pass `-ctk/-ctv q4_0` — quantized KV corrupts relevance scores, issue #16407). Validate the rerank endpoint returns scores at deploy (causal-LM yes/no head vs seq-cls).
- **Runner-up / A-B baseline:** **bge-reranker-v2-m3 Q8_0** — `gpustack/bge-reranker-v2-m3-GGUF`. Verdict = **confirmed**. Most battle-tested llama.cpp rerank path (PR #9510), wins on multilingual (MIRACL 69 vs 58), loses badly on code. Keep as fallback.
- **The 16 GB → 24 GB jump does NOT improve this slot** — a 0.6B reranker is sub-1 GB on any card. Real upgrade vs the deployed bge Q4 is (1) Q4→Q8 precision and (2) Qwen3's code edge.
- Newer 2026 rerankers (gte-reranker-modernbert, jina-v3, mxbai-v2) are **DISQUALIFIED** — their archs are unsupported by llama.cpp's reranker converter.

### Vision / multimodal (VLM, hot-swap)

- **Top pick (XTX):** **Qwen3-VL-30B-A3B-Instruct Q4_K_M** (~17.5 GB) + F16 mmproj — `unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF` (arch `qwen3_vl_moe`). Verdict = **caveat, high**.
- **Why it wins on 24 GB:** real-hardware proof on this exact GPU (issue #16895, RX 7900 XTX / RADV NAVI31 / gfx1100): Q4_K_M @ 32K ctx, `-np 2`, used 22,119 MiB *with mmproj* — 49/49 layers offloaded, **~100–116 tok/s TG, ~730–1470 tok/s PP**. 30B-total knowledge, 3.3B active, best local doc/chart/OCR + bbox grounding for n8n/MCP UI-screenshot flows. PR #16780 added qwen3vl dense+MoE.
- **LOAD-BEARING CAVEAT (the reason it's caveat not confirmed):** the **Vulkan vision/mmproj path on RDNA3 is the documented weak spot**, not the text path. Image-encode is **~20x slower on Vulkan than ROCm** (issue #17012: ~35s vs ~1.5s); GPU util caps ~80%; issue #20081 reports degraded vision output on some images vs CUDA. Operational guidance: tune **`--image-min-tokens 1024`** for OCR/bbox accuracy; pin a build with PR #16956 (Q4_K_M garbage-output fix); if large-ctx + `-fa on` hits `vk::DeviceLostError`, run `-fa off` or set `amdgpu.lockup_timeout`. **This is the #1 slot to flag for a ROCm/Talos re-bench** (see §6) — image-encode is exactly where ROCm pays off.
- **Runner-up + mandatory XT primary:** **Qwen3-VL-8B-Instruct** — `Qwen/Qwen3-VL-8B-Instruct-GGUF`. Verdict = **caveat** (`vulkanRdna3Confirmed=false` because the *vision* path isn't cleanly verified on gfx1100 RADV, even though text is). The 30B is marginal/over-budget on the 20 GB XT → 8B is the only sane XT primary. Bump LLM to **Q8_0 (~8.7 GB)** given the headroom; keep **mmproj at F16** (Qwen recommends it for vision accuracy). **Eyeball vision output correctness on `bigboi-jms-01` before committing** — the text path is verified-clean, the multimodal path is not.
- **Consolidation option:** Gemma-3-12B-it doubles as chat + vision (most mature mmproj Vulkan path) if you want one slot for both, at the cost of weaker doc/chart/grounding.

---

## 4. Autonomous-Coding Slot — Extra Depth (operator's #1 priority)

This is three distinct sub-workloads, and 24 GB lets you cover all three well:

**Agentic / multi-file / tool-use (the daily driver):** **Qwen3-Coder-30B-A3B-Instruct Q4_K_M** is the deploy pick. It is a *standard* Qwen3-MoE (dense attention + sparse FFN, **not** GDN) — so it runs on the rock-solid llama.cpp Vulkan path with zero coopmat risk, full GPU offload, ~50–70 tok/s decode (3B active), native tool-call format wired for Cline / Claude Code / OpenHands / Qwen Code. This is the right default: comfortably interactive for IDE agent loops and n8n/MCP tool-use.

**Does 24 GB let a bigger/newer/higher-quant coder win?**
- **Higher quant: yes** — Q3_K_S (forced on 16 GB) → Q4_K_M. Clean, measurable SWE-bench + instruction-following gain.
- **A GDN coder (Qwen3.6-Coder class): partially.** The dense **Qwen3.6-27B** (SWE-bench 77.2) *does* fit at Q4_K_M and is a strictly stronger coding model than the 30B-A3B (50.3) — it's filed under the frontier-coder slot and is a legitimate swap-in **once the GDN build is validated on gfx1100**. The decode is slower (~12–18 tok/s dense), so it's better for deep refactor/reasoning passes than tight interactive loops.
- **The 80B GDN coder (Qwen3-Coder-Next / Qwen3-Next-80B-A3B): NO — does not fit.** This is the model with frontier agentic scores (~71% SWE-bench, near Claude Sonnet 4.5) and a CONFIRMED-working RDNA3 GDN Vulkan kernel. But Q4_K_M is **~45–46 GB** — roughly half the experts **must** spill to system RAM via `--cpu-moe`. Decode then becomes **host-RAM/PCIe-bound, not VRAM-bound** — the 960 GB/s advantage is wasted. The candidate research's ~30 tok/s claim is **unverified for this hardware** (verdict's "single biggest hole"): every fast number cited came from machines with the weights fully resident (Strix Halo UMA, 96 GB datacenter GPU) or fast DDR5; on a homelab PCIe4 + (unstated DDR4/DDR5) box, realistic decode is **15–30 tok/s and highly RAM-dependent**. **Verdict:** deploy only if you accept it as a hybrid CPU-MoE "maximum-capability, accept-the-speed-hit" option — it is the upgrade path the moment a **2nd GPU or a 48 GB card** lands, *not* a 24 GB single-GPU default. (Note: "Qwen3-Coder-Next" as a first-party Qwen repo could not be confirmed; the verified base is `Qwen/Qwen3-Next-80B-A3B-Instruct` — community coder-tuned variants circulate in the PR threads.)

**Is 32B-dense-coder viable?** Not as a *coder* specifically — there's no compelling 32B dense coder that beats the 30B-A3B MoE or the 27B GDN here, and a dense 32B is context-starved at Q4 (§3 deep-reasoning). Stick with the 30B-A3B MoE (interactive) + Qwen3.6-27B (heavy, GDN-validated).

**FIM is a separate slot** — keep it the resident Qwen2.5-Coder-3B base (§3); never put a big coder there.

**Recommended autonomous-coding layout:** 30B-A3B Q4_K_M as the hot-swap default coder; Qwen3.6-27B as a validated swap-in for hard refactors; Devstral-Small-2507 as the safe cross-family fallback; Qwen2.5-Coder-3B resident for FIM.

---

## 5. XTX (24 GB) vs XT (20 GB) — Buying Guidance

The 4 GB difference changes a pick in exactly these slots:

| Slot | Changes on XT? | What you lose |
|------|----------------|---------------|
| Agentic coder (30B-A3B) | **Yes** | XTX runs Q4_K_M @ 32K; XT must drop to Q4_K_S/IQ4_XS and cap ctx ~16–24K |
| Frontier GDN coder (Qwen3.6-27B) | **Marginal** | XT ~20.1 GB at 32K → Q4_K_S or evict resident embed/rerank under load |
| General chat (Qwen3.5-27B) | **Yes** | XTX Q5_K_M; XT Q4_K_M only |
| Deep reasoning — **Qwen3-32B dense** | **HARD FAIL** | Weights alone ~20 GB; XT cannot run it at Q4 — must use UD-Q3_K_XL/IQ3 or run the 27B GDN / gpt-oss-20b instead |
| Vision — **Qwen3-VL-30B-A3B** | **HARD FAIL** | 30B marginal/over on 20 GB; XT must run Qwen3-VL-8B Q6/Q8 |
| FIM, router, embed, rerank, gpt-oss-20b | No | All sub-13 GB; identical on both |

**Is the XTX worth it for this workload? Yes, clearly.** The 4 GB is the difference between (a) running the top-priority agentic coder at honest Q4_K_M with 32K context vs a starved IQ4_XS, (b) the deep-reasoning slot having a 32B-dense safe-fallback *at all*, and (c) the best local VLM (30B-A3B) being usable vs falling back to the 8B. Three of the highest-value slots — coding, reasoning fallback, vision — degrade on the XT. For a single-GPU box where autonomous coding is #1, the XTX is the right buy; the XT only makes sense if it's materially cheaper and you accept the 8B VLM + GDN-only reasoning path.

---

## 6. ROCm / vLLM Revisit

RDNA3/gfx1100 is **officially ROCm-supported** (unlike the dead RDNA2 path), so this deserves an honest re-examination — but the answer for **most** slots is "stay on Vulkan."

- **The general performance case AGAINST ROCm here:** on the 7900 XTX, llama.cpp **Vulkan (RADV, wave64) is consistently ~20% FASTER than ROCm/HIP for token generation** and more stable at large context (issue #20934). ROCm also crashes at ≥32K ctx on RDNA3 in multiple reports. For chat, reasoning, coding, embeddings, reranking, routing, FIM — **there is no decode win to chase**, and the Talos immutable-rootfs / in-tree-amdgpu / no-DKMS ABI blocker stands. **Verdict: Vulkan/GGUF remains committed.**
- **The ONE place ROCm/vLLM would be a real win — flag for re-bench:** the **VLM vision/mmproj encoder**. Image-encode on Vulkan is **~20x slower than ROCm** (issue #17012, ~35s vs ~1.5s) and has open correctness bugs on RADV (#20081). If Qwen3-VL vision latency/accuracy on Vulkan proves unacceptable, **ROCm-in-container on Talos is the lever worth re-benching** — the CUDA/ROCm vision path is the verified-correct one. **Do not assume vLLM works on Talos** — it needs a from-scratch ABI re-bench (the prior failure was on RDNA2; RDNA3 changes the support story but not the Talos immutable-rootfs constraint). Treat as "revisit/spike", not a plan.
- **GDN models:** a ROCm/HIP fused GDN kernel exists (issue #20354) and would likely beat Vulkan, but GDN's HIP path currently *underperforms* on RDNA and the Talos blocker applies — keep Vulkan, re-bench only if a vision ROCm spike already proves the Talos ABI works.

---

## 7. Concrete Shopping / Config List

Resident set (always loaded, llama-swap `always-on` group):

```
# Embeddings — Qwen/Qwen3-Embedding-0.6B-GGUF  (Q8_0, ~0.7GB)
llama-server -hf Qwen/Qwen3-Embedding-0.6B-GGUF:Q8_0 \
  --embeddings --pooling last -ub 8192 -ngl 99 -c 8192
# (Optional upgrade: Qwen/Qwen3-Embedding-4B-GGUF at Q4_K_M ~2.4GB — NOT Q8_0 resident)

# Reranker — ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF  (~0.7GB)  [avoid mis-converted community GGUFs, issue #16407]
llama-server -hf ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF -c 4096 -ngl 99 --reranking -np 8   # default KV — do NOT quantize KV

# Router — Qwen/Qwen3-1.7B-GGUF  (Q5_K_M, ~1.4GB), non-thinking
llama-server -hf Qwen/Qwen3-1.7B-GGUF:Q5_K_M -c 8192 -ngl 99    # pass /no_think in the routing prompt

# FIM — bartowski/Qwen2.5-Coder-3B-GGUF  (BASE, Q6_K, ~2.5GB)
llama-server -hf bartowski/Qwen2.5-Coder-3B-GGUF:Q6_K \
  -c 16384 -ngl 99 -fa --infill  # KV q8_0; FIM tokens auto-detected (PR #9798)
```

Hot-swap occupants (`chat` group, exclusive — one at a time):

```
# Agentic coder (DEFAULT) — unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF
#   XTX: Q4_K_M (~18.6GB) @ 32K   |   XT: Q4_K_S (~17.5GB) or IQ4_XS @ 16-24K
-ngl 99 -fa 1 -b 512 -c 32768 -ctk q8_0 -ctv q8_0   # Mesa 25.3+ for correct KHR_coopmat

# Frontier coder / deep reasoning — unsloth/Qwen3.6-27B-GGUF
#   XTX: UD-Q4_K_XL (~17.6GB) @ 32-64K | XT: Q4_K_M (16.8GB) @ 16-32K
#   MTP variant for spec-decode: unsloth/Qwen3.6-27B-MTP-GGUF
-ngl 99 -fa 1 -b 512 -c 65536 -ctk q8_0 -ctv q8_0
#   *** REQUIRES llama.cpp build >= April-2026 (post PR #20334 + #20377 + RDNA3 coopmat fixes).
#   *** Run a sanity-gen + short perplexity check on gfx1100 before trusting (GDN path not directly gfx1100-benched).

# General chat — unsloth/Qwen3.5-27B-GGUF   (XTX Q5_K_M / XT Q4_K_M), NON-THINKING
-ngl 99 -fa 1 -b 512 -c 32768 -ctk q8_0 -ctv q8_0   # enable_thinking:false; AVOID IQ-quants (crash #20916); K-quants only
#   Safe fallback: unsloth/gemma-3-12b-it-GGUF Q5_K_M  — use f16 KV (NOT q8_0, Gemma3 KV bug); gated → use bartowski/ggml-org mirror

# Deep-reasoning safe fallback (no GDN risk) — bartowski/Qwen_Qwen3-32B-GGUF Q4_K_M (~19.8GB)
#   XTX ONLY, ctx 16-24K.  XT: does NOT fit at Q4 → UD-Q3_K_XL.
-ngl 99 -fa 1 -b 512 -c 16384 -ctk q8_0 -ctv q8_0
# Universal high-ctx fallback (both cards): ggml-org gpt-oss-20b MXFP4 (~13GB)

# Vision VLM — unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF Q4_K_M + mmproj-F16   (XTX)
llama-server -ngl 999 --mmproj <mmproj-F16.gguf> --jinja \
  -c 16384 -ctk q8_0 -ctv q8_0 --image-min-tokens 1024   # -fa off if DeviceLost at large ctx
#   XT: Qwen/Qwen3-VL-8B-Instruct-GGUF Q8_0 + mmproj-F16  (30B is marginal on 20GB)
#   *** Vision/mmproj Vulkan path is the weak spot — eyeball OCR/bbox correctness before committing; ROCm re-bench candidate.
```

**Global engine requirements:** Mesa 25.3+ (correct KHR_coopmat), llama.cpp Vulkan build pinned **≥ April-2026 master** for any GDN model, RADV (not AMDVLK). Verify the llama-swap image build date before deploying any `qwen3_5` / `qwen3_5moe` / `qwen3next` arch model — an old image silently corrupts GDN output on RDNA3.

---

**Bottom line:** The upgrade's biggest wins land exactly on the #1 priority — autonomous coding gets a clean Q4_K_M 30B-A3B (no more Q3), plus an unlocked frontier GDN coder (Qwen3.6-27B, SWE-bench 77.2) the old card couldn't run at all. The GDN generation is the headline unlock but carries a build-pin + gfx1100-validation requirement (kernel proven on gfx1101, inferred on gfx1100). Two candidate-research picks were corrected by the adversarial verdicts and should NOT be deployed as proposed: the agentic-coder **Q5_K_M → Q4_K_M** (over-budget), and the embeddings **4B-resident → keep 0.6B** (steals the coding hot-swap budget). Vision is the one slot where ROCm-on-Talos is worth a real re-bench; everything else stays Vulkan/GGUF.
