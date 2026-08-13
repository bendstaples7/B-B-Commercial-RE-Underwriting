#!/usr/bin/env bash
# =============================================================================
# spa-uptime-canary.sh
# Every ~5 minutes: ensure nginx can serve SPA assets, auto-heal mode 0700,
# alert on unreachable assets / healed bad perms / dist changes outside Deploy.
#
# Soft lock only — does not hard-block scp/cp. Emergency manual UI updates should
# run ensure_frontend_dist_readable.sh and refresh the fingerprint via Deploy
# when possible.
#
# Installed by install-backup-cron.sh. Safe during Deploy via SPA_DEPLOY_IN_PROGRESS.
#
# Usage: bash /home/deploy/spa-uptime-canary.sh
# =============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/app}"
DIST="${SPA_DIST_DIR:-$APP_DIR/frontend/dist}"
DEPLOY_MARKER="${SPA_DEPLOY_IN_PROGRESS:-/home/deploy/SPA_DEPLOY_IN_PROGRESS}"
DEPLOY_MARKER_MAX_AGE_SECS="${SPA_DEPLOY_MARKER_MAX_AGE_SECS:-900}"  # 15 min
FINGERPRINT_FILE="${SPA_DIST_FINGERPRINT:-/home/deploy/spa-dist.fingerprint}"
LOG_FILE_DEFAULT="/home/deploy/logs/spa-uptime-canary.log"
ALERT_STATE_UNREACHABLE="${SPA_ALERT_UNREACHABLE:-/home/deploy/.spa_canary_unreachable_alerted}"
ALERT_STATE_HEALED="${SPA_ALERT_HEALED:-/home/deploy/.spa_canary_healed_alerted}"
ALERT_STATE_DRIFT="${SPA_ALERT_DRIFT:-/home/deploy/.spa_canary_drift_alerted}"
ALERT_COOLDOWN_SECS="${SPA_CANARY_ALERT_COOLDOWN_SECS:-900}"  # 15 min

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ENSURE_SCRIPT="/home/deploy/ensure_frontend_dist_readable.sh"
if [[ ! -f "${ENSURE_SCRIPT}" ]]; then
    ENSURE_SCRIPT="${SCRIPT_DIR}/ensure_frontend_dist_readable.sh"
fi
if [[ ! -f "${ENSURE_SCRIPT}" ]]; then
    ENSURE_SCRIPT="${APP_DIR}/scripts/ensure_frontend_dist_readable.sh"
fi

FP_SCRIPT="/home/deploy/spa-dist-fingerprint.sh"
if [[ ! -f "${FP_SCRIPT}" ]]; then
    FP_SCRIPT="${SCRIPT_DIR}/spa-dist-fingerprint.sh"
fi
if [[ ! -f "${FP_SCRIPT}" ]]; then
    FP_SCRIPT="${APP_DIR}/scripts/spa-dist-fingerprint.sh"
fi

OPS_ALERT_LIB="${SCRIPT_DIR}/ops-alert.sh"
if [[ ! -f "${OPS_ALERT_LIB}" ]]; then
    OPS_ALERT_LIB="/home/deploy/ops-alert.sh"
fi

mkdir -p "$(dirname "$LOG_FILE_DEFAULT")" 2>/dev/null || true
log() {
    local line
    line="[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
    if [[ -t 1 ]]; then
        echo "$line" | tee -a "$LOG_FILE_DEFAULT" 2>/dev/null || echo "$line"
    else
        echo "$line"
    fi
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
        [[ "${OPS_ALERT_DELIVERY_FAILED:-0}" != "1" ]]
    else
        log "ALERT (no ops-alert.sh): $subject — $body"
    fi
}

maybe_alert() {
    local state_file="$1"
    local subject="$2"
    local body="$3"
    local now_epoch
    now_epoch="$(date -u +%s)"
    if [[ -f "$state_file" ]]; then
        local last
        last="$(tr -d '\n' < "$state_file" 2>/dev/null || echo 0)"
        if [[ "$last" =~ ^[0-9]+$ ]] && [[ $((now_epoch - last)) -lt $ALERT_COOLDOWN_SECS ]]; then
            log "alert suppressed (cooldown): $subject"
            return 0
        fi
    fi
    if _send_ops_alert "$subject" "$body"; then
        tmp="${state_file}.$$.$RANDOM.tmp"
        if ! printf '%s\n' "$now_epoch" > "$tmp" || ! mv -f "$tmp" "$state_file"; then
            rm -f "$tmp" 2>/dev/null || true
        fi
    else
        log "alert delivery failed; cooldown not updated: $subject"
    fi
    return 0
}

bad_spa_perm_summary() {
    local first_bad
    local dist_mode dist_other
    dist_mode="$(stat -c '%a' "$DIST" 2>/dev/null || echo "")"
    if [[ -n "$dist_mode" ]]; then
        dist_other=$((10#$dist_mode % 10))
        if [[ $((dist_other & 1)) -ne 1 ]]; then
            printf 'dist root lacks other+x: %s' "$dist_mode"
            return 0
        fi
    fi
    if [[ ! -x "$DIST" ]]; then
        printf 'dist root is not traversable by deploy user: %s' "${dist_mode:-unknown}"
        return 0
    fi
    first_bad="$(find "$DIST" -type d ! -perm -0001 -print -quit 2>/dev/null || true)"
    if [[ -n "$first_bad" ]]; then
        printf 'directory lacks other+x: %s mode %s' "$first_bad" "$(stat -c '%a' "$first_bad" 2>/dev/null || echo unknown)"
        return 0
    fi
    first_bad="$(find "$DIST" -type f ! -perm -0004 -print -quit 2>/dev/null || true)"
    if [[ -n "$first_bad" ]]; then
        printf 'file lacks other+r: %s mode %s' "$first_bad" "$(stat -c '%a' "$first_bad" 2>/dev/null || echo unknown)"
        return 0
    fi
    return 1
}

# Skip while Deploy owns the frontend swap window.
if [[ -f "$DEPLOY_MARKER" ]]; then
    age=$(( $(date -u +%s) - $(stat -c %Y "$DEPLOY_MARKER" 2>/dev/null || echo 0) ))
    if [[ "$age" -lt "$DEPLOY_MARKER_MAX_AGE_SECS" ]]; then
        log "skip: SPA deploy in progress (marker age ${age}s)"
        exit 0
    fi
    log "stale SPA deploy marker (age ${age}s) — removing"
    rm -f "$DEPLOY_MARKER" 2>/dev/null || true
fi

if [[ ! -d "$DIST" || ! -f "$DIST/index.html" ]]; then
    log "ERROR: missing SPA dist at $DIST"
    maybe_alert "$ALERT_STATE_UNREACHABLE" \
        "SPA dist missing" \
        "spa-uptime-canary: $DIST/index.html missing on $(hostname). Site may be blank."
    exit 1
fi

if [[ ! -f "${ENSURE_SCRIPT}" ]]; then
    log "ERROR: ensure_frontend_dist_readable.sh not found"
    exit 1
fi

need_heal=0
perm_issue_before=""
if perm_issue_before="$(bad_spa_perm_summary)"; then
    need_heal=1
    log "${perm_issue_before} — will heal"
fi

cd "$APP_DIR"
set +e
ensure_out="$(bash "${ENSURE_SCRIPT}" "$DIST" --http-base http://127.0.0.1 2>&1)"
ensure_rc=$?
set -e
printf '%s\n' "$ensure_out" | while IFS= read -r line; do log "ensure: $line"; done

if [[ "$ensure_rc" -ne 0 ]]; then
    log "ERROR: SPA asset ensure/HTTP smoke failed (rc=$ensure_rc)"
    maybe_alert "$ALERT_STATE_UNREACHABLE" \
        "SPA assets unreachable" \
        "spa-uptime-canary: ensure_frontend_dist_readable failed on $(hostname).
DIST=$DIST
output:
$ensure_out"
    exit 1
fi

# Heal succeeded after bad perms — still yell so silent 0700 rewrites are visible.
if [[ "$need_heal" -eq 1 ]]; then
    perm_issue_after="$(bad_spa_perm_summary || true)"
    maybe_alert "$ALERT_STATE_HEALED" \
        "SPA asset perms auto-healed" \
        "spa-uptime-canary healed frontend/dist permissions on $(hostname).
before=${perm_issue_before}
after=${perm_issue_after:-healthy}
Something wrote frontend/dist with nginx-inaccessible permissions (blank SPA class)."
fi

# Soft lock: fingerprint drift without Deploy updating the stamp.
if [[ -f "${FP_SCRIPT}" ]]; then
    current_fp="$(APP_DIR="$APP_DIR" bash "${FP_SCRIPT}" compute "$DIST" || true)"
    stored_fp=""
    if [[ -f "$FINGERPRINT_FILE" ]]; then
        stored_fp="$(tr -d '[:space:]' < "$FINGERPRINT_FILE" || true)"
    fi
    if [[ -n "$current_fp" && -n "$stored_fp" && "$current_fp" != "$stored_fp" ]]; then
        log "fingerprint drift: stored=$stored_fp current=$current_fp"
        maybe_alert "$ALERT_STATE_DRIFT" \
            "SPA dist changed outside Deploy" \
            "spa-uptime-canary detected frontend/dist fingerprint drift on $(hostname).
stored=$stored_fp
current=$current_fp
DEPLOY_SHA=$(tr -d '[:space:]' < "$APP_DIR/DEPLOY_SHA" 2>/dev/null || echo unknown)
Blessed path: Deploy (or refresh fingerprint after intentional emergency copy)."
    elif [[ -n "$current_fp" && -z "$stored_fp" ]]; then
        # First run after upgrade — seed fingerprint without alerting.
        tmp="${FINGERPRINT_FILE}.$$.$RANDOM.tmp"
        if ! printf '%s\n' "$current_fp" > "$tmp" || ! mv -f "$tmp" "$FINGERPRINT_FILE"; then
            rm -f "$tmp" 2>/dev/null || true
        fi
        log "seeded fingerprint file (first canary run)"
    fi
else
    log "WARN: spa-dist-fingerprint.sh missing — skip drift check"
fi

log "OK: SPA assets healthy"
exit 0
