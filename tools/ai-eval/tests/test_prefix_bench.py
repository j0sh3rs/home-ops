import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import prefix_bench

CHUNKS = [
    'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
    'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
    'data: {"choices":[],"usage":{"prompt_tokens":%d,"completion_tokens":4}}\n\n',
    "data: [DONE]\n\n",
]


class Fake(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append(body)
        words = sum(len(m["content"].split()) for m in body["messages"])
        payload = "".join(CHUNKS).replace("%d", str(words)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def server():
    Fake.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_build_prompt_is_deterministic_per_nonce_and_sized():
    a = prefix_bench.build_prefix(1000, "n1")
    assert a == prefix_bench.build_prefix(1000, "n1")
    assert a != prefix_bench.build_prefix(1000, "n2")
    assert len(a.split()) == 1001  # nonce tag + 1000 words
    assert prefix_bench.build_prefix(0, "n1") == ""


def test_body_has_no_system_message_at_zero_prefix():
    b = prefix_bench.build_body("m", "", 64)
    assert [m["role"] for m in b["messages"]] == ["user"]
    assert b["stream"] is True and b["stream_options"] == {"include_usage": True}
    assert b["max_tokens"] == 64 and b["temperature"] == 0


def test_cold_then_warm_resends_identical_bodies(server, tmp_path):
    out = tmp_path / "r.jsonl"
    prefix_bench.main(["--base-url", server, "--model", "m", "--prefix-tokens", "0,100",
                       "--concurrency", "1,2", "--max-tokens", "8", "--label", "t", "--out", str(out)])
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    # (1 + 2) requests per prefix per phase, 2 prefixes, 2 phases
    assert len(rows) == 12
    assert {r["phase"] for r in rows} == {"cold", "warm"}
    assert all(r["error"] is None and r["completion_tokens"] == 4 for r in rows)
    assert all(r["label"] == "t" for r in rows)
    sent = [json.dumps(b, sort_keys=True) for b in Fake.seen]
    # warm bodies repeat cold ones; prefixed cold bodies are distinct (3 at
    # prefix 100), and the no-prefix body is the same every time (1)
    assert len(set(sent)) == 4


def test_distinct_nonces_across_concurrent_cold_requests(server, tmp_path):
    prefix_bench.main(["--base-url", server, "--model", "m", "--prefix-tokens", "100",
                       "--concurrency", "3", "--max-tokens", "8", "--label", "t",
                       "--out", str(tmp_path / "r.jsonl")])
    systems = [b["messages"][0]["content"] for b in Fake.seen[:3]]
    assert len(set(systems)) == 3
