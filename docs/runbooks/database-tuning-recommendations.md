# Database Tuning Recommendations (post-AI-adoption)

**Audit date:** 2026-05-21
**Scope:** CloudNativePG `postgres17` cluster (databases ns) + DragonflyDB `dragonflydb` instance (databases ns).
**Companion PR (this branch):** monitoring (alerts + dashboards).
**Companion PR (planned, not yet authored):** performance tuning (the items in this doc).

This doc captures the audit findings + the changes deferred to PR 2. Apply during a low-traffic window — PG parameter changes restart pods one at a time (rolling update with quorum gating); dragonfly resource bumps cause a brief restart.

---

## CloudNativePG findings

### Live state (probed 2026-05-21)

- Operator chart: `0.28.2` (latest)
- Cluster: `postgres17`, image `ghcr.io/cloudnative-pg/postgresql:17`, 2 instances (`postgres17-1`, `postgres17-2`), healthy
- Storage: 40 GiB per instance, ~1.5 GB used cluster-wide (12 databases)
- Resources: `requests.cpu=500m`, no memory request, `limits.memory=4Gi`, no CPU limit
- Backups: barman → `s3://cloudnative-pg/`, last backup 12h ago (healthy), 30d retention
- Metrics scrape: working (PodMonitor `postgres17`, vmagent ingests, 26+ series)
- Grafana dashboard ConfigMap: present (`cnpg-grafana-dashboard` in databases ns) but no `GrafanaDashboard` CR — dashboard never imported into Grafana. **Fixed in this PR.**
- Alert rules: 8 baseline + 7 added in this PR = 15 total

### Parameter audit

| Parameter | Current | Recommended | Why |
|-----------|---------|-------------|-----|
| `shared_buffers` | `512MB` | `1GB` | 25% rule on 4 GB limit. Bigger buffer cache = better hit ratio under AI/RAG read patterns. |
| `effective_cache_size` | `4GB` (default) | `3GB` | Should reflect available memory minus shared_buffers minus OS. 3 GB on 4 GB pod is honest. |
| `work_mem` | `4MB` (default) | `16MB` | RAG workloads: sort merges, GIN index scans, large IN-lists spill to disk at 4 MB. 16 MB×concurrency stays within budget. |
| `maintenance_work_mem` | `64MB` (default) | `256MB` | Vacuum + index builds slow on growing tables. Set per-session if you don't want it always reserved. |
| `max_connections` | `500` | `200` | 500 backends × ~10 MB = 5 GB ceiling, exceeds the 4 GiB limit. The stat looks high but the cluster will OOM long before reaching it. Pair with PgBouncer (Pooler CR) at 1000:200 ratio. |
| `random_page_cost` | `4` (default) | `1.1` | Default tuned for spinning disks. NVMe (openebs-hostpath) responds in single-digit microseconds. Lower cost = planner picks index scans more often. |
| `track_io_timing` | `off` | `on` | pg_stat_statements without io_timing hides whether queries are CPU- or IO-bound. Negligible overhead on Linux clock_gettime. |
| `track_activity_query_size` | `1kB` (default) | `4kB` | RAG queries with embedded vectors get truncated in `pg_stat_activity` at 1 kB. |
| `shared_preload_libraries` | `""` | `pg_stat_statements,auto_explain` | pg_stat_statements is installed only in `app` DB today. Pre-loading makes it available globally without per-DB `CREATE EXTENSION`. auto_explain logs slow query plans to controller logs. |
| `auto_explain.log_min_duration` | n/a | `1s` | Logs `EXPLAIN ANALYZE` for any query >1s. Cheap, hugely useful for forensics. |
| `auto_explain.log_analyze` | n/a | `on` | Run-time stats in the log. |
| `auto_explain.log_buffers` | n/a | `on` | Buffer hit/read counts. |
| `auto_explain.sample_rate` | n/a | `0.5` | Half of slow queries get full analyze; other half just log. Reduces overhead spike when many slow queries fire at once. |
| `pg_stat_statements.max` | `10000` | (keep) | Already set. |
| `pg_stat_statements.track` | `all` | (keep) | Already set. |
| `wal_compression` | `off` (default) | `on` | Talos kernel has `lz4` available. Smaller WAL → faster replay, less S3 transfer. |
| `wal_buffers` | `16MB` | (keep) | Default already auto-tuned to `shared_buffers/32`. Will scale with shared_buffers bump. |
| `synchronous_commit` | `on` (default) | (keep) | Don't relax — durability matters more than throughput for the small writes this cluster handles. |
| `huge_pages` | `try` (default) | (keep) | Talos kernel doesn't pre-allocate hugepages; `try` falls back gracefully. Switch to `on` only after pre-allocating via Talos kernel cmdline. |
| `jit` | `on` (default) | `off` | Default is on PG 17. JIT compilation is overhead-positive only for very long analytical queries. Most workloads here are short OLTP. |

### Resource shape

| Resource | Current | Recommended | Why |
|----------|---------|-------------|-----|
| `requests.memory` | unset | `2Gi` | Without a memory request, k8s can over-commit and evict the primary under pressure. 2 Gi reserve = 50% of limit, matches working set. |
| `limits.cpu` | unset | (leave unset) | Burstable scheduling is correct for PG — it's spiky. |
| `requests.cpu` | `500m` | `1000m` | 500m gets out-scheduled by competitor pods. Default to 1 vCPU floor; can scale down later. |
| `storage` | `40Gi` | (keep) | 12% used. Plenty of headroom. |

### Pgvector for RAG

- Extension: `vector v0.8.1` is bundled in `ghcr.io/cloudnative-pg/postgresql:17` but NOT installed.
- AnythingLLM (planned phase 2 of AI stack) will need it.
- **Action:** PR 2 adds `vector` to `spec.bootstrap.initdb.postInitTemplateSQL` so it's auto-installed in `template1`, propagating to every new database. Existing databases need manual `CREATE EXTENSION vector;` per-DB, but that's per-tenant work for the consumer.

### Connection pooling (PgBouncer Pooler CR)

CNPG ships first-class PgBouncer support via the `Pooler` CR. **Add when adoption pushes backends >150 sustained**, which the new `CNPGConnectionsNearLimit` alert will catch. Skeleton:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Pooler
metadata:
  name: postgres17-rw-pooler
  namespace: databases
spec:
  cluster:
    name: postgres17
  instances: 2
  type: rw
  pgbouncer:
    poolMode: transaction  # session for n8n compatibility, transaction for everything else
    parameters:
      max_client_conn: "1000"
      default_pool_size: "25"
```

Consumers that re-use prepared statements (n8n, some ORMs) need `pool_mode: session`. Run a per-app pooler if pool modes diverge.

### Custom-query metrics for richer alerts

Several alerts that would be useful (dead tuples, p99 query latency, table-level cache hit) require **custom queries** registered with the cnpg metrics exporter. cnpg supports this via `monitoring.customQueries` on the Cluster CR. Sample (PR 2):

```yaml
spec:
  monitoring:
    customQueries:
      - name: pg_stat_statements
        query: |
          SELECT (pg_database.datname)::text AS datname,
                 pg_stat_statements.query AS query,
                 pg_stat_statements.calls AS calls,
                 pg_stat_statements.mean_exec_time AS mean_exec_time
          FROM pg_stat_statements
          JOIN pg_database ON pg_database.oid = pg_stat_statements.dbid
          ORDER BY mean_exec_time DESC LIMIT 20;
        metrics:
          - datname:
              usage: "LABEL"
          - query:
              usage: "LABEL"
          - calls:
              usage: "COUNTER"
          - mean_exec_time:
              usage: "GAUGE"
```

---

## DragonflyDB findings

### Live state (probed 2026-05-21)

- Operator chart: pinned via OCIRepository (Renovate-tracked)
- Instance: `dragonflydb`, image `dragonflydb:v1.38.1`, single replica
- Resources: `requests.cpu=500m`, `requests.memory=500Mi`, `limits.cpu=1`, `limits.memory=2Gi`
- Args: `--memcached_port=11211`, `--default_lua_flags=allow-undeclared-keys`, plus operator defaults (`--admin_port=9999`, `--admin_nopass`, `--primary_port_http_enabled=false`)
- Persistence: none — emptyDir, snapshots not configured
- Auth: enforced via `dragonflydb-auth` Secret
- Metrics scrape: ServiceMonitor on admin port `:9999/metrics` (this PR + previous)
- DB allocation: db 0 (transient), db 4 (LiteLLM cache), db 6 (Authentik Celery/cache/channels). See `dragonflydb-db-allocation.md`.
- Alert rules: 0 → 10 in this PR

### Resource shape

| Resource | Current | Recommended | Why |
|----------|---------|-------------|-----|
| `requests.memory` | `500Mi` | `2Gi` | Each LiteLLM-cached request is small but the AI cache grows quickly. 500Mi reserve = swap city under load. |
| `limits.memory` | `2Gi` | `4Gi` | Doubles room for Authentik + LiteLLM + AnythingLLM cache. |
| `requests.cpu` | `500m` | (keep) | Dragonfly is single-threaded per shard; rarely CPU-bound. |
| `limits.cpu` | `1` | (keep) | No reason to constrain harder. |

### Persistence

Dragonfly supports periodic snapshots via `--save_schedule`. Useful because:
- After a pod restart, all caches start cold → consumer latency spike.
- Authentik sessions cold = users re-authenticate (mild annoyance, not failure).
- LiteLLM cache cold = first hits hit upstream models (slow, expected).

**Recommendation (PR 2):** Add a small (5 GiB) PVC mounted at `/data` and enable `--snapshot_cron=*/30 * * * *` (every 30 min). On pod restart, dragonfly auto-loads the snapshot. Loss window = 30 min, acceptable for cache.

```yaml
# Excerpt for instance.yaml in PR 2
spec:
  args:
    - --logtostderr
    - --memcached_port=11211
    - --default_lua_flags=allow-undeclared-keys
    - --dir=/data
    - --snapshot_cron=*/30 * * * *
    - --maxmemory_policy=allkeys-lru
  storage:
    size: 5Gi
    storageClassName: openebs-hostpath
```

### Eviction policy

Currently unset → defaults to `noeviction` (returns errors on memory full). For a cache, **always set `--maxmemory_policy=allkeys-lru`** so old keys drop instead of erroring. The `DragonflyMemoryCritical` alert will fire before this matters in practice, but defense-in-depth.

### Replica strategy

Currently `replicas: 1`. Dragonfly operator supports `replicas: 2+` for read-replica + automatic failover. **Don't add yet** — adoption isn't high enough to justify the operational complexity and the workload is cache (loss is fine). Revisit if the cluster ever depends on dragonfly being up for primary writes (it should never, by policy).

### Snapshot to S3

Dragonfly does not have built-in S3 export. If snapshot durability matters (it shouldn't for a cache), add a Velero hook on the dragonfly pod that runs `redis-cli -a $PASS BGSAVE` before the daily PVC snapshot. Probably overkill for a cache; skip.

---

## Risk + rollout plan for PR 2

### Risk register

| Change | Risk | Mitigation |
|--------|------|------------|
| `shared_buffers` bump | Pod OOM if memory request unset | Set memory request first |
| `max_connections` cut | Existing apps may have hardcoded connection counts | Audit consumers; Pooler CR before cut |
| `shared_preload_libraries` add | Restart-required parameter; cnpg handles via rolling restart | Test on staging? — N/A here. Run during low-traffic window. |
| pgvector preload via initdb | Affects new clusters only, not existing template1 | Add `CREATE EXTENSION vector;` to bootstrap.initdb.postInitSQL too |
| Dragonfly PVC add | First reconcile = pod restart = cache loss | Acceptable (cache); schedule during off-peak |
| Dragonfly maxmemory_policy change | Apps that rely on default noeviction-style errors | None of our consumers do; LRU is the right default |

### Rollout order (PR 2)

1. Bump CNPG resource requests (no PG restart, just k8s scheduling).
2. Add Pooler CR. Consumers continue to talk to `postgres17-rw` direct; pooler available on `postgres17-rw-pooler-rw`.
3. Migrate one consumer to pooler (n8n? lowest blast radius). Verify.
4. Migrate the rest opportunistically.
5. Bump CNPG parameters (rolling restart enforced by cnpg).
6. Bump dragonfly resources.
7. Add dragonfly PVC + snapshot config (one-time cache loss).
8. Add dragonfly eviction policy.

### Verification (per change)

- After PG param bump: `kubectl exec postgres17-2 -c postgres -- psql -U postgres -c 'SHOW shared_buffers;'`
- After dragonfly resize: `kubectl exec dragonflydb-0 -- redis-cli -a $PASS CONFIG GET maxmemory`
- After PVC: `kubectl exec dragonflydb-0 -- ls /data/`
- All alerts: `kubectl logs -n monitoring vmalert-vmalert-0 | grep -i 'cnpg\|dragonfly'`
