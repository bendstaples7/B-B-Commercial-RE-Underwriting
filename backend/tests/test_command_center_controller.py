"""
Integration tests for Command Center API endpoints.

Covers:
  34.2 — Core command center endpoints
  34.4 — HubSpot sync → timeline entries with correct source and deduplication
"""
import json
import pytest
from datetime import date, datetime, timedelta, timezone

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry
from app.services.hubspot_timeline_import_service import HubSpotTimelineImportService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(app, street, **kwargs):
    """Create a Lead with sensible defaults."""
    defaults = dict(
        lead_status='mailing_no_contact_made',
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


def _make_task(app, lead_id, status='open', due_date=None, task_type='custom', title='Test task'):
    task = LeadTask(
        lead_id=lead_id,
        task_type=task_type,
        title=title,
        status=status,
        due_date=due_date,
        created_by='test',
    )
    db.session.add(task)
    db.session.commit()
    return task


def _hubspot_activity(activity_id, activity_type='NOTE', body='Test note', days_ago=5):
    """Build a minimal HubSpot activity dict."""
    occurred_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        'id': str(activity_id),
        'type': activity_type,
        'body': body,
        'occurred_at': occurred_at,
    }


# ---------------------------------------------------------------------------
# 34.2 — GET /api/leads/<id>/command-center
# ---------------------------------------------------------------------------

class TestGetCommandCenter:
    def test_returns_200_for_existing_lead(self, client, app):
        """GET /api/leads/<id>/command-center returns 200 for a valid lead."""
        with app.app_context():
            lead = _make_lead(app, '1 CC St')
            response = client.get(f'/api/leads/{lead.id}/command-center')
            assert response.status_code == 200

    def test_returns_404_for_missing_lead(self, client, app):
        """GET /api/leads/99999/command-center returns 404."""
        with app.app_context():
            response = client.get('/api/leads/99999/command-center')
            assert response.status_code == 404

    def test_response_contains_all_sections(self, client, app):
        """Response contains id, recommended_action, open_tasks, and timeline sections."""
        with app.app_context():
            lead = _make_lead(app, '2 CC St')
            response = client.get(f'/api/leads/{lead.id}/command-center')
            data = json.loads(response.data)
            assert 'id' in data
            assert 'recommended_action' in data
            assert 'open_tasks' in data
            assert 'timeline' in data
            assert data['id'] == lead.id

    def test_open_tasks_included_in_response(self, client, app):
        """Open tasks are included in the command center response."""
        with app.app_context():
            lead = _make_lead(app, '3 CC St')
            task = _make_task(app, lead.id, title='Call owner')
            response = client.get(f'/api/leads/{lead.id}/command-center')
            data = json.loads(response.data)
            task_ids = [t['id'] for t in data['open_tasks']]
            assert task.id in task_ids

    def test_clears_review_required_flag(self, client, app):
        """Opening command center clears review_required flag."""
        with app.app_context():
            lead = _make_lead(app, '4 CC St', review_required=True)
            client.get(f'/api/leads/{lead.id}/command-center')
            db.session.refresh(lead)
            assert lead.review_required is False

    def test_timeline_section_has_entries_key(self, client, app):
        """Timeline section contains entries list and total."""
        with app.app_context():
            lead = _make_lead(app, '5 CC St')
            response = client.get(f'/api/leads/{lead.id}/command-center')
            data = json.loads(response.data)
            assert 'entries' in data['timeline']
            assert 'total' in data['timeline']


# ---------------------------------------------------------------------------
# 34.2 — PATCH /api/leads/<id>/status
# ---------------------------------------------------------------------------

class TestUpdateStatus:
    def test_status_change_returns_200(self, client, app):
        """PATCH /api/leads/<id>/status returns 200 on valid status change."""
        with app.app_context():
            lead = _make_lead(app, '6 Status St', lead_status='mailing_no_contact_made')
            response = client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'deprioritize'}),
                content_type='application/json',
            )
            assert response.status_code == 200

    def test_status_change_persists(self, client, app):
        """PATCH /api/leads/<id>/status persists the new status to the database."""
        with app.app_context():
            lead = _make_lead(app, '7 Status St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'deprioritize'}),
                content_type='application/json',
            )
            db.session.refresh(lead)
            assert lead.lead_status == 'deprioritize'

    def test_status_change_appends_timeline_entry(self, client, app):
        """PATCH /api/leads/<id>/status appends a status_changed timeline entry."""
        with app.app_context():
            lead = _make_lead(app, '8 Status St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'negotiating_remote'}),
                content_type='application/json',
            )
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed'
            ).first()
            assert entry is not None
            assert entry.event_metadata['previous_status'] == 'mailing_no_contact_made'
            assert entry.event_metadata['new_status'] == 'negotiating_remote'

    def test_dnc_status_nulls_recommended_action(self, client, app):
        """Setting status to do_not_contact sets recommended_action to null."""
        with app.app_context():
            lead = _make_lead(app, '9 Status St',
                              lead_status='mailing_no_contact_made',
                              recommended_action='follow_up_now')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'do_not_contact'}),
                content_type='application/json',
            )
            db.session.refresh(lead)
            assert lead.recommended_action is None

    def test_dnc_status_cancels_open_tasks(self, client, app):
        """Setting status to do_not_contact cancels all open tasks."""
        with app.app_context():
            lead = _make_lead(app, '10 Status St', lead_status='mailing_no_contact_made')
            task = _make_task(app, lead.id)
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'do_not_contact'}),
                content_type='application/json',
            )
            db.session.refresh(task)
            assert task.status == 'cancelled'

    def test_returns_404_for_missing_lead(self, client, app):
        """PATCH /api/leads/99999/status returns 404."""
        with app.app_context():
            response = client.patch(
                '/api/leads/99999/status',
                data=json.dumps({'status': 'negotiating_remote'}),
                content_type='application/json',
            )
            assert response.status_code == 404

    # ------------------------------------------------------------------
    # Requirement 2.5 — reason in timeline summary
    # ------------------------------------------------------------------

    def test_status_change_with_reason_includes_reason_in_summary(self, client, app):
        """PATCH with reason: summary includes reason text (Req 2.5)."""
        with app.app_context():
            lead = _make_lead(app, '43 Reason St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'negotiating_remote', 'reason': 'Called today, owner interested.'}),
                content_type='application/json',
            )
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed'
            ).first()
            assert entry is not None
            assert entry.summary == (
                "Status changed from 'mailing_no_contact_made' to 'negotiating_remote'. "
                "Called today, owner interested."
            )

    def test_status_change_without_reason_uses_existing_summary_format(self, client, app):
        """PATCH without reason: summary uses existing format (Req 2.5)."""
        with app.app_context():
            lead = _make_lead(app, '44 Reason St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'deprioritize'}),
                content_type='application/json',
            )
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed'
            ).first()
            assert entry is not None
            assert entry.summary == "Status changed from 'mailing_no_contact_made' to 'deprioritize'."

    def test_status_change_empty_reason_uses_existing_summary_format(self, client, app):
        """PATCH with empty reason string: summary uses existing format (Req 2.5)."""
        with app.app_context():
            lead = _make_lead(app, '45 Reason St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'deprioritize', 'reason': ''}),
                content_type='application/json',
            )
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed'
            ).first()
            assert entry is not None
            assert entry.summary == "Status changed from 'mailing_no_contact_made' to 'deprioritize'."

    # ------------------------------------------------------------------
    # Requirement 2.6 — reason stored in event_metadata
    # ------------------------------------------------------------------

    def test_status_change_with_reason_stores_reason_in_metadata(self, client, app):
        """PATCH with reason: event_metadata['reason'] holds the reason string (Req 2.6)."""
        with app.app_context():
            lead = _make_lead(app, '46 Meta St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'negotiating_remote', 'reason': 'Owner called back.'}),
                content_type='application/json',
            )
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed'
            ).first()
            assert entry is not None
            assert entry.event_metadata['reason'] == 'Owner called back.'

    def test_status_change_without_reason_stores_none_in_metadata(self, client, app):
        """PATCH without reason: event_metadata['reason'] is None (Req 2.6)."""
        with app.app_context():
            lead = _make_lead(app, '47 Meta St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'deprioritize'}),
                content_type='application/json',
            )
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed'
            ).first()
            assert entry is not None
            assert entry.event_metadata['reason'] is None

    def test_reason_over_500_chars_rejected(self, client, app):
        """PATCH with reason > 500 chars returns 400 (Req 2.4)."""
        with app.app_context():
            lead = _make_lead(app, '48 Meta St', lead_status='mailing_no_contact_made')
            long_reason = 'x' * 501
            response = client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'deprioritize', 'reason': long_reason}),
                content_type='application/json',
            )
            assert response.status_code == 400


# ---------------------------------------------------------------------------
# 34.2 — POST /api/leads/<id>/tasks
# ---------------------------------------------------------------------------

class TestCreateTask:
    def test_create_task_returns_201(self, client, app):
        """POST /api/leads/<id>/tasks returns 201 on success."""
        with app.app_context():
            lead = _make_lead(app, '11 Task St')
            response = client.post(
                f'/api/leads/{lead.id}/tasks',
                data=json.dumps({'title': 'Call owner', 'task_type': 'custom'}),
                content_type='application/json',
            )
            assert response.status_code == 201

    def test_create_task_persists_to_db(self, client, app):
        """POST /api/leads/<id>/tasks creates a LeadTask record in the database."""
        with app.app_context():
            lead = _make_lead(app, '12 Task St')
            client.post(
                f'/api/leads/{lead.id}/tasks',
                data=json.dumps({'title': 'Send mail', 'task_type': 'custom'}),
                content_type='application/json',
            )
            task = LeadTask.query.filter_by(lead_id=lead.id, title='Send mail').first()
            assert task is not None
            assert task.status == 'open'

    def test_create_task_response_contains_id(self, client, app):
        """POST /api/leads/<id>/tasks response contains the new task id."""
        with app.app_context():
            lead = _make_lead(app, '13 Task St')
            response = client.post(
                f'/api/leads/{lead.id}/tasks',
                data=json.dumps({'title': 'Research PIN', 'task_type': 'custom'}),
                content_type='application/json',
            )
            data = json.loads(response.data)
            assert 'id' in data
            assert isinstance(data['id'], int)

    def test_create_task_empty_title_rejected(self, client, app):
        """POST /api/leads/<id>/tasks with empty title returns 400."""
        with app.app_context():
            lead = _make_lead(app, '14 Task St')
            response = client.post(
                f'/api/leads/{lead.id}/tasks',
                data=json.dumps({'title': '', 'task_type': 'custom'}),
                content_type='application/json',
            )
            assert response.status_code == 400


# ---------------------------------------------------------------------------
# 34.2 — POST /api/leads/<id>/tasks/<task_id>/complete
# ---------------------------------------------------------------------------

class TestCompleteTask:
    def test_complete_task_returns_200(self, client, app):
        """POST /api/leads/<id>/tasks/<task_id>/complete returns 200."""
        with app.app_context():
            lead = _make_lead(app, '15 Complete St')
            task = _make_task(app, lead.id)
            response = client.post(f'/api/leads/{lead.id}/tasks/{task.id}/complete')
            assert response.status_code == 200

    def test_complete_task_sets_status_completed(self, client, app):
        """Completing a task sets its status to 'completed'."""
        with app.app_context():
            lead = _make_lead(app, '16 Complete St')
            task = _make_task(app, lead.id)
            client.post(f'/api/leads/{lead.id}/tasks/{task.id}/complete')
            db.session.refresh(task)
            assert task.status == 'completed'

    def test_complete_task_sets_completed_at(self, client, app):
        """Completing a task sets completed_at timestamp."""
        with app.app_context():
            lead = _make_lead(app, '17 Complete St')
            task = _make_task(app, lead.id)
            client.post(f'/api/leads/{lead.id}/tasks/{task.id}/complete')
            db.session.refresh(task)
            assert task.completed_at is not None

    def test_complete_task_response_contains_status(self, client, app):
        """Response contains status='completed'."""
        with app.app_context():
            lead = _make_lead(app, '18 Complete St')
            task = _make_task(app, lead.id)
            response = client.post(f'/api/leads/{lead.id}/tasks/{task.id}/complete')
            data = json.loads(response.data)
            assert data['status'] == 'completed'


# ---------------------------------------------------------------------------
# 34.2 — POST /api/leads/<id>/notes
# ---------------------------------------------------------------------------

class TestLogNote:
    def test_log_note_returns_201(self, client, app):
        """POST /api/leads/<id>/notes returns 201 on success."""
        with app.app_context():
            lead = _make_lead(app, '19 Note St')
            response = client.post(
                f'/api/leads/{lead.id}/notes',
                data=json.dumps({'body': 'Owner called back.'}),
                content_type='application/json',
            )
            assert response.status_code == 201

    def test_log_note_creates_timeline_entry(self, client, app):
        """POST /api/leads/<id>/notes creates a note_added timeline entry."""
        with app.app_context():
            lead = _make_lead(app, '20 Note St')
            client.post(
                f'/api/leads/{lead.id}/notes',
                data=json.dumps({'body': 'Left voicemail.'}),
                content_type='application/json',
            )
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='note_added'
            ).first()
            assert entry is not None

    def test_log_note_empty_body_rejected(self, client, app):
        """POST /api/leads/<id>/notes with empty body returns 400."""
        with app.app_context():
            lead = _make_lead(app, '21 Note St')
            response = client.post(
                f'/api/leads/{lead.id}/notes',
                data=json.dumps({'body': ''}),
                content_type='application/json',
            )
            assert response.status_code == 400


# ---------------------------------------------------------------------------
# 34.2 — POST /api/leads/<id>/calls
# ---------------------------------------------------------------------------

class TestLogCall:
    def test_log_call_returns_201(self, client, app):
        """POST /api/leads/<id>/calls returns 201 on success."""
        with app.app_context():
            lead = _make_lead(app, '22 Call St')
            response = client.post(
                f'/api/leads/{lead.id}/calls',
                data=json.dumps({'outcome': 'answered', 'duration_minutes': 5}),
                content_type='application/json',
            )
            assert response.status_code == 201

    def test_log_call_creates_timeline_entry(self, client, app):
        """POST /api/leads/<id>/calls creates a call_logged timeline entry."""
        with app.app_context():
            lead = _make_lead(app, '23 Call St')
            client.post(
                f'/api/leads/{lead.id}/calls',
                data=json.dumps({'outcome': 'voicemail'}),
                content_type='application/json',
            )
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='call_logged'
            ).first()
            assert entry is not None

    def test_log_call_invalid_outcome_rejected(self, client, app):
        """POST /api/leads/<id>/calls with invalid outcome returns 400."""
        with app.app_context():
            lead = _make_lead(app, '24 Call St')
            response = client.post(
                f'/api/leads/{lead.id}/calls',
                data=json.dumps({'outcome': 'invalid_outcome_xyz'}),
                content_type='application/json',
            )
            assert response.status_code == 400


# ---------------------------------------------------------------------------
# 34.2 — POST /api/leads/<id>/do-not-contact
# ---------------------------------------------------------------------------

class TestDoNotContact:
    def test_dnc_returns_200(self, client, app):
        """POST /api/leads/<id>/do-not-contact returns 200."""
        with app.app_context():
            lead = _make_lead(app, '25 DNC St', lead_status='mailing_no_contact_made')
            response = client.post(
                f'/api/leads/{lead.id}/do-not-contact',
                data=json.dumps({}),
                content_type='application/json',
            )
            assert response.status_code == 200

    def test_dnc_sets_status(self, client, app):
        """POST /api/leads/<id>/do-not-contact sets lead_status to do_not_contact."""
        with app.app_context():
            lead = _make_lead(app, '26 DNC St', lead_status='mailing_no_contact_made')
            client.post(
                f'/api/leads/{lead.id}/do-not-contact',
                data=json.dumps({}),
                content_type='application/json',
            )
            db.session.refresh(lead)
            assert lead.lead_status == 'do_not_contact'

    def test_dnc_nulls_recommended_action(self, client, app):
        """POST /api/leads/<id>/do-not-contact sets recommended_action to null."""
        with app.app_context():
            lead = _make_lead(app, '27 DNC St',
                              lead_status='mailing_no_contact_made',
                              recommended_action='follow_up_now')
            client.post(
                f'/api/leads/{lead.id}/do-not-contact',
                data=json.dumps({}),
                content_type='application/json',
            )
            db.session.refresh(lead)
            assert lead.recommended_action is None

    def test_dnc_cancels_open_tasks(self, client, app):
        """POST /api/leads/<id>/do-not-contact cancels all open tasks."""
        with app.app_context():
            lead = _make_lead(app, '28 DNC St', lead_status='mailing_no_contact_made')
            task1 = _make_task(app, lead.id, title='Task 1')
            task2 = _make_task(app, lead.id, title='Task 2')
            client.post(
                f'/api/leads/{lead.id}/do-not-contact',
                data=json.dumps({}),
                content_type='application/json',
            )
            db.session.refresh(task1)
            db.session.refresh(task2)
            assert task1.status == 'cancelled'
            assert task2.status == 'cancelled'

    def test_dnc_lead_returns_403_on_log_call(self, client, app):
        """Logging a call on a DNC lead returns 403."""
        with app.app_context():
            lead = _make_lead(app, '29 DNC St', lead_status='do_not_contact')
            response = client.post(
                f'/api/leads/{lead.id}/calls',
                data=json.dumps({'outcome': 'answered'}),
                content_type='application/json',
            )
            assert response.status_code == 403

    def test_dnc_lead_returns_403_on_log_note(self, client, app):
        """Logging a note on a DNC lead returns 403."""
        with app.app_context():
            lead = _make_lead(app, '30 DNC St', lead_status='do_not_contact')
            response = client.post(
                f'/api/leads/{lead.id}/notes',
                data=json.dumps({'body': 'Test note'}),
                content_type='application/json',
            )
            assert response.status_code == 403


# ---------------------------------------------------------------------------
# 34.2 — POST /api/leads/<id>/park
# ---------------------------------------------------------------------------

class TestParkLead:
    def test_park_returns_200(self, client, app):
        """POST /api/leads/<id>/park returns 200."""
        with app.app_context():
            lead = _make_lead(app, '31 Park St', lead_status='mailing_no_contact_made')
            response = client.post(
                f'/api/leads/{lead.id}/park',
                data=json.dumps({}),
                content_type='application/json',
            )
            assert response.status_code == 200

    def test_park_sets_deprioritize_status(self, client, app):
        """POST /api/leads/<id>/park sets lead_status to deprioritize."""
        with app.app_context():
            lead = _make_lead(app, '32 Park St', lead_status='mailing_no_contact_made')
            client.post(
                f'/api/leads/{lead.id}/park',
                data=json.dumps({}),
                content_type='application/json',
            )
            db.session.refresh(lead)
            assert lead.lead_status == 'deprioritize'

    def test_park_with_future_reactivation_date_accepted(self, client, app):
        """POST /api/leads/<id>/park with a future reactivation_date returns 200."""
        with app.app_context():
            lead = _make_lead(app, '33 Park St', lead_status='mailing_no_contact_made')
            future_date = (date.today() + timedelta(days=30)).isoformat()
            response = client.post(
                f'/api/leads/{lead.id}/park',
                data=json.dumps({'reactivation_date': future_date}),
                content_type='application/json',
            )
            assert response.status_code == 200

    def test_park_with_past_reactivation_date_rejected(self, client, app):
        """POST /api/leads/<id>/park with a past reactivation_date returns 400."""
        with app.app_context():
            lead = _make_lead(app, '34 Park St', lead_status='mailing_no_contact_made')
            past_date = (date.today() - timedelta(days=1)).isoformat()
            response = client.post(
                f'/api/leads/{lead.id}/park',
                data=json.dumps({'reactivation_date': past_date}),
                content_type='application/json',
            )
            assert response.status_code == 400

    def test_park_with_reactivation_date_too_far_rejected(self, client, app):
        """POST /api/leads/<id>/park with reactivation_date > 365 days returns 400."""
        with app.app_context():
            lead = _make_lead(app, '35 Park St', lead_status='mailing_no_contact_made')
            far_date = (date.today() + timedelta(days=366)).isoformat()
            response = client.post(
                f'/api/leads/{lead.id}/park',
                data=json.dumps({'reactivation_date': far_date}),
                content_type='application/json',
            )
            assert response.status_code == 400


# ---------------------------------------------------------------------------
# 34.4 — HubSpot sync → timeline entries with correct source and deduplication
# ---------------------------------------------------------------------------

class TestHubSpotTimelineImport:
    """Integration tests for HubSpotTimelineImportService used directly."""

    def test_import_creates_timeline_entries_with_hubspot_source(self, app):
        """Imported HubSpot activities create timeline entries with source='hubspot'."""
        with app.app_context():
            lead = _make_lead(app, '36 HubSpot St')
            svc = HubSpotTimelineImportService()
            activities = [
                _hubspot_activity('hs-001', 'NOTE', 'First note'),
                _hubspot_activity('hs-002', 'CALL', 'Called owner'),
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

    def test_import_deduplicates_on_second_import(self, app):
        """Importing the same activities twice creates no new entries on second import."""
        with app.app_context():
            lead = _make_lead(app, '37 HubSpot St')
            svc = HubSpotTimelineImportService()
            activities = [
                _hubspot_activity('hs-003', 'NOTE', 'Duplicate note'),
                _hubspot_activity('hs-004', 'CALL', 'Duplicate call'),
            ]
            # First import
            first_count = svc.import_activities_for_lead(lead.id, activities)
            assert first_count == 2

            # Second import with same activities
            second_count = svc.import_activities_for_lead(lead.id, activities)
            assert second_count == 0

            # Total entries unchanged
            total = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, source='hubspot'
            ).count()
            assert total == 2

    def test_import_partial_deduplication(self, app):
        """Importing a mix of new and existing activities only creates new entries."""
        with app.app_context():
            lead = _make_lead(app, '38 HubSpot St')
            svc = HubSpotTimelineImportService()

            # First import: 2 activities
            first_batch = [
                _hubspot_activity('hs-005', 'NOTE', 'Existing note'),
            ]
            svc.import_activities_for_lead(lead.id, first_batch)

            # Second import: 1 existing + 1 new
            second_batch = [
                _hubspot_activity('hs-005', 'NOTE', 'Existing note'),  # duplicate
                _hubspot_activity('hs-006', 'TASK', 'New task'),       # new
            ]
            count = svc.import_activities_for_lead(lead.id, second_batch)
            assert count == 1

            total = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, source='hubspot'
            ).count()
            assert total == 2

    def test_import_sets_correct_event_types(self, app):
        """HubSpot activity types map to correct timeline event_type values."""
        with app.app_context():
            lead = _make_lead(app, '39 HubSpot St')
            svc = HubSpotTimelineImportService()
            activities = [
                _hubspot_activity('hs-007', 'NOTE', 'A note'),
                _hubspot_activity('hs-008', 'CALL', 'A call'),
                _hubspot_activity('hs-009', 'TASK', 'A task'),
            ]
            svc.import_activities_for_lead(lead.id, activities)

            entries = {
                e.hubspot_activity_id: e
                for e in LeadTimelineEntry.query.filter_by(lead_id=lead.id).all()
            }
            assert entries['hs-007'].event_type == 'hubspot_note'
            assert entries['hs-008'].event_type == 'hubspot_call'
            assert entries['hs-009'].event_type == 'hubspot_task'

    def test_import_updates_last_hubspot_sync_at(self, app):
        """Importing activities updates last_hubspot_sync_at on the lead."""
        with app.app_context():
            lead = _make_lead(app, '40 HubSpot St')
            assert lead.last_hubspot_sync_at is None
            svc = HubSpotTimelineImportService()
            svc.import_activities_for_lead(lead.id, [_hubspot_activity('hs-010')])
            db.session.refresh(lead)
            assert lead.last_hubspot_sync_at is not None

    def test_import_sets_review_required_when_new_entries(self, app):
        """Importing new HubSpot activities sets review_required=True on the lead."""
        with app.app_context():
            lead = _make_lead(app, '41 HubSpot St', review_required=False)
            svc = HubSpotTimelineImportService()
            svc.import_activities_for_lead(lead.id, [_hubspot_activity('hs-011')])
            db.session.refresh(lead)
            assert lead.review_required is True

    def test_import_empty_activities_returns_zero(self, app):
        """Importing an empty activity list returns 0 and creates no entries."""
        with app.app_context():
            lead = _make_lead(app, '42 HubSpot St')
            svc = HubSpotTimelineImportService()
            count = svc.import_activities_for_lead(lead.id, [])
            assert count == 0
            total = LeadTimelineEntry.query.filter_by(lead_id=lead.id).count()
            assert total == 0

