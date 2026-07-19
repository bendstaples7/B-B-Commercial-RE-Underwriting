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


def test_import_call_without_to_number_updates_hubspot_primary_confidence(app):
    """CRM_UI calls omit toNumber — still raise HubSpot-primary phone confidence."""
    from app import db
    from app.models.contact import Contact
    from app.models.contact_phone import ContactPhone
    from app.models.property_contact import PropertyContact

    with app.app_context():
        lead = _make_lead(app, '2b HubSpot Call Confidence St')
        contact = Contact(first_name='Sam', last_name='Owner', role='owner')
        db.session.add(contact)
        db.session.flush()
        db.session.add(PropertyContact(
            property_id=lead.id,
            contact_id=contact.id,
            role='owner',
            is_primary=True,
        ))
        primary = ContactPhone(
            contact_id=contact.id,
            value='+17732715525',
            label='other',
            notes='HubSpot primary',
            source='hubspot_import',
            confidence_score=50,
        )
        scrape = ContactPhone(
            contact_id=contact.id,
            value='7734540106',
            label='other',
            confidence_score=50,
        )
        db.session.add_all([primary, scrape])
        db.session.commit()

        svc = HubSpotTimelineImportService()
        activity = _make_activity(
            'hs-call-no-tonumber',
            'CALL',
            'Connected call',
            outcome='Connected',
        )
        # No phone_number / toNumber on the activity (CRM_UI shape).
        assert 'phone_number' not in activity
        count = svc.import_activities_for_lead(lead.id, [activity])
        assert count == 1
        db.session.commit()

        refreshed = ContactPhone.query.get(primary.id)
        assert refreshed.confidence_score == 85
        assert refreshed.last_outcome == 'answered'
        assert ContactPhone.query.get(scrape.id).confidence_score == 50


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


# ---------------------------------------------------------------------------
# Interaction → LeadTimelineEntry bridge
# ---------------------------------------------------------------------------

def _make_hubspot_interaction(lead_id, engagement_id, itype='note', body='Note body',
                              disposition=None, occurred_at=None):
    from app import db
    from app.models import Interaction, InteractionAssociation

    raw = {}
    if disposition:
        raw = {'metadata': {'disposition': disposition}}
    interaction = Interaction(
        interaction_type=itype,
        body=body,
        occurred_at=occurred_at or datetime.now(timezone.utc).replace(tzinfo=None),
        source='hubspot_import',
        hubspot_engagement_id=engagement_id,
        raw_payload=raw or None,
        is_orphaned=False,
    )
    db.session.add(interaction)
    db.session.flush()
    db.session.add(InteractionAssociation(
        interaction_id=interaction.id,
        target_type='lead',
        target_id=lead_id,
    ))
    db.session.commit()
    return interaction


def test_interaction_to_activity_maps_note_and_call(app):
    """interaction_to_activity maps Interaction fields to HubSpot activity dicts."""
    with app.app_context():
        lead = _make_lead(app, '11 Bridge St')
        note = _make_hubspot_interaction(lead.id, 'eng-note-1', 'note', 'Hello note')
        call = _make_hubspot_interaction(
            lead.id, 'eng-call-1', 'call', 'Spoke with owner', disposition='CONNECTED'
        )
        svc = HubSpotTimelineImportService()

        note_act = svc.interaction_to_activity(note)
        call_act = svc.interaction_to_activity(call)

        assert note_act['id'] == 'eng-note-1'
        assert note_act['type'] == 'NOTE'
        assert note_act['body'] == 'Hello note'
        assert isinstance(note_act['occurred_at'], str)

        assert call_act['type'] == 'CALL'
        assert call_act['outcome'] == 'CONNECTED'
        assert call_act['disposition'] == 'CONNECTED'


def test_sync_lead_from_interactions_creates_timeline_entries(app):
    """sync_lead_from_interactions bridges HubSpot Interactions into timeline."""
    from app.models import LeadTimelineEntry

    with app.app_context():
        lead = _make_lead(app, '12 Bridge St')
        _make_hubspot_interaction(lead.id, 'eng-sync-1', 'note', 'Past HubSpot note')
        _make_hubspot_interaction(lead.id, 'eng-sync-2', 'call', 'Past HubSpot call')
        svc = HubSpotTimelineImportService()

        count = svc.sync_lead_from_interactions(lead.id, mark_review=True)

        assert count == 2
        entries = LeadTimelineEntry.query.filter_by(
            lead_id=lead.id, source='hubspot'
        ).order_by(LeadTimelineEntry.hubspot_activity_id).all()
        assert len(entries) == 2
        types = {e.event_type for e in entries}
        assert types == {'hubspot_note', 'hubspot_call'}
        assert {e.hubspot_activity_id for e in entries} == {'eng-sync-1', 'eng-sync-2'}


def test_sync_lead_from_interactions_idempotent(app):
    """Re-syncing the same interactions creates zero new entries."""
    with app.app_context():
        lead = _make_lead(app, '13 Bridge St')
        _make_hubspot_interaction(lead.id, 'eng-idemp-1', 'note', 'Once')
        svc = HubSpotTimelineImportService()

        first = svc.sync_lead_from_interactions(lead.id, mark_review=False)
        second = svc.sync_lead_from_interactions(lead.id, mark_review=False)

        assert first == 1
        assert second == 0


def test_mark_review_false_skips_review_required(app):
    """Historical backfill with mark_review=False leaves review_required alone."""
    from app.models import Lead

    with app.app_context():
        lead = _make_lead(app, '14 Bridge St')
        assert lead.review_required is not True
        _make_hubspot_interaction(lead.id, 'eng-review-1', 'note', 'Old note')
        svc = HubSpotTimelineImportService()

        svc.sync_lead_from_interactions(lead.id, mark_review=False)

        refreshed = Lead.query.get(lead.id)
        assert refreshed.review_required is not True


def test_mark_review_skips_old_history_flood(app):
    """mark_review=True only flags Needs Review for newly imported recent entries."""
    from app.models import Lead
    from datetime import timedelta

    with app.app_context():
        lead = _make_lead(app, '14b Bridge St')
        old = datetime.now(timezone.utc) - timedelta(days=400)
        _make_hubspot_interaction(
            lead.id, 'eng-old-hist-1', 'note', 'Ancient note', occurred_at=old
        )
        svc = HubSpotTimelineImportService()
        count = svc.sync_lead_from_interactions(lead.id, mark_review=True)
        assert count == 1
        refreshed = Lead.query.get(lead.id)
        assert refreshed.review_required is not True
        assert refreshed.review_reason is None


def test_global_hubspot_activity_id_dedupe_skips_other_lead(app):
    """Skip insert when hubspot_activity_id already exists on another lead."""
    from app import db
    from app.models import InteractionAssociation, LeadTimelineEntry

    with app.app_context():
        lead_a = _make_lead(app, '15a Bridge St')
        lead_b = _make_lead(app, '15b Bridge St')
        interaction = _make_hubspot_interaction(lead_a.id, 'eng-shared-1', 'note', 'Shared')
        # Same engagement associated to a second lead (multi-match)
        db.session.add(InteractionAssociation(
            interaction_id=interaction.id,
            target_type='lead',
            target_id=lead_b.id,
        ))
        db.session.commit()
        svc = HubSpotTimelineImportService()

        assert svc.sync_lead_from_interactions(lead_a.id, mark_review=False) == 1
        assert svc.sync_lead_from_interactions(lead_b.id, mark_review=False) == 0
        assert LeadTimelineEntry.query.filter_by(
            hubspot_activity_id='eng-shared-1'
        ).count() == 1


def test_sync_strips_html_from_summary(app):
    """HubSpot HTML bodies become plain-text timeline summaries."""
    from app.models import LeadTimelineEntry

    with app.app_context():
        lead = _make_lead(app, '16 Html St')
        html_body = (
            '<div style="" dir="auto" data-top-level="true">'
            '<p style="margin:0;">Left a voicemail.</p></div>'
        )
        _make_hubspot_interaction(lead.id, 'eng-html-1', 'call', html_body)
        svc = HubSpotTimelineImportService()

        assert svc.sync_lead_from_interactions(lead.id, mark_review=False) == 1
        entry = LeadTimelineEntry.query.filter_by(
            hubspot_activity_id='eng-html-1'
        ).first()
        assert entry is not None
        assert entry.summary == 'Left a voicemail.'
        assert '<' not in entry.summary
        assert entry.event_metadata.get('body') == 'Left a voicemail.'


def test_scrub_html_from_hubspot_entries(app):
    """scrub_html_from_hubspot_entries rewrites existing HTML summaries."""
    from app import db
    from app.models import LeadTimelineEntry

    with app.app_context():
        lead = _make_lead(app, '17 Scrub St')
        dirty = (
            '<div style="" dir="auto"><p style="margin:0;">Called owner.</p></div>'
        )
        entry = LeadTimelineEntry(
            lead_id=lead.id,
            event_type='hubspot_call',
            occurred_at=datetime.now(timezone.utc),
            source='hubspot',
            actor='HubSpot',
            summary=dirty,
            event_metadata={'id': 'eng-scrub-1', 'type': 'CALL', 'body': dirty},
            hubspot_activity_id='eng-scrub-1',
        )
        db.session.add(entry)
        db.session.commit()

        svc = HubSpotTimelineImportService()
        updated = svc.scrub_html_from_hubspot_entries(lead_id=lead.id)
        assert updated == 1
        refreshed = LeadTimelineEntry.query.get(entry.id)
        assert refreshed.summary == 'Called owner.'
        assert refreshed.event_metadata['body'] == 'Called owner.'


def test_scrub_rewrites_disposition_uuid_summary(app):
    """Bare HubSpot disposition GUIDs become readable call summaries."""
    from app import db
    from app.models import Interaction, LeadTimelineEntry

    with app.app_context():
        lead = _make_lead(app, '18 Guid St')
        disposition = '73a0d17f-1163-4015-bdd5-ec830791da20'
        interaction = Interaction(
            interaction_type='call',
            body=disposition,
            occurred_at=datetime.now(timezone.utc).replace(tzinfo=None),
            source='hubspot_import',
            hubspot_engagement_id='eng-guid-1',
            raw_payload={
                'metadata': {
                    'disposition': disposition,
                    'title': 'Call with Gilberto Olivares',
                    'direction': 'OUTBOUND',
                    'status': 'COMPLETED',
                },
                'engagement': {},
            },
            is_orphaned=False,
        )
        db.session.add(interaction)
        entry = LeadTimelineEntry(
            lead_id=lead.id,
            event_type='hubspot_call',
            occurred_at=datetime.now(timezone.utc),
            source='hubspot',
            actor='HubSpot',
            summary=disposition,
            event_metadata={
                'id': 'eng-guid-1',
                'type': 'CALL',
                'body': disposition,
                'disposition': disposition,
                'outcome': disposition,
            },
            hubspot_activity_id='eng-guid-1',
        )
        db.session.add(entry)
        db.session.commit()

        svc = HubSpotTimelineImportService()
        assert svc.scrub_html_from_hubspot_entries(lead_id=lead.id) == 1
        refreshed = LeadTimelineEntry.query.get(entry.id)
        assert refreshed.summary == 'Call with Gilberto Olivares — No answer'
        assert refreshed.event_metadata['outcome'] == 'No answer'

