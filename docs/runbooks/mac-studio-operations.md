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
(`clusterNodeIps` in `facts.nix`) to reach ports 8000/9090/9100/9101, and only
the LAN (`lanCidr`) to reach 443 (the Traefik TLS edge, below). SSH (22)
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

## TLS edge: `https://inference.68cc.io`

`macos/modules/traefik.nix` runs Traefik (launchd `org.nixos.traefik`, user `nobody`, port 443) in front of oMLX on
`127.0.0.1:8000`. Certificates are Let's Encrypt DNS-01 on Cloudflare, issued and renewed by Traefik itself (state in
`/var/lib/traefik/acme.json`), using the **same Cloudflare token as cert-manager**, stored as `traefik.cloudflare-token`
in `macos/secrets/mac-jms-01.sops.yaml`. When cert-manager's token rotates, rotate this one too (copy
`kubernetes/apps/cert-manager/cert-manager/app/secret.sops.yaml` `api-token` with `sops set --value-stdin`).
The name resolves to the Mac through `kubernetes/apps/ai/mac-inference/app/dnsendpoint.yaml` (unifi-dns, LAN only).

- Only `/v1` is routed. The admin UI and its login stay at `https://omlx.68cc.io/admin` behind Authentik; everything
  else on this name is a 404.
- oMLX still checks every API key. It exempts loopback peers from its wrong-key lockout and every client is loopback
  behind the proxy, so key guessing is limited only by Traefik's per-client rate limit (100/s, burst 200) and by pf
  (443 is LAN only). Consumers should keep using their sub keys; do not give out the main key.
- Port 8000 is still open to the cluster (consumers use `mac-inference.ai.svc:8000` over plain HTTP). Moving them to
  the TLS name, then closing 8000 to everything but localhost, is a separate change.
- Check: `curl -sS https://inference.68cc.io/v1/models -H "Authorization: Bearer <sub key>"`. First issuance takes
  about a minute after the first apply; `/var/log/home-ops/traefik.log` shows the ACME progress.

## oMLX instance: the user-run app is canonical (for now)

Since 2026-11-13 the oMLX serving port 8000 is the **user-run oMLX app** (`~/.omlx`), not the nix-managed daemon.
The nix daemon and its two reconcilers are disabled by default (`home-ops.omlx.engine.enable = false` in
`macos/modules/omlx.nix`); the code, engine project, scripts, tests and CI checks are kept so re-enabling is one
line. **Quit the app before enabling it**, or the daemon crash-loops on `Address already in use` and the
reconcilers rewrite the app's aliases, pins and keys every 10 minutes.

- **The three sections below ("Engine (oMLX) upgrade", "Rotate or revoke a consumer key", "Model settings")
  describe the nix-managed engine and apply only when it is enabled.** With the app canonical: upgrade with the
  app's updater and rerun the checks in `tools/ai-eval/README.md`; manage models, aliases, pins, TTLs and the
  memory ceiling in the oMLX admin UI (current values: `docs/research/2026-11-13-omlx-splash-model-evaluation/rollout.md`);
  add or revoke sub keys in the admin UI and put them in the consumer's SOPS Secret.
- **`omlx.main-key` in `macos/secrets/mac-jms-01.sops.yaml` must equal the app's main key** (`~/.omlx/settings.json`):
  the oMLX exporter logs in with it (through the sops secret `omlx/exporter-key`, a copy of `omlx/main-key` readable by
  `nobody`), and `omlx_up` is 0 when it is wrong. Update both when the key changes. The exporter runs as `nobody`
  because launchd could not spawn it as `_omlx` once the engine daemon was off (last exit 78, `EX_CONFIG`).
- **Boot dependency:** the app runs only while the admin user is logged in, so after a FileVault reboot inference
  stays down until that login (`auto_start_on_launch` is on). The nix daemon used to serve from boot.
- **Lockout:** a consumer holding a key the app does not know is locked out per source address (8 wrong keys, then
  30 s, then 5 minutes), and pods share their node's address, so one stale key also locks out other consumers on
  that node.
- The app logs to `~/.omlx/logs/server.log` (Splash under `~/.omlx/logs/splash/`).

## Engine (oMLX) upgrade

1. Renovate's pep621 manager opens the PR. It bumps the `tag` under
   `[tool.uv.sources]` in `macos/engines/omlx/pyproject.toml` and regenerates
   `uv.lock` in the same commit (`uv lock --upgrade-package omlx`). Keep the
   pin in `[tool.uv.sources]`: a `omlx @ git+...@tag` URL in `dependencies` is
   invisible to pep621, and a tag bump without a matching lock stops the
   daemon (`uv sync --locked` refuses to start, #785).
2. "Build darwin closure" must pass. A failure there on an engine bump is a
   blocker, not noise. For a manual bump, `task mac:omlx-lock` regenerates
   the lock on the Mac.
3. Run the eval replay against the new build before merging (spec: every
   engine/model bump re-runs the replay as a regression gate).

The lock hash is part of the daemon plist (`OMLX_LOCK_HASH`), so the merge
restarts the engine on the new lock.

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
  cookie for `DELETE /admin/api/sub-keys` (check the request shape in the
  admin UI's network tab before scripting it). oMLX 0.7.0 admin routes do not
  accept the main key as a Bearer token.
- **Main key:** change `omlx.main-key` in sops and merge. oMLX picks it up on
  restart: `sudo launchctl kickstart -k system/org.nixos.omlx`.
  The exporter re-reads it every scrape.

## Model settings (aliases, pins, max_tokens)

`omlxModelSettings` in `macos/modules/omlx.nix` is the source of truth. The
`org.nixos.omlx-model-settings` daemon (every 10 minutes, and at load) PUTs
each entry to `/admin/api/models/<dir>/settings` and loads the pinned ones.
Changes made in the admin UI are reverted on the next run, so edit nix.
Log: `/var/log/home-ops/omlx-model-settings.log`.

| Directory | Alias | Mode |
|---|---|---|
| `gpt-oss-20b-MXFP4-Q8` | `reasoner` | pinned |
| `Qwen3.6-35B-A3B-MLX-4bit` | `agent` (thinking off) | pinned |
| `Qwen3-Coder-Next-MLX-4bit` | `coder` | on demand, 30 min TTL |

- **Add or swap a model:** copy it into `/opt/ai/models.noindex/` as
  `_omlx` (APFS clone, `cp -c`), then add or edit its entry and merge. To
  move an alias to a new model, remove it from the old entry in the same
  change. oMLX rejects an alias that another model still holds (http 400 in
  the log). Each alias has to be unique and must not match a directory name.
- **max_tokens** is only the default for requests that send none.
  Consumers that send their own limit keep it.
- **Unpin:** set `is_pinned = false` and merge. The model stays loaded
  until the TTL or memory pressure evicts it. To free the memory now, use
  `POST /admin/api/models/<dir>/unload` or the admin UI.
- **Apply now:** `sudo launchctl kickstart -k system/org.nixos.omlx-model-settings`.

## Mac IP change

Two places: `macos/hosts/mac-jms-01/facts.nix` and the EndpointSlice in
`kubernetes/apps/ai/mac-inference/app/service.yaml`. Keep the UniFi DHCP
reservation as the source of truth.

## Retiring bigboi (spec Phase 3.5)

Remove `192.168.35.4` from `clusterNodeIps` in `facts.nix` in the same change.
