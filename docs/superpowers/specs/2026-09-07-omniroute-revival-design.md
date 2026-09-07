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
CLIProxyAPI sidecar included, wired to Claude Code, Codex, and Copilot
subscriptions. This is a knowing acceptance of the same ToS-boundary risk
that got the old deployment pulled — real risk of a provider flagging or
banning the account tied to those sessions. Not a neutral technical choice;
recorded here so it isn't silently re-litigated or silently forgotten later.

## Scope decisions (from brainstorming Q&A)

- **CLIProxyAPI subscriptions**: Claude Code + Codex + Copilot, all three.
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

- **bjw-s app-template** (still no upstream Helm chart — to be re-verified,
  see Open Items), two containers:
  - `app` — gateway, dashboard, MCP server. Ports 20128 (dashboard/HTTP)
    and 20129 (API), per the old convention; MCP transports (SSE,
    streamable-HTTP, stdio) exposed off the same container.
  - `cliproxyapi` — sidecar reusing CLI subscription OAuth sessions.
    Config is file-only (`-config` flag, no env var support, confirmed by
    the old deployment's source read of `cmd/server/main.go`).
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
5. Run the OAuth login flows for Claude Code, Codex, and Copilot against the
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

## Open items for Phase 0/Phase 1 implementation (not resolved by this design)

- **Exact current image/tag**: v3.8.51 docs favor `npm install -g omniroute`
  / Electron / headless-server-mode over a monolithic Docker image; the old
  `docker.io/diegosouzapw/omniroute:X.Y.Z-web` tag family needs
  re-verification, not reuse-by-assumption.
- **CLIProxyAPI image**: old deployment used `docker.io/eceasy/cli-proxy-api`
  (the old HelmRelease comment documents that OmniRoute's own
  docker-compose.yml pointed at a nonexistent `ghcr.io/router-for-me/*`
  image) — re-verify this is still the correct publish target at the
  version paired with Omniroute v3.8.51.
- **Model-id / combo addressing scheme** for the Phase 2 consumer repoint —
  determine against the real running Phase 1 instance.
- **MCP endpoint auth** — confirm whether the MCP server needs a management
  token (per the OpenCode-plugin doc's mention of "management tokens...
  required separately for enrichment features") and how that token is
  supplied without living outside git/PVC per the config-as-code requirement.

## Out of scope

- Any BYOK cloud provider credentials — deferred until the user has real
  keys.
- openviking vs. "headroom" comparison — separate future initiative.
- Phase 2's detailed implementation plan — written after Phase 1 lands and
  resolves the open items above.
