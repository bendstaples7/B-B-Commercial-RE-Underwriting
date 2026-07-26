#!/usr/bin/env bash
# =============================================================================
# celery-liveness-check.sh
# Cron/timer: ensure celery (+ beat) are active; self-heal; alert if still down.
# Also soft-restarts Celery when RSS or host MemAvailable crosses thresholds
# (before host OOM thrash blanks the UI). Soft-restart alerts use a separate
# cooldown from hard-down alerts so one does not suppress the other.
# Installed by install-backup-cron.sh (ops cron marker). Safe during deploy via
# CELERY_DEPLOY_MARKER mtime (shared with deploy-async-stack-checks.sh).
#
# Usage: bash /home/deploy/celery-liveness-check.sh
# =============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/app}"
ALERT_STATE="${CELERY_LIVENESS_ALERT_STATE:-/home/deploy/.celery_liveness_alerted}"
ALERT_COOLDOWN_SECS="${CELERY_LIVENESS_ALERT_COOLDOWN_SECS:-21600}"  # 6 hours
# Soft-restart alerts — separate from hard-down ALERT_STATE.
SOFT_ALERT_STATE="${CELERY_SOFT_ALERT_STATE:-/home/deploy/.celery_soft_restart_alerted}"
SOFT_ALERT_COOLDOWN_SECS="${CELERY_SOFT_ALERT_COOLDOWN_SECS:-21600}"
# Soft memory recycle (before systemd MemoryMax / host OOM).
CELERY_SOFT_RSS_MIB="${CELERY_SOFT_RSS_MIB:-500}"
HOST_MIN_AVAILABLE_MIB="${HOST_MIN_AVAILABLE_MIB:-200}"
SOFT_RESTART_STATE="${CELERY_SOFT_RESTART_STATE:-/home/deploy/.celery_soft_restart_at}"
SOFT_RESTART_COOLDOWN_SECS="${CELERY_SOFT_RESTART_COOLDOWN_SECS:-900}"  # 15 min
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

_send_ops_alert() {
    local subject="$1"
    local body="$2"
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
}

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
    _send_ops_alert "$subject" "$body"
    echo "$now_epoch" > "$ALERT_STATE" 2>/dev/null || true
}

maybe_soft_alert() {
    local subject="$1"
    local body="$2"
    local now_epoch
    now_epoch="$(date -u +%s)"
    if [[ -f "$SOFT_ALERT_STATE" ]]; then
        local last
        last="$(tr -d '\n' < "$SOFT_ALERT_STATE" 2>/dev/null || echo 0)"
        if [[ "$last" =~ ^[0-9]+$ ]] && [[ $((now_epoch - last)) -lt $SOFT_ALERT_COOLDOWN_SECS ]]; then
            log "soft-restart alert suppressed (cooldown): $subject"
            return 0
        fi
    fi
    _send_ops_alert "$subject" "$body"
    echo "$now_epoch" > "$SOFT_ALERT_STATE" 2>/dev/null || true
}

clear_alert_state() {
    if [[ -f "$ALERT_STATE" ]]; then
        rm -f "$ALERT_STATE" 2>/dev/null || true
        log "celery liveness recovered — cleared alert state"
    fi
}

# --- Soft memory pressure recycle -------------------------------------------

_mem_available_mib() {
    local kib
    kib="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null || echo "")"
    if [[ -z "$kib" || ! "$kib" =~ ^[0-9]+$ ]]; then
        echo ""
        return 0
    fi
    echo $((kib / 1024))
}

_celery_max_rss_mib() {
    local max_kib=0 rss_kib pid
    # shellcheck disable=SC2009
    while read -r pid; do
        [[ -z "$pid" ]] && continue
        rss_kib="$(awk '/VmRSS:/ {print $2}' "/proc/${pid}/status" 2>/dev/null || echo 0)"
        if [[ "$rss_kib" =~ ^[0-9]+$ ]] && [[ "$rss_kib" -gt "$max_kib" ]]; then
            max_kib=$rss_kib
        fi
    done < <(pgrep -f 'celery.*celery_worker' 2>/dev/null || true)
    echo $((max_kib / 1024))
}

_soft_restart_allowed() {
    local now_epoch last
    now_epoch="$(date -u +%s)"
    if [[ -f "$SOFT_RESTART_STATE" ]]; then
        last="$(tr -d '\n' < "$SOFT_RESTART_STATE" 2>/dev/null || echo 0)"
        if [[ "$last" =~ ^[0-9]+$ ]] && [[ $((now_epoch - last)) -lt $SOFT_RESTART_COOLDOWN_SECS ]]; then
            return 1
        fi
    fi
    return 0
}

maybe_soft_restart_for_memory() {
    local avail_mib rss_mib reason=""
    avail_mib="$(_mem_available_mib)"
    rss_mib="$(_celery_max_rss_mib)"

    if [[ -n "$rss_mib" && "$rss_mib" =~ ^[0-9]+$ && "$rss_mib" -ge "$CELERY_SOFT_RSS_MIB" ]]; then
        reason="celery_rss=${rss_mib}MiB>=${CELERY_SOFT_RSS_MIB}MiB"
    fi
    if [[ -n "$avail_mib" && "$avail_mib" =~ ^[0-9]+$ && "$avail_mib" -lt "$HOST_MIN_AVAILABLE_MIB" ]]; then
        if [[ -n "$reason" ]]; then
            reason="${reason}; MemAvailable=${avail_mib}MiB<${HOST_MIN_AVAILABLE_MIB}MiB"
        else
            reason="MemAvailable=${avail_mib}MiB<${HOST_MIN_AVAILABLE_MIB}MiB"
        fi
    fi

    if [[ -z "$reason" ]]; then
        log "memory ok: MemAvailable=${avail_mib:-?}MiB celery_rss=${rss_mib:-0}MiB"
        return 0
    fi

    if ! _soft_restart_allowed; then
        log "soft-restart suppressed (cooldown): $reason"
        return 0
    fi

    log "soft-restart celery: $reason"
    if sudo -n systemctl restart celery; then
        date -u +%s > "$SOFT_RESTART_STATE" 2>/dev/null || true
        # Log only on success by default; alert via soft channel (does not
        # suppress hard-down alerts). Prefer alerting on failure below.
        log "soft-restart succeeded: $reason"
        maybe_soft_alert \
            "Celery soft-restarted for memory pressure [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
            "Host $(hostname): ${reason}. Celery was restarted to avoid OOM thrash blanking the UI."
    else
        log "ERROR: soft-restart failed (sudo -n systemctl restart celery)"
        maybe_soft_alert \
            "Celery soft-restart FAILED [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
            "Host $(hostname): wanted restart because ${reason}, but sudo systemctl restart celery failed."
        return 1
    fi
    return 0
}

if ensure_async_stack_services; then
    clear_alert_state
    log "ok: redis/celery(+beat) active"
    maybe_soft_restart_for_memory || true
    exit 0
fi

log "FAILED: async stack unhealthy after ensure"
maybe_alert \
    "Celery/async stack down on VPS [$(date -u +%Y-%m-%dT%H:%M:%SZ)]" \
    "ensure_async_stack_services failed on $(hostname). Check: systemctl status celery celery-beat redis-server; journalctl -u celery -n 50."
exit 1
