# OpenClaw Automation Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn OpenClaw from a chat-only tool into an automation feedback loop: unlock its bundled issue→PR skill, fix two skills that point at dead endpoints, add a narrowly-scoped second agent identity for anything unattended, wire Alertmanager/Flux-failure/scheduled triggers into it, and make it reachable from Discord (Signal as a stretch task).

**Architecture:** All changes are Kubernetes manifests in this FluxCD GitOps repo — there is no application code to write. "Tests" in this plan are the repo's own validation commands (`kustomize build` + `kubeconform`, `sops:verify`, `flux build --dry-run`) plus, where a change can only be confirmed against the running pod, an explicit live-verification step run after Flux reconciles. Every task ends in a commit to `main` (this repo's existing single-branch workflow — see recent history); pushing/reconciling is a checkpoint between tasks, not bundled into "commit."

**Tech Stack:** FluxCD (Kustomization/HelmRelease), bjw-s app-template Helm chart, SOPS+age, Prometheus Operator CRDs (AlertmanagerConfig), Flux notification-controller CRDs (Provider/Alert), OpenClaw gateway config (JSON5), kubeconform, kustomize.

**Spec:** `docs/superpowers/specs/2026-08-15-openclaw-automation-integrations-design.md`

## Global Constraints

- **PR-only autonomy.** Nothing in this epic auto-merges. Every write path OpenClaw's `automation` identity can reach ends at "opened a PR" or "posted a finding."
- **No new internet exposure.** No new HTTPRoute, no new DNS record, no new tunnel CNAME. Every new network path in this epic is ClusterIP-to-ClusterIP.
- **Repo scope: `j0sh3rs/home-ops` only.** Do not widen `GITHUB_TOKEN` scope or `gh-issues` target repo in this epic.
- **`codex` plugin disabled** (`codex: { enabled: false }`) — no `openai/*` model or key exists in this deployment; leaving it on contradicts the `ai` namespace's self-hosted-only policy.
- **Every changed manifest passes**: `task sops:verify` (if it touches a `*.sops.yaml` file), `kustomize build kubernetes/apps/{namespace}/{app}/app | kubectl apply --dry-run=client -f -`, and `flux build kustomization {name} --path kubernetes/apps/{path} --dry-run` before being considered done.
- **`automation` agent identity gets no `kube-mcp` access** (`mcpServers: []`) and a reduced, exclusive skill list — it never gets the same trust level as the human-chat `main` identity.

---

## File Map

| File | Change |
|---|---|
| `kubernetes/apps/ai/openclaw/app/resources/skills-configmap.yaml` | Fix `prometheus.md`/`victorialogs.md` endpoints (Task 1) |
| `kubernetes/apps/ai/openclaw/app/configmap.yaml` | `skills.allowBundled`, `codex.enabled`, `agents.ownership`+`entries`, `plugins.entries.discord`, `bindings`, `hooks.mappings` ×2 (Tasks 2, 3, 5, 6, 7) |
| `kubernetes/apps/ai/openclaw/app/secret.sops.yaml` | Reflector annotations, `DISCORD_BOT_TOKEN`, `FLUX_ALERT_HEADERS` (Tasks 4, 5, 7) |
| `kubernetes/apps/ai/openclaw/app/resources/automation-agents-md-configmap.yaml` (new) | `automation` identity's bootstrap `AGENTS.md` guardrail (Task 3) |
| `kubernetes/apps/ai/openclaw/app/resources/kustomization.yaml` | Add the new ConfigMap (Task 3) |
| `kubernetes/apps/ai/openclaw/app/helmrelease.yaml` | `init-config` initContainer extended to seed `workspace-automation/AGENTS.md`; new PVC mount for that ConfigMap; startup-script addition for idempotent `automations` creation (Tasks 3, 8) |
| `kubernetes/apps/monitoring/kube-prometheus-stack/app/alertmanagerconfig.yaml` | New `webhookConfigs` entry on the `discord` receiver (Task 6) |
| `kubernetes/apps/flux-system/flux-instance/app/notification-openclaw.yaml` (new) | `Provider` + `Alert` CRs for Kustomization/HelmRelease failures (Task 7) |
| `kubernetes/apps/flux-system/flux-instance/app/kustomization.yaml` | Add the new file (Task 7) |

---

### Task 1: Fix stale `prometheus`/`victorialogs` OpenClaw skills

These two custom skills currently tell the agent to query
`prometheus-operated.monitoring.svc.cluster.local:9090` and
`victoria-logs-server.monitoring.svc.cluster.local:9428` — both dead.
Prometheus was decommissioned (`kube-prometheus-stack` runs with
`prometheus.enabled: false`); there is no in-cluster `victoria-logs` app —
metrics and logs are externally hosted at `metrics.68cc.io`/`logs.68cc.io`.
This is a prerequisite for every trigger this epic adds — an alert/failure
triage session that can't actually query metrics/logs is useless.

**Files:**
- Modify: `kubernetes/apps/ai/openclaw/app/resources/skills-configmap.yaml`

**Interfaces:**
- Produces: corrected `prometheus`/`victorialogs` skill content, consumed by
  both the `main` and `automation` agent identities (Task 3).

- [ ] **Step 1: Rewrite the two skill bodies**

Edit `kubernetes/apps/ai/openclaw/app/resources/skills-configmap.yaml`,
replacing the `prometheus.md` and `victorialogs.md` values:

```yaml
  prometheus.md: |
    ---
    name: prometheus
    description: Query cluster metrics and active alerts via the externally-hosted VictoriaMetrics and in-cluster Alertmanager.
    ---
    # Prometheus / VictoriaMetrics

    Prometheus itself was decommissioned (home-ops-8bb). Metrics now live in an
    externally-hosted VictoriaMetrics reached via a Prometheus-compatible API:

    - `https://metrics.68cc.io/api/v1/query?query=<promql>` — instant query
    - `https://metrics.68cc.io/api/v1/query_range?query=<promql>&start=<ts>&end=<ts>&step=<dur>` — range query

    Alertmanager (still in-cluster, unaffected by the Prometheus decommission)
    holds currently firing/pending alerts:

    - `http://alertmanager-operated.monitoring.svc.cluster.local:9093/api/v2/alerts`

    If a query against `metrics.68cc.io` fails with a connection error, this
    endpoint may be LAN-only — check reachability from this pod's network
    context before assuming the metric doesn't exist.

  victorialogs.md: |
    ---
    name: victorialogs
    description: Query aggregated container logs via the externally-hosted VictoriaLogs (LogsQL).
    ---
    # VictoriaLogs

    There is no in-cluster VictoriaLogs server. The `vector` DaemonSet ships
    logs to an externally-hosted VictoriaLogs instance. Query it with LogsQL:

    ```
    GET https://logs.68cc.io/select/logsql/query?query=<logsql>
    ```

    Example LogsQL: `{namespace="ai",app="openclaw"} error` — filters by
    Kubernetes labels attached at ingest, then a free-text term.

    If this endpoint fails with a connection error, it may be LAN-only —
    check reachability from this pod's network context before assuming the
    logs don't exist.
```

- [ ] **Step 2: Validate the manifest**

Run: `kustomize build kubernetes/apps/ai/openclaw/app | kubectl apply --dry-run=client -f -`
Expected: no errors; `configmap/openclaw-skills` shown as would-be-applied.

- [ ] **Step 3: Commit**

```bash
git add kubernetes/apps/ai/openclaw/app/resources/skills-configmap.yaml
git commit -m "fix(ai): point openclaw's prometheus/victorialogs skills at real endpoints

Prometheus was decommissioned and victoria-logs was never in-cluster —
both skills pointed at dead Service DNS. Point them at the actual
externally-hosted metrics.68cc.io/logs.68cc.io endpoints instead."
```

- [ ] **Step 4 (post-reconcile, live verification):** After this is merged and
  Flux reconciles, open a chat session at `openclaw.68cc.io` and ask "what
  alerts are currently firing, and what's the API response time p99 over the
  last hour" — confirm it queries `metrics.68cc.io`/the Alertmanager URL
  successfully rather than failing with a DNS/connection error. If
  `metrics.68cc.io`/`logs.68cc.io` are unreachable from the pod (LAN-only
  restriction), note the actual failure and adjust the skill text with the
  correct reachable path before moving on — do not proceed to Task 6/7 with
  broken triage skills.

---

### Task 2: Unlock `gh-issues`/`github` bundled skills; disable `codex`

**Files:**
- Modify: `kubernetes/apps/ai/openclaw/app/configmap.yaml`

**Interfaces:**
- Produces: `gh-issues` and `github` available as skill names, consumed by
  Task 3 (automation agent's skill list) and Task 8 (cron sweep).

- [ ] **Step 1: Edit the `skills` block**

In `kubernetes/apps/ai/openclaw/app/configmap.yaml`, change:

```json5
      skills: {
        allowBundled: [],
        load: {
          extraDirs: ["/skills"],
        },
        entries: {
          prometheus: { enabled: true },
          victorialogs: { enabled: true },
          "kubernetes-events": { enabled: true },
          flux: { enabled: true },
        },
      },
```

to:

```json5
      skills: {
        // gh-issues: OpenClaw's bundled issue-fetch -> sub-agent-fix -> PR
        // autopilot. github: thin `gh` CLI wrapper (PR/CI status, issue
        // listing). Both were disabled by allowBundled: [] before this.
        allowBundled: ["gh-issues", "github"],
        load: {
          extraDirs: ["/skills"],
        },
        entries: {
          prometheus: { enabled: true },
          victorialogs: { enabled: true },
          "kubernetes-events": { enabled: true },
          flux: { enabled: true },
          "gh-issues": { enabled: true },
          github: { enabled: true },
        },
      },
```

- [ ] **Step 2: Disable the `codex` plugin**

In the same file, change:

```json5
          codex: { enabled: true },
```

to:

```json5
          // No openai/* model or API key exists in this deployment (or the
          // ai namespace generally — self-hosted-only policy). This plugin
          // only does anything when an openai/* model ref is selected, so
          // it's dead config left in its default-enabled state. Re-enable
          // explicitly if a future use needs its media-understanding
          // capability with a real OpenAI credential.
          codex: { enabled: false },
```

- [ ] **Step 3: Validate**

Run: `kustomize build kubernetes/apps/ai/openclaw/app | kubectl apply --dry-run=client -f -`
Expected: no errors.

Run: `python3 -c "import json5" 2>/dev/null || pip install json5 --quiet; python3 -c "
import json5
with open('kubernetes/apps/ai/openclaw/app/configmap.yaml') as f:
    content = f.read()
start = content.index('openclaw.json: |') + len('openclaw.json: |\n')
body = '\n'.join(l[4:] if l.startswith('    ') else l for l in content[start:].splitlines())
json5.loads(body)
print('openclaw.json: valid JSON5')
"`
Expected: `openclaw.json: valid JSON5` (catches JSON5 syntax errors — trailing
commas are fine in JSON5, but mismatched braces are not).

- [ ] **Step 4: Commit**

```bash
git add kubernetes/apps/ai/openclaw/app/configmap.yaml
git commit -m "feat(ai): unlock gh-issues/github openclaw skills, disable dead codex plugin

skills.allowBundled: [] disabled every bundled OpenClaw skill, including
gh-issues (issue -> PR autopilot) and github (gh CLI wrapper) -- the
closest thing in the OpenClaw ecosystem to the removed Kelos pipeline.
agentToAgent, git, gh, and GITHUB_TOKEN were already wired; this was a
one-line unlock. Also disables codex, which has no openai/* model or
key configured anywhere in this self-hosted-only namespace."
```

- [ ] **Step 5 (post-reconcile, live verification):** In a chat session, ask
  "list open issues on this repo" and confirm it uses the `github` skill
  successfully (i.e., `gh issue list` runs). Do not yet ask it to run
  `gh-issues` end-to-end — that's verified in Task 8 once the `automation`
  identity and its guardrail exist.

---

### Task 3: Add the `automation` agent identity

Switches `agents.ownership` to `"explicit"` and adds a second, narrower
identity. `main` keeps today's behavior unchanged (full tool access, used for
human chat). `automation` is the target for every hook/cron-triggered run
added in Tasks 6-8: no `kube-mcp`, a reduced skill list (drops
`kubernetes-events`, which depends on kube-mcp/kubectl), its own workspace
directory, and a bootstrap `AGENTS.md` instructing it to draft-and-stop
rather than complete a change to risk/critical paths.

**Files:**
- Create: `kubernetes/apps/ai/openclaw/app/resources/automation-agents-md-configmap.yaml`
- Modify: `kubernetes/apps/ai/openclaw/app/resources/kustomization.yaml`
- Modify: `kubernetes/apps/ai/openclaw/app/configmap.yaml`
- Modify: `kubernetes/apps/ai/openclaw/app/helmrelease.yaml`

**Interfaces:**
- Consumes: `gh-issues`/`github` skill names (Task 2).
- Produces: `agentId: "automation"` — consumed by Tasks 6, 7, 8's
  `hooks.mappings`/`automations` entries as the execution identity; a mounted
  `workspace-automation/AGENTS.md` guardrail file.

- [ ] **Step 1: Create the bootstrap guardrail ConfigMap**

```yaml
# kubernetes/apps/ai/openclaw/app/resources/automation-agents-md-configmap.yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: openclaw-automation-agents-md
data:
  AGENTS.md: |
    # Automation identity — operating rules

    You are OpenClaw's `automation` identity: you run unattended, triggered
    by an Alertmanager alert, a Flux reconcile failure, or a schedule — never
    by a human typing to you directly. You have no Kubernetes API access
    (no kube-mcp). Every change you make must go through a pull request; you
    never merge anything yourself.

    ## Hard stop: risk/critical paths

    If the work you've been triggered to do would require changing any of:

    - anything under `kubernetes/apps/flux-system/`
    - anything under `talos/`
    - any file matching `*.sops.yaml`

    then do NOT make the change. Instead: open a **draft** PR containing only
    your investigation notes (what you found, what change you believe is
    needed, why), explicitly state in the PR body "This touches a
    risk/critical path and was intentionally left as a draft for human
    review," and stop. This applies even if you are confident the fix is
    correct — the point is a human decision gate on this specific class of
    path, not a judgment call on correctness.

    ## Everything else

    Normal `gh-issues`/`github` skill behavior applies: branch, implement,
    test if a test suite exists for what you touched, commit, push, open a
    PR whose body references the triggering issue/alert. Never merge.
```

- [ ] **Step 2: Wire the new ConfigMap into the kustomization**

Edit `kubernetes/apps/ai/openclaw/app/resources/kustomization.yaml`:

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./skills-configmap.yaml
  - ./automation-agents-md-configmap.yaml
```

- [ ] **Step 3: Add `agents.ownership`, the `automation` entry, and `bindings`**

In `kubernetes/apps/ai/openclaw/app/configmap.yaml`, change:

```json5
      agents: {
        defaults: {
          model: {
```

to:

```json5
      agents: {
        // Two identities: "main" (human chat, full access, unchanged
        // behavior) and "automation" (hook/cron-triggered, no kube-mcp,
        // reduced skills, own workspace + AGENTS.md guardrail). A non-empty
        // per-agent `skills` list is exclusive, not additive, so "main"
        // stays unset here to keep inheriting every globally-enabled skill.
        ownership: "explicit",
        entries: {
          main: {},
          automation: {
            workspace: "~/.openclaw/workspace-automation",
            skills: ["gh-issues", "github", "prometheus", "victorialogs", "flux"],
            mcpServers: [],
          },
        },
        defaults: {
          model: {
```

Immediately after the `agents: { ... }` block's closing (before the top-level
`models:` key), add:

```json5
      // Empty for now -- no channel exists yet. hooks.mappings (Tasks 6-7)
      // and automations (Task 8) set agentId: "automation" explicitly
      // per-call, so they never need a binding entry. Task 5 adds an
      // explicit binding once the Discord channel exists -- OpenClaw's
      // docs frame bindings as the actual routing mechanism once
      // agents.ownership is "explicit", with no confirmed silent fallback
      // to a single unbound identity, so this plan does not rely on one.
      bindings: [],
```

- [ ] **Step 4: Mount the ConfigMap onto the PVC via `init-config`**

In `kubernetes/apps/ai/openclaw/app/helmrelease.yaml`, extend the
`init-config` initContainer's script and add a persistence entry for the new
ConfigMap. Change:

```yaml
          init-config:
            image:
              repository: docker.io/library/alpine
              tag: "3.24"
            command:
              - sh
              - -c
              - |
                set -eu
                mkdir -p /home/node/.openclaw
                cp /tmp/openclaw.json /home/node/.openclaw/openclaw.json
                chmod 600 /home/node/.openclaw/openclaw.json
```

to:

```yaml
          init-config:
            image:
              repository: docker.io/library/alpine
              tag: "3.24"
            command:
              - sh
              - -c
              - |
                set -eu
                mkdir -p /home/node/.openclaw
                cp /tmp/openclaw.json /home/node/.openclaw/openclaw.json
                chmod 600 /home/node/.openclaw/openclaw.json
                mkdir -p /home/node/.openclaw/workspace-automation
                cp /tmp/automation-AGENTS.md /home/node/.openclaw/workspace-automation/AGENTS.md
```

Then, in the same file's `persistence.configmap` block, add a second mount
for the new ConfigMap alongside the existing `openclaw.json` mount:

```yaml
      configmap:
        type: configMap
        name: openclaw-config
        defaultMode: 0644
        globalMounts:
          - path: /tmp/openclaw.json
            subPath: openclaw.json
      automation-agents-md:
        type: configMap
        name: openclaw-automation-agents-md
        defaultMode: 0644
        globalMounts:
          - path: /tmp/automation-AGENTS.md
            subPath: AGENTS.md
```

- [ ] **Step 5: Validate**

Run:
```bash
kustomize build kubernetes/apps/ai/openclaw/app | kubectl apply --dry-run=client -f -
flux build kustomization openclaw --path kubernetes/apps/ai/openclaw/app --dry-run
```
Expected: no errors from either command.

- [ ] **Step 6: Commit**

```bash
git add kubernetes/apps/ai/openclaw/app/resources/automation-agents-md-configmap.yaml \
        kubernetes/apps/ai/openclaw/app/resources/kustomization.yaml \
        kubernetes/apps/ai/openclaw/app/configmap.yaml \
        kubernetes/apps/ai/openclaw/app/helmrelease.yaml
git commit -m "feat(ai): add openclaw automation agent identity

Second, narrower agentId for anything hook/cron-triggered: no kube-mcp,
a reduced skill list, its own workspace, and a bootstrap AGENTS.md that
hard-stops (draft PR only) on changes to flux-system/, talos/, or
*.sops.yaml. main is unchanged. Prerequisite for the Alertmanager/Flux/
cron triggers landing in follow-up commits."
```

- [ ] **Step 7 (post-reconcile, live verification):** Confirm the pod mounts
  both files correctly: `kubectl -n ai exec deploy/openclaw -c app -- cat
  /home/node/.openclaw/workspace-automation/AGENTS.md` should print the
  guardrail text. Confirm two agent identities are visible to the running
  gateway (check via `openclaw` CLI/API in-pod — exact command TBD against
  the live `2026.7.1` CLI's help output; this is one of the spec's flagged
  open risks). Do not proceed to Task 6/7 until this identity is confirmed
  working.

---

### Task 4: Reflect `openclaw-secret` into `monitoring` and `flux-system`

Uses the repo's existing Reflector pattern (already used by
`alertmanager-secret` to mirror `DISCORD_WEBHOOK_URL` into `security`) so the
Alertmanager and Flux trigger wiring (Tasks 6-7) can reference OpenClaw's
hooks token without a second hand-copied SOPS secret.

**Files:**
- Modify: `kubernetes/apps/ai/openclaw/app/secret.sops.yaml`

**Interfaces:**
- Produces: `openclaw-secret` (same name, same keys) also present in
  `monitoring` and `flux-system` namespaces — consumed by Task 6
  (`bearerTokenSecret`) and Task 7 (`secretRef.headers`).

- [ ] **Step 1: Decrypt, add annotations + a new key, re-encrypt**

Use the `sops-edit-then-encrypt` skill/pattern for this file (it's already
SOPS-encrypted). The end state, before re-encryption, should have:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: openclaw-secret
  annotations:
    # Mirrors this secret into monitoring (Alertmanager webhook receiver,
    # Task 6) and flux-system (Flux notification Provider, Task 7) so both
    # can authenticate to openclaw's /hooks endpoint without a hand-copied
    # second SOPS secret. Same pattern as alertmanager-secret -> security.
    reflector.v1.k8s.emberstack.com/reflection-allowed: "true"
    reflector.v1.k8s.emberstack.com/reflection-allowed-namespaces: "monitoring,flux-system"
    reflector.v1.k8s.emberstack.com/reflection-auto-enabled: "true"
    reflector.v1.k8s.emberstack.com/reflection-auto-namespaces: "monitoring,flux-system"
stringData:
  OPENCLAW_GATEWAY_TOKEN: <unchanged existing value>
  OPENCLAW_HOOKS_TOKEN: <unchanged existing value>
  MEMINI_API_KEY: <unchanged existing value>
  GITHUB_TOKEN: <unchanged existing value>
  # Flux's generic Provider secretRef reads a "headers" key as a literal
  # HTTP-header dict (not just a bearer value) -- see
  # https://fluxcd.io/flux/components/notification/providers/. Value must be
  # the literal header line, reusing the same token as OPENCLAW_HOOKS_TOKEN.
  FLUX_ALERT_HEADERS: "Authorization: Bearer <same value as OPENCLAW_HOOKS_TOKEN>"
```

Do not touch `DISCORD_BOT_TOKEN` here — that's added in Task 5 to this same
file.

- [ ] **Step 2: Verify encryption**

Run: `task sops:verify`
Expected: `kubernetes/apps/ai/openclaw/app/secret.sops.yaml` reported as
properly encrypted (only `stringData` values encrypted, `metadata` in the
clear).

- [ ] **Step 3: Commit**

```bash
git add kubernetes/apps/ai/openclaw/app/secret.sops.yaml
git commit -m "feat(ai): reflect openclaw-secret into monitoring and flux-system

Lets the Alertmanager webhook receiver (Task 6) and the Flux
notification Provider (Task 7) authenticate to openclaw's /hooks
endpoint using the existing OPENCLAW_HOOKS_TOKEN, mirrored via
Reflector rather than a hand-copied second SOPS secret -- same pattern
already used by alertmanager-secret -> security."
```

- [ ] **Step 4 (post-reconcile, live verification):**
  `kubectl -n monitoring get secret openclaw-secret` and `kubectl -n
  flux-system get secret openclaw-secret` should both exist and match the
  source. If Reflector's RBAC doesn't already cover `flux-system` (it should,
  per CLAUDE.md: `watchGlobally: true`, cluster-wide), check
  `kubectl -n kube-system logs deploy/reflector` for errors before debugging
  further.

---

### Task 5: Discord channel plugin

**Files:**
- Modify: `kubernetes/apps/ai/openclaw/app/secret.sops.yaml`
- Modify: `kubernetes/apps/ai/openclaw/app/configmap.yaml`

**Interfaces:**
- Produces: a working Discord channel bound to `agentId: "main"`, and a
  delivery target (`channel: "discord"`, `to: "channel:<id>"`) consumed by
  Tasks 6-8's hook/cron `deliver`/`channel`/`to` fields for notifications.

- [ ] **Step 0 (manual, outside this repo): create the bot**

In the [Discord Developer Portal](https://discord.com/developers/applications):
1. New Application → name it (e.g. "openclaw").
2. Bot page → enable **Message Content Intent** and **Server Members Intent**.
3. Bot page → Reset Token → copy it (this is `DISCORD_BOT_TOKEN` below).
4. OAuth2 → URL Generator → scopes `bot` + `applications.commands`;
   permissions View Channels, Send Messages, Read Message History, Embed
   Links, Attach Files.
5. Open the generated URL, select your server, authorize.
6. Note the target channel's ID (Discord → enable Developer Mode → right
   click channel → Copy Channel ID) — needed for Task 6/7/8's `to` field.

- [ ] **Step 1: Add `DISCORD_BOT_TOKEN` to the secret**

Add to `kubernetes/apps/ai/openclaw/app/secret.sops.yaml`'s `stringData`
(alongside the keys from Task 4):

```yaml
  DISCORD_BOT_TOKEN: <bot token from Step 0>
```

Re-run `task sops:verify` after editing.

- [ ] **Step 2: Add the `channels.discord` block**

In `kubernetes/apps/ai/openclaw/app/configmap.yaml`, add a new top-level key
(alongside `agents`, `models`, `skills`, etc.):

```json5
      channels: {
        discord: {
          enabled: true,
          token: { source: "env", provider: "default", id: "DISCORD_BOT_TOKEN" },
          dmPolicy: "allowlist",
          allowFrom: ["<your Discord user ID>"],
          groupPolicy: "allowlist",
          guilds: {
            "<your server ID>": {
              requireMention: true,
              users: ["<your Discord user ID>"],
            },
          },
        },
      },
```

Also replace the `bindings: []` array Task 3 added with an explicit entry —
do not rely on an unconfirmed "unbound channels default to the only
non-automation identity" behavior when `agents.ownership: "explicit"` is
set; route Discord to `main` explicitly instead:

```json5
      bindings: [{ agentId: "main", match: { channel: "discord" } }],
```

`DISCORD_BOT_TOKEN` must reach the container's env — add it to the
`envFrom.secretRef` already present on the `app` container in
`helmrelease.yaml` (it already does `envFrom: [{ secretRef: { name:
openclaw-secret } }]`, so every key in the secret is already injected; no
`helmrelease.yaml` change needed here beyond what Task 4 already added).

- [ ] **Step 3: Validate**

```bash
kustomize build kubernetes/apps/ai/openclaw/app | kubectl apply --dry-run=client -f -
task sops:verify
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add kubernetes/apps/ai/openclaw/app/secret.sops.yaml kubernetes/apps/ai/openclaw/app/configmap.yaml
git commit -m "feat(ai): add openclaw Discord channel

Bidirectional Discord bot bound to the main identity -- lets the
operator converse with openclaw from Discord, and is the delivery
target the Alertmanager/Flux/cron triggers (follow-up commits) post
completion notifications to."
```

- [ ] **Step 5 (post-reconcile, live verification):** DM the bot or @mention
  it in the configured guild channel; confirm it responds. This is the
  gate before Task 6/7/8 can usefully notify anywhere.

---

### Task 6: Alertmanager → OpenClaw hook

**Files:**
- Modify: `kubernetes/apps/ai/openclaw/app/configmap.yaml`
- Modify: `kubernetes/apps/monitoring/kube-prometheus-stack/app/alertmanagerconfig.yaml`

**Interfaces:**
- Consumes: `agentId: "automation"` (Task 3), `openclaw-secret` mirrored into
  `monitoring` (Task 4), Discord delivery target (Task 5).

- [ ] **Step 1: Add the `hooks.mappings` entry**

In `kubernetes/apps/ai/openclaw/app/configmap.yaml`, change:

```json5
      hooks: {
        enabled: true,
        path: "/hooks",
        token: "$${OPENCLAW_HOOKS_TOKEN}",
        internal: {
```

to:

```json5
      hooks: {
        enabled: true,
        path: "/hooks",
        token: "$${OPENCLAW_HOOKS_TOKEN}",
        mappings: [
          {
            id: "alertmanager",
            match: { path: "alertmanager" },
            action: "agent",
            agentId: "automation",
            wakeMode: "now",
            name: "Alertmanager",
            sessionMode: "isolated",
            deliver: true,
            channel: "discord",
            to: "channel:<Discord channel ID from Task 5>",
            messageTemplate: "A Prometheus/VictoriaMetrics alert fired: {{alerts[0].labels.alertname}} (severity={{alerts[0].labels.severity}}) on {{alerts[0].labels.namespace}}/{{alerts[0].labels.job}}. Summary: {{alerts[0].annotations.summary}}. Investigate using the prometheus and victorialogs skills, and report your findings. If a fix is warranted and safe (not flux-system/, talos/, or *.sops.yaml), open a PR; otherwise open a draft PR with your findings per your AGENTS.md.",
          },
        ],
        internal: {
```

- [ ] **Step 2: Add the Alertmanager webhook receiver**

In `kubernetes/apps/monitoring/kube-prometheus-stack/app/alertmanagerconfig.yaml`,
change the `discord` receiver:

```yaml
  receivers:
    - name: blackhole
    - name: discord
      discordConfigs:
        - apiURL:
            name: alertmanager-secret
            key: DISCORD_WEBHOOK_URL
```

to:

```yaml
  receivers:
    - name: blackhole
    - name: discord
      discordConfigs:
        - apiURL:
            name: alertmanager-secret
            key: DISCORD_WEBHOOK_URL
      # Every alert that already reaches Discord (severity=critical, per the
      # route above) also triggers an openclaw automation-identity triage
      # session -- pure in-cluster traffic, no new exposure. See
      # docs/superpowers/specs/2026-08-15-openclaw-automation-integrations-design.md.
      webhookConfigs:
        - url: "http://openclaw.ai.svc.cluster.local:18789/hooks/alertmanager"
          httpConfig:
            bearerTokenSecret:
              name: openclaw-secret
              key: OPENCLAW_HOOKS_TOKEN
```

- [ ] **Step 3: Validate**

```bash
kustomize build kubernetes/apps/ai/openclaw/app | kubectl apply --dry-run=client -f -
kustomize build kubernetes/apps/monitoring/kube-prometheus-stack/app | kubectl apply --dry-run=client -f -
```
Expected: no errors from either. If `kubeconform` flags the `webhookConfigs`
block against a stale/cached CRD schema, cross-check field names against
`pkg/apis/monitoring/v1alpha1/alertmanager_config_types.go` in
`prometheus-operator/prometheus-operator` rather than assuming the plan is
wrong — `httpConfig.bearerTokenSecret` is a `v1.SecretKeySelector`
(`name`+`key`), confirmed directly from that source file during planning.

- [ ] **Step 4: Commit**

```bash
git add kubernetes/apps/ai/openclaw/app/configmap.yaml kubernetes/apps/monitoring/kube-prometheus-stack/app/alertmanagerconfig.yaml
git commit -m "feat(ai,monitoring): wire Alertmanager critical alerts to openclaw triage

severity=critical alerts (the same set already reaching Discord) now
also POST to openclaw's /hooks/alertmanager mapped hook, running the
automation identity to triage and report back to the same Discord
channel. In-cluster traffic only, no new exposure."
```

- [ ] **Step 5 (post-reconcile, live verification):** Fire a synthetic test
  alert (e.g. `amtool alert add alertname=OpenClawHookTest severity=critical
  --alertmanager.url=http://<alertmanager>:9093` from a pod with network
  access, or temporarily add a trivial always-firing test rule and remove it
  after). Confirm: (a) Discord still gets the normal alert notification, (b)
  a new openclaw run appears (workboard and/or a follow-up Discord message
  from the automation identity), (c) the run used `agentId: automation` not
  `main`.

---

### Task 7: Flux reconcile-failure → OpenClaw hook

**Files:**
- Modify: `kubernetes/apps/ai/openclaw/app/configmap.yaml`
- Create: `kubernetes/apps/flux-system/flux-instance/app/notification-openclaw.yaml`
- Modify: `kubernetes/apps/flux-system/flux-instance/app/kustomization.yaml`

**Interfaces:**
- Consumes: `agentId: "automation"` (Task 3), `openclaw-secret` mirrored into
  `flux-system` (Task 4), Discord delivery target (Task 5).

- [ ] **Step 1: Add the second `hooks.mappings` entry**

In `kubernetes/apps/ai/openclaw/app/configmap.yaml`, extend the `mappings`
array added in Task 6 with a second entry:

```json5
        mappings: [
          {
            id: "alertmanager",
            /* ...unchanged from Task 6... */
          },
          {
            id: "flux",
            match: { path: "flux" },
            action: "agent",
            agentId: "automation",
            wakeMode: "now",
            name: "Flux",
            sessionMode: "isolated",
            deliver: true,
            channel: "discord",
            to: "channel:<Discord channel ID from Task 5>",
            messageTemplate: "A Flux {{involvedObject.kind}} failed to reconcile: {{involvedObject.namespace}}/{{involvedObject.name}}. Reason: {{reason}}. Message: {{message}}. Investigate using the flux, prometheus, and victorialogs skills, and report your findings. If a fix is warranted and safe (not flux-system/, talos/, or *.sops.yaml), open a PR; otherwise open a draft PR with your findings per your AGENTS.md.",
          },
        ],
```

- [ ] **Step 2: Create the Flux `Provider` + `Alert`**

```yaml
# kubernetes/apps/flux-system/flux-instance/app/notification-openclaw.yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/provider-notification-v1.json
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Provider
metadata:
  name: openclaw
spec:
  type: generic
  address: http://openclaw.ai.svc.cluster.local:18789/hooks/flux
  secretRef:
    name: openclaw-secret
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/alert-notification-v1beta3.json
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: openclaw
spec:
  providerRef:
    name: openclaw
  eventSeverity: error
  eventSources:
    - kind: Kustomization
      name: "*"
    - kind: HelmRelease
      name: "*"
```

The `openclaw-secret` referenced here is the Task 4 Reflector-mirrored copy
in `flux-system`; its `headers` key (`FLUX_ALERT_HEADERS`, set in Task 4) is
what Flux's `generic` provider type reads to attach the `Authorization:
Bearer` header, per
https://fluxcd.io/flux/components/notification/providers/. Only `error`
severity is sent (a resource going `False`/failing to reconcile), not every
successful reconcile.

- [ ] **Step 3: Wire the new file into the kustomization**

Edit `kubernetes/apps/flux-system/flux-instance/app/kustomization.yaml`,
adding `notification-openclaw.yaml` to `resources`.

- [ ] **Step 4: Validate**

```bash
kustomize build kubernetes/apps/ai/openclaw/app | kubectl apply --dry-run=client -f -
kustomize build kubernetes/apps/flux-system/flux-instance/app | kubectl apply --dry-run=client -f -
flux build kustomization flux-instance --path kubernetes/apps/flux-system/flux-instance/app --dry-run
```
Expected: no errors. Confirm the `Alert`'s `apiVersion` matches what this
cluster's Flux Operator/notification-controller version actually serves
(`v1beta3` was the current stable API per Flux docs at plan time — if
`kubeconform`/`flux build` reports a version mismatch, check
`kubectl get crd alerts.notification.toolkit.fluxcd.io -o
jsonpath='{.spec.versions[*].name}'` and adjust).

- [ ] **Step 5: Commit**

```bash
git add kubernetes/apps/ai/openclaw/app/configmap.yaml \
        kubernetes/apps/flux-system/flux-instance/app/notification-openclaw.yaml \
        kubernetes/apps/flux-system/flux-instance/app/kustomization.yaml
git commit -m "feat(ai,flux-system): wire Flux reconcile failures to openclaw triage

Kustomization/HelmRelease failures (eventSeverity: error) now POST to
openclaw's /hooks/flux mapped hook via a new Provider+Alert, running
the automation identity to triage and report to Discord. In-cluster
traffic only -- distinct from the existing github-webhook Receiver,
which is Flux's inbound push-reconcile trigger, not an outbound
notification path."
```

- [ ] **Step 6 (post-reconcile, live verification):** Intentionally break a
  **scratch, non-critical** Kustomization (e.g. point a throwaway test
  Kustomization at a nonexistent path, or temporarily set an impossibly
  short `timeout` on something low-stakes) — never a `risk/critical`-labeled
  path. Confirm the `Alert` fires (`kubectl -n flux-system get events
  --field-selector reason=... ` or notification-controller logs) and
  OpenClaw picks it up. Revert the intentional breakage immediately after
  confirming.

---

### Task 8: Scheduled audits + `gh-issues --cron` sweep

Automations are **not** declarable statically in `openclaw.json` — they live
in the Gateway's own SQLite state, created only via `openclaw automations
create` (CLI/API). This task adds an idempotent, marker-file-guarded startup
step to the `app` container — the same idiom already used by the
`00-install-memini-plugin` initContainer, just running after the gateway is
up (automations creation needs the running Gateway API) rather than before.

**Files:**
- Modify: `kubernetes/apps/ai/openclaw/app/helmrelease.yaml`

**Interfaces:**
- Consumes: `agentId: "automation"` (Task 3), `gh-issues` skill (Task 2),
  Discord delivery target (Task 5).

- [ ] **Step 1: Extend the `app` container's startup script**

In `kubernetes/apps/ai/openclaw/app/helmrelease.yaml`, the `app` container's
`command` currently ends with `exec node dist/index.js gateway --bind lan`.
Insert a backgrounded provisioning block immediately before that `exec`
line:

```yaml
                # Automations live in the Gateway's own SQLite state, not in
                # this ConfigMap -- they must be created via the CLI/API
                # against the *running* gateway. Background a watcher that
                # waits for health, then idempotently (guarded by a marker
                # file on the PVC) creates the two scheduled jobs, so this is
                # safe to re-run on every pod restart.
                (
                  until curl -sf http://127.0.0.1:18789/healthz >/dev/null 2>&1; do
                    sleep 2
                  done
                  MARKER=/home/node/.openclaw/.automations-provisioned-v1
                  if [ ! -f "$MARKER" ]; then
                    openclaw automations create --name hygiene-audit \
                      --cron "0 6 * * *" --tz America/New_York \
                      --agent automation --session isolated \
                      --message "Run the repo's own hygiene checks: bd stale, bd orphans, task sops:verify. Summarize findings; file bd issues for anything actionable. Do not modify any files." \
                      --announce --channel discord --to "channel:<Discord channel ID from Task 5>" \
                      || echo "WARN: hygiene-audit automation create failed"
                    openclaw automations create --name gh-issues-sweep \
                      --every 30m \
                      --agent automation --session isolated \
                      --message "Run gh-issues j0sh3rs/home-ops --cron --label automerge-candidate. Follow your AGENTS.md guardrail on risk/critical paths." \
                      --announce --channel discord --to "channel:<Discord channel ID from Task 5>" \
                      || echo "WARN: gh-issues-sweep automation create failed"
                    touch "$MARKER"
                  fi
                ) &
                exec node dist/index.js gateway --bind lan
```

The `automerge-candidate` label gate means the sweep only ever picks up
issues explicitly labeled for it — it does not scan every open issue. Create
that label on the repo (`gh label create automerge-candidate --description
"Eligible for openclaw's scheduled gh-issues sweep" --color BFD4F2`) as part
of this task, not left implicit.

- [ ] **Step 2: Validate**

```bash
kustomize build kubernetes/apps/ai/openclaw/app | kubectl apply --dry-run=client -f -
```
Expected: no errors. This step can't validate the shell script's correctness
statically beyond YAML/`sh -n` syntax — run `sh -n` locally against the
extracted script block as a sanity check:
```bash
python3 -c "
import yaml
with open('kubernetes/apps/ai/openclaw/app/helmrelease.yaml') as f:
    doc = yaml.safe_load(f)
script = doc['spec']['values']['controllers']['openclaw']['containers']['app']['command'][2]
open('/tmp/openclaw-startup-check.sh', 'w').write(script)
"
sh -n /tmp/openclaw-startup-check.sh
```
Expected: no syntax errors printed.

- [ ] **Step 3: Commit**

```bash
gh label create automerge-candidate --repo j0sh3rs/home-ops --description "Eligible for openclaw's scheduled gh-issues sweep" --color BFD4F2
git add kubernetes/apps/ai/openclaw/app/helmrelease.yaml
git commit -m "feat(ai): add openclaw scheduled hygiene audit + gh-issues sweep

Automations aren't declarable in openclaw.json -- they live in the
Gateway's own SQLite state via the CLI/API. Adds an idempotent,
marker-guarded startup step (background watcher waits for /healthz,
then creates two jobs once): a daily hygiene audit (bd stale/orphans,
sops:verify, read-only) and a 30m gh-issues sweep scoped to issues
labeled automerge-candidate, running as the automation identity."
```

- [ ] **Step 4 (post-reconcile, live verification, the guardrail test from
  the spec):** First confirm both jobs were actually created (exact CLI
  introspection command — `openclaw automations list` or the Gateway API
  equivalent — TBD against the live `2026.7.1` CLI; check `openclaw
  automations --help` in-pod). Then: label a **scratch** issue in
  `j0sh3rs/home-ops` `automerge-candidate` whose fix would require touching
  `kubernetes/apps/flux-system/` (e.g. "typo in flux-instance/app/helmrelease.yaml
  comment"). Wait for the next sweep (or trigger one manually if the CLI
  supports it) and confirm the `automation` identity opens a **draft** PR
  with findings only, per its `AGENTS.md`, rather than completing the edit.
  This is the one guardrail this epic relies on being tested, not just
  configured — do not consider Task 8 done until this specific case is
  observed.

---

### Task 9: Signal channel (stretch, largely manual)

Signal support requires `signal-cli` as a separate daemon process, a
dedicated phone number, and an interactive linking step (QR scan or SMS
registration) — none of which is GitOps-automatable end-to-end. Treat this
as optional; if the manual linking step is more friction than it's worth,
stop after Step 1 and file a follow-up bead instead of continuing.

**Files:**
- Modify: `kubernetes/apps/ai/openclaw/app/helmrelease.yaml`
- Modify: `kubernetes/apps/ai/openclaw/app/configmap.yaml`

- [ ] **Step 1: Decide whether to proceed**

Confirm you have (or are willing to dedicate) a phone number for this, per
the spec's flagged operational cost: separate daemon process, local key
storage that must be backed up, pairing flow for DMs, 4000-char message
chunking. If not, stop here — file a bd issue under the epic (see Task 11)
marked `deferred` and move on; Discord alone (Task 5) already satisfies the
"Discord/Signal conversations" trigger requirement.

- [ ] **Step 2: Install `signal-cli` onto the PVC**

Add a new initContainer to `helmrelease.yaml`, following the exact pattern
of the existing `install-gh` initContainer (pinned version, marker-file
guard, install to `~/.local/bin`):

```yaml
          install-signal-cli:
            image:
              repository: docker.io/library/eclipse-temurin
              tag: "21-jre-alpine"
            command:
              - sh
              - -c
              - |
                set -eu
                # renovate: datasource=github-releases depName=AsamK/signal-cli
                SIGNAL_CLI_VERSION=0.14.7
                BIN=/home/node/.local/bin
                mkdir -p "$BIN"
                if [ "$(cat "$BIN/.signalcliver" 2>/dev/null)" != "$SIGNAL_CLI_VERSION" ]; then
                  wget -qO /tmp/signal-cli.tar.gz "https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz"
                  tar -xzf /tmp/signal-cli.tar.gz -C /tmp
                  cp -r /tmp/signal-cli-${SIGNAL_CLI_VERSION}/* "$BIN/../"
                  printf '%s' "$SIGNAL_CLI_VERSION" > "$BIN/.signalcliver"
                  rm -rf /tmp/signal-cli.tar.gz "/tmp/signal-cli-${SIGNAL_CLI_VERSION}"
                fi
```

`0.14.7` is the actual latest `signal-cli` release as of plan-writing time
(confirmed via `gh api repos/AsamK/signal-cli/releases/latest`); the
downloaded archive is the plain JVM build (`signal-cli-0.14.7.tar.gz`, needs
a JRE — hence `eclipse-temurin:21-jre-alpine` above), not the `-Linux-native`
variant. Renovate will keep this pinned version current the same way it does
`GH_VERSION` in the existing `install-gh` initContainer.

- [ ] **Step 3: Add the `channels.signal` block**

```json5
      channels: {
        discord: { /* ...unchanged from Task 5... */ },
        signal: {
          enabled: true,
          account: "<your E.164 phone number>",
          transport: { kind: "managed-native", cliPath: "signal-cli" },
          dmPolicy: "pairing",
          allowFrom: ["<your existing phone number, if linking your own account>"],
        },
      },
      bindings: [
        { agentId: "main", match: { channel: "discord" } },
        { agentId: "main", match: { channel: "signal" } },
      ],
```

- [ ] **Step 4: Validate**

```bash
kustomize build kubernetes/apps/ai/openclaw/app | kubectl apply --dry-run=client -f -
```

- [ ] **Step 5: Commit**

```bash
git add kubernetes/apps/ai/openclaw/app/helmrelease.yaml kubernetes/apps/ai/openclaw/app/configmap.yaml
git commit -m "feat(ai): add openclaw Signal channel (signal-cli managed-native)"
```

- [ ] **Step 6 (manual, post-reconcile):** `kubectl -n ai exec -it
  deploy/openclaw -c app -- signal-cli link -n "OpenClaw"`, scan the printed
  QR code from an existing Signal install on your phone. Confirm a message
  sent to that number reaches OpenClaw and gets a reply.

---

### Task 10: Full validation pass + spec cross-check

- [ ] **Step 1:** Run the complete validation suite across every file this
  epic touched:
```bash
task sops:verify
for app in ai/openclaw monitoring/kube-prometheus-stack flux-system/flux-instance; do
  echo "=== $app ==="
  kustomize build "kubernetes/apps/$app/app" | kubectl apply --dry-run=client -f -
done
flux build kustomization openclaw --path kubernetes/apps/ai/openclaw/app --dry-run
flux build kustomization flux-instance --path kubernetes/apps/flux-system/flux-instance/app --dry-run
```
Expected: no errors anywhere.

- [ ] **Step 2:** Re-read the spec's Verification plan (10 items) and this
  plan's Tasks 1-9; confirm every spec item maps to a completed task/step. If
  any spec item has no corresponding step, add it as a task before
  considering the epic done.

- [ ] **Step 3:** No commit — this is a check task. If it surfaces a gap,
  fix it in the relevant task above and re-run.

---

## Deferred to a follow-on epic (do not build here)

- SearXNG deployment + `@openclaw/searxng-plugin`.
- GitHub-webhook relay for real-time (vs. polled) issue triggering — needs a
  hand-built HMAC-signature relay and OpenClaw's first internet-facing route.
- `diagnostics-prometheus`/`diagnostics-otel` plugins + Grafana dashboard.
- Third-party Smart PR Review plugin.
- Multi-repo scope beyond `j0sh3rs/home-ops`.

File these as separate bd issues (not children of this epic) once this epic
is done — see Task 11 below for the epic/child-issue structure for the work
actually in this plan.
