# HolmesGPT Auto-Diagnose + Remediation Loop — Design

Date: 2026-08-18
Status: Approved, pending implementation plan
Predecessor: `2026-08-15-holmesgpt-integrations-design.md` (toolset integrations, 6/8 landed — c14.7 Discord bridge and c14.8 API hardening remain open)

## Context

HolmesGPT is deployed (`kubernetes/apps/ai/holmesgpt/`) as a cluster-internal
HTTP API + bundled Operator. It can already investigate using Kubernetes API
state, VictoriaMetrics, VictoriaLogs, Grafana dashboards, and cluster-level
Postgres stats (`postgres17-stats`, `pg_monitor`-scoped). It has **zero write
capability** — no Remediation toolset, no GitHub toolset, no Discord output —
and its LLM backend config is currently broken (points at a retired llama-swap
alias). This spec closes that: gives HolmesGPT a working model, wider
diagnosis toolsets, a Discord front-end with human-in-the-loop approval, and
gated write/remediation capability that respects this cluster's Flux GitOps
model (kubectl mutations to Flux-managed fields get reverted on next
reconcile unless git also changes).

Research basis: live audit of `kubernetes/apps/ai/holmesgpt/`,
`kubernetes/apps/ai/litellm/`, `kubernetes/apps/ai/llama-swap*/`,
`kubernetes/apps/ai/openclaw/` (as the fleet's other proven agentic-tool-use
consumer), `kubectl get clusterrole/clusterrolebinding/sa` live against the
cluster, and HolmesGPT's builtin-toolsets docs
(holmesgpt.dev/latest/data-sources/builtin-toolsets/) cross-referenced
against what's actually configured. Argus (`github.com/olivecasazza/argus`)
evaluated as the Discord bridge — see Corrections.

### Corrections to stale assumptions

- **LiteLLM is back.** `ai/CLAUDE.md`'s "litellm+omniroute removed 2026-08-14"
  narrative is stale. LiteLLM was reintroduced 2026-08-18 in front of both
  llama-swap instances (`kubernetes/apps/ai/litellm/`), and openclaw already
  routes through it (`litellm/coder-large`). HolmesGPT's `helmrelease.yaml`
  still routes direct to llama-swap with a dead model alias (`openai/tool-agent`,
  retired in the 2026-08-17/18 llama-swap restructure) — every investigation
  is currently either failing or silently mis-routing.
- **c14.7's blocker (`bifrost`) is superseded, not resolved.** The prior spec
  deferred the Discord bridge pending a separate unbuilt repo
  (`j0sh3rs/bifrost`, beads `bifrost-a7g`/`bifrost-44f`). This spec replaces
  that plan with `argus`, an existing open-source Helm chart that already
  implements the Alertmanager→Holmes→Discord bridge plus human-approval
  buttons — no custom app code to write. `bifrost` beads should be marked
  superseded when this lands.
- **`coder-large`'s context window grew.** The prior spec's implicit
  assumption (from `ai/CLAUDE.md`) that `coder-large` tops out at 16k ctx is
  stale — it's 49152 now (2026-08-17 restructure), which is why routing
  HolmesGPT to it directly is viable again without a `ContextWindowExceededError`
  repeat.

## Goal

1. Fix HolmesGPT's LLM routing so investigations work at all.
2. Widen diagnosis toolsets: Cilium/Hubble, Helm.
3. Harden the API (mandatory once write access exists, not optional).
4. Deploy `argus` as the Discord front-end with human-in-the-loop approval,
   reusing the existing HolmesGPT deployment rather than argus's bundled one.
5. Add gated remediation: Kubernetes Remediation MCP toolset (transient
   actions) + GitHub MCP toolset (durable, git-represented fixes), every
   mutating action gated behind an argus Discord Approve/Reject/Revise.

## Non-goals (explicitly deferred, tracked as separate beads)

- **Unattended/unapproved remediation.** Every write action — transient
  kubectl mutation or git commit — requires a human Approve click via argus's
  Discord bot buttons in this pass. Removing the approval gate is a future,
  separately-approved decision once the loop has a track record.
- **Grafana MCP toolset (~57 tools: Loki/Alerting/Incidents/OnCall/Sift/Pyroscope).**
  This cluster already covers logs (VictoriaLogs) and metrics (VictoriaMetrics)
  through non-Grafana toolsets; `grafana/dashboards` (already enabled) covers
  dashboard discovery. Standing up a self-hosted `grafana-mcp` server is not
  justified without a concrete need for Sift/OnCall/Incidents specifically.
- **Table-level Postgres access.** `holmesgpt_ro` stays `pg_monitor`-scoped
  (cluster stats only). Per-app database access is a separate, incremental
  decision per the predecessor spec — not reopened here.
- **`HelmRepository`→`OCIRepository` migration for the `holmes` chart.**
  Opportunistic only if Robusta publishes an OCI artifact; not blocking.
- **argus's own GitHub remediation-PR-context feature** (`GITHUB_TOKEN` +
  `REPO_MAPPINGS` on the forwarder). HolmesGPT does its own git commits via
  its own GitHub MCP toolset/token (see Components) — argus's parallel
  GitHub integration is redundant for this design and left unconfigured.

## Components

### 1. Fix LLM routing

`kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`, replace the dead
`modelList` block:

```yaml
modelList:
  litellm:
    model: litellm/coder-large
    api_base: http://litellm.ai.svc.cluster.local:4000/v1
    api_key: "{{ env.LITELLM_MASTER_KEY }}"
```

`LITELLM_MASTER_KEY` added to `holmesgpt-secrets`, mirroring openclaw's
existing `litellm` provider auth pattern (`kubernetes/apps/ai/openclaw/app/configmap.yaml`).
Matches the fleet's only confirmed tool-calling-safe model
(`coder-large`/Qwen3-Coder-30B-A3B, 49152 ctx) already proven under a
comparable agentic-toolset load by openclaw.

### 2. Cilium/Hubble toolset

```yaml
toolsets:
  cilium/core:
    enabled: true
  hubble/observability:
    enabled: true
```

Cluster side is ready (Hubble relay healthy at
`hubble-relay.kube-system.svc.cluster.local:80`, `hubble.enabled: true` in
`kubernetes/apps/kube-system/cilium/app/helm/values.yaml`). Before enabling,
verify the `holmes` chart's pod image ships `cilium` and `hubble` CLI
binaries (`kubectl -n ai exec deploy/holmesgpt-holmes -- cilium version && hubble version`).
If absent, this toolset silently fails its own preflight check — note as a
known limitation and file a follow-up rather than shipping broken config.

### 3. Helm toolset

```yaml
toolsets:
  helm/core:
    enabled: true
```

Verify post-deploy that the chart's default ClusterRole actually covers
Helm's required read set (secrets, pods, services, configmaps, PVCs,
deployments, statefulsets, daemonsets, jobs, cronjobs, ingresses, namespaces)
— `kubectl get clusterrole -l app.kubernetes.io/name=holmes -o yaml`. Extend
via `values.customClusterRoleRules` if the chart supports it and defaults
fall short; this toolset also grants **secrets read**, which is new exposure
worth weighing given the pod's existing bash-toolset credential-theft path
(see Component 4) — hardening that path first is a hard prerequisite, not a
nice-to-have, once Helm's secrets access is added.

### 4. API hardening (mandatory prerequisite for remediation)

- `HOLMES_API_KEY` set (new `holmesgpt-secrets` key) and required on
  `/api/chat` — closes the unauthenticated-Service exposure.
- NetworkPolicy in the `ai` namespace scoping ingress to `holmesgpt-holmes:80`
  down to only the argus-forwarder pod (plus whatever else legitimately
  calls Holmes). Follows the existing scoped-ingress pattern in
  `kubernetes/apps/ai/mcpjungle/app/networkpolicy-kelos.yaml`.
- Restrict the `bash` toolset off `extended` allowlist (or disable it
  entirely — VictoriaLogs/Prometheus/Grafana/Postgres toolsets now cover
  most of what raw shell access was providing). This closes the concrete,
  reproducible path flagged in `home-ops-c14.8`: `extraEnvVarsSecrets`
  renders `GRAFANA_API_KEY`/`POSTGRES_CONNECTION_URL` as env vars in the
  same container bash executes in; `cat /proc/self/environ` exfiltrates
  both today with zero approval gate.

This closes `home-ops-c14.8`. Do this **before** Component 6 (remediation
toolset) ships — adding write capability on top of an unauthenticated,
credential-leaking Service is not an acceptable sequencing.

### 5. Deploy argus

New app `kubernetes/apps/ai/argus/`, Helm chart from `olivecasazza/argus`.
Key values:

```yaml
holmes:
  enabled: false   # reuse the existing HolmesGPT deployment, don't double-deploy
forwarder:
  holmesUrl: http://holmesgpt-holmes.ai.svc.cluster.local:80
  investigateSeverities: "critical,warning"
  dedupeTtlSec: 3600
  discordEnabled: true
  discordChannels:
    default: ""      # filled from secret env vars
    critical: ""
    warning: ""
holmesOperator:
  enabled: true       # ScheduledHealthCheck CRDs -- proactive, not just alert-triggered
```

New SOPS secret `argus-forwarder` (`ai` namespace): `DISCORD_WEBHOOK` (+
per-severity overrides), `DISCORD_BOT_TOKEN` + `DISCORD_CONTROL_CHANNEL_ID`
(enables the Approve/Reject/Revise buttons — required, since this design has
no unapproved-write path). `podAnnotations: reloader.stakater.com/auto: "true"`
per repo convention (consumes a Secret). Since `forwarder.holmesUrl` now
requires `HOLMES_API_KEY` auth (Component 4), pass it through as an
additional forwarder header/env — check argus's forwarder.py for its
outbound-auth-header support during implementation; if absent, this is a
small upstream-adjacent patch to the ConfigMap-mounted script (no image
build needed, per argus's stock `python:3.13-slim` + ConfigMap pattern).

Alertmanager (`kube-prometheus-stack`, already deployed) gets a
`webhook_configs` receiver pointed at `http://argus-forwarder.ai.svc.cluster.local/webhook`.

This closes `home-ops-c14.7`. Mark `bifrost-a7g`/`bifrost-44f` superseded.

### 6. Kubernetes Remediation MCP toolset (transient actions)

New, separate identity — **do not** extend the existing
`holmesgpt-holmes-service-account` (which stays read-only):

```yaml
# new ServiceAccount + ClusterRole + ClusterRoleBinding: holmesgpt-remediation
rules:
  - apiGroups: ["apps"]
    resources: [deployments, statefulsets, daemonsets, replicasets]
    verbs: [get, list, watch, patch, update, delete]
  - apiGroups: [""]
    resources: [pods, pods/exec, pods/eviction]
    verbs: [get, list, watch, create, delete]
  - apiGroups: [""]
    resources: [nodes]
    verbs: [get, list, watch, patch]
  - apiGroups: ["batch"]
    resources: [jobs, cronjobs]
    verbs: [get, list, watch, patch, update, delete]
# explicitly no secrets, no cluster-admin
```

```yaml
toolsets:
  kubernetes/remediation:
    enabled: true
    config:
      require_approval: true   # run_kubectl_command always gated; do not pre-approve mutating verbs
```

Scope: transient/self-healing actions only — rollout-restart a pod, cordon/
uncordon/drain a node, delete a stuck pod, scale a workload. These don't
persist against Flux reconcile because they don't touch git-tracked desired
state (a pod restart isn't drift; a replica-count change is — see Component 7).

### 7. GitHub MCP toolset (durable, git-represented fixes)

New fine-grained PAT, scoped to `j0sh3rs/home-ops` only (Contents + Pull
requests: read/write, Metadata: read-only) — **do not reuse openclaw's
token**. New SOPS secret `holmesgpt-github-secret`.

```yaml
toolsets:
  github/core:
    enabled: true
    config:
      github_personal_access_token: "{{ env.GITHUB_PERSONAL_ACCESS_TOKEN }}"
```

Routing rule (documented in HolmesGPT's system-prompt customization, exact
mechanism — custom instructions vs toolset description — decided during
implementation): any fix that would drift back on the next Flux reconcile
(replica counts, resource limits, config values, anything that lives in a
`kubernetes/apps/**` manifest) is **not** applied via `kubectl patch`.
Instead HolmesGPT edits the manifest and commits directly to `main` via the
GitHub toolset — gated behind the same Discord approval as Component 6.
Flux picks it up on next reconcile. No PR-review step in this pass (explicit
choice — see brainstorming transcript); revisit if a bad auto-generated
commit ever lands.

## Secrets summary

- `holmesgpt-secrets` (`ai` namespace) additions: `LITELLM_MASTER_KEY`,
  `HOLMES_API_KEY`, `GITHUB_PERSONAL_ACCESS_TOKEN`.
- New `argus-forwarder` secret (`ai` namespace): `DISCORD_WEBHOOK` (+
  per-severity), `DISCORD_BOT_TOKEN`, `DISCORD_CONTROL_CHANNEL_ID`.
- New `holmesgpt-remediation` ServiceAccount — no secret, RBAC only.
- All consuming workloads carry `reloader.stakater.com/auto: "true"` per
  repo convention.

## Validation plan

Sequenced — each phase's validation gates the next, do not skip ahead:

1. **Routing fix (Component 1):** `kustomize build`, `flux build --dry-run`,
   deploy, `GET /api/model` confirms `litellm/coder-large` resolves, then a
   real `/api/chat` probe confirms a non-error investigation.
2. **New toolsets (2, 3):** `holmes toolset refresh` equivalent (chart
   redeploy), then probe questions per toolset exercising a real tool call
   (inspect `tool_calls[]` in the response, not just that `analysis` came
   back non-empty — Holmes can fabricate a plausible answer via `kubernetes/core`
   alone if a new toolset silently failed to register). E.g. "show recent
   Hubble flow drops in the `ai` namespace" / "what's the Helm release
   history for `holmesgpt` itself?"
3. **Hardening (4):** confirm `/api/chat` now 401s without `HOLMES_API_KEY`;
   confirm the `cat /proc/self/environ` credential-exfil path no longer
   works (bash restricted/disabled); confirm NetworkPolicy blocks an
   unrelated in-cluster pod from reaching `holmesgpt-holmes:80`.
4. **Argus (5):** synthetic Alertmanager webhook POST to the forwarder,
   confirm Discord message arrives with correct severity routing and
   dedupe; confirm `HOLMES_API_KEY` auth is correctly passed through.
5. **Remediation + git (6, 7):** induce a deliberately low-stakes incident
   (e.g. scale a throwaway test deployment to 0 and let it get flagged).
   Verify full loop: alert → investigation → Discord post → Approve click →
   action executes (transient) or commit lands on `main` (durable) → Flux
   reconciles clean, `flux get ks -A` shows no drift/failure.

## Open items / inputs needed from user before implementation

- Discord bot token + control channel ID for argus's HITL buttons — manual
  creation in the Discord developer portal, same category as prior manual
  credential steps in this epic.
- GitHub fine-grained PAT for the new `holmesgpt-github-secret` — manual
  creation, scoped as specified in Component 7.
- Confirm during implementation whether argus's `forwarder.py` supports
  passing an outbound auth header to Holmes (needed once Component 4's
  `HOLMES_API_KEY` lands) — small ConfigMap-script patch if not, since
  there's no image build step to work around.

## Follow-up work (tracked as separate beads, not this epic)

- Unattended remediation (no approval gate) — future work, only after this
  loop has a track record.
- Grafana MCP toolset (Sift/OnCall/Incidents/Pyroscope) — only if a concrete
  need arises.
- `HelmRepository`→`OCIRepository` migration for the `holmes` chart —
  opportunistic.
- PR-review step for durable git commits, if an auto-generated commit ever
  causes a problem.
