# CNPG Major-Version PostgreSQL Upgrade Runbook

**Status:** PR 1 (bullseye→bookworm + catalog) merged. Trixie distro hop in flight. PG17→PG18 pending.
**Last reviewed:** 2026-05-26 (cnpg operator 1.29.1, cluster on PG 17.10 bookworm).

Reference: https://cloudnative-pg.io/docs/1.29/postgres_upgrades/

## Prerequisites (already merged)

- `kubernetes/apps/databases/cloudnative-pg/cluster/imagecatalog.yaml` — `ClusterImageCatalog/postgresql` with pinned digests, currently bookworm.
- `kubernetes/apps/databases/cloudnative-pg/cluster/service-aliases.yaml` — version-stable `postgres-{rw,r,ro}` ExternalName Services aliasing the cnpg-managed `postgres17-{rw,r,ro}`.
- Cluster CR uses `imageCatalogRef` (not `imageName`).

## Upgrade plan: 4 PRs (revised after bookworm hop completed; trixie hop added)

### PR 1 — bullseye→bookworm distro hop + catalog/aliases (DONE)

**Branch:** `feat/cnpg-imagecatalog-svc-alias` — merged.

Cluster moved bullseye → bookworm. Catalog + aliases established. PG17 retained.

### PR 2 — bookworm→trixie distro hop (one rolling restart)

**Branch:** `feat/cnpg-distro-hop-trixie`

Bumps the catalog digests for major 17 + 18 from bookworm to trixie. Cluster CR is unchanged (still references `major: 17`). The operator detects the catalog change → digest differs → rolling restart lands on trixie.

Trixie is Debian 13, current stable. cnpg-postgres-containers ships trixie images for both PG17.10 and PG18.4 (verified directly against the registry; the catalog YAMLs in cnpg's repo only ship bookworm + bullseye entries but the runtime images for trixie ARE published).

**No pre-merge patch needed** — `imageName` was already removed in PR 1.

**Expected impact:** ~30s write-unavailable during primary switchover. Replicas re-provision PVCs at the new image. Same shape as the bullseye→bookworm hop.

**Verification post-merge:**

```bash
# Confirm trixie
rtk kubectl exec -n databases postgres17-2 -c postgres --context home -- \
  bash -c 'cat /etc/os-release | grep VERSION_CODENAME'
# VERSION_CODENAME=trixie

# Confirm catalog ref still major 17
rtk kubectl get cluster postgres17 -n databases --context home \
  -o jsonpath='{.spec.imageCatalogRef}'
# {"apiGroup":"postgresql.cnpg.io","kind":"ClusterImageCatalog","name":"postgresql","major":17}

# Confirm PG version unchanged
rtk kubectl cnpg psql postgres17 -n databases --context home -- -tAc 'SELECT version();'
# PostgreSQL 17.10 ... (Debian) — note Debian 13 / trixie in the build string

# Confirm health
rtk kubectl get cluster postgres17 -n databases --context home
# 2/2 Ready, primary set
```

**Verification window:** soak the trixie cluster for at least 24h before proceeding to PR 3. Glibc 2.41 in trixie vs 2.36 in bookworm; ICU collations are explicit-version on cnpg images so collation re-indexing is a non-issue, but spot-check sort-dependent queries.

**Manual pre-merge step (defensive, recommended):**

CNPG validation rejects a Cluster CR that has BOTH `imageName` and `imageCatalogRef`. Flux uses server-side apply with its own field manager (`kustomize-controller`), which DOES drop `imageName` correctly when our manifest doesn't include it — verified via dry-run with `--field-manager=kustomize-controller`. Bare `kubectl apply` (different default manager) shows the failure; Flux is fine.

Despite Flux being able to handle it, the safer move is to clear `imageName` manually before the merge so the operator's first reconcile sees ONLY `imageCatalogRef` and there's zero ambiguity:

```bash
rtk kubectl patch cluster postgres17 -n databases --context home \
  --type=json -p='[{"op":"remove","path":"/spec/imageName"}]'
```

The cluster keeps running on the same image (cnpg caches the resolved digest). Then merge the PR. Flux applies `imageCatalogRef`, operator reconciles, sees the catalog's bookworm digest for major 17 differs from the bullseye digest currently running → triggers a rolling restart that lands on bookworm.

If you skip the manual patch and Flux SSA still works as expected, no harm done. If something gets confused mid-reconcile, run the patch and force a reconcile:

```bash
rtk kubectl patch cluster postgres17 -n databases --context home \
  --type=json -p='[{"op":"remove","path":"/spec/imageName"}]'
rtk flux reconcile ks cloudnative-pg-cluster -n flux-system --context home
```

**Expected impact:** ~30s write-unavailable during primary switchover. Consumers retry. Replicas re-provision their PVCs at the new image.

**Verification post-merge:**

```bash
# Confirm bookworm
rtk kubectl exec -n databases postgres17-2 -c postgres --context home -- \
  bash -c 'cat /etc/os-release | grep VERSION_CODENAME'
# VERSION_CODENAME=bookworm

# Confirm catalog ref
rtk kubectl get cluster postgres17 -n databases --context home \
  -o jsonpath='{.spec.imageCatalogRef}'
# {"apiGroup":"postgresql.cnpg.io","kind":"ClusterImageCatalog","name":"postgresql","major":17}

# Confirm health
rtk kubectl get cluster postgres17 -n databases --context home
# 2/2 Ready, primary set, healthy

# Spot-check consumer connectivity
for app in litellm n8n authentik home-assistant; do
  echo "=== $app ==="
  rtk kubectl logs -n <ns> -l app.kubernetes.io/name=$app --tail=10 --context home | \
    grep -iE 'error|connection|failed' | head -3 || echo "  ok"
done
```

**Verification window:** soak the bookworm cluster for at least 24h before proceeding to PR 2. Watch for autovacuum behavior changes, glibc-driven collation surprises (PG17 retains the same default ICU collation across distros, but spot-check `\dC` output if you have queries that depend on collation order), and any consumer warnings.

### PR 3 — Take fresh backup + bump major to 18 (downtime expected)

**Manual pre-merge step (REQUIRED):**

```bash
# Trigger on-demand backup
rtk kubectl cnpg backup postgres17 -n databases --context home

# Wait + verify
rtk kubectl get backup -n databases --context home
# Status should be "completed" before proceeding

# Sanity: object exists in S3
aws --endpoint-url https://s3.68cc.io s3 ls s3://cloudnative-pg/postgres17-v4/base/ --recursive | tail -3
```

**PR content:**

```diff
- major: 17
+ major: 18
```

in `kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml`.

**What happens after merge:**

1. Operator detects `major:` change.
2. Stops all cluster pods (writes blocked from this point).
3. Validates new image, prepares a fresh PGDATA directory.
4. Runs `pg_upgrade --link` (sub-second per database; hardlinks, doesn't copy).
5. Replaces directories.
6. Destroys replica PVCs and re-provisions them at the new version.
7. Cluster comes back up on PG18.

**Expected window:** 5–15 min for ~1.5 GB across 12 databases on openebs-hostpath.

**Consumer impact during downtime:**

| Consumer | Behavior |
|----------|----------|
| LiteLLM | Gateway stays up; cache-served requests succeed; uncached → upstream fallback if cloud keys configured, else 503 |
| n8n | Workflow runs queue; UI shows DB-down; jobs resume after primary returns |
| Atuin | Sync errors logged; client retries on next sync |
| Home Assistant | Recorder integration logs errors; HA itself stays running |
| Authentik | Auth flows fail mid-flow; new flows wait |
| Linkwarden | UI 5xx; resumes |
| Memos / Paperless | Disabled, irrelevant |

### PR 4 — Post-upgrade verification (no downtime)

**Manual post-merge steps:**

```bash
# 1. Version check
rtk kubectl cnpg psql postgres17 -n databases --context home -- -tAc 'SELECT version();'
# Expected: PostgreSQL 18.4 (Debian ...) on x86_64...

# 2. Cluster healthy
rtk kubectl get cluster postgres17 -n databases --context home
# 2/2 Ready, primary set

# 3. ANALYZE every non-template DB (pg_upgrade doesn't transfer optimizer stats)
for DB in $(rtk kubectl cnpg psql postgres17 -n databases --context home -- -tAc \
  "SELECT datname FROM pg_database WHERE datistemplate=false AND datname<>'postgres';"); do
  echo "=== ANALYZE $DB ==="
  rtk kubectl cnpg psql postgres17 -n databases --context home -- -d "$DB" -c "ANALYZE VERBOSE;"
done

# 4. Reset pg_stat_statements (counters meaningless across version boundary)
rtk kubectl cnpg psql postgres17 -n databases --context home -- -c "SELECT pg_stat_statements_reset();"

# 5. Spot-check consumer connectivity
for ns_app in ai/litellm ai/n8n services/home-assistant security/authentik; do
  ns="${ns_app%/*}"; app="${ns_app#*/}"
  echo "=== $ns/$app ==="
  rtk kubectl logs -n "$ns" -l app.kubernetes.io/name="$app" --tail=10 --context home | grep -iE 'error|connection|failed' | head -5 || echo "  ok"
done

# 6. Take fresh post-upgrade backup
rtk kubectl cnpg backup postgres17 -n databases --context home
```

## Rollback paths

| Stage | Recovery |
|-------|----------|
| Before PR 3 merge | Just don't merge. Catalog + aliases are inert. |
| PR 3 merged but pg_upgrade hasn't completed | Revert the `major: 18 → 17` PR. Operator resumes the old version on the original PGDATA (cnpg's `--link` mode preserves it). |
| pg_upgrade completed but consumers broken | Revert `major: 18 → 17`. Operator restores from the pre-upgrade backup taken in PR 3 prereq via `bootstrap.recovery`. **Bump `serverName` to `postgres17-v5`** in cluster.yaml's `spec.backup.barmanObjectStore` so WAL archives don't collide with the old timeline. |
| Disaster (data loss) | `bootstrap.recovery.source` from `postgres17-v4` (last pre-upgrade serverName) into a fresh cluster. ~1 GB recovery is fast. |

## Consumer migration to `postgres-rw` alias (opportunistic)

The new ExternalName Services let consumers reference the database without the version in the hostname:

| Old | New |
|-----|-----|
| `postgres17-rw.databases.svc.cluster.local` | `postgres-rw.databases.svc.cluster.local` |
| `postgres17-r.databases.svc.cluster.local` | `postgres-r.databases.svc.cluster.local` |
| `postgres17-ro.databases.svc.cluster.local` | `postgres-ro.databases.svc.cluster.local` |

**Don't bulk-migrate.** Each consumer's secret is SOPS-encrypted; touching them all at once is high-risk. Instead, migrate when a consumer's secret is next being edited for any reason (rotated password, new field, etc.).

**Inventory of consumers as of 2026-05-25** (from `git grep postgres17`):

- `kubernetes/apps/security/authentik/app/{helmrelease.yaml,secret.sops.yaml}`
- `kubernetes/apps/security/crowdsec/app/helmrelease.yaml`
- `kubernetes/apps/ai/litellm/app/{helmrelease.yaml,secret.sops.yaml}`
- `kubernetes/apps/ai/n8n/app/secret.sops.yaml`
- `kubernetes/apps/services/home-assistant/app/{helmrelease.yaml,secret.sops.yaml}`
- `kubernetes/apps/services/atuin/app/secret.sops.yaml`
- `kubernetes/apps/services/linkwarden/app/secret.sops.yaml`
- `kubernetes/apps/services/memos/app/secret.sops.yaml` (disabled)
- `kubernetes/apps/services/paperless/app/secret.sops.yaml` (disabled)
- `kubernetes/apps/services/metamcp/app/{helmrelease.yaml,secret.sops.yaml}`
- `kubernetes/apps/velero/exclusions/app/pvc-exclusions.yaml`
- `kubernetes/apps/databases/cloudnative-pg/cluster/{tlsroute.yaml,prometheusrule.yaml,scheduledbackup.yaml}` (operator references; leave as-is)

Direct references to internal cnpg objects (`tlsroute.yaml`, `prometheusrule.yaml`, `scheduledbackup.yaml`) MUST keep using `postgres17-*` because they reference the cnpg-managed Cluster and Services BY NAME. These are not consumer connection strings.

**Procedure to migrate one consumer:**

```bash
# 1. Decrypt
task sops:decrypt-file file=kubernetes/apps/<ns>/<app>/secret.sops.yaml

# 2. Edit: replace `postgres17-rw` → `postgres-rw` (and -r/-ro variants)

# 3. Re-encrypt
task sops:encrypt-file file=kubernetes/apps/<ns>/<app>/secret.sops.yaml

# 4. Verify
task sops:verify

# 5. Same migration in helmrelease.yaml if env values reference postgres17 directly

# 6. Commit + push, single-app PR
```

## Future major bumps (PG18 → PG19 etc.)

Once on imageCatalogRef, the procedure shrinks to:

1. Add the new major to `imagecatalog.yaml`.
2. Take backup.
3. Bump `major:` on the Cluster CR.
4. Run ANALYZE.

The OS-distro constraint still applies — verify the catalog has a bullseye image for the target major. If upstream drops bullseye, the upgrade becomes blue/green via dump/restore (different runbook; not yet authored).
