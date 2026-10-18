# Bee Hardening + bigboi Drain (Phase 0c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three `bee-*` nodes able to carry every non-AI workload on their own, and empty `bigboi-jms-01` of everything except the AI and GPU stack. This is spec Phase 0 items 0.4–0.7. Item 0b (the `macos/` flake, CI and Renovate) already shipped in #755.

**Architecture:** Repo changes ship as three PRs. Cluster-mutating steps between them are **operator gates**: the executing agent stops, hands the operator exact commands, and waits for their output.

- **PR1** fixes Velero first. Every PV migration depends on it, and it has been OOM-failing every nightly backup since at least 2026-09-28. PR1 also right-sizes memory requests and raises `systemReserved`.
- **PV migrations** are operator-run: gatus as the rehearsal, then holyclaude, then omniroute. Each one is a labelled Velero Backup, then delete the PVC, then a node-mapped Restore onto a bee.
- **PR2** adds DaemonSet tolerations, removes netdata, and taints bigboi. The descheduler (`RemovePodsViolatingNodeTaints`) then drains it.
- **PR3** converts both Traefik DaemonSets to 2-replica Deployments with `externalTrafficPolicy: Cluster`.

**Tech Stack:** Flux Operator GitOps, Talos + talhelper, Cilium 1.20 (L2 announcements, DSR, `bpf.masquerade`), Velero 1.18.2 (chart 12.2.1, kopia FS backup), OpenEBS LocalPV hostpath (WFFC), bjw-s app-template 5.3.0, Traefik chart 41.6.1, kubernetes-sigs descheduler.

**Spec:** `docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md` (Phase 0 items 4–7, "Pinned PVs" table, "Dedupe", "Migration method").

## Global Constraints

- Spec 0.4: "Bee hardening: `requests` on every workload leaving bigboi; verify `kubelet.systemReserved`."
- Spec 0.5: "Verify Cilium egress masquerade (sets the `pf` allowlist). Rehearse a Velero restore of `services/gatus` onto a bee."
- Spec 0.6: "Drain bigboi's non-AI workloads; migrate pinned PVs; remove netdata; convert Traefik to Deployments."
- Spec 0.7: "Delete orphan PVs after confirmation."
- Pinned-PV dispositions (spec):

  | PVC | Disposition |
  |---|---|
  | holyclaude 50Gi | → bee-03 (D11) |
  | omniroute-data 10Gi + omniroute-cliproxyapi-data 1Gi | migrate |
  | gatus 200Mi | migrate (fresh start acceptable) |
  | data-trivy-server-0 | recreate |
  | netdata-k8s-state-varlib | delete with netdata |
  | ai/llama-swap 50Gi | delete **at cutover**: Phase 3, NOT this plan |
  | ai/ollama, ai/data-agent-canvas-0, ai/claude-code-workspace | delete after operator confirmation |

- Migration method (spec): fresh Velero backup → delete PVC + pod → restore with node affinity to the target bee (WFFC). Rehearse on gatus first.
- `openebs-hostpath-fast` retirement is **out of scope**. ai/llama-swap still uses it until Phase 3.
- Traefik: two separate 2-replica Deployments (external and internal stay separate).
- Memory target (spec): ~40 of 103GiB requested on the bees.
- Never touch `/workspace/home-ops`. That checkout holds the operator's uncommitted work. Work only in `/workspace/home-ops-mac-spec`.
- `KUBECONFIG=/workspace/home-ops/kubeconfig` is for read-only `kubectl get/describe/top`. Every mutation is an operator gate.
- Quorum rules: one node-mutating task at a time, and wait for the node to rejoin and report healthy before the next. `task talos:apply-node` runs `etcd-quorum-precheck`.
- Operator-pasted commands carry **no inline `#` comments**, because the operator's zsh passes them as arguments. Put explanations in prose.
- Reloader: any workload touched that consumes a ConfigMap or Secret keeps its reloader annotation on the pod template.
- Every PR runs these before commit: `task sops:verify`, `kustomize build kubernetes/apps/<ns>/<app>/app | kubectl apply --dry-run=client -f -`, and the `flux-manifest-reviewer` + `sops-leak-detector` agents.
- Commit messages explain the *why*. They end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Use `env -u GITHUB_TOKEN gh …`. Ask before pushing or merging.
- Spec items deferred **to the very end** (operator's instruction): Phase 1 Task 10 operator checks (`sshd -T`, keyed `/v1/models`, §11 FileVault pre-boot unlock, Task 10 Steps 1–4 and 6). They are not part of this plan.

## Survey facts this plan relies on (2026-10-18)

- **Velero is down.** It has had 21 Failed and 0 Completed backups since at least 2026-09-28. Each run fails with "found a backup with status "InProgress" during the server starting, mark it as "Failed"".
  - The server pod is OOMKilled about 15s into each run (exit 137, limit `500Mi`) and has 10 restarts.
  - `velero_backup_failure_total` never increments for startup-marked failures, so `VeleroBackupFailure` stays silent. Only `VeleroScheduleStale` fires.
- **Requests vs usage on bigboi** (`kubectl top`; VM has no cAdvisor series):

  | Workload | Request (Mi) | Usage (Mi) |
  |---|---|---|
  | authentik-server | 256 | 679 |
  | authentik-worker | 256 | 287 |
  | holyclaude | 1088 | 1419 |
  | vmagent | 281 | 407 |
  | kube-state-metrics | 0 | 140 |
  | cloudnative-pg | 0 | 64 |
  | cloudflare-dns | 0 | 40 |
  | unifi-dns | 0 | 70 |
  | tuppr | 0 | 103 |
  | cilium-operator | 0 | 116 |
  | reloader | 64 | 86 |
  | vector (DaemonSet, bees) | 0 | 187–277 |

- **Cilium L2 announcements are incompatible with `externalTrafficPolicy: Local`.** IPs can be announced from a node with no backend, and that traffic drops. Today this is masked only because Traefik runs on every node.
  - `loadBalancer.mode: dsr` preserves the client source IP, so `externalTrafficPolicy: Cluster` is safe for Traefik's PROXY-protocol and CrowdSec client-IP logic. Task 7 verifies this.
- **Descheduler (5m) already has `RemovePodsViolatingNodeTaints`** with `evictLocalStoragePods: true`, `ignorePvcPods: false` and `nodeFit: true`.
  - Once bigboi is tainted, it evicts every non-tolerating pod, including PV-pinned ones, which would then hang Pending.
  - **All PV migrations must finish before the taint.**
- **DaemonSets that already tolerate everything:** cilium, cilium-envoy, spegel, tetragon, node-exporter, netdata-child.
- **DaemonSets that need a toleration to keep bigboi coverage:** amd-gpu DeviceConfig `dgpu` (device-plugin, node-labeller, metrics-exporter), node-feature-discovery worker, drm-exporter, vector, irqbalance, velero node-agent. llama-swap (a Deployment pinned to dgpu) also needs one.
- **Restore gotcha:** a pod Velero restores still carries `ownerReferences` to its old ReplicaSet. The live ReplicaSet controller or the GC then deletes or adopts it before kopia restores the data ([community report](https://archive.git.mtrnord.blog/MTRNord/cluster/commit/60a4d7dcaa2cf1b51bb565c3f2907d64b4840583.html)).
  - The runbook deletes the Deployment (with the HelmRelease suspended) and strips `ownerReferences` through a resource modifier.
- Free `/var` disk: bee-01 772GiB, bee-02 241GiB, bee-03 133GiB. holyclaude's 50Gi fits on bee-03.

## File Map

| File | Task | Change |
|---|---|---|
| `kubernetes/apps/velero/app/helmrelease.yaml` | 1, 6 | server memory; node-agent toleration |
| `kubernetes/apps/velero/app/prometheusrule.yaml` | 1 | add success-staleness alert |
| `kubernetes/apps/security/authentik/app/helmrelease.yaml` | 2 | server/worker requests |
| `kubernetes/apps/ai/holyclaude/app/helmrelease.yaml` | 2, 5 | main requests; affinity |
| `kubernetes/apps/monitoring/victoria-metrics/app/vmagent.yaml` | 2 | requests |
| `kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml` | 2 | kube-state-metrics resources |
| `kubernetes/apps/databases/cloudnative-pg/app/helmrelease.yaml` | 2 | resources |
| `kubernetes/apps/network/cloudflare-dns/app/helmrelease.yaml` | 2 | resources |
| `kubernetes/apps/network/unifi-dns/app/helmrelease.yaml` | 2 | resources |
| `kubernetes/apps/system-upgrade/tuppr/app/helmrelease.yaml` | 2 | resources |
| `kubernetes/apps/kube-system/reloader/app/helmrelease.yaml` | 2 | requests |
| `kubernetes/apps/kube-system/cilium/app/helm/values.yaml` | 2 | operator resources |
| `kubernetes/apps/monitoring/vector/app/helmrelease.yaml` | 2, 6 | resources; toleration |
| `talos/patches/global/machine-kubelet.yaml` | 3 | systemReserved memory |
| `docs/runbooks/pv-node-migration.md` (create) | 4 | Velero node-migration runbook |
| `kubernetes/apps/kube-system/amd-gpu/app/deviceconfig.yaml` | 6 | dgpu tolerations |
| `kubernetes/apps/kube-system/amd-gpu/app/helmrelease.yaml` | 6 | NFD worker toleration |
| `kubernetes/apps/monitoring/drm-exporter/app/helmrelease.yaml` | 6 | toleration |
| `kubernetes/apps/kube-system/irqbalance/app/helmrelease.yaml` | 6 | toleration |
| `kubernetes/apps/ai/llama-swap/app/helmrelease.yaml` | 6 | toleration |
| `talos/talconfig.yaml` (bigboi entry, ~L97–152) | 6 | `nodeTaints` |
| `kubernetes/apps/monitoring/netdata/` (delete dir) | 6 | remove netdata |
| `kubernetes/apps/monitoring/kustomization.yaml` | 6 | drop `./netdata/ks.yaml` |
| `kubernetes/flux/meta/repos/netdata.yaml` (delete) + `kustomization.yaml` | 6 | drop repo |
| `kubernetes/apps/kube-system/tetragon/app/tracingpolicy-container-escape.yaml` L31–37 | 6 | drop netdata exemptions |
| `kubernetes/apps/network/traefik-{external,internal}/app/helmrelease.yaml` | 7 | Deployment + eTP Cluster |
| `README.md` (L132, L160, L247), `docs/runbooks/actions-runner-controller.md` (L48, L183) | 8 | stale netdata/fast-SC docs |

PR boundaries:

- **PR1** = Tasks 1–4.
- Operator migrations = Task 5, which carries its own small commit (holyclaude affinity) shipped as **PR1b** before the holyclaude move.
- **PR2** = Task 6.
- **PR3** = Task 7.
- **PR4** = Task 8.

---

### Task 1: Fix Velero OOM and alert on success staleness

**Files:**
- Modify: `kubernetes/apps/velero/app/helmrelease.yaml:49-56`
- Modify: `kubernetes/apps/velero/app/prometheusrule.yaml` (append a rule to group `velero-backups`)

**Interfaces:**
- Produces: a working Velero that Tasks 4 and 5 rely on, plus alert `VeleroBackupNoRecentSuccess`.

- [ ] **Step 1: Confirm the failure mode is still current**

Run:
```bash
kubectl --kubeconfig /workspace/home-ops/kubeconfig -n velero get pod -l app.kubernetes.io/name=velero -o jsonpath='{.items[0].status.containerStatuses[0].restartCount} {.items[0].status.containerStatuses[0].lastState.terminated.reason}{"\n"}'
kubectl --kubeconfig /workspace/home-ops/kubeconfig -n velero get backups.velero.io --sort-by=.metadata.creationTimestamp -o custom-columns=N:.metadata.name,P:.status.phase | tail -5
```
Expected: restartCount ≥ 10, `OOMKilled`, and the recent backups `Failed`. If the reason is no longer OOMKilled, stop and investigate: the fix below would be wrong.

- [ ] **Step 2: Raise the server memory**

Replace lines 49–56 of `kubernetes/apps/velero/app/helmrelease.yaml` with:
```yaml
    # Server memory: the 500Mi limit OOMKilled the server ~15s into every
    # daily-backup since at least 2026-09-28 (21 Failed / 0 Completed). On
    # restart Velero marks the InProgress backup Failed without bumping
    # velero_backup_failure_total, so VeleroBackupFailure never fired.
    # Item collection for a cluster-wide (includedNamespaces "*") backup
    # holds every object in memory; 2Gi leaves headroom.
    resources:
      requests:
        cpu: 100m
        memory: 512Mi
      limits:
        cpu: "1"
        memory: 2Gi
```

- [ ] **Step 3: Add the success-staleness alert**

In `kubernetes/apps/velero/app/prometheusrule.yaml`, insert after the `VeleroScheduleStale` rule (before `VeleroBackupDurationHigh`), at the same indentation:
```yaml
        - alert: VeleroBackupNoRecentSuccess
          # Attempts-based staleness (above) stayed green for 3 weeks while
          # every attempt died to a server OOM. This one measures outcomes:
          # no Completed backup for daily-backup in 27h.
          expr: |
            absent(velero_backup_last_successful_timestamp{schedule="daily-backup"}) == 1
              or (time() - velero_backup_last_successful_timestamp{schedule="daily-backup"}) > 27 * 3600
          for: 30m
          labels:
            severity: critical
            component: backup
          annotations:
            summary: "Velero daily-backup has not succeeded in 27h"
            description: |-
              No daily-backup Backup has reached Completed in the last 27
              hours. Check the server pod for OOMKilled restarts and:
              kubectl get backups.velero.io -n velero --sort-by=.metadata.creationTimestamp
```
Expected effect: the alert fires right after merge, because there has been no success yet, and clears after Step 7.

- [ ] **Step 4: Validate**

Run:
```bash
cd /workspace/home-ops-mac-spec
kustomize build kubernetes/apps/velero/app | kubectl --kubeconfig /workspace/home-ops/kubeconfig apply --dry-run=server -f - 2>&1 | tail -5
kustomize build kubernetes/apps/velero/app | grep -n -A6 'resources:' | head -20
```
Expected: no errors, and `memory: 2Gi` is present.

- [ ] **Step 5: Commit**

```bash
git add kubernetes/apps/velero/app/helmrelease.yaml kubernetes/apps/velero/app/prometheusrule.yaml
git commit -m "fix(velero): raise server memory to 2Gi; alert on no recent success

The velero server has been OOMKilled (500Mi limit) ~15s into every
daily-backup since at least 2026-09-28: 21 Failed, 0 Completed. On restart
Velero marks the InProgress backup Failed without incrementing
velero_backup_failure_total, so VeleroBackupFailure stayed silent; only
the attempts-based VeleroScheduleStale fired. Add an outcome-based
VeleroBackupNoRecentSuccess on velero_backup_last_successful_timestamp.

Prerequisite for the Phase 0c PV node migrations, which restore from
fresh Velero backups.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: OPERATOR GATE: ship PR1 early if the operator wants it standalone**

Ask the operator whether to push Task 1 alone as an urgent PR now, or to batch it with Tasks 2–4. Do not push without an answer.

- [ ] **Step 7: OPERATOR GATE: verified manual backup (after merge + Flux reconcile)**

The operator creates `/tmp/velero-verify-backup.yaml` with:
```yaml
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: verify-after-oom-fix
  namespace: velero
spec:
  includedNamespaces: ["*"]
  excludedNamespaces: [kube-system, kube-public, kube-node-lease, flux-system]
  snapshotVolumes: false
  defaultVolumesToFsBackup: true
  ttl: 720h0m0s
```
Then runs:
```bash
kubectl apply -f /tmp/velero-verify-backup.yaml
kubectl -n velero get backups.velero.io verify-after-oom-fix -w
```
Pass criteria:

- Phase reaches `Completed`. `PartiallyFailed` is acceptable only if `kubectl -n velero get podvolumebackups.velero.io -l velero.io/backup-name=verify-after-oom-fix` shows `Completed` for the gatus, holyclaude, omniroute-data and omniroute-cliproxyapi-data volumes. List the failing items for the ledger.
- The server pod restart count did not increase.
- `kubectl -n velero top pod` peak stays below 1.5Gi. If it is above, raise the limit before continuing.

**Hard gate:** Tasks 4–5 do not start until this passes.

---

### Task 2: Right-size requests for workloads leaving bigboi

**Files:** listed per step. Every value comes from the survey table. Each new request is about 1.1–1.3× observed usage, rounded up to a power-of-two-ish Mi.

**Interfaces:**
- Produces: honest scheduler accounting on the bees, so the scheduler (and the descheduler's `nodeFit`) never packs a bee past what it can hold.

- [ ] **Step 1: Verify each chart's values key before editing**

Run each command and confirm the key shown exists at the top level of that chart's values (or under the noted parent). Record any mismatch in the ledger and use the chart's real key instead:
```bash
helm show values oci://ghcr.io/home-operations/charts-mirror/external-dns --version 1.23.0 2>/dev/null | grep -n '^resources:'
helm show values cloudnative-pg --repo https://cloudnative-pg.github.io/charts --version 0.29.1 | grep -n '^resources:'
helm show values oci://ghcr.io/home-operations/charts/tuppr --version 0.5.8 | grep -n '^resources:'
helm show values vector --repo https://helm.vector.dev --version 0.59.0 | grep -n -E '^resources:|^tolerations:'
helm show values kube-prometheus-stack --repo https://prometheus-community.github.io/helm-charts | grep -n -A3 '^kube-state-metrics:'
```
Look up the exact OCI URLs for external-dns and tuppr from the `ocirepository.yaml` next to each HelmRelease (`grep url: kubernetes/apps/network/cloudflare-dns/app/ocirepository.yaml`, likewise for tuppr). Take the kube-prometheus-stack version from its `ocirepository.yaml`/HR. The kube-state-metrics subchart takes `resources:` under `kube-state-metrics:`.

- [ ] **Step 2: authentik (`kubernetes/apps/security/authentik/app/helmrelease.yaml`)**

Change the server `resources.requests.memory` (block at ~L40–45) from `256Mi` to `768Mi`, and the worker (~L55–60) from `256Mi` to `320Mi` (usage 287Mi). If either limit is below the new request, raise that limit to 2× the request.

- [ ] **Step 3: holyclaude (`kubernetes/apps/ai/holyclaude/app/helmrelease.yaml` ~L430–435)**

Main container `resources.requests.memory: 1Gi` → `1536Mi`. Keep the limit at `6Gi`.

- [ ] **Step 4: vmagent (`kubernetes/apps/monitoring/victoria-metrics/app/vmagent.yaml` L16–21)**

`requests.memory: 256Mi` → `512Mi`. Keep the limit at `1Gi`.

- [ ] **Step 5: kube-state-metrics (kube-prometheus-stack HR, under `kube-state-metrics:` ~L87)**

Add:
```yaml
      resources:
        requests:
          cpu: 10m
          memory: 192Mi
        limits:
          memory: 512Mi
```

- [ ] **Step 6: cloudnative-pg, cloudflare-dns, unifi-dns, tuppr**

Add a top-level `resources:` under `spec.values:` in each HR:

| HR | requests cpu / memory | limit memory |
|---|---|---|
| `kubernetes/apps/databases/cloudnative-pg/app/helmrelease.yaml` | 10m / 128Mi | 256Mi |
| `kubernetes/apps/network/cloudflare-dns/app/helmrelease.yaml` | 10m / 64Mi | 128Mi |
| `kubernetes/apps/network/unifi-dns/app/helmrelease.yaml` | 10m / 128Mi | 256Mi |
| `kubernetes/apps/system-upgrade/tuppr/app/helmrelease.yaml` | 10m / 128Mi | 256Mi |

Example (cloudflare-dns), indented to sit under `values:`:
```yaml
    resources:
      requests:
        cpu: 10m
        memory: 64Mi
      limits:
        memory: 128Mi
```

- [ ] **Step 7: reloader (`kubernetes/apps/kube-system/reloader/app/helmrelease.yaml` L34–39)**

`requests.memory: 64Mi` → `128Mi`, `limits.memory: 128Mi` → `256Mi`. Usage is 86Mi, so the old limit was within 1.5× of OOM.

- [ ] **Step 8: cilium operator (`kubernetes/apps/kube-system/cilium/app/helm/values.yaml`, `operator:` block at L73)**

Add under `operator:`:
```yaml
  resources:
    requests:
      cpu: 25m
      memory: 128Mi
    limits:
      memory: 256Mi
```
Check how this `values.yaml` is consumed (the HelmRelease `valuesFrom` ConfigMap or `bootstrap/helmfile`). If bootstrap also reads it, the change applies there too, which is intended.

- [ ] **Step 9: vector (`kubernetes/apps/monitoring/vector/app/helmrelease.yaml`)**

Add at `values:` level:
```yaml
    # bigboi's agent uses ~2.7Gi (it tails llama-swap's chatty logs);
    # bees use 187-277Mi. Request reflects the bees — bigboi keeps the
    # headroom of an unrequested node. Limit stops a runaway agent.
    resources:
      requests:
        cpu: 50m
        memory: 256Mi
      limits:
        memory: 3Gi
```

- [ ] **Step 10: Validate all touched apps**

```bash
cd /workspace/home-ops-mac-spec
for a in security/authentik ai/holyclaude monitoring/victoria-metrics monitoring/kube-prometheus-stack databases/cloudnative-pg network/cloudflare-dns network/unifi-dns system-upgrade/tuppr kube-system/reloader monitoring/vector; do echo "== $a"; kustomize build kubernetes/apps/$a/app | kubectl --kubeconfig /workspace/home-ops/kubeconfig apply --dry-run=server -f - 2>&1 | grep -iE 'error|invalid' ; done
```
Expected: no output after each `==` line. Then dispatch the `helmrelease-values-reviewer` agent on the touched HelmReleases to confirm each `resources:` key lands where the chart reads it.

- [ ] **Step 11: Commit**

```bash
git add -A kubernetes/apps
git commit -m "fix(resources): request real memory for workloads leaving bigboi

Phase 0c drains bigboi onto the bees; the scheduler can only pack them
safely if requests reflect reality. Survey (kubectl top, 2026-10-18):
authentik-server 679Mi used vs 256Mi requested, holyclaude 1419 vs 1088,
vmagent 407 vs 281, and kube-state-metrics, cloudnative-pg, external-dns
(x2), tuppr, cilium-operator and vector requested nothing. Requests are
~1.1-1.3x observed usage.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Raise kubelet `systemReserved` to cover etcd

**Files:**
- Modify: `talos/patches/global/machine-kubelet.yaml` (`systemReserved.memory`)

**Interfaces:**
- Consumes: nothing.
- Produces: bee allocatable reduced by etcd + Talos system services. etcd is a Talos service, not a pod, so its memory is invisible to the scheduler today.

- [ ] **Step 1: OPERATOR GATE: measure etcd + system service RSS**

No talosconfig exists in the worktree, so the operator runs:
```bash
talosctl -n 192.168.35.3,192.168.35.6,192.168.35.10 stats
talosctl -n 192.168.35.3,192.168.35.6,192.168.35.10 memory
```
Ask the operator to report the `etcd`, `apid`, `trustd`, `machined` and `containerd` memory rows per node.

- [ ] **Step 2: Compute the value**

`systemReserved.memory` = (largest per-node sum of etcd + apid + trustd + machined + containerd) × 1.25, rounded up to a multiple of 256Mi, with a floor of `1536Mi`. Record the measured numbers and the result in the ledger. The rest of this task writes `1536Mi`. If the computed value is larger, use that instead.

- [ ] **Step 3: Edit**

In `talos/patches/global/machine-kubelet.yaml`, set:
```yaml
          systemReserved:
            cpu: "200m"
            memory: "1536Mi"
            ephemeral-storage: "2Gi"
```

- [ ] **Step 4: Validate the render**

```bash
cd /workspace/home-ops-mac-spec/talos && talhelper validate talconfig talconfig.yaml && talhelper genconfig --dry-run 2>&1 | tail -3
```
Expected: valid. If `--dry-run` isn't supported by the installed talhelper, run `talhelper genconfig -o /tmp/talos-render` and `grep -A3 systemReserved /tmp/talos-render/*.yaml`. Expected: `memory: 1536Mi` in all 4 node configs.

- [ ] **Step 5: Commit**

```bash
git add talos/patches/global/machine-kubelet.yaml
git commit -m "fix(talos): reserve 1536Mi for system services incl. etcd

etcd and the Talos system services run outside the kubelet's pod
accounting, so the old 512Mi systemReserved let the scheduler commit
memory that etcd already holds. Measured RSS: <fill from Step 1 numbers
before committing>. Required before Phase 0c moves bigboi's workloads
onto the three control-plane bees.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Replace the `<fill …>` text with the measured numbers. Never commit the angle-bracket text.

- [ ] **Step 6: OPERATOR GATE: apply one node at a time (after PR1 merges)**

Kubelet config changes apply without a reboot, but they restart the kubelet. The order is bigboi first (worker, no quorum stake), then bee-01, bee-02, bee-03. Before each node, check that the previous one shows `Ready` and that `etcd-quorum-precheck` passes:
```bash
task talos:generate-config
task talos:apply-node IP=192.168.35.4 MODE=auto
kubectl get node bigboi-jms-01 -o jsonpath='{.status.allocatable.memory}{"\n"}'
```
Repeat with `IP=192.168.35.3`, `IP=192.168.35.6`, `IP=192.168.35.10` in turn, waiting for `kubectl get nodes` to show the node `Ready` before the next. Expected: each node's allocatable memory drops by ~1Gi.

---

### Task 4: Masquerade check + PV node-migration runbook + gatus rehearsal

**Files:**
- Create: `docs/runbooks/pv-node-migration.md`

**Interfaces:**
- Consumes: Task 1's verified Velero.
- Produces: the runbook Task 5 follows verbatim, with variables `NS`, `APP` (Deployment, HelmRelease and Kustomization name), `PVCS` (space-separated), `TARGET` (bee hostname).

- [ ] **Step 1: Cilium egress masquerade check (read-only)**

```bash
kubectl --kubeconfig /workspace/home-ops/kubeconfig -n kube-system exec ds/cilium -c cilium-agent -- cilium-dbg status --verbose 2>/dev/null | grep -iE 'masquerading|KubeProxyReplacement|Routing'
```
Expected: `Masquerading: BPF` with the native-routing CIDR `10.42.0.0/16` excluded. This confirms that pod→LAN egress leaves with the **node IP**, so the Mac's `pf` allowlist of node IPs `192.168.35.3/.4/.6/.10` (set in Phase 1) is the correct set. Gatus probes of `mac-jms-01` from in-cluster already succeed through that allowlist, which is behavioural confirmation. Record both in the ledger. If the output shows `Masquerading: Disabled` or iptables, stop and raise it with the operator: the pf allowlist would be wrong.

- [ ] **Step 2: Write the runbook**

Create `docs/runbooks/pv-node-migration.md` with this content:

````markdown
# Runbook: move an openebs-hostpath PVC to another node (Velero)

openebs-hostpath PVs are node-local. Moving one = back up the data with
Velero kopia FS backup, delete the PVC, restore it with the PVC's
selected-node remapped so WFFC provisioning lands on the target node.

Proven on services/gatus (2026-10). All mutating steps are operator-run.

## Variables

Set these once per migration, in the shell you run the steps from:

```bash
export NS=services APP=gatus PVCS="gatus" TARGET=bee-jms-03
export MIG="mig-${APP}-$(date +%Y%m%d%H%M)"
```

Only a throwaway holder pod is backed up and restored (never the app pod),
so app init containers, sidecars, memory emptyDirs and webhook-injected
volumes never enter the backup.

## 0. Preconditions

```bash
kubectl -n velero get backups.velero.io --sort-by=.metadata.creationTimestamp | tail -3
kubectl -n "$NS" get pvc $PVCS -o wide
```

The latest backup must be `Completed`, and every PVC `Bound`.

## 1. Freeze Flux for the app

```bash
flux -n "$NS" suspend kustomization "$APP"
flux -n "$NS" suspend helmrelease "$APP"
```

## 2. Label the PVCs to move

```bash
POD=$(kubectl -n "$NS" get pod -l app.kubernetes.io/name="$APP" -o jsonpath='{.items[0].metadata.name}')
kubectl -n "$NS" label pvc $PVCS migrate.home-ops.io/move=true --overwrite
```

## 3. Quiesce the app, then back up

Scale to zero so the data is consistent. Then run a backup pod that
holds the PVCs. That pod is not part of the scaled-down Deployment.

```bash
kubectl -n "$NS" scale deploy "$APP" --replicas=0
kubectl -n "$NS" wait --for=delete pod/"$POD" --timeout=180s
```

Create `/tmp/$MIG-holder.yaml`, listing every PVC in `$PVCS` under `volumes:` and `volumeMounts:`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: mig-holder
  labels:
    migrate.home-ops.io/move: "true"
  annotations:
    k8tz.io/inject: "false"
spec:
  restartPolicy: Never
  securityContext:
    runAsNonRoot: true
    runAsUser: 65534
    runAsGroup: 65534
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: hold
      image: busybox:1.37
      command: ["sleep", "86400"]
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: v0
          mountPath: /data/v0
  volumes:
    - name: v0
      persistentVolumeClaim:
        claimName: gatus
```

```bash
kubectl -n "$NS" apply -f /tmp/$MIG-holder.yaml
kubectl -n "$NS" wait --for=condition=Ready pod/mig-holder --timeout=180s
```

Create `/tmp/$MIG-backup.yaml`:

```yaml
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: REPLACE_MIG
  namespace: velero
spec:
  includedNamespaces: [REPLACE_NS]
  includedResources: [persistentvolumeclaims, pods]
  labelSelector:
    matchLabels:
      migrate.home-ops.io/move: "true"
  defaultVolumesToFsBackup: true
  snapshotVolumes: false
  ttl: 720h0m0s
```

```bash
sed -i "s/REPLACE_MIG/$MIG/; s/REPLACE_NS/$NS/" /tmp/$MIG-backup.yaml
kubectl apply -f /tmp/$MIG-backup.yaml
kubectl -n velero get backups.velero.io "$MIG" -w
kubectl -n velero get podvolumebackups.velero.io -l velero.io/backup-name="$MIG"
```

**Gate:** the Backup is `Completed`, and there is one `Completed`
PodVolumeBackup per PVC with a non-zero `.status.progress.totalBytes`
(an empty volume like a fresh gatus may show 0, which is acceptable).

## 4. Keep a fallback, then delete

Patch each old PV to Retain so the data survives the PVC delete:

```bash
for p in $PVCS; do kubectl patch pv "$(kubectl -n "$NS" get pvc "$p" -o jsonpath='{.spec.volumeName}')" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'; done
kubectl -n "$NS" delete pod mig-holder
kubectl -n "$NS" delete deploy "$APP"
kubectl -n "$NS" delete pvc $PVCS
```

Deleting the Deployment removes its ReplicaSet, so nothing can adopt or
kill the restored pod in step 5. The HelmRelease is suspended, so Helm
won't recreate it.

## 5. Restore onto the target node

Create `/tmp/$MIG-cm.yaml`. It holds the node remap that rewrites the
restored PVC's `volume.kubernetes.io/selected-node` annotation, plus a
resource modifier that turns the restored pod into a bare pod with no
pinning:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: change-pvc-node-selector-config
  namespace: velero
  labels:
    velero.io/plugin-config: ""
    velero.io/change-pvc-node-selector: RestoreItemAction
data:
  bigboi-jms-01: REPLACE_TARGET
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: mig-pod-modifier
  namespace: velero
data:
  modifier.yaml: |
    version: v1
    resourceModifierRules:
      - conditions:
          groupResource: pods
          namespaces: [REPLACE_NS]
        mergePatches:
          - patchData: |
              {"metadata":{"ownerReferences":null},"spec":{"nodeName":null,"nodeSelector":{"kubernetes.io/hostname":"REPLACE_TARGET"},"affinity":null}}
```

Create `/tmp/$MIG-restore.yaml`:

```yaml
apiVersion: velero.io/v1
kind: Restore
metadata:
  name: REPLACE_MIG
  namespace: velero
spec:
  backupName: REPLACE_MIG
  includedNamespaces: [REPLACE_NS]
  includedResources: [persistentvolumeclaims, pods]
  restorePVs: true
  existingResourcePolicy: none
  resourceModifier:
    kind: ConfigMap
    name: mig-pod-modifier
```

```bash
sed -i "s/REPLACE_TARGET/$TARGET/g; s/REPLACE_NS/$NS/g" /tmp/$MIG-cm.yaml
sed -i "s/REPLACE_MIG/$MIG/g; s/REPLACE_NS/$NS/g" /tmp/$MIG-restore.yaml
kubectl apply -f /tmp/$MIG-cm.yaml
kubectl apply -f /tmp/$MIG-restore.yaml
kubectl -n velero get restores.velero.io "$MIG" -w
kubectl -n velero get podvolumerestores.velero.io -l velero.io/restore-name="$MIG"
kubectl -n "$NS" get pvc $PVCS -o wide
kubectl get pv -o custom-columns=N:.metadata.name,CLAIM:.spec.claimRef.name,NODE:.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0] | grep -E "$(echo $PVCS | tr ' ' '|')"
```

**Gate:** the Restore is `Completed`, the PodVolumeRestores are
`Completed`, and the new PVs show `NODE` = `$TARGET`.

## 6. Hand back to Flux

```bash
kubectl -n "$NS" delete pod mig-holder
kubectl -n velero delete configmap change-pvc-node-selector-config mig-pod-modifier
kubectl -n "$NS" label pvc $PVCS migrate.home-ops.io/move-
flux -n "$NS" resume helmrelease "$APP"
flux -n "$NS" resume kustomization "$APP"
flux -n "$NS" reconcile helmrelease "$APP" --force
kubectl -n "$NS" get pod -l app.kubernetes.io/name="$APP" -o wide
```

**Gate:** the app pod is `Running` on `$TARGET` and the app's data is
present (app-specific check). Helm `--force` recreates the deleted
Deployment and adopts the restored PVCs, which keep their Helm labels
and annotations from the backup.

## 7. Clean up the fallback (after ≥ 7 days healthy)

```bash
kubectl get pv | grep Released
```

Delete each listed old PV by name once the app has been healthy on the
new node for a week. The openebs hostpath directory on the source node is removed
when the PV is deleted only if the reclaim policy is Delete, so set it
back first:
`kubectl patch pv <name> -p '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}'`.

## Rollback (any step before 6)

The old PV is Retained:

1. Remove its `spec.claimRef` (`kubectl patch pv <old> --type json -p '[{"op":"remove","path":"/spec/claimRef"}]'`).
2. Recreate the PVC with `spec.volumeName: <old>`.
3. Resume Flux.
````

Note on the holder pod: it has no `nodeName`/selector, because the old PV's node affinity places it on the source node. On restore, the resource modifier strips its `ownerReferences`/affinity and sets `nodeSelector` = target, while the change-pvc-node-selector ConfigMap points the restored PVC's WFFC selected-node at the same target. kopia's node-agent writes through the kubelet pod dir as root, so the holder's non-root UID doesn't affect the restore. Confirm in the gatus rehearsal that `k8tz.io/inject: "false"` is the correct opt-out annotation for the deployed k8tz (`kubectl -n kube-system get deploy -l app.kubernetes.io/name=k8tz -o yaml | grep -i inject`), and fix the runbook if not.

- [ ] **Step 3: Self-check the runbook against Velero 1.18 docs**

Fetch and confirm three things:

- `change-pvc-node-selector` ConfigMap labels: https://velero.io/docs/v1.18/restore-reference/#changing-pvc-selected-node
- `mergePatches` support in resource modifiers: https://velero.io/docs/v1.18/restore-resource-modifiers/
- that `includedResources` + `labelSelector` on a Backup still triggers FS backup of the selected pods' volumes.

Fix the runbook inline if any detail differs, and note it in the ledger.

- [ ] **Step 4: Commit**

```bash
git add docs/runbooks/pv-node-migration.md
git commit -m "docs(runbooks): Velero-based openebs-hostpath PVC node migration

openebs-hostpath PVs are node-local, so Phase 0c needs a repeatable way
to move holyclaude/omniroute/gatus off bigboi. Uses a holder pod (no app
init containers/webhooks), a labelled backup, Retain on the old PV as a
fallback, Velero's change-pvc-node-selector remap and a merge-patch
resource modifier that strips ownerReferences/nodeName so the restored
pod isn't GC'd before kopia writes the data.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Open PR1 (Tasks 1–4), after asking the operator**

```bash
cd /workspace/home-ops-mac-spec && git push -u origin HEAD
env -u GITHUB_TOKEN gh pr create --title "Phase 0c PR1: Velero OOM fix, requests, systemReserved, PV-migration runbook" --body-file /tmp/pr1-body.md
```
Write `/tmp/pr1-body.md` first. It should summarize the Velero outage, the requests table, the systemReserved rationale, and the runbook, and end with the Generated-with line.

- [ ] **Step 6: OPERATOR GATE: gatus rehearsal (after PR1 merged, Task 1 Step 7 passed)**

The operator follows `docs/runbooks/pv-node-migration.md` with:
```bash
export NS=services APP=gatus PVCS="gatus" TARGET=bee-jms-01
export MIG="mig-${APP}-$(date +%Y%m%d%H%M)"
```
bee-jms-01 has the most free disk and the lowest requests. Pass criteria:

- every runbook gate passes;
- the gatus pod runs on bee-jms-01;
- `https://status.68cc.io` (or the gatus HTTPRoute host) shows history from before the move. Fresh start is acceptable per spec, but record which outcome occurred.

Fold every deviation into the runbook (amend commit or follow-up commit) **before** Task 5.

---

### Task 5: Migrate holyclaude and omniroute to bee-03

**Files:**
- Modify: `kubernetes/apps/ai/holyclaude/app/helmrelease.yaml:20-42` (affinity + comment)

**Interfaces:**
- Consumes: the rehearsed runbook from Task 4.
- Produces: no PVC in `ai` (other than llama-swap/ollama/orphans) bound to a bigboi PV. Task 6's taint depends on this.

- [ ] **Step 1: Repoint holyclaude affinity (PR1b, merge BEFORE its migration)**

Replace lines 20–42 (the comment + `affinity:` block under `defaultPodOptions:`) with:
```yaml
    defaultPodOptions:
      # 50Gi openebs-hostpath PVC (node-local, RWO). The PV's node affinity
      # is what actually pins the pod; this preference only steers the
      # first scheduling decision if the PVC is ever recreated. Moved off
      # bigboi-jms-01 to bee-jms-03 in Phase 0c (spec D11) via
      # docs/runbooks/pv-node-migration.md -- bigboi is being emptied for
      # retirement. Recreating this PVC destroys /workspace and every
      # persisted subtree (~/.claude incl. the `claude login` OAuth
      # session, ~/.cloudcli); use the runbook, never delete it.
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              preference:
                matchExpressions:
                  - key: kubernetes.io/hostname
                    operator: In
                    values: ["bee-jms-03"]
```
Validate with `kustomize build kubernetes/apps/ai/holyclaude/app | grep -A8 'affinity:'`. Commit:
```bash
git add kubernetes/apps/ai/holyclaude/app/helmrelease.yaml
git commit -m "fix(holyclaude): prefer bee-jms-03 instead of requiring bigboi

The required bigboi affinity would leave the pod Pending once its PVC is
migrated to bee-jms-03 (Phase 0c, spec D11). The PV's own node affinity
pins the pod; this preference only guides a future fresh PVC.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
After merge, the holyclaude pod is still on bigboi, because a preferred affinity doesn't evict and the PV still pins it there. That is expected.

- [ ] **Step 2: OPERATOR GATE: migrate holyclaude**

The operator follows the runbook with:
```bash
export NS=ai APP=holyclaude PVCS="holyclaude" TARGET=bee-jms-03
export MIG="mig-${APP}-$(date +%Y%m%d%H%M)"
```
Before step 3, capture `kubectl -n ai exec deploy/holyclaude -c app -- ls -la /workspace > /tmp/holyclaude-before.txt`. The 50Gi volume may take a while to back up. Watch `kubectl -n velero get podvolumebackups.velero.io -l velero.io/backup-name="$MIG" -w`. Before starting, the operator should end any active holyclaude session.

App check after step 6 of the runbook:

- the web terminal opens;
- `ls /workspace` matches the pre-move listing (capture it before step 3);
- `claude` is still logged in.

- [ ] **Step 3: OPERATOR GATE: migrate omniroute**

The operator follows the runbook with:
```bash
export NS=ai APP=omniroute PVCS="omniroute-data omniroute-cliproxyapi-data" TARGET=bee-jms-03
export MIG="mig-${APP}-$(date +%Y%m%d%H%M)"
```
The holder pod lists both PVCs (`v0` = omniroute-data, `v1` = omniroute-cliproxyapi-data). App check: the Omniroute dashboard loads with existing providers and combos, and the Home Assistant conversation agent answers one prompt.

- [ ] **Step 4: Verify nothing PV-pinned remains on bigboi except the expected set**

```bash
kubectl --kubeconfig /workspace/home-ops/kubeconfig get pv -o json | python3 -I -c 'import json,sys; [print(p["spec"]["claimRef"]["namespace"]+"/"+p["spec"]["claimRef"]["name"]) for p in json.load(sys.stdin)["items"] if "bigboi-jms-01" in json.dumps(p["spec"].get("nodeAffinity",{})) and p["status"]["phase"]=="Bound"]'
```
Expected: exactly this set, and nothing else:

- `ai/llama-swap` (Phase 3)
- `ai/ollama`, `ai/data-agent-canvas-0`, `ai/claude-code-workspace` (orphans, Task 8)
- `monitoring/data-trivy-server-0` (recreated in Task 6)
- `monitoring/netdata-k8s-state-varlib` (deleted with netdata in Task 6)

Any other entry blocks Task 6.

---

### Task 6: Tolerations, netdata removal, bigboi taint

**Files:** see File Map rows for Task 6.

**Interfaces:**
- Consumes: Task 5 Step 4's clean PV list.
- Produces: taint `home-ops.io/dedicated=ai:NoSchedule` on bigboi-jms-01. Every bigboi-staying workload tolerates it with this exact block:
```yaml
- key: home-ops.io/dedicated
  operator: Equal
  value: ai
  effect: NoSchedule
```

- [ ] **Step 1: DeviceConfig tolerations (`kubernetes/apps/kube-system/amd-gpu/app/deviceconfig.yaml`, `dgpu` object only)**

Confirm the field names first:
```bash
kubectl --kubeconfig /workspace/home-ops/kubeconfig explain deviceconfig.spec.devicePlugin --api-version=amd.com/v1alpha1 | grep -i toleration
kubectl --kubeconfig /workspace/home-ops/kubeconfig explain deviceconfig.spec.metricsExporter --api-version=amd.com/v1alpha1 | grep -i toleration
```
Then add `devicePluginTolerations:` and `nodeLabellerTolerations:` under `spec.devicePlugin`, and `tolerations:` under `spec.metricsExporter`, each holding the toleration block from Interfaces. The `apu-light` DeviceConfig targets bees, so leave it alone.

- [ ] **Step 2: NFD worker (`kubernetes/apps/kube-system/amd-gpu/app/helmrelease.yaml`)**

Confirm with `helm show values` for the chart named in that HR that `node-feature-discovery.worker.tolerations` exists. Then add the block there. If the HR already sets worker tolerations, append to them instead.

- [ ] **Step 3: drm-exporter, irqbalance, llama-swap (app-template)**

In each HR's `values.defaultPodOptions` (create the key if absent; llama-swap has it at ~L243), add:
```yaml
      tolerations:
        - key: home-ops.io/dedicated
          operator: Equal
          value: ai
          effect: NoSchedule
```
Files: `kubernetes/apps/monitoring/drm-exporter/app/helmrelease.yaml`, `kubernetes/apps/kube-system/irqbalance/app/helmrelease.yaml`, `kubernetes/apps/ai/llama-swap/app/helmrelease.yaml`.

- [ ] **Step 4: vector + velero node-agent**

In `kubernetes/apps/monitoring/vector/app/helmrelease.yaml` add a top-level `tolerations:` under `values:` with the block. In `kubernetes/apps/velero/app/helmrelease.yaml`, append the block to the existing `nodeAgent.tolerations` list (after the control-plane entry, ~L137–140).

- [ ] **Step 5: Remove netdata**

```bash
cd /workspace/home-ops-mac-spec
git rm -r kubernetes/apps/monitoring/netdata
git rm kubernetes/flux/meta/repos/netdata.yaml
```
Then delete the line `- ./netdata/ks.yaml` from `kubernetes/apps/monitoring/kustomization.yaml` and `- ./netdata.yaml` from `kubernetes/flux/meta/repos/kustomization.yaml`. Delete the netdata binary exemptions at lines 31–37 of `kubernetes/apps/kube-system/tetragon/app/tracingpolicy-container-escape.yaml`; read the block first and remove only the netdata entries so the YAML list stays valid. Finally confirm nothing references it:
```bash
grep -rn -i netdata kubernetes/ talos/ .github/ .renovate/ | grep -v '^docs/'
```
Expected: no output. README and docs mentions are handled in Task 8.

The netdata Kustomization has `prune: true`, so Flux deletes the HR, workloads and the `netdata-k8s-state-varlib`/parent PVCs. That was confirmed in the survey; the Helm-created PVCs go with the release uninstall. If any `netdata-*` PVC survives, Task 8 Step 2 deletes it.

- [ ] **Step 6: Taint bigboi in talconfig**

In `talos/talconfig.yaml`, inside the `bigboi-jms-01` node entry (after its `nodeLabels:` map), add:
```yaml
    # Phase 0c: bigboi is AI/GPU-only until retirement. The descheduler's
    # RemovePodsViolatingNodeTaints evicts everything else onto the bees;
    # bigboi-staying DaemonSets/llama-swap carry a matching toleration.
    nodeTaints:
      home-ops.io/dedicated: "ai:NoSchedule"
```
Validate with `cd talos && talhelper validate talconfig talconfig.yaml && talhelper genconfig -o /tmp/talos-render && grep -A3 nodeTaints /tmp/talos-render/*bigboi*.yaml`. Expected: the taint is present only in the bigboi config.

- [ ] **Step 7: Validate manifests**

```bash
for a in kube-system/amd-gpu monitoring/drm-exporter kube-system/irqbalance ai/llama-swap monitoring/vector velero kube-system/tetragon; do echo "== $a"; kustomize build kubernetes/apps/$a/app | kubectl --kubeconfig /workspace/home-ops/kubeconfig apply --dry-run=server -f - 2>&1 | grep -iE 'error|invalid'; done
kustomize build kubernetes/apps/monitoring | grep -c netdata
kustomize build kubernetes/apps/monitoring/vector/app kubernetes/apps/ai/llama-swap/app 2>/dev/null | grep -c 'home-ops.io/dedicated'
```
Expected: no errors; `0` netdata hits; a non-zero toleration count. Run the `kubeconform-validator` and `flux-manifest-reviewer` agents on the diff.

- [ ] **Step 8: Commit + PR2 (ask before push)**

```bash
git add -A kubernetes talos
git commit -m "feat(bigboi): taint AI-only, tolerate GPU/node DaemonSets, drop netdata

Phase 0c empties bigboi of non-AI workloads ahead of its retirement.
A NoSchedule taint (home-ops.io/dedicated=ai) lets the existing
descheduler RemovePodsViolatingNodeTaints strategy drain it; the GPU
stack, llama-swap and per-node agents (vector, velero node-agent,
irqbalance, drm-exporter, NFD) tolerate it so bigboi keeps coverage
until Phase 3. PV-pinned apps were migrated first (pv-node-migration
runbook) so nothing strands Pending. netdata duplicates
node-exporter/VictoriaMetrics coverage and is removed per spec.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 9: OPERATOR GATE: apply the taint (after PR2 merges and Flux shows tolerations live)**

First confirm the tolerations are live:
```bash
kubectl -n kube-system get ds -o custom-columns=N:.metadata.name,T:.spec.template.spec.tolerations[*].key | grep -E 'irqbalance|amd|nfd|node-feature'
kubectl -n monitoring get ds vector -o jsonpath='{.spec.template.spec.tolerations[*].key}{"\n"}'
```
Then apply:
```bash
task talos:generate-config
task talos:apply-node IP=192.168.35.4 MODE=auto
kubectl get node bigboi-jms-01 -o jsonpath='{.spec.taints}{"\n"}'
```
Expected: the taint is listed. Within ~10 minutes (two descheduler cycles) non-tolerating pods move:
```bash
kubectl get pods -A -o wide --field-selector spec.nodeName=bigboi-jms-01
```
Expected remaining set: llama-swap, amd-gpu device-plugin/node-labeller/metrics-exporter, NFD worker, cilium, cilium-envoy, spegel, tetragon, node-exporter, vector, velero node-agent, irqbalance, drm-exporter, crowdsec-agent (if it tolerates all), traefik-external/internal (DaemonSets until Task 7), and trivy-server-0 (PV-pinned, next step). Also check that nothing is stuck Pending: `kubectl get pods -A --field-selector status.phase=Pending`.

- [ ] **Step 10: OPERATOR GATE: recreate trivy-server**

```bash
kubectl -n monitoring delete pvc data-trivy-server-0 --wait=false
kubectl -n monitoring delete pod trivy-server-0
kubectl -n monitoring get pod trivy-server-0 -o wide -w
```
Expected: it reschedules on a bee with a fresh PVC. The vulnerability DB re-downloads, which is acceptable per spec ("recreate").

- [ ] **Step 11: Requested-memory check against spec target**

```bash
kubectl --kubeconfig /workspace/home-ops/kubeconfig describe nodes bee-jms-01 bee-jms-02 bee-jms-03 | grep -A3 'Allocated resources' | grep memory
```
Record the per-bee numbers in the ledger. Spec target: ~40 of 103GiB requested across bees. Flag if any bee is above 70% requested.

---

### Task 7: Traefik DaemonSets → 2-replica Deployments

**Files:**
- Modify: `kubernetes/apps/network/traefik-external/app/helmrelease.yaml` (L14–18 comment/timeout, L120 comment, L146–163 `deployment:`, L195 eTP)
- Modify: `kubernetes/apps/network/traefik-internal/app/helmrelease.yaml` (L23 timeout, L133–148 `deployment:`, L177 eTP)

**Interfaces:**
- Consumes: Task 6 (bigboi tainted, so the Deployments land on bees).
- Produces: 2 pods per Traefik instance on distinct bees, LB VIPs `.15`/`.17` unchanged.

- [ ] **Step 1: Confirm chart keys**

```bash
helm show values oci://ghcr.io/traefik/helm/traefik --version 41.6.1 | grep -n -E '^  (kind|replicas|podDisruptionBudget|updateStrategy):|^topologySpreadConstraints:|^podDisruptionBudget:'
```
Look up the actual OCI URL in `kubernetes/apps/network/traefik-external/app/ocirepository.yaml`. Record where `podDisruptionBudget` and `topologySpreadConstraints` live (top-level vs under `deployment:`) and use those exact paths below.

- [ ] **Step 2: traefik-external edits**

Replace the `deployment:` block's first lines and the updateStrategy comment so it reads:
```yaml
    deployment:
      kind: Deployment
      replicas: 2
      revisionHistoryLimit: 3
      # Explicitly scoped to traefik-secrets (SOPS, holds the CrowdSec
      # bouncer key) rather than a blanket /auto — issue #493. Excludes
      # the botwrangler-robots-template ConfigMap, which doesn't need a
      # pod restart to take effect.
      podAnnotations:
        secret.reloader.stakater.com/reload: traefik-secrets
      # Surge one new pod before removing an old one: with 2 replicas and
      # the PDB below, a rollout never drops below one ready Traefik.
      updateStrategy:
        type: RollingUpdate
        rollingUpdate:
          maxUnavailable: 0
          maxSurge: 1
```
Add (at the path confirmed in Step 1, top-level in chart 41):
```yaml
    podDisruptionBudget:
      enabled: true
      minAvailable: 1
    topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app.kubernetes.io/instance: traefik-external-network
```
Confirm the instance label value with `kubectl -n network get pod -l app.kubernetes.io/name=traefik --show-labels | head -3`, and use the real `app.kubernetes.io/instance` value.

Change the service spec to:
```yaml
      spec:
        # Cluster, not Local: Cilium L2 announcements are incompatible with
        # externalTrafficPolicy: Local (the announcing node may have no
        # backend -> drops). Client source IP is still preserved because
        # Cilium runs loadBalancer.mode: dsr.
        externalTrafficPolicy: Cluster
```
Update the L14–18 comment so it describes a 2-replica Deployment rollout instead of the 4-node DaemonSet; keep `timeout: 5m`. Update the L120 rate-limit comment from `* 3 replicas = ~300 req/s` to `* 2 replicas = ~200 req/s`.

- [ ] **Step 3: traefik-internal edits**

Make the same changes with these differences: the existing reloader comment stays, the instance label is `traefik-internal-…` (confirm the same way), and the L23 `timeout: 2m` stays.

- [ ] **Step 4: Validate**

```bash
for a in traefik-external traefik-internal; do kustomize build kubernetes/apps/network/$a/app | kubectl --kubeconfig /workspace/home-ops/kubeconfig apply --dry-run=server -f - 2>&1 | grep -iE 'error|invalid'; kustomize build kubernetes/apps/network/$a/app | grep -nE 'kind: Deployment|replicas:|externalTrafficPolicy|reloader.stakater'; done
```
Expected: no errors; `kind: Deployment`, `replicas: 2`, `externalTrafficPolicy: Cluster`, and the reloader annotation in each.

- [ ] **Step 5: Commit + PR3 (ask before push; merge in a quiet window)**

```bash
git add kubernetes/apps/network/traefik-external kubernetes/apps/network/traefik-internal
git commit -m "feat(traefik): run both instances as 2-replica Deployments

Spec Phase 0 dedupe: a 4-node DaemonSet per instance was sized for
bigboi + 3 bees; bigboi is now AI-only. Switch externalTrafficPolicy to
Cluster because Cilium L2 announcements are incompatible with Local
(the lease holder may have no backend pod); loadBalancer.mode dsr keeps
client source IPs for PROXY protocol/CrowdSec. PDB minAvailable 1 and
hostname topology spread keep one pod up through rollouts and drains.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Helm switches the workload kind by deleting the DaemonSet and creating the Deployment, which can leave a gap of a few seconds. Tell the operator before merge.

- [ ] **Step 6: OPERATOR GATE: post-merge verification**

```bash
kubectl -n network get deploy,ds,pdb | grep traefik
kubectl -n network get pod -l app.kubernetes.io/name=traefik -o wide
curl -sS -o /dev/null -w '%{http_code}\n' https://grafana.68cc.io
curl -sS -o /dev/null -w '%{http_code}\n' https://status.68cc.io
kubectl -n network logs deploy/traefik-internal --since=5m | tail -5
kubectl -n network logs deploy/traefik-external --since=5m | tail -5
```
Expected:

- no traefik DaemonSet remains; 2 Deployments with 2/2 ready on different bees;
- the curls return 200/302;
- access-log `ClientHost` shows real LAN client IPs (e.g. the operator's workstation) and Cloudflare-forwarded requests carry `CF-Connecting-IP`. A node IP (`192.168.35.3/.6/.10`) as ClientHost for LAN requests means DSR is not preserving source; then roll back by reverting the commit.

CrowdSec check: `kubectl -n security logs deploy/crowdsec-lapi --since=10m | tail` shows no surge of decisions against node IPs.

---

### Task 8: Orphan PVs + doc cleanup

**Files:**
- Modify: `README.md` (L132, L160, L247), `docs/runbooks/actions-runner-controller.md` (L48, L183)

- [ ] **Step 1: OPERATOR GATE: confirm orphan deletion**

Present this table and ask for an explicit yes per row (spec: "after operator confirmation"):

| PVC | Size | Node | Consumer |
|---|---|---|---|
| ai/ollama | 50Gi | bigboi (fast) | none |
| ai/data-agent-canvas-0 | 20Gi | bigboi | none |
| ai/claude-code-workspace | 20Gi | bigboi | none |

Also present, as **report-only** (outside spec scope, no action unless the operator asks), the other unused PVCs from the survey:

- ai: anythingllm, claude-code-claude-home, memini, omega-mcp, open-webui, valkey-data-langfuse-redis-primary-0
- databases: clickhouse ×5, qdrant-storage-qdrant-0
- monitoring: server-volume-victoria-logs-server-0, vmsingle-vmsingle
- services: llama-swap, open-webui

- [ ] **Step 2: OPERATOR GATE: delete confirmed orphans + leftover netdata PVCs**

For each confirmed row, plus any `netdata-*` PVC still present:
```bash
kubectl -n ai delete pvc ollama data-agent-canvas-0 claude-code-workspace
kubectl -n monitoring get pvc | grep netdata
kubectl get pv | grep -E 'Released|Failed'
```
Only include confirmed names in the first command. Released PVs with reclaim `Delete` are removed by openebs; report any that linger.

- [ ] **Step 3: Docs**

Make these edits:

- `README.md:160`: remove the netdata line.
- `README.md:132` and `README.md:247`: change the `openebs-hostpath-fast` mentions to say it is used only by `ai/llama-swap` until Phase 3 cutover.
- `docs/runbooks/actions-runner-controller.md:48` and `:183`: drop the claim that the runner uses `openebs-hostpath-fast`. The runner deployment sets no storage class.

Read each line first and edit the minimum.

- [ ] **Step 4: Commit + PR4 (ask before push)**

```bash
git add README.md docs/runbooks/actions-runner-controller.md
git commit -m "docs: drop netdata, correct openebs-hostpath-fast usage

netdata was removed in Phase 0c and the actions runner no longer uses
the fast storage class; only ai/llama-swap does, until Phase 3.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Close out**

Update the memory file `mac_studio_migration_decisions.md`: Phase 0c done, Velero fix landed, taint key `home-ops.io/dedicated=ai:NoSchedule`, holyclaude/omniroute on bee-03. Remind the operator that the deferred Phase 1 Task 10 checks are next.
