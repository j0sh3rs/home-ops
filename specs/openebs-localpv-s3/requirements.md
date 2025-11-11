# Requirements: OpenEBS LocalPV S3 Backup Integration

## Meta-Context

- **Feature UUID:** FEAT-e8a3c7b2
- **Parent Context:** [CLAUDE.md § Storage Architecture, § Observability Stack]
- **Dependency Graph:**
    - Upstream: OpenEBS LocalPV Provisioner (openebs-localpv-hostpath)
    - Upstream: Minio S3 endpoint (s3.68cc.io)
    - Upstream: FluxCD GitOps deployment system
    - Upstream: SOPS secret encryption
    - Downstream: Stateful workload disaster recovery (CloudNative-PG, LGTM stack)

---

## Functional Requirements

### REQ-e8a3c7b2-001: Velero Deployment with Restic Integration

**Intent Vector:** Deploy Velero backup controller with Restic daemonset for file-level PV backups to S3

**User Story:**
As a **home-lab administrator**, I want **Velero deployed with Restic integration** so that **I can perform reliable file-level backups of OpenEBS LocalPV volumes to S3 storage**.

**Business Value:** 9/10 | **Complexity:** M

**Acceptance Criteria (EARS Syntax):**

- **AC-e8a3c7b2-001-01:** WHEN Velero HelmRelease is applied via FluxCD, the system SHALL deploy Velero controller pod with S3 configuration within 5 minutes {confidence: 95%}
- **AC-e8a3c7b2-001-02:** WHEN Restic daemonset is deployed, the system SHALL run Restic pod on every cluster node with OpenEBS volumes {confidence: 90%}
- **AC-e8a3c7b2-001-03:** WHERE S3 credentials are stored in SOPS-encrypted secret, the system SHALL mount credentials to Velero pods securely {confidence: 95%}
- **AC-e8a3c7b2-001-04:** WHILE Velero is running, the system SHALL maintain persistent connection to Minio S3 endpoint (s3.68cc.io) {confidence: 85%}

**Validation Hooks:**

```gherkin
GIVEN FluxCD HelmRelease for Velero
WHEN kubectl apply is executed
THEN Velero controller pod reaches Running state
AND Restic daemonset has pod per node
AND S3 credentials mounted from velero-s3-secret
```

**Risk Factors:**

- Network connectivity issues between cluster and Minio S3
- SOPS secret decryption failures
- Restic daemonset resource contention on nodes

---

### REQ-e8a3c7b2-002: S3 Bucket Configuration

**Intent Vector:** Configure dedicated S3 bucket for Velero backups with proper access credentials

**User Story:**
As a **home-lab administrator**, I want **a dedicated S3 bucket for Velero backups** so that **backup data is organized separately from other S3 storage**.

**Business Value:** 8/10 | **Complexity:** S

**Acceptance Criteria (EARS Syntax):**

- **AC-e8a3c7b2-002-01:** WHEN Velero is initialized, the system SHALL create or use existing `velero-backups` bucket in Minio S3 {confidence: 95%}
- **AC-e8a3c7b2-002-02:** WHERE S3 bucket is accessed, the system SHALL authenticate using dedicated velero-s3-secret credentials {confidence: 95%}
- **AC-e8a3c7b2-002-03:** IF S3 bucket does not exist, the system SHALL create it automatically with HTTPS-only access {confidence: 90%}
- **AC-e8a3c7b2-002-04:** WHILE backups are stored, the system SHALL organize objects with `velero/backups/{backup-name}/` prefix structure {confidence: 90%}

**Validation Hooks:**

```gherkin
GIVEN Minio S3 endpoint at s3.68cc.io
WHEN Velero initializes S3 backend
THEN bucket `velero-backups` exists
AND access credentials validated successfully
AND HTTPS endpoint configured
```

**Risk Factors:**

- S3 bucket naming conflicts
- Insufficient S3 storage capacity
- Credential permission misconfigurations

---

### REQ-e8a3c7b2-003: PVC Backup Operations

**Intent Vector:** Enable on-demand and scheduled backups of OpenEBS LocalPV PVCs to S3

**User Story:**
As a **home-lab administrator**, I want **to create backups of specific PVCs on-demand** so that **I can protect critical data before risky operations**.

**Business Value:** 10/10 | **Complexity:** M

**Acceptance Criteria (EARS Syntax):**

- **AC-e8a3c7b2-003-01:** WHEN `velero backup create` command is executed, the system SHALL initiate file-level backup of specified PVCs within 30 seconds {confidence: 90%}
- **AC-e8a3c7b2-003-02:** WHILE backup is in progress, the system SHALL upload PVC data to S3 using Restic with progress tracking {confidence: 85%}
- **AC-e8a3c7b2-003-03:** IF backup completes successfully, the system SHALL update Backup CRD status to "Completed" and log summary {confidence: 95%}
- **AC-e8a3c7b2-003-04:** WHERE backup includes PVC with 10GB data, the system SHALL complete backup within 15 minutes on home-lab network {confidence: 80%}
- **AC-e8a3c7b2-003-05:** IF backup fails, the system SHALL update Backup CRD status to "Failed" with error details and retain partial data {confidence: 90%}

**Validation Hooks:**

```gherkin
GIVEN OpenEBS LocalPV PVC with test data
WHEN velero backup create test-backup --include-namespaces=test
THEN Backup CRD created with Phase=InProgress
AND Restic uploads data to S3
AND Backup CRD transitions to Phase=Completed
AND S3 object exists at velero-backups/backups/test-backup/
```

**Risk Factors:**

- Network bandwidth limitations during large backups
- Restic pod resource exhaustion
- Concurrent backup conflicts

---

### REQ-e8a3c7b2-004: PVC Restore Operations

**Intent Vector:** Enable restoration of PVCs from S3 backups to any namespace

**User Story:**
As a **home-lab administrator**, I want **to restore PVCs from S3 backups** so that **I can recover from data loss or migrate workloads**.

**Business Value:** 10/10 | **Complexity:** M

**Acceptance Criteria (EARS Syntax):**

- **AC-e8a3c7b2-004-01:** WHEN `velero restore create` command is executed, the system SHALL fetch backup metadata from S3 within 10 seconds {confidence: 90%}
- **AC-e8a3c7b2-004-02:** WHILE restore is in progress, the system SHALL recreate PVCs with data downloaded from S3 via Restic {confidence: 85%}
- **AC-e8a3c7b2-004-03:** IF restore completes successfully, the system SHALL create PVC in target namespace with identical data to original {confidence: 90%}
- **AC-e8a3c7b2-004-04:** WHERE restored PVC contains 10GB data, the system SHALL complete restore within 20 minutes on home-lab network {confidence: 75%}
- **AC-e8a3c7b2-004-05:** IF original namespace is deleted, the system SHALL support restore to different namespace with namespace mapping {confidence: 85%}

**Validation Hooks:**

```gherkin
GIVEN existing backup in S3 (test-backup)
WHEN velero restore create --from-backup=test-backup
THEN Restore CRD created with Phase=InProgress
AND PVC recreated in target namespace
AND Restic downloads data from S3
AND Restore CRD transitions to Phase=Completed
AND PVC data matches original checksum
```

**Risk Factors:**

- S3 download bandwidth limitations
- Storage class availability in target cluster
- Data corruption during transfer

---

### REQ-e8a3c7b2-005: Automated Backup Scheduling

**Intent Vector:** Configure automatic daily backups with retention policies

**User Story:**
As a **home-lab administrator**, I want **automated daily backups of critical namespaces** so that **I don't need to manually trigger backups and have point-in-time recovery options**.

**Business Value:** 9/10 | **Complexity:** S

**Acceptance Criteria (EARS Syntax):**

- **AC-e8a3c7b2-005-01:** WHEN Schedule CRD is created with cron expression `0 2 * * *`, the system SHALL trigger backups daily at 02:00 UTC {confidence: 95%}
- **AC-e8a3c7b2-005-02:** WHILE schedule is active, the system SHALL create backups automatically without manual intervention {confidence: 95%}
- **AC-e8a3c7b2-005-03:** WHERE schedule defines namespaces (monitoring, database, network), the system SHALL include only specified namespaces in backups {confidence: 90%}
- **AC-e8a3c7b2-005-04:** IF scheduled backup fails, the system SHALL log error and retry next scheduled time (not block future backups) {confidence: 85%}

**Validation Hooks:**

```gherkin
GIVEN Schedule CRD with daily cron schedule
WHEN schedule time arrives (02:00 UTC)
THEN new Backup CRD created automatically
AND backup includes specified namespaces
AND backup uploads to S3
```

**Risk Factors:**

- Cron schedule timezone misconfigurations
- Concurrent scheduled backups
- Missed backup windows during maintenance

---

### REQ-e8a3c7b2-006: Backup Retention and Cleanup

**Intent Vector:** Automatically delete old backups from S3 after retention period expires

**User Story:**
As a **home-lab administrator**, I want **automatic deletion of backups older than 30 days** so that **S3 storage costs remain manageable and stale backups don't accumulate**.

**Business Value:** 7/10 | **Complexity:** S

**Acceptance Criteria (EARS Syntax):**

- **AC-e8a3c7b2-006-01:** WHEN backup is created, the system SHALL set TTL metadata to 30 days (720 hours) {confidence: 95%}
- **AC-e8a3c7b2-006-02:** WHILE Velero garbage collector runs (hourly), the system SHALL identify backups exceeding TTL {confidence: 90%}
- **AC-e8a3c7b2-006-03:** WHERE backup TTL is exceeded, the system SHALL delete Backup CRD and remove S3 objects within 1 hour {confidence: 85%}
- **AC-e8a3c7b2-006-04:** IF manual backup is created without TTL, the system SHALL apply default 30-day retention {confidence: 90%}

**Validation Hooks:**

```gherkin
GIVEN backup older than 30 days
WHEN Velero garbage collector runs
THEN expired backup identified
AND Backup CRD deleted
AND S3 objects removed from velero-backups bucket
```

**Risk Factors:**

- Accidental deletion of important backups
- S3 object deletion failures leaving orphaned data
- Garbage collector not running

---

### REQ-e8a3c7b2-007: GitOps Integration

**Intent Vector:** Manage Velero deployment through FluxCD with SOPS-encrypted secrets

**User Story:**
As a **home-lab administrator**, I want **Velero configuration managed via FluxCD** so that **backup infrastructure is version-controlled and declaratively managed**.

**Business Value:** 8/10 | **Complexity:** S

**Acceptance Criteria (EARS Syntax):**

- **AC-e8a3c7b2-007-01:** WHEN Velero configuration is committed to Git, the system SHALL deploy via FluxCD HelmRelease within 5 minutes {confidence: 95%}
- **AC-e8a3c7b2-007-02:** WHERE S3 credentials are required, the system SHALL store them in SOPS-encrypted secret (velero-s3-secret) {confidence: 100%}
- **AC-e8a3c7b2-007-03:** IF HelmRelease is updated, the system SHALL reconcile Velero deployment automatically via FluxCD {confidence: 90%}
- **AC-e8a3c7b2-007-04:** WHILE GitOps manages deployment, the system SHALL follow pattern: velero/ks.yaml + velero/app/kustomization.yaml + velero/app/helmrelease.yaml {confidence: 95%}

**Validation Hooks:**

```gherkin
GIVEN Velero HelmRelease in Git repository
WHEN FluxCD reconciles kustomization
THEN Velero deployed to cluster
AND SOPS secret decrypted and applied
AND HelmRelease status shows Ready=True
```

**Risk Factors:**

- SOPS decryption key unavailable
- FluxCD reconciliation failures
- Git repository connectivity issues

---

## Non-functional Requirements (EARS Format)

### NFR-e8a3c7b2-PERF-001: Backup Performance

WHEN backing up 10GB PVC, the system SHALL complete within 15 minutes over home-lab network {confidence: 80%}

### NFR-e8a3c7b2-PERF-002: Restore Performance

WHEN restoring 10GB PVC, the system SHALL complete within 20 minutes over home-lab network {confidence: 75%}

### NFR-e8a3c7b2-SEC-001: Credential Security

WHERE S3 credentials are stored, the system SHALL encrypt using SOPS with age keys before Git commit {confidence: 100%}

### NFR-e8a3c7b2-SEC-002: S3 Transport Security

WHILE communicating with S3, the system SHALL use HTTPS transport exclusively (s3.68cc.io) {confidence: 95%}

### NFR-e8a3c7b2-RELIABILITY-001: Backup Success Rate

OVER 30-day period, the system SHALL achieve ≥95% success rate for scheduled backups {confidence: 85%}

### NFR-e8a3c7b2-RELIABILITY-002: Data Integrity

IF PVC is restored from backup, the system SHALL guarantee 100% data integrity (checksums match) {confidence: 90%}

### NFR-e8a3c7b2-RESOURCE-001: Resource Efficiency

WHILE Restic daemonset runs, the system SHALL consume <500MB memory and <0.5 CPU per node {confidence: 80%}

### NFR-e8a3c7b2-OBSERVABILITY-001: Backup Monitoring

WHEN backup operations occur, the system SHALL emit metrics to Prometheus for Grafana dashboard {confidence: 85%}

---

## Traceability Manifest

**Upstream Dependencies:**

- OpenEBS LocalPV Provisioner (openebs-localpv-hostpath storageclass)
- Minio S3 endpoint (s3.68cc.io with HTTPS)
- FluxCD GitOps system (HelmRelease CRD)
- SOPS encryption (age keys)

**Downstream Impact:**

- CloudNative-PG database backups (current: S3 direct, future: Velero fallback)
- LGTM stack data persistence (Loki/Tempo/Mimir S3 backends)
- Stateful workload disaster recovery (all OpenEBS LocalPV PVCs)

**Coverage:**

- Functional Requirements: 7 (all critical backup/restore operations)
- Non-Functional Requirements: 8 (performance, security, reliability, observability)
- EARS Acceptance Criteria: 28 (all measurable and testable)
- Confidence Score: 89% average across all AC

**Risk Summary:**

- High: Network bandwidth limitations (mitigated by home-lab scale)
- Medium: S3 storage capacity (monitored via Minio dashboard)
- Medium: Restic resource contention (mitigated by home-lab workload scale)
- Low: SOPS decryption failures (mitigated by FluxCD validation)
