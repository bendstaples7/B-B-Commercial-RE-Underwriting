#!/usr/bin/env bash
# restore-drill.sh — Verify the latest backup file is restorable (no DB overwrite).
# Downloads from cloud when REMOTE_METHOD is configured; otherwise uses local dump.
#
# VPS location: /home/deploy/restore-drill.sh
# Usage: restore-drill.sh

set -euo pipefail

CONF_FILE="/home/deploy/backup.conf"
# shellcheck source=/home/deploy/backup.conf
source "$CONF_FILE"

RCLONE_REMOTE="${RCLONE_REMOTE:-b2}"
RCLONE_BUCKET="${RCLONE_BUCKET:-}"

MANIFEST="$BACKUP_DIR/backup_manifest.log"
WORKDIR="$(mktemp -d /tmp/restore-drill.XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

LAST_ENTRY="$(python3 -c "
import json
from pathlib import Path
lines = Path('$MANIFEST').read_text().splitlines()
valid = [json.loads(l) for l in lines if l.strip() and json.loads(l).get('integrity')=='valid']
if not valid:
    raise SystemExit('no valid manifest entries')
print(json.dumps(valid[-1]))
")"

FILENAME="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['filename'])" "$LAST_ENTRY")"
REMOTE_OK="$(python3 -c "import json,sys; v=json.loads(sys.argv[1]).get('remote_transferred'); print('yes' if v is True or v == 'true' else 'no')" "$LAST_ENTRY")"
REMOTE_PATH="$(python3 -c "import json,sys; e=json.loads(sys.argv[1]); print(e.get('remote_path') or '')" "$LAST_ENTRY")"
DRILL_FILE="$WORKDIR/$FILENAME"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] restore-drill: target=$FILENAME"

if [[ -n "${REMOTE_METHOD:-}" && "$REMOTE_OK" == "yes" && -n "$REMOTE_PATH" ]]; then
    echo "restore-drill: downloading from ${RCLONE_REMOTE}:${RCLONE_BUCKET}/${REMOTE_PATH}"
    rclone copyto "${RCLONE_REMOTE}:${RCLONE_BUCKET}/${REMOTE_PATH}" "$DRILL_FILE"
else
    LOCAL_FILE="$BACKUP_DIR/$FILENAME"
    if [[ ! -f "$LOCAL_FILE" ]]; then
        echo "ERROR: local backup file missing: $LOCAL_FILE" >&2
        exit 1
    fi
    cp "$LOCAL_FILE" "$DRILL_FILE"
fi

LOCAL_SIZE="$(stat -c '%s' "$DRILL_FILE")"
echo "restore-drill: drill file size=${LOCAL_SIZE}B"

pg_restore --list "$DRILL_FILE" > "$WORKDIR/archive.list"
LIST_LINES="$(wc -l < "$WORKDIR/archive.list")"
echo "restore-drill: pg_restore --list OK ($LIST_LINES TOC entries)"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] restore-drill: PASSED — $FILENAME is restorable"
