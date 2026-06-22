#!/usr/bin/env bash
# =============================================================================
# deploy-async-stack-checks.sh
# Shared async-stack sudo/service checks for deploy.sh and deploy.yml.
# Source this file — do not execute directly.
# =============================================================================

# When deploy.sh gains new sudo commands, existing VPSes need a one-time root run:
#   sudo bash /home/deploy/app/scripts/vps-setup/migrate-async-stack.sh

_require_passwordless_sudo() {
    local pattern="$1"
    local description="$2"
    if ! sudo -n -l 2>/dev/null | grep -qF "${pattern}"; then
        echo "FAILED: deploy user lacks passwordless sudo for: ${description}"
        echo "  Required sudo rule must include: ${pattern}"
        echo "  Run on VPS as root:"
        echo "    sudo bash ${APP_DIR:-/home/deploy/app}/scripts/vps-setup/migrate-async-stack.sh"
        return 1
    fi
    return 0
}

assert_async_stack_sudo_ready() {
    local app_dir="${APP_DIR:-/home/deploy/app}"

    _require_passwordless_sudo "/bin/systemctl restart celery" "celery restart" \
        || return 1
    _require_passwordless_sudo "/bin/systemctl restart celery-beat" "celery-beat restart" \
        || return 1
    _require_passwordless_sudo "/bin/systemctl is-active --quiet redis-server" "redis active check" \
        || return 1
    _require_passwordless_sudo "/bin/systemctl is-active --quiet celery" "celery active check" \
        || return 1
    _require_passwordless_sudo "/bin/systemctl is-active --quiet celery-beat" "celery-beat active check" \
        || return 1

    if ! systemctl list-unit-files celery.service &>/dev/null 2>&1; then
        _require_passwordless_sudo "/usr/local/sbin/bootstrap-async-stack" "async stack bootstrap" \
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
