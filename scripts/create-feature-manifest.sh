#!/usr/bin/env bash
#
# create-feature-manifest.sh — Feature Manifest Generator
#
# Interactive CLI that prompts for feature details and writes
# feature-manifest.json to the repo root. This manifest powers
# the pre-push gate that prevents pushing incomplete features.
#
# Usage:  ./scripts/create-feature-manifest.sh
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_PATH="${REPO_ROOT}/feature-manifest.json"

echo "=== Feature Manifest Generator ==="
echo "Creates feature-manifest.json at: ${MANIFEST_PATH}"
echo ""

read -r -p "Feature name (e.g. Data Enrichment Scoring): " FEATURE_NAME
[[ -z "${FEATURE_NAME}" ]] && { echo "ERROR: Feature name is required." >&2; exit 1; }

echo ""
echo "Enter new route(s) — one per line. Blank line to finish."
echo "Example: /deals/:id/enrichment"
NEW_ROUTES=()
while true; do
    read -r -p "  Route: " ROUTE
    [[ -z "${ROUTE}" ]] && break
    NEW_ROUTES+=("${ROUTE}")
done

echo ""
echo "Enter navigation entry location(s) — one per line. Blank line to finish."
echo "Example: sidebar > Operations > Enrichment"
NAV_ENTRIES=()
while true; do
    read -r -p "  Entry: " ENTRY
    [[ -z "${ENTRY}" ]] && break
    NAV_ENTRIES+=("${ENTRY}")
done

echo ""
echo "How does a user reach this feature? (step by step — one per line. Blank line to finish.)"
HOW_TO=()
while true; do
    read -r -p "  Step: " STEP
    [[ -z "${STEP}" ]] && break
    HOW_TO+=("${STEP}")
done

# Build JSON
cat > "${MANIFEST_PATH}" <<EOF
{
  "feature_name": "${FEATURE_NAME}",
  "new_routes": [$(for r in "${NEW_ROUTES[@]}"; do echo -n "\"${r}\","; done | sed 's/,$//')],
  "navigation_entries": [$(for e in "${NAV_ENTRIES[@]}"; do echo -n "\"${e}\","; done | sed 's/,$//')],
  "how_user_reaches_feature": [$(for h in "${HOW_TO[@]}"; do echo -n "\"${h}\","; done | sed 's/,$//')],
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "validated": false
}
EOF

echo ""
echo "=== Manifest written to ${MANIFEST_PATH} ==="
echo ""
echo "Summary:"
echo "  Feature:        ${FEATURE_NAME}"
echo "  Routes:         ${#NEW_ROUTES[@]}"
echo "  Nav entries:    ${#NAV_ENTRIES[@]}"
echo "  Steps to reach: ${#HOW_TO[@]}"
echo ""
echo "Reminder: update 'validated' to true once the architecture review passes."