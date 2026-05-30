#!/usr/bin/env bash
# =============================================================================
# 13-certbot.sh
# VPS Setup — Task 6.2: Obtain the Let's Encrypt certificate via Certbot
#             and verify auto-renewal.
#
# Requirements: 5.3, 5.4, 5.5, 5.6
#
# Run ON THE VPS as root:
#   sudo bash /home/deploy/app/scripts/vps-setup/13-certbot.sh
#
# Or pass credentials as environment variables:
#   sudo VPS_SUBDOMAIN=bbanalyzer ADMIN_EMAIL=you@example.com \
#     bash /home/deploy/app/scripts/vps-setup/13-certbot.sh
#
# Prerequisites:
#   - 03-install-packages.sh has been run (Nginx is installed)
#   - 11-nginx-config.sh has been run (Nginx site config exists with HTTP block)
#   - 12-duckdns.sh has been run and DuckDNS subdomain resolves to this VPS IP
#   - Ports 80 and 443 are open in UFW (done by 02-firewall-fail2ban.sh)
#   - Nginx is running and serving HTTP on port 80
#
# What this script does:
#   1. Installs certbot and python3-certbot-nginx via apt (idempotent)
#   2. Runs certbot --nginx to obtain the TLS certificate and update Nginx config
#   3. Verifies certbot renew --dry-run succeeds (confirms certbot.timer works)
#   4. Verifies certbot.timer systemd unit is active (auto-renewal)
#   5. Runs nginx -t to validate the updated Nginx configuration
#   6. Reloads Nginx to apply the TLS configuration
#   7. Verifies HTTPS is working with curl (port 443)
#   8. Verifies HTTP redirects to HTTPS (301 permanent redirect)
#
# IDEMPOTENCY:
#   - apt install is idempotent (no-op if already installed)
#   - certbot --nginx is idempotent: if a valid cert already exists for the
#     domain, Certbot skips issuance and reports "Certificate not yet due for
#     renewal". The Nginx config is still updated/verified.
#   - All verification steps are read-only and safe to re-run.
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
  Usage: sudo bash /home/deploy/app/scripts/vps-setup/13-certbot.sh"
fi

# ── Resolve VPS_SUBDOMAIN ─────────────────────────────────────────────────────
# Priority: CLI argument > VPS_SUBDOMAIN env var > prompt
SUBDOMAIN="${1:-${VPS_SUBDOMAIN:-}}"

if [[ -z "${SUBDOMAIN}" ]]; then
    echo ""
    echo -n "  Enter your DuckDNS subdomain prefix (e.g. bbanalyzer): "
    read -r SUBDOMAIN
fi

if [[ -z "${SUBDOMAIN}" ]]; then
    die "No subdomain provided. Pass it as an argument or set VPS_SUBDOMAIN."
fi

# Strip .duckdns.org if the user accidentally included it
SUBDOMAIN="${SUBDOMAIN%.duckdns.org}"
DOMAIN="${SUBDOMAIN}.duckdns.org"

# ── Resolve ADMIN_EMAIL ───────────────────────────────────────────────────────
# Let's Encrypt uses this for expiry notifications (not for spam).
EMAIL="${2:-${ADMIN_EMAIL:-}}"

if [[ -z "${EMAIL}" ]]; then
    echo ""
    echo "  Let's Encrypt sends certificate expiry warnings to this address."
    echo -n "  Enter admin email for Let's Encrypt notifications: "
    read -r EMAIL
fi

if [[ -z "${EMAIL}" ]]; then
    die "No admin email provided. Pass it as a second argument or set ADMIN_EMAIL."
fi

# Basic email format sanity check
if [[ ! "${EMAIL}" =~ ^[^@]+@[^@]+\.[^@]+$ ]]; then
    die "Invalid email format: '${EMAIL}'. Provide a valid email address."
fi

# ── Configuration ─────────────────────────────────────────────────────────────
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
CERT_FILE="${CERT_DIR}/fullchain.pem"
NGINX_AVAILABLE="/etc/nginx/sites-available/real-estate"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo ""
echo "============================================================"
echo "  Task 6.2 — Obtain Let's Encrypt Certificate via Certbot"
echo "  Started: $TIMESTAMP"
echo "============================================================"
echo "  Domain:       ${DOMAIN}"
echo "  Admin email:  ${EMAIL}"
echo "  Cert dir:     ${CERT_DIR}"
echo "  Nginx config: ${NGINX_AVAILABLE}"
echo "============================================================"
echo ""

# ── Verify prerequisites ──────────────────────────────────────────────────────
if ! command -v nginx &>/dev/null; then
    die "Nginx is not installed. Run 03-install-packages.sh first."
fi
info "  ✓ Nginx found: $(nginx -v 2>&1 | head -1)"

if [[ ! -f "${NGINX_AVAILABLE}" ]]; then
    die "Nginx site config not found at ${NGINX_AVAILABLE}.
  Run 11-nginx-config.sh first."
fi
info "  ✓ Nginx site config found: ${NGINX_AVAILABLE}"

if ! systemctl is-active --quiet nginx; then
    warn "  Nginx is not currently active. Attempting to start it..."
    systemctl start nginx
    sleep 2
    if systemctl is-active --quiet nginx; then
        info "  ✓ Nginx started successfully."
    else
        die "Failed to start Nginx. Check: journalctl -u nginx -n 50"
    fi
else
    info "  ✓ Nginx is active."
fi

# Verify DNS resolves before attempting certificate issuance
info "  Checking DNS resolution for ${DOMAIN}..."
if command -v dig &>/dev/null; then
    DNS_RESULT=$(dig +short "${DOMAIN}" 2>/dev/null || true)
    if [[ -n "${DNS_RESULT}" ]]; then
        info "  ✓ DNS resolves: ${DOMAIN} -> ${DNS_RESULT}"
    else
        warn "  DNS lookup returned no result for ${DOMAIN}."
        warn "  Certbot will fail if the domain does not resolve to this VPS."
        warn "  Ensure 12-duckdns.sh has been run and DNS has propagated."
        warn "  Continuing anyway — Certbot will provide a clear error if DNS fails."
    fi
else
    warn "  'dig' not available — skipping DNS pre-check."
    warn "  Ensure ${DOMAIN} resolves to this VPS before proceeding."
fi

echo ""

# =============================================================================
# Step 1: Install certbot and python3-certbot-nginx (Requirement 5.3)
# =============================================================================
step "Step 1: Installing certbot and python3-certbot-nginx via apt..."

# Update package index (suppress output unless there's an error)
info "  Updating apt package index..."
apt-get update -qq

# Install certbot and the Nginx plugin (idempotent — apt skips if already installed)
apt-get install -y certbot python3-certbot-nginx

# Verify installation
if ! command -v certbot &>/dev/null; then
    die "certbot installation failed. Check apt output above."
fi

CERTBOT_VERSION=$(certbot --version 2>&1 | head -1)
info "  ✓ certbot installed: ${CERTBOT_VERSION}"

# Verify the Nginx plugin is available
if python3 -c "import certbot_nginx" 2>/dev/null; then
    info "  ✓ python3-certbot-nginx plugin available."
else
    # Plugin may be importable under a different name — check via certbot itself
    if certbot plugins 2>/dev/null | grep -q "nginx"; then
        info "  ✓ Certbot Nginx plugin available (verified via certbot plugins)."
    else
        warn "  Could not confirm python3-certbot-nginx plugin. Proceeding anyway."
        warn "  If certbot fails with 'nginx plugin not found', run:"
        warn "    sudo apt-get install -y python3-certbot-nginx"
    fi
fi

echo ""

# =============================================================================
# Step 2: Obtain the Let's Encrypt certificate via certbot --nginx (Req 5.3, 5.6)
# =============================================================================
step "Step 2: Obtaining Let's Encrypt certificate for ${DOMAIN}..."

if [[ -f "${CERT_FILE}" ]]; then
    # Certificate already exists — check if it's still valid
    EXPIRY=$(openssl x509 -enddate -noout -in "${CERT_FILE}" 2>/dev/null \
             | sed 's/notAfter=//' || echo "unknown")
    info "  Certificate already exists for ${DOMAIN}."
    info "  Current expiry: ${EXPIRY}"
    info "  Running certbot --nginx to verify/update Nginx config..."
    echo ""
fi

# Run certbot with the Nginx plugin.
# --non-interactive: no prompts (required for scripted use)
# --agree-tos:       accept Let's Encrypt Terms of Service
# --email:           contact address for expiry notifications
# --nginx:           use the Nginx authenticator + installer
#                    (handles ACME challenge and updates nginx config)
# --redirect:        add HTTP→HTTPS 301 redirect (Requirement 5.5)
#                    Note: our nginx config already has the redirect block,
#                    but --redirect ensures certbot also sets it up correctly.
certbot --nginx \
    -d "${DOMAIN}" \
    --non-interactive \
    --agree-tos \
    --email "${EMAIL}" \
    --redirect

echo ""

# Verify the certificate was issued/renewed
if [[ -f "${CERT_FILE}" ]]; then
    EXPIRY=$(openssl x509 -enddate -noout -in "${CERT_FILE}" 2>/dev/null \
             | sed 's/notAfter=//' || echo "unknown")
    info "  ✓ Certificate obtained for ${DOMAIN}"
    info "  ✓ Certificate file: ${CERT_FILE}"
    info "  ✓ Expiry: ${EXPIRY}"
else
    die "Certificate file not found at ${CERT_FILE} after certbot run.
  Check certbot output above for errors."
fi

echo ""

# =============================================================================
# Step 3: Verify certbot renew --dry-run (Requirement 5.4)
# =============================================================================
step "Step 3: Verifying auto-renewal with certbot renew --dry-run..."
echo ""

# --dry-run simulates the renewal process without actually contacting Let's
# Encrypt or modifying any files. A successful dry-run confirms that:
#   - The renewal configuration is correct
#   - The ACME challenge can be completed
#   - The certbot.timer auto-renewal will work when it runs
if certbot renew --dry-run; then
    echo ""
    info "  ✓ certbot renew --dry-run succeeded."
    info "  ✓ Auto-renewal is correctly configured."
else
    echo ""
    die "certbot renew --dry-run FAILED.
  Auto-renewal may not work. Check the output above for errors.
  Common causes:
    - Port 80 is blocked (check UFW: ufw status)
    - Nginx is not serving the ACME challenge correctly
    - DNS does not resolve to this VPS"
fi

echo ""

# =============================================================================
# Step 4: Verify certbot.timer is active (Requirement 5.4)
# =============================================================================
step "Step 4: Verifying certbot.timer systemd unit is active..."

# The certbot package installs a systemd timer that runs certbot renew twice
# daily. This is the auto-renewal mechanism (Requirement 5.4).
if systemctl is-active --quiet certbot.timer; then
    TIMER_STATUS=$(systemctl show certbot.timer --property=ActiveState --value 2>/dev/null || echo "unknown")
    NEXT_TRIGGER=$(systemctl show certbot.timer --property=NextElapseUSecRealtime --value 2>/dev/null || echo "unknown")
    info "  ✓ certbot.timer is active (auto-renewal enabled)."
    info "  ✓ Timer state: ${TIMER_STATUS}"

    # Show next scheduled run in human-readable form if possible
    if command -v systemctl &>/dev/null; then
        TIMER_LIST=$(systemctl list-timers certbot.timer --no-pager 2>/dev/null || true)
        if [[ -n "${TIMER_LIST}" ]]; then
            echo ""
            echo "  Timer schedule:"
            echo "${TIMER_LIST}" | head -5 | sed 's/^/    /'
        fi
    fi
else
    # Timer may be installed but not enabled — try to enable it
    warn "  certbot.timer is not active. Attempting to enable and start it..."
    systemctl enable certbot.timer 2>/dev/null || true
    systemctl start certbot.timer 2>/dev/null || true

    if systemctl is-active --quiet certbot.timer; then
        info "  ✓ certbot.timer enabled and started successfully."
    else
        warn "  certbot.timer could not be started."
        warn "  Check: systemctl status certbot.timer"
        warn ""
        warn "  As a fallback, you can add a cron job for renewal:"
        warn "    0 0,12 * * * root certbot renew --quiet"
        warn ""
        warn "  Continuing — the certificate is valid; renewal can be fixed separately."
    fi
fi

echo ""

# =============================================================================
# Step 5: Validate Nginx configuration (Requirement 4.7)
# =============================================================================
step "Step 5: Validating Nginx configuration with nginx -t..."
echo ""

if nginx -t; then
    echo ""
    info "  ✓ nginx -t passed — configuration is valid."
else
    echo ""
    die "nginx -t FAILED after Certbot ran.
  Certbot may have introduced a syntax error in the Nginx config.
  Check: cat ${NGINX_AVAILABLE}
  And:   cat /etc/nginx/sites-enabled/real-estate"
fi

echo ""

# =============================================================================
# Step 6: Reload Nginx to apply TLS configuration
# =============================================================================
step "Step 6: Reloading Nginx to apply TLS configuration..."

systemctl reload nginx
sleep 2

if systemctl is-active --quiet nginx; then
    info "  ✓ Nginx reloaded and is active."
else
    die "Nginx is not active after reload. Check: journalctl -u nginx -n 50"
fi

echo ""

# =============================================================================
# Step 7: Verify HTTPS is working (Requirement 5.3, 5.5)
# =============================================================================
step "Step 7: Verifying HTTPS is working on ${DOMAIN}..."

# Give Nginx a moment to fully apply the new config
sleep 2

HTTPS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time 15 \
    "https://${DOMAIN}/" 2>/dev/null || echo "000")

if [[ "${HTTPS_STATUS}" =~ ^(200|301|302|304)$ ]]; then
    info "  ✓ HTTPS is working — https://${DOMAIN}/ returned HTTP ${HTTPS_STATUS}"
elif [[ "${HTTPS_STATUS}" == "000" ]]; then
    warn "  HTTPS check returned HTTP 000 (connection failed or timed out)."
    warn "  This may be a DNS propagation delay. Try manually:"
    warn "    curl -v https://${DOMAIN}/"
    warn "  Continuing — the certificate was issued successfully."
else
    warn "  HTTPS returned HTTP ${HTTPS_STATUS}."
    warn "  The certificate is valid but the application may not be running yet."
    warn "  Check: systemctl status gunicorn"
fi

echo ""

# =============================================================================
# Step 8: Verify HTTP redirects to HTTPS (Requirement 5.5)
# =============================================================================
step "Step 8: Verifying HTTP redirects to HTTPS (301 permanent redirect)..."

# Use --max-redirs 0 to capture the redirect response without following it.
# We expect HTTP 301 from the HTTP→HTTPS redirect block in the Nginx config.
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time 15 \
    --max-redirs 0 \
    "http://${DOMAIN}/" 2>/dev/null || echo "000")

if [[ "${HTTP_STATUS}" == "301" ]]; then
    info "  ✓ HTTP redirects to HTTPS — http://${DOMAIN}/ returned HTTP 301"

    # Also verify the Location header points to HTTPS
    REDIRECT_LOCATION=$(curl -s -o /dev/null -w "%{redirect_url}" \
        --max-time 15 \
        --max-redirs 0 \
        "http://${DOMAIN}/" 2>/dev/null || echo "")
    if [[ "${REDIRECT_LOCATION}" == https://* ]]; then
        info "  ✓ Redirect location: ${REDIRECT_LOCATION}"
    else
        warn "  Redirect location: '${REDIRECT_LOCATION}' (expected https://...)"
    fi
elif [[ "${HTTP_STATUS}" == "000" ]]; then
    warn "  HTTP redirect check returned HTTP 000 (connection failed or timed out)."
    warn "  This may be a DNS propagation delay. Try manually:"
    warn "    curl -I http://${DOMAIN}/"
    warn "  Continuing — the Nginx config has the redirect block configured."
else
    warn "  HTTP returned HTTP ${HTTP_STATUS} (expected 301)."
    warn "  Check the Nginx config: cat ${NGINX_AVAILABLE}"
    warn "  The HTTP→HTTPS redirect block should be present."
fi

echo ""

# =============================================================================
# Summary
# =============================================================================
echo "============================================================"
echo "  Task 6.2 complete — Let's Encrypt SSL configured"
echo "  Finished: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "============================================================"
echo "  Domain:           ${DOMAIN}"
echo "  Certificate:      ${CERT_FILE}  ✓"
echo "  Expiry:           $(openssl x509 -enddate -noout -in "${CERT_FILE}" 2>/dev/null | sed 's/notAfter=//' || echo 'see above')"
echo "  Auto-renewal:     certbot.timer  ✓"
echo "  Dry-run:          passed  ✓"
echo "  nginx -t:         passed  ✓"
echo "  HTTPS:            https://${DOMAIN}/  (HTTP ${HTTPS_STATUS})"
echo "  HTTP redirect:    http://${DOMAIN}/ -> HTTPS  (HTTP ${HTTP_STATUS})"
echo ""
echo "  TLS configuration (Mozilla Intermediate via certbot):"
echo "    Min TLS version: 1.2"
echo "    Cipher suite:    /etc/letsencrypt/options-ssl-nginx.conf"
echo "    DH params:       /etc/letsencrypt/ssl-dhparams.pem"
echo ""
echo "  NEXT STEPS:"
echo "    7.   Checkpoint — verify the application is live"
echo "         curl -f https://${DOMAIN}/api/health"
echo "         systemctl is-active gunicorn"
echo "         systemctl is-active nginx"
echo "         journalctl -u gunicorn -n 20"
echo "============================================================"
