"""Record SPA boot-failure beacons and debounce ops alerts."""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
from datetime import datetime
from typing import Any, Optional

from app import db
from app.models.spa_boot_failure_event import SpaBootFailureEvent

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 8 * 1024
MAX_HREF_LEN = 1024
MAX_REASON_LEN = 128
MAX_UA_LEN = 512
MAX_HINTS = 20
ALERT_COOLDOWN_SECS = 15 * 60
REDIS_ALERT_KEY = 'spa:boot_failure:last_alert'
FILE_ALERT_STATE = '/home/deploy/logs/spa-boot-failure.last_alert'


def _clip(value: Any, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def hash_ip(ip: Optional[str]) -> Optional[str]:
    if not ip:
        return None
    salt = os.environ.get('SPA_BOOT_FAILURE_IP_SALT', 'bb-spa-boot')
    return hashlib.sha256(f'{salt}:{ip}'.encode('utf-8')).hexdigest()


def normalize_payload(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    hints = raw.get('assetHints') or raw.get('asset_hints') or []
    if not isinstance(hints, list):
        hints = []
    clean_hints = []
    for item in hints[:MAX_HINTS]:
        if isinstance(item, str):
            clean_hints.append(item[:256])
        elif isinstance(item, dict):
            clean_hints.append({
                'name': _clip(item.get('name'), 256),
                'status': item.get('status'),
            })
    return {
        'href': _clip(raw.get('href'), MAX_HREF_LEN),
        'reason': _clip(raw.get('reason'), MAX_REASON_LEN) or 'boot_watchdog',
        'user_agent': _clip(raw.get('ua') or raw.get('user_agent'), MAX_UA_LEN),
        'asset_hints': clean_hints or None,
    }


def record_event(*, payload: dict, ip: Optional[str], user_agent_header: Optional[str]) -> SpaBootFailureEvent:
    data = normalize_payload(payload)
    ua = data.get('user_agent') or _clip(user_agent_header, MAX_UA_LEN)
    event = SpaBootFailureEvent(
        created_at=datetime.utcnow(),
        ip_hash=hash_ip(ip),
        href=data.get('href'),
        reason=data.get('reason'),
        user_agent=ua,
        asset_hints=data.get('asset_hints'),
    )
    db.session.add(event)
    db.session.commit()
    return event


def _redis_client():
    try:
        import redis
        url = os.environ.get('REDIS_URL') or os.environ.get('CELERY_BROKER_URL', '')
        if not url:
            return None
        return redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
    except Exception:
        return None


def should_send_alert() -> bool:
    """Return True once per ALERT_COOLDOWN_SECS (Redis preferred, file fallback)."""
    r = _redis_client()
    if r is not None:
        try:
            # SET NX EX — first caller in window wins.
            ok = r.set(REDIS_ALERT_KEY, str(int(time.time())), nx=True, ex=ALERT_COOLDOWN_SECS)
            return bool(ok)
        except Exception as exc:
            logger.warning('spa boot alert redis debounce failed: %s', exc)

    try:
        os.makedirs(os.path.dirname(FILE_ALERT_STATE), exist_ok=True)
        now = int(time.time())
        if os.path.isfile(FILE_ALERT_STATE):
            with open(FILE_ALERT_STATE, 'r', encoding='utf-8') as fh:
                raw = fh.read().strip()
            if raw.isdigit() and now - int(raw) < ALERT_COOLDOWN_SECS:
                return False
        with open(FILE_ALERT_STATE, 'w', encoding='utf-8') as fh:
            fh.write(str(now))
        return True
    except Exception as exc:
        logger.warning('spa boot alert file debounce failed: %s', exc)
        return True


def send_ops_alert_sync(event_id: int, href: Optional[str], reason: Optional[str]) -> None:
    if not should_send_alert():
        logger.info('spa boot failure alert suppressed (cooldown) event_id=%s', event_id)
        return

    subject = 'SPA boot failure (blank app)'
    body = (
        f'SPA boot watchdog reported a blank app load.\n'
        f'event_id={event_id}\n'
        f'reason={reason or "unknown"}\n'
        f'href={href or "unknown"}\n'
        f'Check nginx asset perms / last Deploy / spa-uptime-canary logs.\n'
    )
    ops_alert = '/home/deploy/ops-alert.sh'
    backup_conf = '/home/deploy/backup.conf'
    if not os.path.isfile(ops_alert):
        logger.warning('spa boot alert: %s missing — %s', ops_alert, body.replace('\n', ' | '))
        return
    script = '''
set -euo pipefail
if [ -f "$BB_BACKUP_CONF" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$BB_BACKUP_CONF"
  set +a
fi
LOG_FILE="${LOG_FILE:-/home/deploy/logs/ops-alert.log}"
ALERT_SUBJECT_PREFIX="[Ops Alert]"
# shellcheck source=/dev/null
source "$BB_OPS_ALERT"
send_alert "$BB_ALERT_SUBJECT" "$BB_ALERT_BODY"
'''
    env = os.environ.copy()
    env['BB_BACKUP_CONF'] = backup_conf
    env['BB_OPS_ALERT'] = ops_alert
    env['BB_ALERT_SUBJECT'] = subject
    env['BB_ALERT_BODY'] = body
    try:
        subprocess.run(
            ['bash', '-c', script],
            check=False,
            timeout=20,
            capture_output=True,
            text=True,
            env=env,
        )
    except Exception as exc:
        logger.warning('spa boot alert subprocess failed: %s', exc)


def enqueue_or_alert(event: SpaBootFailureEvent) -> None:
    try:
        from celery_worker import alert_spa_boot_failure
        alert_spa_boot_failure.delay(event.id, event.href, event.reason)
    except Exception as exc:
        logger.warning('spa boot celery enqueue failed, alerting sync: %s', exc)
        send_ops_alert_sync(event.id, event.href, event.reason)
