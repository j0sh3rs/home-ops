# Implementation Tasks: fluentbit-to-otel-migration

**Status**: In Progress - Phase 3 ServiceMonitor and Observability Complete
**Progress**: 17/30 subtasks completed (57%)
**Language**: en
**Last Updated**: 2025-11-22

---

## Task Overview

This document defines the implementation tasks for migrating from fluent-bit to OpenTelemetry Collector with OTLP-native log ingestion into VictoriaLogs.

**Task Sizing**: Each subtask estimated at 1-3 hours of implementation work.

**Parallel Execution**: Tasks marked with `(P)` can be executed in parallel with other `(P)` tasks within the same major task group.

---

## 1. GitOps Infrastructure Setup (P)

**Objective**: Create FluxCD-compatible repository structure and OCI chart references for OpenTelemetry Collector deployment.

**Requirements Coverage**: 5.1, 5.2

**Estimated Duration**: 2-3 hours total

### Subtasks

- [x] 1.1 (P) Create OCIRepository resource for OpenTelemetry Collector Helm chart at `kubernetes/flux/repositories/oci/opentelemetry-collector.yaml` with semver constraint `>=0.97.0` pointing to `oci://ghcr.io/open-telemetry/opentelemetry-helm-charts/opentelemetry-collector`
    - **Requirements**: 5.1, 5.2
    - **Acceptance**: OCIRepository YAML file created with correct chart URL, namespace flux-system, and 12-hour reconciliation interval

- [x] 1.2 (P) Create directory structure `kubernetes/apps/monitoring/opentelemetry-collector/` with subdirectory `app/` following existing GitOps patterns
    - **Requirements**: 5.1
    - **Acceptance**: Directory structure matches existing monitoring components (victoria-logs, kube-prometheus-stack patterns)

- [x] 1.3 Create Kustomization entrypoint at `kubernetes/apps/monitoring/opentelemetry-collector/ks.yaml` with dependencies on victoria-logs and kube-prometheus-stack
    - **Requirements**: 5.2
    - **Acceptance**: Kustomization defines targetNamespace monitoring, wait: true, timeout 5m, and correct dependsOn array

- [x] 1.4 Create Kustomization resource aggregation at `kubernetes/apps/monitoring/opentelemetry-collector/app/kustomization.yaml` listing helmrelease.yaml as resource
    - **Requirements**: 5.1
    - **Acceptance**: Kustomization aggregates HelmRelease with proper namespace and labels

---

## 2. OpenTelemetry Collector Configuration

**Objective**: Implement complete OpenTelemetry Collector HelmRelease with filelog receiver, Kubernetes enrichment, and OTLP export to VictoriaLogs.

**Requirements Coverage**: 1.1, 1.2, 1.3, 2.1, 2.2, 4.1, 4.2, 4.3

**Estimated Duration**: 4-6 hours total

### Subtasks

- [x] 2.1 Create HelmRelease skeleton at `kubernetes/apps/monitoring/opentelemetry-collector/app/helmrelease.yaml` with metadata, chart spec referencing OCIRepository, and install/upgrade remediation strategies
    - **Requirements**: 1.1, 5.3
    - **Acceptance**: HelmRelease specifies chart version >=0.97.0, sourceRef to OCIRepository in flux-system, 3 retries on install failure, rollback strategy on upgrade failure

- [x] 2.2 Configure DaemonSet deployment mode with logsCollection preset enabled in Helm values
    - **Requirements**: 1.1, 1.2
    - **Acceptance**: values.mode set to "daemonset", presets.logsCollection.enabled set to true with includeCollectorLogs false

- [x] 2.3 Implement filelog receiver configuration with containerd log format parsing in config.receivers.filelog section
    - **Requirements**: 1.2, 1.3
    - **Acceptance**: Filelog receiver includes `/var/log/pods/*/*/*.log`, excludes self logs, uses regex parser for containerd format extracting time/stream/logtag/log fields, moves log to body, extracts namespace/pod/uid from file path

- [x] 2.4 Configure k8sattributes processor with ServiceAccount authentication and pod metadata extraction in config.processors.k8sattributes section
    - **Requirements**: 2.1
    - **Acceptance**: Processor extracts k8s.namespace.name, k8s.pod.name, k8s.pod.uid, deployment/statefulset/daemonset names, node name, pod start time, and app label from app.kubernetes.io/name with pod_association via uid/name/connection

- [x] 2.5 Implement resource processor to transform OTLP standard k8s.\_ attributes to VictoriaLogs k\_\_ stream fields in config.processors.resource section
    - **Requirements**: 2.2
    - **Acceptance**: Resource processor creates stream field from attributes.stream (upsert), maps k8s.namespace.name to k_namespace_name (insert), maps k8s.pod.name to k_pod_name (insert), preserves app field from k8sattributes

- [x] 2.6 Configure batch processor with 10,000 log limit and 10-second timeout in config.processors.batch section
    - **Requirements**: 4.1
    - **Acceptance**: Batch processor send_batch_size set to 10000, timeout set to 10s

- [x] 2.7 Implement otlphttp exporter targeting VictoriaLogs at `http://victoria-logs-server.monitoring.svc.cluster.local:9428/otlp/v1/logs` with gzip compression and retry logic in config.exporters.otlphttp section
    - **Requirements**: 4.2, 4.3
    - **Acceptance**: OTLP exporter endpoint correct, logs_endpoint `/otlp/v1/logs`, compression gzip, timeout 30s, retry_on_failure enabled with initial 5s/max 30s intervals and 300s max elapsed time, sending_queue with 10 consumers and 5000 queue size

- [x] 2.8 Define logs pipeline connecting filelog receiver through k8sattributes, resource, batch processors to otlphttp exporter in config.service.pipelines.logs section
    - **Requirements**: 1.2, 2.1, 2.2, 4.1, 4.2
    - **Acceptance**: Pipeline declares receivers [filelog], processors [k8sattributes, resource, batch], exporters [otlphttp] in correct order

- [x] 2.9 Configure resource limits (512Mi memory limit, 256Mi request, 100m CPU request) and hostPath volume mounts for /var/log/pods in values section
    - **Requirements**: 1.3
    - **Acceptance**: Resources block defines limits and requests, volumeMounts includes varlogpods with /var/log/pods readOnly true, volumes defines varlogpods hostPath

- [x] 2.10 Enable RBAC and ServiceAccount creation with telemetry metrics on port 8888 in values section
    - **Requirements**: 2.1, 6.2
    - **Acceptance**: rbac.create true, serviceAccount.create true, service.telemetry.metrics.address ':8888', hostNetwork false

---

## 3. ServiceMonitor and Observability (P)

**Objective**: Configure Prometheus metrics scraping and create Grafana dashboards for OpenTelemetry Collector monitoring.

**Requirements Coverage**: 6.1, 6.2

**Estimated Duration**: 2-3 hours total

### Subtasks

- [x] 3.1 (P) Enable ServiceMonitor in HelmRelease values with 30-second scrape interval targeting metrics port
    - **Requirements**: 6.1
    - **Acceptance**: serviceMonitor.enabled set to true, metricsEndpoints array includes port metrics with 30s interval

- [x] 3.2 (P) Create Prometheus alerting rules for OTel Collector high failure rate, queue capacity, and memory usage in monitoring namespace
    - **Requirements**: 6.2
    - **Acceptance**: PrometheusRule YAML created with alerts for otelcol_exporter_send_failed_log_records rate >100, otelcol_exporter_queue_size >4500, container memory >450Mi

- [x] 3.3 (P) Create Grafana dashboard JSON for OpenTelemetry Collector metrics visualization showing receiver accepted logs, batch sizes, exporter success/failure, queue depth
    - **Requirements**: 6.2
    - **Acceptance**: Dashboard JSON includes panels for all key metrics with appropriate queries and visualizations

---

## 4. Parallel Operation Validation

**Objective**: Deploy OpenTelemetry Collector alongside fluent-bit and validate dual ingestion into VictoriaLogs with 24-hour observation period.

**Requirements Coverage**: 7.1, 7.2, 7.3

**Estimated Duration**: 8-10 hours total (includes 24-hour wait time)

### Subtasks

- [ ] 4.1 Commit all GitOps resources to Git repository and verify FluxCD reconciliation of OCIRepository, Kustomization, and HelmRelease
    - **Requirements**: 5.4, 7.3
    - **Acceptance**: Git commit pushed, FluxCD shows OCIRepository Ready, Kustomization reconciled without errors, HelmRelease reports Release reconciliation succeeded

- [ ] 4.2 Verify OpenTelemetry Collector DaemonSet deployment with one pod per node in Running state with 1/1 Ready status
    - **Requirements**: 1.1, 7.1
    - **Acceptance**: kubectl get daemonset opentelemetry-collector -n monitoring shows DESIRED equals CURRENT equals READY equals number of nodes, all pods in Running state

- [ ] 4.3 Validate filelog receiver is tailing container logs by checking otelcol_receiver_accepted_log_records metric shows increasing count
    - **Requirements**: 1.2, 1.3
    - **Acceptance**: Port-forward to collector pod, curl localhost:8888/metrics shows otelcol_receiver_accepted_log_records counter incrementing

- [ ] 4.4 Confirm k8sattributes processor enrichment by querying VictoriaLogs for logs with k_namespace_name, k_pod_name, and app fields populated from OTLP source
    - **Requirements**: 2.1, 2.2
    - **Acceptance**: VictoriaLogs query `{k_namespace_name="monitoring"}` returns logs with all stream fields present and matching actual pod metadata

- [ ] 4.5 Verify OTLP export success by checking otelcol_exporter_sent_log_records metric and confirming VictoriaLogs /otlp/v1/logs endpoint receiving requests
    - **Requirements**: 4.2, 4.3
    - **Acceptance**: otelcol_exporter_sent_log_records counter incrementing, otelcol_exporter_send_failed_log_records remains 0 or very low, VictoriaLogs logs show OTLP requests

- [ ] 4.6 Compare log volumes between fluent-bit and OpenTelemetry Collector over 6-hour period to verify >95% coverage
    - **Requirements**: 7.2
    - **Acceptance**: Query VictoriaLogs for log count from both sources, OTel log volume within 5% of fluent-bit volume

- [ ] 4.7 Execute production LogQL query suite against OTLP-sourced logs to validate query compatibility and result accuracy
    - **Requirements**: 7.2
    - **Acceptance**: All critical queries (namespace filters, pod filters, app filters, error searches) return expected results from OTLP logs matching fluent-bit log results

- [ ] 4.8 Monitor OpenTelemetry Collector metrics for 24 hours to detect anomalies, memory leaks, or performance degradation
    - **Requirements**: 7.2, 7.3
    - **Acceptance**: 24-hour observation period completed with <1% export failure rate, memory usage stable below 450Mi, no pod restarts due to OOMKill

- [ ] 4.9 Validate ServiceMonitor integration by confirming Prometheus scrapes OTel Collector metrics and alerting rules evaluate correctly
    - **Requirements**: 6.1, 6.2
    - **Acceptance**: Prometheus targets show opentelemetry-collector endpoints as UP, PrometheusRule alerts are in Inactive state (no firing alerts during healthy operation)

---

## 5. Migration Cutover and Cleanup

**Objective**: Remove fluent-bit deployment after successful validation and confirm OpenTelemetry Collector as sole log collection system.

**Requirements Coverage**: 7.3, 7.5

**Estimated Duration**: 3-4 hours total

### Subtasks

- [ ] 5.1 Suspend fluent-bit HelmRelease using flux CLI and verify fluent-bit DaemonSet pods terminate gracefully
    - **Requirements**: 7.5
    - **Acceptance**: flux suspend helmrelease fluent-bit -n monitoring succeeds, kubectl get pods shows fluent-bit pods terminating and removed, no error logs during shutdown

- [ ] 5.2 Monitor OpenTelemetry Collector metrics for 2 hours post-fluent-bit removal to confirm stable solo operation with <1% failure rate
    - **Requirements**: 7.3
    - **Acceptance**: otelcol_exporter_send_failed_log_records rate remains <1%, no increase in queue depth, VictoriaLogs continues receiving logs without interruption

- [ ] 5.3 Execute full production query suite against VictoriaLogs to verify all queries function correctly with OTel-only log source
    - **Requirements**: 7.2
    - **Acceptance**: All production queries return expected results, response times remain <500ms p95, Grafana dashboards display data correctly

- [ ] 5.4 Verify VictoriaLogs query performance and storage metrics show no degradation compared to fluent-bit baseline
    - **Requirements**: 7.3
    - **Acceptance**: VictoriaLogs query p95 latency within 10% of baseline, storage write rate stable, no increase in storage overhead

- [ ] 5.5 Remove fluent-bit directory from Git repository including ks.yaml, app subdirectory, and all fluent-bit configuration files
    - **Requirements**: 7.5
    - **Acceptance**: git rm -r kubernetes/apps/monitoring/fluent-bit/ completed, commit pushed, FluxCD prunes fluent-bit resources from cluster

- [ ] 5.6 Update observability documentation to reference OpenTelemetry Collector as log collection system and archive fluent-bit configuration for reference
    - **Requirements**: 7.5
    - **Acceptance**: Documentation updated with OTel Collector architecture diagrams, fluent-bit configuration moved to claudedocs/archive/ directory

- [ ] 5.7 Create operational runbook for OpenTelemetry Collector troubleshooting including common failure scenarios and resolution steps
    - **Requirements**: 7.5
    - **Acceptance**: Runbook documents pod failure recovery, VictoriaLogs connectivity issues, high memory usage mitigation, queue overflow handling

---

## Requirement Coverage Matrix

| Requirement                      | Mapped Tasks            | Status  |
| -------------------------------- | ----------------------- | ------- |
| 1.1 - OCI Repository & DaemonSet | 1.1, 1.3, 2.1, 2.2, 4.2 | Pending |
| 1.2 - Filelog Receiver           | 2.2, 2.3, 2.8, 4.3      | Pending |
| 1.3 - Container Log Access       | 1.3, 2.3, 2.9           | Pending |
| 2.1 - K8s Metadata Enrichment    | 2.4, 2.8, 4.4           | Pending |
| 2.2 - Stream Field Mapping       | 2.5, 2.8, 4.4           | Pending |
| 3.1 - OTLP HTTP Endpoint         | (VictoriaLogs default)  | N/A     |
| 3.2 - OTLP Protocol Support      | 2.7, 4.5                | Pending |
| 4.1 - Batch Processing           | 2.6, 2.8                | Pending |
| 4.2 - OTLP HTTP Export           | 2.7, 2.8, 4.5           | Pending |
| 4.3 - Retry and Backoff          | 2.7                     | Pending |
| 5.1 - GitOps Directory Structure | 1.2, 1.4                | Pending |
| 5.2 - Dependency Management      | 1.3                     | Pending |
| 5.3 - Helm Chart Values          | 2.1-2.10                | Pending |
| 6.1 - ServiceMonitor             | 3.1, 4.9                | Pending |
| 6.2 - Prometheus Metrics         | 2.10, 3.1, 3.2, 4.9     | Pending |
| 7.1 - Parallel Operation         | 4.1, 4.2                | Pending |
| 7.2 - 24-hour Validation         | 4.6, 4.7, 4.8           | Pending |
| 7.3 - Zero Downtime              | 4.1, 5.2, 5.4           | Pending |
| 7.5 - Fluent-bit Removal         | 5.1, 5.5                | Pending |

---

## Implementation Notes

### Task Dependencies

**Sequential Dependencies**:

- Task 1 (GitOps setup) must complete before Task 2 (HelmRelease creation)
- Task 2 must complete before Task 4 (validation)
- Task 4 must complete before Task 5 (cutover)

**Parallel Opportunities**:

- Within Task 1: Subtasks 1.1, 1.2 can execute in parallel
- Within Task 3: All subtasks (3.1, 3.2, 3.3) can execute in parallel with Task 2 completion
- Task 3 can begin as soon as Task 2.1 (HelmRelease skeleton) is complete

### Validation Gates

Each major task includes built-in validation:

- **Task 1**: FluxCD reconciliation success
- **Task 2**: HelmRelease deployment success with all pods Running
- **Task 3**: Prometheus targets showing UP status
- **Task 4**: 24-hour observation with <1% failure rate
- **Task 5**: Query suite passing with OTel-only logs

### Rollback Strategy

If issues detected during Task 4 or Task 5:

1. Execute `flux resume helmrelease fluent-bit -n monitoring`
2. Wait 5 minutes for fluent-bit pod startup
3. Suspend OpenTelemetry Collector with `flux suspend helmrelease opentelemetry-collector -n monitoring`
4. Investigate root cause while fluent-bit handles log collection
5. After fixes applied, resume from Task 4.1

### Testing Approach

- **Unit Testing**: Validate each processor configuration independently using `otelcol validate` CLI
- **Integration Testing**: Deploy to single node first, validate pipeline end-to-end
- **E2E Testing**: Full cluster deployment with production query suite
- **Performance Testing**: Load test with 10,000 logs/sec per node to verify resource limits

---

## Completion Checklist

Before marking feature complete:

- [ ] All 30 subtasks marked complete
- [ ] All requirements in coverage matrix validated
- [ ] fluent-bit completely removed from cluster and Git repository
- [ ] 48+ hours of stable OpenTelemetry Collector operation observed
- [ ] Documentation updated with OTel Collector references
- [ ] Operational runbook created and reviewed
- [ ] Team trained on OTel Collector troubleshooting procedures

---

**Document Status**: Ready for Implementation
**Next Action**: Begin with Task 1.1 (OCIRepository creation) or execute all Task 1 subtasks in parallel for faster setup
