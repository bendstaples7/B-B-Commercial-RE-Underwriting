#!/usr/bin/env bash
# =============================================================================
# ci-ensure-vps-readiness.sh
# Run on the GitHub Actions runner: copy readiness scripts, check VPS, optionally
# auto-migrate as root when VPS_ROOT_SSH_KEY is set.
#
# Exit codes from run-vps-readiness-check.sh:
#   0 — ready
#   1 — hard failure (missing files, sudo, redis down, etc.)
#   2 — celery/beat ensure failed after restart attempt
#
# Set SOFT_ASYNC_ENSURE_FAILURE=1 (CI smoke only) to treat exit 2 as a warning
# so Deploy is not skipped; Deploy itself re-ensures without this flag.
# Redis / other hard failures always exit 1 and still fail CI.
#
# Usage:
#   VPS_USER=deploy VPS_HOST=... SSH_KEY_PATH=~/.ssh/id_deploy \
#     TARGET_SHA=<optional> VPS_ROOT_SSH_KEY=<optional> \
#     bash scripts/ci-ensure-vps-readiness.sh
# =============================================================================

set -euo pipefail

VPS_USER="${VPS_USER:?VPS_USER required}"
VPS_HOST="${VPS_HOST:?VPS_HOST required}"
SSH_KEY_PATH="${SSH_KEY_PATH:?SSH_KEY_PATH required}"
APP_DIR="${APP_DIR:-/home/deploy/app}"

SSH_DEPLOY=(ssh -i "${SSH_KEY_PATH}" -o ConnectTimeout=10 "${VPS_USER}@${VPS_HOST}")
SCP_DEPLOY=(scp -i "${SSH_KEY_PATH}" -o ConnectTimeout=10)

echo "Copying readiness scripts to VPS..."
"${SCP_DEPLOY[@]}" scripts/run-vps-readiness-check.sh \
    scripts/deploy-async-stack-checks.sh \
    "${VPS_USER}@${VPS_HOST}:/home/deploy/"

run_readiness() {
    "${SSH_DEPLOY[@]}" "bash /home/deploy/run-vps-readiness-check.sh"
}

READINESS_LOG=$(mktemp)
trap 'rm -f "${READINESS_LOG}"' EXIT

set +e
run_readiness > "${READINESS_LOG}" 2>&1
READINESS_CODE=$?
set -e
cat "${READINESS_LOG}"

if [[ "${READINESS_CODE}" -eq 0 ]]; then
    echo "VPS readiness check passed."
    exit 0
fi

if [[ "${READINESS_CODE}" -eq 2 ]]; then
    if [[ "${SOFT_ASYNC_ENSURE_FAILURE:-}" == "1" ]]; then
        echo "::warning::VPS async stack ensure failed (exit 2). CI success/Deploy not blocked; Deploy will re-ensure celery/redis."
        exit 0
    fi
    echo "ERROR: VPS async stack ensure failed (celery/redis unhealthy after restart attempt)."
    exit 1
fi

if [[ -z "${VPS_ROOT_SSH_KEY:-}" ]]; then
    echo "ERROR: VPS readiness failed and VPS_ROOT_SSH_KEY is not set."
    echo "Run on VPS as root: sudo bash ${APP_DIR}/scripts/vps-setup/migrate-async-stack.sh"
    exit 1
fi

if ! grep -qE 'bootstrap-async-stack|migrate-async-stack|async stack bootstrap' "${READINESS_LOG}"; then
    echo "ERROR: VPS readiness failed for a reason other than async-stack provisioning."
    echo "Auto-migrate only runs for missing bootstrap sudo / async stack."
    exit 1
fi

echo "AUTO-MIGRATE: VPS not provisioned for async stack — running migrate-async-stack.sh as root"

ROOT_KEY=$(mktemp)
trap 'rm -f "${READINESS_LOG}" "${ROOT_KEY}"' EXIT
echo "${VPS_ROOT_SSH_KEY}" > "${ROOT_KEY}"
chmod 600 "${ROOT_KEY}"

SSH_ROOT=(ssh -i "${ROOT_KEY}" -o ConnectTimeout=10 -o StrictHostKeyChecking=yes "root@${VPS_HOST}")

# Copy vps-setup scripts so migrate uses the same revision as this workflow run.
"${SCP_DEPLOY[@]}" -r scripts/vps-setup "${VPS_USER}@${VPS_HOST}:/home/deploy/ci-vps-setup"

"${SSH_ROOT[@]}" bash -s <<EOF
set -euo pipefail
APP_DIR="${APP_DIR}"
mkdir -p "\${APP_DIR}/scripts"
cp -r /home/deploy/ci-vps-setup "\${APP_DIR}/scripts/vps-setup"
bash "\${APP_DIR}/scripts/vps-setup/migrate-async-stack.sh"
rm -rf /home/deploy/ci-vps-setup
EOF

echo "AUTO-MIGRATE complete — re-running VPS readiness check..."
run_readiness
