#!/usr/bin/env python3
"""Post-deploy HubSpot sync — run on the VPS after every deploy.

Re-runs the post-import pipeline (matching → enrich → activities → signals →
rescore) so code fixes for HubSpot sync take effect on existing data without
manual imports or SSH one-liners.

Usage (from backend/ on the VPS):
    FLASK_ENV=production python3.11 scripts/post_deploy_sync.py

Exits 0 on success, 1 on failure. Safe to run when HubSpot is not configured
(exits 0 with a skip message).
"""
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main() -> int:
    # Ensure backend/ is on sys.path when invoked as scripts/post_deploy_sync.py
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    os.environ.setdefault('FLASK_ENV', 'production')

    from app import create_app
    from app.models.hubspot_config import HubSpotConfig
    from app.services.hubspot_pipeline_runner import (
        count_dangling_confirmed_lead_matches,
        run_post_import_pipeline_sync,
    )

    app = create_app('production')
    with app.app_context():
        if HubSpotConfig.query.first() is None:
            logger.info("HubSpot not configured — skipping post-deploy sync")
            return 0

        dangling = count_dangling_confirmed_lead_matches()
        logger.info(
            "Post-deploy sync starting (dangling confirmed lead matches: %d)",
            dangling,
        )

        try:
            run_post_import_pipeline_sync()
        except Exception as exc:
            logger.error("Post-deploy sync failed: %s", exc, exc_info=True)
            return 1

        remaining = count_dangling_confirmed_lead_matches()
        logger.info(
            "Post-deploy sync complete (dangling matches remaining: %d)",
            remaining,
        )

        # Pull fresh engagements from HubSpot when Celery is running (hourly beat
        # handles ongoing sync; this catches up immediately after deploy).
        try:
            from celery import current_app as celery_app  # noqa: PLC0415

            celery_app.send_task('hubspot.scheduled_engagement_sync')
            logger.info("Queued engagement sync for fresh HubSpot data")
        except Exception as exc:
            logger.info(
                "Celery unavailable — skipped engagement fetch (%s). "
                "Existing DB data was still re-processed by the pipeline above.",
                exc,
            )

        return 0


if __name__ == '__main__':
    sys.exit(main())
