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
(folder `AI`) — see both files' header comments for the metric-naming
caveat below.

**Not yet confirmed**: the exact Prometheus series names VictoriaMetrics'
OTLP ingestion produces for Claude Code's metrics
(`claude_code.session.count` → assumed `claude_code_session_count_total`,
etc. — dots to underscores, `_total` suffix on monotonic sums, matching the
OTel-collector-compatible convention VictoriaMetrics documents). No real
telemetry has flowed yet as of this change. **After the next HolyClaude pod
restart and one real session**, verify with:

```promql
count by (__name__) ({__name__=~"claude_code.*"})
```

against `https://metrics.68cc.io`, and fix the `expr:` fields in
`prometheusrule.yaml`/`grafanadashboard.yaml` if the real names differ.

## Apply by hand: Claude Code on the laptop

This repo cannot set environment variables on the operator's own machine.
Add this to the laptop's shell profile (or Claude Code's own
`~/.claude/settings.json` `env` block, same as HolyClaude's PVC copy):

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
`claude_code_session_count_total{deployment_environment="laptop"}` (or
whatever the real series name turns out to be, per the caveat above)
against `https://metrics.68cc.io`.

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

- **Hindsight retain-queue-depth alert** — blocked on
  [vectorize-io/hindsight#4560](https://github.com/vectorize-io/hindsight/issues/4560)
  per the issue's own sequencing note. Nothing to alert on until that
  metric/queue exists.
- **Hook-failure alerts (recall/retain)** — would need a LogsQL rule
  against OpenViking's actual hook-failure log signature. HolyClaude's pod
  logs already ship to VictoriaLogs today (vector's cluster-wide
  `kubernetes_logs` source, no change needed for that part), but the exact
  failure log pattern to match hasn't been characterized. Follow-up: grep a
  real recall/retain failure from `https://logs.68cc.io` (or trigger one
  deliberately) before writing this rule, and check whether vmalert in this
  cluster can run a LogsQL-datasource rule group at all (today's
  `vmalert.yaml` only configures a Prometheus datasource against
  `metrics.68cc.io`).

## Acceptance criteria status (from issue #707)

- [ ] `claude_code.session.count` and `claude_code.user_prompt` visible in
      Victoria\* — pipeline is wired (HolyClaude side); needs a real session
      to confirm end-to-end, and the metric-naming caveat above resolved.
- [x] Grafana dashboard for agent sessions — `holyclaude-agent-sessions`,
      folder `AI`.
- [ ] Alerts for hook failures and queue depth — explicitly deferred, see
      above. Spend + pipeline-health alerts added instead as what's
      actionable today.
