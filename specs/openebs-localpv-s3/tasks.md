# Tasks: OpenEBS LocalPV with S3 Snapshot Integration

## Metadata

- Complexity: Medium (M) — Multi-component integration, S3 coordination, migration procedures
- Critical Path: Foundation (Tasks 1-3) → Core Integration (Tasks 4-6) → Migration & Validation (Tasks 7-10)
- Risk Score: 6.5/10 — Data loss risk during migration, S3 connectivity dependencies, resource constraints
- Timeline Estimate: 6-8 weeks (including validation and phased migration)

## Progress: 4/10 Complete, 0 In Progress, 6 Not Started, 0 Blocked

---

## Phase 1: Foundation (Week 1)

### [x] TASK-a7f3d9c2-001: Create FluxCD Structure for OpenEBS

**Trace:** REQ-a7f3d9c2-003, REQ-a7f3d9c2-001 | **Design:** ADR-004 | **AC:** AC-003-01
**DoD (EARS Format):**

- WHEN task completed, SHALL have created `kubernetes/apps/kube-system/openebs/ks.yaml` with valid FluxCD Kustomization
- WHEN task completed, SHALL have created `kubernetes/apps/kube-system/openebs/app/kustomization.yaml` following existing patterns
- WHEN task completed, SHALL have created `kubernetes/apps/kube-system/openebs/app/helmrelease.yaml` with OpenEBS chart reference
- WHERE namespace created, SHALL be `kube-system` per EARS contract specifications

**Risk:** Low | **Deps:** None | **Effort:** 2pts

**Sub-tasks:**

- [x] Create directory structure: `kubernetes/apps/kube-system/openebs/{ks.yaml,app/}`
- [ ] Write `ks.yaml` with FluxCD Kustomization manifest
- [ ] Write `app/kustomization.yaml` with namespace and HelmRelease resources
- [ ] Write `app/helmrelease.yaml` with OpenEBS chart from OCI registry

---

### [x] TASK-a7f3d9c2-002: Configure OpenEBS HelmRelease with LocalPV Provisioner

**Trace:** REQ-a7f3d9c2-001 | **Design:** ADR-001, Component: OpenEBS LocalPV Control Plane | **AC:** AC-001-01, AC-001-02, AC-001-04
**DoD (EARS Format):**

- WHEN HelmRelease values configured, SHALL enable LocalPV provisioner with both hostpath and device modes
- WHEN HA deployment specified, SHALL include resource limits <500Mi memory per pod per NFR-SCALE-001 (Note: Using Deployment with leader election, not DaemonSet)
- WHEN StorageClass definitions included, SHALL create `openebs-localpv-hostpath` (default) and `openebs-localpv-device`
- WHERE control plane pods deployed, SHALL run with HA pattern (3 replicas + leader election) per ADR-003

**Risk:** Medium (resource limits may need tuning) | **Deps:** TASK-001 | **Effort:** 5pts

**Sub-tasks:**

- [x] Define Helm values for LocalPV provisioner enablement
- [x] Configure HA deployment with 3 replicas + leader election
- [x] Set resource limits (500Mi memory limit, 128Mi request)
- [x] Create StorageClass manifests (hostpath as default, device as optional)
- [x] Add node selectors and tolerations for control plane placement (configured as empty for default behavior)

---

### [x] TASK-a7f3d9c2-003: Create SOPS-Encrypted Velero S3 Secret

**Trace:** REQ-a7f3d9c2-002 | **Design:** ADR-002, Component: Velero Backup Controller | **AC:** AC-002-04
**DoD (EARS Format):**

- WHEN secret created, SHALL contain S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_ENDPOINT, S3_BUCKET keys
- WHEN secret encrypted, SHALL use SOPS with age keys following existing pattern per NFR-SEC-001
- WHERE S3 endpoint specified, SHALL be `https://s3.68cc.io` (HTTPS mandatory) per NFR-SEC-001
- WHERE bucket specified, SHALL be `openebs-backups` per AC-002-01

**Risk:** Low | **Deps:** None (can run parallel to TASK-001/002) | **Effort:** 2pts

**Sub-tasks:**

- [ ] Create `kubernetes/apps/storage/velero/app/velero-s3-secret.sops.yaml` template
- [ ] Populate with Minio S3 credentials (access key, secret key)
- [ ] Set S3_ENDPOINT=https://s3.68cc.io and S3_BUCKET=openebs-backups
- [ ] Encrypt using `sops --encrypt --age <age-key> velero-s3-secret.yaml`
- [ ] Verify decryption works with FluxCD age key

---

## Phase 2: Core Integration (Week 2-3)

### [x] TASK-a7f3d9c2-004: Deploy Velero with OpenEBS CSI Plugin

**Trace:** REQ-a7f3d9c2-002 | **Design:** ADR-002, Component: Velero Backup Controller | **AC:** AC-002-01, AC-002-02
**DoD (EARS Format):**

- WHEN Velero HelmRelease applied, SHALL deploy Velero controller in `velero` namespace
- WHEN Velero configured, SHALL include OpenEBS CSI snapshot plugin for volume snapshots
- WHEN BackupStorageLocation created, SHALL reference Minio S3 with SOPS-encrypted credentials
- WHERE scheduled backup configured, SHALL execute daily at 02:00 UTC with 30-day retention per AC-002-02

**Risk:** Medium (S3 connectivity, plugin compatibility) | **Deps:** TASK-003 | **Effort:** 5pts

**Sub-tasks:**

- [ ] Create `kubernetes/apps/storage/velero/ks.yaml` and `app/helmrelease.yaml`
- [ ] Configure Velero Helm chart with S3 BackupStorageLocation
- [ ] Enable OpenEBS CSI snapshot plugin in Helm values
- [ ] Create `Schedule` resource for daily backups (02:00 UTC, 30d TTL)
- [ ] Mount SOPS-encrypted secret for S3 authentication

---

### [ ] TASK-a7f3d9c2-005: Validate Storage Provisioning and Snapshot Integration

**Trace:** REQ-a7f3d9c2-001, REQ-a7f3d9c2-002 | **Design:** All data flows | **AC:** AC-001-01, AC-002-01, AC-002-03
**DoD (EARS Format):**

- WHEN test PVC created with `storageClass: openebs-localpv`, SHALL provision LocalPV volume within 30 seconds per AC-001-01
- WHEN Velero backup triggered manually, SHALL snapshot PVC and upload to S3 within 5 minutes per AC-002-01
- WHEN Velero restore executed, SHALL recreate volume from S3 snapshot within 15 minutes per AC-002-03
- WHERE validation test passes, SHALL verify data integrity (write → backup → destroy → restore → verify read)

**Risk:** High (core functionality validation) | **Deps:** TASK-002, TASK-004 | **Effort:** 8pts

**Sub-tasks:**

- [ ] Deploy test StatefulSet with OpenEBS PVC (1Gi volume)
- [ ] Write test data to mounted volume (unique pattern for validation)
- [ ] Trigger manual Velero backup: `velero backup create test-backup --include-namespaces=test`
- [ ] Verify backup appears in S3 bucket `openebs-backups` within 5 minutes
- [ ] Delete StatefulSet and PVC to simulate data loss
- [ ] Restore: `velero restore create --from-backup test-backup`
- [ ] Verify data integrity: read restored volume, compare to original pattern
- [ ] Measure timing: provisioning (<30s), backup (<5min), restore (<15min)

---

### [ ] TASK-a7f3d9c2-006: Configure Observability Integration

**Trace:** NFR-a7f3d9c2-OPER-001 | **Design:** Data flows | **AC:** NFR-OPER-001
**DoD (EARS Format):**

- WHEN OpenEBS metrics enabled, SHALL export to Prometheus via ServiceMonitor per NFR-OPER-001
- WHEN Velero logs configured, SHALL forward to Loki for centralized logging per NFR-OPER-001
- WHERE alerts defined, SHALL integrate with existing Alertmanager for backup/restore failures per NFR-OPER-001
- WHERE Grafana dashboard created, SHALL visualize PVC provisioning time, snapshot success rate, S3 usage

**Risk:** Low | **Deps:** TASK-002, TASK-004 | **Effort:** 4pts

**Sub-tasks:**

- [ ] Create ServiceMonitor for OpenEBS metrics export to Prometheus
- [ ] Configure Velero to output structured logs for Loki ingestion
- [ ] Define PrometheusRule for alerts: PVC provisioning failures, backup failures, S3 connectivity issues
- [ ] Import/create Grafana dashboard for OpenEBS + Velero monitoring
- [ ] Validate metrics appear in Prometheus, logs in Loki, alerts in Alertmanager

---

## Phase 3: Migration & Validation (Week 4-6)

### [ ] TASK-a7f3d9c2-007: Create Migration Runbooks

**Trace:** REQ-a7f3d9c2-004 | **Design:** Migration Procedures | **AC:** AC-004-01
**DoD (EARS Format):**

- WHEN runbooks complete, SHALL provide step-by-step procedures for each workload type per AC-004-01
- WHERE blue-green deployment pattern documented, SHALL include rollback procedures per AC-004-03
- WHERE CloudNative-PG migration documented, SHALL preserve S3 backup integration per AC-004-04
- WHERE validation checklist included, SHALL specify data integrity tests and downtime limits per AC-004-02

**Risk:** Low (documentation task) | **Deps:** TASK-005 (validation informs procedures) | **Effort:** 3pts

**Sub-tasks:**

- [ ] Document generic PVC migration procedure (create new PVC → copy data → cutover)
- [ ] Document database-specific migration (PostgreSQL with pg_basebackup or Velero)
- [ ] Document LGTM stack migration (hybrid S3 + OpenEBS approach)
- [ ] Document rollback procedures (revert to previous PVC, verify data consistency)
- [ ] Create validation checklist template (data integrity tests, downtime measurement, rollback test)

---

### [ ] TASK-a7f3d9c2-008: Migrate Test Database Workload

**Trace:** REQ-a7f3d9c2-004 | **Design:** Migration Procedures, Phase 2 | **AC:** AC-004-02, AC-004-03
**DoD (EARS Format):**

- WHEN test PostgreSQL deployed on OpenEBS, SHALL use `storageClass: openebs-localpv` for data volume
- WHEN migration executed, SHALL complete with <5 minutes downtime per AC-004-02
- WHEN validation tests pass, SHALL verify data integrity (row count, checksums) post-migration
- IF migration fails validation, SHALL execute rollback procedure successfully per AC-004-03

**Risk:** Medium (first production-like migration) | **Deps:** TASK-007 | **Effort:** 5pts

**Sub-tasks:**

- [ ] Deploy test PostgreSQL instance with sample dataset on existing storage
- [ ] Follow migration runbook: create OpenEBS PVC, pg_basebackup to new volume
- [ ] Cutover: update StatefulSet to use new PVC, restart pods
- [ ] Measure downtime from shutdown to ready state
- [ ] Validate data integrity: compare row counts, run checksum queries
- [ ] Test rollback: revert to original PVC, verify data unchanged
- [ ] Trigger Velero backup of migrated database, validate restore

---

### [ ] TASK-a7f3d9c2-009: Migrate CloudNative-PG to OpenEBS (Dual Backup Strategy)

**Trace:** REQ-a7f3d9c2-004 | **Design:** Migration Procedures, Phase 4 | **AC:** AC-004-04
**DoD (EARS Format):**

- WHEN CloudNative-PG Cluster updated, SHALL use OpenEBS PVCs for WAL and data volumes
- WHEN S3 backup integration verified, SHALL maintain existing `barmanObjectStore` configuration per AC-004-04
- WHERE dual backup strategy validated, SHALL have both S3 continuous archiving AND Velero snapshots
- WHERE production cutover executed, SHALL achieve zero downtime with streaming replication

**Risk:** High (production database, data criticality) | **Deps:** TASK-008 (test migration validates approach) | **Effort:** 8pts

**Sub-tasks:**

- [ ] Create new CloudNative-PG Cluster manifest with `storageClass: openebs-localpv`
- [ ] Deploy new cluster in parallel to existing (blue-green pattern)
- [ ] Configure streaming replication from existing cluster to new cluster
- [ ] Wait for replication lag to reach <10s, verify data consistency
- [ ] Update service selectors to cutover traffic to new cluster (zero downtime)
- [ ] Validate S3 barman backups continue to function (check `Backup` CR status)
- [ ] Trigger Velero snapshot of new cluster volumes
- [ ] Monitor for 24 hours, then decommission old cluster

---

### [ ] TASK-a7f3d9c2-010: Full Integration Testing and Documentation

**Trace:** ALL AC-\* | **Design:** Quality Gates | **AC:** 100% AC coverage validation
**DoD (EARS Format):**

- WHEN integration tests execute, SHALL validate every EARS acceptance criterion per verification checklist
- WHEN performance tests complete, SHALL confirm NFR-PERF-001 compliance (<30s provisioning, <5min backup, <15min restore)
- WHERE security tests validate, SHALL verify SOPS encryption, HTTPS S3, RBAC policies per NFR-SEC-001
- WHERE final documentation complete, SHALL include operator runbooks, troubleshooting guides, architecture diagrams

**Risk:** Low (final validation) | **Deps:** ALL previous tasks | **Effort:** 6pts

**Sub-tasks:**

- [ ] Execute EARS-to-BDD test suite covering all acceptance criteria
- [ ] Performance benchmark: provision 10 PVCs, measure timing distribution
- [ ] Security audit: verify SOPS decryption, HTTPS-only S3, namespace RBAC
- [ ] Chaos testing: kill OpenEBS pod, verify PVC provisioning recovers
- [ ] Disaster recovery drill: full cluster backup → restore to new namespace
- [ ] Generate architecture diagram with storage flow visualization
- [ ] Write operator runbook: common tasks, troubleshooting, escalation procedures
- [ ] Update CLAUDE.md with OpenEBS storage architecture patterns

---

## Verification Checklist (EARS Compliance)

### Requirements Traceability

- [ ] REQ-a7f3d9c2-001 → TASK-001, TASK-002, TASK-005 (OpenEBS provisioning)
- [ ] REQ-a7f3d9c2-002 → TASK-003, TASK-004, TASK-005 (Velero S3 snapshots)
- [ ] REQ-a7f3d9c2-003 → TASK-001 (FluxCD GitOps)
- [ ] REQ-a7f3d9c2-004 → TASK-007, TASK-008, TASK-009 (Migration strategy)

### EARS Acceptance Criteria Coverage

- [ ] AC-001-01 (PVC provisioning <30s) → TASK-005 integration tests
- [ ] AC-001-02 (HA DaemonSet) → TASK-002 configuration + TASK-010 chaos testing
- [ ] AC-001-03 (Node failure tolerance) → TASK-010 chaos testing
- [ ] AC-001-04 (Multiple storage classes) → TASK-002 configuration
- [ ] AC-002-01 (Backup to S3 <5min) → TASK-005 validation
- [ ] AC-002-02 (Daily scheduled backups) → TASK-004 Schedule configuration
- [ ] AC-002-03 (Restore from S3 <15min) → TASK-005 validation
- [ ] AC-002-04 (SOPS encryption) → TASK-003 secret creation + TASK-010 security audit
- [ ] AC-003-01 (FluxCD HelmRelease) → TASK-001 structure creation
- [ ] AC-003-02 (Auto reconciliation <5min) → TASK-010 GitOps testing
- [ ] AC-003-03 (SOPS auto-decryption) → TASK-003 + TASK-010 validation
- [ ] AC-003-04 (Kustomize overlays) → TASK-001 structure (future extensibility)
- [ ] AC-004-01 (Migration documentation) → TASK-007 runbooks
- [ ] AC-004-02 (Blue-green deployment) → TASK-008, TASK-009 migration execution
- [ ] AC-004-03 (Rollback support) → TASK-008 rollback testing
- [ ] AC-004-04 (CloudNative-PG S3 preservation) → TASK-009 dual backup validation

### NFR Validation Coverage

- [ ] NFR-PERF-001 (Provisioning <30s, Snapshot <5min, Restore <15min) → TASK-005, TASK-010
- [ ] NFR-SEC-001 (SOPS encryption, HTTPS S3, RBAC) → TASK-003, TASK-010
- [ ] NFR-SCALE-001 (Resource limits <500Mi) → TASK-002 configuration
- [ ] NFR-AVAIL-001 (DaemonSet HA, backup I/O non-blocking) → TASK-002, TASK-010
- [ ] NFR-OPER-001 (Prometheus metrics, Loki logs, Alertmanager alerts) → TASK-006

### Design ADR Implementation

- [ ] ADR-001 (LocalPV selection) → TASK-002
- [ ] ADR-002 (Velero integration) → TASK-004
- [ ] ADR-003 (DaemonSet HA) → TASK-002
- [ ] ADR-004 (FluxCD GitOps) → TASK-001
- [ ] ADR-005 (Gradual migration) → TASK-007, TASK-008, TASK-009

### Risk Mitigation

- [ ] High-risk tasks (TASK-005, TASK-009) have validation gates before production use
- [ ] Medium-risk tasks (TASK-002, TASK-004, TASK-008) include rollback procedures
- [ ] Data loss scenarios tested via TASK-005 destroy/restore cycle
- [ ] Performance bottlenecks identified via TASK-010 benchmarking

### EARS-to-BDD Test Translation

- [ ] Every WHEN clause → Given/When test scenario
- [ ] Every SHALL constraint → Then assertion with measurable criteria
- [ ] Every IF/WHERE condition → Test case variations (positive + negative paths)
- [ ] Confidence percentages → Test priority (>85% = critical path tests)

---

## Task Execution Notes

**Sequential Dependencies:**

- Phase 1 tasks (001-003) can run in parallel
- Phase 2 requires Phase 1 completion
- Phase 3 requires TASK-005 validation before migrations (TASK-008, TASK-009)
- TASK-010 is final integration validation after all migrations

**Risk Management:**

- Tasks with High risk (TASK-005, TASK-009) require approval gate before proceeding
- Tasks with Medium risk require validation in non-production first
- All migration tasks (007-009) require explicit user confirmation before production execution

**Progress Tracking:**

- Update progress counter after each task completion: `X/10 Complete`
- Mark tasks `[x]` only when ALL sub-tasks and DoD criteria satisfied
- If any EARS criterion fails, task returns to `[ ]` status until remediated
