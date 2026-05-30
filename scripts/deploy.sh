#!/usr/bin/env bash
# =============================================================================
# scripts/deploy.sh
# Runs on the VPS during CI/CD deployment.
# Called by .github/workflows/deploy.yml via SSH.
#
# Usage: bash /home/deploy/app/scripts/deploy.sh <TARGET_SHA>
# =============================================================================

set -euo pipefail
export PATH=$PATH:/home/deploy/.local/bin

TARGET_SHA="${1:?TARGET_SHA argument is required}"
APP_DIR="/home/deploy/app"
ROLLBACK_LOG="/home/deploy/rollback.log"

cd "$APP_DIR"

# ── Capture current SHA for rollback ─────────────────────────────────────────
PREVIOUS_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

# ── Rollback function — called automatically on any failure ──────────────────
rollback() {
    local exit_code=$?
    if [ "$PREVIOUS_SHA" = "unknown" ] || [ "$PREVIOUS_SHA" = "$TARGET_SHA" ]; then
        echo "ERROR: Deploy failed (exit $exit_code). No rollback possible."
        exit $exit_code
    fi
    echo "ERROR: Deploy failed (exit $exit_code). Rolling back to $PREVIOUS_SHA..."
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Auto-rollback: $TARGET_SHA -> $PREVIOUS_SHA (deploy failed)" >> "$ROLLBACK_LOG"
    ROLLBACK_FAILED=0
    git checkout -- . 2>/dev/null || { echo "ROLLBACK WARNING: git checkout -- . failed"; ROLLBACK_FAILED=1; }
    git checkout "$PREVIOUS_SHA" 2>/dev/null || { echo "ROLLBACK WARNING: git checkout $PREVIOUS_SHA failed"; ROLLBACK_FAILED=1; }
    pip install --user -r backend/requirements.txt -q 2>/dev/null || { echo "ROLLBACK WARNING: pip install failed"; ROLLBACK_FAILED=1; }
    (cd frontend && npm ci --silent 2>/dev/null && npm run build 2>/dev/null) || { echo "ROLLBACK WARNING: frontend build failed"; ROLLBACK_FAILED=1; }
    sudo systemctl reload gunicorn 2>/dev/null || { echo "ROLLBACK WARNING: gunicorn reload failed"; ROLLBACK_FAILED=1; }
    if [ "$ROLLBACK_FAILED" -eq 0 ]; then
        echo "Rollback to $PREVIOUS_SHA complete."
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Rollback successful: now at $PREVIOUS_SHA" >> "$ROLLBACK_LOG"
    else
        echo "ROLLBACK INCOMPLETE: Some rollback steps failed. Manual intervention required."
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Rollback INCOMPLETE for $PREVIOUS_SHA — manual fix needed" >> "$ROLLBACK_LOG"
    fi
    exit $exit_code
}
trap rollback ERR

# ── Pre-deploy VPS health checks ─────────────────────────────────────────────
echo "==> Pre-deploy checks"

# Check gunicorn is running
systemctl is-active --quiet gunicorn || { echo "FAILED: gunicorn is not active before deploy"; exit 1; }
echo "    gunicorn: active"

# Check PostgreSQL is running
systemctl is-active --quiet postgresql || { echo "FAILED: postgresql is not active before deploy"; exit 1; }
echo "    postgresql: active"

# Check disk space (require at least 1GB free)
FREE_KB=$(df /home/deploy --output=avail | tail -1 | tr -d ' ')
if [ "$FREE_KB" -lt 1048576 ]; then
    echo "FAILED: Less than 1GB disk space available (${FREE_KB}KB free)"
    exit 1
fi
echo "    disk space: ${FREE_KB}KB free (OK)"

# ── Deploy steps ─────────────────────────────────────────────────────────────
echo "==> (1) Discard local changes and checkout SHA: $TARGET_SHA"
git checkout -- . || { echo "FAILED: git reset local changes"; exit 1; }
git fetch origin main || { echo "FAILED: git fetch"; exit 1; }
git checkout "$TARGET_SHA" || { echo "FAILED: git checkout $TARGET_SHA"; exit 1; }
echo "    Checked out $TARGET_SHA"

echo "==> (2) Install Python dependencies"
pip install --user -r backend/requirements.txt -q || { echo "FAILED: pip install"; exit 1; }
echo "    Python dependencies installed"

echo "==> (3) Build frontend"
cd frontend
npm ci || { echo "FAILED: npm ci"; exit 1; }
npm run build || { echo "FAILED: npm run build"; exit 1; }
cd ..
echo "    Frontend built"

echo "==> (4) Run database migrations"
cd backend
set -a
# shellcheck source=/dev/null
source .env
set +a
FLASK_ENV=production flask db upgrade head || { echo "FAILED: flask db upgrade"; exit 1; }
cd ..
echo "    Migrations applied"

echo "==> (5) Reload Gunicorn (zero-downtime)"
sudo systemctl reload gunicorn || { echo "FAILED: systemctl reload gunicorn"; exit 1; }
echo "    Gunicorn reloaded"

echo "==> Deploy complete: $TARGET_SHA"
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Deploy successful: $PREVIOUS_SHA -> $TARGET_SHA" >> "$ROLLBACK_LOG"
