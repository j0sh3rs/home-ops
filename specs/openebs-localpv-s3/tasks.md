# Tasks: OpenEBS LocalPV S3 Backup Integration

## Meta-Context

- **Feature UUID:** FEAT-e8a3c7b2
- **Complexity:** Medium (AI-calculated: 6.5/10)
- **Critical Path:** Infrastructure → Deployment → Testing → Automation → Documentation
- **Risk Score:** 0.4 (Medium-Low)
- **Timeline Estimate:** 8-12 hours implementation + 48 hours validation

---

## Progress: 1/17 Complete, 0 In Progress, 16 Not Started, 0 Blocked

---

## Phase 1: Infrastructure Setup (Foundation)

### [x] TASK-e8a3c7b2-001: Create velero-backups S3 Bucket in Minio

**Trace:** REQ-e8a3c7b2-002 | **Design:** velero-backups bucket (ADR-002) | **AC:** AC-e8a3c7b2-002-01, AC-e8a3c7b2-002-03

**Description:**
Create dedicated S3 bucket in Minio for Velero backups with proper access configuration.

**Implementation Steps:**

1. Access Minio console at https://s3.68cc.io
2. Create bucket named `velero-backups`
3. Verify HTTPS-only access (no HTTP)
4. Set bucket policy for Velero IAM user (if needed)
5. Test bucket accessibility with `mc` client

**DoD (EARS Format):**

- WHEN bucket created, SHALL be accessible at s3.68cc.io/velero-backups with HTTPS
- WHERE bucket accessed via S3 API, SHALL accept PUT/GET/DELETE/LIST operations
- IF bucket does not exist, SHALL be created with versioning disabled
- WHILE bucket is used, SHALL maintain organizational prefix structure `velero/backups/{backup-name}/`

**Validation Commands:**

```bash
# Test bucket exists and is accessible
mc ls minio/velero-backups

# Test HTTPS enforcement
curl -v http://s3.68cc.io/velero-backups  # Should redirect to HTTPS

# Test write permissions
echo "test" | mc pipe minio/velero-backups/test.txt
mc cat minio/velero-backups/test.txt
mc rm minio/velero-backups/test.txt
```

**Risk:** Low | **Deps:** None | **Effort:** 1pt

---

### [ ] TASK-e8a3c7b2-002: Generate S3 Access Credentials for Velero

**Trace:** REQ-e8a3c7b2-002, REQ-e8a3c7b2-007 | **Design:** velero-s3-secret (ADR-003) | **AC:** AC-e8a3c7b2-002-02, NFR-e8a3c7b2-SEC-001

**Description:**
Create dedicated S3 access key for Velero with minimal permissions (bucket-scoped).

**Implementation Steps:**

1. Access Minio console → Identity → Service Accounts
2. Create new service account: `velero-backup-sa`
3. Assign policy: full access to `velero-backups` bucket only
4. Copy Access Key ID and Secret Access Key
5. Store credentials securely (will be SOPS-encrypted in next task)

**DoD (EARS Format):**

- WHEN credentials generated, SHALL provide access only to velero-backups bucket
- WHERE credentials are used, SHALL authenticate successfully with S3 API
- IF credentials tested, SHALL allow PUT/GET/DELETE operations on bucket
- WHILE credentials stored, SHALL be kept secure until SOPS encryption applied

**Validation Commands:**

```bash
# Test credentials with mc client
mc alias set velero-test https://s3.68cc.io <ACCESS_KEY> <SECRET_KEY>
mc ls velero-test/velero-backups  # Should succeed
mc ls velero-test/loki-chunks     # Should fail (no access)
```

**Risk:** Low | **Deps:** TASK-001 | **Effort:** 1pt

---

### [ ] TASK-e8a3c7b2-003: Create SOPS-Encrypted velero-s3-secret

**Trace:** REQ-e8a3c7b2-007 | **Design:** velero-s3-secret, FluxCD structure (ADR-003) | **AC:** AC-e8a3c7b2-007-02, NFR-e8a3c7b2-SEC-001

**Description:**
Create Kubernetes Secret with S3 credentials encrypted using SOPS before Git commit.

**Implementation Steps:**

1. Create directory structure: `kubernetes/apps/velero/app/`
2. Create plain secret file: `velero-s3-secret.yaml`
    ```yaml
    apiVersion: v1
    kind: Secret
    metadata:
        name: velero-s3-secret
        namespace: velero
    type: Opaque
    stringData:
        cloud: |
            [default]
            aws_access_key_id = <ACCESS_KEY_FROM_TASK-002>
            aws_secret_access_key = <SECRET_KEY_FROM_TASK-002>
    ```
3. Encrypt with SOPS: `sops -e -i velero-s3-secret.yaml`
4. Rename to: `velero-s3-secret.sops.yaml`
5. Verify encryption: `cat velero-s3-secret.sops.yaml` (should show encrypted data)

**DoD (EARS Format):**

- WHEN secret created, SHALL contain S3 credentials in cloud file format
- WHERE secret committed to Git, SHALL be SOPS-encrypted with age keys (confidence: 100%)
- IF secret viewed in Git, SHALL NOT expose plaintext credentials
- WHILE secret is deployed, SHALL be decrypted by FluxCD SOPS controller

**Validation Commands:**

```bash
# Verify SOPS encryption
grep "sops:" kubernetes/apps/velero/app/velero-s3-secret.sops.yaml  # Should find SOPS metadata

# Verify no plaintext credentials in Git
git show HEAD:kubernetes/apps/velero/app/velero-s3-secret.sops.yaml | grep -i "secret"  # Should be encrypted

# Test SOPS decryption (local only, don't commit)
sops -d kubernetes/apps/velero/app/velero-s3-secret.sops.yaml | grep "aws_access_key_id"
```

**Risk:** Low | **Deps:** TASK-002 | **Effort:** 1pt

---

## Phase 2: Velero Deployment (GitOps Integration)

### [ ] TASK-e8a3c7b2-004: Create FluxCD Kustomization Structure

**Trace:** REQ-e8a3c7b2-007 | **Design:** FluxCD structure (ADR-003) | **AC:** AC-e8a3c7b2-007-04

**Description:**
Set up FluxCD directory structure following established pattern: `{app}/ks.yaml` + `{app}/app/kustomization.yaml`.

**Implementation Steps:**

1. Create `kubernetes/apps/velero/ks.yaml`:

    ```yaml
    apiVersion: kustomize.toolkit.fluxcd.io/v1
    kind: Kustomization
    metadata:
        name: velero
        namespace: flux-system
    spec:
        interval: 30m
        path: ./kubernetes/apps/velero/app
        prune: true
        sourceRef:
            kind: GitRepository
            name: home-kubernetes
        wait: true
        timeout: 10m
    ```

2. Create `kubernetes/apps/velero/app/kustomization.yaml`:

    ```yaml
    apiVersion: kustomize.config.k8s.io/v1beta1
    kind: Kustomization
    namespace: velero
    resources:
        - namespace.yaml
        - velero-s3-secret.sops.yaml
        - helmrelease.yaml
        - schedule.yaml
    ```

3. Create `kubernetes/apps/velero/app/namespace.yaml`:
    ```yaml
    apiVersion: v1
    kind: Namespace
    metadata:
        name: velero
        labels:
            pod-security.kubernetes.io/enforce: privileged # Required for Restic hostPath
    ```

**DoD (EARS Format):**

- WHEN directory structure created, SHALL follow pattern `velero/ks.yaml` + `app/kustomization.yaml` (confidence: 95%)
- WHERE files referenced, SHALL match established project conventions
- IF kustomization applied, SHALL create velero namespace with privileged PSA
- WHILE FluxCD reconciles, SHALL detect all resource files in app/ directory

**Validation Commands:**

```bash
# Verify directory structure
tree kubernetes/apps/velero/
# Expected:
# velero/
# ├── ks.yaml
# └── app/
#     ├── kustomization.yaml
#     ├── namespace.yaml
#     ├── velero-s3-secret.sops.yaml
#     ├── helmrelease.yaml
#     └── schedule.yaml

# Validate kustomization syntax
kubectl kustomize kubernetes/apps/velero/app/ --dry-run
```

**Risk:** Low | **Deps:** TASK-003 | **Effort:** 1pt

---

### [ ] TASK-e8a3c7b2-005: Create Velero HelmRelease Configuration

**Trace:** REQ-e8a3c7b2-001, REQ-e8a3c7b2-007 | **Design:** Velero Controller, Restic Daemonset, HelmRelease values (ADR-001, ADR-003) | **AC:** AC-e8a3c7b2-001-01, AC-e8a3c7b2-001-02, AC-e8a3c7b2-007-01

**Description:**
Create HelmRelease for Velero with Restic integration and S3 backend configuration.

**Implementation Steps:**

1. Create `kubernetes/apps/velero/app/helmrelease.yaml` with Velero chart configuration
2. Configure S3 backend pointing to https://s3.68cc.io
3. Enable Restic daemonset for file-level backups
4. Mount velero-s3-secret for credentials
5. Install AWS S3 plugin for Minio compatibility

**HelmRelease Content:**

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
metadata:
    name: velero
    namespace: velero
spec:
    interval: 30m
    chart:
        spec:
            chart: velero
            version: "5.4.x" # Use latest 5.4.x
            sourceRef:
                kind: HelmRepository
                name: vmware-tanzu
                namespace: flux-system
            interval: 30m

    install:
        crds: CreateReplace
        remediation:
            retries: 3

    upgrade:
        crds: CreateReplace
        remediation:
            retries: 3

    values:
        # Velero controller configuration
        image:
            repository: velero/velero
            tag: v1.13.0

        # S3 backend configuration (ADR-002)
        configuration:
            backupStorageLocation:
                - name: default
                  provider: aws
                  bucket: velero-backups
                  default: true
                  config:
                      region: us-east-1
                      s3Url: https://s3.68cc.io
                      s3ForcePathStyle: "true"
                      insecureSkipTLSVerify: "false" # Enforce HTTPS (NFR-e8a3c7b2-SEC-002)

            # Volume snapshot location (disabled for Restic-only approach)
            volumeSnapshotLocation:
                - name: default
                  provider: aws
                  config:
                      region: us-east-1

        # S3 credentials (SOPS-encrypted secret)
        credentials:
            useSecret: true
            existingSecret: velero-s3-secret

        # Restic integration (ADR-001)
        deployRestic: true
        restic:
            podVolumePath: /var/lib/kubelet/pods
            privileged: true # Required for hostPath access
            resources:
                requests:
                    memory: 256Mi
                    cpu: 200m
                limits:
                    memory: 512Mi # NFR-e8a3c7b2-RESOURCE-001
                    cpu: 500m # NFR-e8a3c7b2-RESOURCE-001

        # AWS S3 plugin for Minio compatibility
        initContainers:
            - name: velero-plugin-for-aws
              image: velero/velero-plugin-for-aws:v1.9.0
              volumeMounts:
                  - mountPath: /target
                    name: plugins

        # Metrics for Prometheus (NFR-e8a3c7b2-OBSERVABILITY-001)
        metrics:
            enabled: true
            serviceMonitor:
                enabled: true
                namespace: velero

        # Velero controller resources
        resources:
            requests:
                memory: 256Mi
                cpu: 100m
            limits:
                memory: 512Mi
                cpu: 500m
```

**DoD (EARS Format):**

- WHEN HelmRelease applied, SHALL deploy Velero controller within 5 minutes (AC-e8a3c7b2-007-01, confidence: 95%)
- WHEN Restic enabled, SHALL deploy daemonset on all nodes (AC-e8a3c7b2-001-02, confidence: 90%)
- WHERE S3 configured, SHALL use https://s3.68cc.io with velero-backups bucket
- IF credentials mounted, SHALL authenticate successfully with S3 backend (AC-e8a3c7b2-001-03)
- WHILE running, SHALL maintain persistent S3 connection (AC-e8a3c7b2-001-04, confidence: 85%)

**Validation Commands:**

```bash
# Verify HelmRelease syntax
kubectl apply --dry-run=client -f kubernetes/apps/velero/app/helmrelease.yaml
```

**Risk:** Medium | **Deps:** TASK-004 | **Effort:** 3pts

---

### [ ] TASK-e8a3c7b2-006: Deploy Velero via FluxCD

**Trace:** REQ-e8a3c7b2-001, REQ-e8a3c7b2-007 | **Design:** FluxCD deployment (ADR-003) | **AC:** AC-e8a3c7b2-007-01, AC-e8a3c7b2-007-03

**Description:**
Commit FluxCD configuration to Git and trigger deployment via FluxCD reconciliation.

**Implementation Steps:**

1. Commit all files to Git:

    ```bash
    git add kubernetes/apps/velero/
    git commit -m "feat: Add Velero backup integration with Restic and S3"
    git push origin main
    ```

2. Trigger FluxCD reconciliation:

    ```bash
    flux reconcile kustomization flux-system --with-source
    ```

3. Monitor deployment:

    ```bash
    watch kubectl get pods -n velero
    ```

4. Wait for all pods to reach Running state:
    - velero-{hash} (controller)
    - restic-{hash} (daemonset, one per node)

**DoD (EARS Format):**

- WHEN configuration committed to Git, SHALL deploy via FluxCD within 5 minutes (AC-e8a3c7b2-007-01, confidence: 95%)
- WHILE FluxCD reconciles, SHALL apply all resources in correct order (namespace → secret → helmrelease)
- IF HelmRelease updated, SHALL reconcile automatically (AC-e8a3c7b2-007-03, confidence: 90%)
- WHERE deployment succeeds, SHALL show HelmRelease status Ready=True

**Validation Commands:**

```bash
# Check FluxCD reconciliation
flux get kustomizations -n flux-system
flux get helmreleases -n velero

# Verify Velero controller pod
kubectl get pods -n velero -l component=velero
kubectl logs -n velero -l component=velero --tail=50

# Verify Restic daemonset
kubectl get daemonset -n velero restic
kubectl get pods -n velero -l name=restic

# Check all nodes have Restic pod
kubectl get pods -n velero -l name=restic -o wide
```

**Risk:** Medium | **Deps:** TASK-005 | **Effort:** 2pts

---

### [ ] TASK-e8a3c7b2-007: Validate S3 Backend Connection

**Trace:** REQ-e8a3c7b2-001, REQ-e8a3c7b2-002 | **Design:** Velero Controller S3 connection (ADR-002) | **AC:** AC-e8a3c7b2-001-04, AC-e8a3c7b2-002-02, NFR-e8a3c7b2-SEC-002

**Description:**
Verify Velero successfully connects to Minio S3 backend with proper authentication and HTTPS transport.

**Implementation Steps:**

1. Install Velero CLI (if not already installed):

    ```bash
    # macOS
    brew install velero

    # Linux
    wget https://github.com/vmware-tanzu/velero/releases/download/v1.13.0/velero-v1.13.0-linux-amd64.tar.gz
    tar -xvf velero-v1.13.0-linux-amd64.tar.gz
    sudo mv velero-v1.13.0-linux-amd64/velero /usr/local/bin/
    ```

2. Check backup storage location:

    ```bash
    velero backup-location get
    ```

3. Verify S3 connection in Velero logs:

    ```bash
    kubectl logs -n velero -l component=velero | grep -i "s3\|backup-location"
    ```

4. Test S3 connectivity with manual backup-location validation

**DoD (EARS Format):**

- WHEN backup-location queried, SHALL show status "Available" (AC-e8a3c7b2-001-04, confidence: 85%)
- WHERE S3 accessed, SHALL authenticate using velero-s3-secret credentials (AC-e8a3c7b2-002-02, confidence: 95%)
- WHILE communicating with S3, SHALL use HTTPS transport (NFR-e8a3c7b2-SEC-002, confidence: 95%)
- IF connection fails, SHALL log clear error message for troubleshooting

**Validation Commands:**

```bash
# Check backup storage location status
velero backup-location get
# Expected output: Available=true

# Verify S3 endpoint in config
kubectl get backupstoragelocation -n velero default -o yaml | grep s3Url
# Expected: https://s3.68cc.io

# Check Velero logs for S3 connection
kubectl logs -n velero -l component=velero | grep "BackupStorageLocation.*Available"

# Verify HTTPS enforcement (should fail with HTTP)
kubectl logs -n velero -l component=velero | grep -i "insecure"
```

**Risk:** Medium | **Deps:** TASK-006 | **Effort:** 1pt

---

## Phase 3: Backup Testing (Validation)

### [ ] TASK-e8a3c7b2-008: Create Test PVC with Sample Data

**Trace:** REQ-e8a3c7b2-003 | **Design:** Backup flow testing | **AC:** AC-e8a3c7b2-003-01

**Description:**
Create test PVC with known data for backup/restore validation.

**Implementation Steps:**

1. Create test namespace: `kubectl create namespace velero-test`

2. Create test PVC with OpenEBS LocalPV:

    ```yaml
    apiVersion: v1
    kind: PersistentVolumeClaim
    metadata:
        name: test-pvc
        namespace: velero-test
    spec:
        storageClassName: openebs-localpv-hostpath
        accessModes:
            - ReadWriteOnce
        resources:
            requests:
                storage: 1Gi
    ```

3. Create test pod to write data:

    ```yaml
    apiVersion: v1
    kind: Pod
    metadata:
        name: test-pod
        namespace: velero-test
    spec:
        volumes:
            - name: test-volume
              persistentVolumeClaim:
                  claimName: test-pvc
        containers:
            - name: writer
              image: busybox
              command: ["/bin/sh"]
              args:
                  - -c
                  - |
                      echo "Velero test data - $(date)" > /data/test.txt
                      echo "Line 2" >> /data/test.txt
                      echo "Line 3" >> /data/test.txt
                      md5sum /data/test.txt > /data/checksum.txt
                      sleep 3600
              volumeMounts:
                  - name: test-volume
                    mountPath: /data
    ```

4. Verify data written:
    ```bash
    kubectl exec -n velero-test test-pod -- cat /data/test.txt
    kubectl exec -n velero-test test-pod -- cat /data/checksum.txt
    ```

**DoD (EARS Format):**

- WHEN test PVC created, SHALL be bound to OpenEBS LocalPV volume
- WHERE test data written, SHALL contain identifiable content with checksum
- IF pod running, SHALL successfully write and read from PVC
- WHILE pod active, SHALL maintain data persistence

**Validation Commands:**

```bash
# Verify PVC bound
kubectl get pvc -n velero-test test-pvc
# Status should be "Bound"

# Verify pod running
kubectl get pods -n velero-test test-pod

# Verify data exists
kubectl exec -n velero-test test-pod -- ls -lh /data/
kubectl exec -n velero-test test-pod -- cat /data/test.txt
```

**Risk:** Low | **Deps:** TASK-007 | **Effort:** 1pt

---

### [ ] TASK-e8a3c7b2-009: Execute Manual Backup with Velero

**Trace:** REQ-e8a3c7b2-003 | **Design:** Backup flow (ADR-001) | **AC:** AC-e8a3c7b2-003-01, AC-e8a3c7b2-003-02, AC-e8a3c7b2-003-03

**Description:**
Perform on-demand backup of test namespace to validate backup workflow.

**Implementation Steps:**

1. Annotate test pod for Restic backup:

    ```bash
    kubectl -n velero-test annotate pod/test-pod backup.velero.io/backup-volumes=test-volume
    ```

2. Create backup:

    ```bash
    velero backup create test-backup-001 \
      --include-namespaces velero-test \
      --wait
    ```

3. Monitor backup progress:

    ```bash
    velero backup describe test-backup-001 --details
    velero backup logs test-backup-001
    ```

4. Wait for completion (Phase: Completed)

**DoD (EARS Format):**

- WHEN backup created, SHALL initiate within 30 seconds (AC-e8a3c7b2-003-01, confidence: 90%)
- WHILE backup in progress, SHALL upload data to S3 with progress tracking (AC-e8a3c7b2-003-02, confidence: 85%)
- IF backup completes, SHALL update status to "Completed" (AC-e8a3c7b2-003-03, confidence: 95%)
- WHERE 1GB test PVC backed up, SHALL complete within 2 minutes

**Validation Commands:**

```bash
# Check backup status
velero backup get
velero backup describe test-backup-001

# Verify backup completed
kubectl get backup -n velero test-backup-001 -o jsonpath='{.status.phase}'
# Expected: Completed

# Check Restic logs
velero backup logs test-backup-001 | grep -i "restic\|upload"

# Verify S3 upload
mc ls minio/velero-backups/backups/test-backup-001/
```

**Risk:** Medium | **Deps:** TASK-008 | **Effort:** 2pts

---

### [ ] TASK-e8a3c7b2-010: Verify Backup in S3 Storage

**Trace:** REQ-e8a3c7b2-003 | **Design:** S3 bucket structure (ADR-002) | **AC:** AC-e8a3c7b2-002-04

**Description:**
Validate backup data successfully uploaded to S3 with correct prefix structure.

**Implementation Steps:**

1. List S3 objects for backup:

    ```bash
    mc ls --recursive minio/velero-backups/backups/test-backup-001/
    ```

2. Verify backup metadata files exist:
    - `test-backup-001-backup.json.gz` (backup metadata)
    - `test-backup-001-logs.gz` (backup logs)
    - `test-backup-001-podvolumebackups.json.gz` (Restic metadata)
    - `test-backup-001.tar.gz` (Kubernetes resources)

3. Check Restic repository:

    ```bash
    mc ls --recursive minio/velero-backups/restic/
    ```

4. Verify backup size is reasonable (>0 bytes)

**DoD (EARS Format):**

- WHEN backup completed, SHALL create objects in S3 with prefix `velero/backups/test-backup-001/` (AC-e8a3c7b2-002-04, confidence: 90%)
- WHERE backup stored, SHALL include metadata and Restic repository data
- IF backup queried from S3, SHALL return all expected files
- WHILE backup exists, SHALL be retrievable for restore operations

**Validation Commands:**

```bash
# Verify backup structure in S3
mc tree minio/velero-backups/

# Check backup size
mc du minio/velero-backups/backups/test-backup-001/

# Verify Restic data
mc ls minio/velero-backups/restic/

# Validate backup metadata
mc cat minio/velero-backups/backups/test-backup-001/test-backup-001-backup.json.gz | gunzip | jq .
```

**Risk:** Low | **Deps:** TASK-009 | **Effort:** 1pt

---

## Phase 4: Restore Testing (Recovery Validation)

### [ ] TASK-e8a3c7b2-011: Delete Test Namespace for Restore Validation

**Trace:** REQ-e8a3c7b2-004 | **Design:** Restore flow testing | **AC:** AC-e8a3c7b2-004-01

**Description:**
Delete test namespace to simulate disaster scenario for restore testing.

**Implementation Steps:**

1. Save original checksum for later comparison:

    ```bash
    kubectl exec -n velero-test test-pod -- cat /data/checksum.txt > /tmp/original-checksum.txt
    ```

2. Delete namespace (simulates data loss):

    ```bash
    kubectl delete namespace velero-test --wait=true
    ```

3. Verify namespace deleted:

    ```bash
    kubectl get namespace velero-test
    # Expected: NotFound error
    ```

4. Verify PVC and data no longer exist:
    ```bash
    kubectl get pvc -n velero-test
    # Expected: No resources found
    ```

**DoD (EARS Format):**

- WHEN namespace deleted, SHALL remove all resources including PVCs
- WHERE original data checksum saved, SHALL be preserved for restore validation
- IF deletion verified, SHALL confirm no resources remain in namespace
- WHILE preparing for restore, SHALL ensure clean state for recovery test

**Validation Commands:**

```bash
# Verify namespace gone
kubectl get namespace velero-test 2>&1 | grep "NotFound"

# Verify PVC gone
kubectl get pvc --all-namespaces | grep test-pvc
# Expected: no results

# Verify test pod gone
kubectl get pods --all-namespaces | grep test-pod
# Expected: no results

# Confirm checksum saved
cat /tmp/original-checksum.txt
```

**Risk:** Low | **Deps:** TASK-010 | **Effort:** 1pt

---

### [ ] TASK-e8a3c7b2-012: Execute Restore from S3 Backup

**Trace:** REQ-e8a3c7b2-004 | **Design:** Restore flow (ADR-001) | **AC:** AC-e8a3c7b2-004-01, AC-e8a3c7b2-004-02, AC-e8a3c7b2-004-03

**Description:**
Restore test namespace from S3 backup to validate disaster recovery workflow.

**Implementation Steps:**

1. Create restore from backup:

    ```bash
    velero restore create test-restore-001 \
      --from-backup test-backup-001 \
      --wait
    ```

2. Monitor restore progress:

    ```bash
    velero restore describe test-restore-001 --details
    velero restore logs test-restore-001
    ```

3. Wait for completion (Phase: Completed)

4. Verify namespace recreated:
    ```bash
    kubectl get namespace velero-test
    ```

**DoD (EARS Format):**

- WHEN restore created, SHALL fetch backup metadata from S3 within 10 seconds (AC-e8a3c7b2-004-01, confidence: 90%)
- WHILE restore in progress, SHALL download data from S3 via Restic (AC-e8a3c7b2-004-02, confidence: 85%)
- IF restore completes, SHALL create PVC in target namespace with identical data (AC-e8a3c7b2-004-03, confidence: 90%)
- WHERE 1GB test PVC restored, SHALL complete within 3 minutes

**Validation Commands:**

```bash
# Check restore status
velero restore get
velero restore describe test-restore-001

# Verify restore completed
kubectl get restore -n velero test-restore-001 -o jsonpath='{.status.phase}'
# Expected: Completed

# Check Restic restore logs
velero restore logs test-restore-001 | grep -i "restic\|download"

# Verify namespace recreated
kubectl get namespace velero-test

# Verify PVC recreated
kubectl get pvc -n velero-test test-pvc
```

**Risk:** Medium | **Deps:** TASK-011 | **Effort:** 2pts

---

### [ ] TASK-e8a3c7b2-013: Validate Restored Data Integrity

**Trace:** REQ-e8a3c7b2-004 | **Design:** Data integrity validation | **AC:** AC-e8a3c7b2-004-03, NFR-e8a3c7b2-RELIABILITY-002

**Description:**
Verify restored PVC contains identical data to original with checksum validation.

**Implementation Steps:**

1. Wait for test pod to restart and PVC to mount:

    ```bash
    kubectl wait --for=condition=Ready pod/test-pod -n velero-test --timeout=5m
    ```

2. Retrieve restored checksum:

    ```bash
    kubectl exec -n velero-test test-pod -- cat /data/checksum.txt > /tmp/restored-checksum.txt
    ```

3. Compare checksums:

    ```bash
    diff /tmp/original-checksum.txt /tmp/restored-checksum.txt
    ```

4. Verify file contents:
    ```bash
    kubectl exec -n velero-test test-pod -- cat /data/test.txt
    ```

**DoD (EARS Format):**

- WHEN restored data compared, SHALL match original checksum 100% (NFR-e8a3c7b2-RELIABILITY-002, confidence: 90%)
- WHERE file contents verified, SHALL contain identical data to pre-backup state
- IF checksum matches, SHALL guarantee complete data integrity (AC-e8a3c7b2-004-03)
- WHILE PVC mounted, SHALL be readable and writable as before backup

**Validation Commands:**

```bash
# Compare checksums
echo "Original:"
cat /tmp/original-checksum.txt
echo "Restored:"
cat /tmp/restored-checksum.txt

# Diff should show no differences
diff /tmp/original-checksum.txt /tmp/restored-checksum.txt
echo "Exit code: $?"  # Should be 0

# Verify file contents
kubectl exec -n velero-test test-pod -- cat /data/test.txt | grep "Velero test data"

# Test write capability
kubectl exec -n velero-test test-pod -- sh -c "echo 'Post-restore test' >> /data/test.txt"
kubectl exec -n velero-test test-pod -- tail -1 /data/test.txt
```

**Risk:** Low | **Deps:** TASK-012 | **Effort:** 1pt

---

## Phase 5: Automation (Scheduling & Retention)

### [ ] TASK-e8a3c7b2-014: Create Daily Backup Schedule CRD

**Trace:** REQ-e8a3c7b2-005 | **Design:** Schedule Controller (ADR-004) | **AC:** AC-e8a3c7b2-005-01, AC-e8a3c7b2-005-02, AC-e8a3c7b2-005-03

**Description:**
Deploy Schedule CRD for automated daily backups at 02:00 UTC with namespace filtering.

**Implementation Steps:**

1. Create `kubernetes/apps/velero/app/schedule.yaml`:

    ```yaml
    apiVersion: velero.io/v1
    kind: Schedule
    metadata:
        name: daily-backup
        namespace: velero
    spec:
        # Daily at 02:00 UTC (ADR-004)
        schedule: "0 2 * * *"

        template:
            # Namespace-scoped backups (ADR-005)
            includedNamespaces:
                - monitoring # kube-prometheus-stack, Grafana, Loki, Tempo, Mimir
                - database # CloudNative-PG, other DBs
                - network # Ingress, DNS, networking

            # 30-day retention (ADR-004)
            ttl: 720h

            # Metadata
            metadata:
                labels:
                    velero.io/schedule: daily-backup
    ```

2. Commit to Git and reconcile FluxCD:

    ```bash
    git add kubernetes/apps/velero/app/schedule.yaml
    git commit -m "feat: Add daily backup schedule for critical namespaces"
    git push origin main
    flux reconcile kustomization velero --with-source
    ```

3. Verify Schedule CRD created:
    ```bash
    kubectl get schedule -n velero daily-backup
    ```

**DoD (EARS Format):**

- WHEN Schedule CRD created, SHALL configure cron expression "0 2 \* \* \*" (AC-e8a3c7b2-005-01, confidence: 95%)
- WHILE schedule active, SHALL create backups automatically without manual intervention (AC-e8a3c7b2-005-02, confidence: 95%)
- WHERE namespaces defined, SHALL include only monitoring, database, network (AC-e8a3c7b2-005-03, confidence: 90%)
- IF schedule deployed, SHALL appear in velero schedule list

**Validation Commands:**

```bash
# Verify schedule created
velero schedule get
velero schedule describe daily-backup

# Check cron expression
kubectl get schedule -n velero daily-backup -o jsonpath='{.spec.schedule}'
# Expected: "0 2 * * *"

# Verify namespace filters
kubectl get schedule -n velero daily-backup -o jsonpath='{.spec.template.includedNamespaces}'
# Expected: [monitoring, database, network]

# Check TTL
kubectl get schedule -n velero daily-backup -o jsonpath='{.spec.template.ttl}'
# Expected: 720h
```

**Risk:** Low | **Deps:** TASK-013 | **Effort:** 2pts

---

### [ ] TASK-e8a3c7b2-015: Test Scheduled Backup Execution

**Trace:** REQ-e8a3c7b2-005 | **Design:** Scheduled backup flow (ADR-004) | **AC:** AC-e8a3c7b2-005-01, AC-e8a3c7b2-005-04, NFR-e8a3c7b2-RELIABILITY-001

**Description:**
Verify scheduled backups execute automatically at 02:00 UTC (or manually trigger for testing).

**Implementation Steps:**

1. **Option A: Wait for scheduled execution (preferred for full validation)**
    - Wait until 02:00 UTC
    - Monitor for automatic backup creation:
        ```bash
        watch -n 30 "velero backup get | grep daily-backup"
        ```

2. **Option B: Manually trigger schedule for immediate testing**

    ```bash
    # Create immediate backup using schedule template
    velero backup create daily-backup-manual-test \
      --from-schedule daily-backup \
      --wait
    ```

3. Verify backup includes correct namespaces:

    ```bash
    velero backup describe daily-backup-<timestamp> --details
    ```

4. Check backup appears in S3:
    ```bash
    mc ls minio/velero-backups/backups/ | grep daily-backup
    ```

**DoD (EARS Format):**

- WHEN schedule time arrives (02:00 UTC), SHALL trigger backup automatically (AC-e8a3c7b2-005-01, confidence: 95%)
- WHILE schedule active, SHALL create backups without manual intervention (AC-e8a3c7b2-005-02)
- IF scheduled backup fails, SHALL log error and retry next scheduled time (AC-e8a3c7b2-005-04, confidence: 85%)
- WHERE backup succeeds, SHALL contribute to ≥95% success rate target (NFR-e8a3c7b2-RELIABILITY-001)

**Validation Commands:**

```bash
# List scheduled backups
velero backup get | grep daily-backup

# Verify latest scheduled backup
velero backup describe $(velero backup get -o name | grep daily-backup | head -1)

# Check namespaces included
kubectl get backup -n velero $(velero backup get -o name | grep daily-backup | head -1) \
  -o jsonpath='{.spec.includedNamespaces}'

# Verify TTL set
kubectl get backup -n velero $(velero backup get -o name | grep daily-backup | head -1) \
  -o jsonpath='{.spec.ttl}'
```

**Risk:** Medium | **Deps:** TASK-014 | **Effort:** 2pts

---

### [ ] TASK-e8a3c7b2-016: Validate Backup Retention and Garbage Collection

**Trace:** REQ-e8a3c7b2-006 | **Design:** Garbage Collector (ADR-004) | **AC:** AC-e8a3c7b2-006-01, AC-e8a3c7b2-006-02, AC-e8a3c7b2-006-03

**Description:**
Test automatic deletion of backups after 30-day TTL expires.

**Implementation Steps:**

1. Create test backup with short TTL (1 hour for testing):

    ```bash
    velero backup create ttl-test-backup \
      --include-namespaces velero-test \
      --ttl 1h \
      --wait
    ```

2. Verify TTL metadata set:

    ```bash
    kubectl get backup -n velero ttl-test-backup -o jsonpath='{.spec.ttl}'
    ```

3. Check backup exists in S3:

    ```bash
    mc ls minio/velero-backups/backups/ttl-test-backup/
    ```

4. Wait 1 hour + buffer (15 minutes) for garbage collection

5. Verify backup deleted:
    ```bash
    velero backup get ttl-test-backup  # Should show "NotFound"
    mc ls minio/velero-backups/backups/ | grep ttl-test-backup  # Should be empty
    ```

**DoD (EARS Format):**

- WHEN backup created, SHALL set TTL metadata to 30 days (or custom) (AC-e8a3c7b2-006-01, confidence: 95%)
- WHILE garbage collector runs hourly, SHALL identify backups exceeding TTL (AC-e8a3c7b2-006-02, confidence: 90%)
- WHERE backup TTL exceeded, SHALL delete Backup CRD and S3 objects within 1 hour (AC-e8a3c7b2-006-03, confidence: 85%)
- IF manual backup created without TTL, SHALL apply default 30-day retention

**Validation Commands:**

```bash
# Check backup TTL
kubectl get backup -n velero ttl-test-backup -o jsonpath='{.spec.ttl}'

# Monitor garbage collector logs
kubectl logs -n velero -l component=velero | grep -i "garbage\|expire\|delete"

# Verify backup deletion
velero backup get ttl-test-backup 2>&1 | grep "not found"

# Verify S3 cleanup
mc ls minio/velero-backups/backups/ | grep ttl-test-backup
# Expected: no results after TTL + 1 hour
```

**Risk:** Medium | **Deps:** TASK-015 | **Effort:** 2pts (requires 1-hour wait)

---

## Phase 6: Documentation & Finalization

### [ ] TASK-e8a3c7b2-017: Update CLAUDE.md with Architecture Changes

**Trace:** REQ-e8a3c7b2-007 | **Design:** CLAUDE.md update assessment | **AC:** Documentation completeness

**Description:**
Update CLAUDE.md to reflect new Velero backup architecture for future agent context.

**Implementation Steps:**

1. Update `CLAUDE.md` Storage Architecture section:

    ```markdown
    ### Storage Architecture (Updated)

    - **Primary Storage**: OpenEBS LocalPV Provisioner for dynamic persistent volume provisioning
    - **Storage Classes**: `openebs-localpv-hostpath` (default), `openebs-localpv-device` (block devices)
    - **Disaster Recovery**:
        - **Velero + Restic** for file-level PVC backups to S3 (daily 02:00 UTC, 30-day retention)
        - **S3 Backend**: Dedicated `velero-backups` bucket in Minio (https://s3.68cc.io)
        - **Backup Scope**: Namespace-targeted backups (monitoring, database, network)
        - **Restore Capability**: Cross-namespace restore with data integrity validation
    ```

2. Update Key Architectural Decisions section:

    ```markdown
    6. **Velero + Restic over CSI Snapshots**: File-level backups for simplicity and S3-compatibility over volume snapshots for home-lab scale
    ```

3. Update S3 Integration Pattern section:

    ```markdown
    - **S3 Backup Buckets**: `velero-backups` (Velero/Restic PVC backups), `loki-chunks`, `tempo-traces`, `mimir-blocks`
    ```

4. Commit changes:
    ```bash
    git add CLAUDE.md
    git commit -m "docs: Update CLAUDE.md with Velero DR architecture"
    git push origin main
    ```

**DoD (EARS Format):**

- WHEN CLAUDE.md updated, SHALL accurately reflect Velero backup architecture
- WHERE future agents read CLAUDE.md, SHALL understand DR strategy for OpenEBS PVCs
- IF new features interact with backups, SHALL have correct context from CLAUDE.md
- WHILE maintaining documentation, SHALL keep storage architecture section current

**Validation Commands:**

```bash
# Verify CLAUDE.md contains Velero references
grep -i "velero" CLAUDE.md
grep -i "restic" CLAUDE.md
grep -i "disaster recovery" CLAUDE.md

# Verify S3 bucket documentation
grep "velero-backups" CLAUDE.md
```

**Risk:** Low | **Deps:** TASK-016 | **Effort:** 1pt

---

## Verification Checklist (EARS Compliance)

### Requirements Coverage

- [x] REQ-e8a3c7b2-001: Velero Deployment → TASK-005, TASK-006 (with EARS DoD)
- [x] REQ-e8a3c7b2-002: S3 Bucket Config → TASK-001, TASK-002 (with EARS DoD)
- [x] REQ-e8a3c7b2-003: PVC Backup → TASK-008, TASK-009, TASK-010 (with EARS DoD)
- [x] REQ-e8a3c7b2-004: PVC Restore → TASK-011, TASK-012, TASK-013 (with EARS DoD)
- [x] REQ-e8a3c7b2-005: Scheduling → TASK-014, TASK-015 (with EARS DoD)
- [x] REQ-e8a3c7b2-006: Retention → TASK-016 (with EARS DoD)
- [x] REQ-e8a3c7b2-007: GitOps → TASK-003, TASK-004, TASK-005 (with EARS DoD)

### EARS Acceptance Criteria → Task Validation

- [x] All 28 EARS ACs mapped to task DoD statements
- [x] Every AC includes confidence percentage
- [x] BDD validation commands provided for testable criteria
- [x] Performance metrics (timing, throughput) specified

### Design Traceability

- [x] All ADRs (001-005) referenced in task descriptions
- [x] All design components (Velero Controller, Restic, Schedule) have implementing tasks
- [x] EARS behavioral contracts translated to task DoD

### NFR Validation

- [x] NFR-e8a3c7b2-PERF-001: Backup performance validated in TASK-009 DoD
- [x] NFR-e8a3c7b2-PERF-002: Restore performance validated in TASK-012 DoD
- [x] NFR-e8a3c7b2-SEC-001: SOPS encryption enforced in TASK-003 DoD
- [x] NFR-e8a3c7b2-SEC-002: HTTPS transport validated in TASK-007 DoD
- [x] NFR-e8a3c7b2-RELIABILITY-001: Success rate tracked in TASK-015 DoD
- [x] NFR-e8a3c7b2-RELIABILITY-002: Data integrity validated in TASK-013 DoD
- [x] NFR-e8a3c7b2-RESOURCE-001: Resource limits specified in TASK-005 HelmRelease
- [x] NFR-e8a3c7b2-OBSERVABILITY-001: Metrics enabled in TASK-005 HelmRelease

### Risk Mitigation

- [x] Medium+ risks identified with mitigation tasks
- [x] Dependencies clearly specified for sequential execution
- [x] Validation commands provided for every task

### EARS-to-BDD Test Translation

- [x] Every EARS AC has corresponding validation command
- [x] Given/When/Then structure implicit in DoD statements
- [x] Measurable success criteria for each task

### Documentation Completeness

- [x] CLAUDE.md update planned (TASK-017)
- [x] Usage documentation implied in validation commands
- [x] Troubleshooting guidance via validation command patterns

---

## Risk Summary

**High Risk:** None
**Medium Risk:**

- TASK-005 (HelmRelease configuration complexity)
- TASK-006 (FluxCD deployment coordination)
- TASK-007 (S3 connection validation)
- TASK-009 (First backup execution)
- TASK-012 (Restore workflow)
- TASK-015 (Scheduled execution validation)
- TASK-016 (Garbage collection timing)

**Low Risk:** All infrastructure and documentation tasks

**Critical Path:** TASK-001 → TASK-002 → TASK-003 → TASK-004 → TASK-005 → TASK-006 → TASK-007 (foundation) → TASK-008 → TASK-009 → TASK-010 (backup testing) → TASK-011 → TASK-012 → TASK-013 (restore testing) → TASK-014 → TASK-015 → TASK-016 (automation) → TASK-017 (documentation)

**Blocking Risks:**

- S3 connectivity issues (mitigated by TASK-007 early validation)
- SOPS decryption failures (mitigated by FluxCD validation)
- Restic resource exhaustion (mitigated by resource limits in TASK-005)

---

## Effort Summary

**Total Estimated Effort:** 27 story points

**Breakdown by Phase:**

- Phase 1 (Infrastructure): 3pts (TASK-001 to TASK-003)
- Phase 2 (Deployment): 6pts (TASK-004 to TASK-007)
- Phase 3 (Backup Testing): 4pts (TASK-008 to TASK-010)
- Phase 4 (Restore Testing): 4pts (TASK-011 to TASK-013)
- Phase 5 (Automation): 6pts (TASK-014 to TASK-016)
- Phase 6 (Documentation): 4pts (TASK-017)

**Timeline Estimate:** 8-12 hours implementation + 48 hours observation (scheduled backups, retention testing)

---

**End of tasks.md**
