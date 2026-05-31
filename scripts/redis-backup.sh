#!/usr/bin/env bash
# redis-backup.sh — Redis RDB Snapshot
# Called by backup.sh; no arguments.
# Uses 'return 1' (not 'exit 1') for all failure cases so backup.sh can continue.
#
# VPS location: /home/deploy/redis-backup.sh
# VPS permissions: chmod 750 /home/deploy/redis-backup.sh

set -euo pipefail

# ── Source configuration ──────────────────────────────────────────────────────
# shellcheck source=/home/deploy/backup.conf
source /home/deploy/backup.conf

# ── Shared alert function ─────────────────────────────────────────────────────
send_alert() {
    local subject="$1"
    local body="$2"
    # Never log credential values — body must be pre-sanitized by caller
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

# ── Defaults ──────────────────────────────────────────────────────────────────
REDIS_BGSAVE_TIMEOUT="${REDIS_BGSAVE_TIMEOUT:-300}"
REDIS_RDB_PATH="${REDIS_RDB_PATH:-/var/lib/redis/dump.rdb}"
REDIS_RETENTION_DAYS="${REDIS_RETENTION_DAYS:-7}"

# ── Timestamp for this backup run ─────────────────────────────────────────────
TIMESTAMP="$(date -u +%Y-%m-%d_%H-%M-%S)"

# ── Step 1: Ping Redis ────────────────────────────────────────────────────────
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: pinging Redis via WSL" >> "$LOG_FILE"

if ! wsl -d Ubuntu -- redis-cli ping 2>>"$LOG_FILE" | grep -q "PONG"; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Redis ping failed — Redis may be unreachable" >> "$LOG_FILE"
    send_alert \
        "Redis backup failed — Redis unreachable [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
        "Redis did not respond to PING at $(date -u +%Y-%m-%dT%H:%M:%SZ). Redis backup skipped. PostgreSQL backup continues."
    return 1
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: Redis ping OK" >> "$LOG_FILE"

# ── Step 2: Record pre-BGSAVE LASTSAVE value ──────────────────────────────────
PRE_SAVE="$(wsl -d Ubuntu -- redis-cli LASTSAVE 2>>"$LOG_FILE")"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: pre-BGSAVE LASTSAVE=$PRE_SAVE" >> "$LOG_FILE"

# ── Step 3: Send BGSAVE command ───────────────────────────────────────────────
wsl -d Ubuntu -- redis-cli BGSAVE >> "$LOG_FILE" 2>&1
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: BGSAVE issued" >> "$LOG_FILE"

# ── Step 4: Poll LASTSAVE until it changes (or timeout) ──────────────────────
ELAPSED=0
POLL_INTERVAL=5

while true; do
    sleep "$POLL_INTERVAL"
    ELAPSED=$(( ELAPSED + POLL_INTERVAL ))

    CURRENT_SAVE="$(wsl -d Ubuntu -- redis-cli LASTSAVE 2>>"$LOG_FILE")"

    if [[ "$CURRENT_SAVE" != "$PRE_SAVE" ]]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: BGSAVE complete (LASTSAVE changed from $PRE_SAVE to $CURRENT_SAVE)" >> "$LOG_FILE"
        break
    fi

    if (( ELAPSED >= REDIS_BGSAVE_TIMEOUT )); then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: BGSAVE did not complete within ${REDIS_BGSAVE_TIMEOUT}s (LASTSAVE still $PRE_SAVE)" >> "$LOG_FILE"
        send_alert \
            "Redis backup failed — BGSAVE timeout [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
            "Redis BGSAVE did not complete within ${REDIS_BGSAVE_TIMEOUT} seconds at $(date -u +%Y-%m-%dT%H:%M:%SZ). No RDB file was copied."
        return 1
    fi
done

# ── Step 5: Copy RDB file from WSL to backup directory ───────────────────────
DEST_FILENAME="redis_${TIMESTAMP}.rdb"
DEST_PATH="${BACKUP_DIR}/${DEST_FILENAME}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: copying RDB from WSL path $REDIS_RDB_PATH to $DEST_PATH" >> "$LOG_FILE"

# On the VPS (Linux), BACKUP_DIR is a native Linux path — use a direct cp via WSL.
# The WSL path /mnt/... maps Windows/VPS paths; on a pure Linux VPS both paths are
# native, so we translate BACKUP_DIR to its WSL-accessible mount path.
# Strategy: run cp entirely inside WSL, writing to the WSL mount of BACKUP_DIR.
# /home/deploy/backups is a native Linux path on the VPS — accessible directly in WSL.
if ! wsl -d Ubuntu -- cp "$REDIS_RDB_PATH" "$DEST_PATH" 2>>"$LOG_FILE"; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Failed to copy RDB file from $REDIS_RDB_PATH to $DEST_PATH" >> "$LOG_FILE"
    send_alert \
        "Redis backup failed — RDB copy error [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
        "Failed to copy Redis RDB file from $REDIS_RDB_PATH to $DEST_PATH at $(date -u +%Y-%m-%dT%H:%M:%SZ). Existing Redis backups were NOT deleted."
    return 1
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: RDB copy succeeded — $DEST_PATH" >> "$LOG_FILE"

# ── Step 6: Delete Redis backups older than retention threshold ───────────────
# Only runs after a successful copy (requirement 6.6: do NOT delete on copy failure)
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: pruning Redis backups older than ${REDIS_RETENTION_DAYS} days" >> "$LOG_FILE"

find "$BACKUP_DIR" -maxdepth 1 -name 'redis_*.rdb' -mtime "+${REDIS_RETENTION_DAYS}" -delete 2>>"$LOG_FILE" \
    && echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: retention pruning complete" >> "$LOG_FILE" \
    || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: retention pruning encountered an error (non-fatal)" >> "$LOG_FILE"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: completed successfully — $DEST_FILENAME" >> "$LOG_FILE"

# NOTE (VPS setup): After deploying this script to /home/deploy/redis-backup.sh, run:
#   chmod 750 /home/deploy/redis-backup.sh
