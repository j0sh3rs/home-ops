# Authentication Architecture

**Last Updated:** 2026-06-02
**Status:** Production (forwardAuth active, native OIDC expanding)

---

## Overview

Cluster uses a **two-layer auth pattern**:

1. **Gateway-level** — Authentik via forwardAuth Middleware (all `*.68cc.io` routes)
2. **App-native** — Apps with built-in OIDC support configure Authentik directly (no gateway proxy)

**Central IdP:** Authentik (`auth.68cc.io`) with Google OAuth upstream.

---

## Layer 1: Gateway-level (forwardAuth)

**Pattern:** Traefik → Authentik outpost → backend
**Apps:** All LAN-only routes without native OIDC

### Architecture

```
Browser (to any protected *.68cc.io route)
  │
  ├─ GET /path HTTP/1.1
  │
  ▼
Traefik (traefik-internal-gateway or traefik-external-gateway)
  │  [check Middleware: authentik-forwardauth]
  ├─ unauthenticated:
  │  └─ 302 redirect to auth.68cc.io/outpost.goauthentik.io/start?rd=/path
  │
  ├─ authenticated:
  │  └─ Pass request + headers → backend
  │
  ▼
Backend service (Open WebUI, Grafana, etc.)
  │  [receives X-authentik-* headers]
  ├─ X-authentik-username
  ├─ X-authentik-email
  ├─ X-authentik-groups
  └─ X-authentik-name
```

### Middleware Configuration

All protected routes reference `Middleware/authentik-forwardauth` via `ExtensionRef` in their `HTTPRoute` spec:

```yaml
spec:
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: backend-service
      filters:
        - type: ExtensionRef
          extensionRef:
            group: traefik.io
            kind: Middleware
            name: authentik-forwardauth
```

**Materialization:** Per-namespace Component (`kubernetes/components/authentik-forwardauth/`). Namespaces that opt in (`ai`, `services`, `monitoring`, etc.) add:

```yaml
# kubernetes/apps/{namespace}/kustomization.yaml
components:
  - ../../components/authentik-forwardauth
```

The Component creates `Middleware/authentik-forwardauth` in that namespace.

### Apps Using forwardAuth

- **Open WebUI** — `ai.68cc.io`
- **AnythingLLM** — `anythingllm.68cc.io`
- **Grafana** — `grafana.68cc.io`
- **Homepage** — `68cc.io`
- **Homebridge** — `homebridge.68cc.io`
- **Paperless-NGX** — `paperless.68cc.io`
- **Linkwarden** — `linkwarden.68cc.io`
- **IT-Tools** — `it-tools.68cc.io`
- **Atuin** — `atuin.68cc.io`

### Grafana auth.proxy Header

Grafana is configured to read the authenticated user from the `X-authentik-email` header:

```toml
# kubernetes/apps/monitoring/grafana/instance/grafanainstance.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-config
data:
  grafana.ini: |
    [auth.proxy]
    enabled = true
    header_name = X-authentik-email  # ← Authentik sends this
    header_property = email
    auto_sign_up = true
```

---

## Layer 2: App-Native OIDC

**Pattern:** App ↔ Authentik OIDC provider → Google
**Rationale:** Apps that support OIDC natively benefit from direct integration (no gateway proxy overhead, app-level permissions, per-app OIDC scopes)

### Architecture

```
App Configuration (secret: AUTH_AUTHENTIK_CLIENT_ID, etc.)
  │
  ├─ clientId: (registered in Authentik)
  ├─ clientSecret: (stored in K8s secret)
  ├─ issuer: https://auth.68cc.io/application/o/{app-slug}/
  ├─ redirectUri: https://{app-domain}/api/auth/callback/{provider}
  │
  ▼
Authentik OIDC Provider
  │  [backend OIDC server]
  └─ scope: openid, email, profile
     audience: {clientId}
     │
     ▼
     Google OAuth (upstream)
       │
       └─ Redirect: https://auth.68cc.io/source/oauth/callback/google/
```

### App Configuration Pattern

Each app with native OIDC uses a similar secret pattern:

```yaml
# kubernetes/apps/{namespace}/{app}/app/secret.sops.yaml (encrypted)
---
apiVersion: v1
kind: Secret
metadata:
  name: {app}-secrets
type: Opaque
stringData:
  AUTH_AUTHENTIK_CLIENT_ID: "value-from-authentik-provider"
  AUTH_AUTHENTIK_CLIENT_SECRET: "value-from-authentik-provider"
  # ... other secrets
```

The app's Helm values wire these into OIDC provider config:

```yaml
# kubernetes/apps/{namespace}/{app}/app/helmrelease.yaml
spec:
  values:
    auth:
      providers:
        custom:
          name: "Authentik"
          clientId:
            secretKeyRef:
              name: {app}-secrets
              key: AUTH_AUTHENTIK_CLIENT_ID
          clientSecret:
            secretKeyRef:
              name: {app}-secrets
              key: AUTH_AUTHENTIK_CLIENT_SECRET
          issuer: "https://auth.68cc.io/application/o/{app-slug}/"
          redirectUri: "https://{app-domain}/api/auth/callback/custom"
          scope: "openid email profile"
```

### Apps Using App-Native OIDC

- **LangFuse** — `langfuse.68cc.io`
  - Chart provider: `custom` (generic OIDC)
  - Issuer: `https://auth.68cc.io/application/o/langfuse/`
  - Redirect URI: `https://langfuse.68cc.io/api/auth/callback/custom`
  - Headless init: OWNER user seeded on first boot (email `j0sh3rs@gmail.com`), account linking auto-activates on first SSO login

### When to Use App-Native OIDC

✅ **Use native OIDC if:**
- App has built-in OIDC/OAuth2 support
- App needs fine-grained role/permission mappings
- App runs headless with automatic user provisioning (LangFuse model)
- Gateway forwardAuth adds latency (rare edge case)

❌ **Use forwardAuth if:**
- App has no native OIDC
- App should not know about IdP details (simpler coupling)
- Auth state isn't valuable inside app (stateless services)

---

## Authentik Central Configuration

### Instance Details

**Location:** `kubernetes/apps/security/authentik/`
**URL:** `https://auth.68cc.io`
**Database:** CNPG `postgres17`, DB `authentik`
**Broker/Cache:** DragonflyDB db 5

### Setup Steps (post-deployment)

1. **Google OAuth Source**
   - Authentik Admin → Directory → Federation & Social login → Add Google source
   - Callback URL: `https://auth.68cc.io/source/oauth/callback/google/`
   - Scope: `email`, `profile`

2. **Proxy Provider** (forwardAuth routes)
   - Type: "Forward auth (domain level)"
   - External host: `https://auth.68cc.io`
   - Mode: `forward_auth_domain`

3. **OIDC Provider** (app-native routes)
   - Type: "OpenID Connect"
   - Client type: Confidential
   - Grant types: authorization_code, refresh_token
   - Redirect URIs: per-app (e.g., `https://langfuse.68cc.io/api/auth/callback/custom`)

4. **Applications**
   - One per protected service (slug: lowercase app name)
   - Bind provider (proxy or OIDC)
   - Bind policy (user or group)

### User Provisioning

- **Bootstrap:** `j0sh3rs@gmail.com` via Google OAuth
- **Auto-provisioning:** Enabled; first OAuth login creates Authentik user
- **App-level:** Some apps seed OWNER user + link SSO (LangFuse model)

---

## Secret Allocation

| DB | Consumer | Namespace | Purpose |
|----|----------|-----------|---------|
| db 5 | Authentik | security | Celery broker, Django cache, WebSocket |
| db 6 | Paperless | services | Task queue |

---

## Debugging

### Check forwardAuth authentication

```bash
curl -H "X-Forwarded-For: 127.0.0.1" \
     -H "X-Forwarded-Proto: https" \
     -H "X-Forwarded-Host: grafana.68cc.io" \
     http://authentik-server.security.svc.cluster.local/outpost.goauthentik.io/auth/traefik
```

Response: `200 + headers` = authenticated; `401` = unauthenticated

### Verify LangFuse OIDC provider

```bash
kubectl logs -n ai -l app.kubernetes.io/name=langfuse --context home | grep -i "oidc\|auth"
```

### Force re-authentication

```bash
# Clear cookies + navigate to protected route
curl -b "" https://grafana.68cc.io
# Should redirect to auth.68cc.io
```

---

## Migration from traefikoidc

**Status:** Completed 2026-05-28

✅ Deploy Authentik
✅ Configure Google OAuth source
✅ Swap Traefik component (traefik-oidc → authentik-forwardauth)
✅ Migrate HTTPRoutes
✅ Remove traefikoidc plugin
✅ Remove GOOGLE_CLIENT_ID/SECRET from traefik-secrets

🔄 **In-flight:** Migrate apps to native OIDC (LangFuse done, others as-needed)

---

## See Also

- `docs/runbooks/ai-stack-tier1-summary.md` — LangFuse setup + roadmap
- `kubernetes/components/authentik-forwardauth/` — Middleware definition
- `kubernetes/apps/security/authentik/` — Deployment manifests
