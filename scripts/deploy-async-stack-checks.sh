#!/usr/bin/env bash
# =============================================================================
# deploy-async-stack-checks.sh
# Shared async-stack sudo/service checks for deploy.sh and deploy.yml.
# Source this file — do not execute directly.
# =============================================================================

# When deploy.sh gains new sudo commands, existing VPSes need a one-time root run:
#   sudo bash /home/deploy/app/scripts/vps-setup/migrate-async-stack.sh

_require_passwordless_sudo() {
    local description="$1"
    shift
    if ! sudo -n -l "$@" >/dev/null 2>&1; then
        echo "FAILED: deploy user lacks passwordless sudo for: ${description}"
        echo "  Required: $*"
        echo "  Run on VPS as root:"
        echo "    sudo bash ${APP_DIR:-/home/deploy/app}/scripts/vps-setup/migrate-async-stack.sh"
        return 1
    fi
    return 0
}

assert_gunicorn_sudo_ready() {
    _require_passwordless_sudo "gunicorn reload" /bin/systemctl reload gunicorn
}

assert_celery_stop_sudo_ready() {
    _require_passwordless_sudo "celery stop" /bin/systemctl stop celery \
        || return 1
    _require_passwordless_sudo "celery-beat stop" /bin/systemctl stop celery-beat \
        || return 1
    return 0
}

assert_async_stack_sudo_ready() {
    _require_passwordless_sudo "celery restart" /bin/systemctl restart celery \
        || return 1
    _require_passwordless_sudo "celery-beat restart" /bin/systemctl restart celery-beat \
        || return 1
    _require_passwordless_sudo "redis active check" /bin/systemctl is-active --quiet redis-server \
        || return 1
    _require_passwordless_sudo "celery active check" /bin/systemctl is-active --quiet celery \
        || return 1
    _require_passwordless_sudo "celery-beat active check" /bin/systemctl is-active --quiet celery-beat \
        || return 1

    if ! systemctl list-unit-files celery.service &>/dev/null 2>&1; then
        _require_passwordless_sudo "async stack bootstrap" /usr/local/sbin/bootstrap-async-stack \
            || return 1
    fi

    return 0
}

verify_async_stack_services() {
    sudo -n systemctl is-active --quiet redis-server \
        || { echo "FAILED: redis-server not active"; return 1; }
    sudo -n systemctl is-active --quiet celery \
        || { echo "FAILED: celery not active"; return 1; }
    if systemctl list-unit-files celery-beat.service &>/dev/null 2>&1; then
        sudo -n systemctl is-active --quiet celery-beat \
            || { echo "FAILED: celery-beat not active"; return 1; }
    fi
    return 0
}

# Deploy writes this while Celery is stopped for memory prep. Liveness + ensure
# must not restart workers while the marker is fresh (mtime-based).
CELERY_DEPLOY_MARKER="${CELERY_DEPLOY_MARKER:-/home/deploy/.celery_stopped_for_deploy}"
# Max deploy window with Celery stopped (memory wait + backup + pip/migrate).
CELERY_DEPLOY_MARKER_MAX_AGE_SECS="${CELERY_DEPLOY_MARKER_MAX_AGE_SECS:-1500}"

celery_deploy_marker_is_fresh() {
    [[ -f "${CELERY_DEPLOY_MARKER}" ]] || return 1
    local mtime now age
    mtime="$(stat -c %Y "${CELERY_DEPLOY_MARKER}" 2>/dev/null)" || return 1
    now="$(date -u +%s)"
    age=$((now - mtime))
    [[ "${age}" -ge 0 && "${age}" -lt "${CELERY_DEPLOY_MARKER_MAX_AGE_SECS}" ]]
}

_ensure_unit_active() {
    local unit="$1"
    local wait_secs="${2:-15}"
    if sudo -n systemctl is-active --quiet "${unit}"; then
        return 0
    fi
    echo "    ${unit} inactive — attempting restart"
    if ! sudo -n systemctl restart "${unit}"; then
        echo "FAILED: ${unit} restart"
        return 1
    fi
    local i
    for ((i = 1; i <= wait_secs; i++)); do
        if sudo -n systemctl is-active --quiet "${unit}"; then
            echo "    ${unit}: active after restart (${i}s)"
            return 0
        fi
        sleep 1
    done
    echo "FAILED: ${unit} not active after restart"
    return 1
}

# Self-heal inactive celery/beat before failing CI readiness / pre-deploy gates.
# Uses passwordless restart already granted to the deploy user — no root key needed.
# Skips celery/beat restarts while deploy memory-prep marker is fresh.
#
# Return codes:
#   0 — healthy (or celery intentionally stopped for deploy)
#   1 — celery/beat ensure failed (soft for CI smoke → readiness exit 2)
#   3 — redis-server not active (hard infra → readiness exit 1)
ensure_async_stack_services() {
    if ! sudo -n systemctl is-active --quiet redis-server; then
        echo "FAILED: redis-server not active"
        return 3
    fi

    if celery_deploy_marker_is_fresh; then
        echo "    celery: deploy stop marker fresh — skip restart (memory prep in progress)"
        return 0
    fi

    _ensure_unit_active celery 20 || return 1
    if systemctl list-unit-files celery-beat.service &>/dev/null 2>&1; then
        _ensure_unit_active celery-beat 15 || return 1
    fi
    return 0
}
