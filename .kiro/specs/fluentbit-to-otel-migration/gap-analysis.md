# Gap Analysis: Fluent-bit to OpenTelemetry Collector Migration

**Generated**: 2025-11-22T21:22:00Z
**Feature**: fluentbit-to-otel-migration
**Status**: analysis-complete

## 1. Existing Codebase Assessment

### Current Implementation Architecture

**Fluent-bit Deployment** (`kubernetes/apps/monitoring/fluent-bit/`)
- **Chart Source**: `oci://ghcr.io/home-operations/charts-mirror/fluent-bit:0.54.0`
- **Deployment Mode**: DaemonSet (implied by tail input on all nodes)
- **Log Collection**: Tail all container logs from `/var/log/containers/*.log`
- **Parser**: Containerd format parsing
- **Kubernetes Enrichment**: `kubernetes` filter with `merge_log on`
- **Output Protocol**: HTTP JSON to VictoriaLogs
- **Output Endpoint**: `http://victoria-logs-server.monitoring.svc.cluster.local:9428/insert/jsonline`
- **Stream Fields**: `stream`, `k_namespace_name`, `k_pod_name`, `app`
- **Message Field**: `log`
- **Timestamp Field**: `date`
- **Compression**: gzip enabled

**VictoriaLogs Deployment** (`kubernetes/apps/monitoring/victoria-logs/`)
- **Chart Source**: `oci://ghcr.io/victoriametrics/helm-charts/victoria-logs-single:0.11.17`
- **Storage**: OpenEBS hostpath, 50Gi persistent volume
- **Retention**: 14 days
- **Current Ingestion Endpoint**: `/insert/jsonline` (HTTP JSON format)
- **OTLP Support**: VictoriaLogs v0.11.17+ supports OTLP receiver via `/otlp/v1/logs` endpoint

**GitOps Structure**
- **Pattern**: Each app has `ks.yaml` + `app/kustomization.yaml` + `app/helmrelease.yaml` + `app/ocirepository.yaml`
- **Namespace**: `monitoring`
- **Kustomization Aggregation**: `kubernetes/apps/monitoring/kustomization.yaml` lists all monitoring apps
- **FluxCD Resources**: OCIRepository → HelmRelease → Kustomization pattern

### Current System Strengths
1. ✅ **Proven Stability**: Fluent-bit successfully collecting logs from all pods
2. ✅ **Efficient Storage**: VictoriaLogs providing 14-day retention with 50Gi storage
3. ✅ **Metadata Enrichment**: Kubernetes filter properly extracting namespace, pod, app labels
4. ✅ **Compression**: gzip reducing network traffic between log shipper and VictoriaLogs
5. ✅ **GitOps Integration**: Complete FluxCD management with OCIRepository pattern
6. ✅ **Established Patterns**: Well-defined directory structure and resource naming conventions

### Identified Constraints
1. ⚠️ **Custom Chart Mirror**: Fluent-bit using `home-operations/charts-mirror` instead of official charts
2. ⚠️ **HTTP JSON Protocol**: Current protocol is VictoriaLogs-specific, not standards-based
3. ⚠️ **No OTLP Integration**: VictoriaLogs OTLP receiver not currently enabled
4. ⚠️ **Single Log Collector**: No OpenTelemetry components in monitoring namespace

## 2. Capability Gaps

### Missing Components
1. **OpenTelemetry Collector Deployment** (Priority: CRITICAL)
   - No existing OTel Collector in cluster
   - Requires new DaemonSet deployment
   - Chart source: `oci://ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-k8s`
   - **Gap Severity**: HIGH - Core migration requirement

2. **Filelog Receiver Configuration** (Priority: CRITICAL)
   - No equivalent to fluent-bit's tail input
   - Requires configuration for `/var/log/containers/*.log` parsing
   - Must replicate containerd log format parsing: `^(?<time>.+) (?<stream>stdout|stderr) (?<logtag>[^ ]*) (?<log>.*)$`
   - **Gap Severity**: HIGH - Data collection foundation

3. **Kubernetes Attributes Processor** (Priority: CRITICAL)
   - No replacement for fluent-bit's kubernetes filter
   - Must extract: `k8s.namespace.name`, `k8s.pod.name`, `k8s.deployment.name`, `k8s.pod.labels.app`
   - Requires passthrough flag for non-Kubernetes pods
   - **Gap Severity**: HIGH - Metadata enrichment essential

4. **OTLP Exporter Configuration** (Priority: CRITICAL)
   - No existing OTLP export pipeline
   - Requires batch processor (512 logs, 100ms timeout)
   - Needs retry logic (enabled, initial_interval: 5s, max_interval: 30s, max_elapsed_time: 300s)
   - Must configure gzip compression
   - **Gap Severity**: HIGH - Core protocol requirement

5. **VictoriaLogs OTLP Receiver** (Priority: CRITICAL)
   - OTLP endpoint exists (`/otlp/v1/logs`) but not configured
   - Current HelmRelease only configures `/insert/jsonline` ingestion
   - Requires `server.extraArgs` configuration or verification of native OTLP support
   - **Gap Severity**: MEDIUM - VictoriaLogs supports it, configuration needed

6. **OCIRepository for OpenTelemetry** (Priority: HIGH)
   - No OCIRepository resource for OpenTelemetry Collector chart
   - Must follow established pattern: `kubernetes/apps/monitoring/opentelemetry-collector/app/ocirepository.yaml`
   - Chart mirroring decision required (official vs custom mirror)
   - **Gap Severity**: MEDIUM - GitOps infrastructure requirement

7. **ServiceMonitor for OpenTelemetry** (Priority: MEDIUM)
   - No Prometheus monitoring for OTel Collector metrics
   - Requires ServiceMonitor targeting port 8888 (Prometheus metrics endpoint)
   - Labels: `app.kubernetes.io/name: opentelemetry-collector`, `app.kubernetes.io/instance: opentelemetry-collector`
   - **Gap Severity**: LOW - Observability enhancement

### Configuration Gaps

1. **Stream Field Mapping** (Priority: CRITICAL)
   - Current fluent-bit uses: `stream`, `k_namespace_name`, `k_pod_name`, `app`
   - OpenTelemetry resource attributes: `k8s.namespace.name`, `k8s.pod.name`, `k8s.deployment.name`
   - Mapping strategy required: OTLP resource attributes → VictoriaLogs stream fields
   - **Gap Severity**: HIGH - Compatibility critical for existing queries

2. **Log Format Compatibility** (Priority: HIGH)
   - Current: HTTP JSON with explicit `_stream_fields`, `_msg_field`, `_time_field` parameters
   - Target: OTLP protocol with structured log records
   - VictoriaLogs OTLP receiver must automatically map OTLP fields to stream fields
   - **Gap Severity**: MEDIUM - Format translation handled by VictoriaLogs

3. **Chart Version Compatibility** (Priority: MEDIUM)
   - OpenTelemetry Collector chart version: Latest stable (research needed)
   - VictoriaLogs chart version: 0.11.17 (confirmed OTLP support)
   - Compatibility verification required between OTel export and VictoriaLogs ingestion
   - **Gap Severity**: MEDIUM - Version alignment critical

## 3. Implementation Strategy Options

### Option A: Parallel Operation (Recommended)
**Approach**: Deploy OpenTelemetry Collector alongside existing fluent-bit, validate for 24 hours, then deprecate fluent-bit.

**Advantages**:
- ✅ Zero downtime migration
- ✅ Side-by-side validation of log completeness
- ✅ Immediate rollback capability if issues discovered
- ✅ Allows A/B comparison of log formats and metadata
- ✅ Gradual namespace migration possible

**Disadvantages**:
- ⚠️ Temporary resource duplication (2x log collection overhead)
- ⚠️ Requires careful monitoring to avoid log duplication in VictoriaLogs
- ⚠️ Increased network traffic during parallel operation

**Implementation Steps**:
1. Deploy OpenTelemetry Collector with OTLP export to VictoriaLogs
2. Configure VictoriaLogs OTLP receiver (separate endpoint from HTTP JSON)
3. Validate 24 hours of log collection via OTLP
4. Compare log completeness and metadata between fluent-bit and OTel
5. Deprecate fluent-bit after validation passes
6. Remove fluent-bit HelmRelease and OCIRepository

**Risk Level**: LOW - Safest migration path with validation gates

### Option B: Direct Replacement
**Approach**: Remove fluent-bit, deploy OpenTelemetry Collector in single operation.

**Advantages**:
- ✅ No resource duplication
- ✅ Simpler configuration (single log pipeline)
- ✅ Faster migration timeline

**Disadvantages**:
- ⚠️ Risk of log loss during transition window
- ⚠️ No A/B validation capability
- ⚠️ Rollback requires fluent-bit redeployment
- ⚠️ High risk if OTLP integration issues discovered

**Implementation Steps**:
1. Delete fluent-bit HelmRelease
2. Deploy OpenTelemetry Collector
3. Configure VictoriaLogs OTLP receiver
4. Monitor for issues, rollback if problems detected

**Risk Level**: HIGH - Not recommended for production home-lab

### Option C: Namespace-by-Namespace Migration
**Approach**: Migrate logs from specific namespaces progressively using log filtering.

**Advantages**:
- ✅ Gradual rollout with incremental risk
- ✅ Ability to validate per-namespace before proceeding
- ✅ Rollback scoped to individual namespaces

**Disadvantages**:
- ⚠️ Complex filtering configuration required
- ⚠️ Extended migration timeline
- ⚠️ Overhead of managing parallel configurations
- ⚠️ Not aligned with DaemonSet deployment model

**Risk Level**: MEDIUM - Complexity outweighs benefits for home-lab scale

**Recommendation**: **Option A (Parallel Operation)** for safe, validated migration with zero downtime.

## 4. Integration Challenges

### Technical Challenges

1. **Stream Field Mapping Complexity** (Severity: HIGH)
   - **Challenge**: VictoriaLogs expects `stream`, `k_namespace_name`, `k_pod_name`, `app` fields
   - **OTLP Attributes**: `k8s.namespace.name`, `k8s.pod.name`, `k8s.deployment.name`, `stream`
   - **Solution Required**: Verify VictoriaLogs OTLP receiver automatically maps OTLP resource attributes to stream fields
   - **Research Needed**: VictoriaLogs OTLP field mapping documentation

2. **Containerd Log Format Parsing** (Severity: MEDIUM)
   - **Challenge**: Replicate fluent-bit's containerd parser in OpenTelemetry Collector
   - **Current Regex**: `^(?<time>.+) (?<stream>stdout|stderr) (?<logtag>[^ ]*) (?<log>.*)$`
   - **Solution**: Configure filelog receiver with equivalent regex_parser operator
   - **Validation**: Test parsing against sample containerd logs

3. **DaemonSet Permissions** (Severity: MEDIUM)
   - **Challenge**: OpenTelemetry Collector DaemonSet requires access to `/var/log/containers/`
   - **Solution**: Ensure `logsCollection` preset configures correct volume mounts and security context
   - **Validation**: Verify pod security policies allow host path mounting

4. **Batch Processing Tuning** (Severity: LOW)
   - **Challenge**: Balance between log latency and export efficiency
   - **Current Settings**: None (fluent-bit uses streaming HTTP)
   - **Recommended**: 512 logs per batch, 100ms timeout (from requirements)
   - **Validation**: Monitor batch processor metrics in Prometheus

### Operational Challenges

1. **GitOps Coordination** (Severity: LOW)
   - **Challenge**: Ensure proper FluxCD resource ordering during parallel operation
   - **Solution**: Use `dependsOn` in Kustomization to ensure VictoriaLogs OTLP configuration applied before OTel Collector deployment
   - **Pattern**: VictoriaLogs HelmRelease → OpenTelemetry Collector HelmRelease

2. **Chart Mirror Decision** (Severity: MEDIUM)
   - **Challenge**: Decide between official OpenTelemetry charts vs custom `home-operations/charts-mirror`
   - **Current Pattern**: Fluent-bit uses custom mirror
   - **Recommendation**: Use official charts for OpenTelemetry (broader community support, faster updates)
   - **Validation**: Verify chart availability and version stability

3. **Migration Validation Criteria** (Severity: MEDIUM)
   - **Challenge**: Define objective success criteria for 24-hour validation period
   - **Metrics Required**:
     - Log volume parity (OTel vs fluent-bit)
     - Metadata completeness (all stream fields populated)
     - Zero parsing errors
     - Query compatibility (existing VictoriaLogs queries work with OTLP logs)
   - **Solution**: Create ServiceMonitor + Grafana dashboard for migration metrics

## 5. Research and Documentation Needs

### Required Research (Priority Order)

1. **VictoriaLogs OTLP Configuration** (CRITICAL)
   - **Question**: Does VictoriaLogs v0.11.17 require `server.extraArgs` to enable OTLP receiver or is it enabled by default?
   - **Documentation Source**: VictoriaLogs Helm chart values.yaml, official OTLP integration docs
   - **Expected Finding**: Configuration flag for OTLP endpoint or confirmation of automatic enablement

2. **OpenTelemetry Collector Helm Chart Values** (CRITICAL)
   - **Question**: What are the exact Helm values required for DaemonSet mode with `logsCollection` preset?
   - **Documentation Source**: https://github.com/open-telemetry/opentelemetry-helm-charts/tree/main/charts/opentelemetry-collector
   - **Expected Finding**: Values for `mode: daemonset`, `presets.logsCollection.enabled: true`, custom config override

3. **OTLP Field Mapping in VictoriaLogs** (HIGH)
   - **Question**: How does VictoriaLogs map OTLP resource attributes to stream fields?
   - **Documentation Source**: VictoriaLogs OTLP receiver documentation
   - **Expected Finding**: Automatic mapping of `k8s.*` attributes to `k_*` stream fields or configuration required

4. **OpenTelemetry Chart Version Compatibility** (MEDIUM)
   - **Question**: What is the latest stable OpenTelemetry Collector chart version compatible with VictoriaLogs OTLP?
   - **Documentation Source**: OpenTelemetry Collector releases, VictoriaLogs compatibility matrix
   - **Expected Finding**: Chart version recommendation (e.g., 0.x.x)

5. **Kubernetes Attributes Processor Configuration** (MEDIUM)
   - **Question**: What `passthrough` configuration is required for non-Kubernetes pods?
   - **Documentation Source**: OpenTelemetry Collector Kubernetes attributes processor docs
   - **Expected Finding**: `passthrough: true` flag or equivalent configuration

### Documentation to Create

1. **Migration Runbook** (Phase: Implementation)
   - Step-by-step deployment procedure
   - Validation checkpoints at each stage
   - Rollback procedure if issues detected
   - Timeline: 24-hour validation period

2. **Configuration Comparison Matrix** (Phase: Design)
   - Fluent-bit vs OpenTelemetry Collector feature mapping
   - Configuration equivalency table
   - Stream field mapping specification

3. **Troubleshooting Guide** (Phase: Implementation)
   - Common issues during migration (parsing errors, metadata gaps, connectivity)
   - Diagnostic queries for VictoriaLogs (OTLP vs HTTP JSON comparison)
   - ServiceMonitor metrics interpretation

## 6. Design Phase Priorities

### Critical Path Items (Must Design First)

1. **OpenTelemetry Collector Helm Configuration** (Priority 1)
   - Complete Helm values specification for DaemonSet mode
   - Filelog receiver with containerd parsing
   - Kubernetes attributes processor with passthrough
   - OTLP exporter with batch/retry/compression
   - ServiceMonitor configuration

2. **VictoriaLogs OTLP Receiver Configuration** (Priority 2)
   - HelmRelease modifications to enable OTLP endpoint
   - Verify OTLP-to-stream-field mapping behavior
   - Retention and storage impact assessment

3. **GitOps Resource Structure** (Priority 3)
   - OCIRepository for OpenTelemetry Collector chart
   - HelmRelease with complete configuration
   - Kustomization resource ordering (VictoriaLogs → OTel)
   - Namespace-level kustomization.yaml updates

### Secondary Design Elements

4. **Migration Orchestration Strategy** (Priority 4)
   - Parallel operation timeline (deployment → validation → deprecation)
   - Rollback decision tree
   - Validation metrics and success criteria

5. **Observability Integration** (Priority 5)
   - ServiceMonitor for OpenTelemetry Collector metrics
   - Grafana dashboard for migration validation
   - Alert rules for log collection failures

6. **Documentation and Testing** (Priority 6)
   - Migration runbook
   - Configuration comparison matrix
   - Troubleshooting guide

## 7. Risk Assessment and Mitigation

### High-Risk Areas

1. **Log Data Loss During Migration** (Probability: MEDIUM, Impact: HIGH)
   - **Risk**: Transition window between fluent-bit deprecation and OTel Collector full operation
   - **Mitigation**: Parallel operation for 24 hours before fluent-bit removal
   - **Validation**: Compare log volume metrics between pipelines
   - **Rollback**: Keep fluent-bit HelmRelease ready for immediate redeployment

2. **Stream Field Mapping Incompatibility** (Probability: MEDIUM, Impact: HIGH)
   - **Risk**: VictoriaLogs queries fail because OTLP attributes don't map to expected stream fields
   - **Mitigation**: Research VictoriaLogs OTLP field mapping before implementation
   - **Validation**: Test sample queries against OTLP logs during parallel operation
   - **Rollback**: Revert to fluent-bit if queries fail after 24-hour validation

3. **OTLP Receiver Configuration Failure** (Probability: LOW, Impact: HIGH)
   - **Risk**: VictoriaLogs OTLP receiver doesn't accept logs from OpenTelemetry Collector
   - **Mitigation**: Verify VictoriaLogs v0.11.17 OTLP support in design phase
   - **Validation**: Test OTLP connectivity before parallel deployment
   - **Rollback**: Reconfigure OTel Collector to HTTP JSON export as fallback

### Medium-Risk Areas

4. **Performance Impact on VictoriaLogs** (Probability: MEDIUM, Impact: MEDIUM)
   - **Risk**: OTLP ingestion slower than HTTP JSON, causing VictoriaLogs backlog
   - **Mitigation**: Monitor VictoriaLogs ingestion rate during parallel operation
   - **Validation**: Check VictoriaLogs metrics for ingestion lag
   - **Rollback**: Revert to fluent-bit if >10% performance degradation

5. **Chart Version Incompatibility** (Probability: LOW, Impact: MEDIUM)
   - **Risk**: OpenTelemetry Collector chart version has breaking changes or bugs
   - **Mitigation**: Use stable chart version from official OpenTelemetry Helm repository
   - **Validation**: Test chart deployment in isolated namespace first
   - **Rollback**: Pin to previous known-good chart version

6. **GitOps Ordering Issues** (Probability: LOW, Impact: MEDIUM)
   - **Risk**: FluxCD deploys OTel Collector before VictoriaLogs OTLP receiver configured
   - **Mitigation**: Use `dependsOn` in Kustomization for proper sequencing
   - **Validation**: Monitor FluxCD reconciliation order in deployment
   - **Rollback**: Correct Kustomization dependencies and force reconciliation

### Low-Risk Areas (Acceptable)

7. **ServiceMonitor Configuration Drift** (Probability: LOW, Impact: LOW)
   - **Risk**: Prometheus metrics not collected from OpenTelemetry Collector
   - **Mitigation**: Follow established ServiceMonitor patterns from kube-prometheus-stack
   - **Validation**: Verify metrics endpoint availability in Prometheus targets
   - **Rollback**: Adjust ServiceMonitor labels/ports

8. **Temporary Resource Duplication Cost** (Probability: HIGH, Impact: LOW)
   - **Risk**: 24-hour parallel operation doubles log collection resource usage
   - **Mitigation**: Accept temporary cost for zero-downtime migration
   - **Validation**: Monitor cluster resource utilization
   - **Rollback**: N/A - expected behavior

### Risk Mitigation Summary

**Critical Mitigations**:
- ✅ Parallel operation for 24-hour validation before fluent-bit removal
- ✅ Pre-research VictoriaLogs OTLP field mapping behavior
- ✅ Test OTLP connectivity before production deployment

**Validation Gates**:
- ✅ Log volume parity check (OTel matches fluent-bit)
- ✅ Metadata completeness verification (all stream fields populated)
- ✅ Query compatibility testing (existing queries work)
- ✅ Zero parsing errors in OpenTelemetry Collector logs

**Rollback Readiness**:
- ✅ Keep fluent-bit HelmRelease ready for immediate redeployment
- ✅ Maintain HTTP JSON endpoint during parallel operation
- ✅ Document rollback procedure in migration runbook

---

## Analysis Conclusion

### Key Findings

1. **Moderate Implementation Gap**: No existing OpenTelemetry components, requires new deployment from scratch
2. **Strong Foundation**: VictoriaLogs v0.11.17 supports OTLP, established GitOps patterns in place
3. **Clear Migration Path**: Parallel operation strategy provides safe, validated migration
4. **Manageable Risks**: All high-risk areas have defined mitigation strategies

### Readiness for Design Phase

**Ready to Proceed**: ✅ YES

**Prerequisites Met**:
- ✅ Existing architecture fully documented
- ✅ Capability gaps comprehensively identified
- ✅ Implementation strategy selected (Parallel Operation)
- ✅ Research needs clearly defined
- ✅ Risk mitigation strategies established

**Critical Research Required Before Design**:
1. VictoriaLogs OTLP configuration requirements
2. OpenTelemetry Collector Helm chart values for DaemonSet mode
3. OTLP-to-stream-field mapping behavior in VictoriaLogs

**Recommended Next Step**: Proceed to `/kiro:spec-design fluentbit-to-otel-migration` to create detailed technical design incorporating research findings.

### Estimated Complexity

**Implementation Complexity**: MEDIUM
- New component deployment (high)
- Established patterns available (reduces risk)
- Parallel operation adds orchestration complexity (medium)
- Clear requirements and acceptance criteria (reduces ambiguity)

**Migration Risk**: LOW (with parallel operation strategy)
**Research Burden**: MEDIUM (3 critical research items)
**Timeline Estimate**: 2-3 implementation phases (deployment, validation, deprecation)
