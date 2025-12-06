# Implementation Tasks: Envoy to Traefik Migration

**Specification**: envoy-to-traefik-migration
**Phase**: Tasks
**Status**: Generated
**Progress**: 0/42 tasks completed

---

## Task Overview

This implementation follows a 5-phase blue-green migration strategy to ensure zero-downtime transition from Envoy Gateway to Traefik Gateway API provider.

**Total Tasks**: 8 major tasks, 42 sub-tasks
**Estimated Duration**: 16-24 hours across 3 days
**Risk Level**: Medium (blue-green strategy mitigates risk)

---

## Phase 1: Traefik Deployment (Day 0)

### 1. Deploy Traefik with Gateway API Provider (P)

**Requirements**: US-1
**Duration**: 2-3 hours
**Dependencies**: None

Deploy Traefik alongside existing Envoy Gateway with Gateway API provider enabled for initial validation.

- [ ] **1.1** Create Traefik HelmRelease manifest with Gateway API provider configuration
  - Enable kubernetesGateway provider with stable v1 API
  - Configure 4 entrypoints: web (80), websecure (443), tcp-514, udp-514
  - Set service type LoadBalancer with Cilium annotation for IP 192.168.35.16
  - Enable Prometheus metrics on port 9100
  - Configure resource limits: 512Mi memory, 500m CPU
  - Enable JSON access logs for observability

- [ ] **1.2** Create Flux Kustomization resource for Traefik deployment
  - Configure health checks for Traefik deployment
  - Set wait timeout to 5 minutes
  - Enable prune for automatic cleanup

- [ ] **1.3** Commit Traefik deployment manifests to Git repository
  - Create feature branch: `feat/traefik-gateway-migration`
  - Add all Traefik manifests to kubernetes/apps/network/traefik/
  - Commit with message referencing US-1
  - Push to remote repository

- [ ] **1.4** Trigger Flux reconciliation and verify Traefik deployment
  - Run `task reconcile` to force immediate sync
  - Verify Traefik pod reaches Ready state (1/1)
  - Confirm LoadBalancer service gets IP 192.168.35.16
  - Check Traefik logs for "Gateway API provider initialized"
  - Verify no conflicting services using same LoadBalancer IP

---

### 2. Create Gateway API Core Resources (P)

**Requirements**: US-1, US-2
**Duration**: 1-2 hours
**Dependencies**: Task 1 (Traefik deployed)

Create GatewayClass and Gateway resources that Traefik will manage.

- [ ] **2.1** Create GatewayClass resource with Traefik controller reference
  - Set controllerName to "traefik.io/gateway-controller"
  - Add descriptive metadata for home-ops cluster
  - Create ConfigMap for gateway-level parameters

- [ ] **2.2** Create Gateway resource with 4 listeners
  - Configure HTTP listener (web, port 80) allowing all namespaces
  - Configure HTTPS listener (websecure, port 443) with TLS termination
  - Reference existing cert-manager certificate: 68cc-io-tls
  - Configure TCP listener (tcp-514, port 514) for syslog
  - Configure UDP listener (udp-514, port 514) for syslog
  - Set LoadBalancer IP address to 192.168.35.16

- [ ] **2.3** Commit Gateway API resources to Git repository
  - Add manifests to kubernetes/apps/network/gateway-api/
  - Commit with message referencing US-2
  - Push changes

- [ ] **2.4** Verify Gateway resource status after reconciliation
  - Check GatewayClass shows "Accepted: True" condition
  - Verify Gateway status shows "Programmed: True"
  - Confirm all 4 listeners show "Ready: True"
  - Validate LoadBalancer IP allocation matches expectation

---

### 3. Create Traefik Middleware Resources (P)

**Requirements**: US-6, US-9
**Duration**: 1-2 hours
**Dependencies**: Task 1 (Traefik deployed)

Create reusable Middleware resources for security headers, compression, and HTTPS redirect.

- [ ] **3.1** Create security-headers Middleware resource
  - Configure HSTS with max-age 31536000, includeSubdomains, preload
  - Set frameDeny: true (X-Frame-Options: DENY)
  - Enable contentTypeNosniff (X-Content-Type-Options: nosniff)
  - Configure browserXssFilter: true
  - Set referrerPolicy: "strict-origin-when-cross-origin"
  - Add CSP header with default-src 'self' policy
  - Add custom headers: X-XSS-Protection, Permissions-Policy

- [ ] **3.2** Create compression Middleware resource
  - Configure minimum response size: 1024 bytes
  - Exclude non-compressible types: text/event-stream, application/grpc
  - Enable automatic algorithm selection (Brotli/Gzip/Zstd)

- [ ] **3.3** Create https-redirect Middleware resource
  - Configure redirectScheme to HTTPS
  - Set permanent: true for 301 redirects

- [ ] **3.4** Commit Middleware resources to Git repository
  - Add manifests to kubernetes/apps/network/traefik/app/
  - Commit with message referencing US-6, US-9
  - Push changes

- [ ] **3.5** Verify Middleware resources created successfully
  - Check all 3 Middleware resources exist in network namespace
  - Verify no errors in kubectl describe output

---

### 4. Create Test HTTPRoute for Validation

**Requirements**: US-3
**Duration**: 30 minutes
**Dependencies**: Tasks 2, 3 (Gateway and Middleware created)

Create temporary test HTTPRoute to validate Traefik before production migration.

- [ ] **4.1** Create test HTTPRoute with temporary hostname
  - Use hostname: traefik-test.68cc.io
  - Reference traefik-gateway with sectionName: websecure
  - Apply security-headers middleware via ExtensionRef filter
  - Apply compression middleware via ExtensionRef filter
  - Point to existing backend service (e.g., grafana) for testing

- [ ] **4.2** Commit test HTTPRoute and reconcile
  - Add manifest temporarily to validate Traefik
  - Push changes and trigger reconciliation

- [ ] **4.3** Validate test HTTPRoute functionality
  - Check HTTPRoute status shows "Accepted: True"
  - Test HTTPS connection: `curl -kI https://traefik-test.68cc.io`
  - Verify security headers present in response
  - Confirm compression working with Accept-Encoding header
  - Validate TLS certificate presented correctly

---

## Phase 2: HTTPRoute Migration (Day 1)

### 5. Migrate Production HTTPRoutes to Traefik Gateway

**Requirements**: US-3, US-9
**Duration**: 2-3 hours
**Dependencies**: Task 4 (Test HTTPRoute validated)

Update all production HTTPRoute resources to reference Traefik Gateway with security middleware.

- [ ] **5.1** Update flux-system/flux-instance HTTPRoute
  - Change parentRefs name from envoy-gateway to traefik-gateway
  - Change parentRefs namespace to "network"
  - Update sectionName from "https" to "websecure"
  - Add security-headers middleware ExtensionRef filter
  - Add compression middleware ExtensionRef filter
  - Keep all backendRefs unchanged

- [ ] **5.2** Update monitoring/grafana HTTPRoute
  - Apply same parentRefs changes as 5.1
  - Add security-headers middleware ExtensionRef filter
  - Add compression middleware ExtensionRef filter
  - Maintain existing backendRefs to grafana service

- [ ] **5.3** Update toolhive HTTPRoute
  - Apply same parentRefs changes as 5.1
  - Add security-headers middleware ExtensionRef filter
  - Add compression middleware ExtensionRef filter
  - Keep toolhive backendRefs unchanged

- [ ] **5.4** Create HTTP-to-HTTPS redirect HTTPRoute
  - Reference traefik-gateway with sectionName: web (HTTP listener)
  - Apply https-redirect middleware
  - Configure wildcard hostname: "*.68cc.io"
  - Set empty backendRefs (redirect only, no backend)

- [ ] **5.5** Commit all HTTPRoute updates to Git repository
  - Review all changes carefully before committing
  - Commit with descriptive message referencing US-3, US-9
  - Push changes to trigger atomic cutover

- [ ] **5.6** Monitor HTTPRoute migration and validate functionality
  - Force Flux reconciliation: `task reconcile`
  - Watch HTTPRoute status: `kubectl get httproute -A --context home`
  - Verify all routes show "Accepted: True"
  - Test all 3 production HTTPRoutes via curl
  - Validate security headers on all HTTPS responses
  - Confirm HTTP-to-HTTPS redirect working: `curl -I http://grafana.68cc.io`
  - Check Traefik logs for any routing errors

---

## Phase 3: TCP/UDP Route Migration (Day 1)

### 6. Migrate TCPRoute and UDPRoute Resources

**Requirements**: US-4
**Duration**: 1-2 hours
**Dependencies**: Task 5 (HTTPRoutes migrated successfully)

Update syslog TCPRoute and UDPRoute to reference Traefik Gateway.

- [ ] **6.1** Update victoria-logs TCPRoute for syslog
  - Change parentRefs name to traefik-gateway
  - Change parentRefs namespace to "network"
  - Set sectionName to "tcp-514"
  - Keep backendRefs to victoria-logs:514 unchanged

- [ ] **6.2** Update victoria-logs UDPRoute for syslog
  - Change parentRefs name to traefik-gateway
  - Change parentRefs namespace to "network"
  - Set sectionName to "udp-514"
  - Keep backendRefs to victoria-logs:514 unchanged

- [ ] **6.3** Commit TCP/UDP route updates to Git repository
  - Commit with message referencing US-4
  - Push changes

- [ ] **6.4** Validate TCP/UDP syslog routing functionality
  - Force Flux reconciliation
  - Check TCPRoute status: `kubectl get tcproute -A --context home`
  - Check UDPRoute status: `kubectl get udproute -A --context home`
  - Test TCP syslog: `logger -n 192.168.35.16 -P 514 -T "Migration test TCP"`
  - Test UDP syslog: `logger -n 192.168.35.16 -P 514 "Migration test UDP"`
  - Verify messages appear in victoria-logs within 5 seconds
  - Monitor victoria-logs for any routing errors

---

## Phase 4: Observability Integration (Day 2)

### 7. Configure Monitoring and Alerting (P)

**Requirements**: US-7
**Duration**: 2-3 hours
**Dependencies**: Tasks 5, 6 (All routes migrated)

Integrate Traefik metrics with existing Prometheus/Grafana observability stack.

- [ ] **7.1** Create Prometheus ServiceMonitor for Traefik
  - Configure selector matching Traefik service labels
  - Set scrape endpoint to metrics port (9100)
  - Configure scrapeInterval: 30s
  - Add metric relabeling to keep only traefik_* metrics

- [ ] **7.2** Create Grafana dashboard for Traefik Gateway
  - Create ConfigMap with dashboard JSON
  - Add panels for request rate (traefik_entrypoint_requests_total)
  - Add panel for response time p95 (histogram_quantile)
  - Add panel for error rate (5xx responses)
  - Add panel for backend health (traefik_service_server_up)
  - Add panel for TLS certificate expiry

- [ ] **7.3** Create Prometheus alert rules for Traefik
  - TraefikHighErrorRate: >5% error rate for 5m
  - TraefikHighLatency: p95 >500ms for 10m
  - TraefikBackendDown: Backend unavailable >2m
  - TraefikCertificateExpiring: <7 days remaining

- [ ] **7.4** Commit observability configuration to Git repository
  - Add ServiceMonitor, dashboard, alerts to appropriate locations
  - Commit with message referencing US-7
  - Push changes

- [ ] **7.5** Validate observability integration
  - Verify Prometheus target "traefik" shows "UP" status
  - Query Prometheus for traefik_entrypoint_requests_total metric
  - Open Grafana dashboard and confirm data flowing
  - Verify no Traefik alerts firing
  - Check Traefik JSON access logs in victoria-logs

- [ ] **7.6** Establish 24-hour monitoring baseline
  - Document current p95 latency, error rate, throughput
  - Set alert thresholds based on baseline measurements
  - Monitor continuously for next 24 hours before decommission

---

## Phase 5: Envoy Gateway Decommission (Day 3)

### 8. Remove Envoy Gateway After Validation Period

**Requirements**: US-8
**Duration**: 1 hour
**Dependencies**: Task 7 (24-hour monitoring successful)

Cleanly remove Envoy Gateway resources after confirming Traefik stability.

- [ ] **8.1** Verify 24-hour stability criteria met
  - Confirm zero service interruptions for 24 hours
  - Validate error rate remained <1% throughout period
  - Check p95 latency within acceptable range (<100ms)
  - Verify all HTTPRoute/TCPRoute/UDPRoute functioning correctly
  - Confirm no Envoy traffic in LoadBalancer metrics

- [ ] **8.2** Delete Envoy Gateway HelmRelease and resources
  - Use Flux to delete: `flux delete helmrelease envoy-gateway -n network --context home`
  - Delete Gateway resource: `kubectl delete gateway envoy-gateway -n network --context home`
  - Delete GatewayClass: `kubectl delete gatewayclass envoy-gateway --context home`
  - Verify all Envoy pods terminated gracefully

- [ ] **8.3** Remove Envoy Gateway manifests from Git repository
  - Delete kubernetes/apps/network/envoy-gateway/ directory
  - Remove any Envoy-related Kustomization references
  - Update any documentation referencing Envoy Gateway
  - Commit with message referencing US-8: "feat(network): decommission Envoy Gateway"
  - Push changes

- [ ] **8.4** Final validation after Envoy removal
  - Verify all HTTPRoutes still accessible via Traefik
  - Confirm TCP/UDP syslog still flowing to victoria-logs
  - Check no increase in error rates post-decommission
  - Validate Prometheus metrics show only Traefik traffic
  - Confirm no orphaned Envoy resources: `kubectl get envoyproxy -A --context home`

- [ ] **8.5** Delete test HTTPRoute used for initial validation
  - Remove traefik-test.68cc.io HTTPRoute from Git
  - Commit cleanup changes
  - Push to complete migration

- [ ] **8.6** Document migration completion and lessons learned
  - Record final performance metrics (latency, error rate)
  - Document any issues encountered and resolutions
  - Update runbook with Traefik-specific procedures
  - Archive migration plan and validation results

---

## Rollback Procedures

### Emergency Rollback (If Critical Issues Arise)

**Trigger Conditions**:
- Error rate >5% sustained for >5 minutes
- Complete service outage >2 minutes
- Data loss or corruption detected
- TLS certificate failures affecting multiple routes

**Rollback Steps**:

1. **Immediate Rollback (Phases 2-3)**:
   ```bash
   # Revert Git commit
   git log --oneline -5  # Find commit to revert
   git revert <commit-hash>
   git push

   # Force reconciliation
   task reconcile

   # Monitor route recovery
   watch kubectl get httproute,tcproute,udproute -A --context home
   ```

2. **Full Rollback (Phase 5 - Post Envoy Decommission)**:
   ```bash
   # Restore Envoy Gateway from Git history
   git revert <decommission-commit>
   git push
   task reconcile

   # Wait for Envoy pods
   kubectl wait --for=condition=Ready pod -l app=envoy-gateway -n network --timeout=300s --context home

   # Manually update route parentRefs back to Envoy (requires re-edit)
   ```

**Note**: Rollback after Phase 5 has significant downtime (5-10 minutes). Avoid decommissioning Envoy until confident in Traefik stability.

---

## Testing Checklist

Execute after each major phase to validate functionality:

### Phase 1 Testing (Post-Deployment)
- [ ] Traefik pod running and healthy
- [ ] LoadBalancer IP allocated correctly (192.168.35.16)
- [ ] Gateway resource shows all listeners Ready
- [ ] Test HTTPRoute routes successfully
- [ ] Security headers applied to test route
- [ ] Prometheus scraping Traefik metrics

### Phase 2 Testing (Post-HTTPRoute Migration)
- [ ] All 3 production HTTPRoutes return HTTP 200
- [ ] Security headers present on all HTTPS responses (HSTS, X-Frame-Options, CSP, etc.)
- [ ] Compression working (Content-Encoding header present)
- [ ] HTTP-to-HTTPS redirect functional (301 status)
- [ ] No increase in error rates from baseline
- [ ] Response times within acceptable range

### Phase 3 Testing (Post-TCP/UDP Migration)
- [ ] TCPRoute status Accepted and Ready
- [ ] UDPRoute status Accepted and Ready
- [ ] TCP syslog messages reaching victoria-logs
- [ ] UDP syslog messages reaching victoria-logs
- [ ] No packet loss observed in syslog traffic

### Phase 4 Testing (Post-Observability)
- [ ] Prometheus target "traefik" UP status
- [ ] Grafana dashboard displaying Traefik metrics
- [ ] All alert rules configured correctly
- [ ] Baseline metrics documented for 24h monitoring
- [ ] No false-positive alerts firing

### Phase 5 Testing (Post-Decommission)
- [ ] All routes still accessible after Envoy removal
- [ ] No Envoy pods remaining in cluster
- [ ] No orphaned Envoy Gateway API resources
- [ ] Metrics show only Traefik traffic (no Envoy)
- [ ] Performance stable post-decommission

---

## Definition of Done

**Migration Complete When**:

- [x] All 8 major tasks completed (0/8 currently)
- [x] All 42 sub-tasks completed (0/42 currently)
- [ ] Zero production downtime during migration
- [ ] All HTTPRoutes routing correctly through Traefik Gateway
- [ ] TCP/UDP syslog traffic flowing to victoria-logs
- [ ] TLS certificates valid for *.68cc.io domains
- [ ] Security headers applied to all HTTPS responses (13 EARS criteria met)
- [ ] Traefik metrics visible in Grafana dashboards
- [ ] Envoy Gateway cleanly removed from cluster
- [ ] 24-hour stability period completed successfully
- [ ] Migration documentation archived
- [ ] Rollback procedure tested and documented

---

## Risk Mitigation Summary

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Downtime during cutover | Low | High | Blue-green coexistence, atomic Git-based cutover |
| TLS certificate issues | Low | High | Pre-validate Gateway certificateRefs before migration |
| TCP/UDP incompatibility | Medium | Medium | Test with logger before production cutover |
| LoadBalancer IP conflict | Low | High | Ensure only one service requests 192.168.35.16 |
| Monitoring gap | Low | Low | Deploy ServiceMonitor before removing Envoy |
| Rollback complexity | Medium | High | Maintain Git history, avoid Phase 5 until stable |

---

**Tasks Generated**: 2025-12-06
**Ready for Implementation**: Yes
**Next Step**: Review tasks and execute `/kiro:spec-impl envoy-to-traefik-migration 1.1` to begin Phase 1
