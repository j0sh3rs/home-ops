# Parseable Deployment - Implementation Tasks

**Status**: Ready for Implementation
**Progress**: 0/11 tasks completed
**Last Updated**: 2025-01-11

## Task Execution Order

Tasks are ordered by dependencies and must be executed sequentially within each phase.

### Phase 1: Infrastructure Preparation
- [x] TASK-001: Create S3 bucket in Minio
- [ ] TASK-002: Create Parseable namespace structure

### Phase 2: Parseable Deployment
- [ ] TASK-003: Create Parseable HelmRelease
- [ ] TASK-004: Create Parseable S3 secret (SOPS-encrypted)
- [ ] TASK-005: Create Parseable ServiceMonitor

### Phase 3: Vector Deployment
- [ ] TASK-006: Create Vector namespace structure
- [ ] TASK-007: Create Vector RBAC resources
- [ ] TASK-008: Create Vector ConfigMap
- [ ] TASK-009: Create Vector HelmRelease

### Phase 4: Grafana Integration
- [ ] TASK-010: Update Grafana HelmRelease with Parseable plugin

### Phase 5: Integration & Verification
- [ ] TASK-011: Update monitoring kustomization and verify deployment

---

## TASK-001: Create S3 bucket in Minio

**Traceability**: REQ-prs-d8f3-002 (S3 Storage Configuration)

**Description**: Manually create `parseable-logs` bucket in Minio S3 at https://s3.68cc.io with appropriate lifecycle policy.

**Definition of Done (EARS)**:
- DoD-001-01: WHEN bucket is created, it SHALL be named `parseable-logs` {confidence: 100%}
- DoD-001-02: WHEN accessing bucket, system SHALL use path-style URLs with region `minio` {confidence: 100%}
- DoD-001-03: WHERE objects exceed 30 days, bucket lifecycle policy SHALL delete them automatically {confidence: 95%}

**Implementation Steps**:
1. Access Minio console at https://s3.68cc.io
2. Create bucket named `parseable-logs`
3. Configure lifecycle policy: delete objects older than 30 days
4. Verify bucket accessibility with path-style URLs
5. Note access credentials for SOPS encryption in TASK-004

**Verification**:
```bash
# Test bucket access (use actual credentials)
aws s3 ls s3://parseable-logs/ \
  --endpoint-url https://s3.68cc.io \
  --region minio
```

**Risk**: Low (manual step, reversible)

---

## TASK-002: Create Parseable namespace structure

**Traceability**: ADR-005 (FluxCD HelmRelease Pattern)

**Description**: Create directory structure for Parseable deployment following project conventions.

**Definition of Done (EARS)**:
- DoD-002-01: WHEN directory is created, it SHALL exist at `kubernetes/apps/monitoring/parseable/` {confidence: 100%}
- DoD-002-02: WHEN listing directory, it SHALL contain `ks.yaml` and `app/` subdirectory {confidence: 100%}
- DoD-002-03: WHEN app subdirectory exists, it SHALL be ready for HelmRelease and secret files {confidence: 100%}

**Implementation Steps**:
1. Create directory: `mkdir -p kubernetes/apps/monitoring/parseable/app`
2. Verify structure matches pattern: `{app}/ks.yaml` + `{app}/app/`

**Verification**:
```bash
ls -la kubernetes/apps/monitoring/parseable/
# Should show: ks.yaml, app/

ls -la kubernetes/apps/monitoring/parseable/app/
# Should be empty, ready for files
```

**Risk**: None (directory creation)

---

## TASK-003: Create Parseable HelmRelease

**Traceability**: REQ-prs-d8f3-001, ADR-001, ADR-004, Component-001

**Description**: Create Parseable HelmRelease with S3 backend configuration and resource limits.

**Definition of Done (EARS)**:
- DoD-003-01: WHEN HelmRelease is created, it SHALL reference Parseable Helm chart from official repository {confidence: 100%}
- DoD-003-02: WHEN Parseable starts, it SHALL connect to S3 endpoint `https://s3.68cc.io` with `force_path_style=true` {confidence: 95%}
- DoD-003-03: WHEN pod is deployed, it SHALL have memory limit of 2Gi and CPU request of 500m {confidence: 100%}
- DoD-003-04: WHEN retention is applied, system SHALL delete logs older than 30 days {confidence: 90%}

**Files to Create**:
1. `kubernetes/apps/monitoring/parseable/ks.yaml`
2. `kubernetes/apps/monitoring/parseable/app/kustomization.yaml`
3. `kubernetes/apps/monitoring/parseable/app/helmrelease.yaml`

**Implementation Content**:

**File: `kubernetes/apps/monitoring/parseable/ks.yaml`**
```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app parseable
  namespace: flux-system
spec:
  targetNamespace: monitoring
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  path: ./kubernetes/apps/monitoring/parseable/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  wait: false
  interval: 30m
  retryInterval: 1m
  timeout: 5m
```

**File: `kubernetes/apps/monitoring/parseable/app/kustomization.yaml`**
```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: monitoring
resources:
  - ./helmrelease.yaml
  - ./secret.sops.yaml
  - ./servicemonitor.yaml
```

**File: `kubernetes/apps/monitoring/parseable/app/helmrelease.yaml`**
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: parseable
spec:
  interval: 30m
  chart:
    spec:
      chart: parseable
      version: 1.6.5
      sourceRef:
        kind: HelmRepository
        name: parseable
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
    parseable:
      highAvailability:
        enabled: false

      store:
        staging:
          path: ./staging

        objectstore:
          enabled: true
          type: s3
          endpoint: https://s3.68cc.io
          region: minio
          bucket: parseable-logs

          credentials:
            existingSecret: parseable-s3-secret
            accessKeyId: S3_ACCESS_KEY_ID
            secretAccessKey: S3_SECRET_ACCESS_KEY

      local:
        retention:
          days: 30

      resources:
        limits:
          memory: 2Gi
        requests:
          cpu: 500m
          memory: 1Gi

      service:
        type: ClusterIP
        port: 8000
```

**Verification**:
```bash
# Verify HelmRelease exists
kubectl get helmrelease -n monitoring parseable

# Check pod status
kubectl get pods -n monitoring -l app.kubernetes.io/name=parseable

# Check logs for S3 connection
kubectl logs -n monitoring -l app.kubernetes.io/name=parseable | grep -i s3
```

**Risk**: Medium (S3 configuration must be correct, blocked by TASK-004 for secrets)

---

## TASK-004: Create Parseable S3 secret (SOPS-encrypted)

**Traceability**: REQ-prs-d8f3-002, Security Architecture

**Description**: Create SOPS-encrypted Kubernetes secret with S3 credentials for Parseable.

**Definition of Done (EARS)**:
- DoD-004-01: WHEN secret is created, it SHALL contain `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` keys {confidence: 100%}
- DoD-004-02: WHEN secret is committed, it SHALL be encrypted with SOPS using age keys {confidence: 100%}
- DoD-004-03: WHEN Parseable pod starts, it SHALL successfully authenticate to S3 using secret values {confidence: 95%}

**Files to Create**:
1. `kubernetes/apps/monitoring/parseable/app/secret.sops.yaml`

**Implementation Content**:

**File: `kubernetes/apps/monitoring/parseable/app/secret.sops.yaml`**
```yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: parseable-s3-secret
  namespace: monitoring
type: Opaque
stringData:
  S3_ACCESS_KEY_ID: ENC[AES256_GCM,data:... # REPLACE WITH ACTUAL MINIO ACCESS KEY
  S3_SECRET_ACCESS_KEY: ENC[AES256_GCM,data:... # REPLACE WITH ACTUAL MINIO SECRET KEY
```

**Implementation Steps**:
1. Create unencrypted secret file temporarily
2. Add actual Minio credentials from TASK-001
3. Encrypt with SOPS: `sops -e -i kubernetes/apps/monitoring/parseable/app/secret.sops.yaml`
4. Verify encryption: file should contain `sops:` metadata section
5. Delete any unencrypted temporary files

**Verification**:
```bash
# Verify SOPS encryption
grep "sops:" kubernetes/apps/monitoring/parseable/app/secret.sops.yaml

# After deployment, verify secret exists
kubectl get secret -n monitoring parseable-s3-secret

# Verify secret has correct keys
kubectl get secret -n monitoring parseable-s3-secret -o jsonpath='{.data}' | jq 'keys'
# Should show: ["S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"]
```

**Risk**: High (credentials must be correct and encrypted, blocking for Parseable startup)

---

## TASK-005: Create Parseable ServiceMonitor

**Traceability**: NFR-prs-d8f3-OBS-001 (Observability)

**Description**: Create ServiceMonitor for Prometheus to scrape Parseable metrics.

**Definition of Done (EARS)**:
- DoD-005-01: WHEN ServiceMonitor is created, Prometheus SHALL discover Parseable metrics endpoint {confidence: 95%}
- DoD-005-02: WHEN metrics are scraped, system SHALL expose query latency and ingestion rate {confidence: 90%}

**Files to Create**:
1. `kubernetes/apps/monitoring/parseable/app/servicemonitor.yaml`

**Implementation Content**:

**File: `kubernetes/apps/monitoring/parseable/app/servicemonitor.yaml`**
```yaml
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: parseable
  namespace: monitoring
  labels:
    app.kubernetes.io/name: parseable
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: parseable
  endpoints:
    - port: http
      interval: 30s
      path: /metrics
      scheme: http
```

**Verification**:
```bash
# Verify ServiceMonitor exists
kubectl get servicemonitor -n monitoring parseable

# Check Prometheus targets (after deployment)
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090
# Open browser: http://localhost:9090/targets
# Search for "parseable" - should show UP status
```

**Risk**: Low (observability only, non-blocking)

---

## TASK-006: Create Vector namespace structure

**Traceability**: ADR-005 (FluxCD HelmRelease Pattern)

**Description**: Create directory structure for Vector deployment following project conventions.

**Definition of Done (EARS)**:
- DoD-006-01: WHEN directory is created, it SHALL exist at `kubernetes/apps/monitoring/vector/` {confidence: 100%}
- DoD-006-02: WHEN listing directory, it SHALL contain `ks.yaml` and `app/` subdirectory {confidence: 100%}

**Implementation Steps**:
1. Create directory: `mkdir -p kubernetes/apps/monitoring/vector/app`
2. Verify structure matches pattern

**Verification**:
```bash
ls -la kubernetes/apps/monitoring/vector/
# Should show: ks.yaml, app/
```

**Risk**: None (directory creation)

---

## TASK-007: Create Vector RBAC resources

**Traceability**: Component-002, Security Architecture

**Description**: Create ServiceAccount, ClusterRole, and ClusterRoleBinding for Vector to read pod logs.

**Definition of Done (EARS)**:
- DoD-007-01: WHEN Vector pod starts, it SHALL use ServiceAccount `vector` with necessary permissions {confidence: 100%}
- DoD-007-02: WHEN Vector queries Kubernetes API, it SHALL have read access to pods, namespaces, and nodes {confidence: 100%}

**Files to Create**:
1. `kubernetes/apps/monitoring/vector/app/rbac.yaml`

**Implementation Content**:

**File: `kubernetes/apps/monitoring/vector/app/rbac.yaml`**
```yaml
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vector
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: vector
rules:
  - apiGroups: [""]
    resources:
      - namespaces
      - nodes
      - pods
    verbs:
      - get
      - list
      - watch
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: vector
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: vector
subjects:
  - kind: ServiceAccount
    name: vector
    namespace: monitoring
```

**Verification**:
```bash
# Verify RBAC resources exist
kubectl get serviceaccount -n monitoring vector
kubectl get clusterrole vector
kubectl get clusterrolebinding vector

# After Vector deployment, test permissions
kubectl auth can-i list pods --as=system:serviceaccount:monitoring:vector
# Should return: yes
```

**Risk**: Low (RBAC only, non-blocking)

---

## TASK-008: Create Vector ConfigMap

**Traceability**: REQ-prs-d8f3-003, Component-002, ADR-002

**Description**: Create Vector pipeline configuration with Kubernetes log source, metadata enrichment, and Parseable HTTP sink.

**Definition of Done (EARS)**:
- DoD-008-01: WHEN Vector processes logs, it SHALL collect from all pods via Kubernetes API {confidence: 95%}
- DoD-008-02: WHEN logs are enriched, system SHALL add namespace, pod_name, container_name, node_name metadata {confidence: 95%}
- DoD-008-03: WHEN sending to Parseable, Vector SHALL use HTTP POST with JSON encoding and 1GB disk buffer {confidence: 90%}

**Files to Create**:
1. `kubernetes/apps/monitoring/vector/app/configmap.yaml`

**Implementation Content**:

**File: `kubernetes/apps/monitoring/vector/app/configmap.yaml`**
```yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: vector-config
  namespace: monitoring
data:
  vector.yaml: |
    sources:
      kubernetes_logs:
        type: kubernetes_logs
        auto_partial_merge: true
        exclude_paths_glob_patterns:
          - "**/var/log/pods/monitoring_vector-*/**"

    transforms:
      add_k8s_metadata:
        type: remap
        inputs:
          - kubernetes_logs
        source: |
          .k8s.namespace = .kubernetes.pod_namespace
          .k8s.pod_name = .kubernetes.pod_name
          .k8s.container_name = .kubernetes.container_name
          .k8s.node_name = .kubernetes.pod_node_name
          .k8s.labels = .kubernetes.pod_labels

    sinks:
      parseable:
        type: http
        inputs:
          - add_k8s_metadata
        uri: http://parseable.monitoring.svc.cluster.local:8000/api/v1/ingest
        encoding:
          codec: json
        batch:
          timeout_secs: 5
          max_bytes: 1048576
        buffer:
          type: disk
          max_size: 1073741824
        request:
          retry_attempts: 3
          retry_max_duration_secs: 30
```

**Verification**:
```bash
# Verify ConfigMap exists
kubectl get configmap -n monitoring vector-config

# Check ConfigMap content
kubectl get configmap -n monitoring vector-config -o yaml | grep -A5 "vector.yaml"
```

**Risk**: Medium (configuration must be correct for log ingestion)

---

## TASK-009: Create Vector HelmRelease

**Traceability**: REQ-prs-d8f3-003, ADR-002, Component-002

**Description**: Create Vector HelmRelease as DaemonSet with ConfigMap and RBAC references.

**Definition of Done (EARS)**:
- DoD-009-01: WHEN Vector is deployed, it SHALL run as DaemonSet with one pod per node {confidence: 100%}
- DoD-009-02: WHEN Vector starts, it SHALL use `vector-config` ConfigMap and `vector` ServiceAccount {confidence: 100%}
- DoD-009-03: WHEN logs are collected, Vector SHALL send to Parseable at `http://parseable.monitoring.svc.cluster.local:8000` {confidence: 95%}

**Files to Create**:
1. `kubernetes/apps/monitoring/vector/ks.yaml`
2. `kubernetes/apps/monitoring/vector/app/kustomization.yaml`
3. `kubernetes/apps/monitoring/vector/app/helmrelease.yaml`

**Implementation Content**:

**File: `kubernetes/apps/monitoring/vector/ks.yaml`**
```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app vector
  namespace: flux-system
spec:
  targetNamespace: monitoring
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  path: ./kubernetes/apps/monitoring/vector/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  wait: false
  interval: 30m
  retryInterval: 1m
  timeout: 5m
```

**File: `kubernetes/apps/monitoring/vector/app/kustomization.yaml`**
```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: monitoring
resources:
  - ./rbac.yaml
  - ./configmap.yaml
  - ./helmrelease.yaml
```

**File: `kubernetes/apps/monitoring/vector/app/helmrelease.yaml`**
```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: vector
spec:
  interval: 30m
  chart:
    spec:
      chart: vector
      version: 0.35.0
      sourceRef:
        kind: HelmRepository
        name: vector
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
    role: Agent

    serviceAccount:
      create: false
      name: vector

    customConfig:
      data_dir: /vector-data-dir
      api:
        enabled: false
      sources:
        kubernetes_logs:
          type: kubernetes_logs
          auto_partial_merge: true
          exclude_paths_glob_patterns:
            - "**/var/log/pods/monitoring_vector-*/**"

      transforms:
        add_k8s_metadata:
          type: remap
          inputs:
            - kubernetes_logs
          source: |
            .k8s.namespace = .kubernetes.pod_namespace
            .k8s.pod_name = .kubernetes.pod_name
            .k8s.container_name = .kubernetes.container_name
            .k8s.node_name = .kubernetes.pod_node_name
            .k8s.labels = .kubernetes.pod_labels

      sinks:
        parseable:
          type: http
          inputs:
            - add_k8s_metadata
          uri: http://parseable.monitoring.svc.cluster.local:8000/api/v1/ingest
          encoding:
            codec: json
          batch:
            timeout_secs: 5
            max_bytes: 1048576
          buffer:
            type: disk
            max_size: 1073741824
          request:
            retry_attempts: 3
            retry_max_duration_secs: 30

    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        memory: 512Mi

    tolerations:
      - effect: NoSchedule
        operator: Exists
```

**Verification**:
```bash
# Verify HelmRelease exists
kubectl get helmrelease -n monitoring vector

# Check DaemonSet status
kubectl get daemonset -n monitoring vector

# Verify one pod per node
kubectl get pods -n monitoring -l app.kubernetes.io/name=vector -o wide

# Check Vector logs for Parseable connection
kubectl logs -n monitoring -l app.kubernetes.io/name=vector | grep parseable
```

**Risk**: High (log collection depends on correct configuration, blocked by TASK-003 for Parseable availability)

---

## TASK-010: Update Grafana HelmRelease with Parseable plugin

**Traceability**: REQ-prs-d8f3-004, ADR-003, Component-003

**Description**: Add Parseable datasource plugin to Grafana and configure datasource pointing to Parseable server.

**Definition of Done (EARS)**:
- DoD-010-01: WHEN Grafana starts, it SHALL download and install `parseable-parseable-datasource` plugin {confidence: 90%}
- DoD-010-02: WHEN datasource is configured, Grafana SHALL connect to `http://parseable.monitoring.svc.cluster.local:8000` {confidence: 95%}
- DoD-010-03: WHEN user queries logs, Grafana SHALL return results within 5 seconds for last 15 minutes {confidence: 80%}

**Files to Modify**:
1. `kubernetes/apps/monitoring/grafana/app/helmrelease.yaml`

**Implementation Changes**:

Add to `spec.values.grafana` section:

```yaml
    plugins:
      - https://github.com/parseablehq/parseable-datasource-plugin/releases/download/v1.0.0/parseable-parseable-datasource-1.0.0.zip;parseable-datasource
```

Add to `spec.values.grafana.datasources.datasources.yaml.datasources` array:

```yaml
      - name: Parseable
        type: parseable-parseable-datasource
        uid: parseable
        access: proxy
        url: http://parseable.monitoring.svc.cluster.local:8000
        jsonData:
          timeout: 30
        editable: false
```

**Verification**:
```bash
# Verify Grafana pod restarted
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana

# Check Grafana logs for plugin installation
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana | grep parseable

# Access Grafana UI and verify:
# 1. Connections > Data sources > Parseable exists
# 2. Test connection succeeds
# 3. Explore > Parseable > Run query returns logs
```

**Risk**: Medium (plugin installation may fail, but Grafana continues functioning)

---

## TASK-011: Update monitoring kustomization and verify deployment

**Traceability**: ADR-005 (FluxCD HelmRelease Pattern)

**Description**: Add Parseable and Vector to monitoring kustomization, commit changes, and verify full deployment.

**Definition of Done (EARS)**:
- DoD-011-01: WHEN kustomization is updated, FluxCD SHALL reconcile Parseable and Vector resources {confidence: 100%}
- DoD-011-02: WHEN deployment completes, all pods SHALL be in Running state {confidence: 95%}
- DoD-011-03: WHEN logs are queried in Grafana, system SHALL return recent logs from all namespaces {confidence: 90%}
- DoD-011-04: WHEN integration is verified, Vector SHALL be ingesting logs to Parseable at >1000 events/sec {confidence: 85%}

**Files to Modify**:
1. `kubernetes/apps/monitoring/kustomization.yaml`

**Implementation Changes**:

Add to `resources` array:
```yaml
  - ./parseable/ks.yaml
  - ./vector/ks.yaml
```

Add HelmRepository for Parseable and Vector:

**Create File: `kubernetes/flux/meta/repos/parseable.yaml`**
```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: parseable
  namespace: flux-system
spec:
  interval: 1h
  url: https://charts.parseable.com
```

**Create File: `kubernetes/flux/meta/repos/vector.yaml`**
```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: vector
  namespace: flux-system
spec:
  interval: 1h
  url: https://helm.vector.dev
```

**Modify File: `kubernetes/flux/meta/repos/kustomization.yaml`**
Add:
```yaml
  - ./parseable.yaml
  - ./vector.yaml
```

**Commit and Push**:
```bash
git add .
git commit -m "feat(monitoring): deploy Parseable log aggregation with Vector

- Add Parseable HelmRelease with S3 backend (Minio)
- Add Vector DaemonSet for log collection
- Configure Grafana Parseable datasource plugin
- Encrypt S3 credentials with SOPS
- Add ServiceMonitor for Parseable metrics

Implements: specs/parseable-deployment/
Closes: #<issue-number>"

git push
```

**Comprehensive Verification**:

```bash
# 1. Verify FluxCD reconciliation
flux get kustomizations -n flux-system | grep -E "parseable|vector"

# 2. Verify HelmRepositories
kubectl get helmrepository -n flux-system parseable
kubectl get helmrepository -n flux-system vector

# 3. Verify HelmReleases
kubectl get helmrelease -n monitoring parseable
kubectl get helmrelease -n monitoring vector

# 4. Verify all pods running
kubectl get pods -n monitoring | grep -E "parseable|vector"

# 5. Verify Parseable S3 connectivity
kubectl logs -n monitoring -l app.kubernetes.io/name=parseable | grep -i "s3\|storage"

# 6. Verify Vector log collection
kubectl logs -n monitoring -l app.kubernetes.io/name=vector | tail -20

# 7. Verify Grafana datasource
kubectl port-forward -n monitoring svc/grafana 3000:3000
# Open browser: http://localhost:3000
# Login > Connections > Data sources > Parseable
# Click "Test" button - should succeed

# 8. Query logs in Grafana
# Explore > Parseable datasource
# Query: { k8s.namespace="monitoring" }
# Time range: Last 15 minutes
# Should return logs with <5s latency

# 9. Check ingestion rate in Parseable metrics
kubectl port-forward -n monitoring svc/parseable 8000:8000
curl http://localhost:8000/metrics | grep parseable_events_ingested_total
```

**Success Criteria**:
- ✅ All pods in Running state
- ✅ Parseable connects to S3 (check logs)
- ✅ Vector collects logs from all nodes
- ✅ Grafana datasource test succeeds
- ✅ Log queries return results <5s
- ✅ No errors in pod logs

**Rollback Plan** (if verification fails):
```bash
# Remove Parseable and Vector from kustomization
git revert HEAD
git push

# Or manually remove resources
kubectl delete kustomization -n flux-system parseable
kubectl delete kustomization -n flux-system vector
```

**Risk**: High (final integration test, all components must work together)

---

## Task Dependencies Graph

```
TASK-001 (S3 bucket)
    ↓
TASK-002 (Parseable namespace) ──→ TASK-003 (Parseable HelmRelease)
                                        ↓
                                   TASK-004 (S3 secret)
                                        ↓
                                   TASK-005 (ServiceMonitor)
                                        ↓
TASK-006 (Vector namespace) ──→ TASK-007 (Vector RBAC)
                                        ↓
                                   TASK-008 (Vector ConfigMap)
                                        ↓
                                   TASK-009 (Vector HelmRelease)
                                        ↓
                                   TASK-010 (Grafana plugin)
                                        ↓
                                   TASK-011 (Verify deployment)
```

---

## Risk Assessment Summary

| Task | Risk Level | Impact | Mitigation |
|------|-----------|--------|------------|
| TASK-001 | Low | High | Manual verification, reversible |
| TASK-002 | None | Low | Directory creation only |
| TASK-003 | Medium | High | S3 config validation before deployment |
| TASK-004 | High | High | SOPS encryption verification, credential testing |
| TASK-005 | Low | Low | Observability only, non-blocking |
| TASK-006 | None | Low | Directory creation only |
| TASK-007 | Low | Medium | RBAC verification before Vector deployment |
| TASK-008 | Medium | High | ConfigMap syntax validation |
| TASK-009 | High | High | Vector logs monitoring, incremental rollout |
| TASK-010 | Medium | Medium | Grafana continues without plugin if fails |
| TASK-011 | High | Critical | Comprehensive verification, rollback plan ready |

---

## Traceability Matrix

| Requirement | Design Component | Tasks |
|-------------|-----------------|-------|
| REQ-prs-d8f3-001 | Component-001 (Parseable) | TASK-003, TASK-005 |
| REQ-prs-d8f3-002 | S3 Configuration | TASK-001, TASK-004 |
| REQ-prs-d8f3-003 | Component-002 (Vector) | TASK-007, TASK-008, TASK-009 |
| REQ-prs-d8f3-004 | Component-003 (Grafana) | TASK-010 |
| ADR-001 | S3-Native Storage | TASK-001, TASK-003, TASK-004 |
| ADR-002 | Vector DaemonSet | TASK-006, TASK-007, TASK-008, TASK-009 |
| ADR-003 | Parseable Plugin | TASK-010 |
| ADR-004 | Single Replica | TASK-003 |
| ADR-005 | FluxCD Pattern | All tasks |
| NFR-prs-d8f3-PERF-001 | Performance | TASK-011 (verification) |
| NFR-prs-d8f3-SEC-001 | Security | TASK-004 (SOPS encryption) |
| NFR-prs-d8f3-OBS-001 | Observability | TASK-005 (ServiceMonitor) |

---

## Notes

- **Execution Order**: Tasks must be executed in dependency order (see graph above)
- **Approval Gate**: Request user approval after presenting this tasks.md
- **Implementation**: User can request specific task execution: "Please implement TASK-003"
- **Testing**: Each task includes verification steps before proceeding
- **Rollback**: TASK-011 includes comprehensive rollback plan if verification fails
- **Documentation**: All specs archived to `specs/done/` after successful deployment
