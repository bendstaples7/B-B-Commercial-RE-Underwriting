#!/usr/bin/env bash
# =============================================================================
# 10-build-frontend.sh
# VPS Setup — Task 5.1: Build the React frontend as the deploy user.
#
# Requirements: 4.1
#
# Run ON THE VPS as the deploy user (NOT as root):
#   bash /home/deploy/app/scripts/vps-setup/10-build-frontend.sh
#
# Prerequisites:
#   - 03-install-packages.sh has been run (Node.js 20 is installed)
#   - 04-clone-repo.sh has been run (/home/deploy/app exists with the repo)
#
# What this script does:
#   1. Navigates to /home/deploy/app/frontend/
#   2. Runs `npm ci` to install exact dependencies from package-lock.json
#   3. Runs `npm run build` to produce the production build in frontend/dist/
#   4. Verifies frontend/dist/index.html exists
#   5. Reports the size of the dist directory
#
# This script is IDEMPOTENT — safe to run multiple times. Subsequent builds
# simply overwrite the dist/ directory with fresh output.
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
APP_DIR="/home/deploy/app"
FRONTEND_DIR="${APP_DIR}/frontend"
DIST_DIR="${FRONTEND_DIR}/dist"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ── Verify running as deploy user (not root) ──────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    die "Run this script as the deploy user, NOT as root.
  Usage: bash ${APP_DIR}/scripts/vps-setup/10-build-frontend.sh"
fi

# ── Verify frontend directory exists ─────────────────────────────────────────
if [[ ! -d "${FRONTEND_DIR}" ]]; then
    die "Frontend directory not found: ${FRONTEND_DIR}
  Run 04-clone-repo.sh first to clone the application repository."
fi

# ── Verify package.json exists ───────────────────────────────────────────────
if [[ ! -f "${FRONTEND_DIR}/package.json" ]]; then
    die "package.json not found in ${FRONTEND_DIR}
  The repository may not have cloned correctly. Run 04-clone-repo.sh again."
fi

# ── Verify package-lock.json exists (required for npm ci) ────────────────────
if [[ ! -f "${FRONTEND_DIR}/package-lock.json" ]]; then
    die "package-lock.json not found in ${FRONTEND_DIR}
  npm ci requires a lockfile. Ensure the lockfile is committed to the repository."
fi

echo ""
echo "============================================================"
echo "  Task 5.1 — Build React Frontend"
echo "  Started: $TIMESTAMP"
echo "============================================================"
echo "  Frontend dir: ${FRONTEND_DIR}"
echo "  Output dir:   ${DIST_DIR}"
echo "============================================================"
echo ""

# =============================================================================
# Step 1: Verify Node.js and npm are available
# =============================================================================
info "Step 1: Verifying Node.js and npm..."

if ! command -v node &>/dev/null; then
    die "node not found. Run 03-install-packages.sh first to install Node.js 20."
fi

if ! command -v npm &>/dev/null; then
    die "npm not found. Run 03-install-packages.sh first to install Node.js 20."
fi

NODE_VERSION=$(node --version)
NPM_VERSION=$(npm --version)
info "  ✓ Node.js: ${NODE_VERSION}"
info "  ✓ npm:     ${NPM_VERSION}"

# Warn if Node.js major version is not 20
NODE_MAJOR=$(echo "${NODE_VERSION}" | sed 's/v\([0-9]*\).*/\1/')
if [[ "${NODE_MAJOR}" -ne 20 ]]; then
    warn "  Expected Node.js 20.x but found ${NODE_VERSION}."
    warn "  The build may still succeed, but Node.js 20 is the tested version."
fi

# =============================================================================
# Step 2: Navigate to frontend directory
# =============================================================================
info "Step 2: Navigating to frontend directory..."
cd "${FRONTEND_DIR}"
info "  ✓ Working directory: $(pwd)"

# =============================================================================
# Step 3: Install exact dependencies with npm ci (Requirement 4.1)
# =============================================================================
info "Step 3: Running 'npm ci' to install exact dependencies..."
info "  This installs from package-lock.json — no version drift."
echo ""

npm ci

echo ""
info "  ✓ 'npm ci' completed successfully."

# =============================================================================
# Step 4: Build the production bundle (Requirement 4.1)
# =============================================================================
info "Step 4: Running 'npm run build' to produce the production build..."
info "  Build command: tsc && vite build"
info "  Output:        ${DIST_DIR}"
echo ""

npm run build

echo ""
info "  ✓ 'npm run build' completed successfully."

# =============================================================================
# Step 5: Verify dist/index.html exists (Requirement 4.1)
# =============================================================================
info "Step 5: Verifying build output..."

if [[ ! -f "${DIST_DIR}/index.html" ]]; then
    die "Build verification FAILED: ${DIST_DIR}/index.html does not exist.
  The build command exited successfully but did not produce index.html.
  Check the Vite configuration in ${FRONTEND_DIR}/vite.config.ts."
fi

info "  ✓ ${DIST_DIR}/index.html exists. Requirement 4.1 satisfied."

# Verify the assets directory was created (Vite hashed assets)
if [[ -d "${DIST_DIR}/assets" ]]; then
    ASSET_COUNT=$(find "${DIST_DIR}/assets" -type f | wc -l)
    info "  ✓ ${DIST_DIR}/assets/ exists with ${ASSET_COUNT} hashed asset file(s)."
else
    warn "  ${DIST_DIR}/assets/ directory not found."
    warn "  This is unexpected for a Vite build — check the build output above."
fi

# =============================================================================
# Step 6: Report the size of the dist directory
# =============================================================================
info "Step 6: Reporting dist directory size..."
echo ""
echo "  Dist directory contents:"
echo "  ─────────────────────────────────────────────────────────────────"
ls -lh "${DIST_DIR}/"
echo ""

if [[ -d "${DIST_DIR}/assets" ]]; then
    echo "  Assets:"
    echo "  ─────────────────────────────────────────────────────────────────"
    ls -lh "${DIST_DIR}/assets/" | head -20
    ASSET_TOTAL=$(find "${DIST_DIR}/assets" -type f | wc -l)
    if [[ "${ASSET_TOTAL}" -gt 20 ]]; then
        echo "  ... (${ASSET_TOTAL} total asset files, showing first 20)"
    fi
    echo ""
fi

DIST_SIZE=$(du -sh "${DIST_DIR}" | cut -f1)
info "  Total dist size: ${DIST_SIZE}"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "============================================================"
echo "  Task 5.1 complete — React frontend built successfully"
echo "============================================================"
echo "  Build output:  ${DIST_DIR}"
echo "  Entry point:   ${DIST_DIR}/index.html  ✓"
echo "  Total size:    ${DIST_SIZE}"
echo ""
echo "  NEXT STEPS:"
echo "    5.2  Write the Nginx site configuration and enable it"
echo "         sudo bash ${APP_DIR}/scripts/vps-setup/11-nginx-config.sh"
echo ""
echo "  The dist/ directory is now ready to be served by Nginx."
echo "  Nginx will serve static files from:"
echo "    ${DIST_DIR}"
echo "============================================================"
