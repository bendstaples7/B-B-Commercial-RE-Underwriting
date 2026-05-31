#!/usr/bin/env bash
# pg-basebackup.sh — Weekly full base backup using pg_basebackup
# Scheduled: Sunday 01:00 UTC via cron
# Permissions: chmod 750 /home/deploy/pg-basebackup.sh
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
source /home/deploy/backup.conf

# ── Alert function ────────────────────────────────────────────────────────────
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

# ── Generate timestamped output directory ─────────────────────────────────────
OUTPUT_DIR="$BACKUP_DIR/base/base_$(date -u +%Y-%m-%d_%H-%M-%S)"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] pg-basebackup.sh starting — output: $OUTPUT_DIR" >> "$LOG_FILE"

# ── Run pg_basebackup ─────────────────────────────────────────────────────────
# -D: output directory
# -Fp: plain format (directory layout matching PostgreSQL data directory)
# -Xs: stream WAL segments during backup (avoids needing extra WAL retention)
# -P: show progress
# -U: connect as deploy user
BASEBACKUP_EXIT=0
pg_basebackup -D "$OUTPUT_DIR" -Fp -Xs -P -U deploy || BASEBACKUP_EXIT=$?
if [[ "$BASEBACKUP_EXIT" -ne 0 ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: pg_basebackup failed with exit code $BASEBACKUP_EXIT — output dir: $OUTPUT_DIR" >> "$LOG_FILE"
    send_alert \
        "pg_basebackup failed" \
        "pg_basebackup exited with code $BASEBACKUP_EXIT at $(date -u +%Y-%m-%dT%H:%M:%SZ). Output directory: $OUTPUT_DIR"
    exit 1
fi

# ── Log completion ────────────────────────────────────────────────────────────
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] pg-basebackup.sh complete — output: $OUTPUT_DIR" >> "$LOG_FILE"

# ── Check age of most recent base backup ─────────────────────────────────────
# Requirement 5.4: if most recent base backup is older than 7 days, send alert
STALE_THRESHOLD_DAYS=7
STALE_THRESHOLD_SECONDS=$(( STALE_THRESHOLD_DAYS * 86400 ))

# List all base_* directories, sort by name (timestamp-based names sort chronologically)
MOST_RECENT_BASE=$(find "$BACKUP_DIR/base" -maxdepth 1 -name "base_*" -type d \
    | sort \
    | tail -1)

if [[ -n "$MOST_RECENT_BASE" ]]; then
    # Get modification time of the directory in seconds since epoch
    MOST_RECENT_MTIME=$(stat -c "%Y" "$MOST_RECENT_BASE" 2>/dev/null || echo 0)
    NOW_SECONDS=$(date -u +%s)
    AGE_SECONDS=$(( NOW_SECONDS - MOST_RECENT_MTIME ))

    if (( AGE_SECONDS > STALE_THRESHOLD_SECONDS )); then
        AGE_DAYS=$(( AGE_SECONDS / 86400 ))
        MOST_RECENT_TS=$(date -u -d "@$MOST_RECENT_MTIME" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
            || date -u -r "$MOST_RECENT_MTIME" +%Y-%m-%dT%H:%M:%SZ)
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: most recent base backup is $AGE_DAYS days old ($MOST_RECENT_BASE)" >> "$LOG_FILE"
        send_alert \
            "Stale base backup — most recent is $AGE_DAYS days old" \
            "The most recent pg_basebackup was taken at $MOST_RECENT_TS ($AGE_DAYS days ago). A new base backup should be taken immediately to ensure PITR coverage."
    fi
else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WARNING: no base backups found in $BACKUP_DIR/base" >> "$LOG_FILE"
    send_alert \
        "No base backups found" \
        "No base_* directories were found in $BACKUP_DIR/base at $(date -u +%Y-%m-%dT%H:%M:%SZ). PITR is not possible without a base backup."
fi

# ── Purge old WAL segments ────────────────────────────────────────────────────
# Requirement 5.5: delete WAL segments older than WAL_RETENTION_DAYS days
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Purging WAL segments older than $WAL_RETENTION_DAYS days from $WAL_ARCHIVE_DIR" >> "$LOG_FILE"
find "$WAL_ARCHIVE_DIR" -maxdepth 1 -type f -mtime +"$WAL_RETENTION_DAYS" -delete
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] WAL purge complete" >> "$LOG_FILE"
