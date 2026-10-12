import http.client
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import tap

SSE = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'


class FakeUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body.get("stream"):
            payload, ctype = SSE, "text/event-stream"
        else:
            seen = {
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "accept_encoding": self.headers.get("Accept-Encoding"),
            }
            payload, ctype = json.dumps({"seen": seen}).encode(), "application/json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def upstream():
    server = serve(FakeUpstream)
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def make_tap(tmp_path):
    servers = []

    def _make(routes, data_dir=None):
        recorder = tap.Recorder(str(data_dir or tmp_path))
        server = serve(tap.make_handler(tap.parse_routes(routes), recorder, timeout=5))
        servers.append(server)
        return server.server_address[1]

    yield _make
    for server in servers:
        server.shutdown()


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(body) if body is not None else None
    conn.request(method, path, body=payload, headers={"Content-Type": "application/json", **(headers or {})})
    resp = conn.getresponse()
    return resp.status, resp.getheader("Content-Type"), resp.read()


def records(root):
    return [
        json.loads(line)
        for path in sorted(Path(root).rglob("*.jsonl"))
        for line in path.read_text().splitlines()
    ]


def test_parse_routes():
    routes = tap.parse_routes("ha=http://omniroute:20128, hindsight=http://llama-swap:8080/base")
    assert sorted(routes) == ["ha", "hindsight"]
    assert routes["hindsight"].hostname == "llama-swap"
    assert routes["hindsight"].path == "/base"
    for bad in ["", "nourl", "x=ftp://h", "=http://h"]:
        with pytest.raises(ValueError):
            tap.parse_routes(bad)


def test_split_path():
    assert tap.split_path("/ha/v1/chat/completions?x=1") == ("ha", "/v1/chat/completions?x=1")
    assert tap.split_path("/ha") == ("ha", "/")


def test_json_exchange_forwarded_and_recorded(upstream, make_tap, tmp_path):
    port = make_tap(f"hindsight={upstream}")
    status, _, raw = request(
        port, "POST", "/hindsight/v1/chat/completions", {"model": "reasoner"},
        {"Authorization": "Bearer sk-secret"},
    )
    assert status == 200
    seen = json.loads(raw)["seen"]
    assert seen == {
        "path": "/v1/chat/completions",
        "auth": "Bearer sk-secret",
        "accept_encoding": "identity",
    }
    [rec] = records(tmp_path)
    assert set(rec) == {
        "ts", "consumer", "path", "status", "latency_ms", "first_byte_ms",
        "stream", "request", "response", "error",
    }
    assert rec["consumer"] == "hindsight"
    assert rec["path"] == "/v1/chat/completions"
    assert rec["status"] == 200
    assert rec["stream"] is False
    assert rec["request"] == {"model": "reasoner"}
    assert rec["response"]["seen"]["path"] == "/v1/chat/completions"
    assert rec["error"] is None
    assert (tmp_path / "hindsight").is_dir()


def test_accept_encoding_stripped_so_recorded_bodies_stay_plain(upstream, make_tap, tmp_path):
    port = make_tap(f"ha={upstream}")
    status, _, raw = request(
        port, "POST", "/ha/v1/chat/completions", {"model": "m"},
        {"Accept-Encoding": "gzip"},
    )
    assert status == 200
    # http.client supplies "identity" when no Accept-Encoding is forwarded;
    # the client's "gzip" must never reach the upstream.
    assert json.loads(raw)["seen"]["accept_encoding"] == "identity"
    [rec] = records(tmp_path)
    assert rec["response"]["seen"]["accept_encoding"] == "identity"


def test_route_base_path_is_prefixed(upstream, make_tap):
    port = make_tap(f"x={upstream}/base")
    _, _, raw = request(port, "POST", "/x/v1/chat/completions", {"model": "m"})
    assert json.loads(raw)["seen"]["path"] == "/base/v1/chat/completions"


def test_sse_passes_through_unchanged(upstream, make_tap, tmp_path):
    port = make_tap(f"ha={upstream}")
    status, ctype, raw = request(port, "POST", "/ha/v1/chat/completions", {"stream": True})
    assert status == 200
    assert ctype == "text/event-stream"
    assert raw == SSE
    [rec] = records(tmp_path)
    assert rec["stream"] is True
    assert rec["response"] == SSE.decode()
    assert rec["first_byte_ms"] is not None


def test_unknown_consumer_is_404_and_not_recorded(upstream, make_tap, tmp_path):
    port = make_tap(f"ha={upstream}")
    status, _, _ = request(port, "POST", "/nope/v1/chat/completions", {"model": "m"})
    assert status == 404
    assert records(tmp_path) == []


def test_upstream_down_is_502_and_recorded(make_tap, tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()
    port = make_tap(f"ha=http://127.0.0.1:{dead_port}")
    status, _, _ = request(port, "POST", "/ha/v1/chat/completions", {"model": "m"})
    assert status == 502
    [rec] = records(tmp_path)
    assert rec["status"] == 502
    assert rec["error"]


def test_record_failure_does_not_break_proxy(upstream, make_tap, tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")
    port = make_tap(f"ha={upstream}", data_dir=blocker)
    status, _, _ = request(port, "POST", "/ha/v1/chat/completions", {"model": "m"})
    assert status == 200


def test_healthz(make_tap):
    port = make_tap("ha=http://127.0.0.1:1")
    status, _, raw = request(port, "GET", "/healthz")
    assert (status, raw) == (200, b"ok")
