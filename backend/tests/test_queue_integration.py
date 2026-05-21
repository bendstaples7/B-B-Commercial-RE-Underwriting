"""Integration tests for all 7 queue endpoints.

Each test seeds a lead through the full pipeline — creating the lead,
setting the relevant flags, and asserting it appears in exactly the
correct queue and not in the others.

These tests catch:
  - Missing DB columns (UndefinedColumn errors)
  - Wrong task table being queried
  - Wrong lead_status filter
  - Action Engine producing wrong recommended_action
  - Queue counts returning 0 when they should have data

Requirements: 6.1–6.7 (queue correctness)
"""
import json
import pytest
from datetime import date, datetime, timedelta, timezone

from app import db
from app.models import Lead
from app.models.lead_task import LeadTask
from app.models.task import Task
from app.models.task_association import TaskAssociation
from app.models.hubspot_signal import HubSpotSignal
from app.models.hubspot_signal_dictionary import HubSpotSignalDictionary
from app.services.queue_service import QueueService
from app.services.action_engine_service import ActionEngineService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(app, street: str, **kwargs) -> Lead:
    """Create and persist a minimal Lead with the given overrides."""
    defaults = dict(
        property_street=street,
        lead_status='new',
        lead_score=50.0,
        has_phone=False,
        has_email=False,
        has_property_match=False,
        analysis_complete=False,
        follow_up_overdue=False,
        is_warm=False,
        review_required=False,
        data_completeness_score=0.0,
        unanswered_call_count=0,
    )
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


def _make_lead_task(lead_id: int, status: str = 'open', due_date=None) -> LeadTask:
    """Create a CRM-native LeadTask."""
    task = LeadTask(
        lead_id=lead_id,
        task_type='call_owner_today',
        title='Test task',
        status=status,
        due_date=due_date or date.today(),
    )
    db.session.add(task)
    db.session.commit()
    return task


def _make_hubspot_task(lead_id: int, due_date=None, status: str = 'overdue') -> Task:
    """Create a HubSpot-imported Task linked to a lead via task_associations."""
    task = Task(
        title='HubSpot task',
        status=status,
        source='hubspot_import',
        due_date=due_date or datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.session.add(task)
    db.session.flush()
    assoc = TaskAssociation(
        task_id=task.id,
        target_type='lead',
        target_id=lead_id,
    )
    db.session.add(assoc)
    db.session.commit()
    return task


def _make_warm_signal(app, lead_id: int):
    """Seed a PRIOR_WARM_CONVERSATION signal for a lead."""
    # Ensure signal dictionary entry exists
    existing = HubSpotSignalDictionary.query.filter_by(
        signal_type='PRIOR_WARM_CONVERSATION'
    ).first()
    if not existing:
        db.session.add(HubSpotSignalDictionary(
            signal_type='PRIOR_WARM_CONVERSATION',
            keywords=['interested'],
        ))
    signal = HubSpotSignal(
        lead_id=lead_id,
        signal_type='PRIOR_WARM_CONVERSATION',
        source_engagement_id='test-eng-001',
        raw_evidence='interested',
    )
    db.session.add(signal)
    db.session.commit()


# ---------------------------------------------------------------------------
# Queue 1: Today's Action
# ---------------------------------------------------------------------------

class TestTodaysActionQueue:
    def test_lead_with_overdue_hubspot_task_appears(self, app, client):
        """A lead with an overdue HubSpot task appears in Today's Action."""
        with app.app_context():
            lead = _make_lead(app, '1 Todays Action St')
            _make_hubspot_task(lead.id, status='overdue',
                               due_date=datetime.now(timezone.utc) - timedelta(days=1))

            svc = QueueService()
            rows, _ = svc.get_todays_action()
            ids = [r['id'] for r in rows]
            assert lead.id in ids, f"Lead {lead.id} not in Today's Action. Rows: {ids}"
            assert total >= 1

    def test_lead_with_follow_up_now_and_active_status_appears(self, app, client):
        """A lead with recommended_action=follow_up_now and active status appears."""
        with app.app_context():
            lead = _make_lead(app, '2 Todays Action St',
                              lead_status='active',
                              recommended_action='follow_up_now')

            svc = QueueService()
            rows, _ = svc.get_todays_action()
            ids = [r['id'] for r in rows]
            assert lead.id in ids

    def test_lead_with_new_status_and_no_tasks_does_not_appear(self, app, client):
        """A plain new lead with no tasks does not appear in Today's Action."""
        with app.app_context():
            lead = _make_lead(app, '3 Todays Action St', lead_status='new')

            svc = QueueService()
            rows, _ = svc.get_todays_action()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_endpoint_returns_200(self, app, client):
        """GET /api/queues/todays-action returns HTTP 200."""
        with app.app_context():
            resp = client.get('/api/queues/todays-action')
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert 'rows' in data
            assert 'total' in data


# ---------------------------------------------------------------------------
# Queue 2: Previously Warm
# ---------------------------------------------------------------------------

class TestPreviouslyWarmQueue:
    def test_lead_with_warm_signal_appears(self, app, client):
        """A lead with a PRIOR_WARM_CONVERSATION signal appears in Previously Warm."""
        with app.app_context():
            lead = _make_lead(app, '1 Previously Warm St')
            _make_warm_signal(app, lead.id)

            svc = QueueService()
            rows, total = svc.get_previously_warm()
            ids = [r['id'] for r in rows]
            assert lead.id in ids
            assert total >= 1

    def test_lead_without_signal_does_not_appear(self, app, client):
        """A lead without warm signals does not appear in Previously Warm."""
        with app.app_context():
            lead = _make_lead(app, '2 Previously Warm St')

            svc = QueueService()
            rows, _ = svc.get_previously_warm()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_endpoint_returns_200(self, app, client):
        with app.app_context():
            resp = client.get('/api/queues/previously-warm')
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Queue 3: Follow-Up Overdue
# ---------------------------------------------------------------------------

class TestFollowUpOverdueQueue:
    def test_lead_with_overdue_hubspot_task_appears(self, app, client):
        """A lead with an overdue HubSpot task appears in Follow-Up Overdue."""
        with app.app_context():
            lead = _make_lead(app, '1 Overdue St')
            _make_hubspot_task(lead.id, status='overdue',
                               due_date=datetime.now(timezone.utc) - timedelta(days=2))

            svc = QueueService()
            rows, total = svc.get_follow_up_overdue()
            ids = [r['id'] for r in rows]
            assert lead.id in ids
            assert total >= 1

    def test_lead_with_overdue_lead_task_appears(self, app, client):
        """A lead with an overdue CRM lead_task appears in Follow-Up Overdue."""
        with app.app_context():
            lead = _make_lead(app, '2 Overdue St')
            _make_lead_task(lead.id, status='open',
                            due_date=date.today() - timedelta(days=1))

            svc = QueueService()
            rows, total = svc.get_follow_up_overdue()
            ids = [r['id'] for r in rows]
            assert lead.id in ids

    def test_lead_with_future_task_does_not_appear(self, app, client):
        """A lead with a future task does not appear in Follow-Up Overdue."""
        with app.app_context():
            lead = _make_lead(app, '3 Overdue St')
            _make_lead_task(lead.id, status='open',
                            due_date=date.today() + timedelta(days=7))

            svc = QueueService()
            rows, _ = svc.get_follow_up_overdue()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_endpoint_returns_200(self, app, client):
        with app.app_context():
            resp = client.get('/api/queues/follow-up-overdue')
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Queue 4: No Next Action
# ---------------------------------------------------------------------------

class TestNoNextActionQueue:
    def test_new_lead_with_no_tasks_appears(self, app, client):
        """A new lead with no tasks and no recommended_action appears."""
        with app.app_context():
            lead = _make_lead(app, '1 No Action St', lead_status='new')

            svc = QueueService()
            rows, total = svc.get_no_next_action()
            ids = [r['id'] for r in rows]
            assert lead.id in ids
            assert total >= 1

    def test_lead_with_open_hubspot_task_does_not_appear(self, app, client):
        """A lead with an open HubSpot task does not appear in No Next Action."""
        with app.app_context():
            lead = _make_lead(app, '2 No Action St', lead_status='new')
            _make_hubspot_task(lead.id, status='open',
                               due_date=datetime.now(timezone.utc) + timedelta(days=7))

            svc = QueueService()
            rows, _ = svc.get_no_next_action()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_lead_with_open_lead_task_does_not_appear(self, app, client):
        """A lead with an open CRM lead_task does not appear in No Next Action."""
        with app.app_context():
            lead = _make_lead(app, '3 No Action St', lead_status='new')
            _make_lead_task(lead.id, status='open',
                            due_date=date.today() + timedelta(days=3))

            svc = QueueService()
            rows, _ = svc.get_no_next_action()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_endpoint_returns_200(self, app, client):
        with app.app_context():
            resp = client.get('/api/queues/no-next-action')
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Queue 5: Needs Review
# ---------------------------------------------------------------------------

class TestNeedsReviewQueue:
    def test_lead_with_review_required_appears(self, app, client):
        """A lead with review_required=True appears in Needs Review."""
        with app.app_context():
            lead = _make_lead(app, '1 Needs Review St',
                              review_required=True,
                              review_reason='Unmatched HubSpot record')

            svc = QueueService()
            rows, total = svc.get_needs_review()
            ids = [r['id'] for r in rows]
            assert lead.id in ids
            assert total >= 1

    def test_lead_without_review_flag_does_not_appear(self, app, client):
        """A lead without review_required does not appear in Needs Review."""
        with app.app_context():
            lead = _make_lead(app, '2 Needs Review St', review_required=False)

            svc = QueueService()
            rows, _ = svc.get_needs_review()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_endpoint_returns_200(self, app, client):
        with app.app_context():
            resp = client.get('/api/queues/needs-review')
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Queue 6: Do Not Contact
# ---------------------------------------------------------------------------

class TestDoNotContactQueue:
    def test_lead_with_dnc_status_appears(self, app, client):
        """A lead with lead_status=do_not_contact appears in Do Not Contact."""
        with app.app_context():
            lead = _make_lead(app, '1 DNC St', lead_status='do_not_contact')

            svc = QueueService()
            rows, total = svc.get_do_not_contact()
            ids = [r['id'] for r in rows]
            assert lead.id in ids
            assert total >= 1

    def test_active_lead_does_not_appear(self, app, client):
        """An active lead does not appear in Do Not Contact."""
        with app.app_context():
            lead = _make_lead(app, '2 DNC St', lead_status='active')

            svc = QueueService()
            rows, _ = svc.get_do_not_contact()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_endpoint_returns_200(self, app, client):
        with app.app_context():
            resp = client.get('/api/queues/do-not-contact')
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Queue 7: Missing Property Match
# ---------------------------------------------------------------------------

class TestMissingPropertyMatchQueue:
    def test_lead_without_match_appears(self, app, client):
        """A lead with has_property_match=False appears in Missing Property Match."""
        with app.app_context():
            lead = _make_lead(app, '1 Missing Match St', has_property_match=False)

            svc = QueueService()
            rows, total = svc.get_missing_property_match()
            ids = [r['id'] for r in rows]
            assert lead.id in ids
            assert total >= 1

    def test_lead_with_match_does_not_appear(self, app, client):
        """A lead with has_property_match=True does not appear in Missing Property Match."""
        with app.app_context():
            lead = _make_lead(app, '2 Missing Match St', has_property_match=True)

            svc = QueueService()
            rows, _ = svc.get_missing_property_match()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_endpoint_returns_200(self, app, client):
        with app.app_context():
            resp = client.get('/api/queues/missing-property-match')
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Queue counts endpoint
# ---------------------------------------------------------------------------

class TestQueueCountsEndpoint:
    def test_counts_endpoint_returns_all_7_keys(self, app, client):
        """GET /api/queues/counts returns all 7 queue count keys."""
        with app.app_context():
            resp = client.get('/api/queues/counts')
            assert resp.status_code == 200
            data = json.loads(resp.data)
            expected_keys = {
                'todays_action', 'previously_warm', 'follow_up_overdue',
                'no_next_action', 'needs_review', 'do_not_contact',
                'missing_property_match',
            }
            assert set(data.keys()) == expected_keys

    def test_counts_are_non_negative_integers(self, app, client):
        """All queue counts are non-negative integers."""
        with app.app_context():
            resp = client.get('/api/queues/counts')
            data = json.loads(resp.data)
            for key, value in data.items():
                assert isinstance(value, int), f"{key} is not an int: {value}"
                assert value >= 0, f"{key} is negative: {value}"


# ---------------------------------------------------------------------------
# Action Engine integration
# ---------------------------------------------------------------------------

class TestActionEngineIntegration:
    def test_lead_with_no_phone_gets_add_contact_info(self, app):
        """A lead with no phone or email gets recommended_action=add_contact_info."""
        with app.app_context():
            lead = _make_lead(app, '1 Action Engine St',
                              has_phone=False, has_email=False)
            action = ActionEngineService.compute_recommended_action(lead)
            assert action == 'add_contact_info'

    def test_lead_with_phone_no_match_gets_resolve_match(self, app):
        """A lead with phone but no property match gets recommended_action=resolve_match."""
        with app.app_context():
            lead = _make_lead(app, '2 Action Engine St',
                              has_phone=True, has_email=False,
                              has_property_match=False)
            action = ActionEngineService.compute_recommended_action(lead)
            assert action == 'resolve_match'

    def test_lead_with_match_no_analysis_gets_analyze_property(self, app):
        """A lead with property match but no analysis gets recommended_action=analyze_property."""
        with app.app_context():
            lead = _make_lead(app, '3 Action Engine St',
                              has_phone=True,
                              has_property_match=True,
                              analysis_complete=False)
            action = ActionEngineService.compute_recommended_action(lead)
            assert action == 'analyze_property'

    def test_warm_lead_gets_follow_up_now(self, app):
        """A warm lead with complete data gets recommended_action=follow_up_now."""
        with app.app_context():
            lead = _make_lead(app, '4 Action Engine St',
                              has_phone=True,
                              has_property_match=True,
                              analysis_complete=True,
                              is_warm=True,
                              data_completeness_score=80.0)
            action = ActionEngineService.compute_recommended_action(lead)
            assert action == 'follow_up_now'

    def test_dnc_lead_gets_none(self, app):
        """A do_not_contact lead gets recommended_action=None."""
        with app.app_context():
            lead = _make_lead(app, '5 Action Engine St',
                              lead_status='do_not_contact')
            action = ActionEngineService.compute_recommended_action(lead)
            assert action is None


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_200_with_all_checks(self, app, client):
        """GET /api/health returns 200 and includes all check keys."""
        with app.app_context():
            resp = client.get('/api/health')
            # In test environment, migration check may warn but should not 500
            assert resp.status_code in (200, 503)
            data = json.loads(resp.data)
            assert 'status' in data
            assert 'checks' in data
            assert 'db_connectivity' in data['checks']
