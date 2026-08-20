#!/usr/bin/env bash
# =============================================================================
# pg-idle-xact-watchdog.sh
# Cron: terminate dangerous idle-in-transaction sessions (esp. AccessExclusiveLock)
# and alert via ops-alert.sh. Installed by install-backup-cron.sh.
#
# Usage: bash /home/deploy/pg-idle-xact-watchdog.sh
#        bash /home/deploy/pg-idle-xact-watchdog.sh --dry-run
# =============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/app}"
ALERT_STATE="${PG_IDLE_XACT_ALERT_STATE:-/home/deploy/.pg_idle_xact_alerted}"
ALERT_COOLDOWN_SECS="${PG_IDLE_XACT_ALERT_COOLDOWN_SECS:-21600}"
LOG_FILE="${LOG_FILE:-/home/deploy/logs/pg-idle-xact-watchdog.log}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPS_ALERT_LIB="${SCRIPT_DIR}/ops-alert.sh"
if [[ ! -f "${OPS_ALERT_LIB}" ]]; then
    OPS_ALERT_LIB="/home/deploy/ops-alert.sh"
fi

GUARD_PY="${SCRIPT_DIR}/pg_lock_guard.py"
if [[ ! -f "${GUARD_PY}" ]]; then
    GUARD_PY="/home/deploy/pg_lock_guard.py"
fi
if [[ ! -f "${GUARD_PY}" ]]; then
    GUARD_PY="${APP_DIR}/scripts/pg_lock_guard.py"
fi

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE" >/dev/null
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

send_ops_alert() {
    local subject="$1"
    local body="$2"
    if [[ -f "${OPS_ALERT_LIB}" ]]; then
        # shellcheck source=ops-alert.sh
        source "${OPS_ALERT_LIB}"
        send_alert "$subject" "$body" || true
    else
        log "ALERT (no ops-alert.sh): $subject — $body"
    fi
}

should_alert() {
    if [[ ! -f "$ALERT_STATE" ]]; then
        return 0
    fi
    local now mtime age
    now="$(date +%s)"
    mtime="$(stat -c %Y "$ALERT_STATE" 2>/dev/null || echo 0)"
    age=$((now - mtime))
    [[ "$age" -ge "$ALERT_COOLDOWN_SECS" ]]
}

mark_alerted() {
    date -u +%Y-%m-%dT%H:%M:%SZ > "$ALERT_STATE" 2>/dev/null || true
}

# Load DATABASE_URL from app .env when not already set (cron context).
if [[ -z "${DATABASE_URL:-}" ]]; then
    if [[ -f "${APP_DIR}/backend/.env" ]]; then
        set -a
        # shellcheck disable=SC1091
        source "${APP_DIR}/backend/.env"
        set +a
    fi
fi

DRY_ARGS=()
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_ARGS+=(--dry-run)
fi

if [[ ! -f "${GUARD_PY}" ]]; then
    log "ERROR: pg_lock_guard.py not found"
    exit 1
fi

set +e
OUT="$(python3.11 "${GUARD_PY}" watchdog "${DRY_ARGS[@]}" 2>&1)"
RC=$?
if [[ "$RC" -eq 127 ]]; then
    # Fallback when python3.11 is not on PATH (local/dev).
    OUT="$(python3 "${GUARD_PY}" watchdog "${DRY_ARGS[@]}" 2>&1)"
    RC=$?
fi
set -e
log "$OUT"

# Exit 0 = nothing to do; exit 1 = terminated (or would terminate) targets
if [[ "$RC" -eq 0 ]]; then
    rm -f "$ALERT_STATE" 2>/dev/null || true
    exit 0
fi

if [[ "$RC" -eq 1 ]]; then
    if should_alert; then
        send_ops_alert \
            "Postgres idle-in-transaction terminated" \
            "Watchdog terminated dangerous idle-in-transaction session(s) on $(hostname).

${OUT}

Investigate alembic/flask db upgrade hangs and AccessExclusiveLock holders."
        mark_alerted
    else
        log "terminate event suppressed by alert cooldown"
    fi
    exit 0
fi

log "watchdog failed with exit $RC"
exit "$RC"
