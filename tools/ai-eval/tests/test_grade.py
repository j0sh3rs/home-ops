import json

import grade

SCHEMA_REQ = {"response_format": {"type": "json_schema", "json_schema": {"name": "f", "schema": {
    "type": "object", "required": ["facts"],
    "properties": {"facts": {"type": "array", "items": {"type": "string"}}}}}}}
TOOLS_REQ = {"tools": [{"type": "function", "function": {"name": "run"}}]}


def msg(content=None, calls=None):
    m = {"role": "assistant", "content": content}
    if calls is not None:
        m["tool_calls"] = [{"type": "function", "function": {"name": n, "arguments": a}} for n, a in calls]
    return m


def test_structured_valid():
    assert grade.structured_valid({}, msg("x")) is None
    assert grade.structured_valid(SCHEMA_REQ, msg('{"facts": ["a"]}')) is True
    assert grade.structured_valid(SCHEMA_REQ, msg('{"other": 1}')) is False
    assert grade.structured_valid(SCHEMA_REQ, msg("not json")) is False
    assert grade.structured_valid(SCHEMA_REQ, None) is False
    assert grade.structured_valid({"response_format": {"type": "json_object"}}, msg("{}")) is True


def test_tool_calls_valid():
    assert grade.tool_calls_valid({}, None, msg(calls=[("run", "{}")])) is None
    assert grade.tool_calls_valid(TOOLS_REQ, msg("a"), msg("b")) is None
    assert grade.tool_calls_valid(TOOLS_REQ, msg(calls=[("run", "{}")]), msg("b")) is False
    assert grade.tool_calls_valid(TOOLS_REQ, None, msg(calls=[("run", '{"cmd": "ls"}')])) is True
    assert grade.tool_calls_valid(TOOLS_REQ, None, msg(calls=[("nope", "{}")])) is False
    assert grade.tool_calls_valid(TOOLS_REQ, None, msg(calls=[("run", "{bad")])) is False
    assert grade.tool_calls_valid(TOOLS_REQ, None, msg(calls=[("run", "[1]")])) is False


def test_fact_recall():
    prod = msg(json.dumps({"facts": ["Josh moved the cluster to Talos", "the NAS runs RustFS for S3", "ok"]}))
    cand = msg(json.dumps({"facts": ["Josh moved his cluster to Talos Linux"]}))
    assert grade.fact_recall(prod, cand) == 0.5  # "ok" has <3 words, so 2 facts; 1 matched
    assert grade.fact_recall(prod, msg("garbage")) == 0.0
    assert grade.fact_recall(msg("not json"), cand) is None


def test_decode_tps():
    cand = {"ttft_ms": 1000, "latency_ms": 3000, "output": {"usage": {"completion_tokens": 100}}}
    assert grade.decode_tps(cand) == 50.0
    assert grade.decode_tps({"ttft_ms": None, "latency_ms": 1, "output": None}) is None


def row(consumer, request, production, candidate_msg, error=None, rid="r", ttft=100, lat=1100, toks=10):
    output = None if error else {"message": candidate_msg, "usage": {"completion_tokens": toks}}
    return {"id": rid, "consumer": consumer, "request": request,
            "production": {"message": production} if production is not None else None,
            "candidate": {"error": error, "ttft_ms": ttft, "latency_ms": lat, "output": output}}


def test_summarize_and_markdown():
    rows = [
        row("hindsight", SCHEMA_REQ, msg('{"facts": ["a b c"]}'), msg('{"facts": ["a b c"]}'), rid="1"),
        row("hindsight", SCHEMA_REQ, msg('{"facts": ["a b c"]}'), msg("bad"), rid="2"),
        row("hindsight", SCHEMA_REQ, None, None, error="HTTP 500", rid="3"),
        row("ha", TOOLS_REQ, None, msg(calls=[("run", "{}")]), rid="lamp"),
    ]
    baselines = {"lamp": msg(calls=[("run", "{}")])}
    s = grade.summarize(rows, baselines)
    h = s["hindsight"]
    assert h["n"] == 3
    assert h["error_rate"] == 0.333
    assert h["structured_valid_rate"] == 0.333  # errored row counts as invalid
    assert h["fact_recall_mean"] == 0.5
    assert h["ttft_ms_p50"] == 100
    assert h["decode_tps_median"] == 10.0
    assert s["ha"]["ha_agreement_rate"] == 1.0
    assert s["ha"]["tool_valid_rate"] == 1.0
    md = grade.to_markdown(s, "test run")
    assert md.splitlines()[0] == "### test run"
    assert "| hindsight | 3 |" in md


ARGS_REQ = {"tools": [{"type": "function", "function": {"name": "run", "parameters": {
    "type": "object", "required": ["cmd"], "properties": {"cmd": {"type": "string"}}}}}]}


def test_json_object_must_be_dict():
    req = {"response_format": {"type": "json_object"}}
    assert grade.structured_valid(req, msg("[]")) is False
    assert grade.structured_valid(req, msg("{}")) is True


def test_tool_args_checked_against_parameters():
    assert grade.tool_calls_valid(ARGS_REQ, None, msg(calls=[("run", '{"cmd": "ls"}')])) is True
    assert grade.tool_calls_valid(ARGS_REQ, None, msg(calls=[("run", "{}")])) is False
    assert grade.tool_calls_valid(ARGS_REQ, None, msg(calls=[("run", '{"cmd": 5}')])) is False


def test_silent_empty_counts_as_failure_and_skips_latency():
    rows = [
        row("x", TOOLS_REQ, None, msg("hello"), rid="ok", lat=1100),
        row("x", TOOLS_REQ, None, msg(None), rid="empty", lat=5000),
        row("x", TOOLS_REQ, None, msg("   "), rid="blank", lat=5000),
    ]
    x = grade.summarize(rows)["x"]
    assert x["empty_rate"] == 0.667
    assert x["latency_ms_p95"] == 1100  # empty rows excluded from latency


def test_errored_ha_candidate_disagrees_with_text_baseline():
    rows = [row("ha", TOOLS_REQ, None, None, error="HTTP 500", rid="z")]
    s = grade.summarize(rows, {"z": msg("turn on the lamp")})
    assert s["ha"]["ha_agreement_rate"] == 0.0


def test_empty_ha_candidate_disagrees_with_text_baseline():
    rows = [row("ha", TOOLS_REQ, None, msg(None), rid="z")]
    s = grade.summarize(rows, {"z": msg("turn on the lamp")})
    assert s["ha"]["ha_agreement_rate"] == 0.0


def test_errored_candidate_with_tools_is_invalid_tool_call():
    rows = [row("ha", TOOLS_REQ, None, None, error="HTTP 500", rid="z")]
    assert grade.summarize(rows)["ha"]["tool_valid_rate"] == 0.0
