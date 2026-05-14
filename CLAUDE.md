# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home-lab Kubernetes cluster on **Talos Linux** running **Kubernetes**, managed via **FluxCD** GitOps. Source repo: `github.com/j0sh3rs/home-ops`.

## Critical: Kubectl Context

**ALL** kubectl, helm, and flux commands MUST use `--context home`:

```bash
kubectl get pods -A --context home
helm list -A --kube-context home
flux get ks -A --context home
```

## Token-Efficient Commands (RTK)

Prefix all commands with `rtk` per `~/CLAUDE.md` for 60-85% token savings:

```bash
rtk kubectl get pods -A --context home
rtk flux get ks -A --context home
rtk helm list -A --kube-context home
rtk kubectl logs <pod> -n <ns> --context home
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

Each app follows this structure:

```
kubernetes/apps/{namespace}/{app}/
├── ks.yaml                    # Flux Kustomization (entry point)
└── app/
    ├── kustomization.yaml     # Kustomize overlay
    ├── helmrelease.yaml       # Helm chart configuration
    └── secret.sops.yaml       # Encrypted secrets (optional)
```

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
- `kubernetes/apps/kube-system/amd-gpu/` — `rocm.github.io/k8s-device-plugin`
- `kubernetes/apps/kube-system/descheduler/` — OCI available: `ghcr.io/kubernetes-sigs/descheduler`
- `kubernetes/apps/kube-system/nfs-external-provisioner/` — `kubernetes-sigs.github.io/nfs-subdir-external-provisioner`
- `kubernetes/apps/kube-system/tetragon/` — has local `helmrepository.yaml`; check for OCI
- `kubernetes/flux/meta/repos/{prometheus-community,bjw-s}.yaml` — already `oci://` URLs but declared as `HelmRepository`; migrate to `OCIRepository` where charts consume them

Note: `kubernetes/flux/meta/repos/{toolhive-operator,toolhive-operator-crds}.yaml` are the reference examples — already `OCIRepository` with `chartRef` in their HelmReleases.

### app-template (bjw-s) for apps without a Helm chart

The `bjw-s/app-template` chart (`oci://ghcr.io/bjw-s-labs/helm/app-template`, v4.6.2) is used for apps that don't have their own Helm chart. It is **not** globally available — each namespace kustomization must opt in:

```yaml
# In kubernetes/apps/{namespace}/kustomization.yaml
components:
  - ../../components/repos/app-template  # ← required to use app-template
```

Currently opted in: `services`, `databases`. The OCIRepository is at `kubernetes/components/repos/app-template/ocirepository.yaml`.

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

- **Traefik** — Gateway API ingress controller. Two instances: `traefik-external` (public-facing, VIP `192.168.35.15`, gateway `traefik-external-gateway`) and `traefik-internal` (LAN-only, VIP `192.168.35.17`, gateway `traefik-internal-gateway`). Both terminate TLS using the wildcard cert `68cc-io-tls` in `network` namespace (covers `*.68cc.io`). HTTPRoutes opt into one gateway via `parentRefs` and set `external-dns.alpha.kubernetes.io/target` to the matching VIP. oauth2-proxy forwardAuth Middleware (`oauth2-proxy-auth` + `oauth2-proxy-errors`, from component `kubernetes/components/traefik-forwardauth`) is the cluster auth gate; legacy Auth0 middleware was removed.
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
| Model weights, embedding caches (llama-swap, Ollama) | `openebs-hostpath` | Large cold reads; local disk avoids NFS throughput cap |
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
- **kube-prometheus-stack** — Prometheus with ServiceMonitors, recording rules, and alerting. Runs the `prompp/prompp` C++ PromQL drop-in image (version override `v2.55.1`). **Slated for replacement** by VictoriaMetrics under epic `home-ops-v17`.
- **Thanos** — Long-term metrics storage with S3 backend (`thanos-blocks` bucket). Query, store-gateway, compact. **Slated for removal** after VMsingle migration.
- **Alertmanager** — Discord webhook for `severity=critical`, 12h repeat, `Watchdog`/`InfoInhibitor` blackholed.
- **unpoller** — UniFi network device monitoring (2m scrape interval, UniFi API rate-limited).
- **Tetragon** — Runtime security metrics + Grafana dashboard (deployed in `kube-system`, not `monitoring`).

**Log aggregation is currently disabled.** `victoria-logs` manifests exist but are commented out in `kubernetes/apps/monitoring/kustomization.yaml`. Restoration tracked by `home-ops-d1e`. No application log backend until that lands.

**Note**: Single-replica deployments; S3 provides durability. Prometheus runs 6h local retention with all long-term data in Thanos-managed S3 blocks.

### Databases

- **CloudNative-PG** — PostgreSQL operator with S3 backups; cluster `postgres17-rw` service on port 5432
- **DragonflyDB** — Redis-compatible in-memory store; `dragonflydb.databases.svc.cluster.local:6379`
- **Dolt** — Git-versioned MySQL-compatible database; exposed externally at `dolt.68cc.io:3306` via Traefik TLS termination (mysql-tls listener). Connect: `mysql -h dolt.68cc.io -P 3306 -u root -p`. Used as remote backend for Beads task tracking.

### Security

- **Tetragon** — Runtime security observability with eBPF (`kube-system` and `security` namespaces)
- **CrowdSec** — Collaborative IDS/IPS for threat detection and blocking; Traefik bouncer middleware applied globally on `web` and `websecure` entrypoints
- **oauth2-proxy + Google OIDC** — Service-level authentication. Traefik `oauth2-proxy-auth` forwardAuth Middleware calls oauth2-proxy `/oauth2/auth`; unauthenticated requests bounce through `auth.68cc.io/oauth2/start` to Google, then back. Session cookies scoped to `.68cc.io`. Applied per-HTTPRoute via Gateway API `ExtensionRef` filters. See `kubernetes/components/traefik-forwardauth/` and `kubernetes/apps/security/oauth2-proxy/`. Replaced the legacy Auth0 + traefikoidc plugin in a prior migration.

### System Components (`kube-system`)

- **Cilium** — eBPF-based CNI and network policy engine
- **Reflector** — Reflects Secrets and ConfigMaps across namespaces
- **Reloader** — Triggers rolling updates when ConfigMaps/Secrets change
- **Spegel** — P2P container image distribution for faster pulls
- **Descheduler** — Rebalances pods across nodes based on policies
- **K8tz** — Timezone injection for pods
- **AMD GPU Device Plugin** — AMD GPU support for workloads
- **Talos Backups** — Automated etcd backup CronJob
- **IRQBalance** — Hardware interrupt balancing
- **Tuppr** — System upgrade controller (manages Talos OS upgrades)

### Application Namespaces

`cert-manager`, `databases`, `flux-system`, `kube-system`, `monitoring`, `network`, `security`, `services`, `system-upgrade`, `velero`

## Deployed Applications (services namespace)

- **Atuin** — Shell history sync server
- **Home Assistant** — Home automation platform (hostNetwork for mDNS/UPnP)
- **Homebridge** — HomeKit bridge via `homebridge.68cc.io` (hostNetwork for mDNS/HAP; ciao in-process advertiser; `HOMEBRIDGE_INSECURE=1` enables Homepage widget + prometheus-exporter plugin). Pairing PIN shown in pod logs on first boot.
- **Homepage** — Dashboard at `68cc.io` (root). Service tiles + widgets configured via SOPS-encrypted Secret; widget creds injected via `HOMEPAGE_VAR_*` env vars.
- **IT-Tools** — Collection of IT utility tools
- **Linkwarden** — Collaborative bookmark manager
- **N8N** — Workflow automation platform
- **Ollama** — Local LLM inference server
- **Open WebUI** — Web interface for Ollama

Currently disabled (commented out in `kubernetes/apps/services/kustomization.yaml`):
- ~~ChangeDetector~~ — Website change monitoring
- ~~Memos~~ — Lightweight note-taking service
- ~~MetaMCP~~ — MCP server
- ~~Paperless-NGX~~ — Document management system

## Grafana Operator Pattern

Grafana is deployed using the **Grafana Operator** with a multi-kustomization structure:

```
kubernetes/apps/monitoring/grafana/
├── ks.yaml                          # Root Flux Kustomization
├── operator/                        # Grafana Operator deployment
├── instance/                        # GrafanaInstance CR
└── dashboards/                      # Individual GrafanaDashboard CRDs
    └── app/
        ├── kustomization.yaml
        └── {dashboard-name}.json    # Grafana dashboard JSON
```

## CI/CD

### GitHub Actions Workflows

**Validation & Testing:**
- **validate-secrets** — Verifies all `*.sops.yaml` files are properly encrypted
- **flux-local** — Flux manifest validation, kubeconform schema validation, and diff generation for PRs
- **e2e** — End-to-end testing

**Automation:**
- **labeler** — Auto-labels PRs based on changed paths (includes risk-based labels)
- **label-sync** — Syncs GitHub labels from `.github/labels.yaml`

**PR Risk Labels:**
- `risk/critical` — Core infrastructure (Cilium, CoreDNS, Flux, Talos, SOPS config)
- `risk/high` — Networking, cert-manager, security, storage, system-upgrade
- `risk/medium` — Databases, monitoring, backup systems
- `risk/low` — Application services, documentation

### Renovate

Config at `.github/renovate.json5`. Auto-merge behavior:

- **Patch + Minor** — container images, Helm charts, GitHub releases auto-merge
- **Major** — manual review required
- **Talos installer** — scheduled for Saturday after 2pm, no auto-merge

Commit prefixes: `fix(container):`, `fix(helm):`, `fix(deps):`, `feat(deps):`

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

```bash
# Check Flux status
flux get ks -A --context home
flux get hr -A --context home
flux logs --kind=HelmRelease --namespace={ns} --name={app} --context home

# Check pod issues
kubectl -n {ns} get pods -o wide --context home
kubectl -n {ns} describe pod {pod} --context home
kubectl -n {ns} logs {pod} -f --context home
kubectl -n {ns} get events --sort-by='.metadata.creationTimestamp' --context home

# Check HelmRelease
kubectl -n {ns} describe helmrelease {app} --context home

# Check Grafana Operator resources
kubectl -n monitoring get grafanainstance --context home
kubectl -n monitoring get grafanadashboard --context home

# Dump common cluster resources
task template:debug

# Validate manifests before pushing
kustomize build kubernetes/apps/{namespace}/{app}/app

# Check SOPS encryption status
task sops:verify
```

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
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

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
