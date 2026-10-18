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

Rehearsal on services/gatus pending (Phase 0c Task 4 Step 6). All mutating steps are operator-run.

## Variables

Set these once per migration, in the shell you run the steps from:

```bash
export NS=services APP=gatus TARGET=bee-jms-03
export MIG="mig-${APP}-$(date +%Y%m%d%H%M)"
PVCS=(gatus)
```

`PVCS` is a shell array, not a space-separated string, so the steps work
the same in bash and zsh (zsh does not word-split an unquoted `$PVCS`).
For several PVCs, list them inside the parentheses: `PVCS=(pvc-a pvc-b)`.
Every step expands it as `"${PVCS[@]}"`. It is not exported, so run all
steps from this same shell.

Only a throwaway holder pod is backed up and restored (never the app pod),
so app init containers, sidecars, memory emptyDirs and webhook-injected
volumes never enter the backup.

## 0. Preconditions

```bash
kubectl -n velero get backups.velero.io --sort-by=.metadata.creationTimestamp | tail -3
kubectl -n "$NS" get pvc "${PVCS[@]}" -o wide
```

The latest backup must be `Completed`, and every PVC `Bound`. None of the
PVCs may carry the `velero.io/exclude-from-backup=true` label, because the
repo's Velero server runs with `defaultVolumesToFsBackup: true` (opt-out)
and honours it. The label on a bound PV drops it from the backup too, so
check both. Neither command may print the label:

```bash
kubectl -n "$NS" get pvc "${PVCS[@]}" --show-labels
kubectl get pv -l velero.io/exclude-from-backup=true
```

The second command must not list any PV claimed by a PVC in `PVCS`.

## 1. Freeze Flux for the app

```bash
flux -n "$NS" suspend kustomization "$APP"
flux -n "$NS" suspend helmrelease "$APP"
```

## 2. Label the PVCs to move

```bash
POD=$(kubectl -n "$NS" get pod -l app.kubernetes.io/name="$APP" -o jsonpath='{.items[0].metadata.name}')
kubectl -n "$NS" label pvc "${PVCS[@]}" migrate.home-ops.io/move=true --overwrite
```

## 3. Quiesce the app, then back up

Scale to zero so the data is consistent. Then run a backup pod that
holds the PVCs. That pod is not part of the scaled-down Deployment.

```bash
kubectl -n "$NS" scale deploy "$APP" --replicas=0
kubectl -n "$NS" wait --for=delete pod/"$POD" --timeout=180s
```

Create `/tmp/$MIG-holder.yaml`, listing every PVC in `PVCS` under `volumes:` and `volumeMounts:`:

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
        claimName: REPLACE_PVC_0
```

Replace `REPLACE_PVC_0` with the first PVC in `PVCS`. For each further PVC
add a `v1`, `v2`, ... volume and a matching mount at `/data/v1`, `/data/v2`, ...
with its own `claimName`.

```bash
kubectl -n "$NS" apply -f "/tmp/$MIG-holder.yaml"
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
sed -i "s/REPLACE_MIG/$MIG/; s/REPLACE_NS/$NS/" "/tmp/$MIG-backup.yaml"
kubectl apply -f "/tmp/$MIG-backup.yaml"
kubectl -n velero get backups.velero.io "$MIG" -w
kubectl -n velero get podvolumebackups.velero.io -l velero.io/backup-name="$MIG"
```

**Gate:** the Backup is `Completed`, and there is one `Completed`
PodVolumeBackup per PVC with a non-zero `.status.progress.totalBytes`
(an empty volume like a fresh gatus may show 0, which is acceptable).

## 4. Keep a fallback, then delete

Patch each old PV to Retain so the data survives the PVC delete:

Record each PVC name with its old PV name (one `<pvc> <pv>` line each) and save each PVC manifest first. The rollback
section needs both:

```bash
test ! -e "/tmp/$MIG-oldpvs.txt" || echo "already saved, do not re-run"
rm -f "/tmp/$MIG-oldpvs.txt.new"
for p in "${PVCS[@]}"; do pv=$(kubectl -n "$NS" get pvc "$p" -o jsonpath='{.spec.volumeName}') && test -n "$pv" && test ! -e "/tmp/$MIG-oldpvs.txt" && kubectl -n "$NS" get pvc "$p" -o json | jq 'del(.metadata.uid,.metadata.resourceVersion,.metadata.creationTimestamp,.metadata.finalizers,.metadata.annotations,.status)' > "/tmp/$MIG-pvc-$p.json" && printf '%s %s\n' "$p" "$pv" >> "/tmp/$MIG-oldpvs.txt.new"; done
test -e "/tmp/$MIG-oldpvs.txt" || if test "$(awk 'END{print NR}' "/tmp/$MIG-oldpvs.txt.new" 2>/dev/null)" = "${#PVCS[@]}"; then mv "/tmp/$MIG-oldpvs.txt.new" "/tmp/$MIG-oldpvs.txt"; else echo "ERROR: /tmp/$MIG-oldpvs.txt.new does not list all ${#PVCS[@]} PVCs, not moved"; fi
cat "/tmp/$MIG-oldpvs.txt"
```

Run this save block once. Re-running it after the PVCs are deleted would
clobber the saved data, so it does nothing if `/tmp/$MIG-oldpvs.txt`
already exists. It only moves `/tmp/$MIG-oldpvs.txt.new` into place when
that file has one line per PVC in `PVCS`. If it prints `ERROR` instead,
do not go on: find the PVC that failed, remove the partial files, then run
the save block again:

```bash
for p in "${PVCS[@]}"; do rm -f "/tmp/$MIG-pvc-$p.json"; done
rm -f "/tmp/$MIG-oldpvs.txt.new"
```

Then patch each old PV to Retain and delete:

```bash
for p in "${PVCS[@]}"; do kubectl patch pv "$(kubectl -n "$NS" get pvc "$p" -o jsonpath='{.spec.volumeName}')" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'; done
kubectl -n "$NS" delete pod mig-holder
kubectl -n "$NS" delete deploy "$APP"
kubectl -n "$NS" delete pvc "${PVCS[@]}"
```

Deleting the Deployment removes its ReplicaSet, so nothing can adopt or
kill the restored pod in step 5. The HelmRelease is suspended, so Helm
won't recreate it.

## 5. Restore onto the target node

Create `/tmp/$MIG-cm.yaml`. It is a resource modifier that patches the
restored holder pod so it has no `nodeName` or affinity and is pinned by
`nodeSelector` to the target. The ConfigMap must contain exactly one data
key. Velero already drops `ownerReferences` and `nodeName` on pod restore,
so the patch only needs to set the target. It also nulls `nodeName` and
`affinity` as a defensive measure, in case the backed-up pod carried them.

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
sed -i "s/REPLACE_TARGET/$TARGET/g; s/REPLACE_NS/$NS/g" "/tmp/$MIG-cm.yaml"
sed -i "s/REPLACE_MIG/$MIG/g; s/REPLACE_NS/$NS/g" "/tmp/$MIG-restore.yaml"
kubectl apply -f "/tmp/$MIG-cm.yaml"
kubectl apply -f "/tmp/$MIG-restore.yaml"
kubectl -n velero get restores.velero.io "$MIG" -w
kubectl -n velero get podvolumerestores.velero.io -l velero.io/restore-name="$MIG"
kubectl -n "$NS" get pvc "${PVCS[@]}" -o wide
kubectl get pv -o 'custom-columns=N:.metadata.name,CLAIM:.spec.claimRef.name,NODE:.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]' | grep -E "$(IFS='|'; echo "${PVCS[*]}")"
```

**Gate:** the Restore is `Completed`, the PodVolumeRestores are
`Completed`, the new PVs show `NODE` = `$TARGET`, and each restored PVC's
`VOLUME` is a new PV name, not the old Retained one.

## 6. Hand back to Flux

```bash
kubectl -n "$NS" delete pod mig-holder
kubectl -n velero delete configmap mig-pod-modifier
kubectl -n "$NS" label pvc "${PVCS[@]}" migrate.home-ops.io/move-
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

Resuming Flux alone does not bring the app back. The Deployment was
deleted in step 4, and the HelmRelease sees no drift, so it needs a forced
reconcile. Run these in the same shell with `NS`, `APP`, `PVCS` and `MIG`
set. They rely on `/tmp/$MIG-oldpvs.txt` (lines of `<pvc> <pv>`) and
`/tmp/$MIG-pvc-<name>.json`, both written in step 4.

Pick the branch by whether the file exists:

```bash
ls -l "/tmp/$MIG-oldpvs.txt"
```

**File missing (step 4 not started).** Nothing was deleted, and the
Deployment still exists but step 3 scaled it to 0. The HelmRelease has no
drift detection, so a plain resume leaves it at 0 replicas. The forced
reconcile is mandatory here:

```bash
kubectl -n "$NS" delete pod mig-holder --ignore-not-found
kubectl -n "$NS" label pvc "${PVCS[@]}" migrate.home-ops.io/move-
flux -n "$NS" resume helmrelease "$APP"
flux -n "$NS" resume kustomization "$APP"
flux -n "$NS" reconcile helmrelease "$APP" --force
kubectl -n "$NS" rollout status deploy/"$APP" --timeout=5m
```

Stop once the rollout completes.

**File present (step 4 started or finished).** Do items 1 to 4 in order.
The order matters: the PVs must be Retain before anything is deleted.

1. Protect the data first. Patch every old PV to Retain, which is safe to
repeat, then verify. Do not continue until every line shows `Retain`:

```bash
while read -r pvc pv; do kubectl patch pv "$pv" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'; done < "/tmp/$MIG-oldpvs.txt"
while read -r pvc pv; do kubectl get pv "$pv" -o 'custom-columns=N:.metadata.name,RECLAIM:.spec.persistentVolumeReclaimPolicy,PHASE:.status.phase,NODE:.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]'; done < "/tmp/$MIG-oldpvs.txt"
```

If a PV is missing, stop and raise it. Its data is gone from the cluster
and only the Velero backup remains.

2. Remove the holder pod, any restored PVCs and the modifier ConfigMap:

```bash
kubectl -n "$NS" delete pod mig-holder --ignore-not-found
kubectl -n "$NS" delete pvc "${PVCS[@]}" --ignore-not-found
kubectl -n velero delete configmap mig-pod-modifier --ignore-not-found
```

3. Pre-bind each old PV to the PVC about to be recreated. The PV's
`spec.claimRef` still names the deleted PVC with a stale uid, so the PV
controller will not bind to it. A JSON Patch `replace` swaps the whole
object, dropping the uid and resourceVersion (a merge patch would keep
them). The claimRef then holds only namespace and name, so only that PVC
can claim the PV:

```bash
while read -r pvc pv; do kubectl patch pv "$pv" --type json -p "[{\"op\":\"replace\",\"path\":\"/spec/claimRef\",\"value\":{\"namespace\":\"$NS\",\"name\":\"$pvc\"}}]"; done < "/tmp/$MIG-oldpvs.txt"
```

`replace` fails if the PV has no claimRef at all. In that case use
`--type json -p '[{"op":"add","path":"/spec/claimRef","value":{...}}]'`
with the same value. Then recreate each PVC from the manifest saved in
step 4. It keeps the original `storageClassName`, `accessModes`, size and
`volumeName` set to the old PV:

```bash
for p in "${PVCS[@]}"; do kubectl -n "$NS" apply -f "/tmp/$MIG-pvc-$p.json"; done
kubectl -n "$NS" get pvc "${PVCS[@]}" -o wide
```

Each PVC must go `Bound` to its old PV. If one stays `Pending`, run
`kubectl -n "$NS" describe pvc <name>` and `kubectl get pv <old> -o yaml`
and check the claimRef, capacity, access mode and storage class.

4. Resume Flux and force Helm to recreate the Deployment:

```bash
kubectl -n "$NS" label pvc "${PVCS[@]}" migrate.home-ops.io/move- --overwrite
flux -n "$NS" resume helmrelease "$APP"
flux -n "$NS" resume kustomization "$APP"
flux -n "$NS" reconcile helmrelease "$APP" --force
kubectl -n "$NS" rollout status deploy/"$APP" --timeout=5m
kubectl -n "$NS" get pod -l app.kubernetes.io/name="$APP" -o wide
```

The pod should return to the source node, where the old PV lives.
