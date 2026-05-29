#!/usr/bin/env bash
# =============================================================================
# 09-gunicorn-service.sh
# VPS Setup — Task 4.1: Write /etc/systemd/system/gunicorn.service and enable
#             the Gunicorn systemd service.
#
# Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
#
# Run ON THE VPS as root:
#   sudo bash /home/deploy/app/scripts/vps-setup/09-gunicorn-service.sh
#
# Prerequisites:
#   - 01-create-deploy-user.sh has been run (deploy user exists)
#   - 03-install-packages.sh has been run (Python 3.11 installed)
#   - 04-clone-repo.sh has been run (repo cloned to /home/deploy/app)
#   - 07-create-env-file.sh has been run (/home/deploy/app/backend/.env exists)
#   - Python dependencies installed as deploy user:
#       sudo -u deploy pip install --user -r /home/deploy/app/backend/requirements.txt
#     (gunicorn must be at /home/deploy/.local/bin/gunicorn)
#
# This script is IDEMPOTENT — safe to run multiple times.
#   - Writing the unit file overwrites any previous version
#   - systemctl daemon-reload is always safe to re-run
#   - systemctl enable is idempotent (no-op if already enabled)
#   - systemctl start is skipped if the service is already active
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
SERVICE_FILE="/etc/systemd/system/gunicorn.service"
APP_DIR="/home/deploy/app"
BACKEND_DIR="${APP_DIR}/backend"
ENV_FILE="${BACKEND_DIR}/.env"
GUNICORN_BIN="/home/deploy/.local/bin/gunicorn"
DEPLOY_USER="deploy"
DEPLOY_GROUP="deploy"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ── Verify running as root ────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    die "This script must be run as root.
  Usage: sudo bash ${APP_DIR}/scripts/vps-setup/09-gunicorn-service.sh"
fi

# ── Verify deploy user exists ─────────────────────────────────────────────────
if ! id "${DEPLOY_USER}" &>/dev/null; then
    die "User '${DEPLOY_USER}' does not exist.
  Run 01-create-deploy-user.sh first."
fi

# ── Verify backend directory exists ──────────────────────────────────────────
if [[ ! -d "${BACKEND_DIR}" ]]; then
    die "Backend directory not found: ${BACKEND_DIR}
  Run 04-clone-repo.sh first to clone the application repository."
fi

# ── Verify .env file exists ───────────────────────────────────────────────────
if [[ ! -f "${ENV_FILE}" ]]; then
    die "Production .env file not found: ${ENV_FILE}
  Run 07-create-env-file.sh first to create the production environment file."
fi

# ── Verify gunicorn binary exists ─────────────────────────────────────────────
if [[ ! -x "${GUNICORN_BIN}" ]]; then
    die "Gunicorn binary not found or not executable: ${GUNICORN_BIN}
  Install it as the deploy user:
    sudo -u ${DEPLOY_USER} pip install --user -r ${BACKEND_DIR}/requirements.txt"
fi

echo ""
echo "============================================================"
echo "  Task 4.1 — Gunicorn systemd Service"
echo "  Started: $TIMESTAMP"
echo "============================================================"
echo "  Service file: ${SERVICE_FILE}"
echo "  Backend dir:  ${BACKEND_DIR}"
echo "  Env file:     ${ENV_FILE}"
echo "  Gunicorn:     ${GUNICORN_BIN}"
echo "  Run as:       ${DEPLOY_USER}:${DEPLOY_GROUP}"
echo "============================================================"
echo ""

# =============================================================================
# Step 1: Write /etc/systemd/system/gunicorn.service
# =============================================================================
info "Step 1: Writing ${SERVICE_FILE}..."

# Write the unit file exactly as specified in the design document.
# Using a quoted heredoc (<<'EOF') so that $MAINPID is written literally —
# systemd expands it at runtime, not bash.
cat > "${SERVICE_FILE}" <<'EOF'
[Unit]
Description=Gunicorn — B&B Real Estate Analyzer
After=network.target postgresql.service

[Service]
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/app/backend
EnvironmentFile=/home/deploy/app/backend/.env
Environment="FLASK_ENV=production"
ExecStart=/home/deploy/.local/bin/gunicorn \
    --workers 3 \
    --worker-class sync \
    --timeout 120 \
    --bind 127.0.0.1:5000 \
    --access-logfile - \
    --error-logfile - \
    "app:create_app('production')"
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=gunicorn

[Install]
WantedBy=multi-user.target
EOF

# Verify the file was written
if [[ ! -f "${SERVICE_FILE}" ]]; then
    die "Failed to write ${SERVICE_FILE}."
fi

# Set correct permissions: root owns the unit file, world-readable
chmod 644 "${SERVICE_FILE}"
info "  ✓ ${SERVICE_FILE} written (mode 644)."

# =============================================================================
# Step 2: Verify unit file contents match the design specification
# =============================================================================
info "Step 2: Verifying unit file contents..."

check_directive() {
    local directive="$1"
    local description="$2"
    if grep -qF -- "${directive}" "${SERVICE_FILE}"; then
        info "  ✓ ${description}"
    else
        die "  MISSING: ${description}
  Expected to find '${directive}' in ${SERVICE_FILE}"
    fi
}

check_directive "User=deploy"                          "User=deploy (Req 3.5)"
check_directive "Group=deploy"                         "Group=deploy (Req 3.5)"
check_directive "WorkingDirectory=/home/deploy/app/backend" "WorkingDirectory (Req 3.4)"
check_directive "EnvironmentFile=/home/deploy/app/backend/.env" "EnvironmentFile (Req 3.4)"
check_directive 'Environment="FLASK_ENV=production"'  "FLASK_ENV=production (Req 3.7)"
check_directive "--workers 3"                          "3 workers (Req 3.2)"
check_directive "--worker-class sync"                  "sync worker class (Req 3.2)"
check_directive "--timeout 120"                        "--timeout 120 (Req 8.3)"
check_directive "--bind 127.0.0.1:5000"                "--bind 127.0.0.1:5000 (Req 3.2)"
check_directive "ExecReload=/bin/kill -s HUP \$MAINPID" "ExecReload SIGHUP (Req 8.1)"
check_directive "Restart=on-failure"                   "Restart=on-failure (Req 3.3)"
check_directive "RestartSec=5s"                        "RestartSec=5s (Req 3.3)"
check_directive "StandardOutput=journal"               "StandardOutput=journal (Req 10.3)"
check_directive "StandardError=journal"                "StandardError=journal (Req 10.3)"
check_directive "WantedBy=multi-user.target"           "WantedBy=multi-user.target (Req 3.6)"

info "  ✓ All required directives present."

# =============================================================================
# Step 3: Reload systemd daemon so it picks up the new unit file
# =============================================================================
info "Step 3: Running 'systemctl daemon-reload'..."
systemctl daemon-reload
info "  ✓ systemd daemon reloaded."

# =============================================================================
# Step 4: Enable the service (start on boot) — Requirement 3.6
# =============================================================================
info "Step 4: Enabling gunicorn service (start on boot)..."
systemctl enable gunicorn
info "  ✓ gunicorn service enabled (will start automatically on reboot)."

# =============================================================================
# Step 5: Start the service (idempotent — restart if already running)
# =============================================================================
info "Step 5: Starting gunicorn service..."

if systemctl is-active --quiet gunicorn; then
    info "  Service is already active — restarting to apply the new unit file..."
    systemctl restart gunicorn
    info "  ✓ gunicorn service restarted."
else
    systemctl start gunicorn
    info "  ✓ gunicorn service started."
fi

# Give Gunicorn a moment to fully initialise workers before checking status
sleep 3

# =============================================================================
# Step 6: Verify the service is active — Requirement 3.1
# =============================================================================
info "Step 6: Verifying 'systemctl is-active gunicorn'..."

ACTIVE_STATUS=$(systemctl is-active gunicorn 2>&1 || true)

if [[ "${ACTIVE_STATUS}" == "active" ]]; then
    info "  ✓ systemctl is-active gunicorn → active  (Req 3.1 satisfied)"
else
    error "  systemctl is-active gunicorn returned: '${ACTIVE_STATUS}'"
    error "  The service did not start successfully."
    echo ""
    echo "  ── systemctl status gunicorn ──────────────────────────────────"
    systemctl status gunicorn --no-pager -l || true
    echo "  ── journalctl -u gunicorn -n 30 ───────────────────────────────"
    journalctl -u gunicorn -n 30 --no-pager || true
    echo "  ───────────────────────────────────────────────────────────────"
    die "gunicorn service failed to start. See logs above for details.
  Common causes:
    - ${ENV_FILE} is missing required variables (DATABASE_URL, SECRET_KEY)
    - ${GUNICORN_BIN} is not installed or not executable
    - PostgreSQL is not running (sudo systemctl start postgresql)
    - Python dependencies are missing (sudo -u deploy pip install --user -r ${BACKEND_DIR}/requirements.txt)
    - Syntax error in the Flask application code"
fi

# =============================================================================
# Step 7: Show recent journal logs for observability — Requirement 10.3
# =============================================================================
info "Step 7: Recent Gunicorn journal logs (last 20 lines)..."
echo ""
echo "  ── journalctl -u gunicorn -n 20 ───────────────────────────────────"
journalctl -u gunicorn -n 20 --no-pager || true
echo "  ───────────────────────────────────────────────────────────────────"
echo ""

# =============================================================================
# Step 8: Verify Gunicorn is listening on 127.0.0.1:5000
# =============================================================================
info "Step 8: Verifying Gunicorn is listening on 127.0.0.1:5000..."

# ss is available on Ubuntu 22.04; fall back to netstat if needed
if command -v ss &>/dev/null; then
    LISTENING=$(ss -tlnp 2>/dev/null | grep ':5000' || echo "")
else
    LISTENING=$(netstat -tlnp 2>/dev/null | grep ':5000' || echo "")
fi

if [[ -n "${LISTENING}" ]]; then
    info "  ✓ Gunicorn is listening on port 5000:"
    echo "    ${LISTENING}"
else
    warn "  Could not confirm Gunicorn is listening on port 5000."
    warn "  This may be a timing issue — check manually with: ss -tlnp | grep 5000"
    warn "  Or: curl -s http://127.0.0.1:5000/api/health"
fi

# =============================================================================
# Step 9: Quick health check against the loopback address
# =============================================================================
info "Step 9: Quick health check — GET http://127.0.0.1:5000/api/health..."

if command -v curl &>/dev/null; then
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
        --max-time 10 \
        http://127.0.0.1:5000/api/health 2>/dev/null || echo "000")

    if [[ "${HTTP_STATUS}" == "200" ]]; then
        info "  ✓ Health check returned HTTP ${HTTP_STATUS} — application is responding."
    elif [[ "${HTTP_STATUS}" == "503" ]]; then
        warn "  Health check returned HTTP 503 — application started but database may be unavailable."
        warn "  Check: sudo systemctl status postgresql"
        warn "  And:   journalctl -u gunicorn -n 20"
    else
        warn "  Health check returned HTTP ${HTTP_STATUS}."
        warn "  The service is active but the application may still be initialising."
        warn "  Retry manually: curl -v http://127.0.0.1:5000/api/health"
    fi
else
    warn "  curl not available — skipping health check."
    warn "  Verify manually: curl http://127.0.0.1:5000/api/health"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo "============================================================"
echo "  Task 4.1 complete — Gunicorn systemd service installed"
echo "============================================================"
echo "  Service file:  ${SERVICE_FILE}"
echo "  Status:        $(systemctl is-active gunicorn)"
echo "  Enabled:       $(systemctl is-enabled gunicorn)"
echo ""
echo "  Useful commands:"
echo "    systemctl status gunicorn"
echo "    journalctl -u gunicorn -f"
echo "    systemctl reload gunicorn   # zero-downtime reload (SIGHUP)"
echo "    systemctl restart gunicorn  # full restart"
echo ""
echo "  NEXT STEPS:"
echo "    4.2  Grant deploy passwordless sudo for systemctl reload gunicorn"
echo "         sudo bash ${APP_DIR}/scripts/vps-setup/10-sudoers-deploy.sh"
echo ""
echo "    5.1  Build the React frontend"
echo "         sudo -u deploy bash ${APP_DIR}/scripts/vps-setup/11-frontend-build.sh"
echo "============================================================"
