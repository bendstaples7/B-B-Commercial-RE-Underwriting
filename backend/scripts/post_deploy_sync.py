#!/usr/bin/env python3
"""Post-deploy HubSpot sync — dispatch on the VPS after every deploy.

Queues tiered post-deploy work (skip, rescore-only, or full pipeline) via
Celery when workers are live, otherwise a detached subprocess. Does not
block the deploy SSH session — sync runs asynchronously.

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
    """Queue tiered post-deploy sync without blocking. Returns dispatch mode."""
    from app.models.hubspot_config import HubSpotConfig
    from app.services.deploy_sync_policy import (
        load_changed_paths_for_deploy,
        resolve_deploy_sync_from_manifest,
        should_upgrade_dangling_to_full_pipeline,
    )
    from app.services.hubspot_pipeline_runner import (
        count_dangling_confirmed_lead_matches,
        dispatch_tiered_post_deploy_sync,
    )

    paths_file = os.environ.get('DEPLOY_CHANGED_PATHS_FILE')

    with app.app_context():
        if HubSpotConfig.query.first() is None:
            logger.info('HubSpot not configured — skipping post-deploy sync')
            return 'skipped'

        sync_mode = resolve_deploy_sync_from_manifest(paths_file)
        changed_paths, _unknown = load_changed_paths_for_deploy(paths_file)
        logger.info(
            'Post-deploy sync: mode=%s changed_paths=%d',
            sync_mode,
            len(changed_paths),
        )

        dangling = count_dangling_confirmed_lead_matches()
        if dangling > 0 and sync_mode in ('skip', 'rescore_only'):
            if should_upgrade_dangling_to_full_pipeline():
                sync_mode = 'full_pipeline'
                logger.info(
                    'Post-deploy sync upgraded to full_pipeline '
                    '(dangling confirmed lead matches: %d)',
                    dangling,
                )
            else:
                logger.info(
                    'Dangling confirmed lead matches (%d) — deferring full pipeline '
                    '(recent pipeline within cooldown)',
                    dangling,
                )
        elif dangling > 0:
            logger.info(
                'Post-deploy sync (dangling confirmed lead matches: %d)',
                dangling,
            )

        mode = dispatch_tiered_post_deploy_sync(app, sync_mode)
        logger.info('Post-deploy sync dispatched via %s (mode=%s)', mode, sync_mode)

        if sync_mode == 'skip':
            logger.info(
                'Skipped engagement sync — hourly hubspot-scheduled-engagement-sync covers catch-up',
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
