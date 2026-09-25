# Retired AI apps

History moved verbatim from `kubernetes/apps/ai/CLAUDE.md` on 2026-09-25 (#710); current state lives in that file.

## n8n, OpenCode, agent-canvas, cognee, kelos, LiteLLM (2026-08-14 / 2026-09-08)

**n8n, OpenCode, agent-canvas, cognee, and the kelos-system namespace** (Kelos + its GitHub-issue-spawner agents) **were removed 2026-08-14** — collapsing multiple overlapping code-agent surfaces down to openclaw alone (OpenCode later returned as a scoped, interactive-only exception inside holyclaude — see "Decisions explicitly rejected" below). **LiteLLM and OmniRoute were also removed that same day, but the removal did not stick.** OmniRoute was revived 2026-09-07 using a materially different mechanism than the one originally rejected (`docs/superpowers/specs/2026-09-07-omniroute-revival-design.md` — CLIProxyAPI CLI-session reuse, not the earlier Playwright/Chromium browser-scraping approach), then switched over 2026-09-08 to be the live AI-namespace gateway fronting both llama-swap instances plus the cliproxyapi sidecar (`docs/superpowers/specs/2026-09-08-omniroute-phase2-switchover-design.md`). **LiteLLM and litellm-operator were fully removed as part of that same Phase 2 switchover** (not kept as cold standby, per `kubernetes/apps/ai/kustomization.yaml`'s own header comment) — every consumer that previously routed through LiteLLM (openviking, argus, atuin-ai-server) now routes through Omniroute instead, and there is no `kubernetes/apps/ai/litellm/` directory left in this repo. See the "Decisions explicitly rejected" section's OmniRoute and gateway-in-front-of-llama-swap entries for how those two now-reversed rejections are annotated.

## memini (2026-08-16)

**memini (memory/embedding backend, `memini.68cc.io`) was archived 2026-08-16** — its own plugin extension threw a command-registration error on every openclaw boot ("Command name must start with a letter..."), and the wiki-vault rendering built on top of it (`memory-wiki` plugin) went with it. `memory-core` stays explicitly disabled rather than silently becoming the default backend; the `openviking` plugin (`@openviking/openclaw-plugin` from ClawHub) claims `plugins.slots.memory` instead, live since shortly after memini's removal — see `archive/memini/` and the openclaw bullet below.

## LangFuse, AnythingLLM, Open WebUI, Goose, claude-code (2026-07-01)

LangFuse (observability), AnythingLLM (RAG), Open WebUI (chat UI), and Goose (code automation agent) were removed 2026-07-01 — unused, no consumers beyond a chat UI nobody used; see `docs/runbooks/anythingllm-role-and-overlap.md` and `archive/{langfuse,anythingllm,open-webui,goose}/` if reuse is considered later. claude-code (headless code-automation engine, daemon + runner Job template) was also removed 2026-07-01.

## openclaw (2026-09-24, #711)

- **openclaw** — **archived 2026-09-24 (#711)** to `archive/openclaw/`. Never actually deployed under the current config; see "Decision record: openclaw and argus (#711)" below.
