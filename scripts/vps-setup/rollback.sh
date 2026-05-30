#!/usr/bin/env bash
# /home/deploy/rollback.sh
# Usage: ./rollback.sh [<commit-hash>]
# Rolls back the application to the specified commit (default: HEAD~1).

set -euo pipefail

APP_DIR="/home/deploy/app"
LOG_FILE="/home/deploy/rollback.log"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

cd "$APP_DIR"

CURRENT_COMMIT=$(git rev-parse HEAD)
TARGET_COMMIT="${1:-$(git rev-parse HEAD~1)}"

echo "[$TIMESTAMP] Rollback initiated: $CURRENT_COMMIT -> $TARGET_COMMIT" | tee -a "$LOG_FILE"

echo "==> (1) Checking if migration downgrade is needed"
# Count only migration files *added* between TARGET and CURRENT (lines starting with "A").
# This must run BEFORE git checkout so we use the current working tree's migration files
# and Alembic env to perform the downgrade.
GIT_DIFF_OUTPUT=$(git diff --name-status "$TARGET_COMMIT" "$CURRENT_COMMIT" \
  -- backend/alembic_migrations/versions/)
NUM_ADDED_MIGRATIONS=$(echo "$GIT_DIFF_OUTPUT" | grep -c '^A' || true)
# grep -c exits 1 when there are zero matches — that's fine (means no migrations added).
# If git diff itself failed, GIT_DIFF_OUTPUT would be empty and we'd skip the downgrade,
# which is the safe default.
if [ "$NUM_ADDED_MIGRATIONS" -gt 0 ]; then
    echo "    $NUM_ADDED_MIGRATIONS migration file(s) added — running flask db downgrade -${NUM_ADDED_MIGRATIONS}"
    cd backend
    FLASK_ENV=production flask db downgrade "-${NUM_ADDED_MIGRATIONS}"
    cd ..
else
    echo "    No migration changes detected — skipping downgrade"
fi

echo "==> (2) Checking out previous commit: $TARGET_COMMIT"
git checkout -B main "$TARGET_COMMIT"

echo "==> (3) Reinstalling Python dependencies"
pip install --user -r backend/requirements.txt

echo "==> (4) Rebuilding frontend"
cd frontend
npm ci
npm run build
cd ..

echo "==> (5) Reloading Gunicorn"
sudo systemctl reload gunicorn

echo "==> (6) Waiting for health check"
sleep 5
for _ in $(seq 1 10); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
      --max-time 10 http://127.0.0.1:5000/api/health || echo "000")
    if [ "$STATUS" = "200" ]; then
        echo "[$TIMESTAMP] Rollback successful: now at $TARGET_COMMIT" | tee -a "$LOG_FILE"
        echo "Health check passed. Rollback complete."
        exit 0
    fi
    sleep 3
done

echo "[$TIMESTAMP] Rollback FAILED: health check did not pass after rollback to $TARGET_COMMIT" \
  | tee -a "$LOG_FILE"
echo "ERROR: Health check failed after rollback. Check journalctl -u gunicorn."
exit 1
