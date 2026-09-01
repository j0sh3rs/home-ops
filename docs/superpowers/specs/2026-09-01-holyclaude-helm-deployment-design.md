# HolyClaude Helm Deployment — Design

Date: 2026-09-01
Status: Approved, pending implementation plan
Related: `kubernetes/apps/ai/openclaw/` (reference architecture — bjw-s
app-template pattern this design follows/diverges from throughout),
`kubernetes/apps/ai/CLAUDE.md` (namespace policy this design carves an
explicit exception into)

## Context

The user wants a persistent, self-managed "Claude Code" workstation running
in-cluster: [HolyClaude](https://github.com/CoderLuii/HolyClaude) (upstream,
`CoderLuii/HolyClaude`, MIT-style container project) is a Docker image that
bundles the real Anthropic Claude Code CLI, a browser-based UI ("CloudCLI",
port 3001) with an in-browser terminal, up to 7 other AI coding-agent CLIs,
and ~50 general dev tools (git, gh, ripgrep, tmux, ffmpeg, headless Chromium +
Playwright, database clients, deployment CLIs) into one container, with a
built-in persistence layer for CLI config/credentials.

This is deliberately different from `openclaw`
(`kubernetes/apps/ai/openclaw/`), this cluster's existing code-automation
agent: openclaw is a headless, autonomous Gateway wired to local-only
inference (llama-swap) and cron/webhook-triggered work loops, in service of
this repo's explicit "fully self-hosted, no third-party/cloud LLM providers"
policy (`kubernetes/apps/ai/CLAUDE.md`). HolyClaude is the opposite shape: an
interactive, human-driven dev environment authenticated against the user's
own Claude Max/Pro subscription (a real Anthropic cloud dependency), used
directly by the user through a browser, never invoked autonomously or wired
into any automation trigger.

### Research basis

An 8-way parallel research pass read HolyClaude's actual source verbatim
(`Dockerfile`, `scripts/entrypoint.sh`, `scripts/bootstrap.sh`,
`scripts/prepare-cli-persistence.sh`, `scripts/secure-cli-persistence.py`,
all four `s6-overlay/s6-rc.d/*/run` services, `README.md`,
`docs/configuration.md`, all three `docker-compose*.yaml` variants, and the
Docker Hub tags API), cross-checked against `openclaw`'s live
`helmrelease.yaml`/`kustomization.yaml`/`rbac.yaml` as the reference pattern.
Key findings that shape this design:

- **No GHCR mirror exists** — `docker.io/coderluii/holyclaude` is the only
  registry. Real semver tags exist (`1.1.1`–`1.5.7`, plus a `-slim` suffix
  family and ~155 noisy `candidate-<sha>-*` CI tags), so Renovate can track
  this normally on the bare `X.Y.Z` tag — it is not a `latest`-only image.
- **OpenCode is compiled out of the `slim` build entirely** (`npm i -g
  opencode-ai` is gated `if [ "$VARIANT" = "full" ]` in the Dockerfile) — the
  `full` variant is mandatory. This unavoidably also bakes in Junie and Pi
  Coding Agent (no per-CLI build flag exists, only the all-or-nothing
  `VARIANT` arg), but they get no credentials and are simply inert unused
  binaries.
- **HolyClaude's own `docker-compose.yaml` only bind-mounts `~/.claude` and
  `/workspace`** — this actually misses OpenCode's own config
  (`~/.config/opencode`), which upstream's compose files never persist.
  Mounting the entire `/home/claude` as one volume (mirroring openclaw's
  `persistence.config.globalMounts: [{path: *homepath}]` pattern) fixes this
  gap for free and is simpler than replicating upstream's narrower mount set.
- **Claude Code's OAuth session persistence is not a Kubernetes Secret at
  all.** `entrypoint.sh` runs `node persist-claude-json.mjs` on every boot,
  which (per its own comment) keeps a durable copy of the live
  `~/.claude.json` (which Claude Code rewrites directly) inside the
  bind-mounted `~/.claude/` tree, and restores it before the rest of boot
  proceeds. The actual OAuth device-flow login is a one-time interactive step
  performed through CloudCLI or its web terminal; once done, the resulting
  session survives pod restarts purely because it lives on the PVC.
- **`prepare-cli-persistence.sh`/`secure-cli-persistence.py` persist exactly
  two tools: git and gh** (confirmed by grep against every other tool name in
  both scripts — zero matches). Any other tool's persistence (Claude Code's
  own `.claude.json`, OpenCode's `.config/opencode`, CloudCLI's `auth.db`)
  rides along only because it lives under the same `/home/claude` mount, not
  because HolyClaude's persistence scripts specifically manage it.
- **The container's own entrypoint already does all first-boot/every-boot
  bootstrapping** (PUID/GID remap against host-provided `PUID`/`PGID`,
  ownership repair, CLI config symlinks, credential restore, first-boot
  `settings.json`/`CLAUDE.md` seeding gated by a
  `~/.claude/.holyclaude-bootstrapped` sentinel) — unlike openclaw, which
  needed a hand-rolled command wrapper because openclaw's own image has no
  such machinery. This deployment must **not** override
  `containers.app.command`, or all of that gets reimplemented by hand for no
  reason.
- **The image's last `USER` directive is `root`**, and the PUID/GID remap
  logic explicitly assumes it starts as root (individual s6 services drop
  privilege themselves via `s6-setuidgid claude`). Combined with
  `docs/configuration.md`'s explicit `cap_add: [SYS_ADMIN, SYS_PTRACE]` +
  `security_opt: [seccomp=unconfined]` requirement (for the sandboxed
  Chromium/Playwright browser stack), this workload cannot run under a
  `restricted` or `baseline` Pod Security Admission level. The `ai` namespace
  currently carries no PSA label (cluster default is permissive), so nothing
  blocks this today, but it's a real, standing exception that needs
  documenting so nobody tightens PSA on that namespace later without
  accounting for it.
- **CloudCLI already ships a genuine PTY web terminal** (`node-pty` +
  xterm.js over WebSocket, confirmed via
  `scripts/patch-cloudcli-web-terminal-rendering.mjs` and README) with
  `claude`/`task-master`/`opencode` on `$PATH` inside it — this satisfies the
  "bespoke CLI commands via terminal" requirement without a code-server
  sidecar like openclaw uses. It does mean live WebSocket upgrade needs to
  pass cleanly through Traefik + Gateway API + CrowdSec + Authentik
  forwardAuth — no prior art in this repo confirms that chain end-to-end for
  WS traffic (openclaw's UI doesn't lean on it the same way), so this needs a
  live smoke test after deploy, not just an assumption.
- **CloudCLI has its own account/session system** (`~/.cloudcli/auth.db`,
  README: *"sign in with your Anthropic account"*) layered independently on
  top of whatever network-level auth fronts it. Upstream's own docs are blunt
  that this alone is not sufficient protection (*"a password is a speed
  bump, not a door"*) — Authentik forwardAuth at the Gateway is exactly the
  missing layer they assume you'll add, and it's this cluster's standard
  pattern for every other external app.
- **TaskMaster AI has no HolyClaude-specific env var** — it reads whichever
  general LLM-provider key exists in the environment (the same
  `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/etc. that Claude Code/Gemini/Codex
  would also read). Since `ANTHROPIC_API_KEY` must stay unset (to keep Claude
  Code on its OAuth path, not fall back to API-key auth — the exact
  precedence between the two was not confirmed by research and is called out
  as an open risk below), TaskMaster gets a dedicated Perplexity key instead,
  sidestepping the collision entirely.

## Goals

- Deploy HolyClaude as a bjw-s app-template `HelmRelease` under
  `kubernetes/apps/ai/holyclaude/`, following this repo's `OCIRepository` +
  `chartRef` / app-template conventions.
- Persist everything that needs to survive a pod restart: Claude Code's OAuth
  session, TaskMaster and OpenCode config/state, git/gh identity, and the
  user's `/workspace` (checked-out repos, in-progress work).
- Enable exactly three CLI providers with real credentials/integration:
  Claude Code (subscription OAuth), TaskMaster AI (Perplexity key), OpenCode
  (its own interactive auth, explicitly approved as a scoped exception to
  this repo's prior OpenCode rejection).
- Expose it externally at `holyclaude.68cc.io` via `traefik-external-gateway`,
  gated by Authentik forwardAuth SSO, matching `openclaw.68cc.io`'s pattern.
- Get it covered by Renovate (image tag bumps via the standard `docker`
  datasource).
- Leave the deployment shaped so arbitrary future ConfigMap/Secret mounts
  (SSH keys, `.npmrc`, other tool config) can be added later with no
  additional plumbing — just more `persistence.<name>` entries, the same
  pattern openclaw already uses for its `skills`/`automation-agents-md`
  ConfigMaps.
- Document the policy exceptions this creates (cloud Claude subscription,
  OpenCode) directly in `kubernetes/apps/ai/CLAUDE.md`, with the same rigor
  as the existing AMD GPU Operator scoped-exception precedent.

## Non-goals

- Gemini CLI, OpenAI Codex, Cursor, Junie, and Pi Coding Agent stay
  installed (unavoidable — see Research basis) but get **no credentials and
  no CloudCLI integration wiring**. "3 of 8 enabled" is a
  policy/configuration statement, not a binary-removal guarantee — nothing
  technically stops someone from typing `gemini` in the web terminal; this
  is accepted and documented, not solved.
- SSH/Mosh remote access — both default `false`
  (`HOLYCLAUDE_SSH_ENABLE`/`HOLYCLAUDE_MOSH_ENABLE`) and stay that way. This
  cluster's Traefik/Gateway API stack has no confirmed TCP/UDP route kind in
  place, and CloudCLI's web terminal already covers interactive shell
  access. `kubectl exec` remains the standard break-glass fallback.
- Tailscale / HolyClaude's own Cloudflare Tunnel integration — redundant with
  this cluster's existing Traefik + cloudflared + Authentik stack; left
  disabled.
- Apprise notifications — out of scope for this pass; can be added later by
  setting a `NOTIFY_*` var and touching a marker file on the PVC, no
  redesign needed.
- Cluster RBAC — unlike openclaw (`cluster-admin` via a `kube-mcp` sidecar),
  nothing in HolyClaude's scope needs cluster API access. No
  `ClusterRoleBinding`, no `ServiceAccount` grant beyond the default.
- A `docker.io` `imagePullSecret` — matches this repo's existing convention
  of anonymous pulls + Spegel P2P caching everywhere else. Docker Hub's
  anonymous rate limit (100 pulls/6h/IP) is noted as a watch-item, not
  addressed proactively.

## Decisions

1. **Namespace: `ai`.** Groups with openclaw/argus/openviking as the other
   AI-agent surface, documented as the deliberate cloud-LLM/interactive
   exception it is.
2. **Image variant: `full`, pinned semver (`1.5.7` at design time).**
   Mandatory for OpenCode; Renovate tracks it via the `docker` datasource
   with an `allowedVersions` regex excluding the `candidate-*` CI tag noise.
3. **Auth: interactive Claude Max/Pro OAuth subscription login**, not
   `ANTHROPIC_API_KEY`. Session persists via the image's own
   `persist-claude-json.mjs` mechanism on the PVC — no Kubernetes Secret
   represents this credential.
4. **Enabled providers: Claude Code, TaskMaster AI, OpenCode.** OpenCode is
   an explicit, approved, documented exception to this repo's prior OpenCode
   rejection (`ai/CLAUDE.md`'s "Decisions explicitly rejected" section) —
   scoped narrowly to this one interactive container, not a reversal of that
   decision for openclaw or any automation context.
5. **TaskMaster's provider key: Perplexity (`PERPLEXITY_API_KEY`)**, chosen
   specifically to avoid colliding with Claude Code's OAuth-based
   `ANTHROPIC_API_KEY` abstention. TaskMaster's "main" vs "research" model
   role split may need a second key once exercised in practice — flagged as
   an open risk, not blocking.
6. **Persistence: one PVC**, `openebs-hostpath`, mounted at the whole
   `/home/claude` plus `/workspace` via a `subPath` on the same volume — not
   upstream's narrower two-mount compose design, and not multiple separate
   PVCs.
7. **Terminal access: CloudCLI's built-in web terminal**, not a code-server
   sidecar. Needs a post-deploy WebSocket smoke test through the full
   Traefik/Gateway API/CrowdSec/Authentik chain.
8. **Security context: root, `SYS_ADMIN`+`SYS_PTRACE`,
   `seccompProfile: Unconfined`.** A real, documented, scoped exception —
   not something to fight by forcing non-root or a restrictive seccomp
   profile, since the image is not designed for that.
9. **Git identity: `BarryBot` / `github+barrybot@beholdthehurricane.com`** —
   a dedicated bot identity distinct from the user's own git identity, so
   commits made from inside HolyClaude are visually distinguishable in
   history.

## Architecture

### Resources (`kubernetes/apps/ai/holyclaude/`)

Mirrors openclaw's file layout:

```
kubernetes/apps/ai/holyclaude/
├── ks.yaml                      # Flux Kustomization
└── app/
    ├── kustomization.yaml
    ├── helmrelease.yaml
    └── secret.sops.yaml         # holyclaude-secret, holyclaude-taskmaster-secret
```

No `resources/` subdirectory, no `rbac.yaml`, no `configmap.yaml` for
app config (HolyClaude's own image ships working defaults; nothing here
needs a GitOps-managed config file the way openclaw's `openclaw.json` does).

### HelmRelease shape (`app/helmrelease.yaml`)

Uses the cluster-standard `OCIRepository` + `chartRef` pattern pointing at
the shared `app-template` OCIRepository (already available in `ai` via
`components/repos/app-template`, per `kustomization.yaml`).

```yaml
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
            # NOTE: do NOT set command/args -- the image's own ENTRYPOINT
            # handles PUID/GID remap, credential restore, and first-boot
            # bootstrap, then execs s6-overlay as PID 1. Overriding it means
            # reimplementing all of that by hand for no reason.
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

No `defaultPodOptions.securityContext.runAsUser` override (pod runs as root
by default at the container-runtime level, matching Decision 8) and no
`serviceAccount`/RBAC block (matching Non-goal on cluster RBAC).

### Secrets (`app/secret.sops.yaml`)

```yaml
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

Both encrypted via `task sops:encrypt-file` before commit, following this
repo's `CHANGEME` placeholder idiom (same as openclaw's
`DISCORD_BOT_TOKEN`/`GITHUB_TOKEN` gates) so the deployment comes up cleanly
before real values are supplied, and picks them up automatically once real
values land (Reloader-triggered restart).

### Flux Kustomization (`ks.yaml`)

Mirrors openclaw's `ks.yaml` shape; no `dependsOn` needed (HolyClaude has no
in-cluster service dependency, unlike openclaw's dependency on llama-swap).

## Components & files touched

- `kubernetes/apps/ai/holyclaude/ks.yaml` (new)
- `kubernetes/apps/ai/holyclaude/app/kustomization.yaml` (new)
- `kubernetes/apps/ai/holyclaude/app/helmrelease.yaml` (new)
- `kubernetes/apps/ai/holyclaude/app/secret.sops.yaml` (new, SOPS-encrypted)
- `kubernetes/apps/ai/kustomization.yaml` — add `./holyclaude/ks.yaml` to the
  `resources:` list (confirmed: not auto-discovered — `openclaw/ks.yaml` is
  listed there explicitly, same pattern to follow)
- `kubernetes/apps/ai/CLAUDE.md` — new "Currently deployed" entry for
  HolyClaude, plus a new scoped-exception note (mirroring the AMD GPU
  Operator entry's structure) documenting the cloud-Claude and OpenCode
  exceptions and the openclaw-vs-HolyClaude distinction from the Context
  section above.

## Security considerations

- Root + `SYS_ADMIN` + `seccomp: Unconfined` is a real elevated-privilege
  surface, accepted because the image is not designed to run any other way
  and the workload is single-user, human-driven, behind Authentik
  forwardAuth. Documented explicitly in `ai/CLAUDE.md` so a future PSA
  tightening on the `ai` namespace accounts for this workload.
- Two independent auth layers front the app (Authentik forwardAuth at the
  Gateway, CloudCLI's own account system at the app) — neither substitutes
  for the other; both stay in place.
- `GITHUB_TOKEN` and `PERPLEXITY_API_KEY` are SOPS-encrypted, `CHANGEME`-gated
  the same way every other secret-bearing app in this repo handles
  first-deploy-before-real-credentials.
- No cluster RBAC granted — this workload cannot reach the Kubernetes API,
  unlike openclaw's deliberate `cluster-admin` grant.
- `ANTHROPIC_API_KEY` is deliberately never set anywhere in this deployment,
  eliminating any risk of it silently overriding the OAuth session (exact
  precedence unconfirmed — see Open risks).

## Verification plan (high-level; detailed steps go in the implementation plan)

- `task sops:verify` passes on the new secret file.
- `kustomize build kubernetes/apps/ai/holyclaude/app | kubectl apply --dry-run=client -f -` succeeds.
- `flux build kustomization holyclaude --path kubernetes/apps/ai/holyclaude/app --dry-run` succeeds.
- `kustomize build kubernetes/apps/ai/holyclaude/app | grep reloader.stakater` confirms the reload annotation lands on the pod template.
- Post-deploy: complete the one-time Claude Code OAuth login and CloudCLI
  account setup through the web UI; confirm both survive a pod restart
  (`kubectl delete pod` or a Flux-triggered reconcile) without re-prompting
  for login.
- Post-deploy: smoke-test CloudCLI's web terminal specifically (not just the
  chat UI) end-to-end through `holyclaude.68cc.io` — confirm WebSocket
  upgrade survives Traefik + Gateway API + CrowdSec + Authentik forwardAuth.
- Confirm `task-master` and `opencode` are reachable from the web terminal's
  `$PATH` and each completes a trivial command.

## Open risks carried into implementation

1. **`ANTHROPIC_API_KEY` vs. OAuth session precedence is unconfirmed** — not
   a concern here since the key is never set, but worth knowing if a future
   change ever introduces it accidentally.
2. **TaskMaster's exact supported provider env vars are not documented by
   HolyClaude** — `PERPLEXITY_API_KEY` is inferred from task-master-ai's
   general conventions, not confirmed against HolyClaude's own docs. Verify
   against task-master-ai's upstream docs when first exercising it; a second
   key for its "main" role may be needed.
3. **OpenCode's own provider-auth env-var support beyond its interactive TUI
   is undocumented** by HolyClaude — if a non-interactive OpenCode auth path
   is ever wanted, this needs opencode-ai's own docs, not HolyClaude's repo.
4. **CloudCLI web terminal's WebSocket path through this cluster's full
   ingress chain has no prior art** — must be smoke-tested, not assumed.
5. **`persist-claude-json.mjs`'s actual reconciliation logic was never read**
   (only referenced by an entrypoint.sh comment) — if the OAuth-persistence
   mechanism ever misbehaves (e.g. stale PVC state clobbering a good login),
   read this script directly (`/usr/local/bin/persist-claude-json.mjs` in the
   image) before debugging blind.
6. **Docker Hub anonymous pull-rate exposure** — this is the only workload in
   the cluster pulling from `docker.io` rather than `ghcr.io`. Not addressed
   proactively; revisit if pulls start failing with rate-limit errors.
