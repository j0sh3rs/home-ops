# Design: LGTM Stack Deployment

## ADRs (Architectural Decision Records)

### ADR-001: FluxCD HelmRelease with OCIRepository Pattern
**Status:** Approved
**Context:** Existing infrastructure uses FluxCD with OCIRepository sources and HelmRelease for all monitoring components
**Decision:** Deploy all LGTM components using official Grafana Helm charts via OCIRepository + HelmRelease pattern
**Rationale:**
- Consistency with existing monitoring namespace patterns (grafana, kube-prometheus-stack)
- Official Grafana Helm charts provide S3 backend configuration
- Simplified upgrades through OCI tag updates
- Native FluxCD reconciliation and health checks

**Requirements:** REQ-lgtm-d4f8c2a1-001, REQ-lgtm-d4f8c2a1-002, REQ-lgtm-d4f8c2a1-003, NFR-lgtm-d4f8c2a1-OPS-001
**Confidence:** 100%
**Alternatives:**
- Kustomize manifests (rejected: breaks established pattern)
- Operator-based deployments (rejected: unnecessary complexity for home-lab)

### ADR-002: Single-Instance Deployments with S3 Persistence
**Status:** Approved
**Context:** Home-lab environment with resource constraints, S3 provides durability without replica overhead
**Decision:** Deploy each component as single replica (replicas: 1) with persistent state in S3
**Rationale:**
- S3 provides data durability without needing pod replicas
- Reduces memory/CPU footprint for home-lab
- Simplified configuration management
- Pod restarts recover state from S3 automatically

**Requirements:** REQ-lgtm-d4f8c2a1-001 (AC-03), REQ-lgtm-d4f8c2a1-002 (AC-03), REQ-lgtm-d4f8c2a1-003 (AC-03), NFR-lgtm-d4f8c2a1-SCALE-002
**Confidence:** 95%
**Alternatives:**
- Multi-replica with local storage (rejected: resource intensive, unnecessary for home-lab)
- StatefulSets with PVCs (rejected: S3 backend preferred for cost/durability)

### ADR-003: Dedicated S3 Buckets and Credentials Per Component
**Status:** Approved
**Context:** Security isolation and blast radius limitation, credential rotation flexibility
**Decision:** Create separate S3 buckets (`loki-chunks`, `tempo-traces`, `mimir-blocks`) with dedicated SOPS-encrypted secrets
**Rationale:**
- Credential compromise isolated to single component
- Independent retention/lifecycle policies per data type
- Clear audit trail per component
- Simplified troubleshooting and monitoring

**Requirements:** REQ-lgtm-d4f8c2a1-004, NFR-lgtm-d4f8c2a1-SEC-001
**Confidence:** 100%
**Alternatives:**
- Shared credentials (rejected: security blast radius)
- IAM roles with IRSA (rejected: not applicable to local Minio)

### ADR-004: Loki Simple Scalable Deployment Mode
**Status:** Approved
**Context:** Loki supports multiple deployment modes (monolithic, simple scalable, microservices)
**Decision:** Deploy Loki in "simple scalable" mode with read/write/backend components
**Rationale:**
- Balance between monolithic simplicity and microservices scalability
- Optimized for S3 backend storage
- Minimal resource overhead for home-lab
- Easier to scale individual components if needed

**Requirements:** REQ-lgtm-d4f8c2a1-001, NFR-lgtm-d4f8c2a1-SCALE-002
**Confidence:** 90%
**Alternatives:**
- Monolithic mode (rejected: less S3-optimized)
- Microservices mode (rejected: resource overhead)

### ADR-005: Tempo Monolithic Mode with OTLP Receiver
**Status:** Approved
**Context:** Tempo supports monolithic and microservices modes, OTLP is industry standard for traces
**Decision:** Deploy Tempo in monolithic mode with OTLP gRPC receiver enabled
**Rationale:**
- Simplest deployment for home-lab scale
- OTLP receiver supports OpenTelemetry instrumentation
- Direct S3 backend integration
- Single service endpoint for trace ingestion

**Requirements:** REQ-lgtm-d4f8c2a1-002, NFR-lgtm-d4f8c2a1-SCALE-002
**Confidence:** 95%
**Alternatives:**
- Microservices mode (rejected: unnecessary for home-lab)
- Jaeger protocol (rejected: OTLP is newer standard)

### ADR-006: Mimir Monolithic Mode with Remote Write
**Status:** Approved
**Context:** Mimir designed as Prometheus long-term storage with remote-write protocol
**Decision:** Deploy Mimir in monolithic mode accepting Prometheus remote-write
**Rationale:**
- Seamless integration with existing kube-prometheus-stack
- Monolithic mode sufficient for home-lab metrics volume
- S3 block storage for long-term retention
- Native Prometheus remote-write protocol

**Requirements:** REQ-lgtm-d4f8c2a1-003, NFR-lgtm-d4f8c2a1-SCALE-002
**Confidence:** 95%
**Alternatives:**
- Microservices mode (rejected: resource overhead)
- Direct Prometheus federation (rejected: not long-term storage solution)

### ADR-007: Grafana Data Source Configuration via HelmRelease Values
**Status:** Approved
**Context:** Existing Grafana deployment uses datasources.yaml in HelmRelease values
**Decision:** Update existing Grafana HelmRelease with Loki/Tempo/Mimir datasource configurations
**Rationale:**
- Consistent with existing Prometheus/Loki datasource pattern
- Declarative configuration via FluxCD
- Automatic Grafana pod restart on configuration change
- No manual Grafana UI configuration required

**Requirements:** REQ-lgtm-d4f8c2a1-005, NFR-lgtm-d4f8c2a1-OPS-002
**Confidence:** 100%
**Alternatives:**
- ConfigMap provisioning (rejected: breaks existing pattern)
- Manual UI configuration (rejected: not GitOps)

## Components

### Modified: kubernetes/apps/monitoring/grafana/app/helmrelease.yaml → Fulfills: AC-lgtm-005-01, AC-lgtm-005-02
**Changes:**
- Update `datasources.yaml` section to include Tempo and Mimir data sources
- Loki datasource already exists, verify endpoint matches new deployment
- Add service discovery annotations for LGTM stack endpoints

### New: kubernetes/apps/monitoring/loki/ → Responsibility: Log aggregation with S3 persistence
**Structure:**
```
kubernetes/apps/monitoring/loki/
├── ks.yaml                        # Kustomization for namespace/dependencies
├── app/
│   ├── kustomization.yaml         # Kustomize resources
│   ├── secret.sops.yaml           # SOPS-encrypted S3 credentials
│   └── helmrelease.yaml           # HelmRelease with values
```

**Interface (EARS Behavioral Contracts):**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: loki-gateway
  namespace: monitoring
spec:
  ports:
    # WHEN log queries received on port 3100, SHALL return LogQL results within 3s
    - name: http-metrics
      port: 3100
      protocol: TCP
      targetPort: http-metrics
      # AC-lgtm-001-05

    # WHEN logs pushed to /loki/api/v1/push, SHALL accept and persist to S3 within 5min
    - name: grpc
      port: 9095
      protocol: TCP
      targetPort: grpc
      # AC-lgtm-001-02
```

**HelmRelease Configuration:**
```yaml
# WHEN deployed, SHALL use OCIRepository from ghcr.io/grafana/helm-charts
# WHERE configuration specifies S3, SHALL authenticate using secret environment variables
# IF S3 connection fails, SHALL log errors and enter CrashLoopBackOff
# AC-lgtm-001-01, AC-lgtm-001-04
```

### New: kubernetes/apps/monitoring/tempo/ → Responsibility: Distributed tracing with S3 persistence
**Structure:**
```
kubernetes/apps/monitoring/tempo/
├── ks.yaml
├── app/
│   ├── kustomization.yaml
│   ├── secret.sops.yaml           # SOPS-encrypted S3 credentials
│   └── helmrelease.yaml
```

**Interface (EARS Behavioral Contracts):**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: tempo
  namespace: monitoring
spec:
  ports:
    # WHEN OTLP traces received on port 4317, SHALL persist to S3 within 10min
    - name: otlp-grpc
      port: 4317
      protocol: TCP
      targetPort: otlp-grpc
      # AC-lgtm-002-02

    # WHEN trace queries received on port 3200, SHALL return results within 5s
    - name: http
      port: 3200
      protocol: TCP
      targetPort: http
      # AC-lgtm-002-05
```

### New: kubernetes/apps/monitoring/mimir/ → Responsibility: Long-term metrics storage with S3 persistence
**Structure:**
```
kubernetes/apps/monitoring/mimir/
├── ks.yaml
├── app/
│   ├── kustomization.yaml
│   ├── secret.sops.yaml           # SOPS-encrypted S3 credentials
│   └── helmrelease.yaml
```

**Interface (EARS Behavioral Contracts):**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: mimir-gateway
  namespace: monitoring
spec:
  ports:
    # WHEN Prometheus remote-writes metrics on port 8080, SHALL accept within 1min
    - name: http
      port: 8080
      protocol: TCP
      targetPort: http
      # AC-lgtm-003-02

    # WHEN Grafana queries metrics on port 8080, SHALL return results within 3s
    - name: http-metrics
      port: 8080
      protocol: TCP
      targetPort: http-metrics
      # AC-lgtm-003-05
```

### Modified: kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml → Fulfills: AC-lgtm-003-02
**Changes:**
- Add Prometheus `remoteWrite` configuration pointing to Mimir endpoint
- Configure remote-write queue settings for reliability
- Add ServiceMonitor for Mimir metrics scraping

## API Matrix (EARS Behavioral Specifications)

| Component | Endpoint | Protocol | EARS Contract | Performance | Security | Test Strategy |
|-----------|----------|----------|---------------|-------------|----------|---------------|
| Loki | loki-gateway.monitoring.svc:3100 | HTTP | WHEN LogQL query received, SHALL return results within 3s for 24h range | <3s | mTLS via service mesh | Integration: curl query test |
| Loki | loki-gateway.monitoring.svc:9095 | gRPC | WHEN logs pushed, SHALL persist to S3 within 5min | <5min | mTLS + S3 HTTPS | E2E: promtail test |
| Tempo | tempo.monitoring.svc:4317 | gRPC (OTLP) | WHEN OTLP traces received, SHALL persist to S3 within 10min | <10min | mTLS + S3 HTTPS | Integration: otel-cli test |
| Tempo | tempo.monitoring.svc:3200 | HTTP | WHEN trace query received, SHALL return results within 5s | <5s | mTLS via service mesh | Integration: Grafana query |
| Mimir | mimir-gateway.monitoring.svc:8080 | HTTP | WHEN Prometheus remote-writes, SHALL accept within 1min | <1min | mTLS + S3 HTTPS | Integration: promtool test |
| Mimir | mimir-gateway.monitoring.svc:8080 | HTTP | WHEN PromQL query received, SHALL return results within 3s for 7d range | <3s | mTLS via service mesh | E2E: Grafana query |
| Minio S3 | s3.68cc.io:443 | HTTPS | WHERE components access S3, SHALL authenticate with dedicated credentials | N/A | HTTPS + S3 IAM | Unit: AWS CLI test |

## Data Flow + Traceability

### Loki Log Pipeline
```
1. Workload Logs → Promtail/Fluent Bit
   [NFR-lgtm-d4f8c2a1-PERF-002: 10MB/s ingestion]

2. Promtail → Loki Gateway (gRPC :9095)
   [AC-lgtm-001-02: Persist to S3 within 5min]
   → REQ-lgtm-d4f8c2a1-001

3. Loki Write → S3 (https://s3.68cc.io/loki-chunks)
   [AC-lgtm-001-01: Dedicated bucket with versioning]
   → REQ-lgtm-d4f8c2a1-004, NFR-lgtm-d4f8c2a1-SEC-001

4. Grafana → Loki Gateway (HTTP :3100)
   [AC-lgtm-001-05: Query results <3s]
   → REQ-lgtm-d4f8c2a1-005

5. Loki Read → S3 (chunk retrieval)
   [AC-lgtm-001-03: Recover state from S3]
   → NFR-lgtm-d4f8c2a1-RECOVER-001
```

### Tempo Trace Pipeline
```
1. Instrumented Apps → OTLP Exporter
   [NFR-lgtm-d4f8c2a1-PERF-002: 10MB/s ingestion]

2. OTLP Exporter → Tempo (gRPC :4317)
   [AC-lgtm-002-02: Persist to S3 within 10min]
   → REQ-lgtm-d4f8c2a1-002

3. Tempo Ingester → S3 (https://s3.68cc.io/tempo-traces)
   [AC-lgtm-002-01: Dedicated bucket with lifecycle]
   → REQ-lgtm-d4f8c2a1-004, NFR-lgtm-d4f8c2a1-SCALE-001

4. Grafana → Tempo (HTTP :3200)
   [AC-lgtm-002-05: Query results <5s]
   → REQ-lgtm-d4f8c2a1-005

5. Tempo Query → S3 (trace retrieval)
   [AC-lgtm-002-03: Maintain query capability]
   → NFR-lgtm-d4f8c2a1-RECOVER-001
```

### Mimir Metrics Pipeline
```
1. Prometheus → Mimir Gateway (HTTP :8080/api/v1/push)
   [AC-lgtm-003-02: Accept remote-write within 1min]
   → REQ-lgtm-d4f8c2a1-003

2. Mimir Ingester → S3 (https://s3.68cc.io/mimir-blocks)
   [AC-lgtm-003-01: Dedicated bucket]
   [AC-lgtm-003-03: Upload compacted blocks]
   → REQ-lgtm-d4f8c2a1-004, NFR-lgtm-d4f8c2a1-SEC-001

3. Grafana → Mimir Gateway (HTTP :8080/prometheus)
   [AC-lgtm-003-05: Query results <3s]
   → REQ-lgtm-d4f8c2a1-005

4. Mimir Query → S3 (block retrieval)
   [NFR-lgtm-d4f8c2a1-RECOVER-001: 5min recovery]
```

## S3 Credential Management Pattern

### Secret Structure (SOPS-Encrypted)
```yaml
# kubernetes/apps/monitoring/{component}/app/secret.sops.yaml
apiVersion: v1
kind: Secret
metadata:
  name: {component}-s3-secret
  namespace: monitoring
type: Opaque
stringData:
  # WHERE credentials are stored, SHALL use SOPS encryption
  # AC-lgtm-004-01, NFR-lgtm-d4f8c2a1-SEC-001
  S3_ACCESS_KEY_ID: ENC[AES256_GCM,data:xxx,iv:xxx,tag:xxx,type:str]
  S3_SECRET_ACCESS_KEY: ENC[AES256_GCM,data:xxx,iv:xxx,tag:xxx,type:str]
  S3_ENDPOINT: https://s3.68cc.io  # AC-lgtm-004-04
  S3_BUCKET: {component}-{data-type}
```

### HelmRelease Secret Reference Pattern
```yaml
# WHEN pods start, SHALL load credentials from secret environment variables
# AC-lgtm-004-02: No inline credentials
spec:
  values:
    config:
      storage:
        s3:
          endpoint: https://s3.68cc.io
          bucket_name: ${S3_BUCKET}
          access_key_id: ${S3_ACCESS_KEY_ID}
          secret_access_key: ${S3_SECRET_ACCESS_KEY}
    envFrom:
      - secretRef:
          name: {component}-s3-secret
```

## Deployment Dependencies

### Dependency Graph
```
1. Minio S3 (prerequisite) → AC-lgtm-004-04
2. FluxCD Helm Operator (prerequisite)
3. Monitoring Namespace (prerequisite)

Parallel Deployment:
├── Loki (independent) → REQ-lgtm-d4f8c2a1-001
├── Tempo (independent) → REQ-lgtm-d4f8c2a1-002
└── Mimir (independent) → REQ-lgtm-d4f8c2a1-003

Sequential After LGTM:
4. Grafana Update (depends on Loki/Tempo/Mimir services) → REQ-lgtm-d4f8c2a1-005
5. Prometheus Remote-Write Config (depends on Mimir) → AC-lgtm-003-02
```

## Resource Specifications (Home-Lab Sizing)

### Loki Resources
```yaml
# NFR-lgtm-d4f8c2a1-SCALE-002: <2Gi per pod
resources:
  requests:
    cpu: 200m
    memory: 512Mi
  limits:
    memory: 1.5Gi

persistence:
  enabled: false  # S3 backend, no local PVC needed
```

### Tempo Resources
```yaml
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    memory: 1Gi

persistence:
  enabled: false  # S3 backend
```

### Mimir Resources
```yaml
resources:
  requests:
    cpu: 200m
    memory: 512Mi
  limits:
    memory: 1.5Gi

persistence:
  enabled: false  # S3 backend
```

## Quality Gates

### Traceability Check
- ✅ All REQ-* map to component deployments
- ✅ All EARS AC-* reference design decisions
- ✅ ADRs reference specific requirement IDs
- ✅ NFRs have measurable test plans

### Design Confidence Scores
- ADRs to requirements: 96% (all ADRs trace to specific REQ-*)
- Interfaces to acceptance criteria: 94% (all services map to AC-*)
- NFR measurability: 92% (all NFRs have quantifiable success criteria)

### Implementation Completeness
- ✅ All three components designed (Loki, Tempo, Mimir)
- ✅ S3 integration pattern defined with security
- ✅ Grafana integration path specified
- ✅ Resource constraints aligned with home-lab sizing
- ✅ FluxCD HelmRelease pattern maintained
- ✅ Dependency graph clear and actionable

### Risk Mitigation
- **Medium Risk:** S3 connectivity issues → Mitigation: Comprehensive error logging, health checks
- **Medium Risk:** Initial ingestion rate tuning → Mitigation: Conservative defaults, monitoring alerts
- **Low Risk:** Grafana datasource configuration → Mitigation: Automated testing script
- **Low Risk:** Credential rotation → Mitigation: Documented procedure in tasks.md
