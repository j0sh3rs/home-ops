# Mac Studio AI Host and bigboi Decommission — Design

Date: 2026-10-10
Status: Approved design, not started. Hardware shipped, not yet arrived.
Related: `kubernetes/apps/ai/CLAUDE.md`,
`docs/superpowers/specs/2026-09-07-omniroute-revival-design.md`,
`docs/superpowers/specs/2026-09-24-hindsight-deployment-design.md`

## Context

All model serving runs today on `bigboi-jms-01` (RX 9070 XT, ~640 GB/s,
llama-swap serving `gpt-oss-20b`) and on the bee APUs (`llama-swap-apu`,
DDR4 at ~50 GB/s, measured at 11.45 tok/s for qwen3.5-4b). Omniroute
fronts both and adds a cloud lane (cliproxyapi → GPT-5.5) because the
local hardware could not cover every use case.

A Mac Studio is arriving: M5 Ultra, 36-core CPU, 80-core GPU, 96GB
unified memory, ~1228 GB/s memory bandwidth, 2TB, 10GbE. Token
generation is bandwidth-bound, so this is roughly 2× the dGPU and 25×
the APUs. It is fast enough to make local-only serving realistic for
every automated consumer.

## Goals

1. The Mac is the cluster's model-serving host, running **natively on
   macOS** (Metal/MLX). It is not a Kubernetes node.
2. **Local-only models for every automated consumer** (Hindsight, argus,
   atuin, the Home Assistant conversation agent). Claude stays only as
   HolyClaude's native OAuth login.
3. Decommission `bigboi-jms-01`. The 3 bee nodes run every workload.
4. Manage the Mac declaratively and pull-based, like Flux.
5. Pick serving engine and models from measurements on the real
   hardware and real traffic, not from published benchmarks.

## Non-goals (follow-ons)

- **Replicated PVC storage** so workloads stop being node-pinned. This
  reverses the current "durability is never the PVC's job" policy and
  puts write replication on the etcd nodes; it gets its own design.
- **Replacing HolyClaude with OpenClaw** (better macOS integration).
  Deferred until the hardware is in hand.
- **Choosing the replacement AI gateway.** Phase 4 below sets its
  requirements; the choice gets its own short spec.

## Decisions

| # | Decision | Rationale / rejected alternatives |
|---|---|---|
| D1 | Mac runs inference natively; not a Talos or k8s node | Linux VMs on macOS get no Metal; the only GPU path (krunkit/libkrun Venus Vulkan) is alpha, ~75–80% of native, and has no MLX. A Talos reinstall loses the GPU entirely. |
| D2 | Keep 3 bees as the control plane; remove bigboi | 2 etcd members is worse than 1 (no fault tolerance, double the failure surface). The realistic floors are 3 or 1. Removing bigboi (32 CPU + dGPU) is the power win. |
| D3 | Mac is effectively a dedicated inference server | Final Cut is never used; Logic Pro rarely, if ever. Optimize for no desktop apps: model budget ~80GB of 96GB. Logic use is an accepted risk covered by swap and wired-memory alerts. |
| D4 | No LLM fallback when the Mac is down | Hindsight's queue absorbs outages; argus, atuin and HA fail (fast) until the Mac returns. Bees keep only what must survive Mac downtime and meets latency on bee hardware: faster-whisper and piper. |
| D5 | Determinate Nix + nix-darwin, pull-based apply | Ansible rejected (not declarative). Pull model mirrors Flux. Serving-engine app settings may live outside nix. |
| D6 | FileVault on; every service is a LaunchDaemon | Starts at boot without a login. Planned reboots via `fdesetup authrestart`; unplanned via Tahoe SSH pre-boot unlock. |
| D7 | oMLX is the primary engine candidate | Only candidate that both replaces llama-swap's multi-model LRU/TTL/pinning and passed all three SiliconBench audit gates (performance, memory discipline, fidelity). Has per-key auth, embeddings and rerank. Gap: no Prometheus `/metrics`. |
| D8 | Engine bake-off includes LM Studio, Splash and vllm-metal | Operator wants the best pick proven on the hardware, closed source or not. vllm-mlx dropped (failed SiliconBench fidelity and memory gates). |
| D9 | Omniroute is the interim gateway, then replaced | Its reason to exist (cloud fallback for weak local hardware) disappears. Known limits: 120s request cap (Hindsight already bypasses it), keys/combos only in its DB, unreliable combo fallback (HolyClaude revert, 2026-09-26), lane isolation by convention only. |
| D10 | A front door routes model names to engines | Lets a bake-off winner (Splash, vllm-metal) be added for one lane without touching consumers. Interim: Omniroute. Final: the Phase 4 gateway. |
| D11 | HolyClaude moves to bee-03 as an accepted risk | It was pinned to bigboi to keep a privileged, cluster-admin pod off etcd nodes. With bigboi gone every node is control-plane. bee-03 has the most headroom. Revisit with the OpenClaw decision. |

## Architecture

```
consumers (in-cluster on bees, and Mac localhost)
        │  one URL, one key per consumer
        ▼
  gateway (interim: Omniroute; later: Phase 4 choice)
        │
        ▼  mac-inference.ai.svc (selector-less Service + EndpointSlice)
  ┌──────────────── Mac Studio (macOS, nix-darwin) ────────────────┐
  │ oMLX (default: all roles, LRU/TTL, embeddings, rerank)          │
  │ Splash / vllm-metal (only for a lane where the bake-off proves  │
  │   ≥1.5× on a metric that matters)                               │
  │ node_exporter · GPU/power exporter · engine exporter · vector   │
  │ pf allowlist · API keys · sops-nix                              │
  └─────────────────────────────────────────────────────────────────┘
Bees: all workloads + faster-whisper + piper
```

Hindsight talks to the Mac directly (as it talks to llama-swap today)
until the Phase 4 gateway has no request cap below 600s.

### Mac configuration management

- `macos/` flake in this repo: Determinate Nix (sets `nix.enable = false`),
  nix-darwin, sops-nix darwin module with a Mac-only age key, Homebrew
  module with `cleanup = "zap"` for anything that is only a cask.
- Python/MLX engines are `uv`-pinned and run as nix-declared
  LaunchDaemons.
- **Pull loop:** a launchd timer runs
  `darwin-rebuild switch --flake github:j0sh3rs/home-ops?dir=macos#mac-studio`
  when `main` moves, and writes the applied commit and timestamp to a
  node_exporter textfile metric.
- **PR CI:** `nix build` of the darwin closure on a GitHub-hosted macOS
  runner, with `nix store diff-closures` output. Renovate's nix manager
  bumps `flake.lock`; Homebrew/uv pins may need a custom manager.
- **Rollback:** git revert (the pull loop applies it) or
  `darwin-rebuild --rollback` locally.

### Server settings

- `iogpu.wired_limit_mb` ≈ 84GB, set at boot by a LaunchDaemon (sysctl
  does not persist). The engine's own memory limit is ≈ 80GB, leaving
  ~12GB for macOS and the agents.
- `pmset`: never sleep. Spotlight excluded from model and KV-cache
  directories. No auto-login. Automatic macOS updates off; updates are
  a manual runbook step using authrestart.

### Exposure and security

- Engine APIs listen on the LAN; a nix-managed `pf` ruleset allows only
  localhost and the cluster. **To verify:** whether Cilium masquerades
  pod egress to node IPs (allowlist = 3 bee IPs) or not (allowlist =
  pod CIDR `10.42.0.0/16`).
- Every endpoint requires an API key. Consumer keys are SOPS Secrets in
  the cluster.
- In-cluster name: selector-less Service `mac-inference` + EndpointSlice,
  so the Mac's IP lives in one place.
- Admin UIs (oMLX panel, LM Studio) only via `traefik-internal` with
  Authentik forwardAuth; never on the external gateway.
- SSH is key-only and also serves FileVault pre-boot unlock.

### Observability

| Signal | Source | Path |
|---|---|---|
| Host CPU/memory/disk | node_exporter (nix-darwin) | `VMStaticScrape` → vmagent → metrics.68cc.io |
| GPU use, power, wired memory | Apple-silicon exporter (mactop/macmon-based; pick during implementation) | same |
| Engine requests/tokens/latency | Engine `/metrics` where present; for oMLX, a small exporter over its usage/admin API, or gateway metrics | same |
| nix apply health | textfile metric (last applied commit + timestamp) | node_exporter |
| Logs | vector on the Mac | logs.68cc.io |

Alerts (VMRules → Alertmanager → Discord) plus a Gatus check on the model
list endpoint:

- Mac unreachable
- engine down
- sustained swap use
- wired memory near limit
- last successful nix apply older than 24h, or applied commit behind main

One Grafana dashboard via `GrafanaDashboard`.

### Failure handling

- **Mac down:** no fallback (D4). Every consumer gets a short *connect*
  timeout, separate from its long read timeout, so nothing waits 600s
  on a dead host.
- **Reboots:** planned via `task mac:reboot` (authrestart); unplanned
  via SSH pre-boot unlock, with Gatus paging. A UPS is recommended.
- **Upgrades:** engine and model versions are pinned and change by PR
  only. Each bump re-runs the eval replay (below) as a regression gate.

## Model selection and bake-off

**Roles:**

| Role | Consumers | What matters |
|---|---|---|
| reasoner | Hindsight retain/reflect | Strict JSON schema output, long context, concurrency 5 |
| agent/coder | argus, atuin | Tool-call accuracy, cached-prefix TTFT |
| chat/fast | HA conversation agent, routing | Low latency, reliable tool use (it exposes a bash tool) |
| embeddings/rerank | only if moved | oMLX supports both |

**Engine bake-off:** oMLX, LM Studio (llmster, MLX runtime), Splash,
vllm-metal. Reference models are Qwen3.6-35B-A3B and Qwen3.8-27B (the
only two Splash supports). One engine at a time on an idle Mac.

**Model bake-off** on the winning engine. Shortlist, re-verified when the
hardware arrives:

| Model | Approx. size | Note |
|---|---|---|
| Qwen3.6-35B-A3B | ~20GB | Likely workhorse |
| Qwen3.8-27B dense | ~17GB | Higher quality, slower |
| Qwen3-Coder-Next 80B-A3B | ~48GB | Can co-reside with 35B-A3B |
| gpt-oss-120b | ~63GB | Viable with a small fast model alongside |
| gpt-oss-20b | ~13GB | Today's production model — the control baseline |

Fit rule: resident set + KV for 5 concurrent requests at realistic
context ≤ ~80GB. Everything else loads on demand.

**Performance metrics:** decode tok/s at c=1 and c=5; TTFT at 0/8K/32K
prefix, cold and cache-hit; peak memory; cold-load time; 1-hour soak
with zero errors. Tooling: a replay script plus `vllm bench serve`
against the OpenAI endpoint.

**Eval corpus:** ~2 weeks of real request/response pairs for argus,
Hindsight, atuin and HA, captured from Omniroute and llama-swap. It
contains personal memory content: it stays on-cluster or on the Mac and
is never committed. Grading:

- Hindsight: schema-valid rate; fact recall vs production outputs
- argus: triage verdict agreement on known incidents
- atuin and argus: tool-call parse success rate
- HA: scripted intent/action set scored against GPT-5.5's answers

**Decision rules:**

- Engine: the simplest engine within ~15% of the best on the weighted
  metrics. A specialty engine is added behind the front door only at
  ≥1.5× on a lane that matters.
- Local-only gate: each consumer cuts over only when the chosen model
  meets or beats today's production result for that consumer.
- HA: must match GPT-5.5 on the scripted set; otherwise its bash tool is
  narrowed before cutover.
- Results go to `docs/ai-history/`; raw prompts never do.

## bigboi decommission and bee rebalance

**Current state:** bigboi carries ~13GiB of requests (Traefik ×2,
Authentik, CNPG operator, CrowdSec, n8n, atuin, Gatus, Alertmanager,
vmagent, HolyClaude, Omniroute, llama-swap, and others). Bee memory
*limits* are already overcommitted (bee-02 98%, bee-03 116%).

**Quorum risk:** with bigboi gone every node runs etcd, so an OOM storm
can cost quorum. Every workload moving off bigboi gets realistic
`requests`, and Talos `kubelet.systemReserved` must cover etcd and the
apiserver on all 3 bees.

**Pinned PVs:**

| PV | Action |
|---|---|
| ai/holyclaude 50Gi | Migrate to bee-03 (D11) |
| ai/omniroute-data 10Gi, ai/omniroute-cliproxyapi-data 1Gi | Migrate (interim gateway; keys and OAuth sessions live only here) |
| services/gatus 200Mi | Migrate (history only; fresh start acceptable) |
| monitoring/data-trivy-server-0 5Gi | Recreate fresh (cache) |
| monitoring/netdata-k8s-state-varlib 1Gi | Delete with netdata |
| ai/llama-swap 50Gi | Delete at cutover |
| ai/ollama 50Gi, ai/data-agent-canvas-0 20Gi, ai/claude-code-workspace 20Gi | Orphans: delete after operator confirmation |

Migration method: Velero restore. Velero already runs file-level
backups of every volume (`deployNodeAgent: true`, `uploaderType: kopia`,
`defaultVolumesToFsBackup: true`), and none of the PVCs above is in
`kubernetes/apps/velero/exclusions/`, so no separate restic job is
needed. Per PVC: take a fresh backup, delete the PVC and pod, restore
with the workload's node affinity pointing at the target bee. The
`WaitForFirstConsumer` binding lands the new hostpath volume on that
node and the node-agent restores the data into it. Rehearse on
`services/gatus` first. Every migrated PVC stays covered by the daily
schedule. Retire the `openebs-hostpath-fast` StorageClass after.

**Dedupe:** remove netdata (redundant with node-exporter, vmagent and
vector). Convert both Traefik DaemonSets to 2-replica Deployments; the
external and internal instances stay separate (security boundary).

**After:** ~40 of 103GiB requested across the bees; capacity 119GiB once
bee-03's BIOS UMA drops from 16GiB.

## Phases

### Phase 0 — now (no Mac needed)

1. Start eval-corpus capture (argus, Hindsight, atuin, HA), stored
   on-cluster.
2. Build the replay/eval harness and the scripted HA intent set.
3. Scaffold `macos/` (Determinate, nix-darwin, sops-nix), PR CI on a
   macOS runner, Renovate nix manager.
4. Bee hardening: `requests` on every workload leaving bigboi; verify
   `kubelet.systemReserved`.
5. Verify Cilium egress masquerade (sets the `pf` allowlist). Rehearse
   a Velero restore of `services/gatus` onto a bee.
6. Drain bigboi's non-AI workloads; migrate pinned PVs; remove netdata;
   convert Traefik to Deployments.
7. Delete orphan PVs after confirmation.

### Phase 1 — Mac bring-up

1. Manual base: FileVault, SSH key, OS auto-updates off, Determinate
   Nix, age key, first `darwin-rebuild`.
2. Enable the pull loop; confirm the apply-health metric.
3. Wired-memory LaunchDaemon, `pmset`, Spotlight exclusions.
4. Observability: exporters, vector, `VMStaticScrape`, VMRules, Gatus,
   dashboard.
5. `pf`, API keys, `mac-inference` Service + EndpointSlice.
6. `task mac:reboot` and the OS-update runbook.

### Phase 2 — Bake-offs

1. Engine bake-off.
2. Model bake-off per role within ~80GB.
3. Eval gate per consumer; results to `docs/ai-history/`.
4. Optional: small-MoE bake-off on the bees (CPU vs iGPU) — decides
   whether `llama-swap-apu` survives.

### Phase 3 — Cutover and decommission

1. Winning engine(s) as pinned nix LaunchDaemons.
2. Repoint Omniroute's local providers to the Mac; repoint Hindsight
   directly to the Mac.
3. Cut consumers over one at a time as each passes its gate; HA last.
4. Remove llama-swap and its PVC, the AMD GPU stack, drm-exporter and
   its rules, and `llama-swap-apu` unless Phase 2.4 justified it.
5. Retire bigboi: cordon/drain, `talosctl reset`, remove from
   `talconfig.yaml`, delete `talos/schematic-dgpu.yaml`, delete the node,
   retire `openebs-hostpath-fast`, clean bigboi/dGPU references
   (HolyClaude affinity, Omniroute sizing comment, drm-exporter rule
   comments, `machine-features.yaml` comment, llama-swap probes).
6. bee-03 BIOS UMA reset — alone, cordoned, after the quorum precheck.
7. Rewrite `kubernetes/apps/ai/CLAUDE.md` (lane rules, consumers, the
   argus policy contradiction disappears) and the root `CLAUDE.md`
   (AI stack, AMD GPU operator, per-node schematics).

### Phase 4 — Gateway replacement (own spec)

Requirements: no request cap below 600s; routes in git; a key per
consumer with usage attribution; Prometheus metrics; routing by model
name to multiple upstreams; no subscription or web-UI scraping. LiteLLM
stays excluded (do-not-relitigate list). Open: whether it runs on the
Mac (fewer hops, serves localhost) or in-cluster (GitOps-native).
Then migrate consumers and retire Omniroute, cliproxyapi and their PVCs.

## Risks

| Risk | Mitigation |
|---|---|
| Local models underperform on agent/reasoning workloads | Per-consumer eval gate; gpt-oss-20b control baseline; cutover is per consumer |
| HA agent's bash tool with a weaker model | Must match GPT-5.5 on scripted set, else narrow the tool first |
| Single point of failure for all LLM work | Accepted (D4); fail-fast connect timeouts; Gatus + alerts; UPS |
| Memory pressure on etcd nodes after bigboi leaves | Real `requests`; `systemReserved`; UMA reclaim on bee-03 |
| Privileged HolyClaude on a control-plane node | Accepted (D11); pinned to bee-03; revisit with OpenClaw |
| Young engines (Splash v1.0, vllm-metal v0.28, oMLX 373 open issues) | Pinned versions; eval replay gates every bump; specialty engines only behind the front door |
| Splash supports two models only | Never the foundation; a fast lane at most |
| oMLX has no `/metrics` | Small exporter or gateway metrics, Phase 1 |

## Sources

- Splash: https://inco.ai/blog/splash/, https://github.com/incoai/splash
- oMLX: https://github.com/jundot/omlx
- vllm-metal: https://vllm.ai/blog/2026-09-22-vllm-metal-v0-28-0
- SiliconBench: https://arxiv.org/html/2609.19169
- LM Studio auth: https://lmstudio.ai/docs/developer/core/authentication
- LM Studio llama.cpp without the M5 tensor API:
  https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/2040
