#!/usr/bin/env bash
# =============================================================================
# checkpoint-07-verify-live.sh
# VPS Setup — Task 7: Checkpoint — verify the application is live
#
# Requirements: 3.1, 3.6, 10.1, 10.3
#
# Run ON THE VPS as the deploy user:
#   bash /home/deploy/app/scripts/vps-setup/checkpoint-07-verify-live.sh
#
# Or pass the subdomain as an env var or argument:
#   VPS_SUBDOMAIN=bbanalyzer bash /home/deploy/app/scripts/vps-setup/checkpoint-07-verify-live.sh
#   bash /home/deploy/app/scripts/vps-setup/checkpoint-07-verify-live.sh bbanalyzer
#
# What this script checks:
#   1. systemctl is-active gunicorn  → must return "active"
#   2. systemctl is-active nginx     → must return "active"
#   3. curl -f https://<subdomain>.duckdns.org/api/health  → must return HTTP 200
#   4. journalctl -u gunicorn -n 20  → must contain no ERROR lines
#
# Exit codes:
#   0 — all checks passed (PASS)
#   1 — one or more checks failed (FAIL)
#
# This script is READ-ONLY and IDEMPOTENT — it makes no changes to the system.
# =============================================================================

set -uo pipefail
# Note: -e is intentionally omitted so all checks run even if one fails.
# We collect results and print a summary at the end.

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
step()  { echo -e "${CYAN}[CHECK]${NC} $*"; }
pass()  { echo -e "${GREEN}[PASS]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; }

# ── Resolve VPS_SUBDOMAIN ─────────────────────────────────────────────────────
# Priority: CLI argument > VPS_SUBDOMAIN env var > prompt
SUBDOMAIN="${1:-${VPS_SUBDOMAIN:-}}"

if [[ -z "${SUBDOMAIN}" ]]; then
    echo ""
    echo -n "  Enter your DuckDNS subdomain prefix (e.g. bbanalyzer): "
    read -r SUBDOMAIN
fi

if [[ -z "${SUBDOMAIN}" ]]; then
    error "No subdomain provided. Pass it as an argument or set VPS_SUBDOMAIN."
    exit 1
fi

# Strip .duckdns.org if the user accidentally included it
SUBDOMAIN="${SUBDOMAIN%.duckdns.org}"
DOMAIN="${SUBDOMAIN}.duckdns.org"

# ── Tracking ──────────────────────────────────────────────────────────────────
PASS_COUNT=0
FAIL_COUNT=0
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Arrays to collect pass/fail messages for the summary
declare -a PASS_MSGS=()
declare -a FAIL_MSGS=()

record_pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    PASS_MSGS+=("$*")
    pass "$*"
}

record_fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAIL_MSGS+=("$*")
    fail "$*"
}

# ── Header ────────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo -e "  ${BOLD}Task 7 — Checkpoint: Verify Application is Live${NC}"
echo "  Started: $TIMESTAMP"
echo "============================================================"
echo "  Domain:  ${DOMAIN}"
echo "  Health:  https://${DOMAIN}/api/health"
echo "============================================================"
echo ""

# =============================================================================
# Check 1: gunicorn service is active (Requirements 3.1, 3.6)
# =============================================================================
step "Check 1: systemctl is-active gunicorn"

GUNICORN_STATE=$(systemctl is-active gunicorn 2>/dev/null || echo "unknown")

if [[ "${GUNICORN_STATE}" == "active" ]]; then
    record_pass "gunicorn is active"
    info "  State: ${GUNICORN_STATE}"

    # Show a few recent log lines for context (not a failure condition)
    GUNICORN_UPTIME=$(systemctl show gunicorn --property=ActiveEnterTimestamp --value 2>/dev/null || echo "unknown")
    info "  Active since: ${GUNICORN_UPTIME}"
else
    record_fail "gunicorn is NOT active (state: ${GUNICORN_STATE})"
    error "  Expected: active"
    error "  Got:      ${GUNICORN_STATE}"
    error ""
    error "  Diagnose with:"
    error "    systemctl status gunicorn"
    error "    journalctl -u gunicorn -n 50"
fi

echo ""

# =============================================================================
# Check 2: nginx service is active (Requirement 4.6)
# =============================================================================
step "Check 2: systemctl is-active nginx"

NGINX_STATE=$(systemctl is-active nginx 2>/dev/null || echo "unknown")

if [[ "${NGINX_STATE}" == "active" ]]; then
    record_pass "nginx is active"
    info "  State: ${NGINX_STATE}"

    NGINX_UPTIME=$(systemctl show nginx --property=ActiveEnterTimestamp --value 2>/dev/null || echo "unknown")
    info "  Active since: ${NGINX_UPTIME}"
else
    record_fail "nginx is NOT active (state: ${NGINX_STATE})"
    error "  Expected: active"
    error "  Got:      ${NGINX_STATE}"
    error ""
    error "  Diagnose with:"
    error "    systemctl status nginx"
    error "    nginx -t"
    error "    journalctl -u nginx -n 50"
fi

echo ""

# =============================================================================
# Check 3: /api/health returns HTTP 200 (Requirements 10.1, 10.5)
# =============================================================================
step "Check 3: curl -f https://${DOMAIN}/api/health"

HEALTH_URL="https://${DOMAIN}/api/health"
HEALTH_STATUS=$(curl -s -o /tmp/health_response.json -w "%{http_code}" \
    --max-time 15 \
    "${HEALTH_URL}" 2>/dev/null || echo "000")

if [[ "${HEALTH_STATUS}" == "200" ]]; then
    record_pass "/api/health returned HTTP 200"
    info "  URL:    ${HEALTH_URL}"
    info "  Status: HTTP ${HEALTH_STATUS}"

    # Show the response body if it's valid JSON
    if command -v python3 &>/dev/null && [[ -f /tmp/health_response.json ]]; then
        BODY=$(python3 -m json.tool /tmp/health_response.json 2>/dev/null || cat /tmp/health_response.json 2>/dev/null || echo "(empty)")
        info "  Body:   ${BODY}"
    elif [[ -f /tmp/health_response.json ]]; then
        BODY=$(cat /tmp/health_response.json 2>/dev/null || echo "(empty)")
        info "  Body:   ${BODY}"
    fi
elif [[ "${HEALTH_STATUS}" == "000" ]]; then
    record_fail "/api/health — connection failed or timed out (HTTP 000)"
    error "  URL:    ${HEALTH_URL}"
    error "  Status: HTTP 000 (no response)"
    error ""
    error "  Possible causes:"
    error "    - Nginx is not running (see Check 2 above)"
    error "    - DNS has not propagated: dig +short ${DOMAIN}"
    error "    - TLS certificate is missing or invalid"
    error "    - Port 443 is blocked: sudo ufw status"
    error ""
    error "  Try locally (bypasses DNS/TLS):"
    error "    curl -f http://127.0.0.1:5000/api/health"
elif [[ "${HEALTH_STATUS}" == "503" ]]; then
    record_fail "/api/health returned HTTP 503 (database unavailable)"
    error "  URL:    ${HEALTH_URL}"
    error "  Status: HTTP ${HEALTH_STATUS}"
    if [[ -f /tmp/health_response.json ]]; then
        BODY=$(cat /tmp/health_response.json 2>/dev/null || echo "(empty)")
        error "  Body:   ${BODY}"
    fi
    error ""
    error "  The application is running but the database connection failed."
    error "  Diagnose with:"
    error "    systemctl status postgresql"
    error "    psql -U app_user -d real_estate_analysis -c 'SELECT 1'"
    error "    journalctl -u gunicorn -n 50"
else
    record_fail "/api/health returned unexpected HTTP ${HEALTH_STATUS}"
    error "  URL:    ${HEALTH_URL}"
    error "  Status: HTTP ${HEALTH_STATUS} (expected 200)"
    if [[ -f /tmp/health_response.json ]]; then
        BODY=$(cat /tmp/health_response.json 2>/dev/null || echo "(empty)")
        error "  Body:   ${BODY}"
    fi
    error ""
    error "  Diagnose with:"
    error "    curl -v ${HEALTH_URL}"
    error "    journalctl -u gunicorn -n 50"
    error "    journalctl -u nginx -n 50"
fi

# Clean up temp file
rm -f /tmp/health_response.json

echo ""

# =============================================================================
# Check 4: journalctl -u gunicorn -n 20 shows no ERROR lines (Requirement 10.3)
# =============================================================================
step "Check 4: journalctl -u gunicorn -n 20 — scanning for ERROR lines"

# Capture the last 20 gunicorn journal lines
JOURNAL_OUTPUT=$(journalctl -u gunicorn -n 20 --no-pager 2>/dev/null || echo "")

if [[ -z "${JOURNAL_OUTPUT}" ]]; then
    warn "  No journal output found for gunicorn."
    warn "  This may mean gunicorn has never started, or journald is not collecting its output."
    warn "  Check: systemctl status gunicorn"
    # Treat as a warning, not a hard failure — the service check (Check 1) covers this
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAIL_MSGS+=("gunicorn journal is empty — service may not have started")
else
    # Search for ERROR lines (case-insensitive to catch ERROR, Error, error)
    ERROR_LINES=$(echo "${JOURNAL_OUTPUT}" | grep -i "error" || true)

    if [[ -z "${ERROR_LINES}" ]]; then
        record_pass "No ERROR lines in last 20 gunicorn journal entries"
        info "  Last 20 journal lines (no errors found):"
        echo "${JOURNAL_OUTPUT}" | tail -5 | sed 's/^/    /'
        info "  (showing last 5 of 20 lines)"
    else
        # Count the error lines
        ERROR_COUNT=$(echo "${ERROR_LINES}" | wc -l)
        record_fail "${ERROR_COUNT} ERROR line(s) found in gunicorn journal"
        error "  ERROR lines detected:"
        echo "${ERROR_LINES}" | sed 's/^/    /' >&2
        error ""
        error "  Full last 20 lines:"
        echo "${JOURNAL_OUTPUT}" | sed 's/^/    /' >&2
        error ""
        error "  For more context:"
        error "    journalctl -u gunicorn -n 100 --no-pager"
        error "    journalctl -u gunicorn -f   (follow live)"
    fi
fi

echo ""

# =============================================================================
# Summary
# =============================================================================
echo "============================================================"
echo -e "  ${BOLD}Task 7 Checkpoint Summary${NC}"
echo "  Finished: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "============================================================"
echo ""

if [[ ${PASS_COUNT} -gt 0 ]]; then
    echo -e "  ${GREEN}PASSED (${PASS_COUNT}):${NC}"
    for msg in "${PASS_MSGS[@]}"; do
        echo -e "    ${GREEN}✓${NC}  ${msg}"
    done
    echo ""
fi

if [[ ${FAIL_COUNT} -gt 0 ]]; then
    echo -e "  ${RED}FAILED (${FAIL_COUNT}):${NC}"
    for msg in "${FAIL_MSGS[@]}"; do
        echo -e "    ${RED}✗${NC}  ${msg}"
    done
    echo ""
fi

echo "------------------------------------------------------------"
if [[ ${FAIL_COUNT} -eq 0 ]]; then
    echo -e "  ${GREEN}${BOLD}RESULT: ALL CHECKS PASSED ✓${NC}"
    echo ""
    echo "  The application is live at:"
    echo "    https://${DOMAIN}/"
    echo "    https://${DOMAIN}/api/health"
    echo ""
    echo "  NEXT STEPS:"
    echo "    8.  Create the GitHub Actions deploy workflow"
    echo "        See: .github/workflows/deploy.yml"
    echo "        Run: scripts/vps-setup/  (no script needed — edit the YAML)"
    echo "============================================================"
    exit 0
else
    echo -e "  ${RED}${BOLD}RESULT: ${FAIL_COUNT} CHECK(S) FAILED ✗${NC}"
    echo ""
    echo "  Resolve the failures above before proceeding to Task 8."
    echo ""
    echo "  Quick diagnostics:"
    echo "    systemctl status gunicorn"
    echo "    systemctl status nginx"
    echo "    journalctl -u gunicorn -n 50 --no-pager"
    echo "    curl -v https://${DOMAIN}/api/health"
    echo "    curl -f http://127.0.0.1:5000/api/health  (bypass Nginx)"
    echo "============================================================"
    exit 1
fi
