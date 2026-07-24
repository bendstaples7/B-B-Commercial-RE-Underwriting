#!/usr/bin/env bash
# =============================================================================
# ops-alert.sh
# Shared email/webhook alert helper for backup + ops scripts.
# Source AFTER backup.conf (or equivalent) so LOG_FILE / ALERT_METHOD are set.
#
# Optional env:
#   ALERT_SUBJECT_PREFIX  — default "[Ops Alert]"
# =============================================================================

send_alert() {
    local subject="$1"
    local body="$2"
    local prefix="${ALERT_SUBJECT_PREFIX:-[Ops Alert]}"
    local log_target="${LOG_FILE:-/home/deploy/logs/ops-alert.log}"

    mkdir -p "$(dirname "$log_target")" 2>/dev/null || true
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT: $subject" >> "$log_target"

    if [[ "${ALERT_METHOD:-}" == "email" || "${ALERT_METHOD:-}" == "both" ]]; then
        echo "$body" | msmtp --account="${MSMTP_ACCOUNT:-default}" "${ALERT_EMAIL:-}" \
            --subject="${prefix} ${subject}" 2>>"$log_target" \
            || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT DELIVERY FAILED (email): $?" >> "$log_target"
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
            curl -s -X POST "$WEBHOOK_URL" \
                -H "Content-Type: application/json" \
                -d "$payload" \
                --max-time 10 2>>"$log_target" \
                || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT DELIVERY FAILED (webhook): $?" >> "$log_target"
        else
            echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT DELIVERY FAILED (webhook): empty payload or WEBHOOK_URL" >> "$log_target"
        fi
    fi

    if [[ -z "${ALERT_METHOD:-}" || "${ALERT_METHOD:-}" == "none" ]]; then
        echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ALERT_METHOD unset/none — logged only: $subject" >> "$log_target"
    fi
}
