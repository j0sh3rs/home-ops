# Runbook: move an openebs-hostpath PVC to another node (Velero)

openebs-hostpath PVs are node-local. Moving one = back up the data with
Velero kopia FS backup, delete the PVC, restore it together with a pod
pinned to the target node so WaitForFirstConsumer provisioning lands the
new PV on that node.

Velero 1.18 always strips `volume.kubernetes.io/selected-node` from a
restored PVC (the old `change-pvc-node-selector` remap ConfigMap is
deprecated and no longer in the code), so the node comes from where the
restored holder pod schedules. The PV is re-provisioned by the storage
class and filled by the kopia pod volume restore.

Proven on services/gatus (2026-10). All mutating steps are operator-run.

## Variables

Set these once per migration, in the shell you run the steps from:

```bash
export NS=services APP=gatus PVCS="gatus" TARGET=bee-jms-03
export MIG="mig-${APP}-$(date +%Y%m%d%H%M)"
```

Only a throwaway holder pod is backed up and restored (never the app pod),
so app init containers, sidecars, memory emptyDirs and webhook-injected
volumes never enter the backup.

## 0. Preconditions

```bash
kubectl -n velero get backups.velero.io --sort-by=.metadata.creationTimestamp | tail -3
kubectl -n "$NS" get pvc $PVCS -o wide
```

The latest backup must be `Completed`, and every PVC `Bound`. None of the
PVCs may carry the `velero.io/exclude-from-backup=true` label, because the
repo's Velero server runs with `defaultVolumesToFsBackup: true` (opt-out)
and honours it.

## 1. Freeze Flux for the app

```bash
flux -n "$NS" suspend kustomization "$APP"
flux -n "$NS" suspend helmrelease "$APP"
```

## 2. Label the PVCs to move

```bash
POD=$(kubectl -n "$NS" get pod -l app.kubernetes.io/name="$APP" -o jsonpath='{.items[0].metadata.name}')
kubectl -n "$NS" label pvc $PVCS migrate.home-ops.io/move=true --overwrite
```

## 3. Quiesce the app, then back up

Scale to zero so the data is consistent. Then run a backup pod that
holds the PVCs. That pod is not part of the scaled-down Deployment.

```bash
kubectl -n "$NS" scale deploy "$APP" --replicas=0
kubectl -n "$NS" wait --for=delete pod/"$POD" --timeout=180s
```

Create `/tmp/$MIG-holder.yaml`, listing every PVC in `$PVCS` under `volumes:` and `volumeMounts:`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: mig-holder
  labels:
    migrate.home-ops.io/move: "true"
  annotations:
    k8tz.io/inject: "false"
spec:
  restartPolicy: Never
  securityContext:
    runAsNonRoot: true
    runAsUser: 65534
    runAsGroup: 65534
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: hold
      image: busybox:1.37
      command: ["sleep", "86400"]
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: v0
          mountPath: /data/v0
  volumes:
    - name: v0
      persistentVolumeClaim:
        claimName: gatus
```

```bash
kubectl -n "$NS" apply -f /tmp/$MIG-holder.yaml
kubectl -n "$NS" wait --for=condition=Ready pod/mig-holder --timeout=180s
```

Create `/tmp/$MIG-backup.yaml`:

```yaml
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: REPLACE_MIG
  namespace: velero
spec:
  includedNamespaces: [REPLACE_NS]
  includedResources: [persistentvolumeclaims, pods]
  labelSelector:
    matchLabels:
      migrate.home-ops.io/move: "true"
  defaultVolumesToFsBackup: true
  snapshotVolumes: false
  ttl: 720h0m0s
```

```bash
sed -i "s/REPLACE_MIG/$MIG/; s/REPLACE_NS/$NS/" /tmp/$MIG-backup.yaml
kubectl apply -f /tmp/$MIG-backup.yaml
kubectl -n velero get backups.velero.io "$MIG" -w
kubectl -n velero get podvolumebackups.velero.io -l velero.io/backup-name="$MIG"
```

**Gate:** the Backup is `Completed`, and there is one `Completed`
PodVolumeBackup per PVC with a non-zero `.status.progress.totalBytes`
(an empty volume like a fresh gatus may show 0, which is acceptable).

## 4. Keep a fallback, then delete

Patch each old PV to Retain so the data survives the PVC delete:

```bash
for p in $PVCS; do kubectl patch pv "$(kubectl -n "$NS" get pvc "$p" -o jsonpath='{.spec.volumeName}')" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'; done
kubectl -n "$NS" delete pod mig-holder
kubectl -n "$NS" delete deploy "$APP"
kubectl -n "$NS" delete pvc $PVCS
```

Deleting the Deployment removes its ReplicaSet, so nothing can adopt or
kill the restored pod in step 5. The HelmRelease is suspended, so Helm
won't recreate it.

## 5. Restore onto the target node

Create `/tmp/$MIG-cm.yaml`. It is a resource modifier that patches the
restored holder pod so it has no `nodeName` or affinity and is pinned by
`nodeSelector` to the target. The ConfigMap must contain exactly one data
key. Velero already drops `ownerReferences` and `nodeName` on pod restore,
so the patch only needs to set the target.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: mig-pod-modifier
  namespace: velero
data:
  modifier.yaml: |
    version: v1
    resourceModifierRules:
      - conditions:
          groupResource: pods
          namespaces: [REPLACE_NS]
        mergePatches:
          - patchData: |
              {"spec":{"nodeName":null,"nodeSelector":{"kubernetes.io/hostname":"REPLACE_TARGET"},"affinity":null}}
```

Create `/tmp/$MIG-restore.yaml`:

```yaml
apiVersion: velero.io/v1
kind: Restore
metadata:
  name: REPLACE_MIG
  namespace: velero
spec:
  backupName: REPLACE_MIG
  includedNamespaces: [REPLACE_NS]
  includedResources: [persistentvolumeclaims, pods, persistentvolumes]
  restorePVs: true
  existingResourcePolicy: none
  resourceModifier:
    kind: ConfigMap
    name: mig-pod-modifier
```

The Restore must list `persistentvolumes`. Without it Velero skips the
backed-up PV, never marks it for re-provisioning, and keeps `spec.volumeName`
on the restored PVC, which would then point at the old Retained PV on the
source node. With it, Velero sees the pod volume backup and re-provisions.

```bash
sed -i "s/REPLACE_TARGET/$TARGET/g; s/REPLACE_NS/$NS/g" /tmp/$MIG-cm.yaml
sed -i "s/REPLACE_MIG/$MIG/g; s/REPLACE_NS/$NS/g" /tmp/$MIG-restore.yaml
kubectl apply -f /tmp/$MIG-cm.yaml
kubectl apply -f /tmp/$MIG-restore.yaml
kubectl -n velero get restores.velero.io "$MIG" -w
kubectl -n velero get podvolumerestores.velero.io -l velero.io/restore-name="$MIG"
kubectl -n "$NS" get pvc $PVCS -o wide
kubectl get pv -o custom-columns=N:.metadata.name,CLAIM:.spec.claimRef.name,NODE:.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0] | grep -E "$(echo $PVCS | tr ' ' '|')"
```

**Gate:** the Restore is `Completed`, the PodVolumeRestores are
`Completed`, the new PVs show `NODE` = `$TARGET`, and each restored PVC's
`VOLUME` is a new PV name, not the old Retained one.

## 6. Hand back to Flux

```bash
kubectl -n "$NS" delete pod mig-holder
kubectl -n velero delete configmap mig-pod-modifier
kubectl -n "$NS" label pvc $PVCS migrate.home-ops.io/move-
flux -n "$NS" resume helmrelease "$APP"
flux -n "$NS" resume kustomization "$APP"
flux -n "$NS" reconcile helmrelease "$APP" --force
kubectl -n "$NS" get pod -l app.kubernetes.io/name="$APP" -o wide
```

**Gate:** the app pod is `Running` on `$TARGET` and the app's data is
present (app-specific check). Helm `--force` recreates the deleted
Deployment and adopts the restored PVCs, which keep their Helm labels
and annotations from the backup.

## 7. Clean up the fallback (after ≥ 7 days healthy)

```bash
kubectl get pv | grep Released
```

Delete each listed old PV by name once the app has been healthy on the
new node for a week. The openebs hostpath directory on the source node is removed
when the PV is deleted only if the reclaim policy is Delete, so set it
back first:
`kubectl patch pv <name> -p '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}'`.

## Rollback (any step before 6)

The old PV is Retained:

1. Remove its `spec.claimRef` (`kubectl patch pv <old> --type json -p '[{"op":"remove","path":"/spec/claimRef"}]'`).
2. Recreate the PVC with `spec.volumeName: <old>`.
3. Resume Flux.
