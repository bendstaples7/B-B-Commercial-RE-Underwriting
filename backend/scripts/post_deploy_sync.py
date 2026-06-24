#!/usr/bin/env python3
"""Post-deploy HubSpot sync — dispatch on the VPS after every deploy.

Queues the post-import pipeline (matching → enrich → activities → signals →
rescore) via Celery when workers are live, otherwise a detached subprocess.
Does not block the deploy SSH session — sync runs asynchronously.

Usage (from backend/ on the VPS):
    FLASK_ENV=production python3.11 scripts/post_deploy_sync.py

Exits 0 when dispatch succeeds. Safe to run when HubSpot is not configured
(exits 0 with a skip message).
"""
from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def dispatch_post_deploy_sync(app) -> str:
    """Queue post-import pipeline work without blocking. Returns dispatch mode."""
    from app.models.hubspot_config import HubSpotConfig
    from app.services.hubspot_pipeline_runner import (
        count_dangling_confirmed_lead_matches,
        dispatch_post_import_pipeline,
    )

    with app.app_context():
        if HubSpotConfig.query.first() is None:
            logger.info('HubSpot not configured — skipping post-deploy sync')
            return 'skipped'

        dangling = count_dangling_confirmed_lead_matches()
        logger.info(
            'Post-deploy sync dispatch (dangling confirmed lead matches: %d)',
            dangling,
        )

        mode = dispatch_post_import_pipeline(app, run_ids=None)
        logger.info('Post-import pipeline dispatched via %s', mode)

        try:
            from celery import current_app as celery_app  # noqa: PLC0415

            celery_app.send_task('hubspot.scheduled_engagement_sync')
            logger.info('Queued engagement sync for fresh HubSpot data')
        except Exception as exc:
            logger.warning(
                'Celery unavailable — skipped engagement fetch (%s)',
                exc,
            )

        return mode


def main() -> int:
    """Create app, dispatch post-deploy sync, and return process exit code."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    os.environ.setdefault('FLASK_ENV', 'production')

    from app import create_app

    app = create_app('production')
    try:
        mode = dispatch_post_deploy_sync(app)
    except Exception as exc:
        logger.error('Post-deploy sync dispatch failed: %s', exc, exc_info=True)
        return 1

    if mode in ('celery', 'subprocess', 'skipped'):
        return 0

    logger.error('Unexpected dispatch mode: %s', mode)
    return 1


if __name__ == '__main__':
    sys.exit(main())
