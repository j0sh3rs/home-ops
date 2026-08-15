# HolmesGPT Integration Setup — Design

Date: 2026-08-15
Status: Approved, pending implementation plan
Predecessor: `2026-08-04-holmesgpt-poc-deployment-design.md` (base POC deployment)

## Context

HolmesGPT is deployed (`kubernetes/apps/ai/holmesgpt/`) as a cluster-internal HTTP
API + bundled Operator, LLM backend `llama-swap` (`coder-large`). Per the POC
spec it ships with only the default toolsets (`kubernetes/core`,
`kubernetes/logs`, `bash`, `internet`, `connectivity_check`, `skills`), plus
`robusta` and `prometheus/metrics` explicitly disabled. No data-source
integrations beyond bare Kubernetes API access are wired up. This spec covers
enabling the toolsets that give HolmesGPT real observability/data reach into
this cluster's actual stack, based on a full research pass over HolmesGPT's
toolset catalog (github.com/HolmesGPT/holmesgpt, chart `holmes` v0.39.0) cross
referenced against this repo's current state (not the CLAUDE.md description,
which has drifted — see Corrections below).

### Corrections to stale assumptions

- **Prometheus is not "mid-migration"** — it's already decommissioned
  (`home-ops-8bb` stage 2). `kube-prometheus-stack` now runs with
  `prometheus.enabled: false`, kept only for Alertmanager +
  node-exporter + kube-state-metrics + the prometheus-operator CRDs.
  `vmagent`/`vmalert` (VictoriaMetrics) are the real metrics path, remote
  writing to `https://metrics.68cc.io` — an externally-hosted VictoriaMetrics
  instance reachable over the LAN, not an in-cluster `VMSingle`/`VMCluster`.
- **There is no in-cluster `victoria-logs` app** — CLAUDE.md's description of a
  `kubernetes/apps/monitoring/victoria-logs/ks.yaml` deployment with a
  `victoria-logs-vector` DaemonSet does not match the repo. What actually
  exists: a `vector` app (Helm chart `vector`, role Agent) shipping
  `kubernetes_logs` to `https://logs.68cc.io/insert/elasticsearch/` (bulk
  ingest, `AccountID`/`ProjectID` headers `"0"`/`"0"`) — same externally-hosted
  VictoriaLogs instance pattern as metrics.
- **mcpjungle/omega-mcp are currently disabled** (commented out in
  `kubernetes/apps/ai/kustomization.yaml` as of `1286f6e9`) — MCP-aggregator
  wiring for HolmesGPT is not actionable right now.

## Goal

Enable four HolmesGPT toolsets so investigations can actually query this
cluster's real metrics, logs, dashboards, and primary database, instead of
only Kubernetes API state:

1. `prometheus/metrics` (subtype `victoriametrics`) → `https://metrics.68cc.io`
2. `victorialogs` → `https://logs.68cc.io`
3. `grafana/dashboards` → `https://grafana.68cc.io`
4. `database` (Postgres) → `postgres17-rw.databases.svc.cluster.local:5432`

## Non-goals (explicitly deferred, tracked as separate beads)

- **Discord output bridge.** HolmesGPT's HealthCheck/ScheduledHealthCheck
  CRDs only natively push to Slack or PagerDuty; this cluster's only notify
  channel is Discord. A bridge (Alertmanager webhook → Holmes `/api/chat` →
  Discord webhook) is custom application code, not a manifest change — it
  reopens the `bifrost`/`chaski` scope explicitly cut on 2026-08-04 (separate
  repo `j0sh3rs/bifrost`, paused beads `bifrost-a7g`/`bifrost-44f`, not
  reachable from this repo's beads DB). File a tracking bead only; no
  implementation here.
- **Security hardening** (`HOLMES_API_KEY` auth, NetworkPolicy scoping
  ingress). Explicitly deferred — keep the POC's originally-accepted risk
  posture for now. File a tracking bead so it isn't forgotten now that Holmes
  also touches metrics/logs/Grafana/DB credentials, not just K8s+bash+internet.
- **DragonflyDB/Redis, CrowdSec, Tetragon toolsets.** No native HolmesGPT
  toolset exists for any of the three (confirmed via full-repo code search —
  zero matches for `redis`, `falco`, `tetragon`, `crowdsec` in
  github.com/HolmesGPT/holmesgpt). Tetragon is already indirectly covered:
  it exports Prometheus metrics and has its own Grafana dashboard, both
  reachable once toolsets 1 and 3 above are live. CrowdSec/DragonflyDB would
  require a hand-rolled `type: http` custom toolset — not off-the-shelf, not
  in scope here.
- **MCP aggregator wiring** (`mcp_servers.mcpjungle`) — mcpjungle is
  currently disabled cluster-wide; nothing to wire up yet.
- **HealthCheck/ScheduledHealthCheck/TriggeredHealthCheck resources.** Still
  none defined (per the original POC's non-goals) — this pass only expands
  what toolsets are available to on-demand `/api/chat` investigations.

## Components

### 1. Prometheus/VictoriaMetrics toolset

`kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`, replace the existing
disabled block:

```yaml
toolsets:
  prometheus/metrics:
    enabled: true
    config:
      prometheus_url: https://metrics.68cc.io
      subtype: victoriametrics
```

No secret — `vmagent`/`vmalert` remote_write to the same URL today with no
auth headers configured, so the endpoint is assumed reachable
unauthenticated from in-cluster pods (LAN-routed, not behind Cloudflare
tunnel/Authentik). Verify empirically rather than trusting this assumption —
see Validation.

### 2. VictoriaLogs toolset

New block in the same `toolsets:` values:

```yaml
toolsets:
  victorialogs:
    enabled: true
    config:
      api_url: https://logs.68cc.io
      headers:
        AccountID: "0"
        ProjectID: "0"
```

Same no-auth assumption as metrics, same empirical verification requirement.

### 3. Grafana dashboards toolset

```yaml
toolsets:
  grafana/dashboards:
    enabled: true
    config:
      api_url: https://grafana.68cc.io
      api_key: "{{ env.GRAFANA_API_KEY }}"
```

Requires a **manual pre-step**: mint a Grafana service-account token
(Viewer role) via the Grafana UI/API — Grafana's `grafana.yaml` instance
config uses `auth.proxy` (Authentik `X-authentik-email` header) for human
login, there is no existing API key to reuse, and this can't be scripted
without an admin credential (same category of manual input as the original
omniroute API key in the POC spec). Token goes into a new
`kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml`, key
`GRAFANA_API_KEY`, referenced into the pod as an env var so the Jinja2
`{{ env.GRAFANA_API_KEY }}` interpolation resolves it.

### 4. CloudNative-PG Postgres toolset

Highest-risk change — touches the shared `postgres17` `Cluster` CR
(`kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml`), which also
backs other apps (e.g. memini/RAG). No existing precedent in this repo for
CNPG's declarative `spec.managed.roles` — today the cluster only sets
`enableSuperuserAccess: true` / `superuserSecret`.

Plan:

```yaml
# cluster.yaml addition
spec:
  managed:
    roles:
      - name: holmesgpt_ro
        ensure: present
        login: true
        passwordSecret:
          name: holmesgpt-db-creds
```

CNPG creates the role but does **not** grant it access to existing
databases/schemas — that needs an explicit one-off `GRANT SELECT` step
(e.g. a `postInitApplicationSQL`-equivalent or a scoped one-shot `Job`
running `psql` as the CNPG app user, granting `SELECT` on whichever specific
database(s) HolmesGPT should be able to inspect — not a blanket grant across
every database on the shared cluster). Exact target database(s) TBD during
implementation — needs a decision on which app databases are actually useful
for Holmes to see versus unnecessary blast radius.

`holmesgpt-secrets` values addition:

```yaml
toolsets:
  database:
    enabled: true
    config:
      connection_url: "postgresql://holmesgpt_ro:{{ env.POSTGRES_RO_PASSWORD }}@postgres17-rw.databases.svc.cluster.local:5432/<target_db>"
```

`POSTGRES_RO_PASSWORD` sourced from `holmesgpt-db-creds` (the CNPG-managed
role's password Secret) into the Holmes pod's env.

### Secrets summary

New `kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml` (`holmesgpt-secrets`):
`GRAFANA_API_KEY`, `POSTGRES_RO_PASSWORD` (mirrors `holmesgpt-db-creds`'
password, or reference that Secret directly via `envFrom`/`secretKeyRef`
instead of duplicating — decide during implementation). Existing
`podAnnotations: reloader.stakater.com/auto: "true"` on the HelmRelease
already covers rotation for both.

## Validation plan (per toolset)

1. `kustomize build kubernetes/apps/ai/holmesgpt/app` — manifests render.
2. `task sops:verify` — new/changed secret files properly encrypted.
3. `flux build kustomization holmesgpt --path kubernetes/apps/ai/holmesgpt --dry-run`.
4. Post-deploy: `kubectl -n ai get pods`, confirm no crash/auth failure in
   `kubectl -n ai logs`.
5. **Live tool-invocation check** (the real verification — pod-healthy alone
   proves nothing about whether a toolset actually works):
   `kubectl -n ai port-forward svc/holmesgpt-holmes 8080:80`, then
   `curl -X POST localhost:8080/api/chat -H 'Content-Type: application/json' -d '{"ask": "<probe question for this toolset>", "stream": false}'`
   and inspect the response's `tool_calls[]` array for a call into the
   specific toolset (not just that `analysis` came back non-empty — Holmes
   can fabricate a plausible-sounding answer via `kubernetes/core` alone if
   the new toolset silently failed to register). Probe questions per
   toolset:
   - Prometheus: "what's current CPU usage across nodes, per Prometheus metrics?"
   - VictoriaLogs: "show me recent error-level logs from the `ai` namespace"
   - Grafana: "what dashboards exist in the monitoring folder?"
   - Postgres: "what tables exist in the `<target_db>` database?"
6. `GET /api/model` and `/api/info` as cheap pre-checks before the above
   (confirms the server booted with the new toolset config parsed, before
   spending an LLM call on the real probe).

## Open items / inputs needed from user before implementation

- Grafana service-account token (Viewer role) — manual creation, same
  category as the omniroute key in the POC spec.
- Which target database(s) the Postgres `GRANT SELECT` should cover — needs
  an explicit choice, not a blanket grant.

## Follow-up work (tracked as separate beads, not this epic)

- Discord bridge (blocked on resuming `j0sh3rs/bifrost`).
- Security hardening: `HOLMES_API_KEY` + NetworkPolicy.
- Revisit DragonflyDB/CrowdSec custom `type: http` toolsets if a concrete
  need arises.
