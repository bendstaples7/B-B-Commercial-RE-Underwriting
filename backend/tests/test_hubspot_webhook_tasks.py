"""Unit tests for hubspot_webhook_tasks.py.

Tests cover:
  - is_duplicate: within window (returns newer log_id), outside window (returns None),
    different object type (returns None)
  - run_process_webhook_event: dedup path (log marked deduplicated),
    loop-suppressed path (log marked loop_suppressed),
    normal processing path (dispatches fetch_and_upsert)

Uses SQLite in-memory DB (same pattern as test_hubspot_webhook_service.py).
"""
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app import create_app, db
from app.models.hubspot_webhook_log import HubSpotWebhookLog
from app.models.hubspot_platform_write import HubSpotPlatformWrite


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_ctx():
    """Flask app with an in-memory SQLite DB, no seeded data."""
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    os.environ['FLASK_ENV'] = 'testing'

    application = create_app('testing')
    application.config['TESTING'] = True

    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()

    for key in ('DATABASE_URL', 'FLASK_ENV'):
        os.environ.pop(key, None)


def _make_log(
    object_type: str,
    object_id: str,
    status: str = 'pending',
    received_at: datetime = None,
) -> HubSpotWebhookLog:
    """Helper: create and flush a HubSpotWebhookLog row."""
    log = HubSpotWebhookLog(
        hubspot_object_type=object_type,
        hubspot_object_id=object_id,
        event_type=f'{object_type}.propertyChange',
        raw_payload={'objectId': object_id},
        status=status,
        received_at=received_at or datetime.utcnow(),
    )
    db.session.add(log)
    db.session.flush()
    return log


# ---------------------------------------------------------------------------
# Tests: is_duplicate
# ---------------------------------------------------------------------------

class TestIsDuplicate:
    """is_duplicate returns the newer log_id when a duplicate exists within the window."""

    def test_returns_newer_log_id_within_window(self, app_ctx):
        """A newer log for the same object within the dedup window → returns its id."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import is_duplicate

            # Older log (lower id)
            older = _make_log('deal', '111', status='pending')
            # Newer log (higher id, same object, within window)
            newer = _make_log('deal', '111', status='pending')
            db.session.commit()

            result = is_duplicate('deal', '111', older.id)
            assert result == newer.id

    def test_returns_none_outside_window(self, app_ctx):
        """A newer log outside the dedup window → returns None."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import is_duplicate

            # Older log with received_at far in the past
            far_past = datetime.utcnow() - timedelta(seconds=120)
            older = _make_log('deal', '222', status='pending', received_at=far_past)

            # Newer log also in the past (outside the 60s window)
            slightly_less_past = datetime.utcnow() - timedelta(seconds=90)
            newer = _make_log('deal', '222', status='pending', received_at=slightly_less_past)
            db.session.commit()

            # Patch DEDUP_WINDOW_SECONDS to 60 (default) — both logs are outside the window
            with patch('app.tasks.hubspot_webhook_tasks.DEDUP_WINDOW_SECONDS', 60):
                result = is_duplicate('deal', '222', older.id)
            assert result is None

    def test_returns_none_for_different_object_type(self, app_ctx):
        """A newer log for a different object type → returns None."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import is_duplicate

            older = _make_log('deal', '333', status='pending')
            # Newer log for a DIFFERENT object type with the same object_id
            _make_log('contact', '333', status='pending')
            db.session.commit()

            result = is_duplicate('deal', '333', older.id)
            assert result is None

    def test_returns_none_when_no_newer_log(self, app_ctx):
        """No newer log for the same object → returns None."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import is_duplicate

            log = _make_log('deal', '444', status='pending')
            db.session.commit()

            result = is_duplicate('deal', '444', log.id)
            assert result is None

    def test_ignores_failed_and_deduplicated_statuses(self, app_ctx):
        """Newer logs with status 'failed' or 'deduplicated' are not considered duplicates."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import is_duplicate

            older = _make_log('deal', '555', status='pending')
            _make_log('deal', '555', status='failed')
            _make_log('deal', '555', status='deduplicated')
            db.session.commit()

            result = is_duplicate('deal', '555', older.id)
            assert result is None

    def test_returns_none_for_different_object_id(self, app_ctx):
        """A newer log for a different object_id → returns None."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import is_duplicate

            older = _make_log('deal', '666', status='pending')
            _make_log('deal', '777', status='pending')  # different object_id
            db.session.commit()

            result = is_duplicate('deal', '666', older.id)
            assert result is None


# ---------------------------------------------------------------------------
# Tests: run_process_webhook_event — dedup path
# ---------------------------------------------------------------------------

class TestRunProcessWebhookEventDedup:
    """run_process_webhook_event marks the log as 'deduplicated' when a newer event exists."""

    def test_dedup_path_marks_log_deduplicated(self, app_ctx):
        """When is_duplicate returns a newer id, the log is marked deduplicated."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import _process_webhook_event_inner

            # Create the log to process
            log = _make_log('deal', '100', status='pending')
            # Create a newer log for the same object
            newer = _make_log('deal', '100', status='pending')
            db.session.commit()

            log_id = log.id
            newer_id = newer.id

            # Patch fetch_and_upsert_record.delay so it's never called
            with patch('celery_worker.fetch_and_upsert_record') as mock_task:
                mock_task.delay = MagicMock()
                _process_webhook_event_inner(log_id)

            db.session.expire_all()
            updated_log = HubSpotWebhookLog.query.get(log_id)
            assert updated_log.status == 'deduplicated'
            assert updated_log.superseded_by_log_id == newer_id
            mock_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: run_process_webhook_event — loop suppressed path
# ---------------------------------------------------------------------------

class TestRunProcessWebhookEventLoopSuppressed:
    """run_process_webhook_event marks the log as 'loop_suppressed' when a platform write exists."""

    def test_loop_suppressed_path(self, app_ctx):
        """When is_loop_event returns True, the log is marked loop_suppressed."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import _process_webhook_event_inner

            log = _make_log('deal', '200', status='pending')
            db.session.commit()
            log_id = log.id

            # Seed a recent platform write for this object
            write = HubSpotPlatformWrite(
                object_type='deal',
                hubspot_id='200',
                written_at=datetime.utcnow(),
            )
            db.session.add(write)
            db.session.commit()

            with patch('celery_worker.fetch_and_upsert_record') as mock_task:
                mock_task.delay = MagicMock()
                _process_webhook_event_inner(log_id)

            db.session.expire_all()
            updated_log = HubSpotWebhookLog.query.get(log_id)
            assert updated_log.status == 'loop_suppressed'
            mock_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: run_process_webhook_event — normal processing path
# ---------------------------------------------------------------------------

class TestRunProcessWebhookEventNormal:
    """run_process_webhook_event dispatches fetch_and_upsert when no dedup/loop condition."""

    def test_normal_path_dispatches_fetch_and_upsert(self, app_ctx):
        """When no dedup or loop condition, fetch_and_upsert_record.delay is called."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import _process_webhook_event_inner

            log = _make_log('deal', '300', status='pending')
            db.session.commit()
            log_id = log.id

            mock_delay = MagicMock()
            with patch('celery_worker.fetch_and_upsert_record') as mock_task:
                mock_task.delay = mock_delay
                _process_webhook_event_inner(log_id)

            # Log should be in 'processing' state (fetch_and_upsert will update it further)
            db.session.expire_all()
            updated_log = HubSpotWebhookLog.query.get(log_id)
            # Status is 'processing' because fetch_and_upsert hasn't run yet
            assert updated_log.status == 'processing'
            mock_delay.assert_called_once_with('deal', '300', log_id)

    def test_normal_path_log_not_found_returns_gracefully(self, app_ctx):
        """When the log_id doesn't exist, the function returns without error."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import _process_webhook_event_inner

            # Should not raise
            _process_webhook_event_inner(99999)


def test_contact_fetch_includes_additional_phone_numbers():
    from app.tasks.hubspot_webhook_tasks import _OBJECT_TYPE_CONFIG

    props = _OBJECT_TYPE_CONFIG['contact']['params']['properties']
    assert 'additional_phone_numbers' in props
    assert 'hs_additional_emails' in props
