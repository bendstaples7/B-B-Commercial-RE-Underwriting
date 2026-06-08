"""
Unit tests for LeadTaskService.
"""
import pytest
from datetime import date, timedelta
from unittest.mock import patch

from app.services.lead_task_service import LeadTaskService
from app.exceptions import LeadTaskValidationError

# ActionEngineService is lazily imported inside service functions, so we patch
# the canonical location rather than the service module's namespace.
_AE_PATCH = 'app.services.action_engine_service.ActionEngineService.recompute_and_persist'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(app, **kwargs):
    """Create and persist a minimal Lead for testing."""
    from app import db
    from app.models import Lead

    defaults = dict(
        property_street=None,
        lead_status='mailing_no_contact_made',
        has_phone=True,
        has_email=True,
        has_property_match=True,
        analysis_complete=True,
        follow_up_overdue=False,
        is_warm=False,
        lead_score=50.0,
        data_completeness_score=60.0,
    )
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------

def test_create_sets_status_open(app):
    """Task creation sets status='open'."""
    from app import db

    with app.app_context():
        lead = _make_lead(app, property_street='1 Create St')
        svc = LeadTaskService()

        with patch(_AE_PATCH):
            task = svc.create(lead.id, {'title': 'Call owner', 'task_type': 'custom'})

        assert task.status == 'open'
        assert task.lead_id == lead.id
        assert task.title == 'Call owner'


def test_create_appends_task_created_timeline_entry(app):
    """Task creation appends a task_created timeline entry."""
    from app import db
    from app.models import LeadTimelineEntry

    with app.app_context():
        lead = _make_lead(app, property_street='2 Create St')
        svc = LeadTaskService()

        with patch(_AE_PATCH):
            task = svc.create(lead.id, {'title': 'Research PIN'})

        entries = LeadTimelineEntry.query.filter_by(
            lead_id=lead.id, event_type='task_created'
        ).all()
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Task completion
# ---------------------------------------------------------------------------

def test_complete_open_task_sets_completed_at(app):
    """Completing an open task sets completed_at."""
    from app import db

    with app.app_context():
        lead = _make_lead(app, property_street='3 Complete St')
        svc = LeadTaskService()

        with patch(_AE_PATCH):
            task = svc.create(lead.id, {'title': 'Follow up call'})
            completed = svc.complete(task.id, lead.id)

        assert completed.status == 'completed'
        assert completed.completed_at is not None


def test_complete_completed_task_is_noop(app):
    """Completing an already-completed task is a no-op (returns task unchanged)."""
    from app import db

    with app.app_context():
        lead = _make_lead(app, property_street='4 Noop St')
        svc = LeadTaskService()

        with patch(_AE_PATCH):
            task = svc.create(lead.id, {'title': 'Already done'})
            first = svc.complete(task.id, lead.id)
            first_completed_at = first.completed_at

            second = svc.complete(task.id, lead.id)

        assert second.status == 'completed'
        assert second.completed_at == first_completed_at


# ---------------------------------------------------------------------------
# Snooze validation
# ---------------------------------------------------------------------------

def test_snooze_with_past_date_raises_validation_error(app):
    """Snooze with a past date raises LeadTaskValidationError."""
    from app import db

    with app.app_context():
        lead = _make_lead(app, property_street='5 Snooze St')
        svc = LeadTaskService()

        with patch(_AE_PATCH):
            task = svc.create(lead.id, {'title': 'Snooze me'})

        past_date = date.today() - timedelta(days=1)
        with pytest.raises(LeadTaskValidationError):
            svc.snooze(task.id, lead.id, past_date)


def test_snooze_with_today_raises_validation_error(app):
    """Snooze with today's date raises LeadTaskValidationError (must be strictly after today)."""
    from app import db

    with app.app_context():
        lead = _make_lead(app, property_street='6 Snooze St')
        svc = LeadTaskService()

        with patch(_AE_PATCH):
            task = svc.create(lead.id, {'title': 'Snooze today'})

        with pytest.raises(LeadTaskValidationError):
            svc.snooze(task.id, lead.id, date.today())


def test_snooze_with_future_date_succeeds(app):
    """Snooze with a future date updates due_date."""
    from app import db

    with app.app_context():
        lead = _make_lead(app, property_street='7 Snooze St')
        svc = LeadTaskService()

        with patch(_AE_PATCH):
            task = svc.create(lead.id, {'title': 'Snooze future'})

        future_date = date.today() + timedelta(days=3)
        snoozed = svc.snooze(task.id, lead.id, future_date)
        assert snoozed.due_date == future_date


# ---------------------------------------------------------------------------
# list_open ordering
# ---------------------------------------------------------------------------

def test_list_open_orders_by_due_date_asc_nulls_last(app):
    """list_open returns tasks ordered by due_date asc, nulls last."""
    from app import db

    with app.app_context():
        lead = _make_lead(app, property_street='8 Order St')
        svc = LeadTaskService()

        today = date.today()
        future1 = today + timedelta(days=1)
        future2 = today + timedelta(days=5)

        with patch(_AE_PATCH):
            t_null = svc.create(lead.id, {'title': 'No due date'})
            t_far = svc.create(lead.id, {'title': 'Far future', 'due_date': future2})
            t_near = svc.create(lead.id, {'title': 'Near future', 'due_date': future1})

        tasks = svc.list_open(lead.id)
        titles = [t.title for t in tasks]

        # near future first, far future second, null last
        assert titles.index('Near future') < titles.index('Far future')
        assert titles.index('Far future') < titles.index('No due date')

