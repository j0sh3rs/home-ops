"""ai-tap: logging reverse proxy for the Mac Studio eval corpus.

Requests to /<consumer>/<path> go to TAP_ROUTES[<consumer>] + <path>; the
response streams back unchanged. Every POST exchange is appended as one
JSON line to TAP_DATA_DIR/<consumer>/<YYYY-MM-DD>.jsonl. Headers are never
recorded (they carry API keys), and a failed record write never fails the
proxied request.

Spec: docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md
"""

import http.client
import json
import os
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Never forwarded in either direction; the tap sets its own framing.
HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade", "host",
    "content-length",
})


def parse_routes(spec):
    """'ha=http://omniroute:20128,hindsight=http://llama-swap:8080' -> {name: SplitResult}."""
    routes = {}
    for item in (s.strip() for s in spec.split(",")):
        if not item:
            continue
        name, _, url = item.partition("=")
        target = urllib.parse.urlsplit(url.strip())
        if not name.strip() or target.scheme not in ("http", "https") or not target.hostname:
            raise ValueError(f"bad TAP_ROUTES entry: {item!r}")
        routes[name.strip()] = target
    if not routes:
        raise ValueError("TAP_ROUTES is empty")
    return routes


def split_path(path):
    """'/ha/v1/chat/completions?x=1' -> ('ha', '/v1/chat/completions?x=1')."""
    consumer, _, rest = path.lstrip("/").partition("/")
    return consumer, "/" + rest


def decode_body(raw):
    """Parsed JSON if it parses, else text; None for an empty body."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


class Recorder:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.lock = threading.Lock()

    def write(self, consumer, record):
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        directory = os.path.join(self.data_dir, consumer)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        try:
            os.makedirs(directory, exist_ok=True)
            with self.lock, open(os.path.join(directory, f"{day}.jsonl"), "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as exc:
            print(f"ai-tap: record write failed: {exc}", file=sys.stderr, flush=True)


def make_handler(routes, recorder, timeout):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            if self.path == "/healthz":
                self._reply(200, b"ok")
            else:
                self._proxy()

        def do_POST(self):
            self._proxy()

        def _reply(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _proxy(self):
            consumer, upstream_path = split_path(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            target = routes.get(consumer)
            if target is None:
                self._reply(404, b"unknown consumer\n")
                return
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            conn_cls = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
            conn = conn_cls(target.hostname, target.port, timeout=timeout)
            started = time.monotonic()
            first_byte_ms = None
            status = None
            content_type = ""
            chunks = []
            error = None
            try:
                conn.request(self.command, target.path.rstrip("/") + upstream_path,
                             body=body or None, headers=headers)
                resp = conn.getresponse()
                status = resp.status
                content_type = resp.getheader("Content-Type", "")
                self.send_response(status)
                for key, value in resp.getheaders():
                    if key.lower() not in HOP_BY_HOP:
                        self.send_header(key, value)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while chunk := resp.read1(65536):
                    if first_byte_ms is None:
                        first_byte_ms = round((time.monotonic() - started) * 1000)
                    chunks.append(chunk)
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            except (OSError, http.client.HTTPException) as exc:
                error = f"{type(exc).__name__}: {exc}"
                if status is None:
                    status = 502
                    try:
                        self._reply(502, b"upstream error\n")
                    except OSError:
                        pass
                self.close_connection = True
            finally:
                conn.close()
            if self.command != "POST":
                return
            raw = b"".join(chunks)
            stream = content_type.startswith("text/event-stream")
            recorder.write(consumer, {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "consumer": consumer,
                "path": upstream_path,
                "status": status,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "first_byte_ms": first_byte_ms,
                "stream": stream,
                "request": decode_body(body),
                "response": raw.decode("utf-8", "replace") if stream else decode_body(raw),
                "error": error,
            })

    return Handler


def main():
    routes = parse_routes(os.environ["TAP_ROUTES"])
    recorder = Recorder(os.environ.get("TAP_DATA_DIR", "/data"))
    timeout = float(os.environ.get("TAP_UPSTREAM_TIMEOUT", "900"))
    port = int(os.environ.get("TAP_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(routes, recorder, timeout))
    server.daemon_threads = True
    print(f"ai-tap: listening on :{port}, consumers: {', '.join(sorted(routes))}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
