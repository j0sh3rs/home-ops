# OpenViking vlm: Direct-to-Shim (Bypass Omniroute) — Design

Date: 2026-09-18
Status: Approved, pending implementation plan
Related: `docs/superpowers/specs/2026-09-17-cliproxyapi-responses-shim-design.md`
(the shim this spec builds on and partially supersedes — the shim's
Chat-Completions↔Responses-API translation core stays as designed there),
`docs/superpowers/specs/2026-09-16-omniroute-anthropic-lane-design.md`,
`kubernetes/apps/ai/omniroute/`, `kubernetes/apps/ai/openviking/`

## Context

The 2026-09-17 shim spec built a `shim` sidecar in the `omniroute` pod that
translates Chat-Completions requests to the Responses-API shape CLIProxyAPI
actually requires, then repointed Omniroute's `cliproxyapi` provider-node's
`baseUrl` at the shim so every `cliproxyapi/gpt-*` reference cluster-wide
would route through it transparently. Tasks 1-2 of that plan (the shim
itself: stub scaffolding, then real translation logic) completed and were
independently verified working — a direct POST to the shim returns a real,
correctly-translated Chat-Completions response.

Task 3 (repointing Omniroute's provider-node `baseUrl` at the shim) hit a
blocker: the `baseUrl` repoint itself succeeded and was verified via a fresh
`GET` (not just a `200` on the `PATCH`), but the full chain through
Omniroute still failed with the exact "missing input" error the whole
project exists to fix. Root-caused to a bug **inside Omniroute's own
request-construction pipeline**, unrelated to both the shim (re-verified
working standalone) and the `baseUrl` repoint (verified correct and
durable): Omniroute's `app` container drops the `messages` field entirely
when building the downstream request for the `cliproxyapi`/`gpt-5.6-luna`
connection/model once `baseUrl` points at the shim — captured via a
temporary in-pod debug proxy, the outbound body was
`{"model":"gpt-5.6-luna","max_completion_tokens":16}`, no `messages` key at
all.

**Follow-up investigation (2026-09-18, a bounded spike):** hypothesized
Omniroute probes `GET <baseUrl>/v1/models` to auto-detect chat-dialect
support and drops `messages` when that 404s (the shim's stub never
implemented `/v1/models`). Live-tested by adding a temporary `/v1/models`
passthrough + request logger to the shim (never committed, fully reverted
after). **Confirmed Omniroute does call `GET /v1/models`** on the
connection (visible in the shim's request log) — but even with a real `200`
model-list response from CLIProxyAPI's real `/v1/models` (a bare
`{created,id,object,owned_by}` array, no capability/dialect metadata),
Omniroute still sent the same message-stripped body afterward. The
hypothesis is disproven as the direct cause. Deeper root-cause would require
reverse-engineering Omniroute's own minified bundled Next.js logic across
dozens of unlabeled chunks — out of scope for a bounded spike, and there is
no guarantee it's fixable from outside Omniroute's own closed source at
all.

**Decision**: rather than continue chasing a bug inside Omniroute's own
closed code, restructure so OpenViking's `vlm` leg bypasses Omniroute
entirely for this specific call, going straight to the shim (which already
works, proven independently of Omniroute's routing layer). The operator
explicitly confirmed this bypass is acceptable for `openviking-vlm`
specifically, and confirmed staying on the ChatGPT Pro subscription lane
(CLIProxyAPI's CLI-session reuse) rather than a paid BYOK key — Claude Pro
remains available as a model choice on the same shim if ever needed, no
separate plumbing required.

## Scope decisions (from this session's Q&A)

- **Keep local fallback, implemented in the shim itself, not Omniroute's
  combo mechanism.** OpenViking's `vlm` config block (`api_base`,
  `api_key`, `provider`, `model`) has no native multi-model/fallback list —
  the old two-leg behavior only existed because Omniroute's combo
  abstraction provided it server-side, transparent to OpenViking. With
  Omniroute out of the loop, the shim absorbs that responsibility: on
  CLIProxyAPI failure it retries against `llama-swap-apu`'s vlm model
  directly.
- **Shared-secret auth on the shim**, not a NetworkPolicy-only boundary.
  The shim has never had incoming auth (it only authenticates itself
  outbound, to CLIProxyAPI) because it was never reachable outside the
  `omniroute` pod. Now that it gains a real Service, it needs its own
  incoming check — reusing the existing OpenAI-client convention
  (`Authorization: Bearer <key>`, which OpenViking's client already sends
  as `api_key`) rather than inventing a new header scheme.
- **Route non-text content to the local fallback instead of rejecting it
  with 400.** The 2026-09-17 spec's "text-only v1, reject loudly" boundary
  existed specifically because there was no fallback to route images to at
  the time. Now that a real, already-vision-capable local fallback exists
  (the same `qwen2-vl-2b` model that was the sole leg during the capacity-
  gap period), routing image content straight there is strictly more
  capable than today's shim and matches what the original 3-leg combo did
  before the Claude leg was removed. CLIProxyAPI/Responses-API image
  translation itself remains out of scope — this only ever sends image
  content to the (already Chat-Completions-native) local model, never
  translates it for CLIProxyAPI.
- **Revert Task 3's live `baseUrl` repoint** back to
  `http://localhost:8317/v1` (CLIProxyAPI directly). Nothing will route
  through Omniroute→shim once OpenViking bypasses Omniroute entirely, and
  leaving the repoint in place risks exposing HolyClaude's `coding-deep`/
  `advanced` combos (which also reference other `cliproxyapi/gpt-*` models
  as fallback legs) to the same newly-discovered message-dropping bug for
  zero benefit. Reverting restores the prior, already-documented
  "best-effort/fail-closed" status quo for those combos (see
  `kubernetes/apps/ai/CLAUDE.md`'s holyclaude bullet) — no worse than
  before this whole project started.

## Architecture

```
OpenViking --(Chat-Completions, direct, shared-secret auth)-->
  omniroute-shim.ai.svc.cluster.local:8318 [shim, in omniroute pod]
    text request --(translated to Responses API)--> CLIProxyAPI (127.0.0.1:8317, same pod)
      success --(translated back to Chat-Completions)--> OpenViking
      failure --(original untranslated Chat-Completions body)--> llama-swap-apu (vlm)
                                                                    --> OpenViking
    non-text (image) request --(original untranslated body, no translation)--> llama-swap-apu (vlm)
                                                                                  --> OpenViking
```

Omniroute is no longer in this call path at all for `openviking-vlm`.
`embedding.dense` (OpenViking's other Omniroute-routed call) is unaffected
and stays exactly as-is, routed through Omniroute as `llamaswapapu/embedding`.

### New Kubernetes Service

Add a `service.shim` entry to `kubernetes/apps/ai/omniroute/app/helmrelease.yaml`'s
existing `service:` block, same pattern as the existing `cliproxyapi:` entry
(`controller: *app`, no `forceRename`):

```yaml
      shim:
        controller: *app
        ports:
          http:
            port: 8318
```

Following the same naming convention as `cliproxyapi:`'s existing Service
(no `forceRename`, so the Service name derives from the release name +
service key), this becomes reachable at
`omniroute-shim.ai.svc.cluster.local:8318`. This does not change or expose
CLIProxyAPI's own port (8317) in any way — that port still binds to
`127.0.0.1` only, inside the shim's own container's network namespace
reasoning, and remains reachable only via the shim's translation layer, not
directly. The shim itself already binds to `0.0.0.0:8318` (confirmed since
Task 1) — the only thing that changes is a Service object now routes to it.

### Shim: incoming auth

New SOPS-encrypted secret field, `SHIM_SHARED_SECRET`, added to
`kubernetes/apps/ai/omniroute/app/secret.sops.yaml`'s `omniroute-secrets`
Secret (reusing the same Secret object the `shim` container already partly
consumes via its `cliproxy-config` volume mount — this adds a scoped `env`
entry via `secretKeyRef`, not a blanket `envFrom`, to avoid widening the
shim's secret exposure beyond what it needs).

Every route except `GET /healthz` requires
`Authorization: Bearer <SHIM_SHARED_SECRET>` on the incoming request;
missing or mismatched → `401`. OpenViking's existing OpenAI-compatible
client already sends `Authorization: Bearer <api_key>` automatically from
its `vlm.api_key` config field — no new client-side mechanism needed, just
point `OPENVIKING_VLM_API_KEY`'s *value* at the new shared secret (same env
var name/wiring in `kubernetes/apps/ai/openviking/app/helmrelease.yaml`
stays unchanged; only the secret's actual value changes, in
`kubernetes/apps/ai/openviking/app/secret.sops.yaml`).

Both SOPS files must hold the identical secret value — this is a shared
secret between the two apps, not a rotated-independently credential pair.

### Shim: fallback logic

New environment configuration for the shim container:
- `FALLBACK_BASE_URL`: `http://llama-swap-apu.ai.svc.cluster.local:8080/v1`
  (plain container env, no secret needed — matches the existing direct-to-
  llama-swap pattern already used for OpenViking's `retrieval.rerank`).
- `FALLBACK_MODEL`: `vlm` (llama-swap-apu's alias for `qwen2-vl-2b`, per
  `kubernetes/apps/ai/llama-swap-apu/app/configmap.yaml`).

Request handling, in order:
1. Parse the incoming Chat-Completions body.
2. If any message content part is non-text (`image_url` or similar):
   forward the **original, untranslated** body to
   `FALLBACK_BASE_URL/chat/completions` with `model` overridden to
   `FALLBACK_MODEL`, and return that response verbatim (already
   Chat-Completions-shaped — llama-swap speaks it natively, no translation
   needed either direction).
3. Otherwise (text-only): translate to Responses API shape and call
   CLIProxyAPI as today. On success, translate the response back and
   return it (unchanged from the 2026-09-17 spec's design).
4. On CLIProxyAPI failure (non-2xx, connection error, or timeout — reuse
   whatever timeout behavior the shim's outbound `http.request` already
   has): fall back exactly as step 2 does — forward the original body to
   `FALLBACK_BASE_URL` with `model` set to `FALLBACK_MODEL`, return that
   response verbatim.
5. If the fallback call *also* fails: surface a real `5xx` error (matching
   the 2026-09-17 spec's "fail loudly, don't guess" error-handling
   philosophy) rather than inventing a response.

This mirrors the old `openviking-vlm` combo's two-leg behavior
(`cliproxyapi/gpt-*` first, `llamaswapapu/vlm` fallback) exactly, just
implemented in the shim instead of Omniroute's combo mechanism — including
for the case (non-text content) the old combo's local leg always handled
natively.

### OpenViking config changes

`kubernetes/apps/ai/openviking/app/helmrelease.yaml`'s `vlm:` block:
```yaml
      vlm:
        api_base: "http://omniroute-shim.ai.svc.cluster.local:8318/v1"
        api_key: "${OPENVIKING_VLM_API_KEY}"
        provider: "openai"
        model: "gpt-5.6-luna"
```
`model` is now a bare CLIProxyAPI model id, not an Omniroute combo name —
the `cliproxyapi/` prefix and combo indirection were Omniroute-specific
addressing conventions that no longer apply once OpenViking talks to the
shim directly. `OPENVIKING_VLM_API_KEY`'s env wiring
(`envFrom`/`secretKeyRef`) is unchanged; only its secret *value* changes
(see Shim: incoming auth above).

### Omniroute changes

Revert the live `baseUrl` repoint from Task 3
(connection id `3e29f7a8-5c0c-4914-ba78-9c4bf6d38d06`) back to
`http://localhost:8317/v1`, verified via the same PATCH-then-GET discipline
used throughout this project (a `200` on the PATCH alone is not sufficient
proof). Delete the now-unused `openviking-vlm` combo
(id `52b84d63-d6d8-43a9-b9c4-8fe90146535a`) via Omniroute's management API —
no git file represents combos, this is DB-only, same as the original
repoint.

## Error handling

- Shared-secret auth failure: `401`, generic message (don't leak whether
  the header was missing vs. wrong).
- Non-text content: routed to local fallback (see above), not rejected.
- CLIProxyAPI failure: routed to local fallback (see above), not surfaced
  directly to the caller.
- Local fallback *also* failing (either path): `5xx`, clear message,
  preserving the raw upstream error detail — matching the existing
  `upstream_details` pattern from the 2026-09-17 spec.
- Malformed/unexpected response shape from either backend: fail loudly
  (the existing `foundShape` guard from the 2026-09-17 spec's Task 2 fix
  round already covers the CLIProxyAPI leg; the llama-swap-apu leg is a
  passthrough with no shape validation needed, since it's already
  Chat-Completions-native).

## Testing / verification

1. Auth: request with no/wrong `Authorization` header → `401`. Correct
   header → normal behavior, matching pre-auth-change behavior exactly.
2. Fallback-on-failure: force a CLIProxyAPI-leg failure (e.g. a temporarily
   wrong outbound key, or by observing real transient failures), confirm
   the shim falls back to `llama-swap-apu` and returns a real response
   rather than erroring.
3. Image routing: send a request with `image_url` content, confirm it
   reaches `llama-swap-apu` directly (not CLIProxyAPI) and returns a real
   vision response — check via `llama-swap-apu`'s own logs, not just a
   `200` status.
4. Full OpenViking integration: trigger a real memory-extraction session,
   confirm success via the new direct path. Since Omniroute's own call-log
   is no longer in this loop, verification means checking the shim's own
   logs and/or `llama-swap-apu`'s logs directly for the request, not the
   `comboStepId`-based method used in the prior project.
5. Regression: after reverting Task 3's `baseUrl`, confirm `coding-deep`/
   `advanced` (HolyClaude's combos) behave exactly as already documented
   in `kubernetes/apps/ai/CLAUDE.md` (best-effort/fail-closed on their
   `cliproxyapi/gpt-*` legs) — no new failure mode introduced by the
   revert itself.

## Open items for the implementation plan

- Exact Service name Kubernetes assigns the new `shim:` service entry
  (verify via a real `GET` after deploy, matching the `cliproxyapi:`
  precedent — don't assume the naming convention holds without checking).
- Exact shim outbound-request timeout value to treat as "CLIProxyAPI
  failure" for fallback purposes — the shim's current `http.request` calls
  have no explicit timeout set; decide during implementation whether one is
  needed (an unbounded hang would never trigger fallback) or whether
  Node's default socket behavior is sufficient given this is a home-lab
  single-consumer path.
- Whether `llama-swap-apu`'s vlm endpoint needs a real `api_key` value or
  accepts `"not-needed"` the same way the existing rerank direct-call
  pattern does — verify against a real request, don't assume.

## Out of scope

- Fixing Omniroute's own message-dropping bug — root cause lives in its
  closed, minified bundled source; not pursued further after the bounded
  spike found no cheap fix.
- Migrating `embedding.dense` off Omniroute — unaffected by this change,
  stays as-is.
- Streaming support (unchanged from the 2026-09-17 spec — still out of
  scope).
- Translating image content *for CLIProxyAPI* (Responses API's
  `input_image` or similar) — non-text content only ever routes to the
  already-vision-capable local fallback in this design, never to
  CLIProxyAPI.
- Re-adding a Claude leg to any automated combo — the Anthropic lane
  isolation policy (`kubernetes/apps/ai/CLAUDE.md`) is unaffected by this
  change; `gpt-5.6-luna` (OpenAI/Codex lane) remains the configured remote
  model, with Claude Pro noted as available on the same shim mechanism if
  ever explicitly requested later, not adopted here.
