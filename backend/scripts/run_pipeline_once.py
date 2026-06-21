#!/usr/bin/env python3
"""Run the HubSpot post-import pipeline in a detached subprocess.

Used when Celery is unavailable so pipeline work survives Gunicorn worker
reloads (daemon threads do not). Locking is handled inside
run_pipeline_after_imports — do not acquire here to avoid double-lock no-ops.
"""
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main() -> int:
    """Entry point for detached post-import pipeline subprocess execution."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    run_ids = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []

    os.environ.setdefault('FLASK_ENV', 'production')
    os.environ['PIPELINE_SUBPROCESS'] = '1'

    from app import create_app
    from app.services.hubspot_pipeline_runner import run_pipeline_after_imports

    app = create_app('production')
    try:
        run_pipeline_after_imports(app, run_ids or None)
        return 0
    except Exception as exc:
        logger.error("Detached pipeline run failed: %s", exc, exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
