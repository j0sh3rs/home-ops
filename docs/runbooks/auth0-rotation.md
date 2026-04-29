# Auth0 Secret Rotation Runbook

Rotates `AUTH0_CLIENT_SECRET` and/or `SESSION_ENCRYPTION_KEY` used by the
`oidc-auth0-secure` Traefik middleware. Cadence: quarterly, or on suspected
compromise.

## Scope

Affects every site behind the middleware:

- `tools.68cc.io`, `n8n.68cc.io`, `ollama.68cc.io`, `ai.68cc.io`, `ha.68cc.io`
- `grafana.68cc.io`, `alertmanager.68cc.io`, `prometheus.68cc.io`, `logs.68cc.io`
- `hubble.68cc.io`

Public sites (`flux-webhook`, `sh`, `links`) are unaffected.

## Components touched

| Key | Stored in | Consumed by |
|-----|-----------|-------------|
| `AUTH0_CLIENT_ID` | `traefik-secrets` Secret (network ns, mirrored) | Plugin dereferences at request time |
| `AUTH0_CLIENT_SECRET` | `traefik-secrets` Secret (network ns, mirrored) | Exchanged with Auth0 `/oauth/token` |
| `SESSION_ENCRYPTION_KEY` | `traefik-secrets` Secret (network ns, mirrored) | Encrypts session cookie payload |

Source of truth: `kubernetes/apps/network/traefik/app/secret.sops.yaml`.
Reflector mirrors to `services`, `monitoring`, `kube-system`.

## Rotating `AUTH0_CLIENT_SECRET`

### 1. Rotate in Auth0 dashboard

1. Auth0 Dashboard → Applications → Applications → **HomeOps**
2. Settings tab → scroll to **Danger Zone**
3. Click **Rotate** next to Client Secret
4. Copy the new secret (only shown once)

### 2. Update SOPS secret

```bash
cd ~/Documents/github/j0sh3rs/home-ops
task sops:edit file=kubernetes/apps/network/traefik/app/secret.sops.yaml
```

Replace the `AUTH0_CLIENT_SECRET` value. Save + exit editor.

### 3. Verify encryption

```bash
task sops:verify
```

Look for `✅ kubernetes/apps/network/traefik/app/secret.sops.yaml`.

### 4. Commit and push

```bash
rtk git add kubernetes/apps/network/traefik/app/secret.sops.yaml
rtk git commit -m "fix(network): rotate Auth0 client secret"
rtk git pull --rebase && rtk git push
```

### 5. Reconcile and force pod restart

Reloader does not auto-restart Traefik on this Secret, so force it:

```bash
rtk flux reconcile source git flux-system --context home
rtk flux reconcile kustomization traefik -n network --context home
rtk kubectl rollout restart daemonset/traefik -n network --context home
rtk kubectl rollout status daemonset/traefik -n network --context home
```

### 6. Verify

```bash
# Env var in pod should show new length (real secret ≈ 64 chars)
POD=$(rtk kubectl get pod -n network -l app.kubernetes.io/name=traefik -o jsonpath='{.items[0].metadata.name}' --context home)
rtk kubectl exec -n network $POD --context home -- sh -c 'echo len=${#AUTH0_CLIENT_SECRET}'

# Smoke test: protected site must 302 to Auth0
curl -sI https://tools.68cc.io/ | grep -i 'location:'
# expect: location: https://68ccio.us.auth0.com/authorize?...
```

## Rotating `SESSION_ENCRYPTION_KEY`

**WARNING:** Rotating this key invalidates **every active session**. All users
(just you) will be logged out and must re-authenticate. Plan accordingly.

### 1. Generate a new 32-byte base64 key

```bash
openssl rand -base64 32
```

### 2. Update SOPS secret

```bash
task sops:edit file=kubernetes/apps/network/traefik/app/secret.sops.yaml
```

Replace the `SESSION_ENCRYPTION_KEY` value.

### 3. Optional: purge stale Redis sessions

Prevents stale encrypted blobs lingering in DragonflyDB:

```bash
rtk kubectl exec -n databases deploy/dragonflydb --context home -- \
  redis-cli -n 1 --scan --pattern 'traefikoidc:auth0:*' | \
  xargs -I{} rtk kubectl exec -n databases deploy/dragonflydb --context home -- \
  redis-cli -n 1 DEL {}
```

### 4. Steps 3–6 from client-secret rotation apply identically.

## Rotating `AUTH0_CLIENT_ID`

Effectively a new app. Don't rotate — create a new Auth0 app, update the
secret, delete the old app. Rarely needed.

## Rollback

If the new secret is wrong / sites return 500 from the plugin:

```bash
rtk git revert <sha>
rtk git push
rtk flux reconcile source git flux-system --context home
rtk kubectl rollout restart daemonset/traefik -n network --context home
```

Then re-rotate in Auth0 — the old secret is already invalid once rotation
happens in the dashboard, so you must generate *another* new one, not restore
the previous value.

## Audit log check

After rotation, confirm it landed in Auth0's management log:

1. Dashboard → Monitoring → Logs
2. Filter `type:"sapi"` or search for `"rotate"`
3. Expect one `sapi` entry "Rotate client secret" in the past few minutes

## When to rotate

- **Quarterly** — preventive hygiene
- **Immediately if:**
  - Commit history exposes the SOPS file unencrypted
  - A Traefik pod image or node is compromised
  - The Auth0 tenant shows suspicious logins (Monitoring → Logs → `fp` or `fu`)
  - Someone who shouldn't have cluster access had cluster access
