# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a home-lab Kubernetes cluster built on **Talos Linux** with **FluxCD** for GitOps-based deployments. The cluster uses SOPS for secret encryption, mise for development environment management, and follows a structured approach to application deployment via Helm charts and Kustomize overlays.

## Development Environment Setup

**Tool Management**: This project uses [mise](https://mise.jdx.dev/) to manage all development tools.

```bash
# Trust and install all tools (first time only)
mise trust
pip install pipx
mise install

# Tools installed include: kubectl, helm, flux, talosctl, talhelper, sops, age, kustomize, yq, jq
```

**Environment Variables**: Automatically set by mise from `.mise.toml`:

- `KUBECONFIG`: `./kubeconfig` - Cluster access configuration
- `SOPS_AGE_KEY_FILE`: `./age.key` - SOPS decryption key
- `TALOSCONFIG`: `./talos/clusterconfig/talosconfig` - Talos cluster config

## Common Commands

### Cluster Operations

```bash
# Force Flux to reconcile (pull latest from Git)
task reconcile

# Bootstrap Talos Linux on nodes
task bootstrap:talos

# Bootstrap applications into cluster
task bootstrap:apps

# Check Flux status
flux check
flux get sources git -A
flux get ks -A
flux get hr -A

# Check Cilium status
cilium status
```

### Talos Operations

```bash
# Generate Talos configuration from talconfig.yaml
task talos:generate-config

# Apply configuration to a node
task talos:apply-node IP=192.168.1.100 MODE=auto

# Upgrade Talos on a node
task talos:upgrade-node IP=192.168.1.100

# Upgrade Kubernetes version
task talos:upgrade-k8s

# Reset cluster (WARNING: destructive)
task talos:reset
```

### Debugging and Inspection

```bash
# View pods across all namespaces
kubectl get pods -A --watch

# Check namespace-specific resources
kubectl -n <namespace> get pods -o wide
kubectl -n <namespace> logs <pod-name> -f
kubectl -n <namespace> describe <resource> <name>
kubectl -n <namespace> get events --sort-by='.metadata.creationTimestamp'

# Check HelmRelease status for an app
kubectl -n <namespace> describe helmrelease <app-name>

# View Flux reconciliation logs
kubectl -n flux-system logs -l app=flux --tail=100 -f
```

### Secret Management

```bash
# Encrypt a secret (must be in kubernetes/ or talos/ directory)
sops -e -i path/to/secret.yaml

# Decrypt a secret to view contents
sops -d path/to/secret.sops.yaml

# Edit encrypted secret in place
sops path/to/secret.sops.yaml
```

## Repository Architecture

### Directory Structure

```
├── kubernetes/
│   ├── apps/                          # Application deployments
│   │   ├── cert-manager/              # Certificate management
│   │   ├── databases/                 # CloudNative-PG, DragonflyDB
│   │   ├── flux-system/               # Flux operator and instance
│   │   ├── kube-system/               # Core system components
│   │   ├── monitoring/                # Grafana, Loki, Tempo, Mimir
│   │   ├── network/                   # Cloudflared, external-dns
│   │   ├── security/                  # Falco
│   │   ├── services/                  # User-facing applications
│   │   └── velero/                    # Backup solution
│   ├── flux/
│   │   ├── cluster/                   # Cluster-level Flux resources
│   │   ├── meta/                      # Repository sources
│   │   └── repositories/              # Helm repositories
│   └── components/                    # Shared Kustomize components
├── talos/
│   ├── clusterconfig/                 # Generated Talos configs (gitignored)
│   ├── patches/                       # Talos configuration patches
│   │   ├── controller/                # Control plane patches
│   │   └── global/                    # Global node patches
│   ├── talconfig.yaml                 # Talos cluster definition
│   └── talenv.yaml                    # Talos/K8s versions
├── bootstrap/                         # Bootstrap scripts
├── scripts/                           # Utility scripts
├── cluster.yaml                       # Cluster configuration template
└── nodes.yaml                         # Node definitions template
```

### Application Deployment Pattern

Each application follows the **Flux Kustomization + HelmRelease** pattern:

```
kubernetes/apps/{namespace}/{app}/
├── ks.yaml                           # Flux Kustomization (entry point)
└── app/
    ├── kustomization.yaml            # Kustomize overlay
    ├── helmrelease.yaml              # Helm chart configuration
    ├── secret.sops.yaml              # Encrypted secrets (optional)
    └── *.yaml                        # Additional resources (optional)
```

**Key Points**:

- `ks.yaml` is the Flux entry point that references the `app/` directory
- `helmrelease.yaml` defines the Helm chart version and values
- All secrets MUST be encrypted with SOPS before committing
- Each app is namespaced and organized by function

### Flux Repository Structure

**Helm Repositories**: Defined in `kubernetes/flux/meta/repos/*.yaml`

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
    name: repo-name
    namespace: flux-system
spec:
    interval: 1h
    url: https://charts.example.com
```

**OCIRepository Pattern**: For OCI-based charts

```yaml
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: OCIRepository
metadata:
    name: chart-name
spec:
    interval: 12h
    url: oci://ghcr.io/org/charts/chart-name
    ref:
        semver: ">=1.0.0"
```

## Secret Management

**SOPS Configuration** (`.sops.yaml`):

- `talos/`: Entire files encrypted
- `kubernetes/`, `bootstrap/`, `archive/`: Only `data` and `stringData` fields encrypted

**Creating Encrypted Secrets**:

```bash
# Create secret template
kubectl create secret generic my-secret \
  --from-literal=key=value \
  --dry-run=client -o yaml > secret.yaml

# Encrypt with SOPS
sops -e -i secret.yaml
mv secret.yaml secret.sops.yaml
```

**IMPORTANT**: Never commit unencrypted secrets. All `*.sops.yaml` files should show encrypted content.

## Storage Architecture

**Primary Storage**: OpenEBS LocalPV Provisioner

- Storage class: `openebs-localpv-hostpath` (default)
- Dynamic provisioning for persistent volumes
- Local node storage for performance

**S3 Object Storage**: Local Minio instance (`https://s3.68cc.io`)

- Used for: Backup snapshots, observability data persistence
- Buckets: `openebs-backups`, `mimir-blocks`
- Each component has dedicated SOPS-encrypted S3 secrets

**Disaster Recovery**: Velero

- S3-backed snapshots
- Daily backups at 02:00 UTC
- 30-day retention policy

## Observability Stack (LGTM)

**Logs**: VictoriaMetrics with S3 backend (simple scalable mode)
**Metrics**: Mimir with S3 backend (monolithic mode, long-term storage)
**Visualization**: Grafana with datasources for Prometheus, Loki, Tempo, Mimir
**Collection**: OpenTelemetry Collector for logs and metrics sending to Mimir

## Key Architectural Decisions

1. **Talos Linux**: Immutable OS, API-driven configuration, secure by default
2. **FluxCD over ArgoCD**: Simpler for home-lab, native Kubernetes CRDs
3. **SOPS + age**: Git-native secret encryption, no external dependencies
4. **OpenEBS LocalPV**: Local storage for performance, S3 for durability
5. **Monolithic**: Resource efficiency over distributed complexity
6. **Single Replicas**: Home-lab scale, S3 provides data durability

## Workflow Guidelines

### Adding a New Application

1. **Create app structure**:

    ```bash
    mkdir -p kubernetes/apps/{namespace}/{app}/app
    ```

2. **Create Kustomization** (`ks.yaml`):

    ```yaml
    apiVersion: kustomize.toolkit.fluxcd.io/v1
    kind: Kustomization
    metadata:
        name: app-name
        namespace: target-namespace
    spec:
        interval: 1h
        path: ./kubernetes/apps/{namespace}/{app}/app
        prune: true
        sourceRef:
            kind: GitRepository
            name: flux-system
            namespace: flux-system
    ```

3. **Create HelmRelease** (`app/helmrelease.yaml`):

    ```yaml
    apiVersion: helm.toolkit.fluxcd.io/v2
    kind: HelmRelease
    metadata:
        name: app-name
    spec:
        interval: 30m
        chart:
            spec:
                chart: chart-name
                version: x.y.z
                sourceRef:
                    kind: HelmRepository
                    name: repo-name
                    namespace: flux-system
        values:
            # Helm chart values here
    ```

4. **Create Kustomize overlay** (`app/kustomization.yaml`):

    ```yaml
    apiVersion: kustomize.config.k8s.io/v1beta1
    kind: Kustomization
    resources:
        - helmrelease.yaml
    ```

5. **Add secrets if needed** (`app/secret.sops.yaml`):
    - Create unencrypted YAML first
    - Encrypt with `sops -e -i secret.yaml`
    - Rename to `secret.sops.yaml`
    - Reference in `kustomization.yaml`

6. **Commit and push**:

    ```bash
    git add kubernetes/apps/{namespace}/{app}
    git commit -m "feat: add {app} application"
    git push
    ```

7. **Force reconciliation**:
    ```bash
    task reconcile
    # Or wait for Flux's automatic reconciliation (default: 1h)
    ```

### Updating Application Configuration

1. Edit `helmrelease.yaml` to change Helm values or chart version
2. Commit changes: `git commit -m "fix: update {app} configuration"`
3. Push: `git push`
4. Reconcile: `task reconcile` or wait for automatic sync

**NOTE**: Renovate automatically opens PRs for chart version updates.

### Debugging Failed Deployments

1. Check Flux resources:

    ```bash
    flux get hr -n {namespace}  # Check HelmRelease status
    flux logs --kind=HelmRelease --namespace={namespace} --name={app}
    ```

2. Check Kubernetes resources:

    ```bash
    kubectl -n {namespace} get pods
    kubectl -n {namespace} logs {pod-name}
    kubectl -n {namespace} describe pod {pod-name}
    ```

3. Check events:

    ```bash
    kubectl -n {namespace} get events --sort-by='.metadata.creationTimestamp'
    ```

4. Verify secrets are decrypted (Flux handles this automatically via SOPS):
    ```bash
    kubectl -n {namespace} get secret {secret-name} -o yaml
    ```

## Development Best Practices

1. **Always encrypt secrets**: Use `sops -e -i` before committing any secrets
2. **Follow the pattern**: Use the established `ks.yaml` + `app/` structure
3. **Test locally**: Use `kustomize build` to validate manifests before pushing
4. **Version pinning**: Always specify exact chart versions in HelmRelease
5. **Namespace organization**: Group apps by function (monitoring, databases, services, etc.)
6. **Resource limits**: Define resource requests/limits for all workloads (home-lab constraints)
7. **Use Flux reconcile**: After changes, use `task reconcile` to force immediate sync

## Additional Resources

- **Talos Documentation**: https://www.talos.dev/
- **Flux Documentation**: https://fluxcd.io/flux/
- **Template Repository**: https://github.com/onedr0p/cluster-template
- **Community Support**: Discord - https://discord.gg/home-operations
