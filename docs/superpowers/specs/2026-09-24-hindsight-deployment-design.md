# Hindsight Deployment (Parallel Run with OpenViking) — Design

Date: 2026-09-24
Status: Approved design, pending implementation plan
Issue: #701 (P1-06). Folds in #702 (P1-07, Memory Defense).
Related: #704 (P0-05, recall eval — gates cutover, not this work),
#703 (P1-08, backfill), #705 (P0-01, Omniroute CNP — disabled, on branch
`security/705-omniroute-cnp`), `kubernetes/apps/ai/CLAUDE.md`,
`docs/superpowers/specs/2026-09-18-openviking-vlm-direct-shim-design.md`

## Context

OpenViking puts an LLM on every recall: with a session ID set, its plugin's
`recall-core.mjs` calls `/api/v1/search/search`, which runs intent analysis
through the `vlm` leg (omniroute-shim → CLIProxyAPI `gpt-5.6-luna`, falling
back to local `qwen2-vl-2b`). It falls back to embedding-only `/find` only on
an explicit error, not on slowness. The `UserPromptSubmit` hook is killed
after 60s, and the shim's worst case is 45s + 110s. So when CLIProxyAPI is
slow, each prompt stalls up to a minute and then proceeds with no recall and
no visible error.

[Hindsight](https://github.com/vectorize-io/hindsight) (MIT) replaces this
with in-process embeddings and reranking on the recall path, backed by
Postgres + pgvector.

## Goal and scope

Deploy Hindsight and run its Claude Code plugin **alongside** OpenViking on
this machine (the Synology NAS checkout) and on HolyClaude, so both memory
layers operate in parallel ahead of an eval-gated cutover.

In scope:

- Hindsight server (API + control plane) on the shared CNPG cluster
- Memory Defense on by default for every bank (#702)
- `gpt-oss-20b` made the dGPU's sole, always-on chat model, serving retain
  and reflect
- A retain-quality trial on ~20 real sessions (user sign-off gate)
- `hindsight-coding-agents` plugin on this machine and HolyClaude

Out of scope (each is its own later work):

- Codex and Pi plugin rollout
- Backfill of existing history (#703)
- Recall eval and OpenViking baseline (#704)
- Cutover and OpenViking retirement (vlm shim path, `openviking-*` Omniroute
  keys, accepted-risk note updates)
- Enabling the #705 CiliumNetworkPolicy
- Upgrading any consumer to subscription models (see Follow-ups)

## Decisions

| # | Decision | Why |
|---|----------|-----|
| D1 | Upstream OCI chart `oci://ghcr.io/vectorize-io/charts/hindsight` pinned to `0.10.1`, via `OCIRepository` + `chartRef` | Repo convention; the chart is published to OCI |
| D2 | API runs the queue worker in-process (`worker.enabled: false`), 1 replica; control plane 1 replica | Single-replica house rule; volume doesn't justify a worker StatefulSet |
| D3 | External Postgres on `postgres17-rw` via a CNPG managed role + CNPG `Database` resource with `extensions: [vector]` | Hindsight's migrations check for pgvector but never create it; `postgres-init` cannot create extensions |
| D4 | Auth via `StaticKeysTenantExtension`, one user `josh` with one key per client | Per-client revocable keys that all share one schema (`user_josh`), i.e. shared memory. The built-in extension supports only one shared key |
| D5 | Extension source shipped in a ConfigMap and put on the API's `PYTHONPATH`; custom image only if that fails to import | The extension is ~17 KB of pure Python with no dependencies; avoids an image build pipeline |
| D6 | Default in-process models (`BAAI/bge-small-en-v1.5` embedder, `cross-encoder/ms-marco-MiniLM-L-6-v2` reranker), baked into the upstream image | No PVC, no startup download, no inference dependency on recall. See Accepted trade-offs for quality |
| D7 | Retain/reflect LLM: `provider=openai`, base URL `http://omniroute.ai.svc.cluster.local:20128/v1`, model `llamaswap/reasoner` (`gpt-oss-20b`) | Local model, no Claude lane. Largest context available (65k), strong structured output |
| D8 | New Omniroute key `hindsight-retain` with `modelAccessMode: "restricted"` + `allowedModels: ["llamaswap/reasoner"]` | Unlike the 8 existing automated keys (`"all"`), this one cannot reach the Claude lane even by misconfiguration |
| D9 | `gpt-oss-20b` becomes the dGPU's **only** chat model, in the `always-on` group, `--parallel 2` with 2×65k slots. `agentic-coder` and `qwen3.5-35b-a3b` are commented out (not deleted) with the reason. Their aliases (`coder`, `code-large`, `coder-large`, `frontier`, `frontier-chat`) move onto `gpt-oss-20b` | Operator requirement: retain/reflect must never wait on a model swap. At 65k ctx `gpt-oss-20b` holds ~11.5 GiB of 15.9 GiB usable, so no other chat model can co-reside. Two slots keep reflect from queuing behind a long retain. Alias move means no consumer changes |
| D10 | Plugin keeps `autoInject: "reflect"` (the default) | Operator choice: keep the LLM synthesis on the first prompt to maximize memory efficacy, now that D9 removes the swap stall |
| D11 | Plugin pinned to `@vectorize-io/hindsight-coding-agents@0.7.0`, `autoUpdate: false`, `retainExtractionMode: "concise"` | Issue asks to pin. 0.7.0 (2026-09-24) postdates the fix for upstream #4560 (verbose extraction / full re-send); the plan must confirm the fix is in 0.7.0 |
| D12 | Routes on `traefik-internal` (VIP `192.168.35.17`, LAN DNS only): `hindsight.68cc.io` → API `:8888` (bearer-token auth), `hindsight-ui.68cc.io` → control plane `:3000` behind Authentik forwardAuth | All clients are on the LAN or in-cluster. The UI has no login of its own and holds an API key, so it needs forwardAuth. Moving to external later is a one-line change |
| D13 | Memory Defense and concise extraction set server-wide through `HINDSIGHT_API_DEFAULT_BANK_TEMPLATE`, applied to every new bank | The plugin creates banks dynamically per repo; a server default guarantees the policy exists before the first capture |

## Architecture

### Components

```
kubernetes/apps/ai/hindsight/
  ks.yaml                       # Flux Kustomization; dependsOn cloudnative-pg cluster
  app/
    kustomization.yaml
    ocirepository.yaml          # chart 0.10.1
    helmrelease.yaml
    configmap-extension.yaml    # hindsight_ext_static_keys_tenant/ source
    secret.sops.yaml            # postgres-password, HINDSIGHT_API_LLM_API_KEY,
                                # HINDSIGHT_API_TENANT_USERS, control-plane key
    httproute.yaml              # both routes
kubernetes/apps/databases/cloudnative-pg/cluster/
  cluster.yaml                  # + managed role `hindsight`
  hindsight-role-secret.sops.yaml
  database-hindsight.yaml       # CNPG Database, owner hindsight, extensions [vector]
kubernetes/apps/ai/llama-swap/app/configmap.yaml   # D9
kubernetes/apps/ai/holyclaude/app/                 # ~/.hindsight mount + env
```

Wire `./hindsight/ks.yaml` into `kubernetes/apps/ai/kustomization.yaml`.

**HelmRelease values**:

- `postgresql.enabled: false`; `postgresql.external` → `postgres17-rw.databases.svc.cluster.local:5432`, db/user `hindsight`
- `existingSecret: hindsight-secret`
- `podAnnotations: {reloader.stakater.com/auto: "true"}`, verified on both pod templates with `kustomize build | grep reloader.stakater`
- `metrics.serviceMonitor.enabled: true` (vmagent picks it up cluster-wide)
- API env:
  - `HINDSIGHT_API_LLM_PROVIDER=openai`, `HINDSIGHT_API_LLM_BASE_URL`, `HINDSIGHT_API_LLM_MODEL=llamaswap/reasoner` (D7)
  - `HINDSIGHT_API_TENANT_EXTENSION=hindsight_ext_static_keys_tenant:StaticKeysTenantExtension` and `PYTHONPATH` including the ConfigMap mount (D4, D5)
  - `HINDSIGHT_API_DEFAULT_BANK_TEMPLATE` (D13)
  - retain sizing (below)
- Control plane: the env var carrying its API key (exact name taken from the chart/control-plane source during planning)

**Resources**: start from the chart defaults (API request 1Gi, limit 4Gi) and right-size from observed usage after the retain trial. The in-process torch models make the API pod exceed the repo's <2Gi guideline; that is expected and recorded here.

**Storage/backup**: no PVCs. Hindsight's data lives in the CNPG cluster, covered by its existing S3 backups. Nothing new for Velero.

### Retain sizing

`gpt-oss-20b` has 65k context per slot, and its reasoning tokens count against the completion budget. `HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS` and retain batch/chunk sizes (`HINDSIGHT_API_RETAIN_BATCH_TOKENS` and related) must be set so that prompt + reasoning + output fits one 65k slot. Exact values come from reading `hindsight_api/config.py` defaults during planning, and are validated in the retain trial (step 6). Upstream's "≥65k output tokens" guidance cannot be met by any local model; the trial is the check that concise extraction works within the budget.

### Default bank template (D13)

```json
{"version": "1",
 "bank": {"memory_defense": {<sensitive_data rule, action "redact">},
          "retain_extraction_mode": "concise"}}
```

The exact `memory_defense` shape comes from the `DefensePolicy` schema in the pinned image. Planning must confirm that the template's `bank` section accepts `memory_defense`; if it doesn't, the fallback is a post-install `PATCH /v1/{tenant}/banks/{bank_id}/config` for each bank.

## Data flow

**Recall (each session's first prompt)**
1. Plugin `UserPromptSubmit` → API (`hindsight.68cc.io`, or the in-cluster Service from HolyClaude).
2. Low-budget reflect: `gpt-oss-20b` synthesizes from the bank. The plugin timeout is 20s (`reflectTimeoutMs`).
3. On timeout/5xx the plugin falls back to knowledge-page search, then raw recall. Neither fallback uses an LLM: in-process embed → pgvector + full-text → in-process rerank.

Later prompts in the session get the knowledge-page roster, and the agent calls the `hindsight_*` MCP tools on demand. This differs from OpenViking, which recalls on every prompt; the parallel run will show whether that matters.

**Retain (each Stop)**
1. Plugin `Stop` hook → API queues a retain operation in Postgres.
2. The in-process worker extracts facts via Omniroute → `gpt-oss-20b`, applies Memory Defense redaction, embeds, and stores.
3. If Omniroute or llama-swap is unavailable, operations stay queued and retry. Recall is unaffected.

**Parallel run**: both plugins install their own `UserPromptSubmit`/`Stop` hooks. Each session gets both injections, and OpenViking's stall risk remains until cutover. That is accepted for this phase.

**Bank sharing**: the plugin's default bank is `coding-agent::{gitProject}`, so the NAS checkout and HolyClaude's `/workspace/home-ops` checkout share one bank, inside the one `user_josh` schema.

## Rollout and verification

Each step must pass before the next.

1. **llama-swap (D9)**: pin `gpt-oss-20b` (`always-on`, `--parallel 2`, 2×65k), comment out the other two chat models, move the aliases.
   - ✔ rocm-smi on `bigboi-jms-01` shows ≥2 GiB free with `jina-reranker-v2` loaded.
   - ✔ Two concurrent requests are served in parallel, not queued.
   - ✔ atuin-ai-server's `coding-fast` combo still answers.
   - If ≥2 GiB free is not reached, drop to 2×49k and re-measure.
2. **Database (D3)**: managed role, role secret, `Database` resource.
   - ✔ `\dx` in `hindsight` lists `vector`.
   - ✔ The `hindsight` role can connect and owns the database.
3. **Omniroute key (D8)**: create `hindsight-retain` via the management API and store it in SOPS.
   - ✔ 200 for `llamaswap/reasoner`.
   - ✔ Rejected for a `cliproxyapi/*` model.
4. **Hindsight release**: HelmRelease, extension ConfigMap, secret, routes.
   - ✔ `/health` is 200.
   - ✔ No token → 401; each client key → 200.
   - ✔ Schema `user_josh` exists after the first authenticated call.
   - ✔ vmagent target is up for `/metrics`.
   - ✔ `hindsight-ui.68cc.io` redirects to Authentik and the UI loads after login.
5. **Memory Defense (D13, #702)**: retain into a scratch bank content containing a planted fake GitHub token and a planted `postgres://user:pass@host/db` string.
   - ✔ Stored memories and the document body show `[REDACTED:…]`, not the planted values.
   - ✔ A newly created bank's config shows the policy.
   - Then delete the scratch bank.
6. **Retain quality trial**: run `dry-run-extract` (extracts, stores nothing) over ~20 real transcripts from `~/.claude/projects`. Produce a side-by-side review of extracted facts against source excerpts.
   - **Gate: operator sign-off.** Criteria: facts are correct and grounded, decisions and their rationale are captured, nothing hallucinated, output fits the completion budget without truncation.
   - If it fails: swap the pinned model to `qwen3.5-35b-a3b` (49k ctx, re-measure VRAM) and re-run.
7. **Plugin on this machine (D11)**: `npx @vectorize-io/hindsight-coding-agents@0.7.0 install claude-code --server self-hosted --api-url https://hindsight.68cc.io`, then set `apiToken`, `autoUpdate: false`, `retainExtractionMode: "concise"` in `~/.hindsight/coding-agent.json`.
   - ✔ Bank `coding-agent::home-ops` (or the plugin's resolved name) exists with the Memory Defense policy.
   - ✔ The first prompt of a new session gets an injected reflect block.
   - ✔ A Stop produces a retain operation that completes.
8. **Plugin on HolyClaude**:
   - Add a `~/.hindsight` subPath mount to the existing PVC (same pattern as `~/.openviking`).
   - Set `HINDSIGHT_API_URL=http://hindsight-api.ai.svc.cluster.local:8888` (Service name confirmed from the rendered chart) and `HINDSIGHT_API_TOKEN` from HolyClaude's SOPS secret, so connection config lives in git.
   - Run the one-time `install claude-code` from HolyClaude's terminal.
   - ✔ Same checks as step 7.
   - ✔ The postStart `settings.json` patch leaves the plugin's hooks intact across a pod restart.
   - ✔ A fact retained from this machine is recallable from HolyClaude (shared bank).
9. **Degradation test**: scale llama-swap to 0.
   - ✔ A new session's first prompt still gets memories: reflect times out within 20s and falls back to search/recall.
   - ✔ Retain operations queue.
   - After scaling back up: ✔ the queue drains.
10. **Docs**
    - `ai/CLAUDE.md`: a Hindsight bullet, the llama-swap D9 change (updating the llama-swap entry's model list and the notes that reference `agentic-coder`/`coder-large`), and the parallel-run state.
    - Add Hindsight and the `hindsight-retain` key to the #705 allowlist on its branch.

## Accepted trade-offs

- **Local coding models are gone from the dGPU.** `coder-large`/`frontier` now resolve to `gpt-oss-20b`, a step down from Qwen3-Coder for atuin-ai-server. Live impact is atuin only (HolyClaude's `coding-deep` terminal leg was already documented as unable to serve realistic prompts; argus/openclaw aren't deployed).
- **First-prompt stall when the LLM is down.** With `autoInject: "reflect"`, an outage of llama-swap or Omniroute adds up to 20s to each session's first prompt before the fallback. Bounded, once per session, and rare now that `gpt-oss-20b` is never swapped out.
- **Once-per-session injection** instead of OpenViking's every-prompt recall.
- **Embedding quality.** `bge-small-en-v1.5` (384-dim) is weaker than OpenViking's `qwen3-embed`. Changing embedders later requires re-embedding (export/import supports it). The cheapest time to change is **before the #703 backfill**, and #704's eval decides whether to.
- **API pod memory** exceeds the repo's <2Gi guideline because of the in-process models.
- **Double injection and OpenViking's stall** persist during the parallel run.

## Risks

- **Extension import via `PYTHONPATH`** may fail (packaging or entry-point assumptions). Mitigation: build a small image from upstream's `hindsight-extensions/static-keys-tenant/Dockerfile`, which needs an image build/push workflow.
- **`--parallel 2` VRAM** measured below the margin. Mitigation: 2×49k (step 1).
- **Plugin 0.7.0 behavior differs from its README** (e.g. the #4560 fix not included). Mitigation: plan verifies against the 0.7.0 tarball's source before install.
- **HolyClaude's postStart patch** may overwrite the plugin's hooks in `settings.json`. Mitigation: step 8 checks across a restart; patch the postStart merge if needed.

## Follow-ups (not this spec)

- Codex and Pi plugins with their own keys.
- #703 backfill, #704 eval, then cutover and OpenViking retirement.
- Upgrading atuin-ai-server or other consumers to subscription models via CLIProxyAPI `gpt-*` models. Automated consumers stay off the Claude lane per the Anthropic lane policy in `ai/CLAUDE.md`.
- Enabling #705.
