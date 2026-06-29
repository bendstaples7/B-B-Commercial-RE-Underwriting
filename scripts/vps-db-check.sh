#!/usr/bin/env bash
# =============================================================================
# scripts/vps-db-check.sh  —  VPS Database Health Check
#
# Run ON THE VPS as the deploy user.  Reports PostgreSQL health, Alembic
# migration status, and table ownership in a single command.
#
# Usage:
#   bash /home/deploy/app/scripts/vps-db-check.sh
#
# Exit codes:
#   0 — All checks pass
#   1 — One or more checks failed (details printed to stdout)
# =============================================================================

set -euo pipefail

APP_DIR="/home/deploy/app"
BACKEND_DIR="${APP_DIR}/backend"
ENV_FILE="${BACKEND_DIR}/.env"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $*"; }
fail() { echo -e "  ${RED}✗${NC} $*"; }
info() { echo -e "  ${YELLOW}→${NC} $*"; }

ALL_PASS=true

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  VPS Database Health Check"
echo "  $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Check 1: PostgreSQL service ───────────────────────────────────────────────
echo "1. PostgreSQL service"
if systemctl is-active --quiet postgresql; then
    pass "PostgreSQL is running."
else
    fail "PostgreSQL is NOT running."
    ALL_PASS=false
fi

# ── Check 2: PostgreSQL connectivity via DATABASE_URL ─────────────────────────
echo "2. Database connectivity"
set +a
# shellcheck source=/dev/null
source "$ENV_FILE" 2>/dev/null && set -a || {
    fail "Cannot source ${ENV_FILE}."
    ALL_PASS=false
}
set -a

if psql "${DATABASE_URL}" -tAc "SELECT 1;" &>/dev/null; then
    DB_VERSION=$(psql "${DATABASE_URL}" -tAc "SELECT version();" 2>/dev/null | head -1 | cut -d',' -f1)
    pass "Connected to PostgreSQL: ${DB_VERSION:-unknown}"
else
    fail "Cannot connect via DATABASE_URL."
    ALL_PASS=false
fi

# ── Check 3: Database size ────────────────────────────────────────────────────
echo "3. Database size"
DB_SIZE=$(psql "${DATABASE_URL}" -tAc "
    SELECT pg_size_pretty(pg_database_size(current_database()));
" 2>/dev/null || echo "unknown")
pass "Database size: ${DB_SIZE}"

# ── Check 4: Connection count ─────────────────────────────────────────────────
echo "4. Active connections"
CONN_COUNT=$(psql "${DATABASE_URL}" -tAc "
    SELECT count(*) FROM pg_stat_activity WHERE state = 'active';
" 2>/dev/null || echo "unknown")
IDLE_COUNT=$(psql "${DATABASE_URL}" -tAc "
    SELECT count(*) FROM pg_stat_activity WHERE state = 'idle';
" 2>/dev/null || echo "unknown")
pass "Active: ${CONN_COUNT}, Idle: ${IDLE_COUNT}"

# ── Check 5: Alembic migration status ────────────────────────────────────────
echo "5. Alembic migration status"
cd "$BACKEND_DIR" 2>/dev/null || { fail "Backend directory not found."; ALL_PASS=false; }

if command -v flask &>/dev/null || [[ -x "${HOME}/.local/bin/flask" ]]; then
    export PATH="${HOME}/.local/bin:${PATH}"
    export FLASK_ENV=production

    CURRENT=$(flask db current 2>&1 || echo "ERROR")
    if [[ "$CURRENT" != "ERROR" ]]; then
        if echo "$CURRENT" | grep -q "(head)"; then
            pass "${CURRENT}"
        else
            warn "${CURRENT}"
            info "Database is not at head — run vps-db-migrate.sh"
            ALL_PASS=false
        fi
    else
        fail "Could not determine Alembic current revision."
        ALL_PASS=false
    fi
else
    fail "flask command not found."
    ALL_PASS=false
fi

# ── Check 6: Table ownership ──────────────────────────────────────────────────
echo "6. Table ownership"
WRONG_OWNER=$(sudo -u postgres psql -tAc \
    "SELECT count(*) FROM pg_tables
     WHERE schemaname = 'public'
       AND tableowner <> 'app_user';" \
    -d "real_estate_analysis" 2>/dev/null || echo "ERROR")

if [[ "$WRONG_OWNER" == "ERROR" ]]; then
    fail "Could not check table ownership."
    ALL_PASS=false
elif [[ "$WRONG_OWNER" -eq 0 ]]; then
    pass "All public tables owned by 'app_user'."
else
    fail "${WRONG_OWNER} table(s) not owned by 'app_user'."
    ALL_PASS=false
fi

# ── Check 7: Table row counts ────────────────────────────────────────────────
echo "7. Table row counts"
psql "${DATABASE_URL}" -c "
SELECT
    schemaname,
    tablename,
    n_live_tup AS estimated_rows
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC
LIMIT 10;
" 2>/dev/null || info "Could not fetch row counts."

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
if [[ "$ALL_PASS" == "true" ]]; then
    echo "  RESULT: All checks passed ✓"
    exit 0
else
    echo "  RESULT: Some checks failed — review output above"
    exit 1
fi
echo "═══════════════════════════════════════════════════════════"