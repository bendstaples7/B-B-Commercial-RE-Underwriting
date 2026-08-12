#!/usr/bin/env bash
# install-backup-cron.sh — Idempotent installer for backup + celery liveness +
# lead CC mount health cron entries (deploy user). Preserves non-managed
# crontab lines (e.g. DuckDNS). Safe to run on every deploy.
#
# VPS location: /home/deploy/install-backup-cron.sh
# Usage: bash /home/deploy/install-backup-cron.sh

set -euo pipefail

MARKER="backup-system-managed"
CELERY_MARKER="celery-liveness-managed"
LEAD_CC_MARKER="lead-cc-mount-health-managed"
LOG_REDIRECT=">> /home/deploy/logs/backup.log 2>&1"
CELERY_LOG_REDIRECT=">> /home/deploy/logs/celery-liveness.log 2>&1"
LEAD_CC_LOG_REDIRECT=">> /home/deploy/logs/lead-cc-mount-health.log 2>&1"

CURRENT="$(crontab -l 2>/dev/null || true)"

# Remove prior managed lines, legacy backup/liveness cron lines, and blank lines.
FILTERED="$(printf '%s\n' "$CURRENT" | grep -v "$MARKER" \
    | grep -v "$CELERY_MARKER" \
    | grep -v "$LEAD_CC_MARKER" \
    | grep -v '/home/deploy/backup\.sh' \
    | grep -v '/home/deploy/pg-basebackup\.sh' \
    | grep -v '/home/deploy/daily-summary\.sh' \
    | grep -v '/home/deploy/celery-liveness-check\.sh' \
    | grep -v '/home/deploy/check-lead-cc-mount-health\.sh' \
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
    echo "# $CELERY_MARKER"
    echo "*/5 * * * * /home/deploy/celery-liveness-check.sh $CELERY_LOG_REDIRECT # $CELERY_MARKER"
    echo "# $LEAD_CC_MARKER"
    echo "15 * * * * /home/deploy/check-lead-cc-mount-health.sh $LEAD_CC_LOG_REDIRECT # $LEAD_CC_MARKER"
} > "$TMP"

crontab "$TMP"
rm -f "$TMP"

echo "install-backup-cron.sh: installed 5 backup + 1 celery-liveness + 1 lead-cc-mount-health cron entries"
crontab -l | grep -E "$MARKER|$CELERY_MARKER|$LEAD_CC_MARKER" || true
