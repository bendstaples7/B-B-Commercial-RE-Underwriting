#!/usr/bin/env bash
# backup.sh — Main Backup Orchestrator
# Runs as the 'deploy' user on the Hetzner VPS.
# Usage: backup.sh [--pre-deploy]
#
# VPS location: /home/deploy/backup.sh
# VPS permissions: chmod 750 /home/deploy/backup.sh
#
# Exit codes: 0 = success, 1 = any failure

set -euo pipefail

# ── Pre-deploy flag ───────────────────────────────────────────────────────────
if [[ "${1:-}" == "--pre-deploy" ]]; then
    BACKUP_TYPE="pre-deploy"
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

# ── Shared alert function ─────────────────────────────────────────────────────
# Defined after sourcing backup.conf so LOG_FILE, ALERT_METHOD, etc. are available.
# Credential values must never be passed as subject or body by callers.
send_alert() {
    local subject="$1"
    local body="$2"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT: $subject" >> "$LOG_FILE"

    if [[ "$ALERT_METHOD" == "email" || "$ALERT_METHOD" == "both" ]]; then
        echo "$body" | msmtp --account="$MSMTP_ACCOUNT" "$ALERT_EMAIL" \
            --subject="[Backup Alert] $subject" 2>>"$LOG_FILE" \
            || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT DELIVERY FAILED (email): $?" >> "$LOG_FILE"
    fi

    if [[ "$ALERT_METHOD" == "webhook" || "$ALERT_METHOD" == "both" ]]; then
        curl -s -X POST "$WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"text\": \"[Backup Alert] $subject\n$body\"}" \
            --max-time 10 2>>"$LOG_FILE" \
            || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT DELIVERY FAILED (webhook): $?" >> "$LOG_FILE"
    fi
}

# ── Step 2: Validate required config variables ────────────────────────────────
# Abort without writing credential values to the log if any are missing.
REQUIRED_VARS=(PGDATABASE BACKUP_DIR LOG_FILE ALERT_METHOD)
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

# ── Step 10 & 11: Remote transfer with retry loop ────────────────────────────
# Skip remote transfer if REMOTE_METHOD is empty (local-only backup mode)
if [[ -z "${REMOTE_METHOD:-}" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: REMOTE_METHOD not set — skipping remote transfer (local backup only)" >> "$LOG_FILE"
else
# Validate remote method via backup_lib dispatch
DISPATCH_CHECK=0
python3 -c "
import sys
sys.path.insert(0, '/home/deploy')
from backup_lib import dispatch_transfer_method
try:
    dispatch_transfer_method('$REMOTE_METHOD')
except ValueError as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
" 2>>"$LOG_FILE" || DISPATCH_CHECK=$?

if [[ "$DISPATCH_CHECK" -ne 0 ]]; then
    BACKUP_FAILED=1
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Invalid REMOTE_METHOD='$REMOTE_METHOD' — skipping remote transfer" >> "$LOG_FILE"
    send_alert \
        "Remote transfer skipped — invalid REMOTE_METHOD [$BACKUP_TYPE] [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
        "REMOTE_METHOD is not a valid transfer method. Remote transfer was skipped. Backup type: $BACKUP_TYPE."
else
    # Generate remote path
    REMOTE_PATH="$(python3 /home/deploy/backup_lib.py generate-remote-path "$RCLONE_PATH_PREFIX" "$TIMESTAMP_ISO" "$FILENAME")"

    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: remote path=$REMOTE_PATH" >> "$LOG_FILE"

    # Retry loop — up to REMOTE_RETRY_COUNT attempts
    RETRY_MAX="${REMOTE_RETRY_COUNT:-3}"
    RETRY_DELAY="${REMOTE_RETRY_DELAY:-300}"
    TRANSFER_SUCCESS=0
    ATTEMPT=0

    while [[ "$ATTEMPT" -lt "$RETRY_MAX" ]]; do
        ATTEMPT=$(( ATTEMPT + 1 ))
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: remote transfer attempt $ATTEMPT/$RETRY_MAX" >> "$LOG_FILE"

        TRANSFER_EXIT=0
        rclone copyto "$BACKUP_DIR/$FILENAME" "$RCLONE_REMOTE:$RCLONE_BUCKET/$REMOTE_PATH" \
            --contimeout "${REMOTE_CONNECT_TIMEOUT:-30}s" \
            2>>"$LOG_FILE" || TRANSFER_EXIT=$?

        if [[ "$TRANSFER_EXIT" -ne 0 ]]; then
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: rclone copy failed on attempt $ATTEMPT (exit code $TRANSFER_EXIT)" >> "$LOG_FILE"
            if [[ "$ATTEMPT" -lt "$RETRY_MAX" ]]; then
                echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: waiting ${RETRY_DELAY}s before retry" >> "$LOG_FILE"
                sleep "$RETRY_DELAY"
            fi
            continue
        fi

        # Verify remote file size matches local size
        LOCAL_SIZE="$(stat -c "%s" "$BACKUP_DIR/$FILENAME")"
        REMOTE_SIZE_JSON="$(rclone size "$RCLONE_REMOTE:$RCLONE_BUCKET/$REMOTE_PATH" --json 2>>"$LOG_FILE")" || {
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: rclone size check failed on attempt $ATTEMPT" >> "$LOG_FILE"
            if [[ "$ATTEMPT" -lt "$RETRY_MAX" ]]; then
                sleep "$RETRY_DELAY"
            fi
            continue
        }

        REMOTE_SIZE="$(echo "$REMOTE_SIZE_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('bytes', -1))")"

        if [[ "$REMOTE_SIZE" -eq "$LOCAL_SIZE" ]]; then
            TRANSFER_SUCCESS=1
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: remote transfer verified — local=${LOCAL_SIZE}B remote=${REMOTE_SIZE}B" >> "$LOG_FILE"
            break
        else
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: remote size mismatch on attempt $ATTEMPT — local=${LOCAL_SIZE}B remote=${REMOTE_SIZE}B" >> "$LOG_FILE"
            if [[ "$ATTEMPT" -lt "$RETRY_MAX" ]]; then
                sleep "$RETRY_DELAY"
            fi
        fi
    done

    if [[ "$TRANSFER_SUCCESS" -eq 1 ]]; then
        REMOTE_TRANSFERRED="true"
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: remote transfer succeeded — $REMOTE_PATH" >> "$LOG_FILE"

        # ── Step 13: Delete remote backups older than REMOTE_RETENTION_DAYS ──
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: pruning remote backups older than ${REMOTE_RETENTION_DAYS:-30} days" >> "$LOG_FILE"
        rclone delete --min-age "${REMOTE_RETENTION_DAYS:-30}d" \
            "$RCLONE_REMOTE:$RCLONE_BUCKET/$RCLONE_PATH_PREFIX/" \
            2>>"$LOG_FILE" \
            && echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: remote retention pruning complete" >> "$LOG_FILE" \
            || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: remote retention pruning encountered an error (non-fatal)" >> "$LOG_FILE"
    else
        BACKUP_FAILED=1
        REMOTE_TRANSFERRED="false"
        REMOTE_PATH=""
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: remote transfer failed after $RETRY_MAX attempts" >> "$LOG_FILE"
        send_alert \
            "Remote transfer FAILED after $RETRY_MAX attempts [$BACKUP_TYPE] [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
            "All $RETRY_MAX remote transfer attempts for $FILENAME failed at $(date -u +%Y-%m-%dT%H:%M:%SZ). Backup type: $BACKUP_TYPE. Check $LOG_FILE for details."
    fi

    # Update manifest entry with final remote transfer status
    # Append a corrected entry (the restore script uses the last matching entry via lookup_manifest_entry)
    if [[ "$REMOTE_TRANSFERRED" == "true" ]]; then
        REMOTE_TRANSFERRED_BOOL="true"
    else
        REMOTE_TRANSFERRED_BOOL="false"
    fi

    python3 -c "
import json, sys
print(json.dumps({
    'filename': '$FILENAME',
    'timestamp': '$TIMESTAMP_ISO',
    'size_bytes': $SIZE_BYTES,
    'sha256': '$SHA256',
    'integrity': '$INTEGRITY',
    'type': '$BACKUP_TYPE',
    'remote_transferred': $REMOTE_TRANSFERRED_BOOL,
    'remote_path': '$REMOTE_PATH'
}))
" | python3 /home/deploy/backup_lib.py serialize-manifest >> "$BACKUP_DIR/backup_manifest.log"

    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] backup.sh: manifest updated with remote transfer status" >> "$LOG_FILE"
fi
fi  # end: if REMOTE_METHOD is set

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
