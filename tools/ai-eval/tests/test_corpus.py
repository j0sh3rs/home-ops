import json

import corpus

SSE = "\n".join([
    'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}',
    'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}',
    'data: {"choices":[{"delta":{"content":"Hel"}}]}',
    'data: {"choices":[{"delta":{"content":"lo"}}]}',
    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"Hass","arguments":"{\\"na"}}]}}]}',
    'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"me\\":\\"x\\"}"}}]},"finish_reason":"tool_calls"}]}',
    'data: {"choices":[],"usage":{"completion_tokens":7}}',
    "data: [DONE]",
])


def rec(**over):
    base = {"status": 200, "path": "/v1/chat/completions", "stream": False,
            "request": {"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            "response": {"choices": [{"message": {"role": "assistant", "content": "ok"},
                                      "finish_reason": "stop"}], "usage": {"completion_tokens": 1}}}
    base.update(over)
    return base


def write(root, consumer, day, records):
    d = root / consumer
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{day}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records) + "not json\n")


def test_load_records_filters_and_orders(tmp_path):
    write(tmp_path, "ha", "2026-10-12", [rec(request={"model": "b", "messages": []})])
    write(tmp_path, "ha", "2026-10-11", [
        rec(request={"model": "a", "messages": []}),
        rec(status=502),
        rec(path="/v1/embeddings"),
        rec(request="not a dict"),
    ])
    write(tmp_path, "atuin", "2026-10-11", [rec()])
    assert [r["request"]["model"] for r in corpus.load_records(tmp_path, "ha")] == ["a", "b"]
    assert len(corpus.load_records(tmp_path)) == 3


def test_assemble_sse():
    out = corpus.assemble_sse(SSE)
    assert out["message"]["content"] == "Hello"
    assert out["message"]["reasoning_content"] == "think"
    assert out["message"]["tool_calls"] == [
        {"id": "c1", "type": "function", "function": {"name": "Hass", "arguments": '{"name":"x"}'}}
    ]
    assert out["finish_reason"] == "tool_calls"
    assert out["usage"] == {"completion_tokens": 7}


def test_production_output_json_and_stream():
    assert corpus.production_output(rec())["message"]["content"] == "ok"
    assert corpus.production_output(rec(stream=True, response=SSE))["message"]["content"] == "Hello"
    assert corpus.production_output(rec(response="garbage"))["message"] == {}


def test_record_id_is_stable_and_order_insensitive():
    assert corpus.record_id({"a": 1, "b": 2}) == corpus.record_id({"b": 2, "a": 1})
    assert len(corpus.record_id({"a": 1})) == 16


def test_sample_dedupes_and_is_deterministic():
    records = [rec(request={"model": "m", "n": i % 5}) for i in range(20)]
    first = corpus.sample(records, 3, seed=1)
    assert len(first) == 3
    assert len({corpus.record_id(r["request"]) for r in first}) == 3
    assert first == corpus.sample(records, 3, seed=1)
    assert len(corpus.sample(records, 100)) == 5
