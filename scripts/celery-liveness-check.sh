#!/usr/bin/env bash
# =============================================================================
# celery-liveness-check.sh
# Cron/timer: ensure celery (+ beat) are active; self-heal; alert if still down.
# Installed by install-backup-cron.sh (ops cron marker). Safe during deploy via
# CELERY_DEPLOY_MARKER mtime (shared with deploy-async-stack-checks.sh).
#
# Usage: bash /home/deploy/celery-liveness-check.sh
# =============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/app}"
ALERT_STATE="${CELERY_LIVENESS_ALERT_STATE:-/home/deploy/.celery_liveness_alerted}"
ALERT_COOLDOWN_SECS="${CELERY_LIVENESS_ALERT_COOLDOWN_SECS:-21600}"  # 6 hours
LOG_FILE_DEFAULT="/home/deploy/logs/celery-liveness.log"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKS_SCRIPT="${SCRIPT_DIR}/deploy-async-stack-checks.sh"
if [[ ! -f "${CHECKS_SCRIPT}" ]]; then
    CHECKS_SCRIPT="/home/deploy/deploy-async-stack-checks.sh"
fi
if [[ ! -f "${CHECKS_SCRIPT}" ]]; then
    CHECKS_SCRIPT="${APP_DIR}/scripts/deploy-async-stack-checks.sh"
fi

OPS_ALERT_LIB="${SCRIPT_DIR}/ops-alert.sh"
if [[ ! -f "${OPS_ALERT_LIB}" ]]; then
    OPS_ALERT_LIB="/home/deploy/ops-alert.sh"
fi

mkdir -p "$(dirname "$LOG_FILE_DEFAULT")" 2>/dev/null || true
log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE_DEFAULT" 2>/dev/null || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

if [[ ! -f "${CHECKS_SCRIPT}" ]]; then
    log "ERROR: deploy-async-stack-checks.sh not found"
    exit 1
fi
# shellcheck source=deploy-async-stack-checks.sh
source "${CHECKS_SCRIPT}"

# Skip when deploy intentionally stopped Celery (fresh marker by mtime).
if celery_deploy_marker_is_fresh; then
    age=$(( $(date -u +%s) - $(stat -c %Y "${CELERY_DEPLOY_MARKER}") ))
    log "skip: deploy marker present (mtime age ${age}s < ${CELERY_DEPLOY_MARKER_MAX_AGE_SECS}s)"
    exit 0
fi
# Stale marker left by SIGKILL — remove so ensure can heal.
if [[ -f "${CELERY_DEPLOY_MARKER}" ]]; then
    log "stale deploy marker — removing before ensure"
    rm -f "${CELERY_DEPLOY_MARKER}" 2>/dev/null || true
fi

if ! systemctl list-unit-files celery.service &>/dev/null 2>&1; then
    log "celery.service not installed — nothing to check"
    exit 0
fi

maybe_alert() {
    local subject="$1"
    local body="$2"
    local now_epoch
    now_epoch="$(date -u +%s)"
    if [[ -f "$ALERT_STATE" ]]; then
        local last
        last="$(tr -d '\n' < "$ALERT_STATE" 2>/dev/null || echo 0)"
        if [[ "$last" =~ ^[0-9]+$ ]] && [[ $((now_epoch - last)) -lt $ALERT_COOLDOWN_SECS ]]; then
            log "alert suppressed (cooldown): $subject"
            return 0
        fi
    fi
    if [[ -f /home/deploy/backup.conf ]]; then
        # shellcheck source=/dev/null
        source /home/deploy/backup.conf
    fi
    LOG_FILE="${LOG_FILE:-$LOG_FILE_DEFAULT}"
    ALERT_SUBJECT_PREFIX="[Ops Alert]"
    if [[ -f "${OPS_ALERT_LIB}" ]]; then
        # shellcheck source=ops-alert.sh
        source "${OPS_ALERT_LIB}"
        send_alert "$subject" "$body"
    else
        log "ALERT (no ops-alert.sh): $subject — $body"
    fi
    echo "$now_epoch" > "$ALERT_STATE" 2>/dev/null || true
}

clear_alert_state() {
    if [[ -f "$ALERT_STATE" ]]; then
        rm -f "$ALERT_STATE" 2>/dev/null || true
        log "celery liveness recovered — cleared alert state"
    fi
}

if ensure_async_stack_services; then
    clear_alert_state
    log "ok: redis/celery(+beat) active"
    exit 0
fi

log "FAILED: async stack unhealthy after ensure"
maybe_alert \
    "Celery/async stack down on VPS [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
    "ensure_async_stack_services failed on $(hostname). Check: systemctl status celery celery-beat redis-server; journalctl -u celery -n 50."
exit 1
