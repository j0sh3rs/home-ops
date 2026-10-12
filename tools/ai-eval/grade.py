"""Score replay results per consumer (spec: "Model bake-off" grading).

  python3 grade.py results/hindsight-qwen35.jsonl --markdown --label "qwen3.6-35b-a3b on oMLX"
  python3 grade.py results/ha-candidate.jsonl --ha-baseline results/ha-gpt55.jsonl
"""

import argparse
import json
import re
import statistics

from jsonschema import Draft202012Validator

import ha

_WORD = re.compile(r"[a-z0-9]+")
COLUMNS = ["n", "error_rate", "structured_valid_rate", "tool_valid_rate", "fact_recall_mean",
           "ha_agreement_rate", "ttft_ms_p50", "ttft_ms_p95", "latency_ms_p50", "latency_ms_p95",
           "decode_tps_median"]


def _json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def structured_valid(request, message):
    """Whether the answer meets the requested JSON contract; None if none was requested."""
    fmt = request.get("response_format") or {}
    kind = fmt.get("type")
    if kind not in ("json_schema", "json_object"):
        return None
    data = _json((message or {}).get("content"))
    if data is None:
        return False
    if kind == "json_object":
        return True
    schema = (fmt.get("json_schema") or {}).get("schema") or {}
    return next(Draft202012Validator(schema).iter_errors(data), None) is None


def tool_calls_valid(request, production_message, candidate_message):
    """None unless tools are offered and production or candidate called one; then whether every
    candidate call names an offered tool with JSON-object arguments."""
    offered = {(t.get("function") or {}).get("name") for t in request.get("tools") or []}
    if not offered:
        return None
    cand = (candidate_message or {}).get("tool_calls") or []
    prod = (production_message or {}).get("tool_calls") or []
    if not cand and not prod:
        return None
    if not cand:
        return False
    for call in cand:
        fn = call.get("function") or {}
        if fn.get("name") not in offered or not isinstance(_json(fn.get("arguments") or "{}"), dict):
            return False
    return True


def _leaves(node):
    if isinstance(node, str):
        words = set(_WORD.findall(node.lower()))
        if len(words) >= 3:
            yield words
    elif isinstance(node, dict):
        for value in node.values():
            yield from _leaves(value)
    elif isinstance(node, list):
        for value in node:
            yield from _leaves(value)


def fact_recall(production_message, candidate_message, threshold=0.5):
    """Share of production's JSON string leaves (>=3 words) that some candidate leaf matches
    at token Jaccard >= threshold. None when production has no such leaves."""
    prod = _json((production_message or {}).get("content"))
    want = list(_leaves(prod)) if prod is not None else []
    if not want:
        return None
    cand = _json((candidate_message or {}).get("content"))
    have = list(_leaves(cand)) if cand is not None else []
    hits = sum(1 for w in want if any(len(w & h) / len(w | h) >= threshold for h in have))
    return hits / len(want)


def decode_tps(candidate):
    usage = ((candidate or {}).get("output") or {}).get("usage") or {}
    tokens = usage.get("completion_tokens")
    if not tokens or candidate.get("ttft_ms") is None:
        return None
    seconds = (candidate["latency_ms"] - candidate["ttft_ms"]) / 1000
    return tokens / seconds if seconds > 0 else None


def _pct(values, q):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def _rate(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 3) if values else None


def _score(row, baseline):
    cand = row["candidate"]
    msg = (cand.get("output") or {}).get("message")
    prod = (row.get("production") or {}).get("message")
    errored = cand.get("error") is not None
    structured = structured_valid(row["request"], msg)
    return {
        "error": errored,
        "structured_valid": structured,
        "tool_valid": tool_calls_valid(row["request"], prod, msg),
        "fact_recall": fact_recall(prod, msg),
        "ha_agrees": ha.agrees(baseline, msg) if baseline is not None else None,
    }


def summarize(rows, baselines=None):
    groups = {}
    for row in rows:
        groups.setdefault(row["consumer"], []).append(row)
    summary = {}
    for consumer, group in sorted(groups.items()):
        scores = [_score(r, (baselines or {}).get(r["id"])) for r in group]
        ok = [r["candidate"] for r in group if r["candidate"].get("error") is None]
        ttft = [c["ttft_ms"] for c in ok if c.get("ttft_ms") is not None]
        latency = [c["latency_ms"] for c in ok]
        tps = [t for t in (decode_tps(c) for c in ok) if t is not None]
        summary[consumer] = {
            "n": len(group),
            "error_rate": _rate([s["error"] for s in scores]),
            "structured_valid_rate": _rate([s["structured_valid"] for s in scores]),
            "tool_valid_rate": _rate([s["tool_valid"] for s in scores]),
            "fact_recall_mean": _rate([s["fact_recall"] for s in scores]),
            "ha_agreement_rate": _rate([s["ha_agrees"] for s in scores]),
            "ttft_ms_p50": _pct(ttft, 0.5),
            "ttft_ms_p95": _pct(ttft, 0.95),
            "latency_ms_p50": _pct(latency, 0.5),
            "latency_ms_p95": _pct(latency, 0.95),
            "decode_tps_median": round(statistics.median(tps), 1) if tps else None,
        }
    return summary


def to_markdown(summary, label):
    lines = [f"### {label}", "", "| consumer | " + " | ".join(COLUMNS) + " |",
             "|---|" + "---|" * len(COLUMNS)]
    for consumer, metrics in summary.items():
        cells = ["–" if metrics[c] is None else str(metrics[c]) for c in COLUMNS]
        lines.append(f"| {consumer} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("results")
    p.add_argument("--ha-baseline", help="replay.py output of the HA intent set against GPT-5.5")
    p.add_argument("--markdown", action="store_true")
    p.add_argument("--label", default="results")
    args = p.parse_args(argv)
    baselines = None
    if args.ha_baseline:
        baselines = {r["id"]: r["candidate"]["output"]["message"]
                     for r in _read(args.ha_baseline) if r["candidate"].get("error") is None}
    summary = summarize(_read(args.results), baselines)
    print(to_markdown(summary, args.label) if args.markdown else json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
