"""HubSpot post-import pipeline stage progress (Redis).

Stamped by ``hubspot_pipeline_runner`` while the pipeline runs so Admin /
pipeline status can show how far along matching → rescore is.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

PIPELINE_STAGE_KEY = 'hubspot:post_import_pipeline:stage'
PIPELINE_STAGE_TTL_SECONDS = 6 * 60 * 60

# Ordered stages matching run_post_import_pipeline_sync (exclude terminal `done`
# from progress denominator — it is cleared immediately after stamp).
PIPELINE_STAGES: tuple[str, ...] = (
    'matching',
    'enrich',
    'convert',
    'task_sync',
    'recent_sale_reconcile',
    'signals',
    'rescore',
    'done',
)

_WORK_STAGES: tuple[str, ...] = tuple(s for s in PIPELINE_STAGES if s != 'done')

PIPELINE_STAGE_LABELS: dict[str, str] = {
    'matching': 'Matching HubSpot records',
    'enrich': 'Enriching leads',
    'convert': 'Converting activities',
    'task_sync': 'Syncing HubSpot tasks',
    'recent_sale_reconcile': 'Reconciling recent-sale mail tasks',
    'signals': 'Extracting signals',
    'rescore': 'Rescoring leads',
    'done': 'Complete',
    'idle': 'Idle',
}


def _redis_client():
    import redis

    redis_url = os.environ.get('REDIS_URL') or os.environ.get(
        'CELERY_BROKER_URL', 'redis://localhost:6379/0',
    )
    return redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1)


def _with_redis(fn):
    client = None
    try:
        client = _redis_client()
        return fn(client)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def set_pipeline_stage(stage: str) -> None:
    """Persist the current pipeline stage (best-effort; never raises)."""
    if stage not in PIPELINE_STAGES and stage != 'idle':
        logger.warning('Unknown pipeline stage %r — storing anyway', stage)
    if stage in _WORK_STAGES:
        stage_index = _WORK_STAGES.index(stage) + 1
    elif stage == 'done':
        stage_index = len(_WORK_STAGES)
    else:
        stage_index = 0
    payload = {
        'stage': stage,
        'stage_index': stage_index,
        'stage_total': len(_WORK_STAGES),
        'label': PIPELINE_STAGE_LABELS.get(stage, stage),
        'updated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    }
    try:
        def _set(client):
            client.set(
                PIPELINE_STAGE_KEY,
                json.dumps(payload),
                ex=PIPELINE_STAGE_TTL_SECONDS,
            )
        _with_redis(_set)
    except Exception:
        logger.debug('Failed to stamp pipeline stage %s', stage, exc_info=True)


def clear_pipeline_stage() -> None:
    """Clear stage after pipeline finishes (best-effort)."""
    try:
        _with_redis(lambda client: client.delete(PIPELINE_STAGE_KEY))
    except Exception:
        logger.debug('Failed to clear pipeline stage', exc_info=True)


def get_pipeline_stage() -> dict[str, Any]:
    """Return current stage payload or an idle default."""
    idle = {
        'stage': 'idle',
        'stage_index': 0,
        'stage_total': len(_WORK_STAGES),
        'label': PIPELINE_STAGE_LABELS['idle'],
        'updated_at': None,
    }
    try:
        raw = _with_redis(lambda client: client.get(PIPELINE_STAGE_KEY))
        if not raw:
            return idle
        data = json.loads(raw)
        if not isinstance(data, dict):
            return idle
        stage = data.get('stage') or 'idle'
        return {
            'stage': stage,
            'stage_index': int(data.get('stage_index') or 0),
            'stage_total': int(data.get('stage_total') or len(_WORK_STAGES)),
            'label': data.get('label') or PIPELINE_STAGE_LABELS.get(stage, stage),
            'updated_at': data.get('updated_at'),
        }
    except Exception:
        logger.debug('Failed to read pipeline stage', exc_info=True)
        return idle
