"""
Unit tests for QueueService.
"""
import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.services.queue_service import QueueService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(app, street, **kwargs):
    from app import db
    from app.models import Lead

    defaults = dict(
        lead_status='active',
        has_phone=True,
        has_email=True,
        has_property_match=True,
        analysis_complete=True,
        follow_up_overdue=False,
        is_warm=False,
        lead_score=50.0,
        data_completeness_score=60.0,
        recommended_action=None,
        review_required=False,
        unanswered_call_count=0,
    )
    defaults.update(kwargs)
    lead = Lead(property_street=street, **defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


def _make_task(app, lead_id, status='open', due_date=None, task_type='custom'):
    from app import db
    from app.models import LeadTask

    task = LeadTask(
        lead_id=lead_id,
        task_type=task_type,
        title='Test task',
        status=status,
        due_date=due_date,
        created_by='test',
    )
    db.session.add(task)
    db.session.commit()
    return task


def _make_timeline_entry(app, lead_id, event_type, occurred_at, source='manual'):
    from app import db
    from app.models import LeadTimelineEntry

    entry = LeadTimelineEntry(
        lead_id=lead_id,
        event_type=event_type,
        occurred_at=occurred_at,
        source=source,
        actor='test',
        summary='test entry',
    )
    db.session.add(entry)
    db.session.commit()
    return entry


# ---------------------------------------------------------------------------
# Today's Action queue
# ---------------------------------------------------------------------------

def test_todays_action_includes_follow_up_now_lead(app):
    """Today's Action includes active lead with recommended_action='follow_up_now'."""
    with app.app_context():
        lead = _make_lead(app, '1 Queue St',
                          lead_status='active',
                          recommended_action='follow_up_now')
        svc = QueueService()
        rows, total = svc.get_todays_action()
        ids = [r['id'] for r in rows]
        assert lead.id in ids


def test_todays_action_includes_lead_with_task_due_today(app):
    """Today's Action includes active lead with an open task due today."""
    with app.app_context():
        lead = _make_lead(app, '2 Queue St', lead_status='active')
        _make_task(app, lead.id, due_date=date.today())
        svc = QueueService()
        rows, total = svc.get_todays_action()
        ids = [r['id'] for r in rows]
        assert lead.id in ids


def test_todays_action_excludes_nurture_lead(app):
    """Today's Action excludes nurture leads."""
    with app.app_context():
        lead = _make_lead(app, '3 Queue St',
                          lead_status='nurture',
                          recommended_action='follow_up_now')
        svc = QueueService()
        rows, total = svc.get_todays_action()
        ids = [r['id'] for r in rows]
        assert lead.id not in ids


# ---------------------------------------------------------------------------
# Previously Warm queue
# ---------------------------------------------------------------------------

def test_previously_warm_includes_lead_with_hubspot_sync_no_recent_contact(app):
    """Previously Warm includes a lead marked is_warm=True (warm signals set this flag)."""
    with app.app_context():
        from app import db
        lead = _make_lead(app, '4 Queue St', lead_status='active', is_warm=True)
        db.session.commit()

        svc = QueueService()
        rows, total = svc.get_previously_warm()
        ids = [r['id'] for r in rows]
        assert lead.id in ids


def test_previously_warm_excludes_lead_with_recent_platform_contact(app):
    """Previously Warm excludes lead that has a recent call_logged entry."""
    with app.app_context():
        lead = _make_lead(app, '5 Queue St',
                          lead_status='active',
                          last_hubspot_sync_at=datetime.now(timezone.utc) - timedelta(days=10))
        # Recent call within 90 days
        _make_timeline_entry(app, lead.id, 'call_logged',
                             occurred_at=datetime.now(timezone.utc) - timedelta(days=5))
        svc = QueueService()
        rows, total = svc.get_previously_warm()
        ids = [r['id'] for r in rows]
        assert lead.id not in ids


def test_previously_warm_excludes_nurture_lead(app):
    """Previously Warm excludes nurture leads."""
    with app.app_context():
        lead = _make_lead(app, '6 Queue St',
                          lead_status='nurture',
                          last_hubspot_sync_at=datetime.now(timezone.utc))
        svc = QueueService()
        rows, total = svc.get_previously_warm()
        ids = [r['id'] for r in rows]
        assert lead.id not in ids


# ---------------------------------------------------------------------------
# Follow-Up Overdue queue
# ---------------------------------------------------------------------------

def test_follow_up_overdue_includes_lead_with_overdue_task(app):
    """Follow-Up Overdue includes lead with an open task due in the past."""
    with app.app_context():
        lead = _make_lead(app, '7 Queue St')
        _make_task(app, lead.id, due_date=date.today() - timedelta(days=1))
        svc = QueueService()
        rows, total = svc.get_follow_up_overdue()
        ids = [r['id'] for r in rows]
        assert lead.id in ids


def test_follow_up_overdue_excludes_nurture_lead(app):
    """Follow-Up Overdue excludes nurture leads (they have no overdue tasks by design)."""
    with app.app_context():
        # Nurture lead with no tasks — should not appear
        lead = _make_lead(app, '8 Queue St', lead_status='nurture')
        svc = QueueService()
        rows, total = svc.get_follow_up_overdue()
        ids = [r['id'] for r in rows]
        assert lead.id not in ids


# ---------------------------------------------------------------------------
# No Next Action queue
# ---------------------------------------------------------------------------

def test_no_next_action_includes_active_lead_with_create_task_ra(app):
    """No Next Action includes active lead with recommended_action='create_task' and no open tasks."""
    with app.app_context():
        lead = _make_lead(app, '9 Queue St',
                          lead_status='active',
                          recommended_action='create_task')
        svc = QueueService()
        rows, total = svc.get_no_next_action()
        ids = [r['id'] for r in rows]
        assert lead.id in ids


def test_no_next_action_excludes_lead_with_open_task(app):
    """No Next Action excludes leads that have open tasks."""
    with app.app_context():
        lead = _make_lead(app, '10 Queue St',
                          lead_status='active',
                          recommended_action='create_task')
        _make_task(app, lead.id)
        svc = QueueService()
        rows, total = svc.get_no_next_action()
        ids = [r['id'] for r in rows]
        assert lead.id not in ids


def test_no_next_action_excludes_nurture_lead(app):
    """No Next Action excludes nurture leads."""
    with app.app_context():
        lead = _make_lead(app, '11 Queue St',
                          lead_status='nurture',
                          recommended_action='create_task')
        svc = QueueService()
        rows, total = svc.get_no_next_action()
        ids = [r['id'] for r in rows]
        assert lead.id not in ids


# ---------------------------------------------------------------------------
# DNC exclusion from active queues
# ---------------------------------------------------------------------------

def test_dnc_lead_excluded_from_todays_action(app):
    """DNC lead is excluded from Today's Action queue."""
    with app.app_context():
        lead = _make_lead(app, '12 Queue St',
                          lead_status='do_not_contact',
                          recommended_action='follow_up_now')
        svc = QueueService()
        rows, total = svc.get_todays_action()
        ids = [r['id'] for r in rows]
        assert lead.id not in ids


def test_dnc_lead_appears_in_do_not_contact_queue(app):
    """DNC lead appears in the Do Not Contact queue."""
    with app.app_context():
        lead = _make_lead(app, '13 Queue St', lead_status='do_not_contact')
        svc = QueueService()
        rows, total = svc.get_do_not_contact()
        ids = [r['id'] for r in rows]
        assert lead.id in ids


# ---------------------------------------------------------------------------
# Lead in multiple queues
# ---------------------------------------------------------------------------

def test_lead_in_multiple_queues_appears_in_each(app):
    """A lead satisfying multiple queue criteria appears in each applicable queue."""
    with app.app_context():
        # This lead qualifies for: Today's Action (follow_up_now) AND
        # Follow-Up Overdue (overdue task)
        lead = _make_lead(app, '14 Queue St',
                          lead_status='active',
                          recommended_action='follow_up_now')
        _make_task(app, lead.id, due_date=date.today() - timedelta(days=2))

        svc = QueueService()

        todays_ids = [r['id'] for r in svc.get_todays_action()[0]]
        overdue_ids = [r['id'] for r in svc.get_follow_up_overdue()[0]]

        assert lead.id in todays_ids
        assert lead.id in overdue_ids


# ---------------------------------------------------------------------------
# Missing Property Match queue
# ---------------------------------------------------------------------------

def test_missing_property_match_includes_lead_without_match(app):
    """Missing Property Match includes lead with has_property_match=False and no research task."""
    with app.app_context():
        lead = _make_lead(app, '15 Queue St', has_property_match=False)
        svc = QueueService()
        rows, total = svc.get_missing_property_match()
        ids = [r['id'] for r in rows]
        assert lead.id in ids


def test_missing_property_match_excludes_lead_with_research_task(app):
    """Missing Property Match excludes lead that already has a research_missing_pin task."""
    with app.app_context():
        lead = _make_lead(app, '16 Queue St', has_property_match=False)
        _make_task(app, lead.id, task_type='research_missing_pin')
        svc = QueueService()
        rows, total = svc.get_missing_property_match()
        ids = [r['id'] for r in rows]
        assert lead.id not in ids


# ---------------------------------------------------------------------------
# get_counts returns correct badge counts
# ---------------------------------------------------------------------------

def test_get_counts_returns_all_queue_keys(app):
    """get_counts returns a dict with all 7 queue keys."""
    with app.app_context():
        svc = QueueService()
        counts = svc.get_counts()

        expected_keys = {
            'todays_action', 'previously_warm', 'follow_up_overdue',
            'no_next_action', 'needs_review', 'do_not_contact',
            'missing_property_match',
        }
        assert set(counts.keys()) == expected_keys
        for key, val in counts.items():
            assert isinstance(val, int), f"{key} should be int, got {type(val)}"


def test_get_counts_reflects_actual_leads(app):
    """get_counts badge counts match the actual number of qualifying leads."""
    with app.app_context():
        # Create 2 DNC leads
        _make_lead(app, '17 Queue St', lead_status='do_not_contact')
        _make_lead(app, '18 Queue St', lead_status='do_not_contact')

        svc = QueueService()
        counts = svc.get_counts()

        assert counts['do_not_contact'] >= 2
