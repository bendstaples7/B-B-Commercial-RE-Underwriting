#!/usr/bin/env bash
# =============================================================================
# 02-firewall-fail2ban.sh
# VPS Provisioning — Step 2: UFW Firewall + fail2ban
#
# Requirements: 1.4, 1.5
#
# What this script does:
#   1. Configures UFW: default deny inbound, allow outbound, open 22/80/443
#   2. Installs fail2ban
#   3. Writes /etc/fail2ban/jail.local (maxretry=5, findtime=600, bantime=3600)
#   4. Enables and starts fail2ban
#
# Idempotency:
#   - UFW rules are applied with --force to avoid interactive prompts; running
#     the script a second time re-applies the same rules without error.
#   - fail2ban install is idempotent via apt-get (no-op if already installed).
#   - jail.local is overwritten on each run (content is deterministic).
#   - systemctl enable/start are no-ops if the service is already running.
#
# Usage (run as root or with sudo):
#   sudo bash 02-firewall-fail2ban.sh
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo "[INFO]  $*"; }
ok()    { echo "[OK]    $*"; }
die()   { echo "[ERROR] $*" >&2; exit 1; }

# Must run as root
if [[ "$EUID" -ne 0 ]]; then
    die "This script must be run as root (use: sudo bash $0)"
fi

# ---------------------------------------------------------------------------
# 1. Configure UFW
# ---------------------------------------------------------------------------
info "Configuring UFW firewall..."

# Ensure ufw is installed (it ships with Ubuntu 22.04 but be explicit)
info "  Waiting for apt locks to be released before installing ufw..."
while fuser /var/lib/apt/lists/lock /var/lib/dpkg/lock /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
    echo "  apt is locked by another process — waiting 5 seconds..."
    sleep 5
done
info "  apt lock is free."
apt-get install -y ufw > /dev/null

# Set default policies
ufw --force default deny incoming
ufw --force default allow outgoing
ok "UFW defaults: deny incoming, allow outgoing"

# Allow only the three required ports
ufw allow 22/tcp   comment 'SSH'
ufw allow 80/tcp   comment 'HTTP'
ufw allow 443/tcp  comment 'HTTPS'
ok "UFW rules added: 22/tcp (SSH), 80/tcp (HTTP), 443/tcp (HTTPS)"

# Enable UFW using nohup so it runs after the SSH session ends.
# This prevents the SSH connection from being dropped when UFW activates.
# UFW rules are already saved — enabling just activates them.
info "Enabling UFW in background (avoids SSH session drop)..."
nohup bash -c 'sleep 2 && ufw --force enable' >/tmp/ufw-enable.log 2>&1 &
ok "UFW enable scheduled (will activate in ~2 seconds)"
sleep 4  # Wait for UFW to activate before continuing

# Verify UFW actually became active
if ! ufw status | grep -q "Status: active"; then
    die "UFW failed to activate — check /tmp/ufw-enable.log for details."
fi
ok "UFW is active"

# Show active rules for verification
info "Current UFW status:"
ufw status verbose

# ---------------------------------------------------------------------------
# 2. Install fail2ban
# ---------------------------------------------------------------------------
info "Installing fail2ban..."
# Wait for any background apt processes to finish before running apt-get
info "  Waiting for apt locks to be released..."
while fuser /var/lib/apt/lists/lock /var/lib/dpkg/lock /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
    echo "  apt is locked by another process — waiting 5 seconds..."
    sleep 5
done
info "  apt lock is free."
apt-get update -qq
apt-get install -y fail2ban
ok "fail2ban installed"

# ---------------------------------------------------------------------------
# 3. Write /etc/fail2ban/jail.local
# ---------------------------------------------------------------------------
info "Writing /etc/fail2ban/jail.local..."

cat > /etc/fail2ban/jail.local << 'EOF'
# /etc/fail2ban/jail.local
# Managed by 02-firewall-fail2ban.sh — do not edit manually.
#
# Settings:
#   maxretry = 5    ban after 5 failed attempts
#   findtime = 600  within a 10-minute window (600 seconds)
#   bantime  = 3600 ban lasts 1 hour (3600 seconds)

[sshd]
enabled  = true
port     = ssh
maxretry = 5
findtime = 600
bantime  = 3600
EOF

ok "jail.local written: maxretry=5, findtime=600, bantime=3600 for [sshd]"

# ---------------------------------------------------------------------------
# 4. Enable and start fail2ban
# ---------------------------------------------------------------------------
info "Enabling and starting fail2ban..."
systemctl enable fail2ban
systemctl restart fail2ban   # restart (not just start) so new jail.local is loaded

# Give it a moment to initialise
sleep 2

# Verify the service is active
if systemctl is-active --quiet fail2ban; then
    ok "fail2ban is active and running"
else
    die "fail2ban failed to start — check: journalctl -u fail2ban -n 50"
fi

# Show fail2ban status for the sshd jail
info "fail2ban sshd jail status:"
fail2ban-client status sshd 2>/dev/null || info "(jail not yet populated — this is normal on a fresh install)"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo " Step 2 complete: UFW firewall + fail2ban configured"
echo "============================================================"
echo " UFW open ports : 22 (SSH), 80 (HTTP), 443 (HTTPS)"
echo " fail2ban sshd  : maxretry=5  findtime=600s  bantime=3600s"
echo "============================================================"
