# Flux and PostgreSQL recovery, 2026-10-23

## Cause and scope

The pi session recorded repeated deletion of the root GitRepository and uninstallation/reinstallation of the FluxInstance Helm release. Recovery commits ce1d041e and 77a077d1 removed SOPS decryption from the root and application Kustomizations. Encrypted `ENC[...]` values were subsequently applied directly into Kubernetes Secrets, including the namespace-local age keys. Many Kustomizations reported Ready even though their applications could not use those Secrets.

The recreated PostgreSQL cluster had a new system ID, fresh PVCs, and only the default databases. Most other application PVCs survived. Restoring deployments alone could not recover the missing application databases.

## PostgreSQL recovery

Recovery uses the Barman Cloud plugin and PostgreSQL 18.4 image already pinned in the image catalog. The Cluster resource keeps the `postgres17` name for service and credential compatibility.

- Source ObjectStore and archive prefix: `postgres18-v1`.
- Completed base backup: `20261022T040000`, original system ID `7644568095216218142`, timeline 23.
- Last observed archived WAL: `0000001700000179000000B9`, uploaded at `2026-10-22T20:33:42Z`. This upload time is an approximate recovery bound, not an exact last-transaction timestamp.
- Bootstrap recovery pins that backup and timeline and replays all available WAL.
- New backup ObjectStore and archive prefix: `postgres18-v2`. The source ObjectStore has no retention policy; recovery must not prune its source archive.
- The empty replacement cluster's two PVs were changed to `Retain` before its Cluster/PVC objects were removed. Their identifiers are `pvc-91dc806f-2a3b-440d-9bcc-3630003dd951` and `pvc-fb1d2e8a-147f-4de3-93ff-6e115381afe6`. They contain the failed empty replacement, not the original application data.

The restored cluster reached two ready instances on timeline 24, with the original system ID. Its databases include `atuin`, `authentik`, `crowdsec`, `gatus`, `hindsight`, `homeassistant`, `linkwarden`, `memos`, `n8n`, `paperless`, and `vikunja`.

For a future disaster, inspect the newest backup and WAL in the current archive and advance the archive generation again. The checked-in bootstrap records this recovery; do not reuse its historical backup blindly for a later incident. Never bypass the empty-WAL-archive check or write a recovered cluster into its source archive.

## Reconciliation repair

1. Temporarily suspend the root and database Kustomizations while preparing recovery. Check their suspension again after parent reconciliations; old desired state can undo imperative changes.
2. Restore the root `sops-age` Secret from the local encrypted manifest using the repo's age key. Pipe decryption directly to kubectl; do not write plaintext Secrets to disk or logs.
3. Restore decryption on `cluster-meta`, `cluster-apps`, and application Kustomizations. `cluster-apps` decrypts namespace bootstrap Secrets before applying the children. Goldilocks contains no encrypted resources and does not need a namespace-local key.
4. Keep the FluxInstance root decryption patch in its Helm values, so operator reconciliation preserves it.
5. Publish the repair before resuming the root/database Kustomizations. Recheck for ciphertext in live Secret values; resource Ready status alone is insufficient.
6. Reset exhausted Helm retries after their causes are repaired, and restart consumers that loaded old Secret values through environment variables.
7. Verify both PostgreSQL replication and continuous WAL archiving, then complete a new base backup into the new archive.

Additional bootstrap fixes split the AMD operator from its DeviceConfigs, correct Goldilocks flags from a list to a map, and configure the Flux chart publisher's Cosign identity. The FluxInstance HelmRelease adopts the existing `flux` Helm release, matching bootstrap, without uninstalling the operator-managed instance.

## References

- https://cloudnative-pg.io/docs/devel/recovery/
- https://cloudnative-pg.io/plugin-barman-cloud/docs/usage/
- https://fluxcd.io/flux/components/kustomize/kustomizations/
- https://fluxcd.io/flux/components/source/ocirepositories/
