# HolyClaude Omniroute-Routing Revert

Date: 2026-09-26
Status: Implemented
Related: `docs/superpowers/specs/2026-09-16-omniroute-anthropic-lane-design.md`
(the change this reverts), `kubernetes/apps/ai/holyclaude/`,
`docs/ai-history/holyclaude.md`

## Context

The 2026-09-16 Anthropic-lane spec rewired HolyClaude's Claude Code auth to
route through Omniroute (`OMNIROUTE_ANTHROPIC_BASE_URL`/
`OMNIROUTE_ANTHROPIC_MODEL` env plus a `postStart` hook patching
`~/.claude/settings.json`), retiring HolyClaude's own native `claude login`
OAuth session for Claude Code specifically. Its own "Outcomes / findings"
section (added 2026-09-17) already documented that the `coding-deep`
combo's non-Claude legs never worked: the middle leg (`cliproxyapi/gpt-5.5`)
rejects every request with a Responses-API-shape mismatch, and the terminal
leg (`llamaswap/coder-large`, `gpt-oss-20b` at a 32k context) overflows on a
real interactive Claude Code request (76,386 input tokens measured during
that spec's own verification). Net effect: on any Omniroute hiccup —
restart, upstream 504, the queue-wedge incident in #719 — HolyClaude's
Claude Code failed closed, not gracefully, despite the combo's multi-leg
shape implying fallback resilience. The operator experienced this in
practice as HolyClaude being broken, and asked for the routing to be
undone.

## Decision

Revert Claude Code specifically back to native `claude login` OAuth,
talking directly to Anthropic (`api.anthropic.com`, no `ANTHROPIC_BASE_URL`
override at all). Nothing else about HolyClaude changes:

- **TaskMaster AI** (Perplexity key), **OpenCode** (its own interactive
  auth), **Hindsight** (`~/.hindsight` plugin, `HINDSIGHT_API_URL`/
  `HINDSIGHT_API_TOKEN`), the `kube-mcp` sidecar, `cluster-admin` RBAC, the
  rendered SA kubeconfig, the `sops-age` mount, OTel export, gh-auth, and
  every other piece of this deployment are untouched.
- The 2026-09-16 spec's own narrower PVC subPath-mount fix (replacing the
  original whole-`/home/claude` mount that shadowed `~/.local/bin`) is
  unrelated to the auth-routing change and is **not** reverted.

## Implementation

`kubernetes/apps/ai/holyclaude/app/helmrelease.yaml`:

- Removed the `OMNIROUTE_ANTHROPIC_BASE_URL`/`OMNIROUTE_ANTHROPIC_MODEL`
  container env entries and their comment block.
- Rewrote the `postStart` hook's `settings.json` step from an *injection*
  (writing `ANTHROPIC_BASE_URL`/`ANTHROPIC_MODEL`/`ANTHROPIC_AUTH_TOKEN`/
  `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY`/`model` on every boot) into a
  *cleanup* (stripping those same keys if a pod boots from a `settings.json`
  on the retained PVC that a pre-revert pod already patched). This is
  necessary, not just simpler: without an active cleanup step, a pod
  booting from already-patched PVC state would keep routing through
  Omniroute indefinitely even after this change lands, since nothing else
  ever removes those keys. The cleanup is idempotent and safe to leave
  running on every boot — once the keys are gone, it's a no-op.
- Updated the load-bearing comments describing the PVC's OAuth-session
  contents and the `postStart` mechanism, per the 2026-09-16 spec's own
  precedent of correcting comments left describing a retired mechanism.

`kubernetes/apps/ai/CLAUDE.md`: updated the "No cloud LLMs" policy bullet,
the "Anthropic (Claude) lane" bullet (no live consumer as of this change),
and the holyclaude entry to describe native OAuth instead of Omniroute
routing. Also corrected a stale image tag reference (`1.5.7` → `1.6.3`,
already the deployed tag) while touching that line.

`docs/ai-history/holyclaude.md`: appended a dated section summarizing the
revert, ahead of the existing verbatim 2026-09-02–2026-09-23 history (left
unmodified, as-is repo convention for history files).

## Left alone, deliberately

- **The `holyclaude-interactive` Omniroute key and the `coding-deep`
  combo.** Both live in Omniroute's own SQLite DB, not git — nothing here
  can revert them via a manifest change. The key is simply unused now; the
  operator can revoke it via Omniroute's dashboard/management API if
  desired. Not done automatically, since this repo change has no reach into
  that DB.
- **`OMNIROUTE_API_KEY` in `holyclaude-secret.sops.yaml`.** Left in place —
  harmless unused value, not worth a SOPS decrypt/re-encrypt cycle for this
  change alone. Fold its removal into a future edit of that file if one
  happens for another reason.
- **`caveman-proxy`.** Already dormant and out of Claude Code's request
  path before this change (settings.json pointed straight at Omniroute, not
  at `127.0.0.1:8787`); after this change settings.json has no
  `ANTHROPIC_BASE_URL` override at all, so caveman-proxy is still not in
  the loop. Its disposition (remove vs. repurpose) remains the open item
  the 2026-09-16 spec already flagged it as.
- **The Anthropic-lane isolation policy itself**
  (`kubernetes/apps/ai/CLAUDE.md`) — kept as standing policy for if/when a
  future interactive consumer of `cliproxyapi/claude-*` exists, even though
  nothing currently uses that lane.

## Verification

- `python3 -c "import yaml; yaml.safe_load_all(open(...))"` confirms
  `helmrelease.yaml` is still valid YAML after the edits (no cluster access
  from the environment this change was authored in, so `kustomize build`/
  `flux build --dry-run`/`task sops:verify` need to run from a normal
  operator shell before/at merge, per this repo's standard pre-commit
  checklist).
- No `*.sops.yaml` file was touched, so no re-encryption step is needed.
- Post-merge, real verification is a live one: reconcile the `holyclaude`
  Kustomization, confirm the pod boots clean (`kubectl -n ai logs -l
  app.kubernetes.io/name=holyclaude -c app` for the `postStart` cleanup log
  line), and run a real Claude Code interactive turn from the web terminal.
  If it prompts for login, the pre-existing OAuth session on the PVC has
  expired (unsurprising after 10 days) — run `claude login` once; the
  operator has already agreed to this.
