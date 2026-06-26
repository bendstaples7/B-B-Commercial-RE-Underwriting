#!/usr/bin/env bash
# create-pr.sh — End-to-end PR creation with auth checks
#
# 1. Runs gh-auth-check.sh first (exits with its error message if auth fails)
# 2. Takes args: --title "..." --body "..." or reads body from /tmp/pr-body.md
# 3. Auto-pushes the current branch (git push origin HEAD)
# 4. Creates the PR with gh pr create
# 5. Prints PR URL on success
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------- 1. Auth check ----------
echo ">>> Running auth check..."
if ! bash "$SCRIPT_DIR/gh-auth-check.sh"; then
    echo ""
    echo "ERROR: Auth check failed. Run this to diagnose:"
    echo "  bash scripts/gh-auth-check.sh"
    exit 1
fi
echo ""

# ---------- 2. Parse arguments ----------
TITLE=""
BODY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --title)
            TITLE="$2"
            shift 2
            ;;
        --body)
            BODY="$2"
            shift 2
            ;;
        *)
            echo "ERROR: Unknown argument: $1"
            echo "Usage: $0 --title \"PR Title\" [--body \"PR body text\"]"
            exit 1
            ;;
    esac
done

# If no --body given, try /tmp/pr-body.md
if [[ -z "$BODY" && -f /tmp/pr-body.md ]]; then
    BODY="$(cat /tmp/pr-body.md)"
    echo ">>> Body loaded from /tmp/pr-body.md"
fi

# Validate required args
if [[ -z "$TITLE" ]]; then
    echo "ERROR: --title is required."
    echo "Usage: $0 --title \"PR Title\" [--body \"PR body text\"]"
    exit 1
fi

# ---------- 3. Auto-push current branch ----------
cd "$REPO_DIR"
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo ">>> Pushing branch: $CURRENT_BRANCH"
git push origin HEAD 2>&1 || {
    echo "WARNING: git push failed (non-fatal — continuing to create PR)"
}
echo ""

# ---------- 4. Create the PR ----------
echo ">>> Creating pull request..."
PR_URL=""
PR_URL=$(bash "$SCRIPT_DIR/gh-wrapper.sh" pr create \
    --base main \
    --title "$TITLE" \
    --body "${BODY:-}" \
    2>&1) || {
    echo ""
    echo "ERROR: Failed to create pull request."
    echo "  Possible issues:"
    echo "    • Auth failed — run: bash scripts/gh-auth-check.sh"
    echo "    • Branch conflicts — try rebasing"
    echo "    • Network issues — check your connection"
    echo ""
    echo "  gh output:"
    echo "    $PR_URL"
    exit 1
}

echo ""
echo "✓ Pull request created successfully!"
echo "  URL: $PR_URL"