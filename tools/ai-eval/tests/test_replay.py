import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import replay

CHUNKS = [
    'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
    'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n',
    'data: {"choices":[],"usage":{"completion_tokens":1}}\n\n',
    "data: [DONE]\n\n",
]


class Fake(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen = []
    chunks = None  # override per test

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if body["model"] == "broken":
            self.send_response(500)
            self.send_header("Content-Length", "4")
            self.end_headers()
            self.wfile.write(b"boom")
            return
        payload = "".join(Fake.chunks or CHUNKS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def base_url():
    Fake.seen = []
    Fake.chunks = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


def test_prepare_does_not_mutate():
    original = {"model": "reasoner", "stream": False, "messages": []}
    body = replay.prepare(original, "qwen")
    assert body["model"] == "qwen" and body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert original == {"model": "reasoner", "stream": False, "messages": []}


def test_replay_one_success(base_url):
    result = replay.replay_one(base_url, "k", replay.prepare({"messages": []}, "qwen"))
    assert result["error"] is None
    assert result["output"]["message"]["content"] == "ok"
    assert result["output"]["usage"] == {"completion_tokens": 1}
    assert result["ttft_ms"] is not None and result["latency_ms"] >= result["ttft_ms"]
    assert Fake.seen[0]["path"] == "/v1/chat/completions"
    assert Fake.seen[0]["auth"] == "Bearer k"


def test_replay_one_http_error(base_url):
    result = replay.replay_one(base_url, None, replay.prepare({"messages": []}, "broken"))
    assert result["error"].startswith("HTTP 500")
    assert result["output"] is None
    assert Fake.seen[0]["auth"] is None


def write_capture(root, consumer, records):
    d = root / consumer
    d.mkdir(parents=True)
    (d / "2026-10-11.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


def test_cli_corpus_mode(base_url, tmp_path):
    rec = {"status": 200, "path": "/v1/chat/completions", "stream": False,
           "request": {"model": "reasoner", "messages": [{"role": "user", "content": "x"}]},
           "response": {"choices": [{"message": {"role": "assistant", "content": "prod"}}]}}
    write_capture(tmp_path / "corpus", "hindsight", [rec])
    out = tmp_path / "out.jsonl"
    replay.main(["--corpus", str(tmp_path / "corpus"), "--consumer", "hindsight",
                 "--base-url", base_url, "--model", "qwen", "--out", str(out)])
    [row] = [json.loads(line) for line in out.read_text().splitlines()]
    assert row["consumer"] == "hindsight" and row["model"] == "qwen"
    assert row["production"]["message"]["content"] == "prod"
    assert row["candidate"]["output"]["message"]["content"] == "ok"
    assert row["id"] == replay.record_id(rec["request"])


def test_cli_ha_intent_mode(base_url, tmp_path):
    rec = {"status": 200, "path": "/v1/chat/completions", "stream": True, "response": "",
           "request": {"model": "gpt", "tools": [{"function": {"name": "t"}}],
                       "messages": [{"role": "system", "content": "S"}]}}
    write_capture(tmp_path / "corpus", "ha", [rec])
    intents = tmp_path / "intents.yaml"
    intents.write_text("- id: lamp\n  utterance: lamp on\n")
    out = tmp_path / "out.jsonl"
    replay.main(["--corpus", str(tmp_path / "corpus"), "--consumer", "ha",
                 "--ha-intents", str(intents), "--base-url", base_url,
                 "--model", "gpt", "--out", str(out)])
    [row] = [json.loads(line) for line in out.read_text().splitlines()]
    assert row["id"] == "lamp" and row["production"] is None
    assert Fake.seen[0]["body"]["messages"][-1] == {"role": "user", "content": "lamp on"}


@pytest.mark.parametrize("bad", ["data: 1\n\n", "data: [1]\n\n", 'data: {"choices":[1]}\n\n',
                                 "data: {not json\n\n"])
def test_replay_one_malformed_sse_is_row_error(base_url, bad):
    Fake.chunks = [CHUNKS[1], bad, CHUNKS[3]]
    result = replay.replay_one(base_url, None, replay.prepare({"messages": []}, "qwen"))
    assert result["error"] and "malformed" in result["error"]


def test_replay_one_stream_error_event_is_row_error(base_url):
    Fake.chunks = ['data: {"choices":[{"delta":{"content":"{\\"facts\\": ["}}]}\n\n',
                   'data: {"error":{"message":"oom"}}\n\n']
    result = replay.replay_one(base_url, None, replay.prepare({"messages": []}, "qwen"))
    assert result["error"] and "oom" in result["error"]


def test_replay_one_truncated_stream_is_row_error(base_url):
    Fake.chunks = ['data: {"choices":[{"delta":{"content":"par"}}]}\n\n']
    result = replay.replay_one(base_url, None, replay.prepare({"messages": []}, "qwen"))
    assert result["error"] and "truncated" in result["error"]


def test_replay_one_clean_stream_without_done_but_finished_is_ok(base_url):
    Fake.chunks = [CHUNKS[1]]
    assert replay.replay_one(base_url, None, replay.prepare({"messages": []}, "q"))["error"] is None


def test_prepare_merges_extra_body_without_mutating():
    extra = {"chat_template_kwargs": {"enable_thinking": False}, "model": "ignored"}
    body = replay.prepare({"messages": [], "temperature": 0.0}, "qwen", extra)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["model"] == "qwen" and body["temperature"] == 0.0 and body["stream"] is True
    body["chat_template_kwargs"]["enable_thinking"] = True
    assert extra["chat_template_kwargs"]["enable_thinking"] is False


def test_prepare_rewrites_json_object_only_when_asked():
    req = {"messages": [], "response_format": {"type": "json_object"}}
    assert replay.prepare(req, "m")["response_format"] == {"type": "json_object"}
    assert replay.prepare(req, "m", json_object_as="text")["response_format"] == {"type": "text"}
    assert req["response_format"] == {"type": "json_object"}
    schema = {"messages": [], "response_format": {"type": "json_schema", "json_schema": {"name": "x"}}}
    assert replay.prepare(schema, "m", json_object_as="text")["response_format"]["type"] == "json_schema"
