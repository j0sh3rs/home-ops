# Homelab Hardware + Performance Optimization Research

**Date**: 2026-05-03
**Bead**: home-ops-bc1
**Scope**: Non-AI cluster hardware + performance optimizations, observability
gaps, and capacity rebalancing. Parallel track to the LLM/UMA work (home-ops-6tg
→ vo2 chain); deliberately excludes GPU/inference optimization.

## Cluster snapshot (verified 2026-05-03)

| Node | CPU tier | Cores | RAM | NVMe (ephemeral) | Pod count | Role |
|------|----------|-------|-----|------------------|-----------|------|
| bee-jms-01 | zen2 | 8 | 32 GiB | ~930 GiB | 27 | Control plane |
| bee-jms-02 | zen3 | 16 | 32 GiB | ~464 GiB | 47 | Control plane + VIP |
| bee-jms-03 | zen3 | 16 | 64 GiB | ~464 GiB | 61 | Control plane + GPU host |

Live utilization (kubectl top, instantaneous):

| Node | CPU | Mem |
|------|-----|-----|
| bee-jms-01 | 5% / 0.44 core | 26% / 7.3 GiB |
| bee-jms-02 | 1% / 0.30 core | 37% / 10.3 GiB |
| bee-jms-03 | 3% / 0.47 core | 17% / 10.5 GiB |

Platform: Talos v1.13, kernel 6.18.24, Kubernetes v1.36, Cilium CNI, Flux GitOps.

## Findings — prioritized

Each finding is sized as a **bead candidate**: title, priority, rough scope,
expected payoff. None are filed yet — that happens after user triage.

### Finding 1 — Stale `ollama` PVC (100 GiB) still bound (P2, trivial)

**Observation**: `services/ollama` PVC (100 GiB on openebs-hostpath) is
still `Bound` despite the Ollama workload being removed in home-ops-6tg in
favor of llama-swap. Consumes local NVMe on its assigned node.

**Expected payoff**: Recover 100 GiB of hostpath storage on whichever node
it landed. Low risk (models re-downloadable; new stack is llama-swap with
its own 50 GiB PVC already bound).

**Action**: Verify the Helm release / kustomization is fully removed, then
`kubectl -n services delete pvc ollama` after confirming no rollback intent.

### Finding 2 — Memory-tier imbalance vs pod distribution (P3, design)

**Observation**: bee-jms-03 carries 61 of 135 scheduled pods (45%) and has
double the RAM of its peers, yet sits at 17% memory utilization. bee-jms-02
(32 GiB) is at 37% — closer to pressure. Pod-count per node is driven by
anti-affinity + namespace defaults rather than capacity-aware scheduling.

**Expected payoff**: More headroom on bee-jms-02 for future workloads; less
blast radius on bee-jms-03 outage (currently 45% of pods). Likely no perf
change for healthy-state traffic.

**Action**: Audit anti-affinity and `nodeSelector` usage. Enable the
Descheduler `LowNodeUtilization` plugin if not already active. Cross-check
whether topology-spread constraints would express intent better than
hardcoded selectors on GPU workloads.

### Finding 3 — bee-jms-01 NVMe ~2x larger than peers, underused (P3, inventory)

**Observation**: bee-jms-01 has ~930 GiB ephemeral capacity vs ~464 GiB on
02/03. It hosts the fewest pods (27, all infra) and the least PVC traffic.
Wasted local storage.

**Expected payoff**: Could host larger openebs-hostpath PVCs (e.g., thanos
block cache if the VM stack ever needs it, or a Minio tier for hot objects).
Alternatively, re-image 02/03 with matching NVMe if drives are physically
available — delivers even ephemeral capacity for easier workload placement.

**Action**: Physically audit the three Beelinks' NVMe models + health
(`nvme-cli` extension is already installed; accessible via `talosctl
--nodes <ip> get nvmenamespaces`). Document drive model/TBW headroom.

### Finding 4 — Missing CPU/memory requests on 30+ infra pods (P2, correctness)

**Observation**: 30+ infra pods across cert-manager, cilium, hubble,
openebs, spegel, reflector, reloader, k8tz lack CPU or memory `requests`.
Kubernetes falls back to BestEffort QoS — these pods are first to be
OOMKilled under pressure. Most are critical path (Cilium, CoreDNS upstream
via hubble, cert-manager).

**Expected payoff**: Predictable scheduling, graceful degradation under
load, accurate `kubectl top`-style capacity planning. Likely no perf change
at current 3-37% utilization but material insurance against pressure events.

**Action**: Walk the list, add `resources.requests` (not necessarily limits
— limits on infra DaemonSets can trigger throttling far worse than overrun).
Where charts don't expose requests, pin versions and submit upstream fixes
or maintain local overlays.

### Finding 5 — Single-replica control plane is 3/3; reboot of any node drops quorum to 2/3 (P3, resilience)

**Observation**: All three nodes are `controlPlane: true` in talconfig. Any
maintenance reboot (e.g., UMA bump) takes etcd from 3 → 2. Quorum survives,
but a second failure during the maintenance window is cluster-down.

**Expected payoff**: No perf change. Operational confidence during upgrades
and the planned UMA bump.

**Action**: Document "never reboot two control-plane nodes simultaneously"
as a preflight check in the `talos:upgrade-node` task. Consider whether a
4th node (even a cheap NUC) to separate "etcd member" from "workload node"
is worth the ~$400 capex — though it contradicts the broader
consolidation stance.

### Finding 6 — Jumbo frames (MTU 9000) set cluster-wide; no evidence of validation (P3, verify-don't-fix)

**Observation**: `talos/talconfig.yaml` sets `mtu: 9000` on every node
interface. If any switch port or upstream router falls back to 1500,
fragmentation + retransmits silently degrade Pod-to-Pod traffic. Cilium's
VXLAN overlay adds 50 bytes — effective payload is 8950, fine, but any
underlay mismatch is a foot-gun.

**Expected payoff**: Confirm no silent MTU issues. Potentially recover
2-5% on inter-node bandwidth if misconfigured.

**Action**:

```bash
# From inside any pod on bee-jms-01 to bee-jms-02 (adjust IPs):
ping -M do -s 8972 192.168.35.6  # 8972 = 9000 - 20 (IP) - 8 (ICMP)
```

If it fragments, MTU is oversized somewhere. Also validate switch-side:
UniFi port profile must have jumbos enabled on all three node ports.

### Finding 7 — vmsingle retention on 100 GiB openebs-hostpath; no bandwidth metric (P3, observability)

**Observation**: `vmsingle-vmsingle` PVC is 100 GiB on local NVMe. Per the
`monitoring-stack-migration-home-ops-v17-complete-closed` memory, retention
is 30 days. No disk-I/O-per-second alert or dashboard tile shows the metric
backing that budget. If a scrape spike fills the disk, pods go CrashLoop.

**Expected payoff**: Early warning on retention overrun, visibility into
scrape-interval-vs-disk tradeoffs. Zero runtime cost; pure dashboard work.

**Action**: Add a Grafana dashboard tile: vmsingle `vm_data_size_bytes` vs
PV capacity, plus `rate(vm_rows_inserted_total[5m])` for scrape-rate
trending. Alert at 85% PV fill.

### Finding 8 — Two storage classes, no documented selection criteria (P4, docs)

**Observation**: `openebs-hostpath` (default, local NVMe) and `nfs-client`
(NFS external provisioner, network storage). Both are used across the
cluster with no documented rule for which to pick. Recent `llama-swap` PVC
chose openebs-hostpath; crowdsec chose nfs-client. Neither choice is
obviously wrong, but the pattern is ad-hoc.

**Expected payoff**: Consistency. New app authors don't have to guess.

**Action**: Document in CLAUDE.md: "openebs-hostpath for latency-sensitive
workloads (DBs, model weights, log shards); nfs-client for shared or
mobile-across-nodes data." Add a brief rationale table.

### Finding 9 — Power draw per node is unmeasured (P3, observability)

**Observation**: No smart plug or UPS telemetry integration ingesting
per-node watts. Homelab-wide power cost is invisible. Prior session
research noted the Cezanne iGPU path costs ~$30/yr in electricity, but
that was an estimate; there's no ground truth.

**Expected payoff**: Honest TCO for the hardware-buy decision blocked by
home-ops-vo2. Also quantifies whether consolidation (e.g., two nodes
instead of three) is worth the resilience cost.

**Action**: If there's an existing UPS with SNMP/NUT exposure, wire its
metrics into VictoriaMetrics. Otherwise, the cheapest win is a single
TP-Link/Shelly smart plug on the cluster's PDU feeding node-wide power
into Home Assistant → Prometheus exporter → vmsingle. Dashboard: watts
per node, rolling 24h average, $/kWh × hours as a tile.

### Finding 10 — No SLO dashboard; alerting is threshold-only (P3, observability)

**Observation**: Alertmanager → Discord is wired for `severity=critical`
only. No SLO burn-rate alerts, no latency histograms, no
error-budget-remaining tiles. Typical for homelab but limits trend
awareness — problems are detected at threshold-cross, not ramp.

**Expected payoff**: Earlier detection, less toil on reactive dashboards.

**Action**: Pick 3 user-facing services (e.g., Traefik ingress success
ratio, Grafana API latency, Dolt MySQL query latency). Define SLOs.
Add burn-rate alerts (2% in 1h, 5% in 6h). Skip the rest until value is
proven.

## Non-findings (investigated, no action)

- **Cilium BPF tuning**: current config is upstream defaults, pods aren't
  saturating. No benchmark evidence of bottleneck. Revisit only if packet
  drops appear in hubble metrics.
- **kube-proxy replacement**: already using Cilium's kube-proxy-free mode
  per talhelper defaults. No action.
- **CoreDNS tuning**: latency metrics look healthy; no retries visible in
  NodeLocal DNS. Skip.
- **OpenEBS alternatives**: Rook-Ceph or Longhorn would give replication
  but at 3-4x storage overhead on a 3-node cluster where S3 already
  provides durability. Anti-pattern per `home-ops` design principle
  "S3 provides data durability."

## Recommended prioritization

If the user wants to file beads, recommend tackling in this order:

1. **Finding 1** (stale PVC) — trivial, 5-min cleanup.
2. **Finding 4** (missing resource requests) — biggest insurance payoff.
3. **Finding 6** (jumbo frame validation) — one command, huge diagnostic value.
4. **Finding 7** + **Finding 9** (observability — vmsingle + power) —
   grouping the two dashboard tasks into one sprint amortizes Grafana work.
5. **Finding 2** (pod rebalancing) — pairs naturally with Finding 4 once
   requests are in place.
6. **Finding 3, 5, 8, 10** — opportunistic.

## Defer / reject

- Additional monitoring namespaces, service meshes, sidecar fleets: no.
  Current stack is lean and adequate. Adding surface area without proving
  a bottleneck is anti-pattern.
- Node replacement / capacity expansion: the UMA bump track (home-ops-vo2)
  will answer "is the current cluster enough for LLM workloads?" — that
  answer drives hardware decisions, not a research bead.

## References

- Memory `monitoring-stack-migration-home-ops-v17-complete-closed` (vmsingle
  retention = 30d on 100 GiB)
- `talos/schematic.yaml` — already has `amdgpu.gttsize=16384`, `amd_pstate=guided`,
  `cpufreq.default_governor=performance`
- `talos/talconfig.yaml` — MTU 9000, three-node control plane, VIP 192.168.35.2
- `kubectl get nodes -o json` (2026-05-03) — capacity + utilization data above
