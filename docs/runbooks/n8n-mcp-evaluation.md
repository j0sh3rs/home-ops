# n8n MCP Evaluation (#723)

Evaluated 2026-09-28 from upstream docs and source; nothing was deployed or
enabled on the cluster. n8n here runs `2.40.7`.

## Question

Can workflow authoring for the Vikunja/Omniroute triage pipeline (and future
n8n workflows) happen conversationally instead of hand-building flows in the
n8n UI?

## Option 1: n8n's built-in instance-level MCP server

Available from Settings → Instance-level MCP (owner/admin enables it). An MCP
client authenticates with OAuth2 or an access token, and can:

- search workflows (previews of everything the user can see);
- run and test workflows explicitly marked "Available in MCP" (published
  workflows with a webhook, form, schedule, or chat trigger);
- create and edit workflows and data tables (n8n 2.13.0 onward, so available
  on our 2.40.7).

This is the option that answers the question, at zero extra deployment: no new
container, no separate credential to host beyond the MCP access token. It is
distinct from the older `MCP Server Trigger` node, which only exposes one
workflow's tools to other agents and does not help authoring.

**Considerations for this cluster:**
- `n8n.68cc.io` is internal-only and its editor routes sit behind Authentik
  forwardAuth (only `/webhook*` is exempt). An MCP client must be able to reach
  the MCP endpoint through that gate; forwardAuth is a browser-session flow, so
  a headless client may need an additional exempted route or an in-cluster URL.
  Not tested.
- Enabling MCP and minting its token is a live, security-relevant action on the
  instance and belongs to the instance owner.
- `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` is already set for the triage workflow,
  so workflows an agent authors can read `$env` secrets. Keep that in mind when
  granting an agent edit rights.

## Option 2: czlonkowski/n8n-mcp

A separate Node.js MCP server (`ghcr.io/czlonkowski/n8n-mcp`) that gives an LLM
searchable access to n8n's node-type catalog (parameters, examples, validation)
and, when given `N8N_API_URL` + `N8N_API_KEY`, can create/update/activate
workflows through n8n's REST API. HTTP mode needs `MCP_MODE=http` and a
required `AUTH_TOKEN`; it exposes `/health`. Upstream also documents pairing it
with n8n's official instance-level MCP server.

**Findings:**
- One more container to run (app-template, `services` namespace, internal
  route), plus two more secrets (`AUTH_TOKEN`, an n8n API key).
- Its distinct value is the node catalog and validation, which improves the
  quality of agent-authored workflows. The built-in server covers create/edit
  but not that catalog.
- For a single workflow, hand-writing the triage workflow's JSON export was faster than
  deploying a server. Two bugs in the first draft (wrong HMAC encoding, wrong
  HTTP verb for Vikunja comment creation) came from API facts, not node
  parameters, so a node catalog would not have caught them.

## Recommendation

**Not adopted for this issue.** The criterion is to evaluate and document.

If conversational authoring becomes worthwhile (a second or third workflow),
try Option 1 first: enable instance-level MCP, expose only the workflows that
need it, and resolve the forwardAuth reachability question above. Add
`n8n-mcp` (Option 2) only if agents produce invalid node configurations without
the catalog. If deployed, follow the `vikunja-mcp` (#722) shape: app-template,
`services` namespace, internal-only route, SOPS-encrypted tokens, reloader
annotation.

## Sources

- n8n docs: "Connect to n8n MCP server" and "MCP server tools reference"
  (docs.n8n.io).
- czlonkowski/n8n-mcp: `docs/HTTP_DEPLOYMENT.md`, `.env.example`, README.
