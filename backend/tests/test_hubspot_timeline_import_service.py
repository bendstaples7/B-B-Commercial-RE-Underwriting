"""
Unit tests for HubSpotTimelineImportService.
"""
import pytest
from datetime import datetime, timedelta, timezone

from app.services.hubspot_timeline_import_service import HubSpotTimelineImportService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(app, street='HubSpot Test St'):
    from app import db
    from app.models import Lead

    lead = Lead(
        property_street=street,
        lead_status='active',
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


def _make_activity(activity_id, activity_type='CALL', body='Test activity',
                   occurred_at=None, outcome=None):
    """Build a minimal HubSpot activity dict."""
    ts = occurred_at or datetime.now(timezone.utc).isoformat()
    activity = {
        'id': activity_id,
        'type': activity_type,
        'body': body,
        'occurred_at': ts,
    }
    if outcome:
        activity['outcome'] = outcome
    return activity


# ---------------------------------------------------------------------------
# Importing activities creates entries with source='hubspot'
# ---------------------------------------------------------------------------

def test_import_creates_entries_with_hubspot_source(app):
    """Importing activities creates LeadTimelineEntry rows with source='hubspot'."""
    from app.models import LeadTimelineEntry

    with app.app_context():
        lead = _make_lead(app, '1 HubSpot St')
        svc = HubSpotTimelineImportService()

        activities = [
            _make_activity('hs-001', 'CALL', 'Called owner'),
            _make_activity('hs-002', 'NOTE', 'Left voicemail'),
        ]
        count = svc.import_activities_for_lead(lead.id, activities)

        assert count == 2
        entries = LeadTimelineEntry.query.filter_by(
            lead_id=lead.id, source='hubspot'
        ).all()
        assert len(entries) == 2
        for entry in entries:
            assert entry.source == 'hubspot'
            assert entry.actor == 'HubSpot'


def test_import_maps_call_type_to_hubspot_call_event(app):
    """CALL activity type maps to event_type='hubspot_call'."""
    from app.models import LeadTimelineEntry

    with app.app_context():
        lead = _make_lead(app, '2 HubSpot St')
        svc = HubSpotTimelineImportService()

        svc.import_activities_for_lead(lead.id, [_make_activity('hs-003', 'CALL')])

        entry = LeadTimelineEntry.query.filter_by(
            lead_id=lead.id, hubspot_activity_id='hs-003'
        ).first()
        assert entry is not None
        assert entry.event_type == 'hubspot_call'


def test_import_maps_note_type_to_hubspot_note_event(app):
    """NOTE activity type maps to event_type='hubspot_note'."""
    from app.models import LeadTimelineEntry

    with app.app_context():
        lead = _make_lead(app, '3 HubSpot St')
        svc = HubSpotTimelineImportService()

        svc.import_activities_for_lead(lead.id, [_make_activity('hs-004', 'NOTE')])

        entry = LeadTimelineEntry.query.filter_by(
            lead_id=lead.id, hubspot_activity_id='hs-004'
        ).first()
        assert entry is not None
        assert entry.event_type == 'hubspot_note'


# ---------------------------------------------------------------------------
# Re-importing same activities creates zero new entries
# ---------------------------------------------------------------------------

def test_reimport_same_activities_creates_zero_new_entries(app):
    """Re-importing the same activities is idempotent — no new entries created."""
    from app.models import LeadTimelineEntry

    with app.app_context():
        lead = _make_lead(app, '4 HubSpot St')
        svc = HubSpotTimelineImportService()

        activities = [
            _make_activity('hs-005', 'CALL', 'First import'),
            _make_activity('hs-006', 'NOTE', 'First import note'),
        ]

        first_count = svc.import_activities_for_lead(lead.id, activities)
        second_count = svc.import_activities_for_lead(lead.id, activities)

        assert first_count == 2
        assert second_count == 0

        total_entries = LeadTimelineEntry.query.filter_by(
            lead_id=lead.id, source='hubspot'
        ).count()
        assert total_entries == 2


def test_reimport_partial_overlap_only_creates_new_entries(app):
    """Re-importing with some new activities only creates entries for new ones."""
    with app.app_context():
        lead = _make_lead(app, '5 HubSpot St')
        svc = HubSpotTimelineImportService()

        first_batch = [_make_activity('hs-007', 'CALL')]
        second_batch = [
            _make_activity('hs-007', 'CALL'),   # duplicate
            _make_activity('hs-008', 'NOTE'),   # new
        ]

        svc.import_activities_for_lead(lead.id, first_batch)
        new_count = svc.import_activities_for_lead(lead.id, second_batch)

        assert new_count == 1


# ---------------------------------------------------------------------------
# derive_is_warm
# ---------------------------------------------------------------------------

def test_derive_is_warm_true_with_connected_call_within_180_days(app):
    """derive_is_warm returns True when a connected call exists within 180 days."""
    with app.app_context():
        lead = _make_lead(app, '6 HubSpot St')
        svc = HubSpotTimelineImportService()

        recent_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        activities = [
            _make_activity('hs-009', 'CALL', 'Connected call',
                           occurred_at=recent_ts, outcome='connected'),
        ]
        svc.import_activities_for_lead(lead.id, activities)

        assert svc.derive_is_warm(lead.id) is True


def test_derive_is_warm_true_with_answered_outcome(app):
    """derive_is_warm returns True for outcome='answered' (treated as connected)."""
    with app.app_context():
        lead = _make_lead(app, '7 HubSpot St')
        svc = HubSpotTimelineImportService()

        recent_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        activities = [
            _make_activity('hs-010', 'CALL', 'Answered call',
                           occurred_at=recent_ts, outcome='answered'),
        ]
        svc.import_activities_for_lead(lead.id, activities)

        assert svc.derive_is_warm(lead.id) is True


def test_derive_is_warm_false_with_no_calls(app):
    """derive_is_warm returns False when no HubSpot call entries exist."""
    with app.app_context():
        lead = _make_lead(app, '8 HubSpot St')
        svc = HubSpotTimelineImportService()

        # Only import a note, no calls
        activities = [_make_activity('hs-011', 'NOTE', 'Just a note')]
        svc.import_activities_for_lead(lead.id, activities)

        assert svc.derive_is_warm(lead.id) is False


def test_derive_is_warm_false_with_all_calls_older_than_180_days(app):
    """derive_is_warm returns False when all connected calls are older than 180 days."""
    with app.app_context():
        lead = _make_lead(app, '9 HubSpot St')
        svc = HubSpotTimelineImportService()

        old_ts = (datetime.now(timezone.utc) - timedelta(days=181)).isoformat()
        activities = [
            _make_activity('hs-012', 'CALL', 'Old connected call',
                           occurred_at=old_ts, outcome='connected'),
        ]
        svc.import_activities_for_lead(lead.id, activities)

        assert svc.derive_is_warm(lead.id) is False


def test_derive_is_warm_false_with_voicemail_calls_only(app):
    """derive_is_warm returns False when only voicemail/no-answer calls exist."""
    with app.app_context():
        lead = _make_lead(app, '10 HubSpot St')
        svc = HubSpotTimelineImportService()

        recent_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        activities = [
            _make_activity('hs-013', 'CALL', 'Voicemail',
                           occurred_at=recent_ts, outcome='voicemail'),
            _make_activity('hs-014', 'CALL', 'No answer',
                           occurred_at=recent_ts, outcome='no_answer'),
        ]
        svc.import_activities_for_lead(lead.id, activities)

        assert svc.derive_is_warm(lead.id) is False
