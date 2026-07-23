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
        """Response contains all work-queue count keys."""
        with app.app_context():
            response = client.get('/api/queues/counts', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            expected_keys = {
                'todays_action', 'previously_warm', 'follow_up_overdue',
                'no_next_action', 'needs_review', 'skip_trace', 'skip_trace_exhausted',
                'do_not_contact', 'missing_property_match', 'ready_to_mail',
                'mail_candidates', 'prospect_candidates',
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

    def test_invalid_outreach_filter_echoes_null(self, client, app):
        """Invalid outreach filters are ignored and echoed as null."""
        with app.app_context():
            response = client.get('/api/queues/todays-action?outreach=stale', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['outreach'] is None

    def test_invalid_outreach_filter_echoes_null_for_lead_ids(self, client, app):
        """Lead-id bulk selection reports the normalized outreach filter."""
        with app.app_context():
            response = client.get('/api/queues/todays-action/lead-ids?outreach=stale', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['outreach'] is None

    def test_bare_follow_up_now_does_not_appear(self, client, app):
        """Bare follow_up_now without a due task does not appear in Today's Action."""
        with app.app_context():
            lead = _make_lead(app, '2 Todays St',
                              lead_status='mailing_no_contact_made',
                              recommended_action='follow_up_now')
            response = client.get('/api/queues/todays-action', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id not in ids

    def test_lead_with_task_due_today_appears(self, client, app):
        """Lead with open task due today appears in Today's Action."""
        with app.app_context():
            lead = _make_lead(app, '3 Todays St', lead_status='mailing_no_contact_made')
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
            lead = _make_lead(app, '5 Warm St', lead_status='mailing_no_contact_made', is_warm=True)
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
                              lead_status='mailing_no_contact_made',
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
            lead = _make_lead(app, '10 Active St', lead_status='mailing_no_contact_made')
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
# GET /api/queues/mail-candidates
# ---------------------------------------------------------------------------

def _make_mail_ready_lead(app, street, **kwargs):
    defaults = dict(
        lead_status='mailing_no_contact_made',
        recommended_action='mail_ready',
        mailing_address=street,
        mailing_city='Chicago',
        mailing_state='IL',
        mailing_zip='60601',
    )
    defaults.update(kwargs)
    return _make_lead(app, street, **defaults)


class TestMailCandidatesQueue:
    def test_returns_200(self, client, app):
        with app.app_context():
            response = client.get('/api/queues/mail-candidates', headers=_AUTH_HEADERS)
            assert response.status_code == 200

    def test_mail_ready_lead_appears(self, client, app):
        with app.app_context():
            lead = _make_mail_ready_lead(app, '1 Mail Ready St')
            response = client.get('/api/queues/mail-candidates', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id in ids

    def test_already_queued_lead_excluded(self, client, app):
        from app import db
        from app.models.mail_queue_item import MailQueueItem

        with app.app_context():
            lead = _make_mail_ready_lead(app, '2 Mail Ready St')
            db.session.add(MailQueueItem(
                lead_id=lead.id, user_id='test-user', status='queued',
            ))
            db.session.commit()
            response = client.get('/api/queues/mail-candidates', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            ids = [r['id'] for r in data['rows']]
            assert lead.id not in ids

    def test_mail_candidates_include_last_sale_at(self, client, app):
        with app.app_context():
            lead = _make_mail_ready_lead(
                app, '4 Mail Sale St',
                most_recent_sale='6/15/2010',
            )
            response = client.get('/api/queues/mail-candidates', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            match = next(r for r in data['rows'] if r['id'] == lead.id)
            assert match['last_sale_at'] == '2010-06-15'

    def test_counts_include_ready_to_mail(self, client, app):
        from app import db
        from app.models.mail_queue_item import MailQueueItem

        with app.app_context():
            lead = _make_mail_ready_lead(app, '3 Mail Ready St')
            db.session.add(MailQueueItem(
                lead_id=lead.id, user_id='test-user', status='queued',
            ))
            db.session.commit()
            response = client.get('/api/queues/counts', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['ready_to_mail'] >= 1
            candidates = client.get('/api/queues/mail-candidates', headers=_AUTH_HEADERS)
            candidate_rows = json.loads(candidates.data)['rows']
            assert lead.id not in [row['id'] for row in candidate_rows]


# ---------------------------------------------------------------------------
# GET /api/queues/<queue_key>/navigation
# ---------------------------------------------------------------------------

class TestQueueNavigation:
    def test_requires_lead_id(self, client, app):
        with app.app_context():
            response = client.get('/api/queues/todays-action/navigation', headers=_AUTH_HEADERS)
            assert response.status_code == 400

    def test_unknown_queue_key_404(self, client, app):
        with app.app_context():
            response = client.get(
                '/api/queues/not-a-real-queue/navigation?lead_id=1',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 404

    def test_neighbors_for_todays_action(self, client, app):
        with app.app_context():
            from app.services.queue_order_cache import queue_order_cache
            queue_order_cache.clear()

            lead_a = _make_lead(
                app, 'Nav A St',
                lead_status='mailing_no_contact_made',
                recommended_action='follow_up_now',
                lead_score=90,
            )
            lead_b = _make_lead(
                app, 'Nav B St',
                lead_status='mailing_no_contact_made',
                recommended_action='follow_up_now',
                lead_score=80,
            )
            lead_c = _make_lead(
                app, 'Nav C St',
                lead_status='mailing_no_contact_made',
                recommended_action='follow_up_now',
                lead_score=70,
            )
            for lead in (lead_a, lead_b, lead_c):
                _make_task(app, lead.id, due_date=date.today())

            response = client.get(
                f'/api/queues/todays-action/navigation?lead_id={lead_b.id}',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['queue_key'] == 'todays-action'
            assert data['lead_id'] == lead_b.id
            assert data['total'] >= 3
            assert data['position'] is not None
            assert data['prev_id'] == lead_a.id
            assert data['next_id'] == lead_c.id

    def test_lead_not_in_queue_returns_null_position(self, client, app):
        with app.app_context():
            from app.services.queue_order_cache import queue_order_cache
            queue_order_cache.clear()

            outside = _make_lead(
                app, 'Outside St',
                lead_status='do_not_contact',
                lead_score=10,
            )
            response = client.get(
                f'/api/queues/todays-action/navigation?lead_id={outside.id}',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['position'] is None
            assert data['prev_id'] is None

