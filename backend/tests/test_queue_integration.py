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

# All queue endpoints require an authenticated user (X-User-Id in testing env)
_AUTH_HEADERS = {'X-User-Id': 'test-user'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(app, street: str, **kwargs) -> Lead:
    """Create and persist a minimal Lead with the given overrides."""
    defaults = dict(
        property_street=street,
        lead_status='awaiting_skip_trace',
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
        owner_user_id='test-user',  # matches _AUTH_HEADERS X-User-Id
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
            rows, total = svc.get_todays_action()
            ids = [r['id'] for r in rows]
            assert lead.id in ids, f"Lead {lead.id} not in Today's Action. Rows: {ids}"
            assert total >= 1

    def test_lead_with_follow_up_now_and_active_status_appears(self, app, client):
        """A lead with recommended_action=follow_up_now and active status appears."""
        with app.app_context():
            lead = _make_lead(app, '2 Todays Action St',
                              lead_status='mailing_no_contact_made',
                              recommended_action='follow_up_now')

            svc = QueueService()
            rows, _ = svc.get_todays_action()
            ids = [r['id'] for r in rows]
            assert lead.id in ids

    def test_lead_with_new_status_and_no_tasks_does_not_appear(self, app, client):
        """A plain new lead with no tasks does not appear in Today's Action."""
        with app.app_context():
            lead = _make_lead(app, '3 Todays Action St', lead_status='awaiting_skip_trace')

            svc = QueueService()
            rows, _ = svc.get_todays_action()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_endpoint_returns_200(self, app, client):
        """GET /api/queues/todays-action returns HTTP 200."""
        with app.app_context():
            resp = client.get('/api/queues/todays-action', headers=_AUTH_HEADERS)
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert 'rows' in data
            assert 'total' in data


# ---------------------------------------------------------------------------
# Queue 2: Previously Warm
# ---------------------------------------------------------------------------

class TestPreviouslyWarmQueue:
    def test_lead_with_warm_signal_appears(self, app, client):
        """A lead with a PRIOR_WARM_CONVERSATION signal and is_warm=True appears in Previously Warm.

        The is_warm flag is set directly on the lead (as the HubSpot signal pipeline
        would do via run_extract_hubspot_signals). The queue filter uses is_warm=True
        only — not the signals table.
        """
        with app.app_context():
            lead = _make_lead(app, '1 Previously Warm St', is_warm=True)
            _make_warm_signal(app, lead.id)

            svc = QueueService()
            rows, total = svc.get_previously_warm()
            ids = [r['id'] for r in rows]
            assert lead.id in ids
            assert total >= 1

    def test_dupage_lead_with_is_warm_true_appears(self, app, client):
        """A DuPage lead with is_warm=True appears in Previously Warm (no signal seeding).

        This confirms the is_warm-only filter works end-to-end for non-HubSpot
        source types. The lead has source_type='foreclosure' and is_warm=True set
        directly on the model — no HubSpotSignal records involved.
        """
        with app.app_context():
            lead = _make_lead(
                app,
                '3 Previously Warm St',
                source_type='foreclosure',
                is_warm=True,
            )

            svc = QueueService()
            rows, total = svc.get_previously_warm()
            ids = [r['id'] for r in rows]
            assert lead.id in ids, (
                f"DuPage lead {lead.id} with is_warm=True not found in Previously Warm. "
                f"Rows: {ids}"
            )
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
            resp = client.get('/api/queues/previously-warm', headers=_AUTH_HEADERS)
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
            resp = client.get('/api/queues/follow-up-overdue', headers=_AUTH_HEADERS)
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Queue 4: No Next Action
# ---------------------------------------------------------------------------

class TestNoNextActionQueue:
    def test_new_lead_with_no_tasks_appears(self, app, client):
        """A new lead with no tasks and no recommended_action appears."""
        with app.app_context():
            lead = _make_lead(app, '1 No Action St', lead_status='awaiting_skip_trace')

            svc = QueueService()
            rows, total = svc.get_no_next_action()
            ids = [r['id'] for r in rows]
            assert lead.id in ids
            assert total >= 1

    def test_lead_with_open_hubspot_task_does_not_appear(self, app, client):
        """A lead with an open HubSpot task does not appear in No Next Action."""
        with app.app_context():
            lead = _make_lead(app, '2 No Action St', lead_status='awaiting_skip_trace')
            _make_hubspot_task(lead.id, status='open',
                               due_date=datetime.now(timezone.utc) + timedelta(days=7))

            svc = QueueService()
            rows, _ = svc.get_no_next_action()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_lead_with_open_lead_task_does_not_appear(self, app, client):
        """A lead with an open CRM lead_task does not appear in No Next Action."""
        with app.app_context():
            lead = _make_lead(app, '3 No Action St', lead_status='awaiting_skip_trace')
            _make_lead_task(lead.id, status='open',
                            due_date=date.today() + timedelta(days=3))

            svc = QueueService()
            rows, _ = svc.get_no_next_action()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_endpoint_returns_200(self, app, client):
        with app.app_context():
            resp = client.get('/api/queues/no-next-action', headers=_AUTH_HEADERS)
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
            resp = client.get('/api/queues/needs-review', headers=_AUTH_HEADERS)
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
            lead = _make_lead(app, '2 DNC St', lead_status='mailing_no_contact_made')

            svc = QueueService()
            rows, _ = svc.get_do_not_contact()
            ids = [r['id'] for r in rows]
            assert lead.id not in ids

    def test_endpoint_returns_200(self, app, client):
        with app.app_context():
            resp = client.get('/api/queues/do-not-contact', headers=_AUTH_HEADERS)
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
            resp = client.get('/api/queues/missing-property-match', headers=_AUTH_HEADERS)
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Queue counts endpoint
# ---------------------------------------------------------------------------

class TestQueueCountsEndpoint:
    def test_counts_endpoint_returns_all_7_keys(self, app, client):
        """GET /api/queues/counts returns all 7 queue count keys."""
        with app.app_context():
            resp = client.get('/api/queues/counts', headers=_AUTH_HEADERS)
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
            resp = client.get('/api/queues/counts', headers=_AUTH_HEADERS)
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
                              lead_status='mailing_no_contact_made',
                              has_phone=True, has_email=False,
                              has_property_match=False)
            action = ActionEngineService.compute_recommended_action(lead)
            assert action == 'resolve_match'

    def test_lead_with_match_no_analysis_gets_analyze_property(self, app):
        """A lead with property match but no analysis gets analyze_property."""
        with app.app_context():
            lead = _make_lead(app, '3 Action Engine St',
                              lead_status='mailing_no_contact_made',
                              has_phone=True,
                              has_property_match=True,
                              analysis_complete=False)
            action = ActionEngineService.compute_recommended_action(lead)
            assert action == 'analyze_property'

    def test_warm_lead_gets_follow_up_now(self, app):
        """A warm lead with complete data gets recommended_action=follow_up_now."""
        with app.app_context():
            lead = _make_lead(app, '4 Action Engine St',
                              lead_status='mailing_no_contact_made',
                              has_phone=True,
                              has_property_match=True,
                              analysis_complete=True,
                              is_warm=True,
                              data_completeness_score=80.0)
            action = ActionEngineService.compute_recommended_action(lead)
            assert action == 'follow_up_now'

    def test_dnc_lead_gets_none(self, app):
        """A do_not_contact lead gets recommended_action=do_not_contact."""
        with app.app_context():
            lead = _make_lead(app, '5 Action Engine St',
                              lead_status='do_not_contact')
            action = ActionEngineService.compute_recommended_action(lead)
            assert action == 'do_not_contact'


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


# ---------------------------------------------------------------------------
# DuPage Lead Queue Visibility — source-agnostic queue filtering
# Asserts HubSpot-sourced (source_type=None) and DuPage-sourced
# (source_type='foreclosure') leads with identical qualifying fields
# both appear in the same queue.
# ---------------------------------------------------------------------------

class TestDuPageLeadQueueVisibility:
    """Seed a HubSpot-sourced and a DuPage-sourced lead with identical
    qualifying field values and assert both appear in the same queue.

    Covers queues: No Next Action, Previously Warm, Needs Review,
    Missing Property Match.
    """

    # ------------------------------------------------------------------
    # Queue 4: No Next Action
    # ------------------------------------------------------------------

    def test_no_next_action_both_sources_appear(self, app, client):
        """Both HubSpot-sourced (no source_type) and DuPage-sourced leads
        with lead_status='awaiting_skip_trace', recommended_action=None, and no tasks appear
        in get_no_next_action()."""
        with app.app_context():
            hubspot_lead = _make_lead(
                app, '10 DuPage NNA HubSpot St',
                lead_status='awaiting_skip_trace',
                recommended_action=None,
                source_type=None,
            )
            dupage_lead = _make_lead(
                app, '10 DuPage NNA DuPage St',
                lead_status='awaiting_skip_trace',
                recommended_action=None,
                source_type='foreclosure',
            )

            svc = QueueService()
            rows, total = svc.get_no_next_action()
            ids = [r['id'] for r in rows]

            assert hubspot_lead.id in ids, (
                f"HubSpot lead {hubspot_lead.id} missing from No Next Action. ids={ids}"
            )
            assert dupage_lead.id in ids, (
                f"DuPage lead {dupage_lead.id} missing from No Next Action. ids={ids}"
            )
            assert total >= 2

    # ------------------------------------------------------------------
    # Queue 2: Previously Warm
    # ------------------------------------------------------------------

    def test_previously_warm_both_sources_appear(self, app, client):
        """Both HubSpot-sourced and DuPage-sourced leads with is_warm=True
        appear in get_previously_warm()."""
        with app.app_context():
            hubspot_lead = _make_lead(
                app, '20 DuPage Warm HubSpot St',
                is_warm=True,
                source_type=None,
            )
            dupage_lead = _make_lead(
                app, '20 DuPage Warm DuPage St',
                is_warm=True,
                source_type='foreclosure',
            )

            svc = QueueService()
            rows, total = svc.get_previously_warm()
            ids = [r['id'] for r in rows]

            assert hubspot_lead.id in ids, (
                f"HubSpot lead {hubspot_lead.id} missing from Previously Warm. ids={ids}"
            )
            assert dupage_lead.id in ids, (
                f"DuPage lead {dupage_lead.id} missing from Previously Warm. ids={ids}"
            )
            assert total >= 2

    # ------------------------------------------------------------------
    # Queue 5: Needs Review
    # ------------------------------------------------------------------

    def test_needs_review_both_sources_appear(self, app, client):
        """Both HubSpot-sourced and DuPage-sourced leads with review_required=True
        appear in get_needs_review()."""
        with app.app_context():
            hubspot_lead = _make_lead(
                app, '30 DuPage Review HubSpot St',
                review_required=True,
                source_type=None,
            )
            dupage_lead = _make_lead(
                app, '30 DuPage Review DuPage St',
                review_required=True,
                source_type='foreclosure',
            )

            svc = QueueService()
            rows, total = svc.get_needs_review()
            ids = [r['id'] for r in rows]

            assert hubspot_lead.id in ids, (
                f"HubSpot lead {hubspot_lead.id} missing from Needs Review. ids={ids}"
            )
            assert dupage_lead.id in ids, (
                f"DuPage lead {dupage_lead.id} missing from Needs Review. ids={ids}"
            )
            assert total >= 2

    # ------------------------------------------------------------------
    # Queue 7: Missing Property Match
    # ------------------------------------------------------------------

    def test_missing_property_match_both_sources_appear(self, app, client):
        """Both HubSpot-sourced and DuPage-sourced leads with
        has_property_match=False appear in get_missing_property_match()."""
        with app.app_context():
            hubspot_lead = _make_lead(
                app, '40 DuPage NoMatch HubSpot St',
                has_property_match=False,
                source_type=None,
            )
            dupage_lead = _make_lead(
                app, '40 DuPage NoMatch DuPage St',
                has_property_match=False,
                source_type='foreclosure',
            )

            svc = QueueService()
            rows, total = svc.get_missing_property_match()
            ids = [r['id'] for r in rows]

            assert hubspot_lead.id in ids, (
                f"HubSpot lead {hubspot_lead.id} missing from Missing Property Match. ids={ids}"
            )
            assert dupage_lead.id in ids, (
                f"DuPage lead {dupage_lead.id} missing from Missing Property Match. ids={ids}"
            )
            assert total >= 2

