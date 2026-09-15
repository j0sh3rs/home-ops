#!/usr/bin/env bash
# headersHelper for the "home-assistant" MCP server entry in .mcp.json.
#
# Same rationale as scripts/omniroute-mcp-headers.sh: Claude Code's ${VAR}
# expansion for MCP headers doesn't source .env/.env.local, so a static
# header referencing a mise-managed env var never actually resolves.
# headersHelper sidesteps that by decrypting the live SOPS secret on every
# connect/reconnect/401/403 instead.
#
# Must print exactly one JSON object to stdout (headers), nothing else.
# Any diagnostic output goes to stderr, which Claude Code ignores.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRET_FILE="kubernetes/apps/services/home-assistant/app/mcp-secret.sops.yaml"

cd "$REPO_ROOT"

TOKEN="$(mise exec -- sops -d "$SECRET_FILE" 2>/dev/null \
  | python3 -c "
import sys, yaml
d = yaml.safe_load(sys.stdin)
print(d['stringData']['HOMEASSISTANT_LLAT'])
")"

if [ -z "$TOKEN" ]; then
  echo "home-assistant-mcp-headers: failed to decrypt HOMEASSISTANT_LLAT" >&2
  exit 1
fi

TOKEN="$TOKEN" python3 -c "
import json, os
print(json.dumps({'Authorization': 'Bearer ' + os.environ['TOKEN']}))
"
