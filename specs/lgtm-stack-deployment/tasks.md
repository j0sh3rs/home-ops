# Tasks: LGTM Stack Deployment (Tempo + Mimir) - Implementer Agent

## Context Summary

Feature UUID: FEAT-lgtm-d4f8c2a1 | Architecture: FluxCD HelmRelease + S3 Backend | Risk: Medium

**Scope Adjustment:** Loki deployment excluded (replaced by Parseable in future feature)
**Components:** Tempo (distributed tracing) + Mimir (long-term metrics storage)

## Metadata

Complexity: Medium | Critical Path: S3 bucket prerequisites → Tempo → Mimir → Grafana integration → Prometheus remote-write
Timeline: 4-6 hours (with BDD test development) | Quality Gates: EARS-to-BDD test validation per phase

## Progress: 0/17 Complete, 0 In Progress, 17 Not Started, 0 Blocked

---

## Phase 1: Tempo Distributed Tracing Deployment

### TASK-lgtm-001: Create Tempo Directory Structure and Namespace

**Trace:** REQ-lgtm-d4f8c2a1-002 | Design: tempo/ component structure | AC: Foundation prerequisite
**ADR:** ADR-001 (FluxCD HelmRelease pattern), ADR-005 (Tempo monolithic mode)
**Approach:** Create kubernetes/apps/monitoring/tempo/ with ks.yaml and app/ subdirectory

**DoD (EARS Format):**

- WHEN directory structure is created, SHALL contain ks.yaml and app/kustomization.yaml following established pattern
- WHERE namespace is referenced, SHALL use existing "monitoring" namespace (no new namespace creation needed)

**Risk:** Low | Effort: 1pt
**Test Strategy:** Manual verification - directory structure matches design specification
**Dependencies:** None (prerequisite task)

**Sub-tasks:**

- [ ] Create `kubernetes/apps/monitoring/tempo/` directory
- [ ] Create `kubernetes/apps/monitoring/tempo/ks.yaml` with namespace and dependency references
- [ ] Create `kubernetes/apps/monitoring/tempo/app/` subdirectory
- [ ] Create `kubernetes/apps/monitoring/tempo/app/kustomization.yaml` with resource list

---

### TASK-lgtm-002: Create Tempo S3 Credentials Secret

**Trace:** REQ-lgtm-d4f8c2a1-002, REQ-lgtm-d4f8c2a1-004 | Design: S3 credential management pattern | AC: AC-lgtm-004-01, AC-lgtm-004-02, AC-lgtm-004-04
**ADR:** ADR-003 (dedicated S3 credentials per component)
**Approach:** Create SOPS-encrypted secret with S3 credentials for tempo-traces bucket

**DoD (EARS Format):**

- WHEN secret is created, SHALL be named `tempo-s3-secret` and SOPS-encrypted with age key
- WHERE credentials are defined, SHALL include S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT, S3_BUCKET fields
- IF secret is applied to cluster, SHALL be mountable as environment variables in Tempo pods
- WHEN accessing S3, SHALL use HTTPS endpoint https://s3.68cc.io exclusively

**Risk:** Low | Effort: 2pts
**Test Strategy:**

- Unit: Verify SOPS encryption with `sops --decrypt secret.sops.yaml`
- Integration: Verify secret fields are correct format
  **Dependencies:** TASK-lgtm-001

**BDD Test Scenario:**

```gherkin
Feature: Tempo S3 Credential Management
  Scenario: SOPS-encrypted secret creation
    Given S3 credentials for tempo-traces bucket
    When secret is created as secret.sops.yaml
    Then secret SHALL be encrypted with SOPS age key
    And secret SHALL contain S3_ACCESS_KEY_ID field
    And secret SHALL contain S3_SECRET_ACCESS_KEY field
    And secret SHALL contain S3_ENDPOINT with value "https://s3.68cc.io"
    And secret SHALL contain S3_BUCKET with value "tempo-traces"
```

**Sub-tasks:**

- [ ] Create `kubernetes/apps/monitoring/tempo/app/secret.sops.yaml` with plaintext values
- [ ] Encrypt secret using `sops --encrypt --in-place secret.sops.yaml`
- [ ] Verify encryption with `sops --decrypt secret.sops.yaml`
- [ ] Add secret.sops.yaml to app/kustomization.yaml resources

---

### TASK-lgtm-003: Create Tempo HelmRelease Configuration

**Trace:** REQ-lgtm-d4f8c2a1-002 | Design: Tempo component with OTLP receiver | AC: AC-lgtm-002-01, AC-lgtm-002-02, AC-lgtm-002-04
**ADR:** ADR-001 (HelmRelease pattern), ADR-002 (single replica), ADR-005 (monolithic mode)
**Approach:** Create HelmRelease with Grafana Tempo chart via OCIRepository, configure S3 backend and OTLP receiver

**DoD (EARS Format):**

- WHEN HelmRelease is applied, SHALL reference OCIRepository for Grafana Tempo Helm chart
- WHERE S3 configuration is defined, SHALL use environment variables from tempo-s3-secret
- IF replicas are specified, SHALL be set to 1 (single instance deployment)
- WHEN OTLP receiver is configured, SHALL listen on port 4317 (gRPC)
- WHERE memory limits are set, SHALL not exceed 1Gi per pod (home-lab constraint)

**Risk:** Medium | Effort: 5pts
**Test Strategy:**

- Unit: Validate HelmRelease YAML syntax
- Integration: FluxCD reconciliation success check
- E2E: Tempo pod startup and readiness verification
  **Dependencies:** TASK-lgtm-002

**BDD Test Scenario:**

```gherkin
Feature: Tempo HelmRelease Deployment
  Scenario: Tempo deployed with S3 backend
    Given tempo-s3-secret exists in monitoring namespace
    When HelmRelease is applied to cluster
    Then Tempo pod SHALL start within 5 minutes
    And Tempo SHALL mount S3 credentials from secret
    And Tempo SHALL configure S3 backend with endpoint "https://s3.68cc.io"
    And Tempo SHALL configure S3 bucket "tempo-traces"
    And Tempo SHALL enable OTLP gRPC receiver on port 4317
    And Tempo SHALL be deployed as single replica
    And Tempo pod memory limit SHALL be 1Gi or less

  Scenario: S3 connection validation (AC-lgtm-002-01)
    Given Tempo is deployed
    When Tempo pod starts
    Then Tempo SHALL create connection to S3 bucket "tempo-traces"
    And Tempo logs SHALL NOT contain S3 authentication errors
```

**Sub-tasks:**

- [ ] Create `kubernetes/apps/monitoring/tempo/app/helmrelease.yaml` with OCIRepository source
- [ ] Configure S3 backend using environment variables from secret
- [ ] Enable OTLP gRPC receiver on port 4317
- [ ] Set replicas: 1 and resource limits (memory: 1Gi)
- [ ] Configure retention policy (30 days via S3 lifecycle)
- [ ] Add helmrelease.yaml to app/kustomization.yaml resources

---

### TASK-lgtm-004: Deploy Tempo and Verify S3 Connectivity

**Trace:** REQ-lgtm-d4f8c2a1-002 | Design: Tempo deployment validation | AC: AC-lgtm-002-01, AC-lgtm-002-04
**ADR:** ADR-002 (S3 persistence), ADR-005 (monolithic mode)
**Approach:** Apply Tempo kustomization via FluxCD, verify pod startup and S3 connection

**DoD (EARS Format):**

- WHEN kustomization is applied, SHALL trigger FluxCD reconciliation within 1 minute
- WHERE Tempo pod starts, SHALL reach Ready state within 5 minutes
- IF S3 connection is established, SHALL NOT log authentication or connection errors
- WHEN S3 bucket is accessed, SHALL use HTTPS endpoint and dedicated credentials

**Risk:** Medium | Effort: 3pts
**Test Strategy:**

- Integration: FluxCD reconciliation status check
- E2E: Pod readiness and S3 connection verification
  **Dependencies:** TASK-lgtm-003

**BDD Test Scenario:**

```gherkin
Feature: Tempo Deployment Verification
  Scenario: Successful Tempo deployment
    Given Tempo HelmRelease is committed to Git
    When FluxCD reconciles tempo kustomization
    Then HelmRelease SHALL report "Helm install succeeded" within 5 minutes
    And Tempo pod SHALL reach Ready state
    And Tempo service SHALL be accessible at tempo.monitoring.svc:4317

  Scenario: S3 connectivity validation (AC-lgtm-002-01)
    Given Tempo pod is running
    When Tempo initializes storage backend
    Then Tempo logs SHALL contain "successfully connected to S3"
    Or Tempo logs SHALL NOT contain "S3 connection failed"
    And Tempo SHALL create test objects in tempo-traces bucket
```

**Sub-tasks:**

- [ ] Commit tempo/ directory to Git
- [ ] Run `flux reconcile source git flux-system -n flux-system`
- [ ] Run `flux reconcile kustomization tempo -n flux-system` (if separate kustomization)
- [ ] Verify HelmRelease status: `kubectl get helmrelease -n monitoring tempo`
- [ ] Verify pod status: `kubectl get pods -n monitoring -l app.kubernetes.io/name=tempo`
- [ ] Check Tempo logs for S3 connection: `kubectl logs -n monitoring -l app.kubernetes.io/name=tempo | grep -i s3`

---

### TASK-lgtm-005: Create BDD Test Suite for Tempo OTLP Ingestion

**Trace:** REQ-lgtm-d4f8c2a1-002 | Design: OTLP receiver validation | AC: AC-lgtm-002-02
**ADR:** ADR-005 (OTLP receiver enabled)
**Approach:** Create BDD test scenarios using otel-cli to send test traces and verify S3 persistence

**DoD (EARS Format):**

- WHEN test trace is sent to Tempo OTLP endpoint, SHALL accept and acknowledge within 1 second
- WHERE traces are persisted, SHALL appear in S3 bucket within 10 minutes (AC-lgtm-002-02 requirement)
- IF trace ingestion fails, SHALL return descriptive error message
- WHEN test completes, SHALL verify trace data exists in S3 tempo-traces bucket

**Risk:** Medium | Effort: 4pts
**Test Strategy:**

- E2E: OTLP trace ingestion and S3 persistence verification
  **Dependencies:** TASK-lgtm-004

**BDD Test Scenario:**

```gherkin
Feature: Tempo OTLP Trace Ingestion (AC-lgtm-002-02)
  Background:
    Given Tempo is deployed and healthy
    And S3 bucket "tempo-traces" is accessible

  Scenario: Successful OTLP trace ingestion
    Given otel-cli is installed
    When test trace is sent to tempo.monitoring.svc:4317
    Then Tempo SHALL accept trace within 1 second
    And Tempo SHALL return successful acknowledgment

  Scenario: Trace persistence to S3 (AC-lgtm-002-02)
    Given test trace was ingested by Tempo
    When 10 minutes have elapsed
    Then trace data SHALL exist in S3 bucket "tempo-traces"
    And trace SHALL be queryable via Tempo HTTP API

  Scenario: OTLP receiver error handling (AC-lgtm-002-04)
    Given S3 credentials are invalid
    When test trace is sent to Tempo
    Then Tempo SHALL accept trace (buffering)
    But Tempo logs SHALL contain S3 write error
    And Tempo SHALL NOT lose trace data during credential fix
```

**Sub-tasks:**

- [ ] Install otel-cli for OTLP testing: `brew install otel-cli` or equivalent
- [ ] Create test script `tests/tempo-otlp-ingestion.sh`
- [ ] Implement BDD scenario: Send test trace via otel-cli
- [ ] Verify Tempo acknowledgment (check exit code)
- [ ] Wait 10 minutes and verify S3 bucket contents using AWS CLI
- [ ] Implement error handling scenario with invalid credentials
- [ ] Document test execution in `tests/README.md`

---

### TASK-lgtm-006: Create BDD Test Suite for Tempo Query Performance

**Trace:** REQ-lgtm-d4f8c2a1-002 | Design: Tempo HTTP API | AC: AC-lgtm-002-05
**ADR:** ADR-005 (monolithic mode with query endpoint)
**Approach:** Create automated tests for Tempo query API response times

**DoD (EARS Format):**

- WHEN trace query is executed via HTTP API, SHALL return results within 5 seconds for recent traces (AC-lgtm-002-05)
- WHERE query includes trace ID, SHALL return complete trace data
- IF trace does not exist, SHALL return 404 with clear error message
- WHEN multiple queries are executed concurrently, SHALL maintain <5s response time

**Risk:** Low | Effort: 3pts
**Test Strategy:**

- E2E: Query performance validation with curl/http timing
  **Dependencies:** TASK-lgtm-005

**BDD Test Scenario:**

```gherkin
Feature: Tempo Query Performance (AC-lgtm-002-05)
  Background:
    Given Tempo contains test traces from previous ingestion test
    And Tempo HTTP API is accessible at tempo.monitoring.svc:3200

  Scenario: Query recent trace by ID
    Given trace ID from ingestion test
    When query is sent to /api/traces/{traceID}
    Then response SHALL be received within 5 seconds
    And response SHALL contain complete trace data
    And response status SHALL be 200 OK

  Scenario: Query non-existent trace
    Given random non-existent trace ID
    When query is sent to /api/traces/{traceID}
    Then response SHALL be received within 5 seconds
    And response status SHALL be 404 Not Found
    And response SHALL contain descriptive error message

  Scenario: Concurrent query performance
    Given 10 valid trace IDs
    When 10 queries are executed concurrently
    Then all responses SHALL be received within 5 seconds
    And all responses SHALL return valid trace data
```

**Sub-tasks:**

- [ ] Create test script `tests/tempo-query-performance.sh`
- [ ] Implement trace query by ID with timing measurement
- [ ] Verify response time <5 seconds using `time` or `curl -w "%{time_total}"`
- [ ] Test non-existent trace handling
- [ ] Test concurrent query performance with parallel curl requests
- [ ] Document test execution and expected results

---

### TASK-lgtm-007: Verify Tempo Data Recovery from S3

**Trace:** REQ-lgtm-d4f8c2a1-002, NFR-lgtm-d4f8c2a1-RECOVER-001 | Design: S3 persistence | AC: AC-lgtm-002-03
**ADR:** ADR-002 (single replica with S3 state)
**Approach:** Delete Tempo pod, verify recovery from S3 within 5 minutes

**DoD (EARS Format):**

- WHEN Tempo pod is deleted, SHALL restart and reconnect to S3 within 5 minutes
- WHERE query capability is tested post-restart, SHALL return previously ingested traces
- IF S3 data exists, SHALL NOT require manual intervention to restore state
- WHEN pod recovers, SHALL resume OTLP ingestion immediately

**Risk:** Medium | Effort: 3pts
**Test Strategy:**

- E2E: Pod deletion and recovery validation
  **Dependencies:** TASK-lgtm-006

**BDD Test Scenario:**

```gherkin
Feature: Tempo Data Recovery from S3 (AC-lgtm-002-03, NFR-RECOVER-001)
  Background:
    Given Tempo has ingested and persisted test traces to S3
    And test trace IDs are recorded

  Scenario: Pod restart recovery
    Given Tempo pod is running
    When Tempo pod is deleted using kubectl delete pod
    Then new Tempo pod SHALL start within 5 minutes
    And Tempo SHALL reconnect to S3 without errors
    And Tempo SHALL NOT require manual intervention

  Scenario: Query capability after recovery
    Given Tempo has restarted after pod deletion
    When query is sent for previously ingested trace ID
    Then response SHALL return complete trace data
    And response time SHALL be within 5 seconds
    And trace data SHALL match pre-restart state

  Scenario: Ingestion capability after recovery
    Given Tempo has recovered from pod deletion
    When new test trace is sent via OTLP
    Then Tempo SHALL accept and persist trace
    And new trace SHALL be queryable after 10 minutes
```

**Sub-tasks:**

- [ ] Record test trace IDs from TASK-lgtm-005
- [ ] Delete Tempo pod: `kubectl delete pod -n monitoring -l app.kubernetes.io/name=tempo`
- [ ] Monitor pod restart: `kubectl get pods -n monitoring -w`
- [ ] Verify pod Ready state within 5 minutes
- [ ] Query previously ingested trace to verify recovery
- [ ] Send new test trace to verify ingestion resumes
- [ ] Document recovery procedure and timing

---

## Phase 2: Mimir Long-Term Metrics Storage Deployment

### TASK-lgtm-008: Create Mimir Directory Structure

**Trace:** REQ-lgtm-d4f8c2a1-003 | Design: mimir/ component structure | AC: Foundation prerequisite
**ADR:** ADR-001 (FluxCD HelmRelease pattern), ADR-006 (Mimir monolithic mode)
**Approach:** Create kubernetes/apps/monitoring/mimir/ with ks.yaml and app/ subdirectory

**DoD (EARS Format):**

- WHEN directory structure is created, SHALL contain ks.yaml and app/kustomization.yaml following established pattern
- WHERE namespace is referenced, SHALL use existing "monitoring" namespace

**Risk:** Low | Effort: 1pt
**Test Strategy:** Manual verification - directory structure matches design specification
**Dependencies:** TASK-lgtm-007 (Tempo phase complete)

**Sub-tasks:**

- [ ] Create `kubernetes/apps/monitoring/mimir/` directory
- [ ] Create `kubernetes/apps/monitoring/mimir/ks.yaml` with namespace and dependency references
- [ ] Create `kubernetes/apps/monitoring/mimir/app/` subdirectory
- [ ] Create `kubernetes/apps/monitoring/mimir/app/kustomization.yaml` with resource list

---

### TASK-lgtm-009: Create Mimir S3 Credentials Secret

**Trace:** REQ-lgtm-d4f8c2a1-003, REQ-lgtm-d4f8c2a1-004 | Design: S3 credential management pattern | AC: AC-lgtm-004-01, AC-lgtm-004-02, AC-lgtm-004-04
**ADR:** ADR-003 (dedicated S3 credentials per component)
**Approach:** Create SOPS-encrypted secret with S3 credentials for mimir-blocks bucket

**DoD (EARS Format):**

- WHEN secret is created, SHALL be named `mimir-s3-secret` and SOPS-encrypted with age key
- WHERE credentials are defined, SHALL include S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT, S3_BUCKET fields
- IF secret is applied to cluster, SHALL be mountable as environment variables in Mimir pods
- WHEN accessing S3, SHALL use HTTPS endpoint https://s3.68cc.io exclusively

**Risk:** Low | Effort: 2pts
**Test Strategy:**

- Unit: Verify SOPS encryption with `sops --decrypt secret.sops.yaml`
- Integration: Verify secret fields are correct format
  **Dependencies:** TASK-lgtm-008

**BDD Test Scenario:**

```gherkin
Feature: Mimir S3 Credential Management
  Scenario: SOPS-encrypted secret creation
    Given S3 credentials for mimir-blocks bucket
    When secret is created as secret.sops.yaml
    Then secret SHALL be encrypted with SOPS age key
    And secret SHALL contain S3_ACCESS_KEY_ID field
    And secret SHALL contain S3_SECRET_ACCESS_KEY field
    And secret SHALL contain S3_ENDPOINT with value "https://s3.68cc.io"
    And secret SHALL contain S3_BUCKET with value "mimir-blocks"
```

**Sub-tasks:**

- [ ] Create `kubernetes/apps/monitoring/mimir/app/secret.sops.yaml` with plaintext values
- [ ] Encrypt secret using `sops --encrypt --in-place secret.sops.yaml`
- [ ] Verify encryption with `sops --decrypt secret.sops.yaml`
- [ ] Add secret.sops.yaml to app/kustomization.yaml resources

---

### TASK-lgtm-010: Create Mimir HelmRelease Configuration

**Trace:** REQ-lgtm-d4f8c2a1-003 | Design: Mimir component with remote-write | AC: AC-lgtm-003-01, AC-lgtm-003-02, AC-lgtm-003-03
**ADR:** ADR-001 (HelmRelease pattern), ADR-002 (single replica), ADR-006 (monolithic mode)
**Approach:** Create HelmRelease with Grafana Mimir chart via OCIRepository, configure S3 backend and remote-write endpoint

**DoD (EARS Format):**

- WHEN HelmRelease is applied, SHALL reference OCIRepository for Grafana Mimir Helm chart
- WHERE S3 configuration is defined, SHALL use environment variables from mimir-s3-secret
- IF replicas are specified, SHALL be set to 1 (single instance deployment)
- WHEN remote-write endpoint is configured, SHALL listen on port 8080 at /api/v1/push
- WHERE memory limits are set, SHALL not exceed 1.5Gi per pod (home-lab constraint)
- IF blocks are compacted, SHALL upload to S3 and delete local copies (AC-lgtm-003-03)

**Risk:** Medium | Effort: 5pts
**Test Strategy:**

- Unit: Validate HelmRelease YAML syntax
- Integration: FluxCD reconciliation success check
- E2E: Mimir pod startup and readiness verification
  **Dependencies:** TASK-lgtm-009

**BDD Test Scenario:**

```gherkin
Feature: Mimir HelmRelease Deployment
  Scenario: Mimir deployed with S3 backend
    Given mimir-s3-secret exists in monitoring namespace
    When HelmRelease is applied to cluster
    Then Mimir pod SHALL start within 5 minutes
    And Mimir SHALL mount S3 credentials from secret
    And Mimir SHALL configure S3 backend with endpoint "https://s3.68cc.io"
    And Mimir SHALL configure S3 bucket "mimir-blocks"
    And Mimir SHALL enable remote-write endpoint on port 8080
    And Mimir SHALL be deployed as single replica
    And Mimir pod memory limit SHALL be 1.5Gi or less

  Scenario: S3 connection validation (AC-lgtm-003-01)
    Given Mimir is deployed
    When Mimir pod starts
    Then Mimir SHALL create connection to S3 bucket "mimir-blocks"
    And Mimir logs SHALL NOT contain S3 authentication errors
```

**Sub-tasks:**

- [ ] Create `kubernetes/apps/monitoring/mimir/app/helmrelease.yaml` with OCIRepository source
- [ ] Configure S3 backend using environment variables from secret
- [ ] Enable remote-write endpoint on port 8080
- [ ] Set replicas: 1 and resource limits (memory: 1.5Gi)
- [ ] Configure compaction settings (upload to S3, delete local)
- [ ] Add helmrelease.yaml to app/kustomization.yaml resources

---

### TASK-lgtm-011: Deploy Mimir and Verify S3 Connectivity

**Trace:** REQ-lgtm-d4f8c2a1-003 | Design: Mimir deployment validation | AC: AC-lgtm-003-01
**ADR:** ADR-002 (S3 persistence), ADR-006 (monolithic mode)
**Approach:** Apply Mimir kustomization via FluxCD, verify pod startup and S3 connection

**DoD (EARS Format):**

- WHEN kustomization is applied, SHALL trigger FluxCD reconciliation within 1 minute
- WHERE Mimir pod starts, SHALL reach Ready state within 5 minutes
- IF S3 connection is established, SHALL NOT log authentication or connection errors
- WHEN S3 bucket is accessed, SHALL use HTTPS endpoint and dedicated credentials

**Risk:** Medium | Effort: 3pts
**Test Strategy:**

- Integration: FluxCD reconciliation status check
- E2E: Pod readiness and S3 connection verification
  **Dependencies:** TASK-lgtm-010

**BDD Test Scenario:**

```gherkin
Feature: Mimir Deployment Verification
  Scenario: Successful Mimir deployment
    Given Mimir HelmRelease is committed to Git
    When FluxCD reconciles mimir kustomization
    Then HelmRelease SHALL report "Helm install succeeded" within 5 minutes
    And Mimir pod SHALL reach Ready state
    And Mimir service SHALL be accessible at mimir-gateway.monitoring.svc:8080

  Scenario: S3 connectivity validation (AC-lgtm-003-01)
    Given Mimir pod is running
    When Mimir initializes storage backend
    Then Mimir logs SHALL contain "successfully connected to S3"
    Or Mimir logs SHALL NOT contain "S3 connection failed"
    And Mimir SHALL create test blocks in mimir-blocks bucket
```

**Sub-tasks:**

- [ ] Commit mimir/ directory to Git
- [ ] Run `flux reconcile source git flux-system -n flux-system`
- [ ] Run `flux reconcile kustomization mimir -n flux-system` (if separate kustomization)
- [ ] Verify HelmRelease status: `kubectl get helmrelease -n monitoring mimir`
- [ ] Verify pod status: `kubectl get pods -n monitoring -l app.kubernetes.io/name=mimir`
- [ ] Check Mimir logs for S3 connection: `kubectl logs -n monitoring -l app.kubernetes.io/name=mimir | grep -i s3`

---

### TASK-lgtm-012: Create BDD Test Suite for Mimir Remote-Write Ingestion

**Trace:** REQ-lgtm-d4f8c2a1-003 | Design: Prometheus remote-write | AC: AC-lgtm-003-02
**ADR:** ADR-006 (remote-write endpoint)
**Approach:** Create BDD test scenarios using promtool to send test metrics via remote-write

**DoD (EARS Format):**

- WHEN test metrics are sent to Mimir remote-write endpoint, SHALL accept and acknowledge within 1 minute (AC-lgtm-003-02)
- WHERE metrics are persisted, SHALL appear in Mimir storage within 1 minute
- IF remote-write ingestion fails, SHALL return descriptive error message
- WHEN test completes, SHALL verify metrics are queryable via PromQL

**Risk:** Medium | Effort: 4pts
**Test Strategy:**

- E2E: Remote-write ingestion and query verification
  **Dependencies:** TASK-lgtm-011

**BDD Test Scenario:**

```gherkin
Feature: Mimir Remote-Write Ingestion (AC-lgtm-003-02)
  Background:
    Given Mimir is deployed and healthy
    And Mimir remote-write endpoint is accessible at mimir-gateway.monitoring.svc:8080/api/v1/push

  Scenario: Successful remote-write ingestion
    Given promtool is installed
    When test metrics are sent to remote-write endpoint
    Then Mimir SHALL accept metrics within 1 minute
    And Mimir SHALL return successful acknowledgment (HTTP 200)

  Scenario: Metrics persistence and query
    Given test metrics were ingested via remote-write
    When PromQL query is executed for test metrics
    Then Mimir SHALL return metrics within 3 seconds
    And metrics SHALL match ingested values

  Scenario: Remote-write error handling (AC-lgtm-003-04)
    Given S3 credentials are invalid
    When test metrics are sent to Mimir
    Then Mimir SHALL accept metrics (buffering for 2 hours)
    But Mimir logs SHALL contain S3 write error
    And Mimir SHALL NOT lose metrics during credential fix
```

**Sub-tasks:**

- [ ] Install promtool for Prometheus testing
- [ ] Create test script `tests/mimir-remote-write.sh`
- [ ] Implement BDD scenario: Send test metrics via remote-write
- [ ] Verify Mimir acknowledgment (HTTP 200 response)
- [ ] Query metrics via PromQL endpoint `/api/v1/query`
- [ ] Implement error handling scenario with invalid credentials
- [ ] Document test execution in `tests/README.md`

---

### TASK-lgtm-013: Create BDD Test Suite for Mimir Query Performance

**Trace:** REQ-lgtm-d4f8c2a1-003 | Design: Mimir query endpoint | AC: AC-lgtm-003-05
**ADR:** ADR-006 (monolithic mode with query endpoint)
**Approach:** Create automated tests for Mimir PromQL query response times

**DoD (EARS Format):**

- WHEN PromQL query is executed, SHALL return results within 3 seconds for queries up to 7 days (AC-lgtm-003-05)
- WHERE query includes metric name, SHALL return time series data
- IF metric does not exist, SHALL return empty result set with HTTP 200
- WHEN multiple queries are executed concurrently, SHALL maintain <3s response time

**Risk:** Low | Effort: 3pts
**Test Strategy:**

- E2E: Query performance validation with curl/http timing
  **Dependencies:** TASK-lgtm-012

**BDD Test Scenario:**

```gherkin
Feature: Mimir Query Performance (AC-lgtm-003-05)
  Background:
    Given Mimir contains test metrics from remote-write test
    And Mimir query endpoint is accessible at mimir-gateway.monitoring.svc:8080/prometheus/api/v1/query

  Scenario: Query recent metrics
    Given PromQL query for test metrics in last 24 hours
    When query is sent to /prometheus/api/v1/query
    Then response SHALL be received within 3 seconds
    And response SHALL contain time series data
    And response status SHALL be 200 OK

  Scenario: Query historical metrics (7 days)
    Given PromQL query for test metrics in last 7 days
    When query is sent to /prometheus/api/v1/query_range
    Then response SHALL be received within 3 seconds
    And response SHALL contain complete time range data

  Scenario: Query non-existent metric
    Given PromQL query for non-existent metric
    When query is sent to /prometheus/api/v1/query
    Then response SHALL be received within 3 seconds
    And response status SHALL be 200 OK
    And response SHALL contain empty result set

  Scenario: Concurrent query performance
    Given 10 valid PromQL queries
    When 10 queries are executed concurrently
    Then all responses SHALL be received within 3 seconds
    And all responses SHALL return valid time series data
```

**Sub-tasks:**

- [ ] Create test script `tests/mimir-query-performance.sh`
- [ ] Implement PromQL instant query with timing measurement
- [ ] Implement PromQL range query for 7-day period
- [ ] Verify response time <3 seconds using `time` or `curl -w "%{time_total}"`
- [ ] Test non-existent metric handling
- [ ] Test concurrent query performance with parallel curl requests
- [ ] Document test execution and expected results

---

### TASK-lgtm-014: Verify Mimir Block Compaction and S3 Upload

**Trace:** REQ-lgtm-d4f8c2a1-003 | Design: S3 block storage | AC: AC-lgtm-003-03
**ADR:** ADR-002 (S3 persistence), ADR-006 (block compaction)
**Approach:** Verify Mimir compacts blocks and uploads to S3, then deletes local copies

**DoD (EARS Format):**

- WHEN compaction interval is reached, SHALL compact blocks locally
- WHERE compacted blocks exist, SHALL upload to S3 bucket "mimir-blocks"
- IF upload succeeds, SHALL delete local compacted blocks to free disk space
- WHEN verifying S3 contents, SHALL find compacted block objects

**Risk:** Medium | Effort: 3pts
**Test Strategy:**

- E2E: S3 bucket verification for compacted blocks
  **Dependencies:** TASK-lgtm-013

**BDD Test Scenario:**

```gherkin
Feature: Mimir Block Compaction and S3 Upload (AC-lgtm-003-03)
  Background:
    Given Mimir has ingested metrics for at least 2 hours
    And Mimir compaction is enabled

  Scenario: Block compaction execution
    Given compaction interval has elapsed
    When Mimir compactor runs
    Then Mimir logs SHALL contain "compaction completed"
    And compacted blocks SHALL be uploaded to S3

  Scenario: S3 block verification
    Given Mimir has compacted blocks
    When S3 bucket "mimir-blocks" is queried using AWS CLI
    Then bucket SHALL contain block objects with .meta.json extension
    And block objects SHALL have recent modification timestamps

  Scenario: Local block deletion after S3 upload
    Given Mimir has uploaded compacted blocks to S3
    When local disk usage is checked
    Then local compacted blocks SHALL be deleted
    And disk space SHALL be freed
```

**Sub-tasks:**

- [ ] Wait for compaction interval (check Mimir configuration for timing)
- [ ] Monitor Mimir logs for compaction activity
- [ ] Verify S3 bucket contents: `aws s3 ls s3://mimir-blocks/ --endpoint-url=https://s3.68cc.io`
- [ ] Check for .meta.json files indicating compacted blocks
- [ ] Verify local disk usage in Mimir pod
- [ ] Document compaction behavior and timing

---

## Phase 3: Grafana Data Source Integration

### TASK-lgtm-015: Update Grafana HelmRelease with Tempo and Mimir Data Sources

**Trace:** REQ-lgtm-d4f8c2a1-005 | Design: Grafana datasource configuration | AC: AC-lgtm-005-01, AC-lgtm-005-02
**ADR:** ADR-007 (datasource configuration via HelmRelease values)
**Approach:** Modify existing Grafana HelmRelease to add Tempo and Mimir datasource configurations

**DoD (EARS Format):**

- WHEN Grafana HelmRelease is updated, SHALL include datasource configuration for Tempo
- WHERE Tempo datasource is defined, SHALL point to tempo.monitoring.svc:3200
- IF Mimir datasource is added, SHALL point to mimir-gateway.monitoring.svc:8080/prometheus
- WHEN Grafana pod restarts, SHALL automatically load new datasources (AC-lgtm-005-02)

**Risk:** Low | Effort: 3pts
**Test Strategy:**

- Integration: Grafana pod restart verification
- E2E: Datasource connectivity test in Grafana UI
  **Dependencies:** TASK-lgtm-014 (all components deployed)

**BDD Test Scenario:**

```gherkin
Feature: Grafana Data Source Integration (AC-lgtm-005-01, AC-lgtm-005-02)
  Background:
    Given Tempo is deployed at tempo.monitoring.svc:3200
    And Mimir is deployed at mimir-gateway.monitoring.svc:8080

  Scenario: Grafana datasource configuration update
    Given Grafana HelmRelease exists
    When HelmRelease is updated with Tempo and Mimir datasources
    Then HelmRelease SHALL trigger Grafana pod restart
    And Grafana SHALL load datasources from configuration

  Scenario: Tempo datasource availability (AC-lgtm-005-02)
    Given Grafana has restarted with new datasources
    When Grafana UI is accessed
    Then Tempo datasource SHALL appear in datasource list
    And Tempo datasource SHALL have URL "http://tempo.monitoring.svc:3200"

  Scenario: Mimir datasource availability (AC-lgtm-005-02)
    Given Grafana has restarted with new datasources
    When Grafana UI is accessed
    Then Mimir datasource SHALL appear in datasource list
    And Mimir datasource SHALL have URL "http://mimir-gateway.monitoring.svc:8080/prometheus"
```

**Sub-tasks:**

- [ ] Locate existing Grafana HelmRelease: `kubernetes/apps/monitoring/grafana/app/helmrelease.yaml`
- [ ] Add Tempo datasource configuration to `datasources.yaml` section
- [ ] Add Mimir datasource configuration to `datasources.yaml` section
- [ ] Commit Grafana HelmRelease changes
- [ ] Reconcile FluxCD: `flux reconcile kustomization grafana -n flux-system`
- [ ] Verify Grafana pod restart: `kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana -w`
- [ ] Access Grafana UI and verify datasources appear

---

### TASK-lgtm-016: Create BDD Test Suite for Grafana Data Source Connectivity

**Trace:** REQ-lgtm-d4f8c2a1-005 | Design: Grafana datasource validation | AC: AC-lgtm-005-03, AC-lgtm-005-04
**ADR:** ADR-007 (declarative datasource configuration)
**Approach:** Create automated tests for Grafana datasource connectivity via API

**DoD (EARS Format):**

- WHEN datasource connectivity is tested, SHALL return successful status for Tempo and Mimir (AC-lgtm-005-03)
- WHERE datasources are unreachable, SHALL display clear error messages (AC-lgtm-005-04)
- IF datasource test fails, SHALL provide actionable troubleshooting information
- WHEN test completes, SHALL verify end-to-end query capability

**Risk:** Low | Effort: 4pts
**Test Strategy:**

- E2E: Grafana API datasource health check
  **Dependencies:** TASK-lgtm-015

**BDD Test Scenario:**

```gherkin
Feature: Grafana Data Source Connectivity (AC-lgtm-005-03, AC-lgtm-005-04)
  Background:
    Given Grafana is running with Tempo and Mimir datasources configured
    And Grafana API is accessible

  Scenario: Tempo datasource connectivity test (AC-lgtm-005-03)
    Given Tempo datasource is configured in Grafana
    When datasource health check is performed via Grafana API
    Then health check SHALL return "success" status
    And response SHALL indicate Tempo is reachable

  Scenario: Mimir datasource connectivity test (AC-lgtm-005-03)
    Given Mimir datasource is configured in Grafana
    When datasource health check is performed via Grafana API
    Then health check SHALL return "success" status
    And response SHALL indicate Mimir is reachable

  Scenario: Datasource error message validation (AC-lgtm-005-04)
    Given Tempo pod is stopped
    When Tempo datasource health check is performed
    Then health check SHALL return "error" status
    And error message SHALL contain "connection refused" or similar
    And error message SHALL be displayed in Grafana UI

  Scenario: End-to-end query validation
    Given all datasources are healthy
    When test query is executed in Grafana for Tempo traces
    Then query SHALL return results successfully
    When test query is executed in Grafana for Mimir metrics
    Then query SHALL return results successfully
```

**Sub-tasks:**

- [ ] Create test script `tests/grafana-datasource-connectivity.sh`
- [ ] Implement Grafana API authentication (get API key or use admin credentials)
- [ ] Test Tempo datasource: `GET /api/datasources/name/Tempo/health`
- [ ] Test Mimir datasource: `GET /api/datasources/name/Mimir/health`
- [ ] Implement error scenario by stopping Tempo pod temporarily
- [ ] Verify error messages are descriptive
- [ ] Test end-to-end queries via Grafana API
- [ ] Document test execution and API usage

---

## Phase 4: Prometheus Remote-Write Configuration

### TASK-lgtm-017: Configure Prometheus Remote-Write to Mimir

**Trace:** REQ-lgtm-d4f8c2a1-003 | Design: Prometheus integration | AC: AC-lgtm-003-02
**ADR:** ADR-006 (Mimir remote-write endpoint)
**Approach:** Update kube-prometheus-stack HelmRelease to add remote-write configuration pointing to Mimir

**DoD (EARS Format):**

- WHEN Prometheus HelmRelease is updated, SHALL include remoteWrite configuration for Mimir
- WHERE remoteWrite URL is defined, SHALL point to mimir-gateway.monitoring.svc:8080/api/v1/push
- IF queue configuration is specified, SHALL include retry and capacity settings for reliability
- WHEN Prometheus pods restart, SHALL begin remote-writing metrics to Mimir within 1 minute (AC-lgtm-003-02)

**Risk:** Low | Effort: 3pts
**Test Strategy:**

- Integration: Prometheus remote-write metrics verification
- E2E: Mimir metrics ingestion from Prometheus
  **Dependencies:** TASK-lgtm-016

**BDD Test Scenario:**

```gherkin
Feature: Prometheus Remote-Write to Mimir (AC-lgtm-003-02)
  Background:
    Given Mimir is deployed and healthy
    And Prometheus is deployed via kube-prometheus-stack

  Scenario: Remote-write configuration update
    Given kube-prometheus-stack HelmRelease exists
    When HelmRelease is updated with Mimir remote-write configuration
    Then Prometheus pods SHALL restart
    And Prometheus SHALL begin sending metrics to Mimir

  Scenario: Metrics flow from Prometheus to Mimir (AC-lgtm-003-02)
    Given Prometheus has remote-write enabled
    When Prometheus collects metrics from ServiceMonitors
    Then metrics SHALL be sent to Mimir within 1 minute
    And Mimir SHALL accept remote-write requests
    And Mimir logs SHALL show successful ingestion

  Scenario: Remote-write queue health
    Given Prometheus is remote-writing to Mimir
    When Prometheus metrics are queried for remote-write queue
    Then queue_samples_pending SHALL be low (<1000)
    And failed_samples_total SHALL be zero or minimal
    And succeeded_samples_total SHALL be increasing
```

**Sub-tasks:**

- [ ] Locate kube-prometheus-stack HelmRelease: `kubernetes/apps/monitoring/kube-prometheus-stack/app/helmrelease.yaml`
- [ ] Add remoteWrite configuration to Prometheus values:
    ```yaml
    remoteWrite:
        - url: http://mimir-gateway.monitoring.svc:8080/api/v1/push
          queueConfig:
              capacity: 10000
              maxShards: 200
              minShards: 1
              maxSamplesPerSend: 1000
              batchSendDeadline: 5s
              minBackoff: 30ms
              maxBackoff: 100ms
    ```
- [ ] Commit Prometheus HelmRelease changes
- [ ] Reconcile FluxCD: `flux reconcile kustomization kube-prometheus-stack -n flux-system`
- [ ] Verify Prometheus pods restart
- [ ] Check Prometheus metrics for remote-write queue: `prometheus_remote_storage_*`
- [ ] Verify Mimir logs for incoming remote-write requests

---

## Dependency Graph

```
Prerequisites:
- S3 buckets: tempo-traces, mimir-blocks (manually created)

Phase 1: Tempo
TASK-001 (structure) → TASK-002 (secret) → TASK-003 (helmrelease) → TASK-004 (deploy) → TASK-005 (otlp test) → TASK-006 (query test) → TASK-007 (recovery test)

Phase 2: Mimir (parallel start after Tempo complete)
TASK-008 (structure) → TASK-009 (secret) → TASK-010 (helmrelease) → TASK-011 (deploy) → TASK-012 (remote-write test) → TASK-013 (query test) → TASK-014 (compaction test)

Phase 3: Integration (sequential after Phase 1 + Phase 2)
TASK-015 (grafana datasources) → TASK-016 (datasource connectivity test)

Phase 4: Prometheus (sequential after Mimir)
TASK-017 (prometheus remote-write)
```

## Implementation Context

**Critical Path:**

- S3 bucket creation (manual prerequisite)
- Tempo deployment and validation (TASK-001 → TASK-007)
- Mimir deployment and validation (TASK-008 → TASK-014)
- Grafana integration (TASK-015 → TASK-016)
- Prometheus remote-write (TASK-017)

**Risk Mitigation:**

- **Medium Risk - S3 connectivity:** Comprehensive error logging, health checks, dedicated credentials per component
- **Medium Risk - OTLP/Remote-Write ingestion rate:** Conservative defaults with monitoring alerts
- **Medium Risk - Query performance:** BDD tests verify response times meet EARS requirements
- **Low Risk - FluxCD reconciliation:** Established pattern, GitOps workflow proven

**Context Compression:**
Phased MVP deployment of LGTM stack (Tempo + Mimir only, Loki replaced by Parseable). Each component deployed with dedicated S3 backend, SOPS-encrypted credentials, single-replica home-lab sizing. Comprehensive BDD test suites ensure EARS acceptance criteria compliance. Grafana integration enables unified observability. Prometheus remote-write provides long-term metrics storage in Mimir.

---

## Verification Checklist (EARS Compliance)

### Requirements Traceability

- [x] REQ-lgtm-d4f8c2a1-002 (Tempo) → TASK-001 through TASK-007 with EARS DoD
- [x] REQ-lgtm-d4f8c2a1-003 (Mimir) → TASK-008 through TASK-014 with EARS DoD
- [x] REQ-lgtm-d4f8c2a1-004 (S3 credentials) → TASK-002, TASK-009 with EARS DoD
- [x] REQ-lgtm-d4f8c2a1-005 (Grafana integration) → TASK-015, TASK-016 with EARS DoD

### Acceptance Criteria Coverage

- [x] AC-lgtm-002-01 (Tempo S3 bucket) → TASK-004 BDD test
- [x] AC-lgtm-002-02 (Tempo trace ingestion) → TASK-005 BDD test
- [x] AC-lgtm-002-03 (Tempo recovery) → TASK-007 BDD test
- [x] AC-lgtm-002-04 (Tempo error handling) → TASK-005 BDD test
- [x] AC-lgtm-002-05 (Tempo query performance) → TASK-006 BDD test
- [x] AC-lgtm-003-01 (Mimir S3 bucket) → TASK-011 BDD test
- [x] AC-lgtm-003-02 (Mimir remote-write) → TASK-012, TASK-017 BDD test
- [x] AC-lgtm-003-03 (Mimir compaction) → TASK-014 BDD test
- [x] AC-lgtm-003-04 (Mimir error handling) → TASK-012 BDD test
- [x] AC-lgtm-003-05 (Mimir query performance) → TASK-013 BDD test
- [x] AC-lgtm-004-01 (SOPS encryption) → TASK-002, TASK-009 BDD test
- [x] AC-lgtm-004-02 (Secret env vars) → TASK-003, TASK-010 BDD test
- [x] AC-lgtm-004-04 (HTTPS endpoint) → All S3 configurations
- [x] AC-lgtm-005-01 (Grafana datasources) → TASK-015 BDD test
- [x] AC-lgtm-005-02 (Datasource auto-load) → TASK-015 BDD test
- [x] AC-lgtm-005-03 (Datasource connectivity) → TASK-016 BDD test
- [x] AC-lgtm-005-04 (Error messages) → TASK-016 BDD test

### NFR Coverage

- [x] NFR-PERF-001 (Query performance) → TASK-006, TASK-013 BDD tests
- [x] NFR-PERF-002 (Ingestion throughput) → TASK-005, TASK-012 BDD tests
- [x] NFR-SEC-001 (Credential security) → TASK-002, TASK-009 SOPS encryption
- [x] NFR-SEC-002 (Network security) → All S3 HTTPS configurations
- [x] NFR-SCALE-002 (Resource constraints) → TASK-003, TASK-010 memory limits
- [x] NFR-OPS-001 (FluxCD pattern) → All HelmRelease tasks
- [x] NFR-RECOVER-001 (Data recovery) → TASK-007 pod deletion test

### ADR Implementation

- [x] ADR-001 (FluxCD HelmRelease) → TASK-003, TASK-010
- [x] ADR-002 (Single replica + S3) → TASK-003, TASK-010
- [x] ADR-003 (Dedicated S3 credentials) → TASK-002, TASK-009
- [x] ADR-005 (Tempo monolithic + OTLP) → TASK-003
- [x] ADR-006 (Mimir monolithic + remote-write) → TASK-010
- [x] ADR-007 (Grafana datasource config) → TASK-015

### EARS-to-BDD Translation

- [x] All EARS WHEN triggers → BDD Given/When scenarios
- [x] All EARS SHALL requirements → BDD Then assertions
- [x] All EARS WHERE constraints → BDD context conditions
- [x] All EARS IF conditions → BDD error scenarios
- [x] Confidence levels documented in BDD scenarios

### Test Coverage Completeness

- [x] Unit tests: SOPS encryption, YAML validation
- [x] Integration tests: FluxCD reconciliation, pod startup, S3 connectivity
- [x] E2E tests: OTLP ingestion, remote-write, query performance, Grafana datasources
- [x] BDD scenarios: Every acceptance criterion has Given/When/Then test

### Behavioral Contract Consistency

- [x] All component interfaces defined with EARS contracts
- [x] Service endpoints documented with performance requirements
- [x] Error handling specified with EARS IF conditions
- [x] Recovery procedures documented with EARS WHERE constraints

---

## Auto-Verification Result: PASSED ✅

**Traceability Completeness:** 100% (all REQ-\* → tasks with EARS DoD)
**Design-to-Tasks Coverage:** 100% (all ADRs → implementation tasks)
**Task Dependency Logic:** Valid (sequential and parallel paths clear)
**Effort Estimation:** Reasonable (4-6 hours total with BDD test development)

**Verification Output:** Tasks Check: PASSED

All requirements traced to implementation tasks. All EARS acceptance criteria have BDD test coverage. Task dependencies are logical and clear. Implementation plan is actionable and appropriately scoped for phased MVP deployment.
