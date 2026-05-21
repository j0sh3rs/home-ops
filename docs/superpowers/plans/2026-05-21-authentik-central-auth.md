# Authentik Central Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-hostname `traefikoidc` Traefik plugin with Authentik as a central identity broker, so adding/removing routes requires zero Google OAuth configuration changes.

**Architecture:** Authentik runs in the `security` namespace with PostgreSQL (CNPG `postgres17`, DB `authentik`) and DragonflyDB db 6 for broker/cache/channels. Traefik `forwardAuth` middleware points at Authentik's embedded outpost, materialized per-namespace via a Kustomize Component identical in structure to the current `traefik-oidc` Component. One fixed Google OAuth callback URL (`https://auth.68cc.io/source/oauth/callback/google/`) covers all routes permanently.

**Tech Stack:** Authentik 2026.2.3 (`oci://ghcr.io/goauthentik/helm/authentik`), Flux OCIRepository + HelmRelease, SOPS age encryption, Traefik forwardAuth middleware, Gateway API HTTPRoute ExtensionRef, Kustomize Components, `ghcr.io/home-operations/postgres-init` init container.

---

## File Map

**Create:**
- `kubernetes/apps/security/authentik/ks.yaml` — Flux Kustomization entry point
- `kubernetes/apps/security/authentik/app/kustomization.yaml` — app kustomize overlay
- `kubernetes/apps/security/authentik/app/ocirepository.yaml` — OCIRepository for authentik helm chart
- `kubernetes/apps/security/authentik/app/helmrelease.yaml` — Authentik HelmRelease
- `kubernetes/apps/security/authentik/app/secret.sops.yaml` — SOPS-encrypted secrets (admin token, Postgres creds, Dragonfly password)
- `kubernetes/apps/security/authentik/app/httproute.yaml` — HTTPRoute for `auth.68cc.io`
- `kubernetes/components/authentik-forwardauth/kustomization.yaml` — Component definition
- `kubernetes/components/authentik-forwardauth/authentik-forwardauth.yaml` — forwardAuth Middleware

**Modify:**
- `kubernetes/apps/security/kustomization.yaml` — add authentik ks.yaml to resources
- `kubernetes/apps/ai/kustomization.yaml` — swap traefik-oidc → authentik-forwardauth component
- `kubernetes/apps/services/kustomization.yaml` — swap component
- `kubernetes/apps/monitoring/kustomization.yaml` — swap component
- `kubernetes/apps/kube-system/kustomization.yaml` — swap component
- `kubernetes/apps/monitoring/grafana/instance/grafana.yaml` — update auth.proxy header names
- `kubernetes/apps/network/traefik-external/app/helmrelease.yaml` — remove traefikoidc plugin
- `kubernetes/apps/network/traefik-internal/app/helmrelease.yaml` — remove traefikoidc plugin
- `kubernetes/apps/network/traefik-external/app/secret.sops.yaml` — remove Reflector namespaces + OIDC keys (Phase 4)
- All HelmReleases/HTTPRoutes with `google-oidc-secure` ExtensionRef — rename to `authentik-forwardauth`
- `docs/runbooks/dragonflydb-db-allocation.md` — add db 6 Authentik entry

**Delete (Phase 4):**
- `kubernetes/components/traefik-oidc/` directory

---

## Task 1: Create Authentik OCIRepository and HelmRelease

**Files:**
- Create: `kubernetes/apps/security/authentik/app/ocirepository.yaml`
- Create: `kubernetes/apps/security/authentik/app/helmrelease.yaml`

- [ ] **Step 1: Create the OCIRepository**

```yaml
# kubernetes/apps/security/authentik/app/ocirepository.yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/source.toolkit.fluxcd.io/ocirepository_v1.json
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: authentik
  namespace: security
spec:
  interval: 12h
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    # renovate: datasource=docker depName=ghcr.io/goauthentik/helm/authentik
    tag: 2026.2.3
  url: oci://ghcr.io/goauthentik/helm/authentik
```

- [ ] **Step 2: Create the HelmRelease**

```yaml
# kubernetes/apps/security/authentik/app/helmrelease.yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: &app authentik
spec:
  interval: 1h
  chartRef:
    kind: OCIRepository
    name: authentik
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  values:
    global:
      deploymentAnnotations:
        reloader.stakater.com/auto: "true"

    authentik:
      secret_key: "${AUTHENTIK_SECRET_KEY}"
      bootstrap_password: "${AUTHENTIK_BOOTSTRAP_PASSWORD}"
      bootstrap_token: "${AUTHENTIK_BOOTSTRAP_TOKEN}"
      log_level: info
      postgresql:
        host: postgres17-rw.databases.svc.cluster.local
        name: authentik
        user: authentik
        password: "${AUTHENTIK_POSTGRES_PASSWORD}"
      redis:
        host: dragonflydb.databases.svc.cluster.local
        port: 6379
        password: "${DRAGONFLYDB_PASSWORD}"
        db: 6

    server:
      resources:
        requests:
          cpu: 50m
          memory: 256Mi
        limits:
          cpu: 2
          memory: 1Gi
      initContainers:
        - name: init-db
          image: ghcr.io/home-operations/postgres-init:18
          envFrom:
            - secretRef:
                name: authentik-secrets

    worker:
      resources:
        requests:
          cpu: 50m
          memory: 256Mi
        limits:
          cpu: 1
          memory: 512Mi

    # Authentik's bundled Redis subchart disabled — use DragonflyDB db 6
    redis:
      enabled: false

    # Bundled PostgreSQL subchart disabled — use CNPG postgres17
    postgresql:
      enabled: false

    envFrom:
      - secretRef:
          name: authentik-secrets
```

- [ ] **Step 3: Commit**

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops-authentik
git add kubernetes/apps/security/authentik/app/ocirepository.yaml \
        kubernetes/apps/security/authentik/app/helmrelease.yaml
git commit -m "feat(security): add Authentik OCIRepository and HelmRelease"
```

---

## Task 2: Create Authentik secret and HTTPRoute

**Files:**
- Create: `kubernetes/apps/security/authentik/app/secret.sops.yaml`
- Create: `kubernetes/apps/security/authentik/app/httproute.yaml`

- [ ] **Step 1: Create the plaintext secret template then encrypt**

The secret must contain these keys:
- `AUTHENTIK_SECRET_KEY` — 50-char random string (run: `openssl rand -base64 50 | tr -d '\n/'`)
- `AUTHENTIK_BOOTSTRAP_PASSWORD` — admin password for first-run setup (run: `openssl rand -base64 24 | tr -d '\n/'`). Authentik reads this on first boot to set the `akadmin` password deterministically.
- `AUTHENTIK_BOOTSTRAP_TOKEN` — API token for akadmin (run: `openssl rand -hex 32`). Optional but useful for automation.
- `AUTHENTIK_POSTGRES_PASSWORD` — strong random password for the `authentik` Postgres user
- `INIT_POSTGRES_DBNAME` — `authentik`
- `INIT_POSTGRES_HOST` — `postgres17-rw.databases.svc.cluster.local`
- `INIT_POSTGRES_USER` — `authentik`
- `INIT_POSTGRES_PASS` — same value as `AUTHENTIK_POSTGRES_PASSWORD`
- `INIT_POSTGRES_SUPER_USER` — `postgres`
- `INIT_POSTGRES_SUPER_PASS` — cluster superuser password (same as other app secrets)
- `DRAGONFLYDB_PASSWORD` — DragonflyDB password (same value as in `traefik-secrets`)

Create the file at `kubernetes/apps/security/authentik/app/secret.sops.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: authentik-secrets
stringData:
  AUTHENTIK_SECRET_KEY: <openssl rand -base64 50 | tr -d '\n/'>
  AUTHENTIK_BOOTSTRAP_PASSWORD: <openssl rand -base64 24 | tr -d '\n/'>
  AUTHENTIK_BOOTSTRAP_TOKEN: <openssl rand -hex 32>
  AUTHENTIK_POSTGRES_PASSWORD: <generated password>
  INIT_POSTGRES_DBNAME: authentik
  INIT_POSTGRES_HOST: postgres17-rw.databases.svc.cluster.local
  INIT_POSTGRES_USER: authentik
  INIT_POSTGRES_PASS: <same as AUTHENTIK_POSTGRES_PASSWORD>
  INIT_POSTGRES_SUPER_USER: postgres
  INIT_POSTGRES_SUPER_PASS: <cluster superuser password>
  DRAGONFLYDB_PASSWORD: <same password as in traefik-secrets DRAGONFLYDB_PASSWORD>
```

Encrypt it:
```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops-authentik
task sops:encrypt-file file=kubernetes/apps/security/authentik/app/secret.sops.yaml
```

Verify encrypted (all stringData values must be `ENC[AES256_GCM...`):
```bash
grep -c "ENC\[AES256_GCM" kubernetes/apps/security/authentik/app/secret.sops.yaml
# Expected: 11
```

- [ ] **Step 2: Create the HTTPRoute**

```yaml
# kubernetes/apps/security/authentik/app/httproute.yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/gateway.networking.k8s.io/httproute_v1.json
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: authentik
  annotations:
    external-dns.alpha.kubernetes.io/target: 192.168.35.15
spec:
  hostnames:
    - auth.68cc.io
  parentRefs:
    - name: traefik-external-gateway
      namespace: network
  rules:
    - backendRefs:
        - name: authentik-server
          port: 80
      matches:
        - path:
            type: PathPrefix
            value: /
```

Note: **No** `ExtensionRef` filter here — Authentik's own endpoint must be exempt from forwardAuth or an infinite auth loop occurs.

- [ ] **Step 3: Commit**

```bash
git add kubernetes/apps/security/authentik/app/secret.sops.yaml \
        kubernetes/apps/security/authentik/app/httproute.yaml
git commit -m "feat(security): add Authentik secret and HTTPRoute for auth.68cc.io"
```

---

## Task 3: Wire Authentik into Flux

**Files:**
- Create: `kubernetes/apps/security/authentik/app/kustomization.yaml`
- Create: `kubernetes/apps/security/authentik/ks.yaml`
- Modify: `kubernetes/apps/security/kustomization.yaml`

- [ ] **Step 1: Create app kustomization overlay**

```yaml
# kubernetes/apps/security/authentik/app/kustomization.yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./secret.sops.yaml
  - ./ocirepository.yaml
  - ./helmrelease.yaml
  - ./httproute.yaml
```

- [ ] **Step 2: Create the Flux Kustomization**

```yaml
# kubernetes/apps/security/authentik/ks.yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app authentik
  namespace: &namespace security
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  path: ./kubernetes/apps/security/authentik/app
  prune: true
  retryInterval: 2m
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: *namespace
  timeout: 5m
  wait: false
  decryption:
    provider: sops
    secretRef:
      name: sops-age
```

- [ ] **Step 3: Add authentik to the security namespace kustomization**

Edit `kubernetes/apps/security/kustomization.yaml`. Add `- ./authentik/ks.yaml` to the `resources:` list:

```yaml
resources:
  - ./crowdsec/ks.yaml
  - ./authentik/ks.yaml
```

- [ ] **Step 4: Validate kustomize build**

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops-authentik
kustomize build kubernetes/apps/security/authentik/app 2>&1
# Expected: YAML output with OCIRepository, HelmRelease, Secret, HTTPRoute — no errors
```

- [ ] **Step 5: Commit**

```bash
git add kubernetes/apps/security/authentik/ \
        kubernetes/apps/security/kustomization.yaml
git commit -m "feat(security): wire Authentik into Flux (security namespace)"
```

---

## Task 4: Deploy Authentik and verify it starts

This task is a cluster operation — push and observe.

- [ ] **Step 1: Push branch and reconcile**

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops-authentik
git push -u origin feat/authentik-central-auth
task reconcile
```

- [ ] **Step 2: Watch Flux pick up the Kustomization**

```bash
rtk flux get ks -A --context home | grep authentik
# Expected within 2 min: authentik   True   Applied revision: feat/authentik-central-auth@...
```

- [ ] **Step 3: Watch the HelmRelease install**

```bash
rtk flux get hr -n security --context home
# Expected: authentik   True   Release reconciliation succeeded
```

If it fails, inspect:
```bash
kubectl -n security describe helmrelease authentik --context home
kubectl -n security get events --sort-by='.metadata.creationTimestamp' --context home | tail -20
```

- [ ] **Step 4: Verify pods are running**

```bash
rtk kubectl get pods -n security --context home
# Expected: authentik-server-* Running, authentik-worker-* Running
```

- [ ] **Step 5: Verify init-db ran successfully (DB created in postgres17)**

```bash
kubectl -n security logs -l app.kubernetes.io/name=authentik,app.kubernetes.io/component=server --context home | grep -i "migrat\|database\|error" | head -20
# Expected: database migration lines, no ERROR
```

- [ ] **Step 6: Verify auth.68cc.io resolves and shows Authentik login page**

Open `https://auth.68cc.io` in a browser.
Expected: Authentik login page (not a Traefik error, not a 502).

---

## Task 5: Configure Authentik via UI (Google OIDC source + proxy provider)

This task is manual UI configuration. Document each step for reproducibility.

**Prerequisites:** Authentik is running at `https://auth.68cc.io`. First-time setup: navigate to `https://auth.68cc.io/if/flow/initial-setup/` to set the `akadmin` password using the value from `AUTHENTIK_SECRET_KEY` (or a separate bootstrap password — see Authentik docs for `AUTHENTIK_BOOTSTRAP_PASSWORD`).

> **Note:** Authentik uses `AUTHENTIK_BOOTSTRAP_TOKEN` and `AUTHENTIK_BOOTSTRAP_PASSWORD` env vars for first-run admin setup. Add `AUTHENTIK_BOOTSTRAP_PASSWORD` to `authentik-secrets` if you want a deterministic admin password rather than the setup flow.

- [ ] **Step 1: Add Google OAuth source**

1. Go to `https://auth.68cc.io/if/admin/#/core/sources`
2. Click **Create → OAuth2/OpenID OAuth Source**
3. Fill in:
   - Name: `Google`
   - Slug: `google`
   - Consumer key: *(Google OAuth client ID — copy from current `traefik-secrets` GOOGLE_CLIENT_ID)*
   - Consumer secret: *(Google OAuth client secret — copy from current `traefik-secrets` GOOGLE_CLIENT_SECRET)*
   - OIDC well-known URL: `https://accounts.google.com/.well-known/openid-configuration`
   - Scopes: `email profile openid`
4. Save

**Google OAuth app update required:** In Google Cloud Console, add `https://auth.68cc.io/source/oauth/callback/google/` as an Authorized Redirect URI. This is the **last** time you will ever touch Google OAuth config.

- [ ] **Step 2: Create the Proxy Provider (domain-level forward auth)**

1. Go to `https://auth.68cc.io/if/admin/#/core/providers`
2. Click **Create → Proxy Provider**
3. Fill in:
   - Name: `home-ops-proxy`
   - Authentication flow: `default-authentication-flow`
   - Authorization flow: `default-provider-authorization-implicit-consent`
   - Mode: **Forward auth (domain level)**
   - External host: `https://auth.68cc.io`
   - Cookie domain: `68cc.io`
4. Save

- [ ] **Step 3: Create the Application**

1. Go to `https://auth.68cc.io/if/admin/#/core/applications`
2. Click **Create**
3. Fill in:
   - Name: `home-ops`
   - Slug: `home-ops`
   - Provider: `home-ops-proxy` (from Step 2)
4. Save

- [ ] **Step 4: Assign application to embedded outpost**

1. Go to `https://auth.68cc.io/if/admin/#/outpost/outposts`
2. Click the **embedded outpost** (created automatically)
3. Click **Edit**
4. Add `home-ops` to **Applications**
5. Save

The outpost will automatically update — wait ~30 seconds for it to refresh.

- [ ] **Step 5: Bind user policy**

1. Go to `https://auth.68cc.io/if/admin/#/core/applications` → click `home-ops` → **Policy / User / Group Bindings**
2. Click **Bind existing policy**
3. Create a **User** binding: user `j0sh3rs@gmail.com` (or `akadmin` if using local account)
4. Save

- [ ] **Step 6: Test the Google SSO login**

1. Open an incognito browser window
2. Navigate to `https://auth.68cc.io`
3. Click **Sign in with Google** (the Google source)
4. Complete Google OAuth flow
5. Expected: redirected back to `https://auth.68cc.io` and logged in as `j0sh3rs@gmail.com`

---

## Task 6: Create the authentik-forwardauth Kustomize Component

**Files:**
- Create: `kubernetes/components/authentik-forwardauth/authentik-forwardauth.yaml`
- Create: `kubernetes/components/authentik-forwardauth/kustomization.yaml`

- [ ] **Step 1: Create the Middleware**

```yaml
# kubernetes/components/authentik-forwardauth/authentik-forwardauth.yaml
---
# Authentik forwardAuth middleware — materialized per-namespace via Kustomize
# Component. Replaces traefikoidc plugin (components/traefik-oidc/).
#
# Authentik's embedded outpost returns 302 for unauthenticated requests.
# Traefik forwardAuth passes 3xx directly to the browser — no `errors`
# middleware wrapper needed.
#
# The outpost address uses the in-cluster service name. The service is
# created by the Authentik helm chart in the `security` namespace.
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: authentik-forwardauth
spec:
  forwardAuth:
    address: http://authentik-server.security.svc.cluster.local/outpost.goauthentik.io/auth/traefik
    trustForwardHeader: true
    authResponseHeaders:
      - X-authentik-username
      - X-authentik-groups
      - X-authentik-email
      - X-authentik-name
      - X-authentik-uid
      - X-authentik-jwt
      - X-authentik-meta-jwks
      - X-authentik-meta-outpost
      - X-authentik-meta-provider
      - X-authentik-meta-app
      - X-authentik-meta-version
```

- [ ] **Step 2: Create the Component kustomization**

```yaml
# kubernetes/components/authentik-forwardauth/kustomization.yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
# Opts the including namespace into the Authentik forwardAuth Traefik middleware.
# Replaces components/traefik-oidc (traefikoidc plugin pattern).
#
# Gateway API + Traefik reject cross-namespace ExtensionRef filters
# (traefik/traefik#11126, gateway-api#3903), so this Component materializes
# the Middleware into whichever namespace imports it.
apiVersion: kustomize.config.k8s.io/v1alpha1
kind: Component
resources:
  - ./authentik-forwardauth.yaml
```

- [ ] **Step 3: Validate the Component builds cleanly**

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops-authentik
kustomize build kubernetes/components/authentik-forwardauth 2>&1
# Expected: Middleware YAML output, no errors
```

- [ ] **Step 4: Commit**

```bash
git add kubernetes/components/authentik-forwardauth/
git commit -m "feat(security): add authentik-forwardauth Kustomize Component"
```

---

## Task 7: Swap forwardAuth component in all namespaces (Phase 3)

**Files:**
- Modify: `kubernetes/apps/ai/kustomization.yaml`
- Modify: `kubernetes/apps/services/kustomization.yaml`
- Modify: `kubernetes/apps/monitoring/kustomization.yaml`
- Modify: `kubernetes/apps/kube-system/kustomization.yaml`

**In each file**, replace:
```yaml
  - ../../components/traefik-oidc
```
with:
```yaml
  - ../../components/authentik-forwardauth
```

- [ ] **Step 1: Update ai/kustomization.yaml**

Edit `kubernetes/apps/ai/kustomization.yaml`:
```yaml
components:
  - ../../components/common
  - ../../components/repos/app-template
  - ../../components/authentik-forwardauth   # was: traefik-oidc
```

- [ ] **Step 2: Update services/kustomization.yaml**

Edit `kubernetes/apps/services/kustomization.yaml`:
```yaml
components:
  - ../../components/common
  - ../../components/repos/app-template
  - ../../components/authentik-forwardauth   # was: traefik-oidc
```

- [ ] **Step 3: Update monitoring/kustomization.yaml**

Edit `kubernetes/apps/monitoring/kustomization.yaml`:
```yaml
components:
  - ../../components/common
  - ../../components/repos/app-template
  - ../../components/authentik-forwardauth   # was: traefik-oidc
```

- [ ] **Step 4: Update kube-system/kustomization.yaml**

Edit `kubernetes/apps/kube-system/kustomization.yaml`:
```yaml
components:
  - ../../components/common
  - ../../components/repos/app-template
  - ../../components/authentik-forwardauth   # was: traefik-oidc
```

- [ ] **Step 5: Validate all four namespace builds**

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops-authentik
kustomize build kubernetes/apps/ai 2>&1 | grep -E "error|Middleware"
kustomize build kubernetes/apps/services 2>&1 | grep -E "error|Middleware"
kustomize build kubernetes/apps/monitoring 2>&1 | grep -E "error|Middleware"
kustomize build kubernetes/apps/kube-system 2>&1 | grep -E "error|Middleware"
# Expected: each shows `kind: Middleware` with name `authentik-forwardauth`, no errors
```

- [ ] **Step 6: Commit**

```bash
git add kubernetes/apps/ai/kustomization.yaml \
        kubernetes/apps/services/kustomization.yaml \
        kubernetes/apps/monitoring/kustomization.yaml \
        kubernetes/apps/kube-system/kustomization.yaml
git commit -m "feat(security): swap namespaces from traefik-oidc to authentik-forwardauth component"
```

---

## Task 8: Rename ExtensionRef in all HTTPRoutes/HelmReleases

**Files (all contain `google-oidc-secure` ExtensionRef):**
- Modify: `kubernetes/apps/ai/n8n/app/helmrelease.yaml`
- Modify: `kubernetes/apps/ai/open-webui/app/helmrelease.yaml`
- Modify: `kubernetes/apps/ai/llama-swap/app/helmrelease.yaml`
- Modify: `kubernetes/apps/ai/litellm/app/helmrelease.yaml`
- Modify: `kubernetes/apps/kube-system/cilium/app/httproute.yaml`
- Modify: `kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml`
- Modify: `kubernetes/apps/monitoring/grafana/instance/httproute.yaml`
- Modify: `kubernetes/apps/monitoring/victoria-logs/app/helmrelease.yaml`
- Modify: `kubernetes/apps/services/homepage/app/helmrelease.yaml`
- Modify: `kubernetes/apps/services/homebridge/app/helmrelease.yaml`
- Modify: `kubernetes/apps/services/home-assistant/app/helmrelease.yaml`
- Modify: `kubernetes/apps/services/it-tools/app/helmrelease.yaml`
- Modify: `kubernetes/apps/services/metamcp/app/helmrelease.yaml`

- [ ] **Step 1: Bulk rename across all files**

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops-authentik
grep -rl "google-oidc-secure" kubernetes/apps/ | xargs sed -i '' 's/name: google-oidc-secure/name: authentik-forwardauth/g'
```

- [ ] **Step 2: Verify no remaining references to google-oidc-secure in apps/**

```bash
grep -r "google-oidc-secure" kubernetes/apps/
# Expected: no output (zero matches)
```

- [ ] **Step 3: Verify the Component definition file still exists (should NOT be renamed)**

```bash
ls kubernetes/components/traefik-oidc/google-oidc-secure.yaml
# Expected: file exists (component cleanup is Phase 4)
```

- [ ] **Step 4: Validate all affected namespace builds**

```bash
kustomize build kubernetes/apps/ai 2>&1 | grep -c "authentik-forwardauth"
# Expected: >= 4 (one per app with a route)
kustomize build kubernetes/apps/services 2>&1 | grep -c "authentik-forwardauth"
# Expected: >= 5
kustomize build kubernetes/apps/monitoring 2>&1 | grep -c "authentik-forwardauth"
# Expected: >= 3
kustomize build kubernetes/apps/kube-system 2>&1 | grep -c "authentik-forwardauth"
# Expected: >= 1
```

- [ ] **Step 5: Commit**

```bash
git add kubernetes/apps/
git commit -m "feat(security): rename ExtensionRef google-oidc-secure → authentik-forwardauth"
```

---

## Task 9: Update Grafana auth.proxy headers

**Files:**
- Modify: `kubernetes/apps/monitoring/grafana/instance/grafana.yaml`

The traefikoidc plugin forwarded `X-Forwarded-User` (email) and `X-Forwarded-Name` (display name). Authentik forwards `X-authentik-email` and `X-authentik-name`.

- [ ] **Step 1: Update Grafana GrafanaInstance config**

In `kubernetes/apps/monitoring/grafana/instance/grafana.yaml`, find the `auth.proxy` section and update:

```yaml
    auth.proxy:
      enabled: "true"
      header_name: X-authentik-email    # was: X-Forwarded-User
      header_property: email
      auto_sign_up: "true"
      headers: "Name:X-authentik-name Email:X-authentik-email"  # was: Name:X-Forwarded-Name Email:X-Forwarded-User
      whitelist: 10.42.0.0/16
      enable_login_token: "true"
      sync_ttl: "60"
```

Also update the `signout_redirect_url`. The traefikoidc plugin used `/oauth2/logout`. Authentik's logout endpoint is different:

```yaml
    auth:
      disable_login_form: "true"
      signout_redirect_url: https://auth.68cc.io/if/flow/default-invalidation-flow/  # was: /oauth2/logout
```

- [ ] **Step 2: Update the comment in the file to reflect Authentik**

Replace the comment block above `auth.proxy` that references `google-oidc-secure middleware (plugin: lukaszraczylo/traefikoidc`:

```yaml
    # Grafana trusts the X-authentik-email header set by the Authentik
    # forwardAuth middleware (components/authentik-forwardauth/).
    # All external ingress transits that middleware via the HTTPRoute
    # filter, and there is no Service-level path that bypasses it.
    # Authentik identity (email) becomes the Grafana username;
    # auto_sign_up creates the Grafana account on first login.
```

- [ ] **Step 3: Validate kustomize build for monitoring**

```bash
kustomize build kubernetes/apps/monitoring/grafana/instance 2>&1 | grep -A5 "auth.proxy"
# Expected: header_name: X-authentik-email
```

- [ ] **Step 4: Commit**

```bash
git add kubernetes/apps/monitoring/grafana/instance/grafana.yaml
git commit -m "fix(monitoring): update Grafana auth.proxy headers for Authentik (X-authentik-email)"
```

---

## Task 10: Remove traefikoidc plugin from Traefik HelmReleases

**Files:**
- Modify: `kubernetes/apps/network/traefik-external/app/helmrelease.yaml`
- Modify: `kubernetes/apps/network/traefik-internal/app/helmrelease.yaml`

- [ ] **Step 1: Remove traefikoidc plugin block from traefik-external**

In `kubernetes/apps/network/traefik-external/app/helmrelease.yaml`, under `experimental.plugins:`, delete:

```yaml
        traefikoidc:
          moduleName: "github.com/lukaszraczylo/traefikoidc"
          # renovate: datasource=github-releases depName=lukaszraczylo/traefikoidc
          version: v1.0.12
```

- [ ] **Step 2: Remove traefikoidc plugin block from traefik-internal**

Same removal in `kubernetes/apps/network/traefik-internal/app/helmrelease.yaml`.

- [ ] **Step 3: Validate both Traefik builds**

```bash
kustomize build kubernetes/apps/network/traefik-external/app 2>&1 | grep -c "traefikoidc"
# Expected: 0
kustomize build kubernetes/apps/network/traefik-internal/app 2>&1 | grep -c "traefikoidc"
# Expected: 0
```

- [ ] **Step 4: Commit**

```bash
git add kubernetes/apps/network/traefik-external/app/helmrelease.yaml \
        kubernetes/apps/network/traefik-internal/app/helmrelease.yaml
git commit -m "feat(network): remove traefikoidc plugin from Traefik (replaced by Authentik forwardAuth)"
```

---

## Task 11: Deploy Phase 3 changes and verify end-to-end auth

- [ ] **Step 1: Push and reconcile**

```bash
git push
task reconcile
```

- [ ] **Step 2: Wait for Flux to apply all Kustomizations**

```bash
rtk flux get ks -A --context home | grep -E "ai|services|monitoring|kube-system|network"
# Expected: all True, Applied revision pointing to feat/authentik-central-auth
```

- [ ] **Step 3: Verify Traefik restarted without the plugin**

```bash
rtk kubectl get pods -n network --context home | grep traefik
# Expected: traefik-external-* and traefik-internal-* are Running (new pods after plugin removal)
```

- [ ] **Step 4: Test auth on a protected external route**

Open `https://n8n.68cc.io` in an incognito browser window.
Expected: redirect to `https://auth.68cc.io/outpost.goauthentik.io/start?rd=https://n8n.68cc.io/` → Google login → redirect back to `https://n8n.68cc.io` and authenticated.

- [ ] **Step 5: Test auth on a protected internal route**

Open `https://grafana.68cc.io` from LAN.
Expected: same flow — redirect to Authentik login → Google SSO → redirect back → logged into Grafana as `j0sh3rs@gmail.com`.

- [ ] **Step 6: Verify Grafana received correct identity header**

After logging in to Grafana, go to **Profile** in Grafana UI.
Expected: username shows `j0sh3rs@gmail.com` (not `unknown` or blank).

---

## Task 12: Phase 4 cleanup

**Files:**
- Delete: `kubernetes/components/traefik-oidc/` (entire directory)
- Modify: `kubernetes/apps/network/traefik-external/app/secret.sops.yaml` (remove Reflector namespaces + OIDC keys)
- Modify: `docs/runbooks/dragonflydb-db-allocation.md`

- [ ] **Step 1: Delete the traefik-oidc component**

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops-authentik
rm -rf kubernetes/components/traefik-oidc/
```

- [ ] **Step 2: Verify nothing references traefik-oidc**

```bash
grep -r "traefik-oidc" kubernetes/
# Expected: no output
```

- [ ] **Step 3: Update traefik-secrets (SOPS edit)**

Use the `sops-edit-then-encrypt` skill or:
```bash
task sops:edit file=kubernetes/apps/network/traefik-external/app/secret.sops.yaml
```

Remove from `stringData`:
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `SESSION_ENCRYPTION_KEY`

Remove from `metadata.annotations` the Reflector entries for `kube-system,monitoring,services,ai` (Authentik no longer needs `traefik-secrets` mirrored — it reads its own `authentik-secrets`).

Re-encrypt and verify:
```bash
task sops:verify
```

- [ ] **Step 4: Update DragonflyDB allocation doc**

In `docs/runbooks/dragonflydb-db-allocation.md`, update the allocation table row for db 6:

```markdown
| 6 | Authentik | `security/authentik` | Celery broker, Django cache, django-channels WebSocket layer. Key prefix default (Authentik-managed). | `kubernetes/apps/security/authentik/app/helmrelease.yaml` |
```

Also update the **Future / planned consumers** table to remove the AnythingLLM entry for db 6 and suggest db 6 is now taken. Move AnythingLLM suggestion to db 7 or next free.

- [ ] **Step 5: Validate kustomize build for network namespace**

```bash
kustomize build kubernetes/apps/network/traefik-external/app 2>&1 | grep -c "error"
# Expected: 0
```

- [ ] **Step 6: Commit all cleanup**

```bash
git add kubernetes/components/traefik-oidc/  # will be staged as deleted
git add kubernetes/apps/network/traefik-external/app/secret.sops.yaml
git add docs/runbooks/dragonflydb-db-allocation.md
git commit -m "chore(security): Phase 4 cleanup — remove traefik-oidc component, stale OIDC keys from traefik-secrets, update Dragonfly db allocation"
```

- [ ] **Step 7: Final reconcile and smoke test**

```bash
git push
task reconcile
```

Open `https://n8n.68cc.io` and `https://grafana.68cc.io` in incognito — verify auth still works after secrets cleanup.

---

## Task 13: Merge to main

- [ ] **Step 1: Run preflight checks**

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops-authentik
task sops:verify
kustomize build kubernetes/apps/security/authentik/app > /dev/null && echo "OK"
kustomize build kubernetes/apps/ai > /dev/null && echo "OK"
kustomize build kubernetes/apps/services > /dev/null && echo "OK"
kustomize build kubernetes/apps/monitoring > /dev/null && echo "OK"
kustomize build kubernetes/apps/kube-system > /dev/null && echo "OK"
kustomize build kubernetes/apps/network/traefik-external/app > /dev/null && echo "OK"
```

- [ ] **Step 2: Create PR**

```bash
rtk gh pr create \
  --title "feat(security): Authentik as central auth broker (replaces traefikoidc plugin)" \
  --body "$(cat <<'EOF'
## Summary

- Deploys Authentik 2026.2.3 in `security` namespace (Postgres on CNPG postgres17, DragonflyDB db 6)
- Registers one permanent Google OAuth callback: `https://auth.68cc.io/source/oauth/callback/google/`
- Replaces `components/traefik-oidc` with `components/authentik-forwardauth` (Traefik forwardAuth → Authentik embedded outpost)
- Updates Grafana auth.proxy headers: `X-Forwarded-User` → `X-authentik-email`
- Removes `traefikoidc` plugin from both Traefik instances
- Removes stale OIDC keys from `traefik-secrets`

## Test plan

- [ ] `auth.68cc.io` serves Authentik login page
- [ ] Google SSO flow completes and redirects back to origin URL
- [ ] `n8n.68cc.io` (external) redirects unauthenticated requests to Authentik
- [ ] `grafana.68cc.io` (internal+external) shows correct user after login
- [ ] Grafana username = `j0sh3rs@gmail.com` (header forwarded correctly)
- [ ] `kustomize build` succeeds for all namespaces
- [ ] `task sops:verify` passes
EOF
)"
```
