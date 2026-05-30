#!/usr/bin/env bash
# =============================================================================
# 11-nginx-config.sh
# VPS Setup — Task 5.2: Write the Nginx site configuration and enable it.
#
# Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 8.4
#
# Run ON THE VPS as root:
#   sudo bash /home/deploy/app/scripts/vps-setup/11-nginx-config.sh
#
# Or pass the DuckDNS subdomain as an argument or environment variable:
#   sudo VPS_SUBDOMAIN=bbanalyzer bash /home/deploy/app/scripts/vps-setup/11-nginx-config.sh
#   sudo bash /home/deploy/app/scripts/vps-setup/11-nginx-config.sh bbanalyzer
#
# Prerequisites:
#   - 03-install-packages.sh has been run (Nginx is installed)
#   - 10-build-frontend.sh has been run (frontend/dist/ exists)
#
# What this script does:
#   1. Writes /etc/nginx/sites-available/real-estate with the full production
#      config (HTTP→HTTPS redirect + HTTPS block with TLS stubs, proxy timeouts,
#      /api/ proxy, /assets/ long-lived cache, / SPA fallback)
#   2. Creates symlink from sites-available to sites-enabled
#   3. Removes the default Nginx site symlink
#   4. Checks whether Let's Encrypt cert files exist:
#      - If YES: runs `nginx -t` to validate and reloads Nginx
#      - If NO:  skips validation (TLS stubs reference non-existent cert files)
#               and prints a clear message to run Certbot next (task 6.2)
#
# IMPORTANT — TLS stubs:
#   The HTTPS server block references cert files under /etc/letsencrypt/live/.
#   These files do NOT exist until Certbot runs (task 6.2). Therefore:
#   - `nginx -t` will FAIL if run before Certbot.
#   - This script detects that condition and skips validation gracefully.
#   - After running 13-certbot.sh (task 6.2), re-run this script OR manually
#     run: sudo nginx -t && sudo systemctl reload nginx
#
# This script is IDEMPOTENT — safe to run multiple times.
# =============================================================================

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()   { error "$*"; exit 1; }
step()  { echo -e "${CYAN}[STEP]${NC}  $*"; }

# ── Verify running as root ────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    die "This script must be run as root.
  Usage: sudo bash /home/deploy/app/scripts/vps-setup/11-nginx-config.sh [subdomain]"
fi

# ── Resolve subdomain ─────────────────────────────────────────────────────────
# Priority: CLI argument > VPS_SUBDOMAIN env var > prompt
SUBDOMAIN="${1:-${VPS_SUBDOMAIN:-}}"

if [[ -z "${SUBDOMAIN}" ]]; then
    echo ""
    echo -n "  Enter your DuckDNS subdomain (e.g. bbanalyzer): "
    read -r SUBDOMAIN
fi

if [[ -z "${SUBDOMAIN}" ]]; then
    die "No subdomain provided. Pass it as an argument or set VPS_SUBDOMAIN."
fi

# Strip .duckdns.org if the user accidentally included it
SUBDOMAIN="${SUBDOMAIN%.duckdns.org}"

# Validate subdomain format — only alphanumeric characters and hyphens
if [[ ! "$SUBDOMAIN" =~ ^[a-zA-Z0-9-]+$ ]]; then
    die "Invalid subdomain format: '${SUBDOMAIN}'. Use only letters, numbers, and hyphens."
fi

DOMAIN="${SUBDOMAIN}.duckdns.org"

# ── Configuration ─────────────────────────────────────────────────────────────
APP_DIR="/home/deploy/app"
NGINX_AVAILABLE="/etc/nginx/sites-available/real-estate"
NGINX_ENABLED="/etc/nginx/sites-enabled/real-estate"
NGINX_DEFAULT="/etc/nginx/sites-enabled/default"
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
CERT_FILE="${CERT_DIR}/fullchain.pem"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo ""
echo "============================================================"
echo "  Task 5.2 — Write Nginx Site Configuration"
echo "  Started: $TIMESTAMP"
echo "============================================================"
echo "  Domain:          ${DOMAIN}"
echo "  Config file:     ${NGINX_AVAILABLE}"
echo "  Symlink:         ${NGINX_ENABLED}"
echo "  Frontend dist:   ${APP_DIR}/frontend/dist"
echo "  Cert dir:        ${CERT_DIR}"
echo "============================================================"
echo ""

# ── Verify Nginx is installed ─────────────────────────────────────────────────
if ! command -v nginx &>/dev/null; then
    die "Nginx is not installed. Run 03-install-packages.sh first."
fi

NGINX_VERSION=$(nginx -v 2>&1 | head -1)
info "  ✓ Nginx found: ${NGINX_VERSION}"

# ── Verify sites-available directory exists ───────────────────────────────────
if [[ ! -d "/etc/nginx/sites-available" ]]; then
    die "/etc/nginx/sites-available does not exist. Is this a Debian/Ubuntu Nginx install?"
fi

if [[ ! -d "/etc/nginx/sites-enabled" ]]; then
    die "/etc/nginx/sites-enabled does not exist. Is this a Debian/Ubuntu Nginx install?"
fi

# =============================================================================
# Step 1: Write /etc/nginx/sites-available/real-estate
# =============================================================================
step "Step 1: Writing Nginx site configuration to ${NGINX_AVAILABLE}..."

# Back up existing config if present
if [[ -f "${NGINX_AVAILABLE}" ]]; then
    BACKUP="${NGINX_AVAILABLE}.bak.$(date +%Y%m%d%H%M%S)"
    cp "${NGINX_AVAILABLE}" "${BACKUP}"
    warn "  Existing config backed up to: ${BACKUP}"
fi

cat > "${NGINX_AVAILABLE}" << NGINX_CONF
# /etc/nginx/sites-available/real-estate
# Generated by 11-nginx-config.sh on ${TIMESTAMP}
# Domain: ${DOMAIN}
#
# Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 8.4

# ── HTTP → HTTPS redirect (Requirement 5.5) ───────────────────────────────────
server {
    listen 80;
    server_name ${DOMAIN};
    return 301 https://\$host\$request_uri;
}

# ── HTTPS block ───────────────────────────────────────────────────────────────
server {
    listen 443 ssl;
    server_name ${DOMAIN};

    # TLS — managed by Certbot (Requirement 5.3, 5.6)
    # NOTE: These files are created by Certbot (task 6.2 / 13-certbot.sh).
    #       nginx -t will fail until Certbot has run.
    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    include             /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam         /etc/letsencrypt/ssl-dhparams.pem;

    # Logging (Requirement 10.4)
    access_log /var/log/nginx/real-estate-access.log;
    error_log  /var/log/nginx/real-estate-error.log;

    # Proxy timeouts — match Gunicorn --timeout 120 (Requirement 8.4)
    proxy_read_timeout    120s;
    proxy_connect_timeout  10s;
    proxy_send_timeout    120s;

    # API — proxy to Gunicorn (Requirement 4.4)
    location /api/ {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
    }

    # Vite-hashed assets — long-lived cache (Requirement 4.5)
    # Vite produces content-hashed filenames (e.g. index-BxYz1234.js),
    # so max-age=31536000 (1 year) + immutable is safe.
    location /assets/ {
        root       /home/deploy/app/frontend/dist;
        add_header Cache-Control "max-age=31536000, immutable";
        try_files  \$uri =404;
    }

    # React SPA — no-cache for index.html, SPA fallback (Requirements 4.2, 4.3, 4.5)
    location / {
        root       /home/deploy/app/frontend/dist;
        add_header Cache-Control "no-cache";
        try_files  \$uri \$uri/ /index.html;
    }
}
NGINX_CONF

info "  ✓ Nginx config written to ${NGINX_AVAILABLE}"

# =============================================================================
# Step 2: Create symlink in sites-enabled (Requirement 4.6)
# =============================================================================
step "Step 2: Enabling site (creating symlink in sites-enabled)..."

if [[ -L "${NGINX_ENABLED}" ]]; then
    EXISTING_TARGET=$(readlink -f "${NGINX_ENABLED}" 2>/dev/null || echo "broken")
    if [[ "${EXISTING_TARGET}" == "$(readlink -f "${NGINX_AVAILABLE}")" ]]; then
        info "  ✓ Symlink already exists and points to the correct target — skipping."
    else
        warn "  Existing symlink points to: ${EXISTING_TARGET}"
        warn "  Removing and recreating to point to: ${NGINX_AVAILABLE}"
        rm "${NGINX_ENABLED}"
        ln -s "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
        info "  ✓ Symlink recreated: ${NGINX_ENABLED} -> ${NGINX_AVAILABLE}"
    fi
elif [[ -e "${NGINX_ENABLED}" ]]; then
    die "${NGINX_ENABLED} exists but is not a symlink. Remove it manually and re-run."
else
    ln -s "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
    info "  ✓ Symlink created: ${NGINX_ENABLED} -> ${NGINX_AVAILABLE}"
fi

# =============================================================================
# Step 3: Disable the default Nginx site (Requirement 4.6)
# =============================================================================
step "Step 3: Disabling the default Nginx site..."

if [[ -L "${NGINX_DEFAULT}" ]]; then
    rm "${NGINX_DEFAULT}"
    info "  ✓ Default site symlink removed: ${NGINX_DEFAULT}"
elif [[ -e "${NGINX_DEFAULT}" ]]; then
    warn "  ${NGINX_DEFAULT} exists but is not a symlink — leaving it in place."
    warn "  You may want to remove it manually: sudo rm ${NGINX_DEFAULT}"
else
    info "  ✓ Default site already disabled (${NGINX_DEFAULT} does not exist)."
fi

# =============================================================================
# Step 4: Validate config and reload Nginx (Requirement 4.7)
# =============================================================================
step "Step 4: Validating Nginx configuration..."

if [[ -f "${CERT_FILE}" ]]; then
    # Cert files exist — full validation is possible
    info "  ✓ TLS cert found at ${CERT_FILE}"
    info "  Running nginx -t..."
    echo ""

    if nginx -t; then
        echo ""
        info "  ✓ nginx -t passed — configuration is valid."

        step "Step 5: Reloading Nginx..."
        systemctl reload nginx
        info "  ✓ Nginx reloaded successfully."

        # Verify Nginx is active
        if systemctl is-active --quiet nginx; then
            info "  ✓ Nginx is active and serving traffic."
        else
            die "Nginx is not active after reload. Check: journalctl -u nginx -n 50"
        fi
    else
        echo ""
        die "nginx -t FAILED. Review the errors above and fix the configuration."
    fi
else
    # Cert files don't exist yet — nginx -t would fail on the ssl_certificate lines
    echo ""
    warn "  TLS certificate NOT found at: ${CERT_FILE}"
    warn "  This is expected if Certbot has not been run yet."
    warn ""
    warn "  nginx -t will FAIL until the cert files exist, so validation is"
    warn "  being SKIPPED for now. The config has been written correctly."
    warn ""
    warn "  ┌─────────────────────────────────────────────────────────────┐"
    warn "  │  NEXT STEP: Run Certbot to obtain the TLS certificate       │"
    warn "  │                                                             │"
    warn "  │  Task 6.2 — 13-certbot.sh                                  │"
    warn "  │  sudo bash ${APP_DIR}/scripts/vps-setup/13-certbot.sh      │"
    warn "  │                                                             │"
    warn "  │  After Certbot runs, validate and reload Nginx manually:   │"
    warn "  │    sudo nginx -t && sudo systemctl reload nginx             │"
    warn "  └─────────────────────────────────────────────────────────────┘"
    echo ""

    # Attempt a partial validation: test Nginx config syntax ignoring SSL errors
    # by temporarily checking if Nginx itself is running (not a config test)
    if systemctl is-active --quiet nginx; then
        info "  ✓ Nginx service is currently active (serving pre-existing config)."
        info "  The new config will take effect after Certbot runs and you reload."
    else
        warn "  Nginx service is not currently active."
        warn "  Start it after Certbot runs: sudo systemctl start nginx"
    fi
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "============================================================"
echo "  Task 5.2 complete — Nginx site configuration written"
echo "============================================================"
echo "  Config file:  ${NGINX_AVAILABLE}  ✓"
echo "  Symlink:      ${NGINX_ENABLED}  ✓"
echo "  Default site: disabled  ✓"
echo ""

if [[ -f "${CERT_FILE}" ]]; then
    echo "  TLS:          Active (cert found)  ✓"
    echo "  nginx -t:     Passed  ✓"
    echo "  Nginx:        Reloaded  ✓"
    echo ""
    echo "  NEXT STEPS:"
    echo "    7.   Checkpoint — verify the application is live"
    echo "         curl -f https://${DOMAIN}/api/health"
else
    echo "  TLS:          Pending (Certbot not yet run)"
    echo "  nginx -t:     Skipped (cert files missing)"
    echo ""
    echo "  NEXT STEPS:"
    echo "    6.1  Set up DuckDNS subdomain and cron update script"
    echo "         bash ${APP_DIR}/scripts/vps-setup/12-duckdns.sh"
    echo ""
    echo "    6.2  Obtain Let's Encrypt certificate via Certbot"
    echo "         sudo bash ${APP_DIR}/scripts/vps-setup/13-certbot.sh"
    echo ""
    echo "    Then validate and reload Nginx:"
    echo "         sudo nginx -t && sudo systemctl reload nginx"
fi
echo "============================================================"
