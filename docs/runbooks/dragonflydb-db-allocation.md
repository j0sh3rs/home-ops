# DragonflyDB — DB Allocation Registry

Single Dragonfly instance (`dragonflydb` in `databases` ns, image `dragonflydb:v1.38.1`, RESP-protocol-compatible with Redis 7.4) is shared across the cluster. To avoid keyspace collisions between consumers, **every consumer must be assigned a dedicated DB index** and connect using `redis://...:6379/<db>`.

This file is the source of truth for DB allocation. Update it when adding or removing a consumer.

## Connection invariants

- Service: `dragonflydb.databases.svc.cluster.local:6379` (RESP)
- Auth: required. Password in Secret `dragonflydb-auth` (key `password`) in `databases` ns. Reflected via Reflector annotation into consumer namespaces.
- URL form: `redis://:<URL-encoded-password>@dragonflydb.databases.svc.cluster.local:6379/<db>`
- **NEVER quote the password**: `'pwd'` becomes part of the literal. SOPS bare values only.
- **URL-encode special chars**: `/` → `%2F`, `@` → `%40`, `:` → `%3A`. Verify with `redis-cli -a "<pwd>" ping` before committing.
- Admin / metrics port: `9999` (HTTP), no auth (`--admin_nopass`). Service `dragonflydb-metrics:9999` exposes `/metrics` (Prometheus exposition) for the master pod only.

## Allocation table (verified live 2026-05-21)

| DB | Consumer | Namespace / app | Purpose | Reference |
|----|----------|------------------|---------|-----------|
| 0 | _(do not assign)_ | — | Default selection on connect; some clients touch it before `SELECT N`. Treat as transient — do NOT store data here. No consumer should target it. | — |
| 1 | _free_ | — | _(stub registry previously claimed Traefik OIDC; verified WRONG — OIDC actually lives on db 5)_ | — |
| 2 | _free_ | — | _(stub registry previously claimed Grafana; verified WRONG — Grafana has no Redis backend in this cluster)_ | — |
| 3 | _free_ | — | — | — |
| 4 | LiteLLM | `ai/litellm` | Response cache (per-request key, TTL 600s). Default key prefix. | `kubernetes/apps/ai/litellm/app/{configmap,helmrelease,secret.sops}.yaml` |
| 5 | traefikoidc plugin | `network/traefik-{external,internal}` + `components/traefik-oidc` | OIDC session store (Google login state, refresh tokens). Heavy hit ratio (~90%). Key prefix `traefikoidc:google:`. Single shared store across all opted-in namespaces — same user across all sites. | `kubernetes/components/traefik-oidc/google-oidc-secure.yaml` |
| 6 | _free_ | — | — | — |
| 7 | _free_ | — | — | — |
| 8 | _free_ | — | — | — |
| 9 | _free_ | — | — | — |
| 10 | _free_ | — | — | — |
| 11 | _free_ | — | — | — |
| 12 | _free_ | — | — | — |
| 13 | _free_ | — | — | — |
| 14 | _free_ | — | — | — |
| 15 | _free_ | — | — | — |

Dragonfly supports DBs 0-15 by default (matches Redis convention).

## Future / planned consumers

When deploying any of the following, allocate the next free DB and update this table in the same PR:

| Likely consumer | Suggested DB | Notes |
|-----------------|--------------|-------|
| AnythingLLM (RAG cache) | 6 | Phase 2 of AI stack rollout. Pgvector handles embeddings; Redis only for ephemeral cache. |
| Mem0 / Letta | 7 | Phase 6 memory layer. May not need Redis if Postgres-backed. |
| Paperless (re-enabled) | 8 | Currently disabled. Historical config used default DB 0 (`PAPERLESS_REDIS=redis://...:6379` with no `/N` selector) — re-enable means moving to a dedicated index. |
| n8n queue mode | 9 | n8n currently uses Postgres for state. Switch to BullMQ would consume a Redis DB. |
| Open WebUI session cache | 10 | OWUI uses SQLite/Postgres for chat history; Redis would be opt-in for distributed cache. |

## Verification commands

Check current allocation:

```bash
PASS=$(rtk kubectl get secret -n databases dragonflydb-auth -o jsonpath='{.data.password}' --context home | base64 -d)
rtk kubectl run -n databases df-info --rm -i --restart=Never --image=redis:7-alpine --context home -- \
  redis-cli -h dragonflydb.databases.svc.cluster.local -p 6379 -a "$PASS" INFO keyspace
```

Expected output shape:

```
# Keyspace
db0:keys=0,expires=0,...     # transient — DO NOT store here
db4:keys=N,expires=N,...     # LiteLLM cache
db5:keys=N,expires=N,...     # traefikoidc sessions
```

Identify which client is connected to which DB:

```bash
rtk kubectl run -n databases df-clients --rm -i --restart=Never --image=redis:7-alpine --context home -- \
  redis-cli -h dragonflydb.databases.svc.cluster.local -p 6379 -a "$PASS" CLIENT LIST | \
  grep -oE 'addr=[0-9.]+:[0-9]+ .*db=[0-9]+' | sort -u
```

Map pod IP (`addr=10.42.X.Y`) to consumer:

```bash
rtk kubectl get pod -A -o wide --context home | grep '10.42.X.Y'
```

Probe metrics directly (no auth):

```bash
kubectl port-forward -n databases dragonflydb-0 19999:9999 --context home
curl -s http://127.0.0.1:19999/metrics | grep '^dragonfly_db_keys'
# dragonfly_db_keys{db="0"} 0
# dragonfly_db_keys{db="4"} 6
# dragonfly_db_keys{db="5"} 2
```

## Operational notes

- **Single replica.** No HA. Pod restart = full data loss. All consumers MUST treat dragonfly as a cache, not a primary store. Anything that needs durability lives in CNPG or S3.
- **No persistence configured.** Dragonfly writes a snapshot to its emptyDir on graceful shutdown but the operator's default rolling pod replacement may not honor that. Assume `kubectl delete pod` = empty cache after restart.
- **Memcached protocol** also exposed via separate Service `dragonflydb-memcached:11211` for legacy clients. No password supported on memcached protocol — do not use for sensitive data. No current consumers.
- **Operator manages the `dragonflydb` Service** (RESP only, port 6379). The metrics-port Service `dragonflydb-metrics` (9999) is a sibling defined in `instance/instance.yaml` to avoid touching the operator-controlled object.
- **`primary_port_http_enabled=false`** (operator default) — `:6379` serves only RESP, NOT HTTP. To probe metrics use `:9999`. To probe RESP use `redis-cli`.

## Related documentation

- LiteLLM REDIS_URL gotchas (URL-encoding, no quotes, DB selector required): memory `project_ai_stack_plan.md`
- traefikoidc plugin auth pattern: memory `project_auth_traefikoidc.md`
- Grafana dashboard: monitoring ns, dashboard "Dragonfly Dashboard" (uid `xDLNRKUWz`), backed by upstream JSON in `kubernetes/apps/monitoring/grafana/dashboards/app/dragonflydb-dashboard.json` (last upstream pull: 2026-05-21).
