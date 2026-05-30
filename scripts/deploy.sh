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

cd "$APP_DIR"

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
