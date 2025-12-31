#!/usr/bin/env bash
set -xeuo pipefail

# Wazuh Agent Remote Installation Script for UDM Pro (Debian Bookworm)
# This script runs on your workstation and installs the Wazuh agent remotely via SSH

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SECRET_FILE="$PROJECT_ROOT/kubernetes/apps/security/wazuh/app/secret.sops.yaml"

# SSH Configuration
UDM_SSH_HOST="${UDM_SSH_HOST:-udm}"
UDM_SSH_USER="${UDM_SSH_USER:-root}"

# Wazuh Configuration
WAZUH_MANAGER="192.168.35.18"
WAZUH_AGENT_NAME="${WAZUH_AGENT_NAME:-udm-pro}"

echo "==> Remote Wazuh Agent Installation for UDM Pro"
echo "    SSH Target: $UDM_SSH_USER@$UDM_SSH_HOST"
echo "    Manager IP: $WAZUH_MANAGER"
echo "    Agent Name: $WAZUH_AGENT_NAME"

# Check if SOPS is available locally
if ! command -v sops &> /dev/null; then
    echo "Error: sops is not installed. Please install it first."
    exit 1
fi

# Check if secret file exists
if [ ! -f "$SECRET_FILE" ]; then
    echo "Error: Secret file not found at $SECRET_FILE"
    exit 1
fi

# Test SSH connectivity
echo ""
echo "==> Testing SSH connectivity to UDM Pro..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$UDM_SSH_USER@$UDM_SSH_HOST" "echo 'SSH connection successful'" 2>/dev/null; then
    echo "Error: Cannot connect to $UDM_SSH_USER@$UDM_SSH_HOST"
    echo "Please ensure:"
    echo "  1. UDM Pro is accessible at $UDM_SSH_HOST"
    echo "  2. SSH key is set up for passwordless authentication"
    echo "  3. User has root access on UDM Pro"
    exit 1
fi
echo "    ✓ SSH connection verified"

echo ""
echo "==> Extracting secrets from SOPS-encrypted file..."

# Decrypt and extract the registration password
WAZUH_REGISTRATION_PASSWORD=$(sops -d "$SECRET_FILE" | grep 'wazuhAuthdPass:' | awk '{print $2}')

if [ -z "$WAZUH_REGISTRATION_PASSWORD" ]; then
    echo "Error: Failed to extract WAZUH_REGISTRATION_PASSWORD"
    exit 1
fi

echo "    ✓ Registration password extracted"

# Extract certificates
echo ""
echo "==> Extracting certificates from SOPS-encrypted file..."

WAZUH_ROOT_CA=$(sops -d "$SECRET_FILE" | grep 'indexerRootCaPem:' | sed 's/^.*indexerRootCaPem: //')
if [ -z "$WAZUH_ROOT_CA" ]; then
    echo "Error: Failed to extract root CA certificate"
    exit 1
fi
echo "    ✓ Root CA certificate extracted"

WAZUH_NODE_CERT=$(sops -d "$SECRET_FILE" | grep 'indexerNodePem:' | sed 's/^.*indexerNodePem: //')
if [ -z "$WAZUH_NODE_CERT" ]; then
    echo "Error: Failed to extract node certificate"
    exit 1
fi
echo "    ✓ Node certificate extracted"

WAZUH_NODE_KEY=$(sops -d "$SECRET_FILE" | grep 'indexerNodeKeyPem:' | sed 's/^.*indexerNodeKeyPem: //')
if [ -z "$WAZUH_NODE_KEY" ]; then
    echo "Error: Failed to extract node private key"
    exit 1
fi
echo "    ✓ Node private key extracted"

echo ""
echo "==> Transferring certificates to UDM Pro..."

# Create certificate directory on remote system
ssh "$UDM_SSH_USER@$UDM_SSH_HOST" "mkdir -p /var/ossec/etc"

# Transfer certificates using SSH with piped input
echo "$WAZUH_ROOT_CA" | ssh "$UDM_SSH_USER@$UDM_SSH_HOST" "cat > /var/ossec/etc/rootCA.pem"
echo "    ✓ Root CA certificate transferred"

echo "$WAZUH_NODE_CERT" | ssh "$UDM_SSH_USER@$UDM_SSH_HOST" "cat > /var/ossec/etc/agent.pem"
echo "    ✓ Node certificate transferred"

echo "$WAZUH_NODE_KEY" | ssh "$UDM_SSH_USER@$UDM_SSH_HOST" "cat > /var/ossec/etc/agent-key.pem"
ssh "$UDM_SSH_USER@$UDM_SSH_HOST" "chmod 600 /var/ossec/etc/agent-key.pem"
echo "    ✓ Node private key transferred (permissions set to 600)"

echo ""
echo "==> Executing remote installation on UDM Pro..."

# Base64 encode the password to safely transmit special characters through SSH
# This prevents bash history expansion issues with characters like '!'
WAZUH_REGISTRATION_PASSWORD_B64=$(echo -n "$WAZUH_REGISTRATION_PASSWORD" | base64)

# Execute installation script remotely via SSH
# Password is passed as base64 to avoid shell interpretation issues
ssh "$UDM_SSH_USER@$UDM_SSH_HOST" \
    "WAZUH_MANAGER='$WAZUH_MANAGER' \
     WAZUH_AGENT_NAME='$WAZUH_AGENT_NAME' \
     WAZUH_REGISTRATION_PASSWORD_B64='$WAZUH_REGISTRATION_PASSWORD_B64' \
     bash -s" << 'REMOTE_SCRIPT'

set -euo pipefail

# Decode the base64-encoded password back to plaintext
# This restores the original password with special characters for agent registration
WAZUH_REGISTRATION_PASSWORD=$(echo "$WAZUH_REGISTRATION_PASSWORD_B64" | base64 -d)

# echo "==> Installing prerequisites..."
# apt-get update
# apt-get install -y gnupg apt-transport-https

# echo ""
# echo "==> Adding Wazuh GPG key..."
# curl -s https://packages.wazuh.com/key/GPG-KEY-WAZUH | \
#     gpg --no-default-keyring --keyring gnupg-ring:/usr/share/keyrings/wazuh.gpg --import
# chmod 644 /usr/share/keyrings/wazuh.gpg

# echo ""
# echo "==> Adding Wazuh repository..."
# echo "deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/4.x/apt/ stable main #" | \
#    tee -a /etc/apt/sources.list.d/wazuh.list

echo ""
echo "==> Updating package lists..."
apt-get update

echo ""
echo "==> Installing Wazuh agent..."
# Install with manager IP and registration password
WAZUH_MANAGER="$WAZUH_MANAGER" \
WAZUH_AGENT_NAME="$WAZUH_AGENT_NAME" \
WAZUH_REGISTRATION_PASSWORD="$WAZUH_REGISTRATION_PASSWORD" \
    apt-get install -y wazuh-agent

echo ""
echo "==> Configuring Wazuh agent..."

# Verify the configuration
if grep -q "<address>$WAZUH_MANAGER</address>" /var/ossec/etc/ossec.conf; then
    echo "    ✓ Manager address configured correctly"
else
    echo "    Warning: Manager address not found in config, updating..."
    sed -i "s|<address>.*</address>|<address>$WAZUH_MANAGER</address>|g" /var/ossec/etc/ossec.conf
fi

# Enable and start the agent
echo ""
echo "==> Enabling and starting Wazuh agent service..."
systemctl daemon-reload
systemctl enable wazuh-agent
systemctl start wazuh-agent

# Wait a moment for the service to start
sleep 3

echo ""
echo "==> Checking agent status..."
systemctl status wazuh-agent --no-pager || true

REMOTE_SCRIPT

echo ""
echo "==> Verifying agent connectivity..."

# Check if agent connected to manager
if ssh "$UDM_SSH_USER@$UDM_SSH_HOST" "grep -q 'Connected to the server' /var/ossec/logs/ossec.log 2>/dev/null"; then
    echo "    ✓ Agent successfully connected to manager"
else
    echo "    ⚠ Agent connection not yet confirmed (may take a few moments)"
fi

echo ""
echo "==> Wazuh agent remote installation complete!"
echo ""
echo "    Target: $UDM_SSH_USER@$UDM_SSH_HOST"
echo "    Manager: $WAZUH_MANAGER"
echo "    Agent Name: $WAZUH_AGENT_NAME"
echo ""
echo "To check agent status remotely:"
echo "    ssh $UDM_SSH_USER@$UDM_SSH_HOST 'systemctl status wazuh-agent'"
echo ""
echo "To view agent logs remotely:"
echo "    ssh $UDM_SSH_USER@$UDM_SSH_HOST 'tail -f /var/ossec/logs/ossec.log'"
echo ""
echo "To verify connection to manager:"
echo "    ssh $UDM_SSH_USER@$UDM_SSH_HOST \"grep 'Connected to the server' /var/ossec/logs/ossec.log\""
echo ""
echo "To reinstall, simply run this script again with the same environment variables."
echo ""
