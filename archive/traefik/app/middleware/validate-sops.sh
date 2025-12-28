#!/usr/bin/env bash
# Pre-commit hook to validate SOPS encryption for sensitive files
# Add to .git/hooks/pre-commit or use with pre-commit framework

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "Checking for unencrypted secrets..."

# Find all .sops.yaml files
SOPS_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.sops\.ya\?ml$' || true)

if [ -z "$SOPS_FILES" ]; then
    echo -e "${GREEN}✓ No SOPS files to check${NC}"
    exit 0
fi

UNENCRYPTED_FILES=()
PLACEHOLDER_FILES=()

for file in $SOPS_FILES; do
    if [ -f "$file" ]; then
        # Check if file is encrypted (contains sops: metadata)
        if ! grep -q "sops:" "$file" 2>/dev/null; then
            UNENCRYPTED_FILES+=("$file")
        fi

        # Check for placeholder values
        if grep -q "YOUR_CLIENT_SECRET_HERE_REPLACE_ME\|REPLACE_ME\|CHANGEME\|TODO" "$file" 2>/dev/null; then
            PLACEHOLDER_FILES+=("$file")
        fi
    fi
done

# Report findings
if [ ${#UNENCRYPTED_FILES[@]} -gt 0 ]; then
    echo -e "${RED}✗ ERROR: Found unencrypted SOPS files:${NC}"
    printf '%s\n' "${UNENCRYPTED_FILES[@]}"
    echo ""
    echo "Encrypt these files before committing:"
    echo "  sops -e -i <filename>"
    echo ""
    exit 1
fi

if [ ${#PLACEHOLDER_FILES[@]} -gt 0 ]; then
    echo -e "${YELLOW}⚠ WARNING: Found placeholder values in:${NC}"
    printf '%s\n' "${PLACEHOLDER_FILES[@]}"
    echo ""
    echo "Replace placeholder values before committing!"
    echo ""
    # Allow commit but warn
fi

echo -e "${GREEN}✓ All SOPS files are properly encrypted${NC}"
exit 0
