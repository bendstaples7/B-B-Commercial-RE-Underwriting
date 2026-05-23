"""HubSpot Webhook Processing Pipeline — plain function implementations.

All functions here are pure implementations with NO @celery.task decorators.
The decorated wrappers live in celery_worker.py where the celery app instance
is guaranteed to exist.

Entry points (called by the decorated wrappers in celery_worker.py):
  run_process_webhook_event(log_id, self_task=None)
  run_fetch_and_upsert_record(object_type, object_id, log_id, self_task=None)
  run_incremental_matching(object_type, object_id)
  run_convert_incremental_activity(engagement_id)
  run_extract_incremental_signals(engagement_id, lead_id)
  run_rescore_lead(lead_id)
  run_purge_old_webhook_logs()
  is_duplicate(object_type, object_id, current_log_id)
  is_loop_event(object_type, object_id)

Requirements: 3, 4, 5, 6
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment-configurable constants
# ---------------------------------------------------------------------------

DEDUP_WINDOW_SECONDS = int(os.environ.get('HUBSPOT_DEDUP_WINDOW_SECONDS', 60))
LOOP_GUARD_SECONDS = int(os.environ.get('HUBSPOT_LOOP_GUARD_SECONDS', 30))


def _get_or_create_app():
    """Return the current Flask app if already in an app context, else create one.

    This allows the task functions to work both:
    - In a Celery worker (app context already exists via celery_worker.py)
    - As standalone scripts (no app context, must create one)
    """
    # First check if celery_worker has a Flask app stored globally
    try:
        import celery_worker as _cw
        if hasattr(_cw, '_flask_app') and _cw._flask_app is not None:
            return _cw._flask_app  # Use the worker's app — push a new context in the thread
    except ImportError:
        pass

    try:
        from flask import current_app
        # If this succeeds, we're already in an app context
        _ = current_app._get_current_object()
        return None  # Signal: use existing context
    except RuntimeError:
        # No app context — create one
        from dotenv import load_dotenv
        load_dotenv()
        from app import create_app
        return create_app()


class _AppContextManager:
    """Context manager that either uses the existing app context or creates a new one."""

    def __init__(self):
        self._app = _get_or_create_app()
        self._ctx = None

    def __enter__(self):
        if self._app is not None:
            self._ctx = self._app.app_context()
            self._ctx.push()
        return self

    def __exit__(self, *args):
        if self._ctx is not None:
            self._ctx.pop()


# ---------------------------------------------------------------------------
# Deduplication helper
# ---------------------------------------------------------------------------

def is_duplicate(object_type: str, object_id: str, current_log_id: int) -> int | None:
    """Return the log_id of a more recent event for the same object within
    DEDUP_WINDOW_SECONDS, or None if this event should be processed.

    A "more recent" event is one with a higher id (inserted later) for the
    same (object_type, object_id) pair that arrived within the dedup window
    and is still in a processable status.
    """
    from app.models.hubspot_webhook_log import HubSpotWebhookLog

    cutoff = datetime.utcnow() - timedelta(seconds=DEDUP_WINDOW_SECONDS)
    newer = HubSpotWebhookLog.query.filter(
        HubSpotWebhookLog.hubspot_object_type == object_type,
        HubSpotWebhookLog.hubspot_object_id == object_id,
        HubSpotWebhookLog.id > current_log_id,
        HubSpotWebhookLog.received_at >= cutoff,
        HubSpotWebhookLog.status.in_(['pending', 'processing', 'processed'])
    ).order_by(HubSpotWebhookLog.id.desc()).first()
    return newer.id if newer else None


# ---------------------------------------------------------------------------
# Loop guard helper
# ---------------------------------------------------------------------------

def is_loop_event(object_type: str, object_id: str) -> bool:
    """Return True if this object was written to HubSpot by the platform
    within LOOP_GUARD_SECONDS.

    Checks the hubspot_platform_writes table. Until write-back is enabled
    this table is always empty, so this function always returns False.
    """
    from app.models.hubspot_platform_write import HubSpotPlatformWrite

    cutoff = datetime.utcnow() - timedelta(seconds=LOOP_GUARD_SECONDS)
    write = HubSpotPlatformWrite.query.filter(
        HubSpotPlatformWrite.object_type == object_type,
        HubSpotPlatformWrite.hubspot_id == object_id,
        HubSpotPlatformWrite.written_at >= cutoff,
    ).first()
    return write is not None


# ---------------------------------------------------------------------------
# Task 1: process_webhook_event
# ---------------------------------------------------------------------------

def run_process_webhook_event(log_id: int, self_task=None) -> None:
    """Main processing task for a single webhook event.

    1. Load WebhookLog, set status='processing'
    2. Check dedup: is_duplicate(object_type, object_id, log_id)
       - If duplicate found: set status='deduplicated', superseded_by_log_id=newer_id, return
    3. Check loop guard: is_loop_event(object_type, object_id)
       - If loop: set status='loop_suppressed', return
    4. Dispatch fetch_and_upsert_record (via Celery)

    Requirements: 3, 4
    """
    with _AppContextManager():
        _process_webhook_event_inner(log_id, self_task=self_task)


def _process_webhook_event_inner(log_id: int, self_task=None) -> None:
    """Core logic for process_webhook_event — runs inside an existing app context.

    Separated from run_process_webhook_event so tests can call this directly
    without triggering a second create_app() call.
    """
    from app import db
    from app.models.hubspot_webhook_log import HubSpotWebhookLog

    log = HubSpotWebhookLog.query.get(log_id)
    if log is None:
        logger.error("run_process_webhook_event: log_id=%d not found", log_id)
        return

    # Step 1: mark as processing
    log.status = 'processing'
    db.session.commit()

    object_type = log.hubspot_object_type
    object_id = log.hubspot_object_id

    # Step 2: deduplication check
    newer_id = is_duplicate(object_type, object_id, log_id)
    if newer_id is not None:
        logger.info(
            "run_process_webhook_event: log_id=%d deduplicated by log_id=%d",
            log_id, newer_id,
        )
        log.status = 'deduplicated'
        log.superseded_by_log_id = newer_id
        db.session.commit()
        return

    # Step 3: loop guard check
    if is_loop_event(object_type, object_id):
        logger.info(
            "run_process_webhook_event: log_id=%d loop_suppressed (object_type=%s object_id=%s)",
            log_id, object_type, object_id,
        )
        log.status = 'loop_suppressed'
        db.session.commit()
        return

    # Step 4: dispatch fetch_and_upsert_record
    try:
        from celery_worker import fetch_and_upsert_record
        fetch_and_upsert_record.delay(object_type, object_id, log_id)
        logger.info(
            "run_process_webhook_event: dispatched fetch_and_upsert for log_id=%d "
            "object_type=%s object_id=%s",
            log_id, object_type, object_id,
        )
    except Exception as exc:
        logger.error(
            "run_process_webhook_event: failed to dispatch fetch_and_upsert for log_id=%d: %s",
            log_id, exc,
        )
        log.status = 'failed'
        log.error_message = str(exc)
        db.session.commit()
        raise


# ---------------------------------------------------------------------------
# Task 2: fetch_and_upsert_record
# ---------------------------------------------------------------------------

# Object type → (model class name, API path template, extra_value_extractor)
_OBJECT_TYPE_CONFIG = {
    'deal': {
        'model': 'HubSpotDeal',
        'path_template': '/crm/v3/objects/deals/{object_id}',
        'params': {
            'properties': (
                'dealname,pipeline,dealstage,closedate,amount,'
                'county_assessor_pin,pin,address,hs_object_id,'
                'createdate,hs_lastmodifieddate'
            )
        },
        'extra_values': None,
    },
    'contact': {
        'model': 'HubSpotContact',
        'path_template': '/crm/v3/objects/contacts/{object_id}',
        'params': {
            'properties': (
                'firstname,lastname,email,phone,mobilephone,'
                'hs_object_id,createdate,hs_lastmodifieddate,'
                'associatedcompanyid,hs_analytics_source,lifecyclestage,hs_lead_source'
            )
        },
        'extra_values': None,
    },
    'company': {
        'model': 'HubSpotCompany',
        'path_template': '/crm/v3/objects/companies/{object_id}',
        'params': {
            'properties': 'name,type,phone,hs_object_id,createdate,hs_lastmodifieddate'
        },
        'extra_values': None,
    },
    'engagement': {
        'model': 'HubSpotEngagement',
        'path_template': '/engagements/v1/engagements/{object_id}',
        'params': {},
        'extra_values': 'engagement_type',  # special marker — extracted from record
    },
}


def run_fetch_and_upsert_record(
    object_type: str, object_id: str, log_id: int, self_task=None
) -> None:
    """Fetch the full record from HubSpot API and upsert into the raw table.

    - Uses HubSpotClientService._get() to fetch the record
    - Uses _upsert_hubspot_record() from hubspot_tasks.py for the upsert
    - Creates a HubSpotSyncRun record
    - Chains to run_incremental_matching
    - Retries with exponential backoff on API errors (max 3 retries)
    - On success: sets log status='processed', processed_at=now
    - On final failure: sets log status='failed', error_message=str(exc)

    Requirements: 3, 5
    """
    with _AppContextManager():
        import app.models as _models
        from app import db
        from app.models.hubspot_webhook_log import HubSpotWebhookLog
        from app.models.hubspot_sync_run import HubSpotSyncRun
        from app.models.hubspot_config import HubSpotConfig
        from app.services import HubSpotClientService
        from app.exceptions import HubSpotRateLimitError, ExternalServiceError
        from app.tasks.hubspot_tasks import _upsert_hubspot_record

        log = HubSpotWebhookLog.query.get(log_id)
        if log is None:
            logger.error("run_fetch_and_upsert_record: log_id=%d not found", log_id)
            return

        config_obj = _OBJECT_TYPE_CONFIG.get(object_type)
        if config_obj is None:
            logger.error(
                "run_fetch_and_upsert_record: unknown object_type=%s for log_id=%d",
                object_type, log_id,
            )
            log.status = 'failed'
            log.error_message = f"Unknown object_type: {object_type}"
            db.session.commit()
            return

        # Load HubSpot config
        hs_config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if hs_config is None:
            log.status = 'failed'
            log.error_message = "No HubSpot configuration found"
            db.session.commit()
            logger.error("run_fetch_and_upsert_record: no HubSpotConfig found")
            return

        try:
            client = HubSpotClientService(hs_config)
            path = config_obj['path_template'].format(object_id=object_id)
            params = config_obj['params'] or {}
            record = client._get(path, params)

            # Resolve model class
            model_class = getattr(_models, config_obj['model'])

            # Build extra_values for engagements
            extra_values = None
            if config_obj['extra_values'] == 'engagement_type':
                engagement_type = (
                    record.get('engagement', {}).get('type', 'UNKNOWN')
                    or 'UNKNOWN'
                )
                extra_values = {'engagement_type': str(engagement_type).upper()}

            # Use NULL for webhook-triggered upserts — no HubSpotImportRun is
            # created for individual webhook events (run_id=0 violates the FK).
            upsert_result = _upsert_hubspot_record(
                db=db,
                model_class=model_class,
                hubspot_id=object_id,
                raw_payload=record,
                run_id=None,
                extra_values=extra_values,
            )
            db.session.commit()

            # Map 'inserted'/'updated' to 'created'/'updated' for SyncRun
            sync_result = 'created' if upsert_result == 'inserted' else 'updated'

            # Create SyncRun record
            sync_run = HubSpotSyncRun(
                trigger='webhook',
                object_type=object_type,
                hubspot_id=object_id,
                upsert_result=sync_result,
                webhook_log_id=log_id,
            )
            db.session.add(sync_run)
            db.session.commit()

            logger.info(
                "run_fetch_and_upsert_record: log_id=%d object_type=%s object_id=%s "
                "upsert_result=%s sync_run_id=%d",
                log_id, object_type, object_id, sync_result, sync_run.id,
            )

            # Mark log as processed
            log.status = 'processed'
            log.processed_at = datetime.utcnow()
            db.session.commit()

            # Chain to incremental matching
            try:
                from celery_worker import run_incremental_matching as _celery_matching
                _celery_matching.delay(object_type, object_id)
            except Exception as chain_exc:
                logger.warning(
                    "run_fetch_and_upsert_record: failed to dispatch incremental_matching "
                    "for object_type=%s object_id=%s: %s",
                    object_type, object_id, chain_exc,
                )

        except (HubSpotRateLimitError, ExternalServiceError) as retryable_exc:
            logger.warning(
                "run_fetch_and_upsert_record: retryable error for log_id=%d: %s",
                log_id, retryable_exc,
            )
            if self_task is not None:
                raise self_task.retry(
                    exc=retryable_exc,
                    countdown=2 ** self_task.request.retries * 60,
                )
            # If no self_task (direct call), mark as failed
            log.status = 'failed'
            log.error_message = str(retryable_exc)
            db.session.commit()
            raise

        except Exception as fatal_exc:
            logger.error(
                "run_fetch_and_upsert_record: fatal error for log_id=%d: %s",
                log_id, fatal_exc, exc_info=True,
            )
            log.status = 'failed'
            log.error_message = str(fatal_exc)
            db.session.commit()
            raise


# ---------------------------------------------------------------------------
# Task 3: run_incremental_matching
# ---------------------------------------------------------------------------

def run_incremental_matching(object_type: str, object_id: str) -> None:
    """Run HubSpotMatcherService for the updated record.

    - Loads the raw record from the appropriate model by hubspot_id
    - Calls matcher.match_deal/match_contact/match_company
    - Only adds to Review_Queue if confidence is MEDIUM/UNMATCHED AND no
      confirmed match exists
    - Chains to run_convert_incremental_activity for engagements

    Requirements: 3, 5
    """
    with _AppContextManager():
        import app.models as _models
        from app import db
        from app.models.hubspot_match import HubSpotMatch

        # Map object_type to model class name
        model_map = {
            'deal': 'HubSpotDeal',
            'contact': 'HubSpotContact',
            'company': 'HubSpotCompany',
            'engagement': 'HubSpotEngagement',
        }
        model_name = model_map.get(object_type)
        if model_name is None:
            logger.warning(
                "run_incremental_matching: unknown object_type=%s object_id=%s",
                object_type, object_id,
            )
            return

        model_class = getattr(_models, model_name)
        record = model_class.query.filter_by(hubspot_id=object_id).first()
        if record is None:
            logger.warning(
                "run_incremental_matching: %s with hubspot_id=%s not found",
                model_name, object_id,
            )
            return

        # Engagements don't go through the matcher — dispatch conversion directly
        if object_type == 'engagement':
            try:
                from celery_worker import convert_incremental_activity
                convert_incremental_activity.delay(object_id)
            except Exception as exc:
                logger.warning(
                    "run_incremental_matching: failed to dispatch convert_activity "
                    "for engagement_id=%s: %s",
                    object_id, exc,
                )
            return

        # Run the appropriate matcher
        try:
            from app.services.hubspot_matcher_service import HubSpotMatcherService
            matcher = HubSpotMatcherService()

            if object_type == 'deal':
                match = matcher.match_deal(record)
            elif object_type == 'contact':
                match = matcher.match_contact(record)
            elif object_type == 'company':
                match = matcher.match_company(record)
            else:
                logger.warning(
                    "run_incremental_matching: no matcher for object_type=%s", object_type
                )
                return

            db.session.commit()

            # Only add to Review_Queue if confidence is MEDIUM/UNMATCHED AND
            # no confirmed match already exists
            if match.confidence in ('MEDIUM', 'UNMATCHED'):
                existing_confirmed = HubSpotMatch.query.filter_by(
                    hubspot_record_type=object_type,
                    hubspot_id=object_id,
                    status='confirmed',
                ).first()
                if not existing_confirmed:
                    logger.info(
                        "run_incremental_matching: %s hubspot_id=%s confidence=%s "
                        "added to review queue (match_id=%d)",
                        object_type, object_id, match.confidence, match.id,
                    )
                    # The match record itself IS the review queue entry —
                    # it's already persisted with status='pending' by the matcher
                else:
                    logger.debug(
                        "run_incremental_matching: %s hubspot_id=%s has confirmed match — "
                        "skipping review queue",
                        object_type, object_id,
                    )

            logger.info(
                "run_incremental_matching: %s hubspot_id=%s matched with confidence=%s",
                object_type, object_id, match.confidence,
            )

        except Exception as exc:
            logger.error(
                "run_incremental_matching: error matching %s hubspot_id=%s: %s",
                object_type, object_id, exc, exc_info=True,
            )
            db.session.rollback()
            raise


# ---------------------------------------------------------------------------
# Task 4: run_convert_incremental_activity
# ---------------------------------------------------------------------------

def run_convert_incremental_activity(engagement_id: str) -> None:
    """Run HubSpotActivityConverterService for a single engagement.

    - Skips if Interaction or Task already exists with this hubspot_engagement_id
    - Calls converter.convert_engagement(engagement) and saves
    - After conversion, finds the lead_id via InteractionAssociation and
      dispatches run_extract_incremental_signals

    Requirements: 3, 5
    """
    with _AppContextManager():
        from app import db
        from app.models import HubSpotEngagement, Interaction, Task
        from app.models.interaction_association import InteractionAssociation
        from app.services.hubspot_activity_converter_service import HubSpotActivityConverterService

        # Check if already converted
        existing_interaction = Interaction.query.filter_by(
            hubspot_engagement_id=str(engagement_id)
        ).first()
        existing_task = Task.query.filter_by(
            hubspot_task_id=str(engagement_id)
        ).first()

        if existing_interaction is not None or existing_task is not None:
            logger.debug(
                "run_convert_incremental_activity: engagement_id=%s already converted — skipping",
                engagement_id,
            )
            return

        engagement = HubSpotEngagement.query.filter_by(
            hubspot_id=str(engagement_id)
        ).first()
        if engagement is None:
            logger.warning(
                "run_convert_incremental_activity: HubSpotEngagement hubspot_id=%s not found",
                engagement_id,
            )
            return

        try:
            converter = HubSpotActivityConverterService()
            result = converter.convert_engagement(engagement)

            if result is None:
                logger.debug(
                    "run_convert_incremental_activity: engagement_id=%s produced no result "
                    "(unrecognized type or already converted)",
                    engagement_id,
                )
                return

            # result is already committed by the converter — find lead_id for signal extraction
            lead_id = None
            if isinstance(result, Interaction):
                assoc = InteractionAssociation.query.filter_by(
                    interaction_id=result.id,
                    target_type='lead',
                ).first()
                if assoc:
                    lead_id = assoc.target_id

            if lead_id is not None:
                try:
                    from celery_worker import extract_incremental_signals
                    extract_incremental_signals.delay(engagement_id, lead_id)
                    logger.info(
                        "run_convert_incremental_activity: dispatched extract_signals "
                        "for engagement_id=%s lead_id=%d",
                        engagement_id, lead_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "run_convert_incremental_activity: failed to dispatch extract_signals "
                        "for engagement_id=%s: %s",
                        engagement_id, exc,
                    )
            else:
                logger.debug(
                    "run_convert_incremental_activity: no lead association for engagement_id=%s "
                    "— skipping signal extraction",
                    engagement_id,
                )

        except Exception as exc:
            logger.error(
                "run_convert_incremental_activity: error converting engagement_id=%s: %s",
                engagement_id, exc, exc_info=True,
            )
            db.session.rollback()
            raise


# ---------------------------------------------------------------------------
# Task 5: run_extract_incremental_signals
# ---------------------------------------------------------------------------

def run_extract_incremental_signals(engagement_id: str, lead_id: int) -> None:
    """Run HubSpotSignalExtractorService for a single engagement.

    Chains to run_rescore_lead after extraction.

    Requirements: 3, 5
    """
    with _AppContextManager():
        from app import db
        from app.models import HubSpotEngagement
        from app.services.hubspot_signal_extractor_service import HubSpotSignalExtractorService

        engagement = HubSpotEngagement.query.filter_by(
            hubspot_id=str(engagement_id)
        ).first()
        if engagement is None:
            logger.warning(
                "run_extract_incremental_signals: HubSpotEngagement hubspot_id=%s not found",
                engagement_id,
            )
            return

        try:
            extractor = HubSpotSignalExtractorService()
            signals = extractor.extract_signals(engagement, lead_id)

            for signal in signals:
                db.session.add(signal)

            if signals:
                extractor.apply_suppression(signals)

            db.session.commit()

            logger.info(
                "run_extract_incremental_signals: engagement_id=%s lead_id=%d signals=%d",
                engagement_id, lead_id, len(signals),
            )

            # Chain to rescore_lead
            try:
                from celery_worker import rescore_lead
                rescore_lead.delay(lead_id)
            except Exception as exc:
                logger.warning(
                    "run_extract_incremental_signals: failed to dispatch rescore_lead "
                    "for lead_id=%d: %s",
                    lead_id, exc,
                )

        except Exception as exc:
            logger.error(
                "run_extract_incremental_signals: error for engagement_id=%s lead_id=%d: %s",
                engagement_id, lead_id, exc, exc_info=True,
            )
            db.session.rollback()
            raise


# ---------------------------------------------------------------------------
# Task 6: run_rescore_lead
# ---------------------------------------------------------------------------

def run_rescore_lead(lead_id: int) -> None:
    """Run LeadScoringEngine for a single lead.

    Calls engine.bulk_rescore(lead_ids=[lead_id]).

    Requirements: 3, 5
    """
    with _AppContextManager():
        from app.services import LeadScoringEngine

        try:
            engine = LeadScoringEngine()
            rescored = engine.bulk_rescore(lead_ids=[lead_id])
            logger.info(
                "run_rescore_lead: lead_id=%d rescored=%d",
                lead_id, rescored,
            )
        except Exception as exc:
            logger.error(
                "run_rescore_lead: error rescoring lead_id=%d: %s",
                lead_id, exc, exc_info=True,
            )
            raise


# ---------------------------------------------------------------------------
# Task 7: run_purge_old_webhook_logs
# ---------------------------------------------------------------------------

def _purge_old_webhook_logs_inner() -> int:
    """Core logic for purging old webhook logs — runs inside an existing app context.

    Separated from run_purge_old_webhook_logs so tests can call this directly
    without triggering a second create_app() call.
    """
    from app import db
    from app.models.hubspot_webhook_log import HubSpotWebhookLog

    cutoff = datetime.utcnow() - timedelta(days=30)
    deleted = HubSpotWebhookLog.query.filter(
        HubSpotWebhookLog.received_at < cutoff
    ).delete(synchronize_session=False)
    db.session.commit()

    logger.info(
        "run_purge_old_webhook_logs: deleted %d records older than %s",
        deleted, cutoff.isoformat(),
    )
    return deleted


def run_purge_old_webhook_logs() -> int:
    """Delete HubSpotWebhookLog records where received_at < NOW() - 30 days.

    Returns count of deleted records.

    Requirements: 6
    """
    with _AppContextManager():
        return _purge_old_webhook_logs_inner()
