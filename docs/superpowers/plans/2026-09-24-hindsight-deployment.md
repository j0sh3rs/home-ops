# Hindsight Deployment (Parallel Run with OpenViking) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Hindsight as a second, parallel memory layer, with its Claude Code plugin on this machine and HolyClaude, and `gpt-oss-20b` as the always-on local model for retain and reflect.

**Architecture:** The upstream Hindsight Helm chart (API with in-process worker, plus the control plane) runs in the `ai` namespace against a new `hindsight` database on the shared CNPG cluster. pgvector comes from a CNPG `Database` resource. Per-client bearer keys come from the upstream `StaticKeysTenantExtension`, mounted from a ConfigMap. Retain and reflect call Omniroute with a key scoped to `llamaswap/reasoner` only. llama-swap's dGPU becomes a single always-on `gpt-oss-20b` with 4 slots. Memory Defense is on for every bank through the server's default bank template.

**Tech Stack:** Flux (OCIRepository + HelmRelease), CloudNative-PG (`Cluster.managed.roles`, `Database`), SOPS/age, Gateway API HTTPRoutes on Traefik, llama-swap, Omniroute management API, `@vectorize-io/hindsight-coding-agents@0.7.0`.

**Spec:** `docs/superpowers/specs/2026-09-24-hindsight-deployment-design.md`

## Global Constraints

- Chart `oci://ghcr.io/vectorize-io/charts/hindsight` tag `0.10.1`; image tag `0.10.1` (chart `version` value).
- Plugin `@vectorize-io/hindsight-coding-agents@0.7.0`, `autoUpdate: false`, `retainExtractionMode: "concise"`, `autoInject` left at its default `"reflect"`.
- Retain/reflect LLM: `provider=openai`, base URL `http://omniroute.ai.svc.cluster.local:20128/v1`, model `llamaswap/reasoner`.
- llama-swap: `gpt-oss-20b` only chat model, `--parallel 4 --ctx-size 131072`, always-on.
- Hindsight LLM caps: `HINDSIGHT_API_LLM_MAX_CONCURRENT=4`; `RETAIN`, `CONSOLIDATION`, `MENTAL_MODEL_REFRESH` per-op caps `=1`. `HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS=16000`.
- Routes on `traefik-internal-gateway` only, `external-dns.alpha.kubernetes.io/target: 192.168.35.17`: `hindsight.68cc.io` (API, no forwardAuth) and `hindsight-ui.68cc.io` (control plane, `authentik-forwardauth`).
- **Never print a secret value** (keys, passwords) to the terminal or transcript. Generate with `openssl rand -hex 32` into shell variables and write straight into SOPS files. Print only lengths or `OK`.
- Every `*.sops.yaml` must pass `task sops:verify` before commit.
- Every workload consuming a Secret/ConfigMap carries `reloader.stakater.com/auto: "true"` on the pod template (repo `CLAUDE.md`).
- **Deploying** a task means: commit on `feat/701-hindsight`, then `git push origin feat/701-hindsight:main` (fast-forward) and `task reconcile`. Flux reconciles from `main` only. Get the operator's go-ahead before the **first** push of this plan.
- Do not touch OpenViking, its shim, or its Omniroute keys (out of scope, parallel run).
- API calls to Hindsight use the path prefix `/v1/default/` (the tenant extension maps the key to its schema; the URL segment stays `default`).

## Review Focus

1. **Tenant key formatting:** a key with a trailing newline, a comma, or non-ASCII bytes 401s forever with no server-side error (upstream README). Task 4 generates hex keys and asserts every configured key returns 200.
2. **A long session's retain overflowing a 32k slot:** llama-server rejects the request, and the operation fails permanently after 3 retries. Task 6 includes the largest local transcript and greps llama-swap logs for context-overflow errors.
3. **Hindsight unavailable while Claude Code is in use:** a user expects prompts to proceed within the hook timeout, not hang. Task 9 scales `hindsight-api` to 0 and times a prompt.
4. **API restart with queued retain operations:** a user expects queued memories to survive a pod restart. Task 9 restarts the API mid-queue and confirms the queue drains.
5. **Omniroute's default-on compression** silently rewriting retain prompts (the same failure found on Home Assistant's key). Task 3 sets `compressionEnabled: false` and confirms it with a GET.

---

### Task 1: Make `gpt-oss-20b` the dGPU's sole always-on chat model

**Files:**
- Modify: `kubernetes/apps/ai/llama-swap/app/configmap.yaml`
- Modify: `kubernetes/apps/ai/CLAUDE.md` (llama-swap entry, and every place that says `coder-large`/`agentic-coder` resolves to Qwen3-Coder)

**Interfaces:**
- Produces: llama-swap model `gpt-oss-20b` with aliases `reasoner`, `reasoning`, `coder`, `code-large`, `coder-large`, `frontier`, `frontier-chat`; 4 slots of 32768 tokens; always resident.

- [ ] **Step 1: Record the baseline**

The llama-swap image has no `curl`/`wget`, so HTTP checks go through HolyClaude's pod to the llama-swap Service. VRAM is read from sysfs inside llama-swap.

```bash
BASELINE="$(kubectl exec -n ai deploy/llama-swap -c app -- sh -c 'echo vram_used=$(cat /sys/class/drm/card0/device/mem_info_vram_used) vram_total=$(cat /sys/class/drm/card0/device/mem_info_vram_total)') running=$(kubectl exec -n ai deploy/holyclaude -c app -- curl -s http://llama-swap.ai.svc.cluster.local:8080/running | jq -c '[.running[]?.model]')"
echo "$BASELINE"
```

- [ ] **Step 2: Write the failing checks**

Save as `/tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/check-llamaswap.sh` (scratchpad, not the repo):

```bash
#!/bin/sh
# Passes only when gpt-oss-20b is resident with 4x32k slots, >=2 GiB VRAM free, and the moved aliases resolve.
set -e
L='kubectl exec -n ai deploy/llama-swap -c app --'
C='kubectl exec -n ai deploy/holyclaude -c app -- curl -s -m 180'
LS=http://llama-swap.ai.svc.cluster.local:8080
used=$($L cat /sys/class/drm/card0/device/mem_info_vram_used)
total=$($L cat /sys/class/drm/card0/device/mem_info_vram_total)
free_mib=$(( (total - used) / 1048576 ))
echo "free_mib=$free_mib"; [ "$free_mib" -ge 2048 ]
$C $LS/upstream/gpt-oss-20b/slots | jq -e 'length == 4 and all(.[]; .n_ctx == 32768)' >/dev/null; echo "slots OK"
for m in coder-large frontier reasoner; do
  $C $LS/v1/chat/completions -H 'Content-Type: application/json' \
    -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with OK\"}],\"max_tokens\":64}" \
    | jq -e '.choices[0].message' >/dev/null
  echo "alias $m OK"
done
echo PASS
```

- [ ] **Step 3: Run it to confirm it fails today**

Run: `sh .../scratchpad/check-llamaswap.sh`
Expected: FAIL at the slots check (the current single slot is 65536) or the free-VRAM check.

- [ ] **Step 4: Edit `configmap.yaml`**

1. Replace the header comment's "Chat models hot-swap through the 'chat' group (exclusive)." sentence with:
   ```
   # Since 2026-09-24 (issue #701, Hindsight) gpt-oss-20b is the ONLY chat
   # model on this card, always resident with 4x32k slots, so Hindsight's
   # retain/reflect never wait on a model swap. agentic-coder and
   # qwen3.5-35b-a3b are commented out below (each needs ~13-14 GiB, and
   # neither fits beside gpt-oss-20b's ~11.5 GiB); their aliases moved onto
   # gpt-oss-20b so no consumer config changed.
   ```
2. Comment out the whole `"agentic-coder":` block and the whole `"qwen3.5-35b-a3b":` block (prefix each line with `# `, keeping their existing comments). Add above each: `# DISABLED 2026-09-24 (#701): cannot co-reside with always-on gpt-oss-20b. Aliases moved to gpt-oss-20b.`
3. Replace the `"gpt-oss-20b":` block with:
   ```yaml
      # Sole chat model since 2026-09-24 (#701). --parallel 4 splits
      # --ctx-size 131072 into 4 slots of 32768: Hindsight caps retain,
      # consolidation and mental-model refresh at 1 LLM call each, so one
      # slot is always free for reflect (the plugin's first-prompt
      # synthesis). Same total KV as the old single 65536 slot plus one
      # more 65536 -- re-measure VRAM (mem_info_vram_used) after any
      # change here; >=2 GiB free with jina-reranker-v2 loaded is the bar.
      "gpt-oss-20b":
        cmd: |
          ${llama-vulkan}
          --model /models/gpt-oss-20b-Q4_K_M.gguf
          --ctx-size 131072
          --parallel 4
          -ub 2048 -b 16384
          --temp 1.0 --top-p 1.0 --top-k 0
        aliases:
          - "reasoner"
          - "reasoning"
          - "coder"
          - "code-large"
          - "coder-large"
          - "frontier"
          - "frontier-chat"
        ttl: 0
   ```
4. In `groups:`, delete the `"chat":` group and add `- "gpt-oss-20b"` to `"always-on".members` (before `"jina-reranker-v2"`). Update the always-on group comment to say gpt-oss-20b is resident too.
5. Add at the top level of the llama-swap config (same indent as `groups:`):
   ```yaml
    hooks:
      on_startup:
        preload:
          - "gpt-oss-20b"
          - "jina-reranker-v2"
   ```

- [ ] **Step 5: Validate the render**

```bash
kustomize build kubernetes/apps/ai/llama-swap/app | yq 'select(.kind=="ConfigMap" and .metadata.name=="llama-swap-config") | .data["config.yaml"]' | yq '.groups, .hooks, .models["gpt-oss-20b"].aliases'
kustomize build kubernetes/apps/ai/llama-swap/app | kubectl apply --dry-run=server -f - >/dev/null && echo DRYRUN-OK
```
Expected: the always-on members list both models, the preload hook is present, 7 aliases, `DRYRUN-OK`.

- [ ] **Step 6: Update `kubernetes/apps/ai/CLAUDE.md`**

In the llama-swap bullet, replace the model list so it shows `gpt-oss-20b` as the only chat model (aliases as above, 4×32k, always-on, the #701 reason) with `agentic-coder` and `qwen3.5-35b-a3b` "disabled 2026-09-24, cannot co-reside". Everywhere the file says `coder-large` resolves to `agentic-coder` (the holyclaude `coding-deep` passage, the atuin-ai-server bullet, argus, openclaw), change it to say `coder-large` now resolves to `gpt-oss-20b` (32k slot).

- [ ] **Step 7: Commit and deploy**

```bash
git add kubernetes/apps/ai/llama-swap/app/configmap.yaml kubernetes/apps/ai/CLAUDE.md
git commit -m "feat(ai): pin gpt-oss-20b as sole always-on dGPU chat model (#701)" -m "Before: $BASELINE" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin feat/701-hindsight:main && task reconcile
kubectl rollout status -n ai deploy/llama-swap --timeout=10m
```

- [ ] **Step 8: Run the checks until they pass**

Wait for the preload (up to ~3 min), then run `sh .../scratchpad/check-llamaswap.sh`.
Expected: `PASS`.
- If `free_mib < 2048`: change `--ctx-size 131072` to `98304` (4×24k), redeploy, rerun, and record the change in the gpt-oss comment.
- If llama-swap logs reject the `hooks:` key (`kubectl logs -n ai deploy/llama-swap -c app | grep -i hook`): delete the `hooks:` block, redeploy, and rely on `ttl: 0` + always-on; the checks warm the model.

- [ ] **Step 9: Check atuin's path end to end**

```bash
kubectl exec -n ai deploy/holyclaude -c app -- sh -c 'curl -s -m 120 http://omniroute.ai.svc.cluster.local:20128/v1/chat/completions -H "Authorization: Bearer $OMNIROUTE_API_KEY" -H "Content-Type: application/json" -d "{\"model\":\"coding-fast\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with OK\"}],\"max_tokens\":64}"' | jq -r '.choices[0].message.content // .error'
```
Expected: a completion (not an error). `coding-fast` is `llamaswap/coder-large`, now served by `gpt-oss-20b`.

---

### Task 2: `hindsight` database with pgvector on CNPG

**Files:**
- Modify: `kubernetes/apps/databases/cloudnative-pg/cluster/cluster.yaml` (`spec.managed.roles`)
- Create: `kubernetes/apps/databases/cloudnative-pg/cluster/hindsight-role-secret.sops.yaml`
- Create: `kubernetes/apps/databases/cloudnative-pg/cluster/database-hindsight.yaml`
- Modify: `kubernetes/apps/databases/cloudnative-pg/cluster/kustomization.yaml`
- Create: `kubernetes/apps/ai/hindsight/app/secret.sops.yaml` (starts with `postgres-password` only)

**Interfaces:**
- Produces: role `hindsight` (login) owning database `hindsight` on cluster `postgres17`, extension `vector` installed. Secret `hindsight-secret` (ns `ai`, not yet deployed) with key `postgres-password`, identical to `hindsight-db-creds.password` (ns `databases`).

- [ ] **Step 1: Write the failing check**

```bash
kubectl exec -n databases postgres17-1 -c postgres -- psql -tAc "select extname from pg_extension" -d hindsight
```
Expected now: FAIL, `database "hindsight" does not exist`.

- [ ] **Step 2: Add the managed role** to `cluster.yaml` under `spec.managed.roles`, after `holmesgpt_ro`:

```yaml
      # Hindsight memory server (kubernetes/apps/ai/hindsight/, #701).
      # Owns the `hindsight` Database (database-hindsight.yaml), which is
      # what installs pgvector -- Hindsight's migrations require it but
      # never CREATE EXTENSION themselves. Password must match
      # `postgres-password` in kubernetes/apps/ai/hindsight/app/secret.sops.yaml.
      - name: hindsight
        ensure: present
        login: true
        passwordSecret:
          name: hindsight-db-creds
```

- [ ] **Step 3: Create both secrets with one generated password (never printed)**

```bash
PW=$(openssl rand -hex 24)
cat > kubernetes/apps/databases/cloudnative-pg/cluster/hindsight-role-secret.sops.yaml <<EOF
---
apiVersion: v1
kind: Secret
metadata:
  name: hindsight-db-creds
  labels:
    cnpg.io/reload: "true"
type: kubernetes.io/basic-auth
# Password MUST match postgres-password in
# kubernetes/apps/ai/hindsight/app/secret.sops.yaml. Rotate both together.
stringData:
  username: hindsight
  password: ${PW}
EOF
mkdir -p kubernetes/apps/ai/hindsight/app
cat > kubernetes/apps/ai/hindsight/app/secret.sops.yaml <<EOF
---
# All keys are injected into BOTH hindsight pods via the chart's
# existingSecret envFrom. postgres-password must match
# kubernetes/apps/databases/cloudnative-pg/cluster/hindsight-role-secret.sops.yaml.
apiVersion: v1
kind: Secret
metadata:
  name: hindsight-secret
stringData:
  postgres-password: ${PW}
EOF
unset PW
sops --encrypt --in-place kubernetes/apps/databases/cloudnative-pg/cluster/hindsight-role-secret.sops.yaml
sops --encrypt --in-place kubernetes/apps/ai/hindsight/app/secret.sops.yaml
task sops:verify
```
Expected: `task sops:verify` passes; `grep -c ENC\\[ ` on each file is ≥1.

- [ ] **Step 4: Create `database-hindsight.yaml`**

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/postgresql.cnpg.io/database_v1.json
# Hindsight's database (#701). extensions: vector is the reason this is a
# CNPG Database and not a postgres-init initContainer: Hindsight's
# migrations check for pgvector but never create it, and postgres-init
# can't create extensions. databaseReclaimPolicy: retain keeps the data if
# this manifest is ever removed.
apiVersion: postgresql.cnpg.io/v1
kind: Database
metadata:
  name: hindsight
spec:
  cluster:
    name: postgres17
  name: hindsight
  owner: hindsight
  ensure: present
  databaseReclaimPolicy: retain
  extensions:
    - name: vector
      ensure: present
```

Add `- ./hindsight-role-secret.sops.yaml` and `- ./database-hindsight.yaml` to the cluster `kustomization.yaml`.

- [ ] **Step 5: Validate**

```bash
kustomize build kubernetes/apps/databases/cloudnative-pg/cluster | yq 'select(.kind=="Database" or (.kind=="Cluster")) | .kind + " " + .metadata.name' 
kustomize build kubernetes/apps/databases/cloudnative-pg/cluster | yq 'select(.kind=="Database")' | kubectl apply --dry-run=server -n databases -f -
```
Expected: `Database hindsight` listed; the dry-run is accepted.

- [ ] **Step 6: Commit and deploy** (the ai secret is committed but not referenced yet)

```bash
git add kubernetes/apps/databases/cloudnative-pg/cluster/ kubernetes/apps/ai/hindsight/app/secret.sops.yaml
git commit -m "feat(databases): add hindsight role and pgvector database (#701)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin feat/701-hindsight:main && task reconcile
```

- [ ] **Step 7: Run the check until it passes**

```bash
kubectl get database -n databases hindsight -o jsonpath='{.status.applied}{" "}{.status.message}{"\n"}'
kubectl exec -n databases postgres17-1 -c postgres -- psql -tAc "select extname||' '||extversion from pg_extension where extname='vector'" -d hindsight
kubectl exec -n databases postgres17-1 -c postgres -- psql -tAc "select pg_get_userbyid(datdba) from pg_database where datname='hindsight'"
```
Expected: `true`, `vector 0.8.2`, `hindsight`.

---

### Task 3: Scoped Omniroute key `hindsight-retain`

**Files:**
- Modify: `kubernetes/apps/ai/hindsight/app/secret.sops.yaml` (add `HINDSIGHT_API_LLM_API_KEY`)

**Interfaces:**
- Consumes: Omniroute management API on `127.0.0.1:20128` inside `deploy/omniroute -c app`, token `$OMNIROUTE_MGMT_TOKEN` (container env).
- Produces: Omniroute key named `hindsight-retain`: `modelAccessMode: "restricted"`, `allowedModels: ["llamaswap/reasoner"]`, `compressionEnabled: false`. Its value is stored as `HINDSIGHT_API_LLM_API_KEY` in `hindsight-secret`.

- [ ] **Step 1: Mint the key, writing the raw response to a local file only**

```bash
OUT=/tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/hindsight-key.json
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const body=JSON.stringify({name:'hindsight-retain'});
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/keys',method:'POST',headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>process.stdout.write(d));});
req.end(body);" > "$OUT"
jq -r '"id=" + .id + " keylen=" + ((.key // "")|length|tostring)' "$OUT"
```
Expected: an id and `keylen` ≈ 52. Do not `cat` the file.

- [ ] **Step 2: Scope it** (POST only accepts `name`; scope is PATCH-only per `updateKeyPermissionsSchema`)

```bash
ID=$(jq -r .id "$OUT")
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const body=JSON.stringify({modelAccessMode:'restricted',allowedModels:['llamaswap/reasoner'],compressionEnabled:false});
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/keys/$ID',method:'PATCH',headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode));});
req.end(body);"
```
Expected: `200`.

- [ ] **Step 3: Verify with a GET** (a 200 on PATCH has silently dropped fields in this system before)

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');const tok=process.env.OMNIROUTE_MGMT_TOKEN;
http.get({host:'127.0.0.1',port:20128,path:'/api/keys',headers:{Authorization:'Bearer '+tok}},r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>{const j=JSON.parse(d);const k=(j.keys||j).find(k=>k.name==='hindsight-retain');console.log(JSON.stringify({modelAccessMode:k.modelAccessMode,allowedModels:k.allowedModels,compressionEnabled:k.compressionEnabled}));});});"
```
Expected: `{"modelAccessMode":"restricted","allowedModels":["llamaswap/reasoner"],"compressionEnabled":false}`.

- [ ] **Step 4: Test that the scope allows the right model and blocks the Claude lane**

```bash
KEY=$(jq -r .key "$OUT")
for m in llamaswap/reasoner cliproxyapi/claude-sonnet-5; do
  code=$(kubectl exec -n ai deploy/holyclaude -c app -- curl -s -o /dev/null -w '%{http_code}' -m 120 http://omniroute.ai.svc.cluster.local:20128/v1/chat/completions -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with OK\"}],\"max_tokens\":64}")
  echo "$m -> $code"
done
unset KEY
```
Expected: `llamaswap/reasoner -> 200`, and a 4xx for `cliproxyapi/claude-sonnet-5`. If `llamaswap/reasoner` is rejected as not allowed, PATCH `allowedModels` to `["llamaswap/gpt-oss-20b"]`, repeat Steps 3–4, and use that model id everywhere this plan says `llamaswap/reasoner`.

- [ ] **Step 5: Store the key in SOPS, then delete the local file**

```bash
sops set kubernetes/apps/ai/hindsight/app/secret.sops.yaml '["stringData"]["HINDSIGHT_API_LLM_API_KEY"]' "\"$(jq -r .key "$OUT")\""
rm -f "$OUT"
task sops:verify
```

- [ ] **Step 6: Commit**

```bash
git add kubernetes/apps/ai/hindsight/app/secret.sops.yaml
git commit -m "feat(ai): add scoped hindsight-retain Omniroute key (#701)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Hindsight release, tenant keys, and routes

**Files:**
- Create: `kubernetes/apps/ai/hindsight/ks.yaml`
- Create: `kubernetes/apps/ai/hindsight/app/kustomization.yaml`
- Create: `kubernetes/apps/ai/hindsight/app/ocirepository.yaml`
- Create: `kubernetes/apps/ai/hindsight/app/helmrelease.yaml`
- Create: `kubernetes/apps/ai/hindsight/app/configmap-extension.yaml` (generated)
- Create: `kubernetes/apps/ai/hindsight/app/httproute.yaml`
- Modify: `kubernetes/apps/ai/hindsight/app/secret.sops.yaml` (add tenant and control-plane keys)
- Modify: `kubernetes/apps/ai/kustomization.yaml` (add `./hindsight/ks.yaml`)

**Interfaces:**
- Consumes: `hindsight-secret` keys `postgres-password`, `HINDSIGHT_API_LLM_API_KEY` (Tasks 2–3); database `hindsight` (Task 2).
- Produces:
  - Services `hindsight-api:8888` and `hindsight-control-plane:3000` in `ai`; pod labels `app.kubernetes.io/name: hindsight` + `app.kubernetes.io/component: api|control-plane`.
  - `HINDSIGHT_API_TENANT_USERS` holding, in order: `josh:<laptop-claude>`, `josh:<holyclaude>`, `josh:<control-plane>`.
  - To read key N without printing it: `sops -d --extract '["stringData"]["HINDSIGHT_API_TENANT_USERS"]' kubernetes/apps/ai/hindsight/app/secret.sops.yaml | tr ',' '\n' | sed -n Np | cut -d: -f2`
  - Tenant schema `user_josh`.

- [ ] **Step 1: Write the failing checks** to `.../scratchpad/check-hindsight.sh`

```bash
#!/bin/sh
# Passes when the API is healthy, enforces auth, accepts every configured key, and the UI is behind Authentik.
set -e
F=kubernetes/apps/ai/hindsight/app/secret.sops.yaml
U=https://hindsight.68cc.io
test "$(curl -s -o /dev/null -w '%{http_code}' $U/health)" = 200; echo health OK
test "$(curl -s -o /dev/null -w '%{http_code}' $U/v1/default/banks)" = 401; echo no-token 401 OK
for n in 1 2 3; do
  K=$(sops -d --extract '["stringData"]["HINDSIGHT_API_TENANT_USERS"]' $F | tr ',' '\n' | sed -n ${n}p | cut -d: -f2)
  test "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $K" $U/v1/default/banks)" = 200; echo key$n 200 OK
done
kubectl exec -n databases postgres17-1 -c postgres -- psql -tAc "select 1 from pg_namespace where nspname='user_josh'" -d hindsight | grep -q 1; echo schema OK
code=$(curl -s -o /dev/null -w '%{http_code}' https://hindsight-ui.68cc.io/); case $code in 302|303|307) echo ui-forwardauth OK;; *) echo "ui $code"; exit 1;; esac
echo PASS
```

Run it: `sh .../scratchpad/check-hindsight.sh`. Expected: FAIL (the host doesn't resolve yet).

- [ ] **Step 2: Add the tenant and control-plane keys (hex: ASCII, no commas, no newline)**

```bash
L=$(openssl rand -hex 32); H=$(openssl rand -hex 32); C=$(openssl rand -hex 32)
sops set kubernetes/apps/ai/hindsight/app/secret.sops.yaml '["stringData"]["HINDSIGHT_API_TENANT_USERS"]' "\"josh:$L,josh:$H,josh:$C\""
sops set kubernetes/apps/ai/hindsight/app/secret.sops.yaml '["stringData"]["HINDSIGHT_CP_DATAPLANE_API_KEY"]' "\"$C\""
unset L H C
task sops:verify
```

- [ ] **Step 3: Generate the extension ConfigMap from upstream v0.10.1**

```bash
X=/tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/hs/hindsight-extensions/static-keys-tenant/hindsight_ext_static_keys_tenant
git -C /tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/hs describe --tags   # must print v0.10.1
{ printf '%s\n' '---' \
  '# Upstream StaticKeysTenantExtension, verbatim from vectorize-io/hindsight' \
  '# v0.10.1 hindsight-extensions/static-keys-tenant/. Upstream packages it as' \
  '# COPY -> /app/extensions + PYTHONPATH=/app/extensions (its Dockerfile);' \
  '# this ConfigMap + mount + PYTHONPATH is the same thing without an image' \
  '# build. Regenerate from the matching tag when bumping the chart.';
  kubectl create configmap hindsight-static-keys-ext --from-file=__init__.py=$X/__init__.py --from-file=extension.py=$X/extension.py --dry-run=client -o yaml; } \
  > kubernetes/apps/ai/hindsight/app/configmap-extension.yaml
```

- [ ] **Step 4: Create `ocirepository.yaml`**

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/source.toolkit.fluxcd.io/ocirepository_v1.json
apiVersion: source.toolkit.fluxcd.io/v1
kind: OCIRepository
metadata:
  name: hindsight
spec:
  interval: 12h
  layerSelector:
    mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip
    operation: copy
  ref:
    # renovate: datasource=docker depName=ghcr.io/vectorize-io/charts/hindsight
    tag: 0.10.1
  url: oci://ghcr.io/vectorize-io/charts/hindsight
```

- [ ] **Step 5: Create `helmrelease.yaml`**

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json
# Hindsight memory server (#701), running in parallel with OpenViking until
# the #704 eval gates cutover. Design:
# docs/superpowers/specs/2026-09-24-hindsight-deployment-design.md
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: hindsight
spec:
  interval: 1h
  chartRef:
    kind: OCIRepository
    name: hindsight
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  values:
    # Image tag for api + control plane. Keep equal to the chart tag.
    version: "0.10.1"
    # envFrom on both pods: postgres-password, HINDSIGHT_API_LLM_API_KEY,
    # HINDSIGHT_API_TENANT_USERS, HINDSIGHT_CP_DATAPLANE_API_KEY.
    existingSecret: hindsight-secret
    podAnnotations:
      reloader.stakater.com/auto: "true"

    api:
      replicaCount: 1
      # Default image bakes in bge-small-en-v1.5 + ms-marco-MiniLM-L-6-v2, so
      # recall has no inference dependency and no model PVC. The in-process
      # torch models put this pod above the repo's <2Gi guideline (accepted
      # in the spec); right-size after the retain trial.
      resources:
        requests:
          cpu: 250m
          memory: 1Gi
        limits:
          cpu: "2"
          memory: 4Gi
      env:
        HINDSIGHT_API_LLM_PROVIDER: openai
        HINDSIGHT_API_LLM_BASE_URL: http://omniroute.ai.svc.cluster.local:20128/v1
        # gpt-oss-20b via the scoped hindsight-retain key (restricted to this
        # one model -- cannot reach the Claude lane).
        HINDSIGHT_API_LLM_MODEL: llamaswap/reasoner
        # llama-swap runs gpt-oss-20b with 4 slots. Background operations
        # are capped at 1 each so one slot always stays free for reflect
        # (the per-op caps nest inside the global cap).
        HINDSIGHT_API_LLM_MAX_CONCURRENT: "4"
        HINDSIGHT_API_RETAIN_LLM_MAX_CONCURRENT: "1"
        HINDSIGHT_API_CONSOLIDATION_LLM_MAX_CONCURRENT: "1"
        HINDSIGHT_API_MENTAL_MODEL_REFRESH_LLM_MAX_CONCURRENT: "1"
        # Upstream default 64000 cannot fit a 32k slot; reasoning tokens
        # count against this budget, hence low effort.
        HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS: "16000"
        HINDSIGHT_API_RETAIN_LLM_REASONING_EFFORT: low
        # Per-client keys, all mapped to user josh -> one shared schema
        # (user_josh). Extension source: configmap-extension.yaml.
        HINDSIGHT_API_TENANT_EXTENSION: hindsight_ext_static_keys_tenant:StaticKeysTenantExtension
        PYTHONPATH: /app/extensions
        # Applied to every new bank: Memory Defense (#702) redacts secrets
        # and PII before storage; concise extraction (upstream #4560).
        HINDSIGHT_API_DEFAULT_BANK_TEMPLATE: '{"version":"1","bank":{"memory_defense":{"enabled":true,"rules":[{"on":"sensitive_data","action":"redact"}]},"retain_extraction_mode":"concise"}}'
      extraVolumes:
        - name: tenant-ext
          configMap:
            name: hindsight-static-keys-ext
      extraVolumeMounts:
        - name: tenant-ext
          mountPath: /app/extensions/hindsight_ext_static_keys_tenant
          readOnly: true

    worker:
      # The API runs the queue worker in-process (single replica rule).
      enabled: false

    controlPlane:
      replicaCount: 1

    postgresql:
      enabled: false
      external:
        host: postgres17-rw.databases.svc.cluster.local
        port: 5432
        database: hindsight
        username: hindsight

    metrics:
      serviceMonitor:
        enabled: true
```

- [ ] **Step 6: Create `httproute.yaml`**

```yaml
---
# LAN-only (traefik-internal, no Cloudflare record). The API is protected by
# per-client bearer keys (StaticKeysTenantExtension); the control plane has
# no login of its own and holds an API key, so it sits behind Authentik.
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: hindsight-api
  annotations:
    external-dns.alpha.kubernetes.io/target: 192.168.35.17
spec:
  hostnames:
    - hindsight.68cc.io
  parentRefs:
    - name: traefik-internal-gateway
      namespace: network
  rules:
    - backendRefs:
        - name: hindsight-api
          port: 8888
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: hindsight-ui
  annotations:
    external-dns.alpha.kubernetes.io/target: 192.168.35.17
spec:
  hostnames:
    - hindsight-ui.68cc.io
  parentRefs:
    - name: traefik-internal-gateway
      namespace: network
  rules:
    - filters:
        - type: ExtensionRef
          extensionRef:
            group: traefik.io
            kind: Middleware
            name: authentik-forwardauth
      backendRefs:
        - name: hindsight-control-plane
          port: 3000
```

- [ ] **Step 7: Create `kustomization.yaml` and `ks.yaml`, and wire into the namespace**

`app/kustomization.yaml`:
```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./secret.sops.yaml
  - ./configmap-extension.yaml
  - ./ocirepository.yaml
  - ./helmrelease.yaml
  - ./httproute.yaml
```

`ks.yaml`:
```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app hindsight
  namespace: &namespace ai
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  dependsOn:
    - name: cloudnative-pg-cluster
      namespace: databases
  interval: 1h
  path: ./kubernetes/apps/ai/hindsight/app
  prune: true
  retryInterval: 2m
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: *namespace
  timeout: 10m
  wait: false
```

In `kubernetes/apps/ai/kustomization.yaml`, add `  - ./hindsight/ks.yaml` after `./holyclaude/ks.yaml`. Add one sentence to that file's header comment: Hindsight runs in parallel with OpenViking (#701) until the #704 eval gates cutover.

- [ ] **Step 8: Validate the render**

```bash
kustomize build kubernetes/apps/ai/hindsight/app >/dev/null && echo BUILD-OK
kustomize build kubernetes/apps/ai/hindsight/app | yq 'select(.kind!="Secret")' | kubectl apply --dry-run=server -n ai -f - >/dev/null && echo DRYRUN-OK
S=/tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad
yq '.spec.values' kubernetes/apps/ai/hindsight/app/helmrelease.yaml > $S/hs-values.yaml
helm template hindsight $S/hs/helm/hindsight -n ai -f $S/hs-values.yaml | yq 'select(.kind=="Deployment") | .metadata.name + " " + .spec.template.metadata.annotations["reloader.stakater.com/auto"]'
helm template hindsight $S/hs/helm/hindsight -n ai -f $S/hs-values.yaml | yq 'select(.kind=="Deployment" and .metadata.name=="hindsight-api") | .spec.template.spec.containers[0].env[] | select(.name=="HINDSIGHT_API_DATABASE_URL") | .value'
echo '{"version":"1","bank":{"memory_defense":{"enabled":true,"rules":[{"on":"sensitive_data","action":"redact"}]},"retain_extraction_mode":"concise"}}' | jq -e . >/dev/null && echo TEMPLATE-JSON-OK
```
Expected: `BUILD-OK`, `DRYRUN-OK`; both Deployments print `true`; the DATABASE_URL host is `postgres17-rw.databases.svc.cluster.local`; `TEMPLATE-JSON-OK`.

- [ ] **Step 9: Commit and deploy**

```bash
git add kubernetes/apps/ai/hindsight kubernetes/apps/ai/kustomization.yaml
task sops:verify
git commit -m "feat(ai): deploy Hindsight memory server alongside OpenViking (#701)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin feat/701-hindsight:main && task reconcile
kubectl rollout status -n ai deploy/hindsight-api --timeout=10m
kubectl rollout status -n ai deploy/hindsight-control-plane --timeout=5m
```

- [ ] **Step 10: Confirm the extension loaded and the LLM is reachable**

```bash
kubectl exec -n ai deploy/hindsight-api -- /app/api/.venv/bin/python -c "import hindsight_ext_static_keys_tenant; print('EXT-OK')"
kubectl logs -n ai deploy/hindsight-api | grep -i -E "tenant|extension|error|traceback" | head -20
```
Expected: `EXT-OK`; the logs show the StaticKeys extension loaded and no tracebacks. If the `/app/api/.venv/bin/python` path doesn't exist, find it with `kubectl exec -n ai deploy/hindsight-api -- sh -c 'command -v python python3'`.

- [ ] **Step 11: Run the checks until they pass**

Run: `sh .../scratchpad/check-hindsight.sh`
Expected: `PASS`. The schema check needs one authenticated call first; the per-key loop provides it.

- [ ] **Step 12: Confirm metrics are scraped**

```bash
curl -s 'https://metrics.68cc.io/api/v1/query' --data-urlencode 'query=up{namespace="ai",service="hindsight-api"}' | jq -r '.data.result[] | .metric.pod + " " + .value[1]'
```
Expected: one pod with value `1` (allow up to 2 scrape intervals).

---

### Task 5: Verify Memory Defense before any capture

**Files:** none (runtime verification; results go into the Task 10 docs).

**Interfaces:**
- Consumes: laptop key (`TENANT_USERS` entry 1), `https://hindsight.68cc.io`.

- [ ] **Step 1: Retain planted fake secrets into a scratch bank, synchronously**

```bash
K=$(sops -d --extract '["stringData"]["HINDSIGHT_API_TENANT_USERS"]' kubernetes/apps/ai/hindsight/app/secret.sops.yaml | tr ',' '\n' | sed -n 1p | cut -d: -f2)
U=https://hindsight.68cc.io/v1/default/banks/md-scratch
curl -s -m 600 -X POST "$U/memories" -H "Authorization: Bearer $K" -H 'Content-Type: application/json' -d '{"async":false,"items":[{"content":"While debugging the deploy, Josh pasted the GitHub token ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789 and the connection string postgres://hsuser:S3cretPassw0rd@db.example.internal:5432/app into the terminal, then rotated both.","document_id":"md-test-1"}]}' | jq -c '{success, items_count}'
```
Expected: success.

- [ ] **Step 2: Check the bank got the policy and nothing stored the raw values**

```bash
curl -s "$U/config" -H "Authorization: Bearer $K" | jq -c '.. | .memory_defense? // empty' | head -1
curl -s "$U/memories?limit=50" -H "Authorization: Bearer $K" > /tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/md.json
curl -s "$U/documents" -H "Authorization: Bearer $K" >> /tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/md.json
grep -c -E "ghp_aBcDeF|S3cretPassw0rd" /tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/md.json || true
grep -o "REDACTED:[a-z_]*" /tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/md.json | sort -u
```
Expected: the policy JSON with `"enabled":true`; a raw-value count of `0`; at least one `REDACTED:` type, e.g. `REDACTED:github_token`.

**If the raw values appear: STOP.** Do not continue to Task 6 or any plugin install. Report to the operator.

- [ ] **Step 3: Delete the scratch bank and the local dump**

```bash
curl -s -X DELETE "$U" -H "Authorization: Bearer $K" | jq -c .
rm -f /tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/md.json; unset K
```

---

### Task 6: Retain quality trial (operator gate)

**Files:**
- Create (scratchpad only, never committed; transcripts may contain sensitive text): `.../scratchpad/retain-trial.py`, output `.../scratchpad/retain-trial/`

**Interfaces:**
- Consumes: laptop key, `POST /v1/default/banks/{bank}/memories/dry-run-extract` (body: `content`, `context`; extracts and stores nothing).
- Produces: `.../scratchpad/retain-trial/review.md` for the operator.

- [ ] **Step 1: Write the trial script**

```python
#!/usr/bin/env python3
"""Dry-run Hindsight extraction over ~20 real Claude Code transcripts and write a side-by-side review."""
import json, os, pathlib, subprocess, sys, time, urllib.request

PROJ = pathlib.Path.home() / ".claude/projects/-volume1-git-j0sh3rs-home-ops"
OUT = pathlib.Path(sys.argv[1])
KEY = os.environ["HS_KEY"]
URL = "https://hindsight.68cc.io/v1/default/banks/retain-trial/memories/dry-run-extract"
CAP = 40_000  # chars per transcript sent (~13 chunks at the 3,000-char default)

def transcript_text(path):
    lines = []
    for raw in path.read_text(errors="replace").splitlines():
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if e.get("type") not in ("user", "assistant"):
            continue
        c = (e.get("message") or {}).get("content")
        if isinstance(c, str):
            lines.append(f"{e['type'].upper()}: {c}")
        elif isinstance(c, list):
            for b in c:
                if b.get("type") == "text" and b.get("text"):
                    lines.append(f"{e['type'].upper()}: {b['text']}")
    return "\n".join(lines)

files = sorted(PROJ.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
texts = [(p, transcript_text(p)) for p in files]
texts = [(p, t) for p, t in texts if len(t) > 2_000]
largest = max(texts, key=lambda x: len(x[1]))
picked = texts[:19] + ([largest] if largest not in texts[:19] else texts[19:20])

OUT.mkdir(parents=True, exist_ok=True)
review = ["# Hindsight retain trial (gpt-oss-20b, concise)\n"]
for i, (p, t) in enumerate(picked, 1):
    body = json.dumps({"content": t[:CAP], "context": f"Claude Code session in home-ops ({p.name})"}).encode()
    req = urllib.request.Request(URL, body, {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            resp = json.loads(r.read())
        status = "ok"
    except Exception as ex:
        resp, status = {"error": str(ex)}, "error"
    dt = time.time() - t0
    (OUT / f"{i:02d}.json").write_text(json.dumps(resp, indent=2))
    review.append(f"\n## {i:02d}. {p.name} ({len(t)} chars total, {min(len(t), CAP)} sent, {dt:.0f}s, {status})\n")
    review.append("### Source excerpt (first 3,000 chars)\n```\n" + t[:3000] + "\n```\n")
    review.append("### Extracted\n```json\n" + json.dumps(resp, indent=2)[:12000] + "\n```\n")
    print(f"{i:02d} {status} {dt:.0f}s {p.name}", flush=True)
(OUT / "review.md").write_text("".join(review))
print("wrote", OUT / "review.md")
```

- [ ] **Step 2: Run it**

```bash
S=/tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad
HS_KEY=$(sops -d --extract '["stringData"]["HINDSIGHT_API_TENANT_USERS"]' kubernetes/apps/ai/hindsight/app/secret.sops.yaml | tr ',' '\n' | sed -n 1p | cut -d: -f2) \
  python3 $S/retain-trial.py $S/retain-trial
```
Run it in the background (`run_in_background`). It can take tens of minutes. Expected: 20 lines, each `ok`.

- [ ] **Step 3: Check for context overflow and truncation (Review Focus 2)**

```bash
kubectl logs -n ai deploy/llama-swap -c app --since=2h | grep -i -E "exceed|context size|n_ctx|truncat" | head
grep -l '"error"' /tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/retain-trial/*.json
```
Expected: no overflow lines and no error files. If the largest transcript overflowed: lower `HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS` to `12000` in the HelmRelease, deploy, and re-run just that transcript.

- [ ] **Step 4: Operator gate — STOP**

Give the operator the path to `review.md` and a summary: per-session latency, fact counts, and any errors. Ask them to judge against: facts correct and grounded, decisions and their rationale captured, nothing hallucinated, no truncation.
- **Approved:** continue to Task 7.
- **Rejected:** swap to `qwen3.5-35b-a3b`. In Task 1's configmap, uncomment it as the sole always-on model (`--parallel 4 --ctx-size 98304`, re-measure VRAM) and move the aliases. Set `allowedModels: ["llamaswap/frontier"]` on the key and `HINDSIGHT_API_LLM_MODEL: llamaswap/frontier`. Re-run this task.

- [ ] **Step 5: Delete the trial output**

```bash
rm -rf /tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/retain-trial
```

---

### Task 7: Plugin on this machine

**Files:**
- Local only: `~/.hindsight/coding-agent.json`, `~/.claude/settings.json` hooks (written by the installer), user-scope MCP entry.

**Interfaces:**
- Consumes: laptop key, `https://hindsight.68cc.io`.
- Produces: bank `coding-agent::<gitProject>` for this repo. Record its exact id for Task 8.

- [ ] **Step 1: Confirm the pinned package has the #4560 fix and the expected config keys**

```bash
S=/tmp/claude-0/-volume1-git-j0sh3rs-home-ops/fa8accdf-9595-4cee-ba74-2f9c99a7e9ba/scratchpad/pkg/package
grep -o 'DEFAULT_RETAIN_EXTRACTION_MODE = "[a-z]*"' $S/dist/*.js | sort -u
grep -o -E '"(apiUrl|apiToken|autoUpdate|retainExtractionMode|autoInject)"' $S/dist/*.js | sort -u
```
Expected: `"concise"`, and all five keys present. If `pkg/` is gone, re-fetch it with `npm pack @vectorize-io/hindsight-coding-agents@0.7.0`.

- [ ] **Step 2: Install**

```bash
npx -y @vectorize-io/hindsight-coding-agents@0.7.0 install claude-code --server self-hosted --api-url https://hindsight.68cc.io
ls -la ~/.hindsight/
```

- [ ] **Step 3: Set token and pins without printing the token**

```bash
K=$(sops -d --extract '["stringData"]["HINDSIGHT_API_TENANT_USERS"]' kubernetes/apps/ai/hindsight/app/secret.sops.yaml | tr ',' '\n' | sed -n 1p | cut -d: -f2)
C=~/.hindsight/coding-agent.json
jq --arg k "$K" '.apiUrl="https://hindsight.68cc.io" | .apiToken=$k | .autoUpdate=false | .retainExtractionMode="concise"' "$C" > "$C.tmp" && mv "$C.tmp" "$C" && chmod 600 "$C"
unset K
jq 'del(.apiToken) | {serverMode, apiUrl, autoUpdate, retainExtractionMode, autoInject}' "$C"
```
Expected: `apiUrl` set, `autoUpdate: false`, `retainExtractionMode: "concise"`, `autoInject` absent or `"reflect"`.

- [ ] **Step 4: Confirm the hooks sit alongside OpenViking's**

```bash
jq '.hooks | to_entries[] | {event: .key, commands: [.value[].hooks[].command]}' ~/.claude/settings.json
claude mcp list 2>/dev/null | grep -i -E "hindsight|openviking"
```
Expected: SessionStart, UserPromptSubmit and Stop each list both the Hindsight and the OpenViking hook commands; the Hindsight MCP server is listed.

- [ ] **Step 5: First session seeds the bank; confirm the bank and its policy**

```bash
cd /volume1/git/j0sh3rs/home-ops && claude -p "List the namespaces this repo deploys to, from the root CLAUDE.md." >/dev/null
K=$(sops -d --extract '["stringData"]["HINDSIGHT_API_TENANT_USERS"]' kubernetes/apps/ai/hindsight/app/secret.sops.yaml | tr ',' '\n' | sed -n 1p | cut -d: -f2)
curl -s https://hindsight.68cc.io/v1/default/banks -H "Authorization: Bearer $K" | jq -r '.. | .bank_id? // empty' | sort -u
```
Expected: a `coding-agent::…` bank for home-ops. Save its id: `B='<that id>'`, and write it down for Task 8.

```bash
curl -s "https://hindsight.68cc.io/v1/default/banks/$(jq -rn --arg b "$B" '$b|@uri')/config" -H "Authorization: Bearer $K" | jq -c '.. | .memory_defense? // empty' | head -1
curl -s "https://hindsight.68cc.io/v1/default/banks/$(jq -rn --arg b "$B" '$b|@uri')/operations" -H "Authorization: Bearer $K" | jq -c '[.. | .status? // empty] | group_by(.) | map({(.[0]): length}) | add'
```
Expected: the Memory Defense policy with `enabled: true`; operations listed (seed/retain), eventually all `completed`. Re-run until nothing is pending.

- [ ] **Step 6: Second session gets a reflect injection**

```bash
claude -p "Why was LiteLLM removed from this cluster?" >/dev/null
npx -y @vectorize-io/hindsight-coding-agents@0.7.0 stats
grep -i -E "reflect|inject" ~/.hindsight/*.log 2>/dev/null | tail -5
unset K
```
Expected: `stats` shows at least one injection, and the log shows a reflect for this session with no timeout fallback.

---

### Task 8: Plugin on HolyClaude

**Files:**
- Modify: `kubernetes/apps/ai/holyclaude/app/helmrelease.yaml` (`persistence.home.globalMounts` and the `app` container's `env`)
- Modify: `kubernetes/apps/ai/holyclaude/app/secret.sops.yaml` (add `HINDSIGHT_API_TOKEN`)

**Interfaces:**
- Consumes: HolyClaude key (`TENANT_USERS` entry 2), Service `hindsight-api.ai.svc.cluster.local:8888`, the bank id `B` from Task 7.
- Produces: the plugin installed under `/home/claude/.hindsight` (persisted), connection config from env.

- [ ] **Step 1: Write the failing check**

```bash
kubectl exec -n ai deploy/holyclaude -c app -- sh -c 'test -d /home/claude/.hindsight && echo "$HINDSIGHT_API_URL"'
```
Expected: FAIL (no directory, empty variable).

- [ ] **Step 2: Add the mount** in `persistence.home.globalMounts`, directly after the `.openviking` entry:

```yaml
          # Added 2026-09-24 (#701): Hindsight's coding-agents plugin keeps
          # its runtime copy, config (coding-agent.json), caches and logs in
          # ~/.hindsight. Same reason as .openviking above: installed once
          # from the web terminal, must survive restarts. Connection config
          # (HINDSIGHT_API_URL/HINDSIGHT_API_TOKEN) comes from env, not this file.
          - path: /home/claude/.hindsight
            subPath: .hindsight
```

- [ ] **Step 3: Add the env**

In the `app` container's `env:` map (the one holding `OMNIROUTE_ANTHROPIC_BASE_URL`), add:

```yaml
              # Hindsight plugin (#701), running in parallel with OpenViking.
              # In-cluster Service, not the LAN route. The token comes from
              # holyclaude-secret (envFrom).
              HINDSIGHT_API_URL: "http://hindsight-api.ai.svc.cluster.local:8888"
```

Then add the secret:

```bash
K=$(sops -d --extract '["stringData"]["HINDSIGHT_API_TENANT_USERS"]' kubernetes/apps/ai/hindsight/app/secret.sops.yaml | tr ',' '\n' | sed -n 2p | cut -d: -f2)
sops set kubernetes/apps/ai/holyclaude/app/secret.sops.yaml '["stringData"]["HINDSIGHT_API_TOKEN"]' "\"$K\""
unset K
task sops:verify
kustomize build kubernetes/apps/ai/holyclaude/app | yq 'select(.kind=="Deployment") | .spec.template.spec.containers[] | select(.name=="app") | .env[] | select(.name=="HINDSIGHT_API_URL")'
```

- [ ] **Step 4: Commit and deploy**

```bash
git add kubernetes/apps/ai/holyclaude/app/helmrelease.yaml kubernetes/apps/ai/holyclaude/app/secret.sops.yaml
git commit -m "feat(ai): wire Hindsight plugin config into holyclaude (#701)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin feat/701-hindsight:main && task reconcile
kubectl rollout status -n ai deploy/holyclaude --timeout=10m
```
Re-run the Step 1 check. Expected: prints `http://hindsight-api.ai.svc.cluster.local:8888`.

- [ ] **Step 5: Install as the terminal's user**

```bash
kubectl exec -n ai deploy/holyclaude -c app -- sh -c 'ps -eo user,args | grep -i -E "cloudcli|node-pty|claude" | grep -v grep | head -3'
```
Use the user shown (expected `claude`), then run:

```bash
kubectl exec -n ai deploy/holyclaude -c app -- runuser -u claude -- env HOME=/home/claude sh -lc 'cd /workspace/home-ops && npx -y @vectorize-io/hindsight-coding-agents@0.7.0 install claude-code --server self-hosted --api-url http://hindsight-api.ai.svc.cluster.local:8888'
kubectl exec -n ai deploy/holyclaude -c app -- runuser -u claude -- env HOME=/home/claude sh -lc 'C=~/.hindsight/coding-agent.json; jq ".autoUpdate=false | .retainExtractionMode=\"concise\" | del(.apiToken)" $C > $C.tmp && mv $C.tmp $C && jq "{apiUrl, autoUpdate, retainExtractionMode}" $C'
```
Expected: `autoUpdate: false`, `retainExtractionMode: "concise"`. The token comes from `HINDSIGHT_API_TOKEN` env.

- [ ] **Step 6: Check the bank is shared with this machine**

```bash
kubectl exec -n ai deploy/holyclaude -c app -- runuser -u claude -- env HOME=/home/claude sh -lc 'cd /workspace/home-ops && claude -p "Say OK." >/dev/null'
K=$(sops -d --extract '["stringData"]["HINDSIGHT_API_TENANT_USERS"]' kubernetes/apps/ai/hindsight/app/secret.sops.yaml | tr ',' '\n' | sed -n 1p | cut -d: -f2)
curl -s https://hindsight.68cc.io/v1/default/banks -H "Authorization: Bearer $K" | jq -r '.. | .bank_id? // empty' | sort -u
```
Expected: the same single home-ops bank as Task 7 (`$B`), with no second `coding-agent::…home-ops…` bank.
- If a second bank appeared: add `"mapPathToBank": {"/workspace/home-ops": "<B>"}` to HolyClaude's `coding-agent.json`, and `{"/volume1/git/j0sh3rs/home-ops": "<B>"}` to this machine's. Delete the stray bank via `DELETE /v1/default/banks/<stray>` and re-run this step.

Then the recall test:

```bash
BU=$(jq -rn --arg b "$B" '$b|@uri')
curl -s -m 600 -X POST "https://hindsight.68cc.io/v1/default/banks/$BU/memories" -H "Authorization: Bearer $K" -H 'Content-Type: application/json' -d '{"async":false,"items":[{"content":"Sentinel fact for the 2026-09-24 Hindsight parallel-run test: the shared bank check phrase is heliotrope-quasar.","document_id":"sentinel-701"}]}' | jq -c '{success}'
kubectl exec -n ai deploy/holyclaude -c app -- sh -c "curl -s -X POST \"\$HINDSIGHT_API_URL/v1/default/banks/$BU/memories/recall\" -H \"Authorization: Bearer \$HINDSIGHT_API_TOKEN\" -H 'Content-Type: application/json' -d '{\"query\":\"shared bank check phrase\"}'" | grep -o heliotrope-quasar | head -1
curl -s -X DELETE "https://hindsight.68cc.io/v1/default/banks/$BU/documents/sentinel-701" -H "Authorization: Bearer $K" | jq -c .
unset K
```
Expected: `heliotrope-quasar` is printed. Retained with the laptop key, recalled with the HolyClaude key.

- [ ] **Step 7: Survive a restart**

```bash
kubectl rollout restart -n ai deploy/holyclaude && kubectl rollout status -n ai deploy/holyclaude --timeout=10m
kubectl exec -n ai deploy/holyclaude -c app -- runuser -u claude -- env HOME=/home/claude sh -lc 'jq "[.hooks | to_entries[] | .value[].hooks[].command] | map(select(test(\"hindsight\";\"i\"))) | length" ~/.claude/settings.json; claude mcp list 2>/dev/null | grep -i hindsight'
```
Expected: a hook count ≥3 and the Hindsight MCP entry, both after the restart. If either is missing, the postStart `settings.json` patch (or `persist-claude-json.mjs`) is clobbering them. Fix the merge in `helmrelease.yaml`'s postStart script so it only sets its four keys, redeploy, and repeat this step.

---

### Task 9: Degradation and resilience tests

**Files:** none (runtime; results go into Task 10's docs).

**Interfaces:**
- Consumes: bank `$B`, laptop key.

- [ ] **Step 1: Recall with the LLM down**

```bash
task flux:suspend name=llama-swap ns=ai type=helmrelease
kubectl scale -n ai deploy/llama-swap --replicas=0 && kubectl wait -n ai --for=delete pod -l app.kubernetes.io/name=llama-swap --timeout=120s
K=$(sops -d --extract '["stringData"]["HINDSIGHT_API_TENANT_USERS"]' kubernetes/apps/ai/hindsight/app/secret.sops.yaml | tr ',' '\n' | sed -n 1p | cut -d: -f2)
BU=$(jq -rn --arg b "$B" '$b|@uri')
time curl -s -X POST "https://hindsight.68cc.io/v1/default/banks/$BU/memories/recall" -H "Authorization: Bearer $K" -H 'Content-Type: application/json' -d '{"query":"why was LiteLLM removed"}' | jq '.results | length'
time claude -p "Why was LiteLLM removed from this cluster? One sentence." 
```
Expected: recall returns >0 results in under 2s. `claude -p` completes, taking at most ~20s longer than usual (reflect timeout, then fallback).

- [ ] **Step 2: Retain queues while the LLM is down, then survives an API restart (Review Focus 4)**

```bash
curl -s -X POST "https://hindsight.68cc.io/v1/default/banks/$BU/memories" -H "Authorization: Bearer $K" -H 'Content-Type: application/json' -d '{"async":true,"items":[{"content":"Queue test 2026-09-24: this retain was submitted while llama-swap was scaled to zero.","document_id":"queue-test-701"}]}' | jq -c '{success, operation_id}'
curl -s "https://hindsight.68cc.io/v1/default/banks/$BU/operations" -H "Authorization: Bearer $K" | jq -c '[.. | .status? // empty] | group_by(.) | map({(.[0]): length}) | add'
kubectl rollout restart -n ai deploy/hindsight-api && kubectl rollout status -n ai deploy/hindsight-api --timeout=10m
curl -s "https://hindsight.68cc.io/v1/default/banks/$BU/operations" -H "Authorization: Bearer $K" | jq -c '[.. | .status? // empty] | group_by(.) | map({(.[0]): length}) | add'
```
Expected: the operation shows pending (or retrying, not failed) both before and after the restart.

- [ ] **Step 3: Restore the LLM; the queue drains**

```bash
kubectl scale -n ai deploy/llama-swap --replicas=1 && task flux:resume name=llama-swap ns=ai type=helmrelease
kubectl rollout status -n ai deploy/llama-swap --timeout=10m
sleep 180; curl -s "https://hindsight.68cc.io/v1/default/banks/$BU/operations" -H "Authorization: Bearer $K" | jq -c '[.. | .status? // empty] | group_by(.) | map({(.[0]): length}) | add'
```
Expected: no pending operations; `queue-test-701` completed. If it shows `failed` because retries ran out during the outage, record it: queued retains are then only as durable as `HINDSIGHT_API_WORKER_MAX_RETRIES` × backoff (default 3 × 60s). Raise `HINDSIGHT_API_WORKER_MAX_RETRIES` to `20` in the HelmRelease env, deploy, and repeat Steps 2–3 once.

- [ ] **Step 4: Claude Code with Hindsight down (Review Focus 3)**

```bash
task flux:suspend name=hindsight ns=ai type=helmrelease
kubectl scale -n ai deploy/hindsight-api --replicas=0
time claude -p "Say OK."
kubectl scale -n ai deploy/hindsight-api --replicas=1 && task flux:resume name=hindsight ns=ai type=helmrelease
kubectl rollout status -n ai deploy/hindsight-api --timeout=10m
```
Expected: the prompt completes, within ~30s at worst (the installer's hook timeout), with no error surfaced to the user. Record the time.

- [ ] **Step 5: Clean up**

```bash
curl -s -X DELETE "https://hindsight.68cc.io/v1/default/banks/$BU/documents/queue-test-701" -H "Authorization: Bearer $K" | jq -c .
unset K
```

---

### Task 10: Documentation and the #705 allowlist

**Files:**
- Modify: `kubernetes/apps/ai/CLAUDE.md`
- Modify (on branch `security/705-omniroute-cnp`): `kubernetes/apps/ai/omniroute/app/networkpolicy.yaml`

- [ ] **Step 1: Add a Hindsight bullet to `kubernetes/apps/ai/CLAUDE.md`** directly after the openviking bullet, covering:
  - What and where: chart 0.10.1, API + control plane, in-process worker, `hindsight.68cc.io` (bearer keys) and `hindsight-ui.68cc.io` (Authentik), both LAN-only.
  - DB: CNPG `hindsight` Database with `vector`, role secret pairing.
  - Auth: StaticKeysTenantExtension from a ConfigMap (regenerate on chart bump), `TENANT_USERS` order (laptop, holyclaude, control plane), one shared `user_josh` schema.
  - LLM: `hindsight-retain` key restricted to `llamaswap/reasoner`, `compressionEnabled: false`; the 4-slot concurrency design; the 16k completion cap.
  - Memory Defense on every bank via `HINDSIGHT_API_DEFAULT_BANK_TEMPLATE` (Task 5 result).
  - Plugin 0.7.0 pinned on this machine and HolyClaude (`~/.hindsight` mount, env-supplied connection), shared bank id `B`.
  - Parallel run with OpenViking: double injection accepted; cutover gated on #704; Codex/Pi and backfill (#703) pending.
  - Task 9 measurements: recall latency with the LLM down, first-prompt delay, behavior with Hindsight down, queue durability.
  - Accepted trade-offs from the spec: embedding model (change before #703), API pod memory, once-per-session injection.

  In "Known Omniroute limitations", change "All 8 automated Omniroute keys" to note that `hindsight-retain` (added 2026-09-24) is the one restricted automated key.

- [ ] **Step 2: Verify and commit**

```bash
grep -n -i "hindsight" kubernetes/apps/ai/CLAUDE.md | head
git add kubernetes/apps/ai/CLAUDE.md
git commit -m "docs(ai): document Hindsight parallel deployment (#701)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin feat/701-hindsight:main
```

- [ ] **Step 3: Add Hindsight to the disabled #705 allowlist**

```bash
git checkout security/705-omniroute-cnp
```
In `kubernetes/apps/ai/omniroute/app/networkpolicy.yaml`, in the `:20128` `fromEndpoints` list, add after the openviking entry:

```yaml
        # Hindsight API (retain/reflect/consolidation via hindsight-retain
        # key, #701). The in-process worker lives in this pod.
        - matchLabels:
            app.kubernetes.io/name: hindsight
            app.kubernetes.io/component: api
```
Then remove "Hindsight" from the header's "When a new consumer lands (Hindsight, …)" example list.

```bash
kustomize build kubernetes/apps/ai/omniroute/app >/dev/null && yq '.' kubernetes/apps/ai/omniroute/app/networkpolicy.yaml >/dev/null && echo OK
git add kubernetes/apps/ai/omniroute/app/networkpolicy.yaml
git commit -m "feat(ai): allow Hindsight API in the disabled omniroute ingress policy (#705)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git checkout feat/701-hindsight
```
Do not push this branch; it stays disabled per the operator.

- [ ] **Step 4: Comment on #701** with a short status: what's deployed, the Task 5/6/9 results, the parallel-run state, and what remains (Codex/Pi, #703, #704, cutover). Ask the operator before posting.
