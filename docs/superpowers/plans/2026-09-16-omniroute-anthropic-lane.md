# Omniroute Anthropic Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate Anthropic (Claude) in Omniroute to interactive use only,
consolidate HolyClaude onto Omniroute's single Claude Pro session (retiring
its own separate native OAuth login), and fix the `openviking-vlm` combo so
OpenViking's memory-extraction/VLM calls actually succeed on the OpenAI or
local leg instead of failing on all three.

**Architecture:** Omniroute's combos/keys/providers live only in its SQLite
DB (dashboard/API-managed, not git) — mutated here via its management API
(`OMNIROUTE_MGMT_TOKEN`, already present as an env var in the `omniroute`
pod's `app` container, reachable via `kubectl exec` — never decrypted to a
terminal/transcript). Git-tracked changes (HelmRelease env, SOPS secrets,
`llama-swap-apu` ctx-size, doc corrections) go through the normal Flux
reconcile path. HolyClaude's Claude Code auth moves from a native `claude
login` OAuth session to `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` pointed
at Omniroute, with the actual settings.json values patched in by an
idempotent Node snippet in the existing postStart hook (targeted merge, not
a full-file overwrite — `~/.claude/settings.json` accumulates live
plugin/auto-mode state that must not be clobbered).

**Tech Stack:** Flux (HelmRelease), SOPS+age, Omniroute's `/api/keys` +
`/api/combos` + `/api/providers` management endpoints, `kubectl exec`,
`rocm-smi`.

**Spec:** `docs/superpowers/specs/2026-09-16-omniroute-anthropic-lane-design.md`
(read this first — this plan implements it in full, plus corrections found
during this plan's own live investigation — see Task 1's context note).

## Global Constraints

- **Never print a decrypted secret or a live Omniroute key value to a
  terminal/transcript.** Every management-API call in this plan runs
  `OMNIROUTE_MGMT_TOKEN`/minted key values through `node -e` scripts
  executed via `kubectl exec`, printing only status codes, lengths, or
  non-secret response fields — mirrors `scripts/omniroute-mcp-headers.sh`'s
  own established pattern. This repo has already had one transcript-exposure
  incident requiring a full credential rotation (commit `8733af0d`); this
  plan's Task 1 exists specifically to close a second one found live.
- **No automated consumer's Omniroute key may reach any `cliproxyapi/claude-*`
  model**, whether through a combo or a bare model reference. This is the
  core lane rule the whole plan enforces.
- Omniroute's model addressing is `<prefix>/<model>` for bare models
  (`cliproxyapi/claude-sonnet-5`) or a bare combo name with no prefix
  (`coding-deep`) — confirmed live against both `/v1/chat/completions` and
  `/v1/messages`.
- `kustomize build kubernetes/apps/ai/<app>/app | kubectl apply --dry-run=client -f -`
  and `task sops:verify` before every commit touching a manifest/secret —
  matches this repo's standing pre-commit convention (`CLAUDE.md`).
- Working directory for all `git`/`kustomize`/`task` commands in this plan
  is this repo's checkout root (wherever you're actually running from —
  prior plans used `/workspace/home-ops`, the path inside HolyClaude's own
  pod; adjust if executing from elsewhere).

---

### Task 1: Rotate the exposed HolyClaude key and formalize its Omniroute wiring

**Context (found during this plan's own investigation, not in the spec):**
HolyClaude's live `~/.claude/settings.json` (on its PVC, not git) is
*already* pointed at Omniroute — `ANTHROPIC_BASE_URL:
http://omniroute.ai.svc.cluster.local:20128`, `ANTHROPIC_MODEL:
cliproxyapi/claude-sonnet-5`, `ANTHROPIC_AUTH_TOKEN: <plaintext sk-...
key>` — set up manually outside GitOps, last used 3 hours before this plan
was written. The backing Omniroute key (`holyclaude-claude-code`, id
`dadf94cc-88bc-463c-bad0-2ac42f734e87`) has zero scoping
(`allowedCombos: ["combo/*"]`, `modelAccessMode: "all"`) — it can reach
every model/combo Omniroute knows about, not just Claude. A second, unused
key (`holyclaude-claude-code-pilot`, id `9cec0388-70e4-4459-89f2-295dd04b419b`,
`isActive: false`, last used 2026-09-10) is an abandoned earlier attempt.
Both need revoking; a properly scoped, git-tracked replacement takes their
place. `caveman-proxy` (the local daemon `~/.claude/settings.json` used to
point `ANTHROPIC_BASE_URL` at before this manual change) is confirmed
already bypassed — its `proxy.log` has no entries after 2026-09-15 09:35
(a "listening" line from a container restart, no traffic since) — left
running but out of Claude Code's path; not removed by this plan (its
broader disposition is still an open item, but it's confirmed harmless as
long as nothing points at it).

**Files:**
- Modify: `kubernetes/apps/ai/holyclaude/app/secret.sops.yaml`
- Modify: `kubernetes/apps/ai/holyclaude/app/helmrelease.yaml:201-208` (env
  block), `:271-280` (postStart hook), plus the OAuth-mechanism comment
  block around it (the "Also launches the caveman plugin's local proxy
  daemon" comment specifically needs an update — it describes a mechanism
  no longer in Claude Code's path)

**Interfaces:**
- Consumes: Omniroute `/api/keys` (revoke 2, mint 1), `/api/combos` (the
  pre-existing `coding-deep` combo — `claude-sonnet-5` → `gpt-5.5` →
  `llamaswap/coder-large`, already built for exactly this use).
- Produces: `OMNIROUTE_API_KEY` in `holyclaude-secret`, consumed by Task 4's
  access-control audit (which must NOT touch this key — it's the one
  interactive exception the audit is checking for).

- [ ] **Step 1: Revoke both existing ad hoc HolyClaude keys**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const ids=['dadf94cc-88bc-463c-bad0-2ac42f734e87','9cec0388-70e4-4459-89f2-295dd04b419b'];
(async()=>{
  for(const id of ids){
    await new Promise(res=>{
      const req=http.request({host:'127.0.0.1',port:20128,path:'/api/keys/'+id,method:'DELETE',headers:{Authorization:'Bearer '+tok}},r=>{r.on('data',()=>{});r.on('end',()=>{console.log(id, r.statusCode);res();});});
      req.on('error',e=>{console.log(id,'ERR',e.message);res();});
      req.end();
    });
  }
})();
"
```
Expected: both print `200` or `204` (check whichever this Omniroute version
returns for a successful delete — either is a pass, anything else is a
real failure to investigate before continuing).

- [ ] **Step 2: Mint a scoped `holyclaude-interactive` key**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const body=JSON.stringify({name:'holyclaude-interactive',allowedCombos:['coding-fast','coding-deep','debugging','advanced']});
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/keys',method:'POST',headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>{
    const j=JSON.parse(d);
    console.log(r.statusCode, 'key length:', (j.key||'').length, 'allowedCombos:', JSON.stringify(j.allowedCombos));
  });
});
req.end(body);
" > /tmp/holyclaude-key-meta.txt
cat /tmp/holyclaude-key-meta.txt
```
Expected: `201` (or `200`), key length ~52 (matches the `sk-...` format
seen on every other minted key in this cluster), `allowedCombos` echoes
back the 4 combo names — do NOT print the key value itself, only its
length, per the Global Constraints above.

Now retrieve the actual key value into the SOPS edit flow *without* it
passing through this transcript — pipe the mint response's `key` field
directly into `sops` via a second, separate exec that writes straight to a
local temp file this session never `cat`s:

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/keys',method:'GET',headers:{Authorization:'Bearer '+tok}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>{
    const j=JSON.parse(d);
    const k=(j.keys||j).find(k=>k.name==='holyclaude-interactive');
    console.log(k.key || k.keyPrefix+'... (full key only returned at mint time, not on list -- use Step 2 mint response instead if this is empty)');
  });
});
req.end();
" > /tmp/holyclaude-key-value.txt
```
If the list endpoint doesn't return the full key (many key-management APIs
only return the secret once, at creation), re-run Step 2's mint call and
redirect its own output straight to `/tmp/holyclaude-key-value.txt`
instead of this session's stdout — extract the `key` field from that file
with `python3 -c "import json;print(json.load(open('/tmp/holyclaude-key-meta.txt'))['key'])" > /tmp/holyclaude-key-value.txt`
if Step 2 was already run and its raw JSON is still available; otherwise
redo Step 2 capturing the full response to a file this session never reads
back verbatim.

- [ ] **Step 3: Put the new key into `holyclaude-secret.sops.yaml`**

Use the `sops-edit-then-encrypt` skill on
`kubernetes/apps/ai/holyclaude/app/secret.sops.yaml`, adding:
```yaml
stringData:
  GITHUB_TOKEN: <unchanged>
  OMNIROUTE_API_KEY: <contents of /tmp/holyclaude-key-value.txt>
```
Then delete `/tmp/holyclaude-key-meta.txt` and `/tmp/holyclaude-key-value.txt`.
Verify: `task sops:verify` shows ✅ for this file.

- [ ] **Step 4: Edit `helmrelease.yaml`'s env block (lines 201-208)**

Add two new entries after `HOLYCLAUDE_DESLOPPIFY_SETUP`:
```yaml
            env:
              TZ: America/New_York
              PUID: "1000"
              PGID: "1000"
              NODE_OPTIONS: "--max-old-space-size=4096"
              GIT_USER_NAME: BarryBot
              GIT_USER_EMAIL: github+barrybot@beholdthehurricane.com
              HOLYCLAUDE_DESLOPPIFY_SETUP: "claude,opencode"
              # Omniroute-backed Claude Code auth (2026-09-16) -- replaces
              # the native `claude login` OAuth device-flow session this
              # deployment used previously. OMNIROUTE_ANTHROPIC_BASE_URL is
              # a plain value (no secret needed, same cluster-internal
              # pattern every other Omniroute consumer uses);
              # OMNIROUTE_ANTHROPIC_MODEL is the pre-existing "coding-deep"
              # combo (claude-sonnet-5 -> gpt-5.5 -> local llamaswap/
              # coder-large fallback), not a bare model -- gives graceful
              # degradation if the Claude Pro session itself is briefly
              # unavailable, unlike a bare cliproxyapi/claude-sonnet-5
              # reference. The postStart hook below reads both of these
              # plus OMNIROUTE_API_KEY (from envFrom) and patches them into
              # settings.json's own env block on every boot -- Claude Code
              # reads its own settings.json env over real container env
              # vars, so setting these as plain container env here alone
              # would NOT take effect without that patch step.
              OMNIROUTE_ANTHROPIC_BASE_URL: "http://omniroute.ai.svc.cluster.local:20128"
              OMNIROUTE_ANTHROPIC_MODEL: "coding-deep"
```

- [ ] **Step 5: Edit the postStart hook (lines ~271-280) to patch settings.json**

Replace the comment block above `lifecycle:` describing caveman-proxy (the
one starting "Finally, launches the caveman plugin's local proxy daemon.
~/.claude/settings.json points ANTHROPIC_BASE_URL at
http://127.0.0.1:8787/w/claude...") with:
```yaml
            # Finally, launches the caveman plugin's local proxy daemon --
            # kept running (still image/PVC-baked) but NO LONGER in Claude
            # Code's own request path as of 2026-09-16: settings.json's
            # ANTHROPIC_BASE_URL now points directly at Omniroute (see the
            # settings.json patch above this hook), not at caveman-proxy's
            # 127.0.0.1:8787. caveman-proxy's own disposition (remove vs.
            # re-point at Omniroute as ITS upstream) is an open item --
            # left alone here since it's confirmed harmless (dormant, no
            # incoming traffic) rather than guessed at. `setsid` detaches
            # it from this postStart process's session and `nohup`+closed
            # stdio stop a SIGHUP/closed-pipe from taking it down when the
            # hook exits, so it outlives the hook the same way it survived
            # the manual exec session used to confirm the original
            # 2026-09-05 fix. No idempotency guard needed: a container
            # restart tears down its whole PID namespace, so there's never
            # a prior instance still alive when this runs.
```
Then add a new step *before* the `cat /tmp/bashrc-extra` line, patching
`settings.json`'s Claude Code auth fields from the container env set in
Step 4 (this MUST run before caveman-proxy's own launch line, order
doesn't matter relative to it, but must exist):
```yaml
            lifecycle:
              postStart:
                exec:
                  command:
                    - sh
                    - -c
                    - |
                      set -eu
                      for f in /home/claude/.local/share/user-bin/*; do
                        [ -e "$f" ] || continue
                        ln -sf "$f" "/home/claude/.local/bin/$(basename "$f")"
                      done
                      if [ -f /home/claude/.claude/settings.json ]; then
                        node -e '
                          const fs = require("fs");
                          const p = "/home/claude/.claude/settings.json";
                          const s = JSON.parse(fs.readFileSync(p, "utf8"));
                          s.env = s.env || {};
                          s.env.ANTHROPIC_BASE_URL = process.env.OMNIROUTE_ANTHROPIC_BASE_URL;
                          s.env.ANTHROPIC_MODEL = process.env.OMNIROUTE_ANTHROPIC_MODEL;
                          s.env.ANTHROPIC_AUTH_TOKEN = process.env.OMNIROUTE_API_KEY;
                          s.model = process.env.OMNIROUTE_ANTHROPIC_MODEL;
                          fs.writeFileSync(p, JSON.stringify(s, null, 2));
                        '
                      fi
                      cat /tmp/bashrc-extra >> /home/claude/.bashrc
                      setsid nohup /home/claude/.caveman/bin/caveman-proxy \
                        >>/home/claude/.caveman/proxy.log 2>&1 </dev/null &
```
This is a targeted merge (only 4 keys touched: `env.ANTHROPIC_BASE_URL`,
`env.ANTHROPIC_MODEL`, `env.ANTHROPIC_AUTH_TOKEN`, top-level `model`) —
every other field in the live settings.json (`enabledPlugins`,
`extraKnownMarketplaces`, `autoMode`, `hooks`, `statusLine`, etc.) is read
and rewritten back unchanged, never clobbered. The `if [ -f ... ]` guard
skips this on a fresh PVC where settings.json doesn't exist yet (owned by
the image's own first-boot bootstrap, not recreated here).

- [ ] **Step 6: Validate and deploy**

```bash
kustomize build kubernetes/apps/ai/holyclaude/app | kubectl apply --dry-run=client -f -
git add kubernetes/apps/ai/holyclaude/app/helmrelease.yaml kubernetes/apps/ai/holyclaude/app/secret.sops.yaml
git commit -m "fix(ai): rotate exposed holyclaude Omniroute key, wire via GitOps"
git pull --rebase origin main
git push
task flux:reconcile-ks name=holyclaude ns=ai
```

- [ ] **Step 7: Confirm the rotation actually took and the old keys are dead**

```bash
kubectl rollout status deployment/holyclaude -n ai --timeout=180s
kubectl exec -n ai deploy/holyclaude -c app -- node -e "
  const s = JSON.parse(require('fs').readFileSync('/home/claude/.claude/settings.json','utf8'));
  console.log('base_url:', s.env.ANTHROPIC_BASE_URL);
  console.log('model:', s.env.ANTHROPIC_MODEL);
  console.log('token starts with:', (s.env.ANTHROPIC_AUTH_TOKEN||'').slice(0,12));
"
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/keys',method:'GET',headers:{Authorization:'Bearer '+tok}},r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>{
  const rows=(JSON.parse(d).keys||JSON.parse(d));
  console.log(rows.filter(k=>k.name.includes('holyclaude')).map(k=>k.name+' active='+k.isActive));
});});
req.end();
"
```
Expected: settings.json's `base_url`/`model` match the new values, the
token prefix is NOT `sk-04cd564e8` or `sk-011b55b0c` (the two revoked
keys' prefixes — confirms this is genuinely the new key, not a stale
cached one), and the `/api/keys` listing shows only `holyclaude-interactive`
active, the two old ones gone (deleted) or `active=false` (revoked, if this
Omniroute version soft-deletes instead).

---

### Task 2: Fix `llama-swap-apu`'s vlm ctx-size

**Files:**
- Modify: `kubernetes/apps/ai/llama-swap-apu/app/configmap.yaml:127-137`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: a working local-fallback leg for Task 3's `openviking-vlm`
  combo fix — Task 3 depends on this being deployed first, since it
  verifies the combo's local leg specifically.

- [ ] **Step 1: Warm all four always-on models, then measure real headroom**

A cold measurement right after a pod restart under-reports usage — models
load lazily on first request. Force all four to load, then measure:

```bash
kubectl exec -n ai deploy/llama-swap-apu -- sh -c '
  curl -s -X POST http://localhost:8080/v1/chat/completions -H "Content-Type: application/json" -d "{\"model\":\"fast\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":1}" > /dev/null
  curl -s -X POST http://localhost:8080/v1/embeddings -H "Content-Type: application/json" -d "{\"model\":\"embed\",\"input\":\"hi\"}" > /dev/null
  curl -s -X POST http://localhost:8080/v1/chat/completions -H "Content-Type: application/json" -d "{\"model\":\"chat\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":1}" > /dev/null
  curl -s -X POST http://localhost:8080/v1/chat/completions -H "Content-Type: application/json" -d "{\"model\":\"vlm\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":1}" > /dev/null
'
kubectl exec -n ai deploy/llama-swap-apu -- rocm-smi --showmeminfo vram
```
Expected: a `VRAM Total Used Memory (B)` figure. Compute free = 17179869184
(16 GiB total) minus this value. Record this number — it's the real
headroom this step's ctx-size decision is based on, not the stale 1.88 GiB
figure in `kubernetes/apps/ai/CLAUDE.md`.

- [ ] **Step 2: Raise `qwen2-vl-2b`'s ctx-size**

The observed failure needed 45309 tokens. Target `--ctx-size 49152` (a
value already used elsewhere in this repo's llama-swap fleet, e.g.
`agentic-coder`'s ctx-size on the main `llama-swap` instance, so it's a
known-reasonable size class, not an arbitrary pick) — clears the observed
requirement with real margin. Only apply this if Step 1's measured free
headroom is comfortably larger than the KV-cache growth this implies (this
model's KV cache scales with ctx-size; going from 16384 to 49152 is a 3x
increase in KV-cache footprint specifically, not a 3x increase in the
model's total footprint — if Step 1 showed less than ~3 GiB free, drop the
target to `32768` instead and note the reduced number in the commit
message).

Edit `kubernetes/apps/ai/llama-swap-apu/app/configmap.yaml:127-137`:
```yaml
      "qwen2-vl-2b":
        cmd: |
          ${apu-vulkan}
          --model /models/Qwen2-VL-2B-Instruct-Q4_K_M.gguf
          --mmproj /models/mmproj-Qwen2-VL-2B-Instruct-f16.gguf
          --ctx-size 49152
          --temp 0.0
        aliases:
          - "vlm"
          - "vision"
        ttl: 0
```
Update the comment block above it (lines ~99-126) — append a new dated
note in the same style as the existing 2026-08-19 one, recording the real
free-headroom figure from Step 1, the new ctx-size, and the reason (the
45309-token memory-extraction failure from `openviking-vlm`'s local
fallback leg, 2026-09-16).

- [ ] **Step 3: Validate and deploy**

```bash
kustomize build kubernetes/apps/ai/llama-swap-apu/app | kubectl apply --dry-run=client -f -
git add kubernetes/apps/ai/llama-swap-apu/app/configmap.yaml
git commit -m "fix(ai): raise llama-swap-apu vlm ctx-size for real memory-extraction prompts"
git pull --rebase origin main
git push
task flux:reconcile-ks name=llama-swap-apu ns=ai
kubectl rollout status deployment/llama-swap-apu -n ai --timeout=120s
```

- [ ] **Step 4: Re-measure and confirm no OOM**

```bash
kubectl get pods -n ai -l app.kubernetes.io/name=llama-swap-apu
kubectl logs -n ai deploy/llama-swap-apu --tail=50 | grep -i "error\|oom\|killed"
kubectl exec -n ai deploy/llama-swap-apu -- sh -c 'curl -s -X POST http://localhost:8080/v1/chat/completions -H "Content-Type: application/json" -d "{\"model\":\"vlm\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":1}"'
kubectl exec -n ai deploy/llama-swap-apu -- rocm-smi --showmeminfo vram
```
Expected: pod `Running`, no OOM/error lines, the vlm completion returns a
real response (not a 400/500), and the new VRAM-used figure is still well
under 16 GiB. If the pod crash-loops or OOMs, revert to `32768` and repeat
Steps 3-4 — do not leave the tier destabilized to hit the higher number.

---

### Task 3: Fix the `openviking-vlm` combo (remove Claude, fix or replace the OpenAI leg)

**Files:** none in git — this combo lives only in Omniroute's DB.

**Interfaces:**
- Consumes: Task 2's working local fallback leg (verified before this task
  starts), Omniroute's `/api/combos` management endpoint, the `cliproxyapi`
  model catalog already enumerated (16 Claude ids, plus `gpt-5.5`,
  `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-6-astra` as non-Claude
  alternatives to `gpt-5.6-luna`).
- Produces: nothing consumed by later tasks in this plan (Task 4's audit
  checks this combo's *result*, not an interface it exposes).

- [ ] **Step 1: Find a Chat-Completions-compatible OpenAI leg**

`gpt-5.6-luna` 400s with `One of "input" or "previous_response_id" ...
must be provided` — a Responses-API-shaped model being sent a
Chat-Completions request. Test each other available `gpt-*` id from the
`cliproxyapi` catalog against a real, cheap `/v1/chat/completions` call
(1 token, minimal cost against the Codex subscription) to find one that
accepts this shape:

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const candidates=['gpt-5.5','gpt-5.6-terra','gpt-5.6-sol','gpt-6-astra'];
(async()=>{
  for(const m of candidates){
    const body=JSON.stringify({model:'cliproxyapi/'+m,messages:[{role:'user',content:'hi'}],max_tokens:1});
    await new Promise(res=>{
      const req=http.request({host:'127.0.0.1',port:20129,path:'/v1/chat/completions',method:'POST',headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{
        let d='';r.on('data',c=>d+=c);r.on('end',()=>{console.log(m, r.statusCode, d.slice(0,200));res();});
      });
      req.on('error',e=>{console.log(m,'ERR',e.message);res();});
      req.end(body);
    });
  }
})();
"
```
Note: this uses the mgmt token against `/v1/chat/completions`, which
normally wants an `sk-...` inference key, not the mgmt token — if every
candidate 401s instead of giving a real 200/400, re-run using the
`phase1-local-inference` key's value instead (mint a throwaway test key the
same way Task 1 Step 2 did, if none of the existing unscoped keys' values
are already in hand from this session). Expected: at least one candidate
returns `200` with a real completion body (not the `input`/`previous_response_id`
error) — that's the replacement for `gpt-5.6-luna`. If genuinely none do,
this is a real upstream CLIProxyAPI limitation (Codex's OpenAI-shaped
access may be Responses-API-only) — skip to Step 2 with the OpenAI leg
simply removed from the combo (Task 2's fixed local leg becomes the sole
fallback), and note this finding in the commit message and in
`kubernetes/apps/ai/CLAUDE.md` (Task 5) as a documented limitation, not a
silent gap.

- [ ] **Step 2: Edit the combo — remove Claude, fix/replace the OpenAI leg**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const comboId='52b84d63-d6d8-43a9-b9c4-8fe90146535a';
// Replace 'gpt-5.5' below with whichever candidate Step 1 found working,
// or drop the middle entry entirely if Step 1 found none.
const body=JSON.stringify({
  models:[
    {model:'cliproxyapi/gpt-5.5',providerId:'cliproxyapi',weight:0},
    {model:'llamaswapapu/vlm',providerId:'llamaswapapu',weight:0}
  ]
});
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/combos/'+comboId,method:'PATCH',headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d.slice(0,500)));
});
req.end(body);
"
```
If `PATCH` isn't the right method/isn't supported (check the response —
a `404`/`405` means try `PUT`, or check `docs/openapi.yaml`'s
`updateComboSchema` if accessible from inside the pod), adjust the method
accordingly — this is exactly the kind of upstream-doc-vs-real-behavior gap
the Phase 1 spec already hit three times; verify against the actual
response, don't assume `PATCH` is correct just because it reads naturally.

- [ ] **Step 3: Verify the combo no longer references Claude**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/combos',method:'GET',headers:{Authorization:'Bearer '+tok}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>{
    const c=JSON.parse(d).combos.find(c=>c.name==='openviking-vlm');
    console.log(JSON.stringify(c.models.map(m=>m.model)));
  });
});
req.end();
"
```
Expected: no entry contains `claude` (case-insensitive check the output by
eye — the array should be exactly 2 entries now: the OpenAI replacement
(or omitted, per Step 1's fallback) and `llamaswapapu/vlm`).

---

### Task 4: Access-control audit — block Claude on every automated key

**Files:** none in git — Omniroute keys are DB-only.

**Interfaces:**
- Consumes: Task 1's `holyclaude-interactive` key (the one exception this
  audit must NOT touch), the 16-id Claude model list already enumerated
  under the `cliproxyapi` provider.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Set `blockedModels` on every automated key**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const claudeIds=['claude-opus-4-7','claude-opus-5','claude-3-7-sonnet-20250219','claude-opus-4-6','claude-fable-5-1','claude-opus-4-5-20251101','claude-opus-4-8','claude-sonnet-5','claude-fable-5','claude-sonnet-4-20250514','claude-haiku-4-5-20251001','claude-sonnet-4-6','claude-opus-4-1-20250805','claude-opus-4-20250514','claude-3-5-haiku-20241022','claude-sonnet-4-5-20250929'].map(m=>'cliproxyapi/'+m);
const automatedKeyIds={
  'phase1-local-inference':'8f7607cc-9cc7-4a20-a751-c2e94556a875',
  'openviking-embedding':'ca547751-765a-4f08-80b8-2aab18d49a08',
  'openviking-vlm':'786ca1ed-44c5-4d83-86f0-19f30690f367',
  'openclaw':'13445cd5-41f9-41f3-854a-c1afa3ead942',
  'argus-holmes':'0daacd73-f82b-46e4-9b36-6bb6cdab6f60',
  'atuin-ai-server':'71a7ae92-0f75-462a-9140-37ec7018b485',
  'controller-compression-probe':'441f805a-e05d-467b-83ad-a03fc2e8726d',
  'home-assistant-conversation':'a03fd884-62f5-4e73-a910-b59fadfbd45a'
};
const body=JSON.stringify({blockedModels:claudeIds});
(async()=>{
  for(const [name,id] of Object.entries(automatedKeyIds)){
    await new Promise(res=>{
      const req=http.request({host:'127.0.0.1',port:20128,path:'/api/keys/'+id,method:'PATCH',headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{
        let d='';r.on('data',c=>d+=c);r.on('end',()=>{console.log(name, r.statusCode);res();});
      });
      req.on('error',e=>{console.log(name,'ERR',e.message);res();});
      req.end(body);
    });
  }
})();
"
```
Same method caveat as Task 3 Step 2 — check the response, switch to `PUT`
if `PATCH` isn't supported. Expected: every key prints `200`.

- [ ] **Step 2: Verify with a real blocked request**

Using the `openviking-vlm` key's own value (not the mgmt token — mint a
throwaway test won't work here since it needs to be an already-blocked
key; if the key value isn't already in hand from earlier work, decrypt
`kubernetes/apps/ai/openviking/app/secret.sops.yaml`'s
`OPENVIKING_VLM_API_KEY` via the `sops-edit-then-encrypt` skill's read-only
mode and pipe it directly into this exec without printing it):

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const key=process.env.TEST_KEY; // exported into this shell from the decrypted secret, never echoed
const body=JSON.stringify({model:'cliproxyapi/claude-sonnet-5',messages:[{role:'user',content:'hi'}],max_tokens:1});
const req=http.request({host:'127.0.0.1',port:20129,path:'/v1/chat/completions',method:'POST',headers:{Authorization:'Bearer '+key,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d.slice(0,300)));
});
req.end(body);
"
```
Expected: a `403`/`400`-class rejection referencing the blocked model, NOT
a successful completion — this is the actual proof the lane rule is
enforced at the key level, not just by combo convention. If it still
succeeds, `blockedModels` isn't honored the way its name implies (or needs
exact-match strings you don't have — re-check against the real ids
returned in Step 1's request body) — do not consider this task done until
this check genuinely fails closed.

- [ ] **Step 3: Confirm `holyclaude-interactive` is untouched**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/keys',method:'GET',headers:{Authorization:'Bearer '+tok}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>{
    const k=(JSON.parse(d).keys||JSON.parse(d)).find(k=>k.name==='holyclaude-interactive');
    console.log('blockedModels:', JSON.stringify(k.blockedModels), 'allowedCombos:', JSON.stringify(k.allowedCombos));
  });
});
req.end();
"
```
Expected: `blockedModels` is empty/unset (this key was never in the
automated list above) and `allowedCombos` still shows the 4 coding combos
from Task 1.

---

### Task 5: Documentation sweep

**Files:**
- Modify: `kubernetes/apps/ai/CLAUDE.md`

**Interfaces:** none — pure documentation, no code interfaces.

- [ ] **Step 1: Correct the stale LiteLLM/Omniroute narrative**

```bash
grep -n "litellm\|LiteLLM\|LITELLM" kubernetes/apps/ai/CLAUDE.md
```
This file currently states LiteLLM and Omniroute were both removed
2026-08-14 and describes LiteLLM as the live gateway — stale relative to
the two prior Omniroute specs already merged (`2026-09-07-omniroute-revival-design.md`,
`2026-09-08-omniroute-phase2-switchover-design.md`) plus this plan. For
each match: if it's in the top-of-file architecture summary or the
`openviking`/`holyclaude` bullets, rewrite it to describe the current
state (Omniroute fronting both llama-swap instances plus the CLIProxyAPI
sidecar; `openviking-vlm`/`embedding`/`rerank` routing; HolyClaude's
Omniroute-backed Claude Code auth, replacing the native-OAuth description).
If it's in "Decisions explicitly rejected" describing Omniroute as
removed, replace that bullet with a pointer to the three specs (revival,
Phase 2 switchover, this one) instead of leaving it standing as a rejection
that no longer reflects reality.

- [ ] **Step 2: Update the `holyclaude` bullet specifically**

Replace the sentence describing "Claude Code (interactive Max/Pro OAuth
device-flow login, not `ANTHROPIC_API_KEY` — the session persists via the
image's own `persist-claude-json.mjs` mechanism onto the PVC, no
Kubernetes Secret represents this credential)" with a description of the
new mechanism: Omniroute-backed auth via `OMNIROUTE_API_KEY`
(git-tracked SOPS secret, `holyclaude-interactive` Omniroute key scoped to
4 coding combos), the `coding-deep` combo as the default model, and the
postStart settings.json patch that wires it in on every boot. Also update
the `~/.claude` PVC-mount rationale paragraph if it references
`persist-claude-json.mjs` as the sole credential-persistence mechanism —
note that this no longer applies to Claude Code's auth specifically (other
providers on this PVC, if any, are unaffected).

- [ ] **Step 3: Commit**

```bash
git add kubernetes/apps/ai/CLAUDE.md
git commit -m "docs(ai): correct stale LiteLLM/OAuth narrative, describe Omniroute Anthropic lane"
git pull --rebase origin main
git push
```

---

### Task 6: End-to-end verification

**Files:** none — verification only.

**Interfaces:** consumes the results of Tasks 1-4, all of which must be
complete and individually verified before this task starts.

- [ ] **Step 1: Trigger a real OpenViking session and confirm memory extraction succeeds**

Interact with OpenViking (via its bot endpoint or a real Claude Code
session that exercises memory capture — whichever this environment's
normal usage pattern is) enough to trigger a memory-extraction cycle, then:
```bash
kubectl logs -n ai deploy/openviking --since=15m | grep -i "memory extraction\|Phase 2 step long_term\|bad_gateway"
```
Expected: no `bad_gateway`/`502` aggregate failures referencing all three
combo legs — either a successful extraction log line, or at most a
single-leg failure with a clean fallback to the next (not a total combo
exhaustion).

- [ ] **Step 2: Confirm no live Omniroute config still grants Claude access outside the interactive lane**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/combos',method:'GET',headers:{Authorization:'Bearer '+tok}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>{
    JSON.parse(d).combos.forEach(c=>{
      const hasClaude=c.models.some(m=>m.model.includes('claude'));
      if(hasClaude) console.log(c.name, JSON.stringify(c.models.map(m=>m.model)));
    });
  });
});
req.end();
"
```
Expected: only `coding-fast`/`coding-deep`/`debugging`/`advanced` print
(the interactive-only combos `holyclaude-interactive` is scoped to) —
`openviking-vlm` must NOT appear in this list anymore.

- [ ] **Step 3: Real interactive test from inside HolyClaude**

From HolyClaude's own web terminal, run a real Claude Code prompt (e.g.
ask it to read a file), then check Omniroute's own request log/dashboard
(`omniroute.68cc.io`, or `/api/...` usage endpoint if one exists) shows the
call attributed to the `holyclaude-interactive` key and the `coding-deep`
combo — confirms the round-trip actually works end-to-end, not just that
config looks right.

- [ ] **Step 4: Ask the user to confirm real-world recovery**

This can't be verified from cluster-side logs alone — Anthropic's
account-level usage-cap state isn't observable from here. Report Tasks 1-4
complete and ask the user to confirm over the following days that
HolyClaude's Claude Code sessions no longer degrade under OpenViking
background load.

---

## Self-Review Notes

- **Spec coverage:** every section of the design spec maps to a task —
  combo fix (Task 3), HolyClaude consolidation (Task 1), local-fallback fix
  (Task 2), access control (Task 4), documentation (Task 5), verification
  (Task 6). The spec's `caveman-proxy` open item is addressed as "confirmed
  harmless, left alone" rather than resolved outright — a real finding from
  this plan's own investigation (its log shows no traffic since Claude Code
  stopped pointing at it), not a placeholder.
- **New finding folded in, not silently absorbed:** Task 1 exists because
  this plan's own live investigation found HolyClaude already manually
  wired to Omniroute with an unscoped, plaintext-exposed key — called out
  explicitly in Task 1's Context note and in the Global Constraints, not
  buried as if it were always part of the original design.
- **Ordering enforced structurally:** Task 3 depends on Task 2's local
  fallback leg being live and working first (both git-committed changes,
  no overlap, but the dependency is explicit); Task 4 depends on Task 1's
  `holyclaude-interactive` key existing (so the audit has an exception to
  verify against, not just automated keys to lock down); Task 6 depends on
  all four.
- **Known follow-up, not a gap:** Task 3 Step 1's exact PATCH-vs-PUT method
  and Step 1's OpenAI-leg replacement candidate are left as "verify against
  the real response," matching this repo's established discipline (Phase 1
  found three real bugs specifically from trusting assumptions over live
  verification) — not guessed at here.
