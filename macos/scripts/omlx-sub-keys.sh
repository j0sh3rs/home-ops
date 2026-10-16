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

# oMLX admin routes (/admin/api/*) authenticate with a session cookie from
# POST /admin/api/login (main key only), not a Bearer header. Retry the login
# until the server is up.
jar=$(mktemp)
trap 'rm -f "$jar"' EXIT
login=$(jq -n --arg k "$main_key" '{api_key: $k}')
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null -c "$jar" -X POST -H 'Content-Type: application/json' \
    -d "$login" "$BASE_URL/admin/api/login"; then break; fi
  sleep 5
done
curl -fsS -o /dev/null -b "$jar" "$BASE_URL/admin/api/server-info"

for pair in "$@"; do
  name=${pair%%=*}
  key=$(cat "${pair#*=}")
  fp=$(printf '%s:%s' "$name" "$key" | shasum -a 256 | cut -d' ' -f1)
  if grep -qx "$fp" "$STATE"; then continue; fi
  body=$(jq -n --arg name "$name" --arg key "$key" '{name: $name, key: $key}')
  curl -fsS -X POST -b "$jar" -H 'Content-Type: application/json' -d "$body" "$BASE_URL/admin/api/sub-keys" > /dev/null
  echo "$fp" >> "$STATE"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) added sub key $name"
done
