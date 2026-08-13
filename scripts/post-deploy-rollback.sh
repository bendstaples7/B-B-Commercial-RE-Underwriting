#!/usr/bin/env bash
# =============================================================================
# scripts/post-deploy-rollback.sh
# Runs on the VPS after a successful deploy.sh when post-deploy /api/health
# (or SHA verification) fails. Restores the previous SHA + frontend dist backup.
#
# Usage: bash /home/deploy/post-deploy-rollback.sh
#
# Reads /home/deploy/PREVIOUS_DEPLOY_SHA (written by deploy.sh at start).
# =============================================================================

set -euo pipefail
export PATH=$PATH:/home/deploy/.local/bin

APP_DIR="/home/deploy/app"
ROLLBACK_LOG="/home/deploy/rollback.log"
PREV_FILE="/home/deploy/PREVIOUS_DEPLOY_SHA"

cd "$APP_DIR"

if [ ! -f "$PREV_FILE" ]; then
    echo "ERROR: $PREV_FILE missing — cannot determine previous SHA."
    exit 1
fi

PREVIOUS_SHA=$(tr -d '[:space:]' < "$PREV_FILE")
CURRENT_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

if [ -z "$PREVIOUS_SHA" ] || [ "$PREVIOUS_SHA" = "unknown" ]; then
    echo "ERROR: PREVIOUS_DEPLOY_SHA is empty or unknown — no rollback possible."
    exit 1
fi

if [ "$PREVIOUS_SHA" = "$CURRENT_SHA" ]; then
    echo "Already at previous SHA $PREVIOUS_SHA — nothing to roll back."
    exit 0
fi

echo "Post-deploy rollback: $CURRENT_SHA -> $PREVIOUS_SHA"
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Post-deploy rollback: $CURRENT_SHA -> $PREVIOUS_SHA (health/SHA failed)" >> "$ROLLBACK_LOG"

ROLLBACK_FAILED=0
git checkout -- . 2>/dev/null || { echo "ROLLBACK WARNING: git checkout -- . failed"; ROLLBACK_FAILED=1; }
git clean -fd 2>/dev/null || { echo "ROLLBACK WARNING: git clean -fd failed"; ROLLBACK_FAILED=1; }
git checkout "$PREVIOUS_SHA" 2>/dev/null || { echo "ROLLBACK WARNING: git checkout $PREVIOUS_SHA failed"; ROLLBACK_FAILED=1; }
echo "$PREVIOUS_SHA" > "$APP_DIR/DEPLOY_SHA" 2>/dev/null || { echo "ROLLBACK WARNING: could not write DEPLOY_SHA"; ROLLBACK_FAILED=1; }
pip install --user -r backend/requirements.txt -q 2>/dev/null || { echo "ROLLBACK WARNING: pip install failed"; ROLLBACK_FAILED=1; }

if [ -d "/home/deploy/frontend-dist-backup" ]; then
    if ! rm -rf frontend/dist || \
       ! cp -r /home/deploy/frontend-dist-backup frontend/dist 2>/dev/null; then
        echo "ROLLBACK WARNING: frontend dist restore failed"
        ROLLBACK_FAILED=1
    else
        ENSURE_SCRIPT=/home/deploy/ensure_frontend_dist_readable.sh
        if [ ! -f "$ENSURE_SCRIPT" ]; then
            ENSURE_SCRIPT="$APP_DIR/scripts/ensure_frontend_dist_readable.sh"
        fi
        # nginx (www-data) needs other+rx on assets/; mode 0700 blanks the SPA.
        if [ -f "$ENSURE_SCRIPT" ]; then
            if ! bash "$ENSURE_SCRIPT" frontend/dist; then
                echo "ROLLBACK WARNING: frontend dist perms fix failed"
                ROLLBACK_FAILED=1
            fi
        else
            chmod -R a+rX frontend/dist 2>/dev/null || {
                echo "ROLLBACK WARNING: frontend dist chmod failed"
                ROLLBACK_FAILED=1
            }
        fi
        FP_SCRIPT=/home/deploy/spa-dist-fingerprint.sh
        if [ ! -f "$FP_SCRIPT" ]; then
            FP_SCRIPT="$APP_DIR/scripts/spa-dist-fingerprint.sh"
        fi
        if [ -f "$FP_SCRIPT" ]; then
            APP_DIR="$APP_DIR" bash "$FP_SCRIPT" write frontend/dist /home/deploy/spa-dist.fingerprint \
                || { echo "ROLLBACK WARNING: spa-dist.fingerprint update failed"; ROLLBACK_FAILED=1; }
        fi
        rm -f /home/deploy/SPA_DEPLOY_IN_PROGRESS 2>/dev/null || true
    fi
else
    echo "ROLLBACK WARNING: no frontend-dist-backup found — frontend may mismatch backend"
    ROLLBACK_FAILED=1
fi

sudo -n systemctl reload gunicorn 2>/dev/null || { echo "ROLLBACK WARNING: gunicorn reload failed"; ROLLBACK_FAILED=1; }
sudo -n systemctl restart celery 2>/dev/null || true
sudo -n systemctl restart celery-beat 2>/dev/null || true

if [ "$ROLLBACK_FAILED" -eq 0 ]; then
    GUNICORN_READY=0
    for i in $(seq 1 18); do
        HC_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
            --connect-timeout 3 \
            --max-time 5 \
            http://localhost:5000/api/health 2>/dev/null || echo "000")
        echo "localhost health check attempt $i: HTTP $HC_STATUS"
        if [ "$HC_STATUS" = "200" ]; then
            echo "Gunicorn is healthy on localhost."
            GUNICORN_READY=1
            break
        fi
        sleep 2
    done
    if [ "$GUNICORN_READY" = "0" ]; then
        echo "ROLLBACK WARNING: Gunicorn did not become healthy on localhost after ~126s"
        ROLLBACK_FAILED=1
    fi
fi

if [ "$ROLLBACK_FAILED" -eq 0 ]; then
    echo "Post-deploy rollback to $PREVIOUS_SHA complete."
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Post-deploy rollback successful: now at $PREVIOUS_SHA" >> "$ROLLBACK_LOG"
    exit 0
fi

echo "ROLLBACK INCOMPLETE: Some rollback steps failed. Manual intervention required."
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Post-deploy rollback INCOMPLETE for $PREVIOUS_SHA — manual fix needed" >> "$ROLLBACK_LOG"
exit 1
