# Tasks: Parseable Logging Aggregator Deployment - Implementer Agent

## Context Summary

Feature UUID: FEAT-prs-d8f3 | Architecture: S3-Native Log Aggregation with DaemonSet Collection | Risk: Medium (S3 compatibility, Vector config complexity)

## Metadata

Complexity: Medium (5 ADRs, 4 REQs, 29 EARS criteria) | Critical Path: S3 config → Parseable → Vector → Grafana
Timeline: 4-6 hours (incremental deployment with validation gates) | Quality Gates: Manual EARS validation per phase

## Progress: 0/15 Complete, 0 In Progress, 15 Not Started, 0 Blocked

---

## Phase 1: Foundation - Parseable Server + S3 Configuration

### TASK-prs-001: Create Parseable Directory Structure

Trace: All REQs | Design: FluxCD deployment pattern | AC: Project structure consistency
ADR: ADR-005 (FluxCD HelmRelease pattern) | Approach: Follow established monitoring namespace pattern
DoD (EARS Format): WHEN directory structure created, SHALL match pattern `{app}/ks.yaml` + `{app}/app/kustomization.yaml` + `{app}/app/helmrelease.yaml`
Risk: Low | Effort: 1pt
Test Strategy: Manual validation (directory structure inspection) | Dependencies: None

**Implementation Details:**

```bash
# Create directory structure
mkdir -p kubernetes/apps/monitoring/parseable/app

# Files to create:
# - kubernetes/apps/monitoring/parseable/ks.yaml
# - kubernetes/apps/monitoring/parseable/app/kustomization.yaml
# - kubernetes/apps/monitoring/parseable/app/helmrelease.yaml
# - kubernetes/apps/monitoring/parseable/app/secret.sops.yaml
# - kubernetes/apps/monitoring/parseable/app/servicemonitor.yaml
```

**Validation Checklist:**

- [ ] Directory structure matches existing monitoring apps (grafana, loki, tempo)
- [ ] All required files planned (ks.yaml, kustomization.yaml, helmrelease.yaml, secret, servicemonitor)

---

### TASK-prs-002: Create SOPS-Encrypted S3 Credentials Secret

Trace: REQ-prs-d8f3-002 | Design: Secrets Management | AC: AC-prs-002-03 (SOPS encryption)
ADR: ADR-001 (S3-Native Storage), ADR-005 (FluxCD pattern) | Approach: Follow established S3 secret pattern
DoD (EARS Format): WHEN credentials stored, SHALL encrypt with SOPS before Git commit AND WHERE secret contains S3 keys, SHALL include S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT, S3_BUCKET
Risk: Medium (credential handling) | Effort: 2pts
Test Strategy: Manual validation (SOPS encryption verification, gitleaks pre-commit) | Dependencies: TASK-prs-001

**Implementation Details:**

```yaml
# File: kubernetes/apps/monitoring/parseable/app/secret.sops.yaml
apiVersion: v1
kind: Secret
metadata:
    name: parseable-s3-secret
    namespace: monitoring
type: Opaque
stringData:
    S3_ACCESS_KEY_ID: <REPLACE_WITH_ACTUAL_KEY>
    S3_SECRET_ACCESS_KEY: <REPLACE_WITH_ACTUAL_SECRET>
    S3_ENDPOINT: "https://s3.68cc.io"
    S3_BUCKET: "parseable-logs"
```

**SOPS Encryption Command:**

```bash
sops --encrypt \
  --age $(cat ~/.config/sops/age/keys.txt | grep -oP "public key: \K(.*)") \
  --encrypted-regex '^(data|stringData)$' \
  --in-place kubernetes/apps/monitoring/parseable/app/secret.sops.yaml
```

**Validation Checklist (EARS AC-prs-002-03):**

- [ ] Secret file contains all required keys (S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT, S3_BUCKET)
- [ ] SOPS encryption applied (stringData section encrypted)
- [ ] File extension is `.sops.yaml`
- [ ] gitleaks pre-commit hook passes (no plaintext credentials)

---

### TASK-prs-003: Create Parseable HelmRelease Configuration

Trace: REQ-prs-d8f3-001, REQ-prs-d8f3-002 | Design: ParseableAPI component | AC: AC-prs-001-01,02,03,04,05, AC-prs-002-01,02,04,05
ADR: ADR-001 (S3 storage), ADR-004 (single-replica), ADR-005 (FluxCD) | Approach: Official Parseable Helm chart from https://charts.parseable.com/
DoD (EARS Format): WHEN HelmRelease deployed, SHALL configure S3 backend with force_path_style=true AND WHILE Parseable runs, SHALL consume <2Gi memory per pod AND WHERE S3 endpoint is Minio, SHALL use region=minio
Risk: Medium (Helm values complexity, S3 compatibility) | Effort: 5pts
Test Strategy: Manual validation (HelmRelease syntax, resource limits, S3 config) | Dependencies: TASK-prs-001, TASK-prs-002

**Implementation Details:**

```yaml
# File: kubernetes/apps/monitoring/parseable/app/helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
    name: parseable
    namespace: monitoring
spec:
    interval: 15m
    chart:
        spec:
            chart: parseable
            version: ">=1.0.0" # Use latest stable version
            sourceRef:
                kind: HelmRepository
                name: parseable
                namespace: flux-system
            interval: 15m
    install:
        createNamespace: false
        remediation:
            retries: 3
    upgrade:
        cleanupOnFail: true
        remediation:
            retries: 3
    values:
        # Single replica (ADR-004)
        replicaCount: 1

        image:
            repository: parseable/parseable
            tag: latest
            pullPolicy: IfNotPresent

        # Resource limits (AC-prs-001-04, NFR-prs-d8f3-SCALE-001)
        resources:
            requests:
                cpu: 500m
                memory: 512Mi
            limits:
                memory: 2Gi

        # S3 Configuration (REQ-prs-d8f3-002, AC-prs-002-01,02)
        parseable:
            storage:
                mode: "s3"
                s3:
                    endpoint: "https://s3.68cc.io"
                    region: "minio" # Minio compatibility
                    bucket: "parseable-logs"
                    # Force path-style for Minio (AC-prs-002-02)
                    pathStyle: true
                    # Credentials from secret
                    accessKeyId:
                        valueFrom:
                            secretKeyRef:
                                name: parseable-s3-secret
                                key: S3_ACCESS_KEY_ID
                    secretAccessKey:
                        valueFrom:
                            secretKeyRef:
                                name: parseable-s3-secret
                                key: S3_SECRET_ACCESS_KEY

            # Retention policy (AC-prs-002-05)
            retention:
                days: 30

        # Service configuration
        service:
            type: ClusterIP
            port: 8000
            annotations: {}

        # Health checks (AC-prs-001-01)
        livenessProbe:
            httpGet:
                path: /health
                port: 8000
            initialDelaySeconds: 30
            periodSeconds: 10

        readinessProbe:
            httpGet:
                path: /health
                port: 8000
            initialDelaySeconds: 10
            periodSeconds: 5

        # Metrics (NFR-prs-d8f3-OPS-001)
        metrics:
            enabled: true
            serviceMonitor:
                enabled: false # We'll create separate ServiceMonitor
```

**Validation Checklist:**

- [ ] HelmRelease references correct chart source (parseable from https://charts.parseable.com/)
- [ ] S3 configuration includes all required fields (endpoint, region, bucket, pathStyle)
- [ ] Memory limit set to 2Gi (AC-prs-001-04)
- [ ] Single replica configured (ADR-004)
- [ ] Secret references correct (parseable-s3-secret)
- [ ] Health check endpoints configured (/health)
- [ ] Service type is ClusterIP (no external exposure)

---

### TASK-prs-004: Create Parseable HelmRepository Source

Trace: REQ-prs-d8f3-001 | Design: FluxCD deployment | AC: Helm chart availability
ADR: ADR-005 (FluxCD pattern) | Approach: Add HelmRepository to flux-system namespace
DoD (EARS Format): WHEN HelmRepository created, SHALL point to https://charts.parseable.com/ AND WHERE FluxCD reconciles, SHALL successfully fetch chart metadata
Risk: Low | Effort: 1pt
Test Strategy: Manual validation (HelmRepository status, chart availability) | Dependencies: None

**Implementation Details:**

```yaml
# File: kubernetes/flux/repositories/helm/parseable.yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
    name: parseable
    namespace: flux-system
spec:
    interval: 1h
    url: https://charts.parseable.com/
```

**Validation Checklist:**

- [ ] HelmRepository created in flux-system namespace
- [ ] URL points to https://charts.parseable.com/
- [ ] FluxCD successfully reconciles repository (check status)

---

### TASK-prs-005: Create Parseable Kustomization Files

Trace: All REQs | Design: FluxCD deployment | AC: GitOps deployment pattern
ADR: ADR-005 (FluxCD pattern) | Approach: Follow established kustomization pattern
DoD (EARS Format): WHEN kustomization files created, SHALL list all resources AND WHERE ks.yaml deployed, SHALL reference monitoring kustomization as dependency
Risk: Low | Effort: 2pts
Test Strategy: Manual validation (kustomization syntax, resource list completeness) | Dependencies: TASK-prs-001, TASK-prs-002, TASK-prs-003

**Implementation Details:**

```yaml
# File: kubernetes/apps/monitoring/parseable/ks.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
    name: parseable
    namespace: flux-system
spec:
    interval: 10m
    path: ./kubernetes/apps/monitoring/parseable/app
    prune: true
    sourceRef:
        kind: GitRepository
        name: home-kubernetes
    wait: true
    dependsOn:
        - name: monitoring-namespace
```

```yaml
# File: kubernetes/apps/monitoring/parseable/app/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: monitoring
resources:
    - ./helmrelease.yaml
    - ./secret.sops.yaml
    - ./servicemonitor.yaml
```

**Validation Checklist:**

- [ ] ks.yaml references correct path (./kubernetes/apps/monitoring/parseable/app)
- [ ] ks.yaml has dependsOn: monitoring-namespace
- [ ] app/kustomization.yaml lists all resources (helmrelease, secret, servicemonitor)
- [ ] Namespace set to monitoring

---

### TASK-prs-006: Create Parseable ServiceMonitor

Trace: NFR-prs-d8f3-OPS-001 | Design: Monitoring & Observability | AC: Prometheus metrics exposure
ADR: None (standard monitoring pattern) | Approach: ServiceMonitor for /metrics endpoint
DoD (EARS Format): WHEN Parseable is deployed, SHALL expose Prometheus metrics at /metrics endpoint AND WHERE ServiceMonitor configured, SHALL scrape metrics every 30s
Risk: Low | Effort: 1pt
Test Strategy: Manual validation (ServiceMonitor syntax, Prometheus target discovery) | Dependencies: TASK-prs-003

**Implementation Details:**

```yaml
# File: kubernetes/apps/monitoring/parseable/app/servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
    name: parseable
    namespace: monitoring
spec:
    selector:
        matchLabels:
            app.kubernetes.io/name: parseable
    endpoints:
        - port: http
          path: /metrics
          interval: 30s
          scrapeTimeout: 10s
```

**Validation Checklist:**

- [ ] ServiceMonitor selector matches Parseable service labels
- [ ] Metrics path is /metrics
- [ ] Scrape interval is 30s
- [ ] Port name matches service definition (http)

---

### TASK-prs-007: Deploy Parseable and Validate Phase 1

Trace: REQ-prs-d8f3-001, REQ-prs-d8f3-002 | Design: All Parseable components | AC: AC-prs-001-01,02,03,04,05, AC-prs-002-01,02,03,04
ADR: All Phase 1 ADRs | Approach: GitOps deployment via FluxCD, manual validation
DoD (EARS Format): WHEN Parseable deployed, SHALL connect to S3 successfully AND WHERE pod starts, SHALL consume <2Gi memory AND IF S3 bucket doesn't exist, SHALL fail with clear error
Risk: High (first integration point, S3 connectivity) | Effort: 3pts
Test Strategy: Manual validation (EARS acceptance criteria checklist) | Dependencies: TASK-prs-001,002,003,004,005,006

**Deployment Steps:**

1. Commit all files to Git repository
2. Push to remote (FluxCD will reconcile)
3. Monitor FluxCD reconciliation: `flux get kustomizations -n flux-system`
4. Monitor Parseable pod startup: `kubectl get pods -n monitoring -l app.kubernetes.io/name=parseable`

**Manual Validation Checklist (EARS Acceptance Criteria):**

**AC-prs-001-01 (S3 Connectivity):**

- [ ] WHEN Parseable pod starts, system SHALL connect to Minio S3 at https://s3.68cc.io
- Validation: Check pod logs for successful S3 connection
- Command: `kubectl logs -n monitoring <parseable-pod> | grep -i s3`

**AC-prs-001-02 (Credential Validation):**

- [ ] WHERE S3 credentials are invalid, system SHALL fail startup with clear authentication error
- Validation: Verify correct error handling (test by intentionally breaking credentials if needed)

**AC-prs-001-04 (Resource Limits):**

- [ ] WHILE Parseable is running, system SHALL consume <2Gi memory per pod
- Validation: Check pod memory usage
- Command: `kubectl top pod -n monitoring <parseable-pod>`

**AC-prs-001-05 (S3 Durability):**

- [ ] IF Parseable pod restarts, system SHALL reconnect to existing S3 data without data loss
- Validation: Test pod restart and verify S3 reconnection
- Command: `kubectl delete pod -n monitoring <parseable-pod>` (watch recreate)

**AC-prs-002-01 (S3 Bucket):**

- [ ] WHEN Parseable is configured, system SHALL use dedicated "parseable-logs" S3 bucket
- Validation: Check Minio console for bucket usage or HelmRelease values

**AC-prs-002-02 (Minio Compatibility):**

- [ ] WHERE S3 endpoint is Minio, system SHALL use force_path_style=true and region=minio
- Validation: Verify HelmRelease values (pathStyle: true, region: minio)

**AC-prs-002-03 (SOPS Encryption):**

- [ ] WHEN credentials are stored, system SHALL encrypt with SOPS before Git commit
- Validation: Inspect secret.sops.yaml file (stringData encrypted)
- Command: `cat kubernetes/apps/monitoring/parseable/app/secret.sops.yaml | grep "sops:"`

**AC-prs-002-04 (Bucket Existence):**

- [ ] IF S3 bucket doesn't exist, system SHALL fail with clear error message
- Validation: Assumed bucket exists; check pod logs if startup fails

**NFR-prs-d8f3-OPS-001 (Metrics):**

- [ ] WHEN Parseable is deployed, system SHALL expose Prometheus metrics at /metrics endpoint
- Validation: Check ServiceMonitor target discovery
- Command: `kubectl get servicemonitor -n monitoring parseable`
- Prometheus UI: Check Targets page for parseable endpoint

**Health Check:**

- [ ] Parseable pod status is Running
- [ ] FluxCD Kustomization status is Ready
- [ ] No error logs in Parseable pod
- [ ] /health endpoint returns 200 OK: `kubectl exec -n monitoring <pod> -- curl -s http://localhost:8000/health`

**🚨 STOP: Do not proceed to Phase 2 until all Phase 1 validations pass!**

---

## Phase 2: Integration - Vector Log Shipper Deployment

### TASK-prs-008: Create Vector Directory Structure

Trace: REQ-prs-d8f3-003 | Design: FluxCD deployment pattern | AC: Project structure consistency
ADR: ADR-005 (FluxCD HelmRelease pattern) | Approach: Follow established monitoring namespace pattern
DoD (EARS Format): WHEN directory structure created, SHALL match pattern `{app}/ks.yaml` + `{app}/app/kustomization.yaml` + `{app}/app/helmrelease.yaml`
Risk: Low | Effort: 1pt
Test Strategy: Manual validation (directory structure inspection) | Dependencies: TASK-prs-007 (Phase 1 complete)

**Implementation Details:**

```bash
# Create directory structure
mkdir -p kubernetes/apps/monitoring/vector/app

# Files to create:
# - kubernetes/apps/monitoring/vector/ks.yaml
# - kubernetes/apps/monitoring/vector/app/kustomization.yaml
# - kubernetes/apps/monitoring/vector/app/helmrelease.yaml
# - kubernetes/apps/monitoring/vector/app/rbac.yaml
```

**Validation Checklist:**

- [ ] Directory structure matches existing monitoring apps
- [ ] All required files planned (ks.yaml, kustomization.yaml, helmrelease.yaml, rbac.yaml)

---

### TASK-prs-009: Create Vector RBAC Configuration

Trace: REQ-prs-d8f3-003 | Design: VectorPipeline component | AC: AC-prs-003-01 (Kubernetes API access)
ADR: ADR-002 (Vector over Promtail) | Approach: ServiceAccount + ClusterRole for pod log access
DoD (EARS Format): WHEN Vector starts, SHALL have permissions to access Kubernetes API for pod log discovery AND WHERE RBAC configured, SHALL grant read-only access to pods, nodes, namespaces
Risk: Low | Effort: 2pts
Test Strategy: Manual validation (RBAC syntax, permission scope) | Dependencies: TASK-prs-008

**Implementation Details:**

```yaml
# File: kubernetes/apps/monitoring/vector/app/rbac.yaml
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
    # Pod log discovery (AC-prs-003-01)
    - apiGroups: [""]
      resources: ["pods", "namespaces", "nodes"]
      verbs: ["get", "list", "watch"]
    - apiGroups: [""]
      resources: ["pods/log"]
      verbs: ["get"]
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

**Validation Checklist:**

- [ ] ServiceAccount created in monitoring namespace
- [ ] ClusterRole grants access to pods, namespaces, nodes (read-only)
- [ ] ClusterRole grants access to pods/log (read-only)
- [ ] ClusterRoleBinding links ServiceAccount to ClusterRole

---

### TASK-prs-010: Create Vector HelmRelease Configuration

Trace: REQ-prs-d8f3-003 | Design: VectorPipeline component | AC: AC-prs-003-01,02,03,04,05
ADR: ADR-002 (Vector over Promtail) | Approach: Official Vector Helm chart from https://helm.vector.dev
DoD (EARS Format): WHEN Vector deployed as DaemonSet, SHALL collect logs from all pods AND WHILE pods emit logs, SHALL forward to Parseable within 5s AND IF Parseable unavailable, SHALL buffer logs up to 1GB
Risk: High (complex configuration, Kubernetes metadata enrichment) | Effort: 6pts
Test Strategy: Manual validation (HelmRelease syntax, Vector pipeline config, buffer settings) | Dependencies: TASK-prs-008, TASK-prs-009

**Implementation Details:**

```yaml
# File: kubernetes/apps/monitoring/vector/app/helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
    name: vector
    namespace: monitoring
spec:
    interval: 15m
    chart:
        spec:
            chart: vector
            version: ">=0.30.0" # Use latest stable version
            sourceRef:
                kind: HelmRepository
                name: vector
                namespace: flux-system
            interval: 15m
    install:
        createNamespace: false
        remediation:
            retries: 3
    upgrade:
        cleanupOnFail: true
        remediation:
            retries: 3
    values:
        # DaemonSet deployment (one per node)
        role: "Agent"

        image:
            repository: timberio/vector
            tag: latest-alpine
            pullPolicy: IfNotPresent

        # Use existing ServiceAccount
        serviceAccount:
            create: false
            name: vector

        # Resource limits
        resources:
            requests:
                cpu: 100m
                memory: 256Mi
            limits:
                memory: 1Gi

        # Vector configuration
        customConfig:
            data_dir: /vector-data-dir

            # WHEN Vector starts, SHALL discover all pod logs via Kubernetes API
            # AC-prs-003-01
            sources:
                kubernetes_logs:
                    type: kubernetes_logs
                    auto_partial_merge: true
                    pod_annotation_fields:
                        container_image: "container_image"
                        container_name: "container_name"
                        pod_ip: "pod_ip"
                        pod_labels: "pod_labels"
                        pod_name: "pod_name"
                        pod_namespace: "pod_namespace"
                        pod_node_name: "pod_node_name"
                        pod_uid: "pod_uid"

            # WHEN Vector processes logs, SHALL add Kubernetes metadata
            # AC-prs-003-05
            transforms:
                add_k8s_metadata:
                    type: remap
                    inputs:
                        - kubernetes_logs
                    source: |
                        .k8s.namespace = .pod_namespace
                        .k8s.pod_name = .pod_name
                        .k8s.container_name = .container_name
                        .k8s.node_name = .pod_node_name

            # WHILE pods emit logs, Vector SHALL forward to Parseable within 5 seconds
            # AC-prs-003-02
            # IF Parseable is unavailable, Vector SHALL buffer logs locally up to 1GB
            # AC-prs-003-04
            sinks:
                parseable:
                    type: http
                    inputs:
                        - add_k8s_metadata
                    uri: "http://parseable.monitoring.svc.cluster.local:8000/api/v1/ingest"
                    encoding:
                        codec: json
                    batch:
                        max_bytes: 1048576 # 1MB batches
                        timeout_secs: 5 # AC-prs-003-02 (5 second batching)
                    buffer:
                        type: disk
                        max_size: 1073741824 # 1GB buffer (AC-prs-003-04)
                        when_full: block # Backpressure (AC-prs-003-03)
                    request:
                        retry_attempts: 5
                        retry_initial_backoff_secs: 1
                        retry_max_duration_secs: 10

        # Volume mounts for log access
        podVolumes:
            - name: var-log
              hostPath:
                  path: /var/log
            - name: var-lib
              hostPath:
                  path: /var/lib

        podVolumeMounts:
            - name: var-log
              mountPath: /var/log
              readOnly: true
            - name: var-lib
              mountPath: /var/lib
              readOnly: true
```

**Validation Checklist:**

- [ ] HelmRelease references correct chart source (vector from https://helm.vector.dev)
- [ ] Role set to "Agent" (DaemonSet deployment)
- [ ] ServiceAccount name is "vector" (uses existing RBAC)
- [ ] kubernetes_logs source configured with auto_partial_merge
- [ ] add_k8s_metadata transform enriches logs with k8s.namespace, k8s.pod_name, etc. (AC-prs-003-05)
- [ ] parseable sink configured with correct URL (http://parseable.monitoring.svc.cluster.local:8000/api/v1/ingest)
- [ ] Batch timeout set to 5 seconds (AC-prs-003-02)
- [ ] Disk buffer configured with 1GB max_size (AC-prs-003-04)
- [ ] Buffer when_full set to "block" for backpressure (AC-prs-003-03)
- [ ] Volume mounts for /var/log and /var/lib configured
- [ ] Memory limit set to 1Gi

---

### TASK-prs-011: Create Vector HelmRepository Source

Trace: REQ-prs-d8f3-003 | Design: FluxCD deployment | AC: Helm chart availability
ADR: ADR-005 (FluxCD pattern) | Approach: Add HelmRepository to flux-system namespace
DoD (EARS Format): WHEN HelmRepository created, SHALL point to https://helm.vector.dev AND WHERE FluxCD reconciles, SHALL successfully fetch chart metadata
Risk: Low | Effort: 1pt
Test Strategy: Manual validation (HelmRepository status, chart availability) | Dependencies: None

**Implementation Details:**

```yaml
# File: kubernetes/flux/repositories/helm/vector.yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
    name: vector
    namespace: flux-system
spec:
    interval: 1h
    url: https://helm.vector.dev
```

**Validation Checklist:**

- [ ] HelmRepository created in flux-system namespace
- [ ] URL points to https://helm.vector.dev
- [ ] FluxCD successfully reconciles repository (check status)

---

### TASK-prs-012: Create Vector Kustomization Files

Trace: REQ-prs-d8f3-003 | Design: FluxCD deployment | AC: GitOps deployment pattern
ADR: ADR-005 (FluxCD pattern) | Approach: Follow established kustomization pattern
DoD (EARS Format): WHEN kustomization files created, SHALL list all resources AND WHERE ks.yaml deployed, SHALL reference parseable kustomization as dependency
Risk: Low | Effort: 2pts
Test Strategy: Manual validation (kustomization syntax, resource list completeness) | Dependencies: TASK-prs-008, TASK-prs-009, TASK-prs-010

**Implementation Details:**

```yaml
# File: kubernetes/apps/monitoring/vector/ks.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
    name: vector
    namespace: flux-system
spec:
    interval: 10m
    path: ./kubernetes/apps/monitoring/vector/app
    prune: true
    sourceRef:
        kind: GitRepository
        name: home-kubernetes
    wait: true
    dependsOn:
        - name: monitoring-namespace
        - name: parseable # Ensure Parseable is deployed first
```

```yaml
# File: kubernetes/apps/monitoring/vector/app/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: monitoring
resources:
    - ./rbac.yaml
    - ./helmrelease.yaml
```

**Validation Checklist:**

- [ ] ks.yaml references correct path (./kubernetes/apps/monitoring/vector/app)
- [ ] ks.yaml has dependsOn: monitoring-namespace AND parseable
- [ ] app/kustomization.yaml lists all resources (rbac, helmrelease)
- [ ] Namespace set to monitoring

---

### TASK-prs-013: Deploy Vector and Validate Phase 2

Trace: REQ-prs-d8f3-003 | Design: VectorPipeline component | AC: AC-prs-003-01,02,03,04,05
ADR: ADR-002 (Vector over Promtail) | Approach: GitOps deployment via FluxCD, manual validation
DoD (EARS Format): WHEN Vector deployed, SHALL collect logs from all pods AND WHILE pods emit logs, SHALL forward to Parseable within 5 seconds AND IF Parseable unavailable, SHALL buffer logs up to 1GB
Risk: High (first end-to-end log flow, Vector config complexity) | Effort: 4pts
Test Strategy: Manual validation (EARS acceptance criteria checklist, log flow E2E) | Dependencies: TASK-prs-008,009,010,011,012

**Deployment Steps:**

1. Commit all Vector files to Git repository
2. Push to remote (FluxCD will reconcile)
3. Monitor FluxCD reconciliation: `flux get kustomizations -n flux-system`
4. Monitor Vector DaemonSet: `kubectl get daemonset -n monitoring vector`
5. Verify Vector pods running on all nodes: `kubectl get pods -n monitoring -l app.kubernetes.io/name=vector -o wide`

**Manual Validation Checklist (EARS Acceptance Criteria):**

**AC-prs-003-01 (Pod Log Discovery):**

- [ ] WHEN Vector starts, system SHALL discover all pod logs via Kubernetes API
- Validation: Check Vector pod logs for Kubernetes source initialization
- Command: `kubectl logs -n monitoring <vector-pod> | grep -i kubernetes_logs`

**AC-prs-003-02 (Log Forwarding Latency):**

- [ ] WHILE pods emit logs, Vector SHALL forward to Parseable HTTP endpoint within 5 seconds
- Validation: Generate test log, check Parseable receives within 5s
- Test: `kubectl run test-pod --image=busybox --restart=Never -- sh -c "echo 'TEST_LOG_$(date +%s)' && sleep 1"`
- Check Parseable for log appearance (query via Grafana or API)

**AC-prs-003-03 (Backpressure):**

- [ ] WHERE log rate exceeds threshold, Vector SHALL apply backpressure without dropping logs
- Validation: Check Vector config (when_full: block in buffer settings)
- Verify no dropped logs in Vector metrics: `kubectl exec -n monitoring <vector-pod> -- curl -s http://localhost:9090/metrics | grep vector_buffer_discarded_events_total`

**AC-prs-003-04 (Buffer Capacity):**

- [ ] IF Parseable is unavailable, Vector SHALL buffer logs locally up to 1GB
- Validation: Check Vector config (max_size: 1073741824)
- Test (optional): Scale Parseable to 0, generate logs, verify buffering
- Command: `kubectl scale deployment -n monitoring parseable --replicas=0`

**AC-prs-003-05 (Kubernetes Metadata):**

- [ ] WHEN Vector processes logs, system SHALL add Kubernetes metadata (namespace, pod, container)
- Validation: Query Parseable logs via Grafana, verify k8s.namespace, k8s.pod_name labels present
- Check add_k8s_metadata transform in Vector logs

**Health Check:**

- [ ] Vector DaemonSet has pods running on all nodes
- [ ] Vector pods status is Running
- [ ] FluxCD Kustomization status is Ready
- [ ] No error logs in Vector pods
- [ ] Parseable receives logs from Vector (check Parseable metrics: parseable_logs_ingested_total)

**End-to-End Log Flow Test:**

1. Generate test log: `kubectl run test-pod --image=busybox --rm -it --restart=Never -- echo "E2E_TEST_$(date +%s)"`
2. Wait 10 seconds (allow Vector batching + Parseable ingestion)
3. Query Parseable (via API or Grafana Explore)
4. Verify test log appears with k8s.namespace="default" and k8s.pod_name="test-pod"

**🚨 STOP: Do not proceed to Phase 3 until all Phase 2 validations pass!**

---

## Phase 3: Visualization - Grafana Integration

### TASK-prs-014: Modify Grafana HelmRelease for Parseable Datasource

Trace: REQ-prs-d8f3-004 | Design: Grafana datasource integration | AC: AC-prs-004-01,02,03,04,05
ADR: ADR-003 (Grafana plugin) | Approach: Add parseable-datasource plugin and datasource config to existing Grafana HelmRelease
DoD (EARS Format): WHEN Grafana starts, SHALL install parseable-parseable-datasource plugin AND WHERE datasource configured, SHALL connect to http://parseable.monitoring.svc:8000
Risk: Medium (plugin compatibility, Grafana version) | Effort: 4pts
Test Strategy: Manual validation (plugin installation, datasource configuration) | Dependencies: TASK-prs-013 (Phase 2 complete)

**Implementation Details:**

```yaml
# File: kubernetes/apps/monitoring/grafana/app/helmrelease.yaml
# MODIFY existing Grafana HelmRelease by adding to values section

spec:
    values:
        # ADD to existing plugins list
        plugins:
            - grafana-clock-panel
            - grafana-piechart-panel
            # ... existing plugins ...
            # WHEN Grafana starts, SHALL install parseable-parseable-datasource plugin
            # AC-prs-004-01
            - parseable-parseable-datasource

        # ADD to existing datasources section
        datasources:
            datasources.yaml:
                apiVersion: 1
                datasources:
                    # ... existing datasources (Mimir, Tempo, Alertmanager, Loki) ...

                    # WHERE datasource is configured, SHALL connect to parseable service
                    # AC-prs-004-02
                    - name: Parseable
                      type: parseable-parseable-datasource
                      uid: parseable
                      access: proxy
                      url: http://parseable.monitoring.svc.cluster.local:8000
                      jsonData:
                          timeout: 30
                      editable: false
                      isDefault: false
```

**Validation Checklist:**

- [ ] Plugin added to plugins list: parseable-parseable-datasource
- [ ] Datasource name is "Parseable"
- [ ] Datasource type is "parseable-parseable-datasource" (AC-prs-004-01)
- [ ] URL is http://parseable.monitoring.svc.cluster.local:8000 (AC-prs-004-02)
- [ ] Access mode is "proxy" (Grafana backend queries Parseable)
- [ ] Timeout set to 30 seconds
- [ ] editable: false (prevent accidental modification)

---

### TASK-prs-015: Deploy Grafana Changes and Validate Phase 3

Trace: REQ-prs-d8f3-004 | Design: GrafanaParseableDatasource component | AC: AC-prs-004-01,02,03,04,05
ADR: ADR-003 (Grafana plugin) | Approach: GitOps deployment via FluxCD, manual E2E validation
DoD (EARS Format): WHEN user queries logs, Grafana SHALL return results within 5 seconds for last 15 minutes AND WHILE datasource active, SHALL support filtering by namespace and pod
Risk: High (full E2E validation, plugin compatibility) | Effort: 4pts
Test Strategy: Manual validation (EARS acceptance criteria checklist, E2E query flow) | Dependencies: TASK-prs-014

**Deployment Steps:**

1. Commit modified Grafana HelmRelease to Git repository
2. Push to remote (FluxCD will reconcile)
3. Monitor FluxCD reconciliation: `flux get helmreleases -n monitoring grafana`
4. Wait for Grafana pod restart (plugin installation)
5. Verify Grafana pod running: `kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana`

**Manual Validation Checklist (EARS Acceptance Criteria):**

**AC-prs-004-01 (Plugin Installation):**

- [ ] WHEN Grafana starts, system SHALL install parseable-parseable-datasource plugin
- Validation: Check Grafana pod logs for plugin installation
- Command: `kubectl logs -n monitoring <grafana-pod> | grep -i parseable`
- Grafana UI: Navigate to Configuration → Plugins, verify "Parseable" plugin installed

**AC-prs-004-02 (Datasource Configuration):**

- [ ] WHERE datasource is configured, system SHALL connect to http://parseable.monitoring.svc:8000
- Validation: Check Grafana datasource configuration
- Grafana UI: Configuration → Data Sources → Parseable
- Verify URL is http://parseable.monitoring.svc.cluster.local:8000

**AC-prs-004-03 (Query Performance):**

- [ ] WHEN user queries logs, Grafana SHALL return results within 5 seconds for last 15 minutes
- Validation: Execute query in Grafana Explore, measure response time
- Grafana UI: Explore → Parseable datasource
- Query: Select "Last 15 minutes" time range, run query
- Verify results appear within 5 seconds (NFR-prs-d8f3-PERF-001)

**AC-prs-004-04 (Connection Error Handling):**

- [ ] IF Parseable is unreachable, Grafana SHALL display connection error with clear message
- Validation: Test datasource connection
- Grafana UI: Configuration → Data Sources → Parseable → "Test" button
- Should show "Data source is working" (green) when Parseable is healthy
- Test failure scenario (optional): Scale Parseable to 0, verify clear error message

**AC-prs-004-05 (Log Filtering):**

- [ ] WHILE datasource active, system SHALL support log stream filtering by namespace and pod
- Validation: Query logs with filters
- Grafana UI: Explore → Parseable
- Test filters: k8s.namespace="default", k8s.pod_name="test-pod"
- Verify filtered results returned

**End-to-End Validation (Complete Log Pipeline):**

1. **Generate Test Log:**

    ```bash
    kubectl run e2e-test-pod --image=busybox --rm -it --restart=Never -- sh -c "echo 'E2E_FINAL_TEST_$(date +%s)'; sleep 5"
    ```

2. **Wait for Log Propagation:** 10-15 seconds (Vector batching + Parseable ingestion + S3 write)

3. **Query in Grafana:**
    - Navigate to Grafana → Explore → Parseable datasource
    - Time range: Last 15 minutes
    - Filter: k8s.pod_name="e2e-test-pod"
    - Search for "E2E_FINAL_TEST"

4. **Verify Results:**
    - [ ] Log entry appears in Grafana within 15 seconds
    - [ ] Log contains k8s.namespace label (e.g., "default")
    - [ ] Log contains k8s.pod_name label ("e2e-test-pod")
    - [ ] Log contains k8s.container_name label
    - [ ] Log message includes "E2E_FINAL_TEST" text
    - [ ] Query response time <5 seconds (for 15min window)

**Performance Validation (NFR-prs-d8f3-PERF-001):**

- [ ] Query last 15 minutes: Response time <5 seconds (95th percentile)
- [ ] Query last 1 hour: Response time <10 seconds
- [ ] Query last 24 hours: Initial response <10 seconds (progressive streaming)

**Health Check:**

- [ ] Grafana pod status is Running
- [ ] Parseable datasource shows "Connected" status
- [ ] No error logs in Grafana pod related to Parseable plugin
- [ ] Prometheus metrics show parseable_queries_total increasing
- [ ] ServiceMonitor scraping Parseable metrics successfully

**🎉 Phase 3 Complete - Full Parseable Deployment Validated!**

---

## Dependency Graph

```
Phase 1: Foundation
TASK-001 (Directory)
  └─> TASK-002 (S3 Secret)
      └─> TASK-003 (HelmRelease)
          └─> TASK-005 (Kustomization)
TASK-004 (HelmRepo) ────┘
TASK-006 (ServiceMonitor)
  └─> TASK-007 (Deploy Phase 1)

Phase 2: Integration
TASK-008 (Directory)
  └─> TASK-009 (RBAC)
      └─> TASK-010 (HelmRelease)
          └─> TASK-012 (Kustomization)
TASK-011 (HelmRepo) ────┘
  └─> TASK-013 (Deploy Phase 2)

Phase 3: Visualization
TASK-014 (Grafana Modify)
  └─> TASK-015 (Deploy Phase 3)
```

---

## Implementation Context

### Critical Path

1. **S3 Configuration** (TASK-002) → Blocks Parseable deployment
2. **Parseable Deployment** (TASK-007) → Blocks Vector sink configuration
3. **Vector Deployment** (TASK-013) → Blocks E2E log flow
4. **Grafana Integration** (TASK-015) → Completes visualization layer

### Risk Mitigation Strategies

**Medium Risk - S3 Compatibility (TASK-003):**

- Verify force_path_style=true setting
- Test S3 connectivity in Parseable pod logs
- Fallback: Check Minio console for API compatibility

**High Risk - Vector Configuration Complexity (TASK-010):**

- Reference official Parseable documentation for Vector sink configuration
- Test log metadata enrichment thoroughly
- Fallback: Start with minimal config, add complexity incrementally

**High Risk - End-to-End Integration (TASK-013, TASK-015):**

- Incremental validation at each phase gate
- Test individual components before full pipeline
- Fallback: Use Parseable API directly for debugging before Grafana integration

**Medium Risk - Grafana Plugin Compatibility (TASK-014):**

- Verify plugin version compatible with Grafana 10.x
- Check plugin installation logs
- Fallback: Use Loki datasource with Loki-compatible API if plugin fails

### Context Compression

**Architecture Summary:**

- **Write Path**: Pod logs → Vector DaemonSet → Parseable HTTP API → S3 (Minio)
- **Read Path**: Grafana Explore → Parseable datasource plugin → Parseable query engine → S3 objects
- **Deployment**: FluxCD GitOps with HelmRelease pattern, SOPS-encrypted secrets
- **Observability**: ServiceMonitor for Prometheus metrics, Grafana dashboards

**Key Configuration Points:**

- Parseable: S3 endpoint (https://s3.68cc.io), force_path_style=true, 30-day retention
- Vector: kubernetes_logs source, add_k8s_metadata transform, 1GB disk buffer
- Grafana: parseable-parseable-datasource plugin, proxy access mode

**Validation Strategy:**

- Phase 1: S3 connectivity, pod health, metrics exposure
- Phase 2: Log discovery, forwarding latency, metadata enrichment
- Phase 3: Plugin installation, datasource connection, query performance, E2E log flow

---

## Verification Checklist (EARS Compliance)

### Requirements Traceability

- [x] REQ-prs-d8f3-001 → TASK-003,007 (Parseable deployment, 5 EARS AC)
- [x] REQ-prs-d8f3-002 → TASK-002,003,007 (S3 configuration, 5 EARS AC)
- [x] REQ-prs-d8f3-003 → TASK-010,013 (Vector deployment, 5 EARS AC)
- [x] REQ-prs-d8f3-004 → TASK-014,015 (Grafana integration, 5 EARS AC)

### EARS Acceptance Criteria Coverage

- [x] All 20 EARS AC → manual validation tasks with BDD-style checklists
- [x] EARS triggers (WHEN/WHILE/IF/WHERE) → specific validation commands
- [x] EARS SHALL assertions → measurable success criteria

### EARS NFR Validation

- [x] NFR-prs-d8f3-PERF-001 → TASK-015 (query performance <5s)
- [x] NFR-prs-d8f3-SEC-001 → TASK-002 (SOPS encryption)
- [x] NFR-prs-d8f3-SCALE-001 → TASK-003,007 (resource limits <2Gi)
- [x] NFR-prs-d8f3-OPS-001 → TASK-006,007 (Prometheus metrics)
- [x] NFR-prs-d8f3-DATA-001 → TASK-003 (30-day retention)

### ADR Implementation

- [x] ADR-001 (S3-Native Storage) → TASK-002,003
- [x] ADR-002 (Vector Over Promtail) → TASK-010
- [x] ADR-003 (Grafana Plugin) → TASK-014
- [x] ADR-004 (Single-Replica) → TASK-003
- [x] ADR-005 (FluxCD Pattern) → All tasks

### Behavioral Contract Consistency

- [x] ParseableAPI interface → TASK-003 (HelmRelease env vars)
- [x] VectorPipeline interface → TASK-010 (Vector customConfig)
- [x] GrafanaParseableDatasource interface → TASK-014 (datasource config)

### Quality Gate Completeness

- [x] Phase 1 validation gate → TASK-007 (13 EARS criteria)
- [x] Phase 2 validation gate → TASK-013 (5 EARS criteria + E2E)
- [x] Phase 3 validation gate → TASK-015 (5 EARS criteria + performance)

---

## Change Log

| Version | Date       | Author                    | Changes                                                        |
| ------- | ---------- | ------------------------- | -------------------------------------------------------------- |
| 0.1.0   | 2025-11-14 | Claude (Kiro Implementer) | Initial tasks.md generated from approved requirements + design |
