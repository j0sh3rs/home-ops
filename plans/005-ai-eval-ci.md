# Plan 005: Run the tools/ai-eval test suite in CI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8b27891f..HEAD -- tools/ai-eval/`
> If in-scope files changed since this plan was written, compare the
> "Current state" excerpt against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `8b27891f`, 2026-11-24

## Why this matters

`tools/ai-eval/` is the replay/grading harness for the Mac Studio model
bake-off, and it ships with a complete unit-test suite: 7 test files under
`tools/ai-eval/tests/` (`test_corpus.py`, `test_grade.py`, `test_ha.py`,
`test_ha_suite.py`, `test_prefix_bench.py`, `test_replay.py`,
`test_voice_bench.py`) covering every module. Nothing runs them: no CI job,
no task, no reference to `pytest` anywhere in `.github/workflows/` or
`.taskfiles/`. The harness is the measurement instrument for model selection
decisions recorded in `README.md` and `docs/ai-history/` — a silent
regression in grading or replay logic would corrupt those measurements with
no alarm.

## Current state

- `tools/ai-eval/` layout: `replay.py, grade.py, corpus.py, ha.py, ha_suite.py,
  prefix_bench.py, voice_bench.py, memsample.sh, requirements.txt, README.md,
  tests/`.
- `tools/ai-eval/requirements.txt` (complete):

  ```
  jsonschema>=4.23,<5
  pyyaml>=6,<7
  jinja2>=3,<4
  ```

  Light dependencies, no C extensions — compatible with modern CPython
  (3.10+; the repo's `mise` toolchain is on 3.15, so nothing exotic).
- The documented test command (`tools/ai-eval/README.md`, §Setup):

  ```
  cd tools/ai-eval
  pip install --break-system-packages -r requirements.txt
  python3 -m pytest tests -q -p no:cacheprovider
  ```

  (`--break-system-packages` is the Mac's local-pip workaround; CI uses a
  throwaway runner and plain `pip install`.)
- `corpus/` and `results/` are gitignored (they hold personal data) — the
  tests are expected to be self-contained without them.
- Note: the advisor writing this plan could **not** run the suite
  (pytest is not installed on any local interpreter and the advisor is
  read-only). Step 1 of this plan is the executor establishing the local
  baseline.
- CI conventions (from `.github/workflows/flux-diff.yaml` and
  `.github/workflows/validate-secrets.yaml`):
  - `permissions:` block near the top (`contents: read` minimum).
  - `concurrency:` group `${{ github.workflow }}-${{ github.ref }}`,
    `cancel-in-progress: true`.
  - Checkout action pinned by SHA with a version comment:
    `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7`.
  - Workflow file header comment explaining purpose (match that style).
  - `validate-secrets.yaml` uses `runs-on: ubuntu-latest` for
  tool-independent jobs — do the same.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Local baseline (step 1) | `python3 -m venv /tmp/aieval-venv && /tmp/aieval-venv/bin/pip install -q -r tools/ai-eval/requirements.txt pytest && cd tools/ai-eval && /tmp/aieval-venv/bin/python -m pytest tests -q -p no:cacheprovider` | all tests pass, e.g. `N passed in X s` |
| Workflow lint | `yamllint .github/workflows/ai-eval-tests.yaml` | exit 0 |
| Workflow parses | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ai-eval-tests.yaml'))"` | exit 0 |

The venv in `/tmp` keeps the repo tree and the user's system Python
untouched (the README's `--break-system-packages` path must not be used).

## Scope

**In scope**:
- `.github/workflows/ai-eval-tests.yaml` (create)

**Out of scope**:
- Anything under `tools/ai-eval/` — if a test is broken, STOP (see
  conditions); do not fix the harness here.
- Scheduling (nightly/weekly runs) — deliberately not included; a
  scheduled *benchmark* run is a separate, larger decision (needs a corpus
  source and a live endpoint). This plan only gates the unit tests on PRs.

## Git workflow

- Branch: `advisor/005-ai-eval-ci`
- Commit style: `ci: run ai-eval test suite on pull requests`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Establish the local baseline

Run the "Local baseline" command above. Record the pass count
(e.g. `142 passed`).

**Verify**: exit 0, `N passed` with zero failures/errors.
If any test fails **before you changed anything**, STOP and report which —
a red baseline means CI would ship red, and the harness needs a separate
fix first.

### Step 2: Write the workflow

Create `.github/workflows/ai-eval-tests.yaml`:

```yaml
---
# Runs the tools/ai-eval unit test suite. The harness measures the model
# bake-offs documented in README.md / docs/ai-history/; these tests catch
# regressions in replay, grading, and corpus handling before they corrupt
# a measurement. Unit tests only — no corpus, no network, no API keys.
name: AI Eval Tests

on:
  pull_request:
    paths:
      - "tools/ai-eval/**"
      - ".github/workflows/ai-eval-tests.yaml"
  push:
    branches:
      - main
    paths:
      - "tools/ai-eval/**"

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  tests:
    name: pytest
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r tools/ai-eval/requirements.txt pytest

      - name: Run tests
        run: python -m pytest tools/ai-eval/tests -q -p no:cacheprovider
        working-directory: .
```

Two deliberate details:
- `pytest tools/ai-eval/tests` run from the repo root (the test files import
  sibling modules relative to `tools/ai-eval/`; if root-based invocation
  fails with import errors, switch the step to
  `working-directory: tools/ai-eval` and `python -m pytest tests -q
  -p no:cacheprovider` — verify both locally with the venv interpreter
  before committing the choice).
- `pytest` is not in `requirements.txt` (runtime deps only); install it in
  the CI step, and do not add it to `requirements.txt` (would change the
  Mac's `pip install` semantics).

**Verify**: `yamllint .github/workflows/ai-eval-tests.yaml` → exit 0; `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ai-eval-tests.yaml'))"` → exit 0.

**Verify invocation shape locally**:
`cd /Users/j0sh3rs/Documents/git/j0sh3rs/home-ops && /tmp/aieval-venv/bin/python -m pytest tools/ai-eval/tests -q -p no:cacheprovider` → same pass count as step 1. If this differs (import errors), use the `working-directory` variant and verify it the same way.

### Step 3: Negative sanity check of the trigger scope

Confirm the path filters mean a PR touching only, e.g.,
`kubernetes/apps/` will not run this workflow (read the final `on:` block —
`tools/ai-eval/**` is the only content path). No command needed; state the
result in your report.

## Test plan

- The pre-existing suite **is** the test plan: it must pass in CI exactly as
  it passes locally (same count as step 1).
- The local root-vs-working-directory invocation check (step 2) prevents the
  classic "green locally, red in CI" import-path divergence.
- No new unit tests are added by this plan.

## Done criteria

- [ ] Local baseline passed (count recorded in the report)
- [ ] `.github/workflows/ai-eval-tests.yaml` exists; `yamllint` and `yaml.safe_load` pass
- [ ] The exact invocation used in the workflow was verified locally with the same pass count
- [ ] `git diff --name-only` (and `git status` for untracked) shows only the new workflow file
- [ ] `plans/README.md` status row updated

## STOP conditions

- Step 1 baseline is red (any failure/error) — the harness itself needs a
  fix before CI makes that fix mandatory.
- A test requires `corpus/`, `results/`, or an `EVAL_API_KEY`-style
  environment variable (grep: `grep -n "os.environ\|corpus/" tools/ai-eval/tests/*.py`)
  in a way that makes CI runs impossible without personal data — report which
  test and why.
- The root-directory invocation and the `working-directory` invocation both
  fail locally.

## Maintenance notes

- If `requirements.txt` gains a dependency with a C extension, re-check the
  pinned `python-version` in the workflow against the new dependency's
  supported range.
- The `paths:` filter means harness changes gate on PRs but *main-only* drift
  (e.g. a toolchain bump breaking 3.12) surfaces only on the next
  `tools/ai-eval/**` PR. If that bites, widen the trigger or add a weekly
  schedule.
- Follow-up explicitly deferred: scheduled *benchmark* runs (replay + grade
  against live endpoints). That needs a corpus strategy and API-key
  handling in CI secrets — a separate decision, not this plan.
