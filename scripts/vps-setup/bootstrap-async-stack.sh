#!/usr/bin/env bash
# =============================================================================
# bootstrap-async-stack.sh
# Provision Redis + Celery worker + Celery Beat on the VPS.
# Invoked automatically by deploy.sh when celery.service is missing.
# Also safe to run manually as root for idempotent re-provisioning.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "${SCRIPT_DIR}/03b-install-redis.sh"
bash "${SCRIPT_DIR}/09b-celery-service.sh"
bash "${SCRIPT_DIR}/11-sudoers-deploy.sh"

echo ""
echo "Async stack bootstrap complete."
echo "  redis-server:  $(systemctl is-active redis-server)"
echo "  celery:        $(systemctl is-active celery)"
echo "  celery-beat:   $(systemctl is-active celery-beat)"
echo ""
echo "Next deploy will restart Celery and run post_deploy_sync.py automatically."
