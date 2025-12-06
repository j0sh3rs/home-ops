# Design Document: Envoy to Traefik Migration

**Specification**: envoy-to-traefik-migration
**Phase**: Design
**Created**: 2025-12-06
**Status**: Draft

---

## 1. System Architecture Overview

### 1.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Gateway API Resources                     │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  │  │
│  │  │ GatewayClass│  │   Gateway    │  │ HTTPRoute   │  │  │
│  │  │   traefik   │─▶│ (4 listeners)│◀─│ TCPRoute    │  │  │
│  │  └─────────────┘  └──────────────┘  │ UDPRoute    │  │  │
│  │                           │          └─────────────┘  │  │
│  └───────────────────────────┼──────────────────────────┘  │
│                               ▼                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Traefik Gateway Provider                  │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │ Deployment: traefik                             │  │  │
│  │  │ - Gateway API Controller (traefik.io/gateway)  │  │  │
│  │  │ - HTTP/HTTPS Entrypoints (80, 443)             │  │  │
│  │  │ - TCP Entrypoint (514)                         │  │  │
│  │  │ - UDP Entrypoint (514)                         │  │  │
│  │  │ - Middleware Engine (security headers, etc.)   │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  │                          │                             │  │
│  │                          ▼                             │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │ Service: traefik (LoadBalancer)                 │  │  │
│  │  │ - LoadBalancer IP: 192.168.35.16 (Cilium LBIPAM)│ │  │
│  │  │ - Ports: 80/HTTP, 443/HTTPS, 514/TCP, 514/UDP  │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
│                               │                              │
│  ┌────────────────────────────┼──────────────────────────┐  │
│  │         Traefik Middleware Resources                  │  │
│  │  ┌──────────────────────────────────────────────┐    │  │
│  │  │ Middleware: security-headers                 │    │  │
│  │  │ - HSTS, X-Frame-Options, CSP, etc.          │    │  │
│  │  └──────────────────────────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────┘  │
│                               │                              │
│                               ▼                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Backend Services                          │  │
│  │  - grafana, victoria-logs, flux-ui, toolhive, etc.    │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Integration Points

#### 1.2.1 FluxCD GitOps Integration

- **HelmRelease** resource manages Traefik deployment
- **Kustomization** resources manage Gateway API resources
- **Source**: Git repository `github.com/j0sh3rs/home-ops`
- **Reconciliation**: Automatic updates on Git push

#### 1.2.2 Cilium LBIPAM Integration

- **LoadBalancer Service**: Traefik service type LoadBalancer
- **IP Allocation**: Cilium assigns 192.168.35.16 from pool
- **Health Checks**: Cilium monitors Traefik pod health

#### 1.2.3 cert-manager Integration

- **Certificate Resources**: TLS certificates for HTTPS
- **Let's Encrypt**: Automatic certificate issuance and renewal
- **Gateway TLS**: Gateway listener references cert-manager Secret

#### 1.2.4 Prometheus Integration

- **ServiceMonitor**: Scrapes Traefik metrics endpoint
- **Metrics**: Request count, latency, errors, backend health
- **Grafana**: Dashboards visualize Traefik performance

---

## 2. Component Specifications

### 2.1 Traefik Deployment

#### 2.1.1 HelmRelease Configuration

**Requirement Traceability**: US-1

**File**: `kubernetes/apps/network/traefik/app/helmrelease.yaml`

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
    name: traefik
    namespace: network
spec:
    interval: 30m
    chart:
        spec:
            chart: traefik
            version: "32.1.1" # Latest stable version
            sourceRef:
                kind: HelmRepository
                name: traefik
                namespace: flux-system
    values:
        # Gateway API Provider Configuration
        providers:
            kubernetesGateway:
                enabled: true
                experimentalChannel: false # Use stable v1 API
            kubernetesCRD:
                enabled: true # For Middleware resources
                allowCrossNamespace: true # Cross-namespace middleware references
            kubernetesIngress:
                enabled: false # Disable Ingress API

        # Deployment Configuration
        deployment:
            replicas: 1 # Single replica for home-lab
            kind: Deployment

        # Resource Limits (home-lab constraints)
        resources:
            requests:
                cpu: 100m
                memory: 128Mi
            limits:
                cpu: 500m
                memory: 512Mi

        # Entrypoints Configuration
        ports:
            web:
                port: 80
                protocol: TCP
                exposedPort: 80
            websecure:
                port: 443
                protocol: TCP
                exposedPort: 443
                tls:
                    enabled: true
            tcp-514:
                port: 514
                protocol: TCP
                exposedPort: 514
            udp-514:
                port: 514
                protocol: UDP
                exposedPort: 514
            metrics:
                port: 9100
                protocol: TCP
                expose: true # Expose for Prometheus

        # Service Configuration
        service:
            type: LoadBalancer
            annotations:
                io.cilium/lb-ipam-ips: "192.168.35.16"
            spec:
                externalTrafficPolicy: Local # Preserve client IP

        # Metrics Configuration
        metrics:
            prometheus:
                enabled: true
                entryPoint: metrics
                addEntryPointsLabels: true
                addRoutersLabels: true
                addServicesLabels: true

        # Logging Configuration
        logs:
            general:
                level: INFO
            access:
                enabled: true
                format: json
                fields:
                    defaultMode: keep
                    headers:
                        defaultMode: keep # Drop sensitive headers
```

#### 2.1.2 Flux Kustomization

**File**: `kubernetes/apps/network/traefik/ks.yaml`

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
    name: traefik
    namespace: flux-system
spec:
    interval: 1h
    path: ./kubernetes/apps/network/traefik/app
    prune: true
    sourceRef:
        kind: GitRepository
        name: flux-system
        namespace: flux-system
    wait: true
    timeout: 5m
    healthChecks:
        - apiVersion: apps/v1
          kind: Deployment
          name: traefik
          namespace: network
```

### 2.2 GatewayClass Resource

#### 2.2.1 GatewayClass Specification

**Requirement Traceability**: US-1

**File**: `kubernetes/apps/network/gateway-api/gatewayclass.yaml`

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
    name: traefik
spec:
    controllerName: traefik.io/gateway-controller
    description: "Traefik Gateway API implementation for home-ops cluster"
    parametersRef:
        group: ""
        kind: ConfigMap
        name: traefik-gateway-config
        namespace: network
```

**ConfigMap for GatewayClass Parameters**:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
    name: traefik-gateway-config
    namespace: network
data:
    # Gateway-level configuration
    defaultCertificate: "68cc-io-tls"
    defaultCertificateNamespace: "network"
```

### 2.3 Gateway Resource

#### 2.3.1 Gateway Specification

**Requirement Traceability**: US-2, US-5

**File**: `kubernetes/apps/network/gateway-api/gateway.yaml`

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
    name: traefik-gateway
    namespace: network
    annotations:
        cert-manager.io/cluster-issuer: letsencrypt-production
spec:
    gatewayClassName: traefik

    listeners:
        # HTTP Listener (redirect to HTTPS)
        - name: web
          protocol: HTTP
          port: 80
          allowedRoutes:
              namespaces:
                  from: All

        # HTTPS Listener
        - name: websecure
          protocol: HTTPS
          port: 443
          allowedRoutes:
              namespaces:
                  from: All
          tls:
              mode: Terminate
              certificateRefs:
                  - kind: Secret
                    name: 68cc-io-tls
                    namespace: network

        # TCP Listener (syslog)
        - name: tcp-514
          protocol: TCP
          port: 514
          allowedRoutes:
              namespaces:
                  from: All
              kinds:
                  - kind: TCPRoute

        # UDP Listener (syslog)
        - name: udp-514
          protocol: UDP
          port: 514
          allowedRoutes:
              namespaces:
                  from: All
              kinds:
                  - kind: UDPRoute

    addresses:
        - type: IPAddress
          value: "192.168.35.16"
```

### 2.4 Middleware Resources

#### 2.4.1 Security Headers Middleware

**Requirement Traceability**: US-9

**File**: `kubernetes/apps/network/traefik/app/middleware-security-headers.yaml`

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
    name: security-headers
    namespace: network
spec:
    headers:
        # HSTS Configuration
        stsSeconds: 31536000 # 1 year
        stsIncludeSubdomains: true
        stsPreload: true

        # Frame Options
        frameDeny: true

        # Content Type Options
        contentTypeNosniff: true

        # XSS Protection
        browserXssFilter: true

        # Referrer Policy
        referrerPolicy: "strict-origin-when-cross-origin"

        # Content Security Policy
        contentSecurityPolicy: "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'"

        # Custom Response Headers
        customResponseHeaders:
            X-XSS-Protection: "1; mode=block"
            Permissions-Policy: "camera=(), microphone=(), geolocation=()"
```

#### 2.4.2 Compression Middleware

**Requirement Traceability**: US-6

**File**: `kubernetes/apps/network/traefik/app/middleware-compression.yaml`

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
    name: compression
    namespace: network
spec:
    compress:
        excludedContentTypes:
            - text/event-stream
            - application/grpc
        minResponseBodyBytes: 1024
```

#### 2.4.3 HTTPS Redirect Middleware

**Requirement Traceability**: US-6

**File**: `kubernetes/apps/network/traefik/app/middleware-https-redirect.yaml`

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
    name: https-redirect
    namespace: network
spec:
    redirectScheme:
        scheme: https
        permanent: true
```

### 2.5 HTTPRoute Updates

#### 2.5.1 HTTPRoute Pattern with Middleware

**Requirement Traceability**: US-3, US-9

**Example**: Grafana HTTPRoute

**File**: `kubernetes/apps/monitoring/grafana/instance/httproute.yaml`

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
    name: grafana
    namespace: monitoring
spec:
    # Gateway Reference (updated from Envoy to Traefik)
    parentRefs:
        - name: traefik-gateway
          namespace: network
          sectionName: websecure

    # Hostname Configuration
    hostnames:
        - "grafana.68cc.io"

    # Routing Rules
    rules:
        # Rule 1: Apply security headers and compression
        - matches:
              - path:
                    type: PathPrefix
                    value: "/"
          filters:
              # Security Headers Middleware
              - type: ExtensionRef
                extensionRef:
                    group: traefik.io
                    kind: Middleware
                    name: security-headers
                    namespace: network

              # Compression Middleware
              - type: ExtensionRef
                extensionRef:
                    group: traefik.io
                    kind: Middleware
                    name: compression
                    namespace: network

          # Backend Service
          backendRefs:
              - name: grafana
                namespace: monitoring
                port: 80
                weight: 100
```

#### 2.5.2 HTTP to HTTPS Redirect HTTPRoute

**Requirement Traceability**: US-6

**File**: `kubernetes/apps/network/gateway-api/httproute-redirect.yaml`

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
    name: http-to-https-redirect
    namespace: network
spec:
    parentRefs:
        - name: traefik-gateway
          namespace: network
          sectionName: web # HTTP listener

    hostnames:
        - "*.68cc.io"

    rules:
        - filters:
              - type: ExtensionRef
                extensionRef:
                    group: traefik.io
                    kind: Middleware
                    name: https-redirect
                    namespace: network
          backendRefs: [] # No backend for redirect
```

### 2.6 TCPRoute Updates

#### 2.6.1 TCPRoute Pattern

**Requirement Traceability**: US-4

**Example**: VictoriaLogs TCPRoute

**File**: `kubernetes/apps/monitoring/victoria-logs/app/tcproute.yaml`

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TCPRoute
metadata:
    name: victoria-logs-syslog-tcp
    namespace: monitoring
spec:
    # Gateway Reference (updated from Envoy to Traefik)
    parentRefs:
        - name: traefik-gateway
          namespace: network
          sectionName: tcp-514

    # Backend Service
    rules:
        - backendRefs:
              - name: victoria-logs
                namespace: monitoring
                port: 514
                weight: 100
```

### 2.7 UDPRoute Updates

#### 2.7.1 UDPRoute Pattern

**Requirement Traceability**: US-4

**Example**: VictoriaLogs UDPRoute

**File**: `kubernetes/apps/monitoring/victoria-logs/app/udproute.yaml`

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: UDPRoute
metadata:
    name: victoria-logs-syslog-udp
    namespace: monitoring
spec:
    # Gateway Reference (updated from Envoy to Traefik)
    parentRefs:
        - name: traefik-gateway
          namespace: network
          sectionName: udp-514

    # Backend Service
    rules:
        - backendRefs:
              - name: victoria-logs
                namespace: monitoring
                port: 514
                weight: 100
```

### 2.8 Observability Configuration

#### 2.8.1 Prometheus ServiceMonitor

**Requirement Traceability**: US-7

**File**: `kubernetes/apps/network/traefik/app/servicemonitor.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
    name: traefik
    namespace: network
    labels:
        app.kubernetes.io/name: traefik
        app.kubernetes.io/instance: traefik
spec:
    selector:
        matchLabels:
            app.kubernetes.io/name: traefik
            app.kubernetes.io/instance: traefik

    endpoints:
        - port: metrics
          interval: 30s
          path: /metrics
          scheme: http

          # Metric relabeling
          metricRelabelings:
              - sourceLabels: [__name__]
                regex: "traefik_.*"
                action: keep
```

#### 2.8.2 Grafana Dashboard ConfigMap

**Requirement Traceability**: US-7

**File**: `kubernetes/apps/network/traefik/app/dashboard.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
    name: traefik-dashboard
    namespace: monitoring
    labels:
        grafana_dashboard: "1"
data:
    traefik-gateway.json: |
        {
          "dashboard": {
            "title": "Traefik Gateway API",
            "panels": [
              {
                "title": "Request Rate",
                "targets": [
                  {
                    "expr": "rate(traefik_entrypoint_requests_total[5m])"
                  }
                ]
              },
              {
                "title": "Response Time (p95)",
                "targets": [
                  {
                    "expr": "histogram_quantile(0.95, rate(traefik_entrypoint_request_duration_seconds_bucket[5m]))"
                  }
                ]
              },
              {
                "title": "Error Rate",
                "targets": [
                  {
                    "expr": "rate(traefik_entrypoint_requests_total{code=~\"5..\"}[5m])"
                  }
                ]
              }
            ]
          }
        }
```

---

## 3. Migration Implementation Strategy

### 3.1 Blue-Green Migration Phases

**Requirement Traceability**: US-1, US-2, US-8

#### Phase 1: Traefik Deployment (Day 0)

**Objective**: Deploy Traefik alongside Envoy Gateway with temporary test hostname

**Steps**:

1. Deploy Traefik HelmRelease with Gateway API provider enabled
2. Create GatewayClass and Gateway resources
3. Create Middleware resources (security-headers, compression, https-redirect)
4. Deploy test HTTPRoute with hostname `traefik-test.68cc.io`
5. Wait for LoadBalancer IP assignment (192.168.35.16)
6. Wait for Traefik pods to reach Ready state

**Validation**:

- ✅ Traefik pod running: `kubectl get pods -n network -l app.kubernetes.io/name=traefik --context home`
- ✅ LoadBalancer IP assigned: `kubectl get svc traefik -n network --context home`
- ✅ Gateway status Ready: `kubectl get gateway traefik-gateway -n network --context home`
- ✅ Test HTTPRoute accessible: `curl -kv https://traefik-test.68cc.io`

**Rollback**: Delete Traefik HelmRelease, no impact to production

---

#### Phase 2: HTTPRoute Migration (Day 1)

**Objective**: Update all HTTPRoute resources to reference Traefik Gateway

**Steps**:

1. Update HTTPRoute parentRefs from `envoy-gateway` to `traefik-gateway`
2. Add security-headers middleware via ExtensionRef filter
3. Add compression middleware via ExtensionRef filter
4. Update sectionName from `https` to `websecure`
5. Commit and push changes to Git repository
6. Force Flux reconciliation: `task reconcile`

**HTTPRoute Updates**:

```bash
# Applications to update:
- kubernetes/apps/flux-system/flux-instance/app/httproute.yaml
- kubernetes/apps/monitoring/grafana/instance/httproute.yaml
- kubernetes/apps/toolhive/httproute.yaml
```

**Git Commit Pattern**:

```bash
git add kubernetes/apps/*/*/app/httproute.yaml
git commit -m "feat(network): migrate HTTPRoutes to Traefik Gateway

- Update parentRefs to traefik-gateway
- Add security-headers middleware
- Add compression middleware
- Update listener sectionName to websecure

Refs: US-3, US-9"
git push
```

**Validation**:

- ✅ All HTTPRoutes show Accepted status: `kubectl get httproute -A --context home`
- ✅ Applications accessible via HTTPS: `curl -kv https://grafana.68cc.io`
- ✅ Security headers present: `curl -kI https://grafana.68cc.io | grep -E "(Strict-Transport-Security|X-Frame-Options)"`
- ✅ Compression working: `curl -H "Accept-Encoding: gzip" -I https://grafana.68cc.io | grep "Content-Encoding"`

**Rollback**:

```bash
git revert HEAD
git push
task reconcile
```

---

#### Phase 3: TCPRoute and UDPRoute Migration (Day 1)

**Objective**: Update TCPRoute and UDPRoute resources to reference Traefik Gateway

**Steps**:

1. Update TCPRoute parentRefs to `traefik-gateway` with sectionName `tcp-514`
2. Update UDPRoute parentRefs to `traefik-gateway` with sectionName `udp-514`
3. Commit and push changes
4. Force Flux reconciliation

**Route Updates**:

```bash
# Routes to update:
- kubernetes/apps/monitoring/victoria-logs/app/tcproute.yaml
- kubernetes/apps/monitoring/victoria-logs/app/udproute.yaml
```

**Validation**:

- ✅ TCPRoute status Accepted: `kubectl get tcproute -A --context home`
- ✅ UDPRoute status Accepted: `kubectl get udproute -A --context home`
- ✅ Syslog TCP working: `logger -n 192.168.35.16 -P 514 -T "Test TCP syslog"`
- ✅ Syslog UDP working: `logger -n 192.168.35.16 -P 514 "Test UDP syslog"`
- ✅ VictoriaLogs receiving logs: `kubectl logs -n monitoring -l app=victoria-logs --tail=10 --context home`

**Rollback**: Same as Phase 2

---

#### Phase 4: Monitoring Validation (Day 2)

**Objective**: Validate observability integration and monitor for 24 hours

**Steps**:

1. Verify Prometheus scraping Traefik metrics
2. Import Grafana dashboard for Traefik Gateway
3. Configure alerts for Traefik errors and high latency
4. Monitor for 24 hours

**Validation**:

- ✅ Prometheus targets up: Check Prometheus UI for `traefik` target
- ✅ Metrics available: Query `traefik_entrypoint_requests_total` in Prometheus
- ✅ Dashboard displaying data: Open Grafana dashboard "Traefik Gateway API"
- ✅ No error alerts firing for 24 hours
- ✅ Response times within baseline (<100ms p95)

**Rollback**: If issues detected, revert to Phase 2 state

---

#### Phase 5: Envoy Gateway Decommission (Day 3)

**Objective**: Remove Envoy Gateway resources after successful migration

**Steps**:

1. Delete Envoy Gateway HelmRelease
2. Delete EnvoyProxy resource
3. Delete GatewayClass `envoy-gateway`
4. Delete Gateway `envoy-gateway`
5. Commit and push changes

**Resources to Delete**:

```bash
# Delete Envoy Gateway deployment
flux delete helmrelease envoy-gateway -n network --context home

# Delete Gateway API resources
kubectl delete gateway envoy-gateway -n network --context home
kubectl delete gatewayclass envoy-gateway --context home

# Remove from Git
git rm -r kubernetes/apps/network/envoy-gateway/
git commit -m "feat(network): decommission Envoy Gateway after Traefik migration

- Remove envoy-gateway HelmRelease
- Remove envoy-gateway Gateway and GatewayClass
- Complete migration to Traefik Gateway API provider

Refs: US-8"
git push
```

**Validation**:

- ✅ Envoy Gateway pods terminated: `kubectl get pods -n network -l app=envoy-gateway --context home` (should return empty)
- ✅ All routes still accessible via Traefik
- ✅ No increase in error rates
- ✅ Prometheus metrics stable

**Rollback**: Not recommended after decommission; deploy new Envoy Gateway if critical issues

---

### 3.2 Pre-Migration Checklist

- [ ] Backup current Gateway API resources: `kubectl get gateway,httproute,tcproute,udproute -A -o yaml > envoy-backup.yaml --context home`
- [ ] Document all current routes: `kubectl get httproute,tcproute,udproute -A --context home`
- [ ] Verify Cilium LBIPAM has available IPs: `kubectl get ippools -n kube-system --context home`
- [ ] Confirm cert-manager certificate valid: `kubectl get certificate -n network --context home`
- [ ] Review Traefik Helm chart changelog for breaking changes
- [ ] Test Traefik deployment in isolated namespace first
- [ ] Prepare rollback procedure documentation
- [ ] Schedule migration during low-traffic window
- [ ] Notify team of migration timeline

### 3.3 Post-Migration Validation

**Functional Testing**:

- [ ] All HTTPRoutes return HTTP 200
- [ ] HTTPS certificates valid and auto-renewing
- [ ] Security headers present on all HTTPS responses
- [ ] Compression working for compressible content
- [ ] TCPRoute forwarding syslog correctly
- [ ] UDPRoute forwarding syslog correctly
- [ ] HTTP to HTTPS redirect working
- [ ] Wildcard hostname routing working

**Performance Testing**:

- [ ] Response time p95 within baseline (<100ms)
- [ ] No increase in 5xx error rates
- [ ] CPU and memory usage stable (<512Mi)
- [ ] LoadBalancer IP responding to traffic

**Observability Testing**:

- [ ] Prometheus scraping metrics successfully
- [ ] Grafana dashboard displaying Traefik metrics
- [ ] Traefik access logs in JSON format
- [ ] Alert rules configured and not firing

---

## 4. Testing Strategy

### 4.1 Unit Testing (Per Component)

#### 4.1.1 GatewayClass Validation

**Test**: Verify GatewayClass accepted by Traefik controller

```bash
# Expected status.conditions:
# - type: Accepted
#   status: "True"
#   reason: Accepted

kubectl get gatewayclass traefik -o yaml --context home | grep -A 5 "conditions:"
```

**Pass Criteria**:

- Status shows `Accepted: True`
- Controller name matches `traefik.io/gateway-controller`

---

#### 4.1.2 Gateway Validation

**Test**: Verify Gateway listeners programmed correctly

```bash
# Expected status.listeners[]:
# - name: web (port 80, protocol HTTP)
# - name: websecure (port 443, protocol HTTPS)
# - name: tcp-514 (port 514, protocol TCP)
# - name: udp-514 (port 514, protocol UDP)

kubectl get gateway traefik-gateway -n network -o yaml --context home | grep -A 20 "status:"
```

**Pass Criteria**:

- All 4 listeners show `Ready: True`
- LoadBalancer IP assigned: 192.168.35.16
- TLS certificate referenced correctly

---

#### 4.1.3 Middleware Validation

**Test**: Verify Middleware resources created

```bash
kubectl get middleware -n network --context home
```

**Expected Output**:

```
NAME                AGE
security-headers    1m
compression         1m
https-redirect      1m
```

**Pass Criteria**:

- All Middleware resources exist
- No errors in kubectl describe output

---

### 4.2 Integration Testing (Cross-Component)

#### 4.2.1 HTTPRoute with Security Headers

**Test**: Verify security headers applied to HTTPS response

```bash
curl -kI https://grafana.68cc.io
```

**Expected Headers**:

```
HTTP/2 200
strict-transport-security: max-age=31536000; includeSubDomains; preload
x-frame-options: DENY
x-content-type-options: nosniff
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin
permissions-policy: camera=(), microphone=(), geolocation=()
content-security-policy: default-src 'self'; ...
```

**Pass Criteria** (US-9):

- ✅ All security headers present
- ✅ HSTS includes preload directive
- ✅ CSP policy configured

---

#### 4.2.2 HTTPRoute with Compression

**Test**: Verify gzip compression working

```bash
curl -H "Accept-Encoding: gzip" -I https://grafana.68cc.io
```

**Expected Headers**:

```
content-encoding: gzip
vary: Accept-Encoding
```

**Pass Criteria** (US-6):

- ✅ Content-Encoding header present
- ✅ Vary header includes Accept-Encoding

---

#### 4.2.3 HTTP to HTTPS Redirect

**Test**: Verify redirect working

```bash
curl -I http://grafana.68cc.io
```

**Expected Response**:

```
HTTP/1.1 301 Moved Permanently
Location: https://grafana.68cc.io
```

**Pass Criteria** (US-6):

- ✅ Status code 301
- ✅ Location header points to HTTPS

---

#### 4.2.4 TCPRoute Forwarding

**Test**: Verify TCP syslog forwarding

```bash
# Send test syslog message via TCP
logger -n 192.168.35.16 -P 514 -T "Test TCP message from migration validation"

# Verify VictoriaLogs received message
kubectl logs -n monitoring -l app=victoria-logs --tail=20 --context home | grep "Test TCP message"
```

**Pass Criteria** (US-4):

- ✅ Message appears in VictoriaLogs logs within 5 seconds
- ✅ No connection errors in logger output

---

#### 4.2.5 UDPRoute Forwarding

**Test**: Verify UDP syslog forwarding

```bash
# Send test syslog message via UDP
logger -n 192.168.35.16 -P 514 "Test UDP message from migration validation"

# Verify VictoriaLogs received message
kubectl logs -n monitoring -l app=victoria-logs --tail=20 --context home | grep "Test UDP message"
```

**Pass Criteria** (US-4):

- ✅ Message appears in VictoriaLogs logs within 5 seconds

---

### 4.3 End-to-End Testing

#### 4.3.1 Full Application Flow Test

**Test**: Verify complete request flow through Traefik to backend

```bash
# Test Grafana application
curl -kv https://grafana.68cc.io/api/health
```

**Expected Behavior**:

1. DNS resolves to 192.168.35.16
2. TLS handshake succeeds with valid certificate
3. Traefik applies security headers middleware
4. Traefik applies compression middleware
5. Request forwarded to Grafana backend
6. Grafana returns HTTP 200 with `{"database": "ok"}`
7. Security headers present in response

**Pass Criteria** (US-1, US-2, US-3, US-5, US-9):

- ✅ HTTP 200 status
- ✅ Valid TLS certificate
- ✅ Security headers present
- ✅ Compression applied
- ✅ Backend responds correctly

---

#### 4.3.2 Multi-Namespace Routing Test

**Test**: Verify routes from different namespaces work

```bash
# Test routes from multiple namespaces
curl -kI https://grafana.68cc.io          # monitoring namespace
curl -kI https://flux.68cc.io             # flux-system namespace
curl -kI https://toolhive.68cc.io         # toolhive namespace
```

**Pass Criteria**:

- ✅ All routes return HTTP 200
- ✅ All routes have security headers
- ✅ No cross-namespace permission errors

---

### 4.4 Performance Testing

#### 4.4.1 Load Test

**Test**: Verify Traefik handles expected load

```bash
# Use hey tool for load testing (install if needed)
hey -n 1000 -c 10 https://grafana.68cc.io/
```

**Pass Criteria** (US-7):

- ✅ P95 latency <100ms
- ✅ No 5xx errors
- ✅ Memory usage <512Mi
- ✅ CPU usage <500m

---

#### 4.4.2 Prometheus Metrics Test

**Test**: Verify metrics collection working

```bash
# Query Prometheus for Traefik metrics
kubectl port-forward -n monitoring svc/prometheus 9090:9090 --context home

# Open browser to http://localhost:9090 and query:
# traefik_entrypoint_requests_total
# traefik_entrypoint_request_duration_seconds_bucket
# traefik_service_requests_total
```

**Pass Criteria** (US-7):

- ✅ All 3 metric types present
- ✅ Metrics updating in real-time
- ✅ Labels include entrypoint, service, method, code

---

### 4.5 Rollback Testing

#### 4.5.1 Rollback Procedure Validation

**Test**: Verify rollback to Envoy Gateway works

```bash
# Revert Git commit
git revert HEAD
git push

# Force Flux reconciliation
task reconcile

# Wait for reconciliation
kubectl wait --for=condition=Ready helmrelease/envoy-gateway -n network --timeout=300s --context home
```

**Pass Criteria**:

- ✅ Envoy Gateway pods running within 5 minutes
- ✅ All routes accessible via Envoy Gateway
- ✅ No service interruption >1 minute

---

## 5. Rollback Procedures

### 5.1 Phase 1 Rollback (Traefik Deployment)

**Scenario**: Traefik fails to deploy or pass health checks

**Procedure**:

```bash
# Delete Traefik HelmRelease
flux delete helmrelease traefik -n network --context home

# Delete Gateway resources
kubectl delete gateway traefik-gateway -n network --context home
kubectl delete gatewayclass traefik --context home

# Remove from Git
git rm -r kubernetes/apps/network/traefik/
git commit -m "rollback: remove failed Traefik deployment"
git push
```

**Impact**: None - production still on Envoy Gateway

---

### 5.2 Phase 2/3 Rollback (Route Migration)

**Scenario**: Routes not working after migration or performance degraded

**Procedure**:

```bash
# Revert Git commit
git log --oneline -5  # Find commit hash to revert
git revert <commit-hash>
git push

# Force Flux reconciliation
task reconcile

# Monitor route status
watch kubectl get httproute,tcproute,udproute -A --context home
```

**Impact**: Brief interruption (<30 seconds) while routes reconfigure

---

### 5.3 Phase 5 Rollback (Envoy Decommission)

**Scenario**: Critical issue discovered after Envoy removal

**Procedure**:

```bash
# Restore Envoy Gateway from backup
git revert <decommission-commit-hash>
git push

# Force reconciliation
task reconcile

# Wait for Envoy pods
kubectl wait --for=condition=Ready pod -l app=envoy-gateway -n network --timeout=300s --context home

# Update routes back to Envoy (manual)
# This requires re-updating all parentRefs in routes
```

**Impact**: Significant downtime (5-10 minutes) - avoid if possible

---

## 6. Monitoring and Alerting

### 6.1 Prometheus Alert Rules

**File**: `kubernetes/apps/monitoring/prometheus/app/traefik-alerts.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
    name: traefik-alerts
    namespace: monitoring
    labels:
        prometheus: kube-prometheus
data:
    traefik-alerts.yaml: |
        groups:
          - name: traefik
            interval: 30s
            rules:
              # High Error Rate Alert
              - alert: TraefikHighErrorRate
                expr: |
                  (
                    sum(rate(traefik_entrypoint_requests_total{code=~"5.."}[5m]))
                    /
                    sum(rate(traefik_entrypoint_requests_total[5m]))
                  ) > 0.05
                for: 5m
                labels:
                  severity: warning
                  component: traefik
                annotations:
                  summary: "Traefik high error rate (>5%)"
                  description: "Traefik error rate is {{ $value | humanizePercentage }} for entrypoint {{ $labels.entrypoint }}"

              # High Latency Alert
              - alert: TraefikHighLatency
                expr: |
                  histogram_quantile(0.95,
                    sum(rate(traefik_entrypoint_request_duration_seconds_bucket[5m])) by (le, entrypoint)
                  ) > 0.5
                for: 10m
                labels:
                  severity: warning
                  component: traefik
                annotations:
                  summary: "Traefik high latency (p95 >500ms)"
                  description: "Traefik p95 latency is {{ $value | humanizeDuration }} for entrypoint {{ $labels.entrypoint }}"

              # Backend Down Alert
              - alert: TraefikBackendDown
                expr: |
                  traefik_service_server_up == 0
                for: 2m
                labels:
                  severity: critical
                  component: traefik
                annotations:
                  summary: "Traefik backend down"
                  description: "Backend {{ $labels.service }} is down for >2 minutes"

              # Certificate Expiring Alert
              - alert: TraefikCertificateExpiring
                expr: |
                  (traefik_tls_certs_not_after - time()) / 86400 < 7
                for: 1h
                labels:
                  severity: warning
                  component: traefik
                annotations:
                  summary: "Traefik TLS certificate expiring soon"
                  description: "Certificate for {{ $labels.cn }} expires in {{ $value | humanizeDuration }}"
```

### 6.2 Grafana Dashboard Metrics

**Key Metrics to Monitor**:

1. **Request Rate**:
    - Query: `rate(traefik_entrypoint_requests_total[5m])`
    - Threshold: Baseline ±20%

2. **Error Rate**:
    - Query: `rate(traefik_entrypoint_requests_total{code=~"5.."}[5m])`
    - Threshold: <1% error rate

3. **Response Time P95**:
    - Query: `histogram_quantile(0.95, rate(traefik_entrypoint_request_duration_seconds_bucket[5m]))`
    - Threshold: <100ms for home-lab

4. **Backend Health**:
    - Query: `traefik_service_server_up`
    - Threshold: All backends = 1 (up)

5. **TLS Certificate Expiry**:
    - Query: `(traefik_tls_certs_not_after - time()) / 86400`
    - Threshold: >30 days

---

## 7. Security Considerations

### 7.1 TLS Configuration

**Minimum TLS Version**: TLS 1.2
**Cipher Suites**: Modern cipher suites only (AES-GCM preferred)
**Certificate Management**: Automated via cert-manager with Let's Encrypt

**Traefik TLS Options** (to be added if needed):

```yaml
apiVersion: traefik.io/v1alpha1
kind: TLSOption
metadata:
    name: default
    namespace: network
spec:
    minVersion: VersionTLS12
    cipherSuites:
        - TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
        - TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
        - TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305
    curvePreferences:
        - CurveP521
        - CurveP384
    sniStrict: true
```

### 7.2 Security Headers Enforcement

**All HTTPS Routes** MUST include security-headers middleware (US-9)

**Verification**:

```bash
# Check all HTTPRoutes have security-headers middleware
kubectl get httproute -A -o yaml --context home | grep -A 10 "extensionRef" | grep "security-headers"
```

**Remediation**: Add security-headers ExtensionRef to any missing HTTPRoutes

### 7.3 Access Control

**Gateway AllowedRoutes**: `from: All` (allows routes from any namespace)

**Security Trade-off**: Simplified management vs namespace isolation
**Mitigation**: Monitor route creation with admission webhooks (future enhancement)

### 7.4 Secret Management

**cert-manager Certificate Secret**: `68cc-io-tls` in `network` namespace
**Access**: Only Gateway and cert-manager have RBAC permissions

**RBAC Verification**:

```bash
kubectl auth can-i get secret/68cc-io-tls -n network --as=system:serviceaccount:network:traefik --context home
```

---

## 8. Performance Optimization

### 8.1 Resource Allocation

**Traefik Pod Resources** (single replica):

- CPU Request: 100m
- CPU Limit: 500m
- Memory Request: 128Mi
- Memory Limit: 512Mi

**Rationale**: Home-lab scale with <20 routes and <100 req/s traffic

### 8.2 Compression Settings

**Enabled Content Types**: text/\*, application/json, application/javascript, application/xml
**Excluded**: text/event-stream, application/grpc
**Minimum Size**: 1024 bytes

### 8.3 HTTP/2 and HTTP/3

**HTTP/2**: Enabled by default on HTTPS listener
**HTTP/3**: Not enabled (requires UDP/443 and experimental in Traefik)

**Future Enhancement**: Enable HTTP/3 when stable

### 8.4 Connection Pooling

**Default Settings**: Traefik default connection pooling (no tuning needed for home-lab)

---

## 9. Requirements Traceability Matrix

| Requirement              | Design Component     | Implementation File                                                    | Validation Method                           |
| ------------------------ | -------------------- | ---------------------------------------------------------------------- | ------------------------------------------- |
| US-1: Traefik Deployment | Section 2.1          | `kubernetes/apps/network/traefik/app/helmrelease.yaml`                 | kubectl get pods, E2E test 4.3.1            |
| US-2: Gateway Migration  | Section 2.3          | `kubernetes/apps/network/gateway-api/gateway.yaml`                     | kubectl get gateway, Integration test 4.2.1 |
| US-3: HTTPRoute Updates  | Section 2.5          | `kubernetes/apps/monitoring/grafana/instance/httproute.yaml` (example) | E2E test 4.3.1, 4.3.2                       |
| US-4: TCPRoute/UDPRoute  | Section 2.6, 2.7     | `kubernetes/apps/monitoring/victoria-logs/app/{tcp,udp}route.yaml`     | Integration test 4.2.4, 4.2.5               |
| US-5: TLS Integration    | Section 2.3.1        | Gateway TLS configuration                                              | Unit test 4.1.2, E2E test 4.3.1             |
| US-6: Traffic Policies   | Section 2.4.2, 2.4.3 | Compression and redirect Middleware                                    | Integration test 4.2.2, 4.2.3               |
| US-7: Observability      | Section 2.8          | `kubernetes/apps/network/traefik/app/servicemonitor.yaml`              | Performance test 4.4.2                      |
| US-8: Envoy Decommission | Section 3.1 Phase 5  | Delete envoy-gateway resources                                         | Post-migration validation 3.3               |
| US-9: Security Headers   | Section 2.4.1        | `kubernetes/apps/network/traefik/app/middleware-security-headers.yaml` | Integration test 4.2.1                      |

---

## 10. Glossary

- **Gateway API**: Kubernetes SIG-Network API for ingress traffic management (GA in v1.0)
- **Traefik Gateway API Provider**: Native Gateway API implementation in Traefik v3.x
- **ExtensionRef**: Gateway API mechanism for vendor-specific extensions (Middleware)
- **Middleware**: Traefik CRD for traffic policies (headers, compression, auth, etc.)
- **Blue-Green Migration**: Deployment strategy with old/new coexistence and atomic cutover
- **Cilium LBIPAM**: LoadBalancer IP Address Management integrated with Cilium CNI
- **cert-manager**: Kubernetes certificate management controller (Let's Encrypt integration)
- **FluxCD**: GitOps continuous delivery tool for Kubernetes
- **HSTS**: HTTP Strict Transport Security (forces HTTPS)
- **CSP**: Content Security Policy (XSS mitigation)

---

## 11. Approval

**Design Document Status**: Draft
**Awaiting Approval**: Yes

**Approval Criteria**:

- [ ] All 9 user stories addressed in design
- [ ] Architecture diagrams clear and complete
- [ ] Component specifications include YAML manifests
- [ ] Migration strategy has detailed phases with rollback
- [ ] Testing strategy covers unit, integration, E2E
- [ ] Security considerations documented
- [ ] Requirements traceability matrix complete

**Next Phase**: Task Breakdown (after design approval)

---

**Design Completed**: 2025-12-06
**Document Version**: 1.0
