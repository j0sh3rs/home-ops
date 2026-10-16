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
grep -qx "switch --flake github:example/repo/${first}?dir=macos#mac-studio" "$REBUILD_LOG" || fail "rebuild not called with pinned commit"
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
