# Omniroute Phase 2 Switchover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repoint openviking (live), openclaw, and argus (both currently
inert) from LiteLLM to Omniroute, then fully remove LiteLLM from the
cluster.

**Architecture:** Each consumer gets a dedicated Omniroute inference API
key (`sk-...`, minted via `POST /api/keys`, mirrors the dedicated-virtual-
key-per-consumer pattern LiteLLM already used) and its `api_base`/`baseUrl`
repointed to `http://omniroute.ai.svc.cluster.local:20128/v1` with model
ids rewritten to the `<prefix>/<model>` form Omniroute requires
(`llamaswap/coder-large`, `llamaswapapu/embedding`, etc.). Once both
openviking (live-verified) and openclaw/argus (dry-run-verified) are
confirmed, LiteLLM's entire footprint — HelmRelease, operator, CNPG
database/role, DragonflyDB db4, namespace wiring — is removed in one
change.

**Tech Stack:** Flux (Kustomization/HelmRelease), SOPS+age, CloudNativePG
declarative `Database`/`managed.roles` (`ensure: absent` semantics),
Omniroute's `/api/keys` + `/v1/chat/completions`.

**Spec:** `docs/superpowers/specs/2026-09-08-omniroute-phase2-switchover-design.md`
(read this first — this plan implements it in full).

## Global Constraints

- Model addressing is `<prefix>/<model>` (e.g. `llamaswap/coder-large`,
  `llamaswapapu/embedding`) — never a bare alias, confirmed in Phase 1.
- Every consumer gets its OWN dedicated Omniroute inference key — never
  share one key across consumers (matches the existing LiteLLM
  virtual-key-per-consumer convention already in this repo).
- openviking's `rerank` block is **removed entirely**, not repointed —
  Omniroute's `/api/v1/rerank` SSRF filter excludes this cluster's Service
  CIDR (`10.43.0.0/16`). Do not attempt to route it through Omniroute.
- openclaw and argus are **not currently deployed** (`ks.yaml` entries
  commented out in `kubernetes/apps/ai/kustomization.yaml`) — their tasks
  are validated via `kustomize build`/`flux build --dry-run` only, never a
  live pod check. Do not un-comment their `ks.yaml` entries — that's
  explicitly out of scope.
- LiteLLM teardown happens **only after** all three consumer repoints are
  confirmed — never remove it while anything might still reference it.
- CNPG `Database`/managed-role resources must go through `ensure: absent`
  and a confirmed reconcile **before** the manifest is deleted — deleting
  the file/entry outright only stops CNPG from managing the resource, it
  does NOT drop the database/role (confirmed via `kubectl explain
  database.spec.ensure` and the existing comment in `cluster.yaml`).

---

### Task 1: Repoint openviking (live consumer)

**Files:**
- Modify: `kubernetes/apps/ai/openviking/app/helmrelease.yaml:99-189`
- Modify: `kubernetes/apps/ai/openviking/app/secret.sops.yaml`

**Interfaces:**
- Consumes: Omniroute `/api/keys` (mint 2 dedicated keys), `llamaswapapu`
  provider-node prefix (from Phase 1 Task 9 — already live).
- Produces: nothing consumed by later tasks in this plan (openviking is
  independent of openclaw/argus).

- [ ] **Step 1: Mint two dedicated Omniroute inference keys**

```bash
cd /workspace/home-ops
TOKEN=$(./scripts/omniroute-mcp-headers.sh | python3 -c "import json,sys; print(json.load(sys.stdin)['Authorization'].replace('Bearer ',''))")
curl -s -X POST http://omniroute.ai.svc.cluster.local:20128/api/keys \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"openviking-embedding"}' > /tmp/ov-embed-key.json
curl -s -X POST http://omniroute.ai.svc.cluster.local:20128/api/keys \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"openviking-vlm"}' > /tmp/ov-vlm-key.json
unset TOKEN
python3 -c "import json; print('embed key len:', len(json.load(open('/tmp/ov-embed-key.json'))['key']))"
python3 -c "import json; print('vlm key len:', len(json.load(open('/tmp/ov-vlm-key.json'))['key']))"
```
Expected: both print a length around 52 (matches the `sk-...` format
minted in Phase 1). Do not print the key values themselves — only lengths,
per this project's established secret-handling discipline (a transcript
exposure earlier in Phase 1 required a full credential rotation; treat
every decrypted/generated secret the same way going forward).

- [ ] **Step 2: Edit `helmrelease.yaml`**

Replace lines 99-189 (the full comment block plus `embedding:`, `vlm:`,
and `rerank:` sections) with:

```yaml
      # Embedding/VLM provider: routed through Omniroute (ai/omniroute),
      # not straight at llama-swap-apu -- Omniroute sits in front of both
      # llama-swap instances for every consumer as of the 2026-09-08 Phase 2
      # switchover (see docs/superpowers/specs/2026-09-08-omniroute-phase2-switchover-design.md).
      # api_base/model use Omniroute's <prefix>/<model> addressing
      # (llamaswapapu/*), not llama-swap's own aliases directly, and not
      # LiteLLM's bare-alias form (litellm removed entirely this same change).
      # provider: "openai" -- NOT "ollama". Omniroute (like llama-swap) is
      # an OpenAI-compatible proxy, not a real Ollama server; OpenViking's
      # "ollama" provider triggers a readiness probe against Ollama's
      # *native* /api/tags endpoint (openviking_cli/utils/ollama.py), which
      # Omniroute doesn't implement, permanently failing /ready with
      # "ollama: unreachable" even once embedding calls succeed. The
      # "openai" provider talks OpenAI-compatible /v1 only (what Omniroute
      # actually serves).
      # api_key: Omniroute requires an inference key on every request (unlike
      # llama-swap, which has no auth) -- ${OPENVIKING_EMBEDDING_API_KEY}
      # and ${OPENVIKING_VLM_API_KEY} hold dedicated Omniroute inference
      # keys (see secret.sops.yaml), not a llama-swap placeholder.
      # dense.model is Omniroute's llamaswapapu/embedding alias (mirrors
      # llama-swap-apu's real qwen3-embed model) -- required for the
      # embedding readiness check, which depends on a live embedding call
      # succeeding.
      # vlm.model is Omniroute's llamaswapapu/vlm alias -- llama-swap-apu's
      # real Qwen2-VL-2B-Instruct model.
      embedding:
        # allow_metadata_override: OpenViking stamps the embedding
        # provider/model identity into stored vector collection metadata
        # and refuses to boot on a mismatch (EmbeddingRebuildRequiredError)
        # -- tripped here because the route changed (litellm -> omniroute),
        # even though it's the same underlying qwen3-embed weights at the
        # same 1024 dimension. Safe to override since the dimension is
        # unchanged; only set this when you've verified that.
        allow_metadata_override: true
        dense:
          api_base: "http://omniroute.ai.svc.cluster.local:20128/v1"
          api_key: "${OPENVIKING_EMBEDDING_API_KEY}"
          provider: "openai"
          dimension: 1024
          model: "llamaswapapu/embedding"
          input: "text"
        max_concurrent: 10
      # timeout/max_retries/max_concurrent tuned 2026-08-19 after repeated
      # openai.APITimeoutError failures during Phase 2 long_term memory
      # extraction (bee-jms-03/qwen2-vl-2b). Root cause confirmed via the
      # pinned v0.4.15 image's actual source (openviking_cli/utils/config's
      # VLMConfig + session.py): the chart default `timeout` is 600s per
      # HTTP attempt, and session.py wraps every vlm call in its OWN retry
      # loop (hardcoded _MEMORY_EXTRACTION_MAX_RETRIES=3 -> 4 attempts) on
      # top of the vlm-client layer's own max_retries (2 -> 3 attempts) --
      # worst case was 4*3=12 raw attempts * 600s = up to 2 hours with no
      # real ceiling. timeout: 90 + max_retries: 1 (2 attempts at this
      # layer) bounds the compounded worst case to 4*2*90s = 720s (~12
      # min), matching the operator's 10-15 min ceiling for "slow is fine,
      # hung is not". max_concurrent dropped 100 -> 20: 100 let requests
      # pile up against one small model process on a 5-model, VRAM-tight
      # node (llama-swap-apu, 1.88 GiB free), stretching real per-request
      # latency and making the retries above pile onto an already-congested
      # backend instead of a merely slow one. Revert toward the prior
      # values (600/2/100) if legitimate slow-but-healthy VLM calls start
      # getting killed early -- watch for a rise in ERROR-level "Phase 2
      # step long_term failed" logs with APITimeoutError specifically at
      # ~90s elapsed (vs. genuine backend unavailability, which fails fast).
      vlm:
        api_base: "http://omniroute.ai.svc.cluster.local:20128/v1"
        api_key: "${OPENVIKING_VLM_API_KEY}"
        provider: "openai"
        model: "llamaswapapu/vlm"
        temperature: 0.0
        timeout: 90
        max_retries: 1
        thinking: false
        max_concurrent: 20
      # Rerank: dropped 2026-09-08 (Phase 2 switchover) -- Omniroute's
      # /api/v1/rerank endpoint has a hardcoded SSRF filter that only
      # accepts local provider-node backends on localhost/127.0.0.1/
      # 172.16.0.0-172.31.255.255; this cluster's Service CIDR
      # (10.43.0.0/16) never matches, so llama-swap-apu's rerank model is
      # silently filtered out of rerank routing (chat completions are a
      # separate code path, unaffected). Not part of the /ready check, so
      # omitting this block doesn't break the app -- retrieval degrades to
      # pure vector relevance (no rerank pass). Backlog item to revisit if
      # Omniroute upstream relaxes this filter. See
      # docs/superpowers/specs/2026-09-08-omniroute-phase2-switchover-design.md.
```

Note: everything from `retrieval:` onward (previously starting at the old
line 190) is unchanged — only the `embedding`/`vlm`/`rerank` block above it
is replaced.

- [ ] **Step 3: Rotate the secret**

Use the `sops-edit-then-encrypt` skill (or the manual decrypt/edit/encrypt
pattern already established this session — non-`-i` redirect form, never
`sops -e -i` or `sops -d -i`, which risk truncating the file if the
operation is denied mid-write) on
`kubernetes/apps/ai/openviking/app/secret.sops.yaml`:
- `OPENVIKING_EMBEDDING_API_KEY` → the key minted in Step 1 (embed key)
- `OPENVIKING_VLM_API_KEY` → the key minted in Step 1 (vlm key)
- `OPENVIKING_RERANK_API_KEY` → **delete this key entirely** (no longer
  referenced anywhere after Step 2)
- `OPENVIKING_ROOT_API_KEY` → unchanged, not part of this task

Verify: `task sops:verify` shows the file with ✅.

- [ ] **Step 4: Validate and deploy**

```bash
kustomize build kubernetes/apps/ai/openviking/app | kubectl apply --dry-run=client -f -
git add kubernetes/apps/ai/openviking/app/helmrelease.yaml kubernetes/apps/ai/openviking/app/secret.sops.yaml
git commit -m "feat(ai): repoint openviking embedding/vlm to Omniroute, drop rerank"
git pull --rebase origin main
git push
task flux:reconcile-ks name=openviking ns=ai
```
(If `task` isn't found: `ln -sf /home/claude/.local/share/mise/shims/task /home/claude/.local/bin/task` first — known environment quirk that doesn't survive session resets.)

- [ ] **Step 5: Watch rollout and verify live**

```bash
kubectl rollout status deployment/openviking -n ai --timeout=120s
kubectl get pods -n ai -l app.kubernetes.io/name=openviking
```
Expected: pod healthy, no `EmbeddingRebuildRequiredError` or `ollama:
unreachable` errors in logs (`kubectl logs -n ai deploy/openviking --tail=50`).
The embedding readiness check depends on a live embedding call succeeding
against Omniroute — a healthy/ready pod IS the end-to-end proof this
works, no separate curl test needed.

---

### Task 2: Repoint openclaw (inert, dry-run validated)

**Files:**
- Modify: `kubernetes/apps/ai/openclaw/app/configmap.yaml:154-220`
- Modify: `kubernetes/apps/ai/openclaw/app/helmrelease.yaml:203-209`
- Modify: `kubernetes/apps/ai/openclaw/app/secret.sops.yaml`

**Interfaces:**
- Consumes: Omniroute `/api/keys` (mint 1 dedicated key), `llamaswap`
  provider-node prefix.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Mint a dedicated Omniroute inference key**

```bash
cd /workspace/home-ops
TOKEN=$(./scripts/omniroute-mcp-headers.sh | python3 -c "import json,sys; print(json.load(sys.stdin)['Authorization'].replace('Bearer ',''))")
curl -s -X POST http://omniroute.ai.svc.cluster.local:20128/api/keys \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"openclaw"}' > /tmp/openclaw-key.json
unset TOKEN
python3 -c "import json; print('key len:', len(json.load(open('/tmp/openclaw-key.json'))['key']))"
```
Expected: length ~52. Don't print the value.

- [ ] **Step 2: Edit `configmap.yaml`**

Replace lines 154-159 (the comment block immediately before `litellm: {`)
with:

```javascript
          // Omniroute gateway in front of both llama-swap instances --
          // cluster-internal, dedicated inference key (name "openclaw",
          // minted via POST /api/keys), stored in openclaw-secret as
          // OMNIROUTE_API_KEY. See docs/superpowers/specs/
          // 2026-09-08-omniroute-phase2-switchover-design.md. Switched
          // from LiteLLM 2026-09-08 (Phase 2 switchover).
          omniroute: {
            baseUrl: "http://omniroute.ai.svc.cluster.local:20128/v1",
            apiKey: "$${OMNIROUTE_API_KEY}",
            api: "openai-completions",
            timeoutSeconds: 180,
```

Then within the `models:` array (was lines 175-189), change the two model
`id` values:
- `id: "coder-large"` → `id: "llamaswap/coder-large"`
- `id: "frontier-chat"` → `id: "llamaswap/frontier-chat"`

Leave every other field (`name`, `reasoning`, `contextWindow`, `maxTokens`)
and every comment about `gpt-oss-20b`/`qwen3.5-4b` exclusions unchanged —
those explain model-selection behavior independent of which gateway is in
front of llama-swap, still accurate.

Also, at line 80, change:
```javascript
            primary: "litellm/coder-large",
```
to:
```javascript
            primary: "omniroute/llamaswap/coder-large",
```
This field uses openclaw's OWN `<providerKey>/<modelId>` selector syntax —
a different layer from Omniroute's `<prefix>/<model>` addressing. The
`providerKey` is the key in `models.providers` (renamed `litellm` →
`omniroute` above); the `modelId` is one of the `models[].id` entries in
that same block (renamed `"coder-large"` → `"llamaswap/coder-large"`
above). The two rename together into three path segments — this is
correct, not a typo: `omniroute` (provider selector) / `llamaswap`
(Omniroute's prefix) / `coder-large` (the model). Verified by reading how
`models[].id` flows into the actual API request's `model` field
unmodified.

Two other `litellm` mentions in this file (lines 26 and 70) are pure
historical-narrative comments, not functional selectors — update the words
"litellm"/"litellm+omniroute" in their prose to describe Omniroute instead,
but there's no selector logic to get right there, just wording.

- [ ] **Step 3: Edit `helmrelease.yaml`**

Replace lines 203-209 with:

```yaml
              # Omniroute inference key auth for the "omniroute" provider in
              # openclaw.json (models.providers.omniroute.apiKey uses
              # $${OMNIROUTE_API_KEY} substitution). Dedicated key (name
              # "openclaw", minted via POST /api/keys) stored directly in
              # openclaw-secret as OMNIROUTE_API_KEY and picked up below via
              # envFrom -- no explicit env entry needed.
```

- [ ] **Step 4: Rotate the secret**

Using the same sops skill/pattern as Task 1 Step 3, on
`kubernetes/apps/ai/openclaw/app/secret.sops.yaml`: rename `LITELLM_API_KEY`
key to `OMNIROUTE_API_KEY`, value = the key minted in Step 1. All other
keys (`OPENCLAW_GATEWAY_TOKEN`, `OPENCLAW_HOOKS_TOKEN`, `GITHUB_TOKEN`,
`DISCORD_BOT_TOKEN`, `OPENVIKING_API_KEY`) unchanged. Verify: `task
sops:verify` shows ✅.

- [ ] **Step 5: Validate (dry-run only — openclaw is not deployed)**

```bash
kustomize build kubernetes/apps/ai/openclaw/app | kubectl apply --dry-run=client -f -
```
Expected: renders and validates cleanly with no errors. This is the full
verification for this task — there is no live pod to check against
(openclaw's `ks.yaml` stays commented out in
`kubernetes/apps/ai/kustomization.yaml`, per this plan's Global
Constraints).

- [ ] **Step 6: Commit**

```bash
git add kubernetes/apps/ai/openclaw/app/configmap.yaml kubernetes/apps/ai/openclaw/app/helmrelease.yaml kubernetes/apps/ai/openclaw/app/secret.sops.yaml
git commit -m "feat(ai): repoint openclaw (inert) config to Omniroute"
git pull --rebase origin main
git push
```

---

### Task 3: Repoint argus/holmesgpt (inert, dry-run validated)

**Files:**
- Modify: `kubernetes/apps/ai/argus/app/helmrelease.yaml:112-136`
- Modify: `kubernetes/apps/ai/argus/app/secret-holmesgpt.sops.yaml`

**Interfaces:**
- Consumes: Omniroute `/api/keys` (mint 1 dedicated key), `llamaswap`
  provider-node prefix.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Mint a dedicated Omniroute inference key**

```bash
cd /workspace/home-ops
TOKEN=$(./scripts/omniroute-mcp-headers.sh | python3 -c "import json,sys; print(json.load(sys.stdin)['Authorization'].replace('Bearer ',''))")
curl -s -X POST http://omniroute.ai.svc.cluster.local:20128/api/keys \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"argus-holmes"}' > /tmp/argus-key.json
unset TOKEN
python3 -c "import json; print('key len:', len(json.load(open('/tmp/argus-key.json'))['key']))"
```
Expected: length ~52.

- [ ] **Step 2: Edit `helmrelease.yaml`**

Replace lines 112-136 (the `modelList:` block, both `auto:` and `litellm:`
entries) with:

```yaml
      modelList:
        # modelList is a map, so Helm deep-merges rather than replaces --
        # and setting a key to `null` here does NOT delete it from the
        # merged map (confirmed via local `helm template`: it renders as a
        # literal `auto: null` line, which Holmes still chokes on trying to
        # parse a model entry). Instead, overwrite every field the chart's
        # own default "auto" entry sets (api_base/api_key/model) with the
        # same working Omniroute values below, so the merged "auto" key is
        # harmless (points at the same backend) instead of referencing
        # OPENAI_API_BASE/OPENAI_API_KEY, which don't exist in this cluster.
        # See the comment above config.model for the full crash story.
        auto:
          model: llamaswap/coder-large
          api_base: http://omniroute.ai.svc.cluster.local:20128/v1
          api_key: "{{ env.OMNIROUTE_API_KEY }}"
        litellm:
          # Omniroute's own <prefix>/<model> addressing replaces LiteLLM
          # SDK's litellm_proxy/ chaining prefix directly -- that prefix
          # was specifically a LiteLLM-calling-LiteLLM convention, not
          # something Omniroute needs or supports. Confirmed live
          # 2026-09-08 (Phase 1 Task 9): llamaswap/coder-large returns 200
          # with real tool_calls[] against Omniroute's /v1/chat/completions.
          # Map key stays "litellm" (matches config.model below) -- only
          # the values changed, not the key name, to keep this diff
          # mechanical.
          model: llamaswap/coder-large
          api_base: http://omniroute.ai.svc.cluster.local:20128/v1
          api_key: "{{ env.OMNIROUTE_API_KEY }}"
```

- [ ] **Step 3: Rotate the secret**

On `kubernetes/apps/ai/argus/app/secret-holmesgpt.sops.yaml`: rename
`LITELLM_API_KEY` → `OMNIROUTE_API_KEY`, value = the key minted in Step 1.
`GRAFANA_API_KEY` and `POSTGRES_CONNECTION_URL` unchanged. Verify: `task
sops:verify` shows ✅.

- [ ] **Step 4: Validate (dry-run only — argus is not deployed)**

```bash
kustomize build kubernetes/apps/ai/argus/app | kubectl apply --dry-run=client -f -
```
Expected: clean render, no errors.

- [ ] **Step 5: Commit**

```bash
git add kubernetes/apps/ai/argus/app/helmrelease.yaml kubernetes/apps/ai/argus/app/secret-holmesgpt.sops.yaml
git commit -m "feat(ai): repoint argus/holmesgpt (inert) config to Omniroute"
git pull --rebase origin main
git push
```

---

### Task 4: LiteLLM teardown, part 1 — actually drop the database and role

**Files:**
- Modify: `kubernetes/apps/databases/cloudnative-pg/cluster/litellm-database.yaml`
- Modify: `kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml:78-83`

**Interfaces:**
- Consumes: Tasks 1-3 must be complete and verified first (Global
  Constraint — never remove LiteLLM while anything might reference it).
- Produces: an actually-dropped `litellm` Postgres database/role, ready for
  Task 5 to remove the now-inert manifest files.

- [ ] **Step 1: Set `ensure: absent`**

In `kubernetes/apps/databases/cloudnative-pg/cluster/litellm-database.yaml`,
add `ensure: absent` to `spec:`:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Database
metadata:
  name: litellm
spec:
  name: litellm
  owner: litellm
  ensure: absent
  cluster:
    name: postgres17
```

In `kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml`, change
the `litellm` entry in `managed.roles` (lines 78-83) to add `ensure:
absent` (the field already exists on other entries in this schema, per
`kubectl explain database.spec.ensure` confirming the enum
`present|absent`):

```yaml
      - name: litellm
        ensure: absent
        login: true
        connectionLimit: 20
        passwordSecret:
          name: litellm-db-creds
```

- [ ] **Step 2: Commit, push, reconcile**

```bash
cd /workspace/home-ops
git add kubernetes/apps/databases/cloudnative-pg/cluster/litellm-database.yaml kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml
git commit -m "fix(databases): mark litellm database/role ensure:absent"
git pull --rebase origin main
git push
task flux:reconcile-ks name=cloudnative-pg-cluster ns=databases
```
(Check the actual Kustomization name first if this doesn't match —
`kubectl get kustomization -n databases` — the cluster.yaml/litellm-database.yaml
may be managed under a different Flux Kustomization name than assumed
here; use whatever `flux get ks -n databases` actually shows owns these
files.)

- [ ] **Step 3: Confirm the database and role are actually gone**

```bash
kubectl get database -n databases litellm -o jsonpath='{.status.applied}'
```
Expected: eventually `false` or the resource's status shows the drop
completed (check `kubectl describe database -n databases litellm` for the
exact status condition this CNPG version reports). Then confirm directly
against Postgres:
```bash
PGPASS=$(kubectl get secret -n databases postgres17-superuser -o jsonpath='{.data.password}' | base64 -d)
kubectl run -n databases pg-check --rm -i --restart=Never --image=postgres:17-alpine -- \
  psql "postgresql://postgres:$PGPASS@postgres17-rw.databases.svc.cluster.local:5432/postgres" \
  -c "\l" -c "\du"
```
Expected: `litellm` does NOT appear in either the database list (`\l`) or
role list (`\du`). Do not proceed to Task 5 until this is confirmed — the
whole point of the `ensure: absent` step is to verify the actual drop
before deleting the manifest that tracks it.

---

### Task 5: LiteLLM teardown, part 2 — remove all manifests and free db4

**Files:**
- Delete: `kubernetes/apps/ai/litellm/` (entire directory)
- Delete: `kubernetes/apps/ai/litellm-operator/` (entire directory)
- Delete: `kubernetes/apps/databases/cloudnative-pg/cluster/litellm-database.yaml`
- Modify: `kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml:78-83`
  (remove the now-`ensure:absent` entry entirely — it served its purpose
  in Task 4, no reason to keep a dead entry around)
- Modify: `kubernetes/apps/databases/cloudnative-pg/cluster/kustomization.yaml`
  (remove the `litellm-database.yaml` resource reference, if it's not
  auto-globbed — check the file first)
- Modify: `kubernetes/apps/ai/kustomization.yaml`
- Modify: `docs/runbooks/dragonflydb-db-allocation.md`

**Interfaces:**
- Consumes: Task 4's confirmed drop.

- [ ] **Step 1: Delete the app directories**

```bash
cd /workspace/home-ops
git rm -r kubernetes/apps/ai/litellm/ kubernetes/apps/ai/litellm-operator/
git rm kubernetes/apps/databases/cloudnative-pg/cluster/litellm-database.yaml
```

- [ ] **Step 2: Remove the dead role entry from `cluster.yaml`**

Delete these lines (78-83, or wherever they've shifted to after Task 4's
edit) entirely:
```yaml
      - name: litellm
        ensure: absent
        login: true
        connectionLimit: 20
        passwordSecret:
          name: litellm-db-creds
```
Also trim the comment block above `managed:` (lines 62-67) that describes
the now-deleted `litellm-database.yaml` — delete the `# litellm: owner
role for...` through `...connectionLimit 20 matches...` lines, keeping the
rest of the surrounding comment intact.

- [ ] **Step 3: Check and update `cloudnative-pg/cluster/kustomization.yaml`**

```bash
cat kubernetes/apps/databases/cloudnative-pg/cluster/kustomization.yaml
```
If it lists `litellm-database.yaml` explicitly in `resources:`, remove that
line. If it uses a glob pattern that doesn't name files explicitly, no
change needed here — note which case applies in your task report.

- [ ] **Step 4: Update `kubernetes/apps/ai/kustomization.yaml`**

Remove these two lines from `resources:`:
```yaml
  - ./litellm/ks.yaml
  - ./litellm-operator/ks.yaml
```

Replace the top comment block (lines 3-19) with:
```yaml
# AI workloads namespace: fully self-hosted, no third-party providers,
# with one documented scoped exception: holyclaude (see CLAUDE.md).
# llama-swap serves local GGUFs directly (OpenAI-compatible API); Omniroute
# fronts both llama-swap instances as the AI-namespace gateway (Phase 2
# switchover, 2026-09-08 -- see
# docs/superpowers/specs/2026-09-08-omniroute-phase2-switchover-design.md).
# LiteLLM and litellm-operator were fully removed the same change (not kept
# as cold standby). n8n, opencode, agent-canvas, cognee, and kelos-system
# remain removed 2026-08-14 (opencode returns only inside holyclaude, a
# scoped exception -- see CLAUDE.md); memini (memory plugin -- its own
# extension threw a command-registration error on every openclaw boot) was
# removed 2026-08-16; see CLAUDE.md and archive/{cognee,memini}/. The
# standalone holmesgpt app was retired 2026-08-19 -- argus's bundled Holmes
# subchart (argus-holmes) is now the only HolmesGPT instance, fronted by
# argus's Discord-bridging forwarder for triage summaries. openclaw and
# argus remain commented out below (not currently deployed) but their
# config already points at Omniroute for whenever either is re-enabled.
```

- [ ] **Step 5: Update `docs/runbooks/dragonflydb-db-allocation.md`**

Change the db4 row from:
```markdown
| 4 | litellm | `ai/litellm` | Router coordination + response cache. Reintroduced 2026-08-17 as a cluster-internal-only mirror in front of llama-swap/llama-swap-apu (no cloud provider routing, unlike the instance removed 2026-08-14). Redis URL: `redis://...:6379/4`. | `kubernetes/apps/ai/litellm/app/litellmproxy.yaml` |
```
to:
```markdown
| 4 | _free_ | — | Formerly LiteLLM router coordination + cache -- freed 2026-09-08 (Phase 2 switchover, LiteLLM fully removed in favor of Omniroute -- see `docs/superpowers/specs/2026-09-08-omniroute-phase2-switchover-design.md`). | — |
```

- [ ] **Step 6: Validate**

```bash
kustomize build kubernetes/apps/ai | grep -i litellm
```
Expected: no output (zero matches) — confirms nothing in the rendered `ai`
namespace kustomization references litellm anymore.
```bash
kustomize build kubernetes/apps/databases/cloudnative-pg/cluster | kubectl apply --dry-run=client -f -
```
Expected: clean render, no errors.

- [ ] **Step 7: Commit**

```bash
git add -A kubernetes/apps/databases/cloudnative-pg/cluster/ kubernetes/apps/ai/kustomization.yaml docs/runbooks/dragonflydb-db-allocation.md
git status
git commit -m "feat(ai): remove LiteLLM entirely (Phase 2 switchover complete)"
git pull --rebase origin main
git push
task flux:reconcile-ks name=cluster-apps
```

- [ ] **Step 8: Confirm the live cluster no longer has litellm resources**

```bash
kubectl get all -n ai -l app.kubernetes.io/name=litellm
kubectl get all -n ai -l app.kubernetes.io/name=litellm-operator
```
Expected: `No resources found in ai namespace.` for both.

---

### Task 6: Doc sweep, TaskMaster, and memory updates

**Files:**
- Modify: `CLAUDE.md` (top-level, if it describes LiteLLM as the gateway)
- Modify: `kubernetes/apps/ai/CLAUDE.md` (if it exists and references LiteLLM)

**Interfaces:** none — pure documentation/bookkeeping, no code interfaces.

- [ ] **Step 1: Find and update stale LiteLLM references**

```bash
cd /workspace/home-ops
grep -rn "litellm" CLAUDE.md kubernetes/apps/ai/CLAUDE.md 2>/dev/null
```
For each match found, read the surrounding context and update it to
describe Omniroute as the AI-namespace gateway instead — there's no fixed
list of lines to give here since it depends on what the grep actually
finds; read each hit and judge whether it needs a full-sentence rewrite or
just needs "litellm" swapped for "omniroute" (a heading like "### LiteLLM"
needs more than a word-swap; a passing mention might not).

- [ ] **Step 2: Commit doc changes (if any)**

```bash
git add CLAUDE.md kubernetes/apps/ai/CLAUDE.md
git commit -m "docs(ai): update gateway references from LiteLLM to Omniroute"
git pull --rebase origin main
git push
```
Skip this step (no commit) if Step 1 found nothing to change.

- [ ] **Step 3: Update TaskMaster**

```bash
task-master set-status --id=12 --status=done
task-master set-status --id=13 --status=done
task-master set-status --id=14 --status=done
task-master set-status --id=15 --status=done
task-master set-status --id=16 --status=done
git add .taskmaster/tasks/tasks.json
git commit -m "chore(ai): mark Phase 2 TaskMaster tasks 12-16 done"
git pull --rebase origin main
git push
```

- [ ] **Step 4: Update the `ai-omniroute-revival-plan` memory**

Edit `/home/claude/.claude/projects/-workspace-home-ops/memory/ai_omniroute_revival_plan.md`:
mark "Phase 2 (consumer switchover + LiteLLM teardown): DONE as of
2026-09-08" (mirror the exact style used for the Phase 1 status line),
note the rerank-dropped decision and the CNPG `ensure: absent` two-step
pattern discovered in Task 4/5 as durable, non-obvious facts worth keeping
for future database-teardown work in this repo (not specific to
Omniroute — this is a general CNPG pattern this repo now has one real
example of).

---

## Self-Review Notes

- **Spec coverage:** every section of the Phase 2 design spec maps to a
  task above — consumer repoint (Tasks 1-3), teardown footprint (Tasks
  4-5, split specifically because of the `ensure: absent`-then-delete
  ordering requirement the spec's "Ordering / safety" section implies but
  doesn't spell out as two steps — made explicit here since skipping the
  wait-and-confirm step would silently orphan the database), doc sweep
  (Task 6).
- **Ordering enforced structurally:** Task 4 can't start before Tasks 1-3
  commit (no file overlap, but the plan's Global Constraints make the
  dependency explicit for whoever executes this); Task 5 depends on Task
  4's live confirmation step specifically, not just its commit.
- **Known follow-up, not a gap:** Task 4 Step 2's exact Flux Kustomization
  name and Task 5 Step 3's exact resource-list-vs-glob question are called
  out as "verify against the real repo state" rather than assumed — this
  matches the project's established discipline (Phase 1 found three real
  bugs specifically from trusting documentation/assumptions over live
  verification; this plan deliberately doesn't repeat that pattern for the
  two places genuine uncertainty remains).
