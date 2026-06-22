#!/usr/bin/env bash
# =============================================================================
# run-vps-readiness-check.sh
# VPS readiness gate — run on the VPS as the deploy user (non-interactive).
# Used by deploy.yml, ci.yml vps-readiness, and vps-smoke-test jobs.
#
# Usage: bash /home/deploy/run-vps-readiness-check.sh
# =============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/app}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CHECKS_SCRIPT="${SCRIPT_DIR}/deploy-async-stack-checks.sh"
if [[ ! -f "${CHECKS_SCRIPT}" ]]; then
    CHECKS_SCRIPT="/home/deploy/deploy-async-stack-checks.sh"
fi
if [[ ! -f "${CHECKS_SCRIPT}" ]]; then
    CHECKS_SCRIPT="${APP_DIR}/scripts/deploy-async-stack-checks.sh"
fi
# shellcheck source=deploy-async-stack-checks.sh
source "${CHECKS_SCRIPT}"

MISSING=""
[[ -d "${APP_DIR}" ]]              || MISSING="${MISSING} /home/deploy/app (app directory)"
[[ -f "${APP_DIR}/backend/.env" ]] || MISSING="${MISSING} /home/deploy/app/backend/.env"
[[ -d "${APP_DIR}/frontend" ]]     || MISSING="${MISSING} /home/deploy/app/frontend"
git -C "${APP_DIR}" rev-parse --git-dir > /dev/null 2>&1 \
    || MISSING="${MISSING} /home/deploy/app/.git (not a git repo)"

if [[ ! -f /home/deploy/backup.conf ]]; then
    echo "NOTE: /home/deploy/backup.conf not found — Deploy step will create a stub automatically."
fi

if [[ -n "${MISSING}" ]]; then
    echo "ERROR: Required VPS files/directories missing:${MISSING}"
    echo "The VPS may not be fully provisioned. Run the vps-setup scripts first."
    exit 1
fi

if [[ ! -f /home/deploy/deploy.sh ]]; then
    echo "NOTE: /home/deploy/deploy.sh not yet present — will be copied in the Deploy step."
fi

echo "Checking passwordless sudo for deploy (non-interactive)..."
assert_gunicorn_sudo_ready || exit 1
echo "    gunicorn reload sudo: ok"

assert_async_stack_sudo_ready || exit 1

if ! systemctl list-unit-files celery.service &>/dev/null 2>&1; then
    echo "    celery.service not installed — bootstrap sudo verified"
    echo "NOTE: Async stack not yet provisioned. Deploy step 7 will run bootstrap."
else
    echo "    async stack unit files: present"
    verify_async_stack_services || exit 1
    echo "    redis/celery services: active"
fi

echo "VPS readiness check passed."
