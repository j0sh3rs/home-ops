"""Prometheus exporter for oMLX, which has no /metrics of its own.

oMLX documents /admin/api/stats but not its response shape, so this does
not guess field names: every numeric (or boolean) leaf becomes one sample
of omlx_stat{scope,path}, path being the dotted JSON path. Dashboards and
alerts pick the paths they need. omlx_up is 0 when any stats call fails.

Admin routes need a session cookie, so fetch() logs in with the main key
(POST /admin/api/login) and re-logs-in once on 401/403.

The main API key is re-read from its file on every scrape, so a rotation
needs no restart. Stdlib only; packaged by macos/modules/observability.nix.
"""
import argparse
import http.cookiejar
import json
import math
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCOPES = ("session", "alltime")
SESSION_COOKIE = "omlx_admin_session"
_lock = threading.Lock()  # one session shared by concurrent scrapes
_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))
_ESCAPES = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n"})


def flatten(obj, prefix=""):
    """Yield (dotted_path, float) for every finite numeric or boolean leaf."""
    if isinstance(obj, bool):
        yield prefix, 1.0 if obj else 0.0
    elif isinstance(obj, (int, float)):
        value = float(obj)
        if math.isfinite(value):
            yield prefix, value
    elif isinstance(obj, dict):
        for key in sorted(obj, key=str):
            yield from flatten(obj[key], f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            yield from flatten(item, f"{prefix}.{index}" if prefix else str(index))


def render(up, stats, duration):
    lines = [
        "# HELP omlx_up 1 if every oMLX stats request in this scrape succeeded.",
        "# TYPE omlx_up gauge",
        f"omlx_up {1 if up else 0}",
        "# HELP omlx_scrape_duration_seconds Time spent querying oMLX.",
        "# TYPE omlx_scrape_duration_seconds gauge",
        f"omlx_scrape_duration_seconds {duration:.6f}",
        "# HELP omlx_stat Numeric leaf of /admin/api/stats; path is the dotted JSON path.",
        "# TYPE omlx_stat gauge",
    ]
    for scope in SCOPES:
        for path, value in flatten(stats.get(scope, {})):
            lines.append(f'omlx_stat{{scope="{scope}",path="{path.translate(_ESCAPES)}"}} {value!r}')
    return "\n".join(lines) + "\n"


def reset_session():
    """Drop the cached admin session (used by tests)."""
    global _jar, _opener
    _jar = http.cookiejar.CookieJar()
    _opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def _login(base_url, api_key, timeout):
    # oMLX admin routes accept only the omlx_admin_session cookie, which
    # POST /admin/api/login hands out for the main key. The key travels in
    # the JSON body only, never in a URL, and never in an error message.
    req = urllib.request.Request(
        f"{base_url}/admin/api/login",
        data=json.dumps({"api_key": api_key}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _opener.open(req, timeout=timeout):
            pass
    except urllib.error.HTTPError as exc:
        exc.close()
        raise RuntimeError(f"login failed: HTTP {exc.code}") from None


def _get_stats(base_url, scope, timeout):
    with _opener.open(f"{base_url}/admin/api/stats?scope={scope}", timeout=timeout) as resp:
        return json.load(resp)


def fetch(base_url, api_key, scope, timeout=5):
    with _lock:
        return _fetch_locked(base_url, api_key, scope, timeout)


def _fetch_locked(base_url, api_key, scope, timeout):
    if not any(c.name == SESSION_COOKIE for c in _jar):
        _login(base_url, api_key, timeout)
    try:
        return _get_stats(base_url, scope, timeout)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code not in (401, 403):
            raise RuntimeError(f"{scope}: stats failed: HTTP {exc.code}") from None
    # Session expired or the server restarted: log in once more and retry.
    _jar.clear()
    _login(base_url, api_key, timeout)
    try:
        return _get_stats(base_url, scope, timeout)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise RuntimeError(f"{scope}: stats failed after re-login: HTTP {exc.code}") from None


def collect(base_url, api_key, fetcher=fetch):
    start = time.monotonic()
    stats, up = {}, True
    for scope in SCOPES:
        try:
            stats[scope] = fetcher(base_url, api_key, scope)
        except Exception as exc:  # any failure means "engine not answering"
            up = False
            print(f"omlx-exporter: {scope}: {exc}", file=sys.stderr)
    return render(up, stats, time.monotonic() - start)


def make_server(host, port, produce):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/metrics":
                self.send_error(404)
                return
            body = produce().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def make_producer(base_url, api_key_file):
    def produce():
        try:
            with open(api_key_file) as handle:
                key = handle.read().strip()
        except (OSError, ValueError) as exc:
            print(f"omlx-exporter: key file: {type(exc).__name__}", file=sys.stderr)
            return render(False, {}, 0.0)
        return collect(base_url, key)

    return produce


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=9101)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key-file", required=True)
    args = parser.parse_args(argv)

    make_server(args.listen_host, args.listen_port, make_producer(args.base_url, args.api_key_file)).serve_forever()


if __name__ == "__main__":
    main()
