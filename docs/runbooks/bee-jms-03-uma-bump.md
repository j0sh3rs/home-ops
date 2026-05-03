# bee-jms-03 BIOS UMA Frame Buffer Bump Runbook

Expands the Cezanne Vega 8 iGPU's BIOS-reserved UMA VRAM from the current 3 GiB
to the maximum the board firmware allows (typically 8 or 16 GiB). Target node
is the only one with `amd.com/gpu.vram=3G` and the `memory-tier=high` label;
it hosts the `llama-swap` workload and future local-inference pods.

## Why this runbook exists

Current state (verified `2026-05-03` via `kubectl get node bee-jms-03 -o jsonpath='{.metadata.labels}'`):

- `amd.com/gpu.vram: 3G` — BIOS-reserved UMA, immutable at runtime
- `amdgpu.gttsize=16384` already in `talos/schematic.yaml` → 16 GiB pageable
  GTT spill. This lets larger models load but does not raise VRAM bandwidth;
  it simply prevents OOM when weights exceed the 3 GiB UMA window.
- GPU arch: Vega 8 / gfx90c (device 0x1638, 8 CUs, 32 SIMDs)
- Bandwidth source: DDR4 memory controller shared with CPU

Raising UMA moves more model weight into the "primary" VRAM region that
ROCm/Vulkan compute kernels prefer, reducing GTT-mapping overhead on every
forward pass. The effect on tokens/sec depends on working-set fit; large
models that already spilled to GTT should see the biggest gain.

**This runbook produces no tokens/sec improvement on its own — that work is
validated in `home-ops-vo2`. The runbook only prepares and executes the
BIOS change safely.**

## Prerequisites

### Hardware facts to confirm before scheduling

| Item | How to verify | Expected |
|------|---------------|----------|
| Mini-PC vendor/model | Physical label or `dmidecode -s system-product-name` from a live-USB session | Beelink SER-series (MAC OUI `b0:41:6f` is Beelink Computer) |
| CPU | Node label `cpu-tier=zen3`; family/model `25/80` | Ryzen 5825U / 5800H / 5700U (Cezanne, gfx90c iGPU) |
| Installed DRAM | `free -h` via `kubectl debug node/bee-jms-03 --image=busybox` or BIOS POST screen | ≥ 32 GiB (node is the `memory-tier=high` box) |
| BIOS vendor/version | BIOS POST splash, or `dmidecode -s bios-version` from live-USB | AMI or Insyde, version string noted for rollback reference |
| Current UMA value | POST splash "Share Memory" / "UMA Frame Buffer Size"; or confirm `amd.com/gpu.vram=3G` node label | `3G` today |
| Max supported UMA | BIOS dropdown; commonly up to `½ of installed DRAM` on Cezanne | To be recorded during the maintenance window |
| Console access | Physical KB+monitor required (Beelink has no IPMI/BMC) | Confirm physical access or remote-hands plan |

### Cluster pre-checks

Run from workstation before maintenance window:

```bash
# Confirm bee-jms-03 is NOT the current API server VIP holder; reboots it drops
# the Talos control-plane from 3 to 2 nodes temporarily.
kubectl get nodes -o wide --context home

# Verify llama-swap + any other pods pinned to bee-jms-03
kubectl get pods -A \
    -o jsonpath='{range .items[?(@.spec.nodeName=="bee-jms-03")]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' \
    --context home

# Snapshot current Flux state so we can compare post-reboot reconcile
flux get ks -A --context home > /tmp/flux-ks-pre-uma-bump.txt
flux get hr -A --context home > /tmp/flux-hr-pre-uma-bump.txt

# Confirm etcd quorum health (control-plane reboot is safe with 2/3 up)
talosctl --nodes 192.168.35.10 etcd status
```

Abort if:
- Any HelmRelease is `Reconciling` or `Stalled` on `bee-jms-03` — wait for
  steady state.
- `etcd status` reports the node behind on raft index — let it catch up first.

## Maintenance window procedure

### 1. Cordon and drain

```bash
kubectl cordon bee-jms-03 --context home
kubectl drain bee-jms-03 \
    --ignore-daemonsets \
    --delete-emptydir-data \
    --force \
    --timeout=10m \
    --context home
```

`llama-swap` is a Deployment pinned via `nodeSelector` to `bee-jms-03`, so
drain evicts it — it will stay `Pending` until uncordon. Acceptable; there is
no other GPU-capable node.

### 2. Power down

```bash
talosctl --nodes 192.168.35.10 shutdown
```

Wait for all LEDs off (~60 s). Do not pull power while Talos is still
flushing etcd state — the `shutdown` command waits for graceful etcd leave.

### 3. Enter BIOS

On Beelink SER boxes: tap `Delete` (or `F7` / `F2` on some revisions)
repeatedly on power-on until the BIOS splash appears.

Photograph the current settings before changing anything — specifically:

- `Advanced → AMD CBS → NBIO Common Options → GFX Configuration → UMA Frame Buffer Size`
  (path varies by BIOS vendor; alternative names: "iGPU Memory", "Share
  Memory Size", "UMA Buffer Size")
- Boot order (verify `/dev/nvme0n1` is first)
- Secure Boot state (current: disabled — confirm unchanged)
- Resizable BAR / Above 4G Decoding (leave as-is)

### 4. Change UMA

- Set `UMA Frame Buffer Size` to the largest option offered, capped at
  **½ of installed DRAM** (e.g., 16 GiB on a 32 GiB box, 32 GiB on a 64 GiB
  box). Leaving half for the OS avoids OOM on 32 GiB systems running full
  cluster workloads.
- Record the chosen value in the bead `home-ops-3yv` notes before saving.
- Save & Exit (usually `F10 → Y`).

### 5. POST verification

On first boot after the change:

- POST screen should report the new UMA value next to the installed DRAM
  total. If the box hangs on POST, follow **Rollback** below.
- Allow Talos to boot normally. No Talos config change is required for the
  UMA bump — the BIOS reports the new reservation via ACPI and the amdgpu
  driver picks it up.

### 6. Post-boot verification

From workstation after node rejoins the cluster:

```bash
# Watch node come Ready
kubectl get node bee-jms-03 -w --context home

# Confirm new VRAM label (amd-gpu-operator relabels within ~60s of kubelet ready)
kubectl get node bee-jms-03 \
    -o jsonpath='{.metadata.labels.amd\.com/gpu\.vram}{"\n"}' \
    --context home
# Expected: 8G, 16G, or whatever was selected — NOT 3G

# Dmesg check via talosctl
talosctl --nodes 192.168.35.10 dmesg | grep -iE 'amdgpu|vram|uma' | head -40

# Uncordon so llama-swap can reschedule
kubectl uncordon bee-jms-03 --context home

# Confirm llama-swap pod Running
kubectl -n services get pods -l app.kubernetes.io/name=llama-swap \
    -o wide --context home

# Smoke test: hit llama-swap endpoint with a small prompt (fill in correct
# service name after checking `kubectl -n services get svc`)
kubectl -n services port-forward svc/llama-swap 8080:8080 --context home &
curl -s http://localhost:8080/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{"model":"qwen3-1.7b","messages":[{"role":"user","content":"ping"}]}'
```

Exit criteria for this runbook:

1. Node label `amd.com/gpu.vram` reports the new UMA size.
2. `llama-swap` pod is `Running` and serves a test inference without error.
3. Flux state matches `/tmp/flux-*-pre-uma-bump.txt` (no regressions).
4. `talosctl etcd status` reports the node healthy and caught up.

Hand off to `home-ops-vo2` for performance delta measurement once all four
are met.

## Rollback

### If POST hangs or UMA value is rejected

Beelink BIOS has no "clear settings" jumper on most SER models. Recovery path:

1. Power off, unplug AC for 60 s.
2. Remove bottom cover, locate CMOS coin cell, remove for 30 s, reseat.
3. Power on — BIOS reverts to defaults. Re-enter BIOS and set UMA back to
   `3G` (or the previous documented value) before re-enabling boot.

### If Talos boots but amdgpu driver fails to init

Symptom: node Ready, but `amd.com/gpu.*` labels disappear and dmesg shows
amdgpu errors. Cause is almost always the new UMA value exceeding what the
driver's hard-coded limits accept for this arch.

1. Cordon + drain the node again.
2. Reboot into BIOS, lower UMA by one step, save, exit.
3. Observe labels after rejoin.
4. Capture the failing value + dmesg excerpt in the bead notes so we know
   the Cezanne ceiling for this board.

### If Flux reconcile stalls after uncordon

Most likely a stuck HelmRelease with a pod that can't reschedule. Check:

```bash
flux get hr -A --context home | grep -v True
kubectl -n <ns> describe helmrelease <name> --context home
```

Resume with `flux reconcile helmrelease <name> -n <ns> --context home` if
paused; otherwise inspect pod events.

## Notes

- **Kernel cmdline stays the same.** `amdgpu.gttsize=16384` continues to
  provide spill-over capacity beyond UMA. After the bump, fewer models will
  need to spill — that's the whole point.
- **This is a BIOS change, not a Talos config change.** No schematic rebuild,
  no `talosctl apply-config`, no installer regen needed.
- **Only bee-jms-03** is in scope. bee-jms-01 (zen2) and bee-jms-02 (zen3)
  are not GPU-designated and should be left at BIOS defaults.
