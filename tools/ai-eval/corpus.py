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


def assemble_sse(text):
    """Fold an OpenAI chat-completion SSE body into one Output."""
    content, reasoning, calls = [], [], {}
    finish, usage = None, None
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except ValueError:
            continue
        usage = event.get("usage") or usage
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content.append(delta["content"])
            thought = delta.get("reasoning_content") or delta.get("reasoning")
            if thought:
                reasoning.append(thought)
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(tc.get("index", 0), {
                    "id": None, "type": "function", "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                slot["function"]["name"] += fn.get("name") or ""
                slot["function"]["arguments"] += fn.get("arguments") or ""
            finish = choice.get("finish_reason") or finish
    message = {"role": "assistant", "content": "".join(content) or None}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return {"message": message, "finish_reason": finish, "usage": usage}


def production_output(record):
    """The recorded upstream answer as an Output."""
    if record.get("stream"):
        return assemble_sse(record.get("response") or "")
    resp = record.get("response")
    if not isinstance(resp, dict):
        return {"message": {}, "finish_reason": None, "usage": None}
    choice = (resp.get("choices") or [{}])[0]
    return {"message": choice.get("message") or {}, "finish_reason": choice.get("finish_reason"),
            "usage": resp.get("usage")}


def sample(records, n, seed=0):
    """Deterministic sample of up to n records, deduplicated by request."""
    unique = {record_id(r["request"]): r for r in records}
    keys = sorted(unique)
    random.Random(seed).shuffle(keys)
    return [unique[k] for k in keys[:n]]
