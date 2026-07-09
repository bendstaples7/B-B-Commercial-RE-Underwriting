"""Tests for hubspot_stage_mapping helpers."""
from datetime import datetime, timedelta, timezone

from app import db
from app.models.lead import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.services.hubspot_stage_mapping import (
    LEAD_STATUS_TO_HS_STAGE,
    manual_status_change_wins,
)


class TestHubSpotStageMapping:
    def test_lead_status_to_hs_stage_inverse(self):
        assert LEAD_STATUS_TO_HS_STAGE['skip_trace'] == 'Skip Trace'
        assert LEAD_STATUS_TO_HS_STAGE['mailing_no_contact_made'] == 'Mailing, no contact made'

    def test_manual_status_change_wins_after_recent_manual_entry(self, app):
        with app.app_context():
            lead = Lead(
                property_street='100 Manual Wins St',
                lead_status='skip_trace',
                last_hubspot_sync_at=datetime.utcnow() - timedelta(hours=1),
            )
            db.session.add(lead)
            db.session.flush()

            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='status_changed',
                source='manual',
                actor='test-user',
                summary='Status changed.',
                occurred_at=datetime.now(timezone.utc),
                event_metadata={'previous_status': 'mailing_no_contact_made', 'new_status': 'skip_trace'},
            ))
            db.session.commit()

            assert manual_status_change_wins(lead) is True

    def test_manual_status_change_does_not_win_before_hubspot_sync(self, app):
        with app.app_context():
            sync_at = datetime.utcnow()
            lead = Lead(
                property_street='101 Manual Loses St',
                lead_status='skip_trace',
                last_hubspot_sync_at=sync_at,
            )
            db.session.add(lead)
            db.session.flush()

            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='status_changed',
                source='manual',
                actor='test-user',
                summary='Status changed.',
                occurred_at=sync_at - timedelta(hours=1),
                event_metadata={'previous_status': 'mailing_no_contact_made', 'new_status': 'skip_trace'},
            ))
            db.session.commit()

            assert manual_status_change_wins(lead) is False
