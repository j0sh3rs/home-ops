# APU-light Inference Tier (bee-jms-03) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore `llama-swap` as the running inference engine on
`bigboi-jms-01` (archiving the `ollama` comparison spike that currently
holds that node's GPU instead), then stand up a second llama-swap
instance pinned to `bee-jms-03`'s Renoir iGPU (16 GiB BIOS-expanded VRAM)
to host `coder-fim` and `qwen3-1.7b` (router/fast/small), removing them
from the 9070 XT's tight `chat` exclusive-swap group so FIM completions
stop evicting large chat models.

**Architecture:** Two independent, unrelated llama-swap `HelmRelease`s in
the `ai` namespace, each hard-pinned to one node by hostname, each with
its own ConfigMap/PVC/init-container, no shared state, no routing layer
between them. GPU exposure to `bee-jms-03` goes through the same ROCm GPU
Operator installed for the 9070 XT (`kubernetes/apps/kube-system/amd-gpu`),
via a second `DeviceConfig` CR — no new operator install.

**Tech Stack:** Talos Linux (per-node labels), Flux/Kustomize/Helm
(`bjw-s` app-template v4.6.2, OCIRepository + chartRef), ROCm GPU Operator
(`gpu-operator-charts` v1.5.1, driverless `DeviceConfig` mode),
`ghcr.io/mostlygeek/llama-swap` (Vulkan build), Tetragon (TracingPolicy).

**Spec:** `docs/superpowers/specs/2026-08-16-apu-light-inference-tier-design.md`

## Global Constraints

- No routing/gateway layer (LiteLLM or otherwise) — direct per-consumer
  wiring only, per spec Decision §3.
- No consumer config changes in this plan — no in-repo consumer
  references `coder-fim` or `router`/`fast`/`small` today (verified during
  brainstorming: openclaw, holmesgpt, openviking all reference other
  aliases only).
- `bee-jms-01`/`-02` are out of scope entirely — 3 GiB dedicated VRAM,
  excluded on hardware grounds.
- `embed`/`rerank` stay on `bigboi-jms-01` — not part of this migration.
- `DeviceConfig` field names MUST match the live CRD
  (`devicePlugin.enableDevicePlugin` / `enableNodeLabeller`, NOT
  `devicePlugin.enable` / a top-level `nodeLabeller.enable` — this exact
  mistake broke the first `DeviceConfig` rollout for the 9070 XT; verify
  with `kubectl explain deviceconfig.spec` before applying, don't trust
  upstream docs).
- Every new/modified `kubernetes/apps/**/*.yaml` file must pass
  `kustomize build <app-dir> | kubectl apply --dry-run=client -f -`
  before being considered done.

---

### Task 1: Archive `ollama`, restore `llama-swap` on `bigboi-jms-01`

**Context:** `ollama` (`kubernetes/apps/ai/ollama/`) was deployed
2026-08-16 as a comparison spike against `llama-swap`, sharing
`bigboi-jms-01`'s single `amd.com/gpu: 1` allocatable — the two cannot
run concurrently on that node (see the existing warning comment in
`kubernetes/apps/ai/kustomization.yaml`). `llama-swap`'s `HelmRelease` is
currently suspended live (`kubectl -n ai get helmrelease llama-swap -o
jsonpath='{.spec.suspend}'` → `true`; not set in git, an imperative `flux
suspend` done for the spike) while `ollama` runs instead. User has
concluded the spike: archive `ollama`, restore `llama-swap` as the
running engine on this node. This must land before Task 6 (which
verifies the main `llama-swap` instance live) and doesn't depend on
anything else in this plan — do it first.

**Files:**
- Move: `kubernetes/apps/ai/ollama/` → `archive/ollama/ollama/`
  (matches the existing archive pattern — see `archive/goose/goose/`,
  `archive/cognee/`)
- Modify: `kubernetes/apps/ai/kustomization.yaml` (remove the `ollama`
  resource entry and the now-stale explanatory comment block)
- Modify: `CLAUDE.md`

**Interfaces:**
- Produces: `bigboi-jms-01`'s `amd.com/gpu: 1` allocatable freed for
  `llama-swap`; no interface other tasks in this plan consume (they only
  need `llama-swap` un-suspended and serving, which this task delivers).

- [ ] **Step 1: Move the ollama app into archive**

```bash
mkdir -p archive/ollama
git mv kubernetes/apps/ai/ollama archive/ollama/ollama
```

- [ ] **Step 2: Remove ollama from the `ai` namespace kustomization**

In `kubernetes/apps/ai/kustomization.yaml`, remove this comment block
(it documents the now-archived spike and the suspend/resume dance this
task makes permanent):
```yaml
# ollama (2026-08-16): comparison spike, NOT a replacement for llama-swap.
# Shares the same single-GPU node (bigboi-jms-01, amd.com/gpu: 1
# allocatable) -- the two cannot run concurrently. Suspend llama-swap's
# HelmRelease before scaling ollama up. See ollama/app/helmrelease.yaml.
#
```
and remove the `./ollama/ks.yaml` line from `resources:`:
```yaml
resources:
  - ./faster-whisper/ks.yaml
  - ./holmesgpt/ks.yaml
  - ./llama-swap/ks.yaml
  - ./ollama/ks.yaml
  - ./openclaw/ks.yaml
  - ./openviking/ks.yaml
  - ./piper/ks.yaml
  # - ./mcpjungle/ks.yaml
  # - ./omega-mcp/ks.yaml
```
becomes:
```yaml
resources:
  - ./faster-whisper/ks.yaml
  - ./holmesgpt/ks.yaml
  - ./llama-swap/ks.yaml
  - ./openclaw/ks.yaml
  - ./openviking/ks.yaml
  - ./piper/ks.yaml
  # - ./mcpjungle/ks.yaml
  # - ./omega-mcp/ks.yaml
```
(This plan's Task 4 will add `./llama-swap-apu/ks.yaml` back into this
same list, alphabetically between `llama-swap` and `openclaw` — expect to
touch this file again there.)

- [ ] **Step 3: Validate the build**

```bash
kustomize build kubernetes/apps/ai | kubectl apply --dry-run=client -f - 2>&1 | grep -v "^namespace/ai"
```
Expected: no `ollama` resources in the output, no errors.

- [ ] **Step 4: Commit and push**

```bash
git add archive/ollama kubernetes/apps/ai/ollama kubernetes/apps/ai/kustomization.yaml
git commit -m "chore(ai): archive ollama comparison spike"
git push
```
(`git add kubernetes/apps/ai/ollama` stages the deletion half of the
`git mv`; both halves are needed in the same commit for git to record it
as a rename rather than an unexplained delete + untracked add.)

- [ ] **Step 5: Reconcile and confirm ollama is gone**

```bash
flux reconcile kustomization ai -n ai --with-source
kubectl -n ai get pods -l app.kubernetes.io/name=ollama
```
Expected: `No resources found` (prune removes the Deployment/PVC/etc.
once the Kustomization no longer references the `ollama` `ks.yaml`).
Note: `retain: true` on ollama's PVC (if it has one — check
`archive/ollama/ollama/app/helmrelease.yaml`'s `persistence` block) means
the underlying PV/data survives even though the PVC object is pruned;
that's an accepted, harmless leftover, same as the stale GGUF files noted
in Task 6.

- [ ] **Step 6: Un-suspend and verify llama-swap**

```bash
flux resume helmrelease llama-swap -n ai
flux get hr -n ai llama-swap
```
Expected: `SUSPENDED` column now `False`, `READY` `True`. Then:
```bash
kubectl -n ai get pods -l app.kubernetes.io/name=llama-swap -o wide
curl -s http://llama-swap.ai.svc.cluster.local:8080/v1/models | jq
```
Expected: pod `Running 1/1` on `bigboi-jms-01`, `/v1/models` returns the
full existing catalog (this is before Task 6 trims it — `coder-fim` and
`router`/`fast`/`small` should still be present here, confirming
`llama-swap` itself is healthy before this plan changes its model list).

- [ ] **Step 7: Update CLAUDE.md**

Find the existing sentence in the `ai` namespace section documenting the
2026-07-01 removals:
```
LangFuse (observability), AnythingLLM (RAG), Open WebUI (chat UI), and Goose (code automation agent) were removed 2026-07-01 — unused, no consumers beyond a chat UI nobody used; see `docs/runbooks/anythingllm-role-and-overlap.md` and `archive/{langfuse,anythingllm,open-webui,goose}/` if reuse is considered later. claude-code (headless code-automation engine, daemon + runner Job template) was also removed 2026-07-01.
```
Add a new sentence immediately after it:
```
**ollama was archived 2026-08-16** — deployed as a same-node comparison spike against llama-swap (both need bigboi-jms-01's single GPU, so they ran mutually exclusive via manual HelmRelease suspend/resume); spike concluded, llama-swap remains the sole chat/completion engine. See `archive/ollama/`.
```

- [ ] **Step 8: Commit and push**

```bash
git add CLAUDE.md
git commit -m "docs: note ollama spike archival"
git push
```

---

### Task 2: Label `bee-jms-03` for the APU-light tier

**Files:**
- Modify: `talos/talconfig.yaml` (bee-jms-03 node block, `nodeLabels`)

**Interfaces:**
- Produces: node label `node.kubernetes.io/gpu-tier: apu-light` on
  `bee-jms-03`, consumed by Task 3's `DeviceConfig` selector.

- [ ] **Step 1: Add the node label**

In `talos/talconfig.yaml`, find the `bee-jms-03` node block (`hostname:
"bee-jms-03"`, `ipAddress: "192.168.35.10"`). Its current `nodeLabels`
block is:
```yaml
    nodeLabels:
      node.kubernetes.io/cpu-tier: zen3
      node.kubernetes.io/memory-tier: high
```
Change it to:
```yaml
    nodeLabels:
      node.kubernetes.io/cpu-tier: zen3
      node.kubernetes.io/memory-tier: high
      # This node's BIOS UMA framebuffer was manually expanded to 16 GiB
      # dedicated VRAM (vs 3 GiB stock on bee-jms-01/-02) — see
      # docs/superpowers/specs/2026-08-16-apu-light-inference-tier-design.md
      # for the dmesg-verified hardware table. Only bee-jms-03 gets this
      # label; -01/-02 are excluded (too little dedicated VRAM to target).
      node.kubernetes.io/gpu-tier: apu-light
```

- [ ] **Step 2: Regenerate and apply**

```bash
task talos:generate-config
task talos:apply-node IP=192.168.35.10 MODE=auto
```
This is a label-only machine-config change — no kernel-arg/extension
change, no `talos:upgrade-node`, no reboot. `bee-jms-03` is control-plane
(`controlPlane: true`), so the `apply-node` task's `etcd-quorum-precheck`
dependency runs automatically; let it — it will pass since this change
doesn't reboot anything, but the precheck still gates the apply.

- [ ] **Step 3: Verify the label landed**

```bash
kubectl get node bee-jms-03 --show-labels | grep -o 'node.kubernetes.io/gpu-tier=[a-z-]*'
```
Expected output: `node.kubernetes.io/gpu-tier=apu-light`

- [ ] **Step 4: Commit**

```bash
git add talos/talconfig.yaml
git commit -m "feat(talos): label bee-jms-03 as apu-light GPU tier"
git push
```

---

### Task 3: Expose `bee-jms-03`'s GPU via a second `DeviceConfig`

**Files:**
- Modify: `kubernetes/apps/kube-system/amd-gpu/app/deviceconfig.yaml`

**Interfaces:**
- Consumes: node label from Task 2 (`node.kubernetes.io/gpu-tier: apu-light`)
- Produces: `amd.com/gpu: 1` allocatable on `bee-jms-03`, consumed by
  Task 5's pod resource request.

- [ ] **Step 1: Verify the live CRD schema before writing anything**

```bash
kubectl explain deviceconfig.spec.devicePlugin
```
Confirm the field names are `enableDevicePlugin` and `enableNodeLabeller`
(not `enable`), matching what the existing `dgpu` `DeviceConfig` in this
same file already uses. If the schema differs from this plan's Step 2
below, use the live schema, not this document.

- [ ] **Step 2: Add the second `DeviceConfig`**

The file currently contains one `DeviceConfig` (`dgpu`, no leading `---`
since it's the first/only document). Append a new YAML document:
```yaml
---
apiVersion: amd.com/v1alpha1
kind: DeviceConfig
metadata:
  name: apu-light
  namespace: kube-system
spec:
  driver:
    # Same driverless rationale as dgpu — Talos's siderolabs/amdgpu
    # extension already owns the kernel module on every bee-* node.
    enable: false
  selector:
    # bee-jms-03 only (16 GiB BIOS-expanded dedicated VRAM). Never widen
    # this to match bee-jms-01/-02 — see the apu-light design doc for why
    # (3 GiB stock VRAM is too tight to be worth targeting).
    node.kubernetes.io/gpu-tier: apu-light
  devicePlugin:
    enableDevicePlugin: true
    enableNodeLabeller: true
  metricsExporter:
    enable: true
```

- [ ] **Step 3: Validate the build**

```bash
kustomize build kubernetes/apps/kube-system/amd-gpu/app | kubectl apply --dry-run=server -f -
```
Expected: both `DeviceConfig` objects (`dgpu`, `apu-light`) and the
`HelmRelease` report `configured`/`unchanged` with no errors.

- [ ] **Step 4: Commit and push**

```bash
git add kubernetes/apps/kube-system/amd-gpu/app/deviceconfig.yaml
git commit -m "feat(ai): expose bee-jms-03 GPU via apu-light DeviceConfig"
git push
```

- [ ] **Step 5: Reconcile and verify live**

```bash
flux reconcile kustomization amd-gpu -n kube-system --with-source
kubectl -n kube-system get deviceconfig
kubectl describe node bee-jms-03 | grep amd.com/gpu
```
Expected: `deviceconfig` list shows both `dgpu` and `apu-light`;
`bee-jms-03`'s `Allocatable` section shows `amd.com/gpu: 1`. Also confirm
the device-plugin/labeller pods for this `DeviceConfig` are running only
on `bee-jms-03`:
```bash
kubectl -n kube-system get pods -o wide | grep apu-light
```

---

### Task 4: Scaffold the `llama-swap-apu` app (Flux plumbing + ConfigMap)

**Files:**
- Create: `kubernetes/apps/ai/llama-swap-apu/ks.yaml`
- Create: `kubernetes/apps/ai/llama-swap-apu/app/kustomization.yaml`
- Create: `kubernetes/apps/ai/llama-swap-apu/app/configmap.yaml`
- Create: `kubernetes/apps/ai/llama-swap-apu/app/tracingpolicy-models-write.yaml`
- Modify: `kubernetes/apps/ai/kustomization.yaml`

**Interfaces:**
- Produces: `ConfigMap/llama-swap-apu-config` in namespace `ai`, mounted
  by Task 5's `HelmRelease` at `/app/config.yaml`. Model aliases served:
  `fim`/`code-fim`/`coder-small` (→ `coder-fim`), `fast`/`small`/`router`
  (→ `qwen3-1.7b`).

- [ ] **Step 1: Create the Flux Kustomization entry point**

`kubernetes/apps/ai/llama-swap-apu/ks.yaml`:
```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app llama-swap-apu
  namespace: &namespace ai
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  path: ./kubernetes/apps/ai/llama-swap-apu/app
  prune: true
  retryInterval: 2m
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: *namespace
  timeout: 15m
  wait: false
```
(Exact copy of `kubernetes/apps/ai/llama-swap/ks.yaml`, only `name` and
`path` changed.)

- [ ] **Step 2: Create the app kustomization**

`kubernetes/apps/ai/llama-swap-apu/app/kustomization.yaml`:
```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./configmap.yaml
  - ./helmrelease.yaml
  - ./tracingpolicy-models-write.yaml
```

- [ ] **Step 3: Create the ConfigMap**

`kubernetes/apps/ai/llama-swap-apu/app/configmap.yaml` — `coder-fim` and
`qwen3-1.7b` moved verbatim from `kubernetes/apps/ai/llama-swap/app/configmap.yaml`,
with new local macros (`--flash-attn` and KV quant flags dropped: this is
an older Renoir/Vega iGPU, not the RDNA4/RDNA2 silicon the main
instance's macros are tuned for, and VRAM headroom here is generous
enough — ~16 GiB dedicated for ~3.5 GiB of resident models — that neither
optimization is needed):
```yaml
---
# yamllint disable rule:line-length
# yaml-language-server: $schema=https://kubernetesjsonschema.dev/master/configmap-v1.json
apiVersion: v1
kind: ConfigMap
metadata:
  name: llama-swap-apu-config
data:
  config.yaml: |
    # llama-swap config for the APU-light tier (bee-jms-03).
    # Docs: https://github.com/mostlygeek/llama-swap
    #
    # Renoir iGPU on bee-jms-03, BIOS-expanded to 16 GiB dedicated VRAM
    # (see docs/superpowers/specs/2026-08-16-apu-light-inference-tier-design.md).
    # Both models are small enough to stay resident together — no
    # exclusive-swap group needed here, unlike the 9070 XT's tight fit.
    healthCheckTimeout: 180
    logLevel: info
    startPort: 5800

    macros:
      # No --flash-attn / KV quant: older Vega/gfx90c silicon, not tuned
      # or verified for those flags, and VRAM headroom doesn't require
      # the trade-off here. Re-check before enabling if profiling shows
      # a need.
      "apu-vulkan": >-
        /app/llama-server
        --host 0.0.0.0 --port ${PORT}
        -ngl 99
        --jinja

      # FIM / base model invocation. No --jinja: base models have no chat
      # template; applying one produces garbled infill output.
      "apu-fim": >-
        /app/llama-server
        --host 0.0.0.0 --port ${PORT}
        -ngl 99

    models:
      # FIM autocomplete for Continue.dev. Qwen2.5-Coder-3B BASE (not
      # Instruct): pretrained with FIM tokens, no chat post-training.
      # apu-fim macro omits --jinja so infill gets raw completion.
      "coder-fim":
        cmd: |
          ${apu-fim}
          --model /models/Qwen2.5-Coder-3B-Q5_K_M.gguf
          --ctx-size 32768
          --temp 0.2 --top-p 0.95
        aliases:
          - "fim"
          - "code-fim"
          - "coder-small"
        ttl: 600

      # Fast router + HA/voice model. Accessible via fast/small/router
      # aliases. Caller system prompt should include /no_think to
      # suppress CoT.
      "qwen3-1.7b":
        cmd: |
          ${apu-vulkan}
          --model /models/Qwen3-1.7B-Q5_K_M.gguf
          --ctx-size 8192
          --temp 0.7 --top-p 0.8
        aliases:
          - "fast"
          - "small"
          - "router"
        ttl: 300

    groups:
      # Both models resident together — combined footprint (~3.5 GiB) is
      # a small fraction of this node's 16 GiB dedicated VRAM, so no
      # exclusive-swap contention like the 9070 XT's chat group.
      "always-on":
        swap: false
        exclusive: false
        persistent: true
        members:
          - "coder-fim"
          - "qwen3-1.7b"
```

- [ ] **Step 4: Create the TracingPolicy**

`kubernetes/apps/ai/llama-swap-apu/app/tracingpolicy-models-write.yaml`
— exact copy of `kubernetes/apps/ai/llama-swap/app/tracingpolicy-models-write.yaml`,
with `metadata.name` and `spec.podSelector.matchLabels` updated to match
this app (the original's `podSelector` only matches
`app.kubernetes.io/name: llama-swap`, which this app's pods won't carry):
```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/cilium/tetragon/main/pkg/k8s/apis/cilium.io/client/crds/v1alpha1/cilium.io_tracingpolicies.yaml
# llama-swap-apu model-fetch initContainer downloads weights to /models
# (shared PVC) as root via curl from HuggingFace. After init, the main
# container (llama-server) only READS /models — never writes. Same
# supply-chain rationale as the main llama-swap instance's policy
# (kubernetes/apps/ai/llama-swap/app/tracingpolicy-models-write.yaml) —
# see that file for full context. This is a separate policy, not a
# shared one, because podSelector is namespace-scoped by pod label and
# this app's pods carry app.kubernetes.io/name: llama-swap-apu.
apiVersion: cilium.io/v1alpha1
kind: TracingPolicyNamespaced
metadata:
  name: monitor-llama-swap-apu-models-write
  namespace: ai
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: llama-swap-apu
  kprobes:
    - call: "security_file_permission"
      syscall: false
      args:
        - index: 0
          type: "file"
        - index: 1
          type: "int"
      selectors:
        - matchArgs:
            - index: 0
              operator: "Prefix"
              values:
                - "/models/"
            - index: 1
              # MAY_WRITE (0x2) — file is being opened/modified for write.
              operator: "Mask"
              values:
                - "2"
          matchBinaries:
            - operator: "NotIn"
              values:
                - "/usr/bin/curl"
                - "/bin/curl"
          matchActions:
            - action: Post
```

- [ ] **Step 5: Register the app in the `ai` namespace kustomization**

In `kubernetes/apps/ai/kustomization.yaml`, the `resources:` list is
alphabetical. By this point Task 1 has already removed the `ollama`
entry — add the new entry between `llama-swap` and `openclaw`:
```yaml
resources:
  - ./faster-whisper/ks.yaml
  - ./holmesgpt/ks.yaml
  - ./llama-swap/ks.yaml
  - ./llama-swap-apu/ks.yaml
  - ./openclaw/ks.yaml
  - ./openviking/ks.yaml
  - ./piper/ks.yaml
```

- [ ] **Step 6: Validate the build**

```bash
kustomize build kubernetes/apps/ai/llama-swap-apu/app
```
Expected: renders 3 documents (ConfigMap, TracingPolicy — HelmRelease not
yet created, that's Task 5) with no errors. This will fail to find
`./helmrelease.yaml` until Task 5 — that's expected; don't run the
`--dry-run` apply check until Task 5 is also done.

- [ ] **Step 7: Commit** (do not push yet — Task 5 completes this app)

```bash
git add kubernetes/apps/ai/llama-swap-apu kubernetes/apps/ai/kustomization.yaml
git commit -m "feat(ai): scaffold llama-swap-apu config, tracing policy, and Flux entry"
```

---

### Task 5: `llama-swap-apu` HelmRelease

**Files:**
- Create: `kubernetes/apps/ai/llama-swap-apu/app/helmrelease.yaml`

**Interfaces:**
- Consumes: `ConfigMap/llama-swap-apu-config` (Task 4), `amd.com/gpu`
  allocatable on `bee-jms-03` (Task 3)
- Produces: `Service/llama-swap-apu` on port 8080 in namespace `ai`,
  reachable cluster-internal at
  `llama-swap-apu.ai.svc.cluster.local:8080` (OpenAI-compatible API)

- [ ] **Step 1: Write the HelmRelease**

`kubernetes/apps/ai/llama-swap-apu/app/helmrelease.yaml` — same
`bjw-s` app-template + OCIRepository pattern as
`kubernetes/apps/ai/llama-swap/app/helmrelease.yaml`, scaled down: no
external `route` (internal-only, nothing wired to it yet per spec scope),
smaller PVC and resource requests, model-fetch pulls only the 2 GGUFs
this instance needs, `nodeAffinity` hard-pinned by hostname instead of
the main instance's tiered preference:
```yaml
---
# yamllint disable rule:line-length
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: &app llama-swap-apu
spec:
  interval: 1h
  chartRef:
    kind: OCIRepository
    name: app-template
  # Cold fetch is only ~3.5 GiB (2 small GGUFs) vs the main instance's
  # ~60 GiB, but keep the same generous timeout pattern for consistency
  # and slow-link tolerance.
  timeout: 15m
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  values:
    controllers:
      llama-swap-apu:
        # Recreate: init container writes to the same RWO PVC the main
        # container reads from. Rolling update would spawn a second pod
        # competing for that PVC. Same rationale as the main instance.
        strategy: Recreate
        annotations:
          reloader.stakater.com/auto: "true"
        initContainers:
          model-fetch:
            image:
              repository: curlimages/curl
              # renovate: datasource=docker depName=curlimages/curl
              tag: 8.21.0
            command: ["/bin/sh", "-c"]
            args:
              - |
                set -eu
                cd /models
                human() {
                  awk -v b="$1" 'BEGIN{
                    split("B KiB MiB GiB TiB",u," ");
                    i=1; while (b>=1024 && i<5) { b=b/1024; i++ }
                    printf "%.2f %s", b, u[i]
                  }'
                }
                fetch() {
                  url="$1"; out="$2"; min_bytes="$3"
                  if [ -f "$out" ]; then
                    have=$(stat -c %s "$out" 2>/dev/null || echo 0)
                    if [ "$have" -ge "$min_bytes" ]; then
                      echo "[skip] $out exists ($(human $have))"
                      return 0
                    fi
                    echo "[retry] $out too small ($have < $min_bytes), re-fetching"
                    rm -f "$out"
                  fi
                  echo "[fetch] $out"
                  curl --no-progress-meter -Lf -o "$out.part" "$url" &
                  cpid=$!
                  while kill -0 "$cpid" 2>/dev/null; do
                    sleep 5
                    if [ -f "$out.part" ]; then
                      cur=$(stat -c %s "$out.part" 2>/dev/null || echo 0)
                      echo "[progress] $out: $(human $cur)"
                    fi
                  done
                  wait "$cpid"
                  final=$(stat -c %s "$out.part" 2>/dev/null || echo 0)
                  mv "$out.part" "$out"
                  echo "[done]  $out: $(human $final)"
                }
                # Qwen3-1.7B Q5_K_M (~1.17 GiB) — router/fast/small
                fetch \
                  "https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q5_K_M.gguf?download=true" \
                  "Qwen3-1.7B-Q5_K_M.gguf" \
                  1200000000
                # Qwen2.5-Coder-3B BASE Q5_K_M (~2.2 GiB) — FIM autocomplete
                fetch \
                  "https://huggingface.co/bartowski/Qwen2.5-Coder-3B-GGUF/resolve/main/Qwen2.5-Coder-3B-Q5_K_M.gguf?download=true" \
                  "Qwen2.5-Coder-3B-Q5_K_M.gguf" \
                  2100000000
                echo "[finished] model staging complete"
                ls -lh /models
            env:
              HF_HUB_OFFLINE: "0"
            resources:
              requests:
                cpu: 100m
                memory: 128Mi
              limits:
                memory: 512Mi
            securityContext:
              runAsNonRoot: false
              runAsUser: 0
        containers:
          app:
            image:
              repository: ghcr.io/mostlygeek/llama-swap
              # Same Vulkan build as the main instance — portable across
              # AMD GPUs, no ROCm dependency.
              # renovate: datasource=docker depName=ghcr.io/mostlygeek/llama-swap
              tag: v230-vulkan-b9803
            args:
              - --config
              - /app/config.yaml
              - --listen
              - 0.0.0.0:8080
            env:
              GGML_VK_VISIBLE_DEVICES: "0"
              HF_HUB_OFFLINE: "1"
            resources:
              requests:
                cpu: 250m
                memory: 2Gi
              limits:
                # Two small models (~3.5 GiB combined) plus KV cache and
                # process overhead — well under this ceiling.
                memory: 6Gi
                amd.com/gpu: "1"
            probes:
              liveness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /health
                    port: 8080
                  initialDelaySeconds: 30
                  periodSeconds: 30
                  failureThreshold: 5
              readiness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /health
                    port: 8080
                  initialDelaySeconds: 10
                  periodSeconds: 10
              startup:
                enabled: false
            securityContext:
              runAsNonRoot: false
              runAsUser: 0
    service:
      app:
        controller: *app
        ports:
          http:
            port: &port 8080
    persistence:
      models:
        type: persistentVolumeClaim
        storageClass: openebs-hostpath
        accessMode: ReadWriteOnce
        size: 15Gi
        retain: true
        globalMounts:
          - path: /models
      config:
        type: configMap
        name: llama-swap-apu-config
        globalMounts:
          - path: /app/config.yaml
            subPath: config.yaml
            readOnly: true
    defaultPodOptions:
      # Hard-pinned to bee-jms-03 by hostname — this is the only node with
      # enough dedicated VRAM (16 GiB, BIOS-expanded) to be worth
      # targeting. No preference/fallback tiering: unlike the main
      # instance, this one has nowhere sensible to fail over to.
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: kubernetes.io/hostname
                    operator: In
                    values: ["bee-jms-03"]
```

- [ ] **Step 2: Validate the full app build**

```bash
kustomize build kubernetes/apps/ai/llama-swap-apu/app | kubectl apply --dry-run=client -f -
```
Expected: `configmap/llama-swap-apu-config`, `helmrelease.helm.toolkit.fluxcd.io/llama-swap-apu`,
and `tracingpolicynamespaced.cilium.io/monitor-llama-swap-apu-models-write`
all report `created (dry run)` with no errors.

- [ ] **Step 3: Commit and push**

```bash
git add kubernetes/apps/ai/llama-swap-apu/app/helmrelease.yaml
git commit -m "feat(ai): add llama-swap-apu HelmRelease pinned to bee-jms-03"
git push
```

- [ ] **Step 4: Reconcile and verify live**

```bash
flux reconcile kustomization llama-swap-apu -n ai --with-source
kubectl -n ai get pods -l app.kubernetes.io/name=llama-swap-apu -o wide
```
Expected: pod scheduled on `bee-jms-03`, eventually `Running 1/1` (allow
several minutes for the ~3.5 GiB cold GGUF fetch — watch with
`kubectl -n ai logs -f -l app.kubernetes.io/name=llama-swap-apu -c model-fetch`
if it's slow).

- [ ] **Step 5: Functional verification**

```bash
curl -s http://llama-swap-apu.ai.svc.cluster.local:8080/v1/models | jq
```
Expected: JSON listing both models with their aliases. From inside the
cluster (e.g. `kubectl run` a debug pod, or `kubectl -n ai exec` into an
existing pod) if `curl` isn't available from your shell:
```bash
curl -s http://llama-swap-apu.ai.svc.cluster.local:8080/v1/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"coder-fim","prompt":"def add(a, b):\n    return"}' | jq
```
Expected: a completion response continuing the function body (`a + b` or
similar) — confirms the FIM model loads and serves on this node's GPU.

---

### Task 6: Trim the main `llama-swap` instance

**Files:**
- Modify: `kubernetes/apps/ai/llama-swap/app/configmap.yaml`
- Modify: `kubernetes/apps/ai/llama-swap/app/helmrelease.yaml`

**Interfaces:**
- Consumes: nothing from earlier tasks (independent of `llama-swap-apu`
  being live, but do this AFTER Task 5 so there's no window where
  `coder-fim`/`router` are served by neither instance)
- Produces: main `llama-swap` no longer serves `coder-fim` or
  `qwen3-1.7b`/`fast`/`small`/`router`; its `chat` group drops from 7 to
  6 members, `always-on` group drops from 3 to 2 members

**Why the affinity change (Step 3) matters:** the main instance's
existing `defaultPodOptions.affinity` already had a fallback preference
to schedule onto `bee-jms-03` if `bigboi-jms-01` was unavailable
(`amd.com/gpu.vram In ["16G"]` required, weight-50 preference for
`bee-jms-03` by hostname). Now that `bee-jms-03` runs a dedicated,
always-resident `llama-swap-apu` pod holding the node's single
`amd.com/gpu: 1` allocatable, that fallback would leave the main
instance's pod permanently `Pending` if it ever tried to use it (both
pods would be requesting the same single GPU resource on that node,
which is required, not preferred, and there's no second GPU on that
node). Removing the fallback prevents this failure mode outright — the
main instance now requires `node.kubernetes.io/gpu-tier: dgpu` (the
label we already set for `bigboi-jms-01`), full stop.

- [ ] **Step 1: Remove `coder-fim` and `qwen3-1.7b` from the ConfigMap**

In `kubernetes/apps/ai/llama-swap/app/configmap.yaml`:

Delete the `"llama-fim"` macro block (only `coder-fim` used it, and
`coder-fim` is leaving):
```yaml
      # FIM / base model invocation. No --jinja: base models have no chat
      # template; applying one produces garbled infill output.
      "llama-fim": >-
        /app/llama-server
        --host 0.0.0.0 --port ${PORT}
        -ngl 99
        --flash-attn on
        --cache-type-k q8_0 --cache-type-v q8_0

```
Delete the `"coder-fim"` model block:
```yaml
      # FIM autocomplete for Continue.dev. Qwen2.5-Coder-3B BASE (not Instruct):
      # pretrained with FIM tokens, no chat post-training. llama-fim macro omits
      # --jinja so infill gets raw completion. Q5_K_M: fewer hallucinated
      # identifiers vs Q4 at only +0.4 GiB. Do not use a chat template here.
      "coder-fim":
        cmd: |
          ${llama-fim}
          --model /models/Qwen2.5-Coder-3B-Q5_K_M.gguf
          --ctx-size 32768
          --temp 0.2 --top-p 0.95
        aliases:
          - "fim"
          - "code-fim"
          - "coder-small"
        ttl: 600

```
Delete the `"qwen3-1.7b"` model block:
```yaml
      # Fast router + HA/voice model. Always-on (persistent): with the coder at
      # Q3_K_S there is room to keep this resident (~1.3 GiB) so routing,
      # title-gen (opencode small_model) and Home Assistant voice never evict
      # the resident coder. Accessible via fast/small/router aliases.
      # Caller system prompt should include /no_think to suppress CoT.
      "qwen3-1.7b":
        cmd: |
          ${llama-vulkan}
          --model /models/Qwen3-1.7B-Q5_K_M.gguf
          --ctx-size 8192
          --temp 0.7 --top-p 0.8
        aliases:
          - "fast"
          - "small"
          - "router"
        ttl: 300

```
In the `groups.chat.members` list, remove `"coder-fim"`:
```yaml
      "chat":
        swap: true
        exclusive: true
        members:
          - "qwen3-8b"
          - "agentic-coder"
          - "reasoner"
          - "reasoner-agentic"
          - "qwen3-14b"
          - "qwen3.6-27b"
```
In the `groups.always-on` block, remove `"qwen3-1.7b"` from `members` and
update its comment (it referenced routing/voice/title-gen staying
resident, which is no longer true here — that's now `llama-swap-apu`'s
job):
```yaml
      # Always-on: embed + rerank, ~1.3 GiB resident. Router/voice/FIM
      # moved to llama-swap-apu (bee-jms-03) — see
      # docs/superpowers/specs/2026-08-16-apu-light-inference-tier-design.md.
      "always-on":
        swap: false
        exclusive: false
        persistent: true
        members:
          - "qwen3-embed"
          - "qwen3-rerank"
```

- [ ] **Step 2: Update the `model-fetch` init container**

In `kubernetes/apps/ai/llama-swap/app/helmrelease.yaml`, remove the two
`fetch` calls for the models that moved (in the `# ── Always-on group`
and `# ── Chat group` sections of the init container's `args` script):
```yaml
                # Qwen3-1.7B Q5_K_M (~1.17 GiB) — router, always-on
                fetch \
                  "https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q5_K_M.gguf?download=true" \
                  "Qwen3-1.7B-Q5_K_M.gguf" \
                  1200000000
```
and
```yaml
                # Qwen2.5-Coder-3B BASE Q5_K_M (~2.2 GiB) — FIM autocomplete
                # BASE not Instruct: pretrained with FIM tokens, no chat template
                fetch \
                  "https://huggingface.co/bartowski/Qwen2.5-Coder-3B-GGUF/resolve/main/Qwen2.5-Coder-3B-Q5_K_M.gguf?download=true" \
                  "Qwen2.5-Coder-3B-Q5_K_M.gguf" \
                  2100000000
```
(Leave the already-downloaded GGUF files on the PVC alone — no cleanup
step needed; `retain: true` means the PVC and its stale files persist,
which is harmless disk usage, not a correctness issue. Note this as a
known, accepted leftover rather than chasing PVC cleanup in this plan.)

- [ ] **Step 3: Fix the node affinity**

Replace the entire `defaultPodOptions.affinity` block:
```yaml
    defaultPodOptions:
      # Prefer bigboi-jms-01 dGPU (Navi 48/9070 XT, 64CU, 16G VRAM, weight 100).
      # Falls back to bee-jms-03 APU (Cezanne 8CU, 16G UMA, weight 50).
      # `amd.com/gpu.vram In ["16G"]` is REQUIRED — bee-jms-01/02 have 3G UMA
      # which OOMs on Qwen3-14B / Coder-7B.
      # Note: amd.com/gpu.family NOT required — Navi 48 (device-id 7550) is
      # unrecognized by the labeller and emits no family label. vram sufficient.
      # ROCm is non-functional on Talos (HIP ABI mismatch); Vulkan on both.
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: amd.com/gpu.vram
                    operator: In
                    values: ["16G"]
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              preference:
                matchExpressions:
                  - key: node.kubernetes.io/gpu-tier
                    operator: In
                    values: ["dgpu"]
            - weight: 50
              preference:
                matchExpressions:
                  - key: kubernetes.io/hostname
                    operator: In
                    values: ["bee-jms-03"]
```
with:
```yaml
    defaultPodOptions:
      # Hard-required to bigboi-jms-01's dgpu tier — no fallback. The old
      # fallback to bee-jms-03 (weight 50) is gone: that node now runs a
      # dedicated, always-resident llama-swap-apu pod holding its single
      # amd.com/gpu allocatable, so this instance scheduling there would
      # leave it permanently Pending. See
      # docs/superpowers/specs/2026-08-16-apu-light-inference-tier-design.md.
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: node.kubernetes.io/gpu-tier
                    operator: In
                    values: ["dgpu"]
```

- [ ] **Step 4: Validate the build**

```bash
kustomize build kubernetes/apps/ai/llama-swap/app | kubectl apply --dry-run=client -f -
```
Expected: no errors, `configmap/llama-swap-config` and
`helmrelease.helm.toolkit.fluxcd.io/llama-swap` both `configured (dry run)`.

- [ ] **Step 5: Commit and push**

```bash
git add kubernetes/apps/ai/llama-swap/app/configmap.yaml kubernetes/apps/ai/llama-swap/app/helmrelease.yaml
git commit -m "fix(ai): move coder-fim + router off bigboi to llama-swap-apu, remove stale bee-jms-03 fallback affinity"
git push
```

- [ ] **Step 6: Reconcile and verify live**

```bash
flux reconcile kustomization llama-swap -n ai --with-source
kubectl -n ai get pods -l app.kubernetes.io/name=llama-swap -o wide
curl -s http://llama-swap.ai.svc.cluster.local:8080/v1/models | jq
```
Expected: pod still `Running 1/1` on `bigboi-jms-01` (Recreate strategy
means brief downtime during rollout — expected), `/v1/models` list no
longer contains `fim`/`code-fim`/`coder-small`/`fast`/`small`/`router`.
Spot-check a remaining alias still works:
```bash
curl -s http://llama-swap.ai.svc.cluster.local:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"default","messages":[{"role":"user","content":"say hi in one word"}]}' | jq
```

---

### Task 7: Documentation

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** none — pure documentation, no code path depends on this.

- [ ] **Step 1: Update the model alias table entries**

`CLAUDE.md:354` currently:
```
  - `fast`/`small`/`router` → `qwen3-1.7b` (routing/classification, always-on)
```
Change to:
```
  - `fast`/`small`/`router` → `qwen3-1.7b` (routing/classification, always-on, served by **llama-swap-apu** on bee-jms-03 — see below)
```
`CLAUDE.md:356` currently:
```
  - `coder-fim`/`fim` → Qwen2.5-Coder-3B base (FIM autocomplete)
```
Change to:
```
  - `coder-fim`/`fim` → Qwen2.5-Coder-3B base (FIM autocomplete, served by **llama-swap-apu** on bee-jms-03 — see below)
```

- [ ] **Step 2: Add the `llama-swap-apu` entry to "Currently deployed"**

Find the `llama-swap` bullet in the "Currently deployed" list under
"Deployed Applications (ai namespace)" and add a new bullet immediately
after it:
```
- **llama-swap-apu** — second llama-swap instance, hard-pinned to `bee-jms-03` (Renoir iGPU, BIOS-expanded to 16 GiB dedicated VRAM — see `docs/superpowers/specs/2026-08-16-apu-light-inference-tier-design.md` for the bee-* hardware asymmetry). Hosts only `coder-fim` (FIM autocomplete) and `qwen3-1.7b` (`fast`/`small`/`router`), both always-on/non-exclusive — moved off the 9070 XT to stop FIM completions evicting large chat models from its tight exclusive-swap group. Cluster-internal only (`llama-swap-apu.ai.svc.cluster.local:8080`), no external route. `bee-jms-01`/`-02` are excluded (3 GiB stock dedicated VRAM, not worth targeting). No routing layer in front of the two llama-swap instances — consumers pick the endpoint that matches their model directly.
```

- [ ] **Step 3: Update the Continue.dev planned-deployment note**

`CLAUDE.md:373` currently:
```
- **Continue.dev** (client-side, not cluster) — IDE coding assistant. Would point at llama-swap directly (`coder`/`coder-fim` aliases). No deployment, just user config.
```
Change to:
```
- **Continue.dev** (client-side, not cluster) — IDE coding assistant. Chat (`coder`) points at the main `llama-swap` instance; FIM autocomplete (`coder-fim`/`fim`) points at `llama-swap-apu.ai.svc.cluster.local:8080` instead — see the APU-light tier entry above. No deployment yet, just user config.
```

- [ ] **Step 4: Commit and push**

```bash
git add CLAUDE.md
git commit -m "docs: document the llama-swap-apu two-tier inference topology"
git push
```

---

## Final Verification (after all tasks)

```bash
# Both apps build clean
kustomize build kubernetes/apps/ai/llama-swap/app | kubectl apply --dry-run=client -f -
kustomize build kubernetes/apps/ai/llama-swap-apu/app | kubectl apply --dry-run=client -f -
kustomize build kubernetes/apps/kube-system/amd-gpu/app | kubectl apply --dry-run=client -f -

# Both Flux Kustomizations are Ready
flux get ks -n ai llama-swap llama-swap-apu

# GPU allocatable on both target nodes
kubectl describe node bigboi-jms-01 | grep amd.com/gpu
kubectl describe node bee-jms-03 | grep amd.com/gpu

# No pod ever Pending on bee-jms-03 for GPU contention
kubectl -n ai get pods -o wide --field-selector spec.nodeName=bee-jms-03

# Full model catalog split correctly across both endpoints
curl -s http://llama-swap.ai.svc.cluster.local:8080/v1/models | jq '.data[].id'
curl -s http://llama-swap-apu.ai.svc.cluster.local:8080/v1/models | jq '.data[].id'
```
