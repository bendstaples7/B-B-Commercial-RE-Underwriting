#!/usr/bin/env bash
# 14-install-rollback.sh
# Copies the rollback script to /home/deploy/rollback.sh and sets permissions.
# Run as root (or via sudo) on the VPS.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing rollback script to /home/deploy/rollback.sh"
cp "$SCRIPT_DIR/rollback.sh" /home/deploy/rollback.sh
chown deploy:deploy /home/deploy/rollback.sh
chmod 750 /home/deploy/rollback.sh

echo "==> Verifying permissions"
ls -la /home/deploy/rollback.sh

echo "==> rollback.sh installed successfully."
echo "    Usage: sudo -u deploy /home/deploy/rollback.sh [<commit-hash>]"
echo "    Log:   /home/deploy/rollback.log"
