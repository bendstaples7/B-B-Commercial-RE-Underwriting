#!/usr/bin/env bash
# =============================================================================
# migrate-async-stack.sh
# One-time migration for EXISTING VPSes before the first deploy that requires
# Redis + Celery (PR #57 async stack).
#
# Run ON THE VPS as root (not the deploy user):
#   sudo bash /home/deploy/app/scripts/vps-setup/migrate-async-stack.sh
#
# This script is idempotent — safe to re-run.
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()   { error "$*"; exit 1; }

APP_DIR="${APP_DIR:-/home/deploy/app}"
DEPLOY_USER="deploy"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash $0"

echo ""
echo "============================================================"
echo "  Async Stack Migration (existing VPS)"
echo "  Run once before deploys that require Redis/Celery"
echo "============================================================"
echo ""

if [[ ! -d "${APP_DIR}" ]]; then
    die "App directory not found: ${APP_DIR}"
fi

info "Provisioning Redis, Celery, Celery Beat, and deploy sudoers..."
bash "${SCRIPT_DIR}/bootstrap-async-stack.sh"

echo ""
info "Verifying systemd services..."
for svc in redis-server celery celery-beat; do
    if ! systemctl is-active --quiet "${svc}"; then
        die "${svc} is not active — check: journalctl -u ${svc} -n 50 --no-pager"
    fi
    info "  ✓ ${svc}: active"
done

echo ""
info "Verifying deploy user passwordless sudo rules..."
SUDO_LIST=$(sudo -u "${DEPLOY_USER}" sudo -n -l 2>&1 || true)

check_sudo_rule() {
    local pattern="$1"
    local label="$2"
    if echo "${SUDO_LIST}" | grep -qF "${pattern}"; then
        info "  ✓ ${label}"
    else
        die "Missing passwordless sudo for deploy user: ${label}"
    fi
}

check_sudo_rule "/bin/systemctl reload gunicorn" "gunicorn reload"
check_sudo_rule "/bin/systemctl restart celery" "celery restart"
check_sudo_rule "/bin/systemctl restart celery-beat" "celery-beat restart"
check_sudo_rule "/bin/systemctl is-active --quiet redis-server" "redis is-active"
check_sudo_rule "/bin/systemctl is-active --quiet celery" "celery is-active"
check_sudo_rule "/bin/systemctl is-active --quiet celery-beat" "celery-beat is-active"
check_sudo_rule "/usr/local/sbin/bootstrap-async-stack" "bootstrap-async-stack"

echo ""
info "Verifying deploy user can run bootstrap idempotently..."
sudo -u "${DEPLOY_USER}" sudo -n /usr/local/sbin/bootstrap-async-stack \
    || die "deploy user cannot run bootstrap-async-stack without a password"

echo ""
echo "============================================================"
echo "  Async stack migration complete"
echo "============================================================"
echo ""
echo "  Next step: re-trigger the GitHub Actions Deploy workflow"
echo "  (workflow_dispatch or push to main)."
echo ""
