<div align="center">

### Home Operations

_Talos · Flux · Renovate · GitHub Actions_

</div>

<div align="center">

[![Talos](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2Fj0sh3rs%2Fhome-ops%2Fmain%2Ftalos%2Ftalenv.yaml&query=%24.talosVersion&style=for-the-badge&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz4KPCEtLSBHZW5lcmF0b3I6IEFkb2JlIElsbHVzdHJhdG9yIDI3LjguMSwgU1ZHIEV4cG9ydCBQbHVnLUluIC4gU1ZHIFZlcnNpb246IDYuMDAgQnVpbGQgMCkgIC0tPgo8c3ZnIHZlcnNpb249IjEuMSIgaWQ9IkxheWVyXzEiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiIHg9IjBweCIgeT0iMHB4IgoJIHZpZXdCb3g9IjAgMCA1MDAgNTAwIiBzdHlsZT0iZW5hYmxlLWJhY2tncm91bmQ6bmV3IDAgMCA1MDAgNTAwOyIgeG1sOnNwYWNlPSJwcmVzZXJ2ZSI%2BCjxzdHlsZSB0eXBlPSJ0ZXh0L2NzcyI%2BCgkuc3Qwe2ZpbGw6I0ZGNjcwMDt9Cjwvc3R5bGU%2BCjxnPgoJPHBhdGggY2xhc3M9InN0MCIgZD0iTTI1MC43LDM5LjVDMTM0LjIsMzkuNSwzOS41LDEzNC4yLDM5LjUsMjUwLjdTMTM0LjIsNDYxLjksMjUwLjcsNDYxLjlTNDYxLjksMzY3LjIsNDYxLjksMjUwLjcKCQlTMzY3LjIsMzkuNSwyNTAuNywzOS41eiBNMjY3LjMsMzgzLjRIMjMzLjZWMjY3LjRoLTQ5LjRWMjMzLjdoNDkuNHYtMTE1LjdoMzMuN3YxMTUuN2g0OS40djMzLjdoLTQ5LjRWMzgzLjR6Ii8%2BCjwvZz4KPC9zdmc%2BCg%3D%3D&color=orange&label)](https://www.talos.dev/)&nbsp;&nbsp;
[![Kubernetes](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2Fj0sh3rs%2Fhome-ops%2Fmain%2Ftalos%2Ftalenv.yaml&query=%24.kubernetesVersion&style=for-the-badge&logo=kubernetes&logoColor=white&color=blue&label)](https://kubernetes.io/)&nbsp;&nbsp;
[![Flux](https://img.shields.io/badge/Flux-CD?style=for-the-badge&logo=flux&logoColor=white&color=blue)](https://fluxcd.io/)&nbsp;&nbsp;
[![Renovate](https://img.shields.io/badge/Renovate-enabled?style=for-the-badge&logo=renovatebot&logoColor=white&color=blue)](https://github.com/renovatebot/renovate)

</div>

---

## Overview

Monorepo for a bare-metal home-lab Kubernetes cluster. Infrastructure as Code throughout: cluster nodes are defined in `talos/talconfig.yaml`, every application lives under `kubernetes/apps/`, and FluxCD reconciles Git state to the cluster continuously. No imperative kubectl, no SSH into nodes.

The cluster doubles as a self-hosted AI lab — local inference runs on an AMD RDNA4 discrete GPU, fronted by a LiteLLM gateway that exposes a unified OpenAI-compatible API to all clients.

---

## Hardware

### Cluster Nodes

| Hostname | Role | CPU Generation | RAM | Boot Disk | Notes |
|---|---|---|---|---|---|
| `bee-jms-01` | Control Plane | AMD Zen2 | 28 GB | 500 GB NVMe | |
| `bee-jms-02` | Control Plane | AMD Zen3 | 64 GB | 500 GB NVMe | |
| `bee-jms-03` | Control Plane | AMD Zen3 | 28 GB | 500 GB NVMe | high-memory tier label |
| `bigboi-jms-01` | Worker | AMD Zen3 | 64 GB | 1 TB NVMe (boot) | AMD RX 9070 XT (RDNA4, 16 GB VRAM); 1 TB SATA SSD + 500 GB NVMe as OpenEBS UserVolumes |

All four nodes are **bare-metal**, running **Talos Linux** — immutable, API-driven, no SSH. Control planes are schedulable; every node runs workloads. Jumbo frames (MTU 9000) across all node interfaces. The three control-plane nodes form an etcd quorum; quorum safety gates in `task talos:apply-node` and `task talos:upgrade-node` prevent concurrent mutation.

### Storage & Network

| Device | Role |
|---|---|
| Synology DS920+ (4×7.3 TB SSD + 2×500 GB SSD cache, 20 GB RAM) | NFS primary storage + Velero backup target |
| RustFS (`s3.68cc.io`, in-cluster) | S3-compatible object store for Velero snapshots, Thanos/VictoriaMetrics blocks, VictoriaLogs chunks, CNPG backups |
| UniFi Dream Machine Pro | Router / gateway |
| UniFi managed switch | Jumbo-frame LAN fabric |

---

## Platform

### Operating System

[Talos Linux](https://www.talos.dev/) — immutable OS configured entirely via API (`talhelper` + `talosctl`). Nodes are never SSH'd into. Cluster-wide patches live in `talos/patches/`; per-node config in `talos/talconfig.yaml`. Active Talos extensions: `amdgpu` (RDNA4 GPU passthrough), NVMe power management, custom kernel sysctls.

### GitOps

[FluxCD](https://fluxcd.io/) via the [Flux Operator](https://github.com/controlplaneio-fluxcd/flux-operator) watches `kubernetes/` and reconciles continuously. The `FluxInstance` CR in `flux-system` defines the cluster's Flux configuration; a webhook receiver enables push-triggered reconciliation.

All applications follow the **OCIRepository + chartRef** pattern — Helm charts are pulled from OCI registries directly, not via legacy `HelmRepository` + `chart.spec.sourceRef`. The `bjw-s/app-template` chart is opt-in per namespace via a Kustomize Component.

[Renovate](https://github.com/renovatebot/renovate) manages all dependency updates (container images, Helm chart versions, GitHub releases, CLI tooling). Patch and minor updates auto-merge; major updates require manual review. Talos OS upgrades are scheduled for Saturdays and never auto-merge.

### Secret Management

[SOPS](https://github.com/getsops/sops) with age-key encryption. Path-based rules in `.sops.yaml` encrypt only `data`/`stringData` fields in Kubernetes manifests. All secrets are committed encrypted; nothing sensitive is ever stored in plaintext. The age key is injected at bootstrap and never leaves the cluster.

---

## Repository Structure

```
kubernetes/
├── apps/                        # Application deployments, organized by namespace
│   ├── ai/                      # AI inference stack (LiteLLM, llama-swap, Open WebUI, …)
│   ├── cert-manager/
│   ├── databases/               # CNPG, DragonflyDB, ClickHouse
│   ├── flux-system/             # Flux Operator + FluxInstance + webhook receiver
│   ├── kelos-system/            # Kelos agent framework
│   ├── kube-system/             # CNI, storage, cluster add-ons
│   ├── monitoring/              # Grafana, Prometheus stack, VictoriaMetrics, logs
│   ├── network/                 # Traefik, Cloudflare tunnel, external-dns
│   ├── security/                # Authentik, CrowdSec
│   ├── services/                # User-facing apps (Home Assistant, Paperless, …)
│   └── velero/
├── flux/
│   ├── cluster/                 # Cluster-level Kustomizations and variable substitution
│   └── meta/repos/              # Shared HelmRepository and OCIRepository sources
└── components/                  # Reusable Kustomize components
    ├── authentik-forwardauth/   # Authentik forwardAuth Middleware, opt-in per namespace
    ├── common/                  # Namespace + cluster-secrets + sops-age
    └── repos/app-template/      # bjw-s app-template OCIRepository, opt-in per namespace
talos/
├── patches/                     # Global + controller machine config patches
├── talconfig.yaml               # Node definitions, network, labels, UserVolumes
└── talenv.yaml                  # Talos and Kubernetes version pins (Renovate-tracked)
bootstrap/                       # First-time secrets and cluster bring-up scripts
.taskfiles/                      # go-task definitions for all operational workflows
```

---

## Applications

### Networking (`network`)

| Component | Purpose |
|---|---|
| [Traefik](https://traefik.io/) (×2) | Gateway API ingress — `traefik-external` (public, Cloudflare tunnel origin) and `traefik-internal` (LAN-only) |
| [cert-manager](https://cert-manager.io/) | TLS automation; wildcard cert covers all cluster services |
| [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) | Zero-trust public ingress without open inbound ports |
| external-dns (cloudflare + unifi) | Split-horizon DNS: Cloudflare CNAMEs for public routes, UniFi LAN A records for internal |
| [Gateway API CRDs](https://gateway-api.sigs.k8s.io/) | Standard Kubernetes Gateway API |

### Security (`security`)

| Component | Purpose |
|---|---|
| [Authentik](https://goauthentik.io/) | Identity provider; Google OAuth backend; forwardAuth gateway for all apps |
| [CrowdSec](https://www.crowdsec.net/) | Collaborative IDS/IPS with Traefik bouncer middleware on all entrypoints |
| [Tetragon](https://tetragon.io/) | eBPF runtime security observability (deployed in `kube-system`) |

All apps route through Authentik forwardAuth at the gateway layer. Namespaces opt in by adding the `authentik-forwardauth` Kustomize Component; individual HTTPRoutes reference the Middleware via Gateway API `ExtensionRef`.

### System (`kube-system`)

| Component | Purpose |
|---|---|
| [Cilium](https://cilium.io/) | eBPF CNI and network policy engine |
| [OpenEBS LocalPV](https://openebs.io/) | Default storage class (`openebs-hostpath`); fast NVMe tier (`openebs-hostpath-fast`) pinned to `bigboi-jms-01` |
| [NFS External Provisioner](https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner) | `nfs-client` StorageClass backed by Synology |
| [Spegel](https://github.com/spegel-org/spegel) | P2P OCI image distribution across nodes |
| [Reflector](https://github.com/emberstack/kubernetes-reflector) | Secret/ConfigMap cross-namespace sync |
| [Reloader](https://github.com/stakater/Reloader) | Rolling restarts on ConfigMap/Secret changes |
| [Descheduler](https://github.com/kubernetes-sigs/descheduler) | Pod rebalancing across nodes |
| [K8tz](https://github.com/k8tz/k8tz) | Timezone injection for pods |
| [AMD GPU Device Plugin](https://github.com/ROCm/k8s-device-plugin) | Exposes `amd.com/gpu` resource on `bigboi-jms-01` |
| [metrics-server](https://github.com/kubernetes-sigs/metrics-server) | HPA/VPA resource metrics |
| Talos backup CronJob | Automated etcd backups to S3 |
| IRQBalance | Hardware interrupt distribution |
| [Tuppr](https://github.com/siderolabs/system-upgrade-controller) | System upgrade controller for managed Talos OS upgrades |

### Databases (`databases`)

| Component | Purpose |
|---|---|
| [CloudNative-PG](https://cloudnative-pg.io/) | PostgreSQL 18 operator; continuous WAL archival + scheduled base backups via CNPG Barman Cloud plugin |
| [DragonflyDB](https://dragonflydb.io/) | Redis-compatible in-memory store; shared instance with per-DB allocation per consumer |

### Observability (`monitoring`)

| Component | Purpose |
|---|---|
| [Grafana Operator](https://grafana-operator.github.io/grafana-operator/) | Declarative dashboard management via `GrafanaInstance` + `GrafanaDashboard` CRDs |
| [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts) | Prometheus (custom `prompp` drop-in image), Alertmanager (Discord webhook for critical alerts), ServiceMonitors |
| [VictoriaMetrics](https://victoriametrics.com/) | Long-term metrics storage, replacing Thanos + standard Prometheus |
| [VictoriaLogs](https://docs.victoriametrics.com/victorialogs/) | Log aggregation ingested by a Vector DaemonSet on every node; chunks stored in S3 |
| [Netdata](https://www.netdata.cloud/) | System-level node monitoring |
| [unpoller](https://github.com/unpoller/unpoller) | UniFi network device metrics |
| AMD Device Metrics Exporter | GPU utilization and VRAM metrics from `bigboi-jms-01` |

Grafana dashboards are CRDs — adding a dashboard means committing a `GrafanaDashboard` CR, not clicking in the UI.

### AI (`ai`)

The cluster runs a fully self-hosted AI stack. All clients speak to **LiteLLM** via a single OpenAI-compatible endpoint; LiteLLM routes to local inference or cloud providers transparently.

**Inference**

| Component | Purpose |
|---|---|
| [llama-swap](https://github.com/mostlygeek/llama-swap) | Local GGUF inference on AMD RX 9070 XT (RDNA4, 16 GB VRAM) via Vulkan. Hot-swap via model groups; embed + rerank stay resident |
| [faster-whisper](https://github.com/fedirz/faster-whisper-server) | Speech-to-text (Wyoming protocol) wired to Home Assistant Assist |
| [piper](https://github.com/rhasspy/wyoming-piper) | Text-to-speech (Wyoming protocol) wired to Home Assistant Assist |

**Gateway & Routing**

| Component | Purpose |
|---|---|
| [LiteLLM](https://github.com/BerriAI/litellm) | OpenAI-compatible API gateway routing to local and cloud models. Named model aliases: `local-fast`, `local-balanced`, `local-coder`, `local-coder-small`, `local-large`, `local-embed`, `local-rerank` |

**Clients & Tools**

| Component | Purpose |
|---|---|
| [n8n](https://n8n.io/) | Workflow automation; LLM nodes wired to LiteLLM |
| [OpenCode](https://github.com/anomalyco/opencode) | Web-based AI coding assistant |
| [Kelos](https://kelos.ai/) | Agent framework for loop orchestration |
| [MCPJungle](https://github.com/mcpjungle/mcpjungle) | MCP server registry and proxy |
| [Omega MCP](https://github.com/omega-memory/omega-mcp) | Persistent cross-session memory for AI agents |

### Services (`services`)

| Application | Purpose |
|---|---|
| [Home Assistant](https://www.home-assistant.io/) | Home automation; `hostNetwork` for mDNS/UPnP device discovery |
| [Homebridge](https://homebridge.io/) | HomeKit bridge; `hostNetwork` for HAP advertisement |
| [Paperless-NGX](https://docs.paperless-ngx.com/) | Document management with OCR; Tika + Gotenberg sidecars for conversion |
| [Atuin](https://atuin.sh/) | Self-hosted shell history sync |
| [Homepage](https://gethomepage.dev/) | Cluster dashboard at the root domain |
| [Linkwarden](https://linkwarden.app/) | Bookmark manager |
| [IT-Tools](https://github.com/CorentinTh/it-tools) | WebUI for common DevOps utilities |
| [Mosquitto](https://mosquitto.org/) | MQTT broker for Home Assistant integrations |

### Backup & Recovery (`velero`)

[Velero](https://velero.io/) provides cluster-level S3-backed disaster recovery (daily 02:00 UTC, 30-day retention). CNPG manages its own continuous WAL archival and scheduled base backups via the Barman Cloud plugin — independent of Velero.

---

## Development Patterns

### Adding a New Application

1. Create `kubernetes/apps/{namespace}/{app}/` with the standard layout:
   ```
   {app}/
   ├── ks.yaml              # Flux Kustomization — entry point, sets path + interval
   └── app/
       ├── kustomization.yaml
       ├── ocirepository.yaml   # OCIRepository chart source (preferred over HelmRepository)
       ├── helmrelease.yaml     # HelmRelease using chartRef (not chart.spec.sourceRef)
       └── secret.sops.yaml     # SOPS-encrypted secrets (if needed)
   ```
2. Add `- ./{app}/ks.yaml` to the namespace's `kustomization.yaml`.
3. Apps without an upstream Helm chart use `bjw-s/app-template` — opt the namespace in via `components: - ../../components/repos/app-template`.
4. **Public-facing**: reference `traefik-external-gateway` in the HTTPRoute, annotate with the external-dns target, and reference the `authentik-forwardauth` Middleware via `ExtensionRef`.
5. **LAN-only**: reference `traefik-internal-gateway` instead; no Cloudflare DNS record will be created.
6. Encrypt secrets before commit: `task sops:encrypt-file file=kubernetes/apps/{namespace}/{app}/app/secret.sops.yaml`
7. Validate locally before pushing: `kustomize build kubernetes/apps/{namespace}/{app}/app`

**Always use `OCIRepository` + `chartRef`.** Do not copy the legacy `HelmRepository` + `chart.spec.sourceRef` pattern from older apps in the repo.

### Storage Class Selection

| Workload type | StorageClass | Rationale |
|---|---|---|
| Database data dirs (CNPG, DragonflyDB) | `openebs-hostpath` | Local NVMe; sub-ms IO; durability via S3 backup |
| Model weights, embedding caches | `openebs-hostpath` | Large sequential reads; local avoids NFS throughput cap |
| Log shards, TSDB blocks | `openebs-hostpath` | Write-heavy append-only; NFS metadata overhead is too costly |
| Apps that must survive pod reschedule, low write rate | `nfs-client` | Survives reschedule across nodes |
| RWX / multi-replica shared access | `nfs-client` | Only class supporting multi-node concurrent access |

Default to `openebs-hostpath`. Use `nfs-client` only when the pod must reschedule without data loss and write rate is low. Durability is never the PVC's job — S3 backups are the durability layer.

`openebs-hostpath-fast` (backed by a dedicated NVMe UserVolume on `bigboi-jms-01`) is available for latency-sensitive workloads that also need GPU colocation.

### Talos Node Operations

Quorum safety is enforced at the task level — `etcd-quorum-precheck` runs before any node-mutating operation:

```bash
task talos:apply-node IP=<node-ip> MODE=auto   # safe: runs quorum precheck first
task talos:upgrade-node IP=<node-ip>            # safe: same precheck
```

**Never run two node-mutating tasks in parallel.** One node at a time — wait for the target to rejoin and report healthy before touching the next. Ad-hoc `talosctl reboot` bypasses the quorum gate; cordon + drain the node first and verify peer etcd health manually before issuing bare talosctl commands.

### Secret Workflow

```bash
task sops:encrypt-file file=path/to/secret.sops.yaml  # encrypt a single file
task sops:verify                                       # verify all *.sops.yaml before push
task sops:view file=path/to/secret.sops.yaml           # read-only view
task sops:edit file=path/to/secret.sops.yaml           # decrypt → edit → re-encrypt atomically
```

The CI `validate-secrets` workflow blocks any PR containing an unencrypted `*.sops.yaml`.

### AI Model ID Convention

The `model:` field in LiteLLM's `model_list` must be a **llama-swap model key or alias**, not a GGUF filename. Source of truth: `kubernetes/apps/ai/llama-swap/app/configmap.yaml`. Getting this wrong causes silent routing failures — LiteLLM accepts the request but llama-swap returns 404.

---

## CI/CD

### GitHub Actions

| Workflow | Purpose |
|---|---|
| `validate-secrets` | Blocks PRs containing unencrypted `*.sops.yaml` files |
| `flux-local` | Flux manifest validation + kubeconform schema check + diff generation on PRs |
| `labeler` | Auto-labels PRs by changed path with risk tiers (`risk/critical` → `risk/low`) |
| `label-sync` | Syncs GitHub labels from `.github/labels.yaml` |
| `e2e` | End-to-end cluster tests |

### Renovate

Config: `.github/renovate.json5`

- **Auto-merge**: patch + minor for container images, Helm charts, GitHub releases
- **Manual review**: all major version bumps
- **Talos schedule**: Saturdays after 14:00, never auto-merge

Commit prefixes: `fix(container):`, `fix(helm):`, `fix(deps):`, `feat(deps):`

---

## Cloud Dependencies

| Service | Use | Cost |
|---|---|---|
| [Cloudflare](https://www.cloudflare.com/) | DNS, tunneled public ingress, WAF | ~$30/yr (domain registration; Free plan features) |
| [GitHub](https://github.com/) | Repository hosting, CI/CD via Actions | Free |

The cluster is intentionally self-contained. Cloud dependencies are limited to DNS and the zero-trust tunnel — no managed compute, no managed databases.

---

## Toolchain

```bash
# First-time setup
mise trust && mise install   # installs talhelper, talosctl, flux, task, kubectl, age, sops

# Common operations
task -l                      # list all available tasks
task reconcile               # force-reconcile flux-system
task flux:status             # show all Kustomization + HelmRelease status
task template:debug          # dump common cluster resource state
task sops:verify             # verify all secrets are encrypted
```

`mise` injects `KUBECONFIG`, `SOPS_AGE_KEY_FILE`, and `TALOSCONFIG` automatically via `.mise.toml`. No manual environment setup required after `mise install`. Do not pass `--context` to `kubectl`/`helm`/`flux` — the injected kubeconfig points at the cluster directly.

---

## Gratitude

Thanks to the [Home Operations](https://discord.gg/home-operations) Discord community and everyone publishing their configs. [kubesearch.dev](https://kubesearch.dev/) is a great reference for deployment patterns across the community.

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=j0sh3rs/home-ops&type=Date)](https://star-history.com/#j0sh3rs/home-ops&Date)

</div>
