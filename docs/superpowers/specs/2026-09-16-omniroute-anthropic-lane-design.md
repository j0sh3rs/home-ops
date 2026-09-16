# Omniroute Anthropic Lane — Isolation & HolyClaude Consolidation

Date: 2026-09-16
Status: Approved, pending implementation plan
Related: `docs/superpowers/specs/2026-09-07-omniroute-revival-design.md` (Phase 1),
`docs/superpowers/specs/2026-09-08-omniroute-phase2-switchover-design.md` (Phase 2
consumer switchover), `docs/superpowers/specs/2026-09-01-holyclaude-helm-deployment-design.md`
(HolyClaude's original native-OAuth Claude Code setup — superseded for Claude
Code specifically by this spec), `kubernetes/apps/ai/omniroute/`,
`kubernetes/apps/ai/holyclaude/`, `kubernetes/apps/ai/openviking/`

## Context

Phase 1/2 stood up Omniroute with a `cliproxyapi` sidecar that reuses CLI
subscription OAuth sessions (Claude Code, Codex) as OpenAI-compatible
backends. Since then, dashboard-side configuration (Omniroute's combos, which
live only in its SQLite DB, not git) drifted into a state where the same
Claude Pro OAuth session is drawn on by two independent, uncoordinated
consumers:

1. **HolyClaude** — its own separate, native `claude login` OAuth device-flow
   session (`kubernetes/apps/ai/holyclaude/`), used for interactive coding.
2. **Omniroute's `cliproxyapi` sidecar** — a second, independent OAuth login
   to the *same* Anthropic account (`claude-j0sh3rs@gmail.com`), used as a
   leg of the `openviking-vlm` combo for OpenViking's automated
   memory-extraction/VLM calls.

Live logs (2026-09-16, `omniroute`/`openviking` pods) confirm the
`openviking-vlm` combo is currently failing on all three of its legs:

- `cliproxyapi/claude-haiku-4-5-20251001` — 504 from Omniroute's own internal
  request queue (`resilienceSettings.requestQueue.maxWaitMs=15000ms`
  exceeded) before the request reaches Anthropic at all. This automated
  traffic against the shared Claude Pro subscription is the leading suspect
  for HolyClaude's interactive session degrading ("can't properly talk to
  models anymore") — same account, same usage allowance, two independent
  sessions contending for it.
- `cliproxyapi/gpt-5.6-luna` — hard 400:
  `One of "input" or "previous_response_id" or "prompt" or "conversation"
  must be provided`. Omniroute is sending this model a Chat-Completions-shaped
  request; it expects an OpenAI Responses-API shape. This leg has never
  actually worked.
- `llamaswapapu/vlm` — context overflow (a ~45k-token memory-extraction
  prompt against the model's 16384 ctx-size) or the same Omniroute queue
  timeout.

Separately, Home Assistant's voice/conversation integration
(`kubernetes/apps/services/home-assistant/app/omniroute-secret.sops.yaml`,
wired 2026-09-14) already routes through Omniroute → `cliproxyapi`'s
Codex/ChatGPT Plus session, and OpenViking's embedding/rerank already avoid
Claude. These are confirmed-working precedents for "OpenAI/Codex is the
automation lane."

**Decision (explicit, user-approved):** formalize two lanes by provider,
not by consumer-specific ad hoc combo edits:

- **Anthropic lane** (`cliproxyapi/claude-*`) — interactive use only.
  Consolidated onto a **single** Claude Pro OAuth session (Omniroute's
  `cliproxyapi` sidecar's), consumed by HolyClaude via Omniroute rather than
  HolyClaude keeping its own second, independent login. No automated
  consumer may ever reference a `cliproxyapi/claude-*` model.
- **OpenAI/Codex lane** (`cliproxyapi/gpt-*`) — the shared automation lane:
  HA voice (already live), OpenViking VLM (new), rerank/embedding (already
  local/non-Claude), and anything else automated added later.
- **Local lane** (llama-swap / llama-swap-apu) — unchanged role as the
  zero-quota fallback tier for both of the above.

## Scope decisions (from this session's Q&A)

- **Fix all three broken legs of `openviking-vlm`, not just remove Claude.**
  Explicit user choice: narrowly removing Claude and leaving the other two
  legs broken would leave VLM/memory-extraction still 100% failing (now on
  the OpenAI/local legs instead) — no real improvement to OpenViking's actual
  problem. All three get fixed in this pass.
- **HolyClaude gets rewired to consume Claude through Omniroute, retiring its
  own native OAuth login for Claude Code specifically** (explicit
  user-requested addition to the original proposal, made to gain Omniroute's
  request logging, its compression feature, and its skill-routing layer for
  Claude Code's own traffic — benefits HolyClaude's standalone native session
  never had access to). This also happens to be the strongest possible fix
  for the account-contention root cause: after this change there is exactly
  **one** Claude Pro OAuth session cluster-wide (Omniroute's), not two.
- **Feasibility confirmed live, not assumed**, per this repo's established
  practice of verifying against real behavior rather than upstream docs
  (which the Phase 1 spec already found to be stale/inaccurate more than
  once). Via `kubectl exec` into the running `omniroute` pod:
  - `GET http://127.0.0.1:20129/v1/messages` → `405` (route exists, POST
    only) — Omniroute's `app` container exposes an **Anthropic-native
    Messages API-shaped endpoint**, not just the OpenAI-compatible
    `/v1/chat/completions` documented in the Phase 1/2 specs. This is what
    makes routing Claude Code CLI's own native wire protocol through
    Omniroute possible at all — Claude Code cannot speak OpenAI
    chat-completions shape, so without this route this whole approach
    would be infeasible.
  - `POST http://127.0.0.1:20129/v1/messages` with `{"model":"test",...}` →
    `400 {"error":{"message":"Unable to determine provider for model
    'test'. Use a provider/model prefix (e.g. openai/test) or ensure the
    model is added as a combo entry."}}` — confirms `/v1/messages` uses the
    **same `<prefix>/<model>` addressing scheme** as `/v1/chat/completions`
    (e.g. `cliproxyapi/claude-opus-4-5-...`), not bare Anthropic model
    names. Claude Code's model config must send the prefixed form.
  - `cliproxyapi`'s own port 8317 404s on both routes unauthenticated
    (vs. Omniroute's 405) — consistent with CLIProxyAPI's auth middleware
    gating route visibility itself; irrelevant here since HolyClaude will
    talk to Omniroute's port, not CLIProxyAPI directly.
- **Not in scope**: any BYOK cloud provider credentials; re-enabling
  openclaw/argus; changing OpenViking's rerank routing (stays direct to
  llama-swap per the existing, upstream-confirmed SSRF-filter limitation).

## Architecture

### 1. `openviking-vlm` combo — remove Claude, fix the other two legs

Combo config lives only in Omniroute's SQLite DB (dashboard/MCP-managed, not
a git file) — changed via Omniroute's management API/MCP tools, not a
manifest edit.

- Drop the `cliproxyapi/claude-haiku-4-5-20251001` leg entirely. No
  automated combo may reference any `cliproxyapi/claude-*` model going
  forward — this is the core isolation rule.
- Fix the `cliproxyapi/gpt-5.6-luna` 400: investigate whether CLIProxyAPI's
  Codex session exposes a Chat-Completions-compatible model id (upstream
  CLIProxyAPI is known to support multiple wire-format translations per the
  Phase 1 spec's own findings about its multi-format nature — verify against
  its actual registered model list via the management API, don't assume).
  If a working chat-completions-shaped id exists, swap to it. If genuinely
  none exists, document this as an upstream gap and let the local leg be the
  real fallback (not a silent failure — the combo's terminal behavior must
  degrade to local, not 502).
- `llamaswapapu/vlm`: raise `ctx-size` past 16384 in
  `kubernetes/apps/ai/llama-swap-apu/` so real memory-extraction prompts
  (~45k tokens observed) stop overflowing. Re-measure real VRAM headroom via
  `rocm-smi --showmeminfo vram` first — this tier was already down to 1.88
  GiB free per the existing `kubernetes/apps/ai/CLAUDE.md` note; don't raise
  blind. If there's no room, the fallback is trimming/summarizing the
  extraction prompt, which is OpenViking-internal behavior we don't control
  — flag as a hard constraint if VRAM doesn't allow the ctx bump, rather than
  forcing it and destabilizing the other four always-on models on that tier.

### 2. HolyClaude — consume Claude through Omniroute, retire native OAuth login

- `~/.claude/settings.json` (or equivalent env override) changes:
  - `ANTHROPIC_BASE_URL` → `http://omniroute.ai.svc.cluster.local:20129`
    (cluster-internal, same pattern as every other Omniroute consumer —
    no need for the external `omniroute.68cc.io` route or its Authentik
    gate for pod-to-pod traffic).
  - `ANTHROPIC_API_KEY` → a **dedicated** Omniroute inference key (`sk-...`,
    minted via `POST /api/keys`, name `holyclaude-interactive`), stored in
    `holyclaude-secret.sops.yaml`. This key is the enforcement point for the
    lane rule: it must never be handed to an automated consumer, and (if
    Omniroute supports per-key model/provider allow-lists — verify during
    implementation) should be scoped to the `cliproxyapi/claude-*` provider
    only.
  - Claude Code's model config → the prefixed form
    (`cliproxyapi/claude-<model>`, exact model id enumerated from Omniroute's
    registered `cliproxyapi` provider models at implementation time — at
    least `claude-haiku-4-5-20251001` is confirmed registered; pick the
    right-weight model for interactive coding, not necessarily Haiku).
- **Retire HolyClaude's own native `claude login` OAuth device-flow
  session** for Claude Code specifically — `persist-claude-json.mjs`'s
  stored session and the associated `~/.claude` OAuth credential state stop
  being the auth path once `ANTHROPIC_API_KEY`/`ANTHROPIC_BASE_URL` are set
  (Claude Code CLI prefers an explicit API key over OAuth when both could
  apply — confirm this precedence holds at implementation time). Update
  `kubernetes/apps/ai/holyclaude/app/helmrelease.yaml`'s extensive comments
  describing the OAuth-login mechanism to describe the new API-key-via-
  Omniroute mechanism instead — several of those comments are load-bearing
  operational notes (PVC mount rationale, `persist-claude-json.mjs`
  behavior) that will actively mislead the next reader if left describing a
  retired mechanism.
- **`caveman-proxy` disposition — open item, not resolved by this spec.**
  HolyClaude's app container currently points `ANTHROPIC_BASE_URL` at
  `http://127.0.0.1:8787/w/claude` (the `caveman-proxy` local daemon,
  started via the postStart hook) rather than directly at Anthropic.
  Whether `caveman-proxy` should (a) be removed since Omniroute now
  provides the logging/observability layer it may have existed for, (b)
  stay in the chain with its own upstream re-pointed at Omniroute instead of
  Anthropic, or (c) be bypassed entirely by pointing Claude Code straight at
  Omniroute, requires reading `caveman-proxy`'s actual behavior/source
  first (same "verify, don't assume" discipline as everything else in this
  spec) — deferred to the implementation plan, not guessed here.
- OpenCode, TaskMaster, and the other HolyClaude providers are unaffected —
  this change is scoped to the Claude Code provider only.

### 3. Access control audit

- Enumerate every live Omniroute inference key (`sk-...`) and confirm none
  besides `holyclaude-interactive` can reach any `cliproxyapi/claude-*`
  model — via Omniroute's own per-key scoping if it exists, or by auditing
  that no other combo/config references it if per-key scoping turns out not
  to be a real feature (verify which at implementation time; don't assume
  the mechanism from the Phase 1 spec's brief mention of key
  `read`/`write`/`admin` scopes, which describe *management* API access,
  not inference-time model restriction — a distinct thing).

### 4. Documentation correction

- `kubernetes/apps/ai/CLAUDE.md` currently states Omniroute/LiteLLM were
  removed 2026-08-14 and describes LiteLLM as the live gateway — stale
  relative to the Phase 1/2 specs already merged. Both Phase 1 and Phase 2
  specs already flagged this as deferred to "a dedicated doc-sweep task."
  Folded into this change since the same files are being touched again:
  update the namespace overview, the `openviking` bullet (VLM/embedding
  routing, the now-fixed `openviking-vlm` combo), the `holyclaude` bullet
  (new Omniroute-backed Claude Code auth mechanism, retired native OAuth),
  and the "Decisions explicitly rejected" section's OmniRoute entry (still
  describes it as removed — needs a pointer to this spec and the two prior
  Omniroute specs instead of standing as a stale rejection).

## Error handling / degraded-mode behavior

- `openviking-vlm` combo: on total failure (all three legs down), OpenViking
  already degrades gracefully today (memory extraction for that session is
  skipped, not a crash) — this behavior is preserved, just made to actually
  succeed under normal conditions instead of always exhausting to failure.
- HolyClaude: if Omniroute or its `cliproxyapi` sidecar is down, Claude Code
  now fails closed (no local fallback — this is an interactive tool, unlike
  OpenViking's background extraction). This is an accepted behavior change:
  previously a HolyClaude outage was independent of Omniroute's health;
  after this change it isn't. No fallback-to-native-OAuth is planned — that
  would defeat the single-session consolidation. Documented here so it isn't
  a surprise later.

## Testing / verification

1. After the combo edit: trigger a real OpenViking session, confirm a
   memory-extraction call succeeds via the OpenAI or local leg in pod logs
   — no more aggregate `502`/`bad_gateway` across all three attempts.
2. Confirm no live Omniroute config (combos, provider-nodes, keys) still
   grants any automated consumer a path to `cliproxyapi/claude-*`.
3. From inside HolyClaude's terminal, run a real Claude Code interactive
   turn and confirm it round-trips through Omniroute (check Omniroute's own
   request log/dashboard shows the call, not just that Claude Code got a
   response — this is the whole point of the change).
4. User independently confirms HolyClaude's Claude Code session no longer
   degrades under OpenViking load — this can't be measured from cluster-side
   logs alone (Anthropic's account-level usage-cap state isn't observable
   from here), so it's a real-world check on the user's end over the
   following days, not a one-shot verification step.

## Open items for the implementation plan

- Exact `cliproxyapi` Codex model id (if any) that accepts Chat-Completions
  shape, for the `openviking-vlm` combo's OpenAI leg.
- Real VRAM headroom check on `bee-jms-03` before raising `llama-swap-apu`'s
  vlm ctx-size; fallback plan if there's no room.
- Whether Omniroute supports per-inference-key model/provider allow-lists
  (affects how strictly the lane rule can be enforced vs. left as
  convention-plus-combo-audit).
- `caveman-proxy`'s actual role and disposition (remove / re-point / bypass)
  — needs its source/behavior read first.
- Exact Claude model id(s) to register for HolyClaude's interactive use
  (not necessarily Haiku — enumerate what's available under the
  `cliproxyapi` provider-node and pick appropriately for coding work).
- Whether Claude Code CLI's API-key auth path takes precedence over an
  existing persisted OAuth session automatically, or whether the old OAuth
  state needs to be explicitly cleared from the PVC to avoid ambiguity.

## Out of scope

- BYOK cloud provider credentials.
- Re-enabling openclaw/argus.
- Changing OpenViking's rerank routing (stays direct-to-llama-swap; separate
  backlog item per the Phase 2 spec, unrelated to the Anthropic/OpenAI lane
  split).
