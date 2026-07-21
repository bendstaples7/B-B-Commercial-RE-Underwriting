"""
Integration tests for Command Center API endpoints.

Covers:
  34.2 — Core command center endpoints
  34.4 — HubSpot sync → timeline entries with correct source and deduplication
"""
import json
import uuid
import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry, Task
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.hubspot_timeline_import_service import HubSpotTimelineImportService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUTH_HEADERS = {'X-User-Id': 'test-user'}


def _bearer_headers(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def _make_log_user(display_name: str = 'Activity Logger') -> User:
    email = f'logger-{uuid.uuid4().hex[:8]}@test.com'
    user = User(
        user_id=str(uuid.uuid4()),
        email=email,
        email_lower=email.lower(),
        password_hash='$2b$12$fakehashfakehashfakehashfakehashfakehashfakehash',
        display_name=display_name,
        is_active=True,
        password_set=True,
    )
    db.session.add(user)
    db.session.commit()
    return user

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
        owner_user_id='test-user',
    )
    defaults.update(kwargs)
    lead = Lead(property_street=street, **defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


def _make_task(app, lead_id, status='open', due_date=None, task_type='custom', title='Test task', hubspot_task_id=None):
    task = LeadTask(
        lead_id=lead_id,
        task_type=task_type,
        title=title,
        status=status,
        due_date=due_date,
        created_by='test',
        hubspot_task_id=hubspot_task_id,
    )
    db.session.add(task)
    db.session.commit()
    return task


def _make_contact_with_phone(app, lead_id, first_name='Jane', last_name='Doe'):
    from app.models.contact import Contact
    from app.models.property_contact import PropertyContact
    from app.models.contact_phone import ContactPhone
    contact = Contact(first_name=first_name, last_name=last_name, role='owner')
    db.session.add(contact)
    db.session.flush()
    link = PropertyContact(
        property_id=lead_id,
        contact_id=contact.id,
        role='owner',
        is_primary=True,
    )
    phone = ContactPhone(contact_id=contact.id, value='5551234567', label='mobile')
    db.session.add_all([link, phone])
    db.session.commit()
    return contact, phone


def _make_contact_with_email(app, lead_id, first_name='Jane', last_name='Doe'):
    from app.models.contact import Contact
    from app.models.property_contact import PropertyContact
    from app.models.contact_email import ContactEmail
    contact = Contact(first_name=first_name, last_name=last_name, role='owner')
    db.session.add(contact)
    db.session.flush()
    link = PropertyContact(
        property_id=lead_id,
        contact_id=contact.id,
        role='owner',
        is_primary=True,
    )
    email = ContactEmail(contact_id=contact.id, value='jane@work.com', label='work')
    db.session.add_all([link, email])
    db.session.commit()
    return contact, email


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
            response = client.get(f'/api/leads/{lead.id}/command-center', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_returns_404_for_missing_lead(self, client, app):
        """GET /api/leads/99999/command-center returns 404."""
        with app.app_context():
            response = client.get('/api/leads/99999/command-center', headers=_AUTH_HEADERS)
            assert response.status_code == 404

    def test_response_contains_all_sections(self, client, app):
        """Response contains id, recommended_action, open_tasks, and timeline sections."""
        with app.app_context():
            lead = _make_lead(app, '2 CC St')
            response = client.get(f'/api/leads/{lead.id}/command-center', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert 'id' in data
            assert 'recommended_action' in data
            assert 'open_tasks' in data
            assert 'timeline' in data
            assert 'contacts' in data
            assert isinstance(data['contacts'], list)
            assert data['id'] == lead.id

    def test_contacts_ordered_primary_first(self, client, app):
        """contacts[] is primary-first with nested phones/emails; flat fields remain."""
        with app.app_context():
            from app.services.contact_service import ContactService
            lead = _make_lead(app, '2b Contacts St', owner_first_name='Flat', owner_last_name='Owner')
            svc = ContactService()
            secondary = svc.create_contact({
                'first_name': 'Second',
                'last_name': 'Owner',
                'phones': [{'value': '555-0002', 'label': 'mobile'}],
            })
            primary = svc.create_contact({
                'first_name': 'Primary',
                'last_name': 'Contact',
                'phones': [{'value': '555-0001', 'label': 'mobile'}],
                'emails': [{'value': 'p@example.com', 'label': 'personal'}],
            })
            svc.link_contact_to_property(lead.id, secondary.id, role='owner', is_primary=False)
            svc.link_contact_to_property(lead.id, primary.id, role='owner', is_primary=True)

            response = client.get(f'/api/leads/{lead.id}/command-center', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert response.status_code == 200
            assert data['owner_first_name'] == 'Flat'
            assert len(data['contacts']) == 2
            assert data['contacts'][0]['first_name'] == 'Primary'
            assert data['contacts'][0]['is_primary'] is True
            assert data['contacts'][0]['phones'][0]['value'] == '555-0001'
            assert data['contacts'][0]['emails'][0]['value'] == 'p@example.com'
            assert data['contacts'][1]['first_name'] == 'Second'
            assert data['contacts'][1]['is_primary'] is False

    def test_contacts_phones_include_confidence_score(self, client, app):
        """Nested contacts[].phones include confidence_score (not skinny id/value/label)."""
        with app.app_context():
            from app import db
            from app.models.contact_phone import ContactPhone
            from app.services.contact_service import ContactService

            lead = _make_lead(app, '2c Confidence St')
            svc = ContactService()
            contact = svc.create_contact({
                'first_name': 'Hilberto',
                'last_name': 'Olivier',
                'phones': [{'value': '6302023839', 'label': 'mobile'}],
            })
            svc.link_contact_to_property(lead.id, contact.id, role='owner', is_primary=True)
            phone = ContactPhone.query.filter_by(contact_id=contact.id).first()
            phone.confidence_score = 80
            phone.notes = 'CONFIRMED'
            db.session.commit()

            response = client.get(f'/api/leads/{lead.id}/command-center', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert response.status_code == 200
            nested = data['contacts'][0]['phones'][0]
            assert nested['value'] == '6302023839'
            assert nested['confidence_score'] == 80
            assert nested['notes'] == 'CONFIRMED'
            assert 'label' in nested

            # Property-contacts API uses the same full phone DTO
            pc_resp = client.get(
                f'/api/properties/{lead.id}/contacts',
                headers=_AUTH_HEADERS,
            )
            assert pc_resp.status_code == 200
            pc_phones = json.loads(pc_resp.data)[0]['phones']
            assert pc_phones[0]['confidence_score'] == 80
            assert pc_phones[0]['notes'] == 'CONFIRMED'

    def test_open_tasks_included_in_response(self, client, app):
        """Open tasks are included in the command center response."""
        with app.app_context():
            lead = _make_lead(app, '3 CC St')
            task = _make_task(app, lead.id, title='Call owner')
            response = client.get(f'/api/leads/{lead.id}/command-center', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            task_ids = [t['id'] for t in data['open_tasks']]
            assert task.id in task_ids

    def test_open_tasks_are_lead_task_only_not_crm_tasks_union(self, client, app):
        """CC open_tasks comes from LeadTask only — CRM Task rows are not UNION'd in."""
        with app.app_context():
            from app.models.task import Task
            from app.models.task_association import TaskAssociation

            lead = _make_lead(app, '3b CC HubSpot St')
            native = _make_task(app, lead.id, title='Native call')
            hs_lead_task = LeadTask(
                lead_id=lead.id,
                task_type='custom',
                title='HubSpot follow up',
                status='open',
                created_by='HubSpot',
                hubspot_task_id='hs-cc-open-1',
            )
            db.session.add(hs_lead_task)

            crm_only = Task(
                title='CRM-only HubSpot task (should not appear)',
                status='open',
                source='hubspot_import',
                hubspot_task_id='hs-cc-crm-only',
            )
            db.session.add(crm_only)
            db.session.flush()
            db.session.add(TaskAssociation(
                task_id=crm_only.id,
                target_type='lead',
                target_id=lead.id,
            ))
            db.session.commit()

            response = client.get(f'/api/leads/{lead.id}/command-center', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['hubspot_interactions'] == []
            by_id = {t['id']: t for t in data['open_tasks']}
            titles = {t['title'] for t in data['open_tasks']}
            assert native.id in by_id
            assert by_id[native.id]['source'] == 'native'
            assert hs_lead_task.id in by_id
            assert by_id[hs_lead_task.id]['source'] == 'hubspot'
            assert by_id[hs_lead_task.id]['hubspot_task_id'] == 'hs-cc-open-1'
            assert 'CRM-only HubSpot task (should not appear)' not in titles
            assert not any(
                t.get('hubspot_task_id') == 'hs-cc-crm-only' for t in data['open_tasks']
            )

    def test_clears_review_required_flag(self, client, app):
        """Opening command center clears review_required flag."""
        with app.app_context():
            lead = _make_lead(app, '4 CC St', review_required=True)
            client.get(f'/api/leads/{lead.id}/command-center', headers=_AUTH_HEADERS)
            db.session.refresh(lead)
            assert lead.review_required is False

    def test_persists_live_data_completeness_score(self, client, app):
        """Opening command center stores the live completeness score on the lead."""
        with app.app_context():
            lead = _make_lead(app, '4b Completeness St', data_completeness_score=0.0)
            response = client.get(f'/api/leads/{lead.id}/command-center', headers=_AUTH_HEADERS)
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data['data_completeness_score'] > 0
            db.session.refresh(lead)
            assert lead.data_completeness_score == data['data_completeness_score']

    def test_timeline_section_has_entries_key(self, client, app):
        """Timeline section contains entries list and total."""
        with app.app_context():
            lead = _make_lead(app, '5 CC St')
            response = client.get(f'/api/leads/{lead.id}/command-center', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert 'entries' in data['timeline']
            assert 'total' in data['timeline']

    @patch('app.services.hubspot_deal_sync_service.HubSpotDealSyncService.auto_sync_lead_if_stale')
    @patch('app.services.hubspot_deal_sync_service.HubSpotDealSyncService.sync_tasks_for_lead')
    def test_does_not_auto_sync_hubspot_on_load(self, mock_sync_tasks, mock_auto_sync, client, app):
        """Opening command center must not trigger HubSpot sync-on-read or task pull."""
        with app.app_context():
            lead = _make_lead(app, '6 Auto Sync St')
            mock_auto_sync.return_value = True
            response = client.get(f'/api/leads/{lead.id}/command-center', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            mock_auto_sync.assert_not_called()
            mock_sync_tasks.assert_not_called()


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
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 200

    @patch('app.services.hubspot_deal_sync_service.HubSpotDealSyncService.sync_tasks_for_lead')
    @patch('app.services.hubspot_deal_sync_service.HubSpotDealSyncService.refresh_and_enrich_lead')
    @patch('app.services.hubspot_deal_sync_service.HubSpotDealSyncService.auto_sync_lead_if_stale')
    def test_status_change_does_not_pull_hubspot_tasks(
        self, mock_auto_sync, mock_refresh, mock_sync_tasks, client, app,
    ):
        """Status PATCH must not auto-sync or pull HubSpot tasks (user-path split)."""
        with app.app_context():
            lead = _make_lead(app, '6b No HubSpot Pull St', lead_status='mailing_no_contact_made')
            response = client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'in_person_appointment'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 200
            mock_auto_sync.assert_not_called()
            mock_refresh.assert_not_called()
            mock_sync_tasks.assert_not_called()
            body = response.get_json()
            assert body['lead_status'] == 'in_person_appointment'

    def test_in_person_appointment_increases_score_via_pipeline_bonus(self, client, app):
        """Status → in_person_appointment applies +30 bonus and leaves enrich_data."""
        with app.app_context():
            from app.services.lead_scoring_engine import LeadScoringEngine

            lead = _make_lead(
                app,
                '6b In Person St',
                lead_status='mailing_no_contact_made',
                lead_score=30.0,
                has_phone=True,
                has_email=False,
                has_property_match=True,
                analysis_complete=True,
            )
            # Establish a real baseline score at mailing_no_contact_made (0 bonus).
            LeadScoringEngine().score_and_persist(lead.id)
            db.session.refresh(lead)
            before = float(lead.lead_score or 0)
            assert LeadScoringEngine._pipeline_stage_bonus(lead) == 0.0

            response = client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'in_person_appointment'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 200
            body = response.get_json()
            assert body['lead_status'] == 'in_person_appointment'
            assert float(body['lead_score']) == pytest.approx(before + 30.0, abs=0.15)
            assert body['recommended_action'] == 'call_ready'
            db.session.refresh(lead)
            assert LeadScoringEngine._pipeline_stage_bonus(lead) == 30.0

    def test_status_change_persists(self, client, app):
        """PATCH /api/leads/<id>/status persists the new status to the database."""
        with app.app_context():
            lead = _make_lead(app, '7 Status St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'deprioritize'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            db.session.refresh(lead)
            assert lead.lead_status == 'deprioritize'

    def test_awaiting_skip_trace_sticks_when_mailing_address_present(self, client, app):
        """Manual awaiting_skip_trace must not be undone by residential mailing promotion."""
        with app.app_context():
            lead = _make_lead(
                app,
                '7 Await Stick St',
                lead_status='mailing_no_contact_made',
                needs_skip_trace=False,
                mailing_address='100 Main St',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60614',
                lead_category='residential',
            )
            response = client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'awaiting_skip_trace'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 200
            body = response.get_json()
            assert body['lead_status'] == 'awaiting_skip_trace'
            db.session.refresh(lead)
            assert lead.lead_status == 'awaiting_skip_trace'
            assert lead.needs_skip_trace is True

    def test_status_change_does_not_set_hubspot_deal_stage_without_match(self, client, app):
        """PATCH /api/leads/<id>/status leaves hubspot_deal_stage unset without a HubSpot deal."""
        with app.app_context():
            lead = _make_lead(app, '7b Status St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'skip_trace'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            db.session.refresh(lead)
            assert lead.lead_status == 'skip_trace'
            assert lead.hubspot_deal_stage is None

    def test_status_change_to_skip_trace_converts_dated_handoff_no_duplicate(
        self, client, app,
    ):
        """Status selector must reuse canonical handoff logic: a leftover dated
        skip_trace_owner is converted into a single undated handoff, not left
        alongside a freshly-created one."""
        from datetime import date, timedelta
        from app.models import LeadTask

        with app.app_context():
            lead = _make_lead(app, '7e Status St', lead_status='mailing_no_contact_made')
            dated = LeadTask(
                lead_id=lead.id,
                task_type='skip_trace_owner',
                title='Skip trace owner',
                status='open',
                due_date=date.today() - timedelta(days=3),
            )
            db.session.add(dated)
            db.session.commit()

            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'skip_trace'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )

            open_handoffs = (
                LeadTask.query
                .filter_by(lead_id=lead.id, task_type='skip_trace_owner', status='open')
                .all()
            )
            assert len(open_handoffs) == 1
            handoff = open_handoffs[0]
            assert handoff.due_date is None
            assert handoff.workflow_key == 'awaiting_skip_trace_handoff'

    @patch('app.services.hubspot_writeback_service.HubSpotWriteBackService.push_deal_stage_for_lead')
    def test_status_change_pushes_hubspot_stage_for_linked_deal(self, mock_push, client, app):
        """PATCH /api/leads/<id>/status triggers HubSpot stage writeback for linked deals."""
        mock_push.return_value = {
            'synced': True,
            'action': 'stage_updated',
            'hubspot_deal_stage': 'Skip Trace',
        }
        with app.app_context():
            lead = _make_lead(app, '7d Status St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'skip_trace'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            mock_push.assert_called_once_with(lead.id, 'skip_trace')

    @patch('app.services.queue_order_cache.queue_order_cache.clear')
    def test_status_change_clears_queue_navigation_cache(self, mock_clear, client, app):
        """PATCH /api/leads/<id>/status clears the queue navigation cache."""
        with app.app_context():
            lead = _make_lead(app, '7c Status St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'skip_trace'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            mock_clear.assert_called_once()

    def test_status_change_appends_timeline_entry(self, client, app):
        """PATCH /api/leads/<id>/status appends a status_changed timeline entry."""
        with app.app_context():
            lead = _make_lead(app, '8 Status St', lead_status='mailing_no_contact_made')
            response = client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'negotiating_remote'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            body = response.get_json()
            assert 'timeline_entry' in body
            assert body['timeline_entry']['event_type'] == 'status_changed'
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed'
            ).first()
            assert entry is not None
            assert entry.event_metadata['previous_status'] == 'mailing_no_contact_made'
            assert entry.event_metadata['new_status'] == 'negotiating_remote'
            assert 'previous_score' in (entry.event_metadata or {})
            assert 'new_score' in (entry.event_metadata or {})
            assert 'Score' in entry.summary

    def test_in_person_appointment_timeline_includes_score_delta(self, client, app):
        """Status → in_person_appointment timeline summary includes score before → after."""
        with app.app_context():
            from app.services.lead_scoring_engine import LeadScoringEngine

            lead = _make_lead(
                app,
                '8b Score Timeline St',
                lead_status='mailing_contacted_interested',
                lead_score=30.0,
                has_phone=True,
                has_email=False,
                has_property_match=True,
                analysis_complete=True,
            )
            LeadScoringEngine().score_and_persist(lead.id)
            db.session.refresh(lead)
            before = float(lead.lead_score or 0)

            response = client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'in_person_appointment'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 200
            body = response.get_json()
            entry = body['timeline_entry']
            assert entry['event_type'] == 'status_changed'
            assert 'Score' in entry['summary']
            assert '→' in entry['summary']
            meta = entry.get('metadata') or {}
            assert meta.get('previous_score') == pytest.approx(before, abs=0.15)
            assert float(meta.get('new_score')) > float(meta.get('previous_score'))
            assert float(body['lead_score']) == pytest.approx(float(meta.get('new_score')), abs=0.05)

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
                headers=_AUTH_HEADERS,
            )
            db.session.refresh(lead)
            assert lead.recommended_action is None

    def test_dnc_status_cancels_open_tasks(self, client, app):
        """PATCH and dedicated DNC action enforce the same task invariant."""
        with app.app_context():
            lead = _make_lead(app, '10 Status St', lead_status='mailing_no_contact_made')
            task = _make_task(app, lead.id)
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'do_not_contact'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            db.session.refresh(task)
            assert task.status == 'cancelled'
            assert task.completed_at is None

    def test_returns_404_for_missing_lead(self, client, app):
        """PATCH /api/leads/99999/status returns 404."""
        with app.app_context():
            response = client.patch(
                '/api/leads/99999/status',
                data=json.dumps({'status': 'negotiating_remote'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
            )
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed'
            ).first()
            assert entry is not None
            assert entry.summary.startswith(
                "Status changed from 'mailing_no_contact_made' to 'negotiating_remote'. "
                "Called today, owner interested."
            )
            assert 'Score' in entry.summary

    def test_status_change_without_reason_uses_existing_summary_format(self, client, app):
        """PATCH without reason: summary uses existing format (Req 2.5)."""
        with app.app_context():
            lead = _make_lead(app, '44 Reason St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'deprioritize'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed'
            ).first()
            assert entry is not None
            assert entry.summary.startswith(
                "Status changed from 'mailing_no_contact_made' to 'deprioritize'."
            )
            assert 'Score' in entry.summary

    def test_status_change_empty_reason_uses_existing_summary_format(self, client, app):
        """PATCH with empty reason string: summary uses existing format (Req 2.5)."""
        with app.app_context():
            lead = _make_lead(app, '45 Reason St', lead_status='mailing_no_contact_made')
            client.patch(
                f'/api/leads/{lead.id}/status',
                data=json.dumps({'status': 'deprioritize', 'reason': ''}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            entry = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='status_changed'
            ).first()
            assert entry is not None
            assert entry.summary.startswith(
                "Status changed from 'mailing_no_contact_made' to 'deprioritize'."
            )
            assert 'Score' in entry.summary

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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 400


class TestMoveToSkipTrace:
    @patch(
        'app.services.hubspot_writeback_service.HubSpotWriteBackService.'
        'push_deal_stage_for_lead'
    )
    def test_completes_current_task_and_creates_skip_trace_handoff(
        self,
        mock_push,
        client,
        app,
    ):
        with app.app_context():
            lead = _make_lead(
                app,
                '822 N Winchester Ave',
                lead_status='mailing_no_contact_made',
                mailing_address='822 N Winchester Ave',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60622',
            )
            current = _make_task(
                app,
                lead.id,
                due_date=date.today() - timedelta(days=1),
                title='Manually skip trace returned letter',
                hubspot_task_id='hs-skip-17',
            )
            crm_task = Task(
                title=current.title,
                status='open',
                source='hubspot_import',
                lead_id=lead.id,
                task_type='custom',
                due_date=datetime.now() - timedelta(days=1),
                hubspot_task_id='hs-skip-17',
            )
            db.session.add(crm_task)
            db.session.commit()

            response = client.post(
                f'/api/leads/{lead.id}/move-to-skip-trace',
                headers=_AUTH_HEADERS,
                json={'complete_task_id': current.id},
            )
            assert response.status_code == 200
            body = json.loads(response.data)
            assert body['lead_status'] == 'skip_trace'
            assert body['completed_task_id'] == current.id
            assert body.get('changed') is True
            assert body.get('already_done') is False

            db.session.refresh(lead)
            db.session.refresh(current)
            db.session.refresh(crm_task)
            assert lead.lead_status == 'skip_trace'
            assert lead.needs_skip_trace is True
            assert current.status == 'completed'
            assert crm_task.status == 'completed'

            handoffs = LeadTask.query.filter_by(
                lead_id=lead.id,
                task_type='skip_trace_owner',
                status='open',
            ).all()
            assert len(handoffs) == 1
            assert handoffs[0].title == 'Awaiting skip trace'
            assert handoffs[0].due_date is None
            mock_push.assert_called_once_with(lead.id, 'skip_trace')

    def test_reuses_existing_skip_trace_task(self, client, app):
        with app.app_context():
            lead = _make_lead(app, '823 N Winchester Ave')
            current = _make_task(app, lead.id, title='Review returned mail')
            mirror = Task(
                title=current.title,
                status='open',
                source='manual',
                lead_id=lead.id,
                task_type=current.task_type,
                due_date=None,
            )
            db.session.add(mirror)
            db.session.commit()
            existing = _make_task(
                app,
                lead.id,
                task_type='skip_trace_owner',
                title='Awaiting skip trace',
            )
            response = client.post(
                f'/api/leads/{lead.id}/move-to-skip-trace',
                headers=_AUTH_HEADERS,
                json={'complete_task_id': current.id},
            )
            assert response.status_code == 200
            assert json.loads(response.data)['skip_trace_task_id'] == existing.id
            db.session.refresh(mirror)
            assert mirror.status == 'completed'
            assert LeadTask.query.filter_by(
                lead_id=lead.id,
                task_type='skip_trace_owner',
                status='open',
            ).count() == 1

    def test_rejects_other_users_lead(self, client, app):
        with app.app_context():
            lead = _make_lead(
                app,
                '824 N Winchester Ave',
                owner_user_id='other-user',
            )
            response = client.post(
                f'/api/leads/{lead.id}/move-to-skip-trace',
                headers=_AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 404

    def test_rejects_non_object_payload(self, client, app):
        with app.app_context():
            lead = _make_lead(app, '824a Invalid Payload St')
            response = client.post(
                f'/api/leads/{lead.id}/move-to-skip-trace',
                headers=_AUTH_HEADERS,
                json=[],
            )
            assert response.status_code == 400

    def test_does_not_complete_existing_skip_trace_handoff(self, client, app):
        with app.app_context():
            lead = _make_lead(app, '824b Existing Skip Trace St')
            handoff = _make_task(
                app,
                lead.id,
                task_type='skip_trace_owner',
                title='Awaiting skip trace',
            )
            response = client.post(
                f'/api/leads/{lead.id}/move-to-skip-trace',
                headers=_AUTH_HEADERS,
                json={'complete_task_id': handoff.id},
            )
            assert response.status_code == 200
            body = json.loads(response.data)
            assert body['lead_status'] == 'skip_trace'
            assert body['completed_task_id'] is None
            assert body['skip_trace_task_id'] == handoff.id
            db.session.refresh(handoff)
            assert handoff.status == 'open'
            db.session.refresh(lead)
            assert lead.lead_status == 'skip_trace'

    def test_completed_analysis_task_preserves_analysis_side_effect(
        self,
        client,
        app,
    ):
        with app.app_context():
            lead = _make_lead(
                app,
                '824c Analysis Complete St',
                analysis_complete=False,
            )
            analysis_task = _make_task(
                app,
                lead.id,
                task_type='run_property_analysis',
                title='Run property analysis',
            )
            response = client.post(
                f'/api/leads/{lead.id}/move-to-skip-trace',
                headers=_AUTH_HEADERS,
                json={'complete_task_id': analysis_task.id},
            )
            assert response.status_code == 200
            db.session.refresh(lead)
            assert lead.analysis_complete is True
            assert LeadTimelineEntry.query.filter_by(
                lead_id=lead.id,
                event_type='property_analysis_completed',
            ).count() == 1

    @pytest.mark.parametrize(
        'terminal_status',
        ['deprioritize', 'deal_won', 'deal_lost', 'suppressed', 'do_not_contact'],
    )
    def test_rejects_terminal_lead_status(
        self,
        terminal_status,
        client,
        app,
    ):
        with app.app_context():
            lead = _make_lead(
                app,
                f'825 {terminal_status} St',
                lead_status=terminal_status,
            )
            response = client.post(
                f'/api/leads/{lead.id}/move-to-skip-trace',
                headers=_AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 422
            body = json.loads(response.data)
            from tests.action_error_asserts import assert_action_error_is_specific
            assert_action_error_is_specific(body)
            assert body['error'] == 'ActionNotApplicableError'
            assert body['error_type'] == 'action_not_applicable'
            assert body['reason_code'] == 'terminal_status'
            assert body.get('message')
            db.session.refresh(lead)
            assert lead.lead_status == terminal_status
            assert LeadTask.query.filter_by(
                lead_id=lead.id,
                task_type='skip_trace_owner',
            ).count() == 0

    @pytest.mark.parametrize(
        'pipeline_status,reason_code',
        [
            ('skip_trace', 'already_skip_trace'),
        ],
    )
    def test_already_in_skip_trace_pipeline_is_idempotent(
        self,
        pipeline_status,
        reason_code,
        client,
        app,
    ):
        with app.app_context():
            lead = _make_lead(
                app,
                f'825b {pipeline_status} St',
                lead_status=pipeline_status,
                needs_skip_trace=True,
            )
            handoff = _make_task(
                app,
                lead.id,
                task_type='skip_trace_owner',
                title='Awaiting skip trace',
            )
            other = _make_task(
                app,
                lead.id,
                title='Should not complete',
            )
            response = client.post(
                f'/api/leads/{lead.id}/move-to-skip-trace',
                headers=_AUTH_HEADERS,
                json={'complete_task_id': other.id},
            )
            assert response.status_code == 200
            body = json.loads(response.data)
            assert body['already_done'] is True
            assert body['changed'] is False
            assert body['reason_code'] == reason_code
            assert body['completed_task_id'] is None
            assert body['skip_trace_task_id'] == handoff.id
            assert body['lead_status'] == pipeline_status
            db.session.refresh(other)
            assert other.status == 'open'
            assert LeadTimelineEntry.query.filter_by(
                lead_id=lead.id,
                event_type='status_changed',
            ).count() == 0

    def test_move_to_skip_trace_from_awaiting_enqueues_skip_trace_column(
        self,
        client,
        app,
    ):
        """Recent-sale hold end leaves awaiting_skip_trace; Move completes verify work."""
        with app.app_context():
            lead = _make_lead(
                app,
                '825c Awaiting Enqueue St',
                lead_status='awaiting_skip_trace',
                needs_skip_trace=True,
            )
            verify = _make_task(
                app,
                lead.id,
                task_type='skip_trace_owner',
                title='Recent-sale hold ended — verify new owner and contact information',
                due_date=date.today(),
            )
            response = client.post(
                f'/api/leads/{lead.id}/move-to-skip-trace',
                headers=_AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 200
            body = json.loads(response.data)
            assert body.get('already_done') is not True
            assert body['lead_status'] == 'skip_trace'
            assert body['completed_task_id'] == verify.id
            db.session.refresh(lead)
            db.session.refresh(verify)
            assert lead.lead_status == 'skip_trace'
            assert lead.needs_skip_trace is True
            assert verify.status == 'completed'
            handoffs = LeadTask.query.filter_by(
                lead_id=lead.id,
                task_type='skip_trace_owner',
                status='open',
            ).all()
            assert len(handoffs) == 1
            assert handoffs[0].id == body['skip_trace_task_id']
            assert handoffs[0].title == 'Awaiting skip trace'
            assert handoffs[0].due_date is None

    def test_moves_selected_task_due_date_without_changing_task(self, client, app):
        with app.app_context():
            sale_date = date.today() - timedelta(days=30)
            lead = _make_lead(
                app,
                '826 Recent Sale Adjustment St',
                acquisition_date=sale_date,
            )
            task = _make_task(
                app,
                lead.id,
                task_type='research_missing_pin',
                title='Keep this task unchanged',
                due_date=date.today(),
            )

            response = client.post(
                f'/api/leads/{lead.id}/adjust-for-recent-sale',
                headers=_AUTH_HEADERS,
                json={'task_id': task.id},
            )

            assert response.status_code == 200
            body = json.loads(response.data)
            db.session.refresh(task)
            assert body['task_id'] == task.id
            assert body['task_created'] is False
            assert task.title == 'Keep this task unchanged'
            assert task.task_type == 'research_missing_pin'
            assert task.due_date == sale_date + timedelta(days=730)

    def test_rejects_lead_without_recent_sale(self, client, app):
        with app.app_context():
            lead = _make_lead(app, '827 No Recent Sale St')
            response = client.post(
                f'/api/leads/{lead.id}/adjust-for-recent-sale',
                headers=_AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 409

    def test_rejects_non_object_json_body(self, client, app):
        with app.app_context():
            lead = _make_lead(
                app,
                '828 Recent Sale Invalid Body St',
                acquisition_date=date.today() - timedelta(days=30),
            )
            response = client.post(
                f'/api/leads/{lead.id}/adjust-for-recent-sale',
                headers=_AUTH_HEADERS,
                json=[],
            )
            assert response.status_code == 400
            assert response.get_json()['error'] == 'Request body must be a JSON object'

    @pytest.mark.parametrize(
        ('body', 'content_type'),
        [('null', 'application/json'), ('{bad json', 'application/json')],
    )
    def test_rejects_null_or_malformed_json_body(self, client, app, body, content_type):
        with app.app_context():
            lead = _make_lead(
                app,
                '829 Recent Sale Malformed Body St',
                acquisition_date=date.today() - timedelta(days=30),
            )
            response = client.post(
                f'/api/leads/{lead.id}/adjust-for-recent-sale',
                headers=_AUTH_HEADERS,
                data=body,
                content_type=content_type,
            )
            assert response.status_code == 400
            assert response.get_json()['error'] == 'Request body must be a JSON object'


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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 400

    def test_create_task_rejects_non_owner(self, client, app):
        """POST /tasks cannot mutate a lead owned by another user."""
        with app.app_context():
            lead = _make_lead(app, '14b Other Owner Task St', owner_user_id='other-user')
            response = client.post(
                f'/api/leads/{lead.id}/tasks',
                data=json.dumps({'title': 'Call owner', 'task_type': 'custom'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 404
            assert LeadTask.query.filter_by(lead_id=lead.id).count() == 0

    def test_create_task_missing_lead_returns_404(self, client, app):
        with app.app_context():
            response = client.post(
                '/api/leads/999999/tasks',
                data=json.dumps({'title': 'Call owner', 'task_type': 'custom'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 404

    def test_create_skip_trace_task_preserves_due_date_and_refreshes_once(self, client, app):
        with app.app_context():
            lead = _make_lead(app, '14c Skip Trace Due Date St')

            with (
                patch('app.services.action_engine_service.ActionEngineService.recompute_and_persist') as recompute,
                patch('app.services.lead_refresh.refresh_lead_scoring') as refresh_scoring,
            ):
                response = client.post(
                    f'/api/leads/{lead.id}/tasks',
                    data=json.dumps({
                        'title': 'Run skip trace',
                        'task_type': 'skip_trace_owner',
                        'due_date': '2026-08-15',
                    }),
                    content_type='application/json',
                    headers=_AUTH_HEADERS,
                )

            assert response.status_code == 201
            data = json.loads(response.data)
            assert data['due_date'] == '2026-08-15'
            task = LeadTask.query.filter_by(lead_id=lead.id, task_type='skip_trace_owner').one()
            assert task.due_date == date(2026, 8, 15)
            recompute.assert_not_called()
            refresh_scoring.assert_called_once_with(lead.id)


class TestUpdateTaskHubSpotWriteback:
    def test_update_task_rejects_non_owner(self, client, app):
        with app.app_context():
            lead = _make_lead(app, 'HS Other Owner St', owner_user_id='other-user')
            task = _make_task(app, lead.id, title='Do not edit')
            response = client.patch(
                f'/api/leads/{lead.id}/tasks/{task.id}',
                data=json.dumps({'title': 'Edited'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )

            assert response.status_code == 404
            db.session.refresh(task)
            assert task.title == 'Do not edit'

    def test_native_task_update_skips_hubspot(self, client, app):
        with app.app_context():
            lead = _make_lead(app, 'HS Native Skip St')
            task = _make_task(app, lead.id, due_date=date(2026, 9, 15), title='Local only')
            with patch(
                'app.services.hubspot_task_completion_service.sync_hubspot_task_properties',
            ) as mock_sync:
                response = client.patch(
                    f'/api/leads/{lead.id}/tasks/{task.id}',
                    data=json.dumps({'due_date': '2026-07-13', 'title': 'Local sooner'}),
                    content_type='application/json',
                    headers=_AUTH_HEADERS,
                )
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['due_date'] == '2026-07-13'
            assert data['title'] == 'Local sooner'
            assert 'hubspot_synced' not in data
            mock_sync.assert_not_called()

    def test_hubspot_task_update_pushes_properties(self, client, app):
        with app.app_context():
            lead = _make_lead(app, 'HS Writeback St')
            task = _make_task(
                app,
                lead.id,
                due_date=date(2026, 9, 15),
                title='Follow up Bob',
                hubspot_task_id='402073870862',
            )
            with patch(
                'app.services.hubspot_task_completion_service.sync_hubspot_task_properties',
                return_value=True,
            ) as mock_sync:
                response = client.patch(
                    f'/api/leads/{lead.id}/tasks/{task.id}',
                    data=json.dumps({'due_date': '2026-07-13', 'title': 'Follow up sooner'}),
                    content_type='application/json',
                    headers=_AUTH_HEADERS,
                )
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['hubspot_synced'] is True
            assert data['due_date'] == '2026-07-13'
            mock_sync.assert_called_once()
            kwargs = mock_sync.call_args.kwargs
            assert mock_sync.call_args.args[0] == '402073870862'
            assert kwargs['title'] == 'Follow up sooner'
            assert kwargs['due_date'] == date(2026, 7, 13)
            assert kwargs['clear_due_date'] is False

    def test_hubspot_sync_failure_still_saves_locally(self, client, app):
        with app.app_context():
            lead = _make_lead(app, 'HS Fail Soft St')
            task = _make_task(
                app,
                lead.id,
                due_date=date(2026, 9, 15),
                title='Keep local',
                hubspot_task_id='hs-fail-1',
            )
            with patch(
                'app.services.hubspot_task_completion_service.sync_hubspot_task_properties',
                return_value=False,
            ):
                response = client.patch(
                    f'/api/leads/{lead.id}/tasks/{task.id}',
                    data=json.dumps({'due_date': '2026-07-14'}),
                    content_type='application/json',
                    headers=_AUTH_HEADERS,
                )
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['hubspot_synced'] is False
            assert data['due_date'] == '2026-07-14'
            db.session.refresh(task)
            assert task.due_date == date(2026, 7, 14)


# ---------------------------------------------------------------------------
# 34.2 — POST /api/leads/<id>/tasks/<task_id>/complete
# ---------------------------------------------------------------------------

class TestCompleteTask:
    def test_complete_task_returns_200(self, client, app):
        """POST /api/leads/<id>/tasks/<task_id>/complete returns 200."""
        with app.app_context():
            lead = _make_lead(app, '15 Complete St')
            task = _make_task(app, lead.id)
            response = client.post(
                f'/api/leads/{lead.id}/tasks/{task.id}/complete',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 200

    def test_complete_task_sets_status_completed(self, client, app):
        """Completing a task sets its status to 'completed'."""
        with app.app_context():
            lead = _make_lead(app, '16 Complete St')
            task = _make_task(app, lead.id)
            client.post(
                f'/api/leads/{lead.id}/tasks/{task.id}/complete',
                headers=_AUTH_HEADERS,
            )
            db.session.refresh(task)
            assert task.status == 'completed'

    def test_complete_task_sets_completed_at(self, client, app):
        """Completing a task sets completed_at timestamp."""
        with app.app_context():
            lead = _make_lead(app, '17 Complete St')
            task = _make_task(app, lead.id)
            client.post(
                f'/api/leads/{lead.id}/tasks/{task.id}/complete',
                headers=_AUTH_HEADERS,
            )
            db.session.refresh(task)
            assert task.completed_at is not None

    def test_complete_task_response_contains_status(self, client, app):
        """Response contains status='completed'."""
        with app.app_context():
            lead = _make_lead(app, '18 Complete St')
            task = _make_task(app, lead.id)
            response = client.post(
                f'/api/leads/{lead.id}/tasks/{task.id}/complete',
                headers=_AUTH_HEADERS,
            )
            data = json.loads(response.data)
            assert data['status'] == 'completed'

    def test_completing_skip_trace_task_clears_handoff_flag(self, client, app):
        with app.app_context():
            lead = _make_lead(
                app,
                '18a Skip Trace Complete St',
                lead_status='skip_trace',
                needs_skip_trace=True,
                mailing_address='100 Owner Ln',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60614',
            )
            task = _make_task(
                app,
                lead.id,
                task_type='skip_trace_owner',
                title='Awaiting skip trace',
            )
            mirror = Task(
                title=task.title,
                status='open',
                source='manual',
                lead_id=lead.id,
                task_type=task.task_type,
            )
            db.session.add(mirror)
            db.session.commit()
            response = client.post(
                f'/api/leads/{lead.id}/tasks/{task.id}/complete',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 200
            db.session.refresh(lead)
            db.session.refresh(mirror)
            assert lead.needs_skip_trace is False
            assert lead.date_skip_traced == date.today()
            assert lead.lead_status == 'mailing_no_contact_made'
            assert mirror.status == 'completed'

    def test_completing_one_duplicate_skip_trace_task_keeps_handoff_open(
        self,
        client,
        app,
    ):
        with app.app_context():
            lead = _make_lead(
                app,
                '18aa Duplicate Skip Trace St',
                lead_status='skip_trace',
                needs_skip_trace=True,
            )
            first = _make_task(
                app,
                lead.id,
                task_type='skip_trace_owner',
                title='Awaiting skip trace one',
            )
            second = _make_task(
                app,
                lead.id,
                task_type='skip_trace_owner',
                title='Awaiting skip trace two',
            )
            response = client.post(
                f'/api/leads/{lead.id}/tasks/{first.id}/complete',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 200
            db.session.refresh(lead)
            db.session.refresh(second)
            assert second.status == 'open'
            assert lead.needs_skip_trace is True
            assert lead.date_skip_traced is None

    def test_duplicate_tasks_complete_their_exact_mirror(self, client, app):
        from app.services.lead_task_service import LeadTaskService

        with app.app_context():
            lead = _make_lead(app, '18ab Exact Mirror St')
            service = LeadTaskService()
            first = service.create(
                lead.id,
                {'title': 'Same-day follow up', 'task_type': 'custom'},
                actor='test-user',
                recompute_action=False,
            )
            second = service.create(
                lead.id,
                {'title': 'Same-day follow up', 'task_type': 'custom'},
                actor='test-user',
                recompute_action=False,
            )
            first_mirror_id = first.mirror_task_id
            second_mirror_id = second.mirror_task_id
            assert first_mirror_id != second_mirror_id

            response = client.post(
                f'/api/leads/{lead.id}/tasks/{second.id}/complete',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 200
            first_mirror = db.session.get(Task, first_mirror_id)
            second_mirror = db.session.get(Task, second_mirror_id)
            assert first_mirror.status == 'open'
            assert second_mirror.status == 'completed'

    def test_complete_task_rejects_non_owner(self, client, app):
        with app.app_context():
            lead = _make_lead(app, '18b Complete Other Owner St', owner_user_id='other-user')
            task = _make_task(app, lead.id)
            response = client.post(
                f'/api/leads/{lead.id}/tasks/{task.id}/complete',
                headers=_AUTH_HEADERS,
            )

            assert response.status_code == 404
            db.session.refresh(task)
            assert task.status == 'open'


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
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 201
            data = response.get_json()
            assert data['summary'] == 'Owner called back.'
            assert data['event_type'] == 'note_added'

    def test_log_note_response_includes_full_entry(self, client, app):
        """POST /api/leads/<id>/notes returns summary and metadata for timeline display."""
        with app.app_context():
            lead = _make_lead(app, '19b Note St')
            response = client.post(
                f'/api/leads/{lead.id}/notes',
                data=json.dumps({'body': 'Left voicemail.'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            data = response.get_json()
            assert data['summary'] == 'Left voicemail.'
            assert data['metadata'] == {'body': 'Left voicemail.'}
            assert data['id'] is not None
            assert data['occurred_at'] is not None

    def test_log_note_creates_timeline_entry(self, client, app):
        """POST /api/leads/<id>/notes creates a note_added timeline entry."""
        with app.app_context():
            lead = _make_lead(app, '20 Note St')
            client.post(
                f'/api/leads/{lead.id}/notes',
                data=json.dumps({'body': 'Left voicemail.'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 400

    def test_log_note_with_contact_metadata(self, client, app):
        """POST /api/leads/<id>/notes stores email contact context in metadata."""
        with app.app_context():
            lead = _make_lead(app, '21b Note St')
            contact, email = _make_contact_with_email(app, lead.id)
            response = client.post(
                f'/api/leads/{lead.id}/notes',
                data=json.dumps({
                    'body': '[Email] Follow up\n\nChecking in on the offer.',
                    'subject': 'Follow up',
                    'contact_id': contact.id,
                    'contact_email_id': email.id,
                    'email_address': 'jane@work.com',
                    'email_label': 'work',
                }),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 201
            data = response.get_json()
            assert 'Jane Doe' in data['summary']
            assert 'jane@work.com' in data['summary']
            assert data['metadata']['contact_name'] == 'Jane Doe'
            assert data['metadata']['email_address'] == 'jane@work.com'
            assert data['event_type'] == 'email_logged'

    def test_log_note_rejects_unlinked_contact(self, client, app):
        """POST /api/leads/<id>/notes rejects contact_id not linked to the lead."""
        with app.app_context():
            lead = _make_lead(app, '21c Note St')
            other_lead = _make_lead(app, '21d Note St')
            contact, _email = _make_contact_with_email(app, other_lead.id)
            response = client.post(
                f'/api/leads/{lead.id}/notes',
                data=json.dumps({
                    'body': 'Test note',
                    'contact_id': contact.id,
                }),
                content_type='application/json',
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 201
            data = response.get_json()
            assert data['event_type'] == 'call_logged'
            assert 'Call logged: answered' in data['summary']
            assert data['metadata']['outcome'] == 'answered'

    def test_log_call_response_includes_summary(self, client, app):
        """POST /api/leads/<id>/calls returns summary for timeline display."""
        with app.app_context():
            lead = _make_lead(app, '22b Call St')
            response = client.post(
                f'/api/leads/{lead.id}/calls',
                data=json.dumps({
                    'outcome': 'voicemail',
                    'notes': 'Left a message about the offer.',
                }),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            data = response.get_json()
            assert 'voicemail' in data['summary']
            assert 'Left a message' in data['summary']

    def test_log_call_with_contact_metadata(self, client, app):
        """POST /api/leads/<id>/calls stores contact and phone in metadata and summary."""
        with app.app_context():
            lead = _make_lead(app, '22c Call St')
            contact, phone = _make_contact_with_phone(app, lead.id)
            response = client.post(
                f'/api/leads/{lead.id}/calls',
                data=json.dumps({
                    'outcome': 'answered',
                    'duration_minutes': 3,
                    'contact_id': contact.id,
                    'contact_phone_id': phone.id,
                    'phone_number': '5551234567',
                    'phone_label': 'mobile',
                }),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 201
            data = response.get_json()
            assert 'Jane Doe' in data['summary']
            assert '5551234567' in data['summary'] or '(555)' in data['summary']
            assert data['metadata']['contact_name'] == 'Jane Doe'
            assert data['metadata']['phone_number'] == '5551234567'

    def test_log_call_creates_timeline_entry(self, client, app):
        """POST /api/leads/<id>/calls creates a call_logged timeline entry."""
        with app.app_context():
            lead = _make_lead(app, '23 Call St')
            client.post(
                f'/api/leads/{lead.id}/calls',
                data=json.dumps({'outcome': 'voicemail'}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 400


class TestLogActivityAuth:
    def test_log_note_without_auth_returns_401(self, client, app):
        """POST /api/leads/<id>/notes requires authentication."""
        with app.app_context():
            lead = _make_lead(app, '21e Note St')
            response = client.post(
                f'/api/leads/{lead.id}/notes',
                data=json.dumps({'body': 'Unauthorized note'}),
                content_type='application/json',
            )
            assert response.status_code == 401

    def test_log_call_without_auth_returns_401(self, client, app):
        """POST /api/leads/<id>/calls requires authentication."""
        with app.app_context():
            lead = _make_lead(app, '24b Call St')
            response = client.post(
                f'/api/leads/{lead.id}/calls',
                data=json.dumps({'outcome': 'answered'}),
                content_type='application/json',
            )
            assert response.status_code == 401

    def test_log_note_actor_resolved_from_bearer_token(self, client, app):
        """Authenticated note log stores actor as the user's display name."""
        with app.app_context():
            lead = _make_lead(app, '21f Note St')
            user = _make_log_user('Jane Logger')
            token = AuthService().issue_token(user)
            response = client.post(
                f'/api/leads/{lead.id}/notes',
                data=json.dumps({'body': 'Logged by Jane'}),
                content_type='application/json',
                headers=_bearer_headers(token),
            )
            assert response.status_code == 201
            data = response.get_json()
            assert data['actor'] == 'Jane Logger'

    def test_log_call_actor_resolved_from_bearer_token(self, client, app):
        """Authenticated call log stores actor as the user's display name."""
        with app.app_context():
            lead = _make_lead(app, '24c Call St')
            user = _make_log_user('Call Logger')
            token = AuthService().issue_token(user)
            response = client.post(
                f'/api/leads/{lead.id}/calls',
                data=json.dumps({'outcome': 'answered'}),
                content_type='application/json',
                headers=_bearer_headers(token),
            )
            assert response.status_code == 201
            data = response.get_json()
            assert data['actor'] == 'Call Logger'


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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
            )
            db.session.refresh(lead)
            assert lead.lead_status == 'do_not_contact'

    def test_dnc_nulls_recommended_action(self, client, app):
        """POST /api/leads/<id>/do-not-contact sets recommended_action to do_not_contact."""
        with app.app_context():
            lead = _make_lead(app, '27 DNC St',
                              lead_status='mailing_no_contact_made',
                              recommended_action='follow_up_now')
            client.post(
                f'/api/leads/{lead.id}/do-not-contact',
                data=json.dumps({}),
                content_type='application/json',
                headers=_AUTH_HEADERS,
            )
            db.session.refresh(lead)
            assert lead.recommended_action == 'do_not_contact'

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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
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
                headers=_AUTH_HEADERS,
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


class TestSaleDateVerification:
    @patch('app.services.cook_county_enrichment_service.ensure_automated_data_sources')
    @patch('app.services.cook_county_enrichment_service.enqueue_cook_county_sale_date_verification')
    @patch('app.services.cook_county_enrichment_service.enrich_cook_county_sale_date')
    def test_verify_sale_date_runs_sync_when_worker_unavailable(
        self, mock_enrich, mock_enqueue, mock_ensure, client, app,
    ):
        """Explicit verify endpoint uses sale-date-only enrichment and returns metadata."""
        with app.app_context():
            lead = _make_lead(
                app,
                '43 Sale Verify St',
                most_recent_sale='6/12/2018',
                property_city='Chicago',
                property_state='IL',
            )
            mock_enqueue.return_value = False
            mock_enrich.return_value = {
                'lead_id': lead.id,
                'skipped': False,
                'plugins_run': 1,
                'success': 0,
                'no_results': 1,
                'failed': 0,
            }

            response = client.post(
                f'/api/leads/{lead.id}/sale-date-verification',
                headers=_AUTH_HEADERS,
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['lead_id'] == lead.id
            assert data['ran_sync'] is True
            assert data['queued'] is False
            assert data['message'] == 'Sale date verified.'
            mock_ensure.assert_called_once()
            mock_enrich.assert_called_once_with(lead.id)

    @patch('app.services.cook_county_enrichment_service.ensure_automated_data_sources')
    @patch('app.services.cook_county_enrichment_service.enqueue_cook_county_sale_date_verification')
    @patch('app.services.cook_county_enrichment_service.enrich_cook_county_sale_date')
    def test_verify_sale_date_surfaces_skip_reason(
        self, mock_enrich, mock_enqueue, mock_ensure, client, app,
    ):
        with app.app_context():
            lead = _make_lead(
                app,
                '44 Sale Skip St',
                most_recent_sale='6/12/2018',
                property_city='Wheaton',
                property_state='IL',
            )
            mock_enqueue.return_value = False
            mock_enrich.return_value = {
                'lead_id': lead.id,
                'skipped': True,
                'skip_reason': 'not_eligible',
                'plugins_run': 0,
            }

            response = client.post(
                f'/api/leads/{lead.id}/sale-date-verification',
                headers=_AUTH_HEADERS,
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data['message'] == 'Not eligible for Cook County enrichment.'
            assert data['summary']['skipped'] is True

