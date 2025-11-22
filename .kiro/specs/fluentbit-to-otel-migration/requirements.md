# Requirements: fluentbit-to-otel-migration

**Status**: Draft - Awaiting Approval
**Created**: 2025-11-22T21:11:25Z
**Updated**: 2025-11-22T21:14:51Z
**Phase**: Requirements Definition

## Project Description

Convert usage of fluent-bit for logs over to the opentelemetry collector, including full configuration of oci repository, deployment, and migration of existing logs being consumed to proper otel collector formats. Augment existing VictoriaLogs helm chart to support receiving logs via OTLP. Research all configuration requirements thoroughly first before implementing.

## Requirements Overview

This specification covers the complete migration from fluent-bit to OpenTelemetry Collector for Kubernetes log collection with OTLP-native ingestion into VictoriaLogs. Major areas include:

- **OpenTelemetry Collector Deployment**: DaemonSet configuration with filelog receiver and Kubernetes enrichment
- **VictoriaLogs OTLP Integration**: Enable native OTLP receiver endpoint for log ingestion
- **Log Pipeline Migration**: Preserve existing metadata enrichment and stream field mappings
- **GitOps Configuration**: FluxCD-compatible OCI repository and HelmRelease definitions
- **Migration Strategy**: Zero-downtime cutover with validation and rollback capability

---

## Requirement 1: OpenTelemetry Collector Deployment Configuration

### User Story

As a platform engineer, I want OpenTelemetry Collector deployed as a DaemonSet in the monitoring namespace so that logs are collected from all Kubernetes nodes with consistent metadata enrichment.

### Acceptance Criteria (EARS Format)

1. **OCI Repository Configuration**
    - WHEN FluxCD reconciles the OCI repository, the system SHALL fetch the official OpenTelemetry Collector Helm chart from `ghcr.io/open-telemetry/opentelemetry-collector-releases`
    - **Measurable Success**: OCIRepository resource successfully reconciles with Ready status

2. **DaemonSet Deployment Pattern**
    - The OpenTelemetry Collector SHALL deploy as a Kubernetes DaemonSet with one pod per node
    - **Measurable Success**: DaemonSet reports all pods Running with 1/1 Ready status across all nodes

3. **Container Log Access**
    - WHEN deployed, the collector pods SHALL mount `/var/log/containers` and `/var/log/pods` with read-only access
    - **Measurable Success**: Volume mounts configured in pod spec with hostPath type

4. **Filelog Receiver Configuration**
    - The collector SHALL use the filelog receiver to tail `*.log` files from `/var/log/containers/`
    - **Measurable Success**: Filelog receiver configured with appropriate include paths and operators

5. **Containerd Parser**
    - WHEN processing container logs, the collector SHALL parse containerd format (`^(?<time>[^ ]+) (?<stream>stdout|stderr) (?<logtag>[^ ]*) (?<log>.*)$`)
    - **Measurable Success**: Logs successfully parsed with time, stream, and log fields extracted

### Priority

High

### Dependencies

- Kubernetes cluster with containerd runtime
- FluxCD operator for GitOps reconciliation
- Access to OpenTelemetry Collector OCI registry

---

## Requirement 2: Kubernetes Metadata Enrichment

### User Story

As a platform engineer, I want Kubernetes metadata (namespace, pod, labels) automatically added to all log records so that logs are properly contextualized for querying and correlation.

### Acceptance Criteria (EARS Format)

1. **Kubernetes Attributes Processor**
    - The collector SHALL use the Kubernetes Attributes Processor to enrich logs with cluster metadata
    - **Measurable Success**: Processor configured with pod association and metadata extraction

2. **Stream Field Mapping**
    - WHEN logs are enriched, the collector SHALL add `stream`, `k_namespace_name`, `k_pod_name`, and `app` fields matching current fluent-bit convention
    - **Measurable Success**: Enriched logs contain all required stream fields with correct values

3. **App Label Extraction**
    - IF pod has label `app.kubernetes.io/name`, `app`, or `k8s-app`, THEN the collector SHALL extract and map to `app` field
    - **Measurable Success**: App field populated from any of the three label sources

4. **Metadata Cardinality Control**
    - The collector SHALL exclude pod annotations and non-essential namespace labels to prevent high cardinality
    - **Measurable Success**: Only essential metadata fields present in output logs

### Priority

High

### Dependencies

- Requirement 1: OpenTelemetry Collector Deployment
- Kubernetes RBAC permissions for pod and namespace metadata access

---

## Requirement 3: VictoriaLogs OTLP Receiver Integration

### User Story

As a platform engineer, I want VictoriaLogs to accept logs via OTLP protocol so that OpenTelemetry Collector can send logs using native OTLP format instead of HTTP JSON.

### Acceptance Criteria (EARS Format)

1. **OTLP HTTP Endpoint**
    - VictoriaLogs SHALL expose an OTLP HTTP receiver endpoint at `/otlp/v1/logs`
    - **Measurable Success**: HTTP endpoint returns 200 OK for valid OTLP log payloads

2. **OTLP Protocol Support**
    - WHEN receiving OTLP logs, VictoriaLogs SHALL accept protobuf-encoded LogsData format per OpenTelemetry specification
    - **Measurable Success**: OTLP-formatted logs successfully ingested and queryable

3. **Resource Attribute Mapping**
    - VictoriaLogs SHALL extract stream fields from OTLP resource attributes maintaining existing `_stream_fields` convention
    - **Measurable Success**: Logs indexed with stream, k_namespace_name, k_pod_name, app as stream fields

4. **Log Body Extraction**
    - WHEN processing OTLP logs, VictoriaLogs SHALL extract the log message from `Body.StringValue` field
    - **Measurable Success**: Log message content correctly stored in VictoriaLogs message field

5. **Timestamp Preservation**
    - VictoriaLogs SHALL preserve OTLP `TimeUnixNano` as the log timestamp with nanosecond precision
    - **Measurable Success**: Log timestamps match original log generation time within 1ms accuracy

### Priority

High

### Dependencies

- VictoriaLogs v0.4.0+ with OTLP support (verify version compatibility)
- Updated Helm chart with OTLP receiver configuration options

---

## Requirement 4: OTLP Export Configuration

### User Story

As a platform engineer, I want OpenTelemetry Collector to export logs to VictoriaLogs via OTLP protocol so that the log pipeline uses native OpenTelemetry standards end-to-end.

### Acceptance Criteria (EARS Format)

1. **OTLP HTTP Exporter**
    - The collector SHALL use the OTLP HTTP exporter to send logs to VictoriaLogs
    - **Measurable Success**: OTLP exporter configured with correct endpoint and protocol settings

2. **VictoriaLogs Endpoint Configuration**
    - The collector SHALL send logs to `http://victoria-logs-server.monitoring.svc.cluster.local:9428/otlp/v1/logs`
    - **Measurable Success**: Network connectivity verified and logs successfully transmitted

3. **Batch Processing**
    - WHEN exporting logs, the collector SHALL batch records using the batch processor with max 1000 logs or 1s timeout
    - **Measurable Success**: Batch processor configured and operational in telemetry pipeline

4. **Compression**
    - The collector SHALL compress OTLP payloads using gzip to reduce network bandwidth
    - **Measurable Success**: HTTP requests include `Content-Encoding: gzip` header

5. **Retry and Backoff**
    - IF VictoriaLogs endpoint returns 5xx error, THEN the collector SHALL retry with exponential backoff up to 5 attempts
    - **Measurable Success**: Retry logic configured with exponential backoff strategy

6. **Error Logging**
    - WHEN export fails, the collector SHALL log errors with detail level sufficient for troubleshooting
    - **Measurable Success**: Failed exports generate structured error logs with endpoint and error details

### Priority

High

### Dependencies

- Requirement 1: OpenTelemetry Collector Deployment
- Requirement 3: VictoriaLogs OTLP Receiver

---

## Requirement 5: GitOps Configuration Management

### User Story

As a platform engineer, I want all OpenTelemetry Collector configuration managed through GitOps so that changes are version-controlled and automatically reconciled by FluxCD.

### Acceptance Criteria (EARS Format)

1. **Directory Structure**
    - The configuration SHALL follow existing GitOps pattern: `kubernetes/apps/monitoring/otel-collector/{ks.yaml,app/ocirepository.yaml,app/helmrelease.yaml,app/kustomization.yaml}`
    - **Measurable Success**: All required files present in correct directory structure

2. **OCIRepository Resource**
    - The system SHALL define an OCIRepository resource referencing OpenTelemetry Collector Helm chart
    - **Measurable Success**: OCIRepository reconciles successfully with no errors

3. **HelmRelease Resource**
    - The system SHALL define a HelmRelease resource with complete OpenTelemetry Collector configuration as Helm values
    - **Measurable Success**: HelmRelease deploys successfully with all specified values applied

4. **Kustomization Integration**
    - The system SHALL include otel-collector in the monitoring namespace Kustomization
    - **Measurable Success**: FluxCD automatically reconciles otel-collector when changes are committed

5. **SOPS Secret Encryption**
    - IF configuration requires secrets, THEN secrets SHALL be encrypted using SOPS before committing to Git
    - **Measurable Success**: No plaintext secrets in Git repository

### Priority

High

### Dependencies

- FluxCD deployed and operational
- SOPS encryption keys configured

---

## Requirement 6: ServiceMonitor and Observability

### User Story

As a platform engineer, I want OpenTelemetry Collector metrics scraped by Prometheus so that collector health and performance are monitored.

### Acceptance Criteria (EARS Format)

1. **ServiceMonitor Resource**
    - The system SHALL create a ServiceMonitor resource for OpenTelemetry Collector with Prometheus scrape configuration
    - **Measurable Success**: ServiceMonitor created and Prometheus targets show otel-collector endpoints

2. **Prometheus Metrics Endpoint**
    - The collector SHALL expose Prometheus metrics at `:8888/metrics` endpoint
    - **Measurable Success**: HTTP GET to metrics endpoint returns Prometheus-formatted metrics

3. **Health Check Endpoint**
    - The collector SHALL expose health check endpoint at `:13133/health` for Kubernetes liveness/readiness probes
    - **Measurable Success**: Health endpoint returns 200 OK when collector is healthy

4. **Grafana Dashboard**
    - The system SHALL include a Grafana dashboard for OpenTelemetry Collector metrics visualization
    - **Measurable Success**: Dashboard JSON added to GitOps repository and imported into Grafana

### Priority

Medium

### Dependencies

- Prometheus Operator with ServiceMonitor CRD
- Grafana with dashboard provisioning

---

## Requirement 7: Migration Strategy and Cutover

### User Story

As a platform engineer, I want a zero-downtime migration from fluent-bit to OpenTelemetry Collector so that log collection continues uninterrupted during the transition.

### Acceptance Criteria (EARS Format)

1. **Parallel Operation Phase**
    - DURING migration, both fluent-bit and OpenTelemetry Collector SHALL run simultaneously sending logs to VictoriaLogs
    - **Measurable Success**: Both collectors operational with logs flowing from both sources

2. **Log Deduplication**
    - WHEN both collectors are running, VictoriaLogs SHALL handle duplicate log entries without data corruption
    - **Measurable Success**: VictoriaLogs storage remains consistent with no query errors

3. **Validation Period**
    - The system SHALL maintain parallel operation for minimum 24 hours before fluent-bit removal
    - **Measurable Success**: 24-hour validation window completed with no critical errors

4. **Rollback Capability**
    - IF OpenTelemetry Collector fails during migration, THEN fluent-bit SHALL remain operational for rollback
    - **Measurable Success**: Fluent-bit can be reactivated by reverting GitOps commit

5. **Fluent-bit Removal**
    - WHEN OpenTelemetry Collector is validated, the system SHALL remove fluent-bit deployment via GitOps
    - **Measurable Success**: Fluent-bit HelmRelease and resources removed from cluster

### Priority

High

### Dependencies

- All previous requirements completed
- Migration plan approved by platform team

---

## Non-Functional Requirements

### Performance

1. The OpenTelemetry Collector SHALL process logs with latency under 100ms from file write to export
2. The collector SHALL handle minimum 10,000 log lines per second per node without dropping logs
3. VictoriaLogs OTLP receiver SHALL process incoming requests with p99 latency under 500ms

### Resource Utilization

1. OpenTelemetry Collector pods SHALL consume maximum 200Mi memory per instance
2. CPU usage SHALL remain under 100m (0.1 CPU core) per collector pod under normal load
3. VictoriaLogs SHALL not exceed 10% storage overhead increase compared to current HTTP ingestion

### Reliability

1. The collector SHALL automatically recover from VictoriaLogs endpoint unavailability within 30 seconds
2. IF a collector pod crashes, Kubernetes SHALL restart it within 10 seconds
3. The system SHALL maintain 99.9% log collection uptime during steady state operation

### Security

1. The collector SHALL run with non-root security context and read-only root filesystem where possible
2. ServiceAccount permissions SHALL follow principle of least privilege with only necessary RBAC rules
3. Network policies SHALL restrict collector egress to only VictoriaLogs endpoints

### Maintainability

1. Configuration changes SHALL apply automatically via GitOps within 5 minutes of Git commit
2. The collector configuration SHALL use Helm values for all environment-specific settings
3. All configuration SHALL be documented with inline comments explaining purpose and rationale

---

## Out of Scope

Items explicitly excluded from this specification:

- Migration of metrics collection (kube-prometheus-stack remains unchanged)
- Trace collection and OTLP trace ingestion
- OpenTelemetry instrumentation of applications
- VictoriaLogs storage backend changes or optimization
- Log retention policy modifications
- Custom log parsing rules beyond containerd format
- Multi-cluster log aggregation
- Log sampling or filtering rules (all logs collected)
- OpenTelemetry Collector gateway deployment pattern
- Historical log backfill from fluent-bit period

---

## Assumptions

1. VictoriaLogs Helm chart supports OTLP receiver configuration (requires version validation)
2. OpenEBS LocalPV storage class provides sufficient I/O performance for log ingestion rates
3. Kubernetes cluster runs containerd as container runtime (not docker/cri-o)
4. Network bandwidth between nodes and VictoriaLogs is sufficient for OTLP traffic
5. Existing VictoriaLogs queries and dashboards remain compatible with OTLP-ingested logs

---

## Approval

- [ ] Requirements reviewed and approved
- [ ] Architecture team reviewed OTLP integration approach
- [ ] VictoriaLogs OTLP capability verified for deployed version
- [ ] Migration strategy approved with downtime window (if needed)
- [ ] Ready to proceed to design phase

**Approved by**: ******\_******
**Date**: ******\_******
