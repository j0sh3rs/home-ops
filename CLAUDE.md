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

All operational tasks use [go-task](https://taskfile.dev/). Run `task -l` to list all tasks. Taskfiles are in `.taskfiles/`.

### Flux Operations

```bash
# Core Flux operations
task flux:reconcile                              # Force git source + cluster kustomization reconcile
task flux:bootstrap                              # Bootstrap Flux into cluster (first-time)
task flux:apply path=network/cloudflared         # Build and apply a specific Flux Kustomization
task flux:status                                 # Show status of all Kustomizations and HelmReleases

# Suspend/Resume
task flux:suspend name=app ns=default type=helmrelease  # Suspend a resource
task flux:resume name=app ns=default type=helmrelease   # Resume a resource

# Logs and debugging
task flux:logs name=grafana ns=monitoring        # Show logs for a HelmRelease
task flux:check                                  # Check Flux components health

# Specific reconciliation
task flux:reconcile-ks name=cluster-apps         # Reconcile a Kustomization
task flux:reconcile-hr name=grafana ns=monitoring # Reconcile a HelmRelease
```

### Talos Operations

```bash
task talos:generate-config                       # Generate configs from talconfig.yaml
task talos:apply-node IP=192.168.1.100 MODE=auto # Apply config to a node
task talos:upgrade-node IP=192.168.1.100         # Upgrade Talos on a node
task talos:upgrade-k8s                           # Upgrade Kubernetes version
task talos:reset                                 # Reset all nodes (DESTRUCTIVE, prompts)
```

### SOPS Secret Management

```bash
# Bulk operations
task sops:encrypt                                # Encrypt all *.sops.yaml files
task sops:decrypt                                # Decrypt all *.sops.yaml files (prompts for confirmation)
task sops:verify                                 # Verify all *.sops.yaml files are properly encrypted

# Single file operations
task sops:encrypt-file file=path/to/secret.yaml  # Encrypt a specific file
task sops:decrypt-file file=path/to/secret.yaml  # Decrypt a specific file
task sops:view file=path/to/secret.sops.yaml     # View decrypted content (read-only)
task sops:edit file=path/to/secret.sops.yaml     # Edit encrypted file in editor

# Advanced operations
task sops:rotate                                 # Rotate encryption keys for all files
task sops:updatekeys                             # Update keys based on .sops.yaml rules

# Direct SOPS commands
sops -d path/to/secret.sops.yaml                 # Decrypt to view
sops path/to/secret.sops.yaml                    # Edit encrypted file in-place
```

### Kubernetes Debugging

```bash
task kubernetes:network                          # Launch netshoot debug pod
task kubernetes:privileged node=k8s-worker-1     # Privileged pod on a specific node
task kubernetes:drain node=k8s-worker-1          # Drain a node
task kubernetes:browse-pvc claim=data ns=services # Browse a PVC's contents
task kubernetes:delete-failed-pods               # Clean up Succeeded/Failed pods
task kubernetes:resource-dump ns=monitoring      # Dump all resources in namespace to YAML
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

This pattern provides better lifecycle management and upgrades compared to traditional Flux bootstrap.

## Secret Management

**SOPS config** (`.sops.yaml`): age-key encryption with path-based rules:

- `talos/` — entire files encrypted
- `kubernetes/`, `bootstrap/`, `archive/` — only `data` and `stringData` fields encrypted

All secrets MUST be encrypted before committing. Name encrypted files `*.sops.yaml`.

**Important**: Always verify encryption before committing:
```bash
task sops:verify  # Check all *.sops.yaml files are properly encrypted
```

## Architecture

### Networking

- **Cilium** — eBPF-based CNI and network policy engine
- **Envoy Gateway** — Gateway API implementation for ingress
- **Cloudflare DNS** — Cloudflare DNS integration via external-dns
- **Unifi DNS** — Internal DNS integration with UniFi network
- **cert-manager** — TLS certificate automation

### Storage

- **OpenEBS LocalPV** — Default storage class (`openebs-localpv-hostpath`)
- **NFS External Provisioner** — NFS-backed storage provisioner for shared storage
- **Minio S3** — Object storage at `https://s3.68cc.io` (buckets: `openebs-backups`, `thanos-blocks`, `victoria-logs-chunks`)
- **Velero** — Cluster-level S3-backed snapshots (daily 02:00 UTC, 30-day retention)

Each component gets isolated S3 credentials as SOPS-encrypted secrets (`{component}-s3-secret`).

### Observability (Metrics, Logs, Tracing)

- **Grafana** — Unified dashboards (deployed via Grafana Operator with `GrafanaInstance` + `GrafanaDashboard` CRDs)
- **kube-prometheus-stack** — Prometheus with ServiceMonitors, recording rules, and alerting
- **Thanos** — Long-term metrics storage with S3 backend (`thanos-blocks` bucket)
- **Victoria Logs** — Log aggregation with S3 persistence and syslog ingestion (TCP/UDP routes)
- **netdata** — Real-time system metrics and visualization
- **unpoller** — UniFi network device monitoring

**Note**: The monitoring stack uses single-replica deployments with S3 providing durability.

### Databases

- **CloudNative-PG** — PostgreSQL operator with S3 backups
- **DragonflyDB** — Redis-compatible in-memory store

### Security

- **Tetragon** — Runtime security observability with eBPF (deployed in both `kube-system` and `security` namespaces)
- **CrowdSec** — Collaborative IDS/IPS for threat detection and blocking

### System Components

- **Reflector** — Reflects Secrets and ConfigMaps across namespaces
- **Reloader** — Triggers rolling updates when ConfigMaps/Secrets change
- **Spegel** — P2P container image distribution for faster pulls
- **Descheduler** — Rebalances pods across nodes based on policies
- **K8tz** — Timezone injection for pods
- **AMD GPU Device Plugin** — AMD GPU support for workloads
- **Talos Backups** — Automated etcd backup CronJob
- **IRQBalance** — Hardware interrupt balancing
- **Tuppr** — System upgrade controller (manages Talos OS upgrades via Image Update Automation)

### Application Namespaces

`cert-manager`, `databases`, `flux-system`, `kube-system`, `monitoring`, `network`, `security`, `services`, `system-upgrade`, `velero`

## Deployed Applications

### Services Namespace

- **Atuin** — Shell history sync server
- **Linkwarden** — Collaborative bookmark manager
- **ChangeDetector** — Website change monitoring
- **IT-Tools** — Collection of IT utility tools
- **Memos** — Lightweight note-taking service
- **N8N** — Workflow automation platform
- **MetaMCP** — MCP (Model Context Protocol) server

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

This pattern separates operator installation, instance configuration, and dashboard management for better organization.

## CI/CD

### GitHub Actions Workflows

**Validation & Testing:**
- **validate-secrets** — Verifies all `*.sops.yaml` files are properly encrypted (prevents accidental plaintext commits)
- **flux-local** — Flux manifest validation, kubeconform schema validation, and diff generation for PRs
- **e2e** — End-to-end testing

**Automation:**
- **labeler** — Auto-labels PRs based on changed paths (includes risk-based labels)
- **label-sync** — Syncs GitHub labels from `.github/labels.yaml`
- **mise** — Validates mise configuration
- **release** — Creates GitHub releases

**PR Risk Labels:**
PRs are automatically labeled based on the files changed:
- `risk/critical` — Core infrastructure (Cilium, CoreDNS, Flux, Talos, SOPS config)
- `risk/high` — Networking, cert-manager, security, storage, system-upgrade
- `risk/medium` — Databases, monitoring, backup systems
- `risk/low` — Application services, documentation

These labels help reviewers understand the blast radius of changes.

### Renovate

Config at `.github/renovate.json5`. Auto-merge behavior:

- **Patch** container images, Helm charts, GitHub releases — auto-merge
- **Minor** updates across all types — auto-merge
- **Major** updates — manual review required
- **Talos installer** — scheduled for Saturday after 2pm, no auto-merge

**Recommended Enhancement**: Consider adding `stabilityDays` for infrastructure components (Cilium, cert-manager, etc.) to prevent auto-merging freshly-released updates.

Commit prefixes: `fix(container):`, `fix(helm):`, `fix(deps):`, `feat(deps):`

### Pre-Commit Validation

Before pushing changes, validate locally:

```bash
# Verify SOPS encryption
task sops:verify

# Validate Kubernetes manifests
kustomize build kubernetes/apps/{namespace}/{app}/app | kubectl apply --dry-run=client -f -

# Check Flux resources
flux build kustomization {name} --path kubernetes/apps/{path} --dry-run
```

## Key Design Decisions

- **Single replicas everywhere** — S3 provides data durability instead of pod replication
- **Monolithic deployment modes** — Resource efficiency over distributed complexity
- **Resource-constrained** — Prefer vertical scaling, memory <2Gi per pod
- **FluxCD over ArgoCD** — Simpler for home-lab, native Kubernetes CRDs
- **Flux Operator pattern** — Better lifecycle management than traditional bootstrap
- **Grafana Operator** — Declarative dashboard management via CRDs
- **SOPS + age** — Git-native encryption, no external dependency
- **Immutable infrastructure** — Talos nodes are API-configured, never SSH'd into
- **eBPF-native** — Cilium CNI + Tetragon security for kernel-level observability
- **Security-first CI/CD** — Automated validation prevents misconfigurations

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

# Check HelmRelease specifically
kubectl -n {ns} describe helmrelease {app} --context home

# Check Grafana Operator resources
kubectl -n monitoring get grafanainstance --context home
kubectl -n monitoring get grafanadashboard --context home

# Validate manifests before pushing
kustomize build kubernetes/apps/{namespace}/{app}/app

# Check SOPS encryption status
task sops:verify
```
