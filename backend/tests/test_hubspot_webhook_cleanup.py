"""Unit tests for the webhook log cleanup job.

Tests cover:
  - run_purge_old_webhook_logs deletes records older than 30 days
  - run_purge_old_webhook_logs leaves records newer than 30 days intact
  - run_purge_old_webhook_logs returns the correct count of deleted records

Uses SQLite in-memory DB (same pattern as test_hubspot_webhook_tasks.py).
"""
import os
from datetime import datetime, timedelta

import pytest

from app import create_app, db
from app.models.hubspot_webhook_log import HubSpotWebhookLog


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
    object_type: str = 'deal',
    object_id: str = '1',
    received_at: datetime = None,
    status: str = 'processed',
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
# Tests: run_purge_old_webhook_logs
# ---------------------------------------------------------------------------

class TestRunPurgeOldWebhookLogs:
    """run_purge_old_webhook_logs deletes old records and leaves recent ones intact.

    Tests call _purge_old_webhook_logs_inner directly (same pattern as
    _process_webhook_event_inner in test_hubspot_webhook_tasks.py) to avoid
    triggering a second create_app() call inside the already-active test context.
    """

    def test_deletes_records_older_than_30_days(self, app_ctx):
        """Records with received_at older than 30 days are deleted."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import _purge_old_webhook_logs_inner

            old_time = datetime.utcnow() - timedelta(days=31)
            old_log = _make_log(object_id='100', received_at=old_time)
            old_log_id = old_log.id
            db.session.commit()

            _purge_old_webhook_logs_inner()

            db.session.expire_all()
            assert HubSpotWebhookLog.query.get(old_log_id) is None

    def test_leaves_recent_records_intact(self, app_ctx):
        """Records with received_at within the last 30 days are NOT deleted."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import _purge_old_webhook_logs_inner

            recent_time = datetime.utcnow() - timedelta(days=1)
            recent_log = _make_log(object_id='200', received_at=recent_time)
            recent_log_id = recent_log.id
            db.session.commit()

            _purge_old_webhook_logs_inner()

            db.session.expire_all()
            assert HubSpotWebhookLog.query.get(recent_log_id) is not None

    def test_returns_correct_deleted_count(self, app_ctx):
        """The function returns the exact number of records deleted."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import _purge_old_webhook_logs_inner

            old_time = datetime.utcnow() - timedelta(days=45)

            # Create 3 old records and 2 recent records
            for i in range(3):
                _make_log(object_id=f'old_{i}', received_at=old_time)

            recent_time = datetime.utcnow() - timedelta(hours=6)
            for i in range(2):
                _make_log(object_id=f'recent_{i}', received_at=recent_time)

            db.session.commit()

            deleted_count = _purge_old_webhook_logs_inner()

            assert deleted_count == 3

    def test_returns_zero_when_nothing_to_delete(self, app_ctx):
        """Returns 0 when there are no records older than 30 days."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import _purge_old_webhook_logs_inner

            # Only recent records
            recent_time = datetime.utcnow() - timedelta(days=10)
            _make_log(object_id='300', received_at=recent_time)
            db.session.commit()

            deleted_count = _purge_old_webhook_logs_inner()

            assert deleted_count == 0

    def test_old_deleted_recent_preserved_together(self, app_ctx):
        """Mixed batch: old records are deleted, recent records survive."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import _purge_old_webhook_logs_inner

            old_time = datetime.utcnow() - timedelta(days=60)
            recent_time = datetime.utcnow() - timedelta(days=5)

            old_log1 = _make_log(object_id='old_a', received_at=old_time)
            old_log2 = _make_log(object_id='old_b', received_at=old_time)
            recent_log = _make_log(object_id='recent_a', received_at=recent_time)

            old_id1 = old_log1.id
            old_id2 = old_log2.id
            recent_id = recent_log.id
            db.session.commit()

            deleted_count = _purge_old_webhook_logs_inner()

            db.session.expire_all()
            assert deleted_count == 2
            assert HubSpotWebhookLog.query.get(old_id1) is None
            assert HubSpotWebhookLog.query.get(old_id2) is None
            assert HubSpotWebhookLog.query.get(recent_id) is not None

    def test_boundary_exactly_30_days_old_is_deleted(self, app_ctx):
        """A record received exactly 30 days ago (plus a small buffer) is deleted."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import _purge_old_webhook_logs_inner

            # Slightly past the 30-day cutoff
            boundary_time = datetime.utcnow() - timedelta(days=30, seconds=1)
            boundary_log = _make_log(object_id='boundary', received_at=boundary_time)
            boundary_id = boundary_log.id
            db.session.commit()

            _purge_old_webhook_logs_inner()

            db.session.expire_all()
            assert HubSpotWebhookLog.query.get(boundary_id) is None

    def test_returns_zero_on_empty_table(self, app_ctx):
        """Returns 0 when the table is empty."""
        with app_ctx.app_context():
            from app.tasks.hubspot_webhook_tasks import _purge_old_webhook_logs_inner

            deleted_count = _purge_old_webhook_logs_inner()

            assert deleted_count == 0
