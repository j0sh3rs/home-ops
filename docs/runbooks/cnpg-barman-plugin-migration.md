# CNPG Barman Cloud Plugin Migration

**Status:** deferred. Not yet executed.
**Trigger to schedule:** CNPG operator chart hits **1.29.x** (one minor before 1.30.0 removal), OR a plugin-only feature becomes desirable, whichever comes first.
**Last reviewed:** 2026-05-21 (current operator chart `0.28.2` = cnpg 1.26.x).

## Why this exists

CloudNativePG **1.26+** deprecated the in-tree Barman Cloud integration (`spec.backup.barmanObjectStore` block on the Cluster CR). Removal in **1.30.0**. Replacement: out-of-tree **CloudNativePG Plugin** (`barman-cloud.cloudnative-pg.io`) running via the cnpg-i interface.

Each reconcile of `postgres17` currently emits this deprecation warning — that warning is the marker for this migration.

```
Warning: Native support for Barman Cloud backups and recovery is
deprecated and will be completely removed in CloudNativePG 1.30.0.
Found usage in: spec.backup.barmanObjectStore,
spec.externalClusters.0.barmanObjectStore.
```

## Architecture diff

| Today (in-tree, removed in 1.30) | After (plugin) |
|----------------------------------|----------------|
| `spec.backup.barmanObjectStore: {...}` inline on Cluster | `spec.plugins: [{name: barman-cloud.cloudnative-pg.io, parameters: {...}}]` |
| Operator pod ships barman-cloud binaries | Separate `barman-cloud-plugin` Deployment in cnpg ns |
| Inline `s3Credentials`, `destinationPath`, retention etc. | Separate `ObjectStore` CR holds the same fields, referenced by plugin parameters |
| ScheduledBackup writes to cluster's inline barmanObjectStore | ScheduledBackup uses `method: plugin` + `pluginConfiguration: {name: barman-cloud.cloudnative-pg.io}` |
| `externalClusters[].barmanObjectStore` for recovery sources | `externalClusters[].plugin` referencing an ObjectStore CR |

Backup destination, format, and retention semantics are **unchanged** — only the wiring moves.

## Pre-flight (when scheduling)

- Confirm operator chart on **≥ 1.29** (deprecation removed in 1.30; a 1.29 → 1.30 jump without this migration silently breaks backups).
- Confirm last backup timestamp is fresh: `kubectl exec -n databases postgres17-2 -c postgres --context home -- barman-cloud-backup-list --cloud-provider aws-s3 --endpoint-url https://s3.68cc.io s3://cloudnative-pg postgres17-v4`
- Note current `serverName: postgres17-v4` — preserve through migration.
- Take a fresh on-demand backup before starting: `kubectl cnpg backup postgres17 -n databases --context home`

## Migration steps

### 1. Deploy the plugin operator

New HelmRelease, separate from the main cnpg operator. Lives in the same `databases` ns (or `cnpg-system` per upstream docs).

```yaml
# kubernetes/apps/databases/cloudnative-pg-barman-plugin/app/helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: cloudnative-pg-barman-plugin
spec:
  chartRef:
    kind: OCIRepository
    name: cloudnative-pg-barman-plugin
  values:
    # Defaults are usually fine; verify against:
    # https://github.com/cloudnative-pg/plugin-barman-cloud
```

OCIRepository: `oci://ghcr.io/cloudnative-pg/plugin-barman-cloud-helm` (verify exact path at migration time — chart packaging changes).

### 2. Create the ObjectStore CR

```yaml
# kubernetes/apps/databases/cloudnative-pg/cluster/objectstore.yaml
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: postgres17-s3
  namespace: databases
spec:
  configuration:
    destinationPath: s3://cloudnative-pg/
    endpointURL: https://s3.68cc.io
    data:
      compression: bzip2
    wal:
      compression: bzip2
      maxParallel: 8
    s3Credentials:
      accessKeyId:
        name: cloudnative-pg-secret
        key: S3_ACCESS_KEY_ID
      secretAccessKey:
        name: cloudnative-pg-secret
        key: S3_SECRET_ACCESS_KEY
  retentionPolicy: 30d
```

A second ObjectStore for the recovery source (`postgres17-v3`):

```yaml
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata:
  name: postgres17-v3-s3
  namespace: databases
spec:
  configuration:
    destinationPath: s3://cloudnative-pg/
    endpointURL: https://s3.68cc.io
    s3Credentials:
      accessKeyId: { name: cloudnative-pg-secret, key: S3_ACCESS_KEY_ID }
      secretAccessKey: { name: cloudnative-pg-secret, key: S3_SECRET_ACCESS_KEY }
```

### 3. Modify cluster17.yaml

```yaml
spec:
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters:
        barmanObjectName: postgres17-s3
        # serverName preserved across migration
        serverName: postgres17-v4

  # REMOVE the entire spec.backup block — it goes away.
  # REMOVE spec.externalClusters[].barmanObjectStore. Replace with:
  externalClusters:
    - name: postgres17-v3
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters:
          barmanObjectName: postgres17-v3-s3
          serverName: postgres17-v3
```

### 4. Update scheduledbackup.yaml

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata:
  name: postgres
spec:
  schedule: "0 0 2 * * *"
  cluster:
    name: postgres17
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
```

### 5. Apply + verify

- Reconcile the new HelmRelease + ObjectStore CRs first.
- Then reconcile the cluster spec change.
- Watch operator logs: `kubectl logs -n databases -l app.kubernetes.io/name=cloudnative-pg --context home -f`
- Trigger an on-demand backup: `kubectl cnpg backup postgres17 -n databases --context home`
- Verify it lands in S3 at the same path: `aws --endpoint-url https://s3.68cc.io s3 ls s3://cloudnative-pg/postgres17-v4/base/ --recursive | tail -5`
- Verify WAL archive flow continues: `kubectl exec postgres17-2 -c postgres --context home -- psql -U postgres -c "SELECT * FROM pg_stat_archiver"` — `last_archived_time` should advance.

### 6. Confirm CNPGStaleBaseBackup alert resets

The existing alert (`prometheusrule.yaml`) should remain green throughout. If it fires, check the plugin Deployment logs first.

## Rollback

Revert the commits. Backup data in S3 is **format-compatible** with both the in-tree integration and the plugin — re-adding `spec.backup.barmanObjectStore` resumes archiving against the same `serverName`. No data migration needed.

## Risk register

| Concern | Likelihood | Mitigation |
|---------|------------|------------|
| WAL archive gap during the cluster spec swap | Medium — ~1 min while archive_command rewires | Take an on-demand backup before; cnpg retries archive failures, won't lose WAL |
| Plugin operator HelmRelease fails to install | Low | Standard Flux remediation; doesn't affect cluster yet |
| `serverName` mismatch → backups land in wrong path | Medium if not careful | Explicit `serverName` in plugin parameters above; verify `aws s3 ls` shows the expected path |
| 1.29 → 1.30 jump without migration | High if forgotten | This runbook + deprecation warning + memory entry serve as the gate |

## References

- CNPG release notes: https://cloudnative-pg.io/documentation/current/release_notes/
- Plugin repo: https://github.com/cloudnative-pg/plugin-barman-cloud
- Plugin docs: https://cloudnative-pg.io/documentation/current/plugin-barman-cloud/
- Source ObjectStore CRD: `kubectl explain objectstore.barmancloud.cnpg.io --context home` (after plugin install)

## Related

- `kubernetes/apps/databases/cloudnative-pg/cluster/cluster17.yaml` — current Cluster CR (still in-tree)
- `kubernetes/apps/databases/cloudnative-pg/cluster/scheduledbackup.yaml` — current ScheduledBackup
- `cluster17.yaml` `spec.bootstrap.recovery.source: postgres17-v3` — needs migration too
- Memory: `project_cnpg_barman_plugin_migration` (deferred work tracker)
