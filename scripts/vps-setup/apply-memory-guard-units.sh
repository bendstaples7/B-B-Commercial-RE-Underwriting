#!/usr/bin/env bash
# =============================================================================
# apply-memory-guard-units.sh
# Idempotently ensure Celery/Gunicorn systemd units have OOM/memory guards.
# Run as root (or via sudo -n /usr/local/sbin/apply-memory-guard-units).
#
# Does NOT restart services — deploy.sh restarts Celery after this runs.
# =============================================================================

set -euo pipefail

APP_DIR="${APP_DIR:-/home/deploy/app}"
VPS_SETUP="${APP_DIR}/scripts/vps-setup"
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
    grep -qF -- 'MemoryMax=900M' "${CELERY_UNIT}" || return 0
    grep -qF -- 'OOMScoreAdjust=500' "${CELERY_UNIT}" || return 0
    return 1
}

if need_celery_rewrite; then
    echo "Applying Celery memory-guard unit via 09b-celery-service.sh..."
    # 09b rewrites units and restarts celery/beat — acceptable when guards missing.
    bash "${VPS_SETUP}/09b-celery-service.sh"
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
