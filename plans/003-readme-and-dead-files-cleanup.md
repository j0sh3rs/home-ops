# Plan 003: Fix README drift and delete dead onedr0p template files

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8b27891f..HEAD -- README.md .github/tests/ kubernetes/apps/`
> If in-scope files changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none (but plan 004's allowlist must be seeded *after* this
  plan lands, since three scanned files get deleted here)
- **Category**: docs / tech-debt
- **Planned at**: commit `8b27891f`, 2026-11-24

## Why this matters

This is a public repo whose README is the primary orientation document for
humans and AI agents. It currently describes apps that no longer exist
(Open WebUI, ClickHouse, Kelos, OpenCode, MCPJungle, Omega MCP — all
removed/archived), omits six live services, lists a CI workflow that was
deleted (`e2e`), and states a Cloudflare plan that changed in 2026-10. Agents
that trust the README will chase nonexistent paths. Separately,
`.github/tests/` carries three dead files from the onedr0p/cluster-template
origin with fake sample data (`k8s-0 10.10.10.100`) that nothing consumes.

## Current state

Verified at `8b27891f`:

- `kubernetes/apps/ai/kustomization.yaml:10-11` documents the removals:
  "n8n, opencode, agent-canvas, cognee, and kelos-system remain removed
  2026-08-14". `mcpjungle` lives in `archive/`, as do `clickhouse` and
  `open-webui` (check `ls kubernetes/apps/archive/` yourself).
- Live AI apps (`ls kubernetes/apps/ai/`): `ai-tap, argus, atuin-ai-server,
  faster-whisper, hindsight, linkwarden-mcp, llama-swap, llama-swap-apu,
  mac-inference, omniroute, piper, vikunja-mcp, wyoming-openai`.
- Live services (`ls kubernetes/apps/services/`): `atuin, changedetector,
  gatus, home-assistant, homebridge, homepage, it-tools, konflate,
  linkwarden, memos, mosquitto, n8n, paperless, tetragon-policies, vikunja`
  (`tetragon-policies` holds eBPF policy files, not an app).
- `.github/workflows/` contains 7 workflows: `flux-diff, hindsight-changes,
  label-sync, labeler, macos-nix, release, validate-secrets`. There is **no**
  `e2e.yaml`.
- `.github/tests/`:
  - `flate-values.yaml` — **in use** (`.github/workflows/flux-diff.yaml`
    passes it to `flate diff --supply`). KEEP.
  - `nodes.yaml`, `private.yaml`, `public.yaml` — onedr0p leftovers.
    `nodes.yaml:13` contains `repository_name: onedr0p/cluster-template`;
    the files hold fake `k8s-0` sample node data at `10.10.10.100`. The only
    reference in the repo is `.taskfiles/template/Taskfile.yaml:139` (the
    `:tidy:` flow's `rm -rf .github/tests`), which is unrelated to these
    files' content.
- `CLAUDE.md:335` records the Cloudflare plan change (Pro, 2026-10-04).

README locations to change (line numbers as of `8b27891f`; locate by content,
not line number):

1. §Secret Management (~line 68): "The age key is injected at bootstrap and
   never leaves the cluster." — stale. The age key is never committed; local
   tooling gets it via `mise` (`SOPS_AGE_KEY_FILE`, see §Toolchain line
   "mise injects KUBECONFIG, SOPS_AGE_KEY_FILE, and TALOSCONFIG"), and
   `.sops.yaml` defines path-based rules (cluster bootstrap paths plus
   `mac_only` rules for `talos/` and `macos/secrets`).
2. Structure tree (~line 77): `ai/` description lists "Open WebUI" — remove it.
3. Structure tree (~line 79): `databases/` description "CNPG, DragonflyDB,
   ClickHouse" — remove ClickHouse.
4. Structure tree (~line 81): the `kelos-system/` line — delete the line.
5. Structure tree (~line 90): `meta/repos/  # Shared HelmRepository and
   OCIRepository sources` — the repo is mid-migration to pure OCIRepository
   (CLAUDE.md:148-156 lists the legacy `HelmRepository` apps pending
   removal). Rephrase to `# Shared chart sources (OCI; legacy HelmRepository pending removal)`.
6. AI "Clients & Tools" table (~lines 188–191): all four rows
   (OpenCode, Kelos, MCPJungle, Omega MCP) describe removed apps — replace
   the table body with the live apps below.
7. Services table (~lines 212–221): missing six live apps — add rows.
8. GitHub Actions table (~lines 300–304): the `e2e` row describes a
   nonexistent workflow — delete the row. Also update the `validate-secrets`
   row to: "Blocks PRs containing unencrypted `*.sops.yaml` files or
   un-allowlisted plaintext secret patterns" (plan 004 makes the second half
   true; wording lands here so the README is right once 004 merges).
9. Cloud Dependencies table (~line 327): "≈$30/yr (domain registration; Free
   plan features)" — the account is on the Pro plan (CLAUDE.md:335).
   Rephrase the cost cell without inventing prices:
   "Domain registration (~$30/yr) + Pro plan".

Replacement content for the AI "Clients & Tools" table (one line each; verify
each against the app's `helmrelease.yaml` before writing — the descriptions
below are from the source files at `8b27891f`, but confirm):

| Component | Purpose |
|---|---|
| [ai-tap](https://github.com/anomalyco/ai-tap) | Logging reverse proxy that captures the LLM eval corpus for `tools/ai-eval` |
| argus | *(read `kubernetes/apps/ai/argus/app/helmrelease.yaml` and write a one-line purpose from its comments; it has no inline description to copy)* |
| [atuin-ai-server](https://github.com/atuinsh/atuin-ai-server) | AI assistant backend for Atuin |
| hindsight | Memory server; the sole memory layer for AI agents since 2026-09-25 (see its `helmrelease.yaml` header comment) |
| linkwarden-mcp | MCP server exposing Linkwarden via supergateway |
| mac-inference | In-cluster endpoint for the Mac Studio's oMLX (chat + Wyoming audio; `wyoming-openai` and other apps point at `mac-inference.ai.svc.cluster.local:8000`) |
| vikunja-mcp | MCP server exposing Vikunja via supergateway |
| wyoming-openai | Wyoming↔OpenAI audio bridge (STT/TTS) to the Mac's oMLX endpoint |

Do not invent links for argus/hindsight/mac-inference/wyoming-openai — plain
text names are fine when no upstream URL is evident in the app's files.

Services table rows to add (same verification rule — one line each from the
app's files): gatus (health/status checks), changedetector (website change
monitoring), konflate (Kubernetes dashboard), memos (notes), n8n (workflow
automation), vikunja (task management).

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Removed-app strings gone | `grep -n -i "Open WebUI\|kelos-system\|ClickHouse\|OpenCode\|MCPJungle\|Omega MCP" README.md` | no output |
| `e2e` row gone | `grep -n "e2e" README.md` | no output |
| New services present | `grep -n -i "gatus\|changedetector\|konflate\|memos\|n8n\|vikunja" README.md` | matches in the Services table |
| Dead files gone | `ls .github/tests/` | only `flate-values.yaml` |
| flate values still present | `test -f .github/tests/flate-values.yaml && echo ok` | `ok` |

## Scope

**In scope**:
- `README.md`
- Delete: `.github/tests/nodes.yaml`, `.github/tests/private.yaml`,
  `.github/tests/public.yaml`

**Out of scope**:
- `.github/tests/flate-values.yaml` — in use by flux-diff.
- `.taskfiles/template/Taskfile.yaml` — its `rm -rf .github/tests` stays; it
  is generic cleanup of the template flow, not a dependency on the deleted
  files.
- Any file under `kubernetes/apps/` — this plan is docs + dead-file removal
  only.
- The archived apps themselves (`kubernetes/apps/archive/`) — deliberate
  archive, do not touch.

## Git workflow

- Branch: `advisor/003-readme-cleanup`
- Commit style: `docs: sync README with current app inventory` and
  `chore: remove dead onedr0p sample files` (two commits, or one combined —
  repo convention is conventional-commit prefixes).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Delete the dead files

```bash
rm -f .github/tests/nodes.yaml .github/tests/private.yaml .github/tests/public.yaml
```

**Verify**: `ls .github/tests/` → `flate-values.yaml` only.

### Step 2: Apply the README edits

Apply items 1–9 from "Current state" above, in order. Locate each by its
quoted content (line numbers will shift as you edit). For the two table
replacements, confirm each new row against the corresponding app directory
before writing it.

**Verify**: all four "Removed-app strings gone" / "e2e row gone" greps return
no output; the "New services present" grep matches.

### Step 3: Whole-README sanity pass

Read the final README top to bottom once. Check: no dangling references to
deleted rows/sections, tables render (column counts consistent), and nothing
else in the file contradicts `ls kubernetes/apps/`.

**Verify**: `grep -c "^|" README.md` is a plausible table-row count (no
malformed rows) — and your read-through found no contradictions.

## Test plan

No test framework covers the README. The grep battery in "Commands you will
need" is the verification. The risk in this plan is factual error in a new
row, so the per-row verification against the app directory is the test.

## Done criteria

- [ ] `grep -n -i "Open WebUI\|kelos-system\|ClickHouse\|OpenCode\|MCPJungle\|Omega MCP" README.md` → no output
- [ ] `grep -n "e2e" README.md` → no output
- [ ] `.github/tests/` contains only `flate-values.yaml`
- [ ] Services table includes gatus, changedetector, konflate, memos, n8n, vikunja
- [ ] `git diff --name-only` shows only `README.md` + the three deleted files
- [ ] `plans/README.md` status row updated

## STOP conditions

- The README has been restructured (section names or tables in "Current
  state" no longer findable by their quoted content).
- Any of the "live app" lists in this plan disagrees with
  `ls kubernetes/apps/ai/` / `ls kubernetes/apps/services/` (the tree
  drifted).
- You cannot determine a defensible one-line purpose for an app from its own
  files — write the row with just the app name and a "(purpose: see
  kubernetes/apps/<ns>/<app>/)" note rather than guessing.

## Maintenance notes

- The README app tables and `kubernetes/apps/` drift apart whenever an app is
  added or removed. When that happens, the tables need the same update — this
  plan's grep battery doubles as a drift check.
- Plan 004 (validate-secrets gate) seeds its allowlist from a live scan;
  running it after this plan avoids allowlisting the three deleted files.
- A reviewer should spot-check 2–3 of the new table rows against the actual
  app manifests, since this plan's descriptions came from an audit, not from
  the executor's own read.
