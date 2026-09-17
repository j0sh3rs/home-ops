# CLIProxyAPI Chat-Completions→Responses-API Shim — Design

Date: 2026-09-17
Status: Approved, pending implementation plan
Related: `docs/superpowers/specs/2026-09-16-omniroute-anthropic-lane-design.md`
(the openviking-vlm combo fix this directly follows up on),
`kubernetes/apps/ai/omniroute/`, `kubernetes/apps/ai/openviking/`

## Context

Following the Anthropic-lane isolation work (see the related spec above),
OpenViking's `openviking-vlm` Omniroute combo was reduced to a single local
leg (`llamaswapapu/vlm`) after testing found no working Chat-Completions-
compatible replacement among CLIProxyAPI's Codex/ChatGPT-subscription
models. Separately, that same day, the local leg's real hardware
constraints were root-caused and partially mitigated (vlm ctx-size bump,
Omniroute execution-deadline raised to its 120s API maximum, Omniroute's
own memory ceiling fixed) — see `kubernetes/apps/ai/openviking/app/
helmrelease.yaml` and `kubernetes/apps/ai/omniroute/app/helmrelease.yaml`
for that history. The local leg alone still can't cover prompts above
~18,480 tokens (120s at ~154 tok/s measured prefill speed), which is short
of the largest observed real prompt (45,309 tokens) and short of the
model's own 32,768 ctx-size ceiling.

The user asked to re-investigate a working OpenAI-subscription-backed leg
rather than accept that gap, explicitly preferring to keep using the free
CLIProxyAPI/Codex-subscription-reuse mechanism (not a paid BYOK OpenAI key).

## Investigation (2026-09-17, real requests, not assumed)

- Re-tested all 4 originally-tried candidates (`gpt-5.5`, `gpt-5.6-terra`,
  `gpt-5.6-sol`, `gpt-6-astra`) plus a previously-untested one discovered in
  the live model catalog, `codex-auto-review` — **6 for 6 failures**, all
  identical: `One of "input" or "previous_response_id" or "prompt" or
  "conversation" must be provided` (a 400 from the upstream, wrapped by
  Omniroute). This ruled out "wrong model" as the cause — every model
  behind this connection fails identically.
- Traced the real cause by reading Omniroute's own bundled source
  (`/app/.build/next/server/chunks/*.js` inside the running `omniroute`
  pod, not docs): `/v1/responses/[...path]/route.ts` — a route that looks
  like it should be a genuine OpenAI Responses API endpoint — actually just
  calls the exact same internal `handleChat()` function used by
  `/v1/chat/completions`. Confirmed empirically too: POSTing a real
  Responses-API-shaped body (`input: [...]`) to Omniroute's `/v1/responses`
  produces the identical "missing input" error, proving Omniroute never
  looks at `input` at all — it always builds a Chat-Completions-shaped
  (`messages`-based) request internally, regardless of which of its own
  routes is hit.
- Tested CLIProxyAPI's real ports directly (`127.0.0.1:8317`, only
  reachable from inside the `omniroute` pod's own network namespace):
  `GET /v1/chat/completions` → **404 (route does not exist at all)**;
  `GET /v1/responses` → 401 (route exists, needs CLIProxyAPI's own
  API-key auth — a separate credential domain from Omniroute's own keys).
  This is the root cause, definitively: **CLIProxyAPI never implemented a
  Chat Completions endpoint at all** — it is Responses-API-only by design
  (consistent with it reusing Codex CLI's own OAuth session, and Codex CLI
  itself being a Responses-API client). No model choice, retry, or
  Omniroute configuration change can route around this; the wire protocol
  itself is incompatible between what Omniroute's `handleChat` sends and
  what CLIProxyAPI accepts.
- One genuinely useful thing this confirmed: Omniroute's `handleChat`
  already resolves the *destination path* correctly for `cliproxyapi/*`
  models (it lands on `/v1/responses`, the only chat-capable route that
  exists there) — it is only the *request body shape* that is wrong. This
  means routing/addressing does not need to change, only the payload.

## Scope decisions (from this session's Q&A)

- **User confirmed preference**: stay on the free CLIProxyAPI/Codex-
  subscription path rather than switch to a paid BYOK OpenAI key. This
  spec builds a translation shim rather than pursuing Option 2 (real
  OpenAI API key) or accepting the local-only status quo.
- **Buffered responses only, no streaming** — confirmed: OpenViking's vlm
  calls are a batch/structured-extraction use case, not an interactive
  chat UI; every real request/response observed this session has been
  non-streaming. Streaming (SSE-to-SSE event translation between the two
  APIs' different streaming formats) is explicitly out of scope for v1.
- **Text-only translation for v1** — confirmed: most of OpenViking's real
  traffic is session-transcript text, not images. If a request contains
  any non-text message content, the shim must reject it with a clear,
  loud 400 rather than silently dropping the image content — failing
  visibly, not corrupting output silently. Image-content mapping
  (`image_url` → Responses API's `input_image`) is an explicit fast-follow,
  not part of this spec.
- **Sidecar-in-omniroute-pod, not a standalone app**: CLIProxyAPI's port
  (8317) is bound to `127.0.0.1` only and has never been exposed as its
  own Kubernetes Service (a deliberate security boundary from the original
  Omniroute revival design — see `docs/superpowers/specs/
  2026-09-07-omniroute-revival-design.md`). The shim must run inside the
  same pod to reach it, and this spec does not change that boundary or add
  a new externally-reachable port for CLIProxyAPI.
- **No new image/CI pipeline**: implemented as a small, dependency-free
  Node script (built-in `http` module only) mounted via a ConfigMap and
  run with a plain `node <script>` command, matching this repo's existing
  pattern for small in-cluster scripts (e.g. HolyClaude's postStart hook)
  rather than standing up a new build/publish pipeline for a one-file
  translator.
- **Fixes the whole `cliproxyapi` provider-node, not just openviking-vlm**:
  repointing the provider-node's `baseUrl` (an Omniroute DB-only setting,
  not a git file) fixes every current and future `cliproxyapi/gpt-*`
  consumer cluster-wide, as a natural consequence of where the fix lives —
  not a deliberately widened scope, just where the translation has to sit
  to work at all.

## Architecture

```
OpenViking --(Chat-Completions, via Omniroute combo/key)--> Omniroute (app)
  --(Chat-Completions, unchanged internal behavior)--> [shim sidecar, same pod]
    --(translated to Responses API)--> CLIProxyAPI (127.0.0.1:8317, same pod)
    <--(Responses API response)-- CLIProxyAPI
  <--(translated back to Chat-Completions)-- [shim]
<--(Chat-Completions response, Omniroute's normal shape)-- Omniroute
```

Omniroute's `cliproxyapi` provider-node (id
`openai-compatible-chat-efaa5c5e-4da1-4c23-a6fc-1d6efef49857`, connection id
`3e29f7a8-5c0c-4914-ba78-9c4bf6d38d06`) has its `baseUrl` changed from
`http://localhost:8317/v1` to `http://localhost:<shim-port>/v1` — an
Omniroute management-API call (`PATCH /api/providers/<connection-id>` or
the equivalent provider-node update endpoint; exact method to confirm
during implementation, matching this whole project's practice of verifying
against real API responses rather than assuming). No change to any
combo, key, or git-tracked Omniroute config is needed — every existing
`cliproxyapi/gpt-*` reference keeps working unchanged from the caller's
perspective.

### Shim container

New sidecar in `kubernetes/apps/ai/omniroute/app/helmrelease.yaml`'s
`controllers.omniroute` (alongside the existing `app` and `cliproxyapi`
containers): a minimal Node image (e.g. `node:22-alpine`, pinned) with
`command`/`args` running a script mounted from a new ConfigMap. Listens on
a new local-only port (not exposed via any Service — matches
`cliproxyapi`'s own pattern of being reachable only inside the pod).

### Request translation (text-only)

- Validate: every message's `content` must be a plain string, or an array
  containing only `{type: "text", ...}` parts. Any `image_url` (or other
  non-text) part → reject with `400` and a clear message naming the
  unsupported content type, not a silent drop.
- Map `messages` (an array of `{role, content}`) into Responses API's
  `input` field. Exact mapping (a plain string for single-turn, or an
  array of `{role, content: [{type: "input_text", text}]}` items for
  multi-turn) to be confirmed against CLIProxyAPI's actual accepted shape
  during implementation — verify with a real request, don't assume from
  OpenAI's public docs alone (this project's own history shows CLIProxyAPI
  and Omniroute both diverge from upstream docs in load-bearing ways more
  than once).
- Map `max_tokens` → `max_output_tokens` (Responses API's field name).
- Pass `model`, `temperature` through unchanged (model name mapping: the
  shim receives whatever bare model id Omniroute forwards after stripping
  its own `cliproxyapi/` prefix — confirm exact value received during
  implementation).
- Auth: CLIProxyAPI's own API-key auth (`api-keys` in its
  `cliproxy-config.yaml`, a separate credential domain from Omniroute's own
  `sk-...` inference keys or management token). The shim needs one of
  these keys to call CLIProxyAPI — sourcing it without printing it to any
  transcript is an implementation-time task, following this project's
  established discipline (env-var-passthrough inside the target container,
  never `cat`ting the secret file directly).

### Response translation

- Map the Responses API's completed-response shape (exact field names —
  `output`/`output_text` or similar — to confirm against a real response
  during implementation) into a Chat-Completions-shaped body:
  `choices: [{message: {role: "assistant", content: <text>}, finish_reason:
  "stop"}]`, `usage: {prompt_tokens, completion_tokens, total_tokens}`
  (mapped from whatever token-count fields the Responses API actually
  returns).
- Non-2xx from CLIProxyAPI: pass through as a Chat-Completions-shaped
  error envelope (`{"error": {"message", "type", "code"}}`), optionally
  preserving the raw upstream body under an `upstream_details` key —
  matching the pattern Omniroute itself already uses elsewhere in this
  cluster's observed behavior, so failures stay diagnosable the same way
  every other Omniroute-routed failure has been throughout this project.

## Error handling

- Shim unreachable (Omniroute can't connect to the new local port):
  surfaces to Omniroute as a normal upstream-connection failure, handled
  by Omniroute's existing retry/combo-fallback logic unchanged — no new
  failure mode introduced at that layer.
- CLIProxyAPI itself down/erroring: passed through per the response-
  translation rules above.
- Non-text content in a request: `400`, loud and specific, never silently
  stripped.
- Malformed/unexpected CLIProxyAPI response shape (a real risk given how
  much this project's own investigation found upstream docs to
  disagree with real behavior): the shim should fail loudly (5xx with a
  clear message) rather than guess at a translation and return corrupted
  content.

## Testing / verification

1. Direct shim test (bypass Omniroute): a real Chat-Completions-shaped
   POST straight to the shim's port, confirm it reaches CLIProxyAPI and
   returns a real, correctly-shaped Chat-Completions response.
2. Full chain test: a real request through Omniroute using an existing
   `cliproxyapi/gpt-*` model reference (start with `gpt-5.6-luna`, already
   referenced historically, or whichever candidate responds best — no
   strong reason to prefer one over another from this investigation alone)
   — confirm success end-to-end.
3. Re-add a working `cliproxyapi/gpt-*` leg to the `openviking-vlm` combo
   (Omniroute DB-only change, via its management API) and confirm a real
   OpenViking memory-extraction session succeeds via that leg specifically
   (not silently falling through to the local leg) — check the leg
   actually used via Omniroute's own call log, matching the verification
   method already proven out during the Anthropic-lane isolation project.
4. Confirm the `image_url` rejection path with a real multimodal request,
   so the text-only boundary is verified, not assumed.
5. Confirm no other `cliproxyapi/gpt-*` consumer (none currently deployed
   besides `openviking-vlm`, but combos like `coding-deep`/`advanced` also
   reference `gpt-5.5`/`gpt-5.6-terra`) regresses — a quick dry-run/logic
   check given none of those combos are the primary/first leg for their
   consumers today, so a regression there wouldn't have been caught by
   OpenViking testing alone.

## Open items for the implementation plan

- Exact Responses API request/response field names and shapes accepted by
  this specific CLIProxyAPI version — verify against real requests, not
  OpenAI's public docs (this project's established discipline; CLIProxyAPI
  and Omniroute have both diverged from upstream docs in load-bearing ways
  before).
- Exact method to update the `cliproxyapi` provider-node's `baseUrl` via
  Omniroute's management API (`PATCH` vs `PUT`, exact endpoint path) —
  verify against the real API response, matching how the Anthropic-lane
  project resolved analogous uncertainties.
- How to source CLIProxyAPI's own API key for the shim's outbound auth
  without printing it to any transcript.
- Which `cliproxyapi/gpt-*` model to standardize on for `openviking-vlm`'s
  restored remote leg — no strong signal yet on which of the 5 non-review
  candidates (`gpt-5.5`, `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-6-astra`,
  `gpt-5.6-luna`) is fastest/most reliable once the shape mismatch is
  fixed; decide empirically during implementation.

## Out of scope

- Streaming support.
- Image/multimodal content translation.
- A paid BYOK OpenAI API key (Option 2 from the prior discussion) —
  explicitly not pursued while this path is viable.
- Exposing CLIProxyAPI's port outside the `omniroute` pod's own network
  namespace.
