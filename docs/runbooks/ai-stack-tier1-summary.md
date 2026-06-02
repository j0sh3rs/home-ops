# AI Stack Tier 1 — Build Summary & Next Steps

Generated: 2026-06-01
Branch: main (pushed to origin)

---

## What Was Built

This session deployed 6 new components into the `ai` namespace and migrated one existing one.

### Component Map

```
                      ┌─────────────────────────────┐
                      │         CLIENTS              │
                      │  Open WebUI · n8n            │
                      └──────────┬──────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │     OWUI Pipelines       │  port 9099
                    │  (model router)          │  routes: code→coder, short→fast, else→balanced
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │         LiteLLM          │  port 4000
                    │  (gateway + routing)     │◄──── LangFuse traces (success+failure callbacks)
                    └─┬────────┬──────────────┘
                      │        │
               ┌──────▼─┐  ┌──▼──────────────┐
               │llama-  │  │  Cloud (Anthropic │
               │swap    │  │  / OpenAI)        │
               │(local) │  │  (keys in secret) │
               └────────┘  └─────────────────-┘

  OBSERVABILITY              MEMORY              VOICE
  LangFuse                   Mem0 (suspended)    faster-whisper (STT) ← HA Assist
  port 3000                  port 8000           piper (TTS) ← HA Assist
  langfuse.68cc.io           http://mem0:8000    Wyoming protocol TCP

  VECTOR STORE
  pgvector on postgres18 (CNPG)
  ← AnythingLLM (migrated from LanceDB)
  ← Mem0 (when unsuspended)
```

---

## Per-Component Status & Required Steps

### 1. AnythingLLM — pgvector migration
**Status:** Deployed, vector store migrated.
**Action required:** Re-ingest all documents.

```
1. Browse https://anythingllm.68cc.io
2. Each workspace → Documents → Re-embed all documents
3. Verify: kubectl exec -n databases postgres17-1 --context home --      psql -U postgres -d anythingllm -c      "SELECT tablename, n_live_tup FROM pg_stat_user_tables WHERE n_live_tup > 0 ORDER BY n_live_tup DESC LIMIT 10;"
   Expect non-zero rows in vector-related tables.
```

**What changed:** `VECTOR_DB: lancedb` → `VECTOR_DB: pgvector`. The old LanceDB PVC still exists
at 30Gi — shrink or delete it once re-ingest is confirmed successful.

---

### 2. LangFuse — LLM observability
**Status:** Fix committed (needs push + reconcile). Chart v1.5.33 requires ClickHouse.
**URL:** https://langfuse.68cc.io (LAN only, Authentik SSO)
**Postgres DB:** `langfuse` on postgres18 CNPG
**DragonflyDB:** DB 6
**ClickHouse:** bundled single-node (deployed by Helm chart)

**Required actions:**

```
1. git push  (to trigger Flux reconcile)
2. Watch reconcile:
   flux get hr -n ai langfuse --context home --watch
   Expect: "Helm install succeeded"
3. ClickHouse pod will take ~3-5 min to become ready on first deploy.
4. First login:
   - Browse https://langfuse.68cc.io
   - Create admin account (Authentik SSO handles auth at gateway level,
     but LangFuse still needs an internal user for its own session)
   - Create a project named "home-ops"
5. Verify traces arriving:
   - Send any message in Open WebUI
   - LangFuse UI → Traces — request should appear within ~10 seconds
6. Optional: rotate LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY to proper
   random values (currently "pk-lf-homeops-2026" / "sk-lf-homeops-2026"):
   task sops:edit file=kubernetes/apps/ai/langfuse/app/secret.sops.yaml
   task sops:edit file=kubernetes/apps/ai/litellm/app/secret.sops.yaml
   (both must have the same key values)
```

**Wiring:** LiteLLM `litellm_settings.success_callback: ["langfuse"]` is live.
LangFuse host in LiteLLM secret: `http://langfuse-web.ai.svc.cluster.local:3000`.

---

### 3. faster-whisper — Speech-to-Text
**Status:** Running.
**Image:** `fedirz/faster-whisper-server:0.6.0-rc.3-cpu`
**Model:** `tiny.en` (downloads on first start, cached to 2Gi PVC)
**Wyoming port:** 10300 TCP
**Cluster DNS:** `faster-whisper.ai.svc.cluster.local:10300`

**Required action — wire into Home Assistant:**
```
Settings → Devices & Services → Add Integration → Wyoming Protocol
  Host: faster-whisper.ai.svc.cluster.local
  Port: 10300

Settings → Voice Assistants → Assist
  Speech-to-text: faster-whisper
```

**Note:** First request after pod start will be slow (~5s) while the model loads.
Subsequent requests are <1s. Model is cached in the PVC — pod restarts are fast.

**Upgrade path:** When upgrading, check https://hub.docker.com/r/fedirz/faster-whisper-server
for `*-cpu` versioned tags. Renovate comment is in place but Docker Hub versioning
for this image is irregular. Consider upgrading to `base.en` or `small.en` for
better accuracy once voice use is established (at cost of more memory).

---

### 4. Piper — Text-to-Speech
**Status:** Running.
**Image:** `rhasspy/wyoming-piper:2.2.2`
**Voice:** `en_US-lessac-medium` (downloads ~65MB on first start, cached to 1Gi PVC)
**Wyoming port:** 10200 TCP
**Cluster DNS:** `piper.ai.svc.cluster.local:10200`

**Required action — wire into Home Assistant:**
```
Settings → Devices & Services → Add Integration → Wyoming Protocol
  Host: piper.ai.svc.cluster.local
  Port: 10200

Settings → Voice Assistants → Assist
  Text-to-speech: piper
```

**Note:** First start takes ~2 min to download the voice model. The pod will show
Running but not respond to Wyoming requests until the download completes.
Check logs: `kubectl logs -n ai -l app.kubernetes.io/name=piper --context home`

**Other voices available:** Change `--voice en_US-lessac-medium` in
`kubernetes/apps/ai/piper/app/helmrelease.yaml` args. Full list:
https://rhasspy.github.io/piper-samples/

---

### 5. Mem0 — Episodic Memory Layer
**Status:** SUSPENDED — no public Docker image exists yet.
**Suspend reason:** `ghcr.io/mem0ai/mem0-server` is not published by upstream CI.
The project ships source only; a Dockerfile exists at
`https://github.com/mem0ai/mem0/tree/main/server` but no built image is available.

**To unsuspend when an image becomes available:**
```
1. Update image tag in kubernetes/apps/ai/mem0/app/helmrelease.yaml
   (change tag: latest to the actual versioned tag)
2. Remove `suspend: true` from the HelmRelease spec
3. Commit and push
4. Open WebUI is already wired: MEMORY_PROVIDER=mem0_server, MEM0_API_BASE_URL=http://mem0:8000
```

**Track upstream:** https://github.com/mem0ai/mem0/pkgs/container/mem0-server
Or watch: https://github.com/mem0ai/mem0/blob/main/server/Dockerfile for CI additions.

**Alternative:** If upstream never publishes, build and push to your own registry:
```bash
git clone https://github.com/mem0ai/mem0 /tmp/mem0
docker build -t ghcr.io/<your-ghcr>/mem0-server:latest /tmp/mem0/server
docker push ghcr.io/<your-ghcr>/mem0-server:latest
# Update helmrelease image reference to your registry
```

**Postgres DB pre-provisioned:** `mem0` DB on postgres18 will be created by init-db
initContainer on first reconcile after unsuspend. pgvector extension will be enabled
automatically (it's available on the cluster image).

---

### 6. OWUI Pipelines — Model Router
**Status:** Running.
**Port:** 9099 (OWUI points here instead of LiteLLM directly)
**Image:** `ghcr.io/open-webui/pipelines:git-2bd3ba3` (pinned git SHA, no semver available)

**Routing logic (configmap model_router.py):**
```
Message content signal       → Model routed to
─────────────────────────────────────────────────
Code keywords (def/func/write code/debug/etc.)  → local-coder   (Qwen2.5-Coder-7B)
Short message (< 50 chars)                       → local-fast    (Qwen3-1.7B)
Everything else                                  → local-balanced (Qwen3-4B)
```

**Verify routing is working:**
```
1. Send "hi" in OWUI → should route to local-fast
2. Send "write a Python function to sort a list" → should route to local-coder
3. Send "explain how kubernetes networking works in detail" → should route to local-balanced
4. Check LangFuse traces to confirm model field matches expected routing
```

**To tune routing:** Edit `kubernetes/apps/ai/owui-pipelines/app/configmap.yaml`.
Change `SHORT_MSG_THRESHOLD`, add/remove code patterns, or change model targets.
Reloader will restart the pod automatically on ConfigMap change.

**Security note:** `OPENAI_API_KEY` in owui-pipelines-secrets currently holds the
LiteLLM master key. Mint a dedicated virtual key before exposing OWUI externally:
```bash
curl -X POST https://litellm.68cc.io/key/generate   -H "Authorization: Bearer <LITELLM_MASTER_KEY>"   -H "Content-Type: application/json"   -d '{"key_alias": "owui-pipelines", "models": ["local-fast","local-balanced","local-coder","local-coder-small","local-large","local-embed","local-rerank"]}'
# Update owui-pipelines-secrets.OPENAI_API_KEY with the returned sk-... value
```

---

## DragonflyDB DB Allocation

**Source of truth:** `docs/runbooks/dragonflydb-db-allocation.md`

| DB | Consumer | Namespace | Purpose |
|----|----------|-----------|---------|
| 0 | _(reserved)_ | — | Default selection; transient only — do NOT store data |
| 1–3 | _free_ | — | — |
| 4 | LiteLLM | ai/litellm | Response cache (TTL 600s) |
| 5 | _(retired)_ | — | Previously: traefikoidc OIDC sessions (replaced by Authentik forwardAuth 2026-05-21) |
| 6 | Authentik | security/authentik | Celery broker, Django cache, channels layer |
| 7–15 | _free_ | — | — |

**Note:** LangFuse uses configurable Redis DB selector via REDIS_URL secret key (not pinned to a specific DB allocation). Currently empty-selector (default DB 0 transient); future: allocate dedicated DB when LangFuse queue persistence needed. Mem0 (when unsuspended) not yet allocated — will claim DB 7+ when deployed with Redis persistence.

---

## Secrets Inventory (ai namespace)

| Secret | Keys | Used by |
|--------|------|---------|
| `litellm-secrets` | master key, DB URL, redis URL, Anthropic/OpenAI keys, LangFuse keys | LiteLLM |
| `langfuse-secrets` | NEXTAUTH_SECRET, SALT, CLICKHOUSE_PASSWORD, DB URL, Redis URL, LangFuse keypair | LangFuse |
| `anythingllm-secret` | JWT_SECRET, DB URL, VECTOR_DB_CONNECTION_STRING, LiteLLM virtual key | AnythingLLM |
| `open-webui-secrets` | WEBUI_SECRET_KEY, OPENAI_API_KEY (→ pipelines), MEM0_API_KEY | Open WebUI |
| `owui-pipelines-secrets` | PIPELINES_API_KEY, OPENAI_API_KEY (LiteLLM master), OPENAI_BASE_URL | OWUI Pipelines |
| `mem0-secrets` | MEM0_API_KEY, INIT_POSTGRES_*, POSTGRES_URL | Mem0 |
| `n8n-secrets` | DB URL, encryption key | n8n |

---

## Pending Work / Known Issues

| Item | Priority | Notes |
|------|----------|-------|
| AnythingLLM re-ingest | High | All existing RAG vectors lost in LanceDB→pgvector migration |
| LangFuse ClickHouse fix | High | Pushed — wait for reconcile (~5 min) |
| Wire HA Assist voice | Medium | Manual step in HA UI (faster-whisper + piper DNS addresses above) |
| Mint dedicated LiteLLM virtual key for pipelines | Medium | Currently uses master key |
| Rotate LangFuse API keypair to random values | Low | Currently uses readable placeholder strings |
| Mem0 unsuspend | Blocked | Waiting on upstream Docker image publication |
| AnythingLLM LanceDB PVC cleanup | Low | 30Gi can be reclaimed after re-ingest confirmed |
| OWUI Pipelines image pinning | Low | Using git SHA; watch for upstream semver tagging |
| Voice model upgrade | Low | `tiny.en` → `base.en` or `small.en` for better STT accuracy |

---

## Flux Kustomization Graph (ai namespace)

```
cloudnative-pg (databases)
cloudnative-pg-cluster (databases)  ─┬──→ anythingllm
dragonflydb-instance (databases)  ───┤──→ litellm ──→ owui-pipelines ──→ open-webui
                                     ├──→ langfuse
                                     └──→ mem0 (suspended)

llama-swap ──→ litellm

(no dependsOn)  ──→ faster-whisper
(no dependsOn)  ──→ piper
(no dependsOn)  ──→ n8n
```
