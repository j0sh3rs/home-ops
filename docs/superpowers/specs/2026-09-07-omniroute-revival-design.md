# Omniroute Revival — Design

Date: 2026-09-07
Status: Approved, pending implementation plan (Phase 1 only)
Related: `kubernetes/apps/ai/litellm/` (current gateway, being replaced),
`kubernetes/apps/ai/llama-swap/`, `kubernetes/apps/ai/llama-swap-apu/` (local
inference backends, unchanged), `docs/runbooks/dragonflydb-db-allocation.md`,
commit `2a8936e5` (Aug 2026 removal of both litellm and the original
omniroute — see "Why this was removed before" below)

## Context

The user does not currently have enough local hardware to run a full model
fleet, and wants cloud-provider fallback/coverage without losing the local
llama-swap tier. LiteLLM (`kubernetes/apps/ai/litellm/`) is the current
gateway in front of the two llama-swap instances (`llama-swap` on
`bigboi-jms-01`/dGPU, `llama-swap-apu` on `bee-jms-03`/iGPU) — it has zero
cloud provider configuration today; it's purely a local routing/alias/cache
layer. The goal of this project is to replace LiteLLM everywhere with
Omniroute (`docker.io/diegosouzapw/omniroute`, upstream
`github.com/diegosouzapw/OmniRoute`), which additionally offers 40+ cloud
provider integrations, BYOK API-key routing, free-tier aggregation, and
reuse of CLI-subscription OAuth sessions (Claude Code / Codex / Copilot) as
an extra "free" capacity tier — solving the hardware gap.

### Why this was removed before

Omniroute was not archived — it was deleted outright in `2a8936e5` (2026-08-14),
the same commit that removed LiteLLM. LiteLLM came back two commits later
(`f8975b11`) as a local-only mirror; Omniroute never did. The commit message
is explicit about why: "omniroute scraped Claude/Gemini web UIs via
Playwright," dropped so the `ai` namespace would have "zero third-party LLM
dependency."

Reading the deleted `helmrelease.yaml` (`git show 2a8936e5^:kubernetes/apps/ai/omniroute/app/helmrelease.yaml`)
confirms two distinct ToS-boundary mechanisms, both called out in the file's
own comments at the time:

- A `-web` image variant bundling Playwright/Chromium to scrape
  `claude-web`/`gemini-web`/`claude-turnstile` as chat-completion backends.
- A `cliproxyapi` sidecar (`docker.io/eceasy/cli-proxy-api`, upstream
  `router-for-me/CLIProxyAPI`) that repurposes Claude Code / Codex / Gemini
  CLI OAuth *sessions* as a generic OpenAI-compatible backend — the comment
  in that file states plainly this is "explicitly a ToS-boundary tool
  against Anthropic/OpenAI/Google, not a neutral proxy."

Current upstream docs (v3.8.51, fetched 2026-09-07) still describe the same
CLIProxyAPI-style mechanism — "Subscription-based: Claude Code (OAuth),
OpenAI Codex (OAuth), GitHub Copilot (OAuth)" — alongside a much larger set
of legitimate BYOK API-key/free-tier providers (Groq, DeepSeek, Together,
Fireworks, Cerebras, Mistral, xAI, Perplexity, Cohere, NVIDIA NIM, and
others), a built-in MCP server (SSE/streamable-HTTP/stdio transports), and
an OpenAI-compatible `/v1` endpoint.

**Decision (explicit, user-approved):** revive Omniroute with the
CLIProxyAPI sidecar included, wired to Claude Code and Codex subscriptions.
This is a knowing acceptance of the same ToS-boundary risk that got the old
deployment pulled — real risk of a provider flagging or banning the account
tied to those sessions. Not a neutral technical choice; recorded here so it
isn't silently re-litigated or silently forgotten later.

**Correction found during Phase 1 planning (2026-09-07):** Copilot was
originally in scope alongside Claude Code and Codex, but CLIProxyAPI does
not actually support it — its upstream README's own provider table lists
Kimi, OpenAI/Codex, Anthropic/Claude Code, Google/Gemini CLI, and xAI/Grok
only. Omniroute's own `CLI-INTEGRATIONS.md` doesn't cover Copilot either;
the only Copilot-adjacent thing it mentions is an unrelated VS Code
extension ("OmniCopilot"), not a headless gateway backend. **User decision:
drop Copilot from Phase 1, leave a TaskMaster backlog item to revisit if
upstream ever adds support.** Not a silent scope cut — recorded here and in
memory.

## Scope decisions (from brainstorming Q&A)

- **CLIProxyAPI subscriptions**: Claude Code + Codex only (Copilot dropped —
  see correction above; upstream doesn't support it).
- **BYOK cloud providers**: none configured yet — provider slots get wired
  in Omniroute but left without real credentials until the user has actual
  keys. Does not block Phase 1 or Phase 2.
- **MCP server registration**: both locally in this HolyClaude container's
  Claude Code config (`~/.claude/settings.json` or `.mcp.json`) and as a
  repo-committed project-level MCP config, once Omniroute's MCP endpoint is
  confirmed reachable.
- **LiteLLM disposition after cutover**: full removal (HelmRelease,
  `litellm-operator`, Postgres `litellm` DB/role, DragonflyDB db4 freed,
  HTTPRoute, any Grafana dashboard/alert references) — mirrors exactly how
  the old omniroute was torn down, not a cold-standby fallback.
- **openviking is not being replaced, evaluated, or otherwise touched by
  this project.** It remains exactly what it is today — its only change is
  the same mechanical backend-URL repoint every other consumer gets in
  Phase 2 (`litellm.ai.svc.cluster.local:4000` → Omniroute). A separate,
  later comparison between openviking and "headroom" is out of scope here;
  noted in memory so it isn't lost, not actioned as part of this design.
- **Configuration-as-code requirement (explicit, user-added):** nothing in
  this deployment may exist only as unbacked, dashboard-clicked state. Every
  piece of Omniroute/CLIProxyAPI configuration must be either (a) declared
  in git as a HelmRelease value or SOPS-encrypted Secret, or (b) persisted
  on a PVC that Velero's default wildcard daily backup covers (no
  `velero.io/exclude-from-backup` label on either Omniroute PVC). This
  matches the precedent already established for HolyClaude's own Claude Code
  OAuth session (`docs/superpowers/specs/2026-09-01-holyclaude-helm-deployment-design.md`):
  interactive-login state that can't be expressed as a git-tracked secret
  still gets durability through a backed-up PVC, never left to live only in
  a running container.

## Architecture — Phase 1 (parallel install, no consumer cutover)

New `kubernetes/apps/ai/omniroute/` app, same skeleton as the deleted
deployment, updated for v3.8.51:

- **bjw-s app-template** (confirmed still no upstream Helm chart — GitHub
  tree listing at `release/v3.8.51` has no `charts/`/`helm/` dir), two
  containers:
  - `app` — image `docker.io/diegosouzapw/omniroute:3.8.50` (confirmed
    published on Docker Hub 2026-08-27; no `3.8.51` image exists yet even
    though the docs branch is ahead of the image release — pin to `3.8.50`,
    not `3.8.51`). The `-web` variant (bundles Playwright/Chromium for
    `gemini-web`/`claude-web`/`claude-turnstile` scraping) is deliberately
    NOT used — those providers were never in the accepted scope, only
    CLIProxyAPI's CLI-session reuse was. A `runner-cli` Dockerfile target
    also exists upstream (bakes Codex/Claude Code/Droid/OpenClaw CLI support
    directly into the main image, no sidecar needed) but Docker Hub does not
    publish a `-cli` tag — only buildable from source — so it's out of scope
    for Phase 1 (would require standing up our own build/publish pipeline).
    Gateway, dashboard, MCP server. Ports 20128 (dashboard/HTTP) and 20129
    (API); MCP transports (SSE, streamable-HTTP, stdio) exposed off the same
    container.
  - `cliproxyapi` — image `docker.io/eceasy/cli-proxy-api:v6.9.7` (the
    version OmniRoute's own reference `docker-compose.yml` explicitly pins
    its sidecar integration to — not Docker Hub's "latest" tag, which may be
    ahead of what's actually tested against this Omniroute release; see
    "Corrections found during Task 6 validation" below for why version
    tracking wasn't the issue that mattered here). Sidecar reusing CLI
    subscription OAuth sessions — Claude Code **and Codex, both via
    CLIProxyAPI's own native `--claude-login`/`--codex-login` OAuth flows**
    (see Copilot correction above; no separate mechanism for Codex — see
    correction below for why an initial attempt at one was reverted). Config
    is file-only, resolved from the working directory (`/CLIProxyAPI/`) when
    no `--config` flag is passed — confirmed by reading
    `router-for-me/CLIProxyAPI`'s actual `Dockerfile` (`WORKDIR /CLIProxyAPI`,
    default `CMD ["./CLIProxyAPI"]`) and `cmd/server/main.go`'s config
    resolution logic directly, not assumed.
- **Config as code / backup** (see requirement above, made concrete):
  - Static config (ports, secret refs, JWT/API-key-secret/init password,
    `REDIS_URL`, cliproxyapi `config.yaml` contents) → SOPS-encrypted
    `omniroute-secrets` Secret, git-tracked, mounted read-only. Matches the
    old pattern exactly (`envFrom.secretRef`, plus a `secret`-type
    persistence entry mounting `cliproxy-config.yaml` into the sidecar).
  - Interactive-login-only state (CLIProxyAPI's OAuth session tokens for
    Claude Code/Codex/Copilot, Omniroute's own SQLite DB holding
    dashboard-configured combos/endpoints/provider entries) → PVCs
    (`omniroute-data` for `/app/data`, `cliproxyapi-data` for
    `/root/.cli-proxy-api`), both `openebs-hostpath` (matches upstream's
    own no-NFS-with-SQLite stance), both `retain: true`, neither carrying a
    Velero exclusion label — so the default wildcard daily backup covers
    them without any extra Velero config needed.
- **DragonflyDB db1** — freed 2026-08-14 per the allocation runbook,
  reassigned to Omniroute's distributed rate limiter. Runbook table updated
  in the same change.
- **HTTPRoute** `omniroute.68cc.io` on `traefik-external-gateway` +
  `authentik-forwardauth` Middleware, VIP `192.168.35.15` — needed for the
  dashboard and for the CLI OAuth login flows themselves (device-flow
  callbacks typically need a reachable redirect).
- **Reloader**: `reloader.stakater.com/auto: "true"` on both
  `global.annotations` and the controller, matching every other app-template
  deployment in this repo.

### Corrections found during Task 6 (live deploy) validation — 2026-09-07

The Phase 1 implementation plan (written after this spec, in a separate
pass) introduced a third container, `codex-app-server`, using the main
Omniroute image to drive the Codex CLI's own JSON-RPC app-server as a
lower-ToS-risk alternative to CLIProxyAPI's session-replay for Codex
specifically. **This was never reconciled back into this spec, and turned
out to be unbuildable**: direct inspection of OmniRoute's actual Dockerfile
shows `@openai/codex` is installed only in the `runner-cli` build stage,
which is not published to Docker Hub (confirmed: only bare `X.Y.Z` and
`X.Y.Z-web` tags exist) — upstream's own `docker-compose.yml` comment
claiming "Codex CLI baked into omniroute:base" is inaccurate relative to
the actual current Dockerfile. Building `runner-cli` ourselves would mean
standing up a custom image build/publish pipeline, well outside Phase 1's
scope. **Reverted to this spec's original design**: CLIProxyAPI handles
both Claude Code and Codex via its own native OAuth flows, exactly as
originally specified above — no third container.

Separately, the same validation pass found the `cliproxyapi` container's
initially-planned `command` override pointed at a fabricated, never-verified
binary path (`/cli-proxy-api`) — the real binary is
`/CLIProxyAPI/CLIProxyAPI`, and the image's own default `CMD` already runs
it correctly from the right working directory. Fix: don't override
`command`/`args` on this container at all — matches how the `app` container
in the same pod already works (no override there either).

A third bug surfaced on the *next* deploy attempt (after both fixes above
landed): `cliproxyapi`'s liveness/readiness probes hit `/v1/models`
unauthenticated, but that route requires an API key once real `api-keys`
are configured in `cliproxy-config.yaml` (which this deployment always
does, correctly — `cliproxyapi` is reachable cluster-wide via its own
Service, not just pod-local, so requiring auth is real defense-in-depth,
not something to relax). Confirmed via direct inspection of
`router-for-me/CLIProxyAPI`'s route registration
(`internal/api/server_routes.go`): `/v1` carries `AuthMiddleware`, a bare
`GET /healthz` exists unauthenticated on current `main` — but checking the
actual pinned `v6.9.7` tag specifically shows `/healthz` doesn't exist at
that version at all (different route file layout entirely). What does exist
unauthenticated at `v6.9.7` is a bare `GET /` (returns a small static JSON
body, registered outside any auth group). **Fix: point both probes at `/`
instead of `/v1/models`**, staying on the `v6.9.7` pin rather than
upgrading just to get `/healthz`.

All three corrections share one pattern worth flagging for future
Phase 0/plan work on this project: each came from copying a detail out of
OmniRoute's or CLIProxyAPI's own reference config/compose/docs without
verifying it against *this deployment's specific configuration choices*
(no web-scraping providers, real API-key auth enabled, a specific older
version pin). Reference configs assume their own defaults; ours differ on
purpose in each case, and that's exactly where the assumptions broke.

## Phase 1 validation checklist

1. Pin the real current image (see Open Items) and deploy standalone —
   `litellm` keeps serving all three consumers throughout; no cutover yet.
2. Confirm dashboard, `/v1` OpenAI-compatible endpoint, and the MCP endpoint
   are all reachable from this HolyClaude container.
3. Prove MCP-driven control: add and remove a test provider/combo via MCP
   tool calls, confirm it persists in the dashboard and survives a pod
   restart (i.e., actually lands on the PVC, not just in memory).
4. Configure Omniroute's local-provider slots to mirror the current 8
   llama-swap aliases (`coder-large`, `frontier-chat`, `reasoner`, `router`,
   `embedding`, `chat`, `vlm`, `rerank`) against both llama-swap endpoints —
   recreates LiteLLM's local-routing role inside Omniroute.
5. Run the OAuth login flows for Claude Code and Codex against the
   `cliproxyapi` sidecar; confirm sessions survive a pod restart (PVC-backed).
6. Leave BYOK cloud provider slots wired but empty — backlog item, not a
   Phase 1 blocker.

## Architecture — Phase 2 (switchover, separate follow-up spec/plan)

Deferred to a follow-up cycle once Phase 1 reveals the real image tag, real
MCP tool surface, and real model-id addressing scheme (Omniroute uses
`<provider>/<model>` / combo names, not LiteLLM's bare aliases — not
assumed here). Captured now as scope, not as a detailed plan:

- Repoint the 3 real consumers from `litellm.ai.svc.cluster.local:4000` to
  Omniroute:
  - `openclaw` — `configmap.yaml` `providers.litellm.baseUrl`
  - `openviking` — 3 refs (embedding, vlm, rerank `api_base`) — mechanical
    URL repoint only, per the scope decision above
  - `argus`/holmesgpt — `modelList.litellm` entry
- Full LiteLLM teardown per the scope decision above.
- Update `CLAUDE.md`, `kubernetes/apps/ai/CLAUDE.md`,
  `docs/runbooks/dragonflydb-db-allocation.md` to match new architecture.

## Resolved during Phase 1 planning (2026-09-07)

- **Image tags**: `docker.io/diegosouzapw/omniroute:3.8.50` (app) +
  `docker.io/eceasy/cli-proxy-api:v6.9.7` (cliproxyapi, corrected from an
  earlier `v7.2.153` guess — see "Corrections found during Task 6
  validation" above for why the specific version pin, not "latest",
  matters here) — both confirmed live on Docker Hub. See Architecture
  section above for the `-web`/`runner-cli` rationale.
- **MCP/management auth model**: Omniroute has four credential families —
  dashboard JWT cookie (from `INITIAL_PASSWORD` login), a local CLI
  machine-ID token, a **scoped access token** (`oma_live_...`, generated via
  Dashboard Settings → Access Tokens or `omniroute connect`, with
  `read`/`write`/`admin` scopes), and inference API keys (`sk-...` for
  `/v1/*`). The MCP server and management API calls use the scoped access
  token (`Authorization: Bearer oma_live_...`) — this is what gets minted
  for Claude Code's MCP registration, at `admin` scope for config control.
  Per the config-as-code requirement, this token goes in the same
  SOPS-encrypted `omniroute-secrets` Secret, not left unbacked.

## Resolved during Task 9 (2026-09-08)

- **Local provider architecture**: llama-swap/llama-swap-apu are wired in as
  two `/api/provider-nodes` entries (`type: openai-compatible`), not
  `/api/providers` connections directly — that endpoint only supports one
  connection per built-in catalog `provider` id (a second POST with
  `provider: "openai"` silently overwrote the first instead of creating a
  second entry, confirmed empirically). Provider-nodes support arbitrary
  named custom OpenAI-compatible backends via a `prefix`. Each node then
  still needs a companion `/api/providers` credential POSTed with
  `provider: "<node-id>"` (even for a no-auth backend — `apiKey:
  "not-needed"` accepted) before routing actually works; skipping this step
  produces `No active credentials for provider: <node-id>` on every request.
  Both `/api/providers`'s and `/api/provider-nodes`'s request-body docs in
  `docs/openapi.yaml` are stale relative to the real Zod validators
  (`createProviderSchema`/`createProviderNodeSchema` in
  `src/shared/validation/schemas/provider.ts`) — read the source, not the
  spec, for exact required fields going forward.
- **Model-id addressing scheme, confirmed**: `<prefix>/<model>`, e.g.
  `llamaswap/coder-large` — a bare alias (`coder-large`) 400s with `Unable
  to determine provider for model 'coder-large'. Use a provider/model
  prefix... or ensure the model is added as a combo entry.` All 8 aliases
  (`coder-large`, `frontier-chat`, `reasoner` → `llamaswap/*`; `router`,
  `embedding`, `chat`, `vlm`, `rerank` → `llamaswapapu/*`) verified live
  against `/v1/chat/completions` with real completions, except `rerank`,
  which correctly routes but 500s on that endpoint shape — rerank models
  need a dedicated request shape (mirrors LiteLLM's own `infinity/rerank`
  special-casing for the exact same model); resolving that exact shape is a
  Phase 2 concern when openviking is actually repointed, not a Phase 1
  blocker.
- **Inference auth is a separate layer from management auth**: `/v1/*`
  endpoints need an `sk-...` key from `POST /api/keys`, not the `oma_live_...`
  management token from Task 7 — the two are enforced by different code
  paths (`isValidApiKey`/`getApiKeyMetadata` vs `evaluateAccessTokenAuth`).

## Open items remaining for Phase 1 implementation

- **Copilot**: dropped from Phase 1 scope (see correction above) — backlog
  item in TaskMaster to revisit if upstream ever adds support.

## Out of scope

- Any BYOK cloud provider credentials — deferred until the user has real
  keys.
- openviking vs. "headroom" comparison — separate future initiative.
- Phase 2's detailed implementation plan — written after Phase 1 lands and
  resolves the open items above.
