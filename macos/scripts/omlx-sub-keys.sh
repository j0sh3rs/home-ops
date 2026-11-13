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

umask 077
touch "$STATE"

# Secrets never go on argv (ps shows other users' command lines): JSON bodies
# are built by jq from per-command env assignments (not argv) and fed to curl
# on stdin. The cookie jar and response file are 0600 and removed on exit.
jar=$(mktemp)
resp=$(mktemp)
trap 'rm -f "$jar" "$resp"' EXIT

# oMLX admin routes (/admin/api/*) authenticate with a session cookie from
# POST /admin/api/login (main key only), not a Bearer header. Retry the login
# until the server is up.
logged_in=0
for _ in $(seq 1 60); do
  if K="$main_key" jq -n '{api_key: env.K}' |
    curl -fsS -o /dev/null -c "$jar" -X POST -H 'Content-Type: application/json' \
      --data-binary @- "$BASE_URL/admin/api/login"; then
    logged_in=1
    break
  fi
  sleep 5
done
if [ "$logged_in" -ne 1 ]; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) admin login failed (server down or main key mismatch)" >&2
  exit 1
fi

# Each pair is independent: a failure for one is logged by name (never the
# key) and the rest still run; the exit status reflects any failure.
failed=0
for pair in "$@"; do
  name=${pair%%=*}
  if ! key=$(cat "${pair#*=}"); then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cannot read key file for $name" >&2
    failed=1
    continue
  fi
  fp=$(printf '%s:%s' "$name" "$key" | shasum -a 256 | cut -d' ' -f1)
  if grep -qx "$fp" "$STATE"; then continue; fi
  code=$(N="$name" KEY="$key" jq -n '{name: env.N, key: env.KEY}' |
    curl -sS -o "$resp" -w '%{http_code}' -X POST -b "$jar" \
      -H 'Content-Type: application/json' --data-binary @- \
      "$BASE_URL/admin/api/sub-keys") || code=000
  # oMLX 0.7.0 answers a re-registered key with 400 {"detail":"This key
  # already exists"}: it is already applied, so record it and move on.
  if [ "$code" = 200 ] || { [ "$code" = 400 ] && grep -q 'This key already exists' "$resp"; }; then
    echo "$fp" >> "$STATE"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sub key $name applied (http $code)"
  else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sub key $name failed (http $code)" >&2
    failed=1
  fi
done
exit "$failed"
