# CLIProxyAPI Responses-API Shim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every `cliproxyapi/gpt-*` model in Omniroute (currently 100%
broken) by adding a translation sidecar that converts between the
Chat-Completions shape Omniroute always sends and the Responses-API-only
shape CLIProxyAPI actually accepts, then restore a working remote leg to
OpenViking's `openviking-vlm` combo.

**Architecture:** A new `shim` sidecar container in the existing
`omniroute` pod (same pod as `app` and `cliproxyapi`, sharing its network
namespace so it can reach CLIProxyAPI on `127.0.0.1:8317`, which is not
reachable from anywhere else in the cluster). Omniroute's `cliproxyapi`
provider-node has its `baseUrl` repointed (live, via Omniroute's own
management API — a DB-only change, no git file) from
`http://localhost:8317/v1` to the shim's local port. Omniroute's own
combo/key/logging layer is completely unchanged and unaware the shim
exists — from its perspective it's still talking to a normal
Chat-Completions backend.

**Tech Stack:** Node.js (`node:22-alpine`, built-in `http` module only, no
dependencies), bjw-s app-template (ConfigMap-mounted script, no custom
image build), Omniroute's management API, Flux/Kustomize.

**Spec:** `docs/superpowers/specs/2026-09-17-cliproxyapi-responses-shim-design.md`
(read this first — this plan implements it in full).

## Global Constraints

- **Text-only for v1.** Any message with non-text content (e.g.
  `image_url`) must be rejected with a clear `400`, never silently
  dropped. Image/multimodal translation is explicitly out of scope.
- **No streaming.** Buffered request/response only. SSE translation is
  explicitly out of scope.
- **Never print a decrypted secret or API key value anywhere** — not to
  stdout, not into a report, not into a commit. This applies to both
  Omniroute's own management token/inference keys AND CLIProxyAPI's
  separate `api-keys` (from `cliproxy-config.yaml`, mounted into the
  `cliproxyapi` container at `/CLIProxyAPI/config.yaml` and into the new
  `shim` container at `/shim-config/cliproxy-config.yaml` — a raw view of
  this file's structure with values redacted is fine for investigation;
  the raw values are not.
- **The shim's port must never be exposed via a Kubernetes Service** —
  reachable only inside the `omniroute` pod, matching the same boundary
  CLIProxyAPI's own port has always had.
- **CLIProxyAPI has no `/v1/chat/completions` endpoint at all** (confirmed
  404) — only `/v1/responses` (confirmed to exist, needs its own API-key
  auth) and `/v1/models`. Do not target `/v1/chat/completions` on
  CLIProxyAPI from the shim; it does not exist.
- **Omniroute's own `/v1/responses` route is not a real Responses API
  implementation** — it calls the same internal `handleChat()` as
  `/v1/chat/completions` and will never correctly forward a Responses-API-
  shaped request. Do not attempt to use it as a workaround.
- `kustomize build kubernetes/apps/ai/omniroute/app | kubectl apply
  --dry-run=client -f -` before every commit touching this app's manifests.
- Working directory: wherever you're actually running from; commit and
  push directly to `origin/main` (this repo's established single-operator
  workflow — no feature branch).

---

### Task 1: Scaffold the shim sidecar (stub, prove connectivity)

**Files:**
- Create: `kubernetes/apps/ai/omniroute/app/configmap-shim.yaml`
- Modify: `kubernetes/apps/ai/omniroute/app/kustomization.yaml`
- Modify: `kubernetes/apps/ai/omniroute/app/helmrelease.yaml` (add a `shim`
  container under `controllers.omniroute.containers`, alongside the
  existing `app` and `cliproxyapi` containers at line 34; add two
  `persistence` entries after the existing `cliproxy-config` entry at
  line ~223)

**Interfaces:**
- Consumes: nothing from earlier tasks (first task).
- Produces: a running `shim` container listening on `0.0.0.0:8318` inside
  the `omniroute` pod, with `/shim-config/cliproxy-config.yaml` mounted
  read-only (same secret CLIProxyAPI itself uses) — Task 2 replaces the
  stub script with real translation logic and uses this same mount to read
  CLIProxyAPI's own API key.

- [ ] **Step 1: Create the ConfigMap with a stub script**

```yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: omniroute-shim-script
data:
  server.js: |
    'use strict';
    const http = require('http');

    const PORT = 8318;

    // Stub for Task 1 -- proves the container starts, listens, and is
    // reachable from the `app` container over localhost. Task 2 replaces
    // this with real Chat-Completions <-> Responses-API translation logic
    // once CLIProxyAPI's real API-key format and Responses API shapes are
    // confirmed live. See
    // docs/superpowers/specs/2026-09-17-cliproxyapi-responses-shim-design.md.
    const server = http.createServer((req, res) => {
      if (req.method === 'GET' && req.url === '/healthz') {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ status: 'ok' }));
        return;
      }
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ status: 'stub', message: 'shim not yet implemented' }));
    });

    server.listen(PORT, '0.0.0.0', () => console.log('shim stub listening on', PORT));
```

- [ ] **Step 2: Add the ConfigMap to `kustomization.yaml`**

`kubernetes/apps/ai/omniroute/app/kustomization.yaml` currently reads:
```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./secret.sops.yaml
  - ./helmrelease.yaml
  - ./httproute.yaml
```
Add the new file to `resources:`:
```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./secret.sops.yaml
  - ./configmap-shim.yaml
  - ./helmrelease.yaml
  - ./httproute.yaml
```

- [ ] **Step 3: Add the `shim` container to `helmrelease.yaml`**

In `kubernetes/apps/ai/omniroute/app/helmrelease.yaml`, the `containers:`
block (starting at line 34) currently has `app` (lines 35-132) and
`cliproxyapi` (lines 134-183). Add a new `shim` entry immediately after
`cliproxyapi`'s closing (after line 183, before the `service:` key that
currently starts at line 185):

```yaml
          shim:
            # Chat-Completions -> Responses API translation shim for
            # CLIProxyAPI, added 2026-09-17 (see
            # docs/superpowers/specs/2026-09-17-cliproxyapi-responses-shim-design.md).
            # CLIProxyAPI (the cliproxyapi container above) never
            # implemented a Chat Completions endpoint -- confirmed via
            # direct request, GET /v1/chat/completions there returns 404;
            # only /v1/responses exists (confirmed via GET returning 401,
            # not 404 -- the route exists, it just needs CLIProxyAPI's own
            # API-key auth). Omniroute's own handleChat always builds
            # Chat-Completions-shaped requests regardless of which of its
            # own routes is hit -- confirmed by POSTing a real
            # Responses-API-shaped body straight to Omniroute's own
            # /v1/responses and getting the identical "missing input"
            # error, proving that route is not a real implementation, just
            # an alias to the same internal handler. This container
            # translates the shape so every cliproxyapi/gpt-* model works
            # again. Omniroute itself is repointed (via its own management
            # API, a DB-only change -- see Task 3) to treat this container
            # as if it WERE CLIProxyAPI, so no combo/key config changes
            # anywhere else are needed. Reaches CLIProxyAPI at
            # 127.0.0.1:8317 -- only possible because this runs in the
            # SAME pod (shared network namespace); that port has never
            # been exposed as its own Service, a deliberate boundary from
            # the original Omniroute revival design
            # (docs/superpowers/specs/2026-09-07-omniroute-revival-design.md)
            # that this change does not alter -- do not add a Service port
            # for 8318 either.
            image:
              repository: docker.io/library/node
              # renovate: datasource=docker depName=node versioning=node
              tag: 22-alpine
              pullPolicy: IfNotPresent
            command: ["node", "/shim/server.js"]
            resources:
              requests:
                cpu: 50m
                memory: 64Mi
              limits:
                cpu: "1"
                memory: 256Mi
            probes:
              liveness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /healthz
                    port: 8318
                  initialDelaySeconds: 5
                  periodSeconds: 15
              readiness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /healthz
                    port: 8318
                  initialDelaySeconds: 3
                  periodSeconds: 10
```

- [ ] **Step 4: Add persistence mounts**

In the same file's `persistence:` block, the existing `cliproxy-config`
entry (lines 223-231) currently mounts only into `cliproxyapi`:
```yaml
      cliproxy-config:
        type: secret
        name: omniroute-secrets
        advancedMounts:
          omniroute:
            cliproxyapi:
              - path: /CLIProxyAPI/config.yaml
                subPath: cliproxy-config.yaml
                readOnly: true
```
Extend it to also mount into `shim` (the shim needs to read CLIProxyAPI's
own API key from this same file), and add a new entry for the ConfigMap
script:
```yaml
      cliproxy-config:
        type: secret
        name: omniroute-secrets
        advancedMounts:
          omniroute:
            cliproxyapi:
              - path: /CLIProxyAPI/config.yaml
                subPath: cliproxy-config.yaml
                readOnly: true
            shim:
              - path: /shim-config/cliproxy-config.yaml
                subPath: cliproxy-config.yaml
                readOnly: true
      shim-script:
        type: configMap
        name: omniroute-shim-script
        advancedMounts:
          omniroute:
            shim:
              - path: /shim/server.js
                subPath: server.js
                readOnly: true
```

- [ ] **Step 5: Validate**

```bash
kustomize build kubernetes/apps/ai/omniroute/app | kubectl apply --dry-run=client -f -
```
Expected: clean render, no errors (the usual benign
`last-applied-configuration` warnings are fine, same as every other task
in this project has seen).

Also confirm reloader coverage, per this repo's standing requirement that
every ConfigMap/Secret consumer carries a reloader annotation:
```bash
kustomize build kubernetes/apps/ai/omniroute/app | grep reloader.stakater
```
Expected: at least one match on the `omniroute` controller (it already
carries `reloader.stakater.com/auto: "true"` at the controller level,
line 28 — this applies pod-template-wide and already covers the new
ConfigMap/Secret mounts; no new annotation needed, just confirm it's
still there).

- [ ] **Step 6: Commit, push, deploy**

```bash
git add kubernetes/apps/ai/omniroute/app/configmap-shim.yaml kubernetes/apps/ai/omniroute/app/kustomization.yaml kubernetes/apps/ai/omniroute/app/helmrelease.yaml
git commit -m "feat(ai): scaffold cliproxyapi shape-translation shim (stub)"
git pull --rebase origin main
git push
flux reconcile kustomization omniroute -n ai --with-source
```
(If `task flux:reconcile-ks` is used instead and fails with `context
"home" does not exist`: that's a pre-existing kubeconfig-context mismatch
unrelated to this change, already noted in this project's history — use
the raw `flux reconcile kustomization` command above instead.)

- [ ] **Step 7: Verify the stub is live and reachable**

```bash
kubectl get pods -n ai -l app.kubernetes.io/name=omniroute
```
Expected: `3/3` containers ready (was `2/2` before this task).

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const req=http.request({host:'127.0.0.1',port:8318,path:'/healthz',method:'GET'},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d));
});
req.on('error',e=>console.log('ERR',e.message));
req.end();
"
```
Expected: `200 {"status":"ok"}` — proves the `app` container can reach the
new `shim` container over localhost.

```bash
kubectl exec -n ai deploy/omniroute -c shim -- sh -c "ls -la /shim-config/ && wc -l /shim-config/cliproxy-config.yaml"
```
Expected: the file is present and mounted (a line count is not a secret
value — this only confirms the mount worked, don't `cat` the file's
contents in this step).

---

### Task 2: Implement real translation logic

**Files:**
- Modify: `kubernetes/apps/ai/omniroute/app/configmap-shim.yaml` (replace
  the stub `server.js` with the full implementation below)

**Interfaces:**
- Consumes: the `shim` container and `/shim-config/cliproxy-config.yaml`
  mount from Task 1.
- Produces: a working shim listening on `:8318` at `POST
  /v1/chat/completions`, translating to/from CLIProxyAPI's real
  `/v1/responses` — Task 3 repoints Omniroute's provider-node at this
  exact path/port.

- [ ] **Step 1: Investigate CLIProxyAPI's real `api-keys` format (redacted, no values)**

```bash
kubectl exec -n ai deploy/omniroute -c shim -- sh -c "grep -n '^[a-zA-Z_-]*:' /shim-config/cliproxy-config.yaml"
```
This shows the top-level YAML key structure (key *names* and line
numbers only — safe). Find the line number where `api-keys:` appears,
then view that section with all long tokens redacted:
```bash
kubectl exec -n ai deploy/omniroute -c shim -- sh -c "awk '/^api-keys:/,0' /shim-config/cliproxy-config.yaml | head -20 | sed -E 's/[A-Za-z0-9_.-]{10,}/<redacted>/g'"
```
Expected: reveals the *shape* of the `api-keys` list (e.g. a plain list of
redacted strings, or a list of objects with `name:`/`key:` fields) without
exposing any real value. Use this to confirm/adjust the `loadApiKey()`
parser in Step 3 below — the implementation given assumes a plain
YAML list of quoted or unquoted strings under `api-keys:`; if the real
structure is object-based (e.g. `- name: "x"` / `  key: "sk-..."` on
separate lines) or otherwise different, adjust the regex in `loadApiKey()`
accordingly before moving on. Do not guess past this step — confirm the
real shape first.

- [ ] **Step 2: Investigate CLIProxyAPI's real Responses API request/response shape**

Using the API key found in Step 1 (read it server-side inside this exact
script, never printed):
```bash
kubectl exec -n ai deploy/omniroute -c shim -- sh -c "node -e \"
const http=require('http');
const fs=require('fs');
const raw=fs.readFileSync('/shim-config/cliproxy-config.yaml','utf8');
const lines=raw.split('\n');
let inKeys=false, key=null;
for(const line of lines){
  if(/^api-keys:/.test(line)){inKeys=true;continue;}
  if(inKeys){
    if(/^\S/.test(line))break;
    const m=line.match(/-\s*\\\"?([^\\\"\s]+)\\\"?\s*\$/);
    if(m){key=m[1];break;}
  }
}
if(!key){console.log('NO KEY FOUND -- adjust the parser above per Step 1 findings');process.exit(1);}
const body=JSON.stringify({model:'gpt-5.6-luna',input:[{role:'user',content:[{type:'input_text',text:'reply with just: ok'}]}],max_output_tokens:16});
const req=http.request({host:'127.0.0.1',port:8317,path:'/v1/responses',method:'POST',headers:{Authorization:'Bearer '+key,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d));
});
req.on('error',e=>console.log('ERR',e.message));
req.end(body);
\""
```
Expected: either a real `200` response (record its exact JSON shape —
this is the ground truth for `responsesToChatCompletion()` in Step 3
below) or a real error revealing what field/shape it actually wants (in
which case adjust the request body and retry — do not spend more than 3-4
iterations on this before treating a persistent failure as a finding to
report rather than a bug to keep guessing at, per this project's own
debugging discipline). If the response shape differs from what
`responsesToChatCompletion()` assumes below (OpenAI's public Responses API
spec: `output_text` or `output: [{type:"message", content:[{text}]}]`,
`usage: {input_tokens, output_tokens}`), adjust that function's field
extraction to match the real shape before finalizing Step 3 — do not ship
Step 3's code unverified against this real response.

- [ ] **Step 3: Replace the stub with the real implementation**

Update `kubernetes/apps/ai/omniroute/app/configmap-shim.yaml`'s
`data.server.js` to:

```javascript
'use strict';
const http = require('http');
const fs = require('fs');

const PORT = 8318;
const CLIPROXY_HOST = '127.0.0.1';
const CLIPROXY_PORT = 8317;
const CONFIG_PATH = '/shim-config/cliproxy-config.yaml';

// Parses CLIProxyAPI's own api-keys list out of its mounted config file.
// Shape assumed: a plain YAML list of quoted or bare strings under
// `api-keys:`. If Step 1's investigation found a different shape (e.g.
// object entries with a `key:` field), adjust this regex accordingly --
// confirmed structure beats this assumption.
function loadApiKey() {
  const raw = fs.readFileSync(CONFIG_PATH, 'utf8');
  const lines = raw.split('\n');
  let inApiKeys = false;
  for (const line of lines) {
    if (/^api-keys:/.test(line)) { inApiKeys = true; continue; }
    if (inApiKeys) {
      if (/^\S/.test(line)) break;
      const m = line.match(/-\s*"?([^"\s]+)"?\s*$/);
      if (m) return m[1];
    }
  }
  throw new Error('no api key found in ' + CONFIG_PATH);
}

const CLIPROXY_KEY = loadApiKey();

class ShimError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => { data += c; });
    req.on('end', () => resolve(data));
    req.on('error', reject);
  });
}

// Text-only v1 -- any non-text content part throws a ShimError(400),
// never silently dropped. See Global Constraints.
function chatToResponsesInput(messages) {
  const input = [];
  for (const m of messages) {
    if (typeof m.content === 'string') {
      input.push({ role: m.role, content: [{ type: 'input_text', text: m.content }] });
      continue;
    }
    if (Array.isArray(m.content)) {
      const parts = [];
      for (const part of m.content) {
        if (part.type === 'text') {
          parts.push({ type: 'input_text', text: part.text });
        } else {
          throw new ShimError(
            400,
            `Unsupported content type "${part.type}" -- this shim is text-only (v1); image/multimodal content is not translated. See docs/superpowers/specs/2026-09-17-cliproxyapi-responses-shim-design.md.`
          );
        }
      }
      input.push({ role: m.role, content: parts });
      continue;
    }
    throw new ShimError(400, `Unsupported message content shape for role "${m.role}"`);
  }
  return input;
}

function callCliProxy(path, body) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const req = http.request(
      {
        host: CLIPROXY_HOST,
        port: CLIPROXY_PORT,
        path,
        method: 'POST',
        headers: {
          Authorization: 'Bearer ' + CLIPROXY_KEY,
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(payload),
        },
      },
      (res) => {
        let data = '';
        res.on('data', (c) => { data += c; });
        res.on('end', () => resolve({ status: res.statusCode, body: data }));
      }
    );
    req.on('error', reject);
    req.end(payload);
  });
}

// Field names below match OpenAI's public Responses API spec
// (output_text / output[].content[].text, usage.input_tokens/
// output_tokens) -- CONFIRMED-OR-ADJUSTED against a real CLIProxyAPI
// response in Task 2 Step 2 before this code was finalized. If that step
// found a different real shape, this function must already reflect it,
// not the assumed default.
function responsesToChatCompletion(model, responsesBody) {
  const parsed = JSON.parse(responsesBody);
  let text = '';
  if (typeof parsed.output_text === 'string') {
    text = parsed.output_text;
  } else if (Array.isArray(parsed.output)) {
    for (const item of parsed.output) {
      if (item.type === 'message' && Array.isArray(item.content)) {
        for (const c of item.content) {
          if (typeof c.text === 'string') text += c.text;
        }
      }
    }
  }
  const usage = parsed.usage || {};
  return {
    id: parsed.id || 'shim-' + Date.now(),
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [
      {
        index: 0,
        finish_reason: 'stop',
        message: { role: 'assistant', content: text },
      },
    ],
    usage: {
      prompt_tokens: usage.input_tokens || 0,
      completion_tokens: usage.output_tokens || 0,
      total_tokens: usage.total_tokens || (usage.input_tokens || 0) + (usage.output_tokens || 0),
    },
  };
}

function sendError(res, status, message, upstream) {
  const body = { error: { message, type: 'server_error', code: 'shim_error' } };
  if (upstream !== undefined) body.upstream_details = upstream;
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/healthz') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok' }));
    return;
  }
  if (req.method !== 'POST' || req.url !== '/v1/chat/completions') {
    sendError(res, 404, 'not found');
    return;
  }
  try {
    const raw = await readBody(req);
    const parsed = JSON.parse(raw);
    const input = chatToResponsesInput(parsed.messages || []);
    const responsesBody = { model: parsed.model, input };
    if (parsed.max_tokens) responsesBody.max_output_tokens = parsed.max_tokens;
    if (parsed.temperature !== undefined) responsesBody.temperature = parsed.temperature;

    const upstream = await callCliProxy('/v1/responses', responsesBody);
    if (upstream.status < 200 || upstream.status >= 300) {
      let parsedUpstream;
      try { parsedUpstream = JSON.parse(upstream.body); } catch (e) { parsedUpstream = upstream.body; }
      sendError(res, upstream.status, 'CLIProxyAPI request failed', parsedUpstream);
      return;
    }
    const chatBody = responsesToChatCompletion(parsed.model, upstream.body);
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify(chatBody));
  } catch (err) {
    if (err instanceof ShimError) {
      sendError(res, err.status, err.message);
    } else {
      sendError(res, 500, 'shim internal error: ' + err.message);
    }
  }
});

server.listen(PORT, '0.0.0.0', () => console.log('shim listening on', PORT));
```

- [ ] **Step 4: Validate and deploy**

```bash
kustomize build kubernetes/apps/ai/omniroute/app | kubectl apply --dry-run=client -f -
git add kubernetes/apps/ai/omniroute/app/configmap-shim.yaml
git commit -m "feat(ai): implement cliproxyapi shape-translation logic"
git pull --rebase origin main
git push
flux reconcile kustomization omniroute -n ai --with-source
```

- [ ] **Step 5: Verify directly (bypass Omniroute)**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const body=JSON.stringify({model:'gpt-5.6-luna',messages:[{role:'user',content:'reply with just: ok'}],max_tokens:16});
const req=http.request({host:'127.0.0.1',port:8318,path:'/v1/chat/completions',method:'POST',headers:{'content-type':'application/json','content-length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d.slice(0,500)));
});
req.on('error',e=>console.log('ERR',e.message));
req.end(body);
"
```
Expected: `200` with a real Chat-Completions-shaped body (`choices[0].
message.content` containing real text, `usage.prompt_tokens`/
`completion_tokens` populated). This is the core proof the translation
works, independent of Omniroute entirely. If this fails, do not proceed to
Task 3 — fix it here first (this step's failure is much easier to debug in
isolation than a failure surfacing through Omniroute's own combo/retry
logic).

Also confirm the text-only guard fires correctly:
```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const body=JSON.stringify({model:'gpt-5.6-luna',messages:[{role:'user',content:[{type:'image_url',image_url:{url:'https://example.com/x.png'}}]}],max_tokens:16});
const req=http.request({host:'127.0.0.1',port:8318,path:'/v1/chat/completions',method:'POST',headers:{'content-type':'application/json','content-length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d.slice(0,300)));
});
req.on('error',e=>console.log('ERR',e.message));
req.end(body);
"
```
Expected: `400` with a message naming the unsupported content type —
confirms the reject-loudly path works, not a silent pass-through.

---

### Task 3: Repoint Omniroute's cliproxyapi provider-node at the shim

**Files:** none in git — this is a live Omniroute management-API mutation
(DB-only, same as several tasks in the prior Anthropic-lane project).

**Interfaces:**
- Consumes: the working shim from Task 2, listening on `127.0.0.1:8318`
  inside the `omniroute` pod.
- Produces: every `cliproxyapi/gpt-*` reference across the whole cluster
  (not just OpenViking's) now resolves through the shim transparently —
  Task 4 depends on this being live before testing a real combo leg.

- [ ] **Step 1: Repoint the provider-node's `baseUrl`**

The `cliproxyapi` provider-node's connection id is
`3e29f7a8-5c0c-4914-ba78-9c4bf6d38d06` (confirmed live earlier this
project via `GET /api/providers`). Its current `baseUrl` is
`http://localhost:8317/v1`; change it to
`http://localhost:8318/v1` (the shim's port):

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const body=JSON.stringify({providerSpecificData:{baseUrl:'http://localhost:8318/v1'}});
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/providers/3e29f7a8-5c0c-4914-ba78-9c4bf6d38d06',method:'PATCH',headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d.slice(0,500)));
});
req.end(body);
"
```
The exact field path for `baseUrl` inside a PATCH body is not confirmed
against this specific endpoint's real schema — this project's own history
shows Omniroute's request-body schemas differ from what a first
reasonable guess assumes more than once (e.g. the `modelAccessMode`
follow-up PATCH needed for key scoping, discovered empirically). If this
PATCH 400s or the field isn't accepted at the top level, try flattening it
(`{baseUrl: 'http://localhost:8318/v1'}` instead of nested under
`providerSpecificData`), and verify the real accepted shape via the error
message or a follow-up `GET`, exactly as done throughout this whole
project. Do not proceed until a follow-up `GET` (Step 2) confirms the
value actually changed — a `200` on the PATCH alone is not sufficient
proof, per this project's own established discipline (a prior PATCH in
this same system returned `200` while silently dropping the field it
claimed to set).

- [ ] **Step 2: Verify the change actually took effect**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/providers',method:'GET',headers:{Authorization:'Bearer '+tok}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>{
    const j=JSON.parse(d);
    const c=j.connections.find(c=>c.id==='3e29f7a8-5c0c-4914-ba78-9c4bf6d38d06');
    console.log(JSON.stringify(c.providerSpecificData));
  });
});
req.end();
"
```
Expected: `baseUrl` shows `http://localhost:8318/v1`, not the old
`:8317/v1`. If it still shows the old value, the PATCH did not really take
effect regardless of what status code it returned — retry with an
adjusted body shape per Step 1's guidance before continuing.

- [ ] **Step 3: Validate the full chain through Omniroute**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const body=JSON.stringify({model:'cliproxyapi/gpt-5.6-luna',messages:[{role:'user',content:'reply with just: ok'}],max_tokens:16});
const req=http.request({host:'127.0.0.1',port:20129,path:'/v1/chat/completions',method:'POST',headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d.slice(0,500)));
});
req.end(body);
"
```
Expected: `200` with a real Chat-Completions response — the exact same
request that failed with "missing input" at the start of this whole
investigation now succeeds, proving the shim is correctly in the loop.

---

### Task 4: Restore a working leg in `openviking-vlm`, verify, document

**Files:**
- Modify: `kubernetes/apps/ai/CLAUDE.md` (the `openviking-vlm` combo
  capacity-gap paragraph in the `openviking` bullet, and the "Known
  Omniroute limitations" section if the `/v1/messages`/`blockedModels`
  entries need a cross-reference added — read the current file first,
  don't guess at line numbers, it changes structure often in this
  project)

**Interfaces:**
- Consumes: the shim (Tasks 1-2) and repointed provider-node (Task 3).
- Produces: nothing consumed by later tasks (last task in this plan).

- [ ] **Step 1: Add a working remote leg to the `openviking-vlm` combo**

The combo id is `52b84d63-d6d8-43a9-b9c4-8fe90146535a`. It currently has
one leg, `llamaswapapu/vlm`. Add `cliproxyapi/gpt-5.6-luna` (or whichever
model Task 3's testing showed responds fastest/most reliably — no strong
reason from this project's investigation to prefer one over another,
decide empirically here) as the first, higher-priority leg, keeping
`llamaswapapu/vlm` as the fallback:

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const body=JSON.stringify({
  models:[
    {model:'cliproxyapi/gpt-5.6-luna',providerId:'cliproxyapi',weight:0},
    {model:'llamaswapapu/vlm',providerId:'llamaswapapu',weight:0}
  ]
});
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/combos/52b84d63-d6d8-43a9-b9c4-8fe90146535a',method:'PATCH',headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d.slice(0,500)));
});
req.end(body);
"
```
(`PATCH` on `/api/combos/<id>` is the confirmed-working method from the
prior Anthropic-lane project's Task 3 — reuse it, no need to re-discover.)

- [ ] **Step 2: Verify the combo state with a fresh GET**

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
Expected: `["cliproxyapi/gpt-5.6-luna","llamaswapapu/vlm"]`.

- [ ] **Step 3: Trigger a real OpenViking memory-extraction and confirm it uses the new leg**

Trigger a real session-commit / memory-extraction cycle (via OpenViking's
normal usage — whatever this environment's regular interaction pattern
is), then check logs for success with no `bad_gateway`/`504` aggregate
failure:
```bash
kubectl logs -n ai deploy/openviking --since=10m | grep -i "memory extraction\|Phase 2 step long_term\|bad_gateway\|504"
```
Expected: a successful extraction log line, or at most a clean single-leg
failure with fallback to `llamaswapapu/vlm` (not both legs failing).
Cross-check which leg actually served the request via Omniroute's own
on-disk call-log file (same method proven out in the prior Anthropic-lane
project's Task 6):
```bash
kubectl exec -n ai deploy/omniroute -c app -- sh -c "find /app/data/call_logs -name '*.json' -newermt '-10 minutes' -exec grep -l 'openviking-vlm' {} \;" | tail -1
```
Read whichever file this prints (via a normal file read, not by pasting
its full contents into a report) and confirm its `comboStepId`/`model`
field shows `cliproxyapi/gpt-5.6-luna` was actually used for at least one
real request, not just that the combo lists it.

- [ ] **Step 4: Regression-check other combos referencing `gpt-*` models**

`coding-deep` (`cliproxyapi/claude-sonnet-5` → `cliproxyapi/gpt-5.5` →
`llamaswap/coder-large`) and `advanced` (`cliproxyapi/claude-opus-4-8` →
`cliproxyapi/gpt-5.6-terra`) both reference other `cliproxyapi/gpt-*`
models as fallback legs. These are used by HolyClaude's
`holyclaude-interactive` key. Confirm the shim didn't break anything for
them (dry-run test, not a live interactive session):
```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const body=JSON.stringify({model:'cliproxyapi/gpt-5.5',messages:[{role:'user',content:'reply with just: ok'}],max_tokens:16});
const req=http.request({host:'127.0.0.1',port:20129,path:'/v1/chat/completions',method:'POST',headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log('gpt-5.5:', r.statusCode, d.slice(0,200)));
});
req.end(body);
"
```
Repeat with `gpt-5.6-terra` in place of `gpt-5.5`. Expected: both `200`
with real content — the shim fixes every `cliproxyapi/gpt-*` model
uniformly, not just the one added to `openviking-vlm`.

- [ ] **Step 5: Update documentation**

Read `kubernetes/apps/ai/CLAUDE.md`'s current `openviking` bullet in full
first (it changes structure often in this project — don't assume line
numbers from an earlier session). Find the paragraph describing
`openviking-vlm`'s capacity gap (currently states the combo is reduced to
a single local-only leg with no remote fallback, and that memory-
extraction prompts have no fallback beyond the local ctx-size ceiling).
Update it to describe the current, real state:
- The shim exists (`kubernetes/apps/ai/omniroute/app/configmap-shim.yaml`,
  a `shim` sidecar container in the `omniroute` pod) and translates
  Chat-Completions to Responses API for every `cliproxyapi/gpt-*` model.
- `openviking-vlm` is now `cliproxyapi/gpt-5.6-luna` (or whichever model
  Step 1 actually used) → `llamaswapapu/vlm`, restoring real remote
  fallback coverage for prompts beyond the local model's ~18,480-token
  practical ceiling (still true and unchanged — cite it, don't restate the
  math, it's already correct elsewhere in this file).
- Reference `docs/superpowers/specs/2026-09-17-cliproxyapi-responses-shim-design.md`
  for the full investigation and design.

Commit:
```bash
git add kubernetes/apps/ai/CLAUDE.md
git commit -m "docs(ai): document cliproxyapi shim, restored openviking-vlm remote leg"
git pull --rebase origin main
git push
```

---

## Self-Review Notes

- **Spec coverage:** architecture (sidecar shim, provider-node repoint) →
  Tasks 1 and 3; request/response translation (text-only, no streaming) →
  Task 2; testing/verification (direct shim test, full-chain test,
  combo-leg restoration, image-rejection test, regression check) → Tasks
  2-4; documentation → Task 4 Step 5. All spec sections have a
  corresponding task.
- **Ordering enforced structurally:** Task 2 depends on Task 1's mounted
  secret and running container; Task 3 depends on Task 2's shim actually
  working (validated directly before touching Omniroute's routing); Task
  4 depends on Task 3's repoint being live and verified via a real GET,
  not just a 200 status code.
- **Known follow-up, not a gap:** the exact `api-keys` YAML shape and the
  exact Responses API response field names are both explicitly flagged as
  "verify live, adjust if different" rather than hardcoded on faith — this
  project's own history (Omniroute's `modelAccessMode` PATCH quirk, the
  `/v1/responses` red herring itself) shows real API behavior has
  diverged from first-reasonable-guesses more than once. Task 2's Steps
  1-2 exist specifically to close that gap with real evidence before
  Step 3's code is treated as final.
