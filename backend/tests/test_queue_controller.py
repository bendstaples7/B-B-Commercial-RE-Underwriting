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
            response = client.get('/api/queues/counts')
            assert response.status_code == 200

    def test_counts_returns_all_seven_keys(self, client, app):
        """Response contains all 7 queue keys."""
        with app.app_context():
            response = client.get('/api/queues/counts')
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
            response = client.get('/api/queues/counts')
            data = json.loads(response.data)
            for key, val in data.items():
                assert isinstance(val, int), f"{key} should be int"
                assert val >= 0

    def test_counts_reflect_dnc_lead(self, client, app):
        """DNC lead increments do_not_contact count."""
        with app.app_context():
            _make_lead(app, '1 Counts St', lead_status='do_not_contact')
            response = client.get('/api/queues/counts')
            data = json.loads(response.data)
            assert data['do_not_contact'] >= 1


# ---------------------------------------------------------------------------
# GET /api/queues/todays-action
# ---------------------------------------------------------------------------

class TestTodaysActionQueue:
    def test_returns_200(self, client, app):
        """GET /api/queues/todays-action returns HTTP 200."""
        with app.app_context():
            response = client.get('/api/queues/todays-action')
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/todays-action')
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted and reflected in response."""
        with app.app_context():
            response = client.get('/api/queues/todays-action?page=2&per_page=5')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['page'] == 2
            assert data['per_page'] == 5

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/todays-action?sort_by=lead_score&sort_order=asc')
            assert response.status_code == 200

    def test_lead_with_follow_up_now_appears(self, client, app):
        """Lead with recommended_action='follow_up_now' appears in Today's Action."""
        with app.app_context():
            lead = _make_lead(app, '2 Todays St',
                              lead_status='active',
                              recommended_action='follow_up_now')
            response = client.get('/api/queues/todays-action')
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids

    def test_lead_with_task_due_today_appears(self, client, app):
        """Lead with open task due today appears in Today's Action."""
        with app.app_context():
            lead = _make_lead(app, '3 Todays St', lead_status='active')
            _make_task(app, lead.id, due_date=date.today())
            response = client.get('/api/queues/todays-action')
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids

    def test_dnc_lead_excluded(self, client, app):
        """DNC lead does not appear in Today's Action."""
        with app.app_context():
            lead = _make_lead(app, '4 Todays St',
                              lead_status='do_not_contact',
                              recommended_action='follow_up_now')
            response = client.get('/api/queues/todays-action')
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
            response = client.get('/api/queues/previously-warm')
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/previously-warm')
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/previously-warm?page=1&per_page=10')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['page'] == 1
            assert data['per_page'] == 10

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/previously-warm?sort_by=lead_score&sort_order=desc')
            assert response.status_code == 200

    def test_lead_with_hubspot_sync_appears(self, client, app):
        """Lead with a PRIOR_WARM_CONVERSATION signal appears in Previously Warm."""
        with app.app_context():
            from app.models.hubspot_signal_dictionary import HubSpotSignalDictionary
            from app.models.hubspot_signal import HubSpotSignal
            lead = _make_lead(app, '5 Warm St', lead_status='active')
            if not HubSpotSignalDictionary.query.filter_by(signal_type='PRIOR_WARM_CONVERSATION').first():
                db.session.add(HubSpotSignalDictionary(
                    signal_type='PRIOR_WARM_CONVERSATION',
                    keywords=['interested'],
                ))
            db.session.add(HubSpotSignal(
                lead_id=lead.id,
                signal_type='PRIOR_WARM_CONVERSATION',
                source_engagement_id='test-ctrl-warm',
                raw_evidence='interested',
            ))
            db.session.commit()
            response = client.get('/api/queues/previously-warm')
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
            response = client.get('/api/queues/follow-up-overdue')
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/follow-up-overdue')
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/follow-up-overdue?page=1&per_page=15')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['per_page'] == 15

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/follow-up-overdue?sort_by=lead_score&sort_order=asc')
            assert response.status_code == 200

    def test_lead_with_overdue_task_appears(self, client, app):
        """Lead with open task due yesterday appears in Follow-Up Overdue."""
        with app.app_context():
            lead = _make_lead(app, '6 Overdue St')
            _make_task(app, lead.id, due_date=date.today() - timedelta(days=1))
            response = client.get('/api/queues/follow-up-overdue')
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
            response = client.get('/api/queues/no-next-action')
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/no-next-action')
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/no-next-action?page=1&per_page=25')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['per_page'] == 25

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/no-next-action?sort_by=lead_score&sort_order=desc')
            assert response.status_code == 200

    def test_lead_with_create_task_ra_appears(self, client, app):
        """Lead with recommended_action='create_task' and no open tasks appears."""
        with app.app_context():
            lead = _make_lead(app, '7 NoAction St',
                              lead_status='active',
                              recommended_action='create_task')
            response = client.get('/api/queues/no-next-action')
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
            response = client.get('/api/queues/needs-review')
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/needs-review')
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/needs-review?page=1&per_page=20')
            assert response.status_code == 200

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/needs-review?sort_by=lead_score&sort_order=asc')
            assert response.status_code == 200

    def test_review_required_lead_appears(self, client, app):
        """Lead with review_required=True appears in Needs Review queue."""
        with app.app_context():
            lead = _make_lead(app, '8 Review St', review_required=True)
            response = client.get('/api/queues/needs-review')
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
            response = client.get('/api/queues/do-not-contact')
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/do-not-contact')
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/do-not-contact?page=1&per_page=10')
            assert response.status_code == 200

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/do-not-contact?sort_by=lead_score&sort_order=asc')
            assert response.status_code == 200

    def test_dnc_lead_appears(self, client, app):
        """Lead with lead_status='do_not_contact' appears in DNC queue."""
        with app.app_context():
            lead = _make_lead(app, '9 DNC St', lead_status='do_not_contact')
            response = client.get('/api/queues/do-not-contact')
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids

    def test_active_lead_excluded(self, client, app):
        """Active lead does not appear in DNC queue."""
        with app.app_context():
            lead = _make_lead(app, '10 Active St', lead_status='active')
            response = client.get('/api/queues/do-not-contact')
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
            response = client.get('/api/queues/missing-property-match')
            assert response.status_code == 200

    def test_empty_queue_returns_empty_list(self, client, app):
        """Empty database returns rows=[] and total=0."""
        with app.app_context():
            response = client.get('/api/queues/missing-property-match')
            data = json.loads(response.data)
            assert data['rows'] == []
            assert data['total'] == 0

    def test_pagination_params_accepted(self, client, app):
        """page and per_page query params are accepted."""
        with app.app_context():
            response = client.get('/api/queues/missing-property-match?page=1&per_page=10')
            assert response.status_code == 200

    def test_sort_params_accepted(self, client, app):
        """sort_by and sort_order query params are accepted without error."""
        with app.app_context():
            response = client.get('/api/queues/missing-property-match?sort_by=lead_score&sort_order=asc')
            assert response.status_code == 200

    def test_lead_without_property_match_appears(self, client, app):
        """Lead with has_property_match=False and no research task appears."""
        with app.app_context():
            lead = _make_lead(app, '11 NoMatch St', has_property_match=False)
            response = client.get('/api/queues/missing-property-match')
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids

    def test_lead_with_research_task_excluded(self, client, app):
        """Lead with research_missing_pin task is excluded from Missing Property Match."""
        with app.app_context():
            lead = _make_lead(app, '12 NoMatch2 St', has_property_match=False)
            _make_task(app, lead.id, task_type='research_missing_pin')
            response = client.get('/api/queues/missing-property-match')
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id not in ids
