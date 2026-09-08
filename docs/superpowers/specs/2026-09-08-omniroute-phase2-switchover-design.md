# Omniroute Phase 2 — Consumer Switchover & LiteLLM Teardown

Date: 2026-09-08
Status: Approved, pending implementation plan
Related: `docs/superpowers/specs/2026-09-07-omniroute-revival-design.md` (Phase 1
spec — this is its explicitly-deferred Phase 2 follow-up), `.superpowers/sdd/
2026-09-07-omniroute-phase1-implementation/progress.md` (Phase 1 execution
history), `kubernetes/apps/ai/litellm/`, `kubernetes/apps/ai/litellm-operator/`
(being removed)

## Context

Phase 1 (2026-09-07/08) stood up Omniroute alongside LiteLLM and resolved
every open item the original design left for Phase 2: real image tags, a
working MCP integration, and — critically — the real model-id addressing
scheme (`<prefix>/<model>`, confirmed live against all 8 local-provider
aliases). Phase 2 repoints the real consumers from LiteLLM to Omniroute and
fully removes LiteLLM, per the Phase 1 spec's already-made decision ("full
removal, not cold standby").

## Scope decisions (from this session's Q&A)

- **openclaw and argus are not currently deployed** (`ks.yaml` entries
  commented out in `kubernetes/apps/ai/kustomization.yaml`, no live pods).
  Only `openviking` is live and actually consuming LiteLLM today.
  **Decision: repoint openclaw's and argus's config anyway**, even though
  inert — so both are already correct whenever either gets re-enabled.
  Only openviking gets a real end-to-end connectivity check; openclaw/argus
  changes are verified via `kustomize build`/`flux build --dry-run` only
  (no live pod to test against).
- **openviking's rerank cannot route through Omniroute as currently built.**
  Omniroute's `/api/v1/rerank` endpoint has a hardcoded SSRF-hardening
  filter (`src/app/api/v1/rerank/route.ts`) that only accepts local
  provider-node backends whose `baseUrl` hostname is `localhost`,
  `127.0.0.1`, or a literal `172.16.0.0/12` address. This cluster's Service
  CIDR is `10.43.0.0/16` (confirmed via `kubectl cluster-info dump`), so
  `llama-swap-apu.ai.svc.cluster.local` never matches and the provider-node
  is silently filtered out of rerank routing specifically (chat completions
  are unaffected — different code path). **Decision: drop the `rerank`
  block from openviking's config entirely** (not part of its readiness
  check — removing it degrades retrieval to pure vector relevance, doesn't
  break the app) rather than keep LiteLLM alive for one endpoint or add a
  localhost-proxy sidecar. Filed as a TaskMaster backlog item to revisit if
  Omniroute upstream relaxes this filter (e.g. adds a private-CIDR
  allowlist or a way to register a rerank-eligible node explicitly).
- **LiteLLM: full removal**, matching the Phase 1 decision — HelmRelease,
  `litellm-operator`, CNPG `Database`/role/secret, DragonflyDB db4, the
  namespace kustomization entries, and the top-of-file comment block, all
  in one change once both consumers are confirmed working against
  Omniroute.

## Consumer repoint — exact changes

### openclaw (`kubernetes/apps/ai/openclaw/app/`)

- `configmap.yaml`: `models.providers.litellm` block (`baseUrl:
  "http://litellm.ai.svc.cluster.local:4000/v1"`, `apiKey: "$${LITELLM_API_KEY}"`,
  model ids `coder-large`/`frontier-chat`) → repoint `baseUrl` to
  `"http://omniroute.ai.svc.cluster.local:20128/v1"`, `apiKey` to
  `"$${OMNIROUTE_API_KEY}"`. Model ids change from bare (`coder-large`) to
  prefixed (`llamaswap/coder-large`) per the confirmed addressing scheme —
  `frontier-chat` → `llamaswap/frontier-chat`. Provider block key name
  (`litellm:`) and every explanatory comment referencing LiteLLM get
  updated to describe Omniroute instead (mechanical rename, not just a
  value swap — stale comments claiming "LiteLLM proxy" would mislead the
  next reader).
- `helmrelease.yaml`: comment block near the `LITELLM_API_KEY` env wiring
  (lines ~203-208) updated to describe the Omniroute equivalent; the env
  var itself renamed `LITELLM_API_KEY` → `OMNIROUTE_API_KEY`.
- `secret.sops.yaml`: `LITELLM_API_KEY` key replaced with `OMNIROUTE_API_KEY`
  — a dedicated Omniroute inference key (`sk-...`, minted via `POST
  /api/keys`, name `openclaw`), matching the existing dedicated-virtual-
  key-per-consumer pattern LiteLLM used.

### argus (`kubernetes/apps/ai/argus/app/`)

- `helmrelease.yaml`: `holmes.modelList.auto` and `.litellm` entries (both
  currently `api_base: http://litellm.ai.svc.cluster.local:4000/v1`, `model:
  litellm_proxy/coder-large`) → `api_base:
  http://omniroute.ai.svc.cluster.local:20128/v1`, `model:
  llamaswap/coder-large` (Omniroute doesn't use LiteLLM SDK's
  `litellm_proxy/` chaining prefix — that was specifically a LiteLLM-calling-
  LiteLLM convention; Omniroute's own `<prefix>/<model>` scheme replaces it
  directly, confirmed Task 9). `config.model: litellm` stays pointing at the
  same map key (renaming the key itself is optional cosmetic cleanup, not
  required — keep the diff mechanical).
- `secret-holmesgpt.sops.yaml`: `LITELLM_API_KEY` → `OMNIROUTE_API_KEY`,
  dedicated key minted with name `argus-holmes`.

### openviking (`kubernetes/apps/ai/openviking/app/helmrelease.yaml`)

- `embedding.dense`: `api_base` → `http://omniroute.ai.svc.cluster.local:20128/v1`,
  `model: "embedding"` → `"llamaswapapu/embedding"`, `api_key` var renamed
  `OPENVIKING_EMBEDDING_API_KEY` (same name, new value — dedicated Omniroute
  key). `allow_metadata_override: true` stays (same underlying weights/
  dimension, route changed again).
- `vlm`: `api_base` → Omniroute, `model: "vlm"` → `"llamaswapapu/vlm"`,
  same key-rotation treatment for `OPENVIKING_VLM_API_KEY`.
- `rerank` block: **removed entirely** (see scope decision above), along
  with its explanatory comment block and the `OPENVIKING_RERANK_API_KEY`
  secret entry (no longer referenced by anything).
- `secret.sops.yaml`: `OPENVIKING_EMBEDDING_API_KEY`/`OPENVIKING_VLM_API_KEY`
  rotated to dedicated Omniroute keys (names `openviking-embedding`/
  `openviking-vlm`); `OPENVIKING_RERANK_API_KEY` deleted.

## LiteLLM teardown — exact footprint

- `kubernetes/apps/ai/litellm/` (entire directory: `ks.yaml`,
  `app/{httproute.yaml,kustomization.yaml,litellmproxy.yaml,secret.sops.yaml,
  models/*}`)
- `kubernetes/apps/ai/litellm-operator/` (entire directory)
- `kubernetes/apps/databases/cloudnative-pg/cluster/litellm-database.yaml`
  (CNPG `Database` CR) + `litellm-role-secret.sops.yaml` + the `litellm`
  entry in `cluster.yaml`'s `managed.roles` (lines ~62-83) — **verify at
  execution time** whether deleting the `Database` CR actually drops the
  underlying Postgres database or just deregisters CNPG's management of it
  (CNPG semantics differ by version/config; don't assume either way, check
  the CRD's reclaim behavior or drop the DB explicitly via `psql` if the CR
  deletion alone doesn't).
- `kubernetes/apps/ai/kustomization.yaml`: remove `./litellm/ks.yaml` and
  `./litellm-operator/ks.yaml` from `resources:`, update the top comment
  block (currently describes LiteLLM as "reintroduced as a cluster-internal-
  only mirror" — needs to describe Omniroute as the gateway instead).
- `docs/runbooks/dragonflydb-db-allocation.md`: db4 row → `_free_` again
  (mirrors the exact db1 pattern from Phase 1's own allocation).
- No Grafana dashboards or alerts reference `litellm` currently (confirmed
  via repo-wide grep) — nothing to clean up there.
- Top-level `CLAUDE.md` and `kubernetes/apps/ai/CLAUDE.md`: any prose
  describing LiteLLM as the gateway gets updated to describe Omniroute
  (deferred to a dedicated doc-sweep task at the end, so it reflects the
  final post-teardown state rather than being edited twice).

## Ordering / safety

Teardown happens **only after** both openviking (live-verified) and
openclaw/argus (dry-run-verified) are confirmed pointing at Omniroute
successfully — never remove LiteLLM while anything might still reference
it. This mirrors Phase 1's own "never deploy blind" discipline.

## Out of scope

- BYOK cloud provider credentials (Phase 1 backlog item #11, unrelated to
  this switchover).
- Re-enabling openclaw/argus themselves — Phase 2 only makes their config
  correct-when-inert, per the scope decision above; actually turning them
  back on is a separate decision for whenever the user wants it.
- Rerank-via-Omniroute — backlog item, revisit if upstream changes the SSRF
  filter behavior.
