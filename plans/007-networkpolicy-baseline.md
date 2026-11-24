# Plan 007: NetworkPolicy baseline for the four highest-exposure service apps

> **Executor instructions**: Follow this plan step by step. Each app in
> batch 1 is a separate step with its own verification; land them one at a
> time so a breakage is isolated to one app. If anything in the "STOP
> conditions" section occurs, stop and report — do not improvise. When done,
> update the status row for this plan in `plans/README.md`.
>
> **Prerequisite**: Flux sync + `kubectl` access to the cluster (the
> README §Talos/Flux tooling; the Mac Studio or a runner with
> `KUBECONFIG`). Without it, STOP — the done criteria require live
> verification.
>
> **Drift check (run first)**: `git diff --stat 8b27891f..HEAD -- kubernetes/apps/services/ kubernetes/apps/databases/dragonflydb/instance/instance.yaml`
> Compare the exemplar excerpt against the live file; on a mismatch, STOP.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MEDIUM — a wrong policy breaks real traffic (e.g. Mosquitto
  clients, Home Assistant integrations, the n8n webhook path)
- **Depends on**: none
- **Category**: security (posture)
- **Planned at**: commit `8b27891f`, 2026-11-24

## Why this matters

Cluster-wide, only 4 of ~60 apps define a `NetworkPolicy` (argus, dragonflydb,
cloudflared, traefik-internal). Everything else — including Mosquitto (broker
port 1883), Home Assistant, n8n (webhook receiver) and Atuin — is reachable
from every pod in every namespace. That is normal for a single-user home
cluster (hence P3), but the exemplars show the repo already has a clean,
convention-based pattern for the common case, and batch 1 is four apps
whose ingress surface is small and knowable. This plan extends the pattern to
those four and establishes a "who may talk to what" baseline without
pretending to cover the whole cluster.

## Current state

- **The exemplar** — `kubernetes/apps/databases/dragonflydb/instance/instance.yaml`
  (kustomized under the app's `kustomization.yaml`). It defines an ingress
  `NetworkPolicy` (locate the `kind: NetworkPolicy` block; the shape, at
  `8b27891f`):

  ```yaml
  kind: NetworkPolicy
  metadata:
    name: dragonflydb
  spec:
    podSelector:
      matchLabels:
        app.kubernetes.io/name: dragonflydb
    policyTypes:
      - Ingress
    ingress:
      - from:
          - podSelector:
              matchLabels:
                app.kubernetes.io/name: <consumer>
        ports:
          - protocol: TCP
            port: <port>
  ```

  One `from` entry per consumer, explicit ports, and a short comment per
  policy explaining *why* it exists. Copy this shape and its commenting style.
- **Second exemplar** — `kubernetes/apps/argus/` contains a NetworkPolicy
  covering the Traefik→argus ingress path. Read it before touching n8n
  (n8n's webhook traffic enters through Traefik, so argus's policy is the
  closest analogue).
- Batch 1 targets (all in `kubernetes/apps/services/`):
  - `mosquitto/` — MQTT broker; ingress 1883 TCP.
  - `n8n/` — workflow engine; ingress 5678 TCP.
  - `atuin/` — shell-history backend; its API port (check
    `atuin/app/helmrelease.yaml` values for the service port).
  - `home-assistant/` — ingress 8123 TCP.
- The 4 existing policy owners (argus, dragonflydb, cloudflared,
  traefik-internal) are **out of scope** — do not edit them.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Flux sync status | `flux get sources/kustomizations -A` (or the repo's `task` equivalent) | all synced, no Degraded |
| Policies exist | `kubectl get networkpolicy -n <ns>` | new policy listed per app |
| Pods healthy | `kubectl get pods -n <ns>` | all Running/Ready, no CrashLoop |
| Status dashboard | check Gatus (its UI or `kubectl logs` for failing checks) | no new red checks |
| Tunnel probe | `curl -sS -o /dev/null -w '%{http_code}' http://<app>.<ns>.svc...` — see per-app probes | expected code, not `000`/timeout |

Note on in-cluster probes: run `kubectl run tmp-curl --rm -it --image=curlimages/curl:latest -- curl -sS -o /dev/null -w '%{http_code}' http://<svc>:<port>/` **from a pod in a namespace that should have access**, and the same probe from a pod in an unrelated namespace (e.g. `ai`) to confirm the policy denies where intended. Delete `tmp-curl` after (it's `--rm`).

## Scope

**In scope** (create `instance.yaml` or add the policy to the existing
instance file, per each app's existing kustomization layout — match what the
app already does):
- `kubernetes/apps/services/mosquitto/instance/` (new or existing instance
  dir — check `mosquitto/kustomization.yaml` first)
- `kubernetes/apps/services/n8n/instance/`
- `kubernetes/apps/services/atuin/instance/`
- `kubernetes/apps/services/home-assistant/instance/`

**Out of scope**:
- The four existing NetworkPolicy owners.
- Egress policies anywhere (ingress-only in this batch; egress is a later,
  cluster-wide decision).
- Any app not in the batch list.

## Git workflow

- Branch: `advisor/007-np-baseline`
- **One commit per app**, each verified before the next:
  `security(services): restrict mosquitto ingress to consumers` (and so on)
- Do NOT push or open a PR unless instructed.

## Steps

### Step 0: Baseline survey (no changes)

For each of the four apps:
1. Read `kustomization.yaml` and the app's `helmrelease.yaml` — record the
   service name, namespace, and the exact ingress port(s) (from the chart
   values; e.g. Atuin's port is whatever its values set, not assumed).
2. `kubectl get pods -n <ns> -o wide` + `kubectl describe` a representative
   workload to record the pod labels — the policy's `podSelector` **must
   match the actual labels** (`app.kubernetes.io/name` is the exemplar
   convention, but verify each app's labels; Helm charts differ).
3. Identify the consumers: which namespaces/apps currently talk to the
   service. Sources of truth: Traefik routing (ingress resources /
   k8s-sink in the config namespace), Gatus check endpoints, and
   `kubectl get pods -A` + app knowledge. When unsure of a consumer,
   include it and note the uncertainty in the policy comment — a too-wide
   policy is safe, a too-narrow one breaks things.

**Verify**: for each app you can state (service, port, pod labels, consumer
list) before writing a line. If any app's pod labels don't use the
`app.kubernetes.io/*` convention, that's fine — match its actual labels,
and note it in the policy comment.

### Steps 1–4: One app per step (mosquitto → n8n → atuin → home-assistant)

For each app:

1. Write an ingress-only `NetworkPolicy` in the app's instance kustomization,
   following the dragonflydb exemplar: `podSelector` from step 0, one `from`
   entry per consumer (namespace + pod labels), explicit port(s), a leading
   comment stating who and why.
2. Commit this app only.
3. Sync Flux and verify:
   - `flux` sync complete (no Degraded kustomization for the app);
   - `kubectl get networkpolicy -n <ns>` shows the new policy;
   - `kubectl get pods -n <ns>` — all Running/Ready after a rollout
     (policies don't restart pods, but confirm no other drift);
   - in-cluster curl from an **allowed** consumer's namespace → expected
     response (200/2xx or, for MQTT, TCP connect success — use
     `curl telnet://<svc>:<port>` or just check a known client reconnects);
   - in-cluster curl from an **unrelated** namespace (e.g. `ai`) →
     connection refused/timeout (denial confirmed);
   - Gatus: no new red checks.
4. If anything is red or a known client is broken: `git revert` this app's
   commit, re-sync, confirm green, STOP and report.

**Verify** (final, after step 4): all four policies present
(`kubectl get networkpolicy -n services`), all pods in the four apps
Ready, Gatus green.

## Test plan

- The dual in-cluster probes (allowed vs unrelated namespace) per app are
  the tests — they prove both that intended traffic survives and that the
  policy actually restricts something.
- Gatus covers the end-user surface (these four services have checks where
  present; where a service lacks a Gatus check, the curl probe stands in —
  note which).
- No unit-test framework applies to Kubernetes manifests here.

## Done criteria

- [ ] Step-0 survey table (service/port/labels/consumers) present in the report for all four apps
- [ ] Four ingress-only NetworkPolicies committed, one per app, matching the dragonflydb exemplar's shape and comment style
- [ ] Per-app: allowed-namespace probe succeeds, unrelated-namespace probe is denied
- [ ] All four apps' pods Running/Ready; Gatus green
- [ ] `git diff --name-only` covers only the four apps' instance files
- [ ] `plans/README.md` status row updated

## STOP conditions

- Flux can't sync (no cluster access, or a pre-existing Degraded state that
  isn't yours — report it, don't fix it here).
- An app's consumer list cannot be determined with confidence from the
  sources of truth — either include all plausible consumers with a comment,
  or stop and report; do not guess silently.
- Any per-app verification shows a real client broke (Mosquitto device,
  HA integration, n8n webhook) that the survey missed — revert and report
  the missed consumer.
- A policy's `podSelector` matches **multiple** apps' pods (label
  collision) — stop and fix the selector, since you'd be restricting other
  apps' pods unintentionally.

## Maintenance notes

- When a new app needs access to a batch-1 service, add its `from` entry to
  that policy — this is the intended workflow, and the policy comment makes
  the consumer list explicit.
- The denial probe (unrelated namespace) can be folded into a Gatus-style
  recurring check later; not included here.
- Egress policies, and extending coverage beyond batch 1, are follow-up
  decisions — batch 1 is deliberately small because MEDIUM-risk traffic
  changes deserve per-app isolation.
