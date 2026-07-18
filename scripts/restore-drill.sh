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

# Resolve a single rclone source from remote_path.
# Accepts:
#   - object path only: backups/YYYY/MM/DD/file.dump
#   - full path: remote:bucket/object
#   - multi-target: remote:bucket/obj;other:bucket/obj  (prefer primary)
resolve_rclone_source() {
    local remote_path="$1"
    local primary="${RCLONE_REMOTE}:${RCLONE_BUCKET}"
    python3 -c "
import sys
remote_path = sys.argv[1]
primary = sys.argv[2].rstrip('/')
parts = [p.strip() for p in remote_path.split(';') if p.strip()]
if not parts:
    raise SystemExit('empty remote_path')

def is_full(p: str) -> bool:
    # remote:bucket/...  (colon before first slash)
    head = p.split('/', 1)[0]
    return ':' in head

full = [p for p in parts if is_full(p)]
if full:
    for p in full:
        if p == primary or p.startswith(primary + '/'):
            print(p)
            raise SystemExit(0)
    print(full[0])
    raise SystemExit(0)

# Object-path-only (legacy / single-segment) — prepend primary remote:bucket
obj = parts[0].lstrip('/')
if not primary or primary == ':' or primary.endswith(':'):
    raise SystemExit('RCLONE_REMOTE/RCLONE_BUCKET required for object-path remote_path')
print(f'{primary}/{obj}')
" "$remote_path" "$primary"
}

if [[ -n "${REMOTE_METHOD:-}" && "$REMOTE_OK" == "yes" && -n "$REMOTE_PATH" ]]; then
    SOURCE="$(resolve_rclone_source "$REMOTE_PATH")"
    echo "restore-drill: downloading from ${SOURCE}"
    rclone copyto "$SOURCE" "$DRILL_FILE"
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
