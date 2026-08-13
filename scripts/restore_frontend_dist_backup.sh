#!/usr/bin/env bash
# Restore /home/deploy/frontend-dist-backup and refresh SPA perms/fingerprint.
#
# Stages a complete tree under a sibling temp path, validates it, then swaps
# into DIST_DIR with rename(2). Never mutates the live tree entry-by-entry.

set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/app}"
BACKUP_DIR="${1:-/home/deploy/frontend-dist-backup}"
DIST_DIR="${2:-frontend/dist}"
FINGERPRINT_FILE="${3:-/home/deploy/spa-dist.fingerprint}"
DEPLOY_MARKER="${SPA_DEPLOY_IN_PROGRESS:-/home/deploy/SPA_DEPLOY_IN_PROGRESS}"

DIST_PARENT="$(dirname "$DIST_DIR")"
DIST_BASENAME="$(basename "$DIST_DIR")"
TMP_DIST="${DIST_PARENT}/.${DIST_BASENAME}.restore.$$"
OLD_DIST="${DIST_PARENT}/.${DIST_BASENAME}.old.$$"
FP_TMP=""

cleanup_temps() {
    rm -rf "$TMP_DIST" 2>/dev/null || true
    if [ -n "$FP_TMP" ]; then
        rm -f "$FP_TMP" 2>/dev/null || true
    fi
}

clear_marker() {
    rm -f "$DEPLOY_MARKER" 2>/dev/null || true
}

on_exit() {
    cleanup_temps
    clear_marker
}
trap on_exit EXIT

cd "$APP_DIR"

if [ ! -d "$BACKUP_DIR" ]; then
    echo "ROLLBACK WARNING: no frontend-dist-backup found — frontend may mismatch backend"
    exit 2
fi

rm -rf "$TMP_DIST" "$OLD_DIST" 2>/dev/null || true
if ! cp -a "$BACKUP_DIR" "$TMP_DIST" 2>/dev/null; then
    echo "ROLLBACK WARNING: frontend dist restore failed (copy)"
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
if [ ! -f "$FP_SCRIPT" ]; then
    echo "ROLLBACK WARNING: spa-dist-fingerprint.sh not found"
    exit 1
fi

FP_TMP="${FINGERPRINT_FILE}.$$.$RANDOM.tmp"
APP_DIR="$APP_DIR" bash "$FP_SCRIPT" write "$TMP_DIST" "$FP_TMP" || {
    echo "ROLLBACK WARNING: spa-dist.fingerprint update failed"
    exit 1
}

# Atomic publish: move live tree aside, then move validated tree into place.
had_old=0
if [ -e "$DIST_DIR" ]; then
    if ! mv "$DIST_DIR" "$OLD_DIST"; then
        echo "ROLLBACK WARNING: frontend dist old-tree move failed"
        exit 1
    fi
    had_old=1
fi
if ! mv "$TMP_DIST" "$DIST_DIR"; then
    if [ "$had_old" -eq 1 ]; then
        mv "$OLD_DIST" "$DIST_DIR" 2>/dev/null || true
    fi
    echo "ROLLBACK WARNING: frontend dist activate failed"
    exit 1
fi
# TMP is now the live DIST_DIR — do not delete it in EXIT cleanup.
TMP_DIST=""

if ! mv -f "$FP_TMP" "$FINGERPRINT_FILE"; then
    # Prefer putting the previous tree back over leaving a new tree with stale FP.
    if [ "$had_old" -eq 1 ] && [ -d "$OLD_DIST" ]; then
        rm -rf "$DIST_DIR" 2>/dev/null || true
        mv "$OLD_DIST" "$DIST_DIR" 2>/dev/null || true
    elif [ "$had_old" -eq 0 ]; then
        # No prior tree — remove the new one so we do not leave FP/dist mismatch.
        rm -rf "$DIST_DIR" 2>/dev/null || true
    fi
    echo "ROLLBACK WARNING: spa-dist.fingerprint swap failed"
    exit 1
fi
FP_TMP=""

rm -rf "$OLD_DIST" 2>/dev/null || true

echo "Frontend dist backup restored."
