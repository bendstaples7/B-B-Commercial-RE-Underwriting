#!/usr/bin/env bash
# gh-wrapper.sh — Unified auth wrapper for gh CLI
#
# Checks auth sources in order: GH_TOKEN → GITHUB_TOKEN → GITHUB_PAT.
# Validates each token via the GitHub API before selecting it.
# Uses the first valid one, exports it as GH_TOKEN, then execs gh "$@".
# Exits 1 if no valid token found.
set -euo pipefail

# Helper: validate a GitHub token via the API
_validate_token() {
    local token="$1"
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $token" \
        -H "Accept: application/vnd.github+json" \
        https://api.github.com/user 2>/dev/null) || return 1
    [[ "$status" == "200" ]]
}

TOKEN=""

# Check each source in order, validating before using
if [[ -n "${GH_TOKEN:-}" ]] && _validate_token "$GH_TOKEN"; then
    TOKEN="$GH_TOKEN"
elif [[ -n "${GITHUB_TOKEN:-}" ]] && _validate_token "$GITHUB_TOKEN"; then
    TOKEN="$GITHUB_TOKEN"
elif [[ -n "${GITHUB_PAT:-}" ]] && _validate_token "$GITHUB_PAT"; then
    TOKEN="$GITHUB_PAT"
fi

if [[ -z "$TOKEN" ]]; then
    echo "ERROR: No valid GitHub token found. Checked GH_TOKEN, GITHUB_TOKEN, GITHUB_PAT. Set one of these env vars to a valid token." >&2
    exit 1
fi

export GH_TOKEN="$TOKEN"
exec gh "$@"