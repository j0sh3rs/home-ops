# Requirements: VictoriaMetrics Stack Deployment

## Meta-Context
- Feature UUID: FEAT-vm-7f3a9c2d
- Parent Context: [CLAUDE.md - Infrastructure Overview, Observability Stack]
- Dependency Graph:
  - Replaces: kube-prometheus-stack (Prometheus), Mimir, Tempo
  - Integrates: Grafana (existing), Minio S3 (existing), FluxCD (existing)
  - Preserves: ServiceMonitors, PodMonitors (existing scrape targets)

## Functional Requirements

### REQ-vm-7f3a9c2d-001: Deploy VictoriaMetrics k8s Stack
Intent Vector: Deploy complete VictoriaMetrics monitoring solution with operator-managed CRDs, replacing Prometheus for metrics collection and Mimir for long-term storage in single unified platform.

As a **home-lab administrator**
I want **VictoriaMetrics k8s stack deployed via FluxCD HelmRelease**
So that **I have unified metrics collection and storage with lower resource usage than separate Prometheus/Mimir**

Business Value: 9/10 | Complexity: L

Acceptance Criteria (EARS Syntax):
- AC-vm-001-01: WHEN VictoriaMetrics operator HelmRelease is deployed, the system SHALL create VMAgent, VMAlert, VMAlertmanager, VMSingle CRDs in the cluster {confidence: 95%}
- AC-vm-001-02: WHEN VMAgent is configured, the system SHALL automatically discover and scrape all existing ServiceMonitors and PodMonitors {confidence: 90%}
- AC-vm-001-03: WHILE VMSingle is running, the system SHALL accept metrics writes via Prometheus-compatible remote-write endpoint {confidence: 95%}
- AC-vm-001-04: WHERE VMSingle is configured with S3 backend, the system SHALL store metric blocks in Minio bucket victoriametrics-data {confidence: 90%}
- AC-vm-001-05: IF VMSingle memory limit is set to <2Gi, the system SHALL operate within home-lab resource constraints {confidence: 85%}

Validation Hooks:
```gherkin
Given VictoriaMetrics k8s stack is deployed
When I query kubectl get vmclusters,vmagents,vmalerts -n monitoring
Then I should see VMSingle, VMAgent, VMAlert resources in Running state
And ServiceMonitors from kube-prometheus-stack are being scraped
And metrics are queryable via PromQL API
```

Risk Factors:
- CRD compatibility with existing Prometheus ServiceMonitors (Medium)
- S3 backend configuration complexity (Medium)
- Resource usage in single-replica mode (Low)

---

### REQ-vm-7f3a9c2d-002: Configure S3 Backend for Metrics Storage
Intent Vector: Configure VictoriaMetrics to use Minio S3-compatible storage for long-term metrics retention, replacing Mimir's functionality with VictoriaMetrics native S3 support.

As a **home-lab administrator**
I want **VictoriaMetrics to persist metrics blocks to S3 backend**
So that **I have durable long-term storage without local PVC overhead**

Business Value: 8/10 | Complexity: M

Acceptance Criteria (EARS Syntax):
- AC-vm-002-01: WHEN VMSingle configuration includes S3 settings, the system SHALL create SOPS-encrypted secret victoriametrics-s3-secret with keys: S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT=https://s3.68cc.io, S3_BUCKET=victoriametrics-data {confidence: 95%}
- AC-vm-002-02: WHEN VMSingle starts, the system SHALL connect to Minio S3 endpoint using forcepathstyle=true and region=minio for compatibility {confidence: 90%}
- AC-vm-002-03: WHILE metrics are ingested, the system SHALL periodically compact and upload metric blocks to S3 bucket {confidence: 85%}
- AC-vm-002-04: WHERE S3 connectivity fails, the system SHALL buffer metrics locally and retry upload with exponential backoff {confidence: 80%}
- AC-vm-002-05: IF VMSingle pod restarts, the system SHALL recover metrics data from S3 without data loss {confidence: 85%}

Validation Hooks:
```gherkin
Given VMSingle is configured with S3 backend
When I check S3 bucket victoriametrics-data
Then I should see metric block files uploaded
And VMSingle logs show successful S3 connectivity
And metrics query returns data after pod restart
```

Risk Factors:
- S3 authentication issues (similar to Tempo deployment) (High)
- Minio path-style URL configuration (Medium)
- Network latency to S3 affecting write performance (Low)

---

### REQ-vm-7f3a9c2d-003: Deploy VictoriaLogs Cluster
Intent Vector: Deploy VictoriaLogs for centralized log aggregation, replacing planned Parseable/Loki deployments with unified Victoria platform.

As a **home-lab administrator**
I want **VictoriaLogs Cluster deployed for log aggregation**
So that **I have unified observability platform (metrics + logs) from single vendor**

Business Value: 7/10 | Complexity: M

Acceptance Criteria (EARS Syntax):
- AC-vm-003-01: WHEN VictoriaLogs Cluster HelmRelease is deployed, the system SHALL create vlinsert, vlselect, vlstorage components in monitoring namespace {confidence: 90%}
- AC-vm-003-02: WHEN VictoriaLogs is configured, the system SHALL expose ingestion endpoint for Vector/Fluent-bit log shippers {confidence: 90%}
- AC-vm-003-03: WHILE logs are ingested, the system SHALL parse and index log entries for queryability {confidence: 85%}
- AC-vm-003-04: WHERE VictoriaLogs is configured with single replica, the system SHALL operate within home-lab resource constraints (<2Gi memory per component) {confidence: 85%}
- AC-vm-003-05: IF log ingestion rate exceeds 1000 logs/sec, the system SHALL buffer and process without data loss {confidence: 80%}

Validation Hooks:
```gherkin
Given VictoriaLogs Cluster is deployed
When I send test logs via HTTP API
Then logs should be stored and queryable
And VictoriaLogs components are within memory limits
And log queries return results within 500ms
```

Risk Factors:
- VictoriaLogs Cluster complexity vs single-node for home-lab (Medium)
- Log shipper configuration for VictoriaLogs ingestion format (Medium)
- Storage growth rate without log retention policies (Low)

---

### REQ-vm-7f3a9c2d-004: Configure S3 Backend for Log Storage
Intent Vector: Configure VictoriaLogs to use Minio S3-compatible storage for log persistence, following same pattern as metrics storage.

As a **home-lab administrator**
I want **VictoriaLogs to persist logs to S3 backend**
So that **I have durable log storage without local PVC overhead**

Business Value: 7/10 | Complexity: M

Acceptance Criteria (EARS Syntax):
- AC-vm-004-01: WHEN VictoriaLogs configuration includes S3 settings, the system SHALL create SOPS-encrypted secret victorialogs-s3-secret with S3 credentials for bucket victorialogs-data {confidence: 95%}
- AC-vm-004-02: WHEN VictoriaLogs vlstorage component starts, the system SHALL connect to Minio S3 using forcepathstyle=true and region=minio {confidence: 90%}
- AC-vm-004-03: WHILE logs are ingested, the system SHALL write log chunks to S3 bucket with compression {confidence: 85%}
- AC-vm-004-04: WHERE log retention is configured, the system SHALL automatically delete old log chunks from S3 after retention period {confidence: 80%}
- AC-vm-004-05: IF vlstorage pod restarts, the system SHALL recover log data from S3 without data loss {confidence: 85%}

Validation Hooks:
```gherkin
Given VictoriaLogs is configured with S3 backend
When I check S3 bucket victorialogs-data
Then I should see log chunk files uploaded
And VictoriaLogs logs show successful S3 connectivity
And log queries return data after pod restart
```

Risk Factors:
- Similar S3 authentication challenges as Tempo/VictoriaMetrics (High)
- Log chunk size optimization for S3 performance (Medium)
- S3 bandwidth usage for high log volume (Low)

---

### REQ-vm-7f3a9c2d-005: Integrate with Grafana
Intent Vector: Configure existing Grafana instance with VictoriaMetrics and VictoriaLogs datasources, replacing Prometheus/Mimir/Loki datasource configurations.

As a **home-lab administrator**
I want **Grafana configured with VictoriaMetrics and VictoriaLogs datasources**
So that **I can visualize metrics and logs from unified Victoria platform**

Business Value: 9/10 | Complexity: S

Acceptance Criteria (EARS Syntax):
- AC-vm-005-01: WHEN Grafana HelmRelease is updated, the system SHALL add VictoriaMetrics datasource pointing to VMSingle query endpoint {confidence: 95%}
- AC-vm-005-02: WHEN Grafana HelmRelease is updated, the system SHALL add VictoriaLogs datasource pointing to vlselect query endpoint {confidence: 90%}
- AC-vm-005-03: WHILE Grafana is running, the system SHALL support PromQL queries via VictoriaMetrics datasource {confidence: 95%}
- AC-vm-005-04: WHILE Grafana is running, the system SHALL support LogQL-compatible queries via VictoriaLogs datasource {confidence: 85%}
- AC-vm-005-05: WHERE datasource health check runs, the system SHALL report both datasources as healthy {confidence: 90%}

Validation Hooks:
```gherkin
Given Grafana is configured with Victoria datasources
When I create test dashboard with PromQL query
Then metrics data should be displayed
And LogQL query should return log results
And datasource health checks pass
```

Risk Factors:
- LogQL compatibility differences vs Loki (Medium)
- PromQL query performance on large datasets (Low)
- Grafana datasource plugin compatibility (Low)

---

### REQ-vm-7f3a9c2d-006: Remove LGTM Stack Components
Intent Vector: Cleanly remove Prometheus, Mimir, Tempo, and Loki-related configurations to complete big-bang replacement strategy.

As a **home-lab administrator**
I want **existing LGTM stack components fully removed**
So that **I avoid resource conflicts and have clean Victoria-only monitoring**

Business Value: 8/10 | Complexity: M

Acceptance Criteria (EARS Syntax):
- AC-vm-006-01: WHEN kube-prometheus-stack is removed, the system SHALL delete Prometheus StatefulSet, Alertmanager, and operator CRDs {confidence: 95%}
- AC-vm-006-02: WHEN Mimir HelmRelease is deleted, the system SHALL remove all Mimir components (distributor, ingester, querier, compactor, store-gateway) {confidence: 95%}
- AC-vm-006-03: WHEN Tempo HelmRelease is deleted, the system SHALL remove Tempo StatefulSet and associated resources {confidence: 95%}
- AC-vm-006-04: WHERE ServiceMonitors exist, the system SHALL preserve them for VictoriaMetrics VMAgent scraping {confidence: 90%}
- AC-vm-006-05: IF any LGTM component removal fails, the system SHALL provide clear error message and rollback guidance {confidence: 85%}

Validation Hooks:
```gherkin
Given LGTM stack removal is complete
When I check monitoring namespace
Then Prometheus, Mimir, Tempo pods should not exist
And ServiceMonitors should still be present
And VictoriaMetrics is scraping ServiceMonitors
```

Risk Factors:
- ServiceMonitor orphaning during removal (Medium)
- PVC cleanup for Prometheus/Mimir/Tempo (Low)
- CRD removal order dependencies (Medium)

---

### REQ-vm-7f3a9c2d-007: Preserve Existing Scrape Targets
Intent Vector: Ensure VictoriaMetrics VMAgent automatically discovers and scrapes all existing ServiceMonitors and PodMonitors without requiring reconfiguration.

As a **home-lab administrator**
I want **existing ServiceMonitors and PodMonitors automatically scraped**
So that **I don't lose observability for existing workloads during migration**

Business Value: 10/10 | Complexity: S

Acceptance Criteria (EARS Syntax):
- AC-vm-007-01: WHEN VMAgent is deployed, the system SHALL automatically discover all ServiceMonitors in all namespaces {confidence: 95%}
- AC-vm-007-02: WHEN VMAgent is deployed, the system SHALL automatically discover all PodMonitors in all namespaces {confidence: 95%}
- AC-vm-007-03: WHILE VMAgent is running, the system SHALL scrape targets defined by ServiceMonitors at configured intervals {confidence: 95%}
- AC-vm-007-04: WHERE scrape targets change, the system SHALL dynamically update scrape configuration without VMAgent restart {confidence: 90%}
- AC-vm-007-05: IF scrape target is unreachable, the system SHALL log error and continue scraping other targets {confidence: 95%}

Validation Hooks:
```gherkin
Given VMAgent is configured with ServiceMonitor discovery
When I list all ServiceMonitors in cluster
Then VMAgent should scrape all discovered targets
And metrics from existing workloads are queryable
And no ServiceMonitors are orphaned
```

Risk Factors:
- ServiceMonitor label selector configuration (Low)
- Namespace isolation for multi-tenant scraping (Low)
- Scrape interval alignment with Prometheus defaults (Low)

---

## Non-functional Requirements (EARS Format)

### NFR-vm-7f3a9c2d-PERF-001: Query Performance
WHEN user executes PromQL query over 7-day time range, the system SHALL return results within 2 seconds for 95th percentile queries {confidence: 85%}

### NFR-vm-7f3a9c2d-PERF-002: Ingestion Performance
WHEN metrics are written via remote-write, the system SHALL accept at least 10,000 samples/second without backpressure {confidence: 85%}

### NFR-vm-7f3a9c2d-PERF-003: Log Query Performance
WHEN user executes log query over 24-hour time range, the system SHALL return results within 1 second for 95th percentile queries {confidence: 80%}

### NFR-vm-7f3a9c2d-SEC-001: S3 Credential Security
WHERE S3 credentials are stored, the system SHALL encrypt with SOPS using age key age1qwwzsz6z2mmu6hpmjt2he7nepmnhutmhehvkva7l5zy5xzf08d5s5n4d6n {confidence: 100%}

### NFR-vm-7f3a9c2d-SEC-002: S3 Connection Security
WHERE connections to S3 endpoint occur, the system SHALL use HTTPS with insecure=false {confidence: 100%}

### NFR-vm-7f3a9c2d-SCALE-001: Resource Constraints
IF VMSingle memory usage exceeds 1.8Gi, the system SHALL trigger memory pressure alerts before hitting 2Gi limit {confidence: 85%}

### NFR-vm-7f3a9c2d-SCALE-002: Storage Growth
WHEN metrics storage grows, the system SHALL maintain S3 bucket size under 100Gi for 30-day retention {confidence: 80%}

### NFR-vm-7f3a9c2d-OPER-001: Monitoring Observability
WHILE VictoriaMetrics is running, the system SHALL expose Prometheus-compatible metrics about itself for self-monitoring {confidence: 95%}

### NFR-vm-7f3a9c2d-OPER-002: Deployment Safety
WHERE FluxCD reconciliation occurs, the system SHALL validate HelmRelease health before proceeding to next component {confidence: 90%}

### NFR-vm-7f3a9c2d-OPER-003: Rollback Capability
IF deployment fails, the system SHALL preserve ability to rollback via Git revert and FluxCD reconciliation {confidence: 95%}

---

## Traceability Manifest

**Upstream Dependencies:**
- Minio S3 service (s3.68cc.io) - MUST exist and be accessible
- FluxCD (flux-system namespace) - GitOps deployment platform
- Grafana (monitoring namespace) - Visualization platform
- Existing ServiceMonitors/PodMonitors - Scrape target definitions
- SOPS age encryption key - Secret encryption

**Downstream Impacts:**
- Grafana datasources - MUST update to point to VictoriaMetrics/VictoriaLogs
- kube-prometheus-stack - MUST remove to avoid resource conflicts
- Mimir - MUST remove (replaced by VictoriaMetrics long-term storage)
- Tempo - MUST remove (tracing not needed per user decision)
- Any dashboards using Prometheus datasource - WILL need datasource update
- Alerting rules in Prometheus - WILL need migration to VMAlert format

**Coverage Analysis:**
- Requirements Trace: 7 functional requirements, 9 NFRs
- EARS Compliance: 100% (all AC use WHEN/WHILE/IF/WHERE SHALL pattern)
- Risk Coverage: 21 identified risks across requirements
- Test Coverage: BDD scenarios for all functional requirements
- S3 Pattern Reuse: 100% (follows CloudNative-PG/Velero patterns)

**Confidence Scoring:**
- Requirements Clarity: 92% (well-defined scope after Q&A)
- Technical Feasibility: 88% (proven patterns, S3 risks from Tempo experience)
- Resource Sufficiency: 85% (single-replica home-lab constraints)
- Overall Confidence: 88%
