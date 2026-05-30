#!/usr/bin/env bash
# =============================================================================
# 12-duckdns.sh
# VPS Setup — Task 6.1: Set up DuckDNS subdomain and cron-based IP update script.
#
# Requirements: 5.1, 5.2
#
# Run ON THE VPS as the deploy user (NOT as root):
#   bash /home/deploy/app/scripts/vps-setup/12-duckdns.sh
#
# Pass credentials as environment variables or let the script prompt for them:
#   DUCKDNS_TOKEN=your-token DUCKDNS_SUBDOMAIN=bbanalyzer \
#     bash /home/deploy/app/scripts/vps-setup/12-duckdns.sh
#
# Prerequisites:
#   - 03-install-packages.sh has been run (curl is installed)
#   - You have registered a DuckDNS account and created a subdomain at
#     https://www.duckdns.org — see the manual step instructions printed
#     at the end of this script.
#
# What this script does:
#   1. Prompts for DUCKDNS_TOKEN and DUCKDNS_SUBDOMAIN if not set in env
#   2. Creates /home/deploy/duckdns/ directory
#   3. Writes /home/deploy/duckdns/duck.sh with the DuckDNS curl update command
#   4. Makes duck.sh executable (chmod +x)
#   5. Adds the cron job */5 * * * * to the deploy user's crontab (idempotent)
#   6. Runs duck.sh once to verify it works and checks duck.log for "OK"
#   7. Prints instructions for the manual subdomain registration step
#
# MANUAL STEP REQUIRED:
#   Before running this script, register your subdomain at duckdns.org and
#   point it to the VPS public IP. See the instructions printed at the end.
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

# ── Verify running as deploy user (not root) ──────────────────────────────────
if [[ $EUID -eq 0 ]]; then
    die "Run this script as the deploy user, NOT as root.
  Usage: bash /home/deploy/app/scripts/vps-setup/12-duckdns.sh"
fi

# ── Resolve DUCKDNS_TOKEN ─────────────────────────────────────────────────────
if [[ -z "${DUCKDNS_TOKEN:-}" ]]; then
    echo ""
    echo "  Your DuckDNS token is shown on your account page at https://www.duckdns.org"
    echo -n "  Enter your DuckDNS token: "
    read -rs DUCKDNS_TOKEN
    echo ""
fi

if [[ -z "${DUCKDNS_TOKEN:-}" ]]; then
    die "No DuckDNS token provided. Set DUCKDNS_TOKEN or enter it when prompted."
fi

# ── Resolve DUCKDNS_SUBDOMAIN ─────────────────────────────────────────────────
if [[ -z "${DUCKDNS_SUBDOMAIN:-}" ]]; then
    echo ""
    echo "  Enter the subdomain prefix only (e.g. 'bbanalyzer' for bbanalyzer.duckdns.org)"
    echo -n "  Enter your DuckDNS subdomain: "
    read -r DUCKDNS_SUBDOMAIN
fi

if [[ -z "${DUCKDNS_SUBDOMAIN:-}" ]]; then
    die "No DuckDNS subdomain provided. Set DUCKDNS_SUBDOMAIN or enter it when prompted."
fi

# Strip .duckdns.org if the user accidentally included it
DUCKDNS_SUBDOMAIN="${DUCKDNS_SUBDOMAIN%.duckdns.org}"
DOMAIN="${DUCKDNS_SUBDOMAIN}.duckdns.org"

# ── Configuration ─────────────────────────────────────────────────────────────
DUCKDNS_DIR="/home/deploy/duckdns"
DUCK_SCRIPT="${DUCKDNS_DIR}/duck.sh"
DUCK_LOG="${DUCKDNS_DIR}/duck.log"
CRON_JOB="*/5 * * * * ${DUCK_SCRIPT} >/dev/null 2>&1"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo ""
echo "============================================================"
echo "  Task 6.1 — DuckDNS Subdomain + Cron IP Update Script"
echo "  Started: $TIMESTAMP"
echo "============================================================"
echo "  Subdomain:    ${DOMAIN}"
echo "  Script:       ${DUCK_SCRIPT}"
echo "  Log:          ${DUCK_LOG}"
echo "  Cron job:     ${CRON_JOB}"
echo "============================================================"
echo ""

# ── Verify curl is available ──────────────────────────────────────────────────
if ! command -v curl &>/dev/null; then
    die "curl is not installed. Run 03-install-packages.sh first."
fi
info "  ✓ curl found: $(curl --version | head -1)"

# =============================================================================
# Step 1: Create /home/deploy/duckdns/ directory (Requirement 5.1)
# =============================================================================
step "Step 1: Creating ${DUCKDNS_DIR} directory..."

if [[ -d "${DUCKDNS_DIR}" ]]; then
    info "  ✓ Directory already exists: ${DUCKDNS_DIR}"
else
    mkdir -p "${DUCKDNS_DIR}"
    info "  ✓ Directory created: ${DUCKDNS_DIR}"
fi

# =============================================================================
# Step 2: Write /home/deploy/duckdns/duck.sh (Requirement 5.1)
# =============================================================================
step "Step 2: Writing ${DUCK_SCRIPT}..."

# Write the exact curl update command from the design document.
# The -K flag reads the URL from stdin; -k skips SSL verification for the
# DuckDNS API call; -o writes the response ("OK" or "KO") to duck.log.
# Leaving &ip= empty tells DuckDNS to auto-detect the VPS public IP.
cat > "${DUCK_SCRIPT}" << DUCK_SH
#!/usr/bin/env bash
echo url="https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=" | curl -o ${DUCK_LOG} -K -
DUCK_SH

info "  ✓ ${DUCK_SCRIPT} written."

# =============================================================================
# Step 3: Make duck.sh executable (Requirement 5.1)
# =============================================================================
step "Step 3: Making ${DUCK_SCRIPT} executable..."

chmod 700 "${DUCK_SCRIPT}"
info "  ✓ chmod 700 applied to ${DUCK_SCRIPT}"

# Verify permissions
PERMS=$(stat -c "%a" "${DUCK_SCRIPT}")
info "  ✓ Permissions: ${PERMS} (expected: 700)"

# =============================================================================
# Step 4: Add cron job to deploy user's crontab (Requirement 5.2)
# =============================================================================
step "Step 4: Adding cron job to deploy user's crontab (idempotent)..."

# Read existing crontab (empty output is fine if no crontab exists yet)
EXISTING_CRONTAB=$(crontab -l 2>/dev/null || true)

if echo "${EXISTING_CRONTAB}" | grep -qF "${DUCK_SCRIPT}"; then
    info "  ✓ Cron job already present — skipping duplicate addition."
    info "    Existing entry: $(echo "${EXISTING_CRONTAB}" | grep -F "${DUCK_SCRIPT}")"
else
    # Append the new cron job to the existing crontab
    (echo "${EXISTING_CRONTAB}"; echo "${CRON_JOB}") | crontab -
    info "  ✓ Cron job added: ${CRON_JOB}"
fi

# Verify the cron job is now present
UPDATED_CRONTAB=$(crontab -l 2>/dev/null || true)
if echo "${UPDATED_CRONTAB}" | grep -qF "${DUCK_SCRIPT}"; then
    info "  ✓ Cron job confirmed in crontab."
else
    die "Cron job was not found in crontab after insertion. Check crontab manually: crontab -l"
fi

# =============================================================================
# Step 5: Run duck.sh once to verify it works (Requirement 5.1)
# =============================================================================
step "Step 5: Running ${DUCK_SCRIPT} once to verify DuckDNS update..."
echo ""

bash "${DUCK_SCRIPT}"

echo ""

# Check duck.log for "OK" response from DuckDNS API
if [[ -f "${DUCK_LOG}" ]]; then
    DUCK_RESPONSE=$(cat "${DUCK_LOG}")
    info "  DuckDNS API response: '${DUCK_RESPONSE}'"

    if [[ "${DUCK_RESPONSE}" == "OK" ]]; then
        info "  ✓ DuckDNS update succeeded — response is 'OK'."
        info "  ✓ ${DOMAIN} is now pointing to this VPS's public IP."
    elif [[ "${DUCK_RESPONSE}" == "KO" ]]; then
        warn "  ✗ DuckDNS update returned 'KO' (failure)."
        warn ""
        warn "  Common causes:"
        warn "    - The token is incorrect (check https://www.duckdns.org)"
        warn "    - The subdomain '${DUCKDNS_SUBDOMAIN}' does not exist on your account"
        warn "    - The subdomain belongs to a different DuckDNS account"
        warn ""
        warn "  The cron job has still been installed. Fix the token/subdomain"
        warn "  and re-run this script, or edit ${DUCK_SCRIPT} directly."
        warn ""
        warn "  To test manually after fixing:"
        warn "    bash ${DUCK_SCRIPT} && cat ${DUCK_LOG}"
    else
        warn "  Unexpected DuckDNS response: '${DUCK_RESPONSE}'"
        warn "  Expected 'OK' or 'KO'. Check ${DUCK_LOG} for details."
    fi
else
    warn "  ${DUCK_LOG} was not created. The curl command may have failed."
    warn "  Check that curl is working: curl -v https://www.duckdns.org"
fi

# =============================================================================
# Step 6: Print manual subdomain registration instructions
# =============================================================================
echo ""
echo "============================================================"
echo "  MANUAL STEP — Register subdomain at duckdns.org"
echo "============================================================"
echo ""
echo "  If you haven't already registered the subdomain, follow"
echo "  these steps:"
echo ""
echo "  1. Go to https://www.duckdns.org and sign in (GitHub,"
echo "     Google, Twitter, or Reddit account)."
echo ""
echo "  2. In the 'sub domain' field, type: ${DUCKDNS_SUBDOMAIN}"
echo "     Then click 'add domain'."
echo ""
echo "  3. In the 'current ip' column next to your subdomain,"
echo "     enter the VPS public IP address."
echo "     (Find it with: curl -s https://api.ipify.org)"
echo ""
echo "  4. Click 'update ip' to save."
echo ""
echo "  5. Verify DNS propagation (may take a few minutes):"
echo "     nslookup ${DOMAIN}"
echo "     # Should resolve to your VPS public IP"
echo ""
echo "  Your DuckDNS token is stored in ${DUCK_SCRIPT} (owner-read only)."
echo ""
echo "  The cron job will keep the DNS record current automatically"
echo "  every 5 minutes if the VPS IP ever changes."
echo "============================================================"

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "============================================================"
echo "  Task 6.1 complete — DuckDNS configured"
echo "============================================================"
echo "  Directory:    ${DUCKDNS_DIR}  ✓"
echo "  Script:       ${DUCK_SCRIPT}  ✓"
echo "  Executable:   chmod 700 applied  ✓"
echo "  Cron job:     */5 * * * *  ✓"
echo "  Test run:     completed (see response above)"
echo ""
echo "  NEXT STEPS:"
echo "    6.2  Obtain the Let's Encrypt certificate via Certbot"
echo "         sudo bash /home/deploy/app/scripts/vps-setup/13-certbot.sh"
echo ""
echo "  After Certbot runs, the application will be accessible at:"
echo "    https://${DOMAIN}"
echo "============================================================"
