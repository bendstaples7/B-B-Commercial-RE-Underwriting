#!/usr/bin/env bash
# install-backup-cron.sh — Idempotent installer for backup cron entries (deploy user).
# Preserves non-backup crontab lines (e.g. DuckDNS). Safe to run on every deploy.
#
# VPS location: /home/deploy/install-backup-cron.sh
# Usage: bash /home/deploy/install-backup-cron.sh

set -euo pipefail

MARKER="backup-system-managed"
LOG_REDIRECT=">> /home/deploy/logs/backup.log 2>&1"

CURRENT="$(crontab -l 2>/dev/null || true)"

# Remove prior backup-system-managed lines, legacy backup cron lines, and blank lines.
FILTERED="$(printf '%s\n' "$CURRENT" | grep -v "$MARKER" \
    | grep -v '/home/deploy/backup\.sh' \
    | grep -v '/home/deploy/pg-basebackup\.sh' \
    | grep -v '/home/deploy/daily-summary\.sh' \
    | grep -v '^MAILTO=' \
    | grep -v '^[[:space:]]*$' || true)"

TMP="$(mktemp)"
{
    if [[ -n "$FILTERED" ]]; then
        printf '%s\n' "$FILTERED"
    fi
    echo "# $MARKER"
    echo "MAILTO=\"\""
    echo "0 2 * * * /home/deploy/backup.sh $LOG_REDIRECT # $MARKER"
    echo "0 10 * * * /home/deploy/backup.sh $LOG_REDIRECT # $MARKER"
    echo "0 18 * * * /home/deploy/backup.sh $LOG_REDIRECT # $MARKER"
    echo "0 1 * * 0 /home/deploy/pg-basebackup.sh $LOG_REDIRECT # $MARKER"
    echo "30 0 * * * /home/deploy/daily-summary.sh $LOG_REDIRECT # $MARKER"
} > "$TMP"

crontab "$TMP"
rm -f "$TMP"

echo "install-backup-cron.sh: installed 5 backup cron entries (marker=$MARKER)"
crontab -l | grep "$MARKER" || true
