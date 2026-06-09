# Local Model Stack Recommendation — bigboi-jms-01 (RX 6900 XT / Navi 21 / gfx1030, llama.cpp Vulkan)

**Date:** 2026-06-08 · **Engine:** llama.cpp Vulkan + llama-swap, GGUF only · **VRAM:** 16 GiB, ~15 GiB usable for a hot-swapped chat/coder model after the resident embed+rerank pair · **ROCm:** non-functional on this Talos node (no vLLM, no ROCm-only paths)

> Produced by a multi-agent research workflow (8 slot categories × researcher + adversarial verifier against the HuggingFace Hub, 26 agents). Adversarial verification corrected several errors in the first-pass research — flagged inline as CAVEAT/REJECTED.

A hard, recurring theme runs through every verdict: **this is an RDNA2 card with NO cooperative-matrix cores.** That single fact disqualifies the entire 2026 "Gated DeltaNet" generation (Qwen3.5, Qwen3.6) — their Vulkan kernels are benched only on RDNA3/RDNA3.5 with `KHR_coopmat`, and on gfx1030 they either have no Vulkan kernel at all or risk CPU-fallback state corruption. The winning picks are deliberately one generation "behind" the leaderboard because they use **pure-attention `qwen3moe` / standard dense / native-MXFP4** architectures that are *verified* to run fully GPU-offloaded on this exact silicon.

---

## 1. TL;DR — Recommended Slot Map

| Slot | Currently deployed | Recommended model | Action | Quant / est. VRAM | Est. decode tok/s | Confidence |
|------|-------------------|-------------------|--------|-------------------|-------------------|------------|
| **Agentic coder** (flagship) | *(none — gap)* coder-large was Qwen2.5-Coder-7B | **Qwen3-Coder-30B-A3B-Instruct** | **ADD** | Q3_K_S ~13.3 GB (+KV → ~15) | ~80–120 (MoE 3B-active) | High (CAVEAT: use Q3_K_S, **not** IQ3_K) |
| **Coder autocomplete / FIM** | Qwen2.5-Coder-3B-**Instruct** Q4_K_M | **Qwen2.5-Coder-3B (BASE)** | **KEEP** (switch Instruct→Base, Q4→Q5) | Q5_K_M ~2.2 GB | ~250–269 | High (CONFIRMED) |
| **General chat / local-balanced** | Qwen3-4B-Instruct-2507 Q4_K_M | **Qwen3-4B-Instruct-2507** | **KEEP** | Q4_K_M ~4.5 GB | ~90–130 | High (CONFIRMED) |
| **Deep reasoning** | Qwen3-14B Q4_K_M, ctx 8192 | **Qwen3-30B-A3B-Thinking-2507** (+ GPT-OSS-20B as co-occupant) | **REPLACE** | Q3_K_S ~12.85 GB / MXFP4 ~11.3 GB | ~80–110 / ~35–110 | High (CAVEAT on both: VRAM/flags) |
| **Fast routing / classification** | Qwen3-1.7B Q5_K_M | **Qwen3-1.7B** | **KEEP** | Q5_K_M ~1.4 GB resident-able | ~150–250 | High (CAVEAT: landscape only) |
| **RAG embeddings** (resident) | nomic-embed-text-v1.5 Q4_K_M | **Qwen3-Embedding-0.6B** | **REPLACE** | Q8_0 ~0.64 GB | prefill-only (instant) | High (CAVEAT: wiring) |
| **RAG reranker** (resident) | bge-reranker-v2-m3 Q4_K_M | **Qwen3-Reranker-0.6B** | **REPLACE** | Q8_0 ~0.64 GB | prefill-only (instant) | High (CONFIRMED) |
| **Vision / multimodal** (optional) | *(none)* | **Qwen3-VL-8B-Instruct** | **ADD (gated)** | Q4_K_M LM + F16 mmproj ~7.5 GB @32K | ~30–60 text; 3–10s/image | High pick, **CAVEAT: Mesa ≥26.0.5 gate** |

**Retire:** Qwen2.5-Coder-7B-Instruct (coder-large) and Qwen3-14B (reasoning) as *primary* slot occupants — both are superseded. Keep Qwen3-14B Q4_K_M configured as a documented dense safety floor only.

---

## 2. Per-Category Deep Dive

### 2.1 General Chat — KEEP Qwen3-4B-Instruct-2507 (CONFIRMED)

- **Use case:** Highest-volume slot — default Open WebUI driver, `local-balanced` alias, light tool-use, summarization.
- **Top pick:** `Qwen/Qwen3-4B-Instruct-2507`, GGUF `unsloth/Qwen3-4B-Instruct-2507-GGUF` (Q4_K_M present, 706K dl), also bartowski / lmstudio-community. Apache-2.0, arch `qwen3` (first-class Vulkan since May 2025).
- **Why it wins here:** Standard dense arch = flawless full-offload. The headline 2026 upgrade, **Qwen3.5-4B, is REJECTED**: it is Gated DeltaNet and the llama.cpp `GATED_DELTA_NET` op has **no Vulkan kernel** (PR #20455: *"Vulkan need another PR"*; users hit *"fused Gated Delta Net tensor assigned to device CPU"*). On `-ngl 99` Vulkan it spills to CPU and collapses. Gemma-3-4B-it fits and is Vulkan-clean but loses to Qwen3-4B on tool-use/MMLU-Pro (the homelab's priority). IBM Granite-4 had **no canonical GGUF found** — disqualified.
- **VRAM math:** Q4_K_M ~2.5 GB + q8_0 KV @32K ~1.1 GB + ~0.8 GB buffers ≈ **4.5 GB** of 15 GB. Wildly conservative — 100K+ ctx is reachable.
- **vs deployed:** Identical. The only *open* question (raised by the verifier, not blocking): with ~10 GB of unused headroom you could upsize this slot to an **8B-class** (Qwen3-8B / GLM-4-9B) at Q4 to raise the floor. Optional, not required.
- **Verdict:** CONFIRMED, high confidence. KEEP.
- **Optional ADD (not a replacement):** `Qwen3-30B-A3B-Instruct-2507` as a "smart default" swap-in for hard non-coding queries (MMLU-Pro 78.4 vs 67). **CAVEAT:** bartowski Q3_K_M is **14.08 GB** — counting weights only; with KV+buffers it does **not** comfortably reach 32K. Deploy **IQ3_XS/IQ3_M (~12.2–13 GB)** for KV headroom, or Q3_K_M capped at ~8K. GGUF confirmed (`unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF`, 849K dl).

### 2.2 Fast Routing / Classification — KEEP Qwen3-1.7B (CAVEAT: landscape only)

- **Use case:** Sub-second OWUI front-door router behind `local-fast` — intent classification, cheap structured extraction.
- **Top pick:** `Qwen/Qwen3-1.7B` Q5_K_M. GGUF abundantly confirmed including **`ggml-org/Qwen3-1.7B-GGUF`** (the llama.cpp team's own repo = guaranteed Vulkan support). Apache-2.0, dense `qwen3`.
- **Why it wins:** For a router, VRAM is irrelevant (~1.4 GB) — only routing accuracy, JSON/schema reliability, and load+decode latency matter. Qwen family dominates sub-3B structured-output (AscentCore 2026: Qwen2.5-1.5B ~95.7% JSON parse; **SmolLM2-1.7B fails at 4–26%** — so do NOT switch to SmolLM3 for this slot despite its strong tool-call benchmarks).
- **REJECTED alternative:** Qwen3.5-2B — newer and benchmark-strong, but **hybrid Gated DeltaNet + ships as `image-text-to-text`** (vision projector = dead weight for a text router). Re-evaluate only after a Vulkan GDN kernel merges AND a text-only variant ships.
- **Runner-up:** `Qwen3-0.6B` Q8_0 (CONFIRMED) — valid if swap-in latency ever bites; ~2.8x fewer params, `ggml-org/Qwen3-0.6B-GGUF` confirmed.
- **Two free optimizations:** (1) run in `/no_think` mode; (2) consider promoting the router to the **always-on group** (~1.4 GB resident is trivial) so swap-in latency vanishes.
- **Verdict:** CAVEAT (only because a newer generation exists but is disqualified). KEEP.

### 2.3 Coder Autocomplete / FIM — KEEP Qwen2.5-Coder-3B, but switch Instruct→BASE (CONFIRMED)

- **Use case:** Latency-bound inline FIM for Continue.dev — single-keystroke budget, tens-of-ms decode, fast swap-in.
- **Top pick:** `Qwen/Qwen2.5-Coder-3B` **(BASE, not Instruct)**, GGUF `bartowski/Qwen2.5-Coder-3B-GGUF` at **Q5_K_M**. The base build was pretrained with FIM special tokens (`<|fim_prefix|>`=151659, `<|fim_middle|>`=151660, `<|fim_suffix|>`=151661) and no chat post-training — exactly what Continue.dev's `tabAutocompleteModel` expects.
- **Why it wins here:** Nothing has superseded it at the sub-4B FIM tier in 2026. There is **no Qwen3-Coder sub-4B base** (smallest is 30B-A3B MoE) and the 4B Qwen3/Qwen3.5 chat models lack FIM tokens. Codestral 22B is FIM-accuracy SOTA (95.3%) but at Q4 ~14 GB it's a coder-large model, not a tens-of-ms engine — **disqualified for this slot.** arch `qwen2` is one of the most mature Vulkan paths — zero compat risk.
- **VRAM math:** Q5_K_M ~2.2 GB weights + q8_0 KV @32K ~0.64 GB + ~0.5 GB buffers ≈ **3.4 GB** — ~11 GB to spare.
- **vs deployed:** This is a *refinement* of the existing coder-small slot, not new capability. The two deltas: **Instruct→Base** (correct for raw infill — Instruct degrades infill and adds chat scaffolding) and **Q4→Q5** (fewer hallucinated identifiers, ~0.4 GB cost). **HARD CONFIG REQ:** llama-swap/Continue autocomplete role MUST be FIM-templated, not chat — a base model under a chat template emits garbage.
- **Runner-up:** `Qwen/Qwen2.5-Coder-1.5B` (BASE) Q5_K_M — Apache-2.0, `RachidAR/Qwen2.5-Coder-1.5B-Q5_K_M-GGUF`. **CAVEAT:** only adopt if an on-node benchmark proves the 3B is genuinely too slow; the premise is unproven and short FIM completions are dominated by TTFT, not 3B-vs-1.5B decode.
- **Verdict:** CONFIRMED, high confidence. KEEP (with Base + Q5 corrections).

### 2.4 RAG Embeddings (resident) — REPLACE nomic with Qwen3-Embedding-0.6B (CAVEAT: wiring)

- **Use case:** Always-on document/query embeddings for AnythingLLM, `local-embed`.
- **Top pick:** `Qwen/Qwen3-Embedding-0.6B` Q8_0. Official GGUF `Qwen/Qwen3-Embedding-0.6B-GGUF` (360.9K dl). Apache-2.0.
- **Why it wins:** Single highest-value, lowest-risk swap in the stack — same resident slot, materially better retrieval. **MTEB-Code 75.41 vs nomic's near-baseline code retrieval** (decisive for a coding-first stack), 32K ctx vs 8K, 1024 dims with MRL truncation, instruction-aware. Vulkan support landed in PR #15023 (Aug 2025).
- **VRAM math:** Q8_0 ~0.64 GB. **Correction:** this exceeds the old "~370 MB total" embed+rerank budget figure — the resident pair is now ~0.64 GB (embed) + ~0.64 GB (rerank) ≈ **<1.3 GB**, still trivial against 16 GB.
- **CAVEATS (operational, not blocking):** (1) launch via llama-swap with `--embeddings --pooling last`, not as a chat model, or you hit the "Invalid input batch" 500 (#14210); (2) use a current/re-quantized GGUF — earliest official files had broken pooling metadata; (3) Qwen3-Embedding uses **asymmetric query/document** embedding — AnythingLLM must send the query instruction prefix or retrieval quality drops below nomic.
- **Migration cost:** dims change 768→1024 and the model changes → **one-time full pgvector re-index** of the AnythingLLM store. Schedule it.
- **Runner-up:** `EmbeddingGemma-300M` Q8_0 (CAVEAT) — `ggml-org/embeddinggemma-300m-qat-q8_0-GGUF`, beats nomic, dedicated Vulkan arch (PR #15798). Only downside: **2K context ceiling** (fine for AnythingLLM's 1500/200 chunking). Pick this only if minimizing resident VRAM matters.
- **Do NOT:** run Qwen3-Embedding-4B resident — ~2.5 GB for only ~+5 MTEB steals from the hot-swap budget. Run on-demand if ever wanted.
- **Verdict:** CAVEAT, high confidence. REPLACE.

### 2.5 RAG Reranker (resident) — REPLACE bge with Qwen3-Reranker-0.6B (CONFIRMED)

- **Use case:** Always-on cross-encoder re-scoring top-k chunks, `local-rerank`.
- **Top pick:** `Qwen/Qwen3-Reranker-0.6B` Q8_0. Official **`ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`** (the llama.cpp org itself, 149.9K dl, ~639 MB, tagged `text-ranking`). Apache-2.0.
- **Why it wins:** Strictly better than the incumbent at the same 0.6B budget on every axis (arXiv:2506.05176): MTEB-R 65.80 vs 57.03, MMTEB-R 66.36 vs 58.36, MLDR 67.28 vs 59.51, FollowIR +5.41 vs ~0. **Decisive: MTEB-Code 73.42 vs 41.38** — a ~32-point gap. bge-v2-m3 is a known weak code reranker; this homelab is coding-first. 32K ctx vs 8K, instruction-aware.
- **VRAM math:** Q8_0 ~0.64 GB resident; a reranker is a single forward pass with no autoregressive KV → total footprint ~0.7–0.8 GB. Use Q8_0 not Q4 — quant noise directly hurts a precision-critical scoring head and the VRAM cost is negligible.
- **Engine:** serve via `--reranking --pooling rank`, route LiteLLM `local-rerank` to `/v1/rerank` (NOT chat completions). Throughput is prefill-only — same latency class as the incumbent (also 0.6B), so no regression for a large quality+code gain.
- **Runner-up / fallback:** keep `bge-reranker-v2-m3` Q8_0 (CONFIRMED) configured but commented out — `gpustack/bge-reranker-v2-m3-GGUF` is the llama-swap-wiki reference; PR #9510 was developed against this exact model.
- **Do NOT:** Qwen3-Reranker-4B resident (~2.5–4.5 GB breaks the tiny-resident design); BGE-Reranker-v2-Gemma (9B, inappropriate); mxbai-rerank (weak code, no vetted GGUF).
- **Verdict:** CONFIRMED, high confidence. REPLACE.

### 2.6 Vision / Multimodal (optional, gated) — ADD Qwen3-VL-8B-Instruct (CAVEAT: Mesa gate)

- **Use case:** OCR-free document understanding, screenshot/diagram Q&A, image-grounded RAG ingestion in AnythingLLM. Genuinely empty slot today.
- **Top pick:** `Qwen/Qwen3-VL-8B-Instruct`, GGUF `unsloth/Qwen3-VL-8B-Instruct-GGUF` (Q4_K_M LM + mmproj-F16, 308K dl). Apache-2.0. Current SOTA open small VLM for DocVQA/ChartQA/screenshots; text-LM Vulkan support merged in PR #16780 (Oct 2025).
- **VRAM math:** Q4_K_M LM ~4.5 GB + mmproj-F16 ~1.0 GB + q8_0 KV ~1.5 GB @32K + ~0.4 GB vision buffer ≈ **7.5 GB**. Fits with room. Hot-swap-exclusive, **never resident** — image requests are bursty.
- **THE BLOCKING CAVEAT — validate before relying on it:** the Vulkan vision (mmproj/CLIP) path is the risk, exactly on this hardware:
  - llama.cpp #22128: Mesa RADV heap corruption → server SIGSEGV on vision requests on the **exact RX 6900 XT / Navi 21 / gfx1030** card. **Fixed in Mesa 26.0.5**, verified end-to-end 2026-04-23.
  - #17012: image encode 35–90s on some Vulkan builds (GPU idle) vs ~1.8s ROCm.
  - #19735: vision fully broken in builds b8091–b8108 (fixed b8109).
- **Deployment gate (all four required):** (1) confirm the Talos node's Mesa/RADV in the `ghcr.io/mostlygeek/llama-swap:*-vulkan-*` image is **≥ 26.0.5**; (2) pin a known-good llama.cpp build; (3) set `--image-min-tokens 1024` (Qwen-VL grounding) and cap `--image-max-tokens ~1024–2048`; (4) CPU-CLIP fallback if encode is unstable. Expected: text decode ~30–60 tok/s; **image encode ~3–10s** (verified runs 3.2–7.4s) — fine for batch ingestion, **not interactive** screenshot Q&A.
- **If Mesa cannot reach ≥26.0.5:** do **not** deploy a VLM. Use Tesseract/PaddleOCR-VL as a CPU OCR step upstream of AnythingLLM and keep llama-swap text-only.
- **Runner-up:** `ggml-org/gemma-3-12b-it-GGUF` (use the **ungated ggml-org repo**, not the gated QAT repo, for init-container prefetch). Older/more-exercised mtmd path (PR #12344) — same Mesa gate applies; add ~860 MB for its SigLIP tower; consider `-ub 512`. Or `ggml-org/InternVL3-8B-Instruct-GGUF` (standard CLIP head, Apache-2.0).
- **REJECTED:** Qwen3-VL-30B-A3B (Q4 ~18 GB doesn't fit; Q3 ~14 GB too tight with mmproj+KV); any 32B dense.
- **Verdict:** Pick is best-in-class; deployment is CAVEAT-gated on Mesa version. ADD only after hardware verification.

---

## 3. The Autonomous-Coding Slot (top priority — extra depth)

This is the stated #1 priority and needs to be understood as **three distinct sub-roles**, not one model:

**(a) FIM autocomplete** — covered in §2.3. Latency-bound, 3B base, ~250 tok/s. The deployed Qwen2.5-Coder-3B is correct here (switch to Base). Do not put an agent model in this slot — too slow to swap and decode.

**(b) Single-turn / fast completion** — the deployed Qwen2.5-Coder-7B can stay as a `coder-large`/FIM-adjacent model, but understand its ceiling: it is a single-turn code generator with weak tool-calling and **no agentic post-training**. It stalls on multi-step tasks. It is NOT the autonomous agent.

**(c) Agentic / multi-file / tool-use** — the real flagship gap. **ADD Qwen3-Coder-30B-A3B-Instruct.**

- **Top pick:** `Qwen/Qwen3-Coder-30B-A3B-Instruct` (30.5B total / **3.3B active**, arch `qwen3_moe`, Apache-2.0). GGUF `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` (1.9M dl).
- **Why it wins ON THIS BOX — the load-bearing argument:** it is **pure-attention `qwen3moe` with ZERO GatedDeltaNet/SSM layers.** llama.cpp issue #15163 benchmarks **this exact model on an RX 6800 (RDNA2, gfx1030 — same silicon, fewer CUs)** fully offloaded `-ngl 99` at Q3_K_M: **pp512 ~610 t/s, tg128 ~120 t/s**; with FA at 4K depth ~420 pp / ~88 decode. The 6900 XT (80 CUs vs 60) meets or exceeds this. Every "better-on-paper" successor (Qwen3.6-35B-A3B, Qwen3.6-27B) is **GatedDeltaNet** and is **REJECTED** — see below.
- **Is the MoE worth the tight VRAM fit?** Yes, decisively. The runner-up Devstral-Small-2507 is a dense 24B → bandwidth-bound at ~8–13 tok/s on 512 GB/s. The 30B-A3B runs at **3B-active speed (~80–120 tok/s decode)** — a 5–10x speed win for an agent that makes many turns. For agentic loops, decode throughput is the difference between usable and painful.
- **CRITICAL QUANT CORRECTION (CAVEAT):** the original research named **"IQ3_K"** as the primary quant. **IQ3_K does NOT exist in mainline llama.cpp** (only IQ3_XXS=18, IQ3_S=21 in `ggml.h`); it is an `ik_llama.cpp`-exclusive type. An IQ3_K GGUF would **fail to load** on the deployed mainline Vulkan engine. **Deploy `Q3_K_S` (13.29 GB)** — the exact file the gfx1030 benchmarks used — or `UD-Q3_K_XL` (13.81 GB) / `IQ3_XXS` (12.85 GB). Q3_K_M (14.71 GB) fits but leaves too little KV headroom.
- **VRAM math:** Q3_K_S 13.29 GB + (GQA-4, tiny KV ~49 KB/token) q8_0 KV @32K ~1.6 GB + ~1 GB buffer + 0.64 GB resident embed/rerank → ~16K ctx comfortable, 32K at the optimistic edge. Treat **16–24K as the safe ceiling.**
- **Engine requirements:** (1) `-fa 1` is **mandatory** (KV-quant + ctx fit, best perf); (2) pin a llama.cpp Vulkan build **≥ b6272** (Aug 2025) — RDNA2 has no matrix cores, so the `MUL_MAT_ID` MoE path was ~9x slow before that fix; (3) keep ctx bounded — RDNA2 Vulkan can hard-lock on OOM.
- **Runner-up:** Devstral-Small-2507 (24B dense, `mistralai/Devstral-Small-2507`, agentic SWE-bench-tuned). GGUF `bartowski/mistralai_Devstral-Small-2507-GGUF`. The safe dense fallback if Q3 MoE coding quality disappoints — dense Mistral arch = zero Vulkan risk. **CAVEAT (`vramRealistic: false`):** the original Q4_K_S/IQ4_XS claim is too optimistic — Q4_K_S (13.55 GB) does **not** fit even at 8K; deploy **IQ4_XS (12.76 GB) at 8–16K ctx only**, or Q3_K_M/IQ3_M for 32K. 8–16K is a real limitation for multi-file work — accept it only as a fallback at ~8–13 tok/s.

**REJECTED agentic picks (flagged explicitly):**
- **Qwen3.6-35B-A3B** — SOTA benchmarks (SWE-bench 73.4) but `fits: false`: usable quant Q3_K_M is 16.6 GB (over budget) AND it's GatedDeltaNet/SSM — the Vulkan GDN shader (PR #20334) is benched only on RDNA3.5/RDNA3 with coopmat; gfx1030 has none → unverified, high risk of CPU-fallback corruption. Target only if a ≥20 GB dGPU lands.
- **Qwen3.6-27B (dense)** — `fits: false`: Q4_K_M 16.8 GB over budget; dense+GDN benched only ~12.7 tok/s even on RDNA3.5. Wrong box.

**Re-evaluate the Qwen3.6 family only when (a) a ≥20 GB dGPU lands, or (b) someone benches GatedDeltaNet on RDNA2 gfx1030 Vulkan and confirms stable full-GPU execution.**

---

## 4. Deep Reasoning Slot — REPLACE Qwen3-14B

The old "~5 tok/s, tolerated to be slow" framing for this slot is **obsolete and wrong by an order of magnitude.** MoE changes the calculus.

- **Top pick:** **Qwen3-30B-A3B-Thinking-2507** (`Qwen/Qwen3-30B-A3B-Thinking-2507`, `qwen3_moe`, Apache-2.0). GGUF `bartowski/Qwen_Qwen3-30B-A3B-Thinking-2507-GGUF`.
  - Beats Qwen3-14B on every axis: AIME25 **85.0** vs ~70, GPQA 73.4, MMLU-Pro 80.9, LiveCodeBench v6 66.0, BFCL-v3 72.4.
  - **Speed reality:** measured on RX 6800/6900 XT gfx1030 Vulkan — ~107–120 tok/s decode empty, ~92 @4K, 43–58 @16–30K. This is a **fast MoE generalist, not a slow reasoner.**
  - **VRAM CAVEAT (`vramRealistic: false`):** the "Q3_K_M ~14.1 GB fits" claim counts weights only. With KV (4 GQA heads, ~1.6 GB q8_0 @32K) + ~1 GB buffers + 0.64 GB resident, Q3_K_M does **not** fit at 32K and is marginal even at 8K. **Deploy Q3_K_S (~12.85 GB)** for 16–24K ctx, or Q3_K_M capped ~8–16K.
  - **Engine:** flash-attention mandatory (RDNA2 MoE prefill collapses ~9x without it); re-bench `-ctk/-ctv q8_0` KV-quant prefill on bigboi before committing.
- **Co-occupant (ADD to same exclusive chat group):** **GPT-OSS-20B** (`openai/gpt-oss-20b`, MXFP4 MoE, 3.6B active, Apache-2.0). GGUF `ggml-org/gpt-oss-20b-GGUF` (`gpt-oss-20b-mxfp4.gguf`, 11.27 GiB).
  - **Verified on the exact gfx1030 silicon:** ~10,949 MiB GPU weights; SWA + GQA → tiny KV (384 MiB @16K f16); even 128K ctx fits under 15 GB. ~35 tok/s decode (faster than the dense Qwen3-14B it supplements). Best tool-calling for n8n/MCP; adjustable reasoning effort.
  - **CRITICAL flag corrections (CAVEAT):** (1) **`-fa` MUST be OFF** — attention-sinks are unimplemented in the Vulkan FA path; `-fa` segfaults or silently offloads attention to CPU (#15100, #15107); (2) **do NOT quantize KV** (`-ctk/-ctv`) — segfaults; use f16 (cheap anyway due to SWA); (3) requires recent driver + recent llama.cpp build (MXFP4 perf landed Aug 2025); (4) it's a reasoning model — do **not** cross-recommend it for the coding slots.
- **Demote, don't delete:** keep **Qwen3-14B Q4_K_M** as the dense safety floor (it has VRAM room — bump ctx from 8192 to 24–32K). It's the predictable fallback if MoE Vulkan misbehaves on the actual node.
- **REJECTED:** Qwen3-32B dense (Q4 ~19 GB doesn't fit); GLM-4.x-Flash 30B-A3B (`fits: false` — needs CPU offload at Q4 per benchmarks; weaker GGUF/gfx1030 validation than Qwen3-Thinking).

**Usage split:** Qwen-Thinking for hardest math/logic; GPT-OSS-20B for agentic/long-context reasoning.

---

## 5. What the 16 GB dGPU Unlocks vs the Old APU Assumptions

The cluster's prior memory (`project_ai_stack_plan`, `project_amd_gpu_stack`) assumed a UMA APU where ~5 tok/s on a 14B was the slow-but-tolerated reasoning floor. The dedicated RX 6900 XT (16 GiB GDDR6, 512 GB/s, 80 CUs) changes what's viable:

- **30B-A3B MoE class is now the practical sweet spot.** Previously off the table; now Qwen3-Coder-30B-A3B, Qwen3-30B-A3B-Thinking, and Qwen3-30B-A3B-Instruct all fit at Q3_K_S/IQ3 and run at **80–120 tok/s** (3B-active), not ~5 tok/s. This is the single biggest unlock — the flagship agentic coder is only possible because of it.
- **GPT-OSS-20B (MXFP4)** — native day-0 MXFP4 Vulkan, ~11.3 GB, verified on this exact card. A genuinely new reasoning+tool-use option with huge KV headroom.
- **A local VLM (Qwen3-VL-8B)** is newly viable — ~7.5 GB at 32K leaves room, gated only on Mesa ≥26.0.5.
- **Resident retrieval can upgrade to the Qwen3 family** (embed + rerank) with code-retrieval scores that were unreachable on the old setup, at a combined ~1.3 GB resident.
- **Still NOT unlocked (do not chase):** the GatedDeltaNet generation (Qwen3.5/Qwen3.6) — gated on RDNA2 having no coopmat, not on VRAM. 32B dense at Q4 (~19 GB) still doesn't fit. vLLM/ROCm remain dead on this Talos node.

---

## 6. Concrete Next Steps

### GGUFs to pull (init-container prefetch — exact repos)

```
# Agentic coder (ADD — flagship)
unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF        → Q3_K_S (13.29 GB)   [NOT IQ3_K — does not load]

# Deep reasoning (REPLACE Qwen3-14B primary)
bartowski/Qwen_Qwen3-30B-A3B-Thinking-2507-GGUF  → Q3_K_S (~12.85 GB)
ggml-org/gpt-oss-20b-GGUF                         → gpt-oss-20b-mxfp4.gguf (11.27 GB)  [co-occupant]

# FIM autocomplete (KEEP — switch Instruct→Base, Q4→Q5)
bartowski/Qwen2.5-Coder-3B-GGUF                   → Q5_K_M (~2.2 GB)    [BASE repo]

# General chat (KEEP)
unsloth/Qwen3-4B-Instruct-2507-GGUF               → Q4_K_M (~2.5 GB)

# Fast routing (KEEP)
ggml-org/Qwen3-1.7B-GGUF                           → Q5_K_M (~1.4 GB)

# RAG embeddings (REPLACE nomic)
Qwen/Qwen3-Embedding-0.6B-GGUF                     → Q8_0 (~0.64 GB)    [resident]

# RAG reranker (REPLACE bge)
ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF             → Q8_0 (~0.64 GB)    [resident]

# Vision (ADD — gated on Mesa ≥26.0.5)
unsloth/Qwen3-VL-8B-Instruct-GGUF                  → Q4_K_M LM + mmproj-F16 (~7.5 GB @32K)

# Fallbacks (configure, commented out)
bartowski/mistralai_Devstral-Small-2507-GGUF       → IQ4_XS (12.76 GB) @8-16K   [dense coder fallback]
ggml-org/gemma-3-12b-it-GGUF                        → vision fallback (ungated)
# keep existing bge-reranker-v2-m3 + Qwen3-14B Q4_K_M as floors
```

### Suggested llama-swap model keys / quants / ctx / flags

| Key | Repo / quant | Group | ctx | Critical flags |
|-----|-------------|-------|-----|----------------|
| `agentic-coder` | Qwen3-Coder-30B-A3B Q3_K_S | chat (exclusive) | 16–24K | `-fa 1`, build ≥b6272 |
| `reasoner` | Qwen3-30B-A3B-Thinking Q3_K_S | chat (exclusive) | 16–24K | `-fa 1`, recent build |
| `reasoner-agentic` | gpt-oss-20b MXFP4 | chat (exclusive) | 32–60K | **`-fa` OFF**, **f16 KV (no -ctk/-ctv)** |
| `local-balanced` | Qwen3-4B-Instruct-2507 Q4_K_M | chat (exclusive) | 32K+ | standard |
| `coder-small` | Qwen2.5-Coder-3B **BASE** Q5_K_M | own group | 32K | **FIM template, not chat** |
| `local-fast` | Qwen3-1.7B Q5_K_M | always-on (promote) | few-K | `/no_think` |
| `local-embed` | Qwen3-Embedding-0.6B Q8_0 | always-on, ttl 0 | — | `--embeddings --pooling last`, send query-instruction prefix |
| `local-rerank` | Qwen3-Reranker-0.6B Q8_0 | always-on, ttl 0 | — | `--reranking --pooling rank`; LiteLLM → `/v1/rerank` |
| `vision` | Qwen3-VL-8B Q4_K_M + mmproj-F16 | chat (exclusive), never resident | 32K | `--image-min-tokens 1024`, gate on Mesa ≥26.0.5 |

### Models to retire (as primary slot occupants)
- **Qwen2.5-Coder-7B-Instruct** (coder-large) — superseded by the agentic-coder slot; single-turn only, no agentic post-training.
- **Qwen3-14B** as reasoning primary — demote to documented dense safety floor (keep Q4_K_M, bump ctx to 24–32K).
- **nomic-embed-text-v1.5** → fallback only.
- **bge-reranker-v2-m3** → fallback only (keep commented-out).

### One-time migration tasks
1. **Re-index AnythingLLM pgvector** — embedding model + dims change (768→1024).
2. **Verify Mesa ≥ 26.0.5** in the pinned `ghcr.io/mostlygeek/llama-swap:*-vulkan-*` image before enabling vision; if not, defer the VLM and use CPU OCR upstream.
3. **Confirm llama.cpp build ≥ b6272** (RDNA2 MoE perf) and ideally a 2026 build (gpt-oss long-context fix).
4. **On-node bench** the two reasoning MoEs' KV-quant prefill and the coder's actual ctx ceiling on bigboi-jms-01 before committing context sizes.

**Open risk to flag to the operator:** every flagship pick (agentic coder, both reasoners) is an MoE at Q3/MXFP4 on a matrix-core-less card running at the edge of VRAM with mandatory (and conflicting — FA-on for Qwen, FA-off for gpt-oss) flash-attention rules. These are validated against close-silicon benchmarks (RX 6800 gfx1030) but **not yet on bigboi itself.** Keep the dense Qwen3-14B floor in place until the MoE Vulkan path is confirmed stable on the actual node.
