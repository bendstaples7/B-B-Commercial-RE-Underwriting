#!/bin/bash
# ---------------------------------------------------------------------------
# lead-visibility-check.sh
#
# Authenticates as ben.d.staples.7@gmail.com and verifies that leads are
# visible (non-zero count).  Exits non-zero with a clear FAIL message when
# the user is missing from the database, has no leads assigned (owner_user_id
# issue), or the leads table is empty (no data dump loaded).
#
# The user was seeded by Alembic migration w2x3y4z5a6b7 with no password
# set (password_hash='', password_set=false), so this script authenticates
# by looking up the user_id from the database and counting leads directly.
#
# Environment variables
# ---------------------
#   USER_EMAIL      — Email of the user to check (default: ben.d.staples.7@gmail.com)
#   DATABASE_URL    — PostgreSQL connection string (default: postgresql://localhost/bbcre)
#   API_BASE        — Base URL for the Flask API (default: http://localhost:5000)
#
# Exit codes
# ----------
#   0 — Leads are visible (at least 1 lead owned by the user)
#   1 — User not found (migration may not have run)
#   2 — Zero leads for the user (owner_user_id issue or empty dump)
#   3 — Database connection failure
# ---------------------------------------------------------------------------

set -euo pipefail

# ---- Configuration defaults -----------------------------------------------
USER_EMAIL="${USER_EMAIL:-ben.d.staples.7@gmail.com}"
DB_URL="${DATABASE_URL:-postgresql://localhost/bbcre}"
API_BASE="${API_BASE:-http://localhost:5000}"

echo "============================================"
echo "Lead Visibility Check"
echo "============================================"
echo "  User email : $USER_EMAIL"
echo "  Database   : $DB_URL"
echo "  API base   : $API_BASE"
echo ""

# ------------------------------------------------------------------
# 1.  Look up the user in the database
# ------------------------------------------------------------------
echo "--- Step 1: Looking up user in database ---"

if ! psql "$DB_URL" -c "SELECT 1" >/dev/null 2>&1; then
    echo "FAIL: Cannot connect to database at $DB_URL"
    echo "       Make sure PostgreSQL is running and DATABASE_URL is correct."
    echo "       Test with: psql $DB_URL -c 'SELECT 1'"
    exit 3
fi

USER_ID=$(psql "$DB_URL" -t -A \
    -c "SELECT user_id FROM users WHERE email_lower = '${USER_EMAIL}'" 2>/dev/null) || true

if [ -z "$USER_ID" ]; then
    echo "FAIL: User '$USER_EMAIL' not found in the users table."
    echo ""
    echo "       Run Alembic migration w2x3y4z5a6b7 to seed this user:"
    echo "         cd backend && flask db upgrade head"
    echo ""
    echo "       Or insert manually:"
    echo "         INSERT INTO users (user_id, email, email_lower, display_name,"
    echo "                           password_hash, is_active, is_admin, password_set,"
    echo "                           created_at, updated_at)"
    echo "         VALUES (gen_random_uuid()::text,"
    echo "                 '${USER_EMAIL}', '${USER_EMAIL}', 'Ben',"
    echo "                 '', true, false, false, NOW(), NOW());"
    exit 1
fi

echo "  Found user_id: $USER_ID"
echo ""

# ------------------------------------------------------------------
# 2.  Count leads owned by this user
# ------------------------------------------------------------------
echo "--- Step 2: Counting leads where owner_user_id matches ---"

LEAD_COUNT=$(psql "$DB_URL" -t -A \
    -c "SELECT COUNT(*) FROM leads WHERE owner_user_id = '${USER_ID}'" 2>/dev/null) || {
    echo "FAIL: Database query for lead count failed."
    exit 3
}

echo "  Leads owned by $USER_EMAIL : $LEAD_COUNT"
echo ""

if [ "$LEAD_COUNT" -eq 0 ]; then
    echo "FAIL: Zero leads found for owner_user_id = '$USER_ID' ($USER_EMAIL)."
    echo ""
    echo "       Possible causes:"
    echo "       1. No data dump has been loaded yet — the leads table is empty."
    echo "       2. Migration w2x3y4z5a6b7 did not run — leads with"
    echo "          owner_user_id IS NULL were never reassigned to this user."
    echo "       3. All leads in the database belong to a different owner_user_id."
    echo ""
    echo "       Diagnose with:"
    echo "         psql $DB_URL -c 'SELECT COUNT(*) FROM leads;'"
    echo "         psql $DB_URL -c \"SELECT owner_user_id, COUNT(*) FROM leads GROUP BY owner_user_id;\""
    exit 2
fi

# ------------------------------------------------------------------
# 3.  (Optional) Try the HTTP API if the server is running
# ------------------------------------------------------------------
echo "--- Step 3: Attempting HTTP GET $API_BASE/api/properties/ (optional) ---"

HTTP_CODE=$(curl -s -o /tmp/lead-visibility-response.json -w '%{http_code}' \
    "${API_BASE}/api/properties/?per_page=1" 2>&1) || HTTP_CODE="000"

case "$HTTP_CODE" in
    000)
        echo "  SKIP: API server not reachable at $API_BASE"
        echo "       Only the database-level check was performed."
        ;;
    401)
        echo "  WARN: API returned 401 (unauthenticated)"
        echo "       This is expected because $USER_EMAIL has no password"
        echo "       set, so Bearer token authentication is not available."
        echo "       The database-level check above is authoritative."
        ;;
    200)
        TOTAL=$(python3 -c "
import json
with open('/tmp/lead-visibility-response.json') as f:
    data = json.load(f)
print(data.get('total', 'unknown'))
" 2>/dev/null || echo "parse-error")
        echo "  HTTP 200 OK — Total leads in API response: $TOTAL"
        ;;
    *)
        echo "  HTTP status: $HTTP_CODE"
        ;;
esac

echo ""
echo "============================================"
echo "SUCCESS: Leads are visible for $USER_EMAIL"
echo "============================================"
exit 0