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
from typing import Literal, Optional

logger = logging.getLogger(__name__)

PipelineMode = Literal['full', 'rescore_only']

# Per-thread lead IDs touched during the current pipeline run.
_pipeline_ctx = threading.local()

# Import-run statuses that mean the batch is finished (success, partial, or failed).
_TERMINAL_IMPORT_STATUSES = frozenset({'success', 'partial', 'failed'})

# PostgreSQL advisory lock key — prevents concurrent pipeline runs across workers.
_PIPELINE_ADVISORY_LOCK_KEY = 913372001
# Separate key so startup recovery spawn is single-flight across Gunicorn workers.
_RECOVERY_SPAWN_LOCK_KEY = 913372002

# Set on detached subprocess env so Flask startup does not recurse into recovery.
_PIPELINE_SUBPROCESS_ENV = 'PIPELINE_SUBPROCESS'

_in_process_pipeline_lock = threading.Lock()
_advisory_lock_held = False
# Dedicated DB connection holding the PostgreSQL advisory lock for its lifetime.
_lock_connection = None
_spawn_coord_connection = None


def _affected_lead_set() -> set[int]:
    lead_ids = getattr(_pipeline_ctx, 'lead_ids', None)
    if lead_ids is None:
        lead_ids = set()
        _pipeline_ctx.lead_ids = lead_ids
    return lead_ids


def reset_pipeline_affected_leads() -> None:
    """Clear affected-lead tracking at the start of a pipeline run."""
    _pipeline_ctx.lead_ids = set()


def note_pipeline_affected_leads(lead_ids) -> None:
    """Record lead IDs that upstream pipeline steps modified."""
    affected = _affected_lead_set()
    for lead_id in lead_ids:
        if lead_id is not None:
            affected.add(int(lead_id))


def get_pipeline_affected_leads() -> list[int]:
    """Return sorted lead IDs touched in the current pipeline run."""
    return sorted(_affected_lead_set())


def run_post_import_pipeline_sync(force_full_rescore: bool = False) -> None:
    """Run the full post-import pipeline synchronously in the current process."""
    from app.tasks.hubspot_tasks import (
        run_convert_hubspot_activities,
        run_enrich_leads_from_hubspot,
        run_extract_hubspot_signals,
        run_hubspot_matching,
        run_rescore_leads_after_import,
        run_sync_hubspot_tasks_for_confirmed_leads,
    )

    reset_pipeline_affected_leads()

    try:
        run_hubspot_matching()
        logger.info("Post-import pipeline: matching complete")

        run_enrich_leads_from_hubspot()
        logger.info("Post-import pipeline: lead enrichment complete")

        # Legacy engagement payloads can be stale for task status — convert first,
        # then live CRM v3 sync so authoritative HubSpot status wins each run.
        run_convert_hubspot_activities()
        logger.info("Post-import pipeline: activity conversion complete")

        run_sync_hubspot_tasks_for_confirmed_leads()
        logger.info("Post-import pipeline: HubSpot task sync complete")

        from app.services.mail_task_lifecycle_service import (
            reconcile_recent_sale_mail_tasks,
        )
        reconciliation = reconcile_recent_sale_mail_tasks(
            actor='hubspot_post_import',
        )
        logger.info(
            "Post-import pipeline: deferred %s recent-sale mail task(s)",
            reconciliation['rescheduled_task_count'],
        )

        run_extract_hubspot_signals()
        logger.info("Post-import pipeline: signal extraction complete")

        affected = get_pipeline_affected_leads()
        rescored = run_rescore_leads_after_import(
            lead_ids=affected,
            force_full=force_full_rescore,
        )
        from app.services.deploy_sync_policy import record_pipeline_completed

        record_pipeline_completed(rescore_count=rescored)
        logger.info("Post-import pipeline: rescore complete")
    finally:
        reset_pipeline_affected_leads()


def run_rescore_only_sync() -> None:
    """Run a full lead rescore without HubSpot fetch/enrich steps."""
    reset_pipeline_affected_leads()
    from app.services.deploy_sync_policy import record_pipeline_completed
    from app.tasks.hubspot_tasks import run_rescore_leads_after_import

    rescored = run_rescore_leads_after_import(force_full=True)
    record_pipeline_completed(rescore_count=rescored)
    logger.info("Rescore-only pipeline complete")
    reset_pipeline_affected_leads()


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


def _is_non_postgresql_dialect() -> bool:
    """Return True when advisory locks are unavailable (e.g. SQLite tests)."""
    from app import db

    return db.engine.dialect.name != 'postgresql'


def _open_autocommit_connection():
    """Return a dedicated autocommit DB connection (PostgreSQL only)."""
    from app import db

    conn = db.engine.connect()
    return conn.execution_options(isolation_level='AUTOCOMMIT')


def try_acquire_pipeline_lock() -> bool:
    """Acquire a cross-process lock so only one pipeline run executes at a time."""
    global _advisory_lock_held, _lock_connection

    if not _in_process_pipeline_lock.acquire(blocking=False):
        return False

    try:
        from app import db

        if _is_non_postgresql_dialect():
            # SQLite / in-memory tests — in-process lock only.
            _advisory_lock_held = False
            return True

        # Hold a dedicated autocommit connection for the lock lifetime so pool
        # checkouts during pipeline commits cannot drop the advisory lock.
        _lock_connection = _open_autocommit_connection()
        acquired = _lock_connection.execute(
            db.text('SELECT pg_try_advisory_lock(:key)'),
            {'key': _PIPELINE_ADVISORY_LOCK_KEY},
        ).scalar()
        if not acquired:
            _lock_connection.close()
            _lock_connection = None
            _in_process_pipeline_lock.release()
            return False
        _advisory_lock_held = True
        return True
    except Exception:
        if _lock_connection is not None:
            _lock_connection.close()
            _lock_connection = None
        _in_process_pipeline_lock.release()
        raise


def release_pipeline_lock() -> None:
    """Release the pipeline advisory lock if this process holds it."""
    global _advisory_lock_held, _lock_connection

    if _advisory_lock_held and _lock_connection is not None:
        try:
            from app import db

            _lock_connection.execute(
                db.text('SELECT pg_advisory_unlock(:key)'),
                {'key': _PIPELINE_ADVISORY_LOCK_KEY},
            )
        except Exception:
            logger.debug("Could not release advisory lock", exc_info=True)
        finally:
            _lock_connection.close()
            _lock_connection = None
        _advisory_lock_held = False

    if _in_process_pipeline_lock.locked():
        _in_process_pipeline_lock.release()


def run_pipeline_after_imports(
    app,
    run_ids: Optional[list[int]] = None,
    mode: PipelineMode = 'full',
) -> None:
    """Run the post-import pipeline inside *app*'s context (blocking)."""
    with app.app_context():
        if not try_acquire_pipeline_lock():
            logger.info("Pipeline already running — skipping duplicate invocation")
            return
        try:
            if mode == 'rescore_only':
                run_rescore_only_sync()
                return

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


def start_pipeline_subprocess(
    run_ids: Optional[list[int]] = None,
    mode: PipelineMode = 'full',
) -> None:
    """Spawn a detached subprocess so pipeline work survives Gunicorn reloads."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    script = os.path.join(backend_dir, 'scripts', 'run_pipeline_once.py')
    payload = json.dumps({'run_ids': run_ids or [], 'mode': mode})
    env = os.environ.copy()
    env.setdefault('FLASK_ENV', 'production')
    env[_PIPELINE_SUBPROCESS_ENV] = '1'

    subprocess.Popen(  # noqa: S603 — trusted internal script path
        [sys.executable, script, payload],
        cwd=backend_dir,
        env=env,
        start_new_session=True,
    )
    logger.info("Pipeline subprocess started (run_ids=%s, mode=%s)", run_ids, mode)


def _try_claim_recovery_spawn() -> bool:
    """Return True when this worker should spawn startup recovery (single-flight)."""
    try:
        import redis as redis_lib

        redis_url = os.environ.get('REDIS_URL') or os.environ.get('CELERY_BROKER_URL', '')
        if redis_url:
            client = redis_lib.from_url(
                redis_url, socket_connect_timeout=1, socket_timeout=1,
            )
            if client.set('hubspot:pipeline:recovery_spawn', '1', nx=True, ex=600):
                return True
            logger.info("Startup recovery spawn already claimed (Redis guard)")
            return False
    except Exception:
        logger.debug("Redis recovery spawn guard unavailable", exc_info=True)

    return _try_acquire_recovery_spawn_lock()


def _try_acquire_recovery_spawn_lock() -> bool:
    """PostgreSQL fallback: non-blocking advisory lock for recovery spawn."""
    global _spawn_coord_connection

    if _is_non_postgresql_dialect():
        return True

    try:
        from app import db

        _spawn_coord_connection = _open_autocommit_connection()
        acquired = _spawn_coord_connection.execute(
            db.text('SELECT pg_try_advisory_lock(:key)'),
            {'key': _RECOVERY_SPAWN_LOCK_KEY},
        ).scalar()
        if not acquired:
            _spawn_coord_connection.close()
            _spawn_coord_connection = None
            logger.info("Startup recovery spawn already claimed (PostgreSQL guard)")
            return False
        return True
    except Exception:
        if _spawn_coord_connection is not None:
            _spawn_coord_connection.close()
            _spawn_coord_connection = None
        logger.debug("PostgreSQL recovery spawn guard unavailable", exc_info=True)
        return True


def _release_recovery_spawn_lock() -> None:
    """Release the recovery spawn coordination lock after subprocess is started."""
    global _spawn_coord_connection

    if _spawn_coord_connection is None:
        return

    try:
        from app import db

        _spawn_coord_connection.execute(
            db.text('SELECT pg_advisory_unlock(:key)'),
            {'key': _RECOVERY_SPAWN_LOCK_KEY},
        )
    except Exception:
        logger.debug("Could not release recovery spawn lock", exc_info=True)
    finally:
        _spawn_coord_connection.close()
        _spawn_coord_connection = None


def maybe_start_startup_pipeline_recovery(app, dangling_match_count: int) -> None:
    """Start startup recovery pipeline in a detached subprocess (single-flight via lock)."""
    if dangling_match_count <= 0:
        return
    if os.environ.get(_PIPELINE_SUBPROCESS_ENV):
        logger.info(
            "Startup recovery skipped — already running inside pipeline subprocess"
        )
        return

    with app.app_context():
        if not _try_claim_recovery_spawn():
            return

    try:
        logger.warning(
            "Startup recovery: %d dangling confirmed lead match(es) — spawning detached pipeline",
            dangling_match_count,
        )
        start_pipeline_subprocess(run_ids=[])
    finally:
        _release_recovery_spawn_lock()


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


def _celery_workers_responding() -> bool:
    """Return True when at least one Celery workers responds to a control ping."""
    from celery import current_app as celery_app  # noqa: PLC0415

    inspect = celery_app.control.inspect(timeout=1.0)
    ping = inspect.ping() if inspect else None
    return bool(ping)


def try_dispatch_celery_pipeline(
    run_ids: Optional[list[int]] = None,
    mode: PipelineMode = 'full',
) -> bool:
    """Queue the pipeline on Celery when a live workers is available."""
    try:
        if not _celery_workers_responding():
            logger.warning(
                "No Celery workers responding — falling back from Celery dispatch"
            )
            return False

        from celery import current_app as celery_app  # noqa: PLC0415

        if mode == 'rescore_only':
            celery_app.send_task('hubspot.rescore_only')
            logger.info("Rescore-only pipeline dispatched to Celery")
            return True

        celery_app.send_task('hubspot.post_import_pipeline', kwargs={'run_ids': run_ids})
        logger.info("Post-import pipeline dispatched to Celery (run_ids=%s)", run_ids)
        return True
    except Exception as celery_exc:
        logger.warning("Celery unavailable for post-import pipeline: %s", celery_exc)
        return False


def dispatch_post_import_pipeline(
    app,
    run_ids: Optional[list[int]] = None,
    mode: PipelineMode = 'full',
) -> str:
    """Queue via Celery when a workers is live, else run in a detached subprocess.

    Returns ``'celery'`` or ``'subprocess'``.
    """
    if try_dispatch_celery_pipeline(run_ids, mode=mode):
        return 'celery'
    start_pipeline_subprocess(run_ids, mode=mode)
    return 'subprocess'


def dispatch_tiered_post_deploy_sync(app, sync_mode: str) -> str:
    """Dispatch tiered post-deploy sync work without blocking.

    *sync_mode* is ``skip``, ``rescore_only``, or ``full_pipeline``.
    Returns dispatch channel or ``skipped``.
    """
    if sync_mode == 'skip':
        logger.info('Post-deploy sync skipped — no HubSpot/scoring paths changed')
        return 'skipped'

    if sync_mode == 'rescore_only':
        return dispatch_post_import_pipeline(app, run_ids=None, mode='rescore_only')

    return dispatch_post_import_pipeline(app, run_ids=None, mode='full')
