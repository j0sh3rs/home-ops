"""Load ai-tap capture files and normalise responses to one Output shape.

Output = {"message": {...assistant message...}, "finish_reason": str|None, "usage": dict|None}
"""

import hashlib
import json
import random
from pathlib import Path


def load_records(root, consumer=None):
    """Successful chat-completion records under root (optionally one consumer), oldest file first."""
    pattern = f"{consumer}/*.jsonl" if consumer else "*/*.jsonl"
    out = []
    for path in sorted(Path(root).glob(pattern), key=lambda p: (p.name, p.parent.name)):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if (rec.get("status") == 200
                    and str(rec.get("path", "")).split("?")[0].endswith("/chat/completions")
                    and isinstance(rec.get("request"), dict)):
                out.append(rec)
    return out


def record_id(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]


def assemble_sse_checked(text):
    """Fold an OpenAI chat-completion SSE body into (Output, error).

    error is None for a clean stream, else a string: a malformed or non-object `data:` line, a
    mid-stream error event, or a stream that ended with neither finish_reason nor [DONE]
    (truncated). Whatever could be parsed is still returned in the Output.
    """
    content, reasoning, calls = [], [], {}
    finish, usage, errors, done = None, None, [], False
    last_unindexed = None
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data:
            continue
        if data == "[DONE]":
            done = True
            continue
        try:
            event = json.loads(data)
        except ValueError:
            errors.append(f"malformed SSE data line: {data[:80]!r}")
            continue
        if not isinstance(event, dict):
            errors.append(f"malformed SSE data line (not an object): {data[:80]!r}")
            continue
        if event.get("error"):
            errors.append(f"stream error event: {json.dumps(event['error'])[:200]}")
        usage = event.get("usage") or usage
        for choice in event.get("choices") or []:
            if not isinstance(choice, dict):
                errors.append(f"malformed SSE choice: {str(choice)[:80]!r}")
                continue
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                errors.append("malformed SSE delta")
                continue
            if delta.get("content"):
                content.append(delta["content"])
            thought = delta.get("reasoning_content") or delta.get("reasoning")
            if thought:
                reasoning.append(thought)
            for tc in delta.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    errors.append("malformed SSE tool_call")
                    continue
                key = tc.get("index")
                if key is None:
                    # No index: continue the last unindexed call unless this chunk names a different id.
                    cur = calls.get(last_unindexed)
                    if cur is None or (tc.get("id") and cur["id"] and tc["id"] != cur["id"]):
                        last_unindexed = key = ("noindex", len(calls))
                    else:
                        key = last_unindexed
                slot = calls.setdefault(key, {
                    "id": None, "type": "function", "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                slot["function"]["name"] += fn.get("name") or ""
                slot["function"]["arguments"] += fn.get("arguments") or ""
            finish = choice.get("finish_reason") or finish
    if finish is None and not done and not errors:
        errors.append("truncated stream: no finish_reason and no [DONE]")
    message = {"role": "assistant", "content": "".join(content) or None}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if calls:
        message["tool_calls"] = list(calls.values())
    return ({"message": message, "finish_reason": finish, "usage": usage},
            "; ".join(errors) or None)


def assemble_sse(text):
    """Output only; use assemble_sse_checked to also get the stream error."""
    return assemble_sse_checked(text)[0]


def production_output(record):
    """The recorded upstream answer as an Output.

    A record the tap flagged with an error (client disconnect, upstream drop) or whose stream is
    malformed/truncated holds a partial answer: return an empty Output so the request is still
    replayed but has no grading reference.
    """
    empty = {"message": {}, "finish_reason": None, "usage": None}
    if record.get("error"):
        return empty
    if record.get("stream"):
        out, err = assemble_sse_checked(record.get("response") or "")
        return empty if err else out
    resp = record.get("response")
    if not isinstance(resp, dict):
        return empty
    choice = (resp.get("choices") or [{}])[0]
    return {"message": choice.get("message") or {}, "finish_reason": choice.get("finish_reason"),
            "usage": resp.get("usage")}


def sample(records, n, seed=0):
    """Deterministic sample of up to n records, deduplicated by request."""
    unique = {record_id(r["request"]): r for r in records}
    keys = sorted(unique)
    random.Random(seed).shuffle(keys)
    return [unique[k] for k in keys[:n]]
