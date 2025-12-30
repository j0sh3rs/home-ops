# Implementation Plan: Wazuh S3 Backup System

**Generated**: 2025-12-30
**Status**: Ready for implementation

## Goal

Implement comprehensive S3-based backup solution for Wazuh deployment including:
1. OpenSearch indexer snapshots to S3 (wazuh-alerts-*, wazuh-archives-* indices)
2. Wazuh manager backups to S3 (agent keys, databases, configurations)
3. Daily schedule at 02:00 EST with configurable retention policies

## Research Summary

### Key Findings

1. **OpenSearch S3 Repository Plugin**
   - The `repository-s3` plugin must be installed on all OpenSearch/Wazuh Indexer nodes
   - For Wazuh Indexer: `/usr/share/wazuh-indexer/bin/opensearch-plugin install repository-s3`
   - S3 credentials must be added to OpenSearch keystore (not environment variables for security)
   - Custom S3 endpoints (like Minio) require explicit endpoint configuration in opensearch.yml

2. **Wazuh Indexer Already Has Snapshot Support Enabled**
   - Current opensearch.yml already contains:
     ```yaml
     plugins.security.check_snapshot_restore_write_privileges: true
     plugins.security.enable_snapshot_restore_privilege: true
     ```

3. **S3 Credentials Already Available**
   - `wazuh-secrets` already contains `accessKeyId` and `secretAccessKey`
   - S3 endpoint: `s3.68cc.io` (local Minio)
   - Bucket: `wazuh-backups` (pre-existing)

4. **Wazuh Manager Critical Backup Paths**
   - `/var/ossec/etc/client.keys` - Agent registration keys (CRITICAL)
   - `/var/ossec/etc/ossec.conf` - Main configuration
   - `/var/ossec/var/db/` - SQLite databases (agent info, FIM, etc.)
   - `/var/ossec/queue/` - Pending events and agent queues
   - `/var/ossec/api/configuration/` - API configuration

5. **Snapshot Management Options**
   - OpenSearch Snapshot Management (SM) policies - native, built-in
   - Index State Management (ISM) with snapshot action - per-index
   - CronJob + curl API calls - external orchestration
   - **Recommendation**: Use CronJob for flexibility with custom S3 endpoint

## Existing Codebase Analysis

### Current Structure
```
kubernetes/apps/security/wazuh/app/
├── kustomization.yaml              # Main kustomize entry
├── secret.sops.yaml                # Contains S3 creds (accessKeyId, secretAccessKey)
├── indexer_stack/
│   └── wazuh-indexer/
│       ├── cluster/indexer-sts.yaml    # 3-replica StatefulSet
│       └── indexer_conf/opensearch.yml # Snapshot privileges enabled
└── wazuh_managers/
    ├── wazuh-master-sts.yaml       # Master StatefulSet (1 replica)
    └── wazuh-worker-sts.yaml       # Worker StatefulSet (2 replicas)
```

### Patterns to Follow
- CronJob pattern from `kubernetes/apps/kube-system/talos-backups/app/cronjob.yaml`
- Secret reference pattern using `envFrom` with `secretRef`
- Security context with non-root user, dropped capabilities
- Timezone support via `timeZone` field

## Implementation Phases

---

### Phase 1: OpenSearch S3 Plugin Installation

**Goal**: Install repository-s3 plugin and configure S3 keystore on all indexer nodes

**Files to create:**
- `kubernetes/apps/security/wazuh/app/indexer_stack/wazuh-indexer/s3-plugin-job.yaml`

**Files to modify:**
- `kubernetes/apps/security/wazuh/app/indexer_stack/wazuh-indexer/indexer_conf/opensearch.yml`
- `kubernetes/apps/security/wazuh/app/indexer_stack/wazuh-indexer/cluster/indexer-sts.yaml`
- `kubernetes/apps/security/wazuh/app/kustomization.yaml`

**Steps:**

1. **Add S3 client configuration to opensearch.yml**
   ```yaml
   # S3 Repository Configuration (Minio)
   s3.client.default.endpoint: s3.68cc.io
   s3.client.default.protocol: https
   s3.client.default.path_style_access: true
   ```

2. **Add InitContainer to indexer-sts.yaml for plugin installation and keystore setup**
   ```yaml
   initContainers:
     # ... existing initContainers ...
     - name: install-s3-plugin
       image: "wazuh/wazuh-indexer:4.14.1"
       command:
         - sh
         - -c
         - |
           # Install plugin if not present
           if [ ! -d /usr/share/wazuh-indexer/plugins/repository-s3 ]; then
             /usr/share/wazuh-indexer/bin/opensearch-plugin install --batch repository-s3
           fi
           # Setup keystore with S3 credentials
           /usr/share/wazuh-indexer/bin/opensearch-keystore create || true
           echo "$S3_ACCESS_KEY" | /usr/share/wazuh-indexer/bin/opensearch-keystore add --stdin --force s3.client.default.access_key
           echo "$S3_SECRET_KEY" | /usr/share/wazuh-indexer/bin/opensearch-keystore add --stdin --force s3.client.default.secret_key
           # Copy keystore to shared volume
           cp /usr/share/wazuh-indexer/config/opensearch.keystore /keystore/
       env:
         - name: S3_ACCESS_KEY
           valueFrom:
             secretKeyRef:
               name: wazuh-secrets
               key: accessKeyId
         - name: S3_SECRET_KEY
           valueFrom:
             secretKeyRef:
               name: wazuh-secrets
               key: secretAccessKey
       volumeMounts:
         - name: keystore-volume
           mountPath: /keystore
         - name: wazuh-indexer
           mountPath: /usr/share/wazuh-indexer/plugins
           subPath: plugins
   ```

3. **Add keystore volume mount to main container**
   ```yaml
   volumeMounts:
     # ... existing mounts ...
     - name: keystore-volume
       mountPath: /usr/share/wazuh-indexer/config/opensearch.keystore
       subPath: opensearch.keystore
       readOnly: true
   ```

4. **Add volumes to pod spec**
   ```yaml
   volumes:
     # ... existing volumes ...
     - name: keystore-volume
       emptyDir: {}
   ```

**Acceptance criteria:**
- [ ] All 3 indexer pods restart successfully
- [ ] `curl -k https://admin:password@wazuh-indexer:9200/_cat/plugins` shows `repository-s3`
- [ ] Keystore contains S3 credentials on all nodes

---

### Phase 2: OpenSearch Snapshot Repository Registration

**Goal**: Register S3 repository and verify connectivity

**Files to create:**
- `kubernetes/apps/security/wazuh/app/backups/register-snapshot-repo-job.yaml`
- `kubernetes/apps/security/wazuh/app/backups/kustomization.yaml`

**Files to modify:**
- `kubernetes/apps/security/wazuh/app/kustomization.yaml`

**Steps:**

1. **Create backup directory structure**
   ```bash
   mkdir -p kubernetes/apps/security/wazuh/app/backups
   ```

2. **Create one-time Job to register S3 repository**
   ```yaml
   # register-snapshot-repo-job.yaml
   apiVersion: batch/v1
   kind: Job
   metadata:
     name: wazuh-register-snapshot-repo
     namespace: security
     annotations:
       argocd.argoproj.io/hook: PostSync
       argocd.argoproj.io/hook-delete-policy: HookSucceeded
   spec:
     ttlSecondsAfterFinished: 300
     template:
       spec:
         restartPolicy: OnFailure
         containers:
           - name: register-repo
             image: curlimages/curl:8.5.0
             command:
               - /bin/sh
               - -c
               - |
                 # Wait for indexer to be ready
                 until curl -sk https://wazuh-indexer:9200/_cluster/health | grep -q '"status":"green"\|"status":"yellow"'; do
                   echo "Waiting for cluster..."
                   sleep 10
                 done

                 # Register S3 snapshot repository
                 curl -sk -X PUT "https://${INDEXER_USER}:${INDEXER_PASS}@wazuh-indexer:9200/_snapshot/wazuh-s3-repo" \
                   -H "Content-Type: application/json" \
                   -d '{
                     "type": "s3",
                     "settings": {
                       "bucket": "wazuh-backups",
                       "base_path": "opensearch-snapshots",
                       "endpoint": "s3.68cc.io",
                       "protocol": "https",
                       "path_style_access": "true"
                     }
                   }'

                 # Verify repository
                 curl -sk "https://${INDEXER_USER}:${INDEXER_PASS}@wazuh-indexer:9200/_snapshot/wazuh-s3-repo/_verify"
             env:
               - name: INDEXER_USER
                 valueFrom:
                   secretKeyRef:
                     name: wazuh-secrets
                     key: indexerUsername
               - name: INDEXER_PASS
                 valueFrom:
                   secretKeyRef:
                     name: wazuh-secrets
                     key: indexerPassword
   ```

3. **Create backups kustomization.yaml**
   ```yaml
   apiVersion: kustomize.config.k8s.io/v1beta1
   kind: Kustomization
   resources:
     - register-snapshot-repo-job.yaml
   ```

4. **Update main kustomization.yaml**
   ```yaml
   resources:
     # ... existing resources ...
     - ./backups/
   ```

**Acceptance criteria:**
- [ ] Job completes successfully
- [ ] `GET /_snapshot/wazuh-s3-repo` returns valid repository config
- [ ] `GET /_snapshot/wazuh-s3-repo/_verify` returns success

---

### Phase 3: OpenSearch Snapshot CronJob

**Goal**: Create daily snapshot CronJob with 30-day retention

**Files to create:**
- `kubernetes/apps/security/wazuh/app/backups/indexer-snapshot-cronjob.yaml`

**Files to modify:**
- `kubernetes/apps/security/wazuh/app/backups/kustomization.yaml`

**Steps:**

1. **Create snapshot CronJob**
   ```yaml
   # indexer-snapshot-cronjob.yaml
   apiVersion: batch/v1
   kind: CronJob
   metadata:
     name: wazuh-indexer-snapshot
     namespace: security
   spec:
     schedule: "0 7 * * *"  # 02:00 EST = 07:00 UTC
     timeZone: "America/New_York"
     concurrencyPolicy: Forbid
     successfulJobsHistoryLimit: 3
     failedJobsHistoryLimit: 3
     jobTemplate:
       spec:
         template:
           spec:
             restartPolicy: OnFailure
             securityContext:
               runAsUser: 1000
               runAsGroup: 1000
               runAsNonRoot: true
             containers:
               - name: snapshot
                 image: curlimages/curl:8.5.0
                 securityContext:
                   allowPrivilegeEscalation: false
                   capabilities:
                     drop: [ALL]
                   seccompProfile:
                     type: RuntimeDefault
                 command:
                   - /bin/sh
                   - -c
                   - |
                     set -e
                     SNAPSHOT_NAME="wazuh-$(date +%Y%m%d-%H%M%S)"
                     BASE_URL="https://${INDEXER_USER}:${INDEXER_PASS}@wazuh-indexer:9200"

                     echo "Creating snapshot: ${SNAPSHOT_NAME}"

                     # Create snapshot of Wazuh indices
                     curl -sk -X PUT "${BASE_URL}/_snapshot/wazuh-s3-repo/${SNAPSHOT_NAME}?wait_for_completion=true" \
                       -H "Content-Type: application/json" \
                       -d '{
                         "indices": "wazuh-alerts-*,wazuh-archives-*,wazuh-monitoring-*,wazuh-statistics-*",
                         "ignore_unavailable": true,
                         "include_global_state": false
                       }'

                     echo "Snapshot created successfully"

                     # Delete snapshots older than 30 days
                     echo "Cleaning up old snapshots..."
                     CUTOFF_DATE=$(date -d '30 days ago' +%Y%m%d 2>/dev/null || date -v-30d +%Y%m%d)

                     curl -sk "${BASE_URL}/_snapshot/wazuh-s3-repo/_all" | \
                       grep -oP '"snapshot"\s*:\s*"\K[^"]+' | \
                       while read snap; do
                         SNAP_DATE=$(echo "$snap" | grep -oP '\d{8}' | head -1)
                         if [ -n "$SNAP_DATE" ] && [ "$SNAP_DATE" -lt "$CUTOFF_DATE" ]; then
                           echo "Deleting old snapshot: $snap"
                           curl -sk -X DELETE "${BASE_URL}/_snapshot/wazuh-s3-repo/${snap}"
                         fi
                       done

                     echo "Cleanup complete"
                 env:
                   - name: INDEXER_USER
                     valueFrom:
                       secretKeyRef:
                         name: wazuh-secrets
                         key: indexerUsername
                   - name: INDEXER_PASS
                     valueFrom:
                       secretKeyRef:
                         name: wazuh-secrets
                         key: indexerPassword
   ```

2. **Update backups kustomization.yaml**
   ```yaml
   resources:
     - register-snapshot-repo-job.yaml
     - indexer-snapshot-cronjob.yaml
   ```

**Acceptance criteria:**
- [ ] CronJob created and shows next scheduled run
- [ ] Manual job trigger creates snapshot successfully
- [ ] Snapshot appears in S3 bucket under `opensearch-snapshots/`
- [ ] Old snapshots (>30 days) are cleaned up

---

### Phase 4: Wazuh Manager Backup CronJob

**Goal**: Create daily manager backup CronJob with 14-day retention

**Files to create:**
- `kubernetes/apps/security/wazuh/app/backups/manager-backup-cronjob.yaml`
- `kubernetes/apps/security/wazuh/app/backups/manager-backup-script-cm.yaml`

**Files to modify:**
- `kubernetes/apps/security/wazuh/app/backups/kustomization.yaml`

**Steps:**

1. **Create backup script ConfigMap**
   ```yaml
   # manager-backup-script-cm.yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: wazuh-manager-backup-script
     namespace: security
   data:
     backup.sh: |
       #!/bin/sh
       set -e

       BACKUP_DATE=$(date +%Y%m%d-%H%M%S)
       BACKUP_NAME="wazuh-manager-${BACKUP_DATE}"
       BACKUP_DIR="/tmp/${BACKUP_NAME}"
       S3_PATH="s3://${S3_BUCKET}/manager-backups/${BACKUP_NAME}.tar.gz"

       echo "Starting Wazuh manager backup: ${BACKUP_NAME}"

       mkdir -p "${BACKUP_DIR}"

       # Backup critical directories from master
       echo "Backing up client.keys..."
       kubectl exec -n security wazuh-manager-master-0 -- \
         tar czf - /var/ossec/etc/client.keys 2>/dev/null > "${BACKUP_DIR}/client.keys.tar.gz" || true

       echo "Backing up ossec.conf..."
       kubectl exec -n security wazuh-manager-master-0 -- \
         tar czf - /var/ossec/etc/ossec.conf 2>/dev/null > "${BACKUP_DIR}/ossec.conf.tar.gz" || true

       echo "Backing up API configuration..."
       kubectl exec -n security wazuh-manager-master-0 -- \
         tar czf - /var/ossec/api/configuration 2>/dev/null > "${BACKUP_DIR}/api-config.tar.gz" || true

       echo "Backing up databases..."
       kubectl exec -n security wazuh-manager-master-0 -- \
         tar czf - /var/ossec/var/db 2>/dev/null > "${BACKUP_DIR}/databases.tar.gz" || true

       echo "Backing up rules and decoders..."
       kubectl exec -n security wazuh-manager-master-0 -- \
         tar czf - /var/ossec/etc/rules /var/ossec/etc/decoders 2>/dev/null > "${BACKUP_DIR}/rules-decoders.tar.gz" || true

       # Create combined archive
       echo "Creating combined archive..."
       cd /tmp
       tar czf "${BACKUP_NAME}.tar.gz" "${BACKUP_NAME}"

       # Upload to S3
       echo "Uploading to S3: ${S3_PATH}"
       mc alias set minio https://${S3_ENDPOINT} ${AWS_ACCESS_KEY_ID} ${AWS_SECRET_ACCESS_KEY}
       mc cp "${BACKUP_NAME}.tar.gz" "minio/${S3_BUCKET}/manager-backups/"

       # Cleanup local files
       rm -rf "${BACKUP_DIR}" "${BACKUP_NAME}.tar.gz"

       # Delete backups older than 14 days
       echo "Cleaning up old backups..."
       CUTOFF_DATE=$(date -d '14 days ago' +%Y%m%d 2>/dev/null || date -v-14d +%Y%m%d)

       mc ls "minio/${S3_BUCKET}/manager-backups/" | while read line; do
         FILE=$(echo "$line" | awk '{print $NF}')
         FILE_DATE=$(echo "$FILE" | grep -oP '\d{8}' | head -1)
         if [ -n "$FILE_DATE" ] && [ "$FILE_DATE" -lt "$CUTOFF_DATE" ]; then
           echo "Deleting old backup: $FILE"
           mc rm "minio/${S3_BUCKET}/manager-backups/${FILE}"
         fi
       done

       echo "Backup complete: ${BACKUP_NAME}"
   ```

2. **Create manager backup CronJob**
   ```yaml
   # manager-backup-cronjob.yaml
   apiVersion: batch/v1
   kind: CronJob
   metadata:
     name: wazuh-manager-backup
     namespace: security
   spec:
     schedule: "0 7 * * *"  # 02:00 EST = 07:00 UTC
     timeZone: "America/New_York"
     concurrencyPolicy: Forbid
     successfulJobsHistoryLimit: 3
     failedJobsHistoryLimit: 3
     jobTemplate:
       spec:
         template:
           spec:
             serviceAccountName: wazuh-backup-sa
             restartPolicy: OnFailure
             securityContext:
               runAsUser: 1000
               runAsGroup: 1000
               runAsNonRoot: true
             containers:
               - name: backup
                 image: minio/mc:RELEASE.2024-01-28T16-23-14Z
                 securityContext:
                   allowPrivilegeEscalation: false
                   capabilities:
                     drop: [ALL]
                   seccompProfile:
                     type: RuntimeDefault
                 command: ["/bin/sh", "/scripts/backup.sh"]
                 env:
                   - name: S3_ENDPOINT
                     value: "s3.68cc.io"
                   - name: S3_BUCKET
                     value: "wazuh-backups"
                   - name: AWS_ACCESS_KEY_ID
                     valueFrom:
                       secretKeyRef:
                         name: wazuh-secrets
                         key: accessKeyId
                   - name: AWS_SECRET_ACCESS_KEY
                     valueFrom:
                       secretKeyRef:
                         name: wazuh-secrets
                         key: secretAccessKey
                 volumeMounts:
                   - name: backup-script
                     mountPath: /scripts
                   - name: tmp
                     mountPath: /tmp
             volumes:
               - name: backup-script
                 configMap:
                   name: wazuh-manager-backup-script
                   defaultMode: 0755
               - name: tmp
                 emptyDir: {}
   ```

3. **Create ServiceAccount with kubectl exec permissions**
   ```yaml
   # backup-rbac.yaml
   apiVersion: v1
   kind: ServiceAccount
   metadata:
     name: wazuh-backup-sa
     namespace: security
   ---
   apiVersion: rbac.authorization.k8s.io/v1
   kind: Role
   metadata:
     name: wazuh-backup-role
     namespace: security
   rules:
     - apiGroups: [""]
       resources: ["pods"]
       verbs: ["get", "list"]
     - apiGroups: [""]
       resources: ["pods/exec"]
       verbs: ["create"]
   ---
   apiVersion: rbac.authorization.k8s.io/v1
   kind: RoleBinding
   metadata:
     name: wazuh-backup-rolebinding
     namespace: security
   subjects:
     - kind: ServiceAccount
       name: wazuh-backup-sa
       namespace: security
   roleRef:
     kind: Role
     name: wazuh-backup-role
     apiGroup: rbac.authorization.k8s.io
   ```

4. **Update backups kustomization.yaml**
   ```yaml
   apiVersion: kustomize.config.k8s.io/v1beta1
   kind: Kustomization
   resources:
     - register-snapshot-repo-job.yaml
     - indexer-snapshot-cronjob.yaml
     - manager-backup-script-cm.yaml
     - manager-backup-cronjob.yaml
     - backup-rbac.yaml
   ```

**Acceptance criteria:**
- [ ] CronJob created and shows next scheduled run
- [ ] ServiceAccount has necessary RBAC permissions
- [ ] Manual job trigger creates backup successfully
- [ ] Backup archive appears in S3 bucket under `manager-backups/`
- [ ] Archive contains all critical files (client.keys, databases, configs)
- [ ] Old backups (>14 days) are cleaned up

---

### Phase 5: Verification and Documentation

**Goal**: Verify entire backup system and document restore procedures

**Files to create:**
- `kubernetes/apps/security/wazuh/app/backups/README.md`

**Steps:**

1. **Create comprehensive documentation**
   ```markdown
   # Wazuh Backup System

   ## Overview
   - OpenSearch snapshots: Daily at 02:00 EST, 30-day retention
   - Manager backups: Daily at 02:00 EST, 14-day retention
   - S3 Bucket: wazuh-backups at s3.68cc.io

   ## Manual Operations

   ### Trigger immediate OpenSearch snapshot
   kubectl create job --from=cronjob/wazuh-indexer-snapshot manual-snapshot-$(date +%s) -n security

   ### Trigger immediate manager backup
   kubectl create job --from=cronjob/wazuh-manager-backup manual-backup-$(date +%s) -n security

   ### List snapshots
   curl -sk https://admin:password@wazuh-indexer:9200/_snapshot/wazuh-s3-repo/_all

   ### Restore snapshot
   curl -sk -X POST "https://admin:password@wazuh-indexer:9200/_snapshot/wazuh-s3-repo/SNAPSHOT_NAME/_restore" \
     -H "Content-Type: application/json" \
     -d '{"indices": "wazuh-alerts-*"}'

   ## Restore Procedures

   ### Restore OpenSearch Indices
   1. List available snapshots
   2. Close indices if needed: POST /_close
   3. Restore from snapshot
   4. Verify data integrity

   ### Restore Wazuh Manager
   1. Download backup from S3
   2. Extract archive
   3. Stop Wazuh manager
   4. Restore files to appropriate locations
   5. Fix permissions (chown wazuh:wazuh)
   6. Start Wazuh manager
   ```

2. **Verify backup system end-to-end**
   - Trigger both CronJobs manually
   - Verify S3 bucket contents
   - Test restore of a single index
   - Test restore of manager configuration

**Acceptance criteria:**
- [ ] Documentation complete with restore procedures
- [ ] Both backup systems verified working
- [ ] S3 bucket shows organized backup structure
- [ ] Restore procedure tested and validated

---

## Testing Strategy

### Unit Tests
- Verify CronJob schedules parse correctly
- Verify RBAC permissions are sufficient
- Verify S3 connectivity from pods

### Integration Tests
1. Manual trigger of indexer snapshot CronJob
2. Verify snapshot appears in S3
3. Manual trigger of manager backup CronJob
4. Verify backup archive appears in S3
5. Download and extract backup to verify contents

### Disaster Recovery Test
1. Create test index with known data
2. Create snapshot
3. Delete test index
4. Restore from snapshot
5. Verify data integrity

## Risks and Considerations

### High Risk
- **S3 Plugin Installation**: May require StatefulSet rolling restart; plan for brief service interruption
- **Keystore Management**: S3 credentials in keystore must survive pod restarts; use InitContainer pattern

### Medium Risk
- **Large Snapshot Size**: Initial snapshots may be large; monitor S3 storage costs
- **Network Latency**: S3 operations may timeout; add appropriate retry logic

### Low Risk
- **Cleanup Script Edge Cases**: Date parsing may vary between container images; test with busybox date commands

## Estimated Complexity

| Phase | Complexity | Estimated Time |
|-------|------------|----------------|
| Phase 1: S3 Plugin | High | 2-3 hours |
| Phase 2: Repository Registration | Low | 30 minutes |
| Phase 3: Snapshot CronJob | Medium | 1 hour |
| Phase 4: Manager Backup | Medium | 1-2 hours |
| Phase 5: Verification | Medium | 1 hour |

**Total Estimated Time**: 5-7 hours

## File Summary

### New Files to Create
```
kubernetes/apps/security/wazuh/app/backups/
├── kustomization.yaml
├── register-snapshot-repo-job.yaml
├── indexer-snapshot-cronjob.yaml
├── manager-backup-script-cm.yaml
├── manager-backup-cronjob.yaml
├── backup-rbac.yaml
└── README.md
```

### Files to Modify
```
kubernetes/apps/security/wazuh/app/
├── kustomization.yaml                           # Add ./backups/
└── indexer_stack/wazuh-indexer/
    ├── cluster/indexer-sts.yaml                 # Add InitContainer, volumes
    └── indexer_conf/opensearch.yml              # Add S3 client config
```

## Dependencies

- S3 bucket `wazuh-backups` must exist (confirmed)
- S3 credentials in `wazuh-secrets` (confirmed: accessKeyId, secretAccessKey)
- OpenSearch cluster in healthy state before plugin installation
- kubectl access from backup pod (requires RBAC)
