# Auth0 OIDC Authentication for Traefik

This directory contains the Auth0 OIDC middleware configuration for securing Traefik-managed services in your homelab.

## Overview

The setup provides:
- **OIDC-based authentication** via Auth0
- **Social login support** for Google and GitHub
- **Strict user allowlisting** for enhanced security
- **Distributed session management** using DragonflyDB (Redis-compatible)
- **Encrypted session cookies** for security

## Architecture

```
User Request → Traefik → OIDC Middleware → Auth0 → Social Provider (Google/GitHub)
                                              ↓
                                         DragonflyDB
                                      (Session Storage)
```

## Auth0 Configuration

### Application Details
- **Name**: HomeOps
- **Type**: Regular Web Application
- **Client ID**: `IEAIPLfa9MizMMtrkdEPtFu3TswAPVA9`
- **Domain**: `68ccio.us.auth0.com`
- **OIDC Conformant**: Yes

### Configured Callbacks
- `https://dash.68cc.io/oauth2/callback`
- `https://*.68cc.io/oauth2/callback`

### Allowed Logout URLs
- `https://dash.68cc.io`
- `https://68cc.io`

## Setup Instructions

### 1. Enable Social Connections in Auth0

You need to enable Google and GitHub social connections in your Auth0 tenant:

#### Google Connection
1. Go to Auth0 Dashboard → Authentication → Social
2. Click on "Google"
3. Enable the connection
4. Configure your Google OAuth credentials (or use Auth0's dev keys for testing)
5. Ensure the HomeOps application is enabled for this connection

#### GitHub Connection
1. Go to Auth0 Dashboard → Authentication → Social
2. Click on "GitHub"
3. Enable the connection
4. Configure your GitHub OAuth App credentials
5. Ensure the HomeOps application is enabled for this connection

### 2. Get Your Auth0 Client Secret

1. Go to Auth0 Dashboard → Applications → Applications
2. Click on "HomeOps"
3. Go to "Settings" tab
4. Copy the "Client Secret"
5. Update the `secret.sops.yaml` file with this value

### 3. Configure User Allowlist

Edit the `oidc.yaml` file and update the `allowedUsersAndGroups` section:

```yaml
allowedUsersAndGroups:
  - "email:your-actual-email@gmail.com"
  - "email:your-github-email@users.noreply.github.com"
```

**Important**: Replace the placeholder emails with your actual email addresses that you use with Google and GitHub.

### 4. Encrypt the Secret

Encrypt the `secret.sops.yaml` file using SOPS:

```bash
cd /Users/josh.simmonds/Documents/github/j0sh3rs/home-ops
sops -e -i kubernetes/apps/network/traefik/app/middleware/secret.sops.yaml
```

This will encrypt the file in-place using your age key configured in `.sops.yaml`.

### 5. Verify SOPS Encryption

After encryption, the file should look like:

```yaml
apiVersion: v1
kind: Secret
metadata:
    name: auth0-oidc-credentials
    namespace: network
type: Opaque
stringData:
    AUTH0_CLIENT_ID: ENC[AES256_GCM,data:...]
    AUTH0_CLIENT_SECRET: ENC[AES256_GCM,data:...]
    # ... other encrypted fields
```

### 6. Apply the Configuration

The middleware will be automatically applied when Flux reconciles your cluster:

```bash
# Force immediate reconciliation (optional)
flux reconcile kustomization traefik-middleware
```

## Usage Examples

### Protecting a Service with Auth0

To protect a service with Auth0 authentication, add the middleware to your HTTPRoute or IngressRoute:

#### HTTPRoute Example (Gateway API)

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: protected-service
  namespace: apps
spec:
  parentRefs:
    - name: traefik
      namespace: network
      sectionName: websecure
  hostnames:
    - "app.68cc.io"
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      filters:
        # Apply Auth0 OIDC authentication
        - type: ExtensionRef
          extensionRef:
            group: traefik.io
            kind: Middleware
            name: oidc-auth0-secure
            namespace: network
        # Apply security headers
        - type: ExtensionRef
          extensionRef:
            group: traefik.io
            kind: Middleware
            name: security-headers
            namespace: network
      backendRefs:
        - name: my-service
          port: 80
```

#### IngressRoute Example (Traefik CRD)

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: protected-service
  namespace: apps
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`app.68cc.io`)
      kind: Rule
      middlewares:
        - name: oidc-auth0-secure
          namespace: network
        - name: security-headers
          namespace: network
      services:
        - name: my-service
          port: 80
  tls:
    secretName: 68cc-io-tls
```

### Public Endpoints (No Authentication)

For public endpoints that should NOT require authentication, simply don't include the `oidc-auth0-secure` middleware:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: public-service
  namespace: apps
spec:
  parentRefs:
    - name: traefik
      namespace: network
      sectionName: websecure
  hostnames:
    - "public.68cc.io"
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      filters:
        # Only security headers, no authentication
        - type: ExtensionRef
          extensionRef:
            group: traefik.io
            kind: Middleware
            name: security-headers
            namespace: network
      backendRefs:
        - name: public-service
          port: 80
```

## Session Management

Sessions are stored in DragonflyDB with the following characteristics:

- **Session Duration**: 8 hours (28800 seconds)
- **Storage**: Redis-compatible DragonflyDB
- **Cache Mode**: Hybrid (local + distributed)
- **Key Prefix**: `traefikoidc:auth0:`

### Session Behavior

1. User authenticates via Auth0
2. Session token is encrypted and stored in cookie
3. Session data cached in DragonflyDB
4. Subsequent requests validated against cached session
5. Session expires after 8 hours of inactivity

## Advanced Configuration

### Custom Claims and Roles

If you want to use Auth0 roles for authorization:

1. Create an Auth0 Action to add custom claims:

```javascript
exports.onExecutePostLogin = async (event, api) => {
  const namespace = 'https://68cc.io';

  if (event.authorization) {
    api.idToken.setCustomClaim(`${namespace}/roles`, event.authorization.roles);
    api.accessToken.setCustomClaim(`${namespace}/roles`, event.authorization.roles);
  }
};
```

2. Assign roles to users in Auth0 Dashboard
3. Update the `allowedUsersAndGroups` in `oidc.yaml`:

```yaml
allowedUsersAndGroups:
  - "role:admin"
  - "role:homelab_user"
```

### Email Domain Allowlist

To allow all users from a specific domain:

```yaml
allowedUsersAndGroups:
  - "email_domain:68cc.io"
  - "email_domain:yourtrustedcompany.com"
```

## Troubleshooting

### Check Middleware Status

```bash
kubectl get middleware -n network oidc-auth0-secure -o yaml
```

### Check Secret

```bash
# Decrypt and view secret
sops -d kubernetes/apps/network/traefik/app/middleware/secret.sops.yaml

# Verify secret is created in cluster
kubectl get secret -n network auth0-oidc-credentials
```

### View Traefik Logs

```bash
kubectl logs -n network -l app.kubernetes.io/name=traefik --tail=100 -f
```

### Common Issues

1. **"Invalid redirect_uri"**
   - Verify callback URLs in Auth0 match your domain
   - Ensure you're using HTTPS
   - Check that the callback URL format is correct

2. **"User not authorized"**
   - Verify user email is in the allowlist
   - Check that email claim is being returned by Auth0
   - Ensure social connection is enabled for the application

3. **Session not persisting**
   - Verify DragonflyDB is running: `kubectl get pods -n databases`
   - Check Redis connectivity from Traefik pods
   - Review session encryption key configuration

4. **Authentication loop**
   - Clear browser cookies for your domain
   - Verify session encryption key is consistent
   - Check Traefik plugin version compatibility

## Security Considerations

1. **Rotate Secrets Regularly**: Change the session encryption key periodically
2. **Review Allowlist**: Regularly audit authorized users
3. **Monitor Access Logs**: Review Traefik access logs for suspicious activity
4. **Use Strong Secrets**: Ensure Auth0 client secret is complex and unique
5. **HTTPS Only**: Never allow HTTP for authenticated endpoints

## References

- [Auth0 Documentation](https://auth0.com/docs)
- [TraefikOIDC Plugin](https://github.com/lukaszraczylo/traefikoidc)
- [Traefik Middleware Documentation](https://doc.traefik.io/traefik/middlewares/overview/)
- [OIDC Specification](https://openid.net/specs/openid-connect-core-1_0.html)

## Support

For issues or questions:
1. Check Traefik logs
2. Review Auth0 logs in the dashboard
3. Verify DragonflyDB connectivity
4. Ensure all secrets are properly encrypted and applied
