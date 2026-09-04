# HolmesGPT Integration Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable four HolmesGPT toolsets (`prometheus/metrics`, `victorialogs`, `grafana/dashboards`, a Postgres `database` toolset) on the existing HolmesGPT deployment so investigations can query this cluster's real metrics, logs, dashboards, and Postgres cluster health — not just Kubernetes API state.

**Architecture:** Four independent `toolsets:` entries added to the existing `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml` values block, each pointing at an already-running backend (`https://metrics.68cc.io`, `https://logs.68cc.io`, `https://grafana.68cc.io`, `postgres17-rw.databases.svc.cluster.local`). Grafana and Postgres need new credentials (a manually-minted Grafana service-account token; a new CNPG-managed read-only Postgres role) delivered via a new `holmesgpt-secrets` Secret and `extraEnvVarsSecrets`. The Postgres toolset is scoped to cluster-level stats only (`pg_monitor` role) — zero per-app-database data access, since the HolmesGPT Service stays unauthenticated for this pass. This work was tracked as an epic with two follow-up items (Discord bridge, API/NetworkPolicy hardening) filed as tracking-only, no implementation.

**Tech Stack:** FluxCD (`HelmRelease` values, CNPG `Cluster` CR `spec.managed.roles`), SOPS/age secrets, `kustomize`/`flux build`/`task sops:verify` for validation. Toolset config schema confirmed directly against the HolmesGPT chart's pinned `0.39.0` `values.yaml` and the corresponding `docs/data-sources/builtin-toolsets/{prometheus,victorialogs,grafanadashboards,database-postgresql}.md` pages (raw GitHub, not paraphrased).

**Spec:** `docs/superpowers/specs/2026-08-15-holmesgpt-integrations-design.md`

## Global Constraints

- Prometheus itself is already decommissioned (`home-ops-8bb` stage 2) — the real metrics backend is VictoriaMetrics at `https://metrics.68cc.io` (externally hosted, LAN-reachable, no in-cluster `VMSingle`/`VMCluster`). Use `subtype: victoriametrics`, not `subtype: prometheus`.
- VictoriaLogs lives at `https://logs.68cc.io`, multi-tenant headers `AccountID: "0"` / `ProjectID: "0"` (matches what the `vector` app already sends).
- The `subtype` field on the `prometheus/metrics` toolset is a **top-level field, sibling to `enabled`/`config`** — not nested inside `config:`. Confirmed against `docs/data-sources/builtin-toolsets/prometheus.md`.
- The Postgres toolset is identified by `type: database` on a custom-named toolset key, not a fixed toolset name `database:`. Confirmed against `docs/data-sources/builtin-toolsets/database-postgresql.md`.
- Postgres scope is **cluster-level stats only**: `pg_monitor` built-in role, connect to the `postgres` maintenance database. No `GRANT` on any individual app database. Do not expand this scope without a new decision.
- Grafana requires a manually-minted service-account token (Viewer role) — this cannot be scripted; a human step is required before Task 2 can finish.
- Discord bridge and API/NetworkPolicy hardening are explicitly **out of scope** for this plan — file tracking-only follow-up items, no manifest/code changes.
- All secrets SOPS-encrypted before commit — `task sops:verify` must pass after every task that touches a `*.sops.yaml` file.
- When editing (not creating) an existing `*.sops.yaml` file, use the `sops-edit-then-encrypt` skill rather than hand-rolled decrypt/edit/encrypt commands.
- The user has explicitly authorized executing this plan end-to-end, including `git push` and `task flux:reconcile-ks`/`task flux:reconcile-hr` at the points specified below — conservative git policy otherwise still applies (don't push/reconcile things this plan doesn't call for).

---

## File Structure

- **Modify:** `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml` — add `extraEnvVarsSecrets`, `grafana/dashboards`, `prometheus/metrics` (flip enabled), `victorialogs`, and a `database`-typed toolset entry (Tasks 2, 3, 4, 6).
- **Create:** `kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml` — `holmesgpt-secrets` Secret, key `GRAFANA_API_KEY` (Task 2), later amended with `POSTGRES_CONNECTION_URL` (Task 5).
- **Modify:** `kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml` — add `spec.managed.roles` entry for `holmesgpt_ro` (Task 5).
- **Create:** `kubernetes/apps/databases/cloudnative-pg/cluster/holmesgpt-role-secret.sops.yaml` — `holmesgpt-db-creds` Secret (CNPG basic-auth type) (Task 5).
- **Modify:** `kubernetes/apps/databases/cloudnative-pg/cluster/kustomization.yaml` — register the new secret (Task 5).
- **Modify:** `CLAUDE.md` — correct the stale Prometheus/VictoriaLogs description, document the new toolsets (Task 8).

---

### Task 2: Grafana dashboards toolset

**Files:**
- Create: `kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml`
- Modify: `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: Secret `holmesgpt-secrets` (key `GRAFANA_API_KEY`) — Task 5 later amends this same file to add `POSTGRES_CONNECTION_URL`. `extraEnvVarsSecrets` list on the HelmRelease — a shared top-level key Task 5/6 do not need to touch again once it exists.

- [ ] **Step 1: Mint a Grafana service-account token**

Manual step (cannot be scripted — needs an interactive admin session). Grafana's `auth.proxy` config forces Authentik OIDC login for normal users; the chart's own `grafana.yaml` comment notes the login form can still be reached via `https://grafana.68cc.io/login?disableLoginForm=false` for the built-in admin account (credential in the `grafana-admin-password` Secret, `monitoring` namespace) if Authentik SSO doesn't have admin rights.

1. Log into `https://grafana.68cc.io` as an admin.
2. Navigate to **Administration → Users and access → Service accounts**.
3. **Add service account** — name `holmesgpt`, role **Viewer**.
4. On the new service account, **Add service account token** — no expiration needed for an internal tool, but set one if your posture prefers it.
5. Copy the token value (starts `glsa_`) — you will not be able to see it again. Keep it on hand for Step 2; do not paste it into any file yet.

- [ ] **Step 2: Write the plaintext secret**

Create `kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: holmesgpt-secrets
stringData:
  GRAFANA_API_KEY: "<PASTE_TOKEN_FROM_STEP_1>"
```

- [ ] **Step 3: Encrypt it**

```bash
task sops:encrypt-file file=kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml
```

Expected: `stringData.GRAFANA_API_KEY` becomes an `ENC[AES256_GCM,...]` block, a `sops:` footer is appended.

- [ ] **Step 4: Verify encryption**

```bash
task sops:verify
```

Expected: passes, no errors for the new file.

- [ ] **Step 5: Add the toolset block and env wiring to the HelmRelease**

Edit `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`. Find:

```yaml
    # Disable the Robusta SaaS-backed toolset — this cluster has no Robusta
    # account, and leaving it enabled just produces noisy "not configured"
    # log lines at startup.
    #
    # bash (extended allowlist) and internet toolsets are left at chart
    # defaults (enabled) for this POC. Combined with the cluster-wide
    # read-only ClusterRole and an unauthenticated in-cluster Service,
    # this means anything in-cluster that can reach holmesgpt-holmes:80
    # can drive shell/internet-capable investigation. Acceptable for a
    # cluster-internal POC; revisit with a NetworkPolicy or auth layer
    # if this graduates past POC (see home-ops-4rm).
    toolsets:
      robusta:
        enabled: false
      prometheus/metrics:
        enabled: false  # cluster is mid-migration to VictoriaMetrics; no endpoint configured here, avoid auto-discovery of the wrong backend
```

Replace with:

```yaml
    # Disable the Robusta SaaS-backed toolset — this cluster has no Robusta
    # account, and leaving it enabled just produces noisy "not configured"
    # log lines at startup.
    #
    # bash (extended allowlist) and internet toolsets are left at chart
    # defaults (enabled) for this POC. Combined with the cluster-wide
    # read-only ClusterRole and an unauthenticated in-cluster Service,
    # this means anything in-cluster that can reach holmesgpt-holmes:80
    # can drive shell/internet-capable investigation. Acceptable for a
    # cluster-internal POC; revisit with a NetworkPolicy or auth layer
    # if this graduates past POC (see home-ops-4rm). Same caveat now also
    # covers Grafana/Prometheus/VictoriaLogs/Postgres read access below —
    # tracked as a follow-up hardening item, not fixed in this pass.
    #
    # Every key in holmesgpt-secrets is mounted as an env var so toolset
    # config below can reference it via Holmes's own {{ env.VAR }}
    # templating (a runtime Jinja2 render, distinct from Helm's own
    # templating — this string is inert to Helm, Holmes reads it at boot).
    extraEnvVarsSecrets:
      - holmesgpt-secrets

    toolsets:
      robusta:
        enabled: false
      prometheus/metrics:
        enabled: false  # cluster is mid-migration to VictoriaMetrics; no endpoint configured here, avoid auto-discovery of the wrong backend
      grafana/dashboards:
        enabled: true
        config:
          api_key: "{{ env.GRAFANA_API_KEY }}"
          api_url: https://grafana.68cc.io
```

(Task 3 replaces the `prometheus/metrics` block's `enabled: false` line next — leave it as-is here.)

- [ ] **Step 6: Validate**

```bash
kustomize build kubernetes/apps/ai/holmesgpt/app
```

Expected: renders a `Secret` and a `HelmRelease` with no kustomize errors, and the rendered `HelmRelease` values contain `grafana/dashboards:` with `enabled: true`.

- [ ] **Step 7: Commit**

```bash
git add kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml
git commit -m "feat(ai): enable HolmesGPT grafana/dashboards toolset"
```

---

### Task 3: Prometheus/VictoriaMetrics toolset

**Files:**
- Modify: `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`

**Interfaces:**
- Consumes: the `toolsets:` block as left by Task 2 (contains `robusta:` and `prometheus/metrics:` with `enabled: false`, followed by `grafana/dashboards:`).
- Produces: `prometheus/metrics` toolset live, `subtype: victoriametrics`.

- [ ] **Step 1: Edit the toolset block**

In `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`, find:

```yaml
      prometheus/metrics:
        enabled: false  # cluster is mid-migration to VictoriaMetrics; no endpoint configured here, avoid auto-discovery of the wrong backend
```

Replace with:

```yaml
      prometheus/metrics:
        enabled: true
        subtype: victoriametrics
        config:
          prometheus_url: https://metrics.68cc.io
```

Note: `subtype` and `config` are siblings, both direct children of `prometheus/metrics:` — `subtype` is NOT nested inside `config:`.

- [ ] **Step 2: Validate**

```bash
kustomize build kubernetes/apps/ai/holmesgpt/app | grep -A5 "prometheus/metrics"
```

Expected:

```
      prometheus/metrics:
        enabled: true
        subtype: victoriametrics
        config:
          prometheus_url: https://metrics.68cc.io
```

- [ ] **Step 3: Commit**

```bash
git add kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml
git commit -m "feat(ai): enable HolmesGPT prometheus/metrics toolset (victoriametrics)"
```

---

### Task 4: VictoriaLogs toolset

**Files:**
- Modify: `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`

**Interfaces:**
- Consumes: the `toolsets:` block as left by Task 2 (contains `grafana/dashboards:` as the last entry).
- Produces: `victorialogs` toolset live.

- [ ] **Step 1: Add the toolset block**

In `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`, find:

```yaml
      grafana/dashboards:
        enabled: true
        config:
          api_key: "{{ env.GRAFANA_API_KEY }}"
          api_url: https://grafana.68cc.io
```

Replace with:

```yaml
      grafana/dashboards:
        enabled: true
        config:
          api_key: "{{ env.GRAFANA_API_KEY }}"
          api_url: https://grafana.68cc.io
      victorialogs:
        enabled: true
        config:
          api_url: https://logs.68cc.io
          headers:
            AccountID: "0"
            ProjectID: "0"
```

- [ ] **Step 2: Validate**

```bash
kustomize build kubernetes/apps/ai/holmesgpt/app | grep -A6 "victorialogs"
```

Expected:

```
      victorialogs:
        enabled: true
        config:
          api_url: https://logs.68cc.io
          headers:
            AccountID: "0"
            ProjectID: "0"
```

- [ ] **Step 3: Commit**

```bash
git add kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml
git commit -m "feat(ai): enable HolmesGPT victorialogs toolset"
```

---

### Task 5: CNPG `holmesgpt_ro` read-only role

This is the highest-risk task in the plan — it touches the shared `postgres17` `Cluster` CR that also backs other apps. Deploy and verify it independently before moving to Task 6.

**Files:**
- Modify: `kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml`
- Create: `kubernetes/apps/databases/cloudnative-pg/cluster/holmesgpt-role-secret.sops.yaml`
- Modify: `kubernetes/apps/databases/cloudnative-pg/cluster/kustomization.yaml`
- Modify: `kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: Postgres role `holmesgpt_ro` (member of `pg_monitor`, login-capable) on the shared `postgres17` cluster; key `POSTGRES_CONNECTION_URL` added to `holmesgpt-secrets` (`ai` namespace) — consumed by Task 6's `database` toolset config.

- [ ] **Step 1: Generate a password**

```bash
HOLMES_PG_PASSWORD=$(openssl rand -base64 24)
echo "$HOLMES_PG_PASSWORD"
```

Copy the output — it goes into two separate files in Steps 2 and 5 below. Do not regenerate between steps; both files must contain the same value.

- [ ] **Step 2: Add the managed role to the Cluster CR**

In `kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml`, find:

```yaml
  superuserSecret:
    name: cloudnative-pg-secret
  enableSuperuserAccess: true
  postgresql:
```

Replace with:

```yaml
  superuserSecret:
    name: cloudnative-pg-secret
  enableSuperuserAccess: true
  # holmesgpt_ro: read-only monitoring role for HolmesGPT's Postgres toolset.
  # pg_monitor is a Postgres built-in role granting read access
  # to pg_stat_activity/pg_stat_replication/pg_locks/pg_stat_statements etc.
  # across the whole cluster — deliberately NOT granted access to any
  # individual app database's table data. Connects to the `postgres`
  # maintenance DB, not any app database.
  managed:
    roles:
      - name: holmesgpt_ro
        ensure: present
        login: true
        inRoles:
          - pg_monitor
        passwordSecret:
          name: holmesgpt-db-creds
  postgresql:
```

- [ ] **Step 3: Write the CNPG role password secret**

Create `kubernetes/apps/databases/cloudnative-pg/cluster/holmesgpt-role-secret.sops.yaml` (substitute `<HOLMES_PG_PASSWORD>` with the value from Step 1):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: holmesgpt-db-creds
  labels:
    cnpg.io/reload: "true"
type: kubernetes.io/basic-auth
stringData:
  username: holmesgpt_ro
  password: "<HOLMES_PG_PASSWORD>"
```

- [ ] **Step 4: Register it in the cluster kustomization**

Edit `kubernetes/apps/databases/cloudnative-pg/cluster/kustomization.yaml`:

```yaml
resources:
  - ./imagecatalog.yaml
  - ./cluster.yaml
  - ./service-aliases.yaml
  - ./objectstore.yaml
  - ./scheduledbackup.yaml
  - ./prometheusrule.yaml
  - ./grafanadashboard.yaml
  - ./tcproute.yaml
  - ./dnsendpoint.yaml
  - ./holmesgpt-role-secret.sops.yaml
```

- [ ] **Step 5: Add `POSTGRES_CONNECTION_URL` to `holmesgpt-secrets`**

`kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml` already exists (created in Task 2) and is SOPS-encrypted — use the `sops-edit-then-encrypt` skill to add a key to it rather than hand-editing the encrypted file. Invoke that skill with instructions to add:

```yaml
  POSTGRES_CONNECTION_URL: "postgresql://holmesgpt_ro:<HOLMES_PG_PASSWORD>@postgres17-rw.databases.svc.cluster.local:5432/postgres"
```

(same `<HOLMES_PG_PASSWORD>` value from Step 1) to the `stringData` block, alongside the existing `GRAFANA_API_KEY` key.

- [ ] **Step 6: Encrypt and verify both secrets**

```bash
task sops:encrypt-file file=kubernetes/apps/databases/cloudnative-pg/cluster/holmesgpt-role-secret.sops.yaml
task sops:verify
```

Expected: both files pass verification.

- [ ] **Step 7: Validate manifests render**

```bash
kustomize build kubernetes/apps/databases/cloudnative-pg/cluster | grep -A10 "holmesgpt_ro"
kustomize build kubernetes/apps/ai/holmesgpt/app | grep -c "POSTGRES_CONNECTION_URL"
```

Expected: first command shows the `managed.roles` entry; second returns `1` (the encrypted key is present, even though its value is ciphertext at this point — `kustomize build` doesn't decrypt).

- [ ] **Step 8: Commit**

```bash
git add kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml \
        kubernetes/apps/databases/cloudnative-pg/cluster/holmesgpt-role-secret.sops.yaml \
        kubernetes/apps/databases/cloudnative-pg/cluster/kustomization.yaml \
        kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml
git commit -m "feat(databases): add holmesgpt_ro pg_monitor-scoped role for HolmesGPT"
```

- [ ] **Step 9: Push and reconcile the CNPG cluster Kustomization independently**

```bash
git push
task flux:reconcile-ks name=cloudnative-pg-cluster
```

Expected: reconcile completes without error.

- [ ] **Step 10: Verify the role exists and is reachable with the generated password**

```bash
kubectl -n databases get pods -l cnpg.io/cluster=postgres17
```

Pick the first pod name from the output (e.g. `postgres17-1`), then:

```bash
kubectl -n databases exec postgres17-1 -- psql -U postgres -c "\du holmesgpt_ro"
```

Expected: a row for `holmesgpt_ro` with `Cannot login` **absent** (i.e. login is allowed) and `pg_monitor` listed under "Member of".

```bash
kubectl -n databases exec postgres17-1 -- psql "postgresql://holmesgpt_ro:$HOLMES_PG_PASSWORD@localhost:5432/postgres" -c "select pg_has_role('holmesgpt_ro', 'pg_monitor', 'member');"
```

Expected: returns `t`. If this fails with an auth error, re-check that Step 1's password matches exactly what's in both `holmesgpt-role-secret.sops.yaml` and `holmesgpt-secrets`' `POSTGRES_CONNECTION_URL` — CNPG only picks up a `passwordSecret` change on reconcile, so a mismatch here usually means one of the two files has a stale/mistyped value.

---

### Task 6: Postgres `database` toolset

**Files:**
- Modify: `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`

**Interfaces:**
- Consumes: `POSTGRES_CONNECTION_URL` key in `holmesgpt-secrets` (Task 5), already covered by the `extraEnvVarsSecrets` wiring from Task 2 (same secret, no new env-mounting needed).
- Produces: a live `database`-typed toolset named `postgres17-stats`.

- [ ] **Step 1: Add the toolset block**

In `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`, find (the block left by Task 4):

```yaml
      victorialogs:
        enabled: true
        config:
          api_url: https://logs.68cc.io
          headers:
            AccountID: "0"
            ProjectID: "0"
```

Replace with:

```yaml
      victorialogs:
        enabled: true
        config:
          api_url: https://logs.68cc.io
          headers:
            AccountID: "0"
            ProjectID: "0"
      # Cluster-level Postgres stats only (pg_monitor role) — deliberately
      # NOT granted access to any individual app database's table data.
      # See kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml
      # for the holmesgpt_ro role definition.
      postgres17-stats:
        type: database
        enabled: true
        config:
          connection_url: "{{ env.POSTGRES_CONNECTION_URL }}"
```

- [ ] **Step 2: Validate**

```bash
kustomize build kubernetes/apps/ai/holmesgpt/app | grep -A5 "postgres17-stats"
```

Expected:

```
      postgres17-stats:
        type: database
        enabled: true
        config:
          connection_url: "{{ env.POSTGRES_CONNECTION_URL }}"
```

- [ ] **Step 3: Commit**

```bash
git add kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml
git commit -m "feat(ai): enable HolmesGPT postgres17-stats database toolset"
```

---

### Task 7: Full deploy and live toolset verification

**Files:** none (runtime verification only).

**Interfaces:**
- Consumes: everything from Tasks 2, 3, 4, 6 (Task 5 was already independently deployed/verified).

- [ ] **Step 1: Flux-level dry-run validation**

```bash
flux build kustomization holmesgpt --path kubernetes/apps/ai/holmesgpt --dry-run
```

Expected: no schema errors.

- [ ] **Step 2: Push and reconcile**

```bash
git push
task flux:reconcile-ks name=holmesgpt
```

Expected: completes without error.

- [ ] **Step 3: Confirm the pod is healthy**

```bash
kubectl -n ai get pods -l app.kubernetes.io/instance=holmesgpt
```

Expected: the `holmes` pod (and `holmes-operator` pod) reach `Running`/`1/1 Ready`. If it crash-loops:

```bash
kubectl -n ai logs -l app.kubernetes.io/instance=holmesgpt --all-containers --prefix
```

Check for: a Grafana `401` (bad/missing token — re-verify Task 2 Step 1), a Postgres auth failure (re-verify Task 5's password match), or a connection error to `metrics.68cc.io`/`logs.68cc.io` (confirm those hosts are actually LAN-reachable from pod CIDR — if not, this repo's no-auth assumption from the spec was wrong and needs revisiting, not silently worked around).

- [ ] **Step 4: Find the actual Service name**

```bash
kubectl -n ai get svc -l app.kubernetes.io/instance=holmesgpt
```

Note the Service name for the base API (commonly `holmesgpt-holmes` for this chart, but don't assume — use whatever this command reports).

- [ ] **Step 5: Port-forward**

```bash
kubectl -n ai port-forward svc/<SERVICE_NAME> 8080:80
```

- [ ] **Step 6: Cheap pre-checks (no LLM call)**

In a second terminal:

```bash
curl -s http://localhost:8080/healthz
curl -s http://localhost:8080/readyz
curl -s http://localhost:8080/api/model
```

Expected: `healthz`/`readyz` return success; `/api/model` lists the configured `llamaswap` model alias.

- [ ] **Step 7: Probe each toolset via `/api/chat`**

Run each of these and inspect the response's `tool_calls[]` array for a call into the matching toolset — not just that `analysis` came back non-empty (Holmes can produce a plausible-sounding answer from `kubernetes/core` alone if a new toolset silently failed to register):

```bash
curl -s -X POST http://localhost:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"ask": "What is current CPU usage across nodes, per Prometheus metrics?", "stream": false}' | jq '.tool_calls[].tool_name, .analysis'

curl -s -X POST http://localhost:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"ask": "Show me recent error-level logs from the ai namespace.", "stream": false}' | jq '.tool_calls[].tool_name, .analysis'

curl -s -X POST http://localhost:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"ask": "What dashboards exist in the monitoring folder in Grafana?", "stream": false}' | jq '.tool_calls[].tool_name, .analysis'

curl -s -X POST http://localhost:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"ask": "How many active connections and any lock contention on the postgres17 cluster right now?", "stream": false}' | jq '.tool_calls[].tool_name, .analysis'
```

Expected: each response's `tool_calls` includes a tool name recognizable as belonging to that toolset (e.g. a `prometheus_*` tool for the first, a `victorialogs_*`/log-search tool for the second, a `grafana_*`/dashboard tool for the third, a `postgres17-stats_*`/query tool for the fourth), and `.analysis` references real, specific cluster data (actual node names, actual log lines, actual dashboard titles, actual connection counts) rather than a generic non-answer. If any toolset never appears in `tool_calls`, re-check that toolset's config block and the pod's env vars (`kubectl -n ai exec <pod> -- env | grep -E 'GRAFANA_API_KEY|POSTGRES_CONNECTION_URL'`) before concluding the feature doesn't work.

---

### Task 8: Documentation and close-out

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nothing new.

- [ ] **Step 1: Correct the stale monitoring-stack description**

In `CLAUDE.md`, find the "Observability" section's description of Prometheus/Thanos and the "Log aggregation: VictoriaLogs (active)" paragraph. Replace the Prometheus/Thanos line's framing (currently implies Prometheus is still primary and "slated for replacement") and the VictoriaLogs paragraph (currently claims a non-existent `kubernetes/apps/monitoring/victoria-logs/ks.yaml` deployment with a `victoria-logs-vector` DaemonSet) with accurate text reflecting: Prometheus server is disabled (`home-ops-8bb` stage 2 complete), `vmagent`/`vmalert` remote-write to the externally-hosted VictoriaMetrics at `https://metrics.68cc.io` (primary metrics datasource, no in-cluster `VMSingle`), and log shipping is via the `vector` app to an externally-hosted VictoriaLogs at `https://logs.68cc.io` (Elasticsearch-bulk ingest, not a Loki-shim).

- [ ] **Step 2: Add the new toolsets to the holmesgpt bullet**

In the same file's "Deployed Applications (ai namespace)" section, find the `holmesgpt` bullet and append a note that it also now queries `prometheus/metrics` (VictoriaMetrics), `victorialogs`, `grafana/dashboards`, and a `pg_monitor`-scoped Postgres toolset (`postgres17-stats`) — not just Kubernetes API state.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: correct stale monitoring-stack description, document HolmesGPT toolset expansion"
```

- [ ] **Step 4: Confirm final state**

All six implementation items (Tasks 2–7) are complete; the two tracking-only follow-up items (Discord bridge, API/NetworkPolicy hardening) remain intentionally open/deferred — do not treat those as blocking this work's completion, they're left for future work.

- [ ] **Step 5: Report final status**

```bash
git status
git log --oneline -10
```

No push here beyond what Task 7 already did — Task 8's commit (CLAUDE.md) still needs `git push` if not already covered; run it:

```bash
git push
```
