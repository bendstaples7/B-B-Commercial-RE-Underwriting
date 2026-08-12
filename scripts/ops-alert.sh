#!/usr/bin/env bash
# =============================================================================
# ops-alert.sh
# Shared email/webhook alert helper for backup + ops scripts.
# Source AFTER backup.conf (or equivalent) so LOG_FILE / ALERT_METHOD are set.
#
# Optional env:
#   ALERT_SUBJECT_PREFIX  — default "[Ops Alert]"
#
# After send_alert returns, OPS_ALERT_DELIVERY_FAILED is 0 on success / 1 on
# delivery failure. send_alert itself always exits 0 so callers under
# `set -euo pipefail` are not aborted (historical contract). Log writes are
# best-effort so a full/unwritable log cannot skip email/webhook delivery.
# =============================================================================

send_alert() {
    local subject="$1"
    local body="$2"
    local prefix="${ALERT_SUBJECT_PREFIX:-[Ops Alert]}"
    local log_target="${LOG_FILE:-/home/deploy/logs/ops-alert.log}"
    # Single-line subject for RFC822 header (msmtp has no CLI subject flag).
    local full_subject
    full_subject="$(printf '%s %s' "$prefix" "$subject" | tr '\n\r' '  ')"
    local delivery_failed=0
    local err_tmp=""

    _ops_alert_log() {
        # Best-effort only — never abort the caller on log I/O failure.
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "$log_target" 2>/dev/null || true
    }

    mkdir -p "$(dirname "$log_target")" 2>/dev/null || true
    _ops_alert_log "ALERT: $subject"

    if [[ "${ALERT_METHOD:-}" == "email" || "${ALERT_METHOD:-}" == "both" ]]; then
        # msmtp expects a full message on stdin (headers + blank line + body).
        err_tmp="$(mktemp 2>/dev/null || true)"
        if [[ -n "$err_tmp" ]]; then
            if ! {
                printf 'Subject: %s\n' "$full_subject"
                printf '\n'
                printf '%s\n' "$body"
            } | msmtp --account="${MSMTP_ACCOUNT:-default}" "${ALERT_EMAIL:-}" \
                2>"$err_tmp"
            then
                delivery_failed=1
                _ops_alert_log "ALERT DELIVERY FAILED (email)"
            fi
            if [[ -s "$err_tmp" ]]; then
                cat "$err_tmp" >> "$log_target" 2>/dev/null || true
            fi
            rm -f "$err_tmp" 2>/dev/null || true
        else
            if ! {
                printf 'Subject: %s\n' "$full_subject"
                printf '\n'
                printf '%s\n' "$body"
            } | msmtp --account="${MSMTP_ACCOUNT:-default}" "${ALERT_EMAIL:-}" \
                2>/dev/null
            then
                delivery_failed=1
                _ops_alert_log "ALERT DELIVERY FAILED (email)"
            fi
        fi
    fi

    if [[ "${ALERT_METHOD:-}" == "webhook" || "${ALERT_METHOD:-}" == "both" ]]; then
        local payload
        payload="$(
            OPS_ALERT_PREFIX="$prefix" OPS_ALERT_SUBJECT="$subject" OPS_ALERT_BODY="$body" python3 -c '
import json, os
text = "{0} {1}\n{2}".format(
    os.environ.get("OPS_ALERT_PREFIX", "[Ops Alert]"),
    os.environ.get("OPS_ALERT_SUBJECT", ""),
    os.environ.get("OPS_ALERT_BODY", ""),
)
print(json.dumps({"text": text}))
'
        )" || payload=""
        if [[ -n "$payload" && -n "${WEBHOOK_URL:-}" ]]; then
            # --fail so HTTP 4xx/5xx count as delivery failures.
            err_tmp="$(mktemp 2>/dev/null || true)"
            if [[ -n "$err_tmp" ]]; then
                if ! curl -sS --fail -X POST "$WEBHOOK_URL" \
                    -H "Content-Type: application/json" \
                    -d "$payload" \
                    --max-time 10 2>"$err_tmp"
                then
                    delivery_failed=1
                    _ops_alert_log "ALERT DELIVERY FAILED (webhook)"
                fi
                if [[ -s "$err_tmp" ]]; then
                    cat "$err_tmp" >> "$log_target" 2>/dev/null || true
                fi
                rm -f "$err_tmp" 2>/dev/null || true
            else
                if ! curl -sS --fail -X POST "$WEBHOOK_URL" \
                    -H "Content-Type: application/json" \
                    -d "$payload" \
                    --max-time 10 2>/dev/null
                then
                    delivery_failed=1
                    _ops_alert_log "ALERT DELIVERY FAILED (webhook)"
                fi
            fi
        else
            delivery_failed=1
            _ops_alert_log "ALERT DELIVERY FAILED (webhook): empty payload or WEBHOOK_URL"
        fi
    fi

    if [[ -z "${ALERT_METHOD:-}" || "${ALERT_METHOD:-}" == "none" ]]; then
        _ops_alert_log "ALERT_METHOD unset/none — logged only: $subject"
    elif [[ "${ALERT_METHOD}" != "email" && "${ALERT_METHOD}" != "webhook" && "${ALERT_METHOD}" != "both" ]]; then
        delivery_failed=1
        _ops_alert_log "ALERT DELIVERY FAILED: unsupported ALERT_METHOD=${ALERT_METHOD}"
    fi

    OPS_ALERT_DELIVERY_FAILED="$delivery_failed"
    return 0
}
