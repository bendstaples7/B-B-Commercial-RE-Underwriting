"""Admin snapshot of Celery work + HubSpot pipeline + in-flight mail campaigns."""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# How many broker messages to decode for the "up next" list.
_QUEUED_PEEK_LIMIT = 25


def _normalize_task_entry(raw: dict[str, Any], *, state: str) -> dict[str, Any]:
    name = raw.get('name') or raw.get('task') or 'unknown'
    args = raw.get('args') or []
    kwargs = raw.get('kwargs') or {}
    return {
        'id': raw.get('id') or raw.get('delivery_info', {}).get('correlation_id'),
        'name': name,
        'args': args if isinstance(args, list) else list(args) if args else [],
        'kwargs': kwargs if isinstance(kwargs, dict) else {},
        'state': state,
        'worker': raw.get('_worker'),
        'time_start': raw.get('time_start'),
        'is_mail_submit': name == 'open_letter.submit_campaign',
        'is_hubspot_pipeline': name == 'hubspot.post_import_pipeline',
    }


def _flatten_inspect(mapping: dict[str, list] | None, state: str) -> list[dict[str, Any]]:
    if not mapping:
        return []
    out: list[dict[str, Any]] = []
    for worker, tasks in mapping.items():
        for task in tasks or []:
            if not isinstance(task, dict):
                continue
            entry = dict(task)
            entry['_worker'] = worker
            out.append(_normalize_task_entry(entry, state=state))
    return out


def _peek_broker_queue(limit: int = _QUEUED_PEEK_LIMIT) -> tuple[int, list[dict[str, Any]]]:
    """Return (depth, decoded task summaries) from the default Celery Redis list."""
    try:
        import redis
    except ImportError:
        return 0, []

    redis_url = os.environ.get('REDIS_URL') or os.environ.get(
        'CELERY_BROKER_URL', 'redis://localhost:6379/0',
    )
    queue_name = os.environ.get('CELERY_DEFAULT_QUEUE', 'celery')
    client = None
    try:
        client = redis.from_url(
            redis_url,
            decode_responses=False,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        depth = int(client.llen(queue_name) or 0)
        raw_items = client.lrange(queue_name, 0, max(0, limit - 1)) or []
    except Exception:
        logger.debug('Broker peek failed', exc_info=True)
        return 0, []
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    decoded: list[dict[str, Any]] = []
    for raw in raw_items:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode('utf-8', errors='replace')
            msg = json.loads(raw)
            headers = msg.get('headers') or {}
            name = headers.get('task') or 'unknown'
            body = msg.get('body')
            args: list = []
            kwargs: dict = {}
            if isinstance(body, str):
                try:
                    payload = json.loads(base64.b64decode(body))
                    if isinstance(payload, list) and len(payload) >= 2:
                        args = payload[0] if isinstance(payload[0], list) else []
                        kwargs = payload[1] if isinstance(payload[1], dict) else {}
                except Exception:
                    pass
            decoded.append(_normalize_task_entry(
                {
                    'id': headers.get('id'),
                    'name': name,
                    'args': args,
                    'kwargs': kwargs,
                },
                state='queued',
            ))
        except Exception:
            continue
    return depth, decoded


def _mail_campaigns_in_flight(
    celery_tasks: list[dict[str, Any]] | None = None,
    *,
    celery_inspect_ok: bool = False,
    queue_depth: int = 0,
) -> list[dict[str, Any]]:
    from app.models.mail_campaign import MailCampaign

    in_flight = ('pending', 'submitted', 'processing')
    rows = (
        MailCampaign.query
        .filter(MailCampaign.status.in_(in_flight))
        .order_by(MailCampaign.created_at.asc())
        .limit(20)
        .all()
    )
    submit_campaign_ids: set[int] = set()
    for task in celery_tasks or []:
        if not task.get('is_mail_submit'):
            continue
        args = task.get('args') or []
        if args:
            try:
                submit_campaign_ids.add(int(args[0]))
            except (TypeError, ValueError):
                pass
        kwargs = task.get('kwargs') or {}
        if 'campaign_id' in kwargs:
            try:
                submit_campaign_ids.add(int(kwargs['campaign_id']))
            except (TypeError, ValueError):
                pass

    return [
        {
            'id': c.id,
            'status': c.status,
            'lead_count': c.lead_count,
            'olc_order_id': c.olc_order_id,
            'created_at': (
                c.created_at.isoformat() + 'Z'
                if c.created_at and c.created_at.tzinfo is None
                else (c.created_at.isoformat().replace('+00:00', 'Z') if c.created_at else None)
            ),
            'created_by': c.created_by,
            'error_message': c.error_message,
            # Only trust "orphan" when Celery inspect answered; otherwise a live
            # submit may simply be missing from a partial broker peek.
            'orphan': (
                celery_inspect_ok
                and queue_depth <= _QUEUED_PEEK_LIMIT
                and c.id not in submit_campaign_ids
                and not c.olc_order_id
            ),
        }
        for c in rows
    ]


def get_background_jobs_snapshot() -> dict[str, Any]:
    """Build the Admin Background Jobs payload."""
    from app.services.hubspot_pipeline_progress import get_pipeline_stage

    active: list[dict[str, Any]] = []
    reserved: list[dict[str, Any]] = []
    scheduled: list[dict[str, Any]] = []
    inspect_ok = False
    try:
        from celery import current_app as celery_app

        # Keep per-call timeout short so a silent broker does not stall the
        # admin poll (~5s) for a full 3s of serial waits.
        inspect = celery_app.control.inspect(timeout=0.5)
        if inspect is not None:
            active_map = inspect.active()
            reserved_map = inspect.reserved()
            scheduled_map = inspect.scheduled()
            # Celery returns None when no workers replied — that is NOT success.
            if active_map is not None or reserved_map is not None or scheduled_map is not None:
                inspect_ok = True
            active = _flatten_inspect(active_map, 'active')
            reserved = _flatten_inspect(reserved_map, 'reserved')
            scheduled_raw = scheduled_map or {}
            flat_sched: dict[str, list] = {}
            for worker, items in scheduled_raw.items():
                flat_sched[worker] = []
                for item in items or []:
                    if not isinstance(item, dict):
                        continue
                    req = item.get('request') or item
                    if isinstance(req, dict):
                        flat_sched[worker].append(req)
            scheduled = _flatten_inspect(flat_sched, 'scheduled')
    except Exception:
        logger.warning('Celery inspect failed for background-jobs', exc_info=True)
        inspect_ok = False

    queue_depth, queued = _peek_broker_queue()
    pipeline = get_pipeline_stage()
    celery_tasks = active + reserved + scheduled + queued
    mail = _mail_campaigns_in_flight(
        celery_tasks,
        celery_inspect_ok=inspect_ok,
        queue_depth=queue_depth,
    )

    pipeline_running = any(t['is_hubspot_pipeline'] for t in active) or (
        pipeline.get('stage') not in (None, 'idle', 'done')
    )

    return {
        'celery_inspect_ok': inspect_ok,
        'active': active,
        'reserved': reserved,
        'scheduled': scheduled,
        'queued': queued,
        'queue_depth': queue_depth,
        'hubspot_pipeline': {
            **pipeline,
            'pipeline_running': pipeline_running,
        },
        'mail_campaigns_in_flight': mail,
        'busy': bool(
            active or reserved or scheduled or queued or mail or pipeline_running
        ),
    }
