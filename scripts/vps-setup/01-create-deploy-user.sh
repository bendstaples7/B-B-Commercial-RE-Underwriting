#!/usr/bin/env bash
# =============================================================================
# 01-create-deploy-user.sh
# VPS Setup — Task 1.1: Create deploy user with sudo + SSH key-only access
#
# Requirements: 1.2, 1.3
#
# Run as root on the Hetzner CX22 VPS (Ubuntu 22.04 LTS):
#   sudo bash 01-create-deploy-user.sh
#
# This script is IDEMPOTENT — safe to run multiple times.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# CONFIGURATION
# Replace the placeholder below with the actual Ed25519 (or RSA) public key
# for the deploy user before running this script.
# Generate a key pair locally with:
#   ssh-keygen -t ed25519 -C "deploy@bbanalyzer" -f ~/.ssh/bbanalyzer_deploy
# Then paste the contents of ~/.ssh/bbanalyzer_deploy.pub here.
# ---------------------------------------------------------------------------
DEPLOY_PUBLIC_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHJY8BtrSPEkCU2aoDnAz46f2RXovrbkhsn86e5mh7zP deploy@bbanalyzer"

DEPLOY_USER="deploy"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { echo "[INFO]  $*"; }
warn()  { echo "[WARN]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# Ensure we are running as root
if [[ "$(id -u)" -ne 0 ]]; then
    error "This script must be run as root (use: sudo bash $0)"
fi

# ---------------------------------------------------------------------------
# Step 1: Create the deploy user (idempotent — skip if already exists)
# ---------------------------------------------------------------------------
info "Step 1: Creating user '$DEPLOY_USER'..."
if id "$DEPLOY_USER" &>/dev/null; then
    info "  User '$DEPLOY_USER' already exists — skipping creation."
else
    adduser --disabled-password --gecos "" "$DEPLOY_USER"
    info "  User '$DEPLOY_USER' created."
fi

# ---------------------------------------------------------------------------
# Step 2: Grant sudo privileges (idempotent — usermod -aG is safe to repeat)
# ---------------------------------------------------------------------------
info "Step 2: Adding '$DEPLOY_USER' to the sudo group..."
usermod -aG sudo "$DEPLOY_USER"
info "  '$DEPLOY_USER' is now in the sudo group."

# ---------------------------------------------------------------------------
# Step 3: Set up SSH key-only access
# ---------------------------------------------------------------------------
info "Step 3: Configuring SSH authorized_keys for '$DEPLOY_USER'..."

DEPLOY_HOME="/home/$DEPLOY_USER"
SSH_DIR="$DEPLOY_HOME/.ssh"
AUTH_KEYS="$SSH_DIR/authorized_keys"

# Create .ssh directory if it doesn't exist
if [[ ! -d "$SSH_DIR" ]]; then
    mkdir -p "$SSH_DIR"
    info "  Created $SSH_DIR"
fi

# Add the public key if it isn't already present (idempotent)
if grep -qF "$DEPLOY_PUBLIC_KEY" "$AUTH_KEYS" 2>/dev/null; then
    info "  Public key already present in $AUTH_KEYS — skipping."
else
    echo "$DEPLOY_PUBLIC_KEY" >> "$AUTH_KEYS"
    info "  Public key appended to $AUTH_KEYS"
fi

# Enforce correct ownership and permissions
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$SSH_DIR"
chmod 700 "$SSH_DIR"
chmod 600 "$AUTH_KEYS"
info "  Permissions set: $SSH_DIR (700), $AUTH_KEYS (600)"

# ---------------------------------------------------------------------------
# Step 3b: Grant passwordless sudo for ALL commands (temporary — restricted
#          to just 'systemctl reload gunicorn' by 11-sudoers-deploy.sh later)
#          This MUST happen before disabling root SSH so remote provisioning
#          scripts can run sudo commands without a password prompt.
# ---------------------------------------------------------------------------
info "Step 3b: Granting '$DEPLOY_USER' full passwordless sudo (temporary)..."
echo "$DEPLOY_USER ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/deploy-temp
chmod 440 /etc/sudoers.d/deploy-temp
visudo -c -f /etc/sudoers.d/deploy-temp
info "  Passwordless sudo granted. Will be restricted to 'systemctl reload gunicorn' by 11-sudoers-deploy.sh"

# ---------------------------------------------------------------------------
# Step 4: Disable password authentication in sshd_config
# ---------------------------------------------------------------------------
info "Step 4: Disabling password authentication in /etc/ssh/sshd_config..."

SSHD_CONFIG="/etc/ssh/sshd_config"

# Back up sshd_config once (idempotent — skip if backup already exists)
if [[ ! -f "${SSHD_CONFIG}.bak" ]]; then
    cp "$SSHD_CONFIG" "${SSHD_CONFIG}.bak"
    info "  Backup saved to ${SSHD_CONFIG}.bak"
fi

# Disable password authentication — handle both commented and uncommented forms
sed -i \
    -e 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' \
    "$SSHD_CONFIG"

# Ensure the directive is present (add it if sed found nothing to replace)
if ! grep -q "^PasswordAuthentication no" "$SSHD_CONFIG"; then
    echo "PasswordAuthentication no" >> "$SSHD_CONFIG"
    info "  PasswordAuthentication no appended to $SSHD_CONFIG"
else
    info "  PasswordAuthentication no is set in $SSHD_CONFIG"
fi

# Also disable ChallengeResponseAuthentication (covers PAM-based password prompts)
sed -i \
    -e 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' \
    "$SSHD_CONFIG"

if ! grep -q "^ChallengeResponseAuthentication no" "$SSHD_CONFIG"; then
    echo "ChallengeResponseAuthentication no" >> "$SSHD_CONFIG"
    info "  ChallengeResponseAuthentication no appended to $SSHD_CONFIG"
else
    info "  ChallengeResponseAuthentication no is set in $SSHD_CONFIG"
fi

# ---------------------------------------------------------------------------
# Step 5: Disable root SSH login
# ---------------------------------------------------------------------------
info "Step 5: Disabling root SSH login (PermitRootLogin no)..."

sed -i \
    -e 's/^#\?PermitRootLogin.*/PermitRootLogin no/' \
    "$SSHD_CONFIG"

if ! grep -q "^PermitRootLogin no" "$SSHD_CONFIG"; then
    echo "PermitRootLogin no" >> "$SSHD_CONFIG"
    info "  PermitRootLogin no appended to $SSHD_CONFIG"
else
    info "  PermitRootLogin no is set in $SSHD_CONFIG"
fi

# ---------------------------------------------------------------------------
# Step 6: Validate sshd_config and restart sshd
# ---------------------------------------------------------------------------
info "Step 6: Validating sshd_config..."
if sshd -t; then
    info "  sshd_config is valid."
else
    error "  sshd_config validation FAILED. Restoring backup and aborting."
    cp "${SSHD_CONFIG}.bak" "$SSHD_CONFIG"
fi

info "Step 6: Restarting sshd..."
systemctl restart sshd
info "  sshd restarted successfully."

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Task 1.1 complete — deploy user configured"
echo "============================================================"
echo "  User:              $DEPLOY_USER"
echo "  Groups:            $(id -Gn $DEPLOY_USER)"
echo "  SSH dir:           $SSH_DIR (700)"
echo "  Authorized keys:   $AUTH_KEYS (600)"
echo "  PasswordAuth:      $(grep '^PasswordAuthentication' $SSHD_CONFIG)"
echo "  RootLogin:         $(grep '^PermitRootLogin' $SSHD_CONFIG)"
echo ""
echo "  NEXT STEP: Test SSH access before closing your root session:"
echo "    ssh -i ~/.ssh/bbanalyzer_deploy deploy@<VPS_IP>"
echo ""
echo "  WARNING: Do NOT close this root session until you have"
echo "  confirmed the deploy user can SSH in successfully."
echo "============================================================"
