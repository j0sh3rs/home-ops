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
# Absolute path: macOS always ships it, and the launchd PATH need not.
PGREP="${HOME_OPS_PGREP:-/usr/bin/pgrep}"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

# launchd runs this at plist load (RunAtLoad), which happens mid-switch.
# Don't start a second darwin-rebuild; leave state and metrics untouched.
if "$PGREP" -f darwin-rebuild >/dev/null 2>&1; then
  log "darwin-rebuild already running; skipping this run"
  exit 0
fi

mkdir -p "$STATE_DIR" "$TEXTFILE_DIR"
now=$(date +%s)
applied=$(cat "$STATE_DIR/applied-commit" 2>/dev/null || true)
in_sync_at=$(cat "$STATE_DIR/in-sync-at" 2>/dev/null || echo 0)
rc=0
head=""

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
