"""
Integration tests for Bulk Action API endpoints and bulk recomputation.

Covers:
  34.3 — Bulk suppress, bulk create-task, bulk DNC; partial failure counts
  34.5 — Bulk recomputation of 1,000 leads without error
"""
import json
import pytest

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry
from app.services.action_engine_service import ActionEngineService


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


def _make_task(app, lead_id, status='open', task_type='custom', title='Test task'):
    task = LeadTask(
        lead_id=lead_id,
        task_type=task_type,
        title=title,
        status=status,
        created_by='test',
    )
    db.session.add(task)
    db.session.commit()
    return task


def _make_leads_batch(app, count, base_street='Bulk St', **kwargs):
    """Create count leads and return their IDs."""
    leads = []
    for i in range(count):
        lead = _make_lead(app, f'{i + 1} {base_street}', **kwargs)
        leads.append(lead)
    return leads


# ---------------------------------------------------------------------------
# 34.3 — POST /api/leads/bulk/suppress
# ---------------------------------------------------------------------------

class TestBulkSuppress:
    def test_bulk_suppress_returns_200(self, client, app):
        """POST /api/leads/bulk/suppress returns HTTP 200."""
        with app.app_context():
            leads = _make_leads_batch(app, 3, base_street='Suppress St')
            response = client.post(
                '/api/leads/bulk/suppress',
                data=json.dumps({'lead_ids': [lead.id for lead in leads]}),
                content_type='application/json',
            )
            assert response.status_code == 200

    def test_bulk_suppress_sets_status_suppressed(self, client, app):
        """Bulk suppress sets lead_status to 'suppressed' for all leads."""
        with app.app_context():
            leads = _make_leads_batch(app, 3, base_street='Suppress2 St')
            lead_ids = [lead.id for lead in leads]
            client.post(
                '/api/leads/bulk/suppress',
                data=json.dumps({'lead_ids': lead_ids}),
                content_type='application/json',
            )
            for lead in leads:
                db.session.refresh(lead)
                assert lead.lead_status == 'suppressed'

    def test_bulk_suppress_nulls_recommended_action(self, client, app):
        """Bulk suppress sets recommended_action to null for all leads."""
        with app.app_context():
            leads = _make_leads_batch(app, 2, base_street='Suppress3 St',
                                      recommended_action='follow_up_now')
            lead_ids = [lead.id for lead in leads]
            client.post(
                '/api/leads/bulk/suppress',
                data=json.dumps({'lead_ids': lead_ids}),
                content_type='application/json',
            )
            for lead in leads:
                db.session.refresh(lead)
                assert lead.recommended_action is None

    def test_bulk_suppress_returns_correct_success_count(self, client, app):
        """Response contains correct successes count."""
        with app.app_context():
            leads = _make_leads_batch(app, 4, base_street='Suppress4 St')
            response = client.post(
                '/api/leads/bulk/suppress',
                data=json.dumps({'lead_ids': [lead.id for lead in leads]}),
                content_type='application/json',
            )
            data = json.loads(response.data)
            assert data['successes'] == 4
            assert data['failures'] == 0

    def test_bulk_suppress_partial_failure_counts(self, client, app):
        """Non-existent lead IDs count as failures; valid IDs count as successes."""
        with app.app_context():
            lead = _make_lead(app, '1 PartialSuppress St')
            # Mix valid ID with non-existent IDs
            response = client.post(
                '/api/leads/bulk/suppress',
                data=json.dumps({'lead_ids': [lead.id, 99991, 99992]}),
                content_type='application/json',
            )
            data = json.loads(response.data)
            assert data['successes'] == 1
            assert data['failures'] == 2

    def test_bulk_suppress_appends_timeline_entries(self, client, app):
        """Bulk suppress appends a status_changed timeline entry for each lead."""
        with app.app_context():
            leads = _make_leads_batch(app, 2, base_street='Suppress5 St')
            lead_ids = [lead.id for lead in leads]
            client.post(
                '/api/leads/bulk/suppress',
                data=json.dumps({'lead_ids': lead_ids}),
                content_type='application/json',
            )
            for lead in leads:
                entry = LeadTimelineEntry.query.filter_by(
                    lead_id=lead.id, event_type='status_changed'
                ).first()
                assert entry is not None

    def test_bulk_suppress_empty_list_returns_zero_counts(self, client, app):
        """Bulk suppress with empty lead_ids returns 400 (schema requires min 1 ID)."""
        with app.app_context():
            response = client.post(
                '/api/leads/bulk/suppress',
                data=json.dumps({'lead_ids': []}),
                content_type='application/json',
            )
            assert response.status_code == 400


# ---------------------------------------------------------------------------
# 34.3 — POST /api/leads/bulk/create-task
# ---------------------------------------------------------------------------

class TestBulkCreateTask:
    def test_bulk_create_task_returns_200(self, client, app):
        """POST /api/leads/bulk/create-task returns HTTP 200."""
        with app.app_context():
            leads = _make_leads_batch(app, 3, base_street='BulkTask St')
            response = client.post(
                '/api/leads/bulk/create-task',
                data=json.dumps({
                    'lead_ids': [lead.id for lead in leads],
                    'task_data': {'title': 'Bulk task', 'task_type': 'custom'},
                }),
                content_type='application/json',
            )
            assert response.status_code == 200

    def test_bulk_create_task_creates_tasks_for_all_leads(self, client, app):
        """Bulk create-task creates one task per lead."""
        with app.app_context():
            leads = _make_leads_batch(app, 3, base_street='BulkTask2 St')
            lead_ids = [lead.id for lead in leads]
            client.post(
                '/api/leads/bulk/create-task',
                data=json.dumps({
                    'lead_ids': lead_ids,
                    'task_data': {'title': 'Follow up', 'task_type': 'custom'},
                }),
                content_type='application/json',
            )
            for lead in leads:
                task = LeadTask.query.filter_by(
                    lead_id=lead.id, title='Follow up'
                ).first()
                assert task is not None
                assert task.status == 'open'

    def test_bulk_create_task_returns_correct_success_count(self, client, app):
        """Response contains correct successes count."""
        with app.app_context():
            leads = _make_leads_batch(app, 5, base_street='BulkTask3 St')
            response = client.post(
                '/api/leads/bulk/create-task',
                data=json.dumps({
                    'lead_ids': [lead.id for lead in leads],
                    'task_data': {'title': 'Outreach', 'task_type': 'custom'},
                }),
                content_type='application/json',
            )
            data = json.loads(response.data)
            assert data['successes'] == 5
            assert data['failures'] == 0

    def test_bulk_create_task_missing_lead_ids_returns_400(self, client, app):
        """POST /api/leads/bulk/create-task without lead_ids returns 400."""
        with app.app_context():
            response = client.post(
                '/api/leads/bulk/create-task',
                data=json.dumps({'task_data': {'title': 'Test', 'task_type': 'custom'}}),
                content_type='application/json',
            )
            assert response.status_code == 400

    def test_bulk_create_task_partial_failure_counts(self, client, app):
        """Non-existent lead IDs count as failures; valid IDs count as successes."""
        with app.app_context():
            lead = _make_lead(app, '1 PartialTask St')
            response = client.post(
                '/api/leads/bulk/create-task',
                data=json.dumps({
                    'lead_ids': [lead.id, 99993, 99994],
                    'task_data': {'title': 'Test task', 'task_type': 'custom'},
                }),
                content_type='application/json',
            )
            data = json.loads(response.data)
            assert data['successes'] == 1
            assert data['failures'] == 2


# ---------------------------------------------------------------------------
# 34.3 — POST /api/leads/bulk/do-not-contact
# ---------------------------------------------------------------------------

class TestBulkDoNotContact:
    def test_bulk_dnc_returns_200(self, client, app):
        """POST /api/leads/bulk/do-not-contact returns HTTP 200."""
        with app.app_context():
            leads = _make_leads_batch(app, 3, base_street='BulkDNC St')
            response = client.post(
                '/api/leads/bulk/do-not-contact',
                data=json.dumps({'lead_ids': [lead.id for lead in leads]}),
                content_type='application/json',
            )
            assert response.status_code == 200

    def test_bulk_dnc_sets_status_do_not_contact(self, client, app):
        """Bulk DNC sets lead_status to 'do_not_contact' for all leads."""
        with app.app_context():
            leads = _make_leads_batch(app, 3, base_street='BulkDNC2 St')
            lead_ids = [lead.id for lead in leads]
            client.post(
                '/api/leads/bulk/do-not-contact',
                data=json.dumps({'lead_ids': lead_ids}),
                content_type='application/json',
            )
            for lead in leads:
                db.session.refresh(lead)
                assert lead.lead_status == 'do_not_contact'

    def test_bulk_dnc_nulls_recommended_action(self, client, app):
        """Bulk DNC sets recommended_action to null for all leads."""
        with app.app_context():
            leads = _make_leads_batch(app, 2, base_street='BulkDNC3 St',
                                      recommended_action='follow_up_now')
            lead_ids = [lead.id for lead in leads]
            client.post(
                '/api/leads/bulk/do-not-contact',
                data=json.dumps({'lead_ids': lead_ids}),
                content_type='application/json',
            )
            for lead in leads:
                db.session.refresh(lead)
                assert lead.recommended_action is None

    def test_bulk_dnc_cancels_open_tasks(self, client, app):
        """Bulk DNC cancels all open tasks for each lead."""
        with app.app_context():
            leads = _make_leads_batch(app, 2, base_street='BulkDNC4 St')
            tasks = [_make_task(app, lead.id) for lead in leads]
            lead_ids = [lead.id for lead in leads]
            client.post(
                '/api/leads/bulk/do-not-contact',
                data=json.dumps({'lead_ids': lead_ids}),
                content_type='application/json',
            )
            for task in tasks:
                db.session.refresh(task)
                assert task.status == 'cancelled'

    def test_bulk_dnc_returns_correct_success_count(self, client, app):
        """Response contains correct successes count."""
        with app.app_context():
            leads = _make_leads_batch(app, 4, base_street='BulkDNC5 St')
            response = client.post(
                '/api/leads/bulk/do-not-contact',
                data=json.dumps({'lead_ids': [lead.id for lead in leads]}),
                content_type='application/json',
            )
            data = json.loads(response.data)
            assert data['successes'] == 4
            assert data['failures'] == 0

    def test_bulk_dnc_partial_failure_counts(self, client, app):
        """Non-existent lead IDs count as failures; valid IDs count as successes."""
        with app.app_context():
            lead = _make_lead(app, '1 PartialDNC St')
            response = client.post(
                '/api/leads/bulk/do-not-contact',
                data=json.dumps({'lead_ids': [lead.id, 99995, 99996]}),
                content_type='application/json',
            )
            data = json.loads(response.data)
            assert data['successes'] == 1
            assert data['failures'] == 2

    def test_bulk_dnc_appends_timeline_entries(self, client, app):
        """Bulk DNC appends a status_changed timeline entry for each lead."""
        with app.app_context():
            leads = _make_leads_batch(app, 2, base_street='BulkDNC6 St')
            lead_ids = [lead.id for lead in leads]
            client.post(
                '/api/leads/bulk/do-not-contact',
                data=json.dumps({'lead_ids': lead_ids}),
                content_type='application/json',
            )
            for lead in leads:
                entry = LeadTimelineEntry.query.filter_by(
                    lead_id=lead.id, event_type='status_changed'
                ).first()
                assert entry is not None


# ---------------------------------------------------------------------------
# 34.5 — Bulk recomputation of 1,000 leads without error
# ---------------------------------------------------------------------------

class TestBulkRecompute:
    def test_bulk_recompute_1000_leads_without_error(self, app):
        """bulk_recompute processes 1,000 leads without raising an exception."""
        with app.app_context():
            # Create 1,000 leads with varied signal combinations
            lead_ids = []
            for i in range(1000):
                # Vary signals to exercise different rule branches
                has_phone = i % 3 != 0
                has_email = i % 5 != 0
                has_property_match = i % 4 != 0
                analysis_complete = has_property_match and (i % 2 == 0)
                lead_score = 40.0 + (i % 60)
                data_completeness = 30.0 + (i % 70)

                lead = Lead(
                    property_street=f'{i + 1} Bulk Recompute St',
                    lead_status='mailing_no_contact_made',
                    has_phone=has_phone,
                    has_email=has_email,
                    has_property_match=has_property_match,
                    analysis_complete=analysis_complete,
                    follow_up_overdue=False,
                    is_warm=False,
                    lead_score=lead_score,
                    data_completeness_score=data_completeness,
                    recommended_action=None,
                    review_required=False,
                    unanswered_call_count=0,
                )
                db.session.add(lead)
                if (i + 1) % 100 == 0:
                    db.session.commit()
                else:
                    lead_ids.append(None)  # placeholder

            db.session.commit()

            # Collect actual IDs after commit
            all_leads = Lead.query.filter(
                Lead.property_street.like('% Bulk Recompute St')
            ).all()
            actual_ids = [l.id for l in all_leads]
            assert len(actual_ids) == 1000

            # Run bulk recompute directly (not via Celery broker)
            processed = ActionEngineService.bulk_recompute(actual_ids)

            assert processed == 1000

    def test_bulk_recompute_assigns_recommended_action(self, app):
        """bulk_recompute assigns a recommended_action to each active lead."""
        with app.app_context():
            # Create 10 leads with known signals
            leads = []
            for i in range(10):
                lead = Lead(
                    property_street=f'{i + 1} RA Assign St',
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
                db.session.add(lead)
                leads.append(lead)
            db.session.commit()

            lead_ids = [lead.id for lead in leads]
            ActionEngineService.bulk_recompute(lead_ids)

            for lead in leads:
                db.session.refresh(lead)
                # Active leads with all signals set should get a non-null RA
                assert lead.recommended_action is not None

    def test_bulk_recompute_all_leads_when_no_ids_given(self, app):
        """bulk_recompute(None) processes all leads in the database."""
        with app.app_context():
            # Create a small set of leads
            for i in range(5):
                lead = Lead(
                    property_street=f'{i + 1} AllLeads St',
                    lead_status='mailing_no_contact_made',
                    has_phone=True,
                    has_email=True,
                    has_property_match=True,
                    analysis_complete=True,
                    follow_up_overdue=False,
                    is_warm=False,
                    lead_score=55.0,
                    data_completeness_score=65.0,
                    recommended_action=None,
                    review_required=False,
                    unanswered_call_count=0,
                )
                db.session.add(lead)
            db.session.commit()

            # bulk_recompute with None processes all leads
            processed = ActionEngineService.bulk_recompute(None)
            assert processed >= 5

    def test_bulk_recompute_returns_processed_count(self, app):
        """bulk_recompute returns the exact count of leads processed."""
        with app.app_context():
            leads = []
            for i in range(7):
                lead = Lead(
                    property_street=f'{i + 1} Count St',
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
                db.session.add(lead)
                leads.append(lead)
            db.session.commit()

            lead_ids = [lead.id for lead in leads]
            processed = ActionEngineService.bulk_recompute(lead_ids)
            assert processed == 7

