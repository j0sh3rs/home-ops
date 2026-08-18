# HolmesGPT Auto-Diagnose + Remediation Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix HolmesGPT's broken LLM routing, widen its diagnosis toolsets, harden its API, and consolidate it onto `argus` (an existing open-source Helm chart) so alerts flow Alertmanager → HolmesGPT investigation → Discord with human-approval buttons, with gated write access (transient kubectl remediation + durable git-committed fixes) behind that same approval.

**Architecture:** `argus`'s umbrella chart bundles the official `holmes` chart as an unconditional subchart dependency (no `condition:` flag exists to disable it) — this **changes the spec's assumption** that HolmesGPT's existing standalone deployment would be reused as-is. Instead, all of HolmesGPT's toolset/model/hardening config gets consolidated into `argus`'s HelmRelease (`holmes:` values override block), and the standalone `kubernetes/apps/ai/holmesgpt/` app is retired once `argus` is live and verified — one Holmes instance, not two. Both the Kubernetes Remediation toolset and the GitHub toolset ship as `mcpAddons` (self-hosted sidecar containers with chart-generated RBAC/NetworkPolicy), not `toolsets:` config keys — confirmed directly against the pinned chart's `values.yaml` (`helm show values robusta/holmes --version 0.39.0`), not assumed from docs prose.

**Tech Stack:** FluxCD (`HelmRelease`, `GitRepository`, `Kustomization`, `AlertmanagerConfig`), SOPS/age secrets, `kustomize`/`flux build`/`task sops:verify` for validation, `bd` for task tracking.

**Spec:** `docs/superpowers/specs/2026-08-18-holmesgpt-auto-remediation-design.md`

## Global Constraints

- **`toolsets:` vs `mcpAddons:`** — plain data-source toolsets (`prometheus/metrics`, `victorialogs`, `grafana/dashboards`, `postgres17-stats`, `cilium/core`, `hubble/observability`, `helm/core`) are entries under `values.toolsets`, an open map the chart passes straight through — Holmes accepts any toolset name it itself supports, whether or not the chart's default `values.yaml` lists it. Kubernetes Remediation and GitHub are **not** toolset entries — they're `values.mcpAddons.kubernetesRemediation` and `values.mcpAddons.github`, each a separate sidecar container with its own image, its own auto-created ServiceAccount/ClusterRole, and its own `networkPolicy.enabled` toggle. Do not conflate the two mechanisms.
- **`mcpAddons.kubernetesRemediation` already defaults to approval-gated**: `approvalRequiredTools: ["run_kubectl_command"]` is the chart default. Do not touch this list — leaving it as-is is the entire point.
- **`mcpAddons.kubernetesRemediation.serviceAccount.clusterRole: ""`** means the chart generates its own least-privilege ClusterRole — do not author a hand-rolled ClusterRole for this; only override if the generated one is verified insufficient.
- **`HOLMES_API_KEY`** is a real Holmes server env var (confirmed via holmesgpt.dev docs: enforces auth on every endpoint except `/healthz`/`/readyz`, checked via `X-API-Key` or `Authorization: Bearer` header) but has **no dedicated chart values field** — set it via `holmes.additionalEnvVars` (`valueFrom.secretKeyRef`). `argus`'s forwarder (`forwarder.py`, per its own `values.yaml`) has **no config field for an outbound auth header to Holmes** — enabling `HOLMES_API_KEY` as currently designed would 401 the forwarder's own calls. This plan does NOT enable `HOLMES_API_KEY` — it ships NetworkPolicy-only hardening and files a follow-up bead for the forwarder patch. Do not silently skip this note; it is a deliberate, scoped-down deviation from the spec's Component 4, not an oversight.
- **`argus`'s Chart.yaml has no packaged/OCI release** — chart lives only as source under `charts/argus/` in the git repo. Use `chart.spec.sourceRef: {kind: GitRepository}`, matching this repo's existing `kubernetes/apps/ai/openviking/` pattern exactly (see that app's `gitrepository.yaml`/`helmrelease.yaml`/`ks.yaml`/`kustomization.yaml` for the reference shape).
- **Cilium default-deny-on-select**: the moment ANY NetworkPolicy selects a pod, Cilium flips that pod's ingress to default-deny — including same-namespace traffic. Every legitimate source must be enumerated, not just cross-namespace ones (same class of bug flagged in `kubernetes/apps/ai/mcpjungle/app/networkpolicy-kelos.yaml`).
- All secrets SOPS-encrypted before commit — `task sops:verify` must pass after every task touching a `*.sops.yaml` file. When editing (not creating) an existing `*.sops.yaml`, use the `sops-edit-then-encrypt` skill.
- Use `bd` for all task tracking (epic + child issues) per this repo's CLAUDE.md — no TodoWrite/TaskCreate/markdown TODO lists.
- Conservative git policy: do not `git push` or run `task flux:reconcile-*` without checking with the user at that point in execution — this plan does not carry standing authorization for either.

---

## File Structure

- **Modify:** `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml` — fix `modelList` (Task 2), add `cilium/core`/`hubble/observability`/`helm/core` toolsets (Task 3). Deleted entirely in Task 10.
- **Modify:** `kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml` — add nothing new (LiteLLM key comes from the existing `litellm-secret` via `extraEnvVarsSecrets`, Task 2). Deleted entirely in Task 10.
- **Create:** `kubernetes/apps/ai/argus/ks.yaml`, `kubernetes/apps/ai/argus/app/{kustomization.yaml,gitrepository.yaml,helmrelease.yaml,secret.sops.yaml,secret-github.sops.yaml,networkpolicy-holmes.yaml}` (Tasks 5–9).
- **Modify:** `kubernetes/apps/ai/kustomization.yaml` — add `./argus/ks.yaml` (Task 5), remove `./holmesgpt/ks.yaml` (Task 10).
- **Modify:** `kubernetes/apps/monitoring/kube-prometheus-stack/app/alertmanagerconfig.yaml` — add an `argus` webhook receiver route (Task 9).

---

### Task 1: Beads epic + child issues

**Files:** none (bd only).

**Interfaces:**
- Produces: an epic bead, child task beads under it. Every later task looks up its own bead by exact title via `bd list --json --title "<title>" | jq -r '.[0].id'` — do not hardcode IDs.

- [ ] **Step 1: Create the epic**

```bash
bd create --type=epic \
  --title="HolmesGPT auto-diagnose + remediation loop (argus Discord HITL bridge)" \
  --description="Fix broken LLM routing, add Cilium/Hubble+Helm toolsets, harden API, consolidate onto argus (Discord HITL bridge, supersedes bifrost), add gated Remediation MCP + GitHub MCP for git-represented durable fixes. Spec: docs/superpowers/specs/2026-08-18-holmesgpt-auto-remediation-design.md. Plan: docs/superpowers/plans/2026-08-18-holmesgpt-auto-remediation.md." \
  --priority=2
```

- [ ] **Step 2: Look up the epic ID**

```bash
EPIC_ID=$(bd list --json --title "HolmesGPT auto-diagnose + remediation loop (argus Discord HITL bridge)" | jq -r '.[0].id')
echo "$EPIC_ID"
```

Expected: a non-empty issue ID.

- [ ] **Step 3: Create child issues, one per implementation task below**

```bash
bd create --type=task --parent="$EPIC_ID" --priority=2 \
  --title="HolmesGPT: fix LLM routing to litellm/coder-large" \
  --description="Replace dead openai/tool-agent alias with litellm/coder-large via LiteLLM. Closes home-ops-d2x's underlying cause. See Task 2 of docs/superpowers/plans/2026-08-18-holmesgpt-auto-remediation.md."

bd create --type=task --parent="$EPIC_ID" --priority=3 \
  --title="HolmesGPT: enable Cilium/Hubble and Helm toolsets" \
  --description="Add cilium/core, hubble/observability, helm/core toolsets; verify CLI binaries and RBAC. See Task 3 of docs/superpowers/plans/2026-08-18-holmesgpt-auto-remediation.md."

bd create --type=task --parent="$EPIC_ID" --priority=2 \
  --title="argus: scaffold GitRepository chart source + Kustomization" \
  --description="Vendor argus as a GitRepository-sourced chart, following the openviking pattern. See Task 5 of docs/superpowers/plans/2026-08-18-holmesgpt-auto-remediation.md."

bd create --type=task --parent="$EPIC_ID" --priority=2 \
  --title="argus: HelmRelease consolidating HolmesGPT config + forwarder + Discord HITL" \
  --description="holmes: override block carries the LiteLLM routing fix, widened toolsets, and NetworkPolicy hardening. forwarder: config wires Discord webhooks + bot HITL buttons. See Tasks 6-7 of docs/superpowers/plans/2026-08-18-holmesgpt-auto-remediation.md."

bd create --type=task --parent="$EPIC_ID" --priority=2 \
  --title="argus: enable Kubernetes Remediation + GitHub mcpAddons" \
  --description="mcpAddons.kubernetesRemediation (already approval-gated by chart default) and mcpAddons.github (scoped PAT, repos/issues/pull_requests/context toolsets) for durable git-committed fixes. See Task 8 of docs/superpowers/plans/2026-08-18-holmesgpt-auto-remediation.md."

bd create --type=task --parent="$EPIC_ID" --priority=2 \
  --title="argus: wire Alertmanager webhook receiver" \
  --description="AlertmanagerConfig route -> argus-forwarder /webhook. See Task 9 of docs/superpowers/plans/2026-08-18-holmesgpt-auto-remediation.md."

bd create --type=task --parent="$EPIC_ID" --priority=3 \
  --title="HolmesGPT: retire standalone holmesgpt app in favor of argus-holmes" \
  --description="Delete kubernetes/apps/ai/holmesgpt/ once argus-holmes is live and verified end to end. See Task 10 of docs/superpowers/plans/2026-08-18-holmesgpt-auto-remediation.md."

bd create --type=task --parent="$EPIC_ID" --priority=2 \
  --title="argus: live end-to-end remediation loop test" \
  --description="Synthetic incident -> Discord post -> approve -> action executes / commit lands -> Flux reconciles clean. See Task 11 of docs/superpowers/plans/2026-08-18-holmesgpt-auto-remediation.md."

bd create --type=task --parent="$EPIC_ID" --priority=3 \
  --title="HolmesGPT: HOLMES_API_KEY auth (needs argus forwarder.py patch)" \
  --description="Deferred: argus's forwarder.py has no outbound-auth-header config field for calling Holmes. Enabling HOLMES_API_KEY as designed would 401 the forwarder. Needs a small ConfigMap-script patch to forwarder.py (no image build required) before this can ship. See Global Constraints in docs/superpowers/plans/2026-08-18-holmesgpt-auto-remediation.md."
```

- [ ] **Step 4: Mark bifrost/c14.7 superseded and close old blockers if reachable**

```bash
bd show home-ops-c14.7
bd supersede home-ops-c14.7 --with="$EPIC_ID" 2>&1 || bd update home-ops-c14.7 --notes="Superseded by $EPIC_ID (argus adopted instead of bifrost) — see docs/superpowers/specs/2026-08-18-holmesgpt-auto-remediation-design.md."
```

Expected: `home-ops-c14.7` no longer open/actionable in this repo's tracker. (`bifrost-a7g`/`bifrost-44f` live in a separate repo's beads DB and aren't reachable from here — leave a note only, don't attempt to close them.)

- [ ] **Step 5: Verify the tree**

```bash
bd show "$EPIC_ID"
bd list --parent="$EPIC_ID"
```

Expected: epic shows 9 children, all `open`.

No commit — beads live in Dolt, not the git tree.

---

### Task 2: Fix HolmesGPT's LLM routing

**Files:**
- Modify: `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml:99-115`

**Interfaces:**
- Consumes: `litellm-secret` (existing, `kubernetes/apps/ai/litellm/app/secret.sops.yaml`, key `LITELLM_MASTER_KEY`) — reused directly, not duplicated.
- Produces: a working `/api/chat` investigation path. Later tasks (3, 6) build on this same `modelList` block.

- [ ] **Step 1: Write the pre-change check (confirms today's config is broken)**

```bash
kubectl -n ai get pods -l app.kubernetes.io/name=holmesgpt-holmes
kubectl -n ai port-forward svc/holmesgpt-holmes 8080:80 &
sleep 2
curl -s -X POST localhost:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"ask": "what pods are running in the ai namespace?", "stream": false}'
kill %1
```

Expected: an error response (model resolution failure / `openai/tool-agent` not found), or a 5xx — confirms the current broken state before changing anything.

- [ ] **Step 2: Fix the modelList block**

In `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`, replace lines 99–115 (the entire `# LLM backend:` comment block through the end of `modelList:`) with:

```yaml
    # LLM backend: LiteLLM proxy in front of both llama-swap instances
    # (reintroduced 2026-08-18, see kubernetes/apps/ai/litellm/). coder-large
    # (Qwen3-Coder-30B-A3B, MoE, 49152 ctx) is the only fleet model confirmed
    # tool-calling-safe under a heavy toolset registry -- same model openclaw
    # already uses successfully for its own agentic harness. Auth reuses
    # litellm-secret (litellm/app/secret.sops.yaml) directly via
    # extraEnvVarsSecrets below -- not duplicated into holmesgpt-secrets.
    modelList:
      litellm:
        model: litellm/coder-large
        api_base: http://litellm.ai.svc.cluster.local:4000/v1
        api_key: "{{ env.LITELLM_MASTER_KEY }}"
```

Then update `extraEnvVarsSecrets` (currently `helmrelease.yaml:55-56`) to also mount `litellm-secret`:

```yaml
    extraEnvVarsSecrets:
      - holmesgpt-secrets
      - litellm-secret
```

- [ ] **Step 3: Validate manifests render**

```bash
kustomize build kubernetes/apps/ai/holmesgpt/app | grep -A3 "modelList\|litellm-secret"
task sops:verify
flux build kustomization holmesgpt --path kubernetes/apps/ai/holmesgpt --dry-run
```

Expected: `kustomize build` output shows `model: litellm/coder-large` and `litellm-secret` in the rendered `envFrom`; `sops:verify` and `flux build --dry-run` both exit 0.

- [ ] **Step 4: Deploy and confirm the fix live**

```bash
git add kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml
git commit -m "fix(ai): route holmesgpt through litellm/coder-large, dead tool-agent alias retired"
git push
task flux:reconcile-ks name=holmesgpt ns=ai
kubectl -n ai rollout status deploy/holmesgpt-holmes --timeout=120s
kubectl -n ai port-forward svc/holmesgpt-holmes 8080:80 &
sleep 2
curl -s localhost:8080/api/model
curl -s -X POST localhost:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"ask": "what pods are running in the ai namespace?", "stream": false}'
kill %1
```

Expected: `/api/model` reports `litellm/coder-large`; `/api/chat` returns a real answer (not a model-resolution error) with a non-empty `tool_calls[]` array showing a `kubernetes/core` call.

- [ ] **Step 5: Commit if any manual fixups were needed**

```bash
git add -A
git status
# only commit here if Step 4's live test required a manifest tweak beyond Step 2
```

---

### Task 3: Enable Cilium/Hubble and Helm toolsets on the current deployment

**Files:**
- Modify: `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml` (append to the `toolsets:` block, `helmrelease.yaml:58-97`)

**Interfaces:**
- Consumes: healthy Hubble Relay (`hubble-relay.kube-system.svc.cluster.local:80`, already deployed).
- Produces: `cilium/core`, `hubble/observability`, `helm/core` toolset entries later carried forward verbatim into argus's `holmes:` override (Task 6).

- [ ] **Step 1: Verify CLI binaries exist in the Holmes pod before enabling**

```bash
kubectl -n ai exec deploy/holmesgpt-holmes -- cilium version
kubectl -n ai exec deploy/holmesgpt-holmes -- hubble version
kubectl -n ai exec deploy/holmesgpt-holmes -- helm version
```

Expected: one of two outcomes.
- **All three succeed** → proceed to Step 2.
- **Any fails** (`command not found`) → do NOT enable that toolset. Note it in the bead from Task 1's Step 3 ("HolmesGPT: enable Cilium/Hubble and Helm toolsets") as a known limitation (chart image doesn't bundle the CLI), skip that toolset's block below, and stop here for this task — file a follow-up bead rather than shipping a toolset that will fail its own preflight check.

- [ ] **Step 2: Add the toolset blocks**

Append inside the existing `toolsets:` map (after the `postgres17-stats:` block, before the closing of that map):

```yaml
      cilium/core:
        enabled: true
      hubble/observability:
        enabled: true
      helm/core:
        enabled: true
```

- [ ] **Step 3: Validate and deploy**

```bash
kustomize build kubernetes/apps/ai/holmesgpt/app | grep -A2 "cilium/core\|hubble/observability\|helm/core"
task sops:verify
flux build kustomization holmesgpt --path kubernetes/apps/ai/holmesgpt --dry-run
git add kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml
git commit -m "feat(ai): enable cilium/hubble and helm toolsets on holmesgpt"
git push
task flux:reconcile-ks name=holmesgpt ns=ai
```

- [ ] **Step 4: Live probe each new toolset**

```bash
kubectl -n ai port-forward svc/holmesgpt-holmes 8080:80 &
sleep 2
curl -s -X POST localhost:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"ask": "show recent Hubble flow drops in the ai namespace", "stream": false}'
curl -s -X POST localhost:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"ask": "what is the Helm release history for holmesgpt itself?", "stream": false}'
kill %1
```

Expected: each response's `tool_calls[]` shows a call into `hubble/observability` and `helm/core` respectively — not just a plausible-sounding `analysis` with no matching tool call (that would mean the toolset silently failed to register).

- [ ] **Step 5: Verify Helm's RBAC coverage**

```bash
kubectl get clusterrole -l app.kubernetes.io/name=holmes -o yaml | grep -A5 "secrets\|configmaps\|persistentvolumeclaims"
```

Expected: the chart-default ClusterRole includes get/list/watch on secrets, configmaps, PVCs, deployments, statefulsets, daemonsets, jobs, cronjobs, ingresses. If any are missing, note it in the Task 1 bead — do not hand-author a ClusterRole override in this task; that's a separate decision if the gap turns out to matter.

---

### Task 4: (intentionally skipped — see Global Constraints on HOLMES_API_KEY)

This task number is reserved to keep numbering aligned with the beads created in Task 1. HOLMES_API_KEY is NOT implemented in this plan — see Global Constraints and the "HolmesGPT: HOLMES_API_KEY auth" bead from Task 1, Step 3.

---

### Task 5: Scaffold argus as a GitRepository-sourced chart

**Files:**
- Create: `kubernetes/apps/ai/argus/app/gitrepository.yaml`
- Create: `kubernetes/apps/ai/argus/app/kustomization.yaml`
- Create: `kubernetes/apps/ai/argus/ks.yaml`
- Modify: `kubernetes/apps/ai/kustomization.yaml`

**Interfaces:**
- Produces: a `GitRepository` named `argus` and a `Kustomization` named `argus` in the `ai` namespace, ready for `helmrelease.yaml` (Task 6) to reference.

- [ ] **Step 1: Confirm the chart source ref to pin**

```bash
git ls-remote --tags https://github.com/olivecasazza/argus
git ls-remote https://github.com/olivecasazza/argus refs/heads/main
```

Expected: if a `v0.1.0`-style tag exists matching `Chart.yaml`'s `version: 0.1.0`, pin to that tag. If no tags exist yet, pin to the current `main` HEAD commit SHA (not the branch name — a branch ref moves, a SHA doesn't) for reproducibility, and note in the commit message that this should be revisited once argus cuts a tag.

- [ ] **Step 2: Write the GitRepository**

```yaml
# kubernetes/apps/ai/argus/app/gitrepository.yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/gitrepository-source-v1.json
# Deliberate exception to this repo's OCIRepository+chartRef convention,
# same reasoning as kubernetes/apps/ai/openviking/app/gitrepository.yaml:
# argus (olivecasazza/argus) publishes no packaged Helm artifact -- chart
# source only, under charts/argus/ in the git repo itself.
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: argus
spec:
  interval: 12h
  ref:
    # Replace with the tag/SHA confirmed in Step 1.
    commit: "<PASTE_COMMIT_SHA_FROM_STEP_1>"
  url: https://github.com/olivecasazza/argus
```

- [ ] **Step 3: Write the Kustomization resource list (helmrelease/secret files land in later tasks)**

```yaml
# kubernetes/apps/ai/argus/app/kustomization.yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./gitrepository.yaml
```

- [ ] **Step 4: Write the Flux Kustomization**

```yaml
# kubernetes/apps/ai/argus/ks.yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app argus
  namespace: &namespace ai
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  dependsOn:
    - name: litellm
      namespace: *namespace
  path: ./kubernetes/apps/ai/argus/app
  prune: true
  retryInterval: 2m
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: *namespace
  timeout: 10m
  wait: false
```

- [ ] **Step 5: Wire into the ai namespace kustomization**

In `kubernetes/apps/ai/kustomization.yaml`, add `./argus/ks.yaml` to `resources:` (alphabetical position, before `./faster-whisper/ks.yaml`).

- [ ] **Step 6: Validate**

```bash
kustomize build kubernetes/apps/ai/argus/app
flux build kustomization argus --path kubernetes/apps/ai/argus --dry-run
```

Expected: both succeed — this only validates the `GitRepository` at this point, since `helmrelease.yaml` doesn't exist yet.

- [ ] **Step 7: Commit**

```bash
git add kubernetes/apps/ai/argus/ kubernetes/apps/ai/kustomization.yaml
git commit -m "feat(ai): scaffold argus GitRepository chart source"
```

Do not push yet — Task 6 adds the HelmRelease this Kustomization needs to actually reconcile successfully.

---

### Task 6: argus HelmRelease — consolidate HolmesGPT config + forwarder + Discord HITL

**Files:**
- Create: `kubernetes/apps/ai/argus/app/helmrelease.yaml`
- Create: `kubernetes/apps/ai/argus/app/secret.sops.yaml`
- Create: `kubernetes/apps/ai/argus/app/networkpolicy-holmes.yaml`
- Modify: `kubernetes/apps/ai/argus/app/kustomization.yaml`

**Interfaces:**
- Consumes: `litellm-secret` (existing), the toolset config validated in Tasks 2–3.
- Produces: Service `argus-holmes.ai.svc.cluster.local:80` (replaces `holmesgpt-holmes.ai.svc.cluster.local:80` as the investigation endpoint used by Task 8's mcpAddons and Task 9's Alertmanager wiring), Service `argus-forwarder` for the Discord bridge.

- [ ] **Step 1: Create the manual Discord prerequisites**

Before writing the secret, the user creates (outside this repo, manual steps — same category as prior manual credential steps in this epic):
1. A Discord incoming webhook URL for the default/critical/warning channels (or one shared webhook for all).
2. A Discord bot application + token, with `DISCORD_CONTROL_CHANNEL_ID` set to the channel where HITL Approve/Reject/Revise buttons should post.

- [ ] **Step 2: Write the argus-forwarder secret**

```yaml
# kubernetes/apps/ai/argus/app/secret.sops.yaml
apiVersion: v1
kind: Secret
metadata:
  name: argus-forwarder
stringData:
  DISCORD_WEBHOOK: "<PASTE_DEFAULT_WEBHOOK_URL>"
  DISCORD_WEBHOOK_CRITICAL: "<PASTE_CRITICAL_WEBHOOK_URL_OR_LEAVE_EMPTY>"
  DISCORD_WEBHOOK_WARNING: "<PASTE_WARNING_WEBHOOK_URL_OR_LEAVE_EMPTY>"
  DISCORD_BOT_TOKEN: "<PASTE_BOT_TOKEN>"
```

Encrypt with the `sops-edit-then-encrypt` skill (this is a new file — `task sops:encrypt-file file=kubernetes/apps/ai/argus/app/secret.sops.yaml` after filling in real values, or use the skill directly).

- [ ] **Step 3: Write the HelmRelease**

```yaml
# kubernetes/apps/ai/argus/app/helmrelease.yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: &app argus
spec:
  interval: 1h
  timeout: 10m
  chart:
    spec:
      # Chart lives only as git source (charts/argus/), no OCI artifact or
      # HelmRepository index published -- see gitrepository.yaml. version:
      # deliberately omitted: Flux resolves from the pinned GitRepository
      # ref, not semver matching.
      chart: ./charts/argus
      sourceRef:
        kind: GitRepository
        name: argus
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  values:
    podAnnotations:
      reloader.stakater.com/auto: "true"

    forwarder:
      # holmesUrl left at chart default (http://argus-holmes:80) -- with
      # release name "argus" the holmes subchart's Service is exactly that.
      investigateSeverities: "critical,warning"
      dedupeTtlSec: 3600
      discordEnabled: true
      discordSecret:
        name: argus-forwarder
        key: DISCORD_WEBHOOK
      discordChannels:
        critical: ""
        warning: ""
      discordBotToken:
        name: argus-forwarder
        key: DISCORD_BOT_TOKEN
      discordControlChannelId: "<PASTE_CONTROL_CHANNEL_ID>"
      # No repoMappings -- HolmesGPT's own github mcpAddon (Task 8) handles
      # durable git commits directly; argus's parallel repo-mapping feature
      # is unused for this design.
      repoMappings: {}

    # Holmes subchart override -- consolidates everything validated in
    # Tasks 2-3 of this plan onto the one Holmes instance argus manages.
    # Deliberately does NOT override createServiceAccount/k8sRBAC/
    # customServiceAccountName -- this repo's live-audited standalone
    # holmesgpt deployment already proves the chart's own RBAC defaults
    # work at v0.39.0 (kubectl get clusterrole confirmed a working,
    # bound, read-only ClusterRole); no need to port argus's own
    # nixlab-specific RBAC workaround.
    holmes:
      operator:
        enabled: true
      extraEnvVarsSecrets:
        - litellm-secret
      modelList:
        litellm:
          model: litellm/coder-large
          api_base: http://litellm.ai.svc.cluster.local:4000/v1
          api_key: "{{ env.LITELLM_MASTER_KEY }}"
      toolsets:
        robusta:
          enabled: false
        prometheus/metrics:
          enabled: true
          subtype: victoriametrics
          config:
            prometheus_url: https://metrics.68cc.io
        grafana/dashboards:
          enabled: true
          config:
            api_key: "{{ env.GRAFANA_API_KEY }}"
            api_url: http://grafana-service.monitoring.svc.cluster.local:3000
        victorialogs:
          enabled: true
          config:
            api_url: https://logs.68cc.io
            headers:
              AccountID: "0"
              ProjectID: "0"
          llm_instructions: "Log stream fields are: stream, kubernetes.pod_name, kubernetes.container_name, kubernetes.pod_namespace (NOT 'namespace'), app_name, hostname. Message content is in the 'log' field."
        postgres17-stats:
          type: database
          enabled: true
          llm_instructions: "Cluster-level PostgreSQL statistics only (pg_monitor). No table data access -- use pg_stat_activity, pg_locks, pg_stat_replication."
          config:
            connection_url: "{{ env.POSTGRES_CONNECTION_URL }}"
        cilium/core:
          enabled: true
        hubble/observability:
          enabled: true
        helm/core:
          enabled: true
      resources:
        requests:
          cpu: 100m
          memory: 2048Mi
        limits:
          memory: 2048Mi
```

`GRAFANA_API_KEY` and `POSTGRES_CONNECTION_URL` still come from the existing `holmesgpt-secrets` Secret (`kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml`) — add it to `holmes.extraEnvVarsSecrets` too:

```yaml
      extraEnvVarsSecrets:
        - litellm-secret
        - holmesgpt-secrets
```

(Leave `holmesgpt-secrets` itself in place under `kubernetes/apps/ai/holmesgpt/app/` for now — Task 10 deletes the standalone app, at which point this Secret should be copied over to `kubernetes/apps/ai/argus/app/` under its own file rather than left as a dangling cross-app reference. Note this explicitly in Task 10.)

- [ ] **Step 4: NetworkPolicy scoping ingress to argus-holmes**

```yaml
# kubernetes/apps/ai/argus/app/networkpolicy-holmes.yaml
---
# Scopes ingress to the argus-managed Holmes pod. Per the Cilium
# default-deny-on-select rule (see Global Constraints), every legitimate
# source must be listed, not just cross-namespace ones.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-forwarder-to-holmes
  namespace: ai
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: holmes
      app.kubernetes.io/instance: argus
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ai
      ports:
        - protocol: TCP
          port: 80
```

- [ ] **Step 5: Register new files in the Kustomization**

```yaml
# kubernetes/apps/ai/argus/app/kustomization.yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./gitrepository.yaml
  - ./secret.sops.yaml
  - ./networkpolicy-holmes.yaml
  - ./helmrelease.yaml
```

- [ ] **Step 6: Validate**

```bash
kustomize build kubernetes/apps/ai/argus/app
task sops:verify
flux build kustomization argus --path kubernetes/apps/ai/argus --dry-run
```

Expected: all three succeed. Confirm the rendered ClusterRole/Deployment for `argus-holmes` in the `kustomize build` output includes the `toolsets:` block from Step 3 verbatim.

- [ ] **Step 7: Commit**

```bash
git add kubernetes/apps/ai/argus/
git commit -m "feat(ai): argus HelmRelease consolidates holmesgpt config + Discord HITL bridge"
```

Do not push or deploy yet — Task 8 adds the remediation/github mcpAddons before this goes live, so the first live rollout carries the full toolset.

---

### Task 7: (reserved — folded into Task 6's HelmRelease, no separate file changes)

Kept as a numbered marker only so the bead numbering in Task 1 stays legible; the forwarder config landed inside Task 6, Step 3.

---

### Task 8: Enable Kubernetes Remediation + GitHub mcpAddons

**Files:**
- Modify: `kubernetes/apps/ai/argus/app/helmrelease.yaml` (append to `values.holmes.mcpAddons`)
- Create: `kubernetes/apps/ai/argus/app/secret-github.sops.yaml`
- Modify: `kubernetes/apps/ai/argus/app/kustomization.yaml`

**Interfaces:**
- Consumes: a fine-grained GitHub PAT scoped to `j0sh3rs/home-ops` only (Contents + Pull requests read/write, Metadata read-only) — user creates this manually.
- Produces: `mcpAddons.kubernetesRemediation` (own auto-created ServiceAccount `k8s-remediation-mcp-sa` + chart-generated least-privilege ClusterRole) and `mcpAddons.github` (own sidecar, `repos,issues,pull_requests,context` toolsets) available to the Holmes investigation loop, both gated: remediation via the chart-default `approvalRequiredTools: ["run_kubectl_command"]`, github via argus's own Discord HITL flow wrapping every Holmes action.

- [ ] **Step 1: Create the GitHub PAT secret**

```yaml
# kubernetes/apps/ai/argus/app/secret-github.sops.yaml
apiVersion: v1
kind: Secret
metadata:
  name: holmesgpt-github-secret
stringData:
  token: "<PASTE_FINE_GRAINED_PAT>"
```

Encrypt via `sops-edit-then-encrypt`.

- [ ] **Step 2: Add both mcpAddons to the HelmRelease**

In `kubernetes/apps/ai/argus/app/helmrelease.yaml`, under `values.holmes:`, add:

```yaml
      mcpAddons:
        kubernetesRemediation:
          enabled: true
          # approvalRequiredTools stays at chart default
          # (["run_kubectl_command"]) -- every mutating action still
          # requires human approval via argus's Discord HITL buttons.
        github:
          enabled: true
          auth:
            secretName: holmesgpt-github-secret
            secretKey: token
          config:
            # repos covers get/create/update file contents (needed for
            # durable git-committed fixes); pull_requests + context kept
            # for investigation; actions and issues intentionally
            # excluded -- HolmesGPT should read/write repo content, not
            # trigger CI or manage the issue tracker.
            toolsets: "repos,pull_requests,context"
```

- [ ] **Step 3: Register the new secret file**

```yaml
# kubernetes/apps/ai/argus/app/kustomization.yaml
resources:
  - ./gitrepository.yaml
  - ./secret.sops.yaml
  - ./secret-github.sops.yaml
  - ./networkpolicy-holmes.yaml
  - ./helmrelease.yaml
```

- [ ] **Step 4: Validate**

```bash
kustomize build kubernetes/apps/ai/argus/app | grep -A5 "kubernetesRemediation\|mcpAddons"
task sops:verify
flux build kustomization argus --path kubernetes/apps/ai/argus --dry-run
```

Expected: all succeed. Rendered output shows both mcpAddon blocks.

- [ ] **Step 5: Deploy for the first time**

```bash
git add kubernetes/apps/ai/argus/
git commit -m "feat(ai): enable argus kubernetesRemediation + github mcpAddons"
git push
task flux:reconcile-ks name=argus ns=ai
kubectl -n ai get pods -l app.kubernetes.io/instance=argus
```

Expected: `argus-holmes`, `argus-forwarder`, `argus-holmes-kubernetes-remediation-mcp` (or similarly named sidecar), and `argus-holmes-github-mcp` pods all reach `Running`/`Ready`.

- [ ] **Step 6: Verify the remediation ServiceAccount/ClusterRole were generated as expected**

```bash
kubectl get sa -n ai k8s-remediation-mcp-sa
kubectl get clusterrole -l app.kubernetes.io/name=kubernetes-remediation-mcp -o yaml | grep -E "verbs:|resources:"
```

Expected: no `secrets` resource, no `*` verb, verbs limited to the documented allowlist (get/list/watch/patch/update/delete on apps resources, pods/exec, pods/eviction, node patch, batch).

---

### Task 9: Wire Alertmanager to argus-forwarder

**Files:**
- Modify: `kubernetes/apps/monitoring/kube-prometheus-stack/app/alertmanagerconfig.yaml`

**Interfaces:**
- Consumes: `argus-forwarder.ai.svc.cluster.local` (from Task 6).
- Produces: firing alerts (severity=critical, matching the existing `discord` route) also POST to argus for investigation, in addition to the existing plain Discord notification.

- [ ] **Step 1: Add a webhook_configs entry to the existing discord receiver**

In `kubernetes/apps/monitoring/kube-prometheus-stack/app/alertmanagerconfig.yaml`, extend the `discord` receiver (currently lines 64–90) — add alongside the existing `webhookConfigs` entry for openclaw:

```yaml
      webhookConfigs:
        - url: "http://openclaw.ai.svc.cluster.local:18789/hooks/alertmanager"
          sendResolved: false
          httpConfig:
            bearerTokenSecret:
              name: openclaw-hooks-secret
              key: token
        # argus's forwarder does its own severity filtering
        # (forwarder.investigateSeverities: "critical,warning") and
        # dedupe -- safe to send every alert this receiver already
        # handles, not just critical.
        - url: "http://argus-forwarder.ai.svc.cluster.local/webhook"
          sendResolved: false
```

- [ ] **Step 2: Validate**

```bash
kustomize build kubernetes/apps/monitoring/kube-prometheus-stack/app | grep -A10 "webhookConfigs"
flux build kustomization kube-prometheus-stack --path kubernetes/apps/monitoring/kube-prometheus-stack --dry-run
```

- [ ] **Step 3: Deploy and send a synthetic alert**

```bash
git add kubernetes/apps/monitoring/kube-prometheus-stack/app/alertmanagerconfig.yaml
git commit -m "feat(monitoring): route Alertmanager webhooks to argus-forwarder"
git push
task flux:reconcile-ks name=kube-prometheus-stack ns=monitoring
kubectl -n ai port-forward svc/argus-forwarder 8090:80 &
sleep 2
curl -s -X POST localhost:8090/webhook -H 'Content-Type: application/json' -d '{
  "receiver": "discord",
  "status": "firing",
  "alerts": [{
    "status": "firing",
    "labels": {"alertname": "SyntheticTestAlert", "severity": "warning", "namespace": "ai"},
    "annotations": {"summary": "synthetic test alert for argus wiring verification"}
  }]
}'
kill %1
```

Expected: HTTP 200 from the forwarder, and a message appears in the configured Discord channel within the forwarder's investigation timeout (`forwarder.holmesTimeoutSec`, default 300s).

---

### Task 10: Retire the standalone holmesgpt app

**Files:**
- Delete: `kubernetes/apps/ai/holmesgpt/` (entire directory)
- Modify: `kubernetes/apps/ai/kustomization.yaml`
- Create: `kubernetes/apps/ai/argus/app/secret-holmesgpt.sops.yaml` (carries `GRAFANA_API_KEY`/`POSTGRES_CONNECTION_URL` forward, replacing the deleted `holmesgpt-secrets`)
- Modify: `kubernetes/apps/ai/argus/app/helmrelease.yaml` (point `extraEnvVarsSecrets` at the renamed secret)
- Modify: `kubernetes/apps/ai/argus/app/kustomization.yaml`

**Interfaces:**
- Consumes: Tasks 2–9 all verified working against `argus-holmes`.

- [ ] **Step 1: Confirm argus-holmes has been live and stable before deleting anything**

```bash
kubectl -n ai get pods -l app.kubernetes.io/instance=argus
kubectl -n ai logs deploy/argus-holmes --since=1h | grep -i error
```

Expected: pods `Running`, no repeating errors in the last hour. Do not proceed if argus-holmes has been up for less than a full day of real traffic — this step exists to prevent deleting the working fallback prematurely.

- [ ] **Step 2: Carry the Postgres/Grafana secret forward under argus's app dir**

Copy the plaintext values from the current `kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml` (`GRAFANA_API_KEY`, `POSTGRES_CONNECTION_URL`) into a new `kubernetes/apps/ai/argus/app/secret-holmesgpt.sops.yaml` with `metadata.name: holmesgpt-secrets`, via `sops-edit-then-encrypt` (decrypt the old file to read values, encrypt the new one — do not just copy ciphertext, SOPS ciphertext isn't portable across files without matching data keys).

Update the note in `kubernetes/apps/databases/cloudnative-pg/cluster/holmesgpt-role-secret.sops.yaml`'s existing comment (which says "mirrored into `holmesgpt-secrets` in the `ai` namespace") to point at the new file path.

- [ ] **Step 3: Register the new secret, remove the dangling cross-app reference**

Add `./secret-holmesgpt.sops.yaml` to `kubernetes/apps/ai/argus/app/kustomization.yaml`. `helmrelease.yaml`'s `extraEnvVarsSecrets` list (`litellm-secret`, `holmesgpt-secrets`) needs no change — the Secret name stays `holmesgpt-secrets`, only its home directory moves.

- [ ] **Step 4: Delete the standalone app**

```bash
git rm -r kubernetes/apps/ai/holmesgpt/
```

Remove `./holmesgpt/ks.yaml` from `kubernetes/apps/ai/kustomization.yaml`'s `resources:` list.

- [ ] **Step 5: Validate**

```bash
kustomize build kubernetes/apps/ai/argus/app | grep -A2 "holmesgpt-secrets"
task sops:verify
flux build kustomization argus --path kubernetes/apps/ai/argus --dry-run
flux build kustomization ai --path kubernetes/apps/ai --dry-run 2>&1 | grep -i "holmesgpt" || echo "no stray holmesgpt references"
```

Expected: `argus-holmes` still mounts `GRAFANA_API_KEY`/`POSTGRES_CONNECTION_URL` from the relocated secret; no references to the deleted `kubernetes/apps/ai/holmesgpt/` path remain.

- [ ] **Step 6: Deploy and confirm no regression**

```bash
git add -A
git commit -m "refactor(ai): retire standalone holmesgpt app, argus-holmes is now the only instance"
git push
task flux:reconcile-ks name=ai ns=flux-system
kubectl -n ai get ks holmesgpt 2>&1  # expect: not found
kubectl -n ai port-forward svc/argus-holmes 8080:80 &
sleep 2
curl -s -X POST localhost:8080/api/chat -H 'Content-Type: application/json' \
  -d '{"ask": "cluster-level postgres connection count via pg_monitor", "stream": false}'
kill %1
```

Expected: the `holmesgpt` Flux Kustomization is gone; `argus-holmes` still answers a Postgres-toolset probe correctly.

---

### Task 11: Live end-to-end remediation loop test

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything from Tasks 2–10.

- [ ] **Step 1: Pick a deliberately low-stakes target**

Scale a throwaway/non-critical test Deployment to 0 replicas (create one first if none exists — a single-replica `busybox` sleep loop in a scratch namespace is sufficient) so it trips an alert without affecting real workloads.

```bash
kubectl create namespace argus-test --dry-run=client -o yaml | kubectl apply -f -
kubectl -n argus-test create deployment scratch-target --image=busybox --replicas=1 -- sleep infinity
kubectl -n argus-test scale deployment scratch-target --replicas=0
```

- [ ] **Step 2: Trigger and observe the full loop**

Wait for whatever alerting rule fires on the scaled-down deployment (or manually POST a synthetic webhook shaped like Task 9's Step 3 test, with `namespace: argus-test`, `deployment: scratch-target` in the labels) and watch:
1. Discord message arrives with HolmesGPT's investigation summary.
2. Approve/Reject/Revise buttons are present.
3. Click Approve.
4. Confirm the action executes: `kubectl -n argus-test get deployment scratch-target -o jsonpath='{.spec.replicas}'` — should return to a non-zero value if HolmesGPT proposed a scale-up remediation.

- [ ] **Step 3: Confirm Flux health after the test**

```bash
flux get ks -A | grep -v "True.*Applied"
```

Expected: no Kustomization in a failed/drifted state as a result of the test.

- [ ] **Step 4: Tear down the scratch namespace**

```bash
kubectl delete namespace argus-test
```

- [ ] **Step 5: Close beads**

```bash
bd close "$EPIC_ID" --reason="Full loop verified live: Alertmanager -> argus-holmes investigation -> Discord HITL -> approved remediation -> confirmed cluster state change, Flux reconciled clean."
bd list --parent="$EPIC_ID"
```

Expected: all child beads closed except the deferred `HOLMES_API_KEY` one, which stays open as tracked follow-up.

---

## Self-Review Notes

- **Spec coverage:** Component 1 (Task 2), Component 2 Cilium/Hubble+Helm (Task 3), Component 3 hardening (Task 6 Step 4 NetworkPolicy; HOLMES_API_KEY explicitly deferred per Global Constraints — real chart/forwarder investigation surfaced a blocker the spec didn't anticipate), Component 4/5 argus deploy (Tasks 5–7), Component 6 Remediation MCP (Task 8), Component 7 GitHub MCP + durable-fix routing (Task 8) — the durable-vs-transient routing rule itself is a system-prompt/instruction concern for HolmesGPT at runtime, not a manifest change; no further task needed. Validation plan phases 1–5 from the spec map to Tasks 2/3/6/9/11 respectively.
- **Placeholder scan:** all `<PASTE_...>` markers are manual-credential inputs (same category the predecessor plan used for the Grafana token) — not implementation placeholders; every code/YAML block is complete.
- **Type/name consistency:** `holmesgpt-secrets` Secret name is preserved across Tasks 6 and 10 (only its owning directory moves); `argus-holmes` Service name used consistently from Task 6 onward, replacing `holmesgpt-holmes` everywhere after Task 8's live deploy.
