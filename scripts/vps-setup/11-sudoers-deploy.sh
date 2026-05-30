#!/usr/bin/env bash
# =============================================================================
# 11-sudoers-deploy.sh
# VPS Setup — Task 4.2: Grant `deploy` passwordless sudo for
#             `systemctl reload gunicorn`.
#
# Requirements: 6.3, 8.1
#
# Run ON THE VPS as root:
#   sudo bash /home/deploy/app/scripts/vps-setup/11-sudoers-deploy.sh
#
# Prerequisites:
#   - 01-create-deploy-user.sh has been run (deploy user exists)
#   - 09-gunicorn-service.sh has been run (gunicorn.service exists)
#
# What this script does:
#   1. Writes /etc/sudoers.d/deploy with the single passwordless rule
#   2. Sets permissions to 440 (required by sudo for sudoers.d files)
#   3. Validates the file with `visudo -c -f` (syntax check)
#   4. Verifies the rule works by running the command as the deploy user
#
# This script is IDEMPOTENT — safe to run multiple times.
#   - Writing the sudoers file overwrites any previous version
#   - visudo -c is a read-only syntax check (no side effects)
#   - The verification step uses `sudo -u deploy sudo -n` (non-interactive)
# =============================================================================

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()   { error "$*"; exit 1; }

# ── Configuration ─────────────────────────────────────────────────────────────
SUDOERS_FILE="/etc/sudoers.d/deploy"
DEPLOY_USER="deploy"
# Exact rule required by the spec (Requirements 6.3, 8.1)
SUDOERS_RULE="deploy ALL=(ALL) NOPASSWD: /bin/systemctl reload gunicorn"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ── Verify running as root ────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    die "This script must be run as root.
  Usage: sudo bash /home/deploy/app/scripts/vps-setup/11-sudoers-deploy.sh"
fi

# ── Verify deploy user exists ─────────────────────────────────────────────────
if ! id "${DEPLOY_USER}" &>/dev/null; then
    die "User '${DEPLOY_USER}' does not exist.
  Run 01-create-deploy-user.sh first."
fi

# ── Verify visudo is available ────────────────────────────────────────────────
if ! command -v visudo &>/dev/null; then
    die "'visudo' not found. Install sudo: apt install -y sudo"
fi

echo ""
echo "============================================================"
echo "  Task 4.2 — Passwordless sudo for deploy user"
echo "  Started: $TIMESTAMP"
echo "============================================================"
echo "  Sudoers file: ${SUDOERS_FILE}"
echo "  Rule:         ${SUDOERS_RULE}"
echo "============================================================"
echo ""

# =============================================================================
# Step 1: Write /etc/sudoers.d/deploy
# =============================================================================
info "Step 1: Writing ${SUDOERS_FILE}..."

# Write the exact rule specified in the design document.
# The file must NOT end with a trailing newline that could confuse sudo parsers,
# but a single trailing newline is fine and conventional.
printf '%s\n' "${SUDOERS_RULE}" > "${SUDOERS_FILE}"

if [[ ! -f "${SUDOERS_FILE}" ]]; then
    die "Failed to write ${SUDOERS_FILE}."
fi

info "  ✓ ${SUDOERS_FILE} written."

# =============================================================================
# Step 2: Set permissions to 440
# =============================================================================
# sudo requires sudoers.d files to be owned by root and not world-writable.
# Mode 440 (r--r-----) is the standard for sudoers.d files.
# Mode 640 or 600 also work, but 440 is the most restrictive safe value.
info "Step 2: Setting permissions to 440 (root:root)..."

chown root:root "${SUDOERS_FILE}"
chmod 440 "${SUDOERS_FILE}"

ACTUAL_PERMS=$(stat -c "%a %U:%G" "${SUDOERS_FILE}")
info "  ✓ Permissions set: ${ACTUAL_PERMS} (expected: 440 root:root)"

# =============================================================================
# Step 3: Validate the sudoers file with visudo -c
# =============================================================================
info "Step 3: Validating ${SUDOERS_FILE} with 'visudo -c -f'..."

if visudo -c -f "${SUDOERS_FILE}"; then
    info "  ✓ visudo syntax check passed — file is valid."
else
    # Remove the invalid file so sudo is not broken
    rm -f "${SUDOERS_FILE}"
    die "visudo syntax check FAILED. The invalid file has been removed.
  This should not happen with the hardcoded rule — check for filesystem issues."
fi

# =============================================================================
# Step 4: Verify the rule works as the deploy user
# =============================================================================
# We use `sudo -u deploy sudo -n -l` to list what the deploy user can run
# without a password (-n = non-interactive, fails if a password would be needed).
# Then we check that the specific command appears in the output.
#
# We do NOT actually run `systemctl reload gunicorn` here because:
#   a) gunicorn may not be running yet at this point in the setup sequence
#   b) a reload of a non-running service would fail and obscure the real result
#
# The functional test (actually reloading gunicorn) is performed by the
# GitHub Actions deploy workflow once the full stack is running.
info "Step 4: Verifying the sudo rule is effective for the deploy user..."

# List the deploy user's sudo privileges (non-interactive, no password prompt)
SUDO_LIST=$(sudo -u "${DEPLOY_USER}" sudo -n -l 2>&1 || true)

if echo "${SUDO_LIST}" | grep -qF "/bin/systemctl reload gunicorn"; then
    info "  ✓ Rule confirmed: deploy can run 'sudo /bin/systemctl reload gunicorn' without a password."
else
    error "  Could not confirm the rule via 'sudo -n -l'."
    error "  sudo -l output:"
    echo "${SUDO_LIST}" | sed 's/^/    /'
    die "Sudo rule verification failed. The rule in ${SUDOERS_FILE} was not recognised by sudo.
  Check for syntax issues or conflicting rules in /etc/sudoers or /etc/sudoers.d/."
fi

# =============================================================================
# Step 5: Show the final file contents for audit purposes
# =============================================================================
info "Step 5: Final contents of ${SUDOERS_FILE}:"
echo ""
echo "  ── ${SUDOERS_FILE} ──────────────────────────────────────────────────"
cat "${SUDOERS_FILE}" | sed 's/^/  /'
echo "  ─────────────────────────────────────────────────────────────────────"
echo ""

# =============================================================================
# Summary
# =============================================================================
echo "============================================================"
echo "  Task 4.2 complete — Passwordless sudo configured"
echo "============================================================"
echo "  File:        ${SUDOERS_FILE}"
echo "  Permissions: $(stat -c '%a %U:%G' "${SUDOERS_FILE}")"
echo "  Rule:        ${SUDOERS_RULE}"
echo ""
echo "  The deploy user can now run:"
echo "    sudo systemctl reload gunicorn"
echo "  without a password prompt — enabling zero-downtime deploys"
echo "  from GitHub Actions (Req 6.3, 8.1)."
echo ""
echo "  NEXT STEPS:"
echo "    5.2  Write the Nginx site configuration"
echo "         sudo bash /home/deploy/app/scripts/vps-setup/11-nginx-config.sh"
echo "============================================================"
