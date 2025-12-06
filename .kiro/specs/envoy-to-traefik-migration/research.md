# Research: Envoy to Traefik Migration

## Discovery Summary

**Feature Type**: Extension/Migration
**Discovery Approach**: Light Discovery (integration-focused)
**Date**: 2025-12-06
**Researcher**: Claude (AI Assistant)

---

## Architectural Context

### Current State Analysis

#### Existing Infrastructure
- **Kubernetes Version**: 1.31+ (Gateway API v1 GA support confirmed)
- **CNI**: Cilium with LBIPAM for LoadBalancer IP allocation
- **GitOps**: FluxCD-managed deployments via HelmRelease + Kustomize
- **Certificate Management**: cert-manager with wildcard certificate for *.68cc.io
- **Current Gateway**: Envoy Gateway with Gateway API resources
- **LoadBalancer IP**: 192.168.35.16 (allocated by Cilium LBIPAM)

#### Gateway API Resource Inventory
Based on requirements analysis, the following Gateway API resources exist:

**HTTPRoute Resources (3)**:
- `mcp.68cc.io` → toolhive/vmcp-work-vmcp service
- `grafana.68cc.io` → monitoring/grafana-service:3000
- `flux-webhook.68cc.io` → flux-system/webhook-receiver

**TCPRoute Resources (1)**:
- `victoria-logs-syslog-tcp` → monitoring/victoria-logs:514

**UDPRoute Resources (1)**:
- `victoria-logs-syslog-udp` → monitoring/victoria-logs:514

**Gateway Resource (1)**:
- Current gateway using Envoy controller
- HTTP listener (port 80, name "web")
- HTTPS listener (port 443, name "websecure")
- TLS certificate: 68cc-io-tls secret in network namespace

---

## Technology Evaluation

### Traefik Gateway API Provider

**Version Selection**: Traefik v3.0+
**Rationale**: Stable Gateway API v1 support, production-ready

**Key Capabilities**:
1. **Native Gateway API Implementation**
   - Full support for Gateway, HTTPRoute, TCPRoute, UDPRoute resources
   - ControllerName: `traefik.io/gateway-controller`
   - GatewayClass management

2. **Middleware System**
   - Traefik Middleware CRD for traffic policies
   - HTTPRoute ExtensionRef filter integration
   - Security headers, compression, protocol negotiation

3. **Observability**
   - Prometheus metrics endpoint
   - ServiceMonitor integration with kube-prometheus-stack
   - Structured logging compatible with victoria-logs

4. **TLS Handling**
   - Certificate reference from Kubernetes secrets
   - Automatic certificate reloading on renewal
   - TLS 1.2+ enforcement

---

## Architecture Decisions

### AD-1: Gateway API v1 Compliance Strategy

**Decision**: Use Gateway API v1 exclusively, avoid Traefik IngressRoute CRDs

**Rationale**:
- Gateway API v1 is GA and stable
- Maintains vendor-neutral routing configuration
- Simplifies future gateway controller migrations
- Reduces cognitive load (single routing API)

**Trade-offs**:
- Traefik-specific features require Middleware CRDs via ExtensionRef
- Cannot use IngressRoute-specific optimizations
- Accepted: Portability > vendor lock-in

---

### AD-2: Blue-Green Migration Approach

**Decision**: Deploy Traefik alongside Envoy Gateway, atomic cutover via parentRefs update

**Rationale**:
- Zero-downtime requirement (NFR-1)
- Rollback capability if issues detected
- Test traffic validation before production cutover

**Implementation**:
1. **Phase 1**: Deploy Traefik Gateway with temporary test hostname
2. **Phase 2**: Validate Traefik functionality with test HTTPRoute
3. **Phase 3**: Update all HTTPRoute/TCPRoute/UDPRoute parentRefs atomically
4. **Phase 4**: Monitor for 24h before Envoy removal

**Trade-offs**:
- Brief resource duplication (2 gateway controllers)
- Additional validation effort
- Accepted: Safety > resource efficiency during migration

---

### AD-3: Centralized Security Headers Middleware

**Decision**: Create single `security-headers` Middleware resource in network namespace, referenced via HTTPRoute ExtensionRef filters

**Rationale**:
- Consistent security posture across all HTTPRoutes
- Single source of truth for security policy
- Simplified updates (modify one Middleware resource)

**Implementation Pattern**:
```yaml
# kubernetes/apps/network/traefik/app/middleware-security-headers.yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: security-headers
  namespace: network
spec:
  headers:
    stsSeconds: 31536000
    stsIncludeSubdomains: true
    stsPreload: true
    frameDeny: true
    contentTypeNosniff: true
    browserXssFilter: true
    referrerPolicy: "strict-origin-when-cross-origin"
    customResponseHeaders:
      X-XSS-Protection: "1; mode=block"
      Permissions-Policy: "camera=(), microphone=(), geolocation=()"
    contentSecurityPolicy: "default-src 'self'"
```

**HTTPRoute Integration**:
```yaml
spec:
  parentRefs:
    - name: traefik-gateway
      sectionName: websecure
  rules:
    - filters:
        - type: ExtensionRef
          extensionRef:
            group: traefik.io
            kind: Middleware
            name: security-headers
      backendRefs:
        - name: backend-service
          port: 8080
```

**Trade-offs**:
- ExtensionRef coupling to Traefik (breaks Gateway API portability)
- Middleware CRD required (additional API surface)
- Accepted: Security consistency > pure portability

---

### AD-4: Single Traefik Deployment (Home-Lab Scale)

**Decision**: Deploy 1-2 Traefik replicas (home-lab traffic volume)

**Rationale**:
- Home-lab scale: <100 requests/sec
- Resource efficiency prioritized
- LoadBalancer IP allocation handles failover

**Trade-offs**:
- No horizontal scaling during traffic spikes
- Brief downtime if pod crashes
- Accepted: Resource efficiency > high availability (home-lab context)

---

### AD-5: Gateway Listener Configuration

**Decision**: Define HTTP (port 80) and HTTPS (port 443) listeners on Gateway resource, plus TCP/UDP (port 514) listeners

**Rationale**:
- Centralized protocol configuration
- HTTPRoutes inherit TLS from Gateway listener
- Protocol-specific listeners (TCP/UDP for syslog)

**Listener Design**:
```yaml
spec:
  listeners:
    - name: web
      protocol: HTTP
      port: 80
    - name: websecure
      protocol: HTTPS
      port: 443
      tls:
        mode: Terminate
        certificateRefs:
          - name: 68cc-io-tls
            namespace: network
    - name: tcp-514
      protocol: TCP
      port: 514
    - name: udp-514
      protocol: UDP
      port: 514
```

**Trade-offs**:
- Gateway resource becomes single point of configuration
- Listener changes affect all routes
- Accepted: Simplicity > distributed configuration

---

### AD-6: Prometheus Metrics Integration

**Decision**: Deploy Traefik ServiceMonitor targeting Traefik metrics endpoint

**Rationale**:
- Existing kube-prometheus-stack integration
- Standard Kubernetes monitoring pattern
- Grafana dashboard compatibility

**Metrics Exposed**:
- `traefik_entrypoint_requests_total` - Request rate
- `traefik_entrypoint_request_duration_seconds_*` - Latency percentiles
- `traefik_service_requests_total` - Backend routing metrics

**Trade-offs**:
- Requires Prometheus Operator CRDs
- Additional monitoring resource overhead
- Accepted: Observability > minimal resource usage

---

## Security Analysis

### TLS Configuration

**Certificate Management**:
- Existing cert-manager ClusterIssuer remains unchanged
- Wildcard certificate: *.68cc.io (already provisioned)
- Gateway certificateRefs point to existing secret

**TLS Policy**:
- Minimum TLS version: 1.2
- Ciphersuite: Modern (Traefik defaults)
- HSTS: Enforced via security headers middleware

**Risk Mitigation**:
- Certificate renewal handled by cert-manager (no change)
- Traefik hot-reloads certificates without downtime
- Gateway status condition validates certificate availability

---

### Security Headers Implementation

**Headers Applied via Middleware**:
1. **HSTS**: `max-age=31536000; includeSubDomains; preload`
   - Prevents protocol downgrade attacks
   - Prepares for browser HSTS preload list

2. **X-Frame-Options**: `DENY`
   - Prevents clickjacking attacks
   - No iframe embedding allowed

3. **X-Content-Type-Options**: `nosniff`
   - Prevents MIME-sniffing vulnerabilities

4. **X-XSS-Protection**: `1; mode=block`
   - Legacy browser XSS filter (defense-in-depth)

5. **Content-Security-Policy**: `default-src 'self'`
   - Restricts resource origins
   - Per-application customization possible

6. **Referrer-Policy**: `strict-origin-when-cross-origin`
   - Protects user privacy

7. **Permissions-Policy**: Restricts camera, microphone, geolocation
   - Minimizes browser API surface

**Middleware Override Behavior**:
- Traefik middleware headers override backend-set headers
- Ensures consistent security posture
- Backend cannot weaken security policy

---

## Integration Points

### FluxCD GitOps Integration

**Deployment Pattern**:
```
kubernetes/apps/network/traefik/
├── ks.yaml                          # Flux Kustomization (entry point)
└── app/
    ├── kustomization.yaml           # Kustomize overlay
    ├── helmrelease.yaml             # Traefik Helm chart config
    ├── gateway.yaml                 # Gateway resource
    ├── gatewayclass.yaml            # GatewayClass resource
    ├── middleware-security-headers.yaml  # Security headers middleware
    └── servicemonitor.yaml          # Prometheus ServiceMonitor
```

**HelmRelease Configuration**:
- Chart: traefik/traefik
- Version: 30.0.0+ (Traefik v3.0+)
- Values: Gateway API provider enabled

---

### Cilium LBIPAM Integration

**LoadBalancer IP Assignment**:
- IP: 192.168.35.16 (existing allocation)
- LBIPAM annotation: `io.cilium/lb-ipam-ips: "192.168.35.16"`
- Allocation strategy: Request specific IP via Gateway resource

**Conflict Mitigation**:
- Delete Envoy Gateway service before Traefik Gateway creation
- Ensures IP not in-use when Traefik requests allocation

---

### cert-manager Integration

**Certificate Reference**:
- Secret: 68cc-io-tls (network namespace)
- Certificate: Wildcard *.68cc.io
- ClusterIssuer: Unchanged (existing Let's Encrypt configuration)

**Renewal Handling**:
- cert-manager updates secret on renewal
- Traefik watches secret for changes
- Automatic reload without service interruption

---

## Performance Considerations

### Compression Policy

**Supported Algorithms**:
- Brotli (prefer if client supports)
- Gzip (fallback)
- Zstd (optional, high compression)

**Configuration**:
- Enable via Traefik Middleware for compression
- Apply to HTTPRoutes via ExtensionRef
- Minimum response size: 1KB

**Trade-offs**:
- CPU overhead for compression
- Reduced bandwidth usage
- Accepted: Latency increase for bandwidth savings (home-lab)

---

### HTTP/2 and HTTP/3 Support

**HTTP/2**:
- Enabled by default on HTTPS listener
- Protocol negotiation via ALPN

**HTTP/3**:
- Optional (requires Traefik configuration)
- Alt-Svc header advertisement
- QUIC transport

**Decision**: Enable HTTP/2, defer HTTP/3 (complexity vs benefit)

---

## Migration Risk Mitigation

### Rollback Strategy

**Rollback Triggers**:
- Persistent 5xx errors for >5 minutes
- TLS certificate validation failures
- TCP/UDP route traffic loss

**Rollback Procedure**:
1. Revert HTTPRoute/TCPRoute/UDPRoute parentRefs to Envoy Gateway
2. Scale Envoy Gateway deployment back to ready state
3. Monitor traffic recovery
4. Investigate Traefik configuration issues

**Git Reversion**:
- Flux reconciles previous commit
- Automatic rollback via Git revert + push

---

### Monitoring During Migration

**Critical Metrics**:
- HTTP 5xx error rate (threshold: 0% target)
- Request latency p99 (threshold: <500ms)
- Gateway resource status conditions
- Traefik pod health checks

**Alerting**:
- Alert on 5xx error rate >1% for >2 minutes
- Alert on Gateway status "Programmed: False"

---

## Open Questions Resolved

### Q1: Can Traefik and Envoy Gateway coexist on same LoadBalancer IP?

**Answer**: No, LoadBalancer IP must be unique per Gateway resource
**Resolution**: Deploy Traefik with temporary test hostname first, then delete Envoy Gateway before assigning production IP

---

### Q2: Do HTTPRoute resources require modification beyond parentRefs?

**Answer**: No, HTTPRoute hostnames, rules, and backendRefs remain unchanged
**Resolution**: Only parentRefs field updated (envoy → traefik-gateway)

---

### Q3: How to apply Traefik Middleware to Gateway API resources?

**Answer**: Use HTTPRoute ExtensionRef filters pointing to Traefik Middleware CRD
**Resolution**: Middleware resources created in network namespace, referenced via `group: traefik.io, kind: Middleware`

---

### Q4: Does Gateway API support TCP/UDP routing?

**Answer**: Yes, TCPRoute and UDPRoute are v1alpha2 (supported by Traefik)
**Resolution**: Gateway defines TCP/UDP listeners, routes reference via parentRefs

---

## Discovery Artifacts

### Relevant Documentation Reviewed
- Kubernetes Gateway API v1 Specification
- Traefik v3 Gateway API Provider Documentation
- Traefik Middleware CRD Reference
- Cilium LBIPAM Configuration Guide

### Existing Cluster Patterns Analyzed
- FluxCD HelmRelease + Kustomize deployment pattern
- Network namespace resource organization
- cert-manager ClusterIssuer configuration
- Prometheus ServiceMonitor integration

### Code References
- `kubernetes/apps/network/` - Network namespace apps
- `kubernetes/flux/meta/repos/` - Helm repository definitions
- Example HTTPRoute: `kubernetes/apps/monitoring/grafana/instance/httproute.yaml`
- Example cert-manager Certificate: `kubernetes/apps/network/envoy-gateway/app/certificate.yaml`

---

## Recommendations

### High Priority
1. **Deploy Traefik in Test Mode**: Create temporary test Gateway with different hostname for validation before production cutover
2. **Pre-Validate Certificates**: Ensure 68cc-io-tls secret exists and is valid before Gateway creation
3. **Monitor 24h Before Cleanup**: Wait full 24 hours after cutover before removing Envoy Gateway resources

### Medium Priority
1. **Grafana Dashboard**: Create Traefik-specific dashboard before migration for observability
2. **Runbook Documentation**: Document exact kubectl commands for rollback procedure
3. **Compression Testing**: Validate compression middleware with real traffic before applying globally

### Low Priority
1. **HTTP/3 Evaluation**: Test HTTP/3 support post-migration for potential future enablement
2. **Advanced Middleware**: Explore Traefik rate limiting, circuit breaker features for future enhancements

---

**Research Completed**: 2025-12-06
**Next Phase**: Design Document Generation
