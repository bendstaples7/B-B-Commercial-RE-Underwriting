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
ALERT_FAIL_STATE="${PG_IDLE_XACT_FAIL_ALERT_STATE:-/home/deploy/.pg_idle_xact_fail_alerted}"
ALERT_COOLDOWN_SECS="${PG_IDLE_XACT_ALERT_COOLDOWN_SECS:-21600}"
LOG_FILE="${LOG_FILE:-/home/deploy/logs/pg-idle-xact-watchdog.log}"
LOCK_FILE="${PG_IDLE_XACT_LOCK_FILE:-/home/deploy/.pg_idle_xact_watchdog.lock}"
WATCHDOG_TIMEOUT_SEC="${PG_IDLE_XACT_TIMEOUT_SEC:-120}"

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

# Cron already redirects stdout to LOG_FILE — log once (no tee duplication).
log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

_load_alert_config() {
    if [[ -f /home/deploy/backup.conf ]]; then
        set +u
        # shellcheck disable=SC1091
        source /home/deploy/backup.conf
        set -u
    fi
}

send_ops_alert() {
    local subject="$1"
    local body="$2"
    _load_alert_config
    OPS_ALERT_DELIVERY_FAILED=1
    if [[ -f "${OPS_ALERT_LIB}" ]]; then
        # shellcheck source=ops-alert.sh
        source "${OPS_ALERT_LIB}"
        send_alert "$subject" "$body" || true
    else
        log "ALERT (no ops-alert.sh): $subject — $body"
        OPS_ALERT_DELIVERY_FAILED=1
    fi
}

should_alert_state() {
    local state_file="$1"
    if [[ ! -f "$state_file" ]]; then
        return 0
    fi
    local now mtime age
    now="$(date +%s)"
    mtime="$(stat -c %Y "$state_file" 2>/dev/null || echo 0)"
    age=$((now - mtime))
    [[ "$age" -ge "$ALERT_COOLDOWN_SECS" ]]
}

mark_alert_state() {
    local state_file="$1"
    date -u +%Y-%m-%dT%H:%M:%SZ > "$state_file" 2>/dev/null || true
}

# Pull DATABASE_URL only (do not source entire .env under set -u).
if [[ -z "${DATABASE_URL:-}" ]]; then
    ENV_FILE="${APP_DIR}/backend/.env"
    if [[ -f "$ENV_FILE" ]]; then
        DATABASE_URL="$(
            grep -E '^[[:space:]]*DATABASE_URL=' "$ENV_FILE" | head -1 \
                | sed -E 's/^[[:space:]]*DATABASE_URL=//' \
                | sed -E 's/^["'\'']//; s/["'\'']$//'
        )"
        export DATABASE_URL
    fi
fi

DRY_ARGS=()
if [[ $# -gt 1 ]]; then
    log "ERROR: unexpected arguments: $*"
    exit 2
fi
if [[ $# -eq 1 ]]; then
    if [[ "$1" != "--dry-run" ]]; then
        log "ERROR: unknown argument '$1' (only --dry-run is allowed)"
        exit 2
    fi
    DRY_ARGS+=(--dry-run)
fi

if [[ ! -f "${GUARD_PY}" ]]; then
    log "ERROR: pg_lock_guard.py not found"
    if should_alert_state "$ALERT_FAIL_STATE"; then
        send_ops_alert "Postgres idle-xact watchdog broken" \
            "pg_lock_guard.py missing on $(hostname). Watchdog cannot run."
        if [[ "${OPS_ALERT_DELIVERY_FAILED:-1}" -eq 0 ]]; then
            mark_alert_state "$ALERT_FAIL_STATE"
        fi
    fi
    exit 2
fi

# Serialize overlapping cron ticks; bound wall clock.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another watchdog instance holds $LOCK_FILE — exiting"
    exit 0
fi

set +e
OUT="$(timeout --signal=TERM --kill-after=15 "${WATCHDOG_TIMEOUT_SEC}" \
    python3.11 "${GUARD_PY}" watchdog "${DRY_ARGS[@]}" 2>&1)"
RC=$?
if [[ "$RC" -eq 127 ]]; then
    OUT="$(timeout --signal=TERM --kill-after=15 "${WATCHDOG_TIMEOUT_SEC}" \
        python3 "${GUARD_PY}" watchdog "${DRY_ARGS[@]}" 2>&1)"
    RC=$?
fi
set -e
log "$OUT"

# timeout exit 124
if [[ "$RC" -eq 124 ]] || [[ "$RC" -eq 137 ]]; then
    log "watchdog timed out after ${WATCHDOG_TIMEOUT_SEC}s"
    if should_alert_state "$ALERT_FAIL_STATE"; then
        send_ops_alert "Postgres idle-xact watchdog timed out" \
            "Watchdog exceeded ${WATCHDOG_TIMEOUT_SEC}s on $(hostname).

${OUT}"
        if [[ "${OPS_ALERT_DELIVERY_FAILED:-1}" -eq 0 ]]; then
            mark_alert_state "$ALERT_FAIL_STATE"
        fi
    fi
    exit 2
fi

if [[ "$RC" -eq 0 ]]; then
    rm -f "$ALERT_STATE" 2>/dev/null || true
    exit 0
fi

# 1 = terminated sessions (success alert path)
if [[ "$RC" -eq 1 ]]; then
    if should_alert_state "$ALERT_STATE"; then
        send_ops_alert \
            "Postgres idle-in-transaction terminated" \
            "Watchdog terminated dangerous idle-in-transaction session(s) on $(hostname).

${OUT}

Investigate alembic/flask db upgrade hangs and AccessExclusiveLock holders."
        if [[ "${OPS_ALERT_DELIVERY_FAILED:-1}" -eq 0 ]]; then
            mark_alert_state "$ALERT_STATE"
        else
            log "terminate alert delivery failed — not starting cooldown"
        fi
    else
        log "terminate event suppressed by alert cooldown"
    fi
    exit 0
fi

# 2+ = connection/runtime failure — do not claim sessions were killed
log "watchdog failed with exit $RC"
if should_alert_state "$ALERT_FAIL_STATE"; then
    send_ops_alert "Postgres idle-xact watchdog failed" \
        "Watchdog exited $RC on $(hostname) (not a terminate event).

${OUT}"
    if [[ "${OPS_ALERT_DELIVERY_FAILED:-1}" -eq 0 ]]; then
        mark_alert_state "$ALERT_FAIL_STATE"
    fi
fi
exit "$RC"
