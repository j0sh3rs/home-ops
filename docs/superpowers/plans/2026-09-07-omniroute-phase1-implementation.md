# Omniroute Phase 1 (Parallel Install) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up Omniroute in `kubernetes/apps/ai/omniroute/` alongside the
existing LiteLLM gateway, and prove it's controllable as code (git) and via
its own MCP server — without touching LiteLLM or any consumer.

**Architecture:** bjw-s app-template, one Deployment / three containers in
one pod (`app`, `cliproxyapi`, `codex-app-server`), two PVCs
(`omniroute-data`, `cliproxyapi-data`), DragonflyDB db1 for the rate
limiter, HTTPRoute on `traefik-external-gateway`. All static config lives in
a SOPS-encrypted Secret; all interactive-login state lives on PVCs covered
by Velero's default backup.

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
  (upstream doesn't support it; see spec "Correction" section). Codex
  specifically uses the newer `codex-app-server` mechanism (drives the
  Codex CLI's own JSON-RPC app-server), not CLIProxyAPI's session-replay —
  CLIProxyAPI in this deployment handles Claude Code only.
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

### Task 3: HelmRelease — app-template with app + cliproxyapi + codex-app-server

**Files:**
- Create: `kubernetes/apps/ai/omniroute/app/helmrelease.yaml`

**Interfaces:**
- Consumes: Secret `omniroute-secrets` (Task 2), OCIRepository `app-template`
  (already materialized in `ai` namespace via the `repos/app-template`
  Component — same pattern as `llama-swap`).
- Produces: Service `omniroute` (ports 20128 dashboard, 20129 API, 20132
  live-ws), internal-only Service reachable at
  `omniroute.ai.svc.cluster.local` for Task 6's connectivity check; PVCs
  `omniroute-data`, `cliproxyapi-data`, `codex-appserver-token`,
  `codex-appserver-home` (the last two shared between `app` and
  `codex-app-server` containers, safe as `openebs-hostpath` since all
  containers are in the same pod on the same node).

- [ ] **Step 1: Write the HelmRelease**

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
              OMNIROUTE_CODEX_APPSERVER_WS: "ws://127.0.0.1:1456"
              OMNIROUTE_CODEX_APPSERVER_WS_TOKEN_FILE: /run/codex-appserver/token
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
            command: ["/cli-proxy-api"]
            args: ["--config", "/CLIProxyAPI/config.yaml"]
            resources:
              requests:
                cpu: 100m
                memory: 256Mi
              limits:
                cpu: "1"
                memory: 1Gi
            probes:
              liveness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /v1/models
                    port: 8317
                  initialDelaySeconds: 20
                  periodSeconds: 15
                  failureThreshold: 4
              readiness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /v1/models
                    port: 8317
                  initialDelaySeconds: 10
                  periodSeconds: 10

          codex-app-server:
            image:
              repository: docker.io/diegosouzapw/omniroute
              tag: 3.8.50
              pullPolicy: IfNotPresent
            # Overrides the base image's default Next.js entrypoint. Mirrors
            # upstream's own docker-compose.yml codex-app-server service
            # exactly (token bootstrap + `codex app-server` launch).
            command: ["/bin/sh", "-c"]
            args:
              - |
                set -e
                TOKEN_FILE=/run/codex-appserver/token
                mkdir -p /run/codex-appserver
                if [ ! -s "$TOKEN_FILE" ]; then
                  head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$TOKEN_FILE"
                  chmod 600 "$TOKEN_FILE"
                fi
                exec codex app-server \
                  --listen ws://127.0.0.1:1456 \
                  --ws-auth capability-token \
                  --ws-token-file "$TOKEN_FILE"
            env:
              CODEX_HOME: /home/node/.codex
              RUST_LOG: warn
            resources:
              requests:
                cpu: 100m
                memory: 256Mi
              limits:
                cpu: "1"
                memory: 1Gi

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
      codex-appserver-token:
        type: persistentVolumeClaim
        storageClass: openebs-hostpath
        accessMode: ReadWriteOnce
        size: 128Mi
        retain: true
        advancedMounts:
          omniroute:
            app:
              - path: /run/codex-appserver
            codex-app-server:
              - path: /run/codex-appserver
      codex-appserver-home:
        type: persistentVolumeClaim
        storageClass: openebs-hostpath
        accessMode: ReadWriteOnce
        size: 512Mi
        retain: true
        advancedMounts:
          omniroute:
            app:
              - path: /home/node/.codex
            codex-app-server:
              - path: /home/node/.codex
```

- [ ] **Step 2: Validate with kustomize + kubeconform before committing**

(This requires Task 4's `kustomization.yaml`/`ks.yaml` and Task 5's
`ai/kustomization.yaml` wiring to exist first — run this validation after
Task 5's Step 2 instead if working strictly task-by-task. If running ahead,
skip to Task 5 first, then return here.)

- [ ] **Step 3: Commit**

```bash
git add kubernetes/apps/ai/omniroute/app/helmrelease.yaml
git commit -m "feat(ai): add omniroute HelmRelease (Phase 1 scaffold)"
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
Expected: pod reaches `3/3 Running` (app, cliproxyapi, codex-app-server).
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

### Task 10: OAuth login flows — Claude Code (CLIProxyAPI) and Codex (app-server)

**Files:** none (interactive login, PVC-backed session state)

- [ ] **Step 1: Claude Code login via CLIProxyAPI**

```bash
rtk kubectl port-forward -n ai deploy/omniroute 51234:8317 &
# CLIProxyAPI's --claude-login needs a reachable OAuth callback; --no-browser
# prints the URL instead of trying to open one (there's no browser in the pod).
rtk kubectl exec -n ai deploy/omniroute -c cliproxyapi -- \
  /cli-proxy-api --config /CLIProxyAPI/config.yaml --claude-login --no-browser
```
Follow the printed URL in a real browser, complete the OAuth flow. Confirm
the session landed on the PVC:
```bash
rtk kubectl exec -n ai deploy/omniroute -c cliproxyapi -- ls -la /root/.cli-proxy-api/
```
Expected: a Claude auth file present.

- [ ] **Step 2: Codex login via the app-server's own OAuth (not CLIProxyAPI)**

The `codex-app-server` container's Codex CLI self-manages OAuth against the
shared `~/.codex` volume — this needs the dashboard's "Apply auth" flow for
`codex-app-server` (device-OAuth), not a CLIProxyAPI flag. Trigger it via
the dashboard (Providers → codex-app-server → Apply auth) or, if exposed,
its MCP-equivalent tool call. Confirm:
```bash
rtk kubectl exec -n ai deploy/omniroute -c codex-app-server -- ls -la /home/node/.codex/
```
Expected: `auth.json` present.

- [ ] **Step 3: Confirm both survive a pod restart**

```bash
rtk kubectl delete pod -n ai -l app.kubernetes.io/name=omniroute
rtk kubectl wait -n ai --for=condition=ready pod -l app.kubernetes.io/name=omniroute --timeout=120s
rtk kubectl exec -n ai deploy/omniroute -c cliproxyapi -- ls -la /root/.cli-proxy-api/
rtk kubectl exec -n ai deploy/omniroute -c codex-app-server -- ls -la /home/node/.codex/
```
Expected: both still present — confirms PVC-backed persistence, satisfying
the config-as-code/backup requirement for interactive-login-only state.

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
