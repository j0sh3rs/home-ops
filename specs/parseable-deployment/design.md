# Design: Parseable Logging Aggregator Deployment

## Meta-Context
- Feature UUID: FEAT-prs-d8f3
- Requirements Trace: REQ-prs-d8f3-001,002,003,004
- Design Version: 0.1.0
- Architecture Pattern: S3-Native Log Aggregation with DaemonSet Collection

---

## ADRs (Architectural Decision Records)

### ADR-001: S3-Native Storage Architecture
**Status:** Accepted
**Context:** Need durable log storage without consuming local disk on Kubernetes nodes. VictoriaMetrics failure taught us to verify OSS S3 capabilities.
**Decision:** Use Parseable with S3 backend (Minio) as primary storage, no local PersistentVolumes
**Rationale:**
- Parseable OSS natively supports S3 (verified: https://www.parseable.com/docs/installation/distributed/k8s-helm)
- Decouples storage from pod lifecycle
- Leverages existing Minio S3 infrastructure
- Cost-effective for home-lab (no PVC provisioning overhead)

**Requirements:** REQ-prs-d8f3-001, REQ-prs-d8f3-002
**Confidence:** 95%
**Alternatives Rejected:**
- Local PV + S3 backups (rejected: unnecessary complexity for logs)
- Loki with S3 (rejected: want native S3-first design)

---

### ADR-002: Vector Over Promtail/FluentBit
**Status:** Accepted
**Context:** Need log shipper to collect pod logs and forward to Parseable. Parseable documentation shows Vector integration.
**Decision:** Deploy Vector as DaemonSet with Kubernetes log source and Parseable HTTP sink
**Rationale:**
- Official Parseable documentation for Vector: https://www.parseable.com/docs/datasource/log-agents/vector
- Modern, performant (written in Rust)
- Rich Kubernetes metadata enrichment
- Built-in buffering and backpressure
- Lower resource usage than FluentBit/Fluentd

**Requirements:** REQ-prs-d8f3-003
**Confidence:** 90%
**Alternatives Rejected:**
- Promtail (rejected: Loki-specific, not Parseable-optimized)
- FluentBit (rejected: more complex, higher resource usage)
- Direct pod logging (rejected: requires app changes)

---

### ADR-003: Grafana Parseable Plugin Over Loki Datasource
**Status:** Accepted
**Context:** Need Grafana integration for log visualization. Parseable may have Loki-compatible API but has native plugin.
**Decision:** Install parseable-parseable-datasource Grafana plugin
**Rationale:**
- Official Parseable plugin exists: https://grafana.com/grafana/plugins/parseable-parseable-datasource/
- Native integration likely better optimized than Loki compatibility layer
- Avoids assumptions about API compatibility
- Proper error messages and feature support

**Requirements:** REQ-prs-d8f3-004
**Confidence:** 85%
**Alternatives Rejected:**
- Loki datasource (rejected: may have compatibility issues)
- Prometheus datasource (rejected: not designed for logs)

---

### ADR-004: Single-Replica Deployment for Home-Lab
**Status:** Accepted
**Context:** Home-lab resource constraints (<2Gi memory per pod). S3 provides durability without pod replication.
**Decision:** Deploy Parseable as single-replica Deployment (not StatefulSet)
**Rationale:**
- S3 backend provides data durability
- Single-user home-lab doesn't need HA
- Simplifies resource management
- Faster restart/recovery

**Requirements:** REQ-prs-d8f3-001, NFR-prs-d8f3-SCALE-001
**Confidence:** 90%
**Alternatives Rejected:**
- Multi-replica (rejected: unnecessary for home-lab)
- StatefulSet (rejected: no sticky identity needed with S3)

---

### ADR-005: FluxCD HelmRelease Deployment Pattern
**Status:** Accepted
**Context:** Existing infrastructure uses FluxCD GitOps with HelmRelease + OCIRepository/HelmRepository pattern
**Decision:** Deploy Parseable via HelmRelease, Vector via HelmRelease, follow existing monitoring namespace patterns
**Rationale:**
- Consistency with existing deployments (Grafana, Tempo, Mimir)
- Declarative configuration in Git
- Automatic reconciliation and drift detection
- SOPS integration for secrets

**Requirements:** All REQs (deployment mechanism)
**Confidence:** 100%
**Alternatives Rejected:**
- Manual kubectl apply (rejected: no GitOps)
- Kustomize only (rejected: Helm charts available)

---

## Component Architecture

### Component Map

```
┌─────────────────────────────────────────────────────────────┐
│                     Grafana (existing)                       │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Parseable Datasource Plugin                           │  │
│  └─────────────────────────┬─────────────────────────────┘  │
└────────────────────────────┼────────────────────────────────┘
                             │ HTTP Query API
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   Parseable Server Pod                       │
│  ┌──────────────────────┐    ┌──────────────────────────┐  │
│  │   HTTP API Server    │◄───│  S3 Storage Backend      │  │
│  │   :8000              │    │  (Minio Compatible)      │  │
│  └──────────┬───────────┘    └──────────────────────────┘  │
│             │                                                │
│             │ Ingest Logs                                    │
└─────────────┼────────────────────────────────────────────────┘
              ▲
              │ HTTP POST (Vector sink)
              │
┌─────────────┴────────────────────────────────────────────────┐
│             Vector DaemonSet (per node)                       │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ kubernetes_logs source → transforms → parseable sink   │  │
│  │ - Pod log discovery                                     │  │
│  │ - Metadata enrichment                                   │  │
│  │ - Local disk buffer (1GB)                               │  │
│  └────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
              ▲
              │ Kubernetes API (pod logs)
              │
        ┌─────┴──────┐
        │ All Pods   │
        └────────────┘
```

---

### New Components

#### Component: Parseable Server
**Responsibility:** Log ingestion, S3 storage, query API → Fulfills: REQ-prs-d8f3-001, REQ-prs-d8f3-002

**Deployment Spec:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: parseable
  namespace: monitoring
spec:
  replicas: 1  # ADR-004
  selector:
    matchLabels:
      app: parseable
  template:
    spec:
      containers:
      - name: parseable
        image: parseable/parseable:latest
        ports:
        - containerPort: 8000
          name: http
        env:
        # S3 Configuration (REQ-prs-d8f3-002)
        - name: P_S3_URL
          value: "https://s3.68cc.io"
        - name: P_S3_REGION
          value: "minio"  # Minio compatibility
        - name: P_S3_BUCKET
          value: "parseable-logs"
        - name: P_S3_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: parseable-s3-secret
              key: S3_ACCESS_KEY_ID
        - name: P_S3_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: parseable-s3-secret
              key: S3_SECRET_ACCESS_KEY
        # Force path-style for Minio (AC-prs-002-02)
        - name: P_S3_PATH_STYLE
          value: "true"
        # Retention policy (AC-prs-002-05)
        - name: P_STORAGE_RETENTION_DAYS
          value: "30"
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            memory: 2Gi  # NFR-prs-d8f3-SCALE-001
```

**Interface (EARS Behavioral Contracts):**
```typescript
// HTTP API Interface
interface ParseableAPI {
  // WHEN logs ingested via POST /api/v1/ingest, SHALL persist to S3 within 30s
  // AC-prs-001-03
  ingestLogs(stream: string, logs: LogEntry[]): Promise<IngestResponse>

  // WHEN query submitted via POST /api/v1/query, SHALL return results within 5s for 15min window
  // AC-prs-004-03, NFR-prs-d8f3-PERF-001
  query(request: QueryRequest): Promise<QueryResponse>

  // WHERE datasource health checked, SHALL validate S3 connectivity
  // AC-prs-001-01
  health(): Promise<HealthStatus>

  // WHILE running, SHALL expose Prometheus metrics at /metrics
  // NFR-prs-d8f3-OPS-001
  metrics(): PrometheusMetrics
}

interface IngestResponse {
  status: "success" | "error"
  recordsIngested: number
  timestamp: string
}

interface QueryRequest {
  query: string
  startTime: string
  endTime: string
  limit?: number
}

interface HealthStatus {
  status: "healthy" | "degraded" | "unhealthy"
  s3Connected: boolean
  uptime: number
}
```

---

#### Component: Vector Log Shipper
**Responsibility:** Pod log collection, metadata enrichment, HTTP forwarding → Fulfills: REQ-prs-d8f3-003

**Deployment Spec:**
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: vector
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: vector
  template:
    spec:
      serviceAccountName: vector
      containers:
      - name: vector
        image: timberio/vector:latest
        volumeMounts:
        - name: var-log
          mountPath: /var/log
          readOnly: true
        - name: var-lib
          mountPath: /var/lib
          readOnly: true
        - name: config
          mountPath: /etc/vector
        resources:
          requests:
            cpu: 100m
            memory: 256Mi
          limits:
            memory: 1Gi
      volumes:
      - name: var-log
        hostPath:
          path: /var/log
      - name: var-lib
        hostPath:
          path: /var/lib
      - name: config
        configMap:
          name: vector-config
```

**Vector Configuration (EARS Behavioral Contracts):**
```toml
# WHEN Vector starts, SHALL discover all pod logs via Kubernetes API
# AC-prs-003-01
[sources.kubernetes_logs]
type = "kubernetes_logs"
auto_partial_merge = true

# WHEN Vector processes logs, SHALL add Kubernetes metadata
# AC-prs-003-05
[transforms.add_k8s_metadata]
type = "remap"
inputs = ["kubernetes_logs"]
source = '''
  .k8s.namespace = .kubernetes.pod_namespace
  .k8s.pod_name = .kubernetes.pod_name
  .k8s.container_name = .kubernetes.container_name
  .k8s.node_name = .kubernetes.pod_node_name
'''

# IF Parseable is unavailable, Vector SHALL buffer logs locally up to 1GB
# AC-prs-003-04
[sinks.parseable]
type = "http"
inputs = ["add_k8s_metadata"]
uri = "http://parseable.monitoring.svc.cluster.local:8000/api/v1/ingest"
encoding.codec = "json"
batch.max_bytes = 1048576  # 1MB batches
buffer.type = "disk"
buffer.max_size = 1073741824  # 1GB buffer (AC-prs-003-04)

# WHILE pods emit logs, Vector SHALL forward to Parseable within 5 seconds
# AC-prs-003-02
batch.timeout_secs = 5
```

**Interface (EARS Behavioral Contracts):**
```typescript
// Vector Pipeline Interface
interface VectorPipeline {
  // WHEN pod logs emitted, SHALL collect from /var/log/pods
  collectPodLogs(): LogStream

  // WHERE log collected, SHALL enrich with Kubernetes metadata
  // AC-prs-003-05
  enrichMetadata(log: RawLog): EnrichedLog

  // IF Parseable HTTP 429 or 5xx, SHALL apply backpressure
  // AC-prs-003-03, NFR-prs-d8f3-SCALE-001
  handleBackpressure(response: HttpResponse): BufferAction

  // WHILE buffer < 1GB, SHALL accumulate logs during Parseable downtime
  // AC-prs-003-04
  bufferLogs(logs: LogEntry[]): BufferStatus
}

interface EnrichedLog {
  timestamp: string
  message: string
  k8s: {
    namespace: string
    pod_name: string
    container_name: string
    node_name: string
  }
}
```

---

### Modified Components

#### Modified: Grafana HelmRelease
**Changes:** Add Parseable datasource plugin and datasource configuration → Fulfills: REQ-prs-d8f3-004

**Modified Section:**
```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: grafana
spec:
  values:
    # WHEN Grafana starts, SHALL install parseable-parseable-datasource plugin
    # AC-prs-004-01
    plugins:
      - grafana-clock-panel
      - grafana-piechart-panel
      # ... existing plugins ...
      - https://github.com/parseablehq/parseable-datasource-plugin/releases/download/v1.0.0/parseable-parseable-datasource-1.0.0.zip;parseable-datasource

    datasources:
      datasources.yaml:
        apiVersion: 1
        datasources:
          # ... existing datasources (Mimir, Tempo, Alertmanager) ...

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
```

**EARS Behavioral Contract:**
```typescript
// Grafana Datasource Interface
interface GrafanaParseableDatasource {
  // WHEN user queries logs, SHALL return results within 5s for last 15min
  // AC-prs-004-03, NFR-prs-d8f3-PERF-001
  query(query: DataQueryRequest): Promise<DataQueryResponse>

  // IF Parseable unreachable, SHALL display connection error
  // AC-prs-004-04
  testDatasource(): Promise<TestResult>

  // WHILE datasource active, SHALL support filtering by namespace and pod
  // AC-prs-004-05
  getLogStreams(): Promise<LogStream[]>
}
```

---

## API Matrix (EARS Behavioral Specifications)

| Endpoint | Method | EARS Contract | Performance | Security | Test Strategy |
|----------|--------|---------------|-------------|----------|---------------|
| `/api/v1/ingest` | POST | WHEN logs posted, SHALL persist to S3 within 30s | <30s persist | Internal only | Integration (S3 write) |
| `/api/v1/query` | POST | WHEN query submitted, SHALL return results <5s (15min window) | <5s (15min) | Internal only | E2E (Grafana query) |
| `/health` | GET | WHERE health checked, SHALL validate S3 connectivity | <2s | Internal only | Integration (S3 connectivity) |
| `/metrics` | GET | WHILE running, SHALL expose Prometheus metrics | <1s | Internal only | Unit (metrics format) |

---

## Data Flow + Traceability

### Log Ingestion Flow (Write Path)
```
1. Pod emits log to stdout/stderr
   └─> Kubernetes captures to /var/log/pods/
       └─> Vector DaemonSet reads log → AC-prs-003-01
           └─> Vector enriches with k8s metadata → AC-prs-003-05
               └─> Vector batches logs (max 5s delay) → AC-prs-003-02
                   └─> Vector HTTP POST to Parseable → REQ-prs-d8f3-003
                       └─> Parseable ingests via HTTP API → REQ-prs-d8f3-001
                           └─> Parseable writes to S3 (30s max) → AC-prs-001-03
                               └─> S3 persists to parseable-logs bucket → AC-prs-002-01
```

**Traceability:**
- Steps 1-2: Kubernetes native logging
- Steps 3-4: REQ-prs-d8f3-003, AC-prs-003-01, AC-prs-003-05
- Step 5: AC-prs-003-02 (5s batching)
- Step 6: REQ-prs-d8f3-001 (HTTP API)
- Step 7: AC-prs-001-03 (30s persist SLA)
- Step 8: REQ-prs-d8f3-002, AC-prs-002-01 (S3 storage)

---

### Log Query Flow (Read Path)
```
1. User navigates to Grafana Explore → Parseable
   └─> Grafana loads datasource plugin → AC-prs-004-01
       └─> User submits log query (e.g., k8s.namespace="default")
           └─> Plugin sends HTTP POST to Parseable /api/v1/query → AC-prs-004-02
               └─> Parseable queries S3 objects → REQ-prs-d8f3-001
                   └─> S3 returns log data → AC-prs-001-05 (survives restarts)
                       └─> Parseable parses and filters logs
                           └─> Results returned to Grafana <5s → AC-prs-004-03, NFR-prs-d8f3-PERF-001
                               └─> User sees logs with k8s metadata → AC-prs-004-05
```

**Traceability:**
- Step 1-2: REQ-prs-d8f3-004, AC-prs-004-01
- Step 3-4: AC-prs-004-02 (service URL)
- Step 5: REQ-prs-d8f3-001 (query engine)
- Step 6: AC-prs-001-05 (S3 durability)
- Step 7-8: AC-prs-004-03, NFR-prs-d8f3-PERF-001 (performance)
- Step 9: AC-prs-004-05 (filtering)

---

## Security Architecture

### Secrets Management (REQ-prs-d8f3-002, NFR-prs-d8f3-SEC-001)

**S3 Credentials Secret:**
```yaml
# File: kubernetes/apps/monitoring/parseable/app/secret.sops.yaml
apiVersion: v1
kind: Secret
metadata:
  name: parseable-s3-secret
  namespace: monitoring
type: Opaque
stringData:
  S3_ACCESS_KEY_ID: <SOPS_ENCRYPTED>
  S3_SECRET_ACCESS_KEY: <SOPS_ENCRYPTED>
```

**SOPS Encryption Command (AC-prs-002-03):**
```bash
sops --encrypt \
  --age <age-key> \
  --encrypted-regex '^(data|stringData)$' \
  --in-place secret.sops.yaml
```

**Network Security:**
- All services use ClusterIP (no external exposure) → NFR-prs-d8f3-SEC-001
- No Ingress for Parseable API (internal only)
- Grafana datasource uses internal DNS (`parseable.monitoring.svc.cluster.local`)

---

## Quality Gates

### Design Validation Checklist
- [x] ADRs: >80% confidence to requirements (5 ADRs, avg 92% confidence)
- [x] Interfaces: All trace to acceptance criteria
  - ParseableAPI → AC-prs-001-01, AC-prs-001-03, AC-prs-004-03
  - VectorPipeline → AC-prs-003-01, AC-prs-003-05, AC-prs-003-04
  - GrafanaParseableDatasource → AC-prs-004-03, AC-prs-004-04, AC-prs-004-05
- [x] NFRs: All have measurable test plans
  - PERF-001: <5s query latency (E2E test)
  - SEC-001: SOPS encryption (pre-commit validation)
  - SCALE-001: <2Gi memory (resource limit enforcement)
  - OPS-001: Prometheus metrics (unit test)
  - DATA-001: 30-day retention (S3 lifecycle policy)

### Traceability Matrix
| Component | Requirements | Acceptance Criteria | Test Coverage |
|-----------|--------------|---------------------|---------------|
| Parseable | REQ-001, REQ-002 | AC-prs-001-*, AC-prs-002-* | Integration + E2E |
| Vector | REQ-003 | AC-prs-003-* | Integration |
| Grafana | REQ-004 | AC-prs-004-* | E2E |
| S3 Config | REQ-002 | AC-prs-002-01,02,03 | Integration |

---

## Deployment Architecture (FluxCD Pattern)

### Directory Structure
```
kubernetes/apps/monitoring/
├── parseable/
│   ├── ks.yaml                          # FluxCD Kustomization
│   └── app/
│       ├── kustomization.yaml           # Resource list
│       ├── helmrelease.yaml             # Parseable Helm config
│       ├── secret.sops.yaml             # SOPS-encrypted S3 creds
│       └── servicemonitor.yaml          # Prometheus metrics scraping
├── vector/
│   ├── ks.yaml
│   └── app/
│       ├── kustomization.yaml
│       ├── helmrelease.yaml             # Vector Helm config
│       ├── configmap.yaml               # Vector pipeline config
│       └── rbac.yaml                    # ServiceAccount + ClusterRole
└── grafana/
    └── app/
        └── helmrelease.yaml             # Modified: add datasource
```

### FluxCD Reconciliation Flow
```
GitRepository (home-kubernetes)
  └─> Kustomization (monitoring namespace)
      ├─> Kustomization (parseable)
      │   └─> HelmRelease (parseable chart)
      ├─> Kustomization (vector)
      │   └─> HelmRelease (vector chart)
      └─> Kustomization (grafana)
          └─> HelmRelease (grafana chart - modified)
```

---

## Performance Considerations

### Query Optimization (NFR-prs-d8f3-PERF-001)
- **Index Strategy:** Parseable auto-indexes on timestamp and common fields
- **Time Window:** <5s for 15min queries (target), <10s for 24hr queries
- **S3 Read Pattern:** Sequential reads from time-partitioned objects
- **Caching:** Parseable may cache recent query results (implementation-dependent)

### Resource Budgets (NFR-prs-d8f3-SCALE-001)
| Component | CPU Request | Memory Request | Memory Limit | Rationale |
|-----------|-------------|----------------|--------------|-----------|
| Parseable | 500m | 512Mi | 2Gi | Query processing, S3 caching |
| Vector (per node) | 100m | 256Mi | 1Gi | Log buffering, metadata enrichment |

**Scaling Considerations:**
- Vector: Horizontal scaling via DaemonSet (scales with nodes)
- Parseable: Vertical scaling only (single-replica)
- S3 ingestion rate: Limited by Parseable single-pod throughput

---

## Failure Modes & Recovery

### Parseable Pod Failure
- **Detection:** Kubernetes liveness probe fails
- **Recovery:** Kubernetes restarts pod automatically
- **Data Impact:** None (S3 durability) → AC-prs-001-05
- **Availability Impact:** ~30s downtime during restart
- **Vector Behavior:** Buffers logs locally (1GB max) → AC-prs-003-04

### S3 Connectivity Failure
- **Detection:** Parseable health check fails, pod logs show S3 errors
- **Recovery:** Manual intervention (check Minio, credentials, network)
- **Data Impact:** Logs buffered in Vector (up to 1GB), then dropped
- **Mitigation:** Monitor Parseable /health endpoint, alert on failures

### Vector DaemonSet Issues
- **Detection:** Missing logs from specific nodes, Vector pod CrashLoopBackOff
- **Recovery:** Kubernetes restarts Vector pods
- **Data Impact:** Logs lost during downtime (no local buffer persistence across restarts)
- **Mitigation:** Resource limits tuning, Vector config validation

---

## Monitoring & Observability

### Metrics Exposed (NFR-prs-d8f3-OPS-001)

**Parseable Metrics (Prometheus format at `/metrics`):**
```
# Ingestion metrics
parseable_logs_ingested_total{stream="default"} 10523
parseable_ingest_errors_total{reason="rate_limit"} 0
parseable_s3_write_latency_seconds{quantile="0.95"} 0.285

# Query metrics
parseable_queries_total{status="success"} 142
parseable_query_latency_seconds{quantile="0.95"} 3.2

# Storage metrics
parseable_s3_objects_total 34
parseable_storage_bytes_total 1073741824
```

**Vector Metrics:**
```
vector_events_in_total{component_id="kubernetes_logs"} 50231
vector_events_out_total{component_id="parseable"} 50108
vector_buffer_events{component_id="parseable"} 0
```

### ServiceMonitor Configuration
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: parseable
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: parseable
  endpoints:
  - port: http
    path: /metrics
    interval: 30s
```

---

## Change Log

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1.0 | 2025-11-11 | Claude | Initial design based on approved requirements |
