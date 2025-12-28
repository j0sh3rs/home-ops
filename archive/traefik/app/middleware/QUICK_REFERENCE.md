# Auth0 OIDC Quick Reference

## Essential Information

| Item | Value |
|------|-------|
| **Auth0 Domain** | `68ccio.us.auth0.com` |
| **Tenant** | `68ccio` |
| **Application Name** | HomeOps |
| **Client ID** | `IEAIPLfa9MizMMtrkdEPtFu3TswAPVA9` |
| **Application Type** | Regular Web Application |
| **OIDC Conformant** | Yes |

## Quick Links

- **Auth0 Dashboard**: https://manage.auth0.com/dashboard/us/68ccio/
- **Application Settings**: https://manage.auth0.com/dashboard/us/68ccio/applications/IEAIPLfa9MizMMtrkdEPtFu3TswAPVA9/settings
- **Social Connections**: https://manage.auth0.com/dashboard/us/68ccio/connections/social
- **Users**: https://manage.auth0.com/dashboard/us/68ccio/users

## Get Client Secret

```bash
# Navigate to Auth0 Dashboard → Applications → HomeOps → Settings
# Copy the "Client Secret" value
# Update secret.sops.yaml:
AUTH0_CLIENT_SECRET: "paste-here"
```

## Enable Social Connections

### Google
1. Visit: https://manage.auth0.com/dashboard/us/68ccio/connections/social
2. Click "Google"
3. Toggle "Enable"
4. Under "Applications" tab, ensure "HomeOps" is enabled
5. Save

### GitHub
1. Visit: https://manage.auth0.com/dashboard/us/68ccio/connections/social
2. Click "GitHub"
3. Toggle "Enable"
4. Under "Applications" tab, ensure "HomeOps" is enabled
5. Save

## Encrypt Secret

```bash
cd ~/Documents/github/j0sh3rs/home-ops
sops -e -i kubernetes/apps/network/traefik/app/middleware/secret.sops.yaml
```

## Update User Allowlist

Edit `oidc.yaml` and update:

```yaml
allowedUsersAndGroups:
  - "email:your-gmail@gmail.com"
  - "email:your-github-email@users.noreply.github.com"
```

## Apply Configuration

```bash
# Option 1: Use the setup script
cd kubernetes/apps/network/traefik/app/middleware
chmod +x setup-auth0.sh
./setup-auth0.sh

# Option 2: Manual application
kubectl apply -k kubernetes/apps/network/traefik/app/middleware

# Option 3: Let Flux handle it (recommended)
flux reconcile kustomization traefik-middleware
```

## Test Authentication

1. Create a test HTTPRoute (see `example-routes.yaml`)
2. Visit the protected URL
3. Should redirect to Auth0 login
4. Test Google login
5. Test GitHub login
6. Verify access granted after successful login

## Debugging Commands

```bash
# Check middleware status
kubectl get middleware -n network oidc-auth0-secure -o yaml

# View secret (decrypted)
sops -d kubernetes/apps/network/traefik/app/middleware/secret.sops.yaml

# Check if secret exists in cluster
kubectl get secret -n network auth0-oidc-credentials

# View Traefik logs
kubectl logs -n network -l app.kubernetes.io/name=traefik --tail=100 -f

# Check DragonflyDB (session store)
kubectl get pods -n databases -l app.kubernetes.io/name=dragonfly
```

## Common Issues

### Issue: "Invalid redirect_uri"
**Solution**: Verify callback URLs in Auth0 match your domain exactly

### Issue: "User not authorized"
**Solution**:
1. Check email is in allowlist in `oidc.yaml`
2. Verify email claim is returned from Auth0
3. Ensure social connection is enabled for HomeOps app

### Issue: Session not persisting
**Solution**:
1. Check DragonflyDB is running
2. Verify Redis connectivity from Traefik pods
3. Review session encryption key

### Issue: Authentication loop
**Solution**:
1. Clear browser cookies for `*.68cc.io`
2. Verify session encryption key is consistent
3. Check Traefik plugin version

## Callback URLs

The following callback URLs are configured in Auth0:

- `https://dash.68cc.io/oauth2/callback`
- `https://*.68cc.io/oauth2/callback`

**Note**: Wildcard callbacks (`*.68cc.io`) require Auth0 to be on a paid plan. If you're on the free tier, you must specify each subdomain explicitly.

## Logout URLs

- `https://dash.68cc.io`
- `https://68cc.io`

## Session Configuration

- **Duration**: 8 hours (28800 seconds)
- **Storage**: DragonflyDB (Redis-compatible)
- **Key Prefix**: `traefikoidc:auth0:`
- **Encryption**: AES-256-GCM
- **Cache Mode**: Hybrid (local + distributed)

## Security Checklist

- [ ] Client secret retrieved from Auth0 dashboard
- [ ] Secret encrypted with SOPS
- [ ] User allowlist updated with authorized emails
- [ ] Google connection enabled and configured
- [ ] GitHub connection enabled and configured
- [ ] Both connections enabled for HomeOps application
- [ ] DragonflyDB running and accessible
- [ ] HTTPS enforced (forceHTTPS: true)
- [ ] Session encryption key is secure (32 bytes, random)
- [ ] Test authentication flow works end-to-end

## Getting Help

1. Review full documentation: `AUTH0_README.md`
2. Check example routes: `example-routes.yaml`
3. Review Traefik logs for errors
4. Check Auth0 logs in dashboard
5. Verify all secrets are properly configured
