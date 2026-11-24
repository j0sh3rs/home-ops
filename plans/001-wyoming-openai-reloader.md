# Plan 001: Add reloader annotation to wyoming-openai so oMLX key rotation is picked up

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 8b27891f..HEAD -- kubernetes/apps/ai/wyoming-openai/`
> If the file changed since this plan was written, compare the "Current state"
> excerpt against the live code before proceeding; on a mismatch, treat it as
> a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `8b27891f`, 2026-11-24

## Why this matters

The wyoming-openai pod is a long-running Wyoming↔OpenAI audio bridge that
reads its STT/TTS API keys from `wyoming-openai-secret` via `envFrom`. That
secret carries the oMLX `voice-bridge` sub-key, which is rotated whenever the
Mac Studio's oMLX stack re-keys. Without a Reloader annotation, the pod keeps
the old key in memory after rotation until someone manually rolls it out —
Home Assistant Assist voice (STT/TTS) silently breaks. The cluster already
runs stakater Reloader in `kube-system`, and every other AI app that consumes
a secret carries the annotation; wyoming-openai is the sole gap (verified by
scan of all `helmrelease.yaml` files referencing `secretRef`/`secretKeyRef`).

## Current state

- `kubernetes/apps/ai/wyoming-openai/app/helmrelease.yaml` — the app. Key excerpt (lines 45–47):

  ```yaml
          # STT_OPENAI_KEY and TTS_OPENAI_KEY: the `voice-bridge` oMLX sub key.
          envFrom:
            - secretRef:
                name: wyoming-openai-secret
  ```

  There is **no** `reloader.stakater.com/…` key anywhere in this file.
- `kubernetes/apps/ai/atuin-ai-server/app/helmrelease.yaml` — the exemplar
  (same app-template pattern, consumes a secret). Lines 24–26:

  ```yaml
          values:
            controllers:
              atuin-ai-server:
                replicas: 1
                strategy: RollingUpdate
                annotations:
                  reloader.stakater.com/auto: "true"
  ```

  The annotation sits at **controller level** under
  `values.controllers.<app-name>`. Ten other AI apps use the identical key —
  match it exactly.
- Reloader is deployed at `kubernetes/apps/kube-system/reloader/`
  (stakater/reloader chart 2.2.21, cluster-wide watch of Secrets/ConfigMaps).
  With `auto: "true"` it restarts the pod when any secret it references
  changes.
- Repo convention: `annotations` (not `podAnnotations`) under
  `values.controllers.<app>` is this repo's app-template idiom for Reloader.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Lint | `yamllint kubernetes/apps/ai/wyoming-openai/app/helmrelease.yaml` | exit 0, no output |
| Annotation present | `grep -n "reloader.stakater.com" kubernetes/apps/ai/wyoming-openai/app/helmrelease.yaml` | one match: `reloader.stakater.com/auto: "true"` |
| (optional, needs cluster) Pod picked up | `kubectl -n ai get deploy wyoming-openai -o jsonpath='{.spec.template.metadata.annotations}'` | JSON contains `reloader.stakater.com/auto` |

If `yamllint` is not on PATH, run `mise exec yamllint -- yamllint <file>`
or rely on the pre-commit hook (the repo has a yamllint hook).

## Scope

**In scope** (the only file you may modify):
- `kubernetes/apps/ai/wyoming-openai/app/helmrelease.yaml`

**Out of scope** (do NOT touch):
- Any other app's `helmrelease.yaml` — other reloader gaps, if they exist,
  are handled by plan 002's CI gate, not here.
- `kubernetes/apps/ai/wyoming-openai/app/*` other files (kustomization,
  ocirepository, secret).
- The Reloader deployment itself.

## Git workflow

- Branch: `advisor/001-wyoming-openai-reloader`
- Commit message style (match repo): `fix(ai): add reloader annotation to wyoming-openai`
- Do NOT push or open a PR unless instructed.

## Steps

### Step 1: Add the annotation

In `kubernetes/apps/ai/wyoming-openai/app/helmrelease.yaml`, inside
`values:`, add an `annotations:` block at the same level as `controllers`'s
child for `wyoming-openai` — i.e. under `values.controllers.wyoming-openai`,
before `containers:`:

```yaml
  values:
    controllers:
      wyoming-openai:
        annotations:
          reloader.stakater.com/auto: "true"
        containers:
          app:
            …
```

Exactly two lines added, 2-space indent steps matching the file.

**Verify**: `grep -n "reloader.stakater.com" kubernetes/apps/ai/wyoming-openai/app/helmrelease.yaml` → exactly one match, `reloader.stakater.com/auto: "true"`.

### Step 2: Lint

**Verify**: `yamllint kubernetes/apps/ai/wyoming-openai/app/helmrelease.yaml` → exit 0, no findings.

## Test plan

No unit test framework exists for Flux manifests in this repo. The
verification is:

1. The grep check above (annotation present, correct key, quoted `"true"` —
   unquoted `true` would render as a boolean and the Reloader chart expects a
   string).
2. Optional live check (only if `kubectl` reaches the cluster): after the
   commit is synced by Flux, the deployment's pod template carries the
   annotation. If there is no cluster access, skip — say so in the final
   report. Do not attempt to trigger a rollout yourself.

## Done criteria

- [ ] `grep -c "reloader.stakater.com/auto" kubernetes/apps/ai/wyoming-openai/app/helmrelease.yaml` → `1`
- [ ] `yamllint` on the file exits 0
- [ ] `git diff --name-only` shows only `kubernetes/apps/ai/wyoming-openai/app/helmrelease.yaml`
- [ ] `plans/README.md` status row updated

## STOP conditions

- The file at the cited location no longer contains the `envFrom: secretRef:
  wyoming-openai-secret` block (drift).
- The file already contains any `reloader.stakater.com/` key.
- Adding the annotation breaks `yamllint` after a second fix attempt.

## Maintenance notes

- If wyoming-openai gains a ConfigMap it must react to, `auto: "true"` already
  covers it — no change needed.
- A reviewer should confirm the annotation is at controller level (as in
  atuin-ai-server), not container level — both work with Reloader, but this
  repo standardizes on controller level for this chart shape.
- Plan 002 adds a CI gate that fails on any app with a secret reference and
  no Reloader annotation; this plan is what keeps that gate green.
