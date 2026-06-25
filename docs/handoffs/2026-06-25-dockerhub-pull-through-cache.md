# Handoff — Dockerhub Pull-Through Cache

**Date:** 2026-06-25
**Status:** Design done, NOT implemented. Pick up here.
**Design doc:** `docs/research/2026-06-25-dockerhub-pull-through-cache.md` (READ THIS FIRST — full analysis, options, rejected alternatives, open decisions).

---

## TL;DR of the decision

- `DockerhubRateLimitRisk` alert (warning, value 110) → build a pull-through registry cache.
- **Talos `machine.registries.mirrors` = the redirect (native, sufficient). Talos does NOT run the cache** — need an in-cluster `distribution`/registry:2 Flux app in pull-through mode. NOT the doc's external-Docker-host recipe.
- Mirror ghcr.io + quay.io + registry.k8s.io too, not just docker.io.
- Risk is LOW steady-state; this is cold-start hardening. Not urgent.

## How to pick this up in a fresh session

1. **Prime context:**
   - `cat docs/research/2026-06-25-dockerhub-pull-through-cache.md`
   - Recall memory `project-dockerhub-pull-through-cache` (and `project-tuppr-schematic-discipline` for Talos-apply discipline).
2. **Resolve the §4 open decisions FIRST** (they change the design materially):
   - registry:2 vs distribution v3 + pull-through `proxy:` syntax for chosen version
   - storage class + size (lean openebs-hostpath ~50–100Gi)
   - one cache deployment per upstream vs a routing layer (`distribution` proxy = ONE upstream/instance)
   - **VIP vs hostPort** — the riskiest unknown: the mirror endpoint must resolve at the containerd layer, possibly before Cilium is up. A Cilium VIP may not work; may need a plain node IP / hostPort. VERIFY THIS before building.
   - private-registry auth (ghcr creds in proxy config); consider authenticated docker.io creds (200/6h free) as a cheap independent partial mitigation.
3. **Build order (suggested):**
   - a. Scaffold the cache as a Flux app: `kubernetes/apps/<ns>/registry-cache/` (use `/new-app` skill; OCIRepository+chartRef or app-template). Decide namespace (`kube-system`? `network`?).
   - b. Get it serving + reachable at a stable address; test a manual pull through it (`crane`/`docker pull` against the mirror endpoint).
   - c. ONLY THEN add `talos/patches/global/machine-registries.yaml` + wire into `talconfig.yaml` `patches:`.
   - d. `task talos:generate-config`, then `task talos:apply-node IP=<node>` **one node at a time** with etcd-quorum-precheck (per CLAUDE.md). This is a machine-config change, NOT a Flux reconcile.
   - e. Verify on each node: pull a docker.io image, confirm it egresses through the cache (cache logs show the upstream fetch; second node's pull is a cache HIT).
4. **Validate the win:** after rollout, watch `DockerhubRateLimitRisk` + do a controlled mass-restart test of a docker.io-heavy daemonset (e.g. crowdsec ×11) and confirm no `ImagePullBackOff` storm.

## Gotchas already known

- Spegel stays — it's complementary (P2P intra-cluster), not replaced by this.
- RustFS/S3 is NOT a candidate cache backend (S3 ≠ OCI registry protocol).
- Talos `machine.registries.mirrors` falls back to upstream on cache miss → graceful, so a half-working cache won't hard-break pulls.
- `:latest` tags (alpine, homebridge) blunt cache benefit on digest change — acceptable.

## Done-elsewhere context this session (not part of this work)

- omega-mcp license CrashLoopBackOff fixed (MAC-fingerprint root cause). See memory `project-omega-mcp-license-fingerprint`. Unrelated to the cache except both surfaced from the same vmalert review.
- The other 4 firing alerts that session: 3 were omega-mcp (now cleared), 1 Watchdog (intentional). Only `DockerhubRateLimitRisk` + `Watchdog` remain firing.
