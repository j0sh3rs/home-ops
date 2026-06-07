# AI Stack First-Principles Re-Evaluation — 2026-06-07

Archive of the deep-research workflow that re-grounded the `ai/` namespace stack from
first principles after the bigboi worker (AMD Navi 21 RX 6900 XT) came online.

## Trigger

The mem0 memory layer was blocked on a permanently-404 upstream image. Rather than pick a
mem0 replacement, the scope widened to a full first-principles re-eval: what are the layers
of a self-hosted Claude-Code-like toolchain, what OSS options exist per layer, and what
should the go-forward stack be — grounded in this cluster's constraints (Talos, AMD-Vulkan
only, ROCm dead, single-datastore discipline, amd64, solo operator).

## Method

A 5-phase background workflow (`Workflow` tool, ultracode):

1. **Layer Research** — 13 parallel agents, one per stack layer.
2. **Maturity Verify** — 36 finalist candidates adversarially verified (real maintained
   amd64 image? license? deprecation? backend deps?) to kill hallucinated freshness — the
   lesson from mem0/Zep/Letta all being dead-on-arrival.
3. **Integration Map** — cross-layer matrix, glue costs, conflicts, end-to-end data flow.
4. **Adversarial Challenge** — 3 skeptic lenses: over-engineering/YAGNI, integration-debt,
   goal-fit (can a local Vulkan model actually drive an autonomous coding agent?).
5. **Final Synthesis** — per-layer KEEP/ADD/REPLACE/DROP, phased rollout, honest limits.

54 agents total, ~785k subagent tokens.

## Files

| File | What |
|------|------|
| `SYNTHESIS.md` | **Start here.** Human-readable rendering: executive summary, layer verdicts, recommended stack, phased rollout, integration map, all 3 adversarial challenges verbatim. |
| `workflow-result.json` | Raw machine output (the JSON the workflow returned). Source of truth; `SYNTHESIS.md` is rendered from it. |
| `workflow-script.js` | The workflow script that produced this. Re-runnable record of the exact prompts + schema. |

## Bottom line

The deployed stack is ~85% correct. The work is mostly deletion + two config unlocks, NOT
new components. Key conclusions:

- **The coding agent is cloud-only.** A 7-14B Q4 model at 8-16k ctx (even on the 6900 XT)
  cannot drive reliable autonomous multi-file coding. The homelab's role is RAG +
  observability + cheap local completion + the cloud-passthrough gateway — not the brain.
- **Highest-leverage action**: uncomment LiteLLM `cloud-*` aliases + add Anthropic key
  (~30 min) — gates the entire Claude-Code-like goal.
- **Highest-severity risk**: unconstrained Renovate auto-merge could ship a `-rocm`/`-cuda`
  llama-swap image onto Talos unattended. Pin to `-vulkan-b` first.
- **Drop**: dedicated memory layer (mem0), sandboxed code-exec, owui-pipelines.

The actionable distillation lives in agent memory at
`project_ai_stack_determination.md`. This dir is the full backing evidence.
