# HolyClaude Helm Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy HolyClaude (`docker.io/coderluii/holyclaude`) as a new
`ai`-namespace app at `holyclaude.68cc.io`, using the bjw-s app-template
pattern, with Claude Code (OAuth subscription), TaskMaster AI (Perplexity),
and OpenCode enabled, everything under `/home/claude` persisted on one PVC.

**Architecture:** One `HelmRelease` (`OCIRepository` + `chartRef` against the
shared `app-template` OCIRepository already available in `ai`), one PVC
mounted at `/home/claude` (+ `/workspace` via `subPath`), a `gh-auth`
initContainer, and an Authentik-forwardAuth-gated `HTTPRoute` on
`traefik-external-gateway` — directly mirroring
`kubernetes/apps/ai/openclaw/`'s file layout and Flux wiring, with two
deliberate divergences: no custom `command:` override (the image's own
entrypoint already bootstraps itself) and no RBAC (no cluster API access
needed).

**Tech Stack:** FluxCD (Flux Operator pattern), Kustomize, Helm (`bjw-s`
app-template v4.6.2 via `chartRef`), SOPS + age, Traefik Gateway API,
Authentik forwardAuth, `openebs-hostpath` CSI.

**Spec:** `docs/superpowers/specs/2026-09-01-holyclaude-helm-deployment-design.md`

## Global Constraints

- Never set `containers.app.command`/`args` on the main container — the
  image's own `ENTRYPOINT` handles PUID/GID remap, credential restore, and
  first-boot bootstrap, then `exec /init` (s6-overlay). Overriding it breaks
  all of that. (Spec Decision §3/§8, Architecture note.)
- Image variant is always `full` — never switch to a `-slim` tag; OpenCode is
  compiled out of `slim` entirely. (Spec Decision §2.)
- Never set `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or
  `ANTHROPIC_BASE_URL` anywhere in this app — Claude Code must stay on its
  OAuth subscription session, not fall back to API-key auth. (Spec Decision
  §3, Environment variables §4.)
- `GIT_USER_NAME=BarryBot` / `GIT_USER_EMAIL=github+barrybot@beholdthehurricane.com`
  — exact values, not placeholders. (Spec Decision §9.)
- Image reference for every step in this plan:
  `docker.io/coderluii/holyclaude:1.5.7` with a
  `# renovate: datasource=docker depName=coderluii/holyclaude` comment on the
  `tag:` line, everywhere the image is referenced (main container and the
  `gh-auth` initContainer both use it).
- Every new/modified `kubernetes/apps/**/*.yaml` file must pass
  `kustomize build <app-dir> | kubectl apply --dry-run=client -f -` before
  being considered done (this repo's standard pre-commit check, per
  root `CLAUDE.md`). If `kubectl`/cluster connectivity is unavailable in the
  execution environment, `kustomize build <app-dir>` alone (no pipe) still
  validates the rendered YAML is well-formed and is the minimum bar — note
  in the task's completion message which level of validation actually ran.
- Every SOPS-encrypted file must pass `task sops:verify` before commit.
- Every controller that consumes a Secret/ConfigMap must carry
  `reloader.stakater.com/auto: "true"` on the pod template — verify with
  `kustomize build kubernetes/apps/ai/holyclaude/app | grep reloader.stakater`.
- Git policy: commit at the end of each task (small, reviewable commits),
  but do **not** `git push`, run `flux reconcile`, or take any other
  cluster-mutating action until the final task explicitly says to — and even
  then, only after the human operator confirms. This repo's CLAUDE.md
  default git profile is conservative (report status, wait for approval)
  unless a user has explicitly authorized push/reconcile for this session.

---

### Task 1: SOPS secrets

**Context:** Two secrets, both starting as `CHANGEME` placeholders (this
repo's standard idiom — see `openclaw-secret`'s `GITHUB_TOKEN`/
`DISCORD_BOT_TOKEN` gates) so the app deploys cleanly before real credentials
exist, and picks them up automatically via Reloader once real values land.

**Files:**
- Create: `kubernetes/apps/ai/holyclaude/app/secret.sops.yaml`

**Interfaces:**
- Produces: Secret `holyclaude-secret` (key `GITHUB_TOKEN`), Secret
  `holyclaude-taskmaster-secret` (key `PERPLEXITY_API_KEY`) — consumed by
  Task 2's `envFrom` and the `gh-auth` initContainer.

- [ ] **Step 1: Write the plaintext secret file**

```yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: holyclaude-secret
stringData:
  GITHUB_TOKEN: CHANGEME
---
apiVersion: v1
kind: Secret
metadata:
  name: holyclaude-taskmaster-secret
stringData:
  PERPLEXITY_API_KEY: CHANGEME
```

- [ ] **Step 2: Encrypt in place**

Run: `task sops:encrypt-file file=kubernetes/apps/ai/holyclaude/app/secret.sops.yaml`
Expected: exit 0; the file now has `sops:` metadata and `ENC[...]` values in
place of `CHANGEME`/`GITHUB_TOKEN`/`PERPLEXITY_API_KEY` (SOPS's
`encrypted_regex: ^(data|stringData)$` — see `.sops.yaml` — encrypts every
key under `stringData`, not just values).

- [ ] **Step 3: Verify encryption**

Run: `task sops:verify`
Expected: exit 0, no plaintext secrets reported for this file.

- [ ] **Step 4: Commit**

```bash
git add kubernetes/apps/ai/holyclaude/app/secret.sops.yaml
git commit -m "feat(ai): add holyclaude SOPS secrets (placeholder values)"
```

---

### Task 2: HelmRelease — controller, persistence, security context

**Context:** This is the core of the deployment. Build the full
`helmrelease.yaml` in one pass (it's one file, one clear responsibility —
"how HolyClaude runs") but validate it in two stages within this task: first
the controller/persistence/security shape (this task), then service/route
in Task 3, so a build failure is easy to localize.

**Files:**
- Create: `kubernetes/apps/ai/holyclaude/app/helmrelease.yaml`
- Create: `kubernetes/apps/ai/holyclaude/app/kustomization.yaml`

**Interfaces:**
- Consumes: Secret `holyclaude-secret` (key `GITHUB_TOKEN`), Secret
  `holyclaude-taskmaster-secret` (key `PERPLEXITY_API_KEY`) — from Task 1.
- Produces: HelmRelease `holyclaude` with controller `holyclaude`, Service
  port name `http` (3001) — Task 3 adds `service:`/`route:` blocks to this
  same file and depends on the controller name `holyclaude` matching.

- [ ] **Step 1: Write `app/kustomization.yaml`**

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./secret.sops.yaml
  - ./helmrelease.yaml
```

- [ ] **Step 2: Write `app/helmrelease.yaml` (controller + persistence + security context, no service/route yet)**

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: &app holyclaude
spec:
  interval: 1h
  chartRef:
    kind: OCIRepository
    name: app-template
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  values:
    controllers:
      holyclaude:
        annotations:
          reloader.stakater.com/auto: "true"
        initContainers:
          gh-auth:
            image:
              repository: docker.io/coderluii/holyclaude
              # renovate: datasource=docker depName=coderluii/holyclaude
              tag: 1.5.7
            env:
              HOME: /home/claude
            envFrom:
              - secretRef:
                  name: holyclaude-secret
            command:
              - sh
              - -c
              - |
                set -eu
                if [ -n "${GITHUB_TOKEN:-}" ] && [ "$GITHUB_TOKEN" != "CHANGEME" ]; then
                  printf '%s' "$GITHUB_TOKEN" | env -u GITHUB_TOKEN gh auth login --with-token >/dev/null 2>&1 \
                    && echo "gh: credentials persisted" || echo "WARN: gh auth failed"
                fi
        containers:
          app:
            image:
              repository: docker.io/coderluii/holyclaude
              # renovate: datasource=docker depName=coderluii/holyclaude
              tag: 1.5.7
            # NOTE: no command/args override -- the image's own ENTRYPOINT
            # handles PUID/GID remap, credential restore, and first-boot
            # bootstrap, then execs s6-overlay as PID 1. See Global
            # Constraints above.
            env:
              TZ: America/New_York
              PUID: "1000"
              PGID: "1000"
              NODE_OPTIONS: "--max-old-space-size=4096"
              GIT_USER_NAME: BarryBot
              GIT_USER_EMAIL: github+barrybot@beholdthehurricane.com
              HOLYCLAUDE_DESLOPPIFY_SETUP: "claude,opencode"
            envFrom:
              - secretRef:
                  name: holyclaude-secret
              - secretRef:
                  name: holyclaude-taskmaster-secret
            securityContext:
              capabilities:
                add: ["SYS_ADMIN", "SYS_PTRACE"]
              seccompProfile:
                type: Unconfined
              readOnlyRootFilesystem: false
            probes:
              liveness:
                enabled: true
              readiness:
                enabled: true
              startup:
                enabled: true
                spec:
                  failureThreshold: 30
                  periodSeconds: 10
            resources:
              requests:
                cpu: 250m
                memory: 1Gi
              limits:
                memory: 6Gi
    persistence:
      home:
        type: persistentVolumeClaim
        storageClass: openebs-hostpath
        accessMode: ReadWriteOnce
        size: 50Gi
        retain: true
        globalMounts:
          - path: /home/claude
          - path: /workspace
            subPath: workspace
      shm:
        type: emptyDir
        medium: Memory
        sizeLimit: 2Gi
```

- [ ] **Step 3: Validate the build**

Run: `kustomize build kubernetes/apps/ai/holyclaude/app`
Expected: renders a `Secret`, `Secret`, and `HelmRelease` (the app-template
chart itself isn't rendered by `kustomize build` — that only happens at
Flux/Helm-controller reconcile time — so this step confirms the *Kustomize*
layer is well-formed, not the final Kubernetes objects the chart produces).
No errors.

If `kubectl` cluster connectivity is available:
Run: `kustomize build kubernetes/apps/ai/holyclaude/app | kubectl apply --dry-run=client -f -`
Expected: exit 0, `secret/holyclaude-secret created (dry run)`,
`secret/holyclaude-taskmaster-secret created (dry run)`,
`helmrelease.helm.toolkit.fluxcd.io/holyclaude created (dry run)`.

- [ ] **Step 4: Verify the reloader annotation landed**

Run: `kustomize build kubernetes/apps/ai/holyclaude/app | grep reloader.stakater`
Expected: at least one match (`reloader.stakater.com/auto: "true"` under
`spec.values.controllers.holyclaude.annotations`).

- [ ] **Step 5: Commit**

```bash
git add kubernetes/apps/ai/holyclaude/app/kustomization.yaml kubernetes/apps/ai/holyclaude/app/helmrelease.yaml
git commit -m "feat(ai): add holyclaude HelmRelease controller and persistence"
```

---

### Task 3: HelmRelease — service and route

**Context:** Adds the `service:` and `route:` blocks to the same
`helmrelease.yaml` from Task 2, wiring `holyclaude.68cc.io` through
`traefik-external-gateway` with the `authentik-forwardauth` Middleware — the
same external-access pattern `openclaw.68cc.io` uses.

**Files:**
- Modify: `kubernetes/apps/ai/holyclaude/app/helmrelease.yaml`

**Interfaces:**
- Consumes: controller name `holyclaude` (the `&app` YAML anchor defined in
  Task 2's `metadata.name`), container port `3001` (CloudCLI's own listen
  port, not user-configurable — confirmed in the spec's Research basis from
  `docker-compose.yaml`).
- Produces: Service `holyclaude` port `http` (3001), HTTPRoute `holyclaude`
  at `holyclaude.68cc.io`.

- [ ] **Step 1: Add `service:` and `route:` under `spec.values`, alongside the existing `persistence:` block**

In `kubernetes/apps/ai/holyclaude/app/helmrelease.yaml`, after the closing
of `persistence:` (i.e. as a sibling key under `values:`), add:

```yaml
    service:
      app:
        controller: *app
        ports:
          http:
            primary: true
            port: 3001
    route:
      app:
        hostnames: ["holyclaude.68cc.io"]
        annotations:
          external-dns.alpha.kubernetes.io/target: 192.168.35.15
        parentRefs:
          - name: traefik-external-gateway
            namespace: network
        rules:
          - filters:
              - type: ExtensionRef
                extensionRef:
                  group: traefik.io
                  kind: Middleware
                  name: authentik-forwardauth
            backendRefs:
              - name: *app
                port: 3001
```

- [ ] **Step 2: Validate the build**

Run: `kustomize build kubernetes/apps/ai/holyclaude/app`
Expected: same as Task 2 Step 3, still renders cleanly — the `service:`/
`route:` additions are inside the `HelmRelease`'s `spec.values`, an opaque
blob to `kustomize build` (Helm's own schema validation happens at
Flux-reconcile time, not here), so this step mainly confirms the YAML is
still syntactically valid after the edit.

If `flux` CLI + cluster connectivity is available:
Run: `flux build kustomization holyclaude --path kubernetes/apps/ai/holyclaude/app --dry-run`
(Note: this specific command requires the Flux `Kustomization` object named
`holyclaude` to exist and be resolvable, which Task 4 creates — if this
command isn't runnable yet at this point in the plan, defer this specific
check to Task 4's validation step and just confirm `kustomize build`
succeeds here.)

- [ ] **Step 3: Commit**

```bash
git add kubernetes/apps/ai/holyclaude/app/helmrelease.yaml
git commit -m "feat(ai): expose holyclaude via traefik-external + authentik forwardauth"
```

---

### Task 4: Flux Kustomization + namespace wiring

**Context:** Every app under `kubernetes/apps/ai/` needs a Flux
`Kustomization` (`ks.yaml`) pointing at its `app/` directory, and that
`ks.yaml` must be explicitly listed in `kubernetes/apps/ai/kustomization.yaml`'s
`resources:` — confirmed by inspecting how `openclaw/ks.yaml` is wired in;
it is **not** auto-discovered.

**Files:**
- Create: `kubernetes/apps/ai/holyclaude/ks.yaml`
- Modify: `kubernetes/apps/ai/kustomization.yaml`

**Interfaces:**
- Consumes: path `./kubernetes/apps/ai/holyclaude/app` (must exist and
  build cleanly — produced by Tasks 1-3).
- Produces: Flux `Kustomization` named `holyclaude` in namespace `ai`.

- [ ] **Step 1: Write `kubernetes/apps/ai/holyclaude/ks.yaml`**

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app holyclaude
  namespace: &namespace ai
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  path: ./kubernetes/apps/ai/holyclaude/app
  prune: true
  retryInterval: 2m
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: *namespace
  timeout: 5m
  wait: false
```

(No `dependsOn` — HolyClaude has no in-cluster service dependency, unlike
`openclaw`'s dependency on `llama-swap`.)

- [ ] **Step 2: Add `holyclaude` to the `ai` namespace's resources list**

In `kubernetes/apps/ai/kustomization.yaml`, find the `resources:` block
(currently includes `./openclaw/ks.yaml` among others) and add
`./holyclaude/ks.yaml`, keeping the existing alphabetical ordering — it
sorts between `./faster-whisper/ks.yaml` and `./litellm/ks.yaml` (or
whatever the current neighbors are; match the file's existing alphabetical
convention rather than appending to the end).

- [ ] **Step 3: Validate the full namespace build**

Run: `kustomize build kubernetes/apps/ai | kubectl apply --dry-run=client -f - 2>&1 | grep -v "^namespace/ai"`
Expected: no errors; output includes `holyclaude`'s `Secret`s and
`HelmRelease`, plus everything else already in the namespace (openclaw,
llama-swap, etc.) unchanged.

If `flux` CLI + cluster connectivity is available:
Run: `flux build kustomization holyclaude --path kubernetes/apps/ai/holyclaude/app --dry-run`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add kubernetes/apps/ai/holyclaude/ks.yaml kubernetes/apps/ai/kustomization.yaml
git commit -m "feat(ai): wire holyclaude Kustomization into the ai namespace"
```

---

### Task 5: Automated manifest review

**Context:** This repo has three specialized read-only review agents built
exactly for this kind of change. Run them before touching documentation or
pushing anything, so any schema/convention issue they catch gets fixed
before the final commit.

**Files:** none (review-only; fixes, if any, land as amendments to files
from Tasks 1-4)

**Interfaces:** none (this task consumes the files produced by Tasks 1-4 and
produces no new interface — it's a gate, not a build step)

- [ ] **Step 1: Run the Flux manifest reviewer**

Dispatch the `flux-manifest-reviewer` agent against
`kubernetes/apps/ai/holyclaude/` (HelmRelease/Kustomization schema
conventions, missing annotations, convention drift).

- [ ] **Step 2: Run the HelmRelease values reviewer**

Dispatch the `helmrelease-values-reviewer` agent against
`kubernetes/apps/ai/holyclaude/app/helmrelease.yaml` (bjw-s app-template
v4.6.2 values schema — unknown keys, type mismatches).

- [ ] **Step 3: Run the kubeconform validator**

Dispatch the `kubeconform-validator` agent against
`kubernetes/apps/ai/holyclaude/` (schema validation of rendered manifests
against upstream + CRD schemas).

- [ ] **Step 4: Fix any findings**

For each finding reported by the three agents above: apply the fix directly
to the relevant file from Tasks 1-4, then re-run
`kustomize build kubernetes/apps/ai/holyclaude/app` to confirm the fix
didn't break the build. If a finding is a false positive (e.g. it flags
something this plan's spec deliberately decided, like the root
securityContext), do not change the code — note in the commit message why
it was intentionally not addressed.

- [ ] **Step 5: Commit any fixes**

```bash
git add kubernetes/apps/ai/holyclaude/
git commit -m "fix(ai): address holyclaude manifest review findings"
```

(Skip this commit entirely if Step 4 found nothing to fix.)

---

### Task 6: Namespace documentation

**Context:** `kubernetes/apps/ai/CLAUDE.md` documents every currently
deployed app in the namespace, plus a "Decisions explicitly rejected"
section that already covers OpenCode's prior rejection (as part of the
2026-08-14 Kelos/n8n/OpenCode/agent-canvas/cognee removal) and the
AMD GPU Operator's scoped-exception precedent (the structural template to
follow here). This task adds HolyClaude's entry and documents the two policy
exceptions it creates, per spec Goals/Decisions §1 and §4.

**Files:**
- Modify: `kubernetes/apps/ai/CLAUDE.md`

**Interfaces:** none (documentation only)

- [ ] **Step 1: Add a "Currently deployed" entry**

In the `## Currently deployed` section, add a new bullet (alongside the
existing `openclaw`/`argus`/`openviking` bullets), describing: HolyClaude at
`holyclaude.68cc.io` (Authentik forwardAuth), a deliberate interactive
cloud-Claude workstation distinct from openclaw's autonomous local-only
role; Claude Code (OAuth subscription login), TaskMaster AI (Perplexity
key), and OpenCode enabled — Gemini/Codex/Cursor/Junie/Pi Coding Agent
installed but uncredentialed; single PVC at `/home/claude` +
`/workspace`; CloudCLI's own web terminal for interactive CLI access, no
code-server sidecar; root + `SYS_ADMIN`/`SYS_PTRACE`/`seccomp: Unconfined`
required for the sandboxed Chromium/Playwright stack.

- [ ] **Step 2: Add a scoped-exception note**

In (or near) the `## Decisions explicitly rejected` section, add a note in
the same structural style as the AMD GPU Operator entry (bold summary line,
then the scoped-exception paragraph): HolyClaude is a narrow, documented
exception to both the "no third-party/cloud LLM providers" namespace policy
and the prior OpenCode rejection — scoped specifically to this one
interactive, human-driven container, never extended to openclaw or any
automation/cron/webhook-triggered context. openclaw remains the sole
autonomous code-automation agent using only local inference.

- [ ] **Step 3: Commit**

```bash
git add kubernetes/apps/ai/CLAUDE.md
git commit -m "docs(ai): document holyclaude and its scoped policy exceptions"
```

---

### Task 7: Final validation, review with the user, then push/reconcile

**Context:** Everything up to here is local and reversible. This task is
the one place this plan touches shared state (git remote, live cluster) —
per Global Constraints, this only proceeds after the human operator
confirms, matching this repo's conservative git/deploy policy.

**Files:** none

**Interfaces:** none

- [ ] **Step 1: Run the full local validation suite**

```bash
task sops:verify
kustomize build kubernetes/apps/ai/holyclaude/app | kubectl apply --dry-run=client -f -
kustomize build kubernetes/apps/ai | kubectl apply --dry-run=client -f - 2>&1 | grep -v "^namespace/ai"
flux build kustomization holyclaude --path kubernetes/apps/ai/holyclaude/app --dry-run
```
Expected: all four exit 0. If `kubectl`/`flux` cluster connectivity isn't
available in the execution environment, run whichever subset does work and
report exactly which checks could and couldn't run — don't claim a check
passed that wasn't actually executed.

- [ ] **Step 2: Show the user `git log --oneline` for this branch and the full diff since the plan started**

```bash
git log --oneline main..HEAD
git diff main..HEAD --stat
```
Present this to the user and ask for explicit go-ahead before Step 3.

- [ ] **Step 3: Push (only after explicit user confirmation)**

```bash
git push
```

- [ ] **Step 4: Reconcile (only after explicit user confirmation)**

```bash
flux reconcile kustomization flux-system --with-source
flux reconcile kustomization ai --with-source
```

- [ ] **Step 5: Confirm the app came up**

```bash
kubectl -n ai get pods -l app.kubernetes.io/name=holyclaude
kubectl -n ai get helmrelease holyclaude
kubectl -n ai get httproute holyclaude
```
Expected: pod `Running` and `Ready`, HelmRelease `Ready: True`, HTTPRoute
accepted.

- [ ] **Step 6: Hand off manual post-deploy steps to the user**

These cannot be done by an agent (they require an interactive browser
session against a real Anthropic account and a human choosing a CloudCLI
password) — report them to the user as the remaining steps to actually use
the app:

1. Visit `https://holyclaude.68cc.io`, complete Authentik SSO.
2. Complete CloudCLI's own first-run account setup (per spec §7, this is a
   second, independent auth layer on top of Authentik).
3. From CloudCLI, run `claude` and complete the interactive OAuth
   device-flow login against your Claude Max/Pro subscription.
4. Restart the pod (`kubectl -n ai delete pod -l app.kubernetes.io/name=holyclaude`)
   and confirm you are **not** re-prompted for the Claude Code login —
   this is the actual test that PVC persistence of the OAuth session works
   (spec Verification plan, item 1).
5. Open CloudCLI's web terminal specifically (not just the chat UI) and
   confirm it connects — this is the WebSocket-through-the-full-ingress-chain
   smoke test called out as an open risk in the spec (§ Open risks, item 4).
   From the terminal, confirm `task-master` and `opencode` are both on
   `$PATH` and each runs without error.
6. Set the real `GITHUB_TOKEN` and `PERPLEXITY_API_KEY` values in
   `kubernetes/apps/ai/holyclaude/app/secret.sops.yaml` (via
   `task sops:edit file=kubernetes/apps/ai/holyclaude/app/secret.sops.yaml`),
   commit, push, and reconcile — Reloader will restart the pod automatically
   once the new Secret content lands.

No commit for this task (it's validation + a live deploy + a handoff, not a
code change).
