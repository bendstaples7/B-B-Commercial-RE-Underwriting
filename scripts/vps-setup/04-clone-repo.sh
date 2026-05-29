#!/usr/bin/env bash
# =============================================================================
# 04-clone-repo.sh
# Clone the application repository to /home/deploy/app as the deploy user,
# or pull the latest changes if the directory already exists.
#
# Usage:
#   sudo bash 04-clone-repo.sh [<git-repo-url>]
#
# Arguments:
#   git-repo-url  (optional) Override the default REPO_URL variable below.
#
# Idempotent: if /home/deploy/app already exists and is a git repo, runs
#             `git pull` instead of re-cloning.
#
# Requirements: 1.7
# =============================================================================

set -euo pipefail

# =============================================================================
# Configuration — edit REPO_URL before running if needed
# =============================================================================
REPO_URL="${1:-https://github.com/bendstaples7/B-B-Commercial-RE-Underwriting.git}"
DEPLOY_USER="deploy"
APP_DIR="/home/deploy/app"

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()   { error "$*"; exit 1; }

# ── Require root ─────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    die "This script must be run as root (use: sudo bash $0)"
fi

# ── Verify the deploy user exists ────────────────────────────────────────────
if ! id "$DEPLOY_USER" &>/dev/null; then
    die "User '$DEPLOY_USER' does not exist. Run 01-create-deploy-user.sh first."
fi

info "Repository URL : $REPO_URL"
info "Target directory: $APP_DIR"
info "Owner           : $DEPLOY_USER:$DEPLOY_USER"

# =============================================================================
# 1. Clone or pull
# =============================================================================
if [[ -d "$APP_DIR/.git" ]]; then
    # Directory already exists and is a git repo — pull instead of re-cloning
    info "Directory $APP_DIR already exists and is a git repository."
    info "Running 'git pull origin main' as $DEPLOY_USER..."
    sudo -u "$DEPLOY_USER" git -C "$APP_DIR" pull origin main
    info "git pull complete."
else
    if [[ -d "$APP_DIR" ]]; then
        # Directory exists but is NOT a git repo — abort to avoid data loss
        die "$APP_DIR exists but is not a git repository. Remove it manually and re-run."
    fi

    # Fresh clone
    info "Cloning repository as $DEPLOY_USER..."
    sudo -u "$DEPLOY_USER" git clone "$REPO_URL" "$APP_DIR"
    info "Clone complete."
fi

# =============================================================================
# 2. Ensure deploy owns everything under /home/deploy/app
# =============================================================================
info "Setting ownership of $APP_DIR to $DEPLOY_USER:$DEPLOY_USER..."
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"
info "Ownership set."

# =============================================================================
# 3. Verify ownership
# =============================================================================
info "============================================================"
info "Verifying ownership of $APP_DIR..."
info "============================================================"

ls -la "$APP_DIR"

# Check that every file/directory under APP_DIR is owned by deploy.
# We sample the top-level entries; a full recursive check would be slow on
# large repos, so we verify the root and a few key subdirectories.
WRONG_OWNER=$(find "$APP_DIR" -maxdepth 3 \
    ! -user "$DEPLOY_USER" \
    ! -group "$DEPLOY_USER" \
    -print 2>/dev/null | head -5)

if [[ -n "$WRONG_OWNER" ]]; then
    warn "The following paths are NOT owned by $DEPLOY_USER (showing up to 5):"
    echo "$WRONG_OWNER"
    die "Ownership verification FAILED. Review the paths above."
fi

info "============================================================"
info "✓ All files under $APP_DIR are owned by $DEPLOY_USER:$DEPLOY_USER"
info "Provisioning step 04 (clone repo) COMPLETE."
info "============================================================"
