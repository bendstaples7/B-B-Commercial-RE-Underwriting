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

DIST_PARENT="$(dirname "$DIST_DIR")"
DIST_BASENAME="$(basename "$DIST_DIR")"
TMP_DIST="${DIST_PARENT}/.${DIST_BASENAME}.restore.$$"
rm -rf "$TMP_DIST" 2>/dev/null || true
if ! cp -r "$BACKUP_DIR" "$TMP_DIST" 2>/dev/null; then
    rm -rf "$TMP_DIST" 2>/dev/null || true
    echo "ROLLBACK WARNING: frontend dist restore failed"
    exit 1
fi

ENSURE_SCRIPT=/home/deploy/ensure_frontend_dist_readable.sh
if [ ! -f "$ENSURE_SCRIPT" ]; then
    ENSURE_SCRIPT="$APP_DIR/scripts/ensure_frontend_dist_readable.sh"
fi
if [ -f "$ENSURE_SCRIPT" ]; then
    bash "$ENSURE_SCRIPT" "$TMP_DIST" || {
        echo "ROLLBACK WARNING: frontend dist perms fix failed"
        exit 1
    }
else
    chmod -R a+rX "$TMP_DIST" 2>/dev/null || {
        echo "ROLLBACK WARNING: frontend dist chmod failed"
        exit 1
    }
fi

FP_SCRIPT=/home/deploy/spa-dist-fingerprint.sh
if [ ! -f "$FP_SCRIPT" ]; then
    FP_SCRIPT="$APP_DIR/scripts/spa-dist-fingerprint.sh"
fi
FP_TMP="${FINGERPRINT_FILE}.$$.$RANDOM.tmp"
if [ -f "$FP_SCRIPT" ]; then
    APP_DIR="$APP_DIR" bash "$FP_SCRIPT" write "$TMP_DIST" "$FP_TMP" || {
        rm -f "$FP_TMP" 2>/dev/null || true
        echo "ROLLBACK WARNING: spa-dist.fingerprint update failed"
        exit 1
    }
else
    echo "ROLLBACK WARNING: spa-dist-fingerprint.sh not found"
    exit 1
fi
if ! python3 - "$TMP_DIST" "$DIST_DIR" <<'PY'
import os
import shutil
import sys

src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)

for root, dirs, files in os.walk(dst, topdown=False):
    rel = os.path.relpath(root, dst)
    src_root = src if rel == "." else os.path.join(src, rel)
    for name in files:
        if not os.path.exists(os.path.join(src_root, name)):
            os.unlink(os.path.join(root, name))
    for name in dirs:
        if not os.path.exists(os.path.join(src_root, name)):
            shutil.rmtree(os.path.join(root, name))

shutil.copytree(src, dst, dirs_exist_ok=True)
PY
then
    rm -rf "$TMP_DIST" 2>/dev/null || true
    rm -f "$FP_TMP" 2>/dev/null || true
    echo "ROLLBACK WARNING: frontend dist sync failed"
    exit 1
fi
if ! mv -f "$FP_TMP" "$FINGERPRINT_FILE"; then
    rm -f "$FP_TMP" 2>/dev/null || true
    echo "ROLLBACK WARNING: spa-dist.fingerprint swap failed"
    exit 1
fi
rm -rf "$TMP_DIST" 2>/dev/null || true

echo "Frontend dist backup restored."
