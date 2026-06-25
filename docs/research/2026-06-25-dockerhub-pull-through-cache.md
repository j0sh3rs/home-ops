# Dockerhub Pull-Through Cache — Design & Talos Options

**Date:** 2026-06-25
**Status:** Analysis complete, NOT implemented. Decision pending operator review.
**Trigger:** `DockerhubRateLimitRisk` alert firing (value 110).
**Related:** `kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml:81` (alert rule), Spegel (P2P cache, already deployed).

---

## 1. The alert, calibrated

Rule (`DockerhubRateLimitRisk`):

```promql
count(time() - container_last_seen{image=~"(docker.io).*",container!=""} < 30) > 100
```

Fires at 110. **This counts running container *instances* pulling from docker.io, NOT pull events.** Anonymous Dockerhub limit is **100 pulls / 6h / IP**. The two numbers are not directly comparable — 110 running containers ≠ 110 pulls.

Tagged `warning` (soft capacity-planning signal), correctly. The rule's own comment notes Spegel P2P caching blunts the real risk and a mass restart at worst causes transient `ImagePullBackOff`, not an outage.

### Actual docker.io exposure (live, 2026-06-25)

~50 distinct docker.io images. High-replica daemonsets dominate the count:

| Image | Instances |
|-------|-----------|
| `crowdsecurity/crowdsec` | 11 |
| `victoriametrics/operator` (config-reloader) | 6 |
| `netdata/netdata` | 6 |
| `alpine:latest` | 4 |
| `victoriametrics/vmalert` | 2 |
| `curlimages/curl` | 2 |
| singletons: vmagent, victoria-metrics, victoria-logs, velero-plugin-for-aws, wyoming-whisper, wyoming-piper, python:3.14-slim, postgres:18-alpine, n8nio/n8n, mintplexlabs/anythingllm, langfuse, langfuse-worker, homebridge:latest, homeassistant, gotenberg, clickhouse-server, busybox, apache/tika | 1 each |

Only **6 explicit `docker.io/...` refs** exist in the repo manifests; the rest are implicit docker.io (bare image names / Helm chart defaults).

```
docker.io/rocm/k8s-device-plugin            (×4 refs)
docker.io/cloudflare/cloudflared            (×2)
docker.io/rocm/device-metrics-exporter      (×1)
docker.io/library/eclipse-mosquitto         (×1)
docker.io/library/busybox                   (×1)
docker.io/bitnamicharts/clickhouse          (×1)
```

### Real risk window

- **Steady state: LOW.** Images cached on-node; Spegel shares layers node-to-node (node B pulls from node A, not docker.io).
- **Cold cluster restart / mass reschedule: REAL.** Every node's *first* pull of each docker.io image egresses from the single NAT IP simultaneously. ~50 images can burn the 100/6h budget fast → transient `ImagePullBackOff`.
- **`:latest` tags** (`alpine`, `homebridge`) re-pull on digest change, partially bypassing cache benefit.

**Verdict:** a pull-through cache is justified — it converts the worst case (mass restart) into a non-event. Not urgent; it's hardening, not firefighting.

---

## 2. Talos native option — is it sufficient?

Reference: https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/images-container-runtime/pull-through-cache

Talos `machine.registries` does **two distinct things**, and the distinction is the whole analysis:

1. **`machine.registries.mirrors`** — redirects a registry (e.g. `docker.io`) to a mirror endpoint. This is **native, declarative, sufficient as the redirect mechanism.** Lives in `talconfig.yaml`.
2. The doc's example also spins up a **local `registry:2` container in pull-through mode** (`proxy.remoteurl`) on a static Docker host, then points the mirror at it.

**Key finding: Talos does NOT run the cache itself.** The `mirrors` block only *redirects*. Something still has to *be* the cache. The doc's literal recipe (`docker run registry:2` on a host) does not fit this cluster:

| Approach | Cache backend | Fit |
|----------|---------------|-----|
| Doc's literal: `registry:2` on a static Docker host | external Docker host | ❌ No Docker host exists. Talos nodes are immutable — can't `docker run`. Adds an out-of-cluster pet. |
| **`distribution`/`registry:2` as in-cluster Deployment** + Talos mirror → its Service/VIP | in-cluster pod, openebs/nfs PVC | ✅ Best fit. Mirror config is native Talos; cache is just another Flux app. |
| Talos mirror → existing **RustFS** (`s3.68cc.io`) | — | ❌ RustFS is S3 object store, not an OCI registry/proxy. Wrong protocol. |
| **Spegel only** (already deployed) | P2P node-to-node | ⚠️ Mitigates intra-cluster reschedule. Does NOT cache upstream — first pull still hits docker.io. Complementary, not a substitute. |

### The cold-start chicken-and-egg caveat (the real gotcha)

If the pull-through cache runs **as a pod in this cluster**, then during a full cold start the cache itself isn't up yet when other pods need images — exactly the mass-restart scenario we're hardening against. Talos `mirrors` falls back to the upstream on cache miss, so it **degrades gracefully** (miss → direct docker.io pull), but it means an in-cluster cache does **not** fully protect the cold-start case. The doc's external-host design avoids this — that is the one architectural argument *for* a separate box.

Mitigants that make in-cluster acceptable anyway:
- Talos mirror miss → falls back to upstream (no hard failure).
- Spegel already covers most intra-cluster reschedules (the common case).
- A true full-cluster-cold-start is rare (power loss / full Talos upgrade), and even then only the cache's own images + first-wave images race; staggered pod starts spread the rest.

---

## 3. Recommendation

1. **Use native Talos `machine.registries.mirrors` for the redirect.** Add a patch (`talos/patches/global/machine-registries.yaml`), wire into `talconfig.yaml` `patches:`. This is the native half and it IS sufficient as the *mechanism*. (No `machine.registries` block exists today — confirmed; the only `registries:` in rendered config is `cluster.discovery.registries`, unrelated.)
2. **Run the cache in-cluster** as a Flux app (`distribution`/`registry:2` in pull-through mode, openebs-hostpath PVC), exposed via a stable LAN VIP (cilium L2/LB IP, like traefik VIPs). Accept the cold-start caveat — graceful fallback + Spegel cover it.
3. **Mirror the registries worth caching**, not just docker.io. Most images are `ghcr.io`; also `quay.io`, `registry.k8s.io`. Same mechanism, far bigger payoff than docker.io alone.
4. **Do NOT** chase the doc's external-Docker-host pattern — no Docker host, violates immutable-infra.
5. Treat **Spegel as complementary** (P2P intra-cluster), not the answer to upstream rate limits.

**Net:** native Talos is the correct + sufficient *redirect* layer; you still need a cache *workload*, best run in-cluster as Flux-managed.

---

## 4. Open design decisions (resolve before implementing)

- **Cache image:** CNCF `distribution/distribution` (registry:3) vs `registry:2`. registry:3 (distribution v3) is current; confirm pull-through (`proxy:`) config syntax for the chosen version.
- **Storage:** openebs-hostpath (node-local, fast, node-pinned) vs nfs-client (survives reschedule). Cache is regenerable → openebs-hostpath fine, but node-pinning means cache is cold after the pod moves. Lean openebs-hostpath; size ~50–100Gi.
- **Auth to private registries:** ghcr.io pulls for private images need creds in the cache's `proxy` config. docker.io anonymous is the rate-limited path; consider also adding **authenticated** docker.io creds (Docker Hub free authenticated = 200/6h, paid higher) as a cheaper partial mitigation independent of the cache.
- **VIP / exposure:** cilium L2 announcement IP on the LAN (`192.168.35.x`), reachable by every node's containerd before cluster networking is fully up? Verify ordering — the mirror endpoint must resolve at containerd layer, which may predate Cilium. **This is the riskiest unknown** (see caveat §2). May need the cache reachable via a plain node IP / hostPort, not a Cilium VIP.
- **Per-registry mirror entries:** one mirror endpoint multiplexing all upstreams, vs one cache deployment per upstream. `distribution` proxy mode caches ONE upstream per instance — so multiple upstreams = multiple deployments OR a routing layer. This materially affects the design.
- **Talos apply discipline:** `machine.registries` change → `talos:apply-node` per node, one at a time, etcd-quorum-precheck (per CLAUDE.md). Registry mirror config is a machine config change, not a Flux change — needs the Talos rollout path.

---

## 5. Decisions explicitly rejected (do not relitigate without new evidence)

- **External Docker host running `registry:2`** — no Docker host; immutable-infra violation. (The doc's literal recipe.)
- **RustFS/S3 as the cache** — wrong protocol; S3 ≠ OCI registry.
- **Spegel as a substitute** — P2P only, never touches upstream; keep it as complement.
- **Doing nothing** — defensible short-term (steady-state risk low, alert is warning), but leaves cold-start exposed; cache is cheap hardening.

---

## 6. State at time of writing

- No `machine.registries` config in `talos/` (verified).
- Spegel deployed (`kube-system`).
- Alert `DockerhubRateLimitRisk` firing, `warning`, value 110.
- Nothing implemented for this cache. Greenfield.
