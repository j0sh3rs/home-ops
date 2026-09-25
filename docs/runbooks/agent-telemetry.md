# Agent OpenTelemetry Runbook

Source-of-truth for exporting Claude Code and Codex CLI telemetry to the
externally-hosted VictoriaMetrics (`metrics.68cc.io`) and VictoriaLogs
(`logs.68cc.io`), per issue #707. Half of this is GitOps-managed (this repo
applies it to HolyClaude automatically); half has to be applied by hand on
whichever machine actually runs the CLI, since this repo has no reach onto
the operator's laptop.

## Why no in-cluster OTel Collector

Both external endpoints already expose native OTLP ingest, confirmed by a
direct probe (both return `200` on an empty-body `POST`):

```bash
curl -X POST https://metrics.68cc.io/opentelemetry/v1/metrics
curl -X POST https://logs.68cc.io/insert/opentelemetry/v1/logs
```

So every OTLP-emitting client (Claude Code, Codex) can point straight at
these paths — no collector needed as a translation hop, and no auth headers
either (same trust model already used by vmagent's `remoteWrite` and
vector's ES-bulk sink to these same two hosts).

**Endpoint path note**: use the per-signal endpoint env vars
(`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` / `..._LOGS_ENDPOINT`), not the bare
`OTEL_EXPORTER_OTLP_ENDPOINT`. A bare base endpoint gets `/v1/metrics` /
`/v1/logs` auto-appended per the OTel spec, which does not match
VictoriaMetrics' `/opentelemetry/v1/metrics` or VictoriaLogs'
`/insert/opentelemetry/v1/logs` paths.

## Applied automatically: HolyClaude (in-cluster Claude Code)

`kubernetes/apps/ai/holyclaude/app/helmrelease.yaml`'s `app` container now
sets `CLAUDE_CODE_ENABLE_TELEMETRY=1` plus the OTLP metrics/logs env vars,
tagged `OTEL_RESOURCE_ATTRIBUTES: deployment.environment=holyclaude` so its
telemetry is distinguishable from the laptop's. Unlike the
`OMNIROUTE_ANTHROPIC_*`/`ANTHROPIC_*` values in that same file, this did
**not** need a `postStart` `settings.json` patch — Claude Code reads
`OTEL_*` purely from process env, and nothing on the PVC's persisted
`settings.json` sets any `OTEL_*` key.

`kubernetes/apps/ai/holyclaude/app/prometheusrule.yaml` adds two alerts
(`ClaudeCodeTelemetryStale`, `ClaudeCodeSessionSpendHigh`) and
`grafanadashboard.yaml` adds a "Claude Code Agent Sessions" dashboard
(folder `AI`).

**Confirmed end-to-end 2026-09-23** via a one-shot `claude -p` run inside
the holyclaude pod (`kubectl -n ai exec ... -- claude -p "..."`), then
querying both backends live:

- `claude_code.session.count`, `claude_code.cost.usage`,
  `claude_code.token.usage`, `claude_code.active_time.total` all landed in
  VictoriaMetrics within one 60s export interval.
- `claude_code.user_prompt` (and other events, e.g.
  `claude_code.mcp_server_connection`) landed in VictoriaLogs within one
  10s export interval.

**Important finding — VictoriaMetrics does NOT sanitize OTel names.**
Contrary to the original assumption in this file/the manifests (Prometheus-
style dots→underscores + `_total` suffix), VictoriaMetrics' native OTLP
ingestion preserves OTel metric **and label** names verbatim, dots
included: the real series is `claude_code.session.count` with a
`deployment.environment` label, `session.id`, etc. — not
`claude_code_session_count_total{deployment_environment=...}`.

Bare-identifier PromQL can't reference a dotted name. Use MetricsQL's
quoted-name selector instead, confirmed working against both the query API
and vmalert's engine:

```promql
# metric name only
{"claude_code.session.count"}

# metric + dotted label filter
{"claude_code.session.count", "deployment.environment"="holyclaude"}

# aggregating by a dotted label
sum by ("session.id", "deployment.environment") (increase({"claude_code.cost.usage"}[24h]))
```

In Alertmanager/Grafana annotation templates, `$labels.deployment_environment`
silently renders empty against a real `deployment.environment` label — use
`{{ index $labels "deployment.environment" }}` instead. Grafana panel
`legendFormat` (e.g. `{{deployment.environment}}`) works fine as-is — it's
a plain string lookup, not Go struct-field access.

**This applies to any future OTel-sourced metric in this cluster**, not
just Claude Code's — Codex's metrics (once wired, see below) will need the
same quoted-selector treatment.

## Applied: this NAS host's global Claude Code config

This repo is normally checked out and worked on interactively via Claude
Code running directly on the operator's Synology NAS host (not a separate
laptop) — the same session that authored this runbook. Since that's a
real, reachable machine (unlike a genuinely separate laptop), its global
`~/.claude/settings.json` (`/root/.claude/settings.json` on this host) now
carries the same `env` block HolyClaude's HelmRelease sets, tagged
`deployment.environment=synology-nas`:

```json
"env": {
  "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
  "OTEL_METRICS_EXPORTER": "otlp",
  "OTEL_LOGS_EXPORTER": "otlp",
  "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
  "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "https://metrics.68cc.io/opentelemetry/v1/metrics",
  "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "https://logs.68cc.io/insert/opentelemetry/v1/logs",
  "OTEL_METRIC_EXPORT_INTERVAL": "60000",
  "OTEL_LOGS_EXPORT_INTERVAL": "10000",
  "OTEL_RESOURCE_ATTRIBUTES": "deployment.environment=synology-nas"
}
```

This file is outside the git repo (`/root/.claude/`, not
`/volume1/git/j0sh3rs/home-ops/`) so it isn't GitOps-managed or reviewable
via this repo's history — it's genuinely host-local machine config, same
category as `age.key`/`kubeconfig` at the repo root. **Env vars are read
once at process startup**, so this takes effect on the *next* Claude Code
launch on this host, not retroactively for whatever session is already
running when the file is edited.

## Apply by hand: any other machine (e.g. a separate physical laptop)

For any Claude Code install this repo/session genuinely cannot reach, add
the same block to that machine's shell profile or its own
`~/.claude/settings.json` `env` block, with a distinguishing
`deployment.environment` tag (`laptop`, or whatever names the machine):

```bash
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=https://metrics.68cc.io/opentelemetry/v1/metrics
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=https://logs.68cc.io/insert/opentelemetry/v1/logs
export OTEL_METRIC_EXPORT_INTERVAL=60000
export OTEL_LOGS_EXPORT_INTERVAL=10000
export OTEL_RESOURCE_ATTRIBUTES=deployment.environment=laptop
```

Verify: run a Claude Code session, then query
`{"claude_code.session.count", "deployment.environment"="laptop"}` against
`https://metrics.68cc.io` (see the quoted-selector note above).

## Apply by hand: Codex CLI

Codex's `[otel]` config lives in `config.toml` under its `CODEX_HOME`
(default `~/.codex`). Schema is independent per signal
(`exporter` for logs/traces, `metrics_exporter` for metrics — metrics
default to `statsig`, i.e. OpenAI's own telemetry, unless overridden):

```toml
[otel]
environment = "laptop"      # or "holyclaude", etc — tags every event
log_user_prompt = false      # keep prompt text redacted by default

exporter = "otlp-http"
metrics_exporter = "otlp-http"

[otel.exporter.otlp-http]
endpoint = "https://logs.68cc.io/insert/opentelemetry/v1/logs"
protocol = "binary"

[otel.metrics_exporter.otlp-http]
endpoint = "https://metrics.68cc.io/opentelemetry/v1/metrics"
protocol = "binary"
```

A repo-root `.codex/config.toml` already exists in this checkout
(untracked, `[features] hooks = true` only) — its provenance/whether it's
actually `CODEX_HOME` for any real Codex invocation wasn't established
during this change, so the `[otel]` block above was deliberately **not**
applied to it. Apply the block to whichever `config.toml` your real Codex
CLI actually reads (check `CODEX_HOME`, default `~/.codex/config.toml`).

**Known limitation** ([openai/codex#12913](https://github.com/openai/codex/issues/12913)):
only the interactive `codex` CLI fully respects `[otel]`. `codex exec`
exports logs/traces but zero metrics despite a working config; `codex
mcp-server` initializes no telemetry at all. If Codex is driven headlessly
(exec/mcp-server) anywhere in this stack, expect gaps in the metrics side
specifically — logs/traces should still work.

## Explicitly deferred (per issue #707)

- **Hindsight retain-queue-depth alert** — Hindsight **is** deployed
  (#701; the sole memory layer since OpenViking's 2026-09-25 retirement)
  and there is still no alert on this — tracked in #719. A 16-hour silent queue wedge
  actually happened 2026-09-24/25: hostname-based worker ids left 6
  retains stuck `processing` under a replaced pod, blocking 10 pending
  retains behind them with no alert firing (see the "2026-09-24/25
  backlog incident" writeup in `kubernetes/apps/ai/CLAUDE.md`'s hindsight
  bullet, and I1's rollout-strategy fix in the same file). This is an
  open follow-up, not built in this wave. Candidates:
  - A VMRule on the scraped Hindsight `/metrics` endpoint (pending/
    processing counts, or oldest-pending age, if exposed there).
  - A SQL-based check against `user_josh.async_operations` directly —
    e.g. oldest `processing` row older than 30 min, or a rising pending
    count. [vectorize-io/hindsight#4560](https://github.com/vectorize-io/hindsight/issues/4560)
    (referenced in #701's watch-outs) is a *different*, now-closed bug
    about runaway retain cost/extraction-mode, not a queue-depth metric —
    it doesn't cover this gap either way.

- **Hook-failure alerts (recall/retain)** — investigated 2026-09-23,
  deliberately not shipped. Findings (historical: OpenViking was retired
  2026-09-25, so its log queries below no longer return new data):
  - OpenViking's server logs (`app_name:openviking` in VictoriaLogs) have
    **zero** ERROR/exception/traceback-level entries in the last 30 days.
  - The only related signal is a `WARNING ... slow call ... duration_ms=`
    line from `openviking.models.embedder.openai_embedders` — confirmed
    real via `https://logs.68cc.io`:
    `app_name:openviking AND _msg:" - WARNING - " AND _msg:"slow call"`
    returns **1076 hits over the last 7 days** (~one every 9 minutes on
    average, bursty around active sessions). This is the already-known,
    already-accepted embedding-path latency documented elsewhere in this
    repo (issue #701's own motivation) — not a failure, and far too
    high-baseline to threshold naively without causing alert fatigue.
  - The actual silent-failure case issue #701 describes (a
    `UserPromptSubmit` hook stalling up to 60s and "proceeding with no
    recall and no visible error") **logs nothing at all, by design** — the
    failure is the absence of a log line, not the presence of one. There is
    currently no clean signal to match a LogsQL rule against.
  - Shipping anything here would also mean new cluster alerting
    infrastructure (this cluster's single `vmalert` only has a Prometheus
    datasource against `metrics.68cc.io`; a LogsQL-based rule needs either
    a second `VMAlert` instance pointed at VictoriaLogs — carefully
    excluded from the existing vmalert's `selectAllByDefault` so it doesn't
    disturb the 45+ existing rules — or extending Vector's cluster-wide
    log-shipping DaemonSet with a `log_to_metric` transform, which risks
    breaking log ingestion cluster-wide on a config mistake). Real
    production risk for a signal that isn't clean yet.
  - **Decision (operator, 2026-09-23): don't ship an alert on this signal.**
    Revisit when either a real hook-failure incident produces something
    concrete to match against, or when #701 replaces this recall/retain
    path with Hindsight's entirely and the question becomes moot.

## Acceptance criteria status (from issue #707)

- [x] `claude_code.session.count` and `claude_code.user_prompt` visible in
      Victoria\* — confirmed end-to-end 2026-09-23 (HolyClaude side; laptop
      side still needs the by-hand config above applied).
- [x] Grafana dashboard for agent sessions — `holyclaude-agent-sessions`,
      folder `AI`, all panel queries confirmed against live data.
- [ ] Alerts for hook failures and queue depth — investigated and
      deliberately deferred, see above (queue-depth is structurally
      blocked on the not-yet-started #701 Hindsight migration;
      hook-failure has no clean signal to alert on today, and the operator
      chose not to ship a noisy/low-confidence proxy). Spend +
      pipeline-health alerts added instead as what's actionable today, both
      confirmed evaluating correctly against live data
      (`ClaudeCodeSessionSpendHigh` correctly not firing at $0.33 < $10;
      `ClaudeCodeTelemetryStale` correctly not firing while data is
      flowing).
