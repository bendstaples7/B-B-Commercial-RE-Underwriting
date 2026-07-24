#!/usr/bin/env bash
# wal-archive.sh — WAL Segment Archiver
#
# Called by PostgreSQL archive_command:
#   archive_command = '/home/deploy/wal-archive.sh %p %f'
#
# Arguments:
#   $1 = full path to WAL segment (%p)
#   $2 = WAL segment filename (%f)
#
# NOTE: No 'set -e' — PostgreSQL requires explicit exit codes from archive_command.
#       An unhandled error must not silently succeed (exit 0); we must exit 1 so
#       PostgreSQL knows to retry.
#
# Permissions: chmod 755 /home/deploy/wal-archive.sh
#   (755, not 750 — the postgres OS user invokes this script via archive_command,
#    not the deploy user. The postgres user must be able to read and execute it.)

WAL_SEGMENT_PATH="$1"
WAL_SEGMENT_FILE="$2"

# ── Load configuration ────────────────────────────────────────────────────────
# shellcheck source=/home/deploy/backup.conf
source /home/deploy/backup.conf

# Required variables sourced from backup.conf:
#   WAL_ARCHIVE_DIR  — destination directory for archived WAL segments
#   LOG_FILE         — path to backup log file
#   ALERT_METHOD     — "email" | "webhook" | "both"
#   ALERT_EMAIL      — operator email address
#   MSMTP_ACCOUNT    — msmtp account name for email delivery
#   WEBHOOK_URL      — HTTP webhook endpoint (Slack/Discord/custom)

ALERT_SUBJECT_PREFIX="[Backup Alert]"
OPS_ALERT_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ops-alert.sh"
if [[ ! -f "$OPS_ALERT_LIB" ]]; then
    OPS_ALERT_LIB="/home/deploy/ops-alert.sh"
fi
# shellcheck source=ops-alert.sh
source "$OPS_ALERT_LIB"

# ── Validate arguments ────────────────────────────────────────────────────────
if [[ -z "$WAL_SEGMENT_PATH" || -z "$WAL_SEGMENT_FILE" ]]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: wal-archive.sh requires two arguments: <segment_path> <segment_filename>" >> "$LOG_FILE"
    exit 1
fi

# ── Free space check ─────────────────────────────────────────────────────────
# Requirement 5.7: If WAL archive directory has insufficient free space,
# log the error and send an alert, then exit 1.
AVAILABLE_KB=$(df -k "$WAL_ARCHIVE_DIR" | awk 'NR==2 {print $4}')
THRESHOLD_KB=$((500 * 1024))  # 500 MB in KB

if [[ "$AVAILABLE_KB" -lt "$THRESHOLD_KB" ]]; then
    MSG="WAL archive directory $WAL_ARCHIVE_DIR has insufficient free space: ${AVAILABLE_KB}KB available, ${THRESHOLD_KB}KB required. Segment: $WAL_SEGMENT_FILE"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: $MSG" >> "$LOG_FILE"
    send_alert "WAL Archive Disk Full" "$MSG"
    exit 1
fi

# ── Copy WAL segment ──────────────────────────────────────────────────────────
# Requirement 5.1, 5.2: Copy the WAL segment to the archive directory.
# Exit 0 on success so PostgreSQL recycles the segment.
# Exit 1 on failure so PostgreSQL retries.
cp --preserve "$WAL_SEGMENT_PATH" "$WAL_ARCHIVE_DIR/$WAL_SEGMENT_FILE"
COPY_EXIT=$?

if [[ "$COPY_EXIT" -eq 0 ]]; then
    # Success — PostgreSQL will recycle the segment
    exit 0
else
    # Requirement 5.6: Log segment filename and exit code, send alert, exit 1.
    MSG="WAL archive copy failed for segment $WAL_SEGMENT_FILE (exit code: $COPY_EXIT). PostgreSQL will retry."
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: $MSG" >> "$LOG_FILE"
    send_alert "WAL Archive Copy Failed" "$MSG"
    exit 1
fi
