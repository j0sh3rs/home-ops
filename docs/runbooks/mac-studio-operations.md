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
  and, for the oMLX app, `~/.omlx/logs/server.log` of the admin user.

## Planned reboot

```bash
task mac:reboot
```

Uses `fdesetup authrestart`, so the Mac boots past the FileVault screen.
Ends when oMLX answers again (≤ 10 min) — otherwise follow "Unplanned reboot".
The confirmation prompt needs `task -y mac:reboot` when run non-interactively.

## Unplanned reboot (power cut, panic, plain `reboot`)

The Mac stops at FileVault pre-boot; the OS and all services are down and
`MacStudioUnreachable` pages. macOS itself is not running, but the pre-boot
SSH unlock service is expected to be.

Pre-boot unlock result from bring-up (§11): untested at bring-up — after the
first unlock over SSH, replace this line with what happened (worked / needed
console).

1. Attempt the SSH unlock: `ssh mac-jms-01`, answer the pre-boot prompt.
2. If SSH does not answer within a minute, unlock at the console (keyboard and
   monitor on the Mac).
3. Then `task mac:wait-up`.

## macOS update (manual only — auto-updates are off in nix)

1. Read the release notes for Metal / MLX / `iogpu` changes; check oMLX and
   macmon issues for the new version.
2. On the Mac: `softwareupdate --list`.
3. `sudo softwareupdate --install --all --restart --user j0sh3rs --stdinpass`
   (Apple silicon needs the owner's credentials; `--stdinpass` reads the
   password from stdin).
4. The update reboot is expected to land at FileVault pre-boot — unlock as in
   "Unplanned reboot", then `task mac:wait-up`.
5. Verify: `task mac:status`; `home_ops_iogpu_wired_limit_bytes` ≈ 90.2e9;
   `home_ops_pf_ruleset_loaded 1`; Grafana macmon power panels non-zero
   (macmon's power counters are OS-version-sensitive).
6. Re-run the eval replay (`tools/ai-eval/README.md`) before trusting
   output quality on the new OS.

## Config changes and rollback

- Change `macos/` by PR. CI (`macOS Nix`) builds it; merging deploys within
  5 min (pull loop). Test first with `task mac:apply-local` if risky.
- **Before merging a PR that adds any user or group** (including one created
  implicitly by a module, see below), apply the head tree with
  `task mac:apply-local` from a Full Disk Access terminal. Otherwise every
  pull-loop switch aborts.
- **Roll back:** `git revert` the commit on main (the loop applies it), or on
  the Mac `sudo darwin-rebuild --rollback` (immediate; the loop won't
  override it until main moves again).
- Changing `launchd.daemons.home-ops-pull` itself: apply with
  `task mac:apply-local` — the loop can't safely reload its own plist.
- User/group changes (e.g. the `_omlx` service user) are **not** applied by
  the pull loop. Creating users needs Full Disk Access, so apply them
  manually with `task mac:apply-local` from a terminal that has Full Disk
  Access. This includes users created *implicitly* by nix-darwin service
  modules, not only `users.users` entries: for example
  `services.prometheus.exporters.node.enable = true` creates
  `_prometheus-node-exporter`. Any change that adds a user or group must be
  applied with `task mac:apply-local` from an FDA terminal **before** it
  merges. Otherwise the loop's whole switch aborts in `system.checks` every
  5 minutes (nothing in the PR deploys), and each failed run still advances
  the system profile to an unactivated generation, which a reboot would then
  half-activate. Recover with `sudo darwin-rebuild --rollback` or an FDA apply.

## Firewall (pf)

`macos/modules/pf.nix` allows only localhost and the cluster node IPs
(`clusterNodeIps` in `facts.nix`) to reach ports 8000/9090/9100/9101. SSH (22)
is not filtered.

The enforcer is the launchd daemon `org.nixos.pf-home-ops`: it re-asserts the
ruleset every 60 s and publishes the gauge `home_ops_pf_ruleset_loaded`.

The admin workstation is blocked from those ports by design. Use an SSH
tunnel instead, e.g. `ssh -L 8000:localhost:8000 mac-jms-01`. For the admin
UI over the LAN, use `https://omlx.68cc.io/admin`.

**Emergency disable:**

1. Stop the enforcer first: `sudo launchctl bootout system/org.nixos.pf-home-ops`.
   Otherwise it re-enables pf within 60 s.
2. Then `sudo pfctl -d`.
3. Do **not** use `pfctl -X`. The enforcer enables pf with reference-counted
   `pfctl -E` and never releases its token. `-X <token>` only releases that
   one token's reference, so the enforcer's reference is still held and pf
   stays enabled. `-d` force-disables pf.

Recovery: `sudo launchctl bootstrap system /Library/LaunchDaemons/org.nixos.pf-home-ops.plist`.
A `darwin-rebuild switch` does **not** reload it, because nix-darwin only
reloads a daemon whose plist changed.

After `bootout` the `home_ops_pf_ruleset_loaded` gauge goes stale (the last
`.prom` value is frozen at 1) rather than dropping to 0, so
`MacStudioPfNotLoaded` stays quiet. `MacStudioTextfileStale` fires when a textfile
stops updating (pf after 15 min, pull loop after 40 min, wired-limit after
~2 h) and catches a stopped enforcer (and any other dead textfile writer).
A single very long `darwin-rebuild` can also trip it for the pull file; it
clears on the next successful loop run.

## oMLX (user-run app)

Since 2026-11-13 the canonical oMLX is the **user-run oMLX app** (`~/.omlx`, bundled engine, started at login), not
a nix-managed daemon. The earlier nix service, its model-settings and sub-key reconcilers and the pinned engine
project were removed because the app held port 8000 and the daemon crash-looped on `Address already in use`.
Rationale and evidence: `docs/research/2026-11-13-omlx-splash-model-evaluation/`.

- **Boot dependency:** the app only runs while the admin user is logged in. After a reboot (FileVault
  `authrestart`, see "Planned reboot") inference stays down until that login happens and the app starts
  (`auto_start_on_launch` is on). This replaces the old "serves from boot without a login" property; revisit if
  unattended reboots matter.
- **Upgrade:** use the app's own updater. Re-run the speech, Hindsight and coding checks in
  `tools/ai-eval/README.md` after an upgrade (a regression gate), and re-test the Splash profile after any
  profile edit.
- **Models, aliases, pins, TTLs, memory ceiling, `max_tokens` defaults:** set in the oMLX admin UI or admin API
  (`https://omlx.68cc.io/admin`, behind Authentik). Nothing reconciles them any more, so they are not reverted.
  Current values are in `docs/research/2026-11-13-omlx-splash-model-evaluation/rollout.md`.
- **Keys:** the main key lives in the app's `~/.omlx/settings.json` and in `macos/secrets/mac-jms-01.sops.yaml`
  as `omlx.main-key`; the oMLX exporter logs in with the sops copy, so **update both when the main key changes**
  and merge, or `omlx_up` drops to 0. Sub keys (inference only) live in the app and in each consumer's cluster
  Secret. Add a key in the admin UI (`POST /admin/api/sub-keys`), then put it in the consumer's SOPS Secret.
  Revoke by deleting it in the admin UI. A consumer holding a key the app does not know is locked out per
  source address (8 wrong keys, then 30 s, then 5 minutes), and pods share their node's address, so a stale key
  also locks out other consumers on that node.
- **Logs:** the app writes `~/.omlx/logs/server.log`; Splash processes log under `~/.omlx/logs/splash/`.

## Mac IP change

Two places: `macos/hosts/mac-jms-01/facts.nix` and the EndpointSlice in
`kubernetes/apps/ai/mac-inference/app/service.yaml`. Keep the UniFi DHCP
reservation as the source of truth.

## Retiring bigboi (spec Phase 3.5)

Remove `192.168.35.4` from `clusterNodeIps` in `facts.nix` in the same change.
