#!/usr/bin/env bash
# =============================================================================
# 03-install-packages.sh
# Install Python 3.11, Node.js 20, PostgreSQL 15, Nginx, and Certbot on
# Ubuntu 22.04 LTS (Hetzner CX22 VPS).
#
# Usage:
#   sudo bash 03-install-packages.sh
#
# Idempotent: safe to run multiple times. Repository additions and package
# installations are guarded so re-running does not cause errors.
#
# Requirements: 1.6
# =============================================================================

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Require root ─────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    die "This script must be run as root (use: sudo bash $0)"
fi

# ── Verify Ubuntu 22.04 ───────────────────────────────────────────────────────
if [[ -f /etc/os-release ]]; then
    # shellcheck source=/dev/null
    source /etc/os-release
    if [[ "$ID" != "ubuntu" || "$VERSION_ID" != "22.04" ]]; then
        warn "Expected Ubuntu 22.04 LTS, detected: $PRETTY_NAME"
        warn "Proceeding anyway — some steps may behave differently."
    else
        info "OS check passed: $PRETTY_NAME"
    fi
fi

# ── Update apt package index ──────────────────────────────────────────────────
info "Waiting for apt locks to be released (Ubuntu auto-update may be running)..."
while fuser /var/lib/apt/lists/lock /var/lib/dpkg/lock /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
    echo "  apt is locked — waiting 5 seconds..."
    sleep 5
done
info "apt lock is free. Updating package index..."
apt-get update -qq

# ── Install prerequisite tools ────────────────────────────────────────────────
info "Installing prerequisite tools (curl, gnupg, ca-certificates, lsb-release)..."
apt-get install -y -qq \
    curl \
    gnupg \
    ca-certificates \
    lsb-release \
    apt-transport-https \
    software-properties-common

# =============================================================================
# 1. NodeSource repository for Node.js 20
# =============================================================================
NODESOURCE_LIST="/etc/apt/sources.list.d/nodesource.list"

if [[ -f "$NODESOURCE_LIST" ]] && grep -q "node_20" "$NODESOURCE_LIST" 2>/dev/null; then
    info "NodeSource Node.js 20 repository already configured — skipping."
else
    info "Adding NodeSource repository for Node.js 20..."
    # NOTE: Piping a remote script into bash as root carries supply-chain risk.
    # This is the official NodeSource installation method documented at
    # https://github.com/nodesource/distributions — the URL is HTTPS and the
    # script only adds the apt repository (it does not install packages).
    # Verify the script contents manually before running in sensitive environments.
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    info "NodeSource repository added."
fi

# =============================================================================
# 2. PostgreSQL apt repository for PostgreSQL 15
# =============================================================================
PGDG_LIST="/etc/apt/sources.list.d/pgdg.list"
PGDG_KEY="/usr/share/keyrings/postgresql-archive-keyring.gpg"

if [[ -f "$PGDG_LIST" ]]; then
    info "PostgreSQL PGDG repository already configured — skipping."
else
    info "Adding PostgreSQL PGDG apt repository..."
    # Import the PostgreSQL signing key
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        | gpg --dearmor -o "$PGDG_KEY"
    # Add the repository
    echo "deb [signed-by=${PGDG_KEY}] https://apt.postgresql.org/pub/repos/apt \
$(lsb_release -cs)-pgdg main" > "$PGDG_LIST"
    info "PostgreSQL PGDG repository added."
fi

# Refresh index after adding new repos
apt-get update -qq

# =============================================================================
# 3. Install all required packages
# =============================================================================
info "Installing all required packages..."

PACKAGES=(
    python3.11
    python3.11-venv
    python3.11-dev
    python3-pip
    nodejs                  # 20.x from NodeSource
    postgresql-15
    postgresql-client-15
    nginx
    certbot
    python3-certbot-nginx
)

apt-get install -y -qq "${PACKAGES[@]}"

info "All packages installed."

# =============================================================================
# 4. Install pip packages needed globally (gunicorn, etc.)
# =============================================================================
info "Installing global pip packages (gunicorn)..."

# Use python3.11 explicitly to ensure we install for the correct interpreter
python3.11 -m pip install --upgrade pip --quiet
python3.11 -m pip install gunicorn --quiet

info "Global pip packages installed."

# =============================================================================
# 5. Verify each package version
# =============================================================================
info "============================================================"
info "Verifying installed package versions..."
info "============================================================"

VERIFICATION_FAILED=0

# ── Python 3.11 ───────────────────────────────────────────────────────────────
PYTHON_VERSION=$(python3.11 --version 2>&1 || true)
if echo "$PYTHON_VERSION" | grep -q "Python 3\.11"; then
    info "✓ Python:     $PYTHON_VERSION"
else
    error "✗ Python 3.11 not found or wrong version: $PYTHON_VERSION"
    VERIFICATION_FAILED=1
fi

# ── pip ───────────────────────────────────────────────────────────────────────
PIP_VERSION=$(python3.11 -m pip --version 2>&1 || true)
if echo "$PIP_VERSION" | grep -q "pip"; then
    info "✓ pip:        $PIP_VERSION"
else
    error "✗ pip not found: $PIP_VERSION"
    VERIFICATION_FAILED=1
fi

# ── Node.js 20 ────────────────────────────────────────────────────────────────
NODE_VERSION=$(node --version 2>&1 || true)
if echo "$NODE_VERSION" | grep -qE "^v20\."; then
    info "✓ Node.js:    $NODE_VERSION"
else
    error "✗ Node.js 20 not found or wrong version: $NODE_VERSION"
    VERIFICATION_FAILED=1
fi

# ── npm ───────────────────────────────────────────────────────────────────────
NPM_VERSION=$(npm --version 2>&1 || true)
if echo "$NPM_VERSION" | grep -qE "^[0-9]"; then
    info "✓ npm:        v$NPM_VERSION"
else
    error "✗ npm not found: $NPM_VERSION"
    VERIFICATION_FAILED=1
fi

# ── PostgreSQL 15 ─────────────────────────────────────────────────────────────
PG_VERSION=$(psql --version 2>&1 || true)
if echo "$PG_VERSION" | grep -q "15\."; then
    info "✓ PostgreSQL: $PG_VERSION"
else
    error "✗ PostgreSQL 15 not found or wrong version: $PG_VERSION"
    VERIFICATION_FAILED=1
fi

# Verify the PostgreSQL 15 service is present (may not be started yet)
if systemctl list-unit-files postgresql@15-main.service &>/dev/null || \
   systemctl list-unit-files postgresql.service &>/dev/null; then
    info "✓ PostgreSQL service unit is registered."
else
    warn "  PostgreSQL service unit not found — may need 'pg_lsclusters' check."
fi

# ── Nginx ─────────────────────────────────────────────────────────────────────
NGINX_VERSION=$(nginx -v 2>&1 || true)
if echo "$NGINX_VERSION" | grep -q "nginx/"; then
    info "✓ Nginx:      $NGINX_VERSION"
else
    error "✗ Nginx not found: $NGINX_VERSION"
    VERIFICATION_FAILED=1
fi

# ── Certbot ───────────────────────────────────────────────────────────────────
CERTBOT_VERSION=$(certbot --version 2>&1 || true)
if echo "$CERTBOT_VERSION" | grep -q "certbot"; then
    info "✓ Certbot:    $CERTBOT_VERSION"
else
    error "✗ Certbot not found: $CERTBOT_VERSION"
    VERIFICATION_FAILED=1
fi

# ── python3-certbot-nginx plugin ─────────────────────────────────────────────
if python3 -c "import certbot_nginx" 2>/dev/null; then
    info "✓ certbot-nginx plugin: installed"
else
    # Fallback: check via dpkg
    if dpkg -l python3-certbot-nginx 2>/dev/null | grep -q "^ii"; then
        info "✓ certbot-nginx plugin: installed (dpkg)"
    else
        error "✗ python3-certbot-nginx plugin not found"
        VERIFICATION_FAILED=1
    fi
fi

# ── Gunicorn ─────────────────────────────────────────────────────────────────
GUNICORN_VERSION=$(python3.11 -m gunicorn --version 2>&1 || true)
if echo "$GUNICORN_VERSION" | grep -q "gunicorn"; then
    info "✓ Gunicorn:   $GUNICORN_VERSION"
else
    error "✗ Gunicorn not found: $GUNICORN_VERSION"
    VERIFICATION_FAILED=1
fi

# =============================================================================
# 6. Final result
# =============================================================================
info "============================================================"
if [[ $VERIFICATION_FAILED -eq 0 ]]; then
    info "All packages verified successfully."
    info "Provisioning step 03 (install packages) COMPLETE."
else
    die "One or more package verifications FAILED. Review errors above."
fi
