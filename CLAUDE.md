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
task flux:reconcile                              # Force git source + cluster kustomization reconcile
task flux:bootstrap                              # Bootstrap Flux into cluster (first-time)
task flux:apply path=network/cloudflared         # Build and apply a specific Flux Kustomization
```

### Talos Operations

```bash
task talos:generate-config                       # Generate configs from talconfig.yaml
task talos:apply-node IP=192.168.1.100 MODE=auto # Apply config to a node
task talos:upgrade-node IP=192.168.1.100         # Upgrade Talos on a node
task talos:upgrade-k8s                           # Upgrade Kubernetes version
task talos:reset                                 # Reset all nodes (DESTRUCTIVE, prompts)
```

### Workload Operations

```bash
task workload:sync ns=monitoring ks=grafana      # Reconcile a Kustomization
task workload:sync ns=monitoring hr=grafana      # Reconcile a HelmRelease
task workload:minisync ns=monitoring hr=grafana  # Quick HelmRelease reconcile
```

### VolSync Backup/Restore

```bash
task volsync:list app=sonarr ns=services         # List snapshots for an app
task volsync:snapshot app=sonarr ns=services     # Trigger manual snapshot
task volsync:restore app=sonarr ns=services      # Restore from snapshot (suspends/resumes)
task volsync:unlock app=sonarr ns=services       # Unlock stuck Restic repo
```

### SOPS Secret Management

```bash
task sops:encrypt                                # Encrypt all *.sops.* files under kubernetes/
task sops:decrypt                                # Decrypt all *.sops.* files
task sops:encrypt-file file=path/to/secret.yaml  # Encrypt a specific file
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

## Secret Management

**SOPS config** (`.sops.yaml`): age-key encryption with path-based rules:

- `talos/` — entire files encrypted
- `kubernetes/`, `bootstrap/`, `archive/` — only `data` and `stringData` fields encrypted

All secrets MUST be encrypted before committing. Name encrypted files `*.sops.yaml`.

## Architecture

### Networking

- **Cilium** — eBPF-based CNI and network policy engine
- **Cloudflared** — Cloudflare DNS integration
- **external-dns** — Automatic DNS registration
- **cert-manager** — TLS certificate automation
- **k8s-gateway** — Split-horizon DNS

### Storage

- **OpenEBS LocalPV** — Default storage class (`openebs-localpv-hostpath`)
- **Minio S3** — Object storage at `https://s3.68cc.io` (buckets: `openebs-backups`, `loki-chunks`, `tempo-traces`, `mimir-blocks`)
- **Velero** — Cluster-level S3-backed snapshots (daily 02:00 UTC, 30-day retention)
- **VolSync** — Application-level Restic backups to S3

Each component gets isolated S3 credentials as SOPS-encrypted secrets (`{component}-s3-secret`).

### Observability (LGTM Stack)

- **Grafana** — Unified dashboards
- **Loki** — Log aggregation (S3 backend, simple scalable mode)
- **Tempo** — Distributed tracing (S3 backend, monolithic mode)
- **Mimir** — Long-term metrics (S3 backend, monolithic mode)
- **OpenTelemetry Collector** — Telemetry collection pipeline
- **kube-prometheus-stack** — Prometheus with remote-write to Mimir

### Databases

- **CloudNative-PG** — PostgreSQL operator with S3 backups
- **DragonflyDB** — Redis-compatible in-memory store

### Security

- **Falco** — Runtime threat detection
- **Toolhive** — In-cluster MCP servers (`toolhive-system` namespace, managed via `kubernetes/components/toolhive/`)

### Application Namespaces

`cert-manager`, `databases`, `flux-system`, `kube-system`, `monitoring`, `network`, `security`, `services`, `toolhive-system`, `velero`

## CI/CD

### GitHub Actions Workflows

- **flux-diff** — Shows Flux Kustomization diffs on PRs
- **yamllint** — Lints all YAML files
- **lychee** — Checks for broken links
- **label-sync** — Syncs GitHub labels from `.github/labels.yaml`

### Renovate

Config at `.github/renovate.json5`. Auto-merge behavior:

- **Patch** container images, Helm charts, GitHub releases — auto-merge
- **Minor** updates across all types — auto-merge
- **Major** updates — manual review required
- **Talos installer** — scheduled for Saturday after 2pm, no auto-merge

Commit prefixes: `fix(container):`, `fix(helm):`, `fix(deps):`, `feat(deps):`

## Key Design Decisions

- **Single replicas everywhere** — S3 provides data durability instead of pod replication
- **Monolithic deployment modes** — Resource efficiency over distributed complexity
- **Resource-constrained** — Prefer vertical scaling, memory <2Gi per pod
- **FluxCD over ArgoCD** — Simpler for home-lab, native Kubernetes CRDs
- **SOPS + age** — Git-native encryption, no external dependency
- **Immutable infrastructure** — Talos nodes are API-configured, never SSH'd into

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

# Validate manifests before pushing
kustomize build kubernetes/apps/{namespace}/{app}/app
```
