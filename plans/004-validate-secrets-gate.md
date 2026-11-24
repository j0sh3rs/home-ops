# Plan 004: Make the plaintext-secret scan in validate-secrets an actual gate

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8b27891f..HEAD -- .github/workflows/validate-secrets.yaml .github/ kubernetes/apps/`
> If in-scope files changed since this plan was written, compare the
> "Current state" excerpt against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.
> **Ordering**: run this plan *after* plan 003 — plan 003 deletes
> `.github/tests/{nodes,private,public}.yaml`, which would otherwise pollute
> the allowlist seeded in step 2.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (the gate can annoy; it cannot break deployments)
- **Depends on**: plans/003-readme-and-dead-files-cleanup.md (allowlist
  seeding)
- **Category**: security
- **Planned at**: commit `8b27891f`, 2026-11-24

## Why this matters

`.github/workflows/validate-secrets.yaml` has two steps. Step 1 (SOPS
encryption of `*.sops.yaml`) is a real gate. Step 2 ("Check for Accidentally
Committed Plaintext Secrets") matches secret-looking keys
(`password:`, `secret:`, `token:`, `api[_-]?key:`, `private[_-]?key:`) in
non-sops YAML files, prints ⚠️ warnings, and **always exits 0** — the
`EXIT_CODE` variable it initializes is never set. The README claims this gate
"blocks" plaintext secrets. Two independent gaps: (1) the scan never fails,
and (2) the workflow's `paths:` trigger only fires for `**/*.sops.yaml` and
`.sops.yaml` changes, so a PR that adds a plain `secret.yaml` with
plaintext `stringData` runs no scan at all. The pre-commit hook
(`k8s-at-home/sops-pre-commit` `forbid-secrets`) is the first line of defense;
it is bypassed by `git commit --no-verify` and never runs for external PRs.
This plan makes CI a real second line.

## Current state

- `.github/workflows/validate-secrets.yaml` — the workflow. Trigger block:

  ```yaml
  on:
    pull_request:
      paths:
        - "**/*.sops.yaml"
        - ".sops.yaml"
    push:
      branches:
        - main
      paths:
        - "**/*.sops.yaml"
        - ".sops.yaml"
  ```

- Step 2, "Check for Accidentally Committed Plaintext Secrets", ends with:

  ```bash
        if [ ! -z "$MATCHES" ]; then
          echo "⚠️  Found potential secrets (pattern: $pattern):"
          echo "$MATCHES" | sed 's/^/    /'
          echo "    Please verify these files don't contain real secrets."
          echo "    If they do, move to *.sops.yaml files and encrypt."
          echo ""
        fi
      done

      echo "✅ Plaintext secret scan completed"
  ```

  — no `exit $EXIT_CODE` (or any `exit 1` path). The same file set and the
  same five ERE patterns are kept; the search mechanics become a
  `while IFS= read -r` loop over `find` (filename-safe, and grep read
  errors fail the gate instead of being swallowed by `|| true`).
- Step 1 (encryption check) is untouched by this plan.
- `README.md` row for this workflow already says "or un-allowlisted plaintext
  secret patterns" after plan 003 lands.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Generate allowlist | see step 2 command | one sorted relative path per line |
| Gate (clean tree) | `bash /tmp/secret-scan.sh` (extracted script, step 3) | exit 0 |
| Workflow lint | `yamllint .github/workflows/validate-secrets.yaml` | exit 0 |

## Scope

**In scope**:
- `.github/workflows/validate-secrets.yaml` (modify)
- `.github/secret-scan-allowlist.txt` (create)

**Out of scope**:
- Step 1 (the SOPS encryption check) — it already works; don't rework it.
- `.sops.yaml`, any `*.sops.yaml`, the pre-commit config.

## Git workflow

- Branch: `advisor/004-validate-secrets-gate`
- Commit style: `ci: fail plaintext-secret scan on un-allowlisted matches`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Widen the trigger

In the `on:` block, add to **both** `pull_request.paths` and `push.paths`:

```yaml
      - "**/*.yaml"
      - "**/*.yml"
```

Keep the existing `**/*.sops.yaml` and `.sops.yaml` entries (step 1 still
depends on them; duplicates are harmless but redundant — remove them if you
prefer, since `**/*.yaml` covers `*.sops.yaml`).

**Verify**: `python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/validate-secrets.yaml')); print(d[True]['pull_request']['paths'])"` (note: YAML parses bare `on` as boolean `True`) → list includes `**/*.yaml` and `**/*.yml`.

### Step 2: Create the allowlist from a live scan

Run this (from repo root, **after plan 003 is merged or its deletion is
present in the working tree**):

```bash
set -o pipefail
FILELIST="$(mktemp)"
OUT="$(mktemp)"
if ! git ls-files -z '*.yaml' '*.yml' > "$FILELIST"; then
  echo "scan error: git ls-files failed" >&2
  rm -f "$FILELIST" "$OUT"
  exit 1
fi
if ! {
  while IFS= read -r -d '' f; do
    case "$f" in *.sops.yaml) continue ;; esac
    if grep -iq -E "password:|secret:|token:|api[_-]?key:|private[_-]?key:" -- "$f" 2>/dev/null; then
      printf '%s\n' "$f"
    else
      rc=$?
      if [ "$rc" -gt 1 ]; then
        echo "scan error on $f (grep rc=$rc)" >&2
        exit 1
      fi
    fi
  done < "$FILELIST" | sort > "$OUT"
}; then
  echo "scan error: pipeline failed" >&2
  rm -f "$FILELIST" "$OUT"
  exit 1
fi
mv -f "$OUT" .github/secret-scan-allowlist.txt
rm -f "$FILELIST"
```

Inspect the result. It should be ~37 tracked files: app `helmrelease.yaml`
files whose `secret:`/`token:` keys reference SOPS-managed secrets,
`.github/workflows/*.yaml`, `.taskfiles/template/Taskfile.yaml`, and files
under `archive/`. The four gitignored `talos/clusterconfig/*.yaml` files are
deliberately out of scope — they are absent from every git checkout, so the
CI gate can never see them; they were found to hold real plaintext values
(see STOP conditions) and were reported to the user separately. Every
allowlist entry is a *known-legitimate, reviewed* file; new tracked files
matching the patterns will fail until deliberately allowlisted.

**Verify**: `wc -l .github/secret-scan-allowlist.txt` → between 20 and 40;
`head .github/secret-scan-allowlist.txt` → relative paths only, no `./`
prefix, sorted.

### Step 3: Make step 2 of the workflow a real gate

Replace the body of the "Check for Accidentally Committed Plaintext Secrets"
step (from `EXIT_CODE=0` to the final `echo "✅ Plaintext secret scan
completed"`) with:

```yaml
      - name: Check for Accidentally Committed Plaintext Secrets
        run: |
          ALLOWLIST=".github/secret-scan-allowlist.txt"
          UNALLOWED=""
          FILELIST="$(mktemp)"
          if ! git ls-files -z '*.yaml' '*.yml' > "$FILELIST"; then
            echo "💥 Secret scan error: file enumeration failed — failing the gate"
            exit 1
          fi

          for pattern in "password:" "secret:" "token:" "api[_-]?key:" "private[_-]?key:"; do
            while IFS= read -r -d '' f; do
              case "$f" in
                *.sops.yaml) continue ;;
              esac
              if grep -iq -E "$pattern" -- "$f" 2>/dev/null; then
                rel="$f"
                if ! grep -qxF "$rel" "$ALLOWLIST"; then
                  echo "❌ Un-allowlisted file matches secret pattern '$pattern': $rel"
                  UNALLOWED="$UNALLOWED $rel"
                fi
              else
                rc=$?
                if [ "$rc" -gt 1 ]; then
                  echo "💥 Secret scan error on $f (grep rc=$rc) — failing the gate"
                  exit 1
                fi
                # rc=1 = no match; safe to continue
              fi
            done < "$FILELIST"
          done
          rm -f "$FILELIST"

          if [ -n "$UNALLOWED" ]; then
            echo ""
            echo "💥 Plaintext secret scan FAILED."
            echo "For each file above: if it holds real secrets, move them to a"
            echo "*.sops.yaml file and encrypt (task sops:encrypt-file). If the"
            echo "match is a legitimate key name (e.g. a secretRef), review it"
            echo "and add the path to .github/secret-scan-allowlist.txt (keep sorted)."
            exit 1
          fi
          echo "✅ Plaintext secret scan passed (all matches allowlisted)"
```

Notes: `grep -qxF` = exact whole-line match against the allowlist. `-E` is
REQUIRED on the per-pattern grep: the patterns use ERE (`[_-]?`); without
it, BRE treats `?` as literal and the `api[_-]?key:` / `private[_-]?key:`
patterns match nothing real. Scope is *tracked files* via `git ls-files -z`:
the gate runs on CI checkouts, which contain only tracked files, so the seed
and the gate scan the same file set in every environment — a filesystem
`find` would pick up local gitignored files (e.g. `talos/clusterconfig/`)
that the gate can never see, diverging the two. `git ls-files` C-quotes
unusual paths, so `-z` (NUL-separated) plus `read -r -d ''` keeps filenames
with spaces intact; it emits root-relative paths with no `./` prefix. The
`rc=$?` check enforces grep's exit contract: 0 = match, 1 = no match
(continue), >=2 = error (unreadable file, bad pattern) → the gate FAILS
instead of returning a clean verdict, unlike a bare `|| true`. Enumeration
is checked: `git ls-files` writes its output to a temp file and its exit
status is tested — a process substitution would make the status
unobservable, so an enumeration failure would silently yield a clean
verdict. The seed checks the loop-pipeline explicitly (`if ! { ... | sort
> "$OUT" }`) so a `sort` failure cannot be masked by the following cleanup
and publish a partial allowlist; the file is moved into place only on
success.

**Verify**: `yamllint .github/workflows/validate-secrets.yaml` → exit 0.

### Step 4: Negative and positive self-tests

Extract the step's `run:` body into `/tmp/secret-scan.sh` (wrap with
`#!/usr/bin/env bash`) and run it from the repo root. The gate only sees
*tracked* files, so each test file must be staged to be visible
(`git add` — staging only, never committed; staging a path tracks the path,
not its content, so no re-add is needed after overwrites):

1. Clean tree: `bash /tmp/secret-scan.sh` → exit 0, "scan passed".
2. `echo "password: hunter2-test" > ./zz-selftest.yaml && git add ./zz-selftest.yaml` → `bash /tmp/secret-scan.sh` → exit 1, names `zz-selftest.yaml`. Then overwrite the same file with `echo "api_key: hunter2-test" > ./zz-selftest.yaml` and again with `echo "api-key: hunter2-test" > ./zz-selftest.yaml` and again with `echo "private_key: hunter2-test" > ./zz-selftest.yaml` → exit 1 each time (proves the ERE variants are enforced, not just `password:`).
3. Add `zz-selftest.yaml` to a **temporary copy** of the allowlist (do not
   commit it) → scan exits 0.
4. Filename with spaces: `echo "password: hunter2-test" > "./zz selftest space.yaml" && git add "./zz selftest space.yaml"` → `bash /tmp/secret-scan.sh` → exit 1, and the `❌` line names `zz selftest space.yaml` verbatim (proves the NUL-separated read loop is filename-safe).
5. Unstage and remove the test files: `git rm --cached -q ./zz-selftest.yaml "./zz selftest space.yaml"` then `rm -f ./zz-selftest.yaml "./zz selftest space.yaml"`, and remove the temp allowlist copy.

**Verify**: after step 5, `git status` shows only the two in-scope files
changed; `bash /tmp/secret-scan.sh` → exit 0.

## Test plan

- The self-test battery (step 4) is the test: clean pass, un-allowlisted
  fail, allowlisted pass. It exercises the exact bug this plan fixes
  (scan that could never fail).
- The workflow's own step-1 behavior is unchanged; no new tests needed there.

## Done criteria

- [ ] Trigger paths include `**/*.yaml` and `**/*.yml` on both `pull_request` and `push`
- [ ] `.github/secret-scan-allowlist.txt` exists, sorted, 20–40 relative paths, no `./` prefixes
- [ ] The scan step contains an `exit 1` path on un-allowlisted matches
- [ ] Self-tests: clean pass / un-allowlisted fail (4 secret-key variants) / allowlisted pass / space-filename named verbatim; temp files removed
- [ ] `yamllint` on the workflow exits 0
- [ ] `git diff --name-only` shows only the two in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

The live scan (step 2) produces a list far outside 20–40 files, or includes
a file that *looks like it contains a real secret value* (e.g. a long
base64 blob under `data:`) — investigate that file before allowlisting
anything. If a real plaintext secret exists in a **tracked** file, STOP and
report it (reference path and secret type only, never the value); rotation
may be needed. Known and accepted: the four untracked, gitignored
`talos/clusterconfig/*.yaml` files hold real values — out of scope by
design (never in a checkout) and already reported to the user; do not STOP
on them.
- The workflow's trigger or step-1 structure differs from "Current state".

## Maintenance notes

- The allowlist is a reviewed-baseline, like a linter ignore-file: every
  addition is a decision, and PRs that grow it deserve a look at *why*.
- The patterns match key names, not values — a file can be allowlisted while
  still gaining a real secret later. The value-detection layer is gitleaks
  (pre-commit); keep the two layers distinct in any future rework.
- When a file is deleted, its allowlist entry becomes stale but harmless;
  prune opportunistically (a `grep -v` against `git ls-files` catches them).
- `archive/` files are allowlisted, not excluded: an archive file that newly
  matches a pattern still merits a human glance.
