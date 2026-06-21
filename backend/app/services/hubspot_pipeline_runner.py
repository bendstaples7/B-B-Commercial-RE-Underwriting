"""Shared HubSpot post-import pipeline runner.

Runs matching → enrich → convert activities → extract signals → rescore.
Used by import triggers, manual pipeline runs, deploy hooks, Celery tasks,
and startup recovery when dangling matches are detected.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Import-run statuses that mean the batch is finished (success, partial, or failed).
_TERMINAL_IMPORT_STATUSES = frozenset({'success', 'partial', 'failed'})

# PostgreSQL advisory lock key — prevents concurrent pipeline runs across workers.
_PIPELINE_ADVISORY_LOCK_KEY = 913372001

_in_process_pipeline_lock = threading.Lock()
_advisory_lock_held = False


def run_post_import_pipeline_sync() -> None:
    """Run the full post-import pipeline synchronously in the current process."""
    from app.tasks.hubspot_tasks import (
        run_convert_hubspot_activities,
        run_enrich_leads_from_hubspot,
        run_extract_hubspot_signals,
        run_hubspot_matching,
        run_rescore_leads_after_import,
    )

    run_hubspot_matching()
    logger.info("Post-import pipeline: matching complete")

    run_enrich_leads_from_hubspot()
    logger.info("Post-import pipeline: lead enrichment complete")

    run_convert_hubspot_activities()
    logger.info("Post-import pipeline: activity conversion complete")

    run_extract_hubspot_signals()
    logger.info("Post-import pipeline: signal extraction complete")

    run_rescore_leads_after_import()
    logger.info("Post-import pipeline: rescore complete")


def _wait_for_import_runs(run_ids: list[int], max_wait: int = 3600, poll_interval: int = 15) -> None:
    """Block until all import runs in *run_ids* reach a terminal status."""
    from app import db
    from app.models.hubspot_import_run import HubSpotImportRun

    elapsed = 0
    while elapsed < max_wait:
        db.session.rollback()
        db.session.expire_all()
        runs = HubSpotImportRun.query.filter(HubSpotImportRun.id.in_(run_ids)).all()
        if runs and all(r.status in _TERMINAL_IMPORT_STATUSES for r in runs):
            logger.info("Pipeline: all import runs complete — starting pipeline")
            return
        logger.info("Pipeline: waiting for import runs %s (%ds elapsed)…", run_ids, elapsed)
        time.sleep(poll_interval)
        elapsed += poll_interval

    logger.warning(
        "Pipeline: timed out waiting for runs %s — running pipeline anyway",
        run_ids,
    )


def try_acquire_pipeline_lock() -> bool:
    """Acquire a cross-process lock so only one pipeline run executes at a time."""
    global _advisory_lock_held

    if not _in_process_pipeline_lock.acquire(blocking=False):
        return False

    try:
        from app import db

        try:
            acquired = db.session.execute(
                db.text('SELECT pg_try_advisory_lock(:key)'),
                {'key': _PIPELINE_ADVISORY_LOCK_KEY},
            ).scalar()
            if not acquired:
                _in_process_pipeline_lock.release()
                return False
            _advisory_lock_held = True
            return True
        except Exception:
            # SQLite / non-PostgreSQL tests — in-process lock is sufficient.
            _advisory_lock_held = False
            return True
    except Exception:
        _in_process_pipeline_lock.release()
        raise


def release_pipeline_lock() -> None:
    """Release the pipeline advisory lock if this process holds it."""
    global _advisory_lock_held

    if _advisory_lock_held:
        try:
            from app import db

            db.session.execute(
                db.text('SELECT pg_advisory_unlock(:key)'),
                {'key': _PIPELINE_ADVISORY_LOCK_KEY},
            )
        except Exception:
            logger.debug("Could not release advisory lock", exc_info=True)
        _advisory_lock_held = False

    if _in_process_pipeline_lock.locked():
        _in_process_pipeline_lock.release()


def run_pipeline_after_imports(app, run_ids: Optional[list[int]] = None) -> None:
    """Run the post-import pipeline inside *app*'s context (blocking)."""
    with app.app_context():
        if not try_acquire_pipeline_lock():
            logger.info("Pipeline already running — skipping duplicate invocation")
            return
        try:
            if run_ids:
                _wait_for_import_runs(run_ids)
            else:
                logger.info("Pipeline: no run_ids to wait for — running immediately")
            run_post_import_pipeline_sync()
        except Exception as exc:
            logger.error("Pipeline failed: %s", exc, exc_info=True)
            raise
        finally:
            release_pipeline_lock()


def start_pipeline_in_background(app, run_ids: Optional[list[int]] = None) -> threading.Thread:
    """Spawn a daemon thread that runs the post-import pipeline (in-process fallback)."""
    thread_name = f"hubspot-pipeline-{run_ids[0] if run_ids else 'manual'}"
    thread = threading.Thread(
        target=run_pipeline_after_imports,
        args=(app, run_ids or []),
        daemon=True,
        name=thread_name,
    )
    thread.start()
    logger.info("Pipeline background thread started (%s)", thread_name)
    return thread


def start_pipeline_subprocess(run_ids: Optional[list[int]] = None) -> None:
    """Spawn a detached subprocess so pipeline work survives Gunicorn reloads."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    script = os.path.join(backend_dir, 'scripts', 'run_pipeline_once.py')
    payload = json.dumps(run_ids or [])
    env = os.environ.copy()
    env.setdefault('FLASK_ENV', 'production')

    subprocess.Popen(  # noqa: S603 — trusted internal script path
        [sys.executable, script, payload],
        cwd=backend_dir,
        env=env,
        start_new_session=True,
    )
    logger.info("Pipeline subprocess started (run_ids=%s)", run_ids)


def maybe_start_startup_pipeline_recovery(_app, dangling_match_count: int) -> None:
    """Start startup recovery pipeline in a detached subprocess (single-flight via lock)."""
    if dangling_match_count <= 0:
        return
    logger.warning(
        "Startup recovery: %d dangling confirmed lead match(es) — spawning detached pipeline",
        dangling_match_count,
    )
    start_pipeline_subprocess(run_ids=[])


def count_dangling_confirmed_lead_matches() -> int:
    """Return confirmed lead matches whose internal_record_id no longer exists."""
    from sqlalchemy import exists

    from app.models.hubspot_match import HubSpotMatch
    from app.models.lead import Lead

    lead_exists = exists().where(Lead.id == HubSpotMatch.internal_record_id)
    return (
        HubSpotMatch.query
        .filter_by(status='confirmed', internal_record_type='lead')
        .filter(HubSpotMatch.internal_record_id.isnot(None))
        .filter(~lead_exists)
        .count()
    )


def try_dispatch_celery_pipeline(run_ids: Optional[list[int]] = None) -> bool:
    """Queue the pipeline on Celery. Returns True if dispatched, False if Celery unavailable."""
    try:
        from celery import current_app as celery_app  # noqa: PLC0415

        celery_app.send_task('hubspot.post_import_pipeline', kwargs={'run_ids': run_ids})
        logger.info("Post-import pipeline dispatched to Celery (run_ids=%s)", run_ids)
        return True
    except Exception as celery_exc:
        logger.warning("Celery unavailable for post-import pipeline: %s", celery_exc)
        return False


def dispatch_post_import_pipeline(app, run_ids: Optional[list[int]] = None) -> str:
    """Queue via Celery when available, else run in a detached subprocess.

    Returns ``'celery'``, ``'subprocess'``, or ``'thread'`` (legacy in-process).
    """
    if try_dispatch_celery_pipeline(run_ids):
        return 'celery'
    start_pipeline_subprocess(run_ids)
    return 'subprocess'
