#!/usr/bin/env bash
# verify-backup-health.sh — Exit 0 when cron, freshness, and cloud transfer look healthy.
# VPS location: /home/deploy/verify-backup-health.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK_PY="/home/deploy/backup_health_check.py"
if [[ ! -f "$CHECK_PY" ]]; then
    CHECK_PY="$SCRIPT_DIR/backup_health_check.py"
fi

exec python3 "$CHECK_PY"
