#!/usr/bin/env bash
# backup.sh — Main Backup Orchestrator
# Runs as the 'deploy' user on the Hetzner VPS.
# Usage: backup.sh [--pre-deploy] [--pre-deploy-fast] [--check]
#
# VPS location: /home/deploy/backup.sh
# VPS permissions: chmod 750 /home/deploy/backup.sh
#
# Exit codes: 0 = success, 1 = any failure

set -euo pipefail

# ── Pre-deploy flag ───────────────────────────────────────────────────────────
PRE_DEPLOY_FAST=0
if [[ "${1:-}" == "--pre-deploy" ]]; then
    BACKUP_TYPE="pre-deploy"
elif [[ "${1:-}" == "--pre-deploy-fast" ]]; then
    BACKUP_TYPE="pre-deploy"
    PRE_DEPLOY_FAST=1
elif [[ "${1:-}" == "--check" ]]; then
    # --check mode: validate config and test pg_dump connectivity without
    # running a full backup. Exits 0 if everything is configured correctly,
    # 1 if any required config is missing or pg_dump cannot connect.
    BACKUP_TYPE="check"
else
    BACKUP_TYPE="scheduled"
fi

# ── Failure tracking flag ─────────────────────────────────────────────────────
# Set to 1 on any non-fatal failure; deletion is skipped if non-zero.
BACKUP_FAILED=0

# ── Step 1: Source and verify backup.conf ─────────────────────────────────────
CONF_FILE="/home/deploy/backup.conf"

# Verify permissions before sourcing (do NOT write credential values to log)
CONF_STAT="$(stat -c "%a %U:%G" "$CONF_FILE" 2>/dev/null)" || {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Cannot stat $CONF_FILE — file missing or inaccessible" \
        >> /tmp/backup_bootstrap.log 2>&1 || true
    exit 1
}

if [[ "$CONF_STAT" != "600 deploy:deploy" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: $CONF_FILE has incorrect permissions or ownership: $CONF_STAT (expected: 600 deploy:deploy)" \
        >> /tmp/backup_bootstrap.log 2>&1 || true
    exit 1
fi

# shellcheck source=/home/deploy/backup.conf
source "$CONF_FILE"

# Shared alert helper (email/webhook with JSON-safe payload).
ALERT_SUBJECT_PREFIX="[Backup Alert]"
OPS_ALERT_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ops-alert.sh"
if [[ ! -f "$OPS_ALERT_LIB" ]]; then
    OPS_ALERT_LIB="/home/deploy/ops-alert.sh"
fi
# shellcheck source=ops-alert.sh
source "$OPS_ALERT_LIB"

# ── Step 2: Validate required config variables ────────────────────────────────
# Abort without writing credential values to the log if any are missing.
REQUIRED_VARS=(PGDATABASE PGUSER BACKUP_DIR LOG_FILE ALERT_METHOD)
for var in "${REQUIRED_VARS[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Required config variable '$var' is not set — aborting" >> /tmp/backup_bootstrap.log 2>&1 || true
        exit 1
    fi
done

# ── Step 3: Log script start ──────────────────────────────────────────────────
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh starting — type: $BACKUP_TYPE" >> "$LOG_FILE"

# ── --check mode: validate connectivity and exit ──────────────────────────────
if [[ "$BACKUP_TYPE" == "check" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh --check: testing pg_dump connectivity..." >> "$LOG_FILE"
    CHECK_EXIT=0
    PGPASSFILE="${PGPASSFILE:-/home/deploy/.pgpass}" pg_dump \
        --schema-only \
        -h "${PGHOST:-localhost}" \
        -U "$PGUSER" \
        -d "$PGDATABASE" \
        -f /dev/null 2>>"$LOG_FILE" || CHECK_EXIT=$?
    if [[ "$CHECK_EXIT" -ne 0 ]]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh --check: FAILED — pg_dump connectivity test failed (exit $CHECK_EXIT)" >> "$LOG_FILE"
        echo "BACKUP CHECK FAILED: pg_dump cannot connect to $PGDATABASE as $PGUSER@${PGHOST:-localhost}" >&2
        echo "Check /home/deploy/logs/backup.log and /home/deploy/.pgpass for details." >&2
        exit 1
    fi
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh --check: PASSED — pg_dump connectivity OK" >> "$LOG_FILE"
    echo "BACKUP CHECK PASSED: pg_dump can connect to $PGDATABASE as $PGUSER@${PGHOST:-localhost}"
    exit 0
fi

# ── Step 4: Verify BACKUP_DIR exists and is writable ─────────────────────────
if [[ ! -d "$BACKUP_DIR" ]] || [[ ! -w "$BACKUP_DIR" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Backup directory '$BACKUP_DIR' does not exist or is not writable" >> "$LOG_FILE"
    send_alert \
        "Backup aborted — backup directory not writable [$BACKUP_TYPE] [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
        "Backup directory '$BACKUP_DIR' does not exist or is not writable by the deploy user. Backup aborted."
    exit 1
fi

# ── Pre-deploy-fast: skip dump when a recent valid scheduled backup exists ───
if [[ "$PRE_DEPLOY_FAST" -eq 1 ]]; then
    MAX_AGE_HOURS="${PRE_DEPLOY_BACKUP_MAX_AGE_HOURS:-8}"
    RECENT_META=""
    RECENT_META="$(
    python3 -c "
import json, sys
from datetime import datetime, timezone, timedelta

manifest = '$BACKUP_DIR/backup_manifest.log'
max_age = timedelta(hours=int('$MAX_AGE_HOURS'))
cutoff = datetime.now(timezone.utc) - max_age
try:
    with open(manifest) as f:
        lines = [ln.strip() for ln in f if ln.strip()]
except OSError:
    sys.exit(1)
for line in reversed(lines):
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        continue
    if entry.get('type') != 'scheduled':
        continue
    if entry.get('integrity') != 'valid':
        continue
    ts = entry.get('timestamp', '')
    try:
        when = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except ValueError:
        continue
    if when >= cutoff:
        filename = entry.get('filename', '')
        if not filename:
            continue
        # filename<TAB>original timestamp (preserve dump time for remote path / manifest)
        print(f'{filename}\t{ts}')
        sys.exit(0)
sys.exit(1)
" 2>>"$LOG_FILE"
    )" || RECENT_META=""

    RECENT_FILENAME=""
    RECENT_TIMESTAMP=""
    if [[ -n "$RECENT_META" ]]; then
        RECENT_FILENAME="${RECENT_META%%$'\t'*}"
        RECENT_TIMESTAMP="${RECENT_META#*$'\t'}"
    fi

    if [[ -n "$RECENT_FILENAME" && -f "$BACKUP_DIR/$RECENT_FILENAME" ]]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: pre-deploy-fast — recent valid scheduled backup within ${MAX_AGE_HOURS}h — skipping pg_dump ($RECENT_FILENAME)" >> "$LOG_FILE"
        echo "    Pre-deploy-fast: using recent scheduled backup (within ${MAX_AGE_HOURS}h)"
        # Heal off-site copies if cloud transfer is stale (does not re-dump).
        FILENAME="$RECENT_FILENAME"
        TIMESTAMP_ISO="${RECENT_TIMESTAMP:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
        SHA256="$(sha256sum "$BACKUP_DIR/$FILENAME" | awk '{print $1}')"
        SIZE_BYTES="$(stat -c "%s" "$BACKUP_DIR/$FILENAME")"
        INTEGRITY="invalid"
        if pg_restore --list "$BACKUP_DIR/$FILENAME" >> "$LOG_FILE" 2>&1; then
            INTEGRITY="valid"
        else
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: pre-deploy-fast integrity check FAILED for $FILENAME" >> "$LOG_FILE"
            send_alert \
                "Pre-deploy-fast aborted — reused dump failed integrity [$BACKUP_TYPE] [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
                "pg_restore --list failed for reused backup $FILENAME. Falling through would risk uploading a corrupt dump."
            # Fall through to a fresh pg_dump instead of uploading a bad archive.
            PRE_DEPLOY_FAST=0
        fi
        if [[ "$INTEGRITY" == "valid" ]]; then
            REMOTE_PATH=""
            REMOTE_TRANSFERRED="false"
            # shellcheck source=/home/deploy/backup_remote_transfer.sh
            source /home/deploy/backup_remote_transfer.sh
            if [[ "$BACKUP_FAILED" -ne 0 ]]; then
                echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: pre-deploy-fast completed with remote failures — $FILENAME (remote_transferred=$REMOTE_TRANSFERRED)" >> "$LOG_FILE"
                exit 1
            fi
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: pre-deploy-fast completed — $FILENAME (remote_transferred=$REMOTE_TRANSFERRED)" >> "$LOG_FILE"
            exit 0
        fi
    fi
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: pre-deploy-fast — no recent usable scheduled backup — running local pg_dump" >> "$LOG_FILE"
fi

# ── Step 5: Determine output filename ────────────────────────────────────────
FILENAME="$(python3 /home/deploy/backup_lib.py generate-filename "$BACKUP_TYPE")"
TIMESTAMP_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: filename=$FILENAME" >> "$LOG_FILE"

# ── Step 6: Run pg_dump ───────────────────────────────────────────────────────
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: starting pg_dump" >> "$LOG_FILE"

PGDUMP_EXIT=0
PGPASSFILE="${PGPASSFILE:-/home/deploy/.pgpass}" pg_dump \
    -Fc \
    -h "${PGHOST:-localhost}" \
    -U "$PGUSER" \
    -d "$PGDATABASE" \
    -f "$BACKUP_DIR/$FILENAME" 2>>"$LOG_FILE" || PGDUMP_EXIT=$?

if [[ "$PGDUMP_EXIT" -ne 0 ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: pg_dump failed for database '$PGDATABASE' — exit code: $PGDUMP_EXIT" >> "$LOG_FILE"
    send_alert \
        "pg_dump FAILED [$BACKUP_TYPE] [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
        "pg_dump exited with a non-zero status at $(date -u +%Y-%m-%dT%H:%M:%SZ). Backup type: $BACKUP_TYPE. Check $LOG_FILE for details."
    exit 1
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: pg_dump complete — $FILENAME" >> "$LOG_FILE"

# ── Step 7: Compute checksum and integrity check ──────────────────────────────
SHA256="$(sha256sum "$BACKUP_DIR/$FILENAME" | awk '{print $1}')"
SIZE_BYTES="$(stat -c "%s" "$BACKUP_DIR/$FILENAME")"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: SHA-256=$SHA256 size=${SIZE_BYTES}B" >> "$LOG_FILE"

# Run pg_restore --list for integrity check; record valid or invalid
if pg_restore --list "$BACKUP_DIR/$FILENAME" >> "$LOG_FILE" 2>&1; then
    INTEGRITY="valid"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: integrity check PASSED — $FILENAME" >> "$LOG_FILE"
else
    INTEGRITY="invalid"
    BACKUP_FAILED=1
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: integrity check FAILED for $FILENAME (pg_restore --list exited non-zero)" >> "$LOG_FILE"
    send_alert \
        "Backup integrity check FAILED [$BACKUP_TYPE] [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
        "pg_restore --list returned a non-zero exit code for $FILENAME at $(date -u +%Y-%m-%dT%H:%M:%SZ). Integrity recorded as 'invalid'. Backup type: $BACKUP_TYPE."
fi

# ── Step 8: Append NDJSON manifest entry ─────────────────────────────────────
# remote_transferred and remote_path are placeholders; updated after transfer below.
# We write the initial manifest entry now with remote_transferred=false.
REMOTE_PATH=""
REMOTE_TRANSFERRED="false"

python3 -c "
import json, sys
print(json.dumps({
    'filename': '$FILENAME',
    'timestamp': '$TIMESTAMP_ISO',
    'size_bytes': $SIZE_BYTES,
    'sha256': '$SHA256',
    'integrity': '$INTEGRITY',
    'type': '$BACKUP_TYPE',
    'remote_transferred': False,
    'remote_path': ''
}))
" | python3 /home/deploy/backup_lib.py serialize-manifest >> "$BACKUP_DIR/backup_manifest.log"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: manifest entry written for $FILENAME" >> "$LOG_FILE"

# ── Step 9: Redis backup (non-blocking) ───────────────────────────────────────
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: calling redis-backup.sh" >> "$LOG_FILE"

REDIS_EXIT=0
/home/deploy/redis-backup.sh 2>>"$LOG_FILE" || REDIS_EXIT=$?

if [[ "$REDIS_EXIT" -ne 0 ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: redis-backup.sh exited with code $REDIS_EXIT — PostgreSQL backup continues" >> "$LOG_FILE"
    send_alert \
        "Redis backup FAILED [$BACKUP_TYPE] [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
        "redis-backup.sh exited with code $REDIS_EXIT at $(date -u +%Y-%m-%dT%H:%M:%SZ). PostgreSQL backup is continuing. Check $LOG_FILE for details."
fi

# ── Step 10 & 11: Remote transfer (multi-target, gated) ───────────────────────
# Logic lives in backup_remote_transfer.sh (sourced so REMOTE_* / BACKUP_FAILED update).
# shellcheck source=/home/deploy/backup_remote_transfer.sh
source /home/deploy/backup_remote_transfer.sh

# ── Step 12: Delete local backups older than LOCAL_RETENTION_DAYS ─────────────
# Only run if no failures occurred during this backup run.
if [[ "$BACKUP_FAILED" -eq 0 ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: pruning local backups older than ${LOCAL_RETENTION_DAYS:-30} days" >> "$LOG_FILE"
    find "$BACKUP_DIR" -maxdepth 1 -name 'backup_*.dump' \
        -mtime "+${LOCAL_RETENTION_DAYS:-30}" -delete 2>>"$LOG_FILE" \
        && echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: local retention pruning complete" >> "$LOG_FILE" \
        || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: local retention pruning encountered an error (non-fatal)" >> "$LOG_FILE"
else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: skipping local retention pruning due to earlier failure (BACKUP_FAILED=$BACKUP_FAILED)" >> "$LOG_FILE"
fi

# ── Step 14: Log completion ───────────────────────────────────────────────────
if [[ "$BACKUP_FAILED" -eq 0 ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: completed successfully — $FILENAME (type=$BACKUP_TYPE, integrity=$INTEGRITY, remote_transferred=$REMOTE_TRANSFERRED)" >> "$LOG_FILE"
else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: completed with warnings/failures — $FILENAME (type=$BACKUP_TYPE, integrity=$INTEGRITY, remote_transferred=$REMOTE_TRANSFERRED, BACKUP_FAILED=$BACKUP_FAILED)" >> "$LOG_FILE"
fi

# NOTE (VPS setup): After deploying this script to /home/deploy/backup.sh, run:
#   chmod 750 /home/deploy/backup.sh

# Exit non-zero if any failure occurred (ensures pre-deploy hook blocks deploy)
if [[ "$BACKUP_FAILED" -ne 0 ]]; then
    exit 1
fi
