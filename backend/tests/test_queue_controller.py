"""
Integration tests for Queue API endpoints.

Tests all 8 queue endpoints (counts + 7 queue views) via the Flask test client.
Covers: HTTP 200 responses, pagination params, sort params, empty-queue behavior.
"""
import json
import pytest
from datetime import date, timedelta, datetime, timezone

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry

# All queue endpoints require an authenticated user (X-User-Id in testing env)
_AUTH_HEADERS = {'X-User-Id': 'test-user'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(app, street, **kwargs):
    """Create a Lead with sensible defaults."""
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
        owner_user_id='test-user',  # matches _AUTH_HEADERS X-User-Id
    )
    defaults.update(kwargs)
    lead = Lead(property_street=street, **defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


def _make_task(app, lead_id, status='open', due_date=None, task_type='custom'):
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


# ---------------------------------------------------------------------------
# GET /api/queues/counts
# ---------------------------------------------------------------------------

class TestGetCounts:
    def test_counts_returns_200(self, client, app):
        """GET /api/queues/counts returns HTTP 200."""
        with app.app_context():
            response = client.get('/api/queues/counts', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_counts_returns_all_seven_keys(self, client, app):
        """Response contains all 7 queue keys."""
        with app.app_context():
            response = client.get('/api/queues/counts', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            expected_keys = {
                'todays_action', 'previously_warm', 'follow_up_overdue',
                'no_next_action', 'needs_review', 'do_not_contact',
                'missing_property_match',
            }
            assert set(data.keys()) == expected_keys

    def test_counts_are_integers(self, client, app):
        """All count values are non-negative integers."""
        with app.app_context():
            response = client.get('/api/queues/counts', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            for key, val in data.items():
                assert isinstance(val, int), f"{key} should be int"
                assert val >= 0

    def test_counts_reflect_dnc_lead(self, client, app):
        """DNC lead increments do_not_contact count."""
        with app.app_context():
            _make_lead(app, '1 Counts St', lead_status='do_not_contact')
            response = client.get('/api/queues/counts', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['do_not_contact'] >= 1


# ---------------------------------------------------------------------------
# GET /api/queues/todays-action
# ---------------------------------------------------------------------------

class TestTodaysActionQueue:
    def test_returns_200(self, client, app):
        """GET /api/queues/todays-action returns HTTP 200."""
        with app.app_context():
            response = client.get('/api/queues/todays-action', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/todays-action', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted and reflected in response."""
        with app.app_context():
            response = client.get('/api/queues/todays-action?page=2&per_page=5', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['page'] == 2
            assert data['per_page'] == 5

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/todays-action?sort_by=lead_score&sort_order=asc', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_lead_with_follow_up_now_appears(self, client, app):
        """Lead with recommended_action='follow_up_now' appears in Today's Action."""
        with app.app_context():
            lead = _make_lead(app, '2 Todays St',
                              lead_status='active',
                              recommended_action='follow_up_now')
            response = client.get('/api/queues/todays-action', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids

    def test_lead_with_task_due_today_appears(self, client, app):
        """Lead with open task due today appears in Today's Action."""
        with app.app_context():
            lead = _make_lead(app, '3 Todays St', lead_status='active')
            _make_task(app, lead.id, due_date=date.today())
            response = client.get('/api/queues/todays-action', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids

    def test_dnc_lead_excluded(self, client, app):
        """DNC lead does not appear in Today's Action."""
        with app.app_context():
            lead = _make_lead(app, '4 Todays St',
                              lead_status='do_not_contact',
                              recommended_action='follow_up_now')
            response = client.get('/api/queues/todays-action', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id not in ids


# ---------------------------------------------------------------------------
# GET /api/queues/previously-warm
# ---------------------------------------------------------------------------

class TestPreviouslyWarmQueue:
    def test_returns_200(self, client, app):
        """GET /api/queues/previously-warm returns HTTP 200."""
        with app.app_context():
            response = client.get('/api/queues/previously-warm', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/previously-warm', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/previously-warm?page=1&per_page=10', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['page'] == 1
            assert data['per_page'] == 10

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/previously-warm?sort_by=lead_score&sort_order=desc', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_lead_with_hubspot_sync_appears(self, client, app):
        """Lead with is_warm=True appears in Previously Warm."""
        with app.app_context():
            lead = _make_lead(app, '5 Warm St', lead_status='active', is_warm=True)
            response = client.get('/api/queues/previously-warm', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids


# ---------------------------------------------------------------------------
# GET /api/queues/follow-up-overdue
# ---------------------------------------------------------------------------

class TestFollowUpOverdueQueue:
    def test_returns_200(self, client, app):
        """GET /api/queues/follow-up-overdue returns HTTP 200."""
        with app.app_context():
            response = client.get('/api/queues/follow-up-overdue', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/follow-up-overdue', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/follow-up-overdue?page=1&per_page=15', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['per_page'] == 15

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/follow-up-overdue?sort_by=lead_score&sort_order=asc', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_lead_with_overdue_task_appears(self, client, app):
        """Lead with open task due yesterday appears in Follow-Up Overdue."""
        with app.app_context():
            lead = _make_lead(app, '6 Overdue St')
            _make_task(app, lead.id, due_date=date.today() - timedelta(days=1))
            response = client.get('/api/queues/follow-up-overdue', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids


# ---------------------------------------------------------------------------
# GET /api/queues/no-next-action
# ---------------------------------------------------------------------------

class TestNoNextActionQueue:
    def test_returns_200(self, client, app):
        """GET /api/queues/no-next-action returns HTTP 200."""
        with app.app_context():
            response = client.get('/api/queues/no-next-action', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/no-next-action', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/no-next-action?page=1&per_page=25', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['per_page'] == 25

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/no-next-action?sort_by=lead_score&sort_order=desc', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_lead_with_create_task_ra_appears(self, client, app):
        """Lead with recommended_action='create_task' and no open tasks appears."""
        with app.app_context():
            lead = _make_lead(app, '7 NoAction St',
                              lead_status='active',
                              recommended_action='create_task')
            response = client.get('/api/queues/no-next-action', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids


# ---------------------------------------------------------------------------
# GET /api/queues/needs-review
# ---------------------------------------------------------------------------

class TestNeedsReviewQueue:
    def test_returns_200(self, client, app):
        """GET /api/queues/needs-review returns HTTP 200."""
        with app.app_context():
            response = client.get('/api/queues/needs-review', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/needs-review', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/needs-review?page=1&per_page=20', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/needs-review?sort_by=lead_score&sort_order=asc', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_review_required_lead_appears(self, client, app):
        """Lead with review_required=True appears in Needs Review queue."""
        with app.app_context():
            lead = _make_lead(app, '8 Review St', review_required=True)
            response = client.get('/api/queues/needs-review', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids


# ---------------------------------------------------------------------------
# GET /api/queues/do-not-contact
# ---------------------------------------------------------------------------

class TestDoNotContactQueue:
    def test_returns_200(self, client, app):
        """GET /api/queues/do-not-contact returns HTTP 200."""
        with app.app_context():
            response = client.get('/api/queues/do-not-contact', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/do-not-contact', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/do-not-contact?page=1&per_page=10', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/do-not-contact?sort_by=lead_score&sort_order=asc', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_dnc_lead_appears(self, client, app):
        """Lead with lead_status='do_not_contact' appears in DNC queue."""
        with app.app_context():
            lead = _make_lead(app, '9 DNC St', lead_status='do_not_contact')
            response = client.get('/api/queues/do-not-contact', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids

    def test_active_lead_excluded(self, client, app):
        """Active lead does not appear in DNC queue."""
        with app.app_context():
            lead = _make_lead(app, '10 Active St', lead_status='active')
            response = client.get('/api/queues/do-not-contact', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id not in ids


# ---------------------------------------------------------------------------
# GET /api/queues/missing-property-match
# ---------------------------------------------------------------------------

class TestMissingPropertyMatchQueue:
    def test_returns_200(self, client, app):
        """GET /api/queues/missing-property-match returns HTTP 200."""
        with app.app_context():
            response = client.get('/api/queues/missing-property-match', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/missing-property-match', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/missing-property-match?page=1&per_page=10', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/missing-property-match?sort_by=lead_score&sort_order=asc', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_lead_without_property_match_appears(self, client, app):
        """Lead with has_property_match=False and no research task appears."""
        with app.app_context():
            lead = _make_lead(app, '11 NoMatch St', has_property_match=False)
            response = client.get('/api/queues/missing-property-match', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids

    def test_lead_with_research_task_excluded(self, client, app):
        """Lead with research_missing_pin task is excluded from Missing Property Match."""
        with app.app_context():
            lead = _make_lead(app, '12 NoMatch2 St', has_property_match=False)
            _make_task(app, lead.id, task_type='research_missing_pin')
            response = client.get('/api/queues/missing-property-match', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id not in ids



# ---------------------------------------------------------------------------
# REGRESSION GUARD: Legacy unowned leads (owner_user_id=NULL) must be visible
# ---------------------------------------------------------------------------
#
# Root cause of the production outage (June 2026):
#   PR #34 introduced ownership scoping that filtered strictly by
#   owner_user_id = current_user_id. All pre-existing leads have
#   owner_user_id=NULL (imported before the ownership model existed),
#   so every non-admin user saw zero leads in production.
#
# These tests MUST pass on every PR. They seed leads with owner_user_id=NULL
# and assert they appear in each queue and the properties list for a
# non-admin user. If ownership scoping ever regresses to strict equality
# (excluding NULLs), these tests will fail before the PR reaches main.
# ---------------------------------------------------------------------------

class TestLegacyUnownedLeadsAreVisible:
    """Leads with owner_user_id=NULL are visible to all authenticated non-admin users.

    This class guards against the regression where strict owner_user_id == current_user
    scoping made all pre-existing (unowned) leads invisible in production.
    """

    def _make_unowned_lead(self, app, street, **kwargs):
        """Create a lead with owner_user_id=NULL — simulates pre-ownership-model data."""
        defaults = dict(
            lead_status='active',
            has_phone=True,
            has_email=True,
            has_property_match=True,
            analysis_complete=False,
            follow_up_overdue=False,
            is_warm=False,
            lead_score=50.0,
            data_completeness_score=60.0,
            recommended_action=None,
            review_required=False,
            unanswered_call_count=0,
            owner_user_id=None,  # ← NULL: the production data shape before ownership model
        )
        defaults.update(kwargs)
        lead = Lead(property_street=street, **defaults)
        db.session.add(lead)
        db.session.commit()
        return lead

    def test_unowned_dnc_lead_appears_in_do_not_contact_queue(self, client, app):
        """Unowned DNC lead is visible in do-not-contact queue for non-admin user."""
        with app.app_context():
            lead = self._make_unowned_lead(app, '1 Unowned DNC St',
                                           lead_status='do_not_contact')
            response = client.get('/api/queues/do-not-contact', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids, (
                f"REGRESSION: Unowned lead (owner_user_id=NULL) id={lead.id} not found in "
                f"do-not-contact queue. Ownership scoping must include NULL owner_user_id rows."
            )

    def test_unowned_lead_appears_in_no_next_action_queue(self, client, app):
        """Unowned active lead with no tasks is visible in no-next-action queue."""
        with app.app_context():
            lead = self._make_unowned_lead(app, '2 Unowned NNA St',
                                           lead_status='new',
                                           recommended_action=None)
            response = client.get('/api/queues/no-next-action', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids, (
                f"REGRESSION: Unowned lead (owner_user_id=NULL) id={lead.id} not found in "
                f"no-next-action queue. Ownership scoping must include NULL owner_user_id rows."
            )

    def test_unowned_lead_appears_in_needs_review_queue(self, client, app):
        """Unowned lead with review_required=True is visible in needs-review queue."""
        with app.app_context():
            lead = self._make_unowned_lead(app, '3 Unowned Review St',
                                           review_required=True)
            response = client.get('/api/queues/needs-review', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids, (
                f"REGRESSION: Unowned lead (owner_user_id=NULL) id={lead.id} not found in "
                f"needs-review queue. Ownership scoping must include NULL owner_user_id rows."
            )

    def test_unowned_lead_appears_in_missing_property_match_queue(self, client, app):
        """Unowned lead with no property match is visible in missing-property-match queue."""
        with app.app_context():
            lead = self._make_unowned_lead(app, '4 Unowned NoMatch St',
                                           has_property_match=False)
            response = client.get('/api/queues/missing-property-match', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids, (
                f"REGRESSION: Unowned lead (owner_user_id=NULL) id={lead.id} not found in "
                f"missing-property-match queue. Ownership scoping must include NULL owner_user_id rows."
            )

    def test_unowned_lead_appears_in_previously_warm_queue(self, client, app):
        """Unowned warm lead is visible in previously-warm queue."""
        with app.app_context():
            lead = self._make_unowned_lead(app, '5 Unowned Warm St', is_warm=True)
            response = client.get('/api/queues/previously-warm', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids, (
                f"REGRESSION: Unowned lead (owner_user_id=NULL) id={lead.id} not found in "
                f"previously-warm queue. Ownership scoping must include NULL owner_user_id rows."
            )

    def test_unowned_lead_counts_in_badge_counts(self, client, app):
        """Unowned DNC lead is counted in the /counts endpoint for non-admin user."""
        with app.app_context():
            self._make_unowned_lead(app, '6 Unowned Count St',
                                    lead_status='do_not_contact')
            response = client.get('/api/queues/counts', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['do_not_contact'] >= 1, (
                "REGRESSION: Unowned lead (owner_user_id=NULL) not reflected in badge counts. "
                "Ownership scoping must include NULL owner_user_id rows."
            )

    def test_unowned_lead_visible_in_properties_list(self, client, app):
        """Unowned lead is visible in the /api/properties list for a non-admin user."""
        with app.app_context():
            lead = self._make_unowned_lead(app, '7 Unowned Props St')
            response = client.get('/api/properties/', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            ids = [l['id'] for l in data['leads']]
            assert lead.id in ids, (
                f"REGRESSION: Unowned lead (owner_user_id=NULL) id={lead.id} not found in "
                f"/api/properties list. Ownership scoping must include NULL owner_user_id rows."
            )

    def test_unowned_lead_visible_in_property_detail(self, client, app):
        """Unowned lead (owner_user_id=NULL) is accessible via GET /api/properties/<id>."""
        with app.app_context():
            lead = self._make_unowned_lead(app, '8 Unowned Detail St')
            response = client.get(f'/api/properties/{lead.id}', headers=_AUTH_HEADERS)
            assert response.status_code == 200, (
                f"REGRESSION: GET /api/properties/{lead.id} returned {response.status_code} "
                f"for unowned lead. Expected 200 — unowned leads must be accessible to all "
                f"authenticated users."
            )
            data = json.loads(response.data)
            assert data['id'] == lead.id

    def test_unowned_lead_can_be_analyzed_via_property_analyze(self, client, app):
        """Unowned lead (owner_user_id=NULL) can have an analysis session started."""
        with app.app_context():
            lead = self._make_unowned_lead(app, '9 Unowned Analyze St')
            response = client.post(
                f'/api/properties/{lead.id}/analyze',
                json={},
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 201, (
                f"REGRESSION: POST /api/properties/{lead.id}/analyze returned "
                f"{response.status_code} for unowned lead. Expected 201 — analysis must "
                f"be startable on unowned leads for all authenticated users."
            )
            data = json.loads(response.data)
            assert data['lead_id'] == lead.id
            assert 'session_id' in data
