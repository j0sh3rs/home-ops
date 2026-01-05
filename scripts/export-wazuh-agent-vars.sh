#!/usr/bin/env bash
set -xeuo pipefail

# Wazuh Agent Variables Export Script
# Extracts Wazuh agent configuration from SOPS-encrypted secrets
# and outputs bash-compatible variables for .env file

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SECRET_FILE="$PROJECT_ROOT/kubernetes/apps/security/wazuh/app/secret.sops.yaml"

# Wazuh Configuration
WAZUH_MANAGER="${WAZUH_MANAGER:-192.168.35.18}"
WAZUH_AGENT_NAME="${WAZUH_AGENT_NAME:-udm-pro}"

echo "==> Extracting Wazuh Agent Variables from SOPS"
echo ""

# Check if SOPS is available
if ! command -v sops &> /dev/null; then
    echo "Error: sops is not installed. Please install it first." >&2
    exit 1
fi

# Check if secret file exists
if [ ! -f "$SECRET_FILE" ]; then
    echo "Error: Secret file not found at $SECRET_FILE" >&2
    exit 1
fi

echo "==> Decrypting secrets..."

# Extract registration password
WAZUH_REGISTRATION_PASSWORD=$(sops -d "$SECRET_FILE" | grep 'wazuhAuthdPass:' | awk '{print $2}')
if [ -z "$WAZUH_REGISTRATION_PASSWORD" ]; then
    echo "Error: Failed to extract WAZUH_REGISTRATION_PASSWORD" >&2
    exit 1
fi

# Extract certificates (these will be multi-line)
WAZUH_ROOT_CA=$(sops -d "$SECRET_FILE" | grep 'indexerRootCaPem:' | sed 's/^.*indexerRootCaPem: //')
if [ -z "$WAZUH_ROOT_CA" ]; then
    echo "Error: Failed to extract root CA certificate" >&2
    exit 1
fi

WAZUH_NODE_CERT=$(sops -d "$SECRET_FILE" | grep 'indexerNodePem:' | sed 's/^.*indexerNodePem: //')
if [ -z "$WAZUH_NODE_CERT" ]; then
    echo "Error: Failed to extract node certificate" >&2
    exit 1
fi

WAZUH_NODE_KEY=$(sops -d "$SECRET_FILE" | grep 'indexerNodeKeyPem:' | sed 's/^.*indexerNodeKeyPem: //')
if [ -z "$WAZUH_NODE_KEY" ]; then
    echo "Error: Failed to extract node private key" >&2
    exit 1
fi

echo "    ✓ All secrets extracted successfully"
echo ""
echo "==> Bash-Compatible Environment Variables (.env format)"
echo ""
echo "# Wazuh Agent Configuration"
echo "# Generated: $(date)"
echo ""
echo "# Manager Configuration"
echo "WAZUH_MANAGER=\"$WAZUH_MANAGER\""
echo "WAZUH_AGENT_NAME=\"$WAZUH_AGENT_NAME\""
echo ""
echo "# Authentication"
echo "WAZUH_REGISTRATION_PASSWORD=\"$WAZUH_REGISTRATION_PASSWORD\""
echo ""
echo "# Certificates (multi-line values)"
echo "WAZUH_ROOT_CA=\"$WAZUH_ROOT_CA\""
echo ""
echo "WAZUH_NODE_CERT=\"$WAZUH_NODE_CERT\""
echo ""
echo "WAZUH_NODE_KEY=\"$WAZUH_NODE_KEY\""
echo ""
echo "# Certificate File Paths (if writing to disk)"
echo "WAZUH_ROOT_CA_PATH=\"/var/ossec/etc/rootCA.pem\""
echo "WAZUH_NODE_CERT_PATH=\"/var/ossec/etc/agent.pem\""
echo "WAZUH_NODE_KEY_PATH=\"/var/ossec/etc/agent-key.pem\""
