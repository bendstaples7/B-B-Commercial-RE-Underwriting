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
    cd "$APP_DIR"  # Always reset to APP_DIR regardless of where the failure occurred
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
    # Restore the previous frontend/dist backup to avoid a version mismatch:
    # without this, backend would be at PREVIOUS_SHA but frontend/dist would
    # contain the TARGET_SHA build, causing frontend/backend incompatibility.
    if [ -d "/home/deploy/frontend-dist-backup" ]; then
        rm -rf frontend/dist
        cp -r /home/deploy/frontend-dist-backup frontend/dist 2>/dev/null || { echo "ROLLBACK WARNING: frontend dist restore failed"; ROLLBACK_FAILED=1; }
    else
        echo "ROLLBACK WARNING: no frontend-dist-backup found — frontend may be at $TARGET_SHA while backend rolls back to $PREVIOUS_SHA"
        ROLLBACK_FAILED=1
    fi
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

# Check available memory (require at least 300MB free to avoid OOM during deploy)
FREE_MEM_KB=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
if [ "$FREE_MEM_KB" -lt 307200 ]; then
    echo "FAILED: Less than 300MB memory available (${FREE_MEM_KB}KB free). VPS may be under memory pressure."
    exit 1
fi
echo "    memory: ${FREE_MEM_KB}KB available (OK)"

# ── Pre-deploy backup (blocks deploy on failure) ──────────────────────────────
echo "==> (0) Pre-deploy backup"
if [[ ! -e /home/deploy/backup.sh ]]; then
    echo "    WARNING: /home/deploy/backup.sh not found — skipping pre-deploy backup"
    echo "    To enable pre-deploy backups, ensure the deploy workflow has run at least once"
elif [[ ! -x /home/deploy/backup.sh ]]; then
    echo "FAILED: /home/deploy/backup.sh exists but is not executable — check permissions"
    exit 1
else
    /home/deploy/backup.sh --pre-deploy || {
        echo "FAILED: pre-deploy backup failed — aborting deploy (no restore point)"
        echo "--- backup bootstrap error log (if any) ---"
        cat /tmp/backup_bootstrap.log 2>/dev/null || echo "(no bootstrap log found)"
        echo "-------------------------------------------"
        exit 1
    }
    echo "    Pre-deploy backup complete"
fi

# ── Deploy steps ─────────────────────────────────────────────────────────────
echo "==> (1) Discard local changes and checkout SHA: $TARGET_SHA"
git checkout -- . || { echo "FAILED: git reset local changes"; exit 1; }
git fetch origin main || { echo "FAILED: git fetch"; exit 1; }
git checkout "$TARGET_SHA" || { echo "FAILED: git checkout $TARGET_SHA"; exit 1; }
echo "    Checked out $TARGET_SHA"

echo "==> (2) Install Python dependencies"
pip install --user -r backend/requirements.txt -q || { echo "FAILED: pip install"; exit 1; }
echo "    Python dependencies installed"

echo "==> (3) Install frontend (pre-built on CI runner, copied to VPS)"
# The dist/ was built on the GitHub Actions runner (7GB RAM) and copied here
# to avoid OOM kills on the 2GB VPS.
# We back up the current dist before replacing it so rollback can restore it
# and avoid a frontend/backend version mismatch (backend at PREVIOUS_SHA,
# frontend at TARGET_SHA).
# Verify the CI-built dist was copied to the VPS
if [ ! -d "/home/deploy/frontend-dist" ]; then
    echo "FAILED: /home/deploy/frontend-dist not found — CI runner did not copy the build"
    exit 1
fi

# Back up current dist for rollback (only if one exists to protect).
# Clean any stale temp backup first to prevent nested dist/ on retries.
if [ -d "frontend/dist" ]; then
    rm -rf /home/deploy/frontend-dist-backup-new
    cp -r frontend/dist /home/deploy/frontend-dist-backup-new || { echo "FAILED: could not create frontend dist backup — aborting to protect rollback"; exit 1; }
    rm -rf /home/deploy/frontend-dist-backup
    mv /home/deploy/frontend-dist-backup-new /home/deploy/frontend-dist-backup
    echo "    Previous frontend dist backed up for rollback"
fi

# Install new dist
rm -rf frontend/dist
mv /home/deploy/frontend-dist frontend/dist
echo "    Frontend dist installed from CI runner build"

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
