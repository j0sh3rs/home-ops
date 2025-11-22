# Technical Design: FluentBit to OpenTelemetry Collector Migration

## 1. Architecture Pattern & Boundary Map

### Selected Pattern: Parallel Operation Strategy

**Pattern Justification**:
- **Zero-downtime requirement**: Both systems run concurrently during validation
- **Risk mitigation**: Allows 24-hour validation before fluent-bit removal
- **Rollback capability**: Instant fallback to fluent-bit if issues detected
- **Query validation**: Existing VictoriaLogs queries tested against both data sources

**System Boundaries**:
```
┌─────────────────────────────────────────────────────────────────┐
│ Kubernetes Cluster                                              │
│                                                                 │
│  ┌──────────────┐                    ┌─────────────────────┐  │
│  │ Application  │                    │ OpenTelemetry       │  │
│  │ Pods         │──log files────────>│ Collector           │  │
│  │ (containerd) │   /var/log/pods    │ (DaemonSet)         │  │
│  └──────────────┘                    │                     │  │
│                                       │ - filelog receiver  │  │
│  ┌──────────────┐                    │ - k8s processor     │  │
│  │ fluent-bit   │                    │ - resource proc     │  │
│  │ (DaemonSet)  │──HTTP JSON────┐   │ - batch processor   │  │
│  │ [EXISTING]   │               │    │ - otlphttp exporter │  │
│  └──────────────┘               │    └──────────┬──────────┘  │
│                                  │               │ OTLP/HTTP   │
│                                  │               │             │
│                                  v               v             │
│                          ┌─────────────────────────────────┐  │
│                          │ VictoriaLogs                    │  │
│                          │ - /insert/jsonline (existing)   │  │
│                          │ - /otlp/v1/logs (new)          │  │
│                          │ - Stream fields: stream,        │  │
│                          │   k_namespace_name, k_pod_name  │  │
│                          └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

**Component Boundary Definitions**:

| Component | Responsibility | Interface | Dependencies |
|-----------|---------------|-----------|--------------|
| OpenTelemetry Collector | Log collection, enrichment, export | Filelog receiver (filesystem), OTLP exporter (HTTP) | Kubernetes API (pod metadata), VictoriaLogs OTLP endpoint |
| VictoriaLogs | Log aggregation and storage | OTLP HTTP receiver `/otlp/v1/logs`, JSONLine receiver (existing) | None |
| fluent-bit (existing) | Legacy log collection | HTTP JSON exporter | VictoriaLogs JSONLine endpoint |
| Kubernetes API | Metadata source | REST API (ServiceAccount auth) | None |

## 2. Technology Stack & Alignment

### Core Technologies

**OpenTelemetry Collector**:
- **Version**: Latest stable from official Helm chart
- **Repository**: `https://open-telemetry.github.io/opentelemetry-helm-charts`
- **Chart**: `opentelemetry-collector`
- **Deployment Mode**: DaemonSet (one pod per node)
- **Justification**: Official upstream chart with logsCollection preset simplifies configuration significantly

**VictoriaLogs**:
- **Version**: v0.11.17 (already deployed)
- **OTLP Support**: Enabled by default, no configuration changes required
- **Endpoint**: `/otlp/v1/logs` at port 9428
- **Modification**: None needed - existing deployment compatible

**FluxCD GitOps**:
- **OCIRepository**: opentelemetry-collector from ghcr.io/open-telemetry registry
- **HelmRelease**: Declarative configuration with SOPS-encrypted secrets
- **Kustomization**: Dependency management (VictoriaLogs dependency)

### Technology Alignment with Steering

**Observability Standards**:
- ✅ Aligns with LGTM stack strategy (Loki/Tempo/Mimir) - OTLP is native protocol
- ✅ S3 backend strategy maintained (VictoriaLogs already using S3)
- ✅ Single-replica pattern (DaemonSet automatically handles node distribution)
- ✅ SOPS encryption for S3 credentials

**Monitoring Integration**:
- ✅ ServiceMonitor for Prometheus metrics collection
- ✅ Grafana datasource compatibility (VictoriaLogs)
- ✅ Resource sizing follows home-lab philosophy (<2Gi memory per pod)

**Deployment Patterns**:
- ✅ FluxCD OCIRepository + HelmRelease pattern
- ✅ Namespace organization (monitoring namespace)
- ✅ Kustomization dependency management

## 3. Components & Interface Contracts

### 3.1 OpenTelemetry Collector Configuration

**Helm Values Specification** (`kubernetes/apps/monitoring/opentelemetry-collector/app/helmrelease.yaml`):

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: opentelemetry-collector
  namespace: monitoring
spec:
  interval: 30m
  chart:
    spec:
      chart: opentelemetry-collector
      version: '>=0.97.0'
      sourceRef:
        kind: OCIRepository
        name: opentelemetry-collector
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
    mode: daemonset

    presets:
      logsCollection:
        enabled: true
        includeCollectorLogs: false

    config:
      receivers:
        filelog:
          include:
            - /var/log/pods/*/*/*.log
          exclude:
            - /var/log/pods/*/otlp-collector/*.log
          start_at: end
          include_file_path: true
          include_file_name: false
          operators:
            # Parse containerd format: 2024-01-15T10:30:45.123456789Z stdout F <log message>
            - type: regex_parser
              regex: '^(?P<time>[^\s]+)\s+(?P<stream>stdout|stderr)\s+(?P<logtag>[^\s]+)\s+(?P<log>.*)$'
              timestamp:
                parse_from: attributes.time
                layout: '%Y-%m-%dT%H:%M:%S.%LZ'
            # Move log field to body
            - type: move
              from: attributes.log
              to: body
            # Extract pod info from file path
            - type: regex_parser
              regex: '^.*\/(?P<namespace>[^_]+)_(?P<pod_name>[^_]+)_(?P<uid>[^\/]+)\/(?P<container_name>[^\/]+)\/.*\.log$'
              parse_from: attributes["log.file.path"]
            # Clean up temporary attributes
            - type: remove
              field: attributes.time
            - type: remove
              field: attributes.logtag

      processors:
        batch:
          send_batch_size: 10000
          timeout: 10s

        k8sattributes:
          auth_type: serviceAccount
          passthrough: false
          extract:
            metadata:
              - k8s.namespace.name
              - k8s.pod.name
              - k8s.pod.uid
              - k8s.deployment.name
              - k8s.statefulset.name
              - k8s.daemonset.name
              - k8s.cronjob.name
              - k8s.job.name
              - k8s.node.name
              - k8s.pod.start_time
            labels:
              - tag_name: app
                key: app.kubernetes.io/name
                from: pod
          pod_association:
            - sources:
                - from: resource_attribute
                  name: k8s.pod.uid
            - sources:
                - from: resource_attribute
                  name: k8s.pod.name
            - sources:
                - from: connection

        # Transform OTLP standard attributes to VictoriaLogs stream fields
        resource:
          attributes:
            # Create stream field from stderr/stdout
            - key: stream
              from_attribute: stream
              action: upsert
            # Map k8s.namespace.name -> k_namespace_name
            - key: k_namespace_name
              from_attribute: k8s.namespace.name
              action: insert
            # Map k8s.pod.name -> k_pod_name
            - key: k_pod_name
              from_attribute: k8s.pod.name
              action: insert
            # app field already created by k8sattributes label extraction

      exporters:
        otlphttp:
          endpoint: http://victoria-logs-server.monitoring.svc.cluster.local:9428
          logs_endpoint: /otlp/v1/logs
          compression: gzip
          timeout: 30s
          retry_on_failure:
            enabled: true
            initial_interval: 5s
            max_interval: 30s
            max_elapsed_time: 300s
          sending_queue:
            enabled: true
            num_consumers: 10
            queue_size: 5000

      service:
        pipelines:
          logs:
            receivers: [filelog]
            processors: [k8sattributes, resource, batch]
            exporters: [otlphttp]

        telemetry:
          metrics:
            address: ':8888'

    resources:
      limits:
        memory: 512Mi
      requests:
        cpu: 100m
        memory: 256Mi

    serviceMonitor:
      enabled: true
      metricsEndpoints:
        - port: metrics
          interval: 30s

    rbac:
      create: true

    serviceAccount:
      create: true

    hostNetwork: false

    volumeMounts:
      - name: varlogpods
        mountPath: /var/log/pods
        readOnly: true

    volumes:
      - name: varlogpods
        hostPath:
          path: /var/log/pods
```

**Interface Contracts**:

| Interface | Type | Contract | Consumer |
|-----------|------|----------|----------|
| Filelog Input | Filesystem | Read `/var/log/pods/*/*/*.log`, exclude self | Kubernetes containerd |
| Kubernetes API | REST | Read pod metadata via ServiceAccount | k8sattributes processor |
| OTLP Export | HTTP | POST to `/otlp/v1/logs` with gzip, retry logic | VictoriaLogs |
| Metrics Endpoint | HTTP | Expose `:8888/metrics` in Prometheus format | kube-prometheus-stack |

**Component Behavioral Contracts** (EARS Format):

- **WHEN** new log line appears in `/var/log/pods/*/*/*.log`, collector **SHALL** parse containerd format within 1 second
- **WHEN** parsing containerd log, collector **SHALL** extract timestamp, stream (stdout/stderr), and log message
- **WHILE** k8sattributes processor runs, collector **SHALL** enrich with pod metadata (namespace, name, labels)
- **WHEN** enrichment complete, resource processor **SHALL** transform k8s.* attributes to k_* stream fields
- **WHEN** batch reaches 10,000 logs OR 10 seconds elapsed, collector **SHALL** export via OTLP
- **IF** OTLP export fails, collector **SHALL** retry with exponential backoff (5s → 30s, max 300s total)
- **WHERE** collector memory exceeds 512Mi, Kubernetes **SHALL** terminate and restart pod

### 3.2 VictoriaLogs Integration

**No Configuration Changes Required**:
- OTLP receiver enabled by default in v0.11.17
- Endpoint: `http://victoria-logs-server.monitoring.svc.cluster.local:9428/otlp/v1/logs`
- Stream fields automatically extracted from OTLP resource attributes

**Stream Field Mapping** (Backward Compatibility):

| VictoriaLogs Field | OTLP Source | Processor |
|-------------------|-------------|-----------|
| `stream` | `attributes.stream` (stdout/stderr from containerd) | resource processor (upsert) |
| `k_namespace_name` | `k8s.namespace.name` | resource processor (insert) |
| `k_pod_name` | `k8s.pod.name` | resource processor (insert) |
| `app` | `k8s.pod.labels.app.kubernetes.io/name` | k8sattributes (label extraction) |

**Interface Contract**:
- **WHEN** OTLP HTTP POST received at `/otlp/v1/logs`, VictoriaLogs **SHALL** decompress gzip payload
- **WHEN** parsing OTLP payload, VictoriaLogs **SHALL** extract stream, k_namespace_name, k_pod_name, app from resource attributes
- **WHERE** stream fields match existing queries (e.g., `{k_namespace_name="monitoring"}`), VictoriaLogs **SHALL** return identical results as fluent-bit logs

### 3.3 GitOps Resource Structure

**Directory Structure**:
```
kubernetes/apps/monitoring/
├── opentelemetry-collector/
│   ├── ks.yaml                    # Kustomization entrypoint
│   └── app/
│       ├── kustomization.yaml     # Resource aggregation
│       └── helmrelease.yaml       # OTel Collector configuration
└── victoria-logs/
    └── app/
        └── helmrelease.yaml       # Existing (no changes)
```

**Kustomization Dependencies** (`kubernetes/apps/monitoring/opentelemetry-collector/ks.yaml`):
```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app opentelemetry-collector
  namespace: flux-system
spec:
  targetNamespace: monitoring
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 10m
  timeout: 5m
  path: ./kubernetes/apps/monitoring/opentelemetry-collector/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  wait: true
  dependsOn:
    - name: victoria-logs
    - name: kube-prometheus-stack
```

**OCIRepository** (`kubernetes/flux/repositories/oci/opentelemetry-collector.yaml`):
```yaml
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: OCIRepository
metadata:
  name: opentelemetry-collector
  namespace: flux-system
spec:
  interval: 12h
  url: oci://ghcr.io/open-telemetry/opentelemetry-helm-charts/opentelemetry-collector
  ref:
    semver: '>=0.97.0'
```

**Interface Contracts**:
- **WHEN** GitRepository changes pushed, FluxCD **SHALL** reconcile within 10 minutes
- **WHEN** HelmRelease fails installation, FluxCD **SHALL** retry 3 times before marking failed
- **WHERE** VictoriaLogs or kube-prometheus-stack not ready, FluxCD **SHALL** wait before deploying OTel Collector
- **IF** HelmRelease upgrade fails, FluxCD **SHALL** rollback to previous working version

## 4. Data Flow & Integration Points

### Log Collection Flow

```
1. Application Pod
   └─> Container writes to stdout/stderr
       └─> Containerd runtime captures
           └─> Writes to /var/log/pods/{namespace}_{pod}_{uid}/{container}/X.log
               Format: "2024-01-15T10:30:45.123456789Z stdout F <message>"

2. OpenTelemetry Collector (filelog receiver)
   └─> Reads new log lines from /var/log/pods
       └─> Regex parser extracts: time, stream, logtag, log
           └─> Move log content to body
               └─> Extract namespace, pod_name from file path

3. k8sattributes Processor
   └─> Queries Kubernetes API (via ServiceAccount)
       └─> Enriches with: k8s.namespace.name, k8s.pod.name, k8s.pod.uid
           └─> Extracts labels: app.kubernetes.io/name → app

4. Resource Processor
   └─> Transforms OTLP standard attributes to VictoriaLogs stream fields
       stream (upsert from attributes.stream)
       k_namespace_name (insert from k8s.namespace.name)
       k_pod_name (insert from k8s.pod.name)
       app (already present from k8sattributes)

5. Batch Processor
   └─> Buffers logs (10,000 logs OR 10 seconds)
       └─> Compresses batch with gzip

6. OTLP HTTP Exporter
   └─> POST to http://victoria-logs-server.monitoring.svc.cluster.local:9428/otlp/v1/logs
       └─> Retry on failure (5s → 30s backoff, max 300s)

7. VictoriaLogs
   └─> Receives OTLP payload
       └─> Extracts stream fields: stream, k_namespace_name, k_pod_name, app
           └─> Stores in S3-backed storage (loki-chunks bucket)
               └─> Available for querying via Grafana datasource
```

### Parallel Operation Data Flow (Migration Period)

**Dual Ingestion**:
- fluent-bit → `/insert/jsonline` → VictoriaLogs (existing path)
- OTel Collector → `/otlp/v1/logs` → VictoriaLogs (new path)

**Query Validation Strategy**:
```logql
# Test query compatibility
{k_namespace_name="monitoring"} |= "error"

# Should return logs from BOTH sources during parallel operation
# - fluent-bit: HTTP JSON via /insert/jsonline
# - OTel Collector: OTLP via /otlp/v1/logs

# Validation: Compare log volume and content between sources
```

### Integration Points

| Integration | Direction | Protocol | Data Format | Error Handling |
|-------------|-----------|----------|-------------|----------------|
| Containerd → OTel | Pull (filesystem) | File read | Containerd format with timestamp prefix | Skip corrupt lines, continue |
| OTel → Kubernetes API | Pull (REST) | HTTPS with ServiceAccount token | JSON (pod metadata) | Cache metadata, retry on 429/503 |
| OTel → VictoriaLogs | Push (HTTP) | OTLP over HTTP | Protobuf/JSON with gzip | Retry with backoff, queue overflow drops oldest |
| OTel → Prometheus | Pull (HTTP) | Prometheus scrape | OpenMetrics format | ServiceMonitor handles discovery |

## 5. Deployment Specifications

### Resource Requirements

**OpenTelemetry Collector DaemonSet** (per node):
```yaml
resources:
  requests:
    cpu: 100m      # Baseline for log processing
    memory: 256Mi  # Buffer for log queuing
  limits:
    memory: 512Mi  # Prevent OOM, restart on overflow
```

**Justification**:
- **CPU**: Log processing is I/O bound, 100m sufficient for 1000 logs/sec per node
- **Memory**: 256Mi baseline + 256Mi headroom for burst traffic
- **Home-lab alignment**: Conservative limits per resource sizing strategy

### RBAC Configuration

**ServiceAccount Permissions**:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: opentelemetry-collector
rules:
  # k8sattributes processor needs pod metadata
  - apiGroups: [""]
    resources: ["pods", "namespaces"]
    verbs: ["get", "watch", "list"]
  # Deployment/StatefulSet/DaemonSet metadata
  - apiGroups: ["apps"]
    resources: ["replicasets", "deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch"]
  # Job/CronJob metadata
  - apiGroups: ["batch"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list", "watch"]
```

**Security Context**:
```yaml
securityContext:
  runAsUser: 0  # Required for /var/log/pods access
  privileged: false
  readOnlyRootFilesystem: false  # Needs write for internal state
```

### High Availability

**Strategy**: DaemonSet Automatic Distribution
- **Node Affinity**: None (deploy to all nodes)
- **Tolerations**: Inherit from Helm chart defaults (master node toleration)
- **Update Strategy**: RollingUpdate with maxUnavailable: 1
- **Restart Policy**: Always

**Failure Scenarios**:

| Failure | Detection | Recovery | Data Impact |
|---------|-----------|----------|-------------|
| Pod crash | Kubernetes liveness probe | Automatic restart within 30s | Loss of in-memory queue (max 10s of logs) |
| Node failure | Kubernetes node controller | Pod rescheduled to healthy node | Loss of queued logs on failed node |
| VictoriaLogs unavailable | OTLP export retry exhaustion | Queue fills, oldest logs dropped | Data loss after 300s retry window |
| Kubernetes API unavailable | k8sattributes processor timeout | Logs exported without k8s metadata | Temporary metadata loss, logs still captured |

### Monitoring & Alerting

**Exposed Metrics** (`:8888/metrics`):
- `otelcol_receiver_accepted_log_records` - Logs received by filelog receiver
- `otelcol_processor_batch_batch_send_size` - Batch size statistics
- `otelcol_exporter_sent_log_records` - Logs successfully exported
- `otelcol_exporter_send_failed_log_records` - Failed exports
- `otelcol_exporter_queue_size` - Current queue depth

**ServiceMonitor Configuration**:
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: opentelemetry-collector
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: opentelemetry-collector
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```

**Recommended Alerts** (Prometheus rules):
```yaml
- alert: OTelCollectorHighFailureRate
  expr: rate(otelcol_exporter_send_failed_log_records[5m]) > 100
  annotations:
    summary: "OTel Collector failing to export logs to VictoriaLogs"

- alert: OTelCollectorQueueFull
  expr: otelcol_exporter_queue_size > 4500
  annotations:
    summary: "OTel Collector export queue nearing capacity (90%)"

- alert: OTelCollectorHighMemory
  expr: container_memory_usage_bytes{pod=~"opentelemetry-collector.*"} > 450Mi
  annotations:
    summary: "OTel Collector memory usage approaching limit"
```

## 6. Migration Orchestration Strategy

### Phase 1: Preparation (Day 0)

**Actions**:
1. Create OCIRepository for opentelemetry-collector Helm chart
2. Create namespace structure: `kubernetes/apps/monitoring/opentelemetry-collector/`
3. Generate HelmRelease with configuration defined in section 3.1
4. Create Kustomization with VictoriaLogs dependency
5. Commit to Git repository (GitOps)

**Validation Gates**:
- ✅ FluxCD reconciles OCIRepository successfully
- ✅ Kustomization enters "Ready" state
- ✅ HelmRelease shows "Release reconciliation succeeded"
- ✅ DaemonSet reports all pods "Running" (one per node)

**EARS Success Criteria**:
- **WHEN** OCIRepository created, FluxCD **SHALL** fetch chart within 12 hours
- **WHEN** HelmRelease applied, pods **SHALL** reach Running state within 5 minutes
- **WHERE** pod fails to start, Kubernetes **SHALL** restart with backoff, FluxCD **SHALL** retry install 3 times

### Phase 2: Parallel Operation (Day 1-2)

**Dual Data Collection**:
- fluent-bit continues sending to `/insert/jsonline`
- OTel Collector sends to `/otlp/v1/logs`
- Both sources write to same VictoriaLogs instance

**Validation Checklist**:
```bash
# 1. Verify OTel Collector pods running
kubectl get pods -n monitoring -l app.kubernetes.io/name=opentelemetry-collector

# 2. Check OTel Collector metrics
kubectl port-forward -n monitoring daemonset/opentelemetry-collector 8888:8888
curl localhost:8888/metrics | grep otelcol_receiver_accepted_log_records

# 3. Query VictoriaLogs for OTel-sourced logs
# Look for logs with OTLP-specific attributes
curl -G 'http://victoria-logs-server.monitoring.svc.cluster.local:9428/select/logsql/query' \
  --data-urlencode 'query={k_namespace_name="monitoring"} | limit 100'

# 4. Compare log volumes
# fluent-bit metrics: check existing HTTP output metrics
# OTel metrics: otelcol_exporter_sent_log_records

# 5. Test existing LogQL queries
# Verify queries return expected results from OTLP source
```

**Validation Timeline**:
- **Hour 0**: Deploy OTel Collector, verify pod startup
- **Hour 1**: Confirm logs appearing in VictoriaLogs from OTLP endpoint
- **Hour 6**: Compare log volumes (fluent-bit vs OTel should be within 5%)
- **Hour 12**: Run production query suite against OTel-sourced logs
- **Hour 24**: Final go/no-go decision

**EARS Success Criteria**:
- **WHEN** 24 hours elapsed, OTel Collector **SHALL** have exported >95% of fluent-bit log volume
- **WHERE** existing LogQL query executed, VictoriaLogs **SHALL** return identical results from OTLP source
- **IF** OTel failure rate exceeds 1%, migration **SHALL** pause for investigation

### Phase 3: Cutover (Day 3)

**Decommission fluent-bit**:
```bash
# 1. Suspend fluent-bit HelmRelease
flux suspend helmrelease fluent-bit -n monitoring

# 2. Delete fluent-bit DaemonSet
kubectl delete daemonset fluent-bit -n monitoring

# 3. Update Git repository
git rm -r kubernetes/apps/monitoring/fluent-bit/
git commit -m "feat: remove fluent-bit after OTel migration"
git push
```

**Post-Cutover Monitoring** (24 hours):
- Monitor OTel Collector metrics for anomalies
- Watch VictoriaLogs query performance
- Check for missing logs (compare to pre-cutover baselines)
- Verify Grafana dashboards function correctly

**Rollback Procedure** (if issues detected):
```bash
# 1. Unsuspend fluent-bit
flux resume helmrelease fluent-bit -n monitoring

# 2. Wait for fluent-bit pods to start (5 minutes)

# 3. Suspend OTel Collector for investigation
flux suspend helmrelease opentelemetry-collector -n monitoring

# 4. Investigate issue while fluent-bit handles log collection
```

**EARS Success Criteria**:
- **WHEN** fluent-bit suspended, OTel Collector **SHALL** maintain <1% failure rate
- **WHERE** rollback executed, fluent-bit **SHALL** resume log collection within 5 minutes
- **WHILE** OTel-only operation, VictoriaLogs query response time **SHALL** remain <500ms p95

### Phase 4: Cleanup (Day 4+)

**Actions**:
1. Remove fluent-bit Git directory permanently
2. Archive fluent-bit configuration documentation
3. Update observability documentation to reference OTel Collector
4. Create runbook for OTel Collector troubleshooting

**Final Validation**:
- ✅ No fluent-bit resources remain in cluster
- ✅ Git repository contains no fluent-bit references
- ✅ OTel Collector metrics show stable operation
- ✅ VictoriaLogs storage usage matches pre-migration baseline

## 7. Requirements Traceability

### Requirement → Design Component Mapping

| Requirement ID | Requirement Summary | Design Components | Interface Contracts |
|----------------|---------------------|-------------------|---------------------|
| REQ-1.1 | OpenTelemetry Collector Deployment | DaemonSet mode Helm values, hostPath volume mount | Section 3.1: Helm values with logsCollection preset |
| REQ-1.2 | Filelog receiver configuration | Filelog receiver with containerd regex parser | Section 3.1: operators for timestamp/stream/log extraction |
| REQ-1.3 | Container log file paths | `/var/log/pods/*/*/*.log` include pattern | Section 4: Log collection flow step 1-2 |
| REQ-2.1 | Kubernetes metadata enrichment | k8sattributes processor with pod metadata extraction | Section 3.1: k8sattributes configuration with label extraction |
| REQ-2.2 | Stream field mapping | Resource processor transforming k8s.* → k_* | Section 3.2: Stream field mapping table |
| REQ-3.1 | VictoriaLogs OTLP receiver | No config changes (enabled by default) | Section 3.2: Interface contract |
| REQ-3.2 | OTLP endpoint URL | `http://victoria-logs-server.monitoring.svc.cluster.local:9428/otlp/v1/logs` | Section 3.1: otlphttp exporter endpoint |
| REQ-4.1 | Batch processing | Batch processor with 10k logs / 10s timeout | Section 3.1: batch processor configuration |
| REQ-4.2 | OTLP HTTP export | otlphttp exporter with gzip compression | Section 3.1: otlphttp exporter configuration |
| REQ-4.3 | Retry logic | retry_on_failure with exponential backoff | Section 3.1: retry_on_failure configuration (5s → 30s) |
| REQ-5.1 | FluxCD GitOps structure | OCIRepository, HelmRelease, Kustomization | Section 3.3: GitOps resource structure |
| REQ-5.2 | Dependency management | Kustomization dependsOn: victoria-logs, kube-prometheus-stack | Section 3.3: Kustomization dependencies |
| REQ-5.3 | Helm chart values | Section 3.1 complete Helm values | Section 3.1: values yaml block |
| REQ-6.1 | ServiceMonitor creation | serviceMonitor.enabled: true in Helm values | Section 5: ServiceMonitor configuration |
| REQ-6.2 | Prometheus metrics | Telemetry metrics endpoint :8888 | Section 5: Exposed metrics list |
| REQ-7.1 | Parallel operation migration | Dual ingestion strategy (fluent-bit + OTel) | Section 6: Phase 2 parallel operation |
| REQ-7.2 | 24-hour validation | Validation checklist and timeline | Section 6: Phase 2 validation timeline |
| REQ-7.3 | Zero downtime | DaemonSet RollingUpdate, VictoriaLogs dual endpoints | Section 5: Update strategy, Section 6: parallel operation |

### Gap Analysis → Design Resolution

| Gap ID | Gap Description | Design Resolution | Validation |
|--------|----------------|-------------------|------------|
| GAP-1 | No OTel Collector deployment | Section 3.1: Complete Helm values specification | REQ-1.1, REQ-1.2, REQ-1.3 addressed |
| GAP-2 | Missing filelog receiver config | Section 3.1: Filelog receiver with operators | REQ-1.2, REQ-1.3 addressed |
| GAP-3 | Missing k8sattributes processor | Section 3.1: k8sattributes with RBAC | REQ-2.1 addressed |
| GAP-4 | Missing resource processor | Section 3.1: Resource processor with stream field mapping | REQ-2.2 addressed with backward compatibility |
| GAP-5 | VictoriaLogs OTLP endpoint unconfigured | Section 3.2: No config needed (enabled by default) | REQ-3.1, REQ-3.2 addressed |
| GAP-6 | Missing batch processor | Section 3.1: Batch processor (10k/10s) | REQ-4.1 addressed |
| GAP-7 | Missing OTLP exporter | Section 3.1: otlphttp exporter with retry | REQ-4.2, REQ-4.3 addressed |

### Design → Implementation Handoff

**Implementation Prerequisites**:
1. VictoriaLogs v0.11.17 confirmed running (already deployed)
2. kube-prometheus-stack ServiceMonitor CRD available
3. FluxCD OCIRepository support enabled
4. SOPS encryption configured for secrets (if S3 credentials needed)

**Implementation Artifacts to Create**:
- `kubernetes/flux/repositories/oci/opentelemetry-collector.yaml` (OCIRepository)
- `kubernetes/apps/monitoring/opentelemetry-collector/ks.yaml` (Kustomization)
- `kubernetes/apps/monitoring/opentelemetry-collector/app/kustomization.yaml` (Resource aggregation)
- `kubernetes/apps/monitoring/opentelemetry-collector/app/helmrelease.yaml` (Helm values from section 3.1)

**Testing Strategy**:
- Unit: Verify each processor (filelog, k8sattributes, resource) in isolation
- Integration: Validate complete pipeline (filelog → processors → OTLP export)
- E2E: Query VictoriaLogs for logs with all stream fields present
- Performance: Measure log ingestion rate and export latency under load

**Acceptance Criteria** (EARS Format):
- **WHEN** implementation complete, all EARS requirements from requirements.md **SHALL** pass validation
- **WHERE** HelmRelease applied, DaemonSet **SHALL** report all pods Running within 5 minutes
- **WHILE** parallel operation, OTel **SHALL** export >95% of fluent-bit log volume
- **IF** any EARS requirement fails validation, implementation **SHALL** be rejected

---

## Document Metadata

- **Generated**: 2025-11-22
- **Feature**: fluentbit-to-otel-migration
- **Phase**: Design
- **Discovery Type**: Full (research.md created)
- **Requirements Approved**: Yes (auto-approved with -y flag)
- **Next Phase**: Task division (generate tasks.md)
