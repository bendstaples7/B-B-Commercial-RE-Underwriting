#!/usr/bin/env python3
"""Run the HubSpot post-import pipeline in a detached subprocess.

Used when Celery is unavailable so pipeline work survives Gunicorn worker
reloads (daemon threads do not).
"""
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main() -> int:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    run_ids = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []

    os.environ.setdefault('FLASK_ENV', 'production')

    from app import create_app
    from app.services.hubspot_pipeline_runner import (
        release_pipeline_lock,
        run_pipeline_after_imports,
        try_acquire_pipeline_lock,
    )

    app = create_app('production')
    if not try_acquire_pipeline_lock():
        logger.info("Pipeline already running elsewhere — skipping duplicate subprocess run")
        return 0

    try:
        run_pipeline_after_imports(app, run_ids or None)
        return 0
    except Exception as exc:
        logger.error("Detached pipeline run failed: %s", exc, exc_info=True)
        return 1
    finally:
        with app.app_context():
            release_pipeline_lock()


if __name__ == '__main__':
    sys.exit(main())
