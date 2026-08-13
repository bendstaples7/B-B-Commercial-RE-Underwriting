#!/usr/bin/env bash
# Restore /home/deploy/frontend-dist-backup and refresh SPA perms/fingerprint.

set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/app}"
BACKUP_DIR="${1:-/home/deploy/frontend-dist-backup}"
DIST_DIR="${2:-frontend/dist}"
FINGERPRINT_FILE="${3:-/home/deploy/spa-dist.fingerprint}"
DEPLOY_MARKER="${SPA_DEPLOY_IN_PROGRESS:-/home/deploy/SPA_DEPLOY_IN_PROGRESS}"

clear_marker() {
    rm -f "$DEPLOY_MARKER" 2>/dev/null || true
}
trap clear_marker EXIT

cd "$APP_DIR"

if [ ! -d "$BACKUP_DIR" ]; then
    echo "ROLLBACK WARNING: no frontend-dist-backup found — frontend may mismatch backend"
    exit 2
fi

if ! rm -rf "$DIST_DIR" || ! cp -r "$BACKUP_DIR" "$DIST_DIR" 2>/dev/null; then
    echo "ROLLBACK WARNING: frontend dist restore failed"
    exit 1
fi

ENSURE_SCRIPT=/home/deploy/ensure_frontend_dist_readable.sh
if [ ! -f "$ENSURE_SCRIPT" ]; then
    ENSURE_SCRIPT="$APP_DIR/scripts/ensure_frontend_dist_readable.sh"
fi
if [ -f "$ENSURE_SCRIPT" ]; then
    bash "$ENSURE_SCRIPT" "$DIST_DIR" || {
        echo "ROLLBACK WARNING: frontend dist perms fix failed"
        exit 1
    }
else
    chmod -R a+rX "$DIST_DIR" 2>/dev/null || {
        echo "ROLLBACK WARNING: frontend dist chmod failed"
        exit 1
    }
fi

FP_SCRIPT=/home/deploy/spa-dist-fingerprint.sh
if [ ! -f "$FP_SCRIPT" ]; then
    FP_SCRIPT="$APP_DIR/scripts/spa-dist-fingerprint.sh"
fi
if [ -f "$FP_SCRIPT" ]; then
    APP_DIR="$APP_DIR" bash "$FP_SCRIPT" write "$DIST_DIR" "$FINGERPRINT_FILE" || {
        echo "ROLLBACK WARNING: spa-dist.fingerprint update failed"
        exit 1
    }
fi

echo "Frontend dist backup restored."
