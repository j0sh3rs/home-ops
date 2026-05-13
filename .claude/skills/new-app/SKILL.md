---
name: new-app
description: Scaffold a new Flux app under kubernetes/apps/{namespace}/{app}/ using the OCIRepository + chartRef pattern (NOT legacy HelmRepository + sourceRef). Handles bjw-s app-template wiring, namespace kustomization entry, and kustomize build verification. Use when user says "new app", "scaffold app", "add app", or invokes /new-app.
---

# new-app (home-ops)

Scaffold a new Flux-managed application. Enforces repo conventions — blocks legacy `chart.spec.sourceRef` pattern. Every new app must use `OCIRepository` + `chartRef`.

## Usage

- `/new-app` — prompt for inputs interactively
- `/new-app <namespace>/<app>` — start with target known
- Auto-trigger: user asks to add/scaffold/create a new application

## Required inputs (ask if missing)

1. **namespace** — one of `cert-manager`, `databases`, `flux-system`, `kube-system`, `monitoring`, `network`, `security`, `services`, `system-upgrade`, `velero`. Reject other values.
2. **app name** — kebab-case, matches directory + HelmRelease name
3. **chart shape** — pick one:
   - **a. Upstream OCI chart** (preferred): user provides `oci://ghcr.io/...` URL + semver tag
   - **b. bjw-s app-template**: reuse shared OCIRepository (`kubernetes/components/repos/app-template`)
   - **c. HelmRepository fallback** — ONLY if upstream publishes no OCI artifact. Flag loudly and require user confirmation.
4. **externally exposed?** — if yes, ask hostname + OIDC protection (yes/no) + internal vs external gateway

## Workflow

### Stage 1 — guardrails

```bash
# Namespace must already exist in kustomization structure
test -d kubernetes/apps/<ns> || { echo "Namespace dir missing. Create it first via an explicit request."; exit 2 }
# App must not already exist
test ! -d kubernetes/apps/<ns>/<app> || { echo "App dir already exists."; exit 2 }
```

### Stage 2 — verify OCI availability (if user picked shape 'a' or hasn't chosen yet)

Check GHCR / Docker Hub for an OCI-published chart before writing anything.

```bash
# Probe common GHCR locations
curl -sfLI "https://ghcr.io/v2/<org>/charts/<app>/manifests/<tag>" >/dev/null 2>&1 && echo "OCI available" || echo "No OCI at that URL"
```

If upstream only publishes traditional HelmRepository, STOP, surface this, ask user explicitly: "Upstream has no OCI chart. Proceed with HelmRepository pattern knowing it's legacy? (y/N)".

### Stage 3 — ensure namespace opt-in for shared repos

If shape is **bjw-s app-template**:

```bash
grep -q "components/repos/app-template" kubernetes/apps/<ns>/kustomization.yaml || \
  echo "Namespace <ns> not opted into app-template. Must add '../../components/repos/app-template' to its components: list."
```

Do not silently mutate the namespace kustomization — prompt the user and edit only after confirmation.

### Stage 4 — render files

Create three files (four if secrets needed). Minimal, atomic.

**`kubernetes/apps/<ns>/<app>/ks.yaml`**:
```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app <app>
  namespace: &namespace <ns>
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  path: ./kubernetes/apps/<ns>/<app>/app
  prune: true
  retryInterval: 2m
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: *namespace
  timeout: 5m
  wait: false
```

**`kubernetes/apps/<ns>/<app>/app/kustomization.yaml`**:
```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
# Append ./secret.sops.yaml only if secrets required
```

**`kubernetes/apps/<ns>/<app>/app/helmrelease.yaml`** — pick template by shape:

**Shape (a) — upstream OCI chart** (dedicated OCIRepository per app, lives in same dir):
```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: &app <app>
spec:
  interval: 12h
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    # renovate: datasource=docker depName=<repo-path>
    tag: <semver>
  url: oci://<registry-path>
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: *app
spec:
  interval: 1h
  timeout: 10m
  chartRef:
    kind: OCIRepository
    name: *app
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  values: {}
```
Add `./ocirepository.yaml` entry if user prefers a separate file — matches existing app-template component pattern.

**Shape (b) — bjw-s app-template**:
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: &app <app>
spec:
  interval: 1h
  timeout: 10m
  chartRef:
    kind: OCIRepository
    name: app-template
    namespace: flux-system
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  values:
    controllers:
      <app>:
        replicas: 1
        strategy: RollingUpdate
        containers:
          app:
            image:
              repository: <image-repo>
              # renovate: datasource=docker depName=<image-repo>
              tag: <tag>
            env: {}
            resources:
              requests:
                cpu: 10m
                memory: 64Mi
              limits:
                memory: 256Mi
    service:
      app:
        controller: <app>
        ports:
          http:
            port: &port 80
```

### Stage 5 — wire namespace kustomization

Append `- ./<app>/ks.yaml` to `kubernetes/apps/<ns>/kustomization.yaml` `resources:` list. Preserve sort order (alphabetical when possible).

### Stage 6 — verify before handoff

```bash
kustomize build kubernetes/apps/<ns>/<app>/app
kustomize build kubernetes/apps/<ns>
flux build kustomization <app> --path kubernetes/apps/<ns>/<app>/app --dry-run 2>&1 | tail -20
```

All three must succeed. Any error → fix before handing control back.

### Stage 7 — remind user

Single-line reminder:

> Scaffolded `<ns>/<app>`. Renovate will track `<tag>` via the comment. To deploy: commit + push + `task flux:reconcile-ks name=<app>`.

## Non-negotiable rules

- **NEVER** emit `chart.spec.sourceRef` with `HelmRepository` for a new app — always `OCIRepository` + `chartRef`. If user absolutely requires HelmRepository fallback, require explicit written confirmation and add a TODO comment in the file marking it for OCI migration.
- **NEVER** hardcode `tag: latest` — require semver. If upstream has no semver, document why inline and Renovate will still pin digest.
- **NEVER** skip the Renovate comment above `tag:`.
- **NEVER** set `resources.limits.cpu` — repo convention (CPU throttling). Memory limit REQUIRED; CPU+memory requests REQUIRED.
- **NEVER** modify the namespace kustomization without first showing the diff and asking.
- **NEVER** create `Secret` manifests outside `*.sops.yaml` files.

## When NOT to use

- Modifying an existing app → use Edit directly
- Chart version bump → Renovate handles
- Migrating legacy sourceRef app → use `migrate-to-oci` skill instead
- New namespace creation — out of scope; needs cluster-apps.yaml + components wiring which is a bigger change
