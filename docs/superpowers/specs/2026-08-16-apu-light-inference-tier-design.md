# APU-light inference tier (bee-jms-03) — design

## Context

llama-swap runs pinned to `bigboi-jms-01`'s discrete RX 9070 XT (16 GiB
dedicated VRAM). Its `chat` group is an exclusive-swap group holding 7
models on that single 16 GiB card, including `coder-fim` — a small
(~3.7 GiB) FIM-completion model hit on every Continue.dev keystroke once
that client is wired up. Because `coder-fim` shares the same exclusive-swap
slot as the large chat/reasoning models (`agentic-coder` alone already
consumes ~14.19 GiB alongside the ~2.6 GiB always-on group, leaving only
~0.3 GiB of headroom against the documented ~17.1 GiB usable ceiling), any
FIM completion would evict whatever large model was resident — the same
thrash pattern a prior fix (#465) already had to solve once for a
different model pair on this same GPU.

The fix isn't a same-GPU config change — there's no room. It's giving the
small, frequently-hit models (`coder-fim`, and the `qwen3-1.7b`
fast/small/router alias used for routing/voice/title-gen) a completely
separate GPU, so they stop competing with the big chat models for the
9070 XT's VRAM at all.

**Hardware finding that shapes this design:** all three `bee-*` nodes carry
a Renoir-family iGPU, but they are not equivalent. `dmesg` (not the
`amd.com/gpu.vram` node label, which reports something else and is
misleading here) shows:

| Node | Device-ID | Real dedicated VRAM | GTT | System RAM |
|---|---|---|---|---|
| bee-jms-01 | 1636 | 3 GiB (BIOS default) | 16 GiB | 28 GiB |
| bee-jms-02 | 1638 | 3 GiB (BIOS default) | 16 GiB | 28 GiB |
| bee-jms-03 | 1638 | **16 GiB** (BIOS-expanded UMA) | 16 GiB | 47 GiB |

`bee-jms-03` previously had its BIOS UMA framebuffer manually expanded to
16 GiB dedicated VRAM — by far the strongest bee-* node for GPU inference,
and the reason this tier is viable at all. `bee-jms-01`/`-02` stay
excluded from this design (3 GiB dedicated VRAM is too tight to be worth
targeting).

## Decisions already made (confirmed with user during brainstorming)

1. **Scope**: minimal fix — move only `coder-fim` and `qwen3-1.7b`
   (fast/small/router alias) off the 9070 XT to `bee-jms-03`. The rest of
   the `chat` exclusive-swap group and the `embed`/`rerank` always-on
   models stay on `bigboi-jms-01` unchanged.
2. **Topology**: one llama-swap instance, hard-pinned to `bee-jms-03` by
   hostname (not a floating `gpu-tier` label match across bee-02/03 —
   -02 isn't a real candidate given the VRAM gap above).
3. **No routing layer.** Checked every in-repo llama-swap consumer
   (openclaw, holmesgpt, openviking) — none currently reference
   `coder-fim` or the `router`/`fast`/`small` aliases; those are
   documented as future hooks for Continue.dev and Home Assistant Assist,
   neither wired yet. So this migration requires **zero consumer config
   changes** today. A gateway (LiteLLM or otherwise) would add the same
   inert overhead the prior LiteLLM removal (2026-08-14) was reasoned
   about — nothing here is dynamic enough to need one. Future consumers
   get pointed at whichever of the two static endpoints matches their
   model, same pattern as today.
4. **Talos**: no schematic change needed for `bee-jms-03` — the shared
   `talos/schematic.yaml` (`amdgpu.gttsize=16384`, APU shared-RAM-as-VRAM
   tuning) is already correct for this use case. Only a node-label
   addition, which is a machine-config field, not a kernel-arg/extension
   change — no reboot required.

## Implementation

### 1. Node label (`talos/talconfig.yaml`)

Add to `bee-jms-03`'s `nodeLabels`:
```yaml
node.kubernetes.io/gpu-tier: apu-light
```
Comment cross-referencing this design doc and explaining why `-01`/`-02`
are excluded (3 GiB dedicated VRAM too tight). Apply via
`task talos:generate-config` + `task talos:apply-node IP=192.168.35.10
MODE=auto` — label-only change, no `talos:upgrade-node` needed.

### 2. GPU exposure (`kubernetes/apps/kube-system/amd-gpu/app/deviceconfig.yaml`)

Add a second `DeviceConfig` CR to the existing file (same ROCm GPU
Operator install from the 9070 XT work, no new HelmRelease):
```yaml
---
apiVersion: amd.com/v1alpha1
kind: DeviceConfig
metadata:
  name: apu-light
  namespace: kube-system
spec:
  driver:
    enable: false   # same driverless rationale as dgpu — Talos's amdgpu extension owns the module
  selector:
    node.kubernetes.io/gpu-tier: apu-light   # bee-jms-03 only
  devicePlugin:
    enableDevicePlugin: true
    enableNodeLabeller: true
  metricsExporter:
    enable: true
```
Field names must match the live CRD schema (`devicePlugin.enableDevicePlugin`
/ `enableNodeLabeller`, not the docs' `devicePlugin.enable` /
`nodeLabeller.enable` — this was a real bug caught during the 9070 XT
rollout; verify with `kubectl explain deviceconfig.spec` before applying).

### 3. New app: `kubernetes/apps/ai/llama-swap-apu/`

Same `bjw-s` app-template + OCIRepository pattern as the existing
`kubernetes/apps/ai/llama-swap/` app (see that `helmrelease.yaml` as the
template):
- `strategy: Recreate`, `reloader.stakater.com/auto: "true"` — same as main
- Model-fetch init container (`curlimages/curl`), but pulling only the two
  GGUFs this instance needs (~3.5 GiB total): `Qwen2.5-Coder-3B-Q5_K_M.gguf`,
  `Qwen3-1.7B-Q5_K_M.gguf`
- Own RWO PVC on `openebs-hostpath` (node-local, same storage-class
  reasoning as the main instance — see CLAUDE.md storage-class table)
- `nodeAffinity` hard-pinned to `bee-jms-03` by hostname (`kubernetes.io/hostname: bee-jms-03`), not just the `gpu-tier` label, matching the "one instance, one named node" decision
- Own `ConfigMap` (`kubernetes/apps/ai/llama-swap-apu/app/configmap.yaml`):
  - `coder-fim` macro/model block moved verbatim from the main configmap
  - `qwen3-1.7b` macro/model block moved verbatim from the main configmap
  - Flash-attn: re-check before enabling. The main instance's flash-attn
    flags are tuned for RDNA4 (bigboi) and RDNA2 (prior GPU); this is an
    older Renoir Vega iGPU (`gmc_v9_0`/vega10 IP blocks per `dmesg`) —
    default to `--flash-attn` **off** unless verified working on this
    silicon, same caution the existing `reasoner-agentic` block already
    documents for a different arch mismatch
  - Groups: both models can be `always-on` (no swap needed — combined
    footprint ~3.5 GiB fits comfortably in 16 GiB dedicated VRAM with
    massive headroom, unlike the tight fit on bigboi)
- Service DNS: `llama-swap-apu.ai.svc.cluster.local:8080` (OpenAI-compatible,
  same as main instance)

### 4. Main `llama-swap` configmap (`kubernetes/apps/ai/llama-swap/app/configmap.yaml`)

Remove the `coder-fim` and `qwen3-1.7b` model blocks and their macros (keep
`llama-fim` macro only if still used elsewhere — check before deleting).
Remove `qwen3-1.7b` from the `always-on` group's `members` list. Remove
`coder-fim` from the `chat` group's `members` list.

### 5. Docs (`CLAUDE.md`)

- Document the two-tier topology under the `ai` namespace section:
  `bigboi-jms-01` (9070 XT, large/dense chat models) +
  `bee-jms-03` (Renoir iGPU w/ 16 GiB BIOS-expanded VRAM, FIM + routing/
  voice models).
- Update the existing "Planned (not yet deployed)" Continue.dev note:
  FIM traffic should target `llama-swap-apu.ai.svc.cluster.local:8080`,
  not the main instance.
- Add a short note on the `bee-*` VRAM asymmetry (this design's hardware
  table) so a future reader doesn't re-derive it from `dmesg` again.

## Verification

```bash
kustomize build kubernetes/apps/ai/llama-swap-apu/app | kubectl apply --dry-run=client -f -
kustomize build kubernetes/apps/ai/llama-swap/app | kubectl apply --dry-run=client -f -
kustomize build kubernetes/apps/kube-system/amd-gpu/app | kubectl apply --dry-run=client -f -
```
After Flux reconciles:
```bash
kubectl describe node bee-jms-03 | grep amd.com/gpu   # allocatable=1
kubectl -n ai get pods -l app.kubernetes.io/instance=llama-swap-apu -o wide
curl -s http://llama-swap-apu.ai.svc.cluster.local:8080/v1/models | jq
# functional check — FIM completion:
curl -s http://llama-swap-apu.ai.svc.cluster.local:8080/v1/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"coder-fim","prompt":"def add(a, b):\n    return"}'
```
Confirm the main `llama-swap` instance on bigboi still serves its
remaining `chat` group models without the removed models breaking any
alias lookup (`curl` the `/v1/models` list, diff against the configmap).

## Out of scope (explicitly, for this design)

- Moving `embed`/`rerank` off bigboi — user chose the minimal split
  (`coder-fim` + `qwen3-1.7b` only); embed/rerank stay put.
- Wiring Continue.dev or Home Assistant Assist to the new endpoint —
  neither is deployed/configured yet; this design only stands up the
  backend and documents the future target.
- A routing/gateway layer — explicitly rejected for this topology (see
  Decisions §3).
- `bee-jms-01`/`-02` GPU exposure — excluded on hardware grounds (3 GiB
  dedicated VRAM), not part of this design.
