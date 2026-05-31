#!/usr/bin/env bash
# daily-summary.sh — Daily Backup Status Report
# Runs at 00:30 UTC daily via cron as the deploy user.
# After deployment: chmod 750 /home/deploy/daily-summary.sh
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
source /home/deploy/backup.conf

MANIFEST_FILE="$BACKUP_DIR/backup_manifest.log"

# ── Alert function ─────────────────────────────────────────────────────────────
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

# ── Compute time window ────────────────────────────────────────────────────────
WINDOW_END=$(date -u +%Y-%m-%dT%H:%M:%SZ)
WINDOW_START=$(date -u -d "24 hours ago" +%Y-%m-%dT%H:%M:%SZ)

# ── Aggregate summary counts from manifest ────────────────────────────────────
SUMMARY_JSON=$(python3 /home/deploy/backup_lib.py aggregate-summary \
    "$MANIFEST_FILE" "$WINDOW_START" "$WINDOW_END")

SUCCESSFUL=$(echo "$SUMMARY_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['successful'])")
FAILED=$(echo "$SUMMARY_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['failed'])")

# ── Total storage used in backup directory (MB) ───────────────────────────────
STORAGE_MB=$(du -sm "$BACKUP_DIR" | awk '{print $1}')

# ── Most recent successful backup timestamp ───────────────────────────────────
LAST_BACKUP_TS=""
if [[ -f "$MANIFEST_FILE" ]]; then
    LAST_BACKUP_TS=$(grep '"integrity": "valid"' "$MANIFEST_FILE" \
        | tail -1 \
        | python3 -c "import json,sys; e=json.load(sys.stdin); print(e['timestamp'])" 2>/dev/null || true)
fi

# ── Build summary body ────────────────────────────────────────────────────────
SUMMARY_DATE=$(date -u +%Y-%m-%d)
SUBJECT="Daily Backup Summary — $SUMMARY_DATE"

BODY="Backup Summary for $SUMMARY_DATE (window: $WINDOW_START to $WINDOW_END)

Successful backups (last 24h): $SUCCESSFUL
Failed backups (last 24h):     $FAILED
Total storage used:            ${STORAGE_MB} MB
Most recent successful backup: ${LAST_BACKUP_TS:-NONE}"

# ── Stale backup check ────────────────────────────────────────────────────────
if [[ -n "$LAST_BACKUP_TS" ]]; then
    if python3 /home/deploy/backup_lib.py is-stale "$LAST_BACKUP_TS" "$WINDOW_END"; then
        # is-stale exits 0 when the backup IS stale (older than 12 hours)
        ELAPSED_HOURS=$(python3 -c "
from datetime import datetime, timezone
ts = datetime.fromisoformat('${LAST_BACKUP_TS}'.replace('Z', '+00:00'))
now = datetime.fromisoformat('${WINDOW_END}'.replace('Z', '+00:00'))
elapsed = (now - ts).total_seconds() / 3600
print(f'{elapsed:.1f}')
")
        BODY="$BODY

WARNING: Most recent successful backup is STALE.
Last successful backup: $LAST_BACKUP_TS
Hours elapsed since last backup: $ELAPSED_HOURS hours
Immediate attention required — backup gap exceeds 12 hours."
    fi
elif [[ -z "$LAST_BACKUP_TS" ]]; then
    BODY="$BODY

WARNING: No successful backup found in the manifest. Immediate attention required."
fi

# ── Send summary via configured notification channel ─────────────────────────
send_alert "$SUBJECT" "$BODY"

# ── Log completion ────────────────────────────────────────────────────────────
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] daily-summary.sh complete — successful=$SUCCESSFUL failed=$FAILED storage=${STORAGE_MB}MB last_backup=${LAST_BACKUP_TS:-NONE}" >> "$LOG_FILE"
