# Mac Studio Bring-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `macos/` nix-darwin flake, and the cluster-side wiring around it, that turn the M5 Ultra Mac Studio into a managed, monitored, firewalled inference host serving oMLX at `mac-inference.ai.svc:8000`.

**Architecture:**
- **Mac side.** One flake at `macos/` (Determinate Nix + nix-darwin + sops-nix) describes the whole Mac. A launchd pull loop applies `main` whenever it moves, the same way Flux does.
  - Every service is a nix LaunchDaemon: oMLX, three exporters, vector, pf and the pull loop.
  - Daemons publish health as node_exporter textfile metrics.
- **Cluster side.** The cluster reaches the Mac through one selector-less Service plus an EndpointSlice. The Mac's IP lives in exactly one Kubernetes object, and scrapes, Gatus and the admin route all go through that Service name.
- **Pre-merge testing.** Nothing is applied from `main` until the operator merges. Before that, the operator tests the Mac side with `task mac:apply-local`.

**Tech Stack:**
- **Mac:** Determinate Nix ≥ 3.15.2, nix-darwin `nix-darwin-26.05`, nixpkgs `nixpkgs-26.05-darwin`, sops-nix, Homebrew (via the nix-darwin module), uv, oMLX v0.7.0, prometheus-node-exporter, macmon, vector, macOS pf.
- **Cluster:** VMStaticScrape, PrometheusRule (vm-operator converts it to VMRule), GrafanaDashboard, Gateway API HTTPRoute, Gatus, go-task.
- **CI and updates:** GitHub Actions `macos-15` runner, Renovate.

**Spec:** `docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md` (Phase 0.3 and all of Phase 1).
**Manual prerequisite:** `docs/runbooks/mac-studio-bringup.md`. The operator completes it first and hands back its §9 facts.

## Global Constraints

- Work in the `/workspace/home-ops-mac-spec` worktree on branch `feat/macos-bringup`. Never touch `/workspace/home-ops`.
- **Commits:**
  - Commit messages state the *why* (Hindsight recalls them later).
  - Each one ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- **Merging:** `main` requires linear history (rebase and fast-forward only). No push, PR or merge without the operator's explicit OK.
- **Secrets:**
  - Never commit a plaintext secret. Mac secrets go in `macos/secrets/*.sops.yaml`, whole-file encrypted to **both** the repo age key `age1qwwzsz6z2mmu6hpmjt2he7nepmnhutmhehvkva7l5zy5xzf08d5s5n4d6n` and `MAC_AGE_PUBKEY`.
  - Cluster secrets are `*.sops.yaml` under `kubernetes/`.
  - Run `task sops:verify` before every commit that touches secrets.
- **Spec values:**
  - `iogpu.wired_limit_mb` ≈ 84GB → **86016** MB. Engine memory limit ≈ 80GB → oMLX `--memory-guard-gb 80`.
  - pf allows **only** localhost and the cluster to reach engine and exporter ports. Cluster sources are the node IPs, because Cilium masquerades pod egress (`enable-bpf-masquerade`, native routing `10.42.0.0/16`).
  - Cluster IPs: `192.168.35.3` (bee-jms-01), `192.168.35.6` (bee-jms-02), `192.168.35.10` (bee-jms-03), plus `192.168.35.4` (bigboi-jms-01) until spec Phase 3.5 retires it.
  - Every engine endpoint requires an API key. Consumer keys are SOPS Secrets in the cluster.
  - Admin UIs only via `traefik-internal-gateway` with the `authentik-forwardauth` Middleware. Never on the external gateway.
  - Alerts: Mac unreachable, engine down, sustained swap, wired memory near limit, nix apply older than 24h, nix apply behind main. Plus one Gatus check on the model-list endpoint and one GrafanaDashboard.
- **Ports on the Mac:** oMLX `8000`, macmon `9090`, node_exporter `9100`, omlx-exporter `9101`.
- **Fact values:** the §9 facts from `docs/runbooks/mac-studio-bringup.md` are `ADMIN_USER`, `MAC_IP`, `MACOS_VERSION` and `MAC_AGE_PUBKEY`.
  - **Recorded 2026-10-16:** host `mac-jms-01` (Mac Studio hardware; doc filenames keep `mac-studio`), `ADMIN_USER=j0sh3rs`, `MAC_IP=192.168.35.7`, `MACOS_VERSION=27.0.1` (macOS 27, so the macmon >= 0.10.0 rule below matters), `MAC_AGE_PUBKEY=age1hua5s0wwmnysukxmtxkfepwcuzsc08kjmpn9pjjpwaka0lzvydwswlgq0j`.
  - Task 1 writes them into `macos/hosts/mac-jms-01/facts.nix`. Task 8 writes `MAC_IP` into the EndpointSlice.
  - No other file may contain the IP.
- **Execution mode:**
  - **Agent-runnable:** steps marked *(on Mac)* that only need `ssh mac-jms-01` without sudo. Allowed only if the operator authorized HolyClaude's key (checklist §5). If not, hand those steps to the operator.
  - **Operator only:** steps marked **OPERATOR**. They need sudo on the Mac. Stop and ask the operator to run them.
- **kubectl and flux:** prefix with `rtk` when it works. The shim currently errors; plain commands with `KUBECONFIG=/workspace/home-ops/kubeconfig` are fine.
- **Reloader:** every new cluster workload that consumes a Secret or ConfigMap gets a reloader annotation on the pod template (repo CLAUDE.md).

## Rulings baked into this plan

1. **oMLX is installed in Phase 1, not deferred to Phase 2.** Spec Phase 1.4 needs engine metrics and 1.5 needs API keys on engine endpoints. Neither can be verified without a running engine. oMLX is D7's primary candidate, so it is the baseline. Phase 2 adds the other engines next to it.
   - Cost if wrong: one module to remove.
2. **The oMLX engine signal comes from a ~150-line stdlib exporter.** It flattens `/admin/api/stats` into `omlx_stat{scope,path}`. oMLX documents those endpoints but not their response shapes, so the exporter guesses no field names.
3. **macmon comes from nixpkgs when `pkgs.macmon.version >= 0.10.0`, otherwise from Homebrew.** 0.10.0 is the first release that reads power on macOS 27. The module picks automatically.
4. **The pull loop's plist calls `/run/current-system/sw/bin/home-ops-pull` through `/bin/sh -c`, not a store path.** nix-darwin reloads a daemon only when its plist changes. Reloading the pull loop would kill the `darwin-rebuild` it is running.
5. **Sub-keys are reconciled from sops by a small daemon.** The admin API's sub-key body shape is confirmed against `/openapi.json` at implementation time (Task 5, Step 6).
6. **Consumer connect timeouts (spec Failure handling) are out of scope here.** Each consumer gets its timeout when it is cut over (spec Phase 3.3).

## File structure

```
macos/
  flake.nix                       # inputs + darwinConfigurations.mac-jms-01
  flake.lock                      # generated on the Mac (Task 1)
  README.md                       # how the flake is applied, tested, rolled back
  hosts/mac-jms-01/
    default.nix                   # imports the modules below
    facts.nix                     # ADMIN_USER, MAC_IP, cluster IPs (non-secret)
  modules/
    base.nix                      # Determinate, users, Homebrew zap, updates off, sshd, sops key
    pull-loop.nix                 # launchd timer → home-ops-pull
    server.nix                    # wired limit, power, /opt/ai, log dirs, newsyslog
    omlx.nix                      # _omlx user, oMLX daemon, sub-key reconciler, secrets
    observability.nix             # node_exporter, macmon, omlx-exporter, vector
    pf.nix                        # pf ruleset + enforcer daemon + textfile metric
  scripts/
    home-ops-pull.sh              # pull loop body
    test-home-ops-pull.sh         # bash test harness (runs on Linux and macOS)
    omlx-sub-keys.sh              # sub-key reconciler body
  pkgs/omlx-exporter/
    omlx_exporter.py              # stdlib exporter
    test_omlx_exporter.py         # unittest
  engines/omlx/
    pyproject.toml                # uv project pinning oMLX
    uv.lock                       # generated on the Mac (Task 5)
  secrets/
    mac-jms-01.sops.yaml          # omlx main key + sub keys (both age keys)
.sops.yaml                        # + rule for macos/secrets/
.taskfiles/mac/Taskfile.yaml      # apply-local, build-local, omlx-lock, status, reboot
Taskfile.yaml                     # + include mac
.github/workflows/macos-nix.yaml  # PR CI on macos-15
.github/renovate.json5            # + nix manager
.renovate/customManagers.json5    # + oMLX git-tag manager
.renovate/autoMerge.json5         # + never automerge macos/**
kubernetes/apps/ai/kustomization.yaml          # + ./mac-inference/ks.yaml
kubernetes/apps/ai/mac-inference/
  ks.yaml
  app/kustomization.yaml
  app/service.yaml                # Service + EndpointSlice (the one place MAC_IP lives in k8s)
  app/vmstaticscrape.yaml
  app/prometheusrule.yaml
  app/grafanadashboard.yaml
  app/httproute.yaml              # omlx.68cc.io admin, internal + forwardAuth
kubernetes/apps/services/gatus/app/
  helmrelease.yaml                # + endpoint, envFrom, reloader
  secret.sops.yaml                # MAC_INFERENCE_GATUS_KEY
  kustomization.yaml              # + secret
docs/runbooks/mac-studio-operations.md         # reboot, unlock, OS update, rollback, rotation
```

---

### Task 1: Flake scaffold, base module, mac taskfile, first apply

**Files:**
- Create: `macos/flake.nix`, `macos/hosts/mac-jms-01/default.nix`, `macos/hosts/mac-jms-01/facts.nix`, `macos/modules/base.nix`, `macos/README.md`, `.taskfiles/mac/Taskfile.yaml`
- Create (generated on the Mac): `macos/flake.lock`
- Modify: `Taskfile.yaml` (includes), `.gitignore` (add `macos/result*`)

**Interfaces:**
- Consumes: the §9 facts from `docs/runbooks/mac-studio-bringup.md`.
- Produces:
  - Flake output `darwinConfigurations.mac-jms-01`.
  - The module args `facts` (an attrset with `hostName`, `adminUser`, `lanIp`, `clusterNodeIps`) and `self`.
  - Tasks `mac:apply-local`, `mac:build-local`, `mac:status`.
  - Later tasks add one line each to `imports` in `hosts/mac-jms-01/default.nix`.

- [ ] **Step 1: Write `macos/hosts/mac-jms-01/facts.nix`.** Substitute the operator's §9 values for `ADMIN_USER` and `MAC_IP`:

```nix
# Non-secret facts about the Mac Studio, recorded during manual bring-up
# (docs/runbooks/mac-studio-bringup.md §9). The Mac's IP is also in
# kubernetes/apps/ai/mac-inference/app/service.yaml (EndpointSlice) and
# nowhere else.
{
  hostName = "mac-jms-01";
  adminUser = "j0sh3rs";
  lanIp = "192.168.35.7";
  # Cluster node IPs. Cilium masquerades pod egress to the node IP, so these
  # are the only sources pf has to admit. bigboi-jms-01 (.4) leaves at
  # spec Phase 3.5 -- remove it here in that change.
  clusterNodeIps = [
    "192.168.35.3"  # bee-jms-01
    "192.168.35.6"  # bee-jms-02
    "192.168.35.10" # bee-jms-03
    "192.168.35.4"  # bigboi-jms-01
  ];
}
```

- [ ] **Step 2: Write `macos/flake.nix`**

```nix
{
  description = "home-ops macOS hosts (nix-darwin). Applied by the pull loop in modules/pull-loop.nix.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-26.05-darwin";
    nix-darwin = {
      url = "github:nix-darwin/nix-darwin/nix-darwin-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # Determinate owns the Nix daemon and nix.conf; its module replaces
    # nix-darwin's nix.* management (determinateNix.*, needs Determinate Nix >= 3.15.2).
    determinate.url = "https://flakehub.com/f/DeterminateSystems/determinate/3";
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nix-darwin, determinate, sops-nix, ... }: {
    darwinConfigurations.mac-jms-01 = nix-darwin.lib.darwinSystem {
      specialArgs = {
        inherit self;
        facts = import ./hosts/mac-jms-01/facts.nix;
      };
      modules = [
        determinate.darwinModules.default
        sops-nix.darwinModules.sops
        ./hosts/mac-jms-01
      ];
    };
  };
}
```

- [ ] **Step 3: Write `macos/hosts/mac-jms-01/default.nix`**

```nix
{ ... }:
{
  imports = [
    ../../modules/base.nix
  ];
}
```

- [ ] **Step 4: Write `macos/modules/base.nix`**

```nix
# Base system: Nix, identity, Homebrew, update policy, sshd, sops key.
{ pkgs, self, facts, ... }:
{
  nixpkgs.hostPlatform = "aarch64-darwin";

  determinateNix.enable = true;
  determinateNix.customSettings = {
    trusted-users = [ "root" facts.adminUser ];
  };

  networking.hostName = facts.hostName;
  networking.computerName = facts.hostName;
  networking.localHostName = facts.hostName;

  system.primaryUser = facts.adminUser;
  # darwin-version --json reports the commit this generation was built from
  # (null for task mac:apply-local, which builds from an untracked copy).
  system.configurationRevision = self.rev or self.dirtyRev or null;
  system.stateVersion = 6;

  environment.systemPackages = with pkgs; [ age git jq sops ];

  # Homebrew is only for things nixpkgs lacks. "zap" removes anything not
  # declared here, including by-hand installs (see the bring-up checklist).
  homebrew = {
    enable = true;
    onActivation = {
      cleanup = "zap";
      autoUpdate = false;
      upgrade = false;
    };
    brews = [ ];
    casks = [ ];
  };

  # macOS updates are a manual runbook step (docs/runbooks/mac-studio-operations.md):
  # an unattended update reboots into a FileVault-locked pre-boot screen.
  # ConfigDataInstall stays on: XProtect/Gatekeeper data, no restart.
  system.defaults.SoftwareUpdate.AutomaticallyInstallMacOSUpdates = false;
  system.defaults.CustomSystemPreferences = {
    "com.apple.SoftwareUpdate" = {
      AutomaticCheckEnabled = true;
      AutomaticDownload = false;
      CriticalUpdateInstall = false;
      ConfigDataInstall = true;
    };
    "com.apple.commerce".AutoUpdate = false;
  };

  # Key-only SSH. sshd keeps the first value it reads for each keyword and
  # reads sshd_config.d/ in lexical order, so 000- beats Apple's
  # 100-macos.conf and nix-darwin's 100-nix-darwin.conf.
  services.openssh.enable = true;
  environment.etc."ssh/sshd_config.d/000-home-ops.conf".text = ''
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PermitRootLogin no
  '';

  # Mac-only age key, created by hand (bring-up checklist §8). Secrets
  # themselves are declared by the modules that use them.
  sops.age.keyFile = "/var/lib/sops-nix/key.txt";
}
```

- [ ] **Step 5: Write `.taskfiles/mac/Taskfile.yaml`**

```yaml
---
# yaml-language-server: $schema=https://taskfile.dev/schema.json
version: "3"

# Every task reaches the Mac as `ssh mac-jms-01` -- set up the Host alias
# per docs/runbooks/mac-studio-bringup.md §5. Remote commands run through a
# login shell so Determinate's /nix/var/nix/profiles/default/bin is on PATH.

vars:
  MAC_HOST: mac-jms-01
  MACOS_DIR: "{{.ROOT_DIR}}/macos"
  REMOTE_DIR: home-ops-macos

tasks:
  sync:
    internal: true
    cmds:
      - tar -C {{.MACOS_DIR}} --exclude='./result*' -cf - . | ssh {{.MAC_HOST}} 'rm -rf ~/{{.REMOTE_DIR}} && mkdir -p ~/{{.REMOTE_DIR}} && tar -C ~/{{.REMOTE_DIR}} -xf -'

  build-local:
    desc: Copy macos/ to the Mac and build the darwin closure (no sudo, no switch)
    cmds:
      - task: sync
      - ssh {{.MAC_HOST}} 'zsh -lc "cd ~/{{.REMOTE_DIR}} && nix build .#darwinConfigurations.mac-jms-01.system --no-link --print-out-paths"'

  apply-local:
    desc: Copy macos/ to the Mac and darwin-rebuild switch from it (pre-merge testing; the pull loop re-applies main when main next moves)
    prompt: darwin-rebuild switch mac-jms-01 from your working copy of macos/?
    cmds:
      - task: sync
      - ssh -t {{.MAC_HOST}} 'zsh -lc "cd ~/{{.REMOTE_DIR}} && if command -v darwin-rebuild >/dev/null; then sudo darwin-rebuild switch --flake .#mac-jms-01; else sudo nix run nix-darwin/nix-darwin-26.05#darwin-rebuild -- switch --flake .#mac-jms-01; fi"'

  lock:
    desc: Regenerate macos/flake.lock on the Mac and copy it back
    cmds:
      - task: sync
      - ssh {{.MAC_HOST}} 'zsh -lc "cd ~/{{.REMOTE_DIR}} && nix flake lock"'
      - scp {{.MAC_HOST}}:{{.REMOTE_DIR}}/flake.lock {{.MACOS_DIR}}/flake.lock

  status:
    desc: Show the Mac's generation, daemons, and home-ops textfile metrics
    cmds:
      - ssh {{.MAC_HOST}} 'zsh -lc "darwin-version --json 2>/dev/null || true; launchctl list | grep org.nixos || true; cat /var/lib/node-exporter/textfile/*.prom 2>/dev/null || true"'
```

- [ ] **Step 6: Register the taskfile.** In `Taskfile.yaml` `includes:`, add `mac: .taskfiles/mac` between `flux` and `sops`, keeping alphabetical order. Append `macos/result*` to `.gitignore`.

- [ ] **Step 7: Write `macos/README.md`**

````markdown
# macos/ — nix-darwin for the Mac Studio

Spec: `docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md`.

- **How it applies:** `modules/pull-loop.nix` runs every 5 minutes and
  `darwin-rebuild switch`es `github:j0sh3rs/home-ops/<main sha>?dir=macos#mac-jms-01`
  whenever `main` moves. Merging to `main` *is* deploying.
- **Before merge:** `task mac:build-local` (build only) or `task mac:apply-local`
  (switch from your working copy). The next move of `main` re-applies `main`.
- **CI:** `.github/workflows/macos-nix.yaml` builds the closure on a hosted macOS
  runner and posts `nix store diff-closures` on the PR.
- **Rollback:** `git revert` on main (the loop applies it), or on the Mac
  `sudo darwin-rebuild --rollback`. The loop doesn't undo a local rollback
  until main moves again.
- **Secrets:** `secrets/*.sops.yaml`, encrypted to the repo key and the Mac's
  own age key (`/var/lib/sops-nix/key.txt` on the Mac). Edit with
  `sops macos/secrets/mac-jms-01.sops.yaml`.
- **Health:** textfile metrics under `/var/lib/node-exporter/textfile/`, scraped
  via `kubernetes/apps/ai/mac-inference/`.
- **Homebrew:** `cleanup = "zap"` — only declare packages here; by-hand
  installs are removed on the next apply.
````

- [ ] **Step 8: Generate the lock and build** *(on Mac, no sudo)*

Run: `task mac:lock && task mac:build-local`
Expected:
- `macos/flake.lock` is written locally.
- The build prints one `/nix/store/…-darwin-system-…` path.
- If `nixpkgs-26.05-darwin` or `nix-darwin-26.05` is missing, `nix flake lock` fails with "unable to find branch". Use the newest `nixpkgs-YY.MM-darwin` / `nix-darwin-YY.MM` pair that `git ls-remote` lists, and change all three references: the two flake URLs and `apply-local`.
- If any `determinateNix.*` option is reported as nonexistent, read the module's options with `nix eval --json 'https://flakehub.com/f/DeterminateSystems/determinate/3#darwinModules.default' 2>&1 | head` and https://docs.determinate.systems/guides/nix-darwin/, then fix the option names.

- [ ] **Step 9: First apply** **OPERATOR**

Ask the operator to run `task mac:apply-local`, then these checks:

Run (operator, on the Mac):
```
sudo sshd -T | grep -iE '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin)'
defaults read /Library/Preferences/com.apple.SoftwareUpdate
darwin-version --json
```
Expected:
- sshd prints `passwordauthentication no`, `kbdinteractiveauthentication no`, `permitrootlogin no`.
- The SoftwareUpdate domain shows `AutomaticDownload = 0`, `CriticalUpdateInstall = 0`, `ConfigDataInstall = 1`.
- `darwin-version --json` prints JSON.

Then ask the operator to do checklist §11, the pre-boot unlock test, and record the outcome in the ledger.

- [ ] **Step 10: Commit**

```bash
git add macos/flake.nix macos/flake.lock macos/README.md macos/hosts macos/modules/base.nix \
  .taskfiles/mac/Taskfile.yaml Taskfile.yaml .gitignore
git commit -m "feat(macos): scaffold nix-darwin flake for the Mac Studio

Spec Phase 0.3/1.1. Determinate owns Nix; nix-darwin owns everything else.
Updates are off because an unattended update reboots into FileVault
pre-boot; sshd is key-only via a 000- drop-in that wins over Apple's.
task mac:apply-local lets us test before the pull loop exists.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: PR CI on macOS and Renovate

**Files:**
- Create: `.github/workflows/macos-nix.yaml`
- Modify: `.github/renovate.json5`, `.renovate/customManagers.json5`, `.renovate/autoMerge.json5`

**Interfaces:**
- Consumes: `macos/flake.nix` output `darwinConfigurations.mac-jms-01.system` (Task 1).
- Produces:
  - A PR check named **"macOS Nix / Build darwin closure"**, plus a sticky PR comment that starts with `## macOS closure diff`.
  - Two test runners that later tasks append test commands to: `macos/scripts/test-home-ops-pull.sh` and `python3 -m unittest discover -s macos/pkgs/omlx-exporter`. The workflow runs them only if the files exist.

- [ ] **Step 1: Write `.github/workflows/macos-nix.yaml`**

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/github-workflow.json
name: macOS Nix

# Builds the Mac Studio's darwin closure on a GitHub-hosted Apple-silicon
# runner (the in-cluster home-ops-runner is Linux) and posts
# `nix store diff-closures` against the PR base. Merging to main deploys
# (macos/modules/pull-loop.nix), so this check is the only pre-merge gate.
on:
  pull_request:
    paths:
      - "macos/**"
      - ".github/workflows/macos-nix.yaml"
  push:
    branches:
      - "renovate/**"
    paths:
      - "macos/**"

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read
  pull-requests: write

jobs:
  build:
    name: Build darwin closure
    runs-on: macos-15
    steps:
      - name: Checkout
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0

      - name: Install Determinate Nix
        uses: DeterminateSystems/determinate-nix-action@v3

      - name: Unit tests
        run: |
          if [ -f macos/scripts/test-home-ops-pull.sh ]; then bash macos/scripts/test-home-ops-pull.sh; fi
          if [ -d macos/pkgs/omlx-exporter ]; then python3 -m unittest discover -s macos/pkgs/omlx-exporter -v; fi

      - name: Check uv lock is current
        run: |
          if [ -f macos/engines/omlx/pyproject.toml ]; then
            nix run nixpkgs#uv -- lock --check --project macos/engines/omlx
          fi

      - name: Build head closure
        run: nix build ./macos#darwinConfigurations.mac-jms-01.system --out-link result-head --print-build-logs

      - name: Build base closure
        if: ${{ github.event_name == 'pull_request' }}
        run: |
          git worktree add /tmp/macos-base "${{ github.event.pull_request.base.sha }}"
          if [ -f /tmp/macos-base/macos/flake.nix ]; then
            nix build /tmp/macos-base/macos#darwinConfigurations.mac-jms-01.system --out-link result-base
          fi

      - name: Diff closures
        if: ${{ github.event_name == 'pull_request' }}
        run: |
          {
            echo '## macOS closure diff'
            echo ''
            if [ -e result-base ]; then
              echo '```'
              nix store diff-closures ./result-base ./result-head || true
              echo '```'
            else
              echo '_No base closure: first PR that adds macos/._'
            fi
          } > comment.md

      - name: Comment on PR
        if: ${{ github.event_name == 'pull_request' }}
        uses: actions/github-script@3a2844b7e9c422d3c10d287c895573f7108da1b3 # v9.0.0
        with:
          script: |
            const fs = require('fs');
            const body = fs.readFileSync('comment.md', 'utf8');
            const marker = '## macOS closure diff';
            const { data: comments } = await github.rest.issues.listComments({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.payload.pull_request.number,
            });
            const prior = comments.reverse().find(c =>
              c.user.type === 'Bot' && c.body.startsWith(marker));
            if (prior) {
              await github.rest.issues.updateComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                comment_id: prior.id,
                body,
              });
            } else {
              await github.rest.issues.createComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: context.payload.pull_request.number,
                body,
              });
            }
```

- [ ] **Step 2: Renovate nix manager.** In `.github/renovate.json5`, add this after the `kubernetes:` block:

```json5
  // macos/flake.lock. Branch-tracking inputs (nixpkgs-26.05-darwin) only
  // move via lock-file maintenance. Never automerged: merging deploys to the
  // Mac (see .renovate/autoMerge.json5).
  nix: {
    enabled: true,
    lockFileMaintenance: {
      enabled: true,
      schedule: ['before 6am on monday'],
    },
  },
```

- [ ] **Step 3: Custom manager for the oMLX git tag.** Append to the `customManagers` array in `.renovate/customManagers.json5`:

```json5
    {
      customType: "regex",
      description: "oMLX pinned by git tag in the Mac's uv project. Renovate cannot regenerate uv.lock for a git dependency: the macOS Nix check fails until someone runs `task mac:omlx-lock` and pushes to the PR branch",
      fileMatch: ["(^|/)macos/engines/.+/pyproject\\.toml$"],
      matchStrings: [
        "git\\+https://github\\.com/(?<depName>[^/@\\s]+/[^/@\\s\"]+)@(?<currentValue>v[^\"\\s]+)",
      ],
      datasourceTemplate: "github-releases",
      versioningTemplate: "semver",
    },
```

- [ ] **Step 4: Never automerge macos/.** Append to the end of the `packageRules` array in `.renovate/autoMerge.json5`. It is last so it overrides the generic non-major automerge rule:

```json5
    {
      description: "macos/: merging deploys to the Mac via the pull loop, and engine bumps need an eval replay (spec: Failure handling) — never auto-merge; pep621 is off because oMLX is a git dep handled by the custom manager",
      matchFileNames: ["macos/**"],
      automerge: false,
    },
    {
      description: "macos/engines: uv.lock for a git dependency can't be maintained by Renovate",
      matchFileNames: ["macos/engines/**"],
      matchManagers: ["pep621"],
      enabled: false,
    },
```

- [ ] **Step 5: Validate**

Run: `npx --yes --package renovate -- renovate-config-validator --strict .github/renovate.json5 .renovate/customManagers.json5 .renovate/autoMerge.json5`
Expected: `Config validated successfully` for each file. If `--strict` objects to `lockFileMaintenance` inside `nix`, move that block to the top level of `renovate.json5` and add a `packageRules` entry `{matchManagers: ['nix'], matchUpdateTypes: ['lockFileMaintenance'], enabled: true}` alongside top-level `lockFileMaintenance: {enabled: false}`.

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/macos-nix.yaml'))" && echo ok`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/macos-nix.yaml .github/renovate.json5 .renovate/customManagers.json5 .renovate/autoMerge.json5
git commit -m "ci(macos): build the darwin closure on macos-15 and track flake inputs

Merging to main deploys to the Mac, so the PR build plus diff-closures is
the only pre-merge gate. Renovate gets the nix manager and an oMLX tag
manager; macos/ never automerges.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Pull loop and apply-health metrics

**Files:**
- Create: `macos/scripts/home-ops-pull.sh`, `macos/scripts/test-home-ops-pull.sh`, `macos/modules/pull-loop.nix`
- Modify: `macos/hosts/mac-jms-01/default.nix` (import)

**Interfaces:**
- Consumes: `facts` (Task 1). CI runs `macos/scripts/test-home-ops-pull.sh` (Task 2).
- Produces:
  - **Textfile:** `/var/lib/node-exporter/textfile/home_ops_pull.prom` with these gauges:
    - `home_ops_nix_apply_last_attempt_timestamp_seconds`
    - `home_ops_nix_apply_last_in_sync_timestamp_seconds`
    - `home_ops_nix_apply_last_exit_code`
    - `home_ops_nix_apply_behind_main` (absent when main could not be read)
    - `home_ops_nix_apply_info{commit}`
    - `home_ops_nix_main_info{commit}`
  - **Directories:** `/var/lib/node-exporter/textfile` and `/var/log/home-ops`, created here and used by every later daemon.
  - **Launchd label:** `org.nixos.home-ops-pull`.

- [ ] **Step 1: Write the failing test `macos/scripts/test-home-ops-pull.sh`**

```bash
#!/usr/bin/env bash
# Tests home-ops-pull.sh against a throwaway git repo and a fake darwin-rebuild.
# Runs on Linux and macOS: bash macos/scripts/test-home-ops-pull.sh
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

git init -q -b main "$work/repo"
git -C "$work/repo" -c user.email=t@t -c user.name=t commit -q --allow-empty -m one
first=$(git -C "$work/repo" rev-parse HEAD)

cat > "$work/rebuild" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$REBUILD_LOG"
exit "${REBUILD_RC:-0}"
EOF
chmod +x "$work/rebuild"

export HOME_OPS_REPO_URL="$work/repo"
export HOME_OPS_FLAKE_REPO="github:example/repo"
export HOME_OPS_STATE_DIR="$work/state"
export HOME_OPS_TEXTFILE_DIR="$work/textfile"
export HOME_OPS_REBUILD="$work/rebuild"
export REBUILD_LOG="$work/rebuild.log"
prom="$work/textfile/home_ops_pull.prom"

fail() { echo "FAIL: $*"; echo "--- prom:"; cat "$prom" 2>/dev/null || true; exit 1; }
metric() { awk -v m="$1" '$1 == m { print $2 }' "$prom"; }

# 1. First run applies main and is in sync.
bash "$here/home-ops-pull.sh" || fail "first run exited non-zero"
grep -qx "switch --flake github:example/repo/${first}?dir=macos#mac-jms-01" "$REBUILD_LOG" || fail "rebuild not called with pinned commit"
[ "$(metric home_ops_nix_apply_behind_main)" = 0 ] || fail "behind after first apply"
[ "$(metric home_ops_nix_apply_last_exit_code)" = 0 ] || fail "exit code not 0"
grep -q "home_ops_nix_apply_info{commit=\"${first}\"} 1" "$prom" || fail "applied commit info missing"
[ "$(metric home_ops_nix_apply_last_in_sync_timestamp_seconds)" -gt 0 ] || fail "in-sync timestamp not set"

# 2. Unchanged main: no rebuild.
bash "$here/home-ops-pull.sh" || fail "second run exited non-zero"
[ "$(wc -l < "$REBUILD_LOG")" -eq 1 ] || fail "rebuilt although main did not move"

# 3. main moves, rebuild fails: behind, exit code recorded, script fails.
git -C "$work/repo" -c user.email=t@t -c user.name=t commit -q --allow-empty -m two
second=$(git -C "$work/repo" rev-parse HEAD)
if REBUILD_RC=7 bash "$here/home-ops-pull.sh"; then fail "failed rebuild should exit non-zero"; fi
[ "$(metric home_ops_nix_apply_behind_main)" = 1 ] || fail "not behind after failed apply"
[ "$(metric home_ops_nix_apply_last_exit_code)" = 7 ] || fail "exit code not 7"
grep -q "home_ops_nix_apply_info{commit=\"${first}\"} 1" "$prom" || fail "applied commit should still be the first"
grep -q "home_ops_nix_main_info{commit=\"${second}\"} 1" "$prom" || fail "main info missing"

# 4. Retry succeeds.
bash "$here/home-ops-pull.sh" || fail "retry exited non-zero"
[ "$(metric home_ops_nix_apply_behind_main)" = 0 ] || fail "behind after successful retry"

# 5. Unreachable repo: exit 2, no behind metric, in-sync timestamp kept.
kept=$(metric home_ops_nix_apply_last_in_sync_timestamp_seconds)
if HOME_OPS_REPO_URL="$work/missing" bash "$here/home-ops-pull.sh"; then fail "unreachable repo should exit non-zero"; fi
[ "$(metric home_ops_nix_apply_last_exit_code)" = 2 ] || fail "exit code not 2"
[ -z "$(metric home_ops_nix_apply_behind_main)" ] || fail "behind metric should be absent when main is unknown"
[ "$(metric home_ops_nix_apply_last_in_sync_timestamp_seconds)" = "$kept" ] || fail "in-sync timestamp moved"

# 6. No stray temp files in the textfile dir.
[ "$(find "$work/textfile" -type f | wc -l)" -eq 1 ] || fail "temp files left behind"

echo "PASS: home-ops-pull"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash macos/scripts/test-home-ops-pull.sh`
Expected: it fails with `bash: …/home-ops-pull.sh: No such file or directory` and the message `FAIL: first run exited non-zero`.

- [ ] **Step 3: Write `macos/scripts/home-ops-pull.sh`**

```bash
#!/usr/bin/env bash
# home-ops-pull: apply main of j0sh3rs/home-ops to this Mac whenever main
# moves -- the Mac's equivalent of Flux. Run every 5 minutes by
# macos/modules/pull-loop.nix. Health goes to a node_exporter textfile;
# alerts are in kubernetes/apps/ai/mac-inference/app/prometheusrule.yaml.
#
# Exit codes: 0 in sync, 2 could not read main, else darwin-rebuild's code.
set -euo pipefail

REPO_URL="${HOME_OPS_REPO_URL:-https://github.com/j0sh3rs/home-ops}"
FLAKE_REPO="${HOME_OPS_FLAKE_REPO:-github:j0sh3rs/home-ops}"
STATE_DIR="${HOME_OPS_STATE_DIR:-/var/lib/home-ops-pull}"
TEXTFILE_DIR="${HOME_OPS_TEXTFILE_DIR:-/var/lib/node-exporter/textfile}"
REBUILD="${HOME_OPS_REBUILD:-darwin-rebuild}"

mkdir -p "$STATE_DIR" "$TEXTFILE_DIR"
now=$(date +%s)
applied=$(cat "$STATE_DIR/applied-commit" 2>/dev/null || true)
in_sync_at=$(cat "$STATE_DIR/in-sync-at" 2>/dev/null || echo 0)
rc=0
head=""

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

if ! head=$(git ls-remote "$REPO_URL" refs/heads/main | cut -f1) || [ -z "$head" ]; then
  log "could not read main from $REPO_URL"
  head=""
  rc=2
elif [ "$head" != "$applied" ]; then
  log "applying $head (was ${applied:-nothing})"
  if "$REBUILD" switch --flake "${FLAKE_REPO}/${head}?dir=macos#mac-jms-01"; then
    applied="$head"
    printf '%s\n' "$applied" > "$STATE_DIR/applied-commit"
    log "applied $head"
  else
    rc=$?
    log "darwin-rebuild failed with $rc"
  fi
fi

if [ -n "$head" ] && [ "$head" = "$applied" ]; then
  in_sync_at=$now
  printf '%s\n' "$in_sync_at" > "$STATE_DIR/in-sync-at"
fi

tmp=$(mktemp "$TEXTFILE_DIR/.home_ops_pull.XXXXXX")
{
  echo "# HELP home_ops_nix_apply_last_attempt_timestamp_seconds Last pull-loop run."
  echo "# TYPE home_ops_nix_apply_last_attempt_timestamp_seconds gauge"
  echo "home_ops_nix_apply_last_attempt_timestamp_seconds $now"
  echo "# HELP home_ops_nix_apply_last_in_sync_timestamp_seconds Last run that ended with main applied."
  echo "# TYPE home_ops_nix_apply_last_in_sync_timestamp_seconds gauge"
  echo "home_ops_nix_apply_last_in_sync_timestamp_seconds $in_sync_at"
  echo "# HELP home_ops_nix_apply_last_exit_code 0 in sync, 2 main unreadable, else darwin-rebuild exit code."
  echo "# TYPE home_ops_nix_apply_last_exit_code gauge"
  echo "home_ops_nix_apply_last_exit_code $rc"
  if [ -n "$head" ]; then
    echo "# HELP home_ops_nix_apply_behind_main 1 if the applied commit is not main."
    echo "# TYPE home_ops_nix_apply_behind_main gauge"
    if [ "$head" = "$applied" ]; then echo "home_ops_nix_apply_behind_main 0"; else echo "home_ops_nix_apply_behind_main 1"; fi
    echo "# HELP home_ops_nix_main_info Commit main pointed at on the last run."
    echo "# TYPE home_ops_nix_main_info gauge"
    echo "home_ops_nix_main_info{commit=\"$head\"} 1"
  fi
  if [ -n "$applied" ]; then
    echo "# HELP home_ops_nix_apply_info Commit last applied by the pull loop."
    echo "# TYPE home_ops_nix_apply_info gauge"
    echo "home_ops_nix_apply_info{commit=\"$applied\"} 1"
  fi
} > "$tmp"
chmod 644 "$tmp"
mv "$tmp" "$TEXTFILE_DIR/home_ops_pull.prom"

exit "$rc"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `bash macos/scripts/test-home-ops-pull.sh`
Expected: `PASS: home-ops-pull`

Run: `shellcheck macos/scripts/home-ops-pull.sh macos/scripts/test-home-ops-pull.sh` (if shellcheck is missing, the Nix build's `writeShellApplication` check in Step 6 covers the main script).
Expected: no output.

- [ ] **Step 5: Write `macos/modules/pull-loop.nix`**

```nix
# Pull loop: apply main every time it moves (scripts/home-ops-pull.sh).
{ pkgs, ... }:
let
  pull = pkgs.writeShellApplication {
    name = "home-ops-pull";
    runtimeInputs = with pkgs; [ coreutils git ];
    text = builtins.readFile ../scripts/home-ops-pull.sh;
  };
in
{
  environment.systemPackages = [ pull ];

  system.activationScripts.postActivation.text = ''
    install -d -m 0755 -o root -g wheel /var/log/home-ops /var/lib/node-exporter/textfile /var/lib/home-ops-pull
  '';

  launchd.daemons.home-ops-pull.serviceConfig = {
    # Through the system profile, not a store path: a script change must not
    # change this plist. nix-darwin reloads a daemon whose plist changed,
    # and reloading this one would kill the darwin-rebuild it is running.
    # Changes to this block itself: apply with `task mac:apply-local`.
    ProgramArguments = [ "/bin/sh" "-c" "exec /run/current-system/sw/bin/home-ops-pull" ];
    EnvironmentVariables.PATH = "/run/current-system/sw/bin:/nix/var/nix/profiles/default/bin:/usr/bin:/bin:/usr/sbin:/sbin";
    RunAtLoad = true;
    StartInterval = 300;
    StandardOutPath = "/var/log/home-ops/home-ops-pull.log";
    StandardErrorPath = "/var/log/home-ops/home-ops-pull.log";
  };
}
```

Add `../../modules/pull-loop.nix` to `imports` in `macos/hosts/mac-jms-01/default.nix`.

- [ ] **Step 6: Build** *(on Mac, no sudo)*

Run: `task mac:build-local`
Expected: a store path. shellcheck runs inside `writeShellApplication`, and any warning fails the build.

- [ ] **Step 7: Commit**

```bash
git add macos/scripts/home-ops-pull.sh macos/scripts/test-home-ops-pull.sh macos/modules/pull-loop.nix macos/hosts/mac-jms-01/default.nix
git commit -m "feat(macos): pull loop applies main and reports apply health

Spec Phase 1.2. Pins each apply to the commit it read so a mid-apply push
can't mix revisions. The in-sync timestamp (not the last apply) feeds the
24h staleness alert, so a quiet main doesn't page. The plist goes through
the system profile so a script change can't kill a running switch.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Server settings: wired limit, power, Spotlight-safe dirs, log rotation

**Files:**
- Create: `macos/modules/server.nix`
- Modify: `macos/hosts/mac-jms-01/default.nix` (import)

**Interfaces:**
- Consumes: `/var/lib/node-exporter/textfile` and `/var/log/home-ops` (Task 3).
- Produces:
  - **Textfile:** `home_ops_wired_limit.prom` with gauge `home_ops_iogpu_wired_limit_bytes`.
  - **Directory:** `/opt/ai`, owned by root, mode 0755.
  - **Convention:** every large data dir under `/opt/ai` ends in `.noindex`, so Spotlight skips it.
  - **Log rotation:** newsyslog rotates `/var/log/home-ops/*.log`.

- [ ] **Step 1: Write `macos/modules/server.nix`**

```nix
# Dedicated-server settings (spec: Server settings).
{ pkgs, ... }:
let
  # ~84 GB for GPU-wired memory. oMLX's own guard is 80 GB (omlx.nix);
  # the rest is ~12 GB for macOS and the agents. sysctl does not persist,
  # so a daemon sets it at boot and re-asserts hourly.
  wiredLimitMb = 86016;

  wiredLimit = pkgs.writeShellApplication {
    name = "home-ops-wired-limit";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      /usr/sbin/sysctl -w iogpu.wired_limit_mb=${toString wiredLimitMb}
      got=$(/usr/sbin/sysctl -n iogpu.wired_limit_mb)
      dir=/var/lib/node-exporter/textfile
      tmp=$(mktemp "$dir/.wired_limit.XXXXXX")
      {
        echo "# HELP home_ops_iogpu_wired_limit_bytes iogpu.wired_limit_mb currently in effect, in bytes."
        echo "# TYPE home_ops_iogpu_wired_limit_bytes gauge"
        echo "home_ops_iogpu_wired_limit_bytes $(( got * 1024 * 1024 ))"
      } > "$tmp"
      chmod 644 "$tmp"
      mv "$tmp" "$dir/home_ops_wired_limit.prom"
    '';
  };
in
{
  launchd.daemons.home-ops-wired-limit.serviceConfig = {
    ProgramArguments = [ "${wiredLimit}/bin/home-ops-wired-limit" ];
    RunAtLoad = true;
    StartInterval = 3600;
    StandardOutPath = "/var/log/home-ops/home-ops-wired-limit.log";
    StandardErrorPath = "/var/log/home-ops/home-ops-wired-limit.log";
  };

  # Never sleep; come back after a power cut (then FileVault pre-boot
  # unlock over SSH, see docs/runbooks/mac-studio-operations.md).
  power.sleep.computer = "never";
  power.sleep.harddisk = "never";
  power.sleep.display = 10;
  power.restartAfterPowerFailure = true;

  system.activationScripts.postActivation.text = ''
    /usr/bin/pmset -a powernap 0 || echo "pmset: powernap not supported"
    /usr/bin/pmset -a womp 1 || echo "pmset: womp not supported"
    # Spotlight skips any directory whose name ends in .noindex; every model
    # or KV-cache dir under /opt/ai uses that suffix (omlx.nix).
    install -d -m 0755 -o root -g wheel /opt/ai
  '';

  # Rotate our daemons' logs: keep 7, rotate at 10 MB, G = glob, N = no signal.
  environment.etc."newsyslog.d/home-ops.conf".text = ''
    # logfilename              mode count size  when flags
    /var/log/home-ops/*.log    644  7     10240 *    GN
  '';
}
```

Add `../../modules/server.nix` to `imports` in `macos/hosts/mac-jms-01/default.nix`.

- [ ] **Step 2: Build** *(on Mac, no sudo)*

Run: `task mac:build-local`
Expected:
- The build prints a store path.
- If `power.sleep.*` or `power.restartAfterPowerFailure` is reported as a nonexistent option, replace them with `/usr/bin/pmset -a sleep 0 disksleep 0 displaysleep 10 autorestart 1` lines in `postActivation`, written in the same `|| echo` style.

- [ ] **Step 3: Commit**

```bash
git add macos/modules/server.nix macos/hosts/mac-jms-01/default.nix
git commit -m "feat(macos): wired-memory limit, never-sleep, Spotlight-safe /opt/ai

Spec Phase 1.3. iogpu.wired_limit_mb=86016 (~84 GB) is set at boot and
hourly because sysctl doesn't persist; its value is a metric so the
wired-near-limit alert has a denominator. .noindex dirs keep Spotlight out
of model and KV-cache trees.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: oMLX engine daemon, Mac secrets, sub-key reconciler

**Files:**
- Create: `macos/engines/omlx/pyproject.toml`, `macos/engines/omlx/uv.lock` (generated on the Mac), `macos/modules/omlx.nix`, `macos/scripts/omlx-sub-keys.sh`, `macos/secrets/mac-jms-01.sops.yaml`
- Modify:
  - `.sops.yaml`: add the `macos/secrets/` rule
  - `.taskfiles/mac/Taskfile.yaml`: add the `omlx-lock` task
  - `macos/hosts/mac-jms-01/default.nix`: import the new module

**Interfaces:**
- Consumes: `/opt/ai` (Task 4) and `/var/log/home-ops` (Task 3).
- Produces:
  - **Service user:** `_omlx` (uid/gid 455).
  - **Engine:** oMLX on `0.0.0.0:8000`, OpenAI API at `/v1/*`, admin at `/admin`.
  - **sops secrets:** `omlx/main-key` and `omlx/sub-keys/<name>`, both owned by `_omlx`.
  - **Nix attr:** `omlxSubKeyNames = [ "gatus" ]`, defined in `omlx.nix`.
  - **Launchd labels:** `org.nixos.omlx` and `org.nixos.omlx-sub-keys`.
  - **Server log:** `/opt/ai/omlx/home/.omlx/logs/server.log`.
  - **Gatus key:** the plaintext value of `omlx/sub-keys/gatus`. Task 8 needs it.

- [ ] **Step 1: Add the sops rule.** In `.sops.yaml`, add this as the **first** entry under `creation_rules`. Substitute `MAC_AGE_PUBKEY`:

```yaml
  - path_regex: macos/secrets/.*\.sops\.ya?ml
    mac_only_encrypted: true
    age: "age1qwwzsz6z2mmu6hpmjt2he7nepmnhutmhehvkva7l5zy5xzf08d5s5n4d6n,age1hua5s0wwmnysukxmtxkfepwcuzsc08kjmpn9pjjpwaka0lzvydwswlgq0j"
```

- [ ] **Step 2: Create the encrypted secrets file.** The plaintext must never be written into the repo tree:

```bash
umask 077
tmp=$(mktemp -d)
cat > "$tmp/mac-jms-01.sops.yaml" <<EOF
omlx:
  main-key: $(openssl rand -hex 32)
  sub-keys:
    gatus: $(openssl rand -hex 32)
EOF
mkdir -p macos/secrets
sops --encrypt --filename-override macos/secrets/mac-jms-01.sops.yaml "$tmp/mac-jms-01.sops.yaml" > macos/secrets/mac-jms-01.sops.yaml
rm -rf "$tmp"
grep -c 'ENC\[' macos/secrets/mac-jms-01.sops.yaml
grep -c 'recipient: age1' macos/secrets/mac-jms-01.sops.yaml
```
Expected:
- The first `grep -c` prints `2` (two encrypted values).
- The second prints `2` (two recipients).
- If `sops` is too old for `--filename-override`, run the encrypt from a path that matches the rule instead: `cp` the plaintext into a tmpfs directory structured as `macos/secrets/`, with `--config .sops.yaml`.

Run: `task sops:verify`
Expected: passes.

- [ ] **Step 3: Write `macos/engines/omlx/pyproject.toml`**

```toml
# uv project that pins the oMLX engine for the Mac Studio (macos/modules/omlx.nix).
# Bump by PR only: change the tag, run `task mac:omlx-lock`, run the eval
# replay (tools/ai-eval) before merging. Merging deploys.
[project]
name = "home-ops-omlx"
version = "0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "omlx @ git+https://github.com/jundot/omlx@v0.7.0",
]

[tool.uv]
package = false
environments = ["sys_platform == 'darwin' and platform_machine == 'arm64'"]
```

- [ ] **Step 4: Add the `omlx-lock` task.** Append under `tasks:` in `.taskfiles/mac/Taskfile.yaml`:

```yaml
  omlx-lock:
    desc: Regenerate macos/engines/omlx/uv.lock on the Mac and copy it back
    cmds:
      - task: sync
      - ssh {{.MAC_HOST}} 'zsh -lc "cd ~/{{.REMOTE_DIR}}/engines/omlx && nix run nixpkgs#uv -- lock --python 3.12"'
      - scp {{.MAC_HOST}}:{{.REMOTE_DIR}}/engines/omlx/uv.lock {{.MACOS_DIR}}/engines/omlx/uv.lock
```

Run *(on Mac, no sudo)*: `task mac:omlx-lock && grep -c '^name = "omlx"' macos/engines/omlx/uv.lock`
Expected: `1`.

- [ ] **Step 5: Write `macos/scripts/omlx-sub-keys.sh`**

```bash
#!/usr/bin/env bash
# omlx-sub-keys: make sure every sops-managed consumer key exists as an oMLX
# sub key (inference-only, /v1/*). Arguments: the main-key file, then one
# name=keyfile pair per consumer. Applied keys are remembered by fingerprint,
# so reruns are no-ops. Removing a key from sops does NOT revoke it -- see
# docs/runbooks/mac-studio-operations.md "Rotate or revoke a consumer key".
set -euo pipefail

BASE_URL="${OMLX_BASE_URL:-http://127.0.0.1:8000}"
STATE="${OMLX_SUB_KEYS_STATE:-/opt/ai/omlx/sub-keys.applied}"
main_key=$(cat "$1")
shift

touch "$STATE"
auth=(-H "Authorization: Bearer ${main_key}")

for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "${auth[@]}" "$BASE_URL/admin/api/server-info"; then break; fi
  sleep 5
done

for pair in "$@"; do
  name=${pair%%=*}
  key=$(cat "${pair#*=}")
  fp=$(printf '%s:%s' "$name" "$key" | shasum -a 256 | cut -d' ' -f1)
  if grep -qx "$fp" "$STATE"; then continue; fi
  body=$(jq -n --arg name "$name" --arg key "$key" '{name: $name, key: $key}')
  curl -fsS -X POST "${auth[@]}" -H 'Content-Type: application/json' -d "$body" "$BASE_URL/admin/api/sub-keys" > /dev/null
  echo "$fp" >> "$STATE"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) added sub key $name"
done
```

- [ ] **Step 6: Write `macos/modules/omlx.nix`**

```nix
# oMLX: the baseline engine (spec D7). Uv-pinned (engines/omlx), run as an
# unprivileged LaunchDaemon so it serves from boot without a login (D6).
{ config, lib, pkgs, ... }:
let
  uid = 455;
  root = "/opt/ai/omlx";
  project = "/etc/home-ops/omlx";
  python = pkgs.python312;
  mainKey = config.sops.secrets."omlx/main-key".path;
  # One entry per consumer. Each needs omlx/sub-keys/<name> in
  # secrets/mac-jms-01.sops.yaml and a matching cluster Secret.
  omlxSubKeyNames = [ "gatus" ];

  env = ''
    export HOME=${root}/home
    export UV_CACHE_DIR=${root}/uv-cache
    export UV_PROJECT_ENVIRONMENT=${root}/venv
    export UV_PYTHON=${python}/bin/python3.12
    export UV_PYTHON_DOWNLOADS=never
  '';

  serve = pkgs.writeShellApplication {
    name = "omlx-serve";
    runtimeInputs = [ pkgs.uv python pkgs.git pkgs.cmake ];
    text = ''
      ${env}
      OMLX_API_KEY=$(cat ${mainKey})
      export OMLX_API_KEY
      uv sync --locked --project ${project}
      exec uv run --no-sync --project ${project} omlx serve \
        --host 0.0.0.0 \
        --port 8000 \
        --model-dir /opt/ai/models.noindex \
        --paged-ssd-cache-dir /opt/ai/kv-cache.noindex \
        --memory-guard-gb 80
    '';
  };

  subKeys = pkgs.writeShellApplication {
    name = "omlx-sub-keys";
    runtimeInputs = with pkgs; [ coreutils curl jq perl ];
    text = builtins.readFile ../scripts/omlx-sub-keys.sh;
  };
in
{
  users.knownUsers = [ "_omlx" ];
  users.knownGroups = [ "_omlx" ];
  users.groups._omlx = { gid = uid; description = "oMLX inference engine"; };
  users.users._omlx = {
    inherit uid;
    gid = uid;
    home = "${root}/home";
    createHome = false;
    shell = "/usr/bin/false";
    isHidden = true;
    description = "oMLX inference engine";
  };

  sops.defaultSopsFile = ../secrets/mac-jms-01.sops.yaml;
  sops.secrets = {
    "omlx/main-key".owner = "_omlx";
  } // lib.genAttrs (map (n: "omlx/sub-keys/${n}") omlxSubKeyNames) (_: { owner = "_omlx"; });

  environment.etc."home-ops/omlx/pyproject.toml".source = ../engines/omlx/pyproject.toml;
  environment.etc."home-ops/omlx/uv.lock".source = ../engines/omlx/uv.lock;

  system.activationScripts.postActivation.text = ''
    install -d -m 0750 -o _omlx -g _omlx ${root} ${root}/home /opt/ai/models.noindex /opt/ai/kv-cache.noindex
    for f in omlx omlx-sub-keys; do
      touch /var/log/home-ops/$f.log
      chown _omlx:_omlx /var/log/home-ops/$f.log
    done
  '';

  launchd.daemons.omlx.serviceConfig = {
    ProgramArguments = [ "${serve}/bin/omlx-serve" ];
    UserName = "_omlx";
    GroupName = "_omlx";
    # /usr/bin for the Xcode CLT compilers uv needs when building oMLX.
    EnvironmentVariables.PATH = "/usr/bin:/bin:/usr/sbin:/sbin";
    RunAtLoad = true;
    KeepAlive = true;
    ThrottleInterval = 30;
    StandardOutPath = "/var/log/home-ops/omlx.log";
    StandardErrorPath = "/var/log/home-ops/omlx.log";
  };

  launchd.daemons.omlx-sub-keys.serviceConfig = {
    ProgramArguments = [ "${subKeys}/bin/omlx-sub-keys" mainKey ]
      ++ map (n: "${n}=${config.sops.secrets."omlx/sub-keys/${n}".path}") omlxSubKeyNames;
    UserName = "_omlx";
    GroupName = "_omlx";
    RunAtLoad = true;
    StartInterval = 600;
    StandardOutPath = "/var/log/home-ops/omlx-sub-keys.log";
    StandardErrorPath = "/var/log/home-ops/omlx-sub-keys.log";
  };
}
```

`shasum` comes from macOS `/usr/bin`, which needs `perl` in `runtimeInputs`, and `/usr/bin` is on the inherited PATH. Before using uid 455, check that it is free *(on Mac)*: `dscl . -list /Users UniqueID | awk '$2==455'`. Expected: no output. If 455 is taken, pick the next free number below 500 and use it for both uid and gid.

Add `../../modules/omlx.nix` to `imports` in `macos/hosts/mac-jms-01/default.nix`.

- [ ] **Step 7: Build** *(on Mac, no sudo)*

Run: `task mac:build-local`
Expected: a store path.

- [ ] **Step 8: Apply and confirm the sub-key API shape** **OPERATOR**

Ask the operator to run `task mac:apply-local` and then, on the Mac:
```
sudo tail -n 50 /var/log/home-ops/omlx.log            # first start runs uv sync (minutes)
K=$(sudo cat /run/secrets/omlx/main-key)
curl -s -H "Authorization: Bearer $K" localhost:8000/openapi.json | jq '.paths["/admin/api/sub-keys"].post.requestBody'
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/v1/models                      # 401
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $K" localhost:8000/v1/models   # 200
G=$(sudo cat /run/secrets/omlx/sub-keys/gatus)
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $G" localhost:8000/v1/models   # 200
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $G" localhost:8000/admin/api/stats  # 401
```
Expected:
- The status codes are `401 200 200 401`.
- The `requestBody` schema shows the sub-key field names.
- If the field names are not `name` and `key`, change the jq expression in `omlx-sub-keys.sh` to match, delete `/opt/ai/omlx/sub-keys.applied`, and re-apply.
- If the API generates the key server-side (no client-chosen value), stop. The reconciler design needs a ruling: switch to storing the returned key back into sops by hand.
- If oMLX fails to start under launchd with a Metal or device error, stop and report. Spec D6 assumes Metal works from a LaunchDaemon.

- [ ] **Step 9: Commit**

```bash
git add .sops.yaml macos/secrets/mac-jms-01.sops.yaml macos/engines/omlx macos/scripts/omlx-sub-keys.sh \
  macos/modules/omlx.nix macos/hosts/mac-jms-01/default.nix .taskfiles/mac/Taskfile.yaml
git commit -m "feat(macos): oMLX baseline engine as a uv-pinned LaunchDaemon

oMLX (spec D7) lands in Phase 1 so API keys and engine metrics can be
verified; Phase 2 adds the other engines beside it. Runs as _omlx, refuses
LAN binds without the main key, and consumers get inference-only sub keys
reconciled from sops. Memory guard 80 GB under the 84 GB wired limit.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Mac observability: node_exporter, macmon, omlx-exporter, vector

**Files:**
- Create: `macos/pkgs/omlx-exporter/omlx_exporter.py`, `macos/pkgs/omlx-exporter/test_omlx_exporter.py`, `macos/modules/observability.nix`
- Modify: `macos/hosts/mac-jms-01/default.nix` (import)

**Interfaces:**
- Consumes: the textfile dir (Task 3), the `_omlx` user and `omlx/main-key` (Task 5), and the oMLX server log path (Task 5).
- Produces:
  - **node_exporter** on `:9100`, reading the textfile dir.
  - **macmon** on `:9090`, metric prefix `macmon_`.
  - **omlx-exporter** on `:9101`, with metrics `omlx_up`, `omlx_scrape_duration_seconds` and `omlx_stat{scope,path}`.
  - **vector** shipping logs to `https://logs.68cc.io` with `hostname="mac-jms-01"`. `app_name` is the log file's base name, or `omlx` for the server log.

- [ ] **Step 1: Write the failing test `macos/pkgs/omlx-exporter/test_omlx_exporter.py`**

```python
import threading
import unittest
import urllib.error
import urllib.request

import omlx_exporter as ex


class FlattenTest(unittest.TestCase):
    def test_nested_numbers_bools_and_lists(self):
        data = {"b": {"tokens": 5, "ok": True}, "a": [1.5, {"x": 2}], "name": "m", "none": None}
        self.assertEqual(
            list(ex.flatten(data)),
            [("a.0", 1.5), ("a.1.x", 2.0), ("b.ok", 1.0), ("b.tokens", 5.0)],
        )

    def test_non_finite_numbers_are_dropped(self):
        self.assertEqual(list(ex.flatten({"n": float("nan"), "i": float("inf"), "v": 1})), [("v", 1.0)])


class RenderTest(unittest.TestCase):
    def test_up_and_escaped_paths(self):
        text = ex.render(True, {"alltime": {'m"x': {"t": 3}}}, 0.25)
        self.assertIn("omlx_up 1\n", text)
        self.assertIn("omlx_scrape_duration_seconds 0.250000\n", text)
        self.assertIn('omlx_stat{scope="alltime",path="m\\"x.t"} 3.0\n', text)

    def test_down(self):
        self.assertIn("omlx_up 0\n", ex.render(False, {}, 0.0))


class CollectTest(unittest.TestCase):
    def test_all_scopes_ok(self):
        seen = []

        def fetch(base, key, scope):
            seen.append((base, key, scope))
            return {"requests": 2}

        text = ex.collect("http://h:1", "k", fetch)
        self.assertEqual(seen, [("http://h:1", "k", "session"), ("http://h:1", "k", "alltime")])
        self.assertIn("omlx_up 1\n", text)
        self.assertIn('omlx_stat{scope="session",path="requests"} 2.0\n', text)

    def test_one_scope_failing_marks_down_but_keeps_the_other(self):
        def fetch(base, key, scope):
            if scope == "session":
                raise OSError("boom")
            return {"requests": 9}

        text = ex.collect("http://h:1", "k", fetch)
        self.assertIn("omlx_up 0\n", text)
        self.assertIn('omlx_stat{scope="alltime",path="requests"} 9.0\n', text)
        self.assertNotIn('scope="session"', text)


class ServerTest(unittest.TestCase):
    def test_metrics_and_404(self):
        server = ex.make_server("127.0.0.1", 0, lambda: "omlx_up 1\n")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_address[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics") as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers["Content-Type"], "text/plain; version=0.0.4")
                self.assertEqual(resp.read(), b"omlx_up 1\n")
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/other")
            self.assertEqual(err.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s macos/pkgs/omlx-exporter -v`
Expected: `ModuleNotFoundError: No module named 'omlx_exporter'`

- [ ] **Step 3: Write `macos/pkgs/omlx-exporter/omlx_exporter.py`**

```python
"""Prometheus exporter for oMLX, which has no /metrics of its own.

oMLX documents /admin/api/stats but not its response shape, so this does
not guess field names: every numeric (or boolean) leaf becomes one sample
of omlx_stat{scope,path}, path being the dotted JSON path. Dashboards and
alerts pick the paths they need. omlx_up is 0 when any stats call fails.

The main API key is re-read from its file on every scrape, so a rotation
needs no restart. Stdlib only; packaged by macos/modules/observability.nix.
"""
import argparse
import json
import math
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCOPES = ("session", "alltime")
_ESCAPES = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n"})


def flatten(obj, prefix=""):
    """Yield (dotted_path, float) for every finite numeric or boolean leaf."""
    if isinstance(obj, bool):
        yield prefix, 1.0 if obj else 0.0
    elif isinstance(obj, (int, float)):
        value = float(obj)
        if math.isfinite(value):
            yield prefix, value
    elif isinstance(obj, dict):
        for key in sorted(obj, key=str):
            yield from flatten(obj[key], f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            yield from flatten(item, f"{prefix}.{index}" if prefix else str(index))


def render(up, stats, duration):
    lines = [
        "# HELP omlx_up 1 if every oMLX stats request in this scrape succeeded.",
        "# TYPE omlx_up gauge",
        f"omlx_up {1 if up else 0}",
        "# HELP omlx_scrape_duration_seconds Time spent querying oMLX.",
        "# TYPE omlx_scrape_duration_seconds gauge",
        f"omlx_scrape_duration_seconds {duration:.6f}",
        "# HELP omlx_stat Numeric leaf of /admin/api/stats; path is the dotted JSON path.",
        "# TYPE omlx_stat gauge",
    ]
    for scope in SCOPES:
        for path, value in flatten(stats.get(scope, {})):
            lines.append(f'omlx_stat{{scope="{scope}",path="{path.translate(_ESCAPES)}"}} {value!r}')
    return "\n".join(lines) + "\n"


def fetch(base_url, api_key, scope, timeout=5):
    req = urllib.request.Request(
        f"{base_url}/admin/api/stats?scope={scope}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def collect(base_url, api_key, fetcher=fetch):
    start = time.monotonic()
    stats, up = {}, True
    for scope in SCOPES:
        try:
            stats[scope] = fetcher(base_url, api_key, scope)
        except Exception as exc:  # any failure means "engine not answering"
            up = False
            print(f"omlx-exporter: {scope}: {exc}", file=sys.stderr)
    return render(up, stats, time.monotonic() - start)


def make_server(host, port, produce):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/metrics":
                self.send_error(404)
                return
            body = produce().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=9101)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key-file", required=True)
    args = parser.parse_args(argv)

    def produce():
        with open(args.api_key_file) as handle:
            key = handle.read().strip()
        return collect(args.base_url, key)

    make_server(args.listen_host, args.listen_port, produce).serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s macos/pkgs/omlx-exporter -v`
Expected: `Ran 7 tests … OK`

- [ ] **Step 5: Write `macos/modules/observability.nix`**

```nix
# Host, GPU/power, engine metrics and logs (spec: Observability).
# Scraped through kubernetes/apps/ai/mac-inference (VMStaticScrape).
{ config, lib, pkgs, ... }:
let
  # macmon < 0.10.0 reads zero CPU/ANE power on macOS 27; fall back to
  # Homebrew's (current) formula until nixpkgs catches up.
  nixMacmon = lib.versionAtLeast pkgs.macmon.version "0.10.0";
  macmonBin = if nixMacmon then "${pkgs.macmon}/bin/macmon" else "/opt/homebrew/bin/macmon";

  omlxExporter = pkgs.writers.writePython3Bin "omlx-exporter" { flakeIgnore = [ "E501" ]; }
    (builtins.readFile ../pkgs/omlx-exporter/omlx_exporter.py);

  vectorConfig = (pkgs.formats.yaml { }).generate "vector.yaml" {
    data_dir = "/var/lib/vector";
    sources.files = {
      type = "file";
      include = [ "/var/log/home-ops/*.log" "/opt/ai/omlx/home/.omlx/logs/*.log" ];
    };
    transforms.tag = {
      type = "remap";
      inputs = [ "files" ];
      source = ''
        .hostname = "mac-jms-01"
        .stream = "mac-jms-01"
        if contains(string!(.file), "/.omlx/") {
          .app_name = "omlx"
        } else {
          .app_name = replace(replace(string!(.file), r'^.*/', ""), r'\.log$', "")
        }
      '';
    };
    # Same ingest path and headers as the cluster's vector
    # (kubernetes/apps/monitoring/vector/app/helmrelease.yaml).
    sinks.vlogs = {
      type = "elasticsearch";
      inputs = [ "tag" ];
      endpoints = [ "https://logs.68cc.io/insert/elasticsearch/" ];
      mode = "bulk";
      api_version = "v8";
      compression = "zstd";
      healthcheck.enabled = false;
      buffer = { type = "disk"; max_size = 268435488; when_full = "block"; };
      request.headers = {
        VL-Time-Field = "timestamp";
        VL-Stream-Fields = "stream,app_name,hostname";
        VL-Msg-Field = "message";
        AccountID = "0";
        ProjectID = "0";
      };
    };
  };
in
{
  services.prometheus.exporters.node = {
    enable = true;
    port = 9100;
    extraFlags = [ "--collector.textfile.directory=/var/lib/node-exporter/textfile" ];
  };

  homebrew.brews = lib.optional (!nixMacmon) "macmon";

  launchd.daemons.macmon.serviceConfig = {
    ProgramArguments = [ macmonBin "serve" "--port" "9090" ];
    UserName = "nobody";
    RunAtLoad = true;
    KeepAlive = true;
    StandardOutPath = "/var/log/home-ops/macmon.log";
    StandardErrorPath = "/var/log/home-ops/macmon.log";
  };

  launchd.daemons.omlx-exporter.serviceConfig = {
    ProgramArguments = [
      "${omlxExporter}/bin/omlx-exporter"
      "--listen-port" "9101"
      "--api-key-file" config.sops.secrets."omlx/main-key".path
    ];
    UserName = "_omlx";
    GroupName = "_omlx";
    RunAtLoad = true;
    KeepAlive = true;
    StandardOutPath = "/var/log/home-ops/omlx-exporter.log";
    StandardErrorPath = "/var/log/home-ops/omlx-exporter.log";
  };

  launchd.daemons.vector.serviceConfig = {
    ProgramArguments = [ "${pkgs.vector}/bin/vector" "--config" "${vectorConfig}" ];
    RunAtLoad = true;
    KeepAlive = true;
    StandardOutPath = "/var/log/home-ops/vector.log";
    StandardErrorPath = "/var/log/home-ops/vector.log";
  };

  system.activationScripts.postActivation.text = ''
    install -d -m 0700 -o root -g wheel /var/lib/vector
    for f in macmon omlx-exporter; do touch /var/log/home-ops/$f.log; done
    chown nobody /var/log/home-ops/macmon.log
    chown _omlx:_omlx /var/log/home-ops/omlx-exporter.log
  '';
}
```

Notes for the implementer:
- vector ships its own log file too, as `app_name="vector"`. Its error lines go to VictoriaLogs, which is fine.
- The newsyslog glob from Task 4 covers every file in `/var/log/home-ops/`.

Add `../../modules/observability.nix` to `imports` in `macos/hosts/mac-jms-01/default.nix`.

- [ ] **Step 6: Build and validate vector's config** *(on Mac, no sudo)*

Run: `task mac:build-local`
Expected: a store path. flake8 runs inside `writePython3Bin`, and a lint error fails the build.

Then, on the Mac, validate the generated vector config:

```
ssh mac-jms-01 'zsh -lc "cd ~/home-ops-macos && cfg=\$(nix eval --raw .#darwinConfigurations.mac-jms-01.config.launchd.daemons.vector.serviceConfig.ProgramArguments --apply \"a: builtins.elemAt a 2\") && nix build --no-link \$cfg 2>/dev/null; nix run nixpkgs#vector -- validate --no-environment \$cfg"'
```
Expected: `Validated`.

- [ ] **Step 7: Commit**

```bash
git add macos/pkgs/omlx-exporter macos/modules/observability.nix macos/hosts/mac-jms-01/default.nix
git commit -m "feat(macos): node_exporter, macmon, oMLX exporter and vector

Spec Phase 1.4 (Mac half). oMLX has no /metrics and documents no stats
schema, so the exporter flattens /admin/api/stats instead of guessing
names. macmon falls back to Homebrew when nixpkgs predates 0.10.0, the
first release that reads power on macOS 27. Logs reach logs.68cc.io on
the same ingest path as the cluster's vector.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: pf allowlist

**Files:**
- Create: `macos/modules/pf.nix`
- Modify: `macos/hosts/mac-jms-01/default.nix` (import)

**Interfaces:**
- Consumes:
  - `facts.clusterNodeIps` (Task 1)
  - the textfile dir (Task 3)
  - the ports `8000 9090 9100 9101` (Tasks 5–6)
- Produces:
  - **Textfile:** `home_ops_pf.prom` with gauge `home_ops_pf_ruleset_loaded` (1 or 0).
  - **Launchd label:** `org.nixos.pf-home-ops`.

- [ ] **Step 1: Write `macos/modules/pf.nix`**

```nix
# Only localhost and the cluster reach the engine and exporters (spec:
# Exposure and security). Cluster sources are node IPs because Cilium
# masquerades pod egress. SSH (22) is not filtered here: it is key-only
# (base.nix) and needed for FileVault pre-boot unlock.
{ lib, pkgs, facts, ... }:
let
  ports = "{ 8000, 9090, 9100, 9101 }";

  rulesBody = ''
    table <cluster> const { ${lib.concatStringsSep ", " facts.clusterNodeIps} }
    set skip on lo0
    # Apple's own anchors, as in /etc/pf.conf, so system rules still load.
    scrub-anchor "com.apple/*"
    nat-anchor "com.apple/*"
    rdr-anchor "com.apple/*"
    anchor "com.apple/*"
    load anchor "com.apple" from "/etc/pf.anchors/com.apple"
  '';

  # The label carries a hash of the ruleset, so a changed ruleset no longer
  # matches what is loaded and the enforcer reloads it.
  marker = "home-ops-${builtins.substring 0 12 (builtins.hashString "sha256" (rulesBody + ports))}";

  rules = pkgs.writeText "pf.home-ops.conf" ''
    # generated by macos/modules/pf.nix
    ${rulesBody}
    pass in quick proto tcp from <cluster> to any port ${ports} label "${marker}"
    block in quick proto tcp to any port ${ports}
  '';

  # macOS's com.apple.pfctl loads the stock /etc/pf.conf at boot and may
  # run after us, so this re-checks every 5 minutes and reloads when our
  # labelled rule is missing.
  enforce = pkgs.writeShellApplication {
    name = "pf-home-ops";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      if ! /sbin/pfctl -s rules 2>/dev/null | grep -q '${marker}'; then
        /sbin/pfctl -f ${rules}
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) loaded ${rules}"
      fi
      /sbin/pfctl -s info 2>/dev/null | grep -q 'Status: Enabled' || /sbin/pfctl -e
      loaded=0
      if /sbin/pfctl -s rules 2>/dev/null | grep -q '${marker}' && /sbin/pfctl -s info | grep -q 'Status: Enabled'; then loaded=1; fi
      dir=/var/lib/node-exporter/textfile
      tmp=$(mktemp "$dir/.pf.XXXXXX")
      {
        echo "# HELP home_ops_pf_ruleset_loaded 1 if pf is enabled with the home-ops allowlist."
        echo "# TYPE home_ops_pf_ruleset_loaded gauge"
        echo "home_ops_pf_ruleset_loaded $loaded"
      } > "$tmp"
      chmod 644 "$tmp"
      mv "$tmp" "$dir/home_ops_pf.prom"
    '';
  };
in
{
  launchd.daemons.pf-home-ops.serviceConfig = {
    ProgramArguments = [ "${enforce}/bin/pf-home-ops" ];
    RunAtLoad = true;
    StartInterval = 300;
    StandardOutPath = "/var/log/home-ops/pf-home-ops.log";
    StandardErrorPath = "/var/log/home-ops/pf-home-ops.log";
  };
}
```

Add `../../modules/pf.nix` to `imports` in `macos/hosts/mac-jms-01/default.nix`.

- [ ] **Step 2: Syntax-check the generated ruleset** *(on Mac; `pfctl -n` parses without loading, which needs sudo)*

Run: `task mac:build-local`, then:

```
ssh -t mac-jms-01 'zsh -lc "cd ~/home-ops-macos && p=\$(nix eval --raw .#darwinConfigurations.mac-jms-01.config.launchd.daemons.pf-home-ops.serviceConfig.ProgramArguments --apply \"a: builtins.head a\") && nix build --no-link \$(dirname \$(dirname \$p)) && grep -o \"/nix/store/[^ ]*pf.home-ops.conf\" \$p | head -1 | xargs sudo pfctl -nf"'
```

Expected: no output, exit 0. This step needs sudo, so it is **OPERATOR** unless done during Task 8's apply.

- [ ] **Step 3: Commit**

```bash
git add macos/modules/pf.nix macos/hosts/mac-jms-01/default.nix
git commit -m "feat(macos): pf allowlist for engine and exporter ports

Spec Phase 1.5 (Mac half). Only the cluster node IPs (Cilium SNATs pod
egress) and localhost reach 8000/9090/9100/9101. macOS reloads its stock
pf.conf at boot, so an enforcer re-asserts every 5 min, keyed on a label
derived from the ruleset hash, and reports home_ops_pf_ruleset_loaded.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Cluster side: mac-inference Service, scrape, alerts, dashboard, admin route, Gatus

**Files:**
- Create: `kubernetes/apps/ai/mac-inference/ks.yaml`, `…/app/kustomization.yaml`, `…/app/service.yaml`, `…/app/vmstaticscrape.yaml`, `…/app/prometheusrule.yaml`, `…/app/grafanadashboard.yaml`, `…/app/httproute.yaml`, `kubernetes/apps/services/gatus/app/secret.sops.yaml`
- Modify: `kubernetes/apps/ai/kustomization.yaml`, `kubernetes/apps/services/gatus/app/helmrelease.yaml`, `kubernetes/apps/services/gatus/app/kustomization.yaml`

**Interfaces:**
- Consumes:
  - `MAC_IP` (facts)
  - the Mac ports and metric names from Tasks 3–7
  - the plaintext `omlx/sub-keys/gatus` value from `macos/secrets/mac-jms-01.sops.yaml`
- Produces:
  - **Service DNS:** `mac-inference.ai.svc.cluster.local`, with ports `http` 8000, `macmon` 9090, `node-exporter` 9100, `omlx-exporter` 9101.
  - **Scrape job:** `job="mac-jms-01"`, with label `exporter` set to `node`, `macmon` or `omlx`.
  - **Admin host:** `omlx.68cc.io`, internal only.

- [ ] **Step 1: Write `kubernetes/apps/ai/mac-inference/app/service.yaml`.** Substitute `MAC_IP`:

```yaml
---
# The Mac Studio (macOS, not a node) as an in-cluster name. Selector-less:
# the EndpointSlice below is the one place in Kubernetes that holds the
# Mac's IP (the other is macos/hosts/mac-jms-01/facts.nix). Consumers,
# vmagent, Gatus and the admin HTTPRoute all use this Service.
apiVersion: v1
kind: Service
metadata:
  name: mac-inference
spec:
  ports:
    - name: http
      port: 8000
      targetPort: 8000
      protocol: TCP
    - name: macmon
      port: 9090
      targetPort: 9090
      protocol: TCP
    - name: node-exporter
      port: 9100
      targetPort: 9100
      protocol: TCP
    - name: omlx-exporter
      port: 9101
      targetPort: 9101
      protocol: TCP
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: mac-inference-1
  labels:
    kubernetes.io/service-name: mac-inference
    endpointslice.kubernetes.io/managed-by: flux.home-ops
addressType: IPv4
ports:
  - name: http
    port: 8000
    protocol: TCP
  - name: macmon
    port: 9090
    protocol: TCP
  - name: node-exporter
    port: 9100
    protocol: TCP
  - name: omlx-exporter
    port: 9101
    protocol: TCP
endpoints:
  - addresses:
      - "192.168.35.7"
    conditions:
      ready: true
```

- [ ] **Step 2: Write `…/app/vmstaticscrape.yaml`**

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/operator.victoriametrics.com/vmstaticscrape_v1beta1.json
# Scrapes the Mac through the mac-inference Service, so the IP stays in the
# EndpointSlice. vmagent's source IP is its node's (Cilium masquerade),
# which macos/modules/pf.nix allows.
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMStaticScrape
metadata:
  name: mac-jms-01
spec:
  jobName: mac-jms-01
  targetEndpoints:
    - targets: ["mac-inference.ai.svc.cluster.local:9100"]
      labels:
        instance: mac-jms-01
        exporter: node
      interval: 30s
    - targets: ["mac-inference.ai.svc.cluster.local:9090"]
      labels:
        instance: mac-jms-01
        exporter: macmon
      interval: 30s
    - targets: ["mac-inference.ai.svc.cluster.local:9101"]
      labels:
        instance: mac-jms-01
        exporter: omlx
      interval: 30s
```

- [ ] **Step 3: Write `…/app/prometheusrule.yaml`**

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/monitoring.coreos.com/prometheusrule_v1.json
#
# Mac Studio inference host (spec: Observability). home_ops_* series are
# node_exporter textfile metrics written by macos/modules/*.nix. Critical =
# every LLM consumer is down (no fallback, spec D4); everything else warns.
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: mac-jms-01-rules
  labels:
    prometheus: k8s
    role: alert-rules
spec:
  groups:
    - name: mac-jms-01.rules
      rules:
        - alert: MacStudioUnreachable
          expr: |
            up{job="mac-jms-01",exporter="node"} == 0
              or absent(up{job="mac-jms-01",exporter="node"})
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: >-
              Mac Studio node_exporter unreachable for 5m -- every LLM consumer
              is down. Power cut? FileVault pre-boot unlock: see
              docs/runbooks/mac-studio-operations.md

        - alert: MacStudioEngineDown
          expr: |
            omlx_up{job="mac-jms-01"} == 0
              or (up{job="mac-jms-01",exporter="omlx"} == 0 and on(instance) up{job="mac-jms-01",exporter="node"} == 1)
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: >-
              oMLX not answering on the Mac Studio for 5m (host is up) -- check
              /var/log/home-ops/omlx.log

        # Active swap-out, not swap residency: macOS keeps swapped pages
        # around long after pressure ends.
        - alert: MacStudioSwapping
          expr: |
            rate(node_memory_swapped_out_bytes_total{job="mac-jms-01"}[10m]) > 1048576
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: >-
              Mac Studio swapping out >1 MiB/s for 15m -- models plus KV cache
              exceed the 80 GB budget, or a desktop app is running

        - alert: MacStudioWiredNearLimit
          expr: |
            node_memory_wired_bytes{job="mac-jms-01"}
              / on(instance) home_ops_iogpu_wired_limit_bytes{job="mac-jms-01"} > 0.95
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: >-
              Mac Studio wired memory above 95% of iogpu.wired_limit_mb for 15m

        - alert: MacStudioWiredLimitNotSet
          expr: |
            home_ops_iogpu_wired_limit_bytes{job="mac-jms-01"} < 80e9
              or (absent(home_ops_iogpu_wired_limit_bytes{job="mac-jms-01"}) and on() up{job="mac-jms-01",exporter="node"} == 1)
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: >-
              iogpu.wired_limit_mb is not at its ~84 GB setting -- check
              /var/log/home-ops/home-ops-wired-limit.log

        - alert: MacStudioNixApplyStale
          expr: |
            time() - home_ops_nix_apply_last_in_sync_timestamp_seconds{job="mac-jms-01"} > 86400
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: >-
              Mac Studio has not been in sync with main for 24h -- check
              /var/log/home-ops/home-ops-pull.log

        - alert: MacStudioNixBehindMain
          expr: |
            home_ops_nix_apply_behind_main{job="mac-jms-01"} == 1
          for: 2h
          labels:
            severity: warning
          annotations:
            summary: >-
              Mac Studio applied commit is behind main for 2h (last exit code
              {{ with query "home_ops_nix_apply_last_exit_code{job='mac-jms-01'}" }}{{ . | first | value }}{{ end }})

        - alert: MacStudioPfNotLoaded
          expr: |
            home_ops_pf_ruleset_loaded{job="mac-jms-01"} == 0
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: >-
              Mac Studio pf allowlist not loaded -- engine ports are open to
              the whole LAN (API keys still required)
```

- [ ] **Step 4: Write `…/app/grafanadashboard.yaml`.** Metric-name regexes keep it independent of the exact macmon and oMLX names:

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/grafana.integreatly.org/grafanadashboard_v1beta1.json
#
# Hand-built. macmon and oMLX metric names are matched by regex
# ({__name__=~"macmon_.*_power_watts"}, omlx_stat paths) because neither
# upstream documents a stable list; edit the JSON directly.
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: mac-jms-01
spec:
  allowCrossNamespaceImport: true
  instanceSelector:
    matchLabels:
      grafana.internal/instance: grafana
  folder: AI
  datasources:
    - datasourceName: vmsingle
      inputName: DS_PROMETHEUS
  json: |
    {
      "title": "Mac Studio",
      "uid": "mac-jms-01",
      "tags": ["ai", "mac-jms-01"],
      "timezone": "browser",
      "schemaVersion": 39,
      "version": 1,
      "editable": true,
      "refresh": "1m",
      "time": {"from": "now-24h", "to": "now"},
      "templating": {"list": [{"name": "DS_PROMETHEUS", "type": "datasource", "query": "prometheus", "current": {"text": "vmsingle", "value": "vmsingle"}, "hide": 0}]},
      "panels": [
        {"id": 1, "type": "stat", "title": "Host up", "gridPos": {"h": 4, "w": 4, "x": 0, "y": 0},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "targets": [{"expr": "up{job=\"mac-jms-01\",exporter=\"node\"}", "refId": "A", "instant": true}]},
        {"id": 2, "type": "stat", "title": "oMLX up", "gridPos": {"h": 4, "w": 4, "x": 4, "y": 0},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "targets": [{"expr": "omlx_up{job=\"mac-jms-01\"}", "refId": "A", "instant": true}]},
        {"id": 3, "type": "stat", "title": "Since last in sync with main", "gridPos": {"h": 4, "w": 4, "x": 8, "y": 0},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "fieldConfig": {"defaults": {"unit": "s"}},
         "targets": [{"expr": "time() - home_ops_nix_apply_last_in_sync_timestamp_seconds{job=\"mac-jms-01\"}", "refId": "A", "instant": true}]},
        {"id": 4, "type": "stat", "title": "Behind main", "gridPos": {"h": 4, "w": 4, "x": 12, "y": 0},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "targets": [{"expr": "home_ops_nix_apply_behind_main{job=\"mac-jms-01\"}", "refId": "A", "instant": true}]},
        {"id": 5, "type": "stat", "title": "pf allowlist loaded", "gridPos": {"h": 4, "w": 4, "x": 16, "y": 0},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "targets": [{"expr": "home_ops_pf_ruleset_loaded{job=\"mac-jms-01\"}", "refId": "A", "instant": true}]},
        {"id": 6, "type": "stat", "title": "Wired limit", "gridPos": {"h": 4, "w": 4, "x": 20, "y": 0},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "fieldConfig": {"defaults": {"unit": "bytes"}},
         "targets": [{"expr": "home_ops_iogpu_wired_limit_bytes{job=\"mac-jms-01\"}", "refId": "A", "instant": true}]},
        {"id": 7, "type": "timeseries", "title": "Memory", "gridPos": {"h": 8, "w": 12, "x": 0, "y": 4},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "fieldConfig": {"defaults": {"unit": "bytes"}},
         "targets": [
           {"expr": "node_memory_wired_bytes{job=\"mac-jms-01\"}", "legendFormat": "wired", "refId": "A"},
           {"expr": "home_ops_iogpu_wired_limit_bytes{job=\"mac-jms-01\"}", "legendFormat": "wired limit", "refId": "B"},
           {"expr": "node_memory_compressed_bytes{job=\"mac-jms-01\"}", "legendFormat": "compressed", "refId": "C"},
           {"expr": "node_memory_swap_used_bytes{job=\"mac-jms-01\"}", "legendFormat": "swap used", "refId": "D"}]},
        {"id": 8, "type": "timeseries", "title": "Swap-out rate", "gridPos": {"h": 8, "w": 12, "x": 12, "y": 4},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "fieldConfig": {"defaults": {"unit": "Bps"}},
         "targets": [{"expr": "rate(node_memory_swapped_out_bytes_total{job=\"mac-jms-01\"}[5m])", "legendFormat": "swap out", "refId": "A"}]},
        {"id": 9, "type": "timeseries", "title": "Power (macmon)", "gridPos": {"h": 8, "w": 12, "x": 0, "y": 12},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "fieldConfig": {"defaults": {"unit": "watt"}},
         "targets": [{"expr": "{__name__=~\"macmon_.*_power_watts\",job=\"mac-jms-01\"}", "legendFormat": "{{__name__}}", "refId": "A"}]},
        {"id": 10, "type": "timeseries", "title": "Temperature (macmon)", "gridPos": {"h": 8, "w": 12, "x": 12, "y": 12},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "fieldConfig": {"defaults": {"unit": "celsius"}},
         "targets": [{"expr": "{__name__=~\"macmon_.*_temp_celsius\",job=\"mac-jms-01\"}", "legendFormat": "{{__name__}}", "refId": "A"}]},
        {"id": 11, "type": "timeseries", "title": "CPU / GPU utilisation (macmon)", "gridPos": {"h": 8, "w": 12, "x": 0, "y": 20},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "fieldConfig": {"defaults": {"unit": "percentunit", "max": 1}},
         "targets": [{"expr": "{__name__=~\"macmon_(cpu|gpu)_(active|usage|scaled)_ratio\",job=\"mac-jms-01\"}", "legendFormat": "{{__name__}}", "refId": "A"}]},
        {"id": 12, "type": "table", "title": "oMLX stats (all numeric fields, all time)", "gridPos": {"h": 8, "w": 12, "x": 12, "y": 20},
         "datasource": {"type": "prometheus", "uid": "${DS_PROMETHEUS}"},
         "targets": [{"expr": "omlx_stat{job=\"mac-jms-01\",scope=\"alltime\"}", "format": "table", "refId": "A", "instant": true}]}
      ]
    }
```

- [ ] **Step 5: Write `…/app/httproute.yaml`**

```yaml
---
# oMLX admin UI and API, LAN-only (traefik-internal, no Cloudflare record),
# behind Authentik like every admin UI (spec: Exposure and security). oMLX
# still asks for its main key at /admin.
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: omlx-admin
  annotations:
    external-dns.alpha.kubernetes.io/target: 192.168.35.17
spec:
  hostnames:
    - omlx.68cc.io
  parentRefs:
    - name: traefik-internal-gateway
      namespace: network
  rules:
    - filters:
        - type: ExtensionRef
          extensionRef:
            group: traefik.io
            kind: Middleware
            name: authentik-forwardauth
      backendRefs:
        - name: mac-inference
          port: 8000
```

- [ ] **Step 6: Write `…/app/kustomization.yaml` and `ks.yaml`**

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./service.yaml
  - ./vmstaticscrape.yaml
  - ./prometheusrule.yaml
  - ./grafanadashboard.yaml
  - ./httproute.yaml
```

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app mac-inference
  namespace: &namespace ai
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  path: ./kubernetes/apps/ai/mac-inference/app
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

In `kubernetes/apps/ai/kustomization.yaml`, add `  - ./mac-inference/ks.yaml` after `./llama-swap-apu/ks.yaml`. Add a comment line above it: `# Mac Studio inference host (macOS, outside the cluster) -- spec 2026-10-10.`

- [ ] **Step 7: Gatus secret, endpoint and reloader**

Create the Secret without writing plaintext into the repo:

```bash
umask 077
key=$(sops -d --extract '["omlx"]["sub-keys"]["gatus"]' macos/secrets/mac-jms-01.sops.yaml)
tmp=$(mktemp -d)
cat > "$tmp/secret.yaml" <<EOF
---
apiVersion: v1
kind: Secret
metadata:
  name: gatus-mac-inference
type: Opaque
stringData:
  MAC_INFERENCE_GATUS_KEY: "${key}"
EOF
sops --encrypt --filename-override kubernetes/apps/services/gatus/app/secret.sops.yaml "$tmp/secret.yaml" > kubernetes/apps/services/gatus/app/secret.sops.yaml
rm -rf "$tmp"; unset key
task sops:verify
```

In `kubernetes/apps/services/gatus/app/kustomization.yaml`, add `  - ./secret.sops.yaml` before `./helmrelease.yaml`.

In `kubernetes/apps/services/gatus/app/helmrelease.yaml` under `values:`:
- Add the keys below, at the same level as `config:`. Gatus expands `${VAR}` in its config from the environment, and this Kustomization has no `postBuild` substitution, so `${…}` reaches Gatus untouched:

```yaml
    podAnnotations:
      reloader.stakater.com/auto: "true"
    envFrom:
      - secretRef:
          name: gatus-mac-inference
```

- Append this endpoint under `config.endpoints`:

```yaml
        - name: mac-inference-models
          group: ai
          url: "http://mac-inference.ai.svc.cluster.local:8000/v1/models"
          interval: 1m
          headers:
            Authorization: "Bearer ${MAC_INFERENCE_GATUS_KEY}"
          conditions:
            - "[STATUS] == 200"
```

- [ ] **Step 8: Validate**

```bash
kustomize build kubernetes/apps/ai/mac-inference/app > /tmp/mac-inference.yaml && echo built
kustomize build kubernetes/apps/services/gatus/app | grep -c 'reloader.stakater.com/auto'
KUBECONFIG=/workspace/home-ops/kubeconfig kubectl apply --dry-run=server -f /tmp/mac-inference.yaml
python3 - <<'EOF'
import json, yaml
docs = list(yaml.safe_load_all(open("/tmp/mac-inference.yaml")))
dash = next(d for d in docs if d["kind"] == "GrafanaDashboard")
json.loads(dash["spec"]["json"]); print("dashboard json ok")
EOF
```
Expected:
- `built`
- `1`
- every object `created (server dry run)` (or `configured`)
- `dashboard json ok`

Then dispatch the `flux-manifest-reviewer` and `kubeconform-validator` agents on the changed paths, and the `sops-leak-detector` on the staged diff.

- [ ] **Step 9: Commit**

```bash
git add kubernetes/apps/ai/mac-inference kubernetes/apps/ai/kustomization.yaml kubernetes/apps/services/gatus/app
git commit -m "feat(ai): mac-inference Service, scrape, alerts, dashboard, Gatus

Spec Phase 1.4/1.5 (cluster half). A selector-less Service plus
EndpointSlice is the only place k8s holds the Mac's IP; scrapes, Gatus and
the omlx.68cc.io admin route all go through it. Gatus uses an
inference-only oMLX sub key. Mac down and engine down are critical
because there is no LLM fallback (D4).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: `task mac:reboot` and the operations runbook

**Files:**
- Create: `docs/runbooks/mac-studio-operations.md`
- Modify: `.taskfiles/mac/Taskfile.yaml` (add `reboot` and `wait-up`)

**Interfaces:**
- Consumes: the `ssh mac-jms-01` alias, the launchd labels `org.nixos.*`, `task mac:status`, and the outcome of the checklist §11 pre-boot unlock test, which the ledger recorded in Task 1, Step 9.
- Produces: `task mac:reboot`.

- [ ] **Step 1: Add the tasks.** Append under `tasks:` in `.taskfiles/mac/Taskfile.yaml`:

```yaml
  reboot:
    desc: Planned reboot via FileVault authrestart (boots straight past the unlock screen)
    summary: |
      Every LLM consumer fails while the Mac is down (spec D4, no fallback).
      fdesetup asks for the FileVault user's password on the Mac's sudo.
    prompt: Reboot mac-jms-01 now? All LLM consumers fail until it is back (~2-3 min).
    cmds:
      - ssh -t {{.MAC_HOST}} 'fdesetup supportsauthrestart | grep -q true && sudo fdesetup authrestart -delayminutes 0'
      - task: wait-up

  wait-up:
    desc: Wait (up to 10 min) for the Mac's SSH and oMLX to answer after a reboot
    cmds:
      - sleep 60
      - |
        for i in $(seq 1 54); do
          if ssh -o ConnectTimeout=5 -o BatchMode=yes {{.MAC_HOST}} 'curl -s -o /dev/null -w "%{http_code}" localhost:8000/v1/models | grep -q 401'; then
            echo "mac-jms-01 is back and oMLX is answering"; exit 0
          fi
          sleep 10
        done
        echo "mac-jms-01 not back after 10 min -- see docs/runbooks/mac-studio-operations.md (Unplanned reboot)"; exit 1
```

A `401` without a key proves oMLX is serving and enforcing auth, without needing a key on the operator machine.

- [ ] **Step 2: Write `docs/runbooks/mac-studio-operations.md`.** Fill the "Unplanned reboot" paragraph from the §11 test result recorded in the ledger. If that test was never run, keep the "untested" sentence as written.

````markdown
# Mac Studio operations

Host: `mac-jms-01` (macOS, nix-darwin, **not** a k8s node). Config: `macos/`.
In-cluster name: `mac-inference.ai.svc` (`kubernetes/apps/ai/mac-inference/`).
Spec: `docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md`.

**While the Mac is down, every LLM consumer is down** (D4, no fallback);
Hindsight queues, everything else fails fast. Reboot deliberately.

## Health at a glance

- `task mac:status` — current generation, `org.nixos.*` daemons, textfile metrics.
- Grafana → AI → **Mac Studio**.
- Logs: VictoriaLogs `hostname:"mac-jms-01"`, or on the Mac `/var/log/home-ops/*.log`
  and `/opt/ai/omlx/home/.omlx/logs/server.log`.

## Planned reboot

```bash
task mac:reboot
```

Uses `fdesetup authrestart`, so the Mac boots past the FileVault screen.
Ends when oMLX answers again (≤ 10 min) — otherwise follow "Unplanned reboot".

## Unplanned reboot (power cut, panic, plain `reboot`)

The Mac stops at FileVault pre-boot; nothing runs, `MacStudioUnreachable`
pages. Unlock over SSH: `ssh mac-jms-01`, answer the pre-boot prompt, then
`task mac:wait-up`.

Pre-boot unlock result from bring-up (§11): RECORD_RESULT_HERE

## macOS update (manual only — auto-updates are off in nix)

1. Read the release notes for Metal / MLX / `iogpu` changes; check oMLX and
   macmon issues for the new version.
2. On the Mac: `softwareupdate --list`.
3. `sudo softwareupdate --install --all --restart --user j0sh3rs --stdinpass`
   (Apple silicon needs the owner's credentials).
4. The update reboot lands at FileVault pre-boot — unlock as in
   "Unplanned reboot", then `task mac:wait-up`.
5. Verify: `task mac:status`; `home_ops_iogpu_wired_limit_bytes` ≈ 90.2e9;
   `home_ops_pf_ruleset_loaded 1`; Grafana macmon power panels non-zero
   (macmon's power counters are OS-version-sensitive).
6. Re-run the eval replay (`tools/ai-eval/README.md`) before trusting
   output quality on the new OS.

## Config changes and rollback

- Change `macos/` by PR. CI (`macOS Nix`) builds it; merging deploys within
  5 min (pull loop). Test first with `task mac:apply-local` if risky.
- **Roll back:** `git revert` the commit on main (the loop applies it), or on
  the Mac `sudo darwin-rebuild --rollback` (immediate; the loop won't
  override it until main moves again).
- Changing `launchd.daemons.home-ops-pull` itself: apply with
  `task mac:apply-local` — the loop can't safely reload its own plist.

## Engine (oMLX) upgrade

1. Bump the tag in `macos/engines/omlx/pyproject.toml` (Renovate opens this PR).
2. `task mac:omlx-lock`, commit `uv.lock` to the PR branch.
3. Run the eval replay against the new build before merging (spec: every
   engine/model bump re-runs the replay as a regression gate).

## Rotate or revoke a consumer key

oMLX sub keys are inference-only. Keys live in
`macos/secrets/mac-jms-01.sops.yaml` (`omlx.sub-keys.<name>`) and in the
consumer's cluster Secret.

- **Add:** add the key to sops and the name to `omlxSubKeyNames` in
  `macos/modules/omlx.nix`; create the matching SOPS Secret for the consumer.
- **Rotate:** change the value in both places. The reconciler adds the new
  key; the old one stays valid until revoked.
- **Revoke:** in the oMLX admin UI (`https://omlx.68cc.io/admin`) → sub keys,
  or `DELETE /admin/api/sub-keys` with the main key.
- **Main key:** change `omlx.main-key` in sops and merge. oMLX picks it up on
  restart: `sudo launchctl kickstart -k system/org.nixos.omlx`.
  The exporter re-reads it every scrape.

## Mac IP change

Two places: `macos/hosts/mac-jms-01/facts.nix` and the EndpointSlice in
`kubernetes/apps/ai/mac-inference/app/service.yaml`. Keep the UniFi DHCP
reservation as the source of truth.

## Retiring bigboi (spec Phase 3.5)

Remove `192.168.35.4` from `clusterNodeIps` in `facts.nix` in the same change.
````

- [ ] **Step 3: Validate the taskfile**

Run: `task --list | grep -E '^\* mac:'`
Expected: lines for `mac:apply-local`, `mac:build-local`, `mac:lock`, `mac:omlx-lock`, `mac:reboot`, `mac:status`, `mac:wait-up`.

- [ ] **Step 4: Commit**

```bash
git add .taskfiles/mac/Taskfile.yaml docs/runbooks/mac-studio-operations.md
git commit -m "docs(macos): task mac:reboot and the Mac Studio operations runbook

Spec Phase 1.6. Planned reboots use fdesetup authrestart so the Mac comes
back unlocked; wait-up treats a keyless 401 from oMLX as 'serving'. The
runbook covers pre-boot unlock, manual OS updates, rollback, engine bumps
and key rotation.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Full apply, end-to-end verification, merge

**Files:** none new. Ledger notes only, plus fixes if a check fails.

**Interfaces:**
- Consumes: everything above.
- Produces: the branch, ready for the operator to merge. After the merge, Phase 1 is verified in-cluster.

- [ ] **Step 1: Full apply** **OPERATOR**: `task mac:apply-local`, then `task mac:status`.
  Expected: these daemons are listed:
  - `org.nixos.home-ops-pull`, `org.nixos.home-ops-wired-limit`, `org.nixos.omlx`, `org.nixos.omlx-sub-keys`
  - `org.nixos.prometheus-node-exporter`, `org.nixos.macmon`, `org.nixos.omlx-exporter`, `org.nixos.vector`
  - `org.nixos.pf-home-ops`

  The textfiles show `home_ops_iogpu_wired_limit_bytes 90194313216` and `home_ops_pf_ruleset_loaded 1`.

- [ ] **Step 2: Metric names the rules rely on** *(on Mac)*:

```
ssh mac-jms-01 'curl -s localhost:9100/metrics | grep -E "^node_memory_(wired_bytes|swap_used_bytes|swapped_out_bytes_total|compressed_bytes)" ; curl -s localhost:9090/metrics | grep -E "^macmon_" | cut -d"{" -f1 | sort -u ; curl -s localhost:9101/metrics | head -12'
```

Expected:
- All four `node_memory_*` names are present.
- `macmon_*` power and temperature names match the dashboard regexes, and power is non-zero.
- `omlx_up 1`.
- If any `node_memory_*` name differs, fix the rule and dashboard expressions in Task 8's files and commit the fix: `fix(ai): match darwin node_exporter metric names`.

- [ ] **Step 3: Cilium SNAT check (spec Phase 0.5).** **OPERATOR**: run `sudo tcpdump -ni any 'tcp dst port 8000' -c 5` on the Mac. Then from HolyClaude run `curl -s -o /dev/null -w '%{http_code}\n' http://192.168.35.7:8000/v1/models`.
  Expected:
  - The source address is one of `192.168.35.3/.6/.10/.4`, never `10.42.x.x`.
  - curl prints `401`.
  - Record the observed source IP in the ledger and in the memory file.

- [ ] **Step 4: pf blocks the LAN.** **OPERATOR**: from the workstation, which is not a cluster node, run `curl -m 5 http://192.168.35.7:8000/v1/models`.
  Expected: a timeout. pf drops the traffic silently.

- [ ] **Step 5: Stop for the merge.** Push, PR and merge need the operator's OK.
  - Ask the operator: push `feat/macos-bringup` and open a PR? The PR body ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
  - The `macOS Nix` check must pass, then rebase and fast-forward to main.

- [ ] **Step 6: After the merge**
  - **Mac:** within 5 minutes, `task mac:status` shows `home_ops_nix_apply_info{commit="<main sha>"} 1` and `home_ops_nix_apply_behind_main 0`.
  - **Flux:** `KUBECONFIG=/workspace/home-ops/kubeconfig flux get ks -n ai mac-inference` reports Ready.
  - **Scrapes:** `kubectl -n monitoring port-forward svc/vmagent-vmagent 8429` and open `/targets` in a browser. Three `mac-jms-01` targets are up.
  - **Gatus:** `mac-inference-models` is green.
  - **Admin route:** `https://omlx.68cc.io/admin` from the LAN redirects to Authentik.
  - **Alert pipeline:** run `ssh mac-jms-01 sudo launchctl bootout system/org.nixos.omlx-exporter`, then wait 6 minutes. `MacStudioEngineDown` should reach Alertmanager. Restore with `task mac:apply-local`, or wait for the next main move.
````
