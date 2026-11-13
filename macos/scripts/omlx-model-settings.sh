#!/usr/bin/env bash
# omlx-model-settings: push the nix-declared per-model settings (alias, pin,
# max_tokens, TTL, thinking) to oMLX and load the pinned models. Arguments:
# the main-key file, then a JSON file mapping model directory name to the
# body for PUT /admin/api/models/<model>/settings. Every run re-sends every
# model, so edits made in the admin UI are reverted within StartInterval.
# The fields used here are all request-time settings, so re-sending them
# never reloads a loaded model.
set -euo pipefail

BASE_URL="${OMLX_BASE_URL:-http://127.0.0.1:8000}"
attempts="${OMLX_LOGIN_ATTEMPTS:-60}"
delay="${OMLX_LOGIN_DELAY:-5}"
main_key=$(cat "$1")
settings="$2"

umask 077
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# The main key never goes on argv (ps shows other users' command lines): the
# login body is built by jq from an env assignment and fed to curl on stdin.
jar=$(mktemp)
resp=$(mktemp)
trap 'rm -f "$jar" "$resp"' EXIT

# Admin routes authenticate with a session cookie from POST /admin/api/login
# (main key only). Retry the login until the server is up.
logged_in=0
for _ in $(seq 1 "$attempts"); do
  if K="$main_key" jq -n '{api_key: env.K}' |
    curl -fsS -o /dev/null -c "$jar" -X POST -H 'Content-Type: application/json' \
      --data-binary @- "$BASE_URL/admin/api/login"; then
    logged_in=1
    break
  fi
  sleep "$delay"
done
if [ "$logged_in" -ne 1 ]; then
  echo "$(ts) admin login failed (server down or main key mismatch)" >&2
  exit 1
fi

# Each model is independent: a failure is logged by name and the rest still
# run; the exit status reflects any failure. oMLX 404s an unknown model
# directory and 400s a duplicate or clashing alias.
failed=0
while IFS= read -r model; do
  path=$(jq -rn --arg m "$model" '$m | @uri')
  code=$(jq -c --arg m "$model" '.[$m]' "$settings" |
    curl -sS -o "$resp" -w '%{http_code}' -X PUT -b "$jar" \
      -H 'Content-Type: application/json' --data-binary @- \
      "$BASE_URL/admin/api/models/$path/settings") || code=000
  if [ "$code" != 200 ]; then
    echo "$(ts) $model settings failed (http $code): $(head -c 300 "$resp")" >&2
    failed=1
    continue
  fi
  # Pinning only stops eviction; oMLX preloads pinned models at startup but
  # not when the pin is set at runtime. Load them now. 409 = already loading.
  if [ "$(jq --arg m "$model" '.[$m].is_pinned == true' "$settings")" = true ]; then
    code=$(curl -sS -o "$resp" -w '%{http_code}' -X POST -b "$jar" --max-time 900 \
      "$BASE_URL/admin/api/models/$path/load") || code=000
    if [ "$code" != 200 ] && [ "$code" != 409 ]; then
      echo "$(ts) $model load failed (http $code): $(head -c 300 "$resp")" >&2
      failed=1
      continue
    fi
  fi
  echo "$(ts) $model settings applied"
done < <(jq -r 'keys_unsorted[]' "$settings")
exit "$failed"
