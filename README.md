<div align="center">

### Home Operations Repository :octocat:

_... managed with Flux, Renovate, and GitHub Actions_

</div>

<div align="center">

[![Talos](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2Fj0sh3rs%2Fhome-ops%2Fmain%2Ftalos%2Ftalenv.yaml&query=%24.talosVersion&style=for-the-badge&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz4KPCEtLSBHZW5lcmF0b3I6IEFkb2JlIElsbHVzdHJhdG9yIDI3LjguMSwgU1ZHIEV4cG9ydCBQbHVnLUluIC4gU1ZHIFZlcnNpb246IDYuMDAgQnVpbGQgMCkgIC0tPgo8c3ZnIHZlcnNpb249IjEuMSIgaWQ9IkxheWVyXzEiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiIHg9IjBweCIgeT0iMHB4IgoJIHZpZXdCb3g9IjAgMCA1MDAgNTAwIiBzdHlsZT0iZW5hYmxlLWJhY2tncm91bmQ6bmV3IDAgMCA1MDAgNTAwOyIgeG1sOnNwYWNlPSJwcmVzZXJ2ZSI%2BCjxzdHlsZSB0eXBlPSJ0ZXh0L2NzcyI%2BCgkuc3Qwe2ZpbGw6I0ZGNjcwMDt9Cjwvc3R5bGU%2BCjxnPgoJPHBhdGggY2xhc3M9InN0MCIgZD0iTTI1MC43LDM5LjVDMTM0LjIsMzkuNSwzOS41LDEzNC4yLDM5LjUsMjUwLjdTMTM0LjIsNDYxLjksMjUwLjcsNDYxLjlTNDYxLjksMzY3LjIsNDYxLjksMjUwLjcKCQlTMzY3LjIsMzkuNSwyNTAuNywzOS41eiBNMjY3LjMsMzgzLjRIMjMzLjZWMjY3LjRoLTQ5LjRWMjMzLjdoNDkuNHYtMTE1LjdoMzMuN3YxMTUuN2g0OS40djMzLjdoLTQ5LjRWMzgzLjR6Ii8%2BCjwvZz4KPC9zdmc%2BCg%3D%3D&color=orange&label)](https://www.talos.dev/)&nbsp;&nbsp;
[![Kubernetes](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2Fj0sh3rs%2Fhome-ops%2Fmain%2Ftalos%2Ftalenv.yaml&query=%24.kubernetesVersion&style=for-the-badge&logo=kubernetes&logoColor=white&color=blue&label)](https://kubernetes.io/)&nbsp;&nbsp;
[![Flux](https://img.shields.io/badge/Flux-CD?style=for-the-badge&logo=flux&logoColor=white&color=blue)](https://fluxcd.io/)&nbsp;&nbsp;
[![Renovate](https://img.shields.io/badge/Renovate-enabled?style=for-the-badge&logo=renovatebot&logoColor=white&color=blue)](https://github.com/renovatebot/renovate)

</div>

---

## Overview

This is a mono repository for my home infrastructure and Kubernetes cluster. It adheres to Infrastructure as Code (IaC) and GitOps practices using [Talos Linux](https://www.talos.dev/), [Flux](https://github.com/fluxcd/flux2), [Renovate](https://github.com/renovatebot/renovate), and [GitHub Actions](https://github.com/features/actions).

---

## Kubernetes

The cluster runs on [Talos Linux](https://www.talos.dev/) — an immutable, API-driven operating system purpose-built for Kubernetes. All nodes are bare-metal with Secure Boot and UKI enabled. Scheduling on control planes is allowed, so every node runs workloads.

### GitOps

[Flux](https://github.com/fluxcd/flux2) watches the `kubernetes/` directory and reconciles the cluster state to match this Git repository. Each application is deployed via a Flux `Kustomization` that references a `HelmRelease` with an `OCIRepository` chart source.

[Renovate](https://github.com/renovatebot/renovate) monitors the repository for dependency updates across container images, Helm charts, and CLI tools. Patch and minor updates are auto-merged; major updates require manual review.

### Core Components

| Component                                                       | Purpose                                     |
| --------------------------------------------------------------- | ------------------------------------------- |
| [cilium](https://github.com/cilium/cilium)                      | eBPF-based CNI and network policy engine    |
| [cert-manager](https://github.com/cert-manager/cert-manager)    | TLS certificate automation                  |
| [external-dns](https://github.com/kubernetes-sigs/external-dns) | Automatic DNS record management             |
| [k8s-gateway](https://github.com/ori-edge/k8s_gateway)          | Split-horizon DNS for internal resolution   |
| [sops](https://github.com/getsops/sops)                         | Git-native secret encryption with age keys  |
| [spegel](https://github.com/spegel-org/spegel)                  | Stateless cluster-level OCI registry mirror |
| [openebs](https://github.com/openebs/openebs)                   | LocalPV dynamic storage provisioner         |
| [volsync](https://github.com/backube/volsync)                   | Application-level Restic backups to S3      |
| [velero](https://github.com/vmware-tanzu/velero)                | Cluster-level S3-backed disaster recovery   |

### Observability (LGTM Stack)

| Component                                                                    | Purpose                                       |
| ---------------------------------------------------------------------------- | --------------------------------------------- |
| [grafana](https://github.com/grafana/grafana)                                | Unified dashboards and visualization          |
| [victoria-logs](https://docs.victoriametrics.com/victorialogs/)              | Log aggregation (Local backend)               |
| [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts) | Prometheus, Alertmanager, and ServiceMonitors |
| [unpoller](https://github.com/unpoller/unpoller)                             | UniFi network device monitoring               |
| [netdata](https://github.com/netdata/netdata)                                | System-level monitoring                       |

### Databases

| Component                                                          | Purpose                                         |
| ------------------------------------------------------------------ | ----------------------------------------------- |
| [cloudnative-pg](https://github.com/cloudnative-pg/cloudnative-pg) | PostgreSQL operator with S3 backups             |
| [dragonfly](https://github.com/dragonflydb/dragonfly)              | Memcached/Redis-compatible in-memory data store |

### Services

| Application                                                       | Description                      |
| ----------------------------------------------------------------- | -------------------------------- |
| [home-assistant](https://github.com/home-assistant/core)          | Home automation                  |
| [paperless-ngx](https://github.com/paperless-ngx/paperless-ngx)   | Document management              |
| [changedetection](https://github.com/dgtlmoon/changedetection.io) | Website change monitoring        |
| [atuin](https://atuin.sh/)                                        | Self-hosted synced shell history |
| [it-tools](https://github.com/CorentinTh/it-tools)                | WebUI for Common DevOps Actions  |
| [linkwarden](https://linkwarden.app/)                             | Self-hosted bookmark manager     |

### Repository Structure

```
kubernetes/
├── apps/            # Application deployments organized by namespace
├── flux/            # Flux operator, instance, and cluster configuration
└── components/      # Reusable Kustomize components
talos/
├── patches/         # Talos machine configuration patches
├── talconfig.yaml   # Cluster definition (nodes, networking, versions)
└── talenv.yaml      # Version pins for Talos and Kubernetes
bootstrap/           # First-time cluster bootstrap secrets and config
.taskfiles/          # Operational task definitions (Flux, Talos, VolSync, etc.)
```

---

## Cloud Dependencies

| Service                                   | Use                                      | Cost    |
| ----------------------------------------- | ---------------------------------------- | ------- |
| [Cloudflare](https://www.cloudflare.com/) | DNS and Dynamic DNS                      | ~$30/yr |
| [GitHub](https://github.com/)             | Repository hosting and CI/CD via Actions | Free    |

---

## Hardware

| Device                | Count | CPU      | Disk                            | RAM  | Purpose               |
| --------------------- | ----- | -------- | ------------------------------- | ---- | --------------------- |
| Control               | 1     | 16 cores | 500GB NVMe                      | 64GB | Kubernetes Controller |
| Control               | 1     | 16 cores | 500GB NVMe                      | 28GB | Kubernetes Controller |
| Control               | 1     | 8 cores  | 1T NVMe                         | 28GB | Kubernetes Controller |
| Synology DS920+       | 1     | —        | 4x7.3TB SSD + 2x500GB SSD Cache | 20GB | NFS + Backup Storage  |
| UDM Dream Machine Pro | 1     | —        | —                               | —    | Router/Gateway        |

---

## Automation

### GitHub Actions

| Workflow     | Purpose                                               |
| ------------ | ----------------------------------------------------- |
| `flux-diff`  | Shows Kustomization diffs on pull requests            |
| `yamllint`   | Lints all YAML files for syntax correctness           |
| `label-sync` | Synchronizes GitHub labels from `.github/labels.yaml` |

### Renovate

Automated dependency management via [Renovate](https://github.com/renovatebot/renovate):

- **Auto-merge**: Patch container images, Helm charts, and GitHub releases; minor updates across all types
- **Manual review**: Major version bumps
- **Talos upgrades**: Scheduled for Saturdays after 2pm, always require manual approval

---

## Stargazers

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=j0sh3rs/home-ops&type=Date)](https://star-history.com/#j0sh3rs/home-ops&Date)

</div>

---

## Gratitude and Thanks

Thanks to all the people who donate their time to the [Home Operations](https://discord.gg/home-operations) Discord community. Check out [kubesearch.dev](https://kubesearch.dev/) for deployment ideas and inspiration.
