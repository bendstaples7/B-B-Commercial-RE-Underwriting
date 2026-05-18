"""HubSpotImportService — orchestrates HubSpot CRM import runs."""
import logging
import threading
from datetime import datetime

from app import db
from app.exceptions import ImportRunNotFoundError
from app.models.hubspot_config import HubSpotConfig
from app.models.hubspot_import_run import HubSpotImportRun

logger = logging.getLogger(__name__)

# Default object types to import when none are specified.
DEFAULT_OBJECT_TYPES = ['deals', 'contacts', 'companies', 'engagements']

# Maps each object type to the registered Celery task name.
_TASK_MAP = {
    'deals': 'hubspot.import_deals',
    'contacts': 'hubspot.import_contacts',
    'companies': 'hubspot.import_companies',
    'engagements': 'hubspot.import_engagements',
}


def _run_pipeline_after_imports(app, run_ids: list) -> None:
    """Run the post-import pipeline in a background thread.

    Waits for all import runs in *run_ids* to reach a terminal state, then
    runs matching → activity conversion → signal extraction → rescore.
    This is Option 3: background thread guarantee that the pipeline always
    runs after an import, regardless of whether Celery is available.
    """
    import time
    from app.tasks.hubspot_tasks import (
        run_hubspot_matching,
        run_convert_hubspot_activities,
        run_extract_hubspot_signals,
        run_rescore_leads_after_import,
    )

    with app.app_context():
        # Wait for all import runs to reach a terminal state
        if run_ids:
            max_wait = 3600  # 1 hour
            poll_interval = 15
            elapsed = 0
            terminal = {'success', 'partial', 'failed'}

            while elapsed < max_wait:
                runs = HubSpotImportRun.query.filter(
                    HubSpotImportRun.id.in_(run_ids)
                ).all()
                if all(r.status in terminal for r in runs):
                    logger.info(
                        "Pipeline thread: all import runs complete — starting pipeline"
                    )
                    break
                logger.info(
                    "Pipeline thread: waiting for import runs %s (%ds elapsed)…",
                    run_ids, elapsed,
                )
                time.sleep(poll_interval)
                elapsed += poll_interval
            else:
                logger.warning(
                    "Pipeline thread: timed out waiting for runs %s — running pipeline anyway",
                    run_ids,
                )
        else:
            logger.info("Pipeline thread: no run_ids to wait for — running pipeline immediately")

        try:
            run_hubspot_matching()
            logger.info("Pipeline thread: matching complete")
            run_convert_hubspot_activities()
            logger.info("Pipeline thread: activity conversion complete")
            run_extract_hubspot_signals()
            logger.info("Pipeline thread: signal extraction complete")
            run_rescore_leads_after_import()
            logger.info("Pipeline thread: rescore complete — pipeline done")
        except Exception as exc:
            logger.error("Pipeline thread: pipeline failed: %s", exc, exc_info=True)


class HubSpotImportService:
    """Orchestrates HubSpot CRM import runs.

    Responsibilities:
    - Create ``HubSpotImportRun`` records (one per object type).
    - Dispatch the corresponding Celery tasks.
    - Provide status and listing queries for import runs.
    - Manage ``HubSpotConfig`` (read with masked token, upsert with encrypted token).
    """

    # ------------------------------------------------------------------ #
    # Import orchestration                                                 #
    # ------------------------------------------------------------------ #

    def start_import(self, object_types: list = None) -> list:
        """Create ``HubSpotImportRun`` records and dispatch Celery tasks.

        Any existing runs still stuck in 'running' status are marked as failed
        before new runs are created, so the UI always shows accurate state.

        Args:
            object_types: List of object type strings to import.  Defaults
                to ``['deals', 'contacts', 'companies', 'engagements']``.

        Returns:
            List of newly created ``HubSpotImportRun`` instances.
        """
        if object_types is None:
            object_types = DEFAULT_OBJECT_TYPES

        # Mark any previously-stuck runs as failed before starting new ones.
        stuck = HubSpotImportRun.query.filter(
            HubSpotImportRun.status == 'running',
            HubSpotImportRun.object_type.in_(object_types),
        ).all()
        if stuck:
            now = datetime.utcnow()
            for run in stuck:
                run.status = 'failed'
                run.end_time = now
                run.error_message = (
                    'Worker not available — Celery was not running when this '
                    'import was triggered. No data was fetched.'
                )
            db.session.flush()
            logger.warning(
                "Marked %d previously-stuck import run(s) as failed before starting new import.",
                len(stuck),
            )

        runs = []
        for obj_type in object_types:
            run = HubSpotImportRun(
                object_type=obj_type,
                status='running',
                start_time=datetime.utcnow(),
            )
            db.session.add(run)
            runs.append(run)

        db.session.flush()  # Assign IDs before dispatching tasks

        for run in runs:
            try:
                self._dispatch_task(run.object_type, run.id)
            except Exception as dispatch_exc:
                logger.warning(
                    "Failed to dispatch Celery task for %s run_id=%s: %s — marking run as failed.",
                    run.object_type, run.id, dispatch_exc,
                )
                run.status = 'failed'
                run.end_time = datetime.utcnow()
                run.error_message = (
                    f'Task dispatch failed: {dispatch_exc}. '
                    'Celery may not be running. No data was fetched.'
                )

        db.session.commit()
        logger.info(
            "Started import for object types %s; run IDs: %s",
            object_types,
            [r.id for r in runs],
        )

        # Option 3: spawn a background thread to run the pipeline after imports complete.
        # This guarantees the pipeline runs even if Celery/Redis is unavailable.
        # Also dispatch via Celery as a belt-and-suspenders backup.
        from flask import current_app  # noqa: PLC0415
        app = current_app._get_current_object()
        run_ids = [r.id for r in runs]

        pipeline_thread = threading.Thread(
            target=_run_pipeline_after_imports,
            args=(app, run_ids),
            daemon=True,
            name=f"hubspot-pipeline-{run_ids[0]}",
        )
        pipeline_thread.start()
        logger.info("Pipeline thread started for run_ids=%s", run_ids)

        # Also try Celery as a backup (will be a no-op if Celery already ran it)
        try:
            from celery import current_app as celery_app  # noqa: PLC0415
            celery_app.send_task('hubspot.post_import_pipeline', kwargs={'run_ids': run_ids})
        except Exception as celery_exc:
            logger.warning(
                "Could not dispatch Celery pipeline task (thread will handle it): %s",
                celery_exc,
            )

        return runs

    def _dispatch_task(self, object_type: str, run_id: int) -> None:
        """Dispatch the Celery task for *object_type* with *run_id*.

        Uses ``celery.send_task`` with the registered task name to avoid
        circular imports between the service layer and ``celery_worker``.

        Args:
            object_type: One of ``deals``, ``contacts``, ``companies``,
                ``engagements``.
            run_id: Primary key of the ``HubSpotImportRun`` to update.
        """
        task_name = _TASK_MAP.get(object_type)
        if task_name is None:
            logger.warning(
                "No Celery task registered for object type '%s'; skipping dispatch.",
                object_type,
            )
            return

        # Use send_task to dispatch by name — avoids importing celery_worker
        # directly from the service layer (which would create a circular import).
        from celery import current_app as celery_app  # noqa: PLC0415
        celery_app.send_task(task_name, args=[run_id])
        logger.debug("Dispatched Celery task '%s' for run_id=%s", task_name, run_id)

    # ------------------------------------------------------------------ #
    # Run status / listing                                                 #
    # ------------------------------------------------------------------ #

    def get_run_status(self, run_id: int) -> HubSpotImportRun:
        """Return the ``HubSpotImportRun`` for *run_id*.

        Args:
            run_id: Primary key of the import run.

        Returns:
            The matching ``HubSpotImportRun`` instance.

        Raises:
            ImportRunNotFoundError: If no run with *run_id* exists.
        """
        run = HubSpotImportRun.query.get(run_id)
        if run is None:
            raise ImportRunNotFoundError(
                f"Import run {run_id} not found",
                payload={'run_id': run_id},
            )
        return run

    def list_runs(self, page: int = 1, per_page: int = 20) -> tuple:
        """Return a paginated list of import runs, newest first.

        Args:
            page: 1-based page number.
            per_page: Number of records per page.

        Returns:
            A ``(runs, total)`` tuple where *runs* is a list of
            ``HubSpotImportRun`` instances and *total* is the total record
            count across all pages.
        """
        pagination = (
            HubSpotImportRun.query
            .order_by(HubSpotImportRun.start_time.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        return pagination.items, pagination.total

    # ------------------------------------------------------------------ #
    # Config management                                                    #
    # ------------------------------------------------------------------ #

    def get_config(self) -> HubSpotConfig | None:
        """Return the current ``HubSpotConfig`` with the token masked.

        The ``encrypted_token`` field is set to ``'***'`` before the record
        is returned so that callers never receive the raw encrypted value.

        Returns:
            The ``HubSpotConfig`` instance with ``encrypted_token`` masked,
            or ``None`` if no config has been saved yet.
        """
        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if config is None:
            return None
        # Expunge from the session before mutating so the masked value is never
        # accidentally flushed/committed to the database.
        db.session.expunge(config)
        config.encrypted_token = '***'
        return config

    def save_config(self, token: str, portal_id: str = None) -> HubSpotConfig:
        """Encrypt *token* and upsert the ``HubSpotConfig`` record.

        If a config record already exists, it is updated in place.  If none
        exists, a new record is created.

        Args:
            token: The raw (plaintext) HubSpot private-app token.
            portal_id: Optional HubSpot portal ID string.

        Returns:
            The saved ``HubSpotConfig`` instance (with the encrypted token
            stored, not the plaintext value).
        """
        # Lazy import to avoid circular dependency issues.
        from app.services.hubspot_client_service import HubSpotClientService  # noqa: PLC0415

        encrypted = HubSpotClientService.encrypt_token(token)

        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if config is None:
            config = HubSpotConfig(
                encrypted_token=encrypted,
                portal_id=portal_id,
            )
            db.session.add(config)
        else:
            config.encrypted_token = encrypted
            if portal_id is not None:
                config.portal_id = portal_id
            config.updated_at = datetime.utcnow()

        db.session.commit()
        logger.info("HubSpotConfig saved (portal_id=%s)", portal_id)
        return config
