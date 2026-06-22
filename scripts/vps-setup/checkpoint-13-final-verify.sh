#!/usr/bin/env bash
# =============================================================================
# checkpoint-13-final-verify.sh
# VPS Setup — Task 13: Final Checkpoint — End-to-End Deployment Verification
#
# Requirements: 5.5, 6.1, 6.5, 10.1, 10.5
#
# Run LOCALLY (not on the VPS) after all provisioning is complete:
#   bash scripts/vps-setup/checkpoint-13-final-verify.sh bbanalyzer
#
# Or pass the subdomain via environment variable:
#   VPS_SUBDOMAIN=bbanalyzer bash scripts/vps-setup/checkpoint-13-final-verify.sh
#
# What this script checks (all run from your local machine):
#   1. curl -f https://<subdomain>.duckdns.org/api/health  → HTTP 200
#   2. curl -I http://<subdomain>.duckdns.org/             → 301 Moved Permanently
#   3. Prints a summary of all provisioning scripts and their purposes
#   4. Provides instructions for triggering the GitHub Actions deploy workflow
#
# Exit codes:
#   0 — all checks passed (PASS)
#   1 — one or more checks failed (FAIL)
#
# This script is READ-ONLY and IDEMPOTENT — it makes no changes to any system.
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
echo -e "  ${BOLD}Task 13 — Final Checkpoint: End-to-End Verification${NC}"
echo "  Started: $TIMESTAMP"
echo "============================================================"
echo "  Domain:  ${DOMAIN}"
echo "  HTTPS:   https://${DOMAIN}/"
echo "  Health:  https://${DOMAIN}/api/health"
echo "============================================================"
echo ""

# =============================================================================
# Check 1: HTTPS health endpoint returns HTTP 200 (Requirements 10.1, 10.5)
# =============================================================================
step "Check 1: curl -f https://${DOMAIN}/api/health  →  expect HTTP 200"
echo ""

HEALTH_URL="https://${DOMAIN}/api/health"
HEALTH_RESPONSE_FILE=$(mktemp)
HEALTH_STATUS=$(curl -s \
    -o "${HEALTH_RESPONSE_FILE}" \
    -w "%{http_code}" \
    --max-time 20 \
    "${HEALTH_URL}" 2>/dev/null || echo "000")

if [[ "${HEALTH_STATUS}" == "200" ]]; then
    record_pass "/api/health returned HTTP 200"
    info "  URL:    ${HEALTH_URL}"
    info "  Status: HTTP ${HEALTH_STATUS}"

    # Pretty-print the JSON body if python3 is available
    if command -v python3 &>/dev/null && [[ -s "${HEALTH_RESPONSE_FILE}" ]]; then
        BODY=$(python3 -m json.tool "${HEALTH_RESPONSE_FILE}" 2>/dev/null \
               || cat "${HEALTH_RESPONSE_FILE}" 2>/dev/null \
               || echo "(empty)")
        info "  Body:   ${BODY}"
    elif [[ -s "${HEALTH_RESPONSE_FILE}" ]]; then
        BODY=$(cat "${HEALTH_RESPONSE_FILE}" 2>/dev/null || echo "(empty)")
        info "  Body:   ${BODY}"
    fi

elif [[ "${HEALTH_STATUS}" == "000" ]]; then
    record_fail "/api/health — connection failed or timed out (HTTP 000)"
    error "  URL:    ${HEALTH_URL}"
    error "  Status: HTTP 000 (no response)"
    error ""
    error "  Possible causes:"
    error "    - DNS has not propagated: dig +short ${DOMAIN}"
    error "    - TLS certificate is missing or invalid"
    error "    - Nginx is not running on the VPS"
    error "    - Port 443 is blocked by UFW: sudo ufw status"
    error "    - Gunicorn is not running: systemctl is-active gunicorn"
    error ""
    error "  Verify DNS resolution:"
    error "    dig +short ${DOMAIN}"
    error ""
    error "  Test without TLS (from the VPS):"
    error "    curl -f http://127.0.0.1:5000/api/health"

elif [[ "${HEALTH_STATUS}" == "503" ]]; then
    record_fail "/api/health returned HTTP 503 (database unavailable)"
    error "  URL:    ${HEALTH_URL}"
    error "  Status: HTTP ${HEALTH_STATUS}"
    if [[ -s "${HEALTH_RESPONSE_FILE}" ]]; then
        BODY=$(cat "${HEALTH_RESPONSE_FILE}" 2>/dev/null || echo "(empty)")
        error "  Body:   ${BODY}"
    fi
    error ""
    error "  The application is running but the database connection failed."
    error "  On the VPS, diagnose with:"
    error "    systemctl status postgresql"
    error "    psql -U app_user -d real_estate_analysis -c 'SELECT 1'"
    error "    journalctl -u gunicorn -n 50 --no-pager"

else
    record_fail "/api/health returned unexpected HTTP ${HEALTH_STATUS} (expected 200)"
    error "  URL:    ${HEALTH_URL}"
    error "  Status: HTTP ${HEALTH_STATUS}"
    if [[ -s "${HEALTH_RESPONSE_FILE}" ]]; then
        BODY=$(cat "${HEALTH_RESPONSE_FILE}" 2>/dev/null || echo "(empty)")
        error "  Body:   ${BODY}"
    fi
    error ""
    error "  Diagnose with:"
    error "    curl -v ${HEALTH_URL}"
    error "    On VPS: journalctl -u gunicorn -n 50 --no-pager"
    error "    On VPS: journalctl -u nginx -n 50 --no-pager"
fi

rm -f "${HEALTH_RESPONSE_FILE}"
echo ""

# =============================================================================
# Check 2: HTTP redirects to HTTPS with 301 (Requirement 5.5)
# =============================================================================
step "Check 2: curl -I http://${DOMAIN}/  →  expect 301 Moved Permanently"
echo ""

HTTP_URL="http://${DOMAIN}/"
REDIRECT_OUTPUT=$(curl -s -I \
    --max-time 15 \
    --max-redirs 0 \
    "${HTTP_URL}" 2>/dev/null || echo "CURL_FAILED")

if [[ "${REDIRECT_OUTPUT}" == "CURL_FAILED" ]]; then
    record_fail "HTTP redirect check — curl failed (connection refused or timed out)"
    error "  URL:    ${HTTP_URL}"
    error ""
    error "  Possible causes:"
    error "    - DNS has not propagated: dig +short ${DOMAIN}"
    error "    - Port 80 is blocked by UFW: sudo ufw status"
    error "    - Nginx is not running on the VPS"
else
    # Extract the status line (first line of headers)
    STATUS_LINE=$(echo "${REDIRECT_OUTPUT}" | head -1 | tr -d '\r')
    # Extract the Location header
    LOCATION=$(echo "${REDIRECT_OUTPUT}" | grep -i "^location:" | head -1 | tr -d '\r' || echo "")

    if echo "${STATUS_LINE}" | grep -q "301"; then
        record_pass "HTTP → HTTPS redirect returned 301 Moved Permanently"
        info "  URL:      ${HTTP_URL}"
        info "  Status:   ${STATUS_LINE}"
        if [[ -n "${LOCATION}" ]]; then
            info "  Location: ${LOCATION}"
        fi

        # Verify the redirect target is HTTPS
        if echo "${LOCATION}" | grep -qi "^location: https://"; then
            info "  Redirect target is HTTPS ✓"
        elif [[ -n "${LOCATION}" ]]; then
            record_fail "HTTP redirect Location header does not point to HTTPS"
            error "  Location header does not start with https:// — check Nginx config"
            error "  Got: ${LOCATION}"
        fi

    elif echo "${STATUS_LINE}" | grep -q "302\|307\|308"; then
        # Technically a redirect, but not the 301 permanent redirect required
        record_fail "HTTP redirect returned ${STATUS_LINE} (expected 301 Moved Permanently)"
        error "  URL:    ${HTTP_URL}"
        error "  Status: ${STATUS_LINE}"
        error ""
        error "  The Nginx config should use 'return 301 https://\$host\$request_uri;'"
        error "  Check: /etc/nginx/sites-available/real-estate"

    else
        record_fail "HTTP redirect check — unexpected response: ${STATUS_LINE}"
        error "  URL:    ${HTTP_URL}"
        error "  Status: ${STATUS_LINE}"
        error ""
        error "  Expected: HTTP/1.1 301 Moved Permanently"
        error "  Full headers:"
        echo "${REDIRECT_OUTPUT}" | head -10 | sed 's/^/    /' >&2
        error ""
        error "  Check Nginx config: /etc/nginx/sites-available/real-estate"
        error "  Validate config:    sudo nginx -t"
    fi
fi

echo ""

# =============================================================================
# Check 3: /api/health reports Redis and Celery (async stack)
# =============================================================================
step "Check 3: /api/health async stack (redis + celery)"
echo ""

ASYNC_HEALTH_FILE=$(mktemp)
ASYNC_STATUS=$(curl -s \
    -o "${ASYNC_HEALTH_FILE}" \
    -w "%{http_code}" \
    --max-time 20 \
    "${HEALTH_URL}" 2>/dev/null || echo "000")

if [[ "${ASYNC_STATUS}" == "200" ]] && command -v python3 &>/dev/null; then
    if python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
checks = d.get('checks', {})
redis = checks.get('redis', '')
celery = checks.get('celery', '')
if redis == 'ok' and celery == 'ok':
    sys.exit(0)
if 'ok' not in redis:
    print(f'redis: {redis}')
if 'ok' not in celery:
    print(f'celery: {celery}')
sys.exit(1)
" "${ASYNC_HEALTH_FILE}" 2>/dev/null; then
        record_pass "/api/health reports redis=ok and celery=ok"
    else
        ASYNC_DETAIL=$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
checks = d.get('checks', {})
print('redis:', checks.get('redis', 'missing'))
print('celery:', checks.get('celery', 'missing'))
" "${ASYNC_HEALTH_FILE}" 2>/dev/null || echo "(could not parse health JSON)")
        record_fail "/api/health async stack check failed"
        error "  ${ASYNC_DETAIL}"
        error ""
        error "  On the VPS, provision or repair the async stack:"
        error "    sudo bash /home/deploy/app/scripts/vps-setup/migrate-async-stack.sh"
        error "  Re-run sudoers after deploy.sh gains new sudo commands:"
        error "    sudo bash /home/deploy/app/scripts/vps-setup/11-sudoers-deploy.sh"
    fi
else
    record_fail "/api/health async stack check skipped — health endpoint unavailable"
    error "  Could not fetch ${HEALTH_URL} (HTTP ${ASYNC_STATUS})"
fi

rm -f "${ASYNC_HEALTH_FILE}"
echo ""

# =============================================================================
# Provisioning Scripts Summary
# =============================================================================
echo "============================================================"
echo -e "  ${BOLD}Provisioning Scripts Created${NC}"
echo "============================================================"
echo ""
echo "  All scripts are in: scripts/vps-setup/"
echo ""
echo "  ┌─────────────────────────────────────────────────────────────────┐"
echo "  │  Script                          Purpose                        │"
echo "  ├─────────────────────────────────────────────────────────────────┤"
echo "  │  01-create-deploy-user.sh        Create deploy user, SSH keys,  │"
echo "  │                                  disable password auth          │"
echo "  │  02-firewall-fail2ban.sh         UFW firewall (22/80/443),      │"
echo "  │                                  fail2ban SSH protection        │"
echo "  │  03-install-packages.sh          Python 3.11, Node.js 20,       │"
echo "  │                                  PostgreSQL 15, Nginx, Certbot  │"
echo "  │  04-clone-repo.sh                Clone repo to /home/deploy/app │"
echo "  │  05-postgres-setup.sh            Create app_user role and       │"
echo "  │                                  real_estate_analysis database  │"
echo "  │  06a-neon-export.sh              Export data from Neon (local)  │"
echo "  │  06b-neon-restore.sh             Restore dump to VPS PostgreSQL │"
echo "  │  07-create-env-file.sh           Write /home/deploy/app/        │"
echo "  │                                  backend/.env (production)      │"
echo "  │  08-alembic-migrate.sh           flask db upgrade head +        │"
echo "  │                                  transfer table ownership       │"
echo "  │  09-gunicorn-service.sh          Install gunicorn.service,      │"
echo "  │                                  enable + start                 │"
echo "  │  10-build-frontend.sh            npm ci && npm run build        │"
echo "  │  11-nginx-config.sh              Write Nginx site config,       │"
echo "  │                                  symlink, disable default site  │"
echo "  │  03b-install-redis.sh            Redis server for Celery broker     │"
echo "  │  09b-celery-service.sh           Celery worker + Beat systemd units │"
echo "  │  bootstrap-async-stack.sh        Redis + Celery + sudoers (combo)  │"
echo "  │  migrate-async-stack.sh          One-time migration for existing   │"
echo "  │                                  VPSes before async-stack deploys  │"
echo "  │  11-sudoers-deploy.sh            Passwordless sudo for deploy user  │"
echo "  │  12-duckdns.sh                   DuckDNS update script +        │"
echo "  │                                  cron job (every 5 min)        │"
echo "  │  13-certbot.sh                   Let's Encrypt certificate via  │"
echo "  │                                  certbot --nginx                │"
echo "  │  14-install-rollback.sh          Install rollback.sh on VPS     │"
echo "  │  rollback.sh                     Rollback script template       │"
echo "  │  checkpoint-07-verify-live.sh    Task 7 checkpoint (on VPS)     │"
echo "  │  checkpoint-13-final-verify.sh   Task 13 checkpoint (local) ←   │"
echo "  └─────────────────────────────────────────────────────────────────┘"
echo ""

# =============================================================================
# GitHub Actions Deploy Workflow Instructions
# =============================================================================
echo "============================================================"
echo -e "  ${BOLD}Triggering the GitHub Actions Deploy Workflow${NC}"
echo "============================================================"
echo ""
echo "  The deploy workflow (.github/workflows/deploy.yml) triggers"
echo "  automatically on every push to the 'main' branch, after the"
echo "  CI jobs (frontend typecheck/build/tests + backend pytest) pass."
echo ""
echo "  ── Prerequisites ────────────────────────────────────────────"
echo ""
echo "  Ensure these 5 GitHub repository secrets are set:"
echo "  (Settings → Secrets and variables → Actions → New repository secret)"
echo ""
echo "    VPS_SSH_KEY      Private SSH key for the deploy user (Ed25519)"
echo "    VPS_USER         deploy"
echo "    VPS_HOST         <VPS public IP address>"
echo "    VPS_SUBDOMAIN    ${SUBDOMAIN}"
echo "    DATABASE_URL     postgresql://app_user:<pw>@localhost:5432/real_estate_analysis"
echo ""
echo "  ── How to trigger a deploy ──────────────────────────────────"
echo ""
echo "  Option A — Push a commit to main:"
echo "    git add <changed-files>"
echo "    git commit -m 'chore: trigger deploy'"
echo "    git push origin main"
echo ""
echo "  Option B — Re-run the last workflow run (no new commit needed):"
echo "    1. Go to: https://github.com/<owner>/<repo>/actions"
echo "    2. Click the most recent 'Deploy' workflow run"
echo "    3. Click 'Re-run all jobs'"
echo ""
echo "  Option C — GitHub CLI:"
echo "    gh workflow run deploy.yml --ref main"
echo ""
echo "  ── What to watch for ────────────────────────────────────────"
echo ""
echo "  In the GitHub Actions UI, the deploy job runs these steps:"
echo "    1. Load SSH key"
echo "    2. Add VPS to known hosts"
echo "    3. Deploy (git pull → pip install → npm build → db migrate → reload)"
echo "    4. Post-deploy health check (polls /api/health up to 10× with 3s intervals)"
echo ""
echo "  A green checkmark on step 4 confirms:"
echo "    ✓ All deploy steps completed without error"
echo "    ✓ Gunicorn reloaded successfully"
echo "    ✓ https://${DOMAIN}/api/health returned HTTP 200"
echo ""
echo "  If the deploy fails, check:"
echo "    - The failed step's log output in GitHub Actions"
echo "    - On VPS: journalctl -u gunicorn -n 50 --no-pager"
echo "    - On VPS: ./rollback.sh  (to revert to the previous commit)"
echo ""

# =============================================================================
# Summary
# =============================================================================
echo "============================================================"
echo -e "  ${BOLD}Task 13 Final Checkpoint Summary${NC}"
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
    echo "  The deployment is fully verified:"
    echo "    ✓  https://${DOMAIN}/api/health  →  HTTP 200"
    echo "    ✓  /api/health redis + celery      →  ok"
    echo "    ✓  http://${DOMAIN}/             →  301 → https://${DOMAIN}/"
    echo ""
    echo "  The application is live at:"
    echo "    https://${DOMAIN}/"
    echo ""
    echo "  VPS deployment spec is COMPLETE."
    echo "============================================================"
    exit 0
else
    echo -e "  ${RED}${BOLD}RESULT: ${FAIL_COUNT} CHECK(S) FAILED ✗${NC}"
    echo ""
    echo "  Resolve the failures above before declaring the deployment complete."
    echo ""
    echo "  Quick diagnostics (run on the VPS):"
    echo "    systemctl status gunicorn nginx postgresql"
    echo "    journalctl -u gunicorn -n 50 --no-pager"
    echo "    curl -f http://127.0.0.1:5000/api/health"
    echo "    sudo nginx -t"
    echo "    dig +short ${DOMAIN}"
    echo "============================================================"
    exit 1
fi
