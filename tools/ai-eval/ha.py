"""Scripted HA intent set.

Each intent is replayed with the system prompt and tools of a real captured
HA request, so the model sees the same exposed entities as production.
Agreement compares tool calls with GPT-5.5's baseline run. The replay never
executes tool calls.
"""

import copy
import json
from pathlib import Path

import yaml


def load_intents(path):
    items = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    ids = [item.get("id") for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate intent id")
    for item in items:
        if not item.get("utterance"):
            raise ValueError(f"intent {item.get('id')!r} has no utterance")
    return items


def pick_template(records):
    """Captured HA request that offers tools, with the greatest ts (ISO-8601 string)."""
    candidates = [r for r in records if r["request"].get("tools")]
    if not candidates:
        raise ValueError("no captured HA request with tools")
    return max(candidates, key=lambda r: r.get("ts") or "")["request"]


def build_request(template, utterance):
    body = copy.deepcopy(template)
    system = [m for m in body.get("messages", []) if m.get("role") == "system"]
    body["messages"] = system + [{"role": "user", "content": utterance}]
    return body


def _norm(value):
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def normalise_calls(message):
    """Sorted (name, args) pairs; strings lower-cased and trimmed; unparsable args kept raw."""
    calls = []
    for call in (message or {}).get("tool_calls") or []:
        fn = call.get("function") or {}
        raw = fn.get("arguments")
        if isinstance(raw, (dict, list)):
            args = raw
        else:
            try:
                args = json.loads(raw or "{}")
            except (ValueError, TypeError):
                args = raw
        calls.append((fn.get("name"), _norm(args)))
    return sorted(calls, key=lambda c: json.dumps(c, sort_keys=True))


def agrees(baseline_message, candidate_message):
    if candidate_message is None or baseline_message is None:
        return False
    return normalise_calls(baseline_message) == normalise_calls(candidate_message)
