#!/usr/bin/env bash
# =============================================================================
# scripts/pre-flight-data-check.sh  —  Pre-flight data gate for flask run
#
# Ensures the leads table has enough data before the backend starts.
# If the table is empty/light (< 1 000 rows), attempts an automatic restore
# from ~/prod_for_dev.dump.  Falls through with an error if no dump is found.
#
# Usage:
#   bash scripts/pre-flight-data-check.sh
#
# Exit codes:
#   0 — Data is ready (leads count >= 1000)
#   1 — Data is NOT ready and could not be restored (blocked)
# =============================================================================

set -euo pipefail

# ── Resolve repo root (works regardless of which dir the script is run from) ──
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT}/backend"
ENV_FILE="${BACKEND_DIR}/.env"
DUMP_FILE="${HOME}/prod_for_dev.dump"
MIN_LEADS=1000

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $*"; }
fail() { echo -e "  ${RED}✗${NC} $*"; }
info() { echo -e "  ${YELLOW}→${NC} $*"; }

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Pre-flight data check"
echo "  $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Source DATABASE_URL from .env ────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE" 2>/dev/null
    info "Sourced DATABASE_URL from ${ENV_FILE}"
else
    fail "${ENV_FILE} not found — cannot determine database connection."
    exit 1
fi

# Strip any sqlalchemy +driver suffix for psql compatibility
DB_URL="${DATABASE_URL}"

# ── Step 2: Connect to local PG and count leads ─────────────────────────────
echo "1. Checking leads table..."
LEAD_COUNT=$(psql "${DB_URL}" -tAc "SELECT count(*) FROM leads;" 2>/dev/null || echo "ERROR")

if [[ "$LEAD_COUNT" == "ERROR" ]]; then
    fail "Could not query leads table — is PostgreSQL running?"
    info "Expected DATABASE_URL from ${ENV_FILE} to point to a running instance."
    exit 1
fi

LEAD_COUNT=$(( LEAD_COUNT + 0 ))

if [[ "$LEAD_COUNT" -ge "$MIN_LEADS" ]]; then
    pass "leads table has ${LEAD_COUNT} rows — data is ready."
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  RESULT: Data check passed — ready to start the backend."
    echo "═══════════════════════════════════════════════════════════"
    echo ""
    exit 0
fi

# ── Step 3: Flag as EMPTY — count < 1000 ─────────────────────────────────────
echo ""
echo "2. leads table has only ${LEAD_COUNT} rows (need ${MIN_LEADS}) — flagging as EMPTY."

# ── Step 4: Look for ~/prod_for_dev.dump ─────────────────────────────────────
if [[ ! -f "$DUMP_FILE" ]]; then
    fail "No dump file found at ${DUMP_FILE}."
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────┐"
    echo "  │  ERROR: Database is empty and no restore dump available.   │"
    echo "  │                                                             │"
    echo "  │  To get a fresh production dump:                            │"
    echo "  │                                                             │"
    echo "  │    rsync -avz deploy@<vps-ip>:/home/deploy/backups/ \\"
    echo "  │             latest.dump ~/prod_for_dev.dump                 │"
    echo "  │                                                             │"
    echo "  │  Then re-run this script:                                   │"
    echo "  │    bash scripts/pre-flight-data-check.sh                    │"
    echo "  │                                                             │"
    echo "  └─────────────────────────────────────────────────────────────┘"
    echo ""
    exit 1
fi

pass "Found dump: ${DUMP_FILE} ($(du -h "$DUMP_FILE" | cut -f1))"
echo ""

# ── Step 5: Auto-restore with pg_restore --clean --if-exists ────────────────
echo "3. Restoring database from dump..."
info "Running: pg_restore --clean --if-exists -d \"${DB_URL}\" \"${DUMP_FILE}\""
pg_restore --clean --if-exists -d "${DB_URL}" "${DUMP_FILE}" 2>&1 || {
    fail "pg_restore failed — see output above."
    exit 1
}
pass "pg_restore completed successfully."
echo ""

# ── Step 6: Re-run flask db upgrade ──────────────────────────────────────────
echo "4. Running database migrations..."
cd "${BACKEND_DIR}"
flask db upgrade 2>&1 || {
    fail "flask db upgrade failed."
    exit 1
}
pass "Migrations applied successfully."
cd "${ROOT}"
echo ""

# ── Step 7: Run dedup script after restore ───────────────────────────────────
echo "5. Running dedup script..."
cd "${BACKEND_DIR}"
if python scripts/merge_duplicate_leads.py --mode dedup 2>&1; then
    pass "Dedup script completed."
else
    info "Dedup script completed with non-zero exit — continuing anyway."
fi
cd "${ROOT}"
echo ""

# ── Step 8: Final verification ───────────────────────────────────────────────
echo "6. Verifying leads count after restore..."
NEW_COUNT=$(psql "${DB_URL}" -tAc "SELECT count(*) FROM leads;" 2>/dev/null || echo "ERROR")

if [[ "$NEW_COUNT" == "ERROR" ]]; then
    fail "Could not query leads after restore."
    exit 1
fi

NEW_COUNT=$(( NEW_COUNT + 0 ))

if [[ "$NEW_COUNT" -ge "$MIN_LEADS" ]]; then
    pass "leads table now has ${NEW_COUNT} rows — data is ready."
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  RESULT: Restore successful — ready to start the backend."
    echo "═══════════════════════════════════════════════════════════"
    echo ""
    exit 0
else
    fail "After restore, leads table still has only ${NEW_COUNT} rows (need ${MIN_LEADS})."
    exit 1
fi