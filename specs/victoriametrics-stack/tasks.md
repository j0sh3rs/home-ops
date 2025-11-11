# Tasks: VictoriaMetrics Stack Implementation

**Progress:** 0/10 tasks completed

---

## Phase 1: Pre-Deployment Preparation

### Task 1: Create S3 Buckets in Minio
**Fulfills:** AC-vm-001-04, AC-vm-002-02, AC-vm-004-02
**Dependencies:** None
**Estimated Effort:** 15 minutes

**Implementation Steps:**
1. Access Minio console at https://s3.68cc.io
2. Create bucket `victoriametrics-data` with default settings
3. Create bucket `victorialogs-data` with default settings
4. Verify buckets are accessible via S3 API

**EARS Definition of Done:**
- [ ] **DoD-001-01**: WHEN buckets are created, SHALL appear in Minio console bucket list {confidence: 100%}
- [ ] **DoD-001-02**: WHEN S3 API is queried, SHALL return 200 OK for HEAD requests to both buckets {confidence: 95%}
- [ ] **DoD-001-03**: WHERE bucket permissions are set, SHALL allow read/write access with test credentials {confidence: 90%}

**Validation Commands:**
```bash
# Verify bucket existence
aws --endpoint-url https://s3.68cc.io s3 ls

# Expected output should include:
# victoriametrics-data
# victorialogs-data

# Test bucket access
aws --endpoint-url https://s3.68cc.io s3 ls s3://victoriametrics-data/
aws --endpoint-url https://s3.68cc.io s3 ls s3://victorialogs-data/
```

**Rollback:** Delete buckets via Minio console if needed

---

### Task 2: Create SOPS-Encrypted S3 Secrets
**Fulfills:** NFR-vm-7f3a9c2d-SEC-001, ADR-006
**Dependencies:** Task 1 (buckets must exist)
**Estimated Effort:** 20 minutes

**Implementation Steps:**
1. Create `kubernetes/apps/monitoring/victoria-metrics-k8s-stack/app/secret.sops.yaml`:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: victoriametrics-s3-secret
  namespace: monitoring
type: Opaque
stringData:
  S3_ACCESS_KEY_ID: cloudnativepg
  S3_SECRET_ACCESS_KEY: cloudnativepg123
  S3_ENDPOINT: https://s3.68cc.io
  S3_BUCKET: victoriametrics-data
```

2. Create `kubernetes/apps/monitoring/victoria-logs-cluster/app/secret.sops.yaml`:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: victorialogs-s3-secret
  namespace: monitoring
type: Opaque
stringData:
  S3_ACCESS_KEY_ID: cloudnativepg
  S3_SECRET_ACCESS_KEY: cloudnativepg123
  S3_ENDPOINT: https://s3.68cc.io
  S3_BUCKET: victorialogs-data
```

3. Encrypt both secrets with SOPS:
```bash
cd kubernetes/apps/monitoring/victoria-metrics-k8s-stack/app
sops --encrypt --age age1qwwzsz6z2mmu6hpmjt2he7nepmnhutmhehvkva7l5zy5xzf08d5s5n4d6n \
  --encrypted-regex '^(data|stringData)$' \
  --in-place secret.sops.yaml

cd ../victoria-logs-cluster/app
sops --encrypt --age age1qwwzsz6z2mmu6hpmjt2he7nepmnhutmhehvkva7l5zy5xzf08d5s5n4d6n \
  --encrypted-regex '^(data|stringData)$' \
  --in-place secret.sops.yaml
```

**EARS Definition of Done:**
- [ ] **DoD-002-01**: WHEN secrets are created, SHALL contain encrypted data fields {confidence: 100%}
- [ ] **DoD-002-02**: WHERE SOPS encryption is applied, SHALL use age key age1qwwzsz... {confidence: 100%}
- [ ] **DoD-002-03**: IF secrets are decrypted, SHALL contain S3 credentials matching Minio access {confidence: 95%}
- [ ] **DoD-002-04**: WHILE pre-commit hooks run, SHALL pass detect-secrets and check-unencrypted-secrets {confidence: 100%}

**Validation Commands:**
```bash
# Verify encryption
grep -q "sops:" kubernetes/apps/monitoring/victoria-metrics-k8s-stack/app/secret.sops.yaml
grep -q "sops:" kubernetes/apps/monitoring/victoria-logs-cluster/app/secret.sops.yaml

# Verify decryption works
sops --decrypt kubernetes/apps/monitoring/victoria-metrics-k8s-stack/app/secret.sops.yaml | grep S3_ACCESS_KEY_ID
```

**Rollback:** Delete secret files if incorrect

---

## Phase 2: VictoriaMetrics k8s Stack Deployment

### Task 3: Create VictoriaMetrics Directory Structure
**Fulfills:** ADR-005 (FluxCD pattern compliance)
**Dependencies:** Task 2 (secrets must exist)
**Estimated Effort:** 10 minutes

**Implementation Steps:**
1. Create directory structure:
```bash
mkdir -p kubernetes/apps/monitoring/victoria-metrics-k8s-stack/app
```

2. Create `kubernetes/apps/monitoring/victoria-metrics-k8s-stack/ks.yaml`:
```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app victoria-metrics-k8s-stack
  namespace: flux-system
spec:
  targetNamespace: monitoring
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  path: ./kubernetes/apps/monitoring/victoria-metrics-k8s-stack/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  wait: false
  interval: 30m
  retryInterval: 1m
  timeout: 15m
```

3. Create `kubernetes/apps/monitoring/victoria-metrics-k8s-stack/app/kustomization.yaml`:
```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: monitoring
resources:
  - ./helmrelease.yaml
  - ./secret.sops.yaml
```

**EARS Definition of Done:**
- [ ] **DoD-003-01**: WHEN directory structure is created, SHALL match established FluxCD pattern {confidence: 100%}
- [ ] **DoD-003-02**: WHERE ks.yaml is defined, SHALL reference correct GitRepository source {confidence: 100%}
- [ ] **DoD-003-03**: IF kustomization.yaml is applied, SHALL include helmrelease and secret resources {confidence: 100%}

**Validation Commands:**
```bash
# Verify directory structure
ls -la kubernetes/apps/monitoring/victoria-metrics-k8s-stack/
ls -la kubernetes/apps/monitoring/victoria-metrics-k8s-stack/app/

# Verify files exist
test -f kubernetes/apps/monitoring/victoria-metrics-k8s-stack/ks.yaml
test -f kubernetes/apps/monitoring/victoria-metrics-k8s-stack/app/kustomization.yaml
```

**Rollback:** Remove directory structure

---

### Task 4: Create VictoriaMetrics HelmRelease
**Fulfills:** REQ-vm-7f3a9c2d-001, AC-vm-001-01 through AC-vm-001-05
**Dependencies:** Task 3 (directory structure)
**Estimated Effort:** 30 minutes

**Implementation Steps:**
1. Create `kubernetes/apps/monitoring/victoria-metrics-k8s-stack/app/helmrelease.yaml` with comprehensive configuration
2. Configure VMOperator with Prometheus CRD compatibility
3. Configure VMAgent with `selectAllByDefault: true` for ServiceMonitor discovery
4. Configure VMSingle with S3 backend using Minio compatibility settings
5. Configure VMAlert and VMAlertmanager with appropriate resources
6. Inject S3 credentials via environment variables

**Key Configuration Sections:**

```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: victoria-metrics-k8s-stack
spec:
  interval: 30m
  chart:
    spec:
      chart: victoria-metrics-k8s-stack
      version: 0.27.8
      sourceRef:
        kind: HelmRepository
        name: victoriametrics
        namespace: flux-system
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      strategy: rollback
      retries: 3
  values:
    # Operator configuration
    victoria-metrics-operator:
      enabled: true
      operator:
        disable_prometheus_converter: false
        enable_converter_ownership: true

    # VMAgent configuration - metrics scraping
    vmagent:
      enabled: true
      spec:
        selectAllByDefault: true  # AC-vm-007-01: Auto-discover ServiceMonitors
        scrapeInterval: 30s
        externalLabels:
          cluster: home-ops
        remoteWrite:
          - url: http://vmsingle-victoria-metrics-k8s-stack.monitoring.svc:8429/api/v1/write
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            memory: 1Gi

    # VMSingle configuration - metrics storage with S3
    vmsingle:
      enabled: true
      spec:
        retentionPeriod: "30d"
        replicaCount: 1
        extraEnv:
          - name: S3_ACCESS_KEY_ID
            valueFrom:
              secretKeyRef:
                name: victoriametrics-s3-secret
                key: S3_ACCESS_KEY_ID
          - name: S3_SECRET_ACCESS_KEY
            valueFrom:
              secretKeyRef:
                name: victoriametrics-s3-secret
                key: S3_SECRET_ACCESS_KEY
        extraArgs:
          remoteStorage.s3.endpoint: s3.68cc.io:443
          remoteStorage.s3.region: minio
          remoteStorage.s3.bucket: victoriametrics-data
          remoteStorage.s3.forcePathStyle: "true"
          remoteStorage.s3.accessKeyID: ${S3_ACCESS_KEY_ID}
          remoteStorage.s3.secretAccessKey: ${S3_SECRET_ACCESS_KEY}
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            memory: 2Gi  # AC-vm-001-05

    # VMAlert configuration
    vmalert:
      enabled: true
      spec:
        replicaCount: 1
        evaluationInterval: 30s
        datasource:
          url: http://vmsingle-victoria-metrics-k8s-stack.monitoring.svc:8429
        notifiers:
          - url: http://vmalertmanager-victoria-metrics-k8s-stack.monitoring.svc:9093
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            memory: 512Mi

    # VMAlertmanager configuration
    vmalertmanager:
      enabled: true
      spec:
        replicaCount: 1
        resources:
          requests:
            cpu: 50m
            memory: 128Mi
          limits:
            memory: 512Mi
```

**EARS Definition of Done:**
- [ ] **DoD-004-01**: WHEN HelmRelease is applied, SHALL create VMAgent, VMSingle, VMAlert, VMAlertmanager CRDs {confidence: 95%}
- [ ] **DoD-004-02**: WHERE VMAgent is configured, SHALL have selectAllByDefault: true {confidence: 100%}
- [ ] **DoD-004-03**: IF VMSingle starts, SHALL accept remote-write on port 8429 {confidence: 95%}
- [ ] **DoD-004-04**: WHILE VMSingle runs, SHALL inject S3 environment variables {confidence: 90%}
- [ ] **DoD-004-05**: WHERE memory limits are set, SHALL be <2Gi for all components {confidence: 100%}

**Validation Commands:**
```bash
# Verify HelmRelease exists
kubectl get helmrelease -n monitoring victoria-metrics-k8s-stack

# Verify CRDs created
kubectl get vmagent -n monitoring
kubectl get vmsingle -n monitoring
kubectl get vmalert -n monitoring
kubectl get vmalertmanager -n monitoring

# Verify pods running
kubectl get pods -n monitoring -l app.kubernetes.io/name=victoria-metrics-k8s-stack

# Check VMSingle environment variables
kubectl get statefulset -n monitoring vmsingle-victoria-metrics-k8s-stack -o yaml | grep -A 10 env:
```

**Rollback:** `kubectl delete helmrelease -n monitoring victoria-metrics-k8s-stack`

---

### Task 5: Verify VictoriaMetrics S3 Connectivity
**Fulfills:** AC-vm-002-02, AC-vm-002-03, AC-vm-002-05
**Dependencies:** Task 4 (VictoriaMetrics deployed)
**Estimated Effort:** 20 minutes

**Implementation Steps:**
1. Monitor VMSingle pod startup logs for S3 connection
2. Verify no authentication errors (learned from Tempo debugging)
3. Check S3 bucket for metric blocks
4. Test pod restart recovery from S3

**EARS Definition of Done:**
- [ ] **DoD-005-01**: WHEN VMSingle starts, SHALL connect to S3 without authentication errors {confidence: 90%}
- [ ] **DoD-005-02**: WHERE metrics are ingested, SHALL upload blocks to victoriametrics-data bucket {confidence: 85%}
- [ ] **DoD-005-03**: IF VMSingle pod restarts, SHALL recover data from S3 {confidence: 85%}
- [ ] **DoD-005-04**: WHILE running, SHALL show no S3 errors in logs for 5 minutes {confidence: 90%}

**Validation Commands:**
```bash
# Check VMSingle logs for S3 connection
kubectl logs -n monitoring statefulset/vmsingle-victoria-metrics-k8s-stack | grep -i s3

# Verify no auth errors (look for "Access Key Id" errors)
kubectl logs -n monitoring statefulset/vmsingle-victoria-metrics-k8s-stack | grep -i "access key"

# Check S3 bucket contents
aws --endpoint-url https://s3.68cc.io s3 ls s3://victoriametrics-data/

# Test pod restart recovery
kubectl delete pod -n monitoring -l app.kubernetes.io/name=vmsingle
# Wait 2 minutes
kubectl get pods -n monitoring -l app.kubernetes.io/name=vmsingle
kubectl logs -n monitoring -l app.kubernetes.io/name=vmsingle | tail -50
```

**Rollback:** Fix S3 configuration in HelmRelease if errors occur

---

### Task 6: Verify VMAgent ServiceMonitor Discovery
**Fulfills:** REQ-vm-7f3a9c2d-007, AC-vm-007-01, AC-vm-007-02, AC-vm-007-03
**Dependencies:** Task 5 (VictoriaMetrics healthy)
**Estimated Effort:** 15 minutes

**Implementation Steps:**
1. Query VMAgent for discovered ServiceMonitors
2. Verify existing ServiceMonitors are being scraped
3. Check VMAgent logs for scrape activity
4. Verify metrics are reaching VMSingle

**EARS Definition of Done:**
- [ ] **DoD-006-01**: WHEN VMAgent is running, SHALL discover all ServiceMonitors in cluster {confidence: 95%}
- [ ] **DoD-006-02**: WHERE ServiceMonitors exist, SHALL appear in VMAgent /targets endpoint {confidence: 90%}
- [ ] **DoD-006-03**: IF scraping is active, SHALL show scrape success rate >95% {confidence: 85%}
- [ ] **DoD-006-04**: WHILE metrics flow, SHALL remote-write to VMSingle without errors {confidence: 90%}

**Validation Commands:**
```bash
# Check VMAgent targets
kubectl port-forward -n monitoring svc/vmagent-victoria-metrics-k8s-stack 8429:8429 &
curl http://localhost:8429/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'

# Verify ServiceMonitor discovery count
kubectl get servicemonitor --all-namespaces --no-headers | wc -l

# Check VMAgent logs
kubectl logs -n monitoring deployment/vmagent-victoria-metrics-k8s-stack | grep -i "servicemonitor"

# Verify metrics in VMSingle
curl http://localhost:8429/api/v1/query?query=up | jq '.data.result | length'
```

**Rollback:** None (observation only)

---

## Phase 3: VictoriaLogs Cluster Deployment

### Task 7: Create VictoriaLogs Directory Structure and HelmRelease
**Fulfills:** REQ-vm-7f3a9c2d-003, AC-vm-003-02 through AC-vm-003-05
**Dependencies:** Task 2 (secret created)
**Estimated Effort:** 40 minutes

**Implementation Steps:**
1. Create directory structure matching FluxCD pattern
2. Create ks.yaml for FluxCD Kustomization
3. Create kustomization.yaml for resource list
4. Create comprehensive HelmRelease with vlinsert, vlselect, vlstorage configuration

**Directory Structure:**
```bash
kubernetes/apps/monitoring/victoria-logs-cluster/
├── ks.yaml
└── app/
    ├── kustomization.yaml
    ├── helmrelease.yaml
    └── secret.sops.yaml (from Task 2)
```

**HelmRelease Configuration Highlights:**
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: victoria-logs-cluster
spec:
  chart:
    spec:
      chart: victoria-logs-cluster
      version: 0.5.0
      sourceRef:
        kind: HelmRepository
        name: victoriametrics
        namespace: flux-system
  values:
    # vlinsert - log ingestion
    vlinsert:
      replicaCount: 1
      resources:
        requests:
          cpu: 100m
          memory: 256Mi
        limits:
          memory: 2Gi

    # vlselect - log querying
    vlselect:
      replicaCount: 1
      resources:
        requests:
          cpu: 100m
          memory: 256Mi
        limits:
          memory: 1Gi

    # vlstorage - log storage with S3
    vlstorage:
      replicaCount: 1
      retentionPeriod: "30d"
      env:
        - name: S3_ACCESS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: victorialogs-s3-secret
              key: S3_ACCESS_KEY_ID
        - name: S3_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: victorialogs-s3-secret
              key: S3_SECRET_ACCESS_KEY
      extraArgs:
        - -storageDataPath=/storage
        - -retentionPeriod=30d
        - -remoteWrite.url=s3://victorialogs-data?region=minio&force_path_style=true&endpoint=https://s3.68cc.io
      resources:
        requests:
          cpu: 100m
          memory: 512Mi
        limits:
          memory: 2Gi
```

**EARS Definition of Done:**
- [ ] **DoD-007-01**: WHEN HelmRelease is applied, SHALL create vlinsert, vlselect, vlstorage deployments {confidence: 95%}
- [ ] **DoD-007-02**: WHERE vlinsert is deployed, SHALL expose HTTP ingestion endpoint on port 8428 {confidence: 95%}
- [ ] **DoD-007-03**: IF vlstorage starts, SHALL inject S3 environment variables {confidence: 90%}
- [ ] **DoD-007-04**: WHILE components run, SHALL have memory limits <2Gi {confidence: 100%}
- [ ] **DoD-007-05**: WHERE vlselect is deployed, SHALL expose LogQL query endpoint on port 8481 {confidence: 95%}

**Validation Commands:**
```bash
# Verify HelmRelease
kubectl get helmrelease -n monitoring victoria-logs-cluster

# Verify deployments
kubectl get deployment -n monitoring -l app.kubernetes.io/name=victoria-logs-cluster

# Verify services
kubectl get svc -n monitoring | grep -E "(vlinsert|vlselect|vlstorage)"

# Check pod status
kubectl get pods -n monitoring -l app.kubernetes.io/name=victoria-logs-cluster
```

**Rollback:** `kubectl delete helmrelease -n monitoring victoria-logs-cluster`

---

### Task 8: Verify VictoriaLogs S3 Connectivity
**Fulfills:** REQ-vm-7f3a9c2d-004, AC-vm-004-02, AC-vm-004-03, AC-vm-004-05
**Dependencies:** Task 7 (VictoriaLogs deployed)
**Estimated Effort:** 20 minutes

**Implementation Steps:**
1. Monitor vlstorage pod logs for S3 connection
2. Verify no authentication errors
3. Test log ingestion and S3 upload
4. Verify pod restart recovery

**EARS Definition of Done:**
- [ ] **DoD-008-01**: WHEN vlstorage starts, SHALL connect to S3 without authentication errors {confidence: 90%}
- [ ] **DoD-008-02**: WHERE logs are ingested, SHALL upload chunks to victorialogs-data bucket {confidence: 85%}
- [ ] **DoD-008-03**: IF vlstorage pod restarts, SHALL recover from S3 {confidence: 85%}
- [ ] **DoD-008-04**: WHILE running, SHALL show no S3 errors in logs for 5 minutes {confidence: 90%}

**Validation Commands:**
```bash
# Check vlstorage logs
kubectl logs -n monitoring deployment/vlstorage-victoria-logs-cluster | grep -i s3

# Verify no auth errors
kubectl logs -n monitoring deployment/vlstorage-victoria-logs-cluster | grep -i "access key"

# Check S3 bucket for log chunks
aws --endpoint-url https://s3.68cc.io s3 ls s3://victorialogs-data/

# Test ingestion
kubectl port-forward -n monitoring svc/vlinsert 8428:8428 &
curl -X POST http://localhost:8428/insert/jsonline -d '{"_msg":"test log message","level":"info"}'

# Verify log in S3 (wait 1 minute for flush)
aws --endpoint-url https://s3.68cc.io s3 ls s3://victorialogs-data/ --recursive

# Test pod restart recovery
kubectl delete pod -n monitoring -l app=vlstorage
kubectl get pods -n monitoring -l app=vlstorage
```

**Rollback:** Fix S3 configuration if errors occur

---

## Phase 4: Grafana Integration and LGTM Removal

### Task 9: Update Grafana Datasources
**Fulfills:** REQ-vm-7f3a9c2d-005, AC-vm-005-01 through AC-vm-005-05
**Dependencies:** Task 6 (VictoriaMetrics healthy), Task 8 (VictoriaLogs healthy)
**Estimated Effort:** 25 minutes

**Implementation Steps:**
1. Backup current Grafana HelmRelease configuration
2. Update datasources section in `kubernetes/apps/monitoring/grafana/app/helmrelease.yaml`
3. Replace Prometheus/Mimir datasources with VictoriaMetrics
4. Add VictoriaLogs datasource with LogQL compatibility
5. Apply changes via Git commit and FluxCD reconciliation

**Datasource Configuration:**
```yaml
# Add to Grafana HelmRelease values
grafana:
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
        # Replace Prometheus/Mimir with VictoriaMetrics
        - name: VictoriaMetrics
          type: prometheus
          url: http://vmsingle-victoria-metrics-k8s-stack.monitoring.svc:8429
          access: proxy
          isDefault: true
          jsonData:
            timeInterval: 30s
            httpMethod: POST
          editable: false

        # Add VictoriaLogs for log aggregation
        - name: VictoriaLogs
          type: loki
          url: http://vlselect.monitoring.svc:8481/select/logsql
          access: proxy
          jsonData:
            maxLines: 1000
          editable: false
```

**EARS Definition of Done:**
- [ ] **DoD-009-01**: WHEN datasources are updated, SHALL include VictoriaMetrics with type: prometheus {confidence: 100%}
- [ ] **DoD-009-02**: WHERE VictoriaLogs datasource is added, SHALL use type: loki for compatibility {confidence: 95%}
- [ ] **DoD-009-03**: IF Grafana restarts, SHALL show both datasources as healthy {confidence: 90%}
- [ ] **DoD-009-04**: WHILE testing queries, PromQL queries SHALL return data from VictoriaMetrics {confidence: 90%}
- [ ] **DoD-009-05**: WHERE LogQL is used, SHALL return data from VictoriaLogs {confidence: 85%}

**Validation Commands:**
```bash
# Verify Grafana datasources via API
kubectl port-forward -n monitoring svc/grafana 3000:80 &
curl -u admin:password http://localhost:3000/api/datasources | jq '.[] | {name: .name, type: .type, url: .url}'

# Test datasource health
curl -u admin:password http://localhost:3000/api/datasources/name/VictoriaMetrics/health
curl -u admin:password http://localhost:3000/api/datasources/name/VictoriaLogs/health

# Test PromQL query
curl -u admin:password "http://localhost:3000/api/datasources/proxy/uid/victoriametrics/api/v1/query?query=up"

# Test LogQL query (if logs exist)
curl -u admin:password "http://localhost:3000/api/datasources/proxy/uid/victorialogs/loki/api/v1/query?query={job=\"test\"}"
```

**Rollback:** Git revert Grafana HelmRelease changes

---

### Task 10: Remove LGTM Stack Components
**Fulfills:** REQ-vm-7f3a9c2d-006, AC-vm-006-01 through AC-vm-006-04
**Dependencies:** Task 9 (Grafana updated and healthy)
**Estimated Effort:** 30 minutes

**Implementation Steps:**
1. Backup current monitoring kustomization
2. Comment out LGTM components in `kubernetes/apps/monitoring/kustomization.yaml`
3. Verify ServiceMonitors are NOT deleted (managed by applications, not LGTM stack)
4. Commit changes and reconcile FluxCD
5. Monitor component deletion without errors
6. Verify VMAgent continues scraping after LGTM removal

**Kustomization Changes:**
```yaml
# kubernetes/apps/monitoring/kustomization.yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./grafana/ks.yaml
  # - ./kube-prometheus-stack/ks.yaml  # REMOVED (AC-vm-006-01)
  # - ./mimir/ks.yaml                  # REMOVED (AC-vm-006-02)
  # - ./tempo/ks.yaml                  # REMOVED (AC-vm-006-03)
  - ./victoria-metrics-k8s-stack/ks.yaml  # ADDED
  - ./victoria-logs-cluster/ks.yaml       # ADDED
  - ./unpoller/ks.yaml
```

**EARS Definition of Done:**
- [ ] **DoD-010-01**: WHEN kube-prometheus-stack is removed, SHALL delete Prometheus StatefulSet {confidence: 100%}
- [ ] **DoD-010-02**: WHERE Mimir components exist, SHALL delete all Mimir deployments {confidence: 100%}
- [ ] **DoD-010-03**: IF Tempo is removed, SHALL delete Tempo StatefulSet {confidence: 100%}
- [ ] **DoD-010-04**: WHILE LGTM components delete, SHALL preserve all ServiceMonitor CRDs {confidence: 95%}
- [ ] **DoD-010-05**: WHERE VMAgent is scraping, SHALL continue without interruption {confidence: 90%}

**Validation Commands:**
```bash
# Verify LGTM components are gone
kubectl get statefulset -n monitoring prometheus-kube-prometheus-stack-prometheus 2>&1 | grep "NotFound"
kubectl get deployment -n monitoring | grep mimir | wc -l  # Should return 0
kubectl get statefulset -n monitoring tempo 2>&1 | grep "NotFound"

# Verify ServiceMonitors preserved
kubectl get servicemonitor --all-namespaces --no-headers | wc -l

# Verify VMAgent still scraping
kubectl logs -n monitoring deployment/vmagent-victoria-metrics-k8s-stack | tail -20 | grep "scrape"

# Verify metrics still flowing
kubectl port-forward -n monitoring svc/vmsingle-victoria-metrics-k8s-stack 8429:8429 &
curl http://localhost:8429/api/v1/query?query=up | jq '.data.result | length'
```

**Rollback:**
```bash
# Uncomment LGTM components in kustomization.yaml
git revert HEAD
flux reconcile kustomization cluster-apps -n flux-system
```

---

## Implementation Notes

### Big-Bang Deployment Risk Mitigation
- **Pre-validation:** Ensure VictoriaMetrics + VictoriaLogs fully operational before LGTM removal
- **Observability Gap:** Expect 2-5 minute gap during LGTM → Victoria transition
- **Rollback Window:** Keep LGTM components commented (not deleted) for 24 hours for emergency rollback

### S3 Configuration Best Practices (Tempo Lessons Learned)
- **Always verify:** `region: minio` and `s3ForcePathStyle: true` in all S3 configurations
- **Environment variables:** Use explicit `secretKeyRef` injection, not `extraEnvFrom`
- **Test credentials:** Verify S3 access with awscli before deploying components
- **Monitor logs:** Watch for "Access Key Id" errors during first 5 minutes of deployment

### ServiceMonitor Preservation Strategy
- ServiceMonitors are application-owned, not LGTM-owned
- VMAgent discovers via `selectAllByDefault: true`
- No reconfiguration required for existing workloads
- New ServiceMonitors automatically discovered

### Performance Monitoring
- **VMSingle query latency:** Monitor PromQL p95 latency (target: <2s for 7d range)
- **VMAgent scrape health:** Monitor scrape success rate (target: >95%)
- **VictoriaLogs query latency:** Monitor LogQL p95 latency (target: <1s for 24h range)
- **S3 operations:** Monitor upload/download errors (target: 0 errors)

### Success Criteria
- ✅ All components healthy and serving requests
- ✅ S3 connectivity verified with no authentication errors
- ✅ ServiceMonitors discovered and scraped by VMAgent
- ✅ Grafana datasources healthy and returning data
- ✅ LGTM stack cleanly removed without errors
- ✅ No observability gap or data loss during transition

---

## Post-Implementation Validation

**System Health Checklist:**
```bash
# 1. All Victoria components running
kubectl get pods -n monitoring | grep victoria

# 2. No CrashLoopBackOff or Error states
kubectl get pods -n monitoring --field-selector status.phase!=Running,status.phase!=Succeeded

# 3. S3 buckets contain data
aws --endpoint-url https://s3.68cc.io s3 ls s3://victoriametrics-data/ --recursive
aws --endpoint-url https://s3.68cc.io s3 ls s3://victorialogs-data/ --recursive

# 4. Grafana datasources healthy
curl -u admin:password http://localhost:3000/api/datasources | jq '.[] | select(.name | test("Victoria")) | {name: .name, health: .basicAuthUser}'

# 5. Metrics flowing
curl http://localhost:8429/api/v1/query?query=up | jq '.data.result | length'

# 6. LGTM components removed
kubectl get deploy,sts -n monitoring | grep -E "(prometheus|mimir|tempo)" | wc -l  # Should return 0
```

**Performance Validation:**
```bash
# Query latency test (7-day range)
time curl "http://localhost:8429/api/v1/query_range?query=up&start=$(date -u -d '7 days ago' +%s)&end=$(date -u +%s)&step=60"

# Scrape success rate
kubectl logs -n monitoring deployment/vmagent-victoria-metrics-k8s-stack | grep "scrape_samples_scraped" | tail -100
```
