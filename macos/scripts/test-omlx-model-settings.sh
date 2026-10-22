#!/usr/bin/env bash
# Tests omlx-model-settings.sh against a stub oMLX admin API.
# Runs on Linux and macOS: bash macos/scripts/test-omlx-model-settings.sh
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
server_pid=
cleanup() { if [ -n "$server_pid" ]; then kill "$server_pid" 2>/dev/null || true; fi; rm -rf "$work"; }
trap cleanup EXIT

# Stub: login needs api_key "main-secret" and sets a cookie; every other route
# needs that cookie. PUT settings 404s for "missing"; POST load 409s for
# "busy" (already loading). Each request is logged as one JSON line.
cat > "$work/stub.py" <<'EOF'
import http.server, json, sys

log_path, port_path = sys.argv[1], sys.argv[2]
KNOWN = {"pinned-a", "ondemand-b", "busy"}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, code, body, cookie=False):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", "omlx_admin_session=s1; Path=/")
        self.end_headers()
        self.wfile.write(data)

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"null")
        with open(log_path, "a") as f:
            f.write(json.dumps({"method": self.command, "path": self.path, "body": body}) + "\n")
        if self.path == "/admin/api/login":
            if body == {"api_key": "main-secret"}:
                return self._reply(200, {"success": True}, cookie=True)
            return self._reply(401, {"detail": "bad key"})
        if "omlx_admin_session=s1" not in (self.headers.get("Cookie") or ""):
            return self._reply(401, {"detail": "no session"})
        parts = self.path.split("/")
        model = parts[4] if len(parts) > 4 else ""
        if model not in KNOWN:
            return self._reply(404, {"detail": "Model not found"})
        if self.command == "PUT" and parts[5:] == ["settings"]:
            return self._reply(200, {"success": True})
        if self.command == "POST" and parts[5:] == ["load"]:
            if model == "busy":
                return self._reply(409, {"detail": "already loading"})
            return self._reply(200, {"status": "ok"})
        return self._reply(405, {"detail": "unexpected route"})

    do_POST = do_PUT = _handle

srv = http.server.HTTPServer(("127.0.0.1", 0), H)
with open(port_path, "w") as f:
    f.write(str(srv.server_port))
srv.serve_forever()
EOF

python3 "$work/stub.py" "$work/requests.log" "$work/port" &
server_pid=$!
for _ in $(seq 1 50); do [ -s "$work/port" ] && break; sleep 0.1; done
[ -s "$work/port" ] || { echo "FAIL: stub server did not start"; exit 1; }

export OMLX_BASE_URL="http://127.0.0.1:$(cat "$work/port")"
export OMLX_LOGIN_ATTEMPTS=2
export OMLX_LOGIN_DELAY=0
printf 'main-secret' > "$work/main-key"
printf 'wrong' > "$work/wrong-key"

fail() { echo "FAIL: $*"; echo "--- requests:"; cat "$work/requests.log" 2>/dev/null || true; echo "--- output:"; cat "$work/out" 2>/dev/null || true; exit 1; }
reqs() { jq -c --arg m "$1" --arg p "$2" 'select(.method == $m and .path == $p)' "$work/requests.log"; }
run() { bash "$here/omlx-model-settings.sh" "$@" > "$work/out" 2>&1; }

# 1. Every model gets its settings verbatim; only pinned ones are loaded.
cat > "$work/settings.json" <<'EOF'
{
  "pinned-a": {"is_pinned": true, "max_tokens": 16384, "model_alias": "reasoner"},
  "ondemand-b": {"is_pinned": false, "ttl_seconds": 1800, "model_alias": "coder"}
}
EOF
: > "$work/requests.log"
run "$work/main-key" "$work/settings.json" || fail "happy path exited non-zero"
[ "$(reqs PUT /admin/api/models/pinned-a/settings | jq -c .body)" = '{"is_pinned":true,"max_tokens":16384,"model_alias":"reasoner"}' ] || fail "pinned-a settings body"
[ "$(reqs PUT /admin/api/models/ondemand-b/settings | jq -c .body)" = '{"is_pinned":false,"ttl_seconds":1800,"model_alias":"coder"}' ] || fail "ondemand-b settings body"
[ -n "$(reqs POST /admin/api/models/pinned-a/load)" ] || fail "pinned model not loaded"
[ -z "$(reqs POST /admin/api/models/ondemand-b/load)" ] || fail "unpinned model was loaded"
if grep -q main-secret "$work/out"; then fail "main key leaked into output"; fi

# 2. An unknown model fails the run but does not stop the others.
cat > "$work/settings.json" <<'EOF'
{
  "missing": {"max_tokens": 1},
  "pinned-a": {"is_pinned": true}
}
EOF
: > "$work/requests.log"
if run "$work/main-key" "$work/settings.json"; then fail "unknown model should exit non-zero"; fi
grep -q 'missing settings failed (http 404)' "$work/out" || fail "404 not reported by model name"
[ -n "$(reqs POST /admin/api/models/pinned-a/load)" ] || fail "later model skipped after a failure"

# 3. A pinned model that is already loading (409) is not a failure.
printf '{"busy": {"is_pinned": true}}' > "$work/settings.json"
: > "$work/requests.log"
run "$work/main-key" "$work/settings.json" || fail "409 on load should not fail the run"

# 4. Wrong main key: login retried OMLX_LOGIN_ATTEMPTS times, then exit 1.
: > "$work/requests.log"
if run "$work/wrong-key" "$work/settings.json"; then fail "bad login should exit non-zero"; fi
[ "$(reqs POST /admin/api/login | wc -l | tr -d ' ')" = 2 ] || fail "login not retried twice"
[ -z "$(reqs PUT /admin/api/models/busy/settings)" ] || fail "settings sent without a session"

echo "PASS: omlx-model-settings"
