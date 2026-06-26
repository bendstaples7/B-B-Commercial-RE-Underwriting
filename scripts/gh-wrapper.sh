#!/usr/bin/env bash
# gh-wrapper.sh — Unified auth wrapper for gh CLI
#
# Checks auth sources in order: GH_TOKEN → GITHUB_TOKEN → GITHUB_PAT.
# Uses the first non-empty one, exports it as GH_TOKEN, then execs gh "$@".
# Exits 1 if no token found anywhere.
set -euo pipefail

TOKEN=""

if [[ -n "${GH_TOKEN:-}" ]]; then
    TOKEN="$GH_TOKEN"
elif [[ -n "${GITHUB_TOKEN:-}" ]]; then
    TOKEN="$GITHUB_TOKEN"
elif [[ -n "${GITHUB_PAT:-}" ]]; then
    TOKEN="$GITHUB_PAT"
fi

if [[ -z "$TOKEN" ]]; then
    echo "ERROR: No GitHub token found. Checked GH_TOKEN, GITHUB_TOKEN, GITHUB_PAT. Set one of these env vars." >&2
    exit 1
fi

export GH_TOKEN="$TOKEN"
exec gh "$@"