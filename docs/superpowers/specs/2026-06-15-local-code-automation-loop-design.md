# Local Code-Automation Loop — Design Spec

**Date:** 2026-06-15
**Status:** Approved (design); P0 in progress
**Supersedes nothing; extends:** `project-ai-stack-determination` (memory, 2026-06-07)
**Tracking:** GitHub issues in `j0sh3rs/home-ops` (NOT Jira)

## 1. Goal

Build a cluster-resident feedback loop that automates code changes against
`home-ops` (and, later, arbitrary repos the operator points it at). The loop is
triggered by GitHub events or chat, generates changes via cloud-backed agentic
engines, validates them, and opens PRs — auto-merging only the lowest-risk
class.

## 2. Core premise (resolved contradiction)

The 2026-06-07 determination established — via a 13-layer deep-research +
3-skeptic adversarial pass — that **local autonomous coding is not viable on
this hardware**: a 7–14B Q4 model cannot drive reliable multi-file autonomous
coding (malformed tool calls, premature stop, context blowout, 16 GiB OOM).

This design honors that. **"Using local models" = orchestration is local; the
code-generation brain is cloud-Anthropic via LiteLLM.** Local models (now
including Qwen3-Coder-30B MoE and GPT-OSS-20B, which post-date the
determination) handle only the cheap path: triage, classification,
commit-message generation, and embeddings/rerank for RAG.

A future Tier-C (bounded single-file local edits) is explicitly out of scope
until the loop is proven and a concrete trigger exists.

## 3. Locked decisions

| Decision | Choice |
|----------|--------|
| Code-gen brain | Cloud-Anthropic via LiteLLM passthrough (local orchestration) |
| Triggers | A (GitHub webhook) + B (chat) first; C (schedule/event) later |
| Target repos | `home-ops` first; generic-capable design |
| Engines | **Goose only** (`goose run`, headless). claude-code DROPPED 2026-06-16 — see §10. |
| Engine selection | Single engine (Goose). Run-both/scorer deferred until a 2nd viable headless engine exists. |
| Code-RAG | Dedicated, code-aware, **local-only embeddings**; research-first |
| Loop closure / gate | Static + `kubectl apply --dry-run=server` (gate B) |
| Merge policy | Autonomous PR always; auto-merge `risk/low` only; human gate for `risk/medium\|high\|critical` (inherits Renovate philosophy) |
| First use cases | C (OCI migration sweep) + D (docs/codemap drift), then E (open-ended chat) |
| Config audit | Lightweight now (done, §8); full audit becomes dogfood goal |
| Home of the loop | `home-ops` itself |
| Task-state store | GitHub labels/branches/PRs; loop-run log table in postgres18 |
| Dispatch shape | Ephemeral K8s Jobs (clone → work → die); no long-running daemon |

## 4. Architecture

```
TRIGGERS                    ORCHESTRATOR              ENGINES (cloud-backed)         GATES
A. GitHub webhook ─┐                                  ┌─ claude-code headless ─┐
   (issue/PR/label)│                                  │   (claude -p, Job pod) │
                   ├──► n8n ──► dispatch ──► runner ──┤                        ├─► validate
B. Telegram/chat ──┘    (router)   (Job)              └─ Goose (goose run) ────┘    pipeline
                          ▲                            both call LiteLLM ──► cloud      │
                   code-RAG retrieval                                              risk-gate
                          ▲                            local models do:           low→auto-merge
                   vector DB (code index)              triage/classify/msg        med+→human PR
```

**Components (one responsibility each, swappable behind interfaces):**

1. **Trigger layer** (n8n) — GitHub webhook node (A) + Telegram Trigger w/
   chat-ID allowlist (B). Both normalize to a common `TaskRequest{repo, ref,
   intent, source, trigger_id}`.
2. **Orchestrator** (n8n) — claim-lock, RAG retrieval, two-Job fan-out, poll,
   validation pipeline, scorer, risk-gate. Owns control flow only; never
   generates code.
3. **Engine layer** (interchangeable, cloud-backed) — `claude-code` headless
   and `goose run` in ephemeral Jobs. Common contract: in = workdir + task +
   RAG context; out = git diff + run log. `ANTHROPIC_BASE_URL` → LiteLLM.
4. **Code-RAG** — vector DB + code-aware indexer; injects repo context into the
   engine prompt. Local-only embeddings (qwen3-embed). Researched in P2.
5. **Validation pipeline** — `kustomize build` → `flux build --dry-run` →
   kubeconform → `kubectl apply --dry-run=server` → `task sops:verify`. Engine
   iterates until green (bounded N). This is the loop closure.
6. **Risk-gate** — reads PR risk labels (existing labeler). `risk/low` →
   auto-merge; `risk/medium\|high\|critical` → open PR, stop, notify.
7. **Local models** — triage, classification, commit-message gen on
   `local-fast` / `local-reason-agent`. $0.

**Concurrency control:**
- **Claim lock** — orchestrator sets `loop/claimed` label + lock record before
  dispatch; idempotent against webhook re-delivery (one TaskRequest → one
  dispatch).
- **Branch isolation** — each engine works `loop/<id>-<engine>`; separate Job /
  worktree; no collision.
- **Compare gate** — both diffs validated independently; scorer (local model +
  objective signals: passed? diff size? files touched?) picks winner. Winner →
  PR, loser → archived comment. Early: present both to operator.

## 5. Data flow (one task)

1. **Trigger** — GitHub issue `loop/go` (A) or Telegram "fix X" (B).
2. **Normalize** — n8n → `TaskRequest`.
3. **Claim** — check lock; unclaimed → set `loop/claimed` + lock record;
   claimed → exit (idempotent).
4. **Triage** — `local-fast`: actionable? in-scope? pre-estimate risk. Not
   actionable → comment + unclaim + stop.
5. **Retrieve** — code-RAG → context bundle injected into engine prompt.
6. **Dispatch** — two parallel Jobs (claude-code + goose): clone @ ref, own
   branch, run engine (cloud-backed), emit diff + log.
7. **Validate** — per branch: kustomize → flux build → kubeconform →
   apply --dry-run=server → sops:verify. Fail → engine retries (bounded N).
8. **Score** — rank the two green branches → winner (early: present both).
9. **Risk-gate** — winner → PR w/ evidence (diffs, logs, RAG sources, scores).
   Labeler tags risk. `risk/low` → auto-merge; `risk/med+` → stop + notify.
10. **Observe** — every step → LangFuse + loop-run record; unclaim on terminal.

**Failure handling (explicit):**
- Engine OOM/timeout → that branch fails; other can still win; both fail →
  comment w/ logs + unclaim, no PR.
- Validation never green after N → stop, attach last error, notify.
- Cloud 5xx → bounded retry then fail; never silent.
- Webhook double-delivery → claim-lock idempotent.

**State:** GitHub (labels/branches/PRs = task state) + small loop-run record
table in postgres18 (new `loop` DB) for observability/scoring history. No new
stateful pod.

## 6. Code-RAG research spike (P2 — standalone, gates P3)

Deliverable: `docs/research/code-rag-<date>/` — options matrix, local-embed
retrieval benchmark on 5–10 real home-ops tasks, go/no-go on
dedicated-vs-agentic.

| Axis | Options to evaluate |
|------|---------------------|
| Vector DB | Qdrant · pgvector-separate-DB on postgres18 · LanceDB (S3/RustFS-backed) · Weaviate |
| Chunker | tree-sitter · aider-style repo-map (PageRank symbols) · LSP-symbol |
| Embedder | **local only**: qwen3-embed (resident, $0); nomic-embed-code if local-servable |
| Index trigger | push webhook · scheduled · on-demand at dispatch |
| Retrieval | pure vector · hybrid (vector + BM25/grep) · repo-map + bge-rerank (resident) |

**Skeptic's prior (to test, not assume):** for a single operator, agentic live
grep/read may beat a vector index — the engines already navigate repos well, and
a code index goes stale + adds a pod. Spike must prove dedicated code-RAG earns
its keep over "agent reads repo live + vector-index only the non-code knowledge
(runbooks/ADRs/CLAUDE.md/memory)." Kill-switch to that cheaper hybrid if not.

## 7. Phasing

| Phase | What | Depends | Risk |
|-------|------|---------|------|
| **P0** | Cloud unlock — uncomment `cloud-*`, wire auth, mint budget-capped virtual key, wire claude-code-secrets | — | Blocks all |
| **P1** | Engine readiness — (a) redeploy + debug `claude-code` headless to usable; (b) deploy Goose. Both prove edit-test-iterate on a canned task | P0 | Med |
| **P2** | Code-RAG research spike (standalone deliverable; parallel to P1) | P0 | Low |
| **P3** | Code-RAG build (chosen stack; re-index-on-push) | P2 verdict | Med |
| **P4** | Orchestrator core — n8n normalize + claim-lock + two-Job fan-out + validation + scorer + risk-gate; Trigger A first | P1, P3 | Med |
| **P5** | Use case C — OCI migration sweep (`migrate-to-oci`) | P4 | Low-Med |
| **P6** | Use case D — docs/codemap drift (`doc-updater`) | P4 | Low |
| **P7** | Trigger B — Telegram front-door + chat-ID allowlist | P4 | Low |
| **P8** | Use case E — open-ended chat "fix X" | P5,P6,P7 | High |
| **P9** | Dogfood audit — point loop at cluster; audit AI-tool + HA/Bridge wiring; fix PRs | P8 | Med |

Each phase = its own implement cycle; this spec is the umbrella.

## 8. Current-state audit (verified 2026-06-15)

| # | Finding | Impact | Severity |
|---|---------|--------|----------|
| G1 | Cloud `cloud-*` aliases still commented in LiteLLM configmap; determination Phase 1 never executed | Code-gen has no brain until landed | CRITICAL → P0 |
| G2 | `claude-code` dropped today (commit `885d0d7d`; ks.yaml commented) | Named headless engine not deployed; re-add as Job runner | HIGH → P1 |
| G3 | Local lineup grew past "7–14B Q4": `local-coder`=Qwen3-Coder-30B MoE ~120tok/s, `local-reason-agent`=GPT-OSS-20B | Strengthens local for cheap steps; code-gen stays cloud | INFO |
| G4 | `mcpjungle` live, exports OpenAPI MCP gateway | Loop tools (git/GitHub/kubectl) can route through it | ASSET |
| G5 | Goose is Renovate-untrackable (no semver ghcr tag); use `goose run`/`goose serve`, not `command: server` | Manual sha bumps; known maintenance tax | NOTE |

## 9. P0 detail — cloud unlock

Executes determination Phase 1 with one revision for unattended operation:

**Auth method (DECISION REQUIRED before editing configmap):**
- **Option A — raw budget-capped API key.** `ANTHROPIC_API_KEY` in
  `litellm-secrets`; `cloud-*` aliases resolve `os.environ/ANTHROPIC_API_KEY`.
  Clean for unattended Jobs; no OAuth token forwarded through pods. Spend capped
  on the minted LiteLLM virtual key.
- **Option B — subscription passthrough.** `forward_client_headers_to_llm_api:
  true`; forwards claude.ai OAuth token. Determination flagged this
  single-operator-only and security-sensitive. **Riskier for unattended Jobs**
  (token in pod env / forwarded headers).

Recommendation: **Option A** for the loop. The loop runs unattended; a
budget-capped API key is a cleaner blast-radius than forwarding a personal OAuth
token through ephemeral Job pods.

Steps (Option A):
1. `litellm/app/configmap.yaml` — uncomment `cloud-haiku` + `cloud-sonnet`
   (keep `api_key: os.environ/ANTHROPIC_API_KEY`); optionally uncomment fallback
   chains.
2. Add `ANTHROPIC_API_KEY` to `litellm-secrets` via `sops-edit-then-encrypt`.
3. Mint budget-capped virtual key via `POST /key/generate` (model allow-list
   `[cloud-haiku, cloud-sonnet, local-*]`; spend ceiling TBD with operator).
4. Verify: `kustomize build kubernetes/apps/ai/litellm/app` + `task sops:verify`
   + flux reconcile + confirm LangFuse sees `cloud-*` completions.

## 10. Decision record — claude-code dropped, Goose is the engine (2026-06-16)

**What happened:** P0 (cloud unlock) completed and is merged. P1 attempted the
two engines. The **claude-code** path consumed a full session and was abandoned.

**claude-code post-mortem.** It is an interactive/IDE product; forcing it
headless fought the tool at every layer. We did solve every individual problem:
- Remote-control is OAuth-subscription-ONLY (refuses `ANTHROPIC_API_KEY`).
- `nfs-client` squashes files to uid 1024 / gid 100 — pod + image must match.
- `CLAUDE_CONFIG_DIR` must be set or org/account state (`.claude.json`) lands on
  ephemeral fs and is lost on restart → "Unable to determine your organization".
- The container image was pinned to uid 1024:100 (`j0sh3rs/containers`).
- `claude remote-control` has an interactive "Enable Remote Control? (y/n)"
  prompt with no `--yes` flag.

Even with ALL of that fixed, remote-control did not work usefully in-cluster.
**Decision: stop. `claude-code/ks.yaml` disabled in `ai/kustomization.yaml`
(manifests retained, not reconciled). Details in memory
[[project-claude-code-container]].**

**Go-forward: Goose is the sole engine.** Goose is purpose-built for headless,
non-interactive runs (`goose run`), which is exactly what the loop needs:
- OpenAI-compatible: `GOOSE_PROVIDER=openai`,
  `OPENAI_HOST=http://litellm.ai.svc.cluster.local:4000`,
  `OPENAI_API_KEY=<budget-capped LiteLLM vkey>`, model alias `cloud-sonnet`.
- Reuses the P0-proven vkey path — NO OAuth/subscription/org-eligibility tar pit.
- Ephemeral Job re-auths from env each run — no NFS credential-persistence
  problem (the entire class of claude-code bugs disappears).

**Known Goose risks (verify before building, do not assume):**
1. No semver ghcr tag — Renovate-untrackable, manual sha bumps (per
   [[project-ai-stack-determination]]).
2. Config format (`~/.config/goose/config.yaml` vs env) — verify vs current
   release, not memory.
3. mcpjungle/tool wiring (`gh`, `git`) — verify.

**Revised P1 (next session, fresh context):** research current Goose release →
config → one-shot `goose run` Job, cloud-backed via the vkey → prove it produces
a valid diff + traces to LangFuse. That is the P1 gate. The run-both/scorer
design (§4) is deferred until a second viable headless engine exists.

**Status at bank (2026-06-16):**
- P0: ✅ complete + merged (cloud-* enabled, $20/30d vkey minted + verified).
- P1 claude-code: ❌ dropped.
- P1 Goose: ⏸️ not started — the real next step.
- P2 code-RAG spike, P3+: unchanged, still pending.
