"""Record SPA boot-failure beacons and debounce ops alerts."""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from app import db
from app.models.spa_boot_failure_event import SpaBootFailureEvent

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 8 * 1024
MAX_HREF_LEN = 1024
MAX_REASON_LEN = 128
MAX_UA_LEN = 512
MAX_HINTS = 20
ALERT_COOLDOWN_SECS = 15 * 60
EVENT_RETENTION_DAYS = 14
REDIS_ALERT_KEY = 'spa:boot_failure:last_alert'
FILE_ALERT_STATE = '/home/deploy/logs/spa-boot-failure.last_alert'


def _clip(value: Any, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def sanitize_href(value: Any) -> Optional[str]:
    """Keep URL path context without persisting query strings or fragments."""
    text = _clip(value, MAX_HREF_LEN)
    if text is None:
        return None
    try:
        parts = urlsplit(text)
        sanitized = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    except ValueError:
        sanitized = text.split('?', 1)[0].split('#', 1)[0]
    return _clip(sanitized, MAX_HREF_LEN)


def hash_ip(ip: Optional[str]) -> Optional[str]:
    if not ip:
        return None
    salt = (
        os.environ.get('SPA_BOOT_FAILURE_IP_SALT')
        or os.environ.get('SECRET_KEY')
        or os.environ.get('FLASK_SECRET_KEY')
        or ''
    )
    if not salt:
        logger.error('SPA boot IP salt unset — omitting IP hash')
        return None
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
        'href': sanitize_href(raw.get('href')),
        'reason': _clip(raw.get('reason'), MAX_REASON_LEN) or 'boot_watchdog',
        'user_agent': _clip(raw.get('ua') or raw.get('user_agent'), MAX_UA_LEN),
        'asset_hints': clean_hints or None,
    }


def _prune_old_events() -> None:
    """Best-effort retention so anonymous beacons cannot grow unbounded."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=EVENT_RETENTION_DAYS)
        (
            SpaBootFailureEvent.query
            .filter(SpaBootFailureEvent.created_at < cutoff)
            .delete(synchronize_session=False)
        )
    except Exception as exc:
        logger.warning('spa boot event prune failed: %s', exc)


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
    _prune_old_events()
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


def _state_timestamp(raw: str) -> int | None:
    token = (raw or '').split(':', 1)[0].strip()
    if not token.isdigit():
        return None
    return int(token)


def _clear_redis_reservation(client: Any, token: str) -> None:
    try:
        if client.get(REDIS_ALERT_KEY) == token.encode('utf-8'):
            client.delete(REDIS_ALERT_KEY)
    except Exception as exc:
        logger.warning('spa boot alert redis debounce clear failed: %s', exc)


def reserve_alert() -> dict[str, str] | None:
    """Claim one alert slot per cooldown window (Redis preferred, file fallback)."""
    token = uuid.uuid4().hex
    r = _redis_client()
    if r is not None:
        try:
            # SET NX EX — first caller in window wins.
            ok = r.set(REDIS_ALERT_KEY, token, nx=True, ex=ALERT_COOLDOWN_SECS)
            if ok:
                return {'backend': 'redis', 'token': token}
            return None
        except Exception as exc:
            logger.warning('spa boot alert redis debounce failed: %s', exc)
            _clear_redis_reservation(r, token)
            return None

    lock_path = f'{FILE_ALERT_STATE}.lock'
    lock_fd: int | None = None
    try:
        os.makedirs(os.path.dirname(FILE_ALERT_STATE), exist_ok=True)
        now = int(time.time())
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if now - int(os.path.getmtime(lock_path)) > 30:
                    os.unlink(lock_path)
                    lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                else:
                    return None
            except Exception:
                return None

        raw = ''
        try:
            with open(FILE_ALERT_STATE, 'r', encoding='utf-8') as fh:
                raw = fh.read().strip()
        except FileNotFoundError:
            raw = ''
        last = _state_timestamp(raw)
        if last is not None and now - last < ALERT_COOLDOWN_SECS:
            return None

        tmp = f'{FILE_ALERT_STATE}.{now}.{os.getpid()}.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(f'{now}:{token}')
        os.replace(tmp, FILE_ALERT_STATE)
        return {'backend': 'file', 'token': token}
    except Exception as exc:
        logger.warning('spa boot alert file debounce failed: %s', exc)
        return {'backend': 'none', 'token': token}
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
            try:
                os.unlink(lock_path)
            except OSError:
                pass


def should_send_alert() -> bool:
    """Return True once per ALERT_COOLDOWN_SECS (Redis preferred, file fallback)."""
    return reserve_alert() is not None


def clear_alert_debounce(reservation: dict[str, str] | None) -> None:
    """Best-effort rollback when alert delivery failed after reserving cooldown."""
    reservation = reservation or {}
    backend = reservation.get('backend')
    token = reservation.get('token')
    if backend == 'redis' and token:
        r = _redis_client()
        if r is None:
            return
        _clear_redis_reservation(r, token)
    elif backend == 'file' and token:
        try:
            with open(FILE_ALERT_STATE, 'r', encoding='utf-8') as fh:
                raw = fh.read().strip()
            if raw.endswith(f':{token}'):
                os.unlink(FILE_ALERT_STATE)
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.warning('spa boot alert file debounce clear failed: %s', exc)


def send_ops_alert_sync(event_id: int, href: Optional[str], reason: Optional[str]) -> None:
    reservation = reserve_alert()
    if reservation is None:
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
        clear_alert_debounce(reservation)
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
if [ "${OPS_ALERT_DELIVERY_FAILED:-0}" = "1" ]; then
  exit 1
fi
'''
    env = os.environ.copy()
    env['BB_BACKUP_CONF'] = backup_conf
    env['BB_OPS_ALERT'] = ops_alert
    env['BB_ALERT_SUBJECT'] = subject
    env['BB_ALERT_BODY'] = body
    try:
        result = subprocess.run(
            ['bash', '-c', script],
            check=False,
            timeout=20,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0 or 'OPS_ALERT_DELIVERY_FAILED=1' in (
            (result.stdout or '') + (result.stderr or '')
        ):
            logger.warning(
                'spa boot alert delivery failed rc=%s stderr=%s',
                result.returncode,
                (result.stderr or '').strip()[:500],
            )
            clear_alert_debounce(reservation)
    except Exception as exc:
        logger.warning('spa boot alert subprocess failed: %s', exc)
        clear_alert_debounce(reservation)


def enqueue_or_alert(event: SpaBootFailureEvent) -> None:
    """Enqueue Celery alert without importing celery_worker (avoids SystemExit)."""
    try:
        from celery import current_app as celery_app  # noqa: PLC0415
        celery_app.send_task(
            'ops.alert_spa_boot_failure',
            args=[event.id, event.href, event.reason],
        )
    except SystemExit as exc:
        logger.warning('spa boot celery dispatch SystemExit, alerting sync: %s', exc)
        send_ops_alert_sync(event.id, event.href, event.reason)
    except Exception as exc:
        logger.warning('spa boot celery enqueue failed, alerting sync: %s', exc)
        send_ops_alert_sync(event.id, event.href, event.reason)
