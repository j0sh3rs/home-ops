# OpenClaw Automation Integrations — Design

Date: 2026-08-15
Status: Approved, pending implementation plan
Related: `2026-06-15-local-code-automation-loop-design.md` (predecessor — the
original Kelos/local-code-automation design, since removed 2026-08-14 in favor
of consolidating on OpenClaw as the sole code-automation agent, per CLAUDE.md's
"Decisions explicitly rejected" section)

## Context

OpenClaw (`kubernetes/apps/ai/openclaw/`, image `ghcr.io/openclaw/openclaw:2026.7.1`)
is deployed as a single-instance Gateway with cluster-admin RBAC, routed to
llama-swap for inference, with a `kube-mcp` sidecar, `gh` CLI on the PVC, the
`memini`/`memory-wiki` memory plugins, `workboard`, and four custom
investigation skills (`prometheus`, `victorialogs`, `kubernetes-events`,
`flux`). It is reachable today only via chat (`openclaw.68cc.io`, Authentik
forwardAuth) — there is no autonomous or event-triggered work loop.

This spec covers turning it into an actual automation feedback loop: pick up
alerts/failures/scheduled work on its own, propose fixes as PRs, and be
reachable from Discord/Signal — without expanding its footprint into new
internet-exposed surface.

### Research basis

A four-way parallel research pass against OpenClaw's official docs
(`docs.openclaw.ai`) and GitHub repo (`github.com/openclaw/openclaw`),
cross-checked against this repo's actual `configmap.yaml`/`helmrelease.yaml`,
found:

- `skills.allowBundled: []` in `configmap.yaml` disables **every** bundled
  OpenClaw skill — including `gh-issues` (OpenClaw's own issue→PR autopilot:
  fetch issues, dedup against open PRs, spawn up to 8 concurrent sub-agent
  workers via `agentToAgent`, branch/commit/push/PR with `Fixes owner/repo#N`,
  supports `--watch` poll mode and `--cron` spawn-and-exit mode) and `github`
  (a thin `gh` CLI wrapper skill). `agentToAgent` is already `enabled: true`,
  `git`+`gh`+`GITHUB_TOKEN` already work. This is a one-line unlock for
  something that already does most of what the old Kelos pipeline did — just
  as an in-process poll/cron loop instead of a Kubernetes-CRD-triggered pod.
- `hooks: { enabled: true, path: "/hooks", token: ... }` is live but
  `hooks.mappings` is empty — `POST /hooks/agent` is reachable and tokened but
  nothing calls it. In-cluster callers (Alertmanager, Flux's
  notification-controller) can reach `openclaw.ai.svc.cluster.local:18789`
  directly — Kubernetes Services bypass Traefik/Authentik entirely, so wiring
  in-cluster triggers needs **no new HTTPRoute, no new DNS, no new tunnel
  exposure**.
- GitHub cannot safely push webhooks straight at OpenClaw: it has no
  HMAC/signature verification, only a shared bearer token
  (`openclaw/openclaw#4977`, "Enhance webhook authentication", closed **not
  planned**). A real-time GitHub-push trigger would require a hand-built
  signature-verifying relay plus OpenClaw's first-ever internet-facing route
  (every existing route is on `traefik-internal-gateway`, LAN-only, no
  Cloudflare/tunnel record). **Out of scope for this epic** — see Non-goals.
- `codex` plugin is `enabled: true` but no `openai/*` model or API key exists
  anywhere in this deployment or namespace — dead config that contradicts the
  `ai` namespace's explicit self-hosted-only policy.
- `@openclaw/discord` is an official, bidirectional channel plugin (post +
  receive, slash commands, DMs) — not a one-way webhook. Signal is listed
  among OpenClaw's natively-supported channel types in its architecture docs;
  the exact plugin ID needs confirming against the live ClawHub registry at
  implementation time (`openclaw plugins search signal`).
- **This repo's own CLAUDE.md is stale on the observability stack**, discovered
  independently while researching the Alertmanager-trigger design (also
  flagged same-day in `2026-08-15-holmesgpt-integrations-design.md`):
  `kube-prometheus-stack` runs with `prometheus.enabled: false` (Prometheus
  itself was decommissioned under `home-ops-8bb`) — there is no
  `prometheus-operated.monitoring.svc.cluster.local:9090` to query. There is
  also no in-cluster `victoria-logs` app — logs ship out via the `vector`
  DaemonSet to an **externally-hosted** VictoriaLogs at
  `https://logs.68cc.io`, and metrics live at an externally-hosted
  VictoriaMetrics (`vmagent`/`vmalert` remote-write) at
  `https://metrics.68cc.io`. **OpenClaw's existing `prometheus` and
  `victorialogs` skills (`kubernetes/apps/ai/openclaw/app/resources/skills-configmap.yaml`)
  currently instruct the agent to query dead in-cluster endpoints.** Any
  automated alert-triage or scheduled audit built on this deployment would
  silently fail its own investigation step until these two skills are
  corrected — this is a prerequisite fix, folded into this epic rather than
  filed separately, since it directly blocks the Alertmanager-trigger and
  scheduled-audit goals below.

## Goals

Build the automation feedback loop the user asked for, scoped to what they
explicitly approved:

1. Unlock `gh-issues`/`github` bundled skills (chat-driven + scheduled sweep).
2. Correct the stale `prometheus`/`victorialogs` skills so triage actually
   works against the real endpoints.
3. Add a second, narrowly-scoped agent identity (`automation`) for anything
   hook- or cron-triggered, distinct from the fully-privileged default
   cluster-admin identity used for human chat sessions.
4. Wire three in-cluster triggers via `hooks.mappings` + Gateway
   automations/cron: Alertmanager alerts, Flux reconcile failures, and
   scheduled hygiene audits (bd stale/orphans, `sops:verify`, a `gh-issues
   --cron` sweep).
5. Add the Discord channel plugin (and Signal if its plugin ID checks out) so
   the operator can converse with and receive notifications from OpenClaw
   outside the web UI.
6. Decide the fate of the dead `codex` plugin.

**Autonomy contract (per user decision):** every trigger in this epic ends at
"opened a PR" or "posted a finding." Nothing auto-merges. Every write path
that could touch this repo goes through normal PR review + existing CI
(`flux-local`, kubeconform, `sops:verify`).

## Non-goals (deferred to a follow-on epic)

- **SearXNG deployment + `@openclaw/searxng-plugin`** — real infrastructure
  (new app, not just config), needed for the agent to look things up on the
  open web. `configmap.yaml` already anticipates this
  (`tools.web.search.enabled: false`, comment: "No in-cluster search provider
  deployed yet"). Valuable once the core loop above is running and worth
  extending, but independent of it.
- **GitHub-webhook relay for real-time (vs. polled) issue triggering** — the
  one integration in the research set that requires OpenClaw's first
  internet-exposed route and a hand-built HMAC-verifying relay in front of it
  (native support is closed not-planned upstream). Should only be considered
  once the poll-based `gh-issues --cron` sweep from this epic has run long
  enough to be trusted.
- **Prometheus `diagnostics-prometheus`/`diagnostics-otel` plugins** — useful
  once hook/cron runs are frequent enough that Gateway-internal run
  success/failure metrics matter. Revisit after this epic proves out.
- **Third-party Smart PR Review plugin** — an automated second-opinion review
  pass on PRs `gh-issues` opens. Worth adding once `gh-issues` is producing
  real PRs to review; community-maintained (lower trust than bundled/official
  plugins), so it should get its own source read + explicit approval, not
  bundled into this epic's rollout.
- **Multi-repo scope** — GITHUB_TOKEN and triggers stay scoped to
  `j0sh3rs/home-ops` for this epic. User deferred picking additional repos;
  extending scope is a config-only follow-up once named.

## Decisions

| Question | Decision |
|---|---|
| Autonomy | Propose via PR only. Never auto-merge. |
| Triggers | Alertmanager/Prometheus-rule alerts, Flux reconcile failures, scheduled audits (incl. a `gh-issues --cron` sweep), Discord/Signal conversations. **Not** raw "any GitHub issue" auto-pickup beyond the scheduled sweep — the sweep is filtered (see below), not "watch everything." |
| Repo scope | `home-ops` only for this epic; broaden later by name. |
| Notifications | Discord (reuse the operator's existing Discord presence; Alertmanager's own Discord webhook is separate and unaffected). |
| `codex` plugin | Disable (`codex: { enabled: false }`) — no `openai/*` model configured anywhere, and leaving it on contradicts the namespace's self-hosted-only policy for no functional benefit today. Re-enable explicitly if a future use needs its media-understanding capability. |

## Architecture

### Agent identities

Today `agents.ownership` is implicit (a single default `main` identity with
the deployment's full cluster-admin RBAC, kube-mcp, exec, and filesystem
access). This epic switches to `agents.ownership: "explicit"` and adds a
second identity:

- **`main`** (existing behavior, unchanged) — human chat sessions via
  `openclaw.68cc.io` and Discord/Signal DMs. Full tool access, as today.
- **`automation`** (new) — the target for every hook-triggered and cron-fired
  run in this epic. Minimal tool profile: no `kube-mcp`, no raw filesystem
  access outside its own workspace, `exec` restricted to `git`/`gh` for the
  `gh-issues`/`github` skills it needs. This follows OpenClaw's own documented
  guidance for untrusted/automated input ("route through a purpose-built
  agent with a minimal tool allowlist rather than the primary, fully
  privileged agent") and keeps a mis-fired alert-triage or cron job from
  having cluster-admin blast radius.

Bindings route Discord/Signal channel traffic to `main` (it's the human
conversational surface); `hooks.mappings` entries and `automations` (cron)
jobs explicitly target `automation`.

### Triggers → `automation` agent

```
Alertmanager (severity=critical, or a broader rule set — TBD in plan)
  --webhookConfigs receiver--> POST openclaw.ai.svc.cluster.local:18789/hooks/alertmanager
  (Bearer token = shared hooks token)
  --hooks.mappings "alertmanager" (messageTemplate)--> agentId: automation, isolated session
  --on completion, deliver: true--> Discord channel (notify)

Flux notification-controller (Kustomization/HelmRelease events, status != Ready)
  --Provider(webhook)/Alert CR--> POST openclaw.ai.svc.cluster.local:18789/hooks/flux
  --hooks.mappings "flux" (messageTemplate)--> agentId: automation, isolated session
  --on completion, deliver: true--> Discord channel (notify)

Gateway automations (cron, in-process, no network hop)
  --scheduled entry: hygiene audit (bd stale/orphans, sops:verify)--> agentId: automation
  --scheduled entry: gh-issues --cron sweep (interval TBD, label-filtered,
    excludes risk/critical paths per guardrail below)--> agentId: automation
  --on completion, deliver: true--> Discord channel (notify)

Discord / Signal (operator-initiated)
  --channel plugin, bound to main--> agentId: main, full access, human session
```

All three trigger types deliver their result to the same Discord channel so
the operator has one place to see "openclaw did something" regardless of
source — this is what turns items 4-5 in the Goals section into an actual
feedback loop rather than silent background activity.

### `gh-issues --cron` guardrail

`gh-issues` has no native path-based exclusion. Since `automation` is the
identity running it (not `main`'s cluster-admin), and PRs always require
human merge, the residual risk is bounded — but as defense in depth, the
`automation` agent's bootstrap instructions (`AGENTS.md` for that identity)
will explicitly direct it to open the PR as a draft and stop, rather than
attempt a fix, for any issue whose scope touches
`kubernetes/apps/flux-system/`, `talos/`, or any `*.sops.yaml` file. This is
a prompt-level guardrail, not a hard technical block — call this out
explicitly as a residual risk in the implementation plan's verification
section, and test it directly (file a scratch issue that asks for a
`flux-system` change, confirm the agent drafts-and-stops rather than pushing
a completed change).

### Stale-skills fix

`prometheus.md` and `victorialogs.md` in
`kubernetes/apps/ai/openclaw/app/resources/skills-configmap.yaml` get
rewritten to query the real endpoints:
- Metrics: `https://metrics.68cc.io/api/v1/query` (VictoriaMetrics,
  Prometheus-compatible API) instead of the dead
  `prometheus-operated.monitoring.svc.cluster.local:9090`.
- Logs: `https://logs.68cc.io/select/logsql/query` (VictoriaLogs LogsQL)
  instead of the nonexistent `victoria-logs-server.monitoring.svc.cluster.local:9428`.
- Alerting state still comes from the in-cluster Alertmanager
  (`alertmanager-operated.monitoring.svc.cluster.local:9093`), which is
  unaffected by the Prometheus decommission — this part of the existing skill
  stays correct.

Exact auth/reachability from inside the `ai` namespace pod (LAN-only vs. needs
a token) is unconfirmed from static analysis — this is a verification step in
the implementation plan, not an assumption baked into the skill text.

## Components & files touched

- `kubernetes/apps/ai/openclaw/app/configmap.yaml` — `skills.allowBundled`,
  `agents.ownership: "explicit"` + `automation` entry + `bindings`,
  `hooks.mappings` (×2: alertmanager, flux), `automations` (cron) block,
  `plugins.entries.discord` (+ `signal` if confirmed), `codex.enabled: false`.
- `kubernetes/apps/ai/openclaw/app/resources/skills-configmap.yaml` — fix
  `prometheus.md`/`victorialogs.md` endpoints.
- `kubernetes/apps/ai/openclaw/app/secret.sops.yaml` — add
  `DISCORD_BOT_TOKEN` (+ Signal linking secret if applicable).
- A shared hooks-auth value reachable by both OpenClaw and the two trigger
  sources: either duplicate `OPENCLAW_HOOKS_TOKEN` into the `cluster-secrets`
  Secret (consumed via `${VARIABLE_NAME}` `postBuild.substituteFrom`, the
  existing repo-wide pattern per CLAUDE.md) so `alertmanagerconfig.yaml` and
  the new Flux `Provider` can reference it without hand-copying a SOPS value
  across namespaces, or duplicate the literal encrypted value into each
  consumer's own `secret.sops.yaml`. Prefer the `cluster-secrets` route —
  finalize in the implementation plan.
- `kubernetes/apps/monitoring/kube-prometheus-stack/app/alertmanagerconfig.yaml`
  — add a `webhookConfigs` receiver + route alongside the existing
  `discordConfigs` receiver.
- `kubernetes/apps/flux-system/flux-instance/app/` — new `Provider` (type
  `webhook`) + `Alert` CRs (notification.toolkit.fluxcd.io) for
  Kustomization/HelmRelease failure events, alongside the existing
  `receiver.yaml` (which is Flux's *inbound* GitHub-push receiver — an
  unrelated, already-working mechanism; this new Provider/Alert pair is
  Flux's *outbound* event-notification path).
- Bootstrap file for the `automation` agent identity (e.g.
  `AGENTS.md`-equivalent scoped to that identity) encoding the draft-and-stop
  guardrail above.

## Security considerations

- `automation` identity gets a minimal tool profile specifically so a
  misconfigured `hooks.mappings` entry, a spoofed-but-token-valid hook call,
  or a broad `gh-issues` sweep cannot reach kube-mcp or arbitrary shell —
  worst case is a bad PR, not a cluster mutation.
- Hooks auth is a shared bearer token, not per-source HMAC — acceptable here
  because both trigger sources (Alertmanager, Flux notification-controller)
  are in-cluster callers on the same trust boundary as everything else in
  this namespace, not internet-facing. This is explicitly why the
  GitHub-webhook option (an internet-facing caller with no HMAC support) is a
  Non-goal.
- No new HTTPRoute, no new DNS record, no new tunnel exposure in this epic —
  every new network path is ClusterIP-to-ClusterIP.
- `gh-issues --cron` sweep: PR-only, never merges; scoped to `home-ops`;
  draft-and-stop guardrail on risk/critical paths (residual prompt-level risk,
  noted above).
- Discord bot token is a new secret — SOPS-encrypted like every other secret
  in this repo, scoped to `openclaw-secret`.

## Error handling

- Alertmanager retries webhook receivers per its own backoff policy if
  OpenClaw's pod is briefly unavailable (e.g. mid-restart) — no custom retry
  logic needed on the OpenClaw side.
- Flux `Alert`/`Provider` delivery failures show up in
  `notification-controller` logs/events — covered by the existing `flux`
  investigation skill once it's correctly scoped to the `automation` identity
  too (or left on `main` for human-driven Flux debugging — decide in plan).
- A hook call that hits `503` (admission timeout) per OpenClaw's own
  documented behavior means the run was cancelled, not queued — acceptable
  for alert/Flux-failure triage (a subsequent firing/re-check will retrigger
  it) but worth surfacing in Discord if it happens repeatedly (possible
  capacity signal).
- Hooks token compromise → rotate via `task sops:edit
  file=kubernetes/apps/ai/openclaw/app/secret.sops.yaml` (and the
  `cluster-secrets`-shared copy if that path is chosen), same as any other
  secret rotation in this repo.

## Verification plan (high-level; detailed steps go in the implementation plan)

1. Bundled skills unlock — `openclaw skills list` (or equivalent CLI/API
   check against the running pod) shows `gh-issues`/`github` enabled; a chat
   session can run `gh issue list` successfully.
2. Stale-skills fix — confirm `metrics.68cc.io`/`logs.68cc.io` are reachable
   and return data from inside the `ai` namespace pod before shipping the
   corrected skill text.
3. `automation` identity — confirm it exists as a distinct entry
   (`agents.ownership: explicit`) and that its tool profile genuinely
   excludes kube-mcp/broad exec (test: ask it, via a hook call, to do
   something only `main` should be able to do; confirm refusal/absence of the
   tool).
4. Alertmanager trigger — fire a synthetic test alert, confirm a run appears
   (workboard and/or Discord), confirm it used the `automation` identity.
5. Flux-failure trigger — intentionally break a scratch/non-critical
   Kustomization (not a risk/critical one), confirm the `Alert` fires and
   OpenClaw picks it up.
6. Scheduled audits — confirm `automations`/cron entries are listed and fire
   on schedule; confirm the hygiene audit and the `gh-issues --cron` sweep
   both run and report to Discord.
7. `gh-issues --cron` guardrail — file a scratch issue whose fix would touch
   `kubernetes/apps/flux-system/` or a `*.sops.yaml` file; confirm the
   `automation` identity drafts-and-stops instead of completing the change.
8. Discord (and Signal, if wired) — send a message, confirm a reply; confirm
   hook/cron completions post notifications.
9. `codex: false` — confirm no regression to existing model routing
   (`llamaswap/coder-large` unaffected).
10. Full `flux-local`/kubeconform/`sops:verify` pass on every changed
    manifest before merge, per repo convention.

## Rollout sequencing

1. Bundled skills unlock (`gh-issues`, `github`) + stale-skills fix +
   `codex: false` — pure config, no new exposure, immediately useful from
   chat.
2. `automation` agent identity (prerequisite for everything below — nothing
   hook/cron-triggered should run as `main`).
3. Discord channel plugin (needed so steps 4-5 have somewhere to notify).
4. Alertmanager hook (in-cluster only, safer of the two external triggers).
5. Flux-failure hook (in-cluster only).
6. Scheduled audits + `gh-issues --cron` sweep, with the draft-and-stop
   guardrail tested before the sweep is left running unattended.
7. Signal channel plugin, if its ClawHub plugin ID confirms available at
   implementation time — otherwise file as a follow-up bead, not a blocker
   for the rest of the epic.

## Open risks carried into implementation

- Exact `clawhub:` install-locator syntax (`clawhub:<package>` vs.
  `clawhub:@author/package>`) is inconsistent between what the docs show and
  what this repo's existing `memini` init container uses — confirm live via
  `openclaw plugins search` against the running `2026.7.1` pod before writing
  any install command into a HelmRelease init container.
- `hooks.mappings` templating/signature-verification schema should be
  confirmed against the running pod's own config schema/CLI help, not just
  the docs site, before finalizing the Alertmanager/Flux mapping entries.
- Whether the bundled `session-memory` hook (already enabled) and the
  `memini` plugin memory slot double-write the same information — worth
  checking before cron/hooks increase session volume.
- Metrics/logs endpoint reachability + auth from inside the `ai` namespace
  pod is unconfirmed until tested directly (see Verification step 2).
