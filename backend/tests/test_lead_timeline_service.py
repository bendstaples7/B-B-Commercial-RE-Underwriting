"""
Unit tests for LeadTimelineService.
"""
import pytest
from datetime import datetime, timezone

from app.services.lead_timeline_service import LeadTimelineService
from app.exceptions import ResourceNotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(app, street='Timeline Test St'):
    from app import db
    from app.models import Lead

    lead = Lead(
        property_street=street,
        lead_status='mailing_no_contact_made',
        has_phone=True,
        has_email=True,
        has_property_match=True,
        analysis_complete=True,
        lead_score=50.0,
        data_completeness_score=60.0,
    )
    db.session.add(lead)
    db.session.commit()
    return lead


# ---------------------------------------------------------------------------
# append
# ---------------------------------------------------------------------------

def test_append_creates_entry_with_correct_fields(app):
    """append creates a LeadTimelineEntry with the correct fields."""
    with app.app_context():
        lead = _make_lead(app, '1 Append St')
        svc = LeadTimelineService()

        entry = svc.append(
            lead_id=lead.id,
            event_type='note_added',
            actor='test_user',
            summary='Test note',
            metadata={'key': 'value'},
            source='manual',
        )

        assert entry.id is not None
        assert entry.lead_id == lead.id
        assert entry.event_type == 'note_added'
        assert entry.actor == 'test_user'
        assert entry.summary == 'Test note'
        assert entry.event_metadata == {'key': 'value'}
        assert entry.source == 'manual'
        assert entry.is_deleted is False


def test_append_uses_provided_occurred_at(app):
    """append uses the provided occurred_at timestamp."""
    with app.app_context():
        lead = _make_lead(app, '2 Append St')
        svc = LeadTimelineService()

        ts = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        entry = svc.append(
            lead_id=lead.id,
            event_type='call_logged',
            actor='agent',
            summary='Called owner',
            occurred_at=ts,
        )

        # SQLite strips timezone info; compare naive datetimes
        stored = entry.occurred_at
        if stored.tzinfo is not None:
            assert stored == ts
        else:
            assert stored == ts.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# get_page — reverse-chronological order
# ---------------------------------------------------------------------------

def test_get_page_returns_reverse_chronological_order(app):
    """get_page returns entries in reverse-chronological order (newest first)."""
    with app.app_context():
        lead = _make_lead(app, '3 Page St')
        svc = LeadTimelineService()

        t1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
        t3 = datetime(2024, 1, 3, tzinfo=timezone.utc)

        svc.append(lead.id, 'note_added', 'u', 'First', occurred_at=t1)
        svc.append(lead.id, 'note_added', 'u', 'Second', occurred_at=t2)
        svc.append(lead.id, 'note_added', 'u', 'Third', occurred_at=t3)

        entries, total = svc.get_page(lead.id, page=1, per_page=10)

        assert total == 3
        summaries = [e.summary for e in entries]
        assert summaries == ['Third', 'Second', 'First']


def test_get_page_excludes_soft_deleted_entries(app):
    """get_page excludes soft-deleted entries."""
    with app.app_context():
        lead = _make_lead(app, '4 Page St')
        svc = LeadTimelineService()

        e1 = svc.append(lead.id, 'note_added', 'u', 'Visible note')
        e2 = svc.append(lead.id, 'note_added', 'u', 'To be deleted')

        svc.soft_delete(e2.id, actor='u')

        entries, total = svc.get_page(lead.id, page=1, per_page=10)
        summaries = [e.summary for e in entries]

        assert total == 1
        assert 'Visible note' in summaries
        assert '[deleted]' not in summaries


# ---------------------------------------------------------------------------
# soft_delete
# ---------------------------------------------------------------------------

def test_soft_delete_replaces_summary_with_deleted(app):
    """soft_delete replaces summary with '[deleted]' and sets is_deleted=True."""
    with app.app_context():
        lead = _make_lead(app, '5 Delete St')
        svc = LeadTimelineService()

        entry = svc.append(lead.id, 'note_added', 'u', 'Original summary')
        deleted = svc.soft_delete(entry.id, actor='u')

        assert deleted.summary == '[deleted]'
        assert deleted.is_deleted is True
        # Preserves key fields
        assert deleted.id == entry.id
        assert deleted.lead_id == lead.id
        assert deleted.event_type == 'note_added'
        assert deleted.actor == 'u'


def test_soft_delete_preserves_entry_in_db(app):
    """soft_delete keeps the entry in the database (audit trail preserved)."""
    from app.models import LeadTimelineEntry

    with app.app_context():
        lead = _make_lead(app, '6 Delete St')
        svc = LeadTimelineService()

        entry = svc.append(lead.id, 'note_added', 'u', 'Keep me')
        entry_id = entry.id
        svc.soft_delete(entry_id, actor='u')

        db_entry = LeadTimelineEntry.query.get(entry_id)
        assert db_entry is not None
        assert db_entry.summary == '[deleted]'


def test_soft_delete_hubspot_entry_raises_error(app):
    """soft_delete on a HubSpot-sourced entry raises ValueError."""
    with app.app_context():
        lead = _make_lead(app, '7 Delete St')
        svc = LeadTimelineService()

        entry = svc.append(
            lead.id,
            'hubspot_call',
            'HubSpot',
            'HubSpot call',
            source='hubspot',
            hubspot_activity_id='hs-001',
        )

        with pytest.raises(ValueError, match="HubSpot"):
            svc.soft_delete(entry.id, actor='u')

