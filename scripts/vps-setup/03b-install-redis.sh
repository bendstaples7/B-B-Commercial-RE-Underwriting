#!/usr/bin/env bash
# =============================================================================
# 03b-install-redis.sh
# Install and enable Redis for Celery broker/result backend.
#
# Run ON THE VPS as root (once, or idempotently):
#   sudo bash /home/deploy/app/scripts/vps-setup/03b-install-redis.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
die()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash $0"

info "Waiting for apt locks to be released..."
while fuser /var/lib/apt/lists/lock /var/lib/dpkg/lock /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
    echo "  apt is locked — waiting 5 seconds..."
    sleep 5
done

info "Installing redis-server..."
apt-get update -qq
apt-get install -y -qq redis-server

info "Enabling and starting redis-server..."
systemctl enable redis-server
systemctl start redis-server

if systemctl is-active --quiet redis-server; then
    info "redis-server is active"
else
    die "redis-server failed to start — check: journalctl -u redis-server -n 30"
fi

info "03b complete — Redis is ready for Celery"
