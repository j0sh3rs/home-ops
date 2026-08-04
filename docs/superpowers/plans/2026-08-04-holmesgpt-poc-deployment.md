# HolmesGPT POC Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy HolmesGPT (base HTTP API service + bundled Operator) into the `ai` namespace via its Helm chart, wired to omniroute as the LLM backend, with no output-destination wiring yet.

**Architecture:** New `HelmRepository` source (`robusta`, `https://robusta-charts.storage.googleapis.com`) feeding a new `kubernetes/apps/ai/holmesgpt/` Flux app. The chart is installed with `chart.spec.sourceRef` (legacy pattern — no OCI artifact exists for this chart) rather than `OCIRepository`/`chartRef`. HolmesGPT's `modelList` points at omniroute's OpenAI-compatible endpoint in-cluster; API key lives in a new SOPS-encrypted secret. The chart ships CRDs in a static `crds/` directory (HealthCheck/ScheduledHealthCheck/TriggeredHealthCheck) — Flux's `HelmRelease.spec.install.crds`/`upgrade.crds` must be set to `CreateReplace` or they won't get applied/updated the way `helm install`/`helm upgrade --install` would handle them by default.

**Tech Stack:** FluxCD (`HelmRepository` + `HelmRelease`), SOPS/age for secrets, `kustomize`/`flux build`/`task sops:verify` for validation. Chart: `robusta/holmes` (ArtifactHub-confirmed latest `0.38.1`, values schema confirmed by reading `helm/holmes/values.yaml` and `helm/holmes/templates/*.yaml` directly from `github.com/HolmesGPT/holmesgpt` at `master`).

## Global Constraints

- No OCI artifact exists for this chart — use `HelmRepository` + `chart.spec.sourceRef`, per CLAUDE.md's documented fallback rule for charts without OCI publishing.
- No bifrost, no chaski, no Discord integration, no output-destination wiring in this pass (tracked separately in `bifrost-a7g`/`bifrost-44f` and `home-ops-4rm`).
- No HTTPRoute/Gateway exposure — cluster-internal only for this POC.
- No HealthCheck/ScheduledHealthCheck/TriggeredHealthCheck custom resources created — only the Operator's CRDs/controller install.
- All secrets SOPS-encrypted before commit (`task sops:verify` must pass).
- Memory <2Gi per pod guideline (CLAUDE.md "Key Design Decisions") — chart default request/limit (100m/2048Mi request, 2048Mi limit) sits right at that ceiling; do not raise it without cause.
- LiteLLM is being phased out in favor of omniroute — do not wire this to litellm.

---

## File Structure

- **Create:** `kubernetes/flux/meta/repos/robusta.yaml` — `HelmRepository` pointing at the chart source.
- **Modify:** `kubernetes/flux/meta/repos/kustomization.yaml` — add `./robusta.yaml` to `resources`.
- **Create:** `kubernetes/apps/ai/holmesgpt/ks.yaml` — Flux `Kustomization`, `dependsOn: omniroute`.
- **Create:** `kubernetes/apps/ai/holmesgpt/app/kustomization.yaml` — kustomize overlay listing the two resources below.
- **Create:** `kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml` — `holmesgpt-secrets` Secret (`OMNIROUTE_API_KEY`), SOPS-encrypted.
- **Create:** `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml` — the `HelmRelease` itself.
- **Modify:** `kubernetes/apps/ai/kustomization.yaml` — add `./holmesgpt/ks.yaml` to `resources`.

---

### Task 1: Determine the omniroute model name and generate an API key

This is a manual/external prerequisite — omniroute's dashboard is the only place to generate a usable API key, and its `/v1/models` endpoint is the only reliable way to confirm the exact model identifier string to use in HolmesGPT's `modelList`.

**Files:** none (no repo changes in this task).

**Interfaces:**
- Produces: `OMNIROUTE_MODEL_NAME` (a string, e.g. `cc/claude-opus-4-6` — exact value discovered in Step 2 below) and `OMNIROUTE_API_KEY` (a secret string), both consumed by Task 5 (the SOPS secret) and Task 6 (the HelmRelease `modelList`).

- [x] **Step 1: Generate an omniroute API key**

Open `https://omniroute.68cc.io` in a browser, sign in, and generate a new API key from the dashboard's key-management screen (per the omniroute wiki, keys are managed at `/api/settings` and `/api/keys*` — reachable from the dashboard UI, not a CLI command). Copy the key value somewhere safe for Task 5 — do not paste it into any file in this repo yet.

- [x] **Step 2: Confirm the exact model name to route to**

From a machine with cluster access (or via `kubectl -n ai exec` into any pod that can reach the `omniroute` Service), run:

```bash
kubectl -n ai run omniroute-model-check --rm -it --restart=Never --image=curlimages/curl:8.11.1 -- \
  curl -s -H "Authorization: Bearer <PASTE_KEY_FROM_STEP_1>" \
  http://omniroute.ai.svc.cluster.local:20129/v1/models
```

Expected: a JSON `{"data": [{"id": "...", ...}, ...]}` response listing the model identifiers omniroute currently exposes. Pick one (e.g. a Claude or GPT alias already configured in omniroute) and write it down — this becomes `OMNIROUTE_MODEL_NAME` in Task 5/6. If the command errors with connection refused, confirm the omniroute pod is actually running (`kubectl -n ai get pods -l app.kubernetes.io/name=omniroute`) before continuing.

- [x] **Step 3: Record both values for later steps**

No commit for this task — just keep `OMNIROUTE_API_KEY` and `OMNIROUTE_MODEL_NAME` on hand for Task 5 and Task 6.

---

### Task 2: Add the `robusta` HelmRepository source

**Files:**
- Create: `kubernetes/flux/meta/repos/robusta.yaml`
- Modify: `kubernetes/flux/meta/repos/kustomization.yaml`

**Interfaces:**
- Produces: a `HelmRepository` named `robusta` in namespace `flux-system`, consumed by Task 6's `HelmRelease.spec.chart.spec.sourceRef`.

- [x] **Step 1: Create the HelmRepository manifest**

Write `kubernetes/flux/meta/repos/robusta.yaml`:

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/helmrepository-source-v1.json
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: robusta
  namespace: flux-system
spec:
  interval: 1h
  url: https://robusta-charts.storage.googleapis.com
```

- [x] **Step 2: Register it in the repos kustomization**

Edit `kubernetes/flux/meta/repos/kustomization.yaml`, adding `./robusta.yaml` to the `resources` list (alphabetical position, after `./qdrant.yaml` and before `./traefik.yaml`):

```yaml
  - ./qdrant.yaml
  - ./robusta.yaml
  - ./traefik.yaml
```

- [x] **Step 3: Validate**

Run: `kustomize build kubernetes/flux/meta/repos | grep -A5 "name: robusta"`
Expected: the rendered `HelmRepository` object appears with `url: https://robusta-charts.storage.googleapis.com`.

- [x] **Step 4: Commit**

```bash
git add kubernetes/flux/meta/repos/robusta.yaml kubernetes/flux/meta/repos/kustomization.yaml
git commit -m "feat(flux): add robusta HelmRepository for HolmesGPT chart"
```

---

### Task 3: Verify the pinned chart version's actual values schema

The values.yaml content used to write Task 5/6 was read from the `master` branch of `github.com/HolmesGPT/holmesgpt`, not from the packaged `0.38.1` chart tarball itself. Confirm they match before writing the HelmRelease, since a mismatch would silently produce wrong config (e.g. an `image:` field that isn't actually a bare `name:tag` string in the released chart).

**Files:** none (verification only, no repo changes).

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: confirmation (or a list of discrepancies) that Task 6 must account for.

- [x] **Step 1: Pull the actual packaged chart values**

```bash
helm repo add robusta https://robusta-charts.storage.googleapis.com
helm repo update robusta
helm show values robusta/holmes --version 0.38.1 > /tmp/holmes-0.38.1-values.yaml
diff /tmp/holmes-0.38.1-values.yaml <(curl -sL https://raw.githubusercontent.com/HolmesGPT/holmesgpt/master/helm/holmes/values.yaml)
```

Expected: no diff, or only trivial differences (comment wording, whitespace). If there's a substantive diff in the `operator:`, `modelList:`, `toolsets:`, `k8sRBAC:`, `image:`, or `resources:` sections, re-read the corresponding block in `/tmp/holmes-0.38.1-values.yaml` and adjust Task 6's HelmRelease values to match the real 0.38.1 schema before proceeding — do not carry forward a value key that doesn't exist in the pinned version.

- [x] **Step 2: Confirm the image field's actual default**

```bash
grep -A2 "^image:" /tmp/holmes-0.38.1-values.yaml
grep -A2 "^registry:" /tmp/holmes-0.38.1-values.yaml
```

Expected: `image: holmes:<something other than 0.0.0>` if the packaged chart substitutes its own `AppVersion` at package time, or `image: holmes:0.0.0` if it's a literal placeholder that needs overriding. If it's still `0.0.0`, Task 6 must explicitly set `image: holmes:0.38.1` (or whatever `helm show chart robusta/holmes --version 0.38.1` reports as `appVersion`) — do not leave the placeholder in the HelmRelease values.

No commit for this task — it's a verification gate for Task 6.

---

### Task 4: Scaffold the app directory and Flux Kustomization

**Files:**
- Create: `kubernetes/apps/ai/holmesgpt/ks.yaml`
- Create: `kubernetes/apps/ai/holmesgpt/app/kustomization.yaml`
- Modify: `kubernetes/apps/ai/kustomization.yaml`

**Interfaces:**
- Consumes: nothing (structural scaffolding only).
- Produces: `Kustomization` named `holmesgpt` in namespace `ai`, `targetNamespace: ai`, which Task 5/6's manifests get applied through. `dependsOn: omniroute` (namespace `ai`) — mirrors the existing `litellm`/`omniroute` → `llama-swap` dependency pattern in this namespace.

- [x] **Step 1: Write the Flux Kustomization**

Create `kubernetes/apps/ai/holmesgpt/ks.yaml`:

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app holmesgpt
  namespace: &namespace ai
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  dependsOn:
    # omniroute is the LLM backend HolmesGPT's modelList routes to.
    - name: omniroute
      namespace: *namespace
  path: ./kubernetes/apps/ai/holmesgpt/app
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

- [x] **Step 2: Write the app kustomization overlay**

Create `kubernetes/apps/ai/holmesgpt/app/kustomization.yaml`:

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./secret.sops.yaml
  - ./helmrelease.yaml
```

- [x] **Step 3: Register the app in the ai namespace kustomization**

Edit `kubernetes/apps/ai/kustomization.yaml`, adding `./holmesgpt/ks.yaml` to `resources` (alphabetical position, after `./faster-whisper/ks.yaml` and before `./litellm/ks.yaml`):

```yaml
  - ./faster-whisper/ks.yaml
  - ./holmesgpt/ks.yaml
  - ./litellm/ks.yaml
```

- [x] **Step 4: Commit**

```bash
git add kubernetes/apps/ai/holmesgpt/ks.yaml kubernetes/apps/ai/holmesgpt/app/kustomization.yaml kubernetes/apps/ai/kustomization.yaml
git commit -m "feat(ai): scaffold holmesgpt app structure"
```

(This commit will fail `kustomize build` until Task 5/6 add the two referenced resource files — that's expected; the plan builds up the app across tasks and validates fully at the end of Task 6. If you're executing tasks strictly in order within one sitting, it's fine to defer this commit until Task 6's Step 4 instead and combine them — see the note in Task 6.)

---

### Task 5: Write the SOPS-encrypted secret

**Files:**
- Create: `kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml`

**Interfaces:**
- Consumes: `OMNIROUTE_API_KEY` from Task 1.
- Produces: Secret `holmesgpt-secrets` in namespace `ai`, key `OMNIROUTE_API_KEY` — consumed by Task 6's `extraEnvVarsSecrets` + `modelList[...].api_key: envRef:OMNIROUTE_API_KEY`.

- [x] **Step 1: Write the plaintext secret**

Create `kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml` with real plaintext content first (it gets encrypted in Step 2 — do not commit this file before encrypting it):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: holmesgpt-secrets
  namespace: ai
type: Opaque
stringData:
  OMNIROUTE_API_KEY: "<PASTE_KEY_FROM_TASK_1_STEP_1>"
```

- [x] **Step 2: Encrypt it**

```bash
task sops:encrypt-file file=kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml
```

Expected: the `stringData.OMNIROUTE_API_KEY` value is replaced with an `ENC[AES256_GCM,...]` block and a `sops:` metadata footer is appended, matching the shape of `kubernetes/apps/ai/omniroute/app/secret.sops.yaml`.

- [x] **Step 3: Verify encryption**

```bash
task sops:verify
```

Expected: passes with no errors reported for the new file. If it fails, re-run Step 2 — do not hand-edit the encrypted file.

- [x] **Step 4: Commit**

```bash
git add kubernetes/apps/ai/holmesgpt/app/secret.sops.yaml
git commit -m "feat(ai): add holmesgpt-secrets SOPS secret"
```

---

### Task 6: Write the HelmRelease

**Files:**
- Create: `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`

**Interfaces:**
- Consumes: `robusta` HelmRepository (Task 2), `holmesgpt-secrets` Secret with key `OMNIROUTE_API_KEY` (Task 5), `OMNIROUTE_MODEL_NAME` (Task 1), any schema corrections identified in Task 3.
- Produces: `HelmRelease` named `holmesgpt` in namespace `ai`, deploying the `robusta/holmes` chart with the base HTTP API service + bundled Operator.

- [x] **Step 1: Write the HelmRelease**

Create `kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml`. Replace `<OMNIROUTE_MODEL_NAME>` with the value discovered in Task 1, Step 2, and adjust any keys flagged as mismatched in Task 3:

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: &app holmesgpt
spec:
  interval: 1h
  chart:
    spec:
      chart: holmes
      version: "0.38.1"
      sourceRef:
        kind: HelmRepository
        name: robusta
        namespace: flux-system
  install:
    crds: CreateReplace
    remediation:
      retries: 3
  upgrade:
    crds: CreateReplace
    cleanupOnFail: true
    remediation:
      retries: 3
  values:
    # Bundled Operator (HealthCheck / ScheduledHealthCheck / TriggeredHealthCheck
    # CRDs + controller). No HealthCheck resources are created in this pass —
    # just the controller, to prove the deployment path.
    operator:
      enabled: true

    # Disable the Robusta SaaS-backed toolset — this cluster has no Robusta
    # account, and leaving it enabled just produces noisy "not configured"
    # log lines at startup.
    toolsets:
      robusta:
        enabled: false

    # LLM backend: omniroute's in-cluster OpenAI-compatible endpoint.
    # api_key is rewritten by the chart at render time from `envRef:VAR` to
    # the runtime `{{ env.VAR }}` template — VAR must be present via
    # extraEnvVarsSecrets below.
    extraEnvVarsSecrets:
      - holmesgpt-secrets
    modelList:
      omniroute:
        model: openai/<OMNIROUTE_MODEL_NAME>
        api_base: http://omniroute.ai.svc.cluster.local:20129/v1
        api_key: envRef:OMNIROUTE_API_KEY

    resources:
      requests:
        cpu: 100m
        memory: 2048Mi
      limits:
        memory: 2048Mi
```

- [x] **Step 2: Validate the full app renders**

```bash
kustomize build kubernetes/apps/ai/holmesgpt/app
```

Expected: renders a `Secret`, a `HelmRelease`, with no kustomize errors. (This validates YAML structure and kustomize wiring — it does NOT validate the Helm chart's own template logic, since `kustomize build` doesn't invoke Helm for `HelmRelease` objects; that happens at Flux reconcile time in Task 7.)

- [x] **Step 3: Flux-level dry-run validation**

```bash
flux build kustomization holmesgpt --path kubernetes/apps/ai/holmesgpt --dry-run
```

Expected: no schema errors. If this fails on an unrecognized `values` key, go back to Task 3's diff output and correct the key name/structure in Step 1 above.

- [x] **Step 4: Commit**

```bash
git add kubernetes/apps/ai/holmesgpt/app/helmrelease.yaml
git commit -m "feat(ai): deploy HolmesGPT via robusta/holmes chart, wired to omniroute"
```

If Task 4's commit was deferred, combine it with this one: `git add kubernetes/apps/ai/holmesgpt/ kubernetes/apps/ai/kustomization.yaml` before committing.

---

### Task 7: Deploy and smoke-test

**Files:** none (runtime verification only).

**Interfaces:**
- Consumes: everything from Tasks 2–6, once pushed and reconciled.

- [x] **Step 1: Push and force reconcile**

```bash
git push
task flux:reconcile-ks name=holmesgpt
```

Expected: command completes without error.

- [x] **Step 2: Confirm the pods come up healthy**

```bash
kubectl -n ai get pods -l app.kubernetes.io/instance=holmesgpt
```

Expected: both the main `holmes` pod and the `holmes-operator` pod reach `Running`/`1/1 Ready` within a few minutes. If a pod crash-loops, check:

```bash
kubectl -n ai logs -l app.kubernetes.io/instance=holmesgpt --all-containers --prefix
```

Common failure modes to check for: `401`/`403` from omniroute (bad or missing `OMNIROUTE_API_KEY` — re-verify Task 1/5), or a connection refused to `omniroute.ai.svc.cluster.local:20129` (confirm the omniroute Service actually exposes port `20129` as its `api` port — re-check `kubernetes/apps/ai/omniroute/app/helmrelease.yaml`'s `service.app.ports` block if this errors).

- [x] **Step 3: Smoke-test an actual investigation**

First find the actual Service name (Helm's fullname template may produce `holmesgpt-holmes`, `holmesgpt`, or something else depending on how the chart's `_helpers.tpl` combines release+chart name — don't assume):

```bash
kubectl -n ai get svc -l app.kubernetes.io/instance=holmesgpt
```

Then port-forward to whatever that command reports (substitute `<SERVICE_NAME>` below):

```bash
kubectl -n ai port-forward svc/<SERVICE_NAME> 8080:80
```

In a second terminal:

```bash
curl -s -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"ask": "Is the ai namespace healthy? List any pods not in Running state."}' | head -c 2000
```

Expected: a JSON response containing an actual investigation result referencing real cluster state (not an auth error, not an empty/error body). This is the real pass/fail signal for the whole POC — if this doesn't come back with a coherent, cluster-aware answer, the deployment technically succeeded but the tool itself isn't proven useful yet.

- [x] **Step 4: Record the outcome**

No code change — this step is a decision point, not an implementation step. Report back (to the user, or as a beads update on `home-ops-4rm`) whether Step 3's response was useful, and note it in `home-ops-4rm` either way — that's what determines whether the deferred bifrost/chaski/Discord work in `bifrost-a7g` gets picked back up.
