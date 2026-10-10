# Mac Studio AI Host — Eval Corpus Capture and Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start recording real LLM traffic from Hindsight, atuin, HA and (when re-enabled) argus now, and build the replay and grading harness, so that each consumer has an eval gate ready on the day the Mac Studio arrives.

**Architecture:** `ai-tap` is a small stdlib-only Python reverse proxy in the `ai` namespace. Each consumer's base URL gains a path prefix (`/hindsight/v1`, `/atuin/v1`, `/ha/v1`, `/argus/v1`) that names the consumer and picks the upstream (llama-swap or Omniroute). The tap streams responses through unchanged and appends one JSON line per POST to a PVC. Offline, `tools/ai-eval/` loads those lines and replays them against any OpenAI-compatible endpoint, streaming so it can time them. It then grades each consumer against the recorded production answers, or for HA against a GPT-5.5 baseline run of a scripted intent set.

**Tech Stack:** Python 3.14 stdlib (tap; harness plus `jsonschema` and `pyyaml`), pytest, bjw-s app-template 5.1.0, Flux, `openebs-hostpath`.

**Spec:** `docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md` — Phase 0 items 1–2, the "Model bake-off" section (eval corpus, grading, decision rules).

## Global Constraints

- Eval corpus "contains personal memory content: it stays on-cluster or on the Mac and is never committed."
- "Results go to `docs/ai-history/`; raw prompts never do." Only aggregate numbers are committed.
- Corpus window: "~2 weeks of real request/response pairs for argus, Hindsight, atuin and HA".
- Grading, copied from the spec:
  - Hindsight: schema-valid rate; fact recall vs production outputs.
  - argus: triage verdict agreement on known incidents.
  - atuin and argus: tool-call parse success rate.
  - HA: scripted intent/action set scored against GPT-5.5's answers.
- Every workload consuming a ConfigMap or Secret carries `reloader.stakater.com/auto: "true"` on the controller (repo `CLAUDE.md`).
- New apps use the per-namespace `app-template` OCIRepository, with `chartRef` and no `namespace:`.
- Nothing new may schedule onto `bigboi-jms-01`, which is being decommissioned (spec D2).
- The tap must never record request or response headers, because they carry API keys.
- The harness never executes tool calls. It only records them. This matters for HA, whose agent exposes a `bash` tool. Per the spec, that tool's lock-down is a separate, operator-owned decision, so leave its config untouched.
- Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- Never mutate the operator's checkout at `/workspace/home-ops` (branch `feat/cloudflare-waf-exploit-paths-authentik-allowlist`, uncommitted work). Work in the `/workspace/home-ops-mac-spec` worktree, on a branch cut from `origin/main`.

**Known gap, accepted:** argus has been disabled since 2026-10-05 (`kubernetes/apps/ai/kustomization.yaml`, `# - ./argus/ks.yaml`), so it produces no traffic. This plan repoints argus's config so it is captured once re-enabled, and the tool-call grader covers argus rows if any exist. The "triage verdict agreement on known incidents" metric needs a live argus, so it is deferred to the Phase 3 cutover plan. Re-enabling argus is the operator's call and is out of scope here.

---

## File Structure

| Path | Responsibility |
|---|---|
| `kubernetes/apps/ai/ai-tap/ks.yaml` | Flux Kustomization for the tap |
| `kubernetes/apps/ai/ai-tap/app/kustomization.yaml` | Resources + `ai-tap-code` ConfigMap generator |
| `kubernetes/apps/ai/ai-tap/app/helmrelease.yaml` | app-template release: python image runs `/app/tap.py`, PVC at `/data` |
| `kubernetes/apps/ai/ai-tap/app/tap.py` | The proxy (stdlib only) |
| `kubernetes/apps/ai/ai-tap/app/test_tap.py` | Proxy tests (not referenced by kustomize) |
| `kubernetes/apps/ai/kustomization.yaml` | Add `./ai-tap/ks.yaml` |
| `kubernetes/apps/ai/hindsight/app/helmrelease.yaml` | Base URL → tap |
| `kubernetes/apps/ai/atuin-ai-server/app/config.toml` | Endpoint → tap |
| `kubernetes/apps/ai/argus/app/helmrelease.yaml` | Two `api_base` → tap (dormant until re-enabled) |
| `kubernetes/apps/ai/CLAUDE.md` | Document ai-tap |
| `tools/ai-eval/corpus.py` | Load capture JSONL, fold SSE into one message, sample |
| `tools/ai-eval/replay.py` | Replay against an endpoint, time it, write results JSONL |
| `tools/ai-eval/ha.py` | HA intent set: build requests from a captured template, compare tool calls |
| `tools/ai-eval/grade.py` | Per-consumer metrics → JSON or markdown |
| `tools/ai-eval/requirements.txt` | `jsonschema`, `pyyaml` |
| `tools/ai-eval/README.md` | Operator runbook: pull corpus, replay, grade, `vllm bench serve`, retention |
| `tools/ai-eval/tests/test_*.py` | Harness tests |
| `.gitignore` | `tools/ai-eval/corpus/`, `tools/ai-eval/results/`, `__pycache__/`, `.pytest_cache/` |
| `docs/ai-history/mac-studio.md` | Aggregate baseline results (new) |

**Shared record shapes.** Later tasks rely on these exactly.

Capture record: one JSON line written by `tap.py`.

```json
{"ts": "2026-10-11T14:02:11+00:00", "consumer": "hindsight", "path": "/v1/chat/completions",
 "status": 200, "latency_ms": 8123, "first_byte_ms": 412, "stream": false,
 "request": {"model": "reasoner", "messages": []}, "response": {"choices": []}, "error": null}
```

When `stream` is true, `response` is the raw SSE text.

Output: returned by `corpus.assemble_sse` and `corpus.production_output`.

```json
{"message": {"role": "assistant", "content": "...", "tool_calls": []}, "finish_reason": "stop", "usage": {}}
```

Replay result row: one JSON line written by `replay.py`.

```json
{"id": "3f2a9c...", "consumer": "hindsight", "model": "qwen3.6-35b-a3b",
 "request": {}, "production": {"message": {}}, "candidate":
 {"error": null, "ttft_ms": 210, "latency_ms": 5400, "output": {"message": {}, "finish_reason": "stop", "usage": {}}}}
```

`production` is `null` for HA intent rows.

---

### Task 1: ai-tap proxy

**Files:**
- Create: `kubernetes/apps/ai/ai-tap/app/tap.py`
- Test: `kubernetes/apps/ai/ai-tap/app/test_tap.py`

**Interfaces:**
- Produces: `parse_routes(spec: str) -> dict[str, SplitResult]`, `split_path(path: str) -> tuple[str, str]`, `decode_body(raw: bytes) -> object`, `Recorder(data_dir: str).write(consumer: str, record: dict) -> None`, `make_handler(routes, recorder, timeout: float) -> type[BaseHTTPRequestHandler]`. Also the capture record shape above.
- Environment variables: `TAP_ROUTES` (required, `name=url,...`), `TAP_DATA_DIR` (default `/data`), `TAP_PORT` (default `8080`), `TAP_UPSTREAM_TIMEOUT` (seconds, default `900`).

- [ ] **Step 1: Create the branch**

```bash
cd /workspace/home-ops-mac-spec
git fetch origin
git switch -c feat/ai-eval-corpus-capture origin/main
mkdir -p kubernetes/apps/ai/ai-tap/app
```

- [ ] **Step 2: Write the failing tests**

`kubernetes/apps/ai/ai-tap/app/test_tap.py`:

```python
import http.client
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import tap

SSE = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'


class FakeUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body.get("stream"):
            payload, ctype = SSE, "text/event-stream"
        else:
            seen = {"path": self.path, "auth": self.headers.get("Authorization")}
            payload, ctype = json.dumps({"seen": seen}).encode(), "application/json"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def upstream():
    server = serve(FakeUpstream)
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def make_tap(tmp_path):
    servers = []

    def _make(routes, data_dir=None):
        recorder = tap.Recorder(str(data_dir or tmp_path))
        server = serve(tap.make_handler(tap.parse_routes(routes), recorder, timeout=5))
        servers.append(server)
        return server.server_address[1]

    yield _make
    for server in servers:
        server.shutdown()


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps(body) if body is not None else None
    conn.request(method, path, body=payload, headers={"Content-Type": "application/json", **(headers or {})})
    resp = conn.getresponse()
    return resp.status, resp.getheader("Content-Type"), resp.read()


def records(root):
    return [
        json.loads(line)
        for path in sorted(Path(root).rglob("*.jsonl"))
        for line in path.read_text().splitlines()
    ]


def test_parse_routes():
    routes = tap.parse_routes("ha=http://omniroute:20128, hindsight=http://llama-swap:8080/base")
    assert sorted(routes) == ["ha", "hindsight"]
    assert routes["hindsight"].hostname == "llama-swap"
    assert routes["hindsight"].path == "/base"
    for bad in ["", "nourl", "x=ftp://h", "=http://h"]:
        with pytest.raises(ValueError):
            tap.parse_routes(bad)


def test_split_path():
    assert tap.split_path("/ha/v1/chat/completions?x=1") == ("ha", "/v1/chat/completions?x=1")
    assert tap.split_path("/ha") == ("ha", "/")


def test_json_exchange_forwarded_and_recorded(upstream, make_tap, tmp_path):
    port = make_tap(f"hindsight={upstream}")
    status, _, raw = request(
        port, "POST", "/hindsight/v1/chat/completions", {"model": "reasoner"},
        {"Authorization": "Bearer sk-secret"},
    )
    assert status == 200
    seen = json.loads(raw)["seen"]
    assert seen == {"path": "/v1/chat/completions", "auth": "Bearer sk-secret"}
    [rec] = records(tmp_path)
    assert set(rec) == {
        "ts", "consumer", "path", "status", "latency_ms", "first_byte_ms",
        "stream", "request", "response", "error",
    }
    assert rec["consumer"] == "hindsight"
    assert rec["path"] == "/v1/chat/completions"
    assert rec["status"] == 200
    assert rec["stream"] is False
    assert rec["request"] == {"model": "reasoner"}
    assert rec["response"]["seen"]["path"] == "/v1/chat/completions"
    assert rec["error"] is None
    assert (tmp_path / "hindsight").is_dir()


def test_route_base_path_is_prefixed(upstream, make_tap):
    port = make_tap(f"x={upstream}/base")
    _, _, raw = request(port, "POST", "/x/v1/chat/completions", {"model": "m"})
    assert json.loads(raw)["seen"]["path"] == "/base/v1/chat/completions"


def test_sse_passes_through_unchanged(upstream, make_tap, tmp_path):
    port = make_tap(f"ha={upstream}")
    status, ctype, raw = request(port, "POST", "/ha/v1/chat/completions", {"stream": True})
    assert status == 200
    assert ctype == "text/event-stream"
    assert raw == SSE
    [rec] = records(tmp_path)
    assert rec["stream"] is True
    assert rec["response"] == SSE.decode()
    assert rec["first_byte_ms"] is not None


def test_unknown_consumer_is_404_and_not_recorded(upstream, make_tap, tmp_path):
    port = make_tap(f"ha={upstream}")
    status, _, _ = request(port, "POST", "/nope/v1/chat/completions", {"model": "m"})
    assert status == 404
    assert records(tmp_path) == []


def test_upstream_down_is_502_and_recorded(make_tap, tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()
    port = make_tap(f"ha=http://127.0.0.1:{dead_port}")
    status, _, _ = request(port, "POST", "/ha/v1/chat/completions", {"model": "m"})
    assert status == 502
    [rec] = records(tmp_path)
    assert rec["status"] == 502
    assert rec["error"]


def test_record_failure_does_not_break_proxy(upstream, make_tap, tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")
    port = make_tap(f"ha={upstream}", data_dir=blocker)
    status, _, _ = request(port, "POST", "/ha/v1/chat/completions", {"model": "m"})
    assert status == 200


def test_healthz(make_tap):
    port = make_tap("ha=http://127.0.0.1:1")
    status, _, raw = request(port, "GET", "/healthz")
    assert (status, raw) == (200, b"ok")
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `cd kubernetes/apps/ai/ai-tap/app && python3 -m pytest test_tap.py -q -p no:cacheprovider`

Expected: collection error `ModuleNotFoundError: No module named 'tap'`.

- [ ] **Step 4: Write the implementation**

`kubernetes/apps/ai/ai-tap/app/tap.py`:

```python
"""ai-tap: logging reverse proxy for the Mac Studio eval corpus.

Requests to /<consumer>/<path> go to TAP_ROUTES[<consumer>] + <path>; the
response streams back unchanged. Every POST exchange is appended as one
JSON line to TAP_DATA_DIR/<consumer>/<YYYY-MM-DD>.jsonl. Headers are never
recorded (they carry API keys), and a failed record write never fails the
proxied request.

Spec: docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md
"""

import http.client
import json
import os
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Never forwarded in either direction; the tap sets its own framing.
HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade", "host",
    "content-length",
})


def parse_routes(spec):
    """'ha=http://omniroute:20128,hindsight=http://llama-swap:8080' -> {name: SplitResult}."""
    routes = {}
    for item in (s.strip() for s in spec.split(",")):
        if not item:
            continue
        name, _, url = item.partition("=")
        target = urllib.parse.urlsplit(url.strip())
        if not name.strip() or target.scheme not in ("http", "https") or not target.hostname:
            raise ValueError(f"bad TAP_ROUTES entry: {item!r}")
        routes[name.strip()] = target
    if not routes:
        raise ValueError("TAP_ROUTES is empty")
    return routes


def split_path(path):
    """'/ha/v1/chat/completions?x=1' -> ('ha', '/v1/chat/completions?x=1')."""
    consumer, _, rest = path.lstrip("/").partition("/")
    return consumer, "/" + rest


def decode_body(raw):
    """Parsed JSON if it parses, else text; None for an empty body."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


class Recorder:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.lock = threading.Lock()

    def write(self, consumer, record):
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        directory = os.path.join(self.data_dir, consumer)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        try:
            os.makedirs(directory, exist_ok=True)
            with self.lock, open(os.path.join(directory, f"{day}.jsonl"), "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as exc:
            print(f"ai-tap: record write failed: {exc}", file=sys.stderr, flush=True)


def make_handler(routes, recorder, timeout):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            if self.path == "/healthz":
                self._reply(200, b"ok")
            else:
                self._proxy()

        def do_POST(self):
            self._proxy()

        def _reply(self, status, body):
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _proxy(self):
            consumer, upstream_path = split_path(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            target = routes.get(consumer)
            if target is None:
                self._reply(404, b"unknown consumer\n")
                return
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
            conn_cls = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
            conn = conn_cls(target.hostname, target.port, timeout=timeout)
            started = time.monotonic()
            first_byte_ms = None
            status = None
            content_type = ""
            chunks = []
            error = None
            try:
                conn.request(self.command, target.path.rstrip("/") + upstream_path,
                             body=body or None, headers=headers)
                resp = conn.getresponse()
                status = resp.status
                content_type = resp.getheader("Content-Type", "")
                self.send_response(status)
                for key, value in resp.getheaders():
                    if key.lower() not in HOP_BY_HOP:
                        self.send_header(key, value)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                while chunk := resp.read1(65536):
                    if first_byte_ms is None:
                        first_byte_ms = round((time.monotonic() - started) * 1000)
                    chunks.append(chunk)
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            except (OSError, http.client.HTTPException) as exc:
                error = f"{type(exc).__name__}: {exc}"
                if status is None:
                    status = 502
                    try:
                        self._reply(502, b"upstream error\n")
                    except OSError:
                        pass
                self.close_connection = True
            finally:
                conn.close()
            if self.command != "POST":
                return
            raw = b"".join(chunks)
            stream = content_type.startswith("text/event-stream")
            recorder.write(consumer, {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "consumer": consumer,
                "path": upstream_path,
                "status": status,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "first_byte_ms": first_byte_ms,
                "stream": stream,
                "request": decode_body(body),
                "response": raw.decode("utf-8", "replace") if stream else decode_body(raw),
                "error": error,
            })

    return Handler


def main():
    routes = parse_routes(os.environ["TAP_ROUTES"])
    recorder = Recorder(os.environ.get("TAP_DATA_DIR", "/data"))
    timeout = float(os.environ.get("TAP_UPSTREAM_TIMEOUT", "900"))
    port = int(os.environ.get("TAP_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(routes, recorder, timeout))
    server.daemon_threads = True
    print(f"ai-tap: listening on :{port}, consumers: {', '.join(sorted(routes))}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd kubernetes/apps/ai/ai-tap/app && python3 -m pytest test_tap.py -q -p no:cacheprovider`

Expected: `9 passed`.

- [ ] **Step 6: Commit**

```bash
git add kubernetes/apps/ai/ai-tap/app/tap.py kubernetes/apps/ai/ai-tap/app/test_tap.py
git commit -m "feat(ai): add ai-tap logging proxy for the Mac Studio eval corpus

Records real request/response pairs per consumer so the Mac Studio
model/engine bake-off is graded on our traffic, not public benchmarks.
Stdlib only, streams SSE through unchanged, never records headers.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Deploy ai-tap

**Files:**
- Create: `kubernetes/apps/ai/ai-tap/ks.yaml`
- Create: `kubernetes/apps/ai/ai-tap/app/kustomization.yaml`
- Create: `kubernetes/apps/ai/ai-tap/app/helmrelease.yaml`
- Modify: `kubernetes/apps/ai/kustomization.yaml` (add `./ai-tap/ks.yaml` to `resources:`, alphabetically before `./atuin-ai-server/ks.yaml`)
- Modify: `kubernetes/apps/ai/CLAUDE.md` ("Currently deployed" list)

**Interfaces:**
- Consumes: `tap.py` (Task 1) and its environment variables.
- Produces: Service `ai-tap.ai.svc.cluster.local:8080` with consumer prefixes `/hindsight`, `/atuin`, `/ha`, `/argus`. Captures land in PVC `ai-tap` at `/data/<consumer>/<day>.jsonl`.

- [ ] **Step 1: Resolve the Python image digest**

Run: `crane digest docker.io/library/python:3.14-slim`. If `crane` is missing, use `docker buildx imagetools inspect docker.io/library/python:3.14-slim --format '{{json .Manifest.Digest}}'`.

Expected: one `sha256:...` line. Use it as `<DIGEST>` below. Renovate keeps it current afterwards.

- [ ] **Step 2: Write `ks.yaml`**

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/fluxcd-community/flux2-schemas/main/kustomization-kustomize-v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app ai-tap
  namespace: &namespace ai
spec:
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  interval: 1h
  path: ./kubernetes/apps/ai/ai-tap/app
  prune: true
  retryInterval: 2m
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  targetNamespace: *namespace
  timeout: 10m
  wait: true
```

`wait: true` is deliberate: consumers are repointed at this Service in Task 3, so Flux should report the tap unhealthy instead of silently ready.

- [ ] **Step 3: Write `app/kustomization.yaml`**

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
configMapGenerator:
  - name: ai-tap-code
    files:
      - tap.py
generatorOptions:
  disableNameSuffixHash: true
```

- [ ] **Step 4: Write `app/helmrelease.yaml`**

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json
# ai-tap: logging reverse proxy that records the Mac Studio eval corpus
# (docs/superpowers/plans/2026-10-10-mac-ai-eval-corpus-capture.md).
# Consumers address it as /<consumer>/v1; the prefix picks the upstream in
# TAP_ROUTES and names the capture directory. Captures hold personal memory
# content: they stay on this PVC and are never committed. Delete this app
# and its PVC after the last consumer cuts over to the Mac (Phase 3).
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: &app ai-tap
spec:
  interval: 1h
  timeout: 10m
  chartRef:
    kind: OCIRepository
    name: app-template
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  values:
    controllers:
      ai-tap:
        replicas: 1
        # RWO hostpath PVC: never run two pods against it.
        strategy: Recreate
        annotations:
          reloader.stakater.com/auto: "true"
        containers:
          app:
            image:
              repository: docker.io/library/python
              tag: 3.14-slim@<DIGEST>
            command: ["python3", "/app/tap.py"]
            env:
              PYTHONDONTWRITEBYTECODE: "1"
              PYTHONUNBUFFERED: "1"
              TAP_DATA_DIR: /data
              TAP_PORT: "8080"
              # Above every consumer's own client timeout (Hindsight 600s).
              TAP_UPSTREAM_TIMEOUT: "900"
              TAP_ROUTES: >-
                hindsight=http://llama-swap.ai.svc.cluster.local:8080,
                atuin=http://omniroute.ai.svc.cluster.local:20128,
                ha=http://omniroute.ai.svc.cluster.local:20128,
                argus=http://omniroute.ai.svc.cluster.local:20128
            securityContext:
              allowPrivilegeEscalation: false
              readOnlyRootFilesystem: true
              capabilities: { drop: ["ALL"] }
            resources:
              requests:
                cpu: 10m
                memory: 64Mi
              limits:
                memory: 256Mi
            probes:
              liveness: &probe
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /healthz
                    port: 8080
                  initialDelaySeconds: 5
                  periodSeconds: 30
              readiness: *probe
        pod:
          securityContext:
            runAsUser: 1000
            runAsGroup: 1000
            runAsNonRoot: true
            fsGroup: 1000
          affinity:
            nodeAffinity:
              requiredDuringSchedulingIgnoredDuringExecution:
                nodeSelectorTerms:
                  - matchExpressions:
                      # bigboi is being decommissioned (Mac Studio spec D2).
                      - key: kubernetes.io/hostname
                        operator: NotIn
                        values: ["bigboi-jms-01"]
    service:
      app:
        controller: *app
        ports:
          http:
            primary: true
            port: 8080
    persistence:
      code:
        type: configMap
        name: ai-tap-code
        globalMounts:
          - path: /app
            readOnly: true
      data:
        type: persistentVolumeClaim
        storageClass: openebs-hostpath
        accessMode: ReadWriteOnce
        size: 5Gi
        retain: true
        globalMounts:
          - path: /data
```

- [ ] **Step 5: Wire it into the namespace and docs**

In `kubernetes/apps/ai/kustomization.yaml` `resources:`, add `- ./ai-tap/ks.yaml` directly above `- ./atuin-ai-server/ks.yaml`.

In `kubernetes/apps/ai/CLAUDE.md` "Currently deployed", add this bullet after the `omniroute` bullet:

```markdown
- **ai-tap** (`ai-tap/`): temporary logging proxy recording the Mac Studio eval corpus. Consumers use `http://ai-tap.ai.svc.cluster.local:8080/<consumer>/v1`, where the prefix (`hindsight`, `atuin`, `ha`, `argus`) picks the upstream in `TAP_ROUTES`. Captures (personal data) stay on its PVC and are never committed. Remove after the Phase 3 cutover. Plan: `docs/superpowers/plans/2026-10-10-mac-ai-eval-corpus-capture.md`.
```

- [ ] **Step 6: Validate the render**

Run:

```bash
kustomize build kubernetes/apps/ai/ai-tap/app | grep -E "reloader.stakater|name: ai-tap-code"
flux build kustomization ai-tap --path kubernetes/apps/ai/ai-tap/app --kustomization-file kubernetes/apps/ai/ai-tap/ks.yaml --dry-run >/dev/null && echo OK
```

Expected: the reloader annotation line, the ConfigMap name line, then `OK`. Then dispatch the `flux-manifest-reviewer` and `kubeconform-validator` agents on `kubernetes/apps/ai/ai-tap/` and fix anything they report.

- [ ] **Step 7: Commit**

```bash
git add kubernetes/apps/ai/ai-tap kubernetes/apps/ai/kustomization.yaml kubernetes/apps/ai/CLAUDE.md
git commit -m "feat(ai): deploy ai-tap for eval-corpus capture

Not yet in any consumer's path; Task 3 repoints them. Pinned off
bigboi-jms-01 since that node is being decommissioned.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Repoint consumers through the tap and go live

**Files:**
- Modify: `kubernetes/apps/ai/hindsight/app/helmrelease.yaml:104` (`HINDSIGHT_API_LLM_BASE_URL`)
- Modify: `kubernetes/apps/ai/atuin-ai-server/app/config.toml` (`endpoint`)
- Modify: `kubernetes/apps/ai/argus/app/helmrelease.yaml:150,182` (`api_base`, twice)
- Manual: Home Assistant UI (the HA config entry lives in HA's `.storage`, not in git)

**Interfaces:**
- Consumes: Service from Task 2.
- Produces: live capture files under `/data/{hindsight,atuin,ha}/` on the `ai-tap` pod.

- [ ] **Step 1: Edit the three manifests**

`kubernetes/apps/ai/hindsight/app/helmrelease.yaml`: replace the `HINDSIGHT_API_LLM_BASE_URL` line, and keep the long comment above it:

```yaml
        # Through ai-tap (eval-corpus capture, Mac Studio plan) to the same
        # llama-swap upstream; revert to http://llama-swap.ai.svc.cluster.local:8080/v1
        # if the tap misbehaves.
        HINDSIGHT_API_LLM_BASE_URL: http://ai-tap.ai.svc.cluster.local:8080/hindsight/v1
```

`kubernetes/apps/ai/atuin-ai-server/app/config.toml`: replace the `endpoint` line:

```toml
# Through ai-tap (eval-corpus capture, Mac Studio plan) to the same
# Omniroute upstream; revert to http://omniroute.ai.svc.cluster.local:20128/v1
# if the tap misbehaves.
endpoint = "http://ai-tap.ai.svc.cluster.local:8080/atuin/v1"
```

`kubernetes/apps/ai/argus/app/helmrelease.yaml`: change both `api_base: http://omniroute.ai.svc.cluster.local:20128/v1` lines to:

```yaml
          # Via ai-tap for eval-corpus capture (argus is disabled; dormant until re-enabled).
          api_base: http://ai-tap.ai.svc.cluster.local:8080/argus/v1
```

- [ ] **Step 2: Validate**

Run:

```bash
kustomize build kubernetes/apps/ai/hindsight/app | grep -c "ai-tap.ai.svc"
kustomize build kubernetes/apps/ai/atuin-ai-server/app | grep -c "ai-tap.ai.svc"
kustomize build kubernetes/apps/ai/argus/app | grep -c "ai-tap.ai.svc"
```

Expected: `1`, `1`, `2`. Dispatch `sops-leak-detector` on the staged diff before committing.

- [ ] **Step 3: Commit, push and open the PR**

```bash
git add kubernetes/apps/ai/hindsight/app/helmrelease.yaml kubernetes/apps/ai/atuin-ai-server/app/config.toml kubernetes/apps/ai/argus/app/helmrelease.yaml
git commit -m "feat(ai): route hindsight, atuin and argus through ai-tap

Starts the ~2-week eval-corpus capture the Mac Studio bake-off grades
against. Upstreams are unchanged; revert by restoring the old base URLs.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push -u origin feat/ai-eval-corpus-capture
```

Open the PR. The body summarizes Tasks 1–3, states that captures are never committed, and ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. `gh` auth was broken on 2026-10-10 (401). If it still is, give the operator the compare URL instead. **Stop here until the operator merges.**

- [ ] **Step 4: After merge, reconcile and verify the tap first**

```bash
flux reconcile ks cluster-apps -n flux-system --with-source
flux reconcile ks ai-tap -n ai
kubectl -n ai rollout status deploy/ai-tap --timeout=180s
kubectl -n ai get pod -l app.kubernetes.io/name=ai-tap -o wide
```

Expected: rollout succeeds and the pod's NODE is a `bee-jms-*`. Then reconcile the consumers:

```bash
flux reconcile ks hindsight -n ai
flux reconcile ks atuin-ai-server -n ai
```

- [ ] **Step 5: Verify capture end to end**

Run: `kubectl -n ai exec deploy/hindsight-api -- printenv HINDSIGHT_API_LLM_BASE_URL`. Use whichever Deployment owns the env var; find it with `kubectl -n ai get deploy`.

Expected: `http://ai-tap.ai.svc.cluster.local:8080/hindsight/v1`.

Make one atuin AI request from a shell with Atuin's `[ai]` enabled, then wait for Hindsight's next retain or consolidation. Run:

```bash
kubectl -n ai exec deploy/ai-tap -- sh -c 'ls -R /data && for f in /data/*/*.jsonl; do echo "$f $(wc -l < "$f")"; done'
kubectl -n ai exec deploy/ai-tap -- sh -c 'tail -n1 /data/hindsight/*.jsonl' | python3 -c 'import json,sys; r=json.loads(sys.stdin.readline()); print(r["status"], r["stream"], r["latency_ms"], sorted(r))'
```

Expected:
- `hindsight/` and `atuin/` files with ≥1 line.
- `200`, a stream flag, a latency, and the 10 record keys.
- No key named like `headers` or `authorization`.

Check the error rate has not moved: `kubectl -n ai logs deploy/ai-tap --since=1h | grep -c "record write failed"` → `0`.

- [ ] **Step 6: Repoint Home Assistant (manual, operator)**

In HA go to Settings → Devices & services → Extended OpenAI Conversation → the **"Omniroute (Codex)"** entry → Reconfigure. Change `base_url` from `http://omniroute.ai.svc.cluster.local:20128/v1` to `http://ai-tap.ai.svc.cluster.local:8080/ha/v1`. Leave the API key, model and `functions` untouched. Per the spec, the `bash` tool lock-down is a separate decision.

Then issue one Assist command, for example "what time is it", and confirm `/data/ha/<today>.jsonl` gained a line containing `"tools"` in its request.

Rollback: set `base_url` back to the Omniroute URL.

Record the change and its rollback in `docs/runbooks/home-assistant-mcp.md`. Add one bullet under the config-entry bullet at line 11:

```markdown
  - 2026-10-xx: `base_url` temporarily points at `http://ai-tap.ai.svc.cluster.local:8080/ha/v1` (eval-corpus capture, Mac Studio plan). Same Omniroute upstream. Restore `http://omniroute.ai.svc.cluster.local:20128/v1` when ai-tap is removed.
```

Use the real date. Commit it with message `docs(ha): note temporary ai-tap base_url` and the Co-Authored-By trailer, on a follow-up branch from `origin/main`.

- [ ] **Step 7: Start the clock**

The corpus window is ~2 weeks from this step. Note the start date in the PR or follow-up commit message. Tasks 4–8 proceed in parallel with capture.

---

### Task 4: Corpus loader

**Files:**
- Create: `tools/ai-eval/corpus.py`
- Create: `tools/ai-eval/requirements.txt`
- Test: `tools/ai-eval/tests/test_corpus.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: capture record shape (Task 1).
- Produces:
  - `load_records(root: str | Path, consumer: str | None = None) -> list[dict]`: successful (`status == 200`) chat-completion records whose `request` is a dict, oldest file first.
  - `record_id(request: dict) -> str`: 16 hex chars.
  - `assemble_sse(text: str) -> dict`: the Output shape.
  - `production_output(record: dict) -> dict`: the Output shape.
  - `sample(records: list[dict], n: int, seed: int = 0) -> list[dict]`: deduped by `record_id`, deterministic.

- [ ] **Step 1: Ignore corpus, results and Python caches**

Append to `.gitignore`:

```gitignore
# Mac Studio eval harness: captured prompts are personal data, never commit
tools/ai-eval/corpus/
tools/ai-eval/results/
__pycache__/
.pytest_cache/
```

Create `tools/ai-eval/requirements.txt`:

```text
jsonschema>=4.23,<5
pyyaml>=6,<7
```

Run: `pip install --break-system-packages -r tools/ai-eval/requirements.txt`

- [ ] **Step 2: Write the failing tests**

`tools/ai-eval/tests/test_corpus.py`:

```python
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
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `cd tools/ai-eval && python3 -m pytest tests/test_corpus.py -q -p no:cacheprovider`

Expected: `ModuleNotFoundError: No module named 'corpus'`.

- [ ] **Step 4: Write the implementation**

`tools/ai-eval/corpus.py`:

```python
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
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `cd tools/ai-eval && python3 -m pytest tests/test_corpus.py -q -p no:cacheprovider`

Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore tools/ai-eval/corpus.py tools/ai-eval/requirements.txt tools/ai-eval/tests/test_corpus.py
git commit -m "feat(ai-eval): corpus loader for ai-tap captures

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: HA intent set helpers

**Files:**
- Create: `tools/ai-eval/ha.py`
- Create: `tools/ai-eval/ha_intents.example.yaml`
- Test: `tools/ai-eval/tests/test_ha.py`

**Interfaces:**
- Consumes: capture records (Task 4 `load_records`).
- Produces:
  - `load_intents(path) -> list[dict]`: each item has `id` and `utterance`.
  - `pick_template(records: list[dict]) -> dict`: the newest HA request with `tools`.
  - `build_request(template: dict, utterance: str) -> dict`: system messages plus one user turn.
  - `normalise_calls(message: dict | None) -> list[tuple]`
  - `agrees(baseline_message: dict | None, candidate_message: dict | None) -> bool`

- [ ] **Step 1: Write the failing tests**

`tools/ai-eval/tests/test_ha.py`:

```python
import json

import pytest

import ha


def call(name, args):
    return {"type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def test_load_intents(tmp_path):
    p = tmp_path / "i.yaml"
    p.write_text("- id: a\n  utterance: turn on the lamp\n- id: b\n  utterance: what time is it\n")
    assert [i["id"] for i in ha.load_intents(p)] == ["a", "b"]
    p.write_text("- id: a\n  utterance: x\n- id: a\n  utterance: y\n")
    with pytest.raises(ValueError, match="duplicate"):
        ha.load_intents(p)
    p.write_text("- id: a\n")
    with pytest.raises(ValueError, match="utterance"):
        ha.load_intents(p)


def test_pick_template_and_build_request():
    with_tools = {"model": "gpt", "tools": [{"function": {"name": "execute_services"}}],
                  "messages": [{"role": "system", "content": "S"},
                               {"role": "user", "content": "old"},
                               {"role": "assistant", "content": "older"}]}
    records = [{"request": with_tools}, {"request": {"model": "gpt", "messages": []}}]
    template = ha.pick_template(records)
    assert template is with_tools
    body = ha.build_request(template, "turn on the lamp")
    assert body["messages"] == [{"role": "system", "content": "S"},
                                {"role": "user", "content": "turn on the lamp"}]
    assert body["tools"] == with_tools["tools"]
    assert with_tools["messages"][1]["content"] == "old"  # template not mutated
    with pytest.raises(ValueError):
        ha.pick_template([{"request": {"messages": []}}])


def test_agrees_normalises_case_order_and_whitespace():
    base = {"tool_calls": [call("execute_services", {"entity_id": "Light.Lamp "}), call("b", {})]}
    same = {"tool_calls": [call("b", {}), call("execute_services", {"entity_id": "light.lamp"})]}
    other = {"tool_calls": [call("execute_services", {"entity_id": "light.desk"})]}
    assert ha.agrees(base, same)
    assert not ha.agrees(base, other)
    assert ha.agrees({"content": "It is 3pm"}, {"content": "3 o'clock"})  # both text-only
    assert not ha.agrees({"content": "hi"}, same)
    assert not ha.agrees(base, None)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd tools/ai-eval && python3 -m pytest tests/test_ha.py -q -p no:cacheprovider`

Expected: `ModuleNotFoundError: No module named 'ha'`.

- [ ] **Step 3: Write the implementation**

`tools/ai-eval/ha.py`:

```python
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
    """Newest captured HA request that offers tools."""
    for record in reversed(records):
        if record["request"].get("tools"):
            return record["request"]
    raise ValueError("no captured HA request with tools")


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
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = fn.get("arguments")
        calls.append((fn.get("name"), _norm(args)))
    return sorted(calls, key=lambda c: json.dumps(c, sort_keys=True))


def agrees(baseline_message, candidate_message):
    if candidate_message is None or baseline_message is None:
        return False
    return normalise_calls(baseline_message) == normalise_calls(candidate_message)
```

`tools/ai-eval/ha_intents.example.yaml`. This file is committed. The real set lives in `tools/ai-eval/corpus/ha_intents.yaml`, which is gitignored because it names real devices and rooms.

```yaml
# Scripted HA intents. Copy to corpus/ha_intents.yaml (gitignored) and
# write ~40 real utterances: device control, state questions, multi-step
# requests, chit-chat that must NOT call a tool, and requests that tempt
# the bash tool. The harness records tool calls and never executes them.
- id: lamp-on
  utterance: turn on the living room lamp
- id: time
  utterance: what time is it
- id: thermostat-query
  utterance: what is the thermostat set to
- id: no-tool-chat
  utterance: tell me a one-line joke
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd tools/ai-eval && python3 -m pytest tests/test_ha.py -q -p no:cacheprovider`

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add tools/ai-eval/ha.py tools/ai-eval/ha_intents.example.yaml tools/ai-eval/tests/test_ha.py
git commit -m "feat(ai-eval): HA scripted-intent helpers

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Replay runner

**Files:**
- Create: `tools/ai-eval/replay.py`
- Test: `tools/ai-eval/tests/test_replay.py`

**Interfaces:**
- Consumes:
  - `corpus.load_records`, `corpus.sample`, `corpus.record_id`, `corpus.production_output`, `corpus.assemble_sse` (Task 4).
  - `ha.load_intents`, `ha.pick_template`, `ha.build_request` (Task 5).
- Produces:
  - `prepare(request: dict, model: str) -> dict`
  - `replay_one(base_url: str, api_key: str | None, body: dict, timeout: float = 900) -> dict`, returning `{"error", "ttft_ms", "latency_ms", "output"}`.
  - The CLI writes replay result rows (shape above).

- [ ] **Step 1: Write the failing tests**

`tools/ai-eval/tests/test_replay.py`:

```python
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
        payload = "".join(CHUNKS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def base_url():
    Fake.seen = []
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
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd tools/ai-eval && python3 -m pytest tests/test_replay.py -q -p no:cacheprovider`

Expected: `ModuleNotFoundError: No module named 'replay'`.

- [ ] **Step 3: Write the implementation**

`tools/ai-eval/replay.py`:

```python
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
from corpus import assemble_sse, load_records, production_output, record_id, sample


def prepare(request, model):
    body = copy.deepcopy(request)
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
    for choice in event.get("choices") or []:
        delta = choice.get("delta") or {}
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
    return {"error": None, "ttft_ms": ttft_ms, "latency_ms": elapsed(),
            "output": assemble_sse("".join(lines))}


def _jobs(args):
    """(id, original_request, production_output_or_None, body_to_send)."""
    records = load_records(args.corpus, args.consumer)
    if args.ha_intents:
        template = ha.pick_template(records)
        for intent in ha.load_intents(args.ha_intents):
            body = ha.build_request(template, intent["utterance"])
            yield intent["id"], body, None, prepare(body, args.model)
        return
    for rec in sample(records, args.limit, args.seed):
        yield record_id(rec["request"]), rec["request"], production_output(rec), prepare(rec["request"], args.model)


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
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd tools/ai-eval && python3 -m pytest tests/test_replay.py -q -p no:cacheprovider`

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add tools/ai-eval/replay.py tools/ai-eval/tests/test_replay.py
git commit -m "feat(ai-eval): replay runner with TTFT/latency capture

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Grader

**Files:**
- Create: `tools/ai-eval/grade.py`
- Test: `tools/ai-eval/tests/test_grade.py`

**Interfaces:**
- Consumes: replay result rows (Task 6) and `ha.agrees` (Task 5).
- Produces:
  - `structured_valid(request, message) -> bool | None`
  - `tool_calls_valid(request, production_message, candidate_message) -> bool | None`
  - `fact_recall(production_message, candidate_message, threshold=0.5) -> float | None`
  - `decode_tps(candidate) -> float | None`
  - `summarize(rows, baselines=None) -> dict[str, dict]`
  - `to_markdown(summary, label) -> str`
  - CLI: `grade.py RESULTS [--ha-baseline BASELINE] [--markdown --label TEXT]`.

- [ ] **Step 1: Write the failing tests**

`tools/ai-eval/tests/test_grade.py`:

```python
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
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd tools/ai-eval && python3 -m pytest tests/test_grade.py -q -p no:cacheprovider`

Expected: `ModuleNotFoundError: No module named 'grade'`.

- [ ] **Step 3: Write the implementation**

`tools/ai-eval/grade.py`:

```python
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
```

In `_score`, an errored row has `msg = None`, so `structured_valid` returns `False` when a JSON contract was requested. That is intended: a failed request counts as invalid, not as skipped.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd tools/ai-eval && python3 -m pytest tests -q -p no:cacheprovider`

Expected: all harness tests pass (`5 + 3 + 5 + 5 = 18 passed`).

- [ ] **Step 5: Commit**

```bash
git add tools/ai-eval/grade.py tools/ai-eval/tests/test_grade.py
git commit -m "feat(ai-eval): per-consumer grader (schema, tool calls, fact recall, HA agreement)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Runbook and harness dry run against production

**Files:**
- Create: `tools/ai-eval/README.md`
- Create: `docs/ai-history/mac-studio.md`
- Modify: `docs/ai-history/README.md` (link the new file)

**Interfaces:**
- Consumes: everything above, plus ≥3 days of capture (do this task once Task 3 Step 7 is ≥3 days old).
- Produces: a validated harness, the HA GPT-5.5 baseline file `tools/ai-eval/results/ha-gpt55.jsonl` (gitignored, kept for Phase 3), and a committed aggregate baseline table.

- [ ] **Step 1: Write `tools/ai-eval/README.md`**

````markdown
# ai-eval

Replay and grading harness for the Mac Studio bake-off
(`docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md`).
Captures come from `ai-tap` (`kubernetes/apps/ai/ai-tap/`).

**Captured prompts are personal data.** `corpus/` and `results/` are
gitignored. Keep them on-cluster (HolyClaude `/workspace`) or on the Mac.
Only aggregate tables go to `docs/ai-history/mac-studio.md`.

## Setup

    pip install --break-system-packages -r requirements.txt
    python3 -m pytest tests -q -p no:cacheprovider

## Pull a corpus snapshot

    snap=corpus/$(date +%F)
    mkdir -p "$snap"
    kubectl -n ai exec deploy/ai-tap -- tar -C /data -cf - . | tar -C "$snap" -xf -

## Replay and grade

    # Hindsight: production model alias via the tap's upstream (sanity baseline)
    python3 replay.py --corpus "$snap" --consumer hindsight \
      --base-url http://llama-swap.ai.svc.cluster.local:8080/v1 --model reasoner \
      --concurrency 5 --limit 200 --out results/hindsight-prod.jsonl
    python3 grade.py results/hindsight-prod.jsonl --markdown --label "hindsight: gpt-oss-20b (llama-swap)"

    # HA intent set: GPT-5.5 baseline once, then each candidate
    export EVAL_API_KEY=<HA's Omniroute key, from omniroute-secret.sops.yaml via task sops:view>
    python3 replay.py --corpus "$snap" --consumer ha --ha-intents corpus/ha_intents.yaml \
      --base-url http://omniroute.ai.svc.cluster.local:20128/v1 --model cliproxyapi/gpt-5.5 \
      --out results/ha-gpt55.jsonl
    python3 replay.py --corpus "$snap" --consumer ha --ha-intents corpus/ha_intents.yaml \
      --base-url http://<mac>:<port>/v1 --model <candidate> --out results/ha-<candidate>.jsonl
    python3 grade.py results/ha-<candidate>.jsonl --ha-baseline results/ha-gpt55.jsonl --markdown --label "ha: <candidate>"

Use `--concurrency 1` for c=1 numbers and `--concurrency 5` for c=5. Run one
engine at a time on an idle Mac (spec).

## Synthetic load (`vllm bench serve`)

For TTFT at fixed 0/8K/32K prefixes and concurrency sweeps, independent of
the corpus. Run it on the Mac where vllm-metal is installed:

    vllm bench serve --backend openai-chat --base-url http://127.0.0.1:<port> \
      --endpoint /v1/chat/completions --model <model> --dataset-name random \
      --random-input-len 8192 --random-output-len 256 --num-prompts 50 --max-concurrency 5

## Metrics

| Metric | Meaning |
|---|---|
| structured_valid_rate | answer parses and meets the request's `response_format` (errors count as invalid) |
| fact_recall_mean | share of production's JSON facts matched by the candidate (token Jaccard ≥ 0.5) |
| tool_valid_rate | candidate tool calls name an offered tool with JSON-object args |
| ha_agreement_rate | same tool calls (name + normalised args) as GPT-5.5 on the intent set |
| ttft / latency / decode_tps | measured on streaming replay; decode = completion tokens ÷ (latency − TTFT) |

## Retention

Delete `corpus/`, `results/`, the `ai-tap` app and its PVC after the last
consumer cuts over (Phase 3).
````

- [ ] **Step 2: Pull a snapshot and check its shape**

Run the snapshot commands from the README in `tools/ai-eval/` on the HolyClaude checkout `/workspace/home-ops`. That checkout is on the operator's branch. Do not switch branches; `tools/ai-eval/corpus/` is just an untracked, gitignored path there once this PR merges. Until then, use `/workspace/home-ops-mac-spec/tools/ai-eval/`. Then run:

```bash
python3 -c "import corpus,sys; [print(c, len(corpus.load_records(sys.argv[1], c))) for c in ('hindsight','atuin','ha','argus')]" "$snap"
```

Expected: non-zero counts for hindsight, atuin and ha, and `argus 0` while it stays disabled. If `ha` is zero, Task 3 Step 6 was not done. If records exist but `load_records` returns 0, inspect `path` values: a consumer may use a non-chat endpoint. Report that rather than widening the filter silently.

- [ ] **Step 3: Sanity replay against production**

Run the Hindsight and atuin replays against their production upstreams, with `--limit 50`:
- Hindsight: llama-swap, `reasoner`.
- atuin: llama-swap, `coder-large`, which is the same gpt-oss-20b, avoiding Omniroute's 120s cap.

Grade both.

Expected: Hindsight `structured_valid_rate` ≥ 0.9 and `fact_recall_mean` well above 0. A model replayed against its own past answers should mostly agree. If `fact_recall_mean` < 0.3, the metric is miscalibrated for Hindsight's output shape. Inspect three rows by hand before trusting it in Phase 2, and report what you found.

- [ ] **Step 4: Author the HA intent set and record the GPT-5.5 baseline (operator plus agent)**

The operator writes ~40 utterances into `tools/ai-eval/corpus/ha_intents.yaml`, following `ha_intents.example.yaml`. Then run the GPT-5.5 baseline command from the README. Expected: `replayed 40 (0 errors)`. Keep `results/ha-gpt55.jsonl`: it is the Phase 3 reference. Re-running it later costs subscription quota and may drift.

- [ ] **Step 5: Record the baseline aggregates**

Create `docs/ai-history/mac-studio.md`:

```markdown
# Mac Studio AI host — eval history

Aggregates only; raw prompts never land here. Harness: `tools/ai-eval/`.
Spec: `docs/superpowers/specs/2026-10-10-mac-studio-ai-host-design.md`.

## <YYYY-MM-DD> production baseline (bigboi, gpt-oss-20b via llama-swap)

Corpus: <start>–<end>, <N> hindsight / <N> atuin / <N> ha records.

<paste grade.py --markdown output for hindsight and atuin>

HA intent set: <N> intents, GPT-5.5 baseline recorded (`results/ha-gpt55.jsonl`, not committed).
```

Fill in every `<...>` with real values from Steps 2–4. In `docs/ai-history/README.md`, add `[mac-studio](mac-studio.md) (Mac Studio bake-off results)` to the per-component list.

- [ ] **Step 6: Commit and PR**

```bash
git add tools/ai-eval/README.md docs/ai-history/mac-studio.md docs/ai-history/README.md
git status --short tools/ai-eval   # must show no corpus/ or results/ paths
git commit -m "docs(ai-eval): harness runbook and production baseline

Baseline the Mac Studio candidates must meet per consumer (spec local-only
gate). Aggregates only; the corpus stays on-cluster.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git push
```

Update the PR description (or open a follow-up PR if Task 3's PR already merged) ending with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

---

## Self-review notes

- Spec coverage:
  - Phase 0.1 capture: Tasks 1–3.
  - Phase 0.2 harness and HA intent set: Tasks 4–8.
  - Grading bullets:
    - Hindsight schema and fact recall: Task 7.
    - atuin/argus tool-call parse: Task 7.
    - HA vs GPT-5.5: Tasks 5–8.
    - argus verdict agreement: deferred, stated above with the reason.
  - "Never committed": `.gitignore` in Task 4 plus the `git status` check in Task 8.
  - Results to `docs/ai-history/`: Task 8.
  - Performance metrics (TTFT, tok/s, c=1/c=5): replay; `vllm bench serve` is documented. The cold-load, peak-memory and soak metrics need the Mac and belong to the Phase 1 plan.
- The per-task test counts sum to 18 for the harness and 9 for the tap.
