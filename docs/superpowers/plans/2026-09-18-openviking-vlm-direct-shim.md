# OpenViking vlm Direct-to-Shim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give OpenViking's `vlm` leg a working remote model again by bypassing
Omniroute entirely — repoint it at the existing `shim` sidecar (in the
`omniroute` pod) directly via a new Service, add incoming auth to the shim
(it's never been reachable outside its pod before), and add shim-side
fallback to the local `llamaswapapu/vlm` model (including for image content,
which the shim previously just rejected) so the old two-leg combo behavior
is preserved without Omniroute's combo mechanism.

**Architecture:** The shim (already built and working, from the prior
2026-09-17 plan) gains a real Kubernetes Service, a shared-secret auth
check, and fallback-on-failure/fallback-on-image-content logic that calls
`llama-swap-apu`'s native Chat-Completions endpoint directly (no
translation needed for that leg). OpenViking's `vlm` config points straight
at the shim's new Service instead of Omniroute. Omniroute's own
`cliproxyapi` provider-node `baseUrl` is reverted back to CLIProxyAPI
directly, since nothing routes through Omniroute→shim anymore.

**Tech Stack:** Node.js (`node:22-alpine`, built-in `http` module only —
unchanged from the existing shim), bjw-s app-template Service/env wiring,
SOPS, Omniroute's management API, Flux/Kustomize.

**Spec:** `docs/superpowers/specs/2026-09-18-openviking-vlm-direct-shim-design.md`
(read this first — this plan implements it in full). Also read
`docs/superpowers/specs/2026-09-17-cliproxyapi-responses-shim-design.md`
for the shim's existing translation core, which this plan extends but does
not replace.

## Global Constraints

- **Never print a decrypted secret or API key value anywhere** — not to
  stdout, not into a report, not into a commit, not into any command's
  visible output. This applies to the new `SHIM_SHARED_SECRET` value
  exactly as much as to every existing secret in this project. When
  generating and setting the shared secret (Task 1), do it inside a single
  shell script where the value only ever exists in a shell variable /
  temp file, never as literal text in a command you write or a tool
  output you see. Existence checks use `grep -c` (a count) against key
  *names*, never a value-printing grep.
- **Both `SHIM_SHARED_SECRET` (in `kubernetes/apps/ai/omniroute/app/secret.sops.yaml`)
  and `OPENVIKING_VLM_API_KEY` (in `kubernetes/apps/ai/openviking/app/secret.sops.yaml`)
  must hold the identical string value.** This is a shared secret between
  two apps, not a pair of independently-rotatable credentials.
- **No streaming.** Buffered request/response only — unchanged from the
  2026-09-17 spec.
- The shim's Service (added in Task 1) is the *first* time the shim
  becomes reachable outside the `omniroute` pod — CLIProxyAPI's own port
  (8317) remains bound to `127.0.0.1` only and is NOT exposed by this
  plan; do not add a Service for it. The shim's own auth check (Task 2)
  is what makes exposing its Service safe.
- `kustomize build kubernetes/apps/ai/omniroute/app | kubectl apply
  --dry-run=client -f -` and `kustomize build kubernetes/apps/ai/openviking/app
  | kubectl apply --dry-run=client -f -` before every commit touching
  either app's manifests.
- `task sops:verify` before every commit touching a `*.sops.yaml` file.
- Working directory: wherever you're actually running from; commit and
  push directly to `origin/main` (this repo's established single-operator
  workflow — no feature branch).

---

### Task 1: Shim Service, shared secret, and fallback env config

**Files:**
- Modify: `kubernetes/apps/ai/omniroute/app/secret.sops.yaml` (add
  `SHIM_SHARED_SECRET`)
- Modify: `kubernetes/apps/ai/openviking/app/secret.sops.yaml` (set
  `OPENVIKING_VLM_API_KEY` to the same value)
- Modify: `kubernetes/apps/ai/omniroute/app/helmrelease.yaml` (add `shim`
  container env vars, add `service.shim` entry, rewrite the now-stale
  `shim` container comment block)

**Interfaces:**
- Consumes: nothing from earlier tasks (first task in this plan; builds on
  the already-deployed shim from the 2026-09-17 plan).
- Produces: a reachable `omniroute-shim.ai.svc.cluster.local:8318` Service,
  a `SHIM_SHARED_SECRET` env var in the `shim` container (value not yet
  checked by any code — Task 2 adds that), `FALLBACK_BASE_URL`/
  `FALLBACK_MODEL` env vars in the `shim` container (not yet read by any
  code — Task 2 adds that too), and `OPENVIKING_VLM_API_KEY` set to the
  matching shared value (not yet consumed anywhere new — Task 3 repoints
  OpenViking to actually use it against the new Service).

- [ ] **Step 1: Generate and set the shared secret in both SOPS files**

Run this as a single script so the generated value never appears as literal
text in any command or output you produce:

```bash
cd /volume1/git/j0sh3rs/home-ops
SECRET_FILE=$(mktemp)
openssl rand -hex 32 > "$SECRET_FILE"
chmod 600 "$SECRET_FILE"
SECRET=$(cat "$SECRET_FILE")
sops --set "[\"stringData\"][\"SHIM_SHARED_SECRET\"] \"$SECRET\"" kubernetes/apps/ai/omniroute/app/secret.sops.yaml
sops --set "[\"stringData\"][\"OPENVIKING_VLM_API_KEY\"] \"$SECRET\"" kubernetes/apps/ai/openviking/app/secret.sops.yaml
unset SECRET
rm -f "$SECRET_FILE"
```

If `sops --set`'s path syntax errors, run `sops --help` to confirm the
exact accepted form for this pinned `sops` version and adjust — the path
addresses the document's structure top-down (`stringData` is the top-level
key both these Secrets nest their fields under, confirmed by reading both
files' current structure).

- [ ] **Step 2: Verify both SOPS files without printing values**

```bash
cd /volume1/git/j0sh3rs/home-ops
task sops:verify
sops -d kubernetes/apps/ai/omniroute/app/secret.sops.yaml | grep -c '^  SHIM_SHARED_SECRET:'
sops -d kubernetes/apps/ai/openviking/app/secret.sops.yaml | grep -c '^  OPENVIKING_VLM_API_KEY:'
```
Expected: `task sops:verify` reports all files properly encrypted; both
`grep -c` commands print `1` (key present), never the value itself.

- [ ] **Step 3: Add env vars and rewrite the shim container comment**

In `kubernetes/apps/ai/omniroute/app/helmrelease.yaml`, the `shim:`
container currently (lines 185-244) has this comment block (lines 186-212)
and no `env:` key. Replace the comment block (it's now partially stale —
it said "do not add a Service port for 8318 either", which this task
does) and add `env:`:

```yaml
          shim:
            # Chat-Completions -> Responses API translation shim for
            # CLIProxyAPI, added 2026-09-17 (see
            # docs/superpowers/specs/2026-09-17-cliproxyapi-responses-shim-design.md).
            # CLIProxyAPI (the cliproxyapi container above) never
            # implemented a Chat Completions endpoint -- confirmed via
            # direct request, GET /v1/chat/completions there returns 404;
            # only /v1/responses exists. This container translates the
            # shape so CLIProxyAPI's gpt-* models work over plain
            # Chat-Completions.
            #
            # As of 2026-09-18 (see
            # docs/superpowers/specs/2026-09-18-openviking-vlm-direct-shim-design.md),
            # this container is reached DIRECTLY by OpenViking via the new
            # `shim` Service below (not through Omniroute's own routing --
            # Omniroute's cliproxyapi provider-node baseUrl was reverted
            # back to CLIProxyAPI directly after a bug was found in
            # Omniroute's own request-construction pipeline that silently
            # dropped the `messages` field once its baseUrl pointed
            # anywhere but CLIProxyAPI itself; root cause lives in
            # Omniroute's closed bundled source, not fixable from this
            # repo). CLIProxyAPI's own port (8317) still binds to
            # 127.0.0.1 only and is NOT exposed by the new Service --
            # only this container's own translated+auth-gated endpoint is.
            # SHIM_SHARED_SECRET gates every route except /healthz (see
            # configmap-shim.yaml) since this is now reachable
            # cluster-wide, not just pod-locally. FALLBACK_BASE_URL/
            # FALLBACK_MODEL point at llama-swap-apu's real vlm model,
            # used when CLIProxyAPI fails or the request contains
            # non-text content this shim doesn't translate for CLIProxyAPI.
            image:
              repository: docker.io/library/node
              # renovate: datasource=docker depName=node versioning=node
              tag: 22-alpine
              pullPolicy: IfNotPresent
            command: ["node", "/shim/server.js"]
            env:
              FALLBACK_BASE_URL: "http://llama-swap-apu.ai.svc.cluster.local:8080/v1"
              FALLBACK_MODEL: "vlm"
              SHIM_SHARED_SECRET:
                valueFrom:
                  secretKeyRef:
                    name: omniroute-secrets
                    key: SHIM_SHARED_SECRET
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

- [ ] **Step 4: Add the `shim` Service entry**

In the same file, the `service:` block (currently lines 246-261) has
`app:` and `cliproxyapi:` entries. Add a `shim:` entry after
`cliproxyapi:`, following the exact same pattern (no `forceRename`):

```yaml
    service:
      app:
        forceRename: *app
        controller: *app
        ports:
          http:
            port: 20128
          api:
            port: 20129
          livews:
            port: 20132
      cliproxyapi:
        controller: *app
        ports:
          http:
            port: 8317
      shim:
        controller: *app
        ports:
          http:
            port: 8318
```

- [ ] **Step 5: Validate**

```bash
cd /volume1/git/j0sh3rs/home-ops
kustomize build kubernetes/apps/ai/omniroute/app | kubectl apply --dry-run=client -f -
```
Expected: clean render (the usual benign `last-applied-configuration`
warnings are fine).

- [ ] **Step 6: Commit, push, deploy**

```bash
cd /volume1/git/j0sh3rs/home-ops
git add kubernetes/apps/ai/omniroute/app/secret.sops.yaml kubernetes/apps/ai/openviking/app/secret.sops.yaml kubernetes/apps/ai/omniroute/app/helmrelease.yaml
git commit -m "feat(ai): expose shim via Service, add shared-secret auth and local-fallback config"
git pull --rebase origin main
git push
flux reconcile kustomization omniroute -n ai --with-source
```

- [ ] **Step 7: Verify live**

```bash
kubectl get pods -n ai -l app.kubernetes.io/name=omniroute
kubectl get svc -n ai | grep -i shim
```
Expected: pod `3/3` ready (unchanged container count — no new container,
just new env/Service on the existing `shim` container); a Service exists
whose name contains `shim`, port `8318`. Note the exact Service name
printed here for Task 3.

```bash
kubectl exec -n ai deploy/omniroute -c shim -- printenv | grep -c '^SHIM_SHARED_SECRET='
kubectl exec -n ai deploy/omniroute -c shim -- printenv | grep '^FALLBACK_'
```
Expected: first command prints `1` (secret env var present, value never
shown); second command prints the two plain (non-secret) fallback env
vars with their real values (`FALLBACK_BASE_URL=http://llama-swap-apu...`,
`FALLBACK_MODEL=vlm`) — these are not secrets, safe to print.

---

### Task 2: Shim auth, fallback, and image-routing logic

**Files:**
- Modify: `kubernetes/apps/ai/omniroute/app/configmap-shim.yaml` (replace
  `data.server.js` with the version below)

**Interfaces:**
- Consumes: `SHIM_SHARED_SECRET`, `FALLBACK_BASE_URL`, `FALLBACK_MODEL` env
  vars from Task 1.
- Produces: a shim that requires `Authorization: Bearer <SHIM_SHARED_SECRET>`
  on every route except `/healthz`, routes non-text content and
  CLIProxyAPI failures to the local fallback model, and otherwise behaves
  exactly as the existing (2026-09-17 plan) translation logic — Task 3
  points OpenViking at this exact behavior.

- [ ] **Step 1: Replace `server.js`**

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
const REQUEST_TIMEOUT_MS = 60000;

function requireEnv(name) {
  const v = process.env[name];
  if (!v) throw new Error('missing required env var ' + name);
  return v;
}

const SHIM_SHARED_SECRET = requireEnv('SHIM_SHARED_SECRET');
const FALLBACK_BASE_URL = requireEnv('FALLBACK_BASE_URL');
const FALLBACK_MODEL = requireEnv('FALLBACK_MODEL');

// Parses CLIProxyAPI's own api-keys list out of its mounted config file.
// Shape confirmed live (2026-09-17 plan, Task 2 Step 1): a plain YAML list
// of quoted strings under `api-keys:`, e.g.:
//   api-keys:
//     - "sk-..."
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

function checkAuth(req) {
  const header = req.headers['authorization'] || '';
  return header === 'Bearer ' + SHIM_SHARED_SECRET;
}

// True if any message has a non-text content part (e.g. image_url). These
// route straight to the local fallback (already vision-capable) instead of
// being translated for CLIProxyAPI -- see
// docs/superpowers/specs/2026-09-18-openviking-vlm-direct-shim-design.md.
function hasNonTextContent(messages) {
  for (const m of messages) {
    if (Array.isArray(m.content)) {
      for (const part of m.content) {
        if (part.type !== 'text') return true;
      }
    }
  }
  return false;
}

// Text-only -- callers must route non-text content to the fallback via
// hasNonTextContent() BEFORE calling this. The throw below is
// defense-in-depth only (should be unreachable in normal operation); if it
// ever fires, the caller's catch block routes to the fallback anyway.
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
          throw new ShimError(400, `Unsupported content type "${part.type}" reached chatToResponsesInput -- this should have been routed to the fallback by hasNonTextContent() first.`);
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
        timeout: REQUEST_TIMEOUT_MS,
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
    req.on('timeout', () => req.destroy(new Error('CLIProxyAPI request timed out after ' + REQUEST_TIMEOUT_MS + 'ms')));
    req.on('error', reject);
    req.end(payload);
  });
}

// Forwards the ORIGINAL (untranslated) Chat-Completions body to
// llama-swap-apu's real vlm model, only overriding `model`. No translation
// needed either direction -- llama-swap already speaks Chat-Completions
// natively, images included.
function callFallback(originalBody) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(Object.assign({}, originalBody, { model: FALLBACK_MODEL }));
    const url = new URL(FALLBACK_BASE_URL + '/chat/completions');
    const req = http.request(
      {
        host: url.hostname,
        port: url.port || 80,
        path: url.pathname,
        method: 'POST',
        timeout: REQUEST_TIMEOUT_MS,
        headers: {
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
    req.on('timeout', () => req.destroy(new Error('fallback request timed out after ' + REQUEST_TIMEOUT_MS + 'ms')));
    req.on('error', reject);
    req.end(payload);
  });
}

// Field extraction CONFIRMED against a real CLIProxyAPI /v1/responses
// response (2026-09-17 plan, Task 2 Step 2). Real shape observed:
//   output: [{ type: "message", role: "assistant", content: [
//     { type: "output_text", text: "..." }
//   ]}]
//   usage: { input_tokens, output_tokens, total_tokens, ... }
function responsesToChatCompletion(model, responsesBody) {
  const parsed = JSON.parse(responsesBody);
  let text = '';
  // foundShape tracks whether a recognized output field was present at all
  // (an output_text string, or an output[] item shaped like
  // {type:"message", content:[...]}) -- NOT whether any text ended up
  // extracted. A model legitimately replying with empty text is a normal
  // 200; a response with no recognizable output field at all is an
  // unexpected upstream shape and must fail loudly (caught by the caller,
  // which routes to the fallback) instead of silently returning empty
  // content.
  let foundShape = false;
  if (typeof parsed.output_text === 'string') {
    text = parsed.output_text;
    foundShape = true;
  } else if (Array.isArray(parsed.output)) {
    for (const item of parsed.output) {
      if (item.type === 'message' && Array.isArray(item.content)) {
        foundShape = true;
        for (const c of item.content) {
          if (typeof c.text === 'string') text += c.text;
        }
      }
    }
  }
  if (!foundShape) {
    throw new ShimError(
      502,
      'unexpected /v1/responses shape: no extractable output (no output_text string and no output[] item shaped {type:"message", content:[...]})'
    );
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

  if (!checkAuth(req)) {
    sendError(res, 401, 'unauthorized');
    return;
  }

  if (req.method !== 'POST' || req.url !== '/v1/chat/completions') {
    sendError(res, 404, 'not found');
    return;
  }

  let parsed;
  try {
    const raw = await readBody(req);
    parsed = JSON.parse(raw);
  } catch (err) {
    sendError(res, 400, 'invalid request body: ' + err.message);
    return;
  }

  const messages = parsed.messages || [];

  if (hasNonTextContent(messages)) {
    try {
      const fb = await callFallback(parsed);
      res.writeHead(fb.status, { 'content-type': 'application/json' });
      res.end(fb.body);
    } catch (err) {
      sendError(res, 502, 'local fallback request failed: ' + err.message);
    }
    return;
  }

  let primaryErrMessage = null;
  try {
    const input = chatToResponsesInput(messages);
    const responsesBody = { model: parsed.model, input };
    if (parsed.max_tokens) responsesBody.max_output_tokens = parsed.max_tokens;
    if (parsed.temperature !== undefined) responsesBody.temperature = parsed.temperature;

    const upstream = await callCliProxy('/v1/responses', responsesBody);
    if (upstream.status < 200 || upstream.status >= 300) {
      throw new ShimError(upstream.status, 'CLIProxyAPI request failed');
    }
    const chatBody = responsesToChatCompletion(parsed.model, upstream.body);
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify(chatBody));
    return;
  } catch (err) {
    primaryErrMessage = err.message;
  }

  // CLIProxyAPI leg failed (non-2xx, network error, timeout, or unexpected
  // response shape) -- fall back to the local model, mirroring the old
  // openviking-vlm combo's two-leg behavior. See
  // docs/superpowers/specs/2026-09-18-openviking-vlm-direct-shim-design.md.
  try {
    const fb = await callFallback(parsed);
    res.writeHead(fb.status, { 'content-type': 'application/json' });
    res.end(fb.body);
  } catch (fallbackErr) {
    sendError(res, 502, 'both CLIProxyAPI and local fallback failed: ' + primaryErrMessage + ' / ' + fallbackErr.message);
  }
});

server.listen(PORT, '0.0.0.0', () => console.log('shim listening on', PORT));
```

- [ ] **Step 2: Validate and deploy**

```bash
cd /volume1/git/j0sh3rs/home-ops
kustomize build kubernetes/apps/ai/omniroute/app | kubectl apply --dry-run=client -f -
git add kubernetes/apps/ai/omniroute/app/configmap-shim.yaml
git commit -m "feat(ai): add shim auth, local-fallback, and image-routing logic"
git pull --rebase origin main
git push
flux reconcile kustomization omniroute -n ai --with-source
```

- [ ] **Step 3: Verify auth**

Read the real secret value server-side only, inside the exec script, never
printed:
```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const req=http.request({host:'127.0.0.1',port:8318,path:'/v1/chat/completions',method:'POST',headers:{'content-type':'application/json'}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log('no-auth:', r.statusCode, d.slice(0,200)));
});
req.end(JSON.stringify({model:'gpt-5.6-luna',messages:[{role:'user',content:'ok'}]}));
"
```
Expected: `401` (no `Authorization` header sent at all).

```bash
kubectl exec -n ai deploy/omniroute -c shim -- node -e "
const http=require('http');
const fs=require('fs');
const req2=process.env;
const secret=req2.SHIM_SHARED_SECRET;
const body=JSON.stringify({model:'gpt-5.6-luna',messages:[{role:'user',content:'reply with just: ok'}],max_tokens:16});
const req=http.request({host:'127.0.0.1',port:8318,path:'/v1/chat/completions',method:'POST',headers:{Authorization:'Bearer '+secret,'content-type':'application/json','content-length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log('with-auth:', r.statusCode, d.slice(0,300)));
});
req.end(body);
"
```
Expected: `200` with a real translated response (`choices[0].message.content`
containing real text) — the secret is read from the container's own env by
the script itself, never printed to stdout.

- [ ] **Step 4: Verify fallback-on-failure**

Send a request with a model id CLIProxyAPI will reject (a clean,
non-destructive way to trigger a real primary-leg failure without touching
any live config):
```bash
kubectl exec -n ai deploy/omniroute -c shim -- node -e "
const http=require('http');
const secret=process.env.SHIM_SHARED_SECRET;
const body=JSON.stringify({model:'definitely-not-a-real-model-xyz',messages:[{role:'user',content:'reply with just: ok'}],max_tokens:16});
const req=http.request({host:'127.0.0.1',port:8318,path:'/v1/chat/completions',method:'POST',headers:{Authorization:'Bearer '+secret,'content-type':'application/json','content-length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d.slice(0,400)));
});
req.end(body);
"
```
Expected: `200` with a real response — but note its `id` field format and
`model`/content are now llama-swap-apu's own (not CLIProxyAPI's translated
shape), confirming this response came from the FALLBACK leg, not
CLIProxyAPI (which would have rejected the bogus model id).

- [ ] **Step 5: Verify image content routes to fallback**

```bash
kubectl exec -n ai deploy/omniroute -c shim -- node -e "
const http=require('http');
const secret=process.env.SHIM_SHARED_SECRET;
const tinyPngDataUri='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';
const body=JSON.stringify({model:'gpt-5.6-luna',messages:[{role:'user',content:[{type:'text',text:'what color is this 1x1 pixel? reply in one word'},{type:'image_url',image_url:{url:tinyPngDataUri}}]}],max_tokens:16});
const req=http.request({host:'127.0.0.1',port:8318,path:'/v1/chat/completions',method:'POST',headers:{Authorization:'Bearer '+secret,'content-type':'application/json','content-length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d.slice(0,400)));
});
req.end(body);
"
```
Expected: `200` with a real response from llama-swap-apu's vision model —
confirms non-text content routes straight to the fallback (never attempted
against CLIProxyAPI, which this shim never translates images for).

---

### Task 3: Repoint OpenViking's vlm config at the shim directly

**Files:**
- Modify: `kubernetes/apps/ai/openviking/app/helmrelease.yaml` (the `vlm:`
  block and its preceding comment)

**Interfaces:**
- Consumes: the shim's new Service (Task 1) and auth+fallback logic
  (Task 2); `OPENVIKING_VLM_API_KEY`'s value already matches
  `SHIM_SHARED_SECRET` (Task 1 Step 1).
- Produces: OpenViking's vlm calls flowing through the new direct path —
  Task 4 depends on this being live before the baseUrl revert (so there's
  no window where neither path works).

- [ ] **Step 1: Update the `vlm:` block**

Read `kubernetes/apps/ai/openviking/app/helmrelease.yaml`'s current `vlm:`
block and its preceding comment in full first — this file changes
structure often in this project. As of this plan's writing, the `vlm:`
block reads:
```yaml
      vlm:
        api_base: "http://omniroute.ai.svc.cluster.local:20128/v1"
        api_key: "${OPENVIKING_VLM_API_KEY}"
        provider: "openai"
        model: "openviking-vlm"
        temperature: 0.0
        timeout: 120
        max_retries: 0
        thinking: false
        max_concurrent: 20
```
Change `api_base` and `model` (everything else — `provider`, `temperature`,
`timeout`, `max_retries`, `thinking`, `max_concurrent` — stays exactly as
today; those values were tuned for real observed latency/timeout behavior
unrelated to which backend serves the request):
```yaml
      vlm:
        api_base: "http://omniroute-shim.ai.svc.cluster.local:8318/v1"
        api_key: "${OPENVIKING_VLM_API_KEY}"
        provider: "openai"
        model: "gpt-5.6-luna"
        temperature: 0.0
        timeout: 120
        max_retries: 0
        thinking: false
        max_concurrent: 20
```
Use the exact Service name confirmed live in Task 1 Step 7 if it differs
from `omniroute-shim` — don't assume without checking.

Also update the comment block immediately above this (currently describing
the Omniroute-combo routing, the 3→1-leg capacity-gap history, and the
Claude-leg removal) to reflect the new reality — replace it with:
```yaml
      # vlm: bypasses Omniroute entirely as of 2026-09-18 (see
      # docs/superpowers/specs/2026-09-18-openviking-vlm-direct-shim-design.md)
      # -- talks directly to the omniroute pod's `shim` sidecar via its own
      # Service, which translates to CLIProxyAPI's Responses API shape and
      # falls back to llama-swap-apu's real vlm model (qwen2-vl-2b) on
      # CLIProxyAPI failure or non-text content. api_key is the shared
      # secret the shim itself checks (SHIM_SHARED_SECRET in
      # kubernetes/apps/ai/omniroute/app/secret.sops.yaml -- both files
      # must hold the identical value), not an Omniroute inference key.
      # model is a bare CLIProxyAPI model id (no cliproxyapi/ prefix or
      # combo indirection -- that was Omniroute-specific addressing that
      # no longer applies once the shim is reached directly). This
      # replaces the prior Omniroute-combo-based routing after Omniroute's
      # own request-construction pipeline was found to silently drop the
      # messages field once its cliproxyapi provider-node baseUrl pointed
      # anywhere but CLIProxyAPI directly -- root cause lives in
      # Omniroute's own closed bundled source, not fixable from this repo.
```

- [ ] **Step 2: Validate**

```bash
cd /volume1/git/j0sh3rs/home-ops
kustomize build kubernetes/apps/ai/openviking/app | kubectl apply --dry-run=client -f -
```
Expected: clean render.

- [ ] **Step 3: Commit, push, deploy**

```bash
cd /volume1/git/j0sh3rs/home-ops
git add kubernetes/apps/ai/openviking/app/helmrelease.yaml
git commit -m "feat(ai): repoint openviking vlm at the shim directly, bypassing omniroute"
git pull --rebase origin main
git push
flux reconcile kustomization openviking -n ai --with-source
```

- [ ] **Step 4: Verify live**

```bash
kubectl get pods -n ai -l app.kubernetes.io/name=openviking
```
Expected: pod healthy/ready (readiness probe depends on a live embedding
call succeeding, unaffected by this change — `embedding.dense` still routes
through Omniroute unchanged).

Trigger a real OpenViking memory-extraction/session-commit cycle via this
environment's normal usage pattern, then check the shim's own logs for the
request landing (not Omniroute's call-log — Omniroute is no longer in this
path):
```bash
kubectl logs -n ai deploy/omniroute -c shim --since=10m
```
Expected: no crash/error logs during the window of the real request (the
shim's current logging is just its own startup line plus whatever Node
prints on an uncaught exception — the absence of the latter is the signal
here). Cross-check success from OpenViking's own side:
```bash
kubectl logs -n ai deploy/openviking --since=10m | grep -i "memory extraction\|Phase 2 step long_term\|bad_gateway\|504"
```
Expected: a successful extraction log line, or at most a clean single-leg
failure with fallback (not a total failure) — matching the same
verification bar the 2026-09-17 plan used.

---

### Task 4: Revert Omniroute's baseUrl, delete the unused combo, regression-check HolyClaude

**Files:** none in git — live Omniroute management-API mutations, same as
several tasks in the prior 2026-09-17 plan.

**Interfaces:**
- Consumes: Task 3 being live and verified (so there's no window where
  neither the old nor new path works for OpenViking).
- Produces: nothing consumed by later tasks (last functional task in this
  plan; Task 5 is documentation only).

- [ ] **Step 1: Revert the `cliproxyapi` provider-node's `baseUrl`**

The connection id is `3e29f7a8-5c0c-4914-ba78-9c4bf6d38d06` (confirmed live
in the prior plan). Its current `baseUrl` is `http://localhost:8318/v1`
(the shim, from the prior plan's Task 3); revert to
`http://localhost:8317/v1` (CLIProxyAPI directly):
```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const body=JSON.stringify({providerSpecificData:{baseUrl:'http://localhost:8317/v1'}});
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/providers/3e29f7a8-5c0c-4914-ba78-9c4bf6d38d06',method:'PATCH',headers:{Authorization:'Bearer '+tok,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d.slice(0,500)));
});
req.end(body);
"
```
The nested `providerSpecificData` shape is confirmed working (the prior
plan's Task 3 used it successfully on first try) — no need to try the
flattened fallback.

- [ ] **Step 2: Verify the revert took effect via a fresh GET**

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
Expected: `baseUrl` shows `http://localhost:8317/v1`, not `:8318/v1`. A
`200` on the PATCH alone is not sufficient proof — this GET is required
before proceeding.

- [ ] **Step 3: Delete the unused `openviking-vlm` combo**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/combos/52b84d63-d6d8-43a9-b9c4-8fe90146535a',method:'DELETE',headers:{Authorization:'Bearer '+tok}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>console.log(r.statusCode, d.slice(0,300)));
});
req.end();
"
```
If `DELETE` isn't the accepted method or 400s, check the response body for
the real accepted shape/method and adjust, matching this whole project's
established discipline of verifying against real API responses.

- [ ] **Step 4: Verify the combo is gone via a fresh GET**

```bash
kubectl exec -n ai deploy/omniroute -c app -- node -e "
const http=require('http');
const tok=process.env.OMNIROUTE_MGMT_TOKEN;
const req=http.request({host:'127.0.0.1',port:20128,path:'/api/combos',method:'GET',headers:{Authorization:'Bearer '+tok}},r=>{
  let d='';r.on('data',c=>d+=c);r.on('end',()=>{
    const j=JSON.parse(d);
    const found=j.combos.find(c=>c.name==='openviking-vlm');
    console.log(found?'STILL PRESENT':'confirmed deleted');
  });
});
req.end();
"
```
Expected: `confirmed deleted`.

- [ ] **Step 5: Regression-check HolyClaude's other cliproxyapi/gpt-* legs**

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
Repeat with `gpt-5.6-terra` in place of `gpt-5.5`. Expected: **the same
Responses-API-shape-mismatch error already documented** in
`kubernetes/apps/ai/CLAUDE.md`'s holyclaude bullet (best-effort/fail-closed,
not a new failure mode) — this confirms the `baseUrl` revert restored the
prior status quo for these legs rather than introducing anything worse.

---

### Task 5: Update documentation

**Files:**
- Modify: `kubernetes/apps/ai/CLAUDE.md` (top-of-file overview paragraph,
  and the `openviking` bullet's `openviking-vlm` capacity-gap paragraph)

**Interfaces:**
- Consumes: the completed, verified state from Tasks 1-4.
- Produces: nothing consumed by later tasks (last task in this plan).

- [ ] **Step 1: Update the top-of-file overview**

In `kubernetes/apps/ai/CLAUDE.md`, the overview paragraph (the file's first
paragraph, starting "Fully self-hosted AI stack...") currently contains
this exact sentence, with markdown bold markers around each app name —
match it verbatim, including the `**...**` markers, or the exact-string
edit will not find a match:
```
**argus** (observability/triage, bundles HolmesGPT), **openviking** (context/memory server, embedding + vlm), and **atuin-ai-server** all route through Omniroute (`http://omniroute.ai.svc.cluster.local:20128/v1`) instead, each with its own dedicated Omniroute inference key (`sk-...`), addressing models either by a named routing **combo** (multi-leg with fallback, e.g. `coding-fast`, `coding-deep`, `debugging`) or a bare `<provider>/<model>` reference (`llamaswap/coder-large`, `llamaswapapu/vlm`).
```
Read the current file first (structure may have shifted since this plan
was written) and replace that sentence with:
```
**argus** (observability/triage, bundles HolmesGPT) and **atuin-ai-server** route through Omniroute (`http://omniroute.ai.svc.cluster.local:20128/v1`), each with its own dedicated Omniroute inference key (`sk-...`), addressing models either by a named routing **combo** (multi-leg with fallback, e.g. `coding-fast`, `coding-deep`, `debugging`) or a bare `<provider>/<model>` reference (`llamaswap/coder-large`, `llamaswapapu/vlm`). **openviking** routes only its embedding leg through Omniroute the same way (`llamaswapapu/embedding`) — its vlm leg bypasses Omniroute entirely as of 2026-09-18, talking directly to a Service on the omniroute pod's own shim sidecar (see the openviking bullet below and `docs/superpowers/specs/2026-09-18-openviking-vlm-direct-shim-design.md`).
```

Separately, the `llama-swap-apu` bullet (further down, in its `coder-fim`
removal sentence) also currently says: `argus, openviking, and
atuin-ai-server all route through Omniroute instead, using its
\`<provider>/<model>\` addressing scheme (\`llamaswap/<model>\`,
\`llamaswapapu/<model>\`) rather than a mirrored alias list`. This remains
technically true for `argus`/`atuin-ai-server` and for openviking's
embedding leg, so it is not strictly wrong — but for precision, change
`argus, openviking, and atuin-ai-server all route through Omniroute
instead` to `argus, openviking's embedding leg, and atuin-ai-server all
route through Omniroute instead` in that same sentence (verify the exact
surrounding text via `grep -n "coder-fim.*FIM autocomplete" kubernetes/apps/ai/CLAUDE.md`
first, since this plan does not reproduce that whole sentence verbatim).

- [ ] **Step 2: Replace the `openviking-vlm` capacity-gap paragraph**

Read the current `openviking` bullet in full first — don't assume line
numbers or exact surrounding text from an earlier session; this file
changes structure often in this project. Find the sentence beginning
`**\`openviking-vlm\` combo — known capacity gap, not resolved.**` and
everything through the sentence ending `...or if \`llama-swap-apu\` gets
enough extra VRAM headroom to raise \`qwen2-vl-2b\`'s ctx-size further.`
(this whole span describes the now-superseded 3-leg → 1-leg history and the
capacity gap). Replace it with:
```
**`openviking-vlm` — now bypasses Omniroute entirely, direct to the shim (2026-09-18).** After the 2026-09-16 Anthropic-lane isolation work removed the Claude leg and left no working Chat-Completions-shaped `cliproxyapi/gpt-*` replacement (CLIProxyAPI is Responses-API-only by design — see `docs/superpowers/specs/2026-09-17-cliproxyapi-responses-shim-design.md`), a translation shim was built (a `shim` sidecar in the `omniroute` pod, `kubernetes/apps/ai/omniroute/app/configmap-shim.yaml`) to bridge that gap. Repointing Omniroute's own `cliproxyapi` provider-node at the shim worked when tested directly, but the full chain through Omniroute itself failed: Omniroute's own request-construction pipeline was found to silently drop the `messages` field once its `baseUrl` pointed anywhere but CLIProxyAPI directly — root cause lives in Omniroute's own closed bundled source (confirmed via a live `/v1/models`-probe hypothesis test that ruled that out as the direct cause; deeper root-causing would mean reverse-engineering Omniroute's own minified logic, not pursued further). Rather than continue chasing that, OpenViking's `vlm` leg now bypasses Omniroute entirely: `vlm.api_base` points directly at a new `omniroute-shim.ai.svc.cluster.local:8318` Service (see `docs/superpowers/specs/2026-09-18-openviking-vlm-direct-shim-design.md` for the full design), gated by a shared secret (`SHIM_SHARED_SECRET`, matched by `OPENVIKING_VLM_API_KEY`) since this is the shim's first exposure outside its own pod. `vlm.model` is `gpt-5.6-luna`, a bare CLIProxyAPI model id (no more Omniroute combo indirection). The shim itself now owns the old combo's two-leg fallback behavior: on CLIProxyAPI failure, or on any non-text (image) content — which this shim doesn't translate for CLIProxyAPI — it forwards the original request straight to `llama-swap-apu`'s real `vlm` model (`qwen2-vl-2b`, see the llama-swap-apu entry above) instead. Omniroute's `cliproxyapi` provider-node `baseUrl` was reverted back to CLIProxyAPI directly (`:8317/v1`) since nothing routes through Omniroute→shim anymore, and the now-unused `openviking-vlm` combo was deleted. This restores real remote-model coverage for prompts beyond the local model's practical ceiling (previously documented as ~18,480 tokens at 120s/154 tok/s, short of real observed prompts up to 45,309 tokens) without reintroducing the Anthropic-lane policy violation the 2026-09-16 work fixed — `gpt-5.6-luna` stays on the OpenAI/Codex lane, Claude Pro remains available as a model choice on the same shim mechanism if ever explicitly requested, not adopted here.
```

- [ ] **Step 3: Validate and commit**

```bash
cd /volume1/git/j0sh3rs/home-ops
git add kubernetes/apps/ai/CLAUDE.md
git commit -m "docs(ai): document openviking vlm direct-to-shim architecture"
git pull --rebase origin main
git push
```

---

## Self-Review Notes

- **Spec coverage:** new Service + shared-secret auth → Task 1; fallback +
  image-routing logic → Task 2; OpenViking repoint → Task 3; Omniroute
  baseUrl revert + combo cleanup + HolyClaude regression check → Task 4;
  documentation → Task 5. All spec sections have a corresponding task.
- **Ordering enforced structurally:** Task 2 depends on Task 1's env vars
  and Service; Task 3 depends on Task 2's auth+fallback logic actually
  working (verified directly, bypassing OpenViking, before OpenViking is
  repointed); Task 4's revert happens only after Task 3 confirms the new
  path is live, so there's no window where OpenViking's vlm has no working
  path at all.
- **Both SOPS files' shared value** is set together in Task 1 Step 1 (a
  single script, one generated value, two `sops --set` calls) specifically
  to avoid a window where the two files could drift — verified via
  `grep -c` (presence only) in Step 2, never a value comparison that would
  require printing either value.
- **Known follow-up, not a gap:** the exact Kubernetes Service name (Task 1
  Step 7) and `sops --set`'s exact path syntax (Task 1 Step 1) are both
  flagged as "verify live, don't assume" rather than hardcoded on faith,
  matching this project's established discipline.
