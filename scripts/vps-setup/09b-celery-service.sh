#!/usr/bin/env bash
# =============================================================================
# 09b-celery-service.sh
# Install Celery worker + Celery Beat systemd units for async HubSpot sync.
#
# Run ON THE VPS as root (once, or idempotently):
#   sudo bash /home/deploy/app/scripts/vps-setup/09b-celery-service.sh
#
# Prerequisites:
#   - 03b-install-redis.sh (redis-server active)
#   - 09-gunicorn-service.sh (backend .env exists)
#   - pip install --user -r backend/requirements.txt as deploy user
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash $0"

BACKEND_DIR="/home/deploy/app/backend"
ENV_FILE="${BACKEND_DIR}/.env"
CELERY_BIN="/home/deploy/.local/bin/celery"

[[ -f "${ENV_FILE}" ]] || die "Missing ${ENV_FILE} — run 07-create-env-file.sh first"
[[ -x "${CELERY_BIN}" ]] || die "Missing ${CELERY_BIN} — run: sudo -u deploy pip install --user -r ${BACKEND_DIR}/requirements.txt"

systemctl is-active --quiet redis-server || die "redis-server is not active — run 03b-install-redis.sh first"

info "Writing celery.service..."
cat > /etc/systemd/system/celery.service <<'EOF'
[Unit]
Description=Celery worker — B&B Real Estate Analyzer
After=network.target postgresql.service redis-server.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/app/backend
EnvironmentFile=/home/deploy/app/backend/.env
Environment=FLASK_ENV=production
Environment=CELERY_WORKER_RUNNING=1
ExecStart=/home/deploy/.local/bin/celery -A celery_worker.celery worker \
    --loglevel=info --concurrency=1 --pool=prefork
# Always restart after unexpected exits (crash, OOM, SIGHUP). systemctl stop
# during deploy still leaves the unit inactive until an explicit start/restart.
Restart=always
RestartSec=10s
KillSignal=SIGTERM
TimeoutStopSec=120
StandardOutput=journal
StandardError=journal
SyslogIdentifier=celery

[Install]
WantedBy=multi-user.target
EOF

info "Writing celery-beat.service..."
cat > /etc/systemd/system/celery-beat.service <<'EOF'
[Unit]
Description=Celery Beat — B&B Real Estate Analyzer
After=network.target redis-server.service celery.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
User=deploy
Group=deploy
WorkingDirectory=/home/deploy/app/backend
EnvironmentFile=/home/deploy/app/backend/.env
Environment=FLASK_ENV=production
Environment=CELERY_WORKER_RUNNING=1
ExecStart=/home/deploy/.local/bin/celery -A celery_worker.celery beat \
    --loglevel=info --pidfile=/home/deploy/celerybeat.pid \
    --schedule=/home/deploy/celerybeat-schedule
Restart=always
RestartSec=10s
KillSignal=SIGTERM
TimeoutStopSec=60
StandardOutput=journal
StandardError=journal
SyslogIdentifier=celery-beat

[Install]
WantedBy=multi-user.target
EOF

chmod 644 /etc/systemd/system/celery.service /etc/systemd/system/celery-beat.service
systemctl daemon-reload

info "Enabling and starting Celery worker + beat..."
systemctl enable celery celery-beat
systemctl restart celery
sleep 2
systemctl restart celery-beat

for svc in celery celery-beat; do
    if systemctl is-active --quiet "${svc}"; then
        info "  ${svc}: active"
    else
        warn "  ${svc}: NOT active — journalctl -u ${svc} -n 30"
        systemctl status "${svc}" --no-pager -l || true
        die "${svc} failed to start"
    fi
done

info "09b complete — Celery worker and beat are running"
