#!/usr/bin/env bash
# Auth0 OIDC Setup Helper Script
# This script helps you configure Auth0 OIDC authentication for your homelab

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../../.." && pwd)"
SECRET_FILE="${SCRIPT_DIR}/secret.sops.yaml"
OIDC_FILE="${SCRIPT_DIR}/oidc.yaml"

print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

check_dependencies() {
    print_header "Checking Dependencies"

    local missing_deps=()

    if ! command -v sops &> /dev/null; then
        missing_deps+=("sops")
    fi

    if ! command -v kubectl &> /dev/null; then
        missing_deps+=("kubectl")
    fi

    if ! command -v age &> /dev/null; then
        missing_deps+=("age")
    fi

    if [ ${#missing_deps[@]} -eq 0 ]; then
        print_success "All dependencies found"
    else
        print_error "Missing dependencies: ${missing_deps[*]}"
        print_info "Please install missing dependencies and try again"
        exit 1
    fi
    echo
}

check_secret_file() {
    print_header "Checking Secret Configuration"

    if [ ! -f "${SECRET_FILE}" ]; then
        print_error "Secret file not found: ${SECRET_FILE}"
        exit 1
    fi

    # Check if file is encrypted
    if grep -q "sops:" "${SECRET_FILE}" 2>/dev/null; then
        print_success "Secret file is encrypted"
        ENCRYPTED=true
    else
        print_warning "Secret file is NOT encrypted"
        ENCRYPTED=false

        # Check if placeholder values exist
        if grep -q "YOUR_CLIENT_SECRET_HERE_REPLACE_ME" "${SECRET_FILE}"; then
            print_error "Client secret still contains placeholder value!"
            print_info "Please update the AUTH0_CLIENT_SECRET in ${SECRET_FILE}"
            print_info "Get your client secret from: https://manage.auth0.com/dashboard/us/68ccio/applications/IEAIPLfa9MizMMtrkdEPtFu3TswAPVA9/settings"
            exit 1
        fi
    fi
    echo
}

update_allowlist() {
    print_header "Updating User Allowlist"

    print_info "Current configuration requires manual update"
    print_info "Edit ${OIDC_FILE}"
    print_info "Update the allowedUsersAndGroups section with your email addresses"
    echo
    print_info "Example:"
    echo "  allowedUsersAndGroups:"
    echo "    - \"email:josh@example.com\""
    echo "    - \"email:josh@users.noreply.github.com\""
    echo

    read -p "Have you updated the allowlist? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_warning "Please update the allowlist before continuing"
        exit 1
    fi
    print_success "Allowlist updated"
    echo
}

encrypt_secret() {
    print_header "Encrypting Secret File"

    if [ "$ENCRYPTED" = true ]; then
        print_info "Secret file is already encrypted"
        read -p "Do you want to re-encrypt? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Skipping encryption"
            echo
            return
        fi
    fi

    print_info "Encrypting ${SECRET_FILE}..."
    cd "${REPO_ROOT}"

    if sops -e -i "${SECRET_FILE}"; then
        print_success "Secret file encrypted successfully"
    else
        print_error "Failed to encrypt secret file"
        exit 1
    fi
    echo
}

verify_auth0_config() {
    print_header "Auth0 Configuration Summary"

    echo "Auth0 Domain: 68ccio.us.auth0.com"
    echo "Client ID: IEAIPLfa9MizMMtrkdEPtFu3TswAPVA9"
    echo "Callback URLs:"
    echo "  - https://dash.68cc.io/oauth2/callback"
    echo "  - https://*.68cc.io/oauth2/callback"
    echo
    echo "Required Social Connections:"
    echo "  - Google (configure at: https://manage.auth0.com/dashboard/us/68ccio/connections/social)"
    echo "  - GitHub (configure at: https://manage.auth0.com/dashboard/us/68ccio/connections/social)"
    echo
    print_warning "Ensure both social connections are enabled for the HomeOps application"
    echo
}

apply_to_cluster() {
    print_header "Applying Configuration to Cluster"

    read -p "Do you want to apply the configuration to your cluster? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Skipping cluster application"
        echo
        return
    fi

    # Check if kubectl is configured
    if ! kubectl cluster-info &> /dev/null; then
        print_error "kubectl is not configured or cluster is not accessible"
        exit 1
    fi

    print_info "Current cluster:"
    kubectl config current-context
    echo

    read -p "Is this the correct cluster? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_warning "Please configure kubectl to point to the correct cluster"
        exit 1
    fi

    print_info "Applying middleware kustomization..."
    cd "${SCRIPT_DIR}"

    if kubectl apply -k .; then
        print_success "Configuration applied successfully"
    else
        print_error "Failed to apply configuration"
        exit 1
    fi
    echo

    # Wait for secret to be created
    print_info "Waiting for secret to be created..."
    if kubectl wait --for=jsonpath='{.data}' --timeout=30s secret/auth0-oidc-credentials -n network 2>/dev/null; then
        print_success "Secret created successfully"
    else
        print_warning "Secret may not be created yet. Check with: kubectl get secret -n network auth0-oidc-credentials"
    fi
    echo
}

show_next_steps() {
    print_header "Next Steps"

    echo "1. Enable Social Connections in Auth0:"
    echo "   - Google: https://manage.auth0.com/dashboard/us/68ccio/connections/social"
    echo "   - GitHub: https://manage.auth0.com/dashboard/us/68ccio/connections/social"
    echo
    echo "2. Test Authentication:"
    echo "   - Apply the middleware to a test service"
    echo "   - Visit the protected URL"
    echo "   - Verify redirect to Auth0 login"
    echo "   - Test Google and GitHub logins"
    echo
    echo "3. Monitor Logs:"
    echo "   kubectl logs -n network -l app.kubernetes.io/name=traefik --tail=100 -f"
    echo
    echo "4. Example HTTPRoute with Auth0:"
    echo "   See examples in ${SCRIPT_DIR}/AUTH0_README.md"
    echo
    print_success "Setup complete!"
}

main() {
    print_header "Auth0 OIDC Setup Helper"

    check_dependencies
    check_secret_file
    verify_auth0_config
    update_allowlist
    encrypt_secret
    apply_to_cluster
    show_next_steps
}

# Run main function
main "$@"
