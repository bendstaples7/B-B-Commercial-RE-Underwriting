#!/usr/bin/env bash
set -euo pipefail

# verify-data-snapshot.sh
# Compares current DB state against data-snapshot.json
# Fails if lead count drops below 90% of snapshot baseline

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

if [ ! -f "$SNAPSHOT_FILE" ]; then
    echo "FAIL: No snapshot found at $SNAPSHOT_FILE"
    echo "Run ./scripts/capture-data-snapshot.sh after pg_restore"
    exit 1
fi

if ! command -v psql &>/dev/null; then
    echo "ERROR: psql not found"
    exit 1
fi

# Read snapshot
SNAP_LEAD_COUNT=$(python3 -c "import json;print(json.load(open('$SNAPSHOT_FILE'))['lead_count'])")
SNAP_BEN_LEAD_COUNT=$(python3 -c "import json;print(json.load(open('$SNAPSHOT_FILE'))['ben_lead_count'])")
BEN_USER_EMAIL=$(python3 -c "import json;print(json.load(open('$SNAPSHOT_FILE'))['ben_user_email'])")
BEN_USER_ID=$(python3 -c "import json;print(json.load(open('$SNAPSHOT_FILE'))['ben_user_id'])")

# Get current values
CUR_LEAD_COUNT=$(psql "$DATABASE_URL" -t -A -c "SELECT count(*) FROM leads;" 2>/dev/null || echo "0")
CUR_BEN_LEAD_COUNT=$(psql "$DATABASE_URL" -t -A -c "SELECT count(*) FROM leads WHERE owner_user_id='$BEN_USER_ID';" 2>/dev/null || echo "0")

# Thresholds
LEAD_THRESHOLD=$(echo "$SNAP_LEAD_COUNT * 0.9" | bc | cut -d. -f1)
BEN_THRESHOLD=$(echo "$SNAP_BEN_LEAD_COUNT * 0.9" | bc | cut -d. -f1)

ALL_PASS=true

echo "=== Data Snapshot Verification ==="
echo ""

# Check total leads
if [ "$CUR_LEAD_COUNT" -lt "$LEAD_THRESHOLD" ]; then
    echo "❌ FAIL: Total leads ($CUR_LEAD_COUNT) below 90% of snapshot ($SNAP_LEAD_COUNT, threshold=$LEAD_THRESHOLD)"
    echo "   Run: ./scripts/capture-data-snapshot.sh to update, or restore production dump"
    ALL_PASS=false
else
    echo "✅ PASS: Total leads $CUR_LEAD_COUNT >= threshold $LEAD_THRESHOLD (snapshot: $SNAP_LEAD_COUNT)"
fi

# Check Ben's leads
if [ "$CUR_BEN_LEAD_COUNT" -lt "$BEN_THRESHOLD" ]; then
    echo "❌ FAIL: Ben's leads ($CUR_BEN_LEAD_COUNT) below 90% of snapshot ($SNAP_BEN_LEAD_COUNT, threshold=$BEN_THRESHOLD)"
    echo "   Check if owner_user_id mapping changed or data was lost"
    ALL_PASS=false
else
    echo "✅ PASS: Ben's leads $CUR_BEN_LEAD_COUNT >= threshold $BEN_THRESHOLD (snapshot: $SNAP_BEN_LEAD_COUNT)"
fi

echo ""

if [ "$ALL_PASS" = true ]; then
    echo "✅ All data snapshot checks passed."
    exit 0
else
    echo "❌ Some checks failed. Restore the production dump and re-capture the snapshot."
    exit 1
fi
