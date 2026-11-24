# Plan 002: Add a CI gate that fails on apps consuming secrets without a Reloader annotation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8b27891f..HEAD -- .github/workflows/flux-diff.yaml .github/tests/ kubernetes/apps/ai/`
> If in-scope files changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/001-wyoming-openai-reloader.md (the gate fails while
  any un-annotated secret consumer exists; 001 removes the only current one)
- **Category**: direction (systemic guard, issue #493 class)
- **Planned at**: commit `8b27891f`, 2026-11-24

## Why this matters

Apps that read long-lived secrets via `envFrom`/`secretKeyRef` only pick up
rotated values on pod restart. stakater Reloader (running cluster-wide in
`kube-system`) does that restart automatically — but only for pods carrying
its annotation. The cluster has already burned a full incident cycle on this
class (issue #493), and a manual scan found exactly one un-annotated consumer
(wyoming-openai, fixed by plan 001). Without a gate, the next app added from
the app-template pattern silently reintroduces the bug; a new app is added
roughly every month. This gate makes the class permanently dead at PR time,
with no cluster access required.

## Current state

- `.github/workflows/flux-diff.yaml` — the render/diff workflow. Facts the
  executor needs:
  - Header comment documents why it has two triggers (`pull_request` +
    `push` to `renovate/**`) — Renovate's default `automergeType: branch`
    merges without a PR. Keep the header and trigger structure untouched.
  - `on:` paths: `kubernetes/**/*.yaml`, `.github/workflows/flux-diff.yaml`,
    `.github/tests/flate-values.yaml` (same set on both triggers).
  - `permissions:` (workflow-level): `contents: read`, `pull-requests: write`.
  - `concurrency:` group `${{ github.workflow }}-${{ github.ref }}`,
    `cancel-in-progress: true`.
  - Single job `flux-diff` runs on `runs-on: home-ops-runner` (self-hosted).
- `.github/tests/` — contains `flate-values.yaml` (used by flux-diff) and,
  until plan 003 lands, three dead onedr0p files. New script goes here.
- Reloader annotation idiom in this repo (10 AI apps, e.g.
  `kubernetes/apps/ai/atuin-ai-server/app/helmrelease.yaml:24-26`):

  ```yaml
  values:
    controllers:
      atuin-ai-server:
        annotations:
          reloader.stakater.com/auto: "true"
  ```

- Verified baseline (run at `8b27891f`): among all `helmrelease.yaml` files
  under `kubernetes/apps/` that reference `secretRef` or `secretKeyRef`,
  exactly **one** lacks any `reloader.stakater.com/` key —
  `kubernetes/apps/ai/wyoming-openai/app/helmrelease.yaml`, fixed by plan 001.
  So after 001 the gate is green with **zero exemptions**.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Gate (clean tree) | `bash .github/tests/check-reloader.sh` | exit 0, prints PASS lines |
| Workflow lint | `yamllint .github/workflows/flux-diff.yaml` | exit 0 |
| Workflow parses | `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/flux-diff.yaml'))"` | exit 0 |

## Scope

**In scope** (the only files you may create/modify):
- `.github/tests/check-reloader.sh` (create)
- `.github/workflows/flux-diff.yaml` (add one job; nothing else changes)

**Out of scope**:
- Any app under `kubernetes/apps/` — if the gate finds an un-annotated app
  at runtime, STOP (plan 001 should have cleared the only known one).
- `.github/tests/flate-values.yaml` and the dead onedr0p files (plan 003).
- The Reloader deployment in `kube-system`.

## Git workflow

- Branch: `advisor/002-reloader-ci-gate`
- Commit style: `ci: gate apps without reloader annotations` (repo uses
  conventional-commit prefixes; Renovate commits look like `fix(helm): ...`).
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Write the gate script

Create `.github/tests/check-reloader.sh` (executable, `chmod +x`):

```bash
#!/usr/bin/env bash
# Fail when an app consumes a Secret via envFrom/secretKeyRef but has no
# Reloader annotation — rotated keys would stay stale until a manual
# rollout (issue #493 class). Pattern of record:
#   kubernetes/apps/ai/atuin-ai-server/app/helmrelease.yaml
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

fail=0
while IFS= read -r f; do
  if ! grep -q "reloader.stakater.com/" "$f"; then
    echo "FAIL: $f references a secret without a reloader.stakater.com/ annotation"
    fail=1
  else
    echo "PASS: $f"
  fi
done < <(grep -rl -E "secretRef|secretKeyRef" kubernetes/apps --include="helmrelease.yaml")

if [ "$fail" -ne 0 ]; then
  echo ""
  echo "Fix: add at controller level (under values.controllers.<app>):"
  echo "    annotations:"
  echo '      reloader.stakater.com/auto: "true"'
  exit 1
fi
echo "All secret-consuming apps have Reloader annotations."
```

**Verify**: `bash .github/tests/check-reloader.sh` → exit 0, last line
`All secret-consuming apps have Reloader annotations.` (requires plan 001
already applied — check `grep -q "reloader.stakater.com" kubernetes/apps/ai/wyoming-openai/app/helmrelease.yaml` first; if it fails, STOP).

### Step 2: Negative test

Create a throwaway file
`kubernetes/apps/services/n8n/app/zz-gate-selftest-helmrelease.yaml`
containing a minimal `kind: HelmRelease` document with
`envFrom: - secretRef: { name: selftest }` and **no** reloader annotation.

**Verify**: `bash .github/tests/check-reloader.sh` → exit 1, output contains
`FAIL: kubernetes/apps/services/n8n/app/zz-gate-selftest-helmrelease.yaml`.
Then delete the file (`rm -f`). Re-run → exit 0 again.

### Step 3: Add the CI job

In `.github/workflows/flux-diff.yaml`, after the existing `flux-diff:` job
block, add a second job:

```yaml
  reloader-check:
    name: Reloader Coverage
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7

      - name: Check secret consumers have Reloader annotations
        run: bash .github/tests/check-reloader.sh
```

No job-level `permissions:` (workflow-level `contents: read` covers it).
Match the checkout action version and comment style of the existing job.

**Verify**: `yamllint .github/workflows/flux-diff.yaml` → exit 0; `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/flux-diff.yaml'))"` → exit 0.

## Test plan

- The script's negative test (step 2) is the regression test: it proves the
  gate catches exactly the bug shape (secret ref, no annotation) and that a
  clean tree passes.
- No other test framework applies to GitHub workflows in this repo.

## Done criteria

- [ ] `bash .github/tests/check-reloader.sh` exits 0 on the current tree
- [ ] Negative test file made the script exit 1, then was deleted (`git status` clean of it)
- [ ] `flux-diff.yaml` contains a `reloader-check:` job; `yamllint` and `yaml.safe_load` both pass
- [ ] `git diff --name-only` shows only the two in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

- The baseline is not clean: `check-reloader.sh` reports FAIL for any file
  other than wyoming-openai (plan 001 didn't land, or the tree drifted).
- `flux-diff.yaml` drifts from the "Current state" description (triggers,
  permissions, or job structure differ).

## Maintenance notes

- **Known limitation**: the gate only sees `secretRef`/`secretKeyRef` written
  in `helmrelease.yaml` files. Secrets passed via chart values (e.g.
  `existingSecret:`) are invisible to it. If that pattern spreads, extend the
  grep — don't silently assume coverage.
- New app from the app-template pattern: add the annotation at the same time
  as the secret reference; the gate enforces it.
- If an app legitimately should not reload (e.g. a CronJob with a fresh pod
  per run lives in its own `cronjob.yaml`, not `helmrelease.yaml` — already
  outside the scan), no exemption mechanism is needed. If one ever is, make
  it a deny-list inside the script with a comment per entry.
- A reviewer should check the script exits non-zero on the first FAIL (it
  does via `fail=1` + final `exit 1`, and `set -euo pipefail` guards the rest).
