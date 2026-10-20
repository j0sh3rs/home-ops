"""Replay captured requests against an OpenAI-compatible endpoint.

Always streams (with usage) so TTFT and decode speed are measurable, then
folds the stream back into one Output. Tool calls are recorded, never
executed.

  python3 replay.py --corpus corpus/<snapshot> --consumer hindsight \
      --base-url http://mac:8000/v1 --model qwen3.6-35b-a3b \
      --concurrency 5 --limit 200 --out results/hindsight-qwen35.jsonl
"""

import argparse
import copy
import http.client
import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import ha
from corpus import assemble_sse_checked, load_records, production_output, record_id, sample


def prepare(request, model, extra=None):
    body = copy.deepcopy(request)
    body.update(copy.deepcopy(extra or {}))
    body["model"] = model
    body["stream"] = True
    body["stream_options"] = {"include_usage": True}
    return body


def _is_token(line):
    if not line.startswith("data:"):
        return False
    try:
        event = json.loads(line[5:])
    except ValueError:
        return False
    if not isinstance(event, dict):
        return False
    for choice in event.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            continue
        if (delta.get("content") or delta.get("reasoning_content")
                or delta.get("reasoning") or delta.get("tool_calls")):
            return True
    return False


def replay_one(base_url, api_key, body, timeout=900):
    url = urllib.parse.urlsplit(base_url.rstrip("/") + "/chat/completions")
    conn_cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(url.hostname, url.port, timeout=timeout)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    started = time.monotonic()
    elapsed = lambda: round((time.monotonic() - started) * 1000)  # noqa: E731
    ttft_ms = None
    lines = []
    try:
        conn.request("POST", url.path, body=json.dumps(body), headers=headers)
        resp = conn.getresponse()
        if resp.status != 200:
            detail = resp.read(500).decode("utf-8", "replace")
            return {"error": f"HTTP {resp.status}: {detail}", "ttft_ms": None,
                    "latency_ms": elapsed(), "output": None}
        for raw in resp:
            line = raw.decode("utf-8", "replace")
            if ttft_ms is None and _is_token(line):
                ttft_ms = elapsed()
            lines.append(line)
    except (OSError, http.client.HTTPException) as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "ttft_ms": ttft_ms,
                "latency_ms": elapsed(), "output": None}
    finally:
        conn.close()
    try:
        output, stream_error = assemble_sse_checked("".join(lines))
    except Exception as exc:  # any parse failure is this row's error, never the run's
        return {"error": f"unparseable stream: {type(exc).__name__}: {exc}", "ttft_ms": ttft_ms,
                "latency_ms": elapsed(), "output": None}
    return {"error": stream_error, "ttft_ms": ttft_ms, "latency_ms": elapsed(), "output": output}


def _jobs(args):
    """(id, original_request, production_output_or_None, body_to_send)."""
    records = load_records(args.corpus, args.consumer)
    if args.ha_intents:
        template = ha.pick_template(records)
        for intent in ha.load_intents(args.ha_intents):
            body = ha.build_request(template, intent["utterance"])
            yield intent["id"], body, None, prepare(body, args.model, args.extra_body)
        return
    for rec in sample(records, args.limit, args.seed):
        yield record_id(rec["request"]), rec["request"], production_output(rec), prepare(rec["request"], args.model, args.extra_body)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corpus", required=True, help="capture root (contains <consumer>/*.jsonl)")
    p.add_argument("--consumer", required=True)
    p.add_argument("--base-url", required=True, help="OpenAI-compatible base, ending in /v1")
    p.add_argument("--model", required=True)
    p.add_argument("--api-key-env", default="EVAL_API_KEY", help="env var holding the bearer key")
    p.add_argument("--ha-intents", help="replay this intent set instead of the corpus (consumer ha)")
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--timeout", type=float, default=900)
    p.add_argument("--extra-body", type=json.loads, default=None,
                   help='JSON object merged into every request, e.g. \'{"chat_template_kwargs":{"enable_thinking":false}}\'')
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    api_key = os.environ.get(args.api_key_env)
    jobs = list(_jobs(args))

    def run(job):
        job_id, request, production, body = job
        return {"id": job_id, "consumer": args.consumer, "model": args.model, "request": request,
                "production": production,
                "candidate": replay_one(args.base_url, api_key, body, args.timeout)}

    errors = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool, \
            open(args.out, "w", encoding="utf-8") as out:
        for row in pool.map(run, jobs):
            errors += row["candidate"]["error"] is not None
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"replayed {len(jobs)} ({errors} errors) -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
