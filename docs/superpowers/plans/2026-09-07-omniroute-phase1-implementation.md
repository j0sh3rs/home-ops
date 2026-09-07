# Omniroute Phase 1 (Parallel Install) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up Omniroute in `kubernetes/apps/ai/omniroute/` alongside the
existing LiteLLM gateway, and prove it's controllable as code (git) and via
its own MCP server — without touching LiteLLM or any consumer.

**Architecture:** bjw-s app-template, one Deployment / two containers in one
pod (`app`, `cliproxyapi`), two PVCs (`omniroute-data`, `cliproxyapi-data`),
DragonflyDB db1 for the rate limiter, HTTPRoute on
`traefik-external-gateway`. All static config lives in a SOPS-encrypted
Secret; all interactive-login state lives on PVCs covered by Velero's
default backup.

> **Correction (2026-09-07, post Task 6 live-deploy validation):** this plan
> originally specified a third `codex-app-server` container. Task 6's
> deploy found it crash-looping (`codex: not found`) — root-caused to the
> `codex` CLI only existing in Omniroute's unpublished `runner-cli` build
> target, not the published bare image this plan uses. Reverted to the
> design spec's original architecture: CLIProxyAPI handles both Claude Code
> and Codex via its own native OAuth flows. Task 6's `cliproxyapi`
> crash-loop was a second, unrelated bug (wrong hardcoded binary path) — also
> fixed. See the design spec's "Corrections found during Task 6 validation"
> section and this plan's SDD ledger for full root-cause detail. Task 3 and
> Task 10 below are updated in place to reflect the corrected 2-container
> design — treat this document as authoritative over the original Task 3
> commit's now-superseded 3-container HelmRelease.

**Tech Stack:** Flux (HelmRelease/Kustomization), bjw-s app-template v5.1.0,
SOPS+age, DragonflyDB (Redis-compatible), Omniroute 3.8.50, CLIProxyAPI
v6.9.7.

**Spec:** `docs/superpowers/specs/2026-09-07-omniroute-revival-design.md`
(read this first — this plan implements its Phase 1 section only).

## Global Constraints

- Image tags are pinned exactly: `docker.io/diegosouzapw/omniroute:3.8.50`
  (plain, no `-web`) and `docker.io/eceasy/cli-proxy-api:v6.9.7` (the
  version OmniRoute's own reference `docker-compose.yml` targets — not the
  Docker Hub "latest", which may be ahead of what's tested against this
  Omniroute release).
- CLIProxyAPI covers **Claude Code and Codex only** — Copilot is dropped
  (upstream doesn't support it; see spec "Correction" section). Both Claude
  Code and Codex use CLIProxyAPI's own native OAuth flows
  (`--claude-login`, `--codex-login`/`--codex-device-login`) in the same
  sidecar — no separate `codex-app-server` mechanism (reverted, see
  Correction note above).
- Nothing may exist only as unbacked, dashboard-only state: static config →
  SOPS Secret (git), interactive-login state → PVC (Velero-covered, no
  exclusion label).
- Do NOT touch `kubernetes/apps/ai/litellm/`, `litellm-operator`, or any
  consumer (`openclaw`, `openviking`, `argus`) in this plan — that's Phase 2.
- Namespace `ai` already has PodSecurity `privileged` (see
  `kubernetes/apps/ai/kustomization.yaml` patch) and the `app-template`
  component — no new namespace-level changes needed.

---

### Task 1: DragonflyDB db1 allocation + runbook update

**Files:**
- Modify: `docs/runbooks/dragonflydb-db-allocation.md:16` (allocation table
  row for db1)

**Interfaces:**
- Produces: the `REDIS_URL` value `redis://:<password>@dragonflydb.databases.svc.cluster.local:6379/1`
  that Task 3's Secret consumes.

- [ ] **Step 1: Update the allocation table row for db1**

Change this row in `docs/runbooks/dragonflydb-db-allocation.md`:

```markdown
| 1 | _free_ | — | Formerly OmniRoute rate limiter — freed 2026-08-14 (OmniRoute removed, cloud-gateway layer dropped in favor of llama-swap direct). | — |
```

to:

```markdown
| 1 | Omniroute | `ai/omniroute` | Distributed rate limiter (Redis backend, per Omniroute's own compose reference). Reassigned 2026-09-07 (Omniroute revival, Phase 1 — see `docs/superpowers/specs/2026-09-07-omniroute-revival-design.md`). Redis URL: `redis://...:6379/1`. | `kubernetes/apps/ai/omniroute/app/helmrelease.yaml` |
```

- [ ] **Step 2: Verify db1 is actually empty before claiming it**

Run:
```bash
PASS=$(rtk kubectl get secret -n databases dragonflydb-auth -o jsonpath='{.data.password}' --context home | base64 -d)
rtk kubectl run -n databases df-check-db1 --rm -i --restart=Never --image=redis:7-alpine --context home -- \
  redis-cli -h dragonflydb.databases.svc.cluster.local -p 6379 -a "$PASS" -n 1 DBSIZE
```
Expected: `(integer) 0` (confirms nothing is silently using db1 already).

- [ ] **Step 3: Commit**

```bash
git add docs/runbooks/dragonflydb-db-allocation.md
git commit -m "docs(ai): reassign DragonflyDB db1 to Omniroute (Phase 1 revival)"
```

---

### Task 2: SOPS secret — static config + CLIProxyAPI config file

**Files:**
- Create: `kubernetes/apps/ai/omniroute/app/secret.sops.yaml`

**Interfaces:**
- Consumes: DragonflyDB password from Task 1's `REDIS_URL` (read live from
  cluster, not hardcoded), Reflector-mirrored `dragonflydb-auth` Secret
  already present in `ai` namespace (confirmed — `litellm` already consumes
  it the same way).
- Produces: Secret `omniroute-secrets` with keys `JWT_SECRET`,
  `API_KEY_SECRET`, `INITIAL_PASSWORD`, `OMNIROUTE_WS_BRIDGE_SECRET`,
  `REDIS_URL`, `CLIPROXYAPI_CONFIG` (the CLIProxyAPI `config.yaml` content,
  mounted via `subPath` in Task 3's HelmRelease). Task 6 later adds an
  `OMNIROUTE_MGMT_TOKEN` key once the scoped access token can be minted
  (can't exist before the app runs — not a placeholder, a real ordering
  constraint, tracked explicitly here so it isn't forgotten).

- [ ] **Step 1: Generate the four Omniroute secrets locally (never commit plaintext)**

```bash
openssl rand -hex 32   # JWT_SECRET
openssl rand -hex 32   # API_KEY_SECRET
openssl rand -hex 24   # OMNIROUTE_WS_BRIDGE_SECRET
openssl rand -base64 24 | tr -d '=+/'   # INITIAL_PASSWORD (dashboard login)
```

- [ ] **Step 2: Get the DragonflyDB password and build REDIS_URL**

```bash
PASS=$(rtk kubectl get secret -n databases dragonflydb-auth -o jsonpath='{.data.password}' --context home | base64 -d)
python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$PASS"
```
Build `REDIS_URL=redis://:<url-encoded-password>@dragonflydb.databases.svc.cluster.local:6379/1`
— per the runbook's connection invariants, never quote the password, always
URL-encode it.

- [ ] **Step 3: Write the plaintext secret file, then use the sops-edit-then-encrypt skill**

Write `kubernetes/apps/ai/omniroute/app/secret.sops.yaml`:

```yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: omniroute-secrets
stringData:
  JWT_SECRET: "<generated>"
  API_KEY_SECRET: "<generated>"
  INITIAL_PASSWORD: "<generated>"
  OMNIROUTE_WS_BRIDGE_SECRET: "<generated>"
  REDIS_URL: "redis://:<url-encoded-password>@dragonflydb.databases.svc.cluster.local:6379/1"
  cliproxy-config.yaml: |
    host: ""
    port: 8317
    tls:
      enable: false
      cert: ""
      key: ""
    remote-management:
      allow-remote: false
      secret-key: "<generated: openssl rand -hex 32>"
      disable-control-panel: false
    auth-dir: "/root/.cli-proxy-api"
    api-keys:
      - "<generated: openssl rand -hex 32, this is what the omniroute app container uses to call the cliproxyapi sidecar>"
    debug: false
    pprof:
      enable: false
```

Then invoke the `sops-edit-then-encrypt` skill (or manually run
`task sops:encrypt-file file=kubernetes/apps/ai/omniroute/app/secret.sops.yaml`)
to encrypt it in place before it ever touches git history.

- [ ] **Step 4: Verify encryption**

```bash
task sops:verify
```
Expected: `kubernetes/apps/ai/omniroute/app/secret.sops.yaml` listed with ✅.

- [ ] **Step 5: Commit**

```bash
git add kubernetes/apps/ai/omniroute/app/secret.sops.yaml
git commit -m "feat(ai): add omniroute-secrets (Phase 1 scaffold)"
```

---

### Task 3: HelmRelease — app-template with app + cliproxyapi (CORRECTED 2026-09-07)

> This task was originally executed with a third `codex-app-server`
> container (commit `f4ec1b2b`). Task 6's live deploy found it and the
> `cliproxyapi` container both crash-looping — root-caused in the SDD
> ledger and the design spec's "Corrections found during Task 6
> validation" section (fix round 1, commit `89dd0ab0`). A second Task 6
> retry then found a THIRD bug — `cliproxyapi`'s probes hit an
> auth-gated path — fixed in fix round 2 (probes below already reflect
> the corrected `path: /` target). The content below is the fully
> corrected version; it's what actually gets applied as a fix to the
> already-committed `helmrelease.yaml`, not a from-scratch file.

**Files:**
- Modify: `kubernetes/apps/ai/omniroute/app/helmrelease.yaml` (already
  exists from the original Task 3 commit — apply the corrections below to it)

**Interfaces:**
- Consumes: Secret `omniroute-secrets` (Task 2), OCIRepository `app-template`
  (already materialized in `ai` namespace via the `repos/app-template`
  Component — same pattern as `llama-swap`).
- Produces: Service `omniroute` (ports 20128 dashboard, 20129 API, 20132
  live-ws), internal-only Service reachable at
  `omniroute.ai.svc.cluster.local` for Task 6's connectivity check; PVCs
  `omniroute-data`, `cliproxyapi-data` only (the `codex-appserver-token`/
  `codex-appserver-home` PVCs and their mounts are removed entirely).

- [ ] **Step 1: Apply these corrections to the existing HelmRelease**

Three changes to `kubernetes/apps/ai/omniroute/app/helmrelease.yaml`:

1. Remove these two env vars from the `app` container (no `codex-app-server`
   to talk to anymore):
   ```yaml
   OMNIROUTE_CODEX_APPSERVER_WS: "ws://127.0.0.1:1456"
   OMNIROUTE_CODEX_APPSERVER_WS_TOKEN_FILE: /run/codex-appserver/token
   ```

2. On the `cliproxyapi` container: remove the `command`/`args` override
   entirely — delete these two lines:
   ```yaml
   command: ["/cli-proxy-api"]
   args: ["--config", "/CLIProxyAPI/config.yaml"]
   ```
   The image's own default `CMD ["./CLIProxyAPI"]` (run from `WORKDIR
   /CLIProxyAPI`) already finds `config.yaml` in its working directory with
   no flag needed — confirmed by reading `router-for-me/CLIProxyAPI`'s
   actual `Dockerfile` and `cmd/server/main.go`'s config-path fallback
   logic. Also update the image tag comment/pin: it should already read
   `tag: v6.9.7` (Renovate may have auto-bumped it since the original
   commit — check the live value and re-pin to `v6.9.7` if it drifted,
   since the crash was path-related, not version-related, but this plan's
   Global Constraints still call for the specific tested version).

3. Remove the entire `codex-app-server` container block (the whole
   `codex-app-server:` entry under `containers:`, everything from its
   `image:` through its `resources:` block).

4. Remove the `codex-appserver-token` and `codex-appserver-home` entries
   entirely from `persistence:` (both the top-level entries and their
   `advancedMounts` references under `app:`).

The resulting file's `containers:` section should contain exactly `app` and
`cliproxyapi` (no `codex-app-server`), and `persistence:` should contain
exactly `data`, `cliproxyapi-data`, and `cliproxy-config` (no
`codex-appserver-*` entries). Everything else (ports, probes, resources,
service block) stays as originally written.

For reference, here is the corrected `containers:` and `persistence:`
content in full (use this as the source of truth over the step-by-step
diff instructions above if there's ever ambiguity):

```yaml
---
# yamllint disable rule:line-length
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: &app omniroute
spec:
  interval: 1h
  chartRef:
    kind: OCIRepository
    name: app-template
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  values:
    global:
      annotations:
        reloader.stakater.com/auto: "true"

    controllers:
      omniroute:
        annotations:
          reloader.stakater.com/auto: "true"

        pod:
          securityContext:
            fsGroup: 1000

        containers:
          app:
            image:
              repository: docker.io/diegosouzapw/omniroute
              # renovate: datasource=docker depName=diegosouzapw/omniroute versioning=semver
              tag: 3.8.50
              pullPolicy: IfNotPresent
            env:
              DATA_DIR: /app/data
              PORT: &dashboardPort "20128"
              DASHBOARD_PORT: *dashboardPort
              API_PORT: &apiPort "20129"
              API_HOST: "0.0.0.0"
              LIVE_WS_PORT: &liveWsPort "20132"
              LIVE_WS_HOST: "0.0.0.0"
              LIVE_WS_ALLOWED_ORIGINS: "https://omniroute.68cc.io"
              NODE_ENV: production
              NODE_OPTIONS: "--max-old-space-size=2048"
              CLIPROXYAPI_HOST: "127.0.0.1"
              CLIPROXYAPI_PORT: "8317"
            envFrom:
              - secretRef:
                  name: omniroute-secrets
            resources:
              requests:
                cpu: 200m
                memory: 512Mi
              limits:
                cpu: "2"
                memory: 2Gi
            probes:
              # Upstream's own compose healthcheck is `node healthcheck.mjs`
              # (an exec script, not an HTTP path) — confirmed by reading
              # both docker-compose.yml and docker-compose.prod.yml.
              liveness:
                enabled: true
                custom: true
                spec:
                  exec:
                    command: ["node", "healthcheck.mjs"]
                  initialDelaySeconds: 30
                  periodSeconds: 15
                  failureThreshold: 4
              readiness:
                enabled: true
                custom: true
                spec:
                  exec:
                    command: ["node", "healthcheck.mjs"]
                  initialDelaySeconds: 15
                  periodSeconds: 10
                  successThreshold: 2
              startup:
                enabled: true
                custom: true
                spec:
                  exec:
                    command: ["node", "healthcheck.mjs"]
                  failureThreshold: 30
                  periodSeconds: 10

          cliproxyapi:
            image:
              repository: docker.io/eceasy/cli-proxy-api
              # renovate: datasource=docker depName=eceasy/cli-proxy-api versioning=semver
              tag: v6.9.7
              pullPolicy: IfNotPresent
            # No command/args override — the image's own default
            # CMD ["./CLIProxyAPI"] (run from WORKDIR /CLIProxyAPI) already
            # finds config.yaml in its working directory with no flag
            # needed. An earlier version of this file hardcoded
            # command: ["/cli-proxy-api"], a fabricated path that doesn't
            # exist in the image (real binary: /CLIProxyAPI/CLIProxyAPI) —
            # confirmed by reading router-for-me/CLIProxyAPI's Dockerfile
            # and cmd/server/main.go's config-path fallback directly. Don't
            # reintroduce a command override here.
            resources:
              requests:
                cpu: 100m
                memory: 256Mi
              limits:
                cpu: "1"
                memory: 1Gi
            probes:
              # GET / — NOT /v1/models. /v1 requires an API key once real
              # api-keys are configured (always, by design, since
              # cliproxyapi's Service is cluster-reachable, not just
              # pod-local). GET / is registered outside any auth group at
              # our pinned v6.9.7 (confirmed via source read of
              # internal/api/server.go — /healthz doesn't exist at this
              # version, only on newer releases; don't "fix" this by
              # switching to /healthz without also bumping the pin).
              liveness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /
                    port: 8317
                  initialDelaySeconds: 20
                  periodSeconds: 15
                  failureThreshold: 4
              readiness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /
                    port: 8317
                  initialDelaySeconds: 10
                  periodSeconds: 10

    service:
      app:
        forceRename: *app
        controller: *app
        ports:
          http:
            port: 20128
          api:
            port: 20129
          livews:
            port: 20132
      cliproxyapi:
        controller: *app
        ports:
          http:
            port: 8317

    persistence:
      data:
        type: persistentVolumeClaim
        storageClass: openebs-hostpath
        accessMode: ReadWriteOnce
        size: 10Gi
        retain: true
        advancedMounts:
          omniroute:
            app:
              - path: /app/data
      cliproxyapi-data:
        type: persistentVolumeClaim
        storageClass: openebs-hostpath
        accessMode: ReadWriteOnce
        size: 1Gi
        retain: true
        advancedMounts:
          omniroute:
            cliproxyapi:
              - path: /root/.cli-proxy-api
      cliproxy-config:
        type: secret
        name: omniroute-secrets
        advancedMounts:
          omniroute:
            cliproxyapi:
              - path: /CLIProxyAPI/config.yaml
                subPath: cliproxy-config.yaml
                readOnly: true
```

- [ ] **Step 2: Validate**

Tasks 4/5 already exist and are deployed (this is a post-deploy fix, not the
original from-scratch sequencing) — run the full validation immediately:

```bash
kustomize build kubernetes/apps/ai/omniroute/app | kubectl apply --dry-run=client -f -
flux build kustomization omniroute -n ai --kustomization-file kubernetes/apps/ai/omniroute/ks.yaml --path kubernetes/apps/ai/omniroute/app --dry-run
```
(Note the corrected `flux build` invocation — the plan's original Task 5
text used a flag combination that didn't match the installed flux2 CLI
version; this is the working form, recorded in the SDD ledger.)

- [ ] **Step 3: Commit**

```bash
git add kubernetes/apps/ai/omniroute/app/helmrelease.yaml
git commit -m "fix(ai): drop unbuildable codex-app-server, fix cliproxyapi command

codex-app-server required the unpublished runner-cli Omniroute image
build target (codex CLI only exists there, not in the published bare
image) -- reverts to the design spec's original 2-container
architecture, CLIProxyAPI handles both Claude Code and Codex via its
own native OAuth flows. Also fixes cliproxyapi's command override,
which hardcoded a fabricated binary path (/cli-proxy-api) instead of
the real one (/CLIProxyAPI/CLIProxyAPI) -- removed the override
entirely since the image's own default CMD already resolves config.yaml
correctly from its working directory."
```

---

### Task 4: Kustomization + Flux Kustomization (ks.yaml) + HTTPRoute

**Files:**
- Create: `kubernetes/apps/ai/omniroute/app/kustomization.yaml`
- Create: `kubernetes/apps/ai/omniroute/app/httproute.yaml`
- Create: `kubernetes/apps/ai/omniroute/ks.yaml`

**Interfaces:**
- Consumes: `omniroute-secrets` (Task 2), `omniroute` HelmRelease (Task 3).
- Produces: Flux Kustomization `omniroute` in namespace `ai`, dependent on
  `dragonflydb-instance` (databases) — no dependency on `llama-swap` in
  Phase 1 since local-provider wiring (Task 8) happens after deploy, not as
  a hard Flux dependency.

- [ ] **Step 1: Write `app/kustomization.yaml`**

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./secret.sops.yaml
  - ./helmrelease.yaml
  - ./httproute.yaml
```

- [ ] **Step 2: Write `app/httproute.yaml`**

```yaml
---
# External access for the dashboard + CLI OAuth login redirect flows.
# authentik-forwardauth gates it (same pattern as every other external
# route in this cluster) — Omniroute's own INITIAL_PASSWORD login sits
# behind that.
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: omniroute
  annotations:
    external-dns.alpha.kubernetes.io/target: 192.168.35.15
spec:
  hostnames:
    - omniroute.68cc.io
  parentRefs:
    - name: traefik-external-gateway
      namespace: network
  rules:
    - filters:
        - type: ExtensionRef
          extensionRef:
            group: traefik.io
            kind: Middleware
            name: authentik-forwardauth
      backendRefs:
        - name: omniroute
          port: 20128
```

- [ ] **Step 3: Write `ks.yaml`**

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app omniroute
  namespace: &namespace ai
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  dependsOn:
    - name: dragonflydb-instance
      namespace: databases
  path: ./kubernetes/apps/ai/omniroute/app
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

- [ ] **Step 4: Commit**

```bash
git add kubernetes/apps/ai/omniroute/app/kustomization.yaml kubernetes/apps/ai/omniroute/app/httproute.yaml kubernetes/apps/ai/omniroute/ks.yaml
git commit -m "feat(ai): add omniroute kustomization/httproute/ks (Phase 1 scaffold)"
```

---

### Task 5: Wire into `ai/kustomization.yaml`, validate, confirm Velero coverage

**Files:**
- Modify: `kubernetes/apps/ai/kustomization.yaml:32-43` (add `./omniroute/ks.yaml`
  to `resources`, update the top comment block)

**Interfaces:**
- Consumes: `kubernetes/apps/ai/omniroute/ks.yaml` (Task 4).
- Produces: nothing new — this is the point where Flux picks up the app.

- [ ] **Step 1: Add the resource entry**

In `kubernetes/apps/ai/kustomization.yaml`, change:

```yaml
resources:
  # - ./argus/ks.yaml
  - ./atuin-ai-server/ks.yaml
  - ./faster-whisper/ks.yaml
  - ./holyclaude/ks.yaml
  - ./litellm/ks.yaml
  - ./litellm-operator/ks.yaml
  - ./llama-swap/ks.yaml
  - ./llama-swap-apu/ks.yaml
  # - ./openclaw/ks.yaml
  - ./openviking/ks.yaml
  - ./piper/ks.yaml
```

to (adding the new line, alphabetically placed):

```yaml
resources:
  # - ./argus/ks.yaml
  - ./atuin-ai-server/ks.yaml
  - ./faster-whisper/ks.yaml
  - ./holyclaude/ks.yaml
  - ./litellm/ks.yaml
  - ./litellm-operator/ks.yaml
  - ./llama-swap/ks.yaml
  - ./llama-swap-apu/ks.yaml
  - ./omniroute/ks.yaml
  # - ./openclaw/ks.yaml
  - ./openviking/ks.yaml
  - ./piper/ks.yaml
```

Also update the top-of-file comment (lines 9-11) — remove `omniroute` from
the "remain removed 2026-08-14" list and note the Phase 1 revival with a
pointer to the spec, since that comment is what a future reader trusts.

- [ ] **Step 2: Validate with kustomize build**

```bash
kustomize build kubernetes/apps/ai/omniroute/app | kubectl apply --dry-run=client -f -
kustomize build kubernetes/apps/ai | grep -A2 "kind: Kustomization" | grep omniroute
```
Expected: both commands succeed with no errors, and the second confirms
`omniroute` appears in the rendered namespace kustomization.

- [ ] **Step 3: Validate with flux build --dry-run**

```bash
flux build kustomization omniroute --path kubernetes/apps/ai/omniroute --dry-run
```
Expected: renders without error (this will fail if the HelmRelease values
don't match the app-template chart schema — fix and re-run before
proceeding, do not commit a HelmRelease that doesn't render).

- [ ] **Step 4: Confirm Velero does NOT exclude the new PVCs**

```bash
grep -c "omniroute" kubernetes/apps/velero/exclusions/app/pvc-exclusions.yaml
```
Expected: `0` (grep finds nothing) — the four Omniroute PVCs
(`omniroute-data`, `cliproxyapi-data`, `codex-appserver-token`,
`codex-appserver-home`) must NOT appear here, so the daily wildcard backup
covers them by default. This is the explicit config-as-code/backup
requirement from the design spec — do not add an exclusion "to be safe."

- [ ] **Step 5: Commit**

```bash
git add kubernetes/apps/ai/kustomization.yaml
git commit -m "feat(ai): wire omniroute into ai namespace kustomization"
```

---

### Task 6: Deploy and validate connectivity

**Files:** none (operational task — reconcile + verify a live cluster)

**Interfaces:**
- Consumes: everything from Tasks 1-5, once pushed and reconciled.

- [ ] **Step 1: Push and reconcile**

```bash
git push
task flux:reconcile-ks name=omniroute ns=ai
```

- [ ] **Step 2: Watch rollout**

```bash
rtk kubectl get pods -n ai -l app.kubernetes.io/name=omniroute -w
```
Expected: pod reaches `2/2 Running` (app, cliproxyapi).
If it doesn't, check `rtk kubectl describe pod -n ai <pod>` and
`rtk kubectl logs -n ai <pod> -c <container>` before proceeding — do not
move to Step 3 with a crashing pod.

- [ ] **Step 3: Confirm dashboard, `/v1`, and `/health`-equivalent reachable**

```bash
rtk kubectl exec -n ai deploy/omniroute -c omniroute -- node healthcheck.mjs; echo "exit: $?"
curl -sk https://omniroute.68cc.io/ -o /dev/null -w "%{http_code}\n"
curl -sk https://omniroute.68cc.io/v1/models -o /dev/null -w "%{http_code}\n"
```
Expected: `exit: 0`, and both curl calls return `200` or `401`/`403` (auth
required is fine — that confirms the endpoint is live and gated, not that
it's broken). A `502`/`connection refused` means the route or Service is
misconfigured — fix before continuing.

- [ ] **Step 4: Confirm CLIProxyAPI sidecar reachable internally**

```bash
rtk kubectl exec -n ai deploy/omniroute -c omniroute -- wget -q -O- http://127.0.0.1:8317/v1/models
```
Expected: a JSON response (empty model list is fine — no CLI accounts
logged in yet, that's Task 9).

---

### Task 7: MCP endpoint — mint scoped access token, register client config

**Files:**
- Modify: `kubernetes/apps/ai/omniroute/app/secret.sops.yaml` (add
  `OMNIROUTE_MGMT_TOKEN` — actually this token lives in the MCP client
  config, not the app's own env; see Step 3)
- Create: `.mcp.json` at repo root (or modify if one already exists — check
  first with `ls -la /workspace/home-ops/.mcp.json`)

**Interfaces:**
- Consumes: Omniroute dashboard login (`INITIAL_PASSWORD` from Task 2's
  secret), live instance from Task 6.
- Produces: a `oma_live_...` scoped access token with `admin` scope, used
  by both the local Claude Code MCP registration and the repo-committed one.

- [ ] **Step 1: Log in to the dashboard and mint a scoped access token**

```bash
curl -sk -c /tmp/omniroute-cookies.txt -X POST https://omniroute.68cc.io/login \
  -H "Content-Type: application/json" \
  -d "{\"password\": \"<INITIAL_PASSWORD from omniroute-secrets>\"}"
```
Then, via Dashboard Settings → Access Tokens (browser, through the
authentik-forwardauth-gated route) or `omniroute connect` from a shell with
network access to the instance, generate a token with `admin` scope. Copy
the resulting `oma_live_...` value — treat it as a secret from this point on.

- [ ] **Step 2: Store the token in git (SOPS), not just locally**

Add to `kubernetes/apps/ai/omniroute/app/secret.sops.yaml`'s `stringData`:
```yaml
  OMNIROUTE_MGMT_TOKEN: "oma_live_<the token from Step 1>"
```
Re-encrypt via the `sops-edit-then-encrypt` skill, verify with
`task sops:verify`, commit.

- [ ] **Step 3: Confirm the MCP endpoint responds**

```bash
curl -sk https://omniroute.68cc.io/api/mcp/sse \
  -H "Authorization: Bearer oma_live_<token>" \
  -H "Accept: text/event-stream" --max-time 5
```
Expected: an SSE stream opens (curl will hang until `--max-time` cuts it —
that's success; a `401` or immediate connection close means the token/scope
is wrong).

- [ ] **Step 4: Register locally in this HolyClaude container**

Add to `~/.claude/settings.json` (or `.mcp.json` if that's the pattern this
container already uses — check first):
```json
{
  "mcpServers": {
    "omniroute": {
      "type": "sse",
      "url": "https://omniroute.68cc.io/api/mcp/sse",
      "headers": {
        "Authorization": "Bearer oma_live_<token>"
      }
    }
  }
}
```

- [ ] **Step 5: Register as a repo-committed project MCP config**

Create (or extend) `/workspace/home-ops/.mcp.json` with the same
`omniroute` entry, but reference the token via an env var placeholder
(`${OMNIROUTE_MCP_TOKEN}`) rather than the literal value, since this file
is git-tracked and NOT sops-encrypted:
```json
{
  "mcpServers": {
    "omniroute": {
      "type": "sse",
      "url": "https://omniroute.68cc.io/api/mcp/sse",
      "headers": {
        "Authorization": "Bearer ${OMNIROUTE_MCP_TOKEN}"
      }
    }
  }
}
```
Add `OMNIROUTE_MCP_TOKEN=oma_live_<token>` to the mise-loaded, gitignored
`.env.local` (already in `.mise.toml`'s `_.file` list — confirmed present).

- [ ] **Step 6: Commit**

```bash
git add kubernetes/apps/ai/omniroute/app/secret.sops.yaml .mcp.json
git commit -m "feat(ai): register omniroute MCP server (repo + local)"
```

---

### Task 8: Prove MCP-driven config control

**Files:** none (live validation)

- [ ] **Step 1: Restart the Claude Code session / reload MCP servers**

Confirm the `omniroute` MCP server's tools appear (check via whatever this
harness's MCP-tools listing shows after reconnect).

- [ ] **Step 2: Add a test provider/combo via an MCP tool call**

Use the `omniroute` MCP server's config-management tool (exact tool name
depends on what Omniroute's MCP server exposes — inspect the tool list
first) to add a throwaway test entry, e.g. a dummy OpenAI-compatible
provider pointed at `http://httpbin.org` with an obviously-fake name like
`phase1-mcp-test`.

- [ ] **Step 3: Confirm it persisted via the dashboard**

```bash
curl -sk https://omniroute.68cc.io/api/providers -H "Authorization: Bearer oma_live_<token>" | grep -i "phase1-mcp-test"
```
Expected: the test entry appears.

- [ ] **Step 4: Confirm it survives a pod restart (proves PVC-backed, not in-memory)**

```bash
rtk kubectl delete pod -n ai -l app.kubernetes.io/name=omniroute
rtk kubectl wait -n ai --for=condition=ready pod -l app.kubernetes.io/name=omniroute --timeout=120s
curl -sk https://omniroute.68cc.io/api/providers -H "Authorization: Bearer oma_live_<token>" | grep -i "phase1-mcp-test"
```
Expected: the entry is still there after the pod restart.

- [ ] **Step 5: Remove the test entry via MCP**

Use the MCP tool to delete `phase1-mcp-test`; confirm via the same curl
command that it's gone.

---

### Task 9: Configure local-provider slots mirroring llama-swap aliases

**Files:** none (dashboard/MCP-driven config, not git — this is exactly the
kind of state Task 7/8 proved lands on the PVC)

**Interfaces:**
- Consumes: `llama-swap.ai.svc.cluster.local:8080/v1` and
  `llama-swap-apu.ai.svc.cluster.local:8080/v1` (existing, unchanged).

- [ ] **Step 1: Add each of the 8 current LiteLLM model aliases as an Omniroute provider entry**

Via the MCP server (or dashboard, both land in the same PVC-backed store),
create OpenAI-compatible provider entries for each of:
`coder-large`, `frontier-chat`, `reasoner` (→
`http://llama-swap.ai.svc.cluster.local:8080/v1`), and `router`,
`embedding`, `chat`, `vlm`, `rerank` (→
`http://llama-swap-apu.ai.svc.cluster.local:8080/v1`) — matching the exact
model names in `kubernetes/apps/ai/litellm/app/models/llama-swap.yaml` and
`llama-swap-apu.yaml`. No API key needed (cluster-internal, matches
LiteLLM's `apiKey: "not-needed"` pattern) — use a placeholder value if
Omniroute's provider form requires a non-empty key.

- [ ] **Step 2: Confirm each alias resolves via Omniroute's `/v1` endpoint**

```bash
curl -sk https://omniroute.68cc.io/v1/chat/completions \
  -H "Authorization: Bearer <an inference API key minted in the dashboard>" \
  -H "Content-Type: application/json" \
  -d '{"model": "coder-large", "messages": [{"role": "user", "content": "reply with the word OK"}], "max_tokens": 5}'
```
Expected: a real completion response, not a 404/model-not-found. Repeat for
all 8 aliases. Note the exact addressing form Omniroute actually requires
(bare alias vs. `<provider>/<model>`) — this resolves the Phase 2 open item
about model-id addressing; record the answer in the design spec's "Open
items" section once confirmed.

---

### Task 10: OAuth login flows — Claude Code and Codex (both via CLIProxyAPI)

> Corrected 2026-09-07: Codex now goes through CLIProxyAPI's own
> `--codex-login`/`--codex-device-login` flags, same sidecar as Claude
> Code — the `codex-app-server` container this step originally referenced
> was dropped (see Task 3's correction note). Also: the binary path is
> `/CLIProxyAPI/CLIProxyAPI` (or `./CLIProxyAPI` from its own working
> directory), not `/cli-proxy-api` — the earlier draft of this task had the
> same fabricated-path bug Task 3's HelmRelease did.

**Files:** none (interactive login, PVC-backed session state)

- [ ] **Step 1: Claude Code login via CLIProxyAPI**

```bash
rtk kubectl port-forward -n ai deploy/omniroute 51234:8317 &
# CLIProxyAPI's --claude-login needs a reachable OAuth callback; --no-browser
# prints the URL instead of trying to open one (there's no browser in the pod).
rtk kubectl exec -n ai deploy/omniroute -c cliproxyapi -- \
  /CLIProxyAPI/CLIProxyAPI --config /CLIProxyAPI/config.yaml --claude-login --no-browser
```
Follow the printed URL in a real browser, complete the OAuth flow. Confirm
the session landed on the PVC:
```bash
rtk kubectl exec -n ai deploy/omniroute -c cliproxyapi -- ls -la /root/.cli-proxy-api/
```
Expected: a Claude auth file present.

- [ ] **Step 2: Codex login, also via CLIProxyAPI**

Prefer the device-code flow (`--codex-device-login`) over `--codex-login`
here — it prints a short code to enter at a URL instead of needing a
reachable OAuth callback port, simpler for a pod with no ports port-forwarded
for this specific purpose:
```bash
rtk kubectl exec -n ai deploy/omniroute -c cliproxyapi -- \
  /CLIProxyAPI/CLIProxyAPI --config /CLIProxyAPI/config.yaml --codex-device-login
```
Follow the printed code/URL to complete the OAuth flow. Confirm:
```bash
rtk kubectl exec -n ai deploy/omniroute -c cliproxyapi -- ls -la /root/.cli-proxy-api/
```
Expected: both a Claude auth file and a Codex/OpenAI auth file present in
the same directory (CLIProxyAPI stores all provider sessions under one
`auth-dir`).

- [ ] **Step 3: Confirm both survive a pod restart**

```bash
rtk kubectl delete pod -n ai -l app.kubernetes.io/name=omniroute
rtk kubectl wait -n ai --for=condition=ready pod -l app.kubernetes.io/name=omniroute --timeout=120s
rtk kubectl exec -n ai deploy/omniroute -c cliproxyapi -- ls -la /root/.cli-proxy-api/
```
Expected: both auth files still present — confirms PVC-backed persistence,
satisfying the config-as-code/backup requirement for interactive-login-only
state.

- [ ] **Step 4: Update TaskMaster and memory**

```bash
task-master set-status --id=10 --status=done
```
Update the `ai-omniroute-revival-plan` memory's "Phase status" section to
mark Phase 1 complete, and note the confirmed model-id addressing form from
Task 9 Step 2.

---

## Self-Review Notes

- **Spec coverage**: every item in the design spec's "Phase 1 validation
  checklist" (image pin, deploy+validate, MCP prove, local-provider combos,
  OAuth logins, BYOK deferred) maps to a task above. BYOK (Task 11 in
  TaskMaster) is correctly NOT in this plan — it's explicit backlog.
- **Config-as-code requirement**: every task either writes to git (Tasks
  1-5, 7) or explicitly proves PVC persistence with a restart-and-recheck
  step (Tasks 8, 10) — no task leaves state unverified.
- **Known follow-up, not a gap**: Task 8/9's exact MCP tool names and
  Task 9's exact model-addressing form can't be pinned before Task 6's live
  instance exists — this is real dependency ordering (an MCP server's tool
  schema can't be read before it's running), not a placeholder. Both tasks
  include the concrete verification command needed to resolve them.
