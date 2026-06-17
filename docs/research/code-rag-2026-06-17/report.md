# P2 Code-RAG Research Spike

**Date:** 2026-06-17
**Status:** Complete — verdict reached
**Feeds:** spec §6 axes; gates P3

---

## Repo Inventory (Measured)

| Category | Count |
|---|---|
| Total files | ~993 |
| YAML files | 566 |
| Meaningful operational YAML | ~314 (excl. CRD blobs, encrypted SOPS, dashboards) |
| HelmReleases | 55 |
| Flux Kustomizations (ks.yaml) | 62 |
| kustomization.yaml overlays | 77 |
| Markdown worth indexing | ~40 (docs/, CLAUDE.md, memory files) |

**Token budget for full meaningful corpus:** ~314 files × ~450 avg tokens = ~112,000 tokens.
Entire indexable repo fits in one 200K context window.

**Embedder reality check:** Resident embedder is `Qwen3-Embedding-0.6B-Q8_0`
(1024 dims), exposed via llama-swap as `embed-nomic` alias through LiteLLM.

**pgvector status:** Already live in postgres18 (AnythingLLM uses it). Zero new infra.

**Repo change rate:** ~10 commits/day, heavily Renovate bot bumps.

---

## Skeptic's Prior Verdict

**Live grep beats dedicated vector RAG for YAML/GitOps operational queries.**
**Vector indexing earns its keep only for ~40 prose files (runbooks, ADRs, memory, CLAUDE.md).**

Evidence:
- `grep -r "nfs-client" kubernetes/` → 21ms, 4 files, ~250 tokens, zero false positives
- `grep -r "storageClass" kubernetes/` → 19ms, 20 lines, complete PVC coverage
- Semantic gap vector search closes does not materialize in a single-operator repo
  with consistent conventions ("nfs-client" is always that string)
- 112K token YAML corpus fits in one context window — vector compression adds no value
- 10 commits/day pushes incremental indexing overhead that grep never needs
- Prose queries ("rationale for rejecting Ollama", "CNPG failover procedure") return
  nothing useful from grep → prose IS worth indexing

---

## Decision

| Question | Answer |
|---|---|
| Build vector index for YAML? | **No.** Grep is faster, more precise, zero infra. |
| Build vector index for prose? | **Yes.** pgvector on postgres18, ~200 chunks. |
| New pods required? | **None.** pgvector + embedder + reranker all already resident. |
| Grep harness effort | 1 afternoon |
| Prose index effort | 1–2 days |

---

## Recommended Stack (Prose Index Only)

| Axis | Choice | Reasoning |
|---|---|---|
| Vector DB | pgvector on postgres18 | Already live, zero new pods, one new table |
| Embedder | `local-embed` (qwen3-embed, resident) | Always-on, $0 |
| Reranker | `rerank-bge` (qwen3-rerank, resident) | Already resident; top-20 → top-3 |
| Chunking | Header-based Markdown split on `##`/`###` | Each section ~200–600 tokens |
| YAML chunking | **Don't index YAML** | Use grep |
| Index trigger | Daily CronJob or n8n webhook | Prose changes ~1x/week |
| Chunk count | ~200 | 40 files × avg 5 sections; sequential scan <5ms |

### Indexer Job sketch

1. Walk `docs/`, `CLAUDE.md`, memory files — skip `*.sops.yaml`
2. Split each `.md` on `##` headers
3. POST chunks to `http://litellm.ai.svc.cluster.local:4000/v1/embeddings`
   (`model: local-embed`)
4. Upsert into `repo_chunks(id, path, header, content, embedding,
   indexed_at, model_version)` in postgres18
5. Query time: embed question → top-20 → rerank → top-3

### Grep injection harness

Run 3–4 targeted greps at Job dispatch; inject results as mounted file:

| Query | Pattern | Tokens |
|---|---|---|
| App scaffold | `kind: HelmRelease\|chartRef\|OCIRepo` | ~2,000 |
| Storage | `storageClass\|storageClassName` | ~900 |
| Auth wiring | `authentik-forwardauth\|forwardAuth` | ~400 |
| Namespace topology | namespace kustomization | ~500 |
| App-as-template | 3-file read: ks + kustomization + helmrelease | ~1,600 |

Total per Job: **4,000–6,000 tokens**.
Always inject: relevant CLAUDE.md section (architecture + app namespace topology).

---

## K8s Job Injection Gotchas

1. **postgres18 creds:** Dedicated `repo_rag` user, `SELECT/INSERT/UPDATE` only.
   CNPG service: `postgres17-rw.databases.svc.cluster.local:5432`
2. **SOPS exclusion:** Filter all `*.sops.yaml` — embed as garbage otherwise
3. **LiteLLM network:** Works from `ai` namespace; verify NetworkPolicy if indexer
   Job runs in a different namespace
4. **Model version tracking:** Store `model_version` in chunks — re-index on model
   change (nomic→qwen3 broke existing index; dims changed 768→1024)
5. **Context serialization:** grep output + pgvector top-3 = plain strings;
   mount as ConfigMap or Job env var

---

## Risk Table

### Grep for YAML

| Risk | Likelihood | Mitigation |
|---|---|---|
| Convention drift causes grep miss | Medium | Keep patterns broad; read matched files fully |
| Multi-pattern query too noisy | Medium | Cap at 20 lines per query |
| Semantic bridging across prose impossible | High (by design) | Use prose vector index for runbook/ADR |

### Prose pgvector index

| Risk | Likelihood | Mitigation |
|---|---|---|
| Model migration invalidates index | Low (qwen3 recent) | `model_version` column; re-index on change |
| Stale runbook during incident | Low (daily sync OK) | Alert if index >48h stale |
| pgvector contention | Very low at 200 vectors | Non-issue; HNSW only needed past ~10K chunks |

---

## Complexity Scores

| Approach | Score | Notes |
|---|---|---|
| Grep injection harness | 1/5 | Shell/30-line Python; no new K8s resources |
| Prose pgvector index | 2/5 | One Python Job + CronJob; hard parts done |
| Full YAML vector index | 4/5 | Worse retrieval than grep; not recommended |

---

## P3 Scope (What to Build)

1. **Grep harness** — runs at Job dispatch; 3–4 pattern queries + CLAUDE.md injection;
   serializes to mounted ConfigMap for goose Job
2. **Prose indexer** — daily CronJob; indexes ~40 markdown files into `repo_chunks`;
   uses `local-embed` + `model_version` guard
3. **Query helper** — at dispatch: embed task → pgvector top-20 → rerank top-3 →
   append to grep context bundle

No new pods. No new databases. postgres18 wins on all axes.
