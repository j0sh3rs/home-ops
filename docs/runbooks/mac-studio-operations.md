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

Pre-boot unlock result from bring-up (§11): untested at bring-up — after the first unlock over SSH, replace this line with what happened (worked / needed console).

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
- User/group changes (e.g. the `_omlx` service user) are **not** applied by
  the pull loop. Creating users needs Full Disk Access, so apply them
  manually with `task mac:apply-local` from a terminal that has Full Disk
  Access.

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
   `pfctl -E` and never releases its token, so `-X` on another token doesn't
   turn pf off.

Recovery is the next `darwin-rebuild switch`, which reloads the daemon, or
`sudo launchctl bootstrap system /Library/LaunchDaemons/org.nixos.pf-home-ops.plist`.

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
- **Revoke:** log in through the admin UI (`https://omlx.68cc.io/admin`) →
  sub keys, or POST the main key to `/admin/api/login` (JSON
  `{"api_key": "<main key>"}`) and use the returned `omlx_admin_session`
  cookie for `DELETE /admin/api/sub-keys`. oMLX 0.7.0 admin routes do not
  accept the main key as a Bearer token.
- **Main key:** change `omlx.main-key` in sops and merge. oMLX picks it up on
  restart: `sudo launchctl kickstart -k system/org.nixos.omlx`.
  The exporter re-reads it every scrape.

## Mac IP change

Two places: `macos/hosts/mac-jms-01/facts.nix` and the EndpointSlice in
`kubernetes/apps/ai/mac-inference/app/service.yaml`. Keep the UniFi DHCP
reservation as the source of truth.

## Retiring bigboi (spec Phase 3.5)

Remove `192.168.35.4` from `clusterNodeIps` in `facts.nix` in the same change.
