# Mac Studio bring-up — manual base setup

Spec: `docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md`, Phase 1.1.
Plan: `docs/superpowers/plans/2026-10-16-mac-studio-bringup.md` (everything after
this checklist is nix and GitOps).

Do these at the Mac, in order. The steps can't be done from the repo, or they
must exist before the first `darwin-rebuild`. Section 9 lists the facts to
hand back; the plan's Task 1 needs every one of them.

## 1. macOS Setup Assistant

- [ ] Create **one admin account**. Pick a short username and write it down
      (fact `ADMIN_USER`).
- [ ] Computer name: **`mac-jms-01`** (System Settings → General → Sharing →
      Local hostname, check it reads `mac-jms-01.local`).
- [ ] Decline Apple Intelligence, Siri, Screen Time and analytics. None are
      needed on a server and each adds background memory use.
- [ ] Sign in to an Apple Account **only if** you want Find My. It is not needed
      for anything in the plan.
- [ ] Wire 10GbE. Disable Wi-Fi (System Settings → Wi-Fi → off) so the
      host has one stable address.

## 2. FileVault, auto-login, power

- [ ] System Settings → Privacy & Security → FileVault → **On**. Choose
      "Create a recovery key" (not iCloud). Store the recovery key in your
      password manager **before** clicking Continue.
- [ ] System Settings → Users & Groups → Automatically log in as → **Off**.
      FileVault forces this anyway; confirm it.
- [ ] System Settings → Energy → "Start up automatically after a power
      failure" → **On**. (nix sets the sleep settings later; this one is
      just the most important to have before nix exists.)

## 3. Updates off

- [ ] System Settings → General → Software Update → Automatic updates (ⓘ) →
      turn **off** "Download new updates when available", "Install macOS
      updates" and "Install Security Responses and system files".
      nix also enforces these keys (Task 1). Turning them off by hand closes
      the gap before the first `darwin-rebuild`.
- [ ] Write down the macOS version: `sw_vers -productVersion` (fact `MACOS_VERSION`).
      macmon's power counters change behaviour on macOS 27, so the plan needs
      this.

## 4. Network

- [ ] Create a **DHCP reservation** in UniFi for the Mac's 10GbE MAC address.
      Pick a free address in `192.168.35.0/24` **outside** the Cilium LB / VIP
      ranges (`.15` and `.17` are Traefik VIPs). This is fact `MAC_IP`.
- [ ] Renew the lease (`sudo ipconfig set en0 DHCP` or replug), then confirm with
      `ipconfig getifaddr <iface>`.
- [ ] Confirm the Mac can reach GitHub: `curl -sI https://github.com | head -1`.

## 5. SSH (key-only)

- [ ] System Settings → General → Sharing → **Remote Login → On**, "Allow
      access for: Only these users" → your admin user.
- [ ] From your workstation: `ssh-copy-id <ADMIN_USER>@<MAC_IP>`, then
      `ssh <ADMIN_USER>@<MAC_IP> true` must succeed **without a password**.
- [ ] Add this to `~/.ssh/config` on every machine you'll run `task mac:*` from.
      The taskfile only ever calls `ssh mac-jms-01`:

      ```
      Host mac-jms-01
        HostName <MAC_IP>
        User <ADMIN_USER>
        IdentitiesOnly yes
      ```

- [ ] **Optional: let HolyClaude/subagents verify on the Mac.** Plan steps
      marked *(on Mac)* can run from HolyClaude if it has a key; otherwise you
      run them by hand. HolyClaude already holds cluster-admin, so this
      widens what a compromised pod can reach. Your call. To allow it, in
      HolyClaude:

      ```bash
      mkdir -p ~/.claude/ssh && chmod 700 ~/.claude/ssh
      ssh-keygen -t ed25519 -N '' -f ~/.claude/ssh/mac-jms-01 -C holyclaude@mac-jms-01
      cat ~/.claude/ssh/mac-jms-01.pub   # paste into the Mac's ~/.ssh/authorized_keys
      ```

      Then add `IdentityFile ~/.claude/ssh/mac-jms-01` to HolyClaude's
      `Host mac-jms-01` block. (`~/.claude` is the only persisted path in the
      container.)
- [ ] Do **not** disable password auth by hand. nix does it in Task 1, and you
      verify with `sudo sshd -T | grep -i passwordauthentication`.

## 6. Xcode Command Line Tools and Homebrew

- [ ] `xcode-select --install`. git, the compilers uv needs to build oMLX,
      and Homebrew all need it.
- [ ] Install Homebrew: https://brew.sh. nix-darwin's `homebrew` module manages
      it but does not install it. **Warning:** the module runs with
      `cleanup = "zap"`, so any formula or cask you install by hand **will be
      removed** on the next apply. Only add packages through `macos/`.

## 7. Determinate Nix

- [ ] Install with the Determinate installer (the graphical `.pkg` from
      https://docs.determinate.systems, or
      `curl -fsSL https://install.determinate.systems/nix | sh -s -- install`).
- [ ] New terminal: `nix --version` prints `Determinate Nix 3.15.2` or newer.
      The `determinateNix.*` module options need ≥ 3.15.2.

## 8. Mac-only age key (sops-nix)

- [ ] Generate it at the root-only path sops-nix reads during activation:

      ```bash
      sudo mkdir -p /var/lib/sops-nix
      sudo nix shell nixpkgs#age -c age-keygen -o /var/lib/sops-nix/key.txt
      sudo chmod 600 /var/lib/sops-nix/key.txt
      sudo nix shell nixpkgs#age -c age-keygen -y /var/lib/sops-nix/key.txt
      ```

- [ ] The last command prints `age1…`. That is fact `MAC_AGE_PUBKEY` (public,
      safe to paste anywhere).
- [ ] Back up the **private** key file to your password manager. Losing it
      means re-keying `macos/secrets/`, nothing worse.

## 9. Hand back these facts

| Fact | Example | Used by |
|---|---|---|
| `ADMIN_USER` | `josh` | `system.primaryUser`, SSH |
| `MAC_IP` | `192.168.35.20` | EndpointSlice, VMStaticScrape, ssh config |
| `MACOS_VERSION` | `26.1` | macmon choice, OS-update runbook |
| `MAC_AGE_PUBKEY` | `age1…` | `.sops.yaml` rule for `macos/secrets/` |
| HolyClaude key authorized? | yes / no | whether plan steps marked *(on Mac)* run unattended |

## 10. After the plan's Task 1 lands (first apply)

The first `darwin-rebuild` runs from a local copy of `macos/`, because the
pull loop only exists after Task 3. The command is in the plan (Task 1,
"first apply"). In short:

```bash
# workstation / HolyClaude, from the repo root
task mac:apply-local
```

## 11. Once, after Task 1: prove pre-boot unlock works

Tahoe's FileVault pre-boot SSH lets you unlock after an unplanned reboot
(power cut). Test it while you are at the Mac, not during an outage:

- [ ] `sudo reboot` (plain reboot, **not** authrestart).
- [ ] From the workstation: `ssh mac-jms-01`. Expect the pre-boot unlock
      prompt. Unlock, and confirm the Mac finishes booting and SSH works
      normally afterwards.
- [ ] If pre-boot SSH needs password auth, or refuses the key, write down
      exactly what it asked for. The operations runbook (Task 9) records the
      answer.
