# Authentik Central Auth — Design Spec

**Date:** 2026-05-21
**Branch:** feat/authentik-central-auth
**Status:** Approved, pending implementation

## Problem

`traefikoidc` plugin constructs `redirect_uri` from the incoming request host, requiring each new hostname to be manually registered in Google's OAuth client. Adding/removing endpoints requires a Google Cloud Console touchpoint. Goal: zero Google config changes when routes are added or removed.

## Decision

Deploy **Authentik** as a central identity broker. Authentik registers one fixed callback URL with Google. Traefik uses `forwardAuth` pointing at Authentik's embedded outpost. All `*.68cc.io` routes auth through a single proxy provider — no per-route IdP config.

## Architecture

```
Browser
  │
  ▼
Traefik (traefik-external-gateway or traefik-internal-gateway)
  │  forwardAuth → authentik-forwardauth Middleware (materialized per-namespace via Component)
  ▼
Authentik embedded outpost  (security/authentik-proxy, port 9000)
  │  unauthenticated → 302 to auth.68cc.io/outpost.goauthentik.io/start?rd=<original-url>
  │  authenticated   → 200 + identity headers forwarded to backend
  ▼
Backend service
```

**Single Google OAuth registration (permanent):**
`https://auth.68cc.io/source/oauth/callback/google/`

Authentik is the OIDC broker. Google sees only Authentik. Adding routes requires zero Google config.

## Why forwardAuth works here (not `errors` middleware)

Authentik outpost returns `302` for unauthenticated requests. Traefik `forwardAuth` passes 3xx directly to the browser — no `errors` middleware wrapper needed. The original oauth2-proxy failure was caused by wrapping `forwardAuth` with an `errors` middleware that intercepted the 302 and returned 401 with the redirect body verbatim. That failure mode cannot occur with Authentik's outpost design.

## Components

### Authentik deployment (`kubernetes/apps/security/authentik/`)

| Parameter | Value |
|-----------|-------|
| Namespace | `security` |
| Chart | `oci://ghcr.io/goauthentik/helm/authentik` (OCIRepository pattern) |
| Database | CNPG `postgres17`, DB `authentik`, via `postgres-init` initContainer |
| Cache/broker | DragonflyDB db 6 (`dragonflydb.databases.svc.cluster.local:6379/6`) |
| Ingress | `auth.68cc.io` on `traefik-external-gateway` (no forwardAuth — exempt) |
| Resources | ~500Mi RAM for server+worker combined |
| Secrets | `authentik-secrets.sops.yaml` — admin bootstrap key, Postgres creds, Dragonfly password |

DragonflyDB db 6 is used for Celery broker, Django cache, and django-channels WebSocket layer. DB 6 was previously reserved for AnythingLLM (undeployed) — Authentik takes it. Update allocation doc post-implementation.

### forwardAuth Component (`kubernetes/components/authentik-forwardauth/`)

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: authentik-forwardauth
spec:
  forwardAuth:
    address: http://authentik-proxy.security.svc.cluster.local:9000/outpost.goauthentik.io/auth/traefik
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

Per-namespace materialization pattern is identical to current `traefik-oidc` Component. Namespaces import via:
```yaml
components:
  - ../../components/authentik-forwardauth
```

HTTPRoutes reference via ExtensionRef:
```yaml
- type: ExtensionRef
  extensionRef:
    group: traefik.io
    kind: Middleware
    name: authentik-forwardauth
```

### Authentik configuration (manual UI bootstrap, post-deploy)

1. **Google OAuth Source** — Authentik Admin → Directory → Federation & Social login → Add Google source. Callback URL: `https://auth.68cc.io/source/oauth/callback/google/`
2. **Proxy Provider** — type "Forward auth (domain level)", external host `https://auth.68cc.io`, mode `forward_auth_domain`
3. **Application** — bind provider, slug `home-ops`
4. **Outpost** — assign embedded outpost to the application. Outpost exposes port 9000 for forwardAuth requests.
5. **Policy** — bind user `j0sh3rs@gmail.com` to the application (or use group policy)

## Grafana auth.proxy update

Grafana currently uses `header_name = X-Forwarded-User`. Authentik sends `X-authentik-email`. Change in Grafana instance config:

```ini
# Before
header_name = X-Forwarded-User

# After
header_name = X-authentik-email
```

## Migration phases

### Phase 1 — Deploy Authentik (no auth disruption)
- Scaffold `kubernetes/apps/security/authentik/` with ks.yaml, kustomization.yaml, helmrelease.yaml, ocirepository.yaml, secret.sops.yaml
- Verify pod starts, DB migrations succeed, `auth.68cc.io` resolves

### Phase 2 — Configure Authentik via UI
- Add Google OAuth source
- Create proxy provider (domain-level forward auth, `*.68cc.io`)
- Create application + bind to embedded outpost
- Bind user policy
- Verify login at `auth.68cc.io` with Google SSO

### Phase 3 — Swap forwardAuth Component (blast-radius phase)
- Add `kubernetes/components/authentik-forwardauth/`
- Swap component in `ai`, `services`, `monitoring`, `kube-system` kustomizations
- Update HTTPRoutes: `google-oidc-secure` → `authentik-forwardauth`
- Update Grafana `auth.proxy` header
- Remove `traefikoidc` plugin from both Traefik helmreleases
- Verify auth flow end-to-end

### Phase 4 — Cleanup
- Remove `kubernetes/components/traefik-oidc/`
- Remove `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SESSION_ENCRYPTION_KEY` from `traefik-secrets`
- Update `docs/runbooks/dragonflydb-db-allocation.md`: db 6 → Authentik
- Update OMEGA memory: `project_auth_traefikoidc` → Authentik pattern

## Rollback

Phase 3 is the only high-risk phase. Keep `traefik-oidc` component in place until Phase 3 verified. Old (`google-oidc-secure`) and new (`authentik-forwardauth`) Middleware names are distinct — rollback is swapping the component reference back. No state to migrate.

## Explicitly rejected alternatives

- **Stay on traefikoidc plugin** — solves nothing. Google registration still manual per hostname.
- **Cloudflare Zero Trust** — doesn't cover `traefik-internal-gateway` (LAN-only routes). Partial solution only.
- **oauth2-proxy only (no central IdP)** — same per-hostname Google registration problem unless fixed callback URL is used. Less capable than Authentik for family accounts/policies.
- **Authelia** — does not support Google as upstream OIDC provider in released versions. Requires local username/password — loses Google SSO.
