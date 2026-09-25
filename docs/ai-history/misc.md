# Miscellaneous AI namespace history

History moved verbatim from `kubernetes/apps/ai/CLAUDE.md` on 2026-09-25 (#710); current state lives in that file.

## omega-mcp, faster-whisper, piper (as of 2026-09-25)

- **omega-mcp** — MCP server, no LLM backend. (kustomization entry commented out, not currently deployed)
- **faster-whisper** — Speech-to-text (Wyoming protocol, port 10300). `rhasspy/wyoming-whisper:3.3.0`, model `tiny-int8` (Wyoming TCP server HA's Wyoming integration speaks to — NOT the `fedirz/faster-whisper-server` OpenAI-HTTP image, which does not implement Wyoming and silently served nothing). Wired to Home Assistant Assist for STT. First request ~5s; cached afterward.
- **piper** — Text-to-speech (Wyoming protocol, port 10200). `rhasspy/wyoming-piper:2.2.2`. Voice: `en_US-lessac-medium` (1 GiB PVC, ~65MB voice model). Wired to Home Assistant Assist for TTS. First start ~2 min for model download.

## Planned (not yet deployed)

- **Kid-safe layer** — deferred, build only if concrete need arises: a second llama-swap API key scoped via a Traefik middleware path-restriction, or a second llama-swap group, rather than speculative per-kid gateway infrastructure.
