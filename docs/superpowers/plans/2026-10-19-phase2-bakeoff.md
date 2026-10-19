# Phase 2: Engine and Model Bake-off, plus Gateway Evaluation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure which engine and which models the Mac Studio should serve per role, and separately decide whether Omniroute stays as the gateway or is replaced. The output is evidence in `docs/ai-history/mac-studio.md`, not a cutover.

**Architecture:** The bake-off runs **on the Mac against `127.0.0.1`**, using the existing `tools/ai-eval` harness and a corpus snapshot copied to the Mac. That way engines are measured without a network hop, and no engine has to be exposed while it's on trial. A new `prefix_bench.py` covers the spec's synthetic metrics (TTFT at 0/8K/32K prefixes, cold and cache-hit, decode tok/s at c=1/c=5) without depending on vllm. The gateway is scored on a separate track against the spec's Phase 4 requirements. That track is also where "how does the cluster reach LM Studio or any other engine" gets answered, because whatever fronts the engines in production *is* the gateway (or the D10 front door).

**Tech Stack:** Python 3 stdlib plus `jsonschema`/`pyyaml` (harness); `uv`/`nix shell` on the Mac for throwaway engine installs; oMLX v0.7.0 (nix, :8000); LM Studio (Bionic GUI today, llmster headless as a candidate); Splash; vllm-metal.

**Spec:** `docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md`, sections "Model selection and bake-off", "Phase 4 — Gateway replacement", D9 and D10.

## Global Constraints

- One engine at a time on an idle Mac (spec). Quit Bionic and leave oMLX with nothing loaded while another engine is under test.
- Reference models for the engine bake-off: Qwen3.6-35B-A3B and Qwen3.8-27B, at the **same quantisation on every engine** (MLX 4-bit; GGUF Q4_K_M only where an engine can't load MLX, recorded as such).
- Metrics (spec): decode tok/s at c=1 and c=5; TTFT at 0/8K/32K prefix, cold and cache-hit; peak memory; cold-load time; 1-hour soak with zero errors.
- Engine decision rule (spec): pick the simplest engine within ~15% of the best on the weighted metrics. A specialty engine goes behind the front door only at ≥1.5× on a lane that matters.
- Model fit rule (spec): resident set plus KV for 5 concurrent requests at realistic context ≤ ~80GB.
- Consumer gate (spec): a consumer cuts over only if its candidate meets or beats today's production result for that consumer. HA is out of scope (operator, 2026-10-19): the current HA setup is being torn down and rebuilt (#764), so it has no gate here.
- Gateway requirements (spec Phase 4): no request cap below 600s; routes in git; a key per consumer with usage attribution; Prometheus metrics; routing by model name to multiple upstreams; no subscription or web-UI scraping. LiteLLM stays excluded.
- Corpus, `results/` and raw prompts are never committed. They stay in HolyClaude `/workspace` or on the Mac. Only aggregate tables go to `docs/ai-history/mac-studio.md`.
- Mac `sudo` and anything that edits `/opt/ai` as another user are operator gates. Live Omniroute mutations are operator gates. Bake-off installs live in `~/bakeoff` on the Mac. **Never use `brew install`**: nix-darwin's homebrew module runs `cleanup = "zap"`.
- Don't touch `/workspace/home-ops`. Work in `/workspace/home-ops-mac-spec`.
- Commits explain *why* and end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Rulings (made while writing; revisit only on evidence)

- **R1 — No front proxy for the bake-off.** LM Studio listening only on `127.0.0.1:1235` doesn't block the bake-off: every engine is measured from the Mac itself. A Caddy or Traefik front just for LM Studio would be throwaway, because production exposure is decided in Task 6. Cost if wrong: the cluster→Mac hop goes unmeasured until Task 6's PoC, which adds one RTT on the LAN (sub-millisecond, negligible next to TTFT).
- **R2 — Bionic isn't a production candidate as-is.** What's running is `Bionic.app`, an Electron GUI that only serves while someone is logged in, which conflicts with D6 (every service is a boot-start LaunchDaemon). It's measured because it carries LM Studio's MLX runtime and Splash. If LM Studio wins, production runs **llmster** (headless `lms daemon up` / `lms server start --bind`) under launchd, and that gets one confirming run.
- **R3 — The Claude path is decoupled from the Omniroute verdict.** The explicit Claude path HolyClaude uses comes from the `cliproxyapi` sidecar, not from Omniroute's routing. Any replacement gateway can treat cliproxyapi as one more upstream (`claude-*` model names only). That keeps the documented HolyClaude-only subscription exception (rejected-decisions.md) without Omniroute. So "drop Omniroute" never means "lose Claude".
- **R4 — Phase 0a's baseline never ran.** `docs/ai-history/mac-studio.md` doesn't exist and `results/` was empty on 2026-10-19. Task 1 runs it first: every gate compares against it.
- **R5 — Withdrawn (2026-10-19).** It required a GPT-5.5 HA baseline before any Codex or OpenAI removal. HA is being rebuilt from scratch (#764), so there's no baseline to protect. The rebuild picks its agent after this phase.

## File Structure

| File | Responsibility |
|---|---|
| `tools/ai-eval/prefix_bench.py` (create) | Synthetic fixed-prefix TTFT and decode probe, cold vs cache-hit, at a list of concurrencies |
| `tools/ai-eval/tests/test_prefix_bench.py` (create) | Tests against a fake streaming server |
| `tools/ai-eval/memsample.sh` (create) | Samples an engine process's RSS and system memory while a run is in flight (Mac-side) |
| `tools/ai-eval/README.md` (modify) | "Bake-off on the Mac" section: rig sync, `prefix_bench.py`, `memsample.sh` |
| `docs/ai-history/mac-studio.md` (create) | Aggregate baseline, engine and model tables, gateway scorecard, decisions |
| `docs/ai-history/README.md` (modify) | Link mac-studio.md |
| `docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md` (modify, Task 7) | D9/D10/Phase 4 updated per the verdict |

---

### Task 1: Production baselines and corpus gaps

**Files:** Create `docs/ai-history/mac-studio.md`; modify `docs/ai-history/README.md`.

**Interfaces:** Produces the gitignored `tools/ai-eval/results/hindsight-prod.jsonl` plus the committed baseline table. The HA outputs (`results/ha-gpt55.jsonl`, `corpus/ha_intents.yaml`) were dropped with #764.

State on 2026-10-19:
- Only `hindsight` has captures (2026-10-14 to 10-19, 321M).
- atuin is already pointed at the tap (`atuin-ai-server/app/config.toml:10`) but has produced no traffic.
- HA was never repointed, and now won't be: it's being rebuilt (#764).
- argus is disabled (accepted gap, Phase 0a).

- [ ] **Step 1: Snapshot the corpus** (done 2026-10-19 into `tools/ai-eval/corpus/2026-10-19`). Use the README command, run from `tools/ai-eval/`.
- [ ] **Step 2: Hindsight production baseline.** Run from `tools/ai-eval/`:
  ```bash
  python3 replay.py --corpus corpus/2026-10-19 --consumer hindsight --base-url http://llama-swap.ai.svc.cluster.local:8080/v1 --model reasoner --concurrency 5 --limit 200 --seed 1 --timeout 900 --out results/hindsight-prod.jsonl
  python3 grade.py results/hindsight-prod.jsonl --markdown --label "hindsight: gpt-oss-20b (llama-swap, prod)"
  ```
  Expected: `structured_valid_rate` close to 1.0. `fact_recall_mean` is production replayed against itself, so it's the noise ceiling that later candidates are read against.
- [x] **Step 3: dropped** (HA rebuild, #764).
- [x] **Step 4: dropped** (HA rebuild, #764).
- [x] **Step 5: dropped** (HA rebuild, #764).
- [ ] **Step 6: Write `docs/ai-history/mac-studio.md`.** It gets a "Production baselines (2026-10-19)" section containing the grade tables, the capture window, row counts per consumer, and the known gaps (atuin has no traffic, argus is disabled). Link it from `docs/ai-history/README.md`. Before committing, run `git status --porcelain tools/ai-eval` and expect no corpus or results paths.
- [ ] **Step 7: Commit** with the message `docs(ai-history): Phase 2 production baselines for the Mac bake-off`.

### Task 2: `prefix_bench.py` (synthetic TTFT and decode probe)

**Files:** Create `tools/ai-eval/prefix_bench.py` and `tools/ai-eval/tests/test_prefix_bench.py`.

**Interfaces:** Consumes `replay.replay_one(base_url, api_key, body, timeout) -> {"error", "ttft_ms", "latency_ms", "output"}` and `grade.decode_tps(candidate)`. Produces the CLI `prefix_bench.py --base-url --model --prefix-tokens 0,8192,32768 --concurrency 1,5 --max-tokens 256 --label --out`, which writes one JSONL row per request with these keys: `label, prefix_tokens, concurrency, phase ("cold"|"warm"), ttft_ms, latency_ms, prompt_tokens, completion_tokens, decode_tps, error`. It prints a markdown summary table: median TTFT per (prefix, phase, c), the median per-request decode_tps, and the aggregate tok/s at c (the sum over concurrent requests).

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run them and confirm they fail.** Command: `cd tools/ai-eval && python3 -m pytest tests/test_prefix_bench.py -q -p no:cacheprovider`. Expected: `ModuleNotFoundError: No module named 'prefix_bench'`.

- [ ] **Step 3: Implement**

```python
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
```

- [ ] **Step 4: Run the full suite.** Command: `python3 -m pytest tests -q -p no:cacheprovider`. Expected: all pass (44 existing plus 4 new).
- [ ] **Step 5: Add `memsample.sh`**, a Mac-side script that prints one CSV line per second (`epoch,rss_mb,mem_free_pct`) for the PID given as `$1`. Stop it with Ctrl-C. Peak = the maximum `rss_mb`.

```bash
#!/bin/bash
# Usage: ./memsample.sh <pid> > results/mem-<label>.csv   (Mac only)
set -euo pipefail
pid=$1
echo "epoch,rss_mb,mem_free_pct"
while kill -0 "$pid" 2>/dev/null; do
  rss=$(ps -o rss= -p "$pid" | tr -d ' ')
  free=$(memory_pressure | awk -F': ' '/free percentage/ {gsub("%","",$2); print $2}')
  echo "$(date +%s),$((rss / 1024)),$free"
  sleep 1
done
```

  `chmod +x`. RSS undercounts Metal wired memory for some engines, so also record `sudo footprint <pid>`, or the sum from Activity Monitor's "Memory" column, once at the peak if the operator can provide it. `mem_free_pct` is the system-wide cross-check.
- [ ] **Step 6: README.** Add a "Bake-off on the Mac" section documenting `prefix_bench.py`, `memsample.sh`, and the Task 3 rig sync commands.
- [ ] **Step 7: Commit** with the message `feat(ai-eval): prefix_bench for cold/warm TTFT and c=1/c=5 decode without vllm`. The body explains that vllm bench only exists once vllm-metal is installed, and every engine needs the same probe.

### Task 3: Bake-off rig on the Mac

**Interfaces:** Produces `~/bakeoff/ai-eval/` on the Mac (harness code plus the corpus snapshot) and `~/bakeoff/py` (a Python 3.12 venv with `jsonschema` and `pyyaml`). Nothing here is committed.

- [ ] **Step 1: Sync the harness and corpus over SSH.** HolyClaude reaches the Mac as `ssh -F ~/.claude/ssh/config mac-jms-01`.
  ```bash
  ssh -F ~/.claude/ssh/config mac-jms-01 'mkdir -p ~/bakeoff/ai-eval && chmod 700 ~/bakeoff'
  tar -C /workspace/home-ops-mac-spec/tools/ai-eval --exclude=__pycache__ --exclude=results -cf - . | ssh -F ~/.claude/ssh/config mac-jms-01 'tar -C ~/bakeoff/ai-eval -xf -'
  ```
  The corpus is personal data. It stays inside the 700-mode home directory on the FileVault volume (spec-allowed), and is deleted at Phase 3 retention alongside the cluster copy.
- [ ] **Step 2: Python env.** Run `ssh … 'nix shell nixpkgs#uv -c uv venv --python 3.12 ~/bakeoff/py && nix shell nixpkgs#uv -c uv pip install --python ~/bakeoff/py/bin/python -r ~/bakeoff/ai-eval/requirements.txt'`, then run the test suite on the Mac with `~/bakeoff/py/bin/python -m pytest tests -q -p no:cacheprovider`. Expected: all pass.
- [ ] **Step 3: Models.**
  - `lmstudio-community/Qwen3.8-27B-MLX-4bit` is already in `~/.lmstudio/models`. It's the one Bionic serves (operator, 2026-10-19), so 4-bit MLX is the bake-off quantisation. The 8-bit copy is unused.
  - Download `Qwen3.6-35B-A3B` MLX 4-bit into `~/bakeoff/models/`. Verify the repo id with the HF MCP `hub_repo_search` first; prefer `mlx-community` or `lmstudio-community`.
  - oMLX runs as uid 455 and can't read `~`. **Operator gate:** clone both model dirs into `/opt/ai/models.noindex/` with `/bin/cp -cR` (an APFS copy-on-write clone, so no extra disk), then `chown -R _omlx:_omlx`. Hard links won't work: the chown would also change the operator's copy.
  - Record each model dir's size and its HF revision sha in the ledger.
- [ ] **Step 4: Quiet-Mac checklist (record before each engine run).**
  - Bionic is quit, unless it's the engine under test.
  - oMLX shows no loaded models (`/v1/models/status` or the admin API with the main key).
  - `memory_pressure` reports ≥ 90% free.
  - No Time Machine run or Spotlight indexing is in progress.
  - Note: an unknown `bun` listener on `*:18789` was seen on 2026-10-19. It's the operator's OpenClaw gateway (confirmed 2026-10-19). It's outside the pf-filtered port set, so it's LAN-reachable. That's out of scope here, but quit it during runs if it holds a model.

### Task 4: Engine bake-off (4 engines × 2 reference models)

Engines, in this order (simplest and most likely first):
1. **oMLX** v0.7.0 (nix, :8000, main key)
2. **LM Studio**: Bionic's built-in server on :1235 for the measurement, plus a confirming llmster run if it lands within 15% (R2). Install llmster with LM Studio's official headless installer into the user account, never brew.
3. **Splash**: `splash serve` standalone, installed per its docs into `~/bakeoff/splash`
4. **vllm-metal**: uv venv in `~/bakeoff/vllm-metal`, pinned version

Verify each engine's current install command and flags against its upstream docs at run time, and paste the exact commands into the ledger.

For each engine × model, run from `~/bakeoff/ai-eval` on the Mac. Put the engine port in `PORT`, the engine's model id in `M`, a short label in `L`, and the key (if any) in `EVAL_API_KEY`.

- [ ] **Step 1: Cold load.** With the model unloaded, run `time` around the engine's load call (or the first 1-token request) and record the seconds. Start `memsample.sh <engine pid> > results/mem-$L.csv &`.
- [ ] **Step 2: Synthetic probe:**
  ```bash
  ~/bakeoff/py/bin/python prefix_bench.py --base-url http://127.0.0.1:$PORT/v1 --model "$M" --prefix-tokens 0,8192,32768 --concurrency 1,5 --label "$L" --out results/bench-$L.jsonl
  ```
- [ ] **Step 3: Real-traffic replay** (Hindsight is the only corpus with volume), at c=1 and c=5:
  ```bash
  ~/bakeoff/py/bin/python replay.py --corpus corpus/2026-10-19 --consumer hindsight --base-url http://127.0.0.1:$PORT/v1 --model "$M" --concurrency 5 --limit 200 --seed 1 --out results/hindsight-$L-c5.jsonl
  ~/bakeoff/py/bin/python grade.py results/hindsight-$L-c5.jsonl --markdown --label "$L c=5"
  ```
  Repeat with `--concurrency 1 --limit 50`.
- [ ] **Step 4: Soak, finalist engine × model pairs only** (within 15% of the best after Steps 1–3). Loop `replay.py --concurrency 5 --limit 200` with seeds 1, 2, 3, … for 60 minutes and require `error_rate == 0` across all of them. Stop `memsample.sh` and record peak RSS.
- [ ] **Step 5: Unload or stop the engine** and re-run the quiet-Mac checklist before the next one.
- [ ] **Step 6: Scoring.** In `mac-studio.md`, add an "Engine bake-off" table: one row per engine × model with cold-load s, TTFT p50 (0/8K/32K, cold and warm), c=1 and c=5 decode tok/s, aggregate tok/s at c=5, peak memory, structured_valid_rate, error_rate, and soak result.
  - Weights: c=5 aggregate decode 30%, warm-8K TTFT 25%, cold-32K TTFT 15%, structured_valid_rate 20%, ops simplicity 10% (LaunchDaemon-able, nix-installable, pinned, auth, metrics).
  - Apply the 15% / 1.5× rules and write the ruling, plus any specialty-engine lane, in prose under the table.
- [ ] **Step 7: Commit** with the message `docs(ai-history): Phase 2 engine bake-off results and winner`.

### Task 5: Model bake-off on the winning engine

Candidates, re-verified against HF for current MLX builds when the task runs: Qwen3.6-35B-A3B, Qwen3.8-27B, Qwen3-Coder-Next 80B-A3B (~48GB), gpt-oss-120b (~63GB), and gpt-oss-20b as the control.

- [ ] **Step 1: Fit check per model.** Load the model and run `prefix_bench.py --prefix-tokens 32768 --concurrency 5` while `memsample.sh` runs. A model passes the fit rule if peak memory ≤ ~80GB. List which pairs can co-reside (for example 35B-A3B with Coder-Next).
- [ ] **Step 2: Reasoner role (Hindsight).** Run `replay.py` c=5 with `--limit 200 --seed 1` for each candidate, plus the gpt-oss-20b control on the Mac. Grade each; the gate is structured_valid_rate and fact_recall_mean ≥ `hindsight-prod`.
- [x] **Step 3: Chat/fast role (HA): dropped** (HA rebuild, #764). The fresh HA picks its agent from this task's role table.
- [ ] **Step 4: Agent/coder role (atuin, argus).** If the atuin or argus captures are empty by now, record "no corpus; gate deferred to Phase 3 live shadow" and use the Hindsight replay's tool_valid_rate as the only tool-call signal.
- [ ] **Step 5: Role → model table, plus the resident set** in `mac-studio.md`: which models stay loaded, which load on demand, and the total memory budget.
- [ ] **Step 6: Commit** with the message `docs(ai-history): Phase 2 model bake-off and per-role picks`.

### Task 6: Gateway evaluation — does Omniroute stay?

Independent of Tasks 4–5. It can run while engines download. It produces the "Gateway" section in `mac-studio.md` and a keep/replace recommendation.

- [ ] **Step 1: Measure Omniroute against each requirement, using evidence rather than recollection** (read-only probes; no config changes):
  - Request cap: send one Hindsight corpus request whose production latency was > 120s through Omniroute's llama-swap connection, and record whether it is cut at about 120s. Hindsight currently bypasses Omniroute, so this exercises the documented `maxWaitMs` limit.
  - Routes in git: today they are DB-only (combos, connections, keys).
  - Per-consumer keys and attribution: list keys via the MCP `omniroute_cost_report` and check per-key usage.
  - Prometheus: check whether `/metrics` exists on :20128.
  - Model-name routing to multiple upstreams: yes (connections plus combos).
  - Scraping: cliproxyapi uses CLI OAuth and does no web-UI scraping. This is the documented exception, and it's acceptable.
  - Plus the known defects: `/v1/messages` unauthenticated (re-test with a request carrying no key); combo fallback reliability; and the `blockedModels` PATCH stripping.
- [ ] **Step 2: Candidate list.**
  - Verify each candidate against its upstream docs and releases (WebSearch extended plus Context7). Don't rely on memory.
  - Minimum set:
    - (a) **Omniroute as-is**
    - (b) **Envoy AI Gateway**: in-cluster, CRDs in git, model-name routing on the request body
    - (c) **Bifrost**: Go binary, Mac or cluster
    - (d) **llama-swap as the Mac front door**: check whether its current release can proxy to non-spawned upstreams and has API keys; it already has `/metrics`
    - (e) **A thin front door**: Caddy or Traefik with per-consumer bearer keys plus routing by path or model header, only if no consumer needs body-based model routing
    - (f) **Engine-native**: oMLX sub-keys and no gateway, viable only if the winning engine serves every role alone
  - LiteLLM is excluded and isn't listed.
- [ ] **Step 3: Score each candidate** against the six requirements (pass/fail), plus:
  - Where it runs. On the Mac it's one hop and can bind localhost-only engines (which solves the LM Studio/llmster exposure, R1). In-cluster it's GitOps-native, but every request crosses the LAN and the pf allowlist.
  - Whether it can carry the explicit Claude path to cliproxyapi (R3).
  - Ops cost: nix-packaging or Flux-packaging, and pinning.
  - Project health: release cadence, open critical issues.
- [ ] **Step 4: PoC the top non-Omniroute candidate**, only if it beats Omniroute on paper:
  - Run it on the Mac (`~/bakeoff/gw`, user-space) in front of the winning engine and Bionic's :1235.
  - Re-run `prefix_bench.py --prefix-tokens 8192 --concurrency 5` through it and directly; added TTFT must be < 5% (or < 20ms).
  - Run one 600s+ request to prove there's no cap.
  - Use two keys and confirm usage is split per key.
  - Scrape its metrics.
  - Making it reachable from the cluster needs a pf rule plus a launchd unit; that's Phase 3 nix work and isn't done here.
- [ ] **Step 5: Write the recommendation.** It's one of:
  - **keep Omniroute**, listing which limits are accepted and which mitigations (for example, `maxWaitMs` overrides recorded in a repo runbook) apply; the parked `2026-10-19-omniroute-mac-gateway.md` is then revived
  - **replace with X**, located on the Mac or in-cluster, with cliproxyapi kept as a standalone upstream for the Claude path
  - **front door only**

  Include the "Codex/OpenAI removal" consequence: with HA being rebuilt (#764), the Codex lane has no automated consumer now.
- [ ] **Step 6: Commit** with the message `docs(ai-history): Phase 2 gateway evaluation and Omniroute verdict`.

### Task 7: Decisions, spec amendment, hand-off

- [ ] **Step 1: Present the engine, models and gateway verdicts to the operator.** The gateway choice is theirs to approve.
- [ ] **Step 2: Amend the spec** to match: D7 (engine), D9 (Omniroute keep or replace), D10 (front-door location), and Phase 4 (requirements met, or a mini-spec for the chosen gateway). Update `docs/ai-history/rejected-decisions.md` for every candidate that was rejected, with the reason.
- [ ] **Step 3: Update the memory** (`mac_studio_migration_decisions.md`) and its MEMORY.md hook with the verdicts.
- [ ] **Step 4: Commit and open the PR** (stop for the operator before merging). Next step: the Phase 3 cutover plan, which covers per-consumer gates, nixifying the winner and gateway, and bigboi decommission.

## Self-review notes

- Spec coverage:

  | Spec requirement | Covered by |
  |---|---|
  | All 4 engines, both reference models, one at a time | Task 4 |
  | Every performance metric | Task 4 Steps 1–4, plus `prefix_bench` and `memsample` |
  | 5-model shortlist with control | Task 5 |
  | Fit rule | Task 5 Step 1 |
  | Per-role grading | Task 5 Steps 2–4 |
  | Decision rules | Tasks 4.6 and 5 |
  | Results in `docs/ai-history` | Every task |
  | Phase 4 requirements and on-Mac vs in-cluster | Task 6 |

- argus "verdict agreement" is still deferred (argus is disabled), as Phase 0a accepted.
- Engines' Prometheus metrics aren't scored separately: they're part of the "ops simplicity" weight and the gateway's metrics.
