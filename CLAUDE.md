# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home-lab Kubernetes cluster on **Talos Linux** running **Kubernetes**, managed via **FluxCD** GitOps. Source repo: `github.com/j0sh3rs/home-ops`.

## Critical: Kubectl Context

**Do NOT pass `--context home`.** `mise` injects `KUBECONFIG=./kubeconfig`
automatically via `.mise.toml`, pointing at the single cluster (the real context
name is `admin@kubernetes`; there is no `home` context). Run bare:

```bash
kubectl get pods -A
helm list -A
flux get ks -A
```

> History: a PreToolUse hook in `.claude/settings.json` used to refuse commands
> missing `--context home`. Removed 2026-06-15 once mise took over KUBECONFIG.
> Any older doc/memory referencing `--context home` is stale.

## Token-Efficient Commands (RTK)

Prefix all commands with `rtk` per `~/CLAUDE.md` for 60-85% token savings:

```bash
rtk kubectl get pods -A
rtk flux get ks -A
rtk helm list -A
rtk kubectl logs <pod> -n <ns>
```

## Task Tracking (Beads)

Issue tracker backed by Dolt (`dolt.68cc.io:3306`). Use `bd` CLI:

```bash
bd list              # List open tasks
bd show <id>         # Show task details
bd ready             # Tasks ready to work (no blockers)
bd create            # Create new issue interactively
```

## Development Environment

**Tool chain**: `mise` installs `aqua` (via `aqua:cli/cli` in `.mise.toml`), which pins `talhelper` and `talos` CLI versions via `aqua.yaml`.

```bash
# First-time setup
mise trust && mise install

# Environment variables (set automatically by mise via .mise.toml)
# KUBECONFIG=./kubeconfig
# SOPS_AGE_KEY_FILE=./age.key
# TALOSCONFIG=./talos/clusterconfig/talosconfig
```

## Task Runner Commands

All operational tasks use [go-task](https://taskfile.dev/). Run `task -l` to list all tasks. Taskfiles are in `.taskfiles/`. Valid namespaces: `bootstrap`, `flux`, `sops`, `talos`, `template`.

### Core

```bash
task reconcile                                   # Shorthand: reconcile flux-system kustomization
task template:debug                              # Dump common cluster resources (pods, helmreleases, etc.)
```

### Bootstrap (First-Time Setup)

```bash
task template:init                               # Generate age key, deploy key, push token
task template:configure                          # Render configs, validate schemas, encrypt secrets
task bootstrap:talos                             # Bootstrap Talos cluster from talconfig.yaml
task bootstrap:apps                              # Apply initial app manifests via bootstrap-apps.sh
```

### Flux Operations

```bash
task flux:reconcile                              # Force git source + all kustomizations reconcile
task flux:apply path=network/cloudflare-dns      # Build and apply a specific Flux Kustomization
task flux:status                                 # Show status of all Kustomizations and HelmReleases
task flux:check                                  # Check Flux components health
task flux:logs name=grafana ns=monitoring        # Show logs for a HelmRelease
task flux:suspend name=app ns=default type=helmrelease
task flux:resume name=app ns=default type=helmrelease
task flux:reconcile-ks name=cluster-apps         # Reconcile a specific Kustomization
task flux:reconcile-hr name=grafana ns=monitoring
```

### Talos Operations

**Per-node Factory schematics**: `talos/schematic.yaml` covers the 3 `bee-*` control-plane nodes (AMD APU). `bigboi-jms-01` (worker, 9070 XT dGPU) has its own `talos/schematic-dgpu.yaml` with dGPU-tuned kernel args (`amd_iommu=off`, smaller `amdgpu.gttsize`) — see comments in both files and in `talconfig.yaml` before editing either. A kernel-arg or extension change on one file does NOT need mirroring to the other unless it's a shared hardening/perf flag. Changing `talosImageURL` alone (via `task talos:apply-node`) does not swap the running image — that requires `task talos:upgrade-node IP=<ip>`, which reads `talosImageURL` from `talconfig.yaml` and reboots the node into it.

```bash
task talos:generate-config                       # Generate configs from talconfig.yaml
task talos:apply-node IP=192.168.1.100 MODE=auto # Apply config to a node
task talos:upgrade-node IP=192.168.1.100         # Upgrade Talos on a node
task talos:upgrade-k8s                           # Upgrade Kubernetes version
task talos:reset                                 # Reset all nodes (DESTRUCTIVE, prompts)
```

**Quorum safety (all 3 nodes are control-plane members):**

Rebooting any node drops etcd 3→2. A second failure during that window is cluster-down. `talos:apply-node` and `talos:upgrade-node` now run an `etcd-quorum-precheck` dep that calls `talosctl --nodes <peers> etcd status` before touching the target — the task fails loudly if any OTHER control-plane peer is behind or unhealthy.

Operational rules:

- **Never run two node-mutating tasks in parallel.** One at a time. Wait for the target to rejoin and report healthy before touching the next.
- **Never reboot, reset, or power-off a node manually without first cordoning it** — the taskfile prechecks are bypassed, and you lose the quorum gate.
- If `etcd-quorum-precheck` fails: investigate via `talosctl --nodes <peer> etcd status` and `talosctl --nodes <peer> dmesg | grep -i etcd` before overriding.
- Ad-hoc `talosctl reboot` / `talosctl shutdown` have no built-in quorum check. Cordon + drain the node in Kubernetes first, then confirm peer etcd health manually before the Talos-level command.

### SOPS Secret Management

```bash
task sops:encrypt                                # Encrypt all *.sops.yaml files
task sops:decrypt                                # Decrypt all *.sops.yaml files (prompts)
task sops:verify                                 # Verify all *.sops.yaml files are properly encrypted
task sops:encrypt-file file=path/to/secret.yaml
task sops:decrypt-file file=path/to/secret.yaml
task sops:view file=path/to/secret.sops.yaml     # View decrypted content (read-only)
task sops:edit file=path/to/secret.sops.yaml     # Edit encrypted file in editor
task sops:rotate                                 # Rotate encryption keys for all files
task sops:updatekeys                             # Update keys based on .sops.yaml rules
```

## Application Deployment Pattern

### IMPORTANT: Use OCIRepository + chartRef Pattern

New applications **must** use the `OCIRepository` + `chartRef` pattern. Do NOT use the old `chart.spec.sourceRef` with `HelmRepository`:

```yaml
# Correct: OCIRepository + chartRef
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: OCIRepository
metadata:
    name: app-name
    namespace: flux-system
spec:
    interval: 12h
    layerSelector:
        mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
        operation: copy
    ref:
        tag: 1.2.3
    url: oci://ghcr.io/example/charts/app-name
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
    name: app-name
spec:
    interval: 1h
    chartRef:
        kind: OCIRepository
        name: app-name
        namespace: flux-system
    values: {}

# WRONG: chart.spec.sourceRef with HelmRepository (legacy pattern, do not use)
```

Helm repository definitions live in `kubernetes/flux/meta/repos/`.

**`chartRef.namespace` gotcha**: Omit the `namespace:` field in `chartRef` when the OCIRepository lives in the HR's own namespace (via `components/repos/app-template`). Setting `namespace: flux-system` makes Flux look for the OCIRepository in `flux-system` and fail reconcile with `OCIRepository "app-template" not found`. The shared `app-template` OCIRepository is materialized per-namespace via the Component, not globally in flux-system.

**When adding a new app, ALWAYS check for an OCI-published chart first.** Most upstreams now publish to `ghcr.io` or `oci://` registries. Only fall back to `HelmRepository` + `sourceRef` when the upstream has no OCI artifact available. If you're copying an existing legacy-pattern app as a template, migrate it to `OCIRepository` + `chartRef` during the copy.

**Legacy `HelmRepository` + `sourceRef` apps pending OCI migration** (migrate opportunistically when touching them):
- `kubernetes/apps/cert-manager/cert-manager/` — `charts.jetstack.io` (check for OCI equivalent)
- `kubernetes/apps/databases/cloudnative-pg/` — `cloudnative-pg.github.io` (OCI available: `ghcr.io/cloudnative-pg/charts`)
- `kubernetes/apps/databases/dragonflydb/` — hybrid: `HelmRepository` kind but `oci://` URL → switch to proper `OCIRepository`
- `kubernetes/apps/velero/` — `vmware-tanzu.github.io`
- `kubernetes/apps/kube-system/descheduler/` — OCI available: `ghcr.io/kubernetes-sigs/descheduler`
- `kubernetes/apps/kube-system/nfs-external-provisioner/` — `kubernetes-sigs.github.io/nfs-subdir-external-provisioner`
- `kubernetes/apps/kube-system/tetragon/` — has local `helmrepository.yaml`; check for OCI
- `kubernetes/flux/meta/repos/{prometheus-community,bjw-s}.yaml` — already `oci://` URLs but declared as `HelmRepository`; migrate to `OCIRepository` where charts consume them

### app-template (bjw-s) for apps without a Helm chart

The `bjw-s/app-template` chart (`oci://ghcr.io/bjw-s-labs/helm/app-template`, v4.6.2) is used for apps that don't have their own Helm chart. It is **not** globally available — each namespace kustomization must opt in:

```yaml
# In kubernetes/apps/{namespace}/kustomization.yaml
components:
  - ../../components/repos/app-template  # ← required to use app-template
```

Currently opted in: `ai`, `services`, `databases`. The OCIRepository is at `kubernetes/components/repos/app-template/ocirepository.yaml`.

### IMPORTANT: Wire stakater/reloader on every ConfigMap/Secret consumer

Every workload that consumes a ConfigMap or Secret **must** carry a reloader annotation so edits/rotations trigger a pod restart instead of silently going stale. This is not optional polish — issue #493 found 6 production apps (unpoller, qdrant, crowdsec, both traefik instances, velero) silently running on stale secrets because this was skipped.

**When adding a new app or reviewing an existing one:**

1. If the app consumes ANY ConfigMap or Secret (envFrom, `valueFrom.configMapKeyRef`/`secretKeyRef`, or a mounted volume) and there's no compelling reason to scope narrowly, default to a blanket auto-reload annotation:
   - **app-template apps**: `controllers.<name>.annotations: {reloader.stakater.com/auto: "true"}` (or `global.annotations` if it should apply to every controller in the release).
   - **Non-app-template charts**: check the chart's values schema for a `podAnnotations`/`deploymentAnnotations`/`global.deploymentAnnotations`-style key (name varies per chart — verify by reading that chart's actual `values.yaml`, don't assume). Set `reloader.stakater.com/auto: "true"` there.
2. Use the scoped form instead of blanket `/auto` when you deliberately don't want every mounted object to trigger a restart (e.g. a ConfigMap that's read live, or you want to protect against restart-storms on a chatty ConfigMap):
   - `configmap.reloader.stakater.com/reload: "name1,name2"`
   - `secret.reloader.stakater.com/reload: "name1,name2"`
3. **Never assume a chart auto-generates its own checksum/reload annotation** — verify against the chart's actual template. `credentials.existingSecret`-style overrides (velero being the concrete example) frequently bypass a chart's built-in reload path even when the chart appears to support secrets natively.
4. Confirm the annotation lands on the **pod template**, not just Deployment/HelmRelease/Kustomization metadata — Reloader checks workload object annotations first, then falls back to pod-template annotations; either is fine, but a `kustomization.yaml`-level annotation does nothing.
5. Verify with `kustomize build kubernetes/apps/{namespace}/{app}/app | grep reloader.stakater` before considering the change done.

Reloader itself (`kubernetes/apps/kube-system/reloader/app/helmrelease.yaml`) runs `watchGlobally: true` (cluster-wide RBAC, all namespaces) with the default rolling-restart strategy — no per-namespace opt-in needed on the reloader side, only the per-app annotation.

### Flux Variable Substitution

The cluster-apps Kustomization (`kubernetes/flux/cluster/apps.yaml`) injects variables via `postBuild.substituteFrom` from:

- `cluster-settings` ConfigMap
- `cluster-secrets` Secret

Apps can reference these variables using `${VARIABLE_NAME}` syntax in their manifests.

## Flux Operator Pattern

This cluster uses the **Flux Operator** pattern rather than standard Flux bootstrap:

- `kubernetes/apps/flux-system/flux-operator/` — Flux Operator deployment
- `kubernetes/apps/flux-system/flux-instance/` — FluxInstance CR that defines the cluster's Flux configuration
- `kubernetes/apps/flux-system/flux-instance/app/receiver.yaml` — Webhook receiver for push-based reconciliation

## Secret Management

**SOPS config** (`.sops.yaml`): age-key encryption with path-based rules:

- `talos/` — entire files encrypted
- `kubernetes/`, `bootstrap/`, `archive/` — only `data` and `stringData` fields encrypted

All secrets MUST be encrypted before committing. Name encrypted files `*.sops.yaml`.

**Important**: Always verify encryption before committing:
```bash
task sops:verify  # Check all *.sops.yaml files are properly encrypted
```

**Cloudflare API MCP** authenticates via `CLOUDFLARE_API_TOKEN` env loaded from `cloudflare-mcp.env` (gitignored, mise `_.file` directive in `.mise.toml`). Token requires `Zone:Rulesets:Edit`, `Zone:Zone Settings:Edit`, `Zone:Bot Management:Edit`, `Zone:DNS:Edit`, `Account:Cloudflare Tunnel:Edit` scoped to `68cc.io` + `BTH Account`. The OAuth flow via `mcp.cloudflare.com/mcp` has insufficient scope for rulesets — bearer token is mandatory for Phase 4+ work. See `docs/runbooks/cloudflare-waf.md`.

## Architecture

### Networking

- **Traefik** — Gateway API ingress controller. Two instances: `traefik-external` (public-facing, VIP `192.168.35.15`, gateway `traefik-external-gateway`) and `traefik-internal` (LAN-only, VIP `192.168.35.17`, gateway `traefik-internal-gateway`). Both terminate TLS using the wildcard cert `68cc-io-tls` in `network` namespace (covers `*.68cc.io`). HTTPRoutes opt into one gateway via `parentRefs` and set `external-dns.alpha.kubernetes.io/target` to the matching VIP. Service-level auth is the **traefikoidc plugin** Middleware `google-oidc-secure`, materialized per-namespace via the `kubernetes/components/traefik-oidc/` Component. Apps reference it via Gateway API `ExtensionRef` filters.
- **Traefik `proxyProtocol.trustedIPs`**: LAN CIDR only (`192.168.35.0/24`). Pod CIDR (`10.42.0.0/16`) is intentionally NOT trusted — cloudflared speaks plain HTTP, not PROXY, and Traefik fail-parses if the pod CIDR is trusted. End-user IP over the tunnel is preserved via the `CF-Connecting-IP` HTTP header instead.
- **Cloudflare tunnel** (`home`, id `3ecf7dee-f421-46df-bcc1-1ea7ff24155c`) runs in-cluster at `kubernetes/apps/network/cloudflared/`. Tunnel ingress config is managed **remotely** via the Cloudflare dashboard/API (not this repo). Origin: `https://traefik-external.network.svc.cluster.local:443` with `originServerName: 68cc.io` (matches wildcard cert SAN). Verify via Cloudflare MCP — see `docs/runbooks/cloudflare-waf.md`.
- **External-DNS split-horizon**: `cloudflare-dns` writes CNAMEs to `<tunnel-id>.cfargotunnel.com` with `--cloudflare-proxied` for every route on `traefik-external-gateway`. `unifi-dns` writes LAN A records pointing at the VIP matching each route's `external-dns.alpha.kubernetes.io/target` annotation. Internal-only routes (`traefik-internal-gateway`, target `192.168.35.17`) get only a LAN record — no Cloudflare record.
- **unifi-dns** — Split-horizon DNS for internal cluster resolution via UniFi
- **cert-manager** — TLS certificate automation; cluster wildcard cert `68cc-io-tls` in `network` namespace

### Storage

- **OpenEBS LocalPV** — Default storage class (`openebs-hostpath`)
- **NFS External Provisioner** — NFS-backed storage provisioner for shared storage
- **Minio S3** — Object storage at `https://s3.68cc.io` (buckets: `openebs-backups`, `thanos-blocks`, `victoria-logs-chunks`)
- **Velero** — Cluster-level S3-backed snapshots (daily 02:00 UTC, 30-day retention)

Each component gets isolated S3 credentials as SOPS-encrypted secrets (`{component}-s3-secret`).

#### Storage class selection

Pick the storage class based on the workload's latency sensitivity and whether the data must survive node reschedule. When in doubt, favor `openebs-hostpath`: node-pinning is an acceptable cost for the latency win, and S3 backups provide the durability layer.

| Workload shape | Class | Why |
|----------------|-------|-----|
| Database data dirs (Postgres, Dolt, DragonflyDB) | `openebs-hostpath` | Local NVMe; sub-ms IO; backup separately via S3 |
| Model weights, embedding caches (llama-swap) | `openebs-hostpath` | Large cold reads; local disk avoids NFS throughput cap |
| Log shards, TSDB blocks (vmsingle, victoria-logs) | `openebs-hostpath` | Write-heavy, append-only; NFS metadata ops too costly |
| Grafana dashboards/plugins on-disk cache | `openebs-hostpath` | Startup-read-heavy; tolerable node-pinning |
| Config-heavy apps needing RWO but mobile (CrowdSec, AlertManager state) | `nfs-client` | Survives pod reschedule across nodes; low write rate |
| Shared read-mostly state across replicas | `nfs-client` | Only class supporting effective multi-node access patterns |

Rules of thumb:

- **RWX required** → `nfs-client` (openebs-hostpath is RWO + node-local)
- **Pod must reschedule without data loss + low write volume** → `nfs-client`
- **Performance-critical + tolerates pod being pinned to one node** → `openebs-hostpath`
- **Durability** is never the PVC's job here — S3 backups (Velero, CNPG, Minio replicas) are the answer

### Observability

- **Grafana** — Unified dashboards (deployed via Grafana Operator with `GrafanaInstance` + `GrafanaDashboard` CRDs). Anonymous auth enabled for LAN; root URL `grafana.68cc.io`.
- **kube-prometheus-stack** — Prometheus server itself is disabled (`prometheus.enabled: false`, `home-ops-8bb` stage 2 complete — no in-cluster Prometheus CR, Thanos sidecar, or local TSDB). What remains from the chart: Alertmanager, prometheus-node-exporter, kube-state-metrics, and prometheus-operator (source of the ServiceMonitor/PodMonitor/PrometheusRule CRDs that `vm-operator` auto-converts).
- **VictoriaMetrics** (`kubernetes/apps/monitoring/victoria-metrics/`, `victoria-metrics-operator`) — `vmagent` scrapes every ServiceMonitor/PodMonitor/Probe/VMRule cluster-wide (`selectAllByDefault: true`) and remote-writes to the externally-hosted VictoriaMetrics at `https://metrics.68cc.io`; `vmalert` (2 replicas) evaluates VMRules and reads/writes against the same endpoint. `https://metrics.68cc.io` is the primary metrics datasource in Grafana (`isDefault: true`) — there is no in-cluster `VMSingle`.
- **Alertmanager** — Discord webhook for `severity=critical`, 12h repeat, `Watchdog`/`InfoInhibitor` blackholed.
- **unpoller** — UniFi network device monitoring (2m scrape interval, UniFi API rate-limited).
- **Tetragon** — Runtime security metrics + Grafana dashboard (deployed in `kube-system`, not `monitoring`).

**Log aggregation**: the `vector` app (`kubernetes/apps/monitoring/vector/`) runs as a Vector Agent DaemonSet, tailing `kubernetes_logs` on every node and shipping them to the externally-hosted VictoriaLogs at `https://logs.68cc.io` via its Elasticsearch-bulk ingest endpoint (`/insert/elasticsearch/`, `api_version: v8`) — not a Loki-shim. There is no in-cluster VictoriaLogs server.

**Note**: Grafana, Alertmanager, and the remaining kube-prometheus-stack exporters/operator are single-replica in-cluster deployments (`vmalert` runs 2 replicas for HA alert evaluation). Both metrics and logs are stored externally (`metrics.68cc.io`, `logs.68cc.io`) — no in-cluster long-term retention to manage.

### Databases

- **CloudNative-PG** — PostgreSQL operator with S3 backups; cluster `postgres17-rw` service on port 5432
- **DragonflyDB** — Redis-compatible in-memory store; `dragonflydb.databases.svc.cluster.local:6379`
- **Dolt** — Git-versioned MySQL-compatible database; exposed externally at `dolt.68cc.io:3306` via Traefik TLS termination (mysql-tls listener). Connect: `mysql -h dolt.68cc.io -P 3306 -u root -p`. Used as remote backend for Beads task tracking.

### Security

- **Tetragon** — Runtime security observability with eBPF (`kube-system` and `security` namespaces)
- **CrowdSec** — Collaborative IDS/IPS for threat detection and blocking; Traefik bouncer middleware applied globally on `web` and `websecure` entrypoints
- **Authentik forwardAuth** — Service-level authentication via Authentik (`auth.68cc.io`) using its native Traefik forwardAuth plugin. OAuth callback to Google via single Authentik OAuth application. Traefik middleware `authentik-forwardauth` materialized per-namespace by the `kubernetes/components/authentik-forwardauth/` Component. Backing auth endpoint: `https://auth.68cc.io/outpost.goauthentik.io/auth/traefik`. Session cookies scoped to `.68cc.io`. Applied per-HTTPRoute via Gateway API `ExtensionRef`. Namespaces opt in by adding `../../components/authentik-forwardauth` to their kustomization `components:` list. Individual applications may also support native Authentik OIDC for internal authentication on top of gateway-level forwardAuth.

### System Components (`kube-system`)

- **Cilium** — eBPF-based CNI and network policy engine
- **Reflector** — Reflects Secrets and ConfigMaps across namespaces
- **Reloader** — Triggers rolling updates when ConfigMaps/Secrets change
- **Spegel** — P2P container image distribution for faster pulls
- **Descheduler** — Rebalances pods across nodes based on policies
- **K8tz** — Timezone injection for pods
- **AMD GPU Operator** (ROCm GPU Operator, `kubernetes/apps/kube-system/amd-gpu/`) — device-plugin, node-labeller, and metrics-exporter for `bigboi-jms-01`'s 9070 XT only, driverless mode (see "Decisions explicitly rejected" for the scoped-exception reasoning). Not deployed to the bee-* APU nodes.
- **Talos Backups** — Automated etcd backup CronJob
- **IRQBalance** — Hardware interrupt balancing
- **Tuppr** — System upgrade controller (manages Talos OS upgrades)

### Application Namespaces

`ai`, `cert-manager`, `databases`, `flux-system`, `kube-system`, `monitoring`, `network`, `security`, `services`, `system-upgrade`, `velero`

## Deployed Applications

- `ai` namespace: see `kubernetes/apps/ai/CLAUDE.md`
- `services` namespace: see `kubernetes/apps/services/CLAUDE.md`

## Grafana Operator Pattern

Grafana is deployed using the **Grafana Operator** with a multi-kustomization structure. See `.claude/skills/ci-cd-reference/SKILL.md` for CI workflow and Renovate details.

## CI/CD

### Pre-Commit Validation

```bash
task sops:verify
kustomize build kubernetes/apps/{namespace}/{app}/app | kubectl apply --dry-run=client -f -
flux build kustomization {name} --path kubernetes/apps/{path} --dry-run
```

## Key Design Decisions

- **Single replicas everywhere** — S3 provides data durability instead of pod replication
- **Resource-constrained** — Prefer vertical scaling, memory <2Gi per pod
- **FluxCD over ArgoCD** — Simpler for home-lab, native Kubernetes CRDs
- **Flux Operator pattern** — Better lifecycle management than traditional bootstrap
- **Grafana Operator** — Declarative dashboard management via CRDs
- **SOPS + age** — Git-native encryption, no external dependency
- **Immutable infrastructure** — Talos nodes are API-configured, never SSH'd into
- **eBPF-native** — Cilium CNI + Tetragon security for kernel-level observability
- **Cloudflare Free plan** — 5 custom WAF rules, 1 rate-limiting rule (new engine). Bot Fight Mode is tunnel-hostile (breaks cloudflared with `websocket: bad handshake`) — keep OFF. `ai_bots_protection: block` is safe and on. Managed Rules / Super Bot Fight Mode / multi-rule rate-limit need Pro ($25/mo/zone) — not currently justified for this threat model.

## Debugging Cheat Sheet

See `.claude/skills/debug-cheatsheet/SKILL.md`.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
