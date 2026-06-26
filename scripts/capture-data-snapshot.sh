#!/usr/bin/env bash
set -euo pipefail

# capture-data-snapshot.sh
# Captures current DB metrics to backend/data-snapshot.json
# Run after pg_restore to establish a baseline for verify-data-snapshot.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
SNAPSHOT_FILE="$BACKEND_DIR/data-snapshot.json"

# Source DATABASE_URL from backend/.env
if [ -f "$BACKEND_DIR/.env" ]; then
    set -a
    source "$BACKEND_DIR/.env"
    set +a
fi

: "${DATABASE_URL:=postgresql://jeffreyops@localhost:5433/real_estate_analysis}"

if ! command -v psql &>/dev/null; then
    echo "ERROR: psql not found. Install PostgreSQL client."
    exit 1
fi

BEN_USER_EMAIL="ben.d.staples.7@gmail.com"

# Capture metrics
LEAD_COUNT=$(psql "$DATABASE_URL" -t -A -c "SELECT count(*) FROM leads;" 2>/dev/null || echo "0")
USER_COUNT=$(psql "$DATABASE_URL" -t -A -c "SELECT count(*) FROM users;" 2>/dev/null || echo "0")

# Get ben's user_id and lead count
BEN_USER_ID=$(psql "$DATABASE_URL" -t -A -c "SELECT user_id FROM users WHERE email='$BEN_USER_EMAIL' LIMIT 1;" 2>/dev/null || echo "")

if [ -n "$BEN_USER_ID" ]; then
    BEN_LEAD_COUNT=$(psql "$DATABASE_URL" -t -A -c "SELECT count(*) FROM leads WHERE owner_user_id='$BEN_USER_ID';" 2>/dev/null || echo "0")
else
    BEN_LEAD_COUNT=0
fi

# Get all users
USERS_JSON=$(psql "$DATABASE_URL" -t -A -c "SELECT json_agg(json_build_object('id', id, 'user_id', user_id, 'email', email, 'display_name', display_name)) FROM users;" 2>/dev/null || echo "[]")

CHECKED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Build JSON snapshot
cat > "$SNAPSHOT_FILE" <<JSONEOF
{
  "lead_count": $LEAD_COUNT,
  "user_count": $USER_COUNT,
  "ben_lead_count": $BEN_LEAD_COUNT,
  "ben_user_id": "$BEN_USER_ID",
  "ben_user_email": "$BEN_USER_EMAIL",
  "user_ids": $USERS_JSON,
  "checked_at": "$CHECKED_AT"
}
JSONEOF

echo "✅ Snapshot saved to $SNAPSHOT_FILE"
echo "   Leads:     $LEAD_COUNT"
echo "   Users:     $USER_COUNT"
echo "   Ben leads: $BEN_LEAD_COUNT"
echo "   Checked:   $CHECKED_AT"
