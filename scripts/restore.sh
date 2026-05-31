#!/usr/bin/env bash
# restore.sh — Database Restore Script
# Location: /home/deploy/restore.sh
# Permissions: chmod 750 /home/deploy/restore.sh && chown deploy:deploy /home/deploy/restore.sh
set -euo pipefail

# ── Argument validation ───────────────────────────────────────────────────────
if [[ $# -ne 1 ]]; then
    echo "Usage: restore.sh <backup_filename>" >&2
    exit 1
fi
BACKUP_FILENAME="$1"

# ── Script start ──────────────────────────────────────────────────────────────
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] restore.sh starting — target: $BACKUP_FILENAME"

# ── Load configuration ────────────────────────────────────────────────────────
# Verify backup.conf permissions before sourcing
CONF_STAT="$(stat -c "%a %U:%G" /home/deploy/backup.conf 2>/dev/null)" || {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Cannot stat /home/deploy/backup.conf" >&2
    exit 1
}
if [[ "$CONF_STAT" != "600 deploy:deploy" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: /home/deploy/backup.conf has wrong permissions: $CONF_STAT (expected 600 deploy:deploy)" >&2
    exit 1
fi
# shellcheck source=/home/deploy/backup.conf
source /home/deploy/backup.conf

# ── Manifest lookup ───────────────────────────────────────────────────────────
# Requirement 8.2: abort without modifying database if entry not found
MANIFEST_ENTRY=$(python3 /home/deploy/backup_lib.py lookup-manifest "$BACKUP_DIR/backup_manifest.log" "$BACKUP_FILENAME") || {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: '$BACKUP_FILENAME' not found in manifest — aborting without modifying database" >&2
    exit 1
}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] manifest lookup complete"

# ── Manifest integrity check ──────────────────────────────────────────────────
MANIFEST_INTEGRITY=$(echo "$MANIFEST_ENTRY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('integrity', 'unknown'))")
if [[ "$MANIFEST_INTEGRITY" != "valid" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: manifest entry for '$BACKUP_FILENAME' has integrity='$MANIFEST_INTEGRITY' (not 'valid') — aborting without modifying database" >&2
    exit 1
fi

# ── Checksum verification ─────────────────────────────────────────────────────
# Requirement 8.3: abort with both checksums if mismatch
MANIFEST_SHA256=$(echo "$MANIFEST_ENTRY" | python3 -c "import json,sys; print(json.load(sys.stdin)['sha256'])")
COMPUTED_SHA256=$(sha256sum "$BACKUP_DIR/$BACKUP_FILENAME" | awk '{print $1}')

python3 /home/deploy/backup_lib.py compare-checksums "$MANIFEST_SHA256" "$COMPUTED_SHA256" || {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: checksum mismatch — aborting without modifying database" >&2
    echo "  Expected (manifest): $MANIFEST_SHA256" >&2
    echo "  Computed (file):     $COMPUTED_SHA256" >&2
    exit 1
}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] checksum verification passed"

# ── Safety backup ─────────────────────────────────────────────────────────────
# Requirement 8.4: create safety backup before overwriting; abort if it fails
SAFETY_FILE="$BACKUP_DIR/pre_restore_$(date -u +%Y-%m-%dT%H-%M-%SZ).dump"

pg_dump -Fc -d "$PGDATABASE" -f "$SAFETY_FILE" || {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: safety backup failed — aborting without modifying database" >&2
    exit 1
}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] safety backup created: $SAFETY_FILE"

# ── Restore ───────────────────────────────────────────────────────────────────
# Requirement 8.1: restore using pg_restore
pg_restore -d "$PGDATABASE" --clean --if-exists "$BACKUP_DIR/$BACKUP_FILENAME"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] pg_restore complete"

# ── Flask migrations ──────────────────────────────────────────────────────────
# Requirement 8.5: run flask db upgrade head; exit 1 on failure
(
    cd /home/deploy/app/backend/
    flask db upgrade head
) || {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: flask db upgrade head failed — database is restored but migrations did not complete" >&2
    exit 1
}

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] flask db upgrade complete — restore finished"
