# AnythingLLM — Removal Rationale (was: Role, Capabilities, Overlap)

**Status (2026-07-01): REMOVED.** This doc records why, for future reference if the underlying idea (RAG over this repo + saved bookmarks) resurfaces.

## What it was supposed to do

AnythingLLM is a per-workspace RAG (retrieval-augmented generation) tool: chunk + embed documents, store vectors, let an LLM answer questions grounded in that corpus. Two workspaces existed (`home-ops`, `linkwarden-bookmarks`), both empty — 0 documents, 0 vectors, 0 chats. The two n8n workflows meant to feed them (`Linkwarden → AnythingLLM RAG Sync`, `home-ops → AnythingLLM Full Resync`) were wired correctly but left `active: false`, so nothing ever synced.

Infra was fully correct: LiteLLM `local-embed`/`local-rerank` wiring, pgvector on shared CNPG, Authentik forwardAuth, HTTPRoute. The tool wasn't broken. It was unused.

## Why removed instead of trialed

Original plan was a 1-week trial: activate the sync workflows, see if usage justified the app. Reversed after two facts surfaced in the same conversation:

1. **AnythingLLM's only interface is a chat UI** (`anythingllm.68cc.io`). No MCP server mode, no API surface OpenCode or any agent currently calls.
2. **The user does not use generic chat UIs for real tasks** — confirmed independently when deciding to also remove Open WebUI ("I'm much more likely to use OpenCode instead to perform the tasks I need, which aren't generic chat ones anyway"). The same reasoning applies to AnythingLLM's interface: a trial only makes sense if something other than manually opening a browser tab would consume it, and nothing does.

Checked whether OpenCode could reach it via the existing MCP aggregator (mcpjungle, fronted by LiteLLM `/mcp`) — no. AnythingLLM has no MCP server mode; it's a tool-call *target*, not a caller, and nothing in mcpjungle's config registers it. Wiring that up would mean building and hosting an MCP shim around AnythingLLM's raw-text/query API — real net-new work, not a config flip. Not worth doing speculatively.

## What was removed

- `kubernetes/apps/ai/anythingllm/` (app + ks.yaml)
- Entry in `kubernetes/apps/ai/kustomization.yaml`
- `anythingllm-secret`, PVC (30Gi `openebs-hostpath`), HTTPRoute (`anythingllm.68cc.io`)
- n8n workflow files `home-ops/kubernetes/apps/ai/n8n/workflows/{home-ops-full-resync,home-ops-webhook-sync,linkwarden-to-anythingllm}.json` archived (not deleted — see `archive/`), plus live n8n workflows deactivated/removed via n8n API/UI (not git-tracked)
- Doc/README mentions

## If this idea comes back

The genuinely distinct capability AnythingLLM offered — a standing, automation-fed knowledge base (vs. ad-hoc per-chat file attachment) — is still a reasonable thing to want. If so, the shape that fits how this stack is actually used: an MCP server that wraps a RAG backend's query API and gets registered in mcpjungle, so OpenCode can call it as a tool mid-task. That's a different, smaller build than resurrecting AnythingLLM's UI — scope it fresh rather than reactivating this app.

## Related

- `docs/runbooks/ai-stack-tier1-summary.md` — broader AI stack status (needs updating to drop AnythingLLM/Langfuse/Goose/Open WebUI references)
- `docs/runbooks/dragonflydb-db-allocation.md` — DB7 was reserved for AnythingLLM RAG cache, never actually wired; now fully free
- memory `project_ai_stack_determination.md` — original Phase 0+1 determination that kept AnythingLLM; superseded by this removal
