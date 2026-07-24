#!/usr/bin/env bash
# redis-backup.sh — Redis RDB Snapshot
# Called by backup.sh; no arguments.
# Uses 'exit 1' for all failure cases.
#
# VPS location: /home/deploy/redis-backup.sh
# VPS permissions: chmod 750 /home/deploy/redis-backup.sh

set -euo pipefail

# ── Source configuration ──────────────────────────────────────────────────────
# shellcheck source=/home/deploy/backup.conf
source /home/deploy/backup.conf

# ── Shared alert helper ───────────────────────────────────────────────────────
ALERT_SUBJECT_PREFIX="[Backup Alert]"
OPS_ALERT_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ops-alert.sh"
if [[ ! -f "$OPS_ALERT_LIB" ]]; then
    OPS_ALERT_LIB="/home/deploy/ops-alert.sh"
fi
# shellcheck source=ops-alert.sh
source "$OPS_ALERT_LIB"

# ── Redis command prefix ──────────────────────────────────────────────────────
# On a Linux VPS with native Redis, CMD_PREFIX is empty.
# On Windows/WSL, set CMD_PREFIX="wsl -d Ubuntu --" in backup.conf or here.
CMD_PREFIX="${REDIS_CMD_PREFIX:-}"
# Auto-detect: if 'wsl' is not available, clear the prefix
if [[ -n "$CMD_PREFIX" ]] && ! command -v wsl &>/dev/null; then
    CMD_PREFIX=""
fi

# ── Defaults ──────────────────────────────────────────────────────────────────
REDIS_BGSAVE_TIMEOUT="${REDIS_BGSAVE_TIMEOUT:-300}"
REDIS_RDB_PATH="${REDIS_RDB_PATH:-/var/lib/redis/dump.rdb}"
REDIS_RETENTION_DAYS="${REDIS_RETENTION_DAYS:-7}"

# ── Timestamp for this backup run ─────────────────────────────────────────────
TIMESTAMP="$(date -u +%Y-%m-%d_%H-%M-%S)"

# ── Step 1: Ping Redis ────────────────────────────────────────────────────────
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: pinging Redis" >> "$LOG_FILE"

if ! ${CMD_PREFIX:+$CMD_PREFIX }redis-cli ping 2>>"$LOG_FILE" | grep -q "PONG"; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Redis ping failed — Redis may be unreachable" >> "$LOG_FILE"
    send_alert \
        "Redis backup failed — Redis unreachable [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
        "Redis did not respond to PING at $(date -u +%Y-%m-%dT%H:%M:%SZ). Redis backup skipped. PostgreSQL backup continues."
    exit 1
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: Redis ping OK" >> "$LOG_FILE"

# ── Step 2: Record pre-BGSAVE LASTSAVE value ──────────────────────────────────
PRE_SAVE="$(${CMD_PREFIX:+$CMD_PREFIX }redis-cli LASTSAVE 2>>"$LOG_FILE")"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: pre-BGSAVE LASTSAVE=$PRE_SAVE" >> "$LOG_FILE"

# ── Step 3: Send BGSAVE command ───────────────────────────────────────────────
${CMD_PREFIX:+$CMD_PREFIX }redis-cli BGSAVE >> "$LOG_FILE" 2>&1
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: BGSAVE issued" >> "$LOG_FILE"

# ── Step 4: Poll LASTSAVE until it changes (or timeout) ──────────────────────
ELAPSED=0
POLL_INTERVAL=5

while true; do
    sleep "$POLL_INTERVAL"
    ELAPSED=$(( ELAPSED + POLL_INTERVAL ))

    CURRENT_SAVE="$(${CMD_PREFIX:+$CMD_PREFIX }redis-cli LASTSAVE 2>>"$LOG_FILE")"

    if [[ "$CURRENT_SAVE" != "$PRE_SAVE" ]]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: BGSAVE complete (LASTSAVE changed from $PRE_SAVE to $CURRENT_SAVE)" >> "$LOG_FILE"
        break
    fi

    if (( ELAPSED >= REDIS_BGSAVE_TIMEOUT )); then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: BGSAVE did not complete within ${REDIS_BGSAVE_TIMEOUT}s (LASTSAVE still $PRE_SAVE)" >> "$LOG_FILE"
        send_alert \
            "Redis backup failed — BGSAVE timeout [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
            "Redis BGSAVE did not complete within ${REDIS_BGSAVE_TIMEOUT} seconds at $(date -u +%Y-%m-%dT%H:%M:%SZ). No RDB file was copied."
        exit 1
    fi
done

# ── Step 5: Copy RDB file from WSL to backup directory ───────────────────────
DEST_FILENAME="redis_${TIMESTAMP}.rdb"
DEST_PATH="${BACKUP_DIR}/${DEST_FILENAME}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] redis-backup.sh: copying RDB from $REDIS_RDB_PATH to $DEST_PATH" >> "$LOG_FILE"

if ! ${CMD_PREFIX:+$CMD_PREFIX }cp "$REDIS_RDB_PATH" "$DEST_PATH" 2>>"$LOG_FILE"; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Failed to copy RDB file from $REDIS_RDB_PATH to $DEST_PATH" >> "$LOG_FILE"
    send_alert \
        "Redis backup failed — RDB copy error [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
        "Failed to copy Redis RDB file from $REDIS_RDB_PATH to $DEST_PATH at $(date -u +%Y-%m-%dT%H:%M:%SZ). Existing Redis backups were NOT deleted."
    exit 1
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
