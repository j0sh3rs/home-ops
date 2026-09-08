#!/usr/bin/env bash
# headersHelper for the "omniroute" MCP server entry in .mcp.json.
#
# Claude Code's ${VAR} expansion for MCP headers only resolves against the
# OS environment at Claude Code's own process startup -- it does not source
# .env/.env.local, so a mise-managed token in .env.local never actually
# reaches it. headersHelper sidesteps that: Claude Code runs this script
# fresh on every connect/reconnect/401/403 and uses its stdout JSON as the
# request headers, so we just decrypt the live SOPS secret each time
# instead of relying on any derived, syncable-out-of-date copy.
#
# Must print exactly one JSON object to stdout (headers), nothing else.
# Any diagnostic output goes to stderr, which Claude Code ignores.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRET_FILE="kubernetes/apps/ai/omniroute/app/secret.sops.yaml"

# mise resolves KUBECONFIG/SOPS_AGE_KEY_FILE/etc. from .mise.toml relative to
# cwd, and sops's own path (for the file it's decrypting) must also match
# the repo-relative form its .sops.yaml creation/decryption rules expect.
cd "$REPO_ROOT"

TOKEN="$(mise exec -- sops -d "$SECRET_FILE" 2>/dev/null \
  | python3 -c "
import sys, yaml
d = yaml.safe_load(sys.stdin)
print(d['stringData']['OMNIROUTE_MGMT_TOKEN'])
")"

if [ -z "$TOKEN" ]; then
  echo "omniroute-mcp-headers: failed to decrypt OMNIROUTE_MGMT_TOKEN" >&2
  exit 1
fi

TOKEN="$TOKEN" python3 -c "
import json, os
print(json.dumps({'Authorization': 'Bearer ' + os.environ['TOKEN']}))
"
