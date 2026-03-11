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
task flux:apply path=network/cloudflared         # Build and apply a specific Flux Kustomization
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

## Architecture

### Networking

- **Traefik** — Ingress controller with HTTPRoute and middleware support
- **k8s-gateway** — Split-horizon DNS for internal cluster resolution
- **Cloudflare DNS** — External DNS integration via external-dns
- **cert-manager** — TLS certificate automation

### Storage

- **OpenEBS LocalPV** — Default storage class (`openebs-localpv-hostpath`)
- **NFS External Provisioner** — NFS-backed storage provisioner for shared storage
- **Minio S3** — Object storage at `https://s3.68cc.io` (buckets: `openebs-backups`, `thanos-blocks`, `victoria-logs-chunks`)
- **Velero** — Cluster-level S3-backed snapshots (daily 02:00 UTC, 30-day retention)

Each component gets isolated S3 credentials as SOPS-encrypted secrets (`{component}-s3-secret`).

### Observability

- **Grafana** — Unified dashboards (deployed via Grafana Operator with `GrafanaInstance` + `GrafanaDashboard` CRDs)
- **kube-prometheus-stack** — Prometheus with ServiceMonitors, recording rules, and alerting
- **Thanos** — Long-term metrics storage with S3 backend (`thanos-blocks` bucket)
- **Victoria Logs** — Log aggregation with S3 persistence and syslog ingestion
- **netdata** — Real-time system metrics and visualization
- **unpoller** — UniFi network device monitoring

**Note**: Single-replica deployments; S3 provides durability.

### Databases

- **CloudNative-PG** — PostgreSQL operator with S3 backups
- **DragonflyDB** — Redis-compatible in-memory store

### Security

- **Tetragon** — Runtime security observability with eBPF (`kube-system` and `security` namespaces)
- **CrowdSec** — Collaborative IDS/IPS for threat detection and blocking

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
- **Home Assistant** — Home automation platform
- **Linkwarden** — Collaborative bookmark manager
- **ChangeDetector** — Website change monitoring
- **IT-Tools** — Collection of IT utility tools
- **Memos** — Lightweight note-taking service
- **N8N** — Workflow automation platform
- **Ollama** — Local LLM inference server
- **Open WebUI** — Web interface for Ollama
- **Paperless-NGX** — Document management system
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
