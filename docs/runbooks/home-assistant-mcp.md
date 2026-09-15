# Home Assistant MCP + Conversation Agent

**Last updated:** 2026-09-14

---

## What's set up

- **MCP Server integration** (`ha.68cc.io`, HA 2026.9.1) — enabled via UI, exposes `/api/mcp` (bearer-token auth, LLAT). Registered as the `home-assistant` MCP server in `.mcp.json`, using `scripts/home-assistant-mcp-headers.sh` (decrypts `kubernetes/apps/services/home-assistant/app/mcp-secret.sops.yaml` live on every connect — same pattern as `omniroute-mcp-headers.sh`) rather than a static header, since Claude Code doesn't resolve `${VAR}`-style headers for HTTP MCP servers in this container. Endpoint used: the in-cluster URL `http://home-assistant.services.svc.cluster.local:8123/api/mcp` (bypasses Traefik/authentik-forwardAuth entirely — bearer token is the only gate).
- **Conversation agent** — `extended_openai_conversation` (HACS custom integration), upgraded live from stable `2.0.2` to prerelease `3.0.0-beta11` because `2.0.2` pins `openai~=2.21.0`, incompatible with the `openai==2.45.0` HA core already has installed (`RequirementsNotFound` on every setup attempt — this is why the previous configuration attempt was abandoned, leaving a dangling `conversation.ollama_conversation` pipeline reference). Old `2.0.2` backed up in-pod at `/config/custom_components/extended_openai_conversation.beta-backup`.
  - Config entry: **"Omniroute (Codex)"**. `api_key`/`base_url` point at Omniroute's OpenAI-compatible gateway (`http://omniroute.ai.svc.cluster.local:20128/v1`), not real OpenAI — see `kubernetes/apps/services/home-assistant/app/omniroute-secret.sops.yaml`. Model: `cliproxyapi/gpt-5.5`, i.e. Codex/ChatGPT Plus subscription capacity via Omniroute's CLIProxyAPI sidecar (see the `ai-omniroute-revival-plan` memory for the full ToS-risk context this rides on — already knowingly accepted at the project level, HA is just a new consumer of the same mechanism).
  - Omniroute key `home-assistant-conversation` (id `a03fd884-62f5-4e73-a910-b59fadfbd45a`) has `compressionEnabled: false` explicitly patched — Omniroute's default-on compression was found injecting unmarked `ponytail`/`i-have-adhd` output-style content into requests, which has no business being sent to a home-control LLM. Every other existing Omniroute consumer key still has compression **on** — untouched, out of scope for this task, but worth knowing if odd behavior ever shows up elsewhere.
  - Default "Home Assistant" pipeline (`preferred_item` in `.storage/assist_pipeline.pipelines`, i.e. the one actually used by the Assist UI/satellites) has `conversation_engine: conversation.extended_openai_conversation`.

## Known accepted gap — bash tool exposure (not locked down yet)

`extended_openai_conversation`'s auto-generated default system prompt wires up a **literal `bash` tool function** (plus `load_skill`, `execute_services`, `get_attributes`) that lets the configured model run arbitrary shell commands in a "workspace" inside the HA container, triggered by natural-language conversation — not just entity control. This is the integration's out-of-the-box default; nothing here was added or restricted.

**Decision (2026-09-14):** left as-is for now — acceptable while this is being evaluated, not yet meant to be relied on as hardened.

**Follow-up task, not started:** review and lock down the `functions` config on the `conversation` subentry (entry `01M2G8G1SY3HZ0S71RXPDWJ6CG`, subentry `01M2G8G1SYK4JN6J16HDQ93EGK`) before treating this as production — likely means removing/scoping the `bash` and `load_skill` functions, or at minimum understanding what filesystem path `extended_openai.working_directory()` actually resolves to and what's reachable from it. A GitHub issue should track this but couldn't be filed here — `gh auth status` is currently failing (`GITHUB_TOKEN` invalid/expired), same root cause as the GitHub MCP server connection failure noted elsewhere this session. File one once that token's fixed.
