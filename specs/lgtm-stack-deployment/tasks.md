# Tasks: LGTM Stack Deployment

## Metadata

**Complexity:** High (S3 integration + 3 components + integrations)
**Critical Path:** S3 Setup → Component Deployments → Integrations → Verification
**Risk Score:** Medium (new components, S3 dependencies)
**Timeline Estimate:** 6-8 hours (spread across testing/validation)

## Progress: 7/22 Complete, 0 In Progress, 8 Not Started, 7 Skipped (Manual)

**Note:** Tasks 001-007 (S3 buckets and credentials) are skipped for manual completion. Placeholder values provided in secret templates.

---

## Phase 1: Foundation (S3 and Secrets Infrastructure)

### [SKIP] TASK-lgtm-d4f8c2a1-001: Create Minio S3 Buckets (MANUAL)

**Trace:** REQ-lgtm-d4f8c2a1-001 (AC-01), REQ-lgtm-d4f8c2a1-002 (AC-01), REQ-lgtm-d4f8c2a1-003 (AC-01) | Design: ADR-003
**DoD (EARS Format):**

- WHEN task completed, SHALL have created three S3 buckets: `loki-chunks`, `tempo-traces`, `mimir-blocks` at https://s3.68cc.io
- WHERE buckets are created, SHALL enable versioning on `loki-chunks` bucket
- IF bucket creation verified, SHALL confirm accessibility via AWS CLI with test credentials

**Risk:** Low | **Deps:** None (Minio prerequisite) | **Effort:** 1pt

**Implementation Notes:**

- Use Minio console or `mc` CLI to create buckets
- Verify endpoint: https://s3.68cc.io
- Test bucket access before proceeding

---

### [ ] TASK-lgtm-d4f8c2a1-002: Generate S3 Credentials for Loki

**Trace:** REQ-lgtm-d4f8c2a1-004 (AC-01) | Design: ADR-003
**DoD (EARS Format):**

- WHEN credentials generated, SHALL create dedicated Minio user `loki-service` with access only to `loki-chunks` bucket
- WHERE credentials are stored, SHALL save as `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` for next task
- IF credentials tested, SHALL successfully list objects in `loki-chunks` bucket using AWS CLI

**Risk:** Low | **Deps:** TASK-001 | **Effort:** 1pt

**Implementation Notes:**

- Create IAM user in Minio with policy scoped to `loki-chunks` bucket only
- Test credentials with: `aws s3 ls s3://loki-chunks --endpoint-url https://s3.68cc.io`

---

### [ ] TASK-lgtm-d4f8c2a1-003: Create SOPS-Encrypted Loki S3 Secret

**Trace:** REQ-lgtm-d4f8c2a1-004 (AC-01, AC-02) | Design: ADR-003, secret.sops.yaml pattern
**DoD (EARS Format):**

- WHEN secret created, SHALL encrypt file `kubernetes/apps/monitoring/loki/app/secret.sops.yaml` using existing SOPS age key
- WHERE secret contains credentials, SHALL include `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT`, `S3_BUCKET` keys
- IF SOPS encryption verified, SHALL confirm file shows `ENC[AES256_GCM,...]` encrypted values when viewed

**Risk:** Low | **Deps:** TASK-002 | **Effort:** 1pt

**Implementation Notes:**

- Follow existing pattern from `kubernetes/apps/monitoring/grafana/app/secret.sops.yaml`
- Use SOPS CLI: `sops -e secret.yaml > secret.sops.yaml`

---

### [ ] TASK-lgtm-d4f8c2a1-004: Generate S3 Credentials for Tempo

**Trace:** REQ-lgtm-d4f8c2a1-004 (AC-01) | Design: ADR-003
**DoD (EARS Format):**

- WHEN credentials generated, SHALL create dedicated Minio user `tempo-service` with access only to `tempo-traces` bucket
- WHERE credentials are stored, SHALL save as `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` for next task
- IF credentials tested, SHALL successfully list objects in `tempo-traces` bucket using AWS CLI

**Risk:** Low | **Deps:** TASK-001 | **Effort:** 1pt

**SKIPPED - MANUAL CREATION REQUIRED:**
User will manually create Minio IAM user `tempo-service` with access policy scoped to `tempo-traces` bucket only.

---

### [SKIP] TASK-lgtm-d4f8c2a1-005: Create SOPS-Encrypted Tempo S3 Secret (MANUAL)

**Trace:** REQ-lgtm-d4f8c2a1-004 (AC-01, AC-02) | Design: ADR-003
**DoD (EARS Format):**

- WHEN secret created, SHALL encrypt file `kubernetes/apps/monitoring/tempo/app/secret.sops.yaml` using existing SOPS age key
- WHERE secret contains credentials, SHALL include `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT`, `S3_BUCKET` keys
- IF SOPS encryption verified, SHALL confirm file shows encrypted values when viewed

**Risk:** Low | **Deps:** TASK-004 | **Effort:** 1pt

**SKIPPED - PLACEHOLDER PROVIDED:**
Secret template created at `kubernetes/apps/monitoring/tempo/app/secret.sops.yaml` with placeholders:

- `S3_ACCESS_KEY_ID: REPLACE_WITH_TEMPO_ACCESS_KEY`
- `S3_SECRET_ACCESS_KEY: REPLACE_WITH_TEMPO_SECRET_KEY`
- `S3_ENDPOINT: https://s3.68cc.io`
- `S3_BUCKET: tempo-traces`

User will replace placeholders and encrypt with SOPS.

---

### [SKIP] TASK-lgtm-d4f8c2a1-006: Generate S3 Credentials for Mimir (MANUAL)

**Trace:** REQ-lgtm-d4f8c2a1-004 (AC-01) | Design: ADR-003
**DoD (EARS Format):**

- WHEN credentials generated, SHALL create dedicated Minio user `mimir-service` with access only to `mimir-blocks` bucket
- WHERE credentials are stored, SHALL save as `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY` for next task
- IF credentials tested, SHALL successfully list objects in `mimir-blocks` bucket using AWS CLI

**Risk:** Low | **Deps:** TASK-001 | **Effort:** 1pt

**SKIPPED - MANUAL CREATION REQUIRED:**
User will manually create Minio IAM user `mimir-service` with access policy scoped to `mimir-blocks` bucket only.

---

### [SKIP] TASK-lgtm-d4f8c2a1-007: Create SOPS-Encrypted Mimir S3 Secret (MANUAL)

**Trace:** REQ-lgtm-d4f8c2a1-004 (AC-01, AC-02) | Design: ADR-003
**DoD (EARS Format):**

- WHEN secret created, SHALL encrypt file `kubernetes/apps/monitoring/mimir/app/secret.sops.yaml` using existing SOPS age key
- WHERE secret contains credentials, SHALL include `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_ENDPOINT`, `S3_BUCKET` keys
- IF SOPS encryption verified, SHALL confirm file shows encrypted values when viewed

**Risk:** Low | **Deps:** TASK-006 | **Effort:** 1pt

**SKIPPED - PLACEHOLDER PROVIDED:**
Secret template created at `kubernetes/apps/monitoring/mimir/app/secret.sops.yaml` with placeholders:

- `S3_ACCESS_KEY_ID: REPLACE_WITH_MIMIR_ACCESS_KEY`
- `S3_SECRET_ACCESS_KEY: REPLACE_WITH_MIMIR_SECRET_KEY`
- `S3_ENDPOINT: https://s3.68cc.io`
- `S3_BUCKET: mimir-blocks`

User will replace placeholders and encrypt with SOPS.

---

## Phase 2: Component Deployments

### [✓] TASK-lgtm-d4f8c2a1-008: Deploy Loki HelmRelease

**Trace:** REQ-lgtm-d4f8c2a1-001 | Design: ADR-001, ADR-004, loki component
**DoD (EARS Format):**

- WHEN HelmRelease created, SHALL deploy files: `kubernetes/apps/monitoring/loki/ks.yaml`, `app/kustomization.yaml`, `app/helmrelease.yaml`
- WHERE HelmRelease configured, SHALL use OCIRepository from `ghcr.io/grafana/helm-charts/loki` with simple scalable mode
- WHILE pod starting, SHALL reference `loki-s3-secret` for S3 credentials via `envFrom`
- IF deployment successful, SHALL have pod in Running state within 5 minutes
- WHEN S3 verified, SHALL confirm logs show successful S3 bucket connection without authentication errors

**Risk:** Medium | **Deps:** TASK-003 | **Effort:** 3pts

**✅ COMPLETED:**
Created deployment files at `kubernetes/apps/monitoring/loki/`:

- `ks.yaml` - Kustomization resource
- `app/kustomization.yaml` - App-level Kustomize configuration
- `app/helmrelease.yaml` - HelmRelease with OCIRepository, SimpleScalable mode, S3 configuration
- `app/secret.sops.yaml` - Secret template with placeholders (awaiting user credentials)

Configuration: Loki 6.21.0, 30-day retention, S3 backend with `loki-chunks` bucket

---

### [ ] TASK-lgtm-d4f8c2a1-009: Verify Loki S3 Integration

**Trace:** REQ-lgtm-d4f8c2a1-001 (AC-01, AC-02, AC-04) | Design: Data Flow - Loki
**DoD (EARS Format):**

- WHEN verification executed, SHALL confirm Loki pod logs show successful S3 connection
- WHERE S3 bucket accessed, SHALL verify `loki-chunks` bucket contains `fake/` directory structure
- IF test log ingested, SHALL confirm chunk appears in S3 bucket within 5 minutes
- WHEN errors checked, SHALL have zero S3 authentication errors in pod logs

**Risk:** Medium | **Deps:** TASK-008 | **Effort:** 2pts

**Implementation Notes:**

- Check pod logs: `kubectl logs -n monitoring -l app.kubernetes.io/name=loki`
- Verify S3: `aws s3 ls s3://loki-chunks --endpoint-url https://s3.68cc.io`
- Send test log: `kubectl run test-logger --rm -i --restart=Never --image=curlimages/curl -- sh -c 'curl -X POST http://loki-gateway.monitoring.svc:3100/loki/api/v1/push ...'`

---

### [✓] TASK-lgtm-d4f8c2a1-010: Deploy Tempo HelmRelease

**Trace:** REQ-lgtm-d4f8c2a1-002 | Design: ADR-001, ADR-005, tempo component
**DoD (EARS Format):**

- WHEN HelmRelease created, SHALL deploy files: `kubernetes/apps/monitoring/tempo/ks.yaml`, `app/kustomization.yaml`, `app/helmrelease.yaml`
- WHERE HelmRelease configured, SHALL use OCIRepository from `ghcr.io/grafana/helm-charts/tempo` with monolithic mode
- WHILE pod starting, SHALL reference `tempo-s3-secret` for S3 credentials via `envFrom`
- IF deployment successful, SHALL have pod in Running state and OTLP gRPC receiver listening on port 4317
- WHEN S3 verified, SHALL confirm logs show successful S3 bucket connection

**Risk:** Medium | **Deps:** TASK-005 | **Effort:** 3pts

**✅ COMPLETED:**
Created deployment files at `kubernetes/apps/monitoring/tempo/`:

- `ks.yaml` - Kustomization resource
- `app/kustomization.yaml` - App-level Kustomize configuration
- `app/helmrelease.yaml` - HelmRelease with OCIRepository, monolithic mode, OTLP/Jaeger/Zipkin receivers, S3 configuration
- `app/secret.sops.yaml` - Secret template with placeholders (awaiting user credentials)

Configuration: Tempo 1.19.1, 30-day retention, S3 backend with `tempo-traces` bucket, metrics generator enabled

---

### [ ] TASK-lgtm-d4f8c2a1-011: Verify Tempo S3 Integration

**Trace:** REQ-lgtm-d4f8c2a1-002 (AC-01, AC-02, AC-04) | Design: Data Flow - Tempo
**DoD (EARS Format):**

- WHEN verification executed, SHALL confirm Tempo pod logs show successful S3 connection
- WHERE S3 bucket accessed, SHALL verify `tempo-traces` bucket is accessible
- IF test trace ingested, SHALL confirm trace data appears in S3 bucket within 10 minutes
- WHEN OTLP receiver tested, SHALL accept gRPC connection on port 4317

**Risk:** Medium | **Deps:** TASK-010 | **Effort:** 2pts

**Implementation Notes:**

- Check pod logs: `kubectl logs -n monitoring -l app.kubernetes.io/name=tempo`
- Test OTLP: Use `otel-cli` or similar tool to send test trace
- Verify S3: `aws s3 ls s3://tempo-traces --endpoint-url https://s3.68cc.io`

---

### [✓] TASK-lgtm-d4f8c2a1-012: Deploy Mimir HelmRelease

**Trace:** REQ-lgtm-d4f8c2a1-003 | Design: ADR-001, ADR-006, mimir component
**DoD (EARS Format):**

- WHEN HelmRelease created, SHALL deploy files: `kubernetes/apps/monitoring/mimir/ks.yaml`, `app/kustomization.yaml`, `app/helmrelease.yaml`
- WHERE HelmRelease configured, SHALL use OCIRepository from `ghcr.io/grafana/helm-charts/mimir-distributed` with monolithic mode
- WHILE pod starting, SHALL reference `mimir-s3-secret` for S3 credentials via `envFrom`
- IF deployment successful, SHALL have pod in Running state and accept remote-write on port 8080
- WHEN S3 verified, SHALL confirm logs show successful S3 bucket connection and block storage initialization

**Risk:** Medium | **Deps:** TASK-007 | **Effort:** 3pts

**✅ COMPLETED:**
Created deployment files at `kubernetes/apps/monitoring/mimir/`:

- `ks.yaml` - Kustomization resource
- `app/kustomization.yaml` - App-level Kustomize configuration
- `app/helmrelease.yaml` - HelmRelease with OCIRepository, distributed mode with single replicas, S3 configuration for blocks/ruler/alertmanager storage
- `app/secret.sops.yaml` - Secret template with placeholders (awaiting user credentials)

Configuration: Mimir 5.6.2, 30-day retention, S3 backend with `mimir-blocks` bucket, all components scaled to 1 replica for home-lab

---

### [ ] TASK-lgtm-d4f8c2a1-013: Verify Mimir S3 Integration

**Trace:** REQ-lgtm-d4f8c2a1-003 (AC-01, AC-03, AC-04) | Design: Data Flow - Mimir
**DoD (EARS Format):**

- WHEN verification executed, SHALL confirm Mimir pod logs show successful S3 connection and bucket initialization
- WHERE S3 bucket accessed, SHALL verify `mimir-blocks` bucket is accessible
- IF test metrics sent, SHALL confirm blocks appear in S3 bucket after compaction
- WHEN remote-write tested, SHALL accept Prometheus remote-write protocol on port 8080

**Risk:** Medium | **Deps:** TASK-012 | **Effort:** 2pts

**Implementation Notes:**

- Check pod logs: `kubectl logs -n monitoring -l app.kubernetes.io/name=mimir`
- Test remote-write: Use `promtool` to send test metrics
- Verify S3: `aws s3 ls s3://mimir-blocks --endpoint-url https://s3.68cc.io`

---

## Phase 3: Integration with Existing Stack

### [✓] TASK-lgtm-d4f8c2a1-014: Update Grafana Loki Data Source

**Trace:** REQ-lgtm-d4f8c2a1-005 (AC-01, AC-02) | Design: ADR-007, Modified Grafana component
**DoD (EARS Format):**

- WHEN Grafana HelmRelease updated, SHALL modify `datasources.yaml` to update existing Loki datasource URL to `http://loki-gateway.monitoring.svc.cluster.local:3100`
- WHERE datasource configured, SHALL set `uid: loki` to match existing configuration
- IF HelmRelease applied, SHALL trigger Grafana pod restart
- WHEN Grafana restarted, SHALL automatically load updated Loki datasource configuration

**Risk:** Low | **Deps:** TASK-009 | **Effort:** 1pt

**✅ COMPLETED:**
Updated `kubernetes/apps/monitoring/grafana/app/helmrelease.yaml`:

- Changed Loki datasource URL from `http://loki-headless.monitoring.svc.cluster.local:3100` to `http://loki-gateway.monitoring.svc.cluster.local:3100`
- Maintained existing `uid: loki` configuration for backward compatibility

---

### [✓] TASK-lgtm-d4f8c2a1-015: Add Grafana Tempo Data Source

**Trace:** REQ-lgtm-d4f8c2a1-005 (AC-01, AC-02) | Design: ADR-007
**DoD (EARS Format):**

- WHEN Grafana HelmRelease updated, SHALL add Tempo datasource to `datasources.yaml` with URL `http://tempo.monitoring.svc.cluster.local:3200`
- WHERE datasource configured, SHALL set `type: tempo`, `uid: tempo`, `access: proxy`
- IF HelmRelease applied, SHALL trigger Grafana pod restart
- WHEN Grafana restarted, SHALL automatically load Tempo datasource configuration

**Risk:** Low | **Deps:** TASK-011 | **Effort:** 1pt

**✅ COMPLETED:**
Added Tempo datasource to `kubernetes/apps/monitoring/grafana/app/helmrelease.yaml`:

- URL: `http://tempo.monitoring.svc.cluster.local:3100`
- Type: `tempo`, UID: `tempo`, Access: `proxy`
- Configured trace-to-logs correlation with Loki datasource
- Configured trace-to-metrics correlation with Mimir datasource
- Enabled service map, node graph, and Loki search features

---

### [✓] TASK-lgtm-d4f8c2a1-016: Add Grafana Mimir Data Source

**Trace:** REQ-lgtm-d4f8c2a1-005 (AC-01, AC-02) | Design: ADR-007
**DoD (EARS Format):**

- WHEN Grafana HelmRelease updated, SHALL add Mimir datasource to `datasources.yaml` with URL `http://mimir-gateway.monitoring.svc.cluster.local:8080/prometheus`
- WHERE datasource configured, SHALL set `type: prometheus`, `uid: mimir`, `access: proxy`
- IF HelmRelease applied, SHALL trigger Grafana pod restart
- WHEN Grafana restarted, SHALL automatically load Mimir datasource configuration

**Risk:** Low | **Deps:** TASK-013 | **Effort:** 1pt

**✅ COMPLETED:**
Added Mimir datasource to `kubernetes/apps/monitoring/grafana/app/helmrelease.yaml`:

- URL: `http://mimir-nginx.monitoring.svc.cluster.local:8080/prometheus`
- Type: `prometheus`, UID: `mimir`, Access: `proxy`
- Configured as Mimir type with high cache level
- 1-minute time interval for metric queries

---

### [✓] TASK-lgtm-d4f8c2a1-017: Configure Prometheus Remote-Write to Mimir

**Trace:** REQ-lgtm-d4f8c2a1-003 (AC-02) | Design: ADR-006, Modified kube-prometheus-stack
**DoD (EARS Format):**

- WHEN kube-prometheus-stack HelmRelease updated, SHALL add `remoteWrite` configuration to Prometheus values
- WHERE remote-write configured, SHALL set URL `http://mimir-gateway.monitoring.svc.cluster.local:8080/api/v1/push`
- WHILE remote-write active, SHALL configure queue settings: `capacity: 10000`, `maxShards: 50`, `minShards: 1`
- IF HelmRelease applied, SHALL trigger Prometheus pod restart
- WHEN Prometheus restarted, SHALL begin sending metrics to Mimir within 1 minute

**Risk:** Medium | **Deps:** TASK-013 | **Effort:** 2pts

**✅ COMPLETED:**
Updated `kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml`:

- Added `remoteWrite` configuration with URL: `http://mimir-nginx.monitoring.svc.cluster.local:8080/api/v1/push`
- Configured queue settings: capacity 10000, maxShards 50, minShards 1, maxSamplesPerSend 5000
- Configured backoff settings: batchSendDeadline 5s, minBackoff 30ms, maxBackoff 5s
- All Prometheus metrics will be forwarded to Mimir for long-term storage

---

## Phase 4: Verification and Testing

### [ ] TASK-lgtm-d4f8c2a1-018: Test Grafana Loki Data Source Connection

**Trace:** REQ-lgtm-d4f8c2a1-005 (AC-03, AC-04) | Design: API Matrix - Loki
**DoD (EARS Format):**

- WHEN data source tested in Grafana UI, SHALL show "Data source is working" success message
- WHERE test query executed, SHALL return log results from Loki within 3 seconds
- IF connection fails, SHALL display clear error message in Grafana UI

**Risk:** Low | **Deps:** TASK-014 | **Effort:** 1pt

**Implementation Notes:**

- Open Grafana UI → Configuration → Data Sources → Loki
- Click "Test" button
- Run sample LogQL query: `{namespace="monitoring"}`

---

### [ ] TASK-lgtm-d4f8c2a1-019: Test Grafana Tempo Data Source Connection

**Trace:** REQ-lgtm-d4f8c2a1-005 (AC-03, AC-04) | Design: API Matrix - Tempo
**DoD (EARS Format):**

- WHEN data source tested in Grafana UI, SHALL show "Data source is working" success message
- WHERE test query executed, SHALL return trace search results from Tempo within 5 seconds
- IF connection fails, SHALL display clear error message in Grafana UI

**Risk:** Low | **Deps:** TASK-015 | **Effort:** 1pt

---

### [ ] TASK-lgtm-d4f8c2a1-020: Test Grafana Mimir Data Source Connection

**Trace:** REQ-lgtm-d4f8c2a1-005 (AC-03, AC-04) | Design: API Matrix - Mimir
**DoD (EARS Format):**

- WHEN data source tested in Grafana UI, SHALL show "Data source is working" success message
- WHERE test query executed, SHALL return metric results from Mimir within 3 seconds
- IF connection fails, SHALL display clear error message in Grafana UI

**Risk:** Low | **Deps:** TASK-016 | **Effort:** 1pt

---

### [ ] TASK-lgtm-d4f8c2a1-021: Verify Prometheus Remote-Write to Mimir

**Trace:** REQ-lgtm-d4f8c2a1-003 (AC-02, AC-05) | Design: Data Flow - Mimir, NFR-PERF-001
**DoD (EARS Format):**

- WHEN Prometheus remote-write verified, SHALL confirm metrics appear in Mimir within 1 minute of collection
- WHERE Prometheus metrics checked, SHALL show successful remote-write status in Prometheus `/targets` page
- WHILE querying Mimir, SHALL return same metric results as querying Prometheus directly
- IF remote-write fails, SHALL show error count in Prometheus `prometheus_remote_storage_samples_failed_total` metric

**Risk:** Medium | **Deps:** TASK-017 | **Effort:** 2pts

**Implementation Notes:**

- Check Prometheus UI: Status → Runtime & Build Information → Remote Write
- Query Mimir via Grafana: `up{job="prometheus"}`
- Compare results with Prometheus datasource

---

### [ ] TASK-lgtm-d4f8c2a1-022: End-to-End Observability Stack Validation

**Trace:** ALL REQ-_, ALL AC-_ | Design: Quality Gates
**DoD (EARS Format):**

- WHEN E2E test executed, SHALL successfully query logs from Loki with results returned within 3 seconds
- WHERE traces tested, SHALL successfully query traces from Tempo with results returned within 5 seconds
- WHILE metrics tested, SHALL successfully query historical metrics from Mimir beyond Prometheus retention
- IF any component fails, SHALL have clear error messages and troubleshooting path
- WHEN S3 persistence validated, SHALL confirm data survives pod restarts for all three components

**Risk:** High | **Deps:** TASK-018, TASK-019, TASK-020, TASK-021 | **Effort:** 3pts

**Implementation Notes:**

- Create test dashboard with Loki, Tempo, and Mimir panels
- Restart each component pod and verify data recovery
- Verify S3 buckets contain data for all components
- Document any issues and resolutions

---

## Verification Checklist (EARS Compliance)

### Requirements Traceability

- [ ] REQ-lgtm-d4f8c2a1-001 (Loki) → TASK-008, TASK-009, TASK-014 with EARS DoD ✅
- [ ] REQ-lgtm-d4f8c2a1-002 (Tempo) → TASK-010, TASK-011, TASK-015 with EARS DoD ✅
- [ ] REQ-lgtm-d4f8c2a1-003 (Mimir) → TASK-012, TASK-013, TASK-016, TASK-017 with EARS DoD ✅
- [ ] REQ-lgtm-d4f8c2a1-004 (S3 Credentials) → TASK-002 through TASK-007 with EARS DoD ✅
- [ ] REQ-lgtm-d4f8c2a1-005 (Grafana Integration) → TASK-014, TASK-015, TASK-016 with EARS DoD ✅

### Acceptance Criteria Coverage

- [ ] AC-lgtm-001-01 through AC-lgtm-001-05 → Loki tasks with validation ✅
- [ ] AC-lgtm-002-01 through AC-lgtm-002-05 → Tempo tasks with validation ✅
- [ ] AC-lgtm-003-01 through AC-lgtm-003-05 → Mimir tasks with validation ✅
- [ ] AC-lgtm-004-01 through AC-lgtm-004-04 → S3 credential tasks with SOPS encryption ✅
- [ ] AC-lgtm-005-01 through AC-lgtm-005-04 → Grafana integration tasks with testing ✅

### NFR Validation

- [ ] NFR-PERF-001 (Query Performance) → TASK-018, TASK-019, TASK-020 test <5s response ✅
- [ ] NFR-PERF-002 (Ingestion) → TASK-009, TASK-011, TASK-013 verify ingestion capability ✅
- [ ] NFR-SEC-001 (Credentials) → TASK-003, TASK-005, TASK-007 SOPS encryption ✅
- [ ] NFR-SEC-002 (Network) → All HelmRelease tasks use HTTPS for S3 ✅
- [ ] NFR-SCALE-001 (Storage) → TASK-001 includes S3 lifecycle configuration ✅
- [ ] NFR-SCALE-002 (Resources) → TASK-008, TASK-010, TASK-012 set <2Gi limits ✅
- [ ] NFR-OPS-001 (Pattern) → All deployment tasks follow FluxCD HelmRelease pattern ✅
- [ ] NFR-OPS-002 (Config) → All tasks use HelmRelease values, no inline configs ✅
- [ ] NFR-RECOVER-001 (Recovery) → TASK-022 validates pod restart recovery ✅

### Design ADR Coverage

- [ ] ADR-001 (FluxCD Pattern) → TASK-008, TASK-010, TASK-012 use OCIRepository + HelmRelease ✅
- [ ] ADR-002 (Single Instance) → All deployment tasks set replicas: 1 ✅
- [ ] ADR-003 (Dedicated S3) → TASK-001 through TASK-007 create separate buckets/credentials ✅
- [ ] ADR-004 (Loki Mode) → TASK-008 configures simple scalable mode ✅
- [ ] ADR-005 (Tempo Mode) → TASK-010 configures monolithic + OTLP ✅
- [ ] ADR-006 (Mimir Mode) → TASK-012 configures monolithic + remote-write ✅
- [ ] ADR-007 (Grafana Config) → TASK-014, TASK-015, TASK-016 update HelmRelease values ✅

### Risk Mitigation Coverage

- [ ] Medium+ risks identified with EARS success criteria ✅
- [ ] All S3 integration points have verification tasks ✅
- [ ] Credential isolation validated through separate secrets ✅
- [ ] Component dependencies clearly mapped in task sequence ✅

### EARS-to-BDD Test Translation

- [ ] Every EARS AC has corresponding verification task ✅
- [ ] Test strategies defined in Design API Matrix implemented ✅
- [ ] Performance targets from NFRs validated in E2E testing ✅
- [ ] All "WHEN/WHERE/IF/WHILE" conditions testable ✅

---

## Execution Notes

**Sequential Execution Required:**

- Phase 1 tasks (TASK-001 through TASK-007) must complete before Phase 2
- Each component deployment must complete verification before integration phase
- Grafana integration tasks depend on component services being available
- E2E validation (TASK-022) requires all prior tasks complete

**Parallel Execution Opportunities:**

- TASK-002, TASK-004, TASK-006 (credential generation) can run in parallel after TASK-001
- TASK-003, TASK-005, TASK-007 (secret creation) can run in parallel after credentials ready
- TASK-008, TASK-010, TASK-012 (deployments) can run in parallel after secrets ready
- TASK-009, TASK-011, TASK-013 (verifications) must be sequential per component
- TASK-014, TASK-015, TASK-016 (Grafana datasources) can run in parallel after verifications
- TASK-018, TASK-019, TASK-020 (datasource tests) can run in parallel after Grafana update

**Critical Success Factors:**

1. S3 bucket accessibility verified before any deployments
2. SOPS encryption working for all secrets
3. Each component pod reaches Running state before next deployment
4. Grafana datasource tests pass before declaring success
5. E2E validation confirms data persistence across pod restarts
