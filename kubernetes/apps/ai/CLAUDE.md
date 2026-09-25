# AI namespace

Fully self-hosted AI namespace: no cloud LLM providers for automated workloads. **omniroute** is the gateway (`http://omniroute.ai.svc.cluster.local:20128/v1`), fronting **llama-swap** (dGPU) and **llama-swap-apu**, plus an in-pod **cliproxyapi** sidecar (`127.0.0.1:8317`) that reuses Claude Code's and Codex CLI's own OAuth sessions. **hindsight** is the sole memory layer. Local speech (faster-whisper STT, piper TTS) serves Home Assistant Assist. Current state only; history in `docs/ai-history/`.

## Policies (binding)

- **No cloud LLMs**, with one scoped exception: **HolyClaude** interactive use (Claude subscription via Omniroute) and **OpenCode** inside HolyClaude. It never extends to cron/webhook/automated workloads (argus included). Do not use it as precedent to relitigate the no-cloud policy or the OpenCode rejection. See `docs/ai-history/rejected-decisions.md`.
- **Anthropic (Claude) lane**: `cliproxyapi/claude-*` models, bare or via a combo, are interactive-only, and HolyClaude is the sole consumer. Automated consumers use the OpenAI/Codex lane (`cliproxyapi/gpt-*`) or local models. Enforcement has gaps (Accepted risks); never add a Claude leg to a combo that an automated key uses.
- **Addressing**: Omniroute models are `<provider>/<model>` (`llamaswap/coder-large`, `llamaswapapu/<alias>`, `cliproxyapi/gpt-*`) or a bare combo name (`coding-fast`, `coding-deep`, `debugging`, `advanced`). Each consumer gets its own Omniroute inference key (`sk-...`). LiteLLM SDK clients (Holmes) need an `openai/` prefix (`openai/llamaswap/coder-large`); the bare form fails (#718).
- **New Omniroute connection**: set a `maxWaitMs` override (see Accepted risks) and check the key's model access.

## Currently deployed

- **llama-swap** (dGPU, `bigboi-jms-01`, RX 9070 XT / gfx1201, 16 GiB): Vulkan `unified-vulkan-YYYY-MM-DD` image (bundles `rocm-smi`), `--flash-attn on`. **`gpt-oss-20b` is the sole chat model**, always resident, `ttl: 0`, 5 parallel slots × 32768 tokens (`--ctx-size 163840 --parallel 5`). Aliases `reasoner`/`reasoning`/`coder`/`code-large`/`coder-large`/`frontier`/`frontier-chat` all point to it. Route `llm.68cc.io` (forwardAuth). Truth: `llama-swap/app/configmap.yaml`. History: `docs/ai-history/llama-swap.md`.
- **llama-swap-apu** (`bee-jms-03` Renoir iGPU, BIOS 16 GiB VRAM): always-on, all models co-resident: `qwen3-1.7b` (`fast`/`small`/`router`) and `qwen3.5-4b` (`chat`/`small-chat`). `embed`, `vlm`, and `rerank` were disabled on 2026-09-25 with OpenViking. Cluster-internal only. Re-measure with `rocm-smi` before adding a model. `bee-jms-01`/`-02` are excluded (3 GiB VRAM). History: `docs/ai-history/llama-swap.md`.
- **omniroute** (`omniroute/`): the gateway plus the cliproxyapi sidecar. Debug UI `omniroute.68cc.io` (Authentik forwardAuth). Keys, combos, and connection overrides live in its DB, not git. History: `docs/ai-history/omniroute.md`.
- **hindsight** (`hindsight/`): OCI chart and image 0.10.1. API with in-process worker, plus control plane. Routes (both `traefik-internal`): `hindsight.68cc.io` → API `:8888`, bearer keys only, no forwardAuth; `hindsight-ui.68cc.io` → `:3000`, forwardAuth. In-cluster: `hindsight-api.ai.svc.cluster.local:8888`.
  - Auth: `StaticKeysTenantExtension` ConfigMap, copied verbatim from v0.10.1 (regenerate on chart bump). `HINDSIGHT_API_TENANT_USERS` maps the laptop-claude, holyclaude, and control-plane keys to user `josh`, so all share schema `user_josh`. Routes are `/v1/default/...`.
  - DB: CNPG `postgres17` database `hindsight`; pgvector comes from a CNPG `Database` resource. `hindsight-db-creds` (ns `databases`) must match `postgres-password` in `hindsight-secret`. Rotate both together.
  - LLM: **direct to llama-swap** (`reasoner`), not Omniroute (its 120s cap killed long calls); 600s timeout. Concurrency: global 5, retain 2, consolidation 1, mental-model 1. atuin and argus share the same 5 gpt-oss slots without being counted. Settings: `RETAIN_MAX_COMPLETION_TOKENS=16000`, reasoning `low`, `LLM_STRICT_SCHEMA_RETAIN=true` (soft schema drops fields).
  - Memory Defense redacts sensitive data on every bank via `DEFAULT_BANK_TEMPLATE`. The `relation "public.banks" does not exist` log line is a known, swallowed upstream quirk.
  - Worker durability: stable `HINDSIGHT_API_WORKER_ID=hindsight-api` plus a `Recreate` strategy via `postRenderers`. Keep both, because orphaned `processing` rows wedge the queue. There is no wedged-queue alert yet.
  - Clients: plugin `@vectorize-io/hindsight-coding-agents@0.7.0`, `autoInject: "recall"` (not `reflect`, which times out), `autoUpdate: false`, bank `coding-agent::home-ops`. **Not GitOps-managed**: `~/.hindsight/coding-agent.json` lives on the laptop and on HolyClaude's PVC. Check both copies after plugin maintenance, because `autoUpdate` has flipped back to `true` before.
  - Quirks: `/metrics` and `/docs` are unauthenticated (LAN-only). The 4Gi memory limit is accepted. History: `docs/ai-history/hindsight.md`.
- **holyclaude** (`holyclaude/`): interactive dev workstation, `holyclaude.68cc.io` (forwardAuth, external gateway). Image `docker.io/coderluii/holyclaude` `full` 1.5.7; OpenCode needs `full`.
  - Claude Code goes through Omniroute with the `holyclaude-interactive` key, restricted to combos `coding-fast`/`coding-deep`/`debugging`/`advanced`. The default model is `coding-deep`. Its fallback legs don't work (`gpt-5.5` rejects on request shape, and the local model overflows on context), so it fails closed.
  - `postStart` rewrites `~/.claude/settings.json` (`ANTHROPIC_*` env plus `model`) on every boot, so in-session `/model` changes revert on restart. It also leaves the file **root-owned**, so chown before any in-pod plugin reinstall.
  - Runs as root with `SYS_ADMIN`+`SYS_PTRACE` and an Unconfined seccomp profile; the `ai` namespace is PSA `privileged` for this. It uses `cluster-admin` via SA `holyclaude`, a `kube-mcp` sidecar (`localhost:8081`), a rendered SA kubeconfig, and a `sops-age` key at `/workspace/home-ops`.
  - Single PVC with narrow subPath mounts. Never mount the whole `/home/claude`, because that shadows `~/.local/bin`. Git identity is `BarryBot`. OTel metrics and logs go straight to `metrics.68cc.io`/`logs.68cc.io`. Query them with dotted names (`{"claude_code.session.count"}`); see `docs/runbooks/agent-telemetry.md`. History: `docs/ai-history/holyclaude.md`.
- **argus** (`argus/`): Alertmanager → HolmesGPT (`argus-holmes` subchart) → Discord triage. Incident memory in shared bank `coding-agent::home-ops` (#712). The chart comes from the fork `j0sh3rs/argus` (GitRepository `ref.tag`). Model `openai/llamaswap/coder-large` (LiteLLM prefix, #718), local only (automated). The chart default `modelList.auto` is overwritten field by field, not nulled (Helm ignores null). `cilium`/`hubble`/`helm` toolsets stay off: they overflow the context, so re-check the 32k budget before adding any toolset. The standalone holmesgpt app is retired; its secret now lives at `argus/app/secret-holmesgpt.sops.yaml`. History: `docs/ai-history/argus.md`.
- **atuin-ai-server** (`atuin-ai-server/`): backend for Atuin's `[ai]` feature. It has no auth of its own, so it is LAN-only (`atuin-ai.68cc.io`, internal gateway). It uses Omniroute with its own key (`CHAT_API_KEY`). `default_model = "coder-large"` → the `coding-fast` combo (local only). History: `docs/ai-history/atuin-ai-server.md`.
- **linkwarden-mcp**: read-only MCP, `linkwarden-mcp.68cc.io/mcp` (LAN, no auth; #714/#708).
- **faster-whisper**: `rhasspy/wyoming-whisper:3.3.0`, `tiny-int8`, Wyoming `:10300`. HA needs Wyoming, **not** the OpenAI-HTTP `fedirz/faster-whisper-server`.
- **piper**: `rhasspy/wyoming-piper:2.2.2`, `en_US-lessac-medium`, Wyoming `:10200`. History for both: `docs/ai-history/misc.md`.
- **omega-mcp**: commented out of the kustomization. **Planned**: a kid-safe layer, only if a concrete need arises (`docs/ai-history/misc.md`).

## Retired

- **openviking**: retired 2026-09-25; Hindsight replaces it (`docs/ai-history/openviking.md`).
- **openclaw**: archived 2026-09-24. Revive only with a concrete autonomous use case, pointing its memory at Hindsight (`docs/ai-history/argus.md`, `docs/ai-history/retired-apps.md`).
- **LiteLLM/litellm-operator**: removed 2026-09-08 when Omniroute took over (`docs/ai-history/retired-apps.md`).
- **n8n, OpenCode (standalone), agent-canvas, cognee, kelos**: removed 2026-08-14. **memini**, **ollama**: archived 2026-08-16. LangFuse/AnythingLLM/Open WebUI/Goose/claude-code: 2026-07-01 (`docs/ai-history/retired-apps.md`).

## Accepted risks

Details: `docs/ai-history/omniroute.md`.

- **`/v1/messages` has no auth**: any pod that can reach Omniroute gets free Claude inference, bypassing the lane policy. Accepted for a single-user lab.
- **`blockedModels` can't be set through the API**, because PATCH strips it. The automated keys have `modelAccessMode: "all"`. Lane isolation relies only on no automated combo containing Claude.
- **`maxWaitMs` is an execution deadline**, not a queue wait; the default is 15s. The `llama-swap` connection's `120000` override (the max) lives **only in Omniroute's DB**, not git. Re-apply it after any data reset, and restart Omniroute after any change.

## Do not relitigate

Details: `docs/ai-history/rejected-decisions.md`.

- **Continue.dev / FIM-only models**: rejected; there was no real consumer.
- **AMD GPU Operator in driver-managed mode**: DKMS conflicts, and its features are Instinct-only. The driverless per-node `DeviceConfig`s for `bigboi-jms-01` and `bee-jms-03` are the approved exception; never widen them to `bee-jms-01`/`-02`.
- **ROCm DKMS**: impossible on Talos's immutable rootfs.
- **Replacing llama-swap with Ollama**: duplicate engine; we'd lose GGUF control.
- **LiteLLM as a gateway**: its features were inert here. (Omniroute as the gateway is adopted, not rejected.)
- **OmniRoute browser-scraping mode**: ToS risk. Only CLIProxyAPI CLI-session reuse is allowed.
- **Kelos, n8n, agent-canvas, cognee**: redundant or unused surfaces.
- **Khoj**: no notes habit; stalled upstream.
- **vLLM**: needs ROCm; no gain on APUs.
- **Moving whisper/piper onto llama-swap's audio tools**: they don't speak Wyoming.
