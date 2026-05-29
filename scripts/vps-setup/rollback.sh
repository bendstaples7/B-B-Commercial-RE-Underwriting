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

echo "==> (1) Checking out previous commit: $TARGET_COMMIT"
git checkout "$TARGET_COMMIT"

echo "==> (2) Reinstalling Python dependencies"
pip install --user -r backend/requirements.txt

echo "==> (3) Rebuilding frontend"
cd frontend
npm ci
npm run build
cd ..

echo "==> (4) Checking if migration downgrade is needed"
# If the current (failing) commit added a migration, downgrade by 1
MIGRATION_CHANGED=$(git diff "$TARGET_COMMIT" "$CURRENT_COMMIT" \
  --name-only -- backend/alembic_migrations/versions/ | wc -l)
if [ "$MIGRATION_CHANGED" -gt 0 ]; then
    echo "    Migration files changed — running flask db downgrade -1"
    cd backend
    FLASK_ENV=production flask db downgrade -1
    cd ..
else
    echo "    No migration changes detected — skipping downgrade"
fi

echo "==> (5) Reloading Gunicorn"
sudo systemctl reload gunicorn

echo "==> (6) Waiting for health check"
sleep 5
for i in $(seq 1 10); do
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
