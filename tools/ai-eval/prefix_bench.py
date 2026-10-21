"""Synthetic TTFT / decode probe for the engine bake-off.

Each (prefix, concurrency) cell sends `c` requests with distinct random
prefixes (cold: nothing cached), then re-sends the identical bodies (warm:
prefix-cache hit if the engine has one). Prefix size is in words of a
fixed vocabulary, roughly one token each; the actual prompt_tokens the
engine reports are recorded.

  python3 prefix_bench.py --base-url http://127.0.0.1:8000/v1 --model qwen3.6-35b-a3b \
      --prefix-tokens 0,8192,32768 --concurrency 1,5 --label "omlx qwen3.6-35b-a3b" \
      --out results/bench-omlx-qwen35.jsonl
"""

import argparse
import json
import os
import random
import statistics
import uuid
from concurrent.futures import ThreadPoolExecutor

from grade import decode_tps
from replay import replay_one

VOCAB = ("the of and to in is was for on that with as by at from his her this which "
         "or had are but not have one were all they an been has more when there can "
         "who out up into time only new some could these two may then do first any "
         "my now such like our over man me even most made after also did many off "
         "before must well back through years where much your way down should because").split()
QUESTION = "Ignore the text above. Write about 200 words on how lighthouses work."


def build_prefix(n_words, nonce):
    if n_words <= 0:
        return ""
    rng = random.Random(nonce)
    return f"[{nonce}] " + " ".join(rng.choice(VOCAB) for _ in range(n_words))


def build_body(model, prefix, max_tokens):
    messages = [{"role": "system", "content": prefix}] if prefix else []
    messages.append({"role": "user", "content": QUESTION})
    return {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
            "stream": True, "stream_options": {"include_usage": True}}


def _row(label, prefix_tokens, concurrency, phase, res):
    usage = (res.get("output") or {}).get("usage") or {}
    tps = decode_tps(res)
    return {"label": label, "prefix_tokens": prefix_tokens, "concurrency": concurrency,
            "phase": phase, "ttft_ms": res["ttft_ms"], "latency_ms": res["latency_ms"],
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "decode_tps": round(tps, 1) if tps else None, "error": res["error"]}


def run_cell(args, key, prefix_tokens, concurrency):
    bodies = [build_body(args.model, build_prefix(prefix_tokens, uuid.uuid4().hex[:12]), args.max_tokens)
              for _ in range(concurrency)]
    rows = []
    for phase in ("cold", "warm"):
        with ThreadPoolExecutor(concurrency) as pool:
            results = list(pool.map(lambda b: replay_one(args.base_url, key, b, args.timeout), bodies))
        rows += [_row(args.label, prefix_tokens, concurrency, phase, r) for r in results]
    return rows


def summarize(rows):
    lines = ["| prefix | c | phase | ttft_ms p50 | decode tok/s p50 | aggregate tok/s | errors |",
             "|---|---|---|---|---|---|---|"]
    cells = {}
    for r in rows:
        cells.setdefault((r["prefix_tokens"], r["concurrency"], r["phase"]), []).append(r)
    for (p, c, ph), rs in sorted(cells.items()):
        ok = [r for r in rs if r["error"] is None]
        ttft = [r["ttft_ms"] for r in ok if r["ttft_ms"] is not None]
        tps = [r["decode_tps"] for r in ok if r["decode_tps"]]
        med = lambda xs: round(statistics.median(xs), 1) if xs else "-"  # noqa: E731
        lines.append(f"| {p} | {c} | {ph} | {med(ttft)} | {med(tps)} | "
                     f"{round(sum(tps), 1) if tps else '-'} | {len(rs) - len(ok)} |")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--api-key-env", default="EVAL_API_KEY")
    p.add_argument("--prefix-tokens", default="0,8192,32768")
    p.add_argument("--concurrency", default="1,5")
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--timeout", type=float, default=900)
    p.add_argument("--label", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    key = os.environ.get(args.api_key_env)
    rows = []
    for prefix_tokens in (int(x) for x in args.prefix_tokens.split(",")):
        for concurrency in (int(x) for x in args.concurrency.split(",")):
            rows += run_cell(args, key, prefix_tokens, concurrency)
    with open(args.out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(summarize(rows))


if __name__ == "__main__":
    main()
