# Requirements: Envoy to Traefik Migration

## Feature Overview

**Feature Name**: envoy-to-traefik-migration
**Description**: Complete migration from Envoy Gateway to Traefik using Kubernetes Gateway API (HTTPRoute, TCPRoute, UDPRoute) for all routing in the home-ops Kubernetes cluster.

**Business Context**: Traefik provides mature Gateway API implementation with simplified configuration management. Migration preserves existing Gateway API resources (HTTPRoute/TCPRoute/UDPRoute) while swapping the underlying gateway controller from Envoy to Traefik.

**Success Criteria Confidence**: High (0.95) - Gateway API provides standardized interface, making controller swap straightforward with minimal resource changes.

---

## User Stories with EARS Acceptance Criteria

### US-1: Traefik Gateway API Provider Deployment

**As a** cluster administrator
**I want** to deploy Traefik with Gateway API provider enabled
**So that** Traefik can manage Gateway API resources (Gateway, HTTPRoute, TCPRoute, UDPRoute)

**Acceptance Criteria**:

1. **WHEN** Traefik Helm chart is deployed with Gateway API provider enabled, the system **SHALL** create GatewayClass named "traefik" with controllerName "traefik.io/gateway-controller"
    - **Verification**: `kubectl get gatewayclass traefik -o jsonpath='{.spec.controllerName}'` returns "traefik.io/gateway-controller"
    - **Confidence**: 1.0

2. **WHEN** Traefik deployment completes, the system **SHALL** report healthy readiness probe status
    - **Verification**: Traefik pod shows `READY 1/1` and `STATUS Running` in network namespace
    - **Confidence**: 1.0

3. **WHEN** Traefik Gateway API provider starts, the system **SHALL** watch for Gateway, HTTPRoute, TCPRoute, and UDPRoute resources cluster-wide
    - **Verification**: Traefik logs show "Gateway API provider initialized" message
    - **Confidence**: 0.95

4. **WHEN** Traefik is fully operational, the system **SHALL** expose Prometheus metrics endpoint for observability
    - **Verification**: `kubectl get servicemonitor -n network` shows Traefik ServiceMonitor configured
    - **Confidence**: 0.95

**Priority**: Critical
**Dependencies**: None

---

### US-2: Gateway Resource Migration

**As a** platform engineer
**I want** to replace Envoy Gateway resource with Traefik Gateway
**So that** all routing uses Traefik as the gateway controller

**Acceptance Criteria**:

1. **WHEN** Traefik Gateway is created, the system **SHALL** reference gatewayClassName "traefik"
    - **Verification**: `kubectl get gateway -n network -o jsonpath='{.items[*].spec.gatewayClassName}'` returns "traefik"
    - **Confidence**: 1.0

2. **WHEN** Traefik Gateway is deployed, the system **SHALL** allocate the same LoadBalancer IP (192.168.35.16) previously used by Envoy Gateway
    - **Verification**: `kubectl get gateway -n network -o jsonpath='{.status.addresses[0].value}'` returns "192.168.35.16"
    - **Confidence**: 0.95

3. **WHEN** Traefik Gateway defines listeners, the system **SHALL** expose HTTP (port 80, name "web") and HTTPS (port 443, name "websecure") listeners
    - **Verification**: `kubectl get gateway -n network -o jsonpath='{.spec.listeners[*].name}'` includes "web" and "websecure"
    - **Confidence**: 1.0

4. **WHEN** HTTPS listener is configured, the system **SHALL** reference certificateRefs pointing to 68cc-io-tls secret in network namespace
    - **Verification**: `kubectl get gateway -n network -o jsonpath='{.spec.listeners[?(@.name=="websecure")].tls.certificateRefs[0].name}'` returns "68cc-io-tls"
    - **Confidence**: 1.0

5. **WHEN** HTTP request arrives on port 80, Traefik **SHALL** redirect to HTTPS (port 443) with 301 status code
    - **Verification**: `curl -I http://68cc.io` returns `HTTP/1.1 301 Moved Permanently` with `Location: https://68cc.io`
    - **Confidence**: 0.95

6. **WHEN** Traefik Gateway becomes ready, the system **SHALL** update Gateway status conditions with "Programmed: True"
    - **Verification**: `kubectl get gateway -n network -o jsonpath='{.status.conditions[?(@.type=="Programmed")].status}'` returns "True"
    - **Confidence**: 0.95

**Priority**: Critical
**Dependencies**: US-1 (Traefik Gateway API Provider)

---

### US-3: HTTPRoute Resource Updates

**As a** platform engineer
**I want** to update existing HTTPRoute resources to reference Traefik Gateway
**So that** HTTP routing continues functioning with new gateway controller

**Acceptance Criteria**:

1. **WHEN** HTTPRoute for mcp.68cc.io is updated, the system **SHALL** change parentRefs to reference Gateway name "traefik-gateway" with sectionName "websecure"
    - **Verification**: `kubectl get httproute -n toolhive mcp -o jsonpath='{.spec.parentRefs[0].name}'` returns "traefik-gateway"
    - **Confidence**: 1.0

2. **WHEN** mcp.68cc.io receives HTTPS request, Traefik **SHALL** route to vmcp-work-vmcp service in toolhive namespace
    - **Verification**: `curl -k https://mcp.68cc.io` returns 200 OK from vmcp service
    - **Confidence**: 0.95

3. **WHEN** HTTPRoute for grafana.68cc.io is updated, the system **SHALL** maintain backendRefs to grafana-service:3000 unchanged
    - **Verification**: `kubectl get httproute -n monitoring grafana -o jsonpath='{.spec.rules[0].backendRefs[0].name}'` returns "grafana-service"
    - **Confidence**: 1.0

4. **WHEN** grafana.68cc.io receives HTTPS request, Traefik **SHALL** route to grafana-service:3000 in monitoring namespace
    - **Verification**: `curl -k https://grafana.68cc.io` returns Grafana login page
    - **Confidence**: 0.95

5. **WHEN** HTTPRoute for flux-webhook.68cc.io is updated, the system **SHALL** maintain backendRefs to webhook-receiver unchanged
    - **Verification**: `kubectl get httproute -n flux-system flux-webhook -o jsonpath='{.spec.rules[0].backendRefs[0].name}'` returns "webhook-receiver"
    - **Confidence**: 1.0

6. **WHEN** flux-webhook.68cc.io receives HTTPS POST request, Traefik **SHALL** route to webhook-receiver service in flux-system namespace
    - **Verification**: `curl -k -X POST https://flux-webhook.68cc.io` returns webhook receiver response (not 404)
    - **Confidence**: 0.95

7. **WHERE** HTTPRoute hostname does not match any configured route, Traefik **SHALL** return 404 Not Found
    - **Verification**: `curl -k https://nonexistent.68cc.io` returns 404 status code
    - **Confidence**: 1.0

8. **WHEN** all HTTPRoutes are updated, the system **SHALL** maintain zero downtime during transition
    - **Verification**: Continuous monitoring shows <2s disruption during cutover
    - **Confidence**: 0.85

**Priority**: Critical
**Dependencies**: US-2 (Gateway Resource Migration)

---

### US-4: TCPRoute and UDPRoute Resource Updates

**As a** observability engineer
**I want** to update TCPRoute and UDPRoute resources to reference Traefik Gateway
**So that** syslog traffic routing continues functioning with new gateway controller

**Acceptance Criteria**:

1. **WHEN** TCPRoute for syslog is updated, the system **SHALL** change parentRefs to reference Gateway name "traefik-gateway" with sectionName "tcp-514"
    - **Verification**: `kubectl get tcproute -n monitoring victoria-logs-syslog-tcp -o jsonpath='{.spec.parentRefs[0].name}'` returns "traefik-gateway"
    - **Confidence**: 1.0

2. **WHEN** TCP syslog traffic arrives on port 514, Traefik **SHALL** route to victoria-logs:514 in monitoring namespace
    - **Verification**: `logger -n 192.168.35.16 -P 514 -T "test message"` appears in victoria-logs within 5 seconds
    - **Confidence**: 0.9

3. **WHEN** UDPRoute for syslog is updated, the system **SHALL** change parentRefs to reference Gateway name "traefik-gateway" with sectionName "udp-514"
    - **Verification**: `kubectl get udproute -n monitoring victoria-logs-syslog-udp -o jsonpath='{.spec.parentRefs[0].name}'` returns "traefik-gateway"
    - **Confidence**: 1.0

4. **WHEN** UDP syslog traffic arrives on port 514, Traefik **SHALL** route to victoria-logs:514 in monitoring namespace
    - **Verification**: `logger -n 192.168.35.16 -P 514 -d "test message"` appears in victoria-logs within 5 seconds
    - **Confidence**: 0.9

5. **WHERE** victoria-logs service is unavailable, Traefik **SHALL** drop syslog packets without crashing
    - **Verification**: Scale victoria-logs to 0, send syslog traffic, Traefik remains healthy
    - **Confidence**: 0.95

6. **WHEN** Traefik Gateway defines TCP/UDP listeners, the system **SHALL** expose port 514 for both protocols
    - **Verification**: `kubectl get gateway -n network -o jsonpath='{.spec.listeners[?(@.port==514)].protocol}'` includes "TCP" and "UDP"
    - **Confidence**: 1.0

**Priority**: High
**Dependencies**: US-2 (Gateway Resource Migration)

---

### US-5: TLS Certificate Integration

**As a** security administrator
**I want** Traefik Gateway to reference existing cert-manager wildcard certificate
**So that** HTTPS traffic maintains trust without certificate regeneration

**Acceptance Criteria**:

1. **WHEN** Traefik Gateway routes HTTPS traffic, the system **SHALL** present the 68cc-io-tls certificate for \*.68cc.io domains
    - **Verification**: `echo | openssl s_client -connect grafana.68cc.io:443 -servername grafana.68cc.io 2>/dev/null | openssl x509 -noout -subject` shows "CN=68cc.io"
    - **Confidence**: 1.0

2. **WHERE** TLS certificate secret is missing, Traefik Gateway **SHALL** report "Programmed: False" status condition with reason "CertificateNotFound"
    - **Verification**: Delete certificate secret, observe Gateway status condition message
    - **Confidence**: 0.9

3. **WHEN** cert-manager renews the 68cc-io-tls certificate, Traefik **SHALL** reload without service interruption
    - **Verification**: Force certificate renewal, monitor for zero 5xx errors during reload period
    - **Confidence**: 0.85

4. **WHEN** HTTPRoute references HTTPS listener, the system **SHALL** automatically apply TLS termination using Gateway's certificateRefs
    - **Verification**: HTTPRoute does not need to specify TLS configuration, inherited from Gateway listener
    - **Confidence**: 1.0

**Priority**: Critical
**Dependencies**: US-2 (Gateway Resource Migration)

---

### US-6: Traffic Policy Configuration

**As a** performance engineer
**I want** Traefik to apply compression and protocol policies equivalent to Envoy configuration
**So that** application performance characteristics remain consistent

**Acceptance Criteria**:

1. **WHEN** HTTPS response exceeds 1KB, Traefik **SHALL** apply compression (Brotli, Gzip, or Zstd) based on Accept-Encoding header
    - **Verification**: `curl -H "Accept-Encoding: br,gzip" https://grafana.68cc.io` returns response with Content-Encoding header
    - **Confidence**: 0.9

2. **WHEN** client supports HTTP/2, Traefik **SHALL** negotiate HTTP/2 protocol
    - **Verification**: `curl --http2 -I https://grafana.68cc.io` shows `HTTP/2 200`
    - **Confidence**: 1.0

3. **WHEN** client supports HTTP/3, Traefik **SHALL** advertise HTTP/3 via Alt-Svc header
    - **Verification**: Response headers include `alt-svc: h3=":443"` (if Traefik HTTP/3 enabled)
    - **Confidence**: 0.7

4. **WHEN** request includes X-Forwarded-For header, Traefik **SHALL** preserve client IP for backend services
    - **Verification**: Backend logs show original client IP, not Traefik pod IP
    - **Confidence**: 0.95

5. **WHERE** TLS version is below 1.2, Traefik **SHALL** reject connection with handshake failure
    - **Verification**: `openssl s_client -connect grafana.68cc.io:443 -tls1_1` fails with handshake error
    - **Confidence**: 1.0

6. **WHEN** Traefik Helm values configure compression middleware, the system **SHALL** apply middleware via HTTPRoute ExtensionRef filters
    - **Verification**: HTTPRoute can reference Traefik Middleware resource for custom compression settings
    - **Confidence**: 0.85

**Priority**: Medium
**Dependencies**: US-3 (HTTPRoute Resource Updates)

---

### US-7: Observability Integration

**As a** SRE
**I want** Traefik metrics integrated with existing Prometheus/Grafana stack
**So that** ingress performance monitoring continues without gaps

**Acceptance Criteria**:

1. **WHEN** Traefik exposes metrics, Prometheus **SHALL** scrape Traefik ServiceMonitor every 30 seconds
    - **Verification**: `kubectl get servicemonitor -n network traefik` exists with 30s scrapeInterval
    - **Confidence**: 1.0

2. **WHEN** Prometheus scrapes Traefik, the system **SHALL** collect HTTP request rate, duration, and error metrics
    - **Verification**: PromQL query `traefik_entrypoint_requests_total` returns data
    - **Confidence**: 0.95

3. **WHEN** Grafana dashboard queries Traefik metrics, the system **SHALL** display request latency percentiles (p50, p95, p99)
    - **Verification**: Grafana dashboard shows histogram quantiles for request duration
    - **Confidence**: 0.9

4. **WHEN** Traefik logs events, the system **SHALL** send structured logs to victoria-logs for aggregation
    - **Verification**: Victoria-logs query shows Traefik pod logs with JSON structure
    - **Confidence**: 0.85

5. **WHEN** Gateway resource status changes, Traefik **SHALL** emit Kubernetes events visible via kubectl describe
    - **Verification**: `kubectl describe gateway -n network` shows status change events
    - **Confidence**: 0.95

**Priority**: Medium
**Dependencies**: US-1 (Traefik Gateway API Provider)

---

### US-8: Envoy Gateway Decommission

**As a** cluster administrator
**I want** Envoy Gateway resources cleanly removed after migration validation
**So that** cluster resources are freed and configuration complexity reduced

**Acceptance Criteria**:

1. **WHEN** all HTTPRoute, TCPRoute, UDPRoute resources route successfully through Traefik for 24 hours, the system **SHALL** allow Envoy Gateway removal without errors
    - **Verification**: All routes function correctly, zero Envoy-related traffic for 24h
    - **Confidence**: 0.9

2. **WHEN** Envoy Gateway HelmRelease is deleted, Flux **SHALL** remove all Envoy-related resources (EnvoyProxy, policies)
    - **Verification**: `kubectl get envoyproxy -A` returns no resources
    - **Confidence**: 1.0

3. **WHEN** Envoy Gateway namespace resources are deleted, Kubernetes **SHALL** terminate all remaining Envoy pods gracefully
    - **Verification**: No Envoy pods remain after deletion completes
    - **Confidence**: 1.0

4. **WHEN** Envoy GatewayClass is deleted, the system **SHALL** leave HTTPRoute/TCPRoute/UDPRoute resources intact (referencing Traefik Gateway)
    - **Verification**: All route resources remain with updated parentRefs
    - **Confidence**: 1.0

5. **WHERE** old Gateway resource named "envoy" exists, the system **SHALL** remove it without affecting Traefik Gateway resource
    - **Verification**: `kubectl get gateway -A` shows only Traefik Gateway
    - **Confidence**: 1.0

**Priority**: Low
**Dependencies**: US-3 (HTTPRoute Updates), US-4 (TCP/UDP Updates), US-5 (TLS Integration)

---

### US-9: Security Header Middleware

**As a** security administrator
**I want** Traefik to apply comprehensive HTTP security headers to all HTTPS responses
**So that** applications are protected against common web vulnerabilities (clickjacking, XSS, MIME-sniffing)

**Acceptance Criteria**:

1. **WHEN** Traefik Middleware resource for security headers is created, the system **SHALL** configure HSTS with max-age 31536000 (1 year), includeSubdomains, and preload directives
    - **Verification**: `kubectl get middleware -n network security-headers -o jsonpath='{.spec.headers.stsSeconds}'` returns "31536000"
    - **Confidence**: 1.0

2. **WHEN** HTTPS response is sent through security headers middleware, Traefik **SHALL** add `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` header
    - **Verification**: `curl -I https://grafana.68cc.io | grep Strict-Transport-Security` shows HSTS header with correct directives
    - **Confidence**: 0.95

3. **WHEN** HTTPS response is sent through security headers middleware, Traefik **SHALL** add `X-Frame-Options: DENY` header to prevent clickjacking attacks
    - **Verification**: `curl -I https://grafana.68cc.io | grep X-Frame-Options` returns "DENY"
    - **Confidence**: 1.0

4. **WHEN** HTTPS response is sent through security headers middleware, Traefik **SHALL** add `X-Content-Type-Options: nosniff` header to prevent MIME-sniffing
    - **Verification**: `curl -I https://grafana.68cc.io | grep X-Content-Type-Options` returns "nosniff"
    - **Confidence**: 1.0

5. **WHEN** HTTPS response is sent through security headers middleware, Traefik **SHALL** add `X-XSS-Protection: 1; mode=block` header for legacy browser XSS filter
    - **Verification**: `curl -I https://grafana.68cc.io | grep X-XSS-Protection` returns "1; mode=block"
    - **Confidence**: 1.0

6. **WHEN** HTTPS response is sent through security headers middleware, Traefik **SHALL** add Content-Security-Policy header restricting resource origins
    - **Verification**: `curl -I https://grafana.68cc.io | grep Content-Security-Policy` shows CSP with "default-src" directive
    - **Confidence**: 0.9

7. **WHEN** HTTPS response is sent through security headers middleware, Traefik **SHALL** add `Referrer-Policy: strict-origin-when-cross-origin` header for privacy
    - **Verification**: `curl -I https://grafana.68cc.io | grep Referrer-Policy` returns "strict-origin-when-cross-origin"
    - **Confidence**: 0.95

8. **WHEN** HTTPS response is sent through security headers middleware, Traefik **SHALL** add Permissions-Policy header restricting browser features (camera, microphone, geolocation)
    - **Verification**: `curl -I https://grafana.68cc.io | grep Permissions-Policy` shows restrictions for camera, microphone, geolocation
    - **Confidence**: 0.9

9. **WHEN** HTTPRoute references security headers middleware via ExtensionRef filter, Traefik **SHALL** apply all configured security headers to matching requests
    - **Verification**: HTTPRoute with ExtensionRef filter `{group: traefik.io, kind: Middleware, name: security-headers}` applies headers to responses
    - **Confidence**: 0.95

10. **WHEN** multiple HTTPRoutes reference security headers middleware, Traefik **SHALL** apply headers consistently across all routes
    - **Verification**: All HTTPRoutes with security middleware ExtensionRef show identical security headers in responses
    - **Confidence**: 1.0

11. **WHERE** HTTPRoute does not reference security headers middleware, Traefik **SHALL** not add security headers to responses
    - **Verification**: Test HTTPRoute without middleware ExtensionRef shows no security headers added by Traefik
    - **Confidence**: 1.0

12. **WHEN** security headers middleware is updated, Traefik **SHALL** reload configuration without service interruption
    - **Verification**: Update middleware configuration, monitor for zero 5xx errors during reload
    - **Confidence**: 0.85

13. **WHEN** backend service sets conflicting security header, Traefik security middleware **SHALL** override with configured value
    - **Verification**: Backend returns X-Frame-Options: SAMEORIGIN, Traefik middleware changes to DENY
    - **Confidence**: 0.9

**Priority**: High
**Dependencies**: US-3 (HTTPRoute Resource Updates)

**Security Context**: These headers provide defense-in-depth against common web vulnerabilities:

- **HSTS**: Prevents protocol downgrade attacks and cookie hijacking
- **X-Frame-Options**: Prevents clickjacking by controlling iframe embedding
- **X-Content-Type-Options**: Prevents MIME-sniffing attacks
- **X-XSS-Protection**: Enables browser XSS filters (legacy support)
- **Content-Security-Policy**: Mitigates XSS by controlling resource origins
- **Referrer-Policy**: Protects user privacy by controlling Referer header
- **Permissions-Policy**: Restricts access to sensitive browser APIs

**Implementation Notes**:

- Middleware resource created in `network` namespace for cluster-wide reference
- HTTPRoutes reference middleware via `filters[].extensionRef` with `{group: traefik.io, kind: Middleware}`
- CSP policy should be tailored per application based on resource requirements
- HSTS preload directive prepares domain for browser HSTS preload list submission

---

## Non-Functional Requirements

### NFR-1: Migration Safety

**WHEN** Traefik deployment begins, the system **SHALL** maintain Envoy Gateway operational until Traefik validation completes

- **Verification**: Both gateway controllers coexist during migration window
- **Confidence**: 0.95

**WHERE** Traefik configuration error occurs, the system **SHALL** preserve rollback capability to Envoy Gateway

- **Verification**: Git history preserves Envoy Gateway manifests for restoration
- **Confidence**: 1.0

**WHEN** both Gateway resources exist, the system **SHALL** allow testing Traefik with temporary hostname (e.g., traefik.68cc.io) before production cutover

- **Verification**: Create test HTTPRoute with different hostname for validation
- **Confidence**: 0.9

### NFR-2: Gateway API Compatibility

**WHEN** migration completes, the system **SHALL** maintain 100% Gateway API v1 compliance for all route resources

- **Verification**: All HTTPRoute, TCPRoute, UDPRoute resources use `gateway.networking.k8s.io/v1` API group
- **Confidence**: 1.0

**WHERE** Traefik-specific features are required, the system **SHALL** use ExtensionRef filters referencing Traefik Middleware CRDs

- **Verification**: HTTPRoute applies Traefik middleware through standard ExtensionRef, not custom annotations
- **Confidence**: 0.9

### NFR-3: Resource Efficiency

**WHEN** Traefik replaces Envoy Gateway, the cluster **SHALL** maintain similar or lower ingress controller memory footprint

- **Verification**: Compare memory usage between Envoy and Traefik deployments
- **Confidence**: 0.7

### NFR-4: Configuration Simplicity

**WHEN** Gateway resource is created, the system **SHALL** centralize TLS certificate configuration (no per-HTTPRoute TLS config)

- **Verification**: HTTPRoutes reference Gateway listeners, inherit TLS from Gateway
- **Confidence**: 1.0

**WHEN** new HTTPRoute is required, the system **SHALL** require only parentRefs update (from "envoy" to "traefik-gateway")

- **Verification**: HTTPRoute backendRefs and rules remain unchanged during migration
- **Confidence**: 1.0

---

## Technical Constraints

1. **Kubernetes Version**: Cluster runs Kubernetes 1.31+ (Gateway API v1 GA support)
2. **Gateway API CRDs**: Gateway API v1 CRDs must be installed cluster-wide
3. **Traefik Version**: Traefik v3.0+ required for stable Gateway API support
4. **CNI Integration**: Traefik must integrate with Cilium CNI and LBIPAM for LoadBalancer IP allocation (192.168.35.16)
5. **GitOps Workflow**: All Traefik configuration deployed via Flux CD HelmRelease + Kustomize pattern
6. **Namespace Isolation**: Traefik deployed in `network` namespace, routes applications across multiple namespaces
7. **Home-Lab Scale**: Single Traefik deployment (replica count: 1-2) sufficient for home-lab traffic volume

---

## Out of Scope

1. **DNS Management**: External DNS configuration remains unchanged (Cloudflare)
2. **Certificate Renewal**: cert-manager ClusterIssuer configuration unchanged
3. **Application Code Changes**: No modifications to backend services or their networking
4. **Load Balancer Migration**: Cilium LBIPAM configuration remains the same, only Gateway resource changes
5. **IngressRoute Exploration**: Migration uses Gateway API exclusively, not Traefik IngressRoute CRDs
6. **Gateway API v1beta1 Support**: Migration targets v1 GA resources only
7. **Advanced Middleware**: Initial migration focuses on basic compression/protocol policies, not complex Traefik middleware chains

---

## Definition of Done

- [ ] All EARS acceptance criteria verified with confidence ≥0.85
- [ ] Zero customer-facing downtime during migration
- [ ] All 3 HTTPRoutes routing correctly through Traefik Gateway
- [ ] TCP and UDP syslog traffic (port 514) flowing to victoria-logs
- [ ] TLS certificate presented correctly for \*.68cc.io domains
- [ ] Traefik metrics visible in Grafana dashboards
- [ ] Envoy Gateway resources cleanly removed from cluster
- [ ] Gateway API resources remain v1-compliant (no proprietary CRDs)
- [ ] Migration runbook documented for future reference
- [ ] Rollback procedure tested and documented

---

## Risk Assessment

| Risk                            | Likelihood | Impact | Mitigation                                                                    |
| ------------------------------- | ---------- | ------ | ----------------------------------------------------------------------------- |
| Downtime during cutover         | Low        | High   | Blue-green deployment: Both gateways coexist, atomic DNS/parentRefs cutover   |
| TLS certificate issues          | Low        | High   | Pre-validate Gateway certificateRefs before updating HTTPRoute parentRefs     |
| TCP/UDP route incompatibility   | Medium     | Medium | Traefik TCP/UDP support mature; test syslog traffic before production cutover |
| Gateway API v1 breaking changes | Low        | Low    | Kubernetes 1.31 includes stable Gateway API v1                                |
| LoadBalancer IP conflict        | Low        | High   | Ensure Envoy Gateway service deleted before Traefik Gateway requests same IP  |
| Monitoring gap                  | Low        | Low    | Deploy Traefik ServiceMonitor before removing Envoy metrics                   |

---

## Migration Strategy

### Phase 1: Traefik Deployment (Coexistence)

1. Deploy Traefik with Gateway API provider enabled
2. Create Traefik Gateway resource with temporary test hostname
3. Validate Traefik Gateway healthy and LoadBalancer IP allocated
4. Create test HTTPRoute for validation (e.g., test.68cc.io)

### Phase 2: Route Migration (Production Cutover)

1. Update all HTTPRoute resources: change parentRefs from Envoy Gateway to Traefik Gateway
2. Update TCPRoute and UDPRoute resources: change parentRefs to Traefik Gateway
3. Monitor application traffic for errors
4. Validate all routes functioning correctly

### Phase 3: Cleanup (Envoy Removal)

1. Wait 24 hours for stability validation
2. Delete Envoy Gateway resource
3. Delete Envoy GatewayClass
4. Delete Envoy Gateway HelmRelease
5. Remove Envoy Gateway manifests from Git repository

---

**Requirements Author**: Claude (AI Assistant)
**Date**: 2025-12-06
**Status**: Pending Approval
**Revision**: 2 (Updated for Gateway API compatibility)
