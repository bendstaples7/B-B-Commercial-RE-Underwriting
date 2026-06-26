#!/usr/bin/env bash
# gh-auth-check.sh — GitHub authentication readiness check
#
# Tests all three token env vars (GH_TOKEN, GITHUB_TOKEN, GITHUB_PAT).
# For each found token, validates it against https://api.github.com/user.
# Also checks gh auth status.
# Exits 0 if at least one valid auth method works, 1 otherwise.
set -euo pipefail

VALID_COUNT=0
TESTED_ANY=false

echo "=== GitHub Auth Readiness Check ==="
echo ""

# ---------- Check individual token env vars ----------
for VAR_NAME in GH_TOKEN GITHUB_TOKEN GITHUB_PAT; do
    VALUE="${!VAR_NAME:-}"
    if [[ -z "$VALUE" ]]; then
        echo "  ${VAR_NAME}: x (not set)"
        continue
    fi

    # Mask for display (show first 4 chars)
    MASKED="${VALUE:0:4}..."
    TESTED_ANY=true

    # Test against GitHub API
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: token $VALUE" \
        -H "Accept: application/vnd.github.v3+json" \
        "https://api.github.com/user" 2>/dev/null || echo "000")

    if [[ "$HTTP_STATUS" == "200" ]]; then
        echo "  ${VAR_NAME}: set (${MASKED}) v valid"
        VALID_COUNT=$((VALID_COUNT + 1))
    elif [[ "$HTTP_STATUS" == "401" ]]; then
        echo "  ${VAR_NAME}: set (${MASKED}) x invalid (HTTP 401 - token rejected)"
    elif [[ "$HTTP_STATUS" == "403" ]]; then
        echo "  ${VAR_NAME}: set (${MASKED}) x rate-limited (HTTP 403 - try again later)"
    else
        echo "  ${VAR_NAME}: set (${MASKED}) x error (HTTP ${HTTP_STATUS} - network or API issue)"
    fi
done

echo ""

# ---------- Check gh CLI auth status ----------
echo "--- gh CLI auth status ---"
GH_STATUS=""
GH_STATUS=$(gh auth status 2>&1 || true)
echo "$GH_STATUS" | head -5
echo ""

# ---------- Summary ----------
echo "--- Summary ---"
if [[ "$VALID_COUNT" -gt 0 ]]; then
    echo "v At least one valid auth method found (${VALID_COUNT} valid)."
    exit 0
else
    echo "x No valid auth method found."
    if ! $TESTED_ANY; then
        echo ""
        echo "  What to fix: Set one of these environment variables:"
        echo "    export GH_TOKEN=ghp_..."
        echo "    export GITHUB_TOKEN=ghp_..."
        echo "    export GITHUB_PAT=ghp_..."
        echo ""
        echo "  Or authenticate gh CLI directly:"
        echo "    gh auth login"
    else
        echo ""
        echo "  What to fix: Check that your token is valid and has the right scopes."
        echo "  To create a new token: https://github.com/settings/tokens"
    fi
    exit 1
fi
