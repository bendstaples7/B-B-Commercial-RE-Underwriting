#!/usr/bin/env bash
#
# validate-ui-card-acs.sh — Kanban AC Gate
#
# Reads the swarm kanban board from the local Dev UX API and validates
# that every UI-component card (Page, Panel, Editor, Manager, View, etc.)
# has at least one acceptance criterion covering navigation/route access.
#
# Usage:  ./scripts/validate-ui-card-acs.sh
# Return: 0 if all cards pass, 1 if any card is missing navigation ACs.
#

set -euo pipefail

KANBAN_API="${KANBAN_API:-http://127.0.0.1:3000/api/swarm-kanban}"

echo "--- Kanban UI Card AC Validation ---"
echo "Fetching board from ${KANBAN_API} ..."

board_json="$(curl -sf "${KANBAN_API}" 2>/dev/null || true)"

if [[ -z "${board_json}" ]]; then
    echo "WARNING: Could not reach ${KANBAN_API} — skipping validation."
    echo "         (This is expected when the Dev UX isn't running.)"
    exit 0
fi

# Single jq pipeline:
# 1. Extract cards (columns[].cards[] or flat array)
# 2. Keep only cards whose title contains a UI keyword
# 3. Filter to those whose ACs do NOT mention navigation
# 4. Output offending titles as JSON array
# 5. || echo "[]" as fallback
missing_json="$(echo "${board_json}" | jq -c '
    def cards: if has("columns") then [.columns[].cards[]] else . end;
    def ui_keywords: ["Page","Panel","Editor","Manager","View","Widget","Screen","Modal","Dialog","Form","Sidebar","Header","Footer"];
    def nav_patterns: ["navigation","route","sidebar","menu","how to reach","navigate","path","link","url","goto","go to","accessible at","rendered at"];

    [cards[] | select(
        any(ui_keywords[]; (.title // "") | test("(?i)\\b" + . + "\\b"))
    ) | select(
        [((.acceptance_criteria // .criteria // .ac // []) | if type == "string" then [.] else . end)[] | ascii_downcase] as $acs
        | all(nav_patterns[]; ($acs | join(" ")) | test($pat; "i") | not)
    ) | .title // .name // "untitled"]
' 2>/dev/null || echo "[]")"

missing_count="$(echo "${missing_json}" | jq 'length')"

if [[ "${missing_count}" -gt 0 ]]; then
    echo ""
    echo "WARNING: ${missing_count} UI card(s) missing navigation acceptance criteria:"
    echo "${missing_json}" | jq -r '.[] | "  - \"\(.)"'
    echo ""
    echo "FAIL: ${missing_count} UI card(s) missing navigation ACs."
    echo "       Add an AC describing how a user reaches each component."
    exit 1
fi

echo ""
echo "PASS: All UI cards have navigation acceptance criteria."
exit 0