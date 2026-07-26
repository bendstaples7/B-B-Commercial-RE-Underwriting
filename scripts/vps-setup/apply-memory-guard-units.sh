#!/usr/bin/env bash
# =============================================================================
# apply-memory-guard-units.sh
# Idempotently ensure Celery/Gunicorn systemd units have OOM/memory guards.
# Run as root (or via sudo -n /usr/local/sbin/apply-memory-guard-units).
#
# Installed to /usr/local/sbin (root:root) by 11-sudoers-deploy.sh so Deploy
# never executes checkout-controlled scripts as root. Unit content is inlined
# here — do NOT bash scripts under APP_DIR from this helper.
#
# Does NOT restart services — deploy.sh restarts Celery after this runs.
# =============================================================================

set -euo pipefail

CELERY_UNIT="/etc/systemd/system/celery.service"
GUNICORN_DROPIN_DIR="/etc/systemd/system/gunicorn.service.d"
GUNICORN_DROPIN="${GUNICORN_DROPIN_DIR}/oom.conf"
CHANGED=0

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: run as root (or via passwordless sudo wrapper)"
    exit 1
fi

need_celery_rewrite() {
    [[ -f "${CELERY_UNIT}" ]] || return 0
    grep -qF -- '--max-tasks-per-child=50' "${CELERY_UNIT}" || return 0
    grep -qF -- '--max-memory-per-child=400000' "${CELERY_UNIT}" || return 0
    grep -qF -- 'MemoryHigh=700M' "${CELERY_UNIT}" || return 0
    grep -qF -- 'MemoryMax=900M' "${CELERY_UNIT}" || return 0
    grep -qF -- 'OOMScoreAdjust=500' "${CELERY_UNIT}" || return 0
    return 1
}

write_celery_unit() {
    # Keep in sync with the celery.service heredoc in 09b (memory guards + recycle).
    # Beat is left untouched.
    cat > "${CELERY_UNIT}" <<'EOF'
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
# Recycle the prefork child before RSS can exhaust a small VPS.
# max-memory-per-child is KiB (400000 ≈ 390 MiB).
ExecStart=/home/deploy/.local/bin/celery -A celery_worker.celery worker \
    --loglevel=info --concurrency=1 --pool=prefork \
    --max-tasks-per-child=50 \
    --max-memory-per-child=400000
# Prefer killing this worker over Gunicorn/Postgres under host OOM.
OOMScoreAdjust=500
MemoryAccounting=yes
MemoryHigh=700M
MemoryMax=900M
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
    chmod 644 "${CELERY_UNIT}"
}

if need_celery_rewrite; then
    echo "Writing Celery memory-guard unit (inline; no checkout scripts)..."
    write_celery_unit
    CHANGED=1
else
    echo "Celery unit already has memory guards."
fi

mkdir -p "${GUNICORN_DROPIN_DIR}"
DESIRED_GUNICORN=$'[Service]\nOOMScoreAdjust=-500\n'
if [[ ! -f "${GUNICORN_DROPIN}" ]] || ! grep -qF 'OOMScoreAdjust=-500' "${GUNICORN_DROPIN}"; then
    printf '%s' "${DESIRED_GUNICORN}" > "${GUNICORN_DROPIN}"
    CHANGED=1
    echo "Wrote ${GUNICORN_DROPIN}"
fi

# Prefer Postgres surviving Celery OOM when the cluster unit exists.
if systemctl cat postgresql@15-main.service &>/dev/null; then
    PG_DROPIN_DIR="/etc/systemd/system/postgresql@15-main.service.d"
    PG_DROPIN="${PG_DROPIN_DIR}/oom.conf"
    mkdir -p "${PG_DROPIN_DIR}"
    if [[ ! -f "${PG_DROPIN}" ]] || ! grep -qF 'OOMScoreAdjust=-800' "${PG_DROPIN}"; then
        printf '%s\n' '[Service]' 'OOMScoreAdjust=-800' > "${PG_DROPIN}"
        CHANGED=1
        echo "Wrote ${PG_DROPIN}"
    fi
fi

if [[ "${CHANGED}" -eq 1 ]]; then
    systemctl daemon-reload
    echo "systemd daemon reloaded."
fi

# Verify Celery MemoryMax is finite (not infinity).
MEM_MAX="$(systemctl show celery -p MemoryMax --value 2>/dev/null || echo "")"
if [[ -z "${MEM_MAX}" || "${MEM_MAX}" == "infinity" ]]; then
    echo "ERROR: celery MemoryMax is '${MEM_MAX:-unset}' — expected ~900M"
    exit 1
fi
echo "OK: celery MemoryMax=${MEM_MAX} OOMScoreAdjust=$(systemctl show celery -p OOMScoreAdjust --value)"
exit 0
