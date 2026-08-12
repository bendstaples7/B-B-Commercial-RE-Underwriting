#!/usr/bin/env bash
# =============================================================================
# check-lead-cc-mount-health.sh
# Hourly: alert when Command Center JS loads but /command-center API is ~dead.
# Installed by install-backup-cron.sh (lead-cc-mount-health-managed).
#
# Usage: bash /home/deploy/check-lead-cc-mount-health.sh
# =============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/app}"
LOG_FILE_DEFAULT="/home/deploy/logs/lead-cc-mount-health.log"
ALERT_STATE="${LEAD_CC_MOUNT_ALERT_STATE:-/home/deploy/.lead_cc_mount_alerted}"
ALERT_COOLDOWN_SECS="${LEAD_CC_MOUNT_ALERT_COOLDOWN_SECS:-21600}"  # 6 hours
# Separate cooldown for infra/read failures so mount blanks and log-blind
# alerts do not suppress each other.
INFRA_ALERT_STATE="${LEAD_CC_MOUNT_INFRA_ALERT_STATE:-/home/deploy/.lead_cc_mount_infra_alerted}"
INFRA_ALERT_COOLDOWN_SECS="${LEAD_CC_MOUNT_INFRA_ALERT_COOLDOWN_SECS:-21600}"
NGINX_ACCESS_LOG="${NGINX_ACCESS_LOG:-/var/log/nginx/real-estate-access.log}"
WINDOW_HOURS="${LEAD_CC_MOUNT_WINDOW_HOURS:-24}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPS_ALERT_LIB="${SCRIPT_DIR}/ops-alert.sh"
if [[ ! -f "${OPS_ALERT_LIB}" ]]; then
    OPS_ALERT_LIB="/home/deploy/ops-alert.sh"
fi

HELPER_PY="${SCRIPT_DIR}/lead_cc_mount_health.py"
if [[ ! -f "${HELPER_PY}" ]]; then
    HELPER_PY="${APP_DIR}/scripts/lead_cc_mount_health.py"
fi
if [[ ! -f "${HELPER_PY}" ]]; then
    HELPER_PY="/home/deploy/lead_cc_mount_health.py"
fi

mkdir -p "$(dirname "$LOG_FILE_DEFAULT")" 2>/dev/null || true
log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE_DEFAULT" 2>/dev/null || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

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

_maybe_alert_state() {
    local state_file="$1"
    local cooldown="$2"
    local subject="$3"
    local body="$4"
    local now_epoch
    now_epoch="$(date -u +%s)"
    if [[ -f "$state_file" ]]; then
        local last
        last="$(tr -d '\n' < "$state_file" 2>/dev/null || echo 0)"
        if [[ "$last" =~ ^[0-9]+$ ]] && [[ $((now_epoch - last)) -lt $cooldown ]]; then
            log "alert suppressed (cooldown): $subject"
            return 0
        fi
    fi
    _send_ops_alert "$subject" "$body"
    echo "$now_epoch" > "$state_file" 2>/dev/null || true
}

maybe_alert() {
    _maybe_alert_state "$ALERT_STATE" "$ALERT_COOLDOWN_SECS" "$1" "$2"
}

maybe_infra_alert() {
    _maybe_alert_state "$INFRA_ALERT_STATE" "$INFRA_ALERT_COOLDOWN_SECS" "$1" "$2"
}

clear_alert_state() {
    if [[ -f "$ALERT_STATE" ]]; then
        rm -f "$ALERT_STATE" 2>/dev/null || true
        log "lead CC mount health recovered — cleared alert state"
    fi
}

# Infra / blind-scan path: alert and DO NOT clear mount-blank alert state.
fail_infra() {
    local reason="$1"
    log "ERROR: $reason"
    maybe_infra_alert \
        "Lead CC mount health check cannot read nginx logs" \
        "check-lead-cc-mount-health.sh failed: ${reason}

The blank-mount detector is blind until this is fixed (helper path, log ACL/sudo, or Python scan).
Do not treat the absence of blank-mount alerts as healthy while this fires."
    exit 1
}

if [[ ! -f "${HELPER_PY}" ]]; then
    fail_infra "lead_cc_mount_health.py not found (looked in SCRIPT_DIR/APP_DIR/home/deploy)"
fi

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
    if command -v python3.11 >/dev/null 2>&1; then
        PYTHON_BIN=python3.11
    else
        PYTHON_BIN=python3
    fi
fi

LOG_FILES=()
if [[ -f "${NGINX_ACCESS_LOG}.1" ]]; then
    LOG_FILES+=("${NGINX_ACCESS_LOG}.1")
fi
if [[ -f "$NGINX_ACCESS_LOG" ]]; then
    LOG_FILES+=("$NGINX_ACCESS_LOG")
fi

if [[ ${#LOG_FILES[@]} -eq 0 ]]; then
    fail_infra "nginx access log not found at $NGINX_ACCESS_LOG (and .1)"
fi

BYTES_READ=0
LOG_TMP="$(mktemp)"
trap 'rm -f "$LOG_TMP"' EXIT

_read_logs_to_tmp() {
    local f
    local ok=0
    : > "$LOG_TMP"
    for f in "${LOG_FILES[@]}"; do
        if cat "$f" >> "$LOG_TMP" 2>/dev/null; then
            ok=1
            continue
        fi
        if sudo -n cat "$f" >> "$LOG_TMP" 2>/dev/null; then
            ok=1
            continue
        fi
        log "WARN: cannot read $f (cat and sudo -n cat failed)"
    done
    if [[ "$ok" -eq 0 ]]; then
        return 1
    fi
    BYTES_READ="$(wc -c < "$LOG_TMP" | tr -d ' ')"
    if [[ -z "$BYTES_READ" || "$BYTES_READ" -eq 0 ]]; then
        return 1
    fi
    return 0
}

if ! _read_logs_to_tmp; then
    fail_infra "unable to read any bytes from nginx access log(s): ${LOG_FILES[*]} (need read ACL or passwordless sudo -n for deploy)"
fi

DECISION_JSON="$(
    WINDOW_HOURS="$WINDOW_HOURS" HELPER_PY="$HELPER_PY" "$PYTHON_BIN" -c "
import json, os, sys, importlib.util
from pathlib import Path
helper_path = Path(os.environ['HELPER_PY'])
spec = importlib.util.spec_from_file_location('lead_cc_mount_health', helper_path)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
window = float(os.environ.get('WINDOW_HOURS', '24'))
with open(sys.argv[1], encoding='utf-8', errors='replace') as fh:
    counts = mod.count_mount_health(fh, window_hours=window)
decision = mod.decide_mount_health(counts)
print(json.dumps({
    'unhealthy': decision.unhealthy,
    'reason': decision.reason,
    'ulcc_loads': counts.ulcc_loads,
    'command_center_hits': counts.command_center_hits,
    'window_start': counts.window_start.isoformat(),
    'window_end': counts.window_end.isoformat(),
}))
" "$LOG_TMP"
)" || {
    fail_infra "failed to scan nginx logs (python helper crash)"
}

UNHEALTHY="$("$PYTHON_BIN" -c "import json,sys; print('1' if json.load(sys.stdin)['unhealthy'] else '0')" <<< "$DECISION_JSON")"
REASON="$("$PYTHON_BIN" -c "import json,sys; print(json.load(sys.stdin)['reason'])" <<< "$DECISION_JSON")"
ULCC="$("$PYTHON_BIN" -c "import json,sys; print(json.load(sys.stdin)['ulcc_loads'])" <<< "$DECISION_JSON")"
CC="$("$PYTHON_BIN" -c "import json,sys; print(json.load(sys.stdin)['command_center_hits'])" <<< "$DECISION_JSON")"

log "scan: bytes=$BYTES_READ ulcc=$ULCC command_center=$CC reason=$REASON"

if [[ "$UNHEALTHY" == "1" ]]; then
    maybe_alert \
        "Lead Command Center mount appears blank" \
        "Nginx access log (last ${WINDOW_HOURS}h): UnifiedLeadCommandCenter JS loads=${ULCC}, /api/leads/*/command-center hits=${CC}.
Reason: ${REASON}

This pattern means the lead detail SPA chunk loaded but the command-center API never ran — users likely see a blank lead page.
Check: recent deploy, browser console on /leads/:id, and CI lead-cc-mount-smoke."
    exit 1
fi

clear_alert_state
# Successful healthy scan — clear infra alert state too.
if [[ -f "$INFRA_ALERT_STATE" ]]; then
    rm -f "$INFRA_ALERT_STATE" 2>/dev/null || true
    log "lead CC mount infra check recovered — cleared infra alert state"
fi
exit 0
