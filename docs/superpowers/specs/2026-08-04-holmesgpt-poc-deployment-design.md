# HolmesGPT POC Deployment — Design

Date: 2026-08-04
Status: Approved, pending implementation

## Context

Evaluating AI-driven incident investigation tools for this cluster. Two candidates researched:

- **OpenSRE** (`Tracer-Cloud/opensre`) — rejected. No official Helm chart or Kubernetes manifests published; install paths are binary/curl, Homebrew, or Docker (Railway/ECS/Vercel). Would require hand-authoring a `bjw-s/app-template` wrapper with zero upstream chart to track, which reproduces the "rough edges" problem the OpenSRE CLI already has, just moved into this repo.
- **HolmesGPT** (`HolmesGPT/holmesgpt`, chart published by Robusta) — selected. Ships a real Helm chart (not OCI-published, but a working `HelmRepository` source) with a bundled Operator for autonomous health checks.

Originally scoped as a full Alertmanager → HolmesGPT → Discord pipeline, via a new custom bridge service (working name `bifrost`, repo created at `j0sh3rs/bifrost`) and `home-operations/chaski` as a webhook-to-Discord relay. That scope was cut back on 2026-08-04: bifrost and chaski are both **out of scope for this spec**. The reasoning and paused design work live in the `bifrost` repo's own beads (`bifrost-a7g`, `bifrost-44f`) and in `home-ops-4rm`. This spec covers only the narrower POC: deploy HolmesGPT itself, using its native capabilities, prove it's worth building further automation around before investing in bridge/relay plumbing.

## Goal

Deploy HolmesGPT (base HTTP API service + bundled Operator) into the `ai` namespace, wired to **omniroute** as its LLM backend. No output-destination wiring (Slack, PagerDuty, etc.) in this pass — that's a separate follow-up conversation once the POC proves the tool's investigation quality is worth it.

## Non-goals

- No bifrost, no chaski, no Discord integration.
- No external exposure (HTTPRoute/Gateway) — cluster-internal only for this POC.
- No HealthCheck/ScheduledHealthCheck/TriggeredHealthCheck custom resources created yet — only the Operator's CRDs and controller get installed. Actual health-check definitions are follow-up work once someone decides what should be monitored.
- No LiteLLM involvement. LiteLLM is being phased out of this cluster in favor of omniroute as the single LLM gateway; this deployment reflects that direction from day one rather than wiring to the outgoing gateway.

## Architecture

```
Alertmanager (existing) ──X── (no wiring yet, future work)

kubectl / manual testing ──> HolmesGPT HTTP API (cluster-internal svc)
                                    │
                                    ▼
                              omniroute (OpenAI-compatible gateway)
                                    │
                                    ▼
                        cloud/local model providers (existing routing)
```

## Components

1. **New HelmRepository**: `kubernetes/flux/meta/repos/robusta.yaml`
   - URL: `https://robusta-charts.storage.googleapis.com`
   - This is the actual chart source (confirmed via ArtifactHub API — package `robusta/holmes`, latest `0.38.1`). No OCI artifact exists, so this follows the CLAUDE.md fallback rule (`HelmRepository` + `chart.spec.sourceRef`) rather than the standard `OCIRepository` + `chartRef` pattern used for new apps.

2. **New app**: `kubernetes/apps/ai/holmesgpt/`
   - `ks.yaml` — Flux Kustomization, namespace `ai`, `dependsOn: omniroute` (mirrors the existing dependency pattern used by `litellm`/`omniroute` on `llama-swap`).
   - `app/kustomization.yaml`
   - `app/helmrelease.yaml` — `chart.spec.sourceRef` pointing at the new `robusta` HelmRepository, chart `holmes`.
   - `app/secret.sops.yaml` — new `holmesgpt-secrets` Secret holding the omniroute API key (and any other required env, TBD once chart values are finalized during implementation).

3. **HelmRelease values** (exact keys to be finalized against chart `0.38.1`'s `values.yaml` during implementation, not guessed here):
   - `operator.enabled: true` — installs CRDs + operator controller only; no HealthCheck resources created in this pass.
   - LLM provider config pointed at omniroute's OpenAI-compatible endpoint: `http://omniroute.ai.svc.cluster.local:20129/v1`, API key sourced from `holmesgpt-secrets` via `envRef:`-style reference (chart's actual `extraEnvVarsSecrets`/`modelList` mechanism, per the chart's own values schema).
   - No `route`/HTTPRoute values — internal-only.

4. **Namespace fit**: `ai` namespace already has `common` + `authentik-forwardauth` components; HolmesGPT doesn't need `app-template` (it ships its own chart) and doesn't need forwardAuth since it's not externally routed in this pass.

## Open items / inputs needed from user before secrets can be real

- **omniroute API key** — must be generated via the omniroute dashboard (`omniroute.68cc.io`) by the user; cannot be scripted. Placeholder in the secret until provided.
- **Model alias/name** — which model omniroute exposes that HolmesGPT's `modelList.model:` field should reference. TBD, confirm against omniroute's dashboard/config during implementation.

## Validation plan

- `kustomize build kubernetes/apps/ai/holmesgpt/app` — manifests render cleanly.
- `task sops:verify` — new secret file properly encrypted.
- `flux build kustomization holmesgpt --path kubernetes/apps/ai/holmesgpt --dry-run` — Flux-level validation.
- Post-deploy: `kubectl -n ai get pods`, `kubectl -n ai logs` on the holmesgpt pod, confirm it starts and can reach omniroute (no immediate crash/auth failure).
- Manual smoke test: `holmes ask` or a direct API call against the in-cluster service (via port-forward) to confirm an end-to-end investigation actually returns a sensible result.

## Follow-up work (explicitly deferred, not part of this spec)

- Output destination wiring (Slack native destination, or revisiting the bifrost/chaski/Discord pipeline) — separate design conversation.
- HealthCheck/ScheduledHealthCheck/TriggeredHealthCheck resource definitions — once it's clear what should be monitored.
- External exposure via HTTPRoute if the POC proves useful enough to want ad hoc access beyond port-forward.
