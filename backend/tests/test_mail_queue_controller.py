"""HTTP smoke tests for /api/mail-queue endpoints."""
import json

import pytest

from app import db
from app.models.lead import Lead
from app.models.mail_queue_item import MailQueueItem

_AUTH_HEADERS = {'X-User-Id': 'test-user'}


def _make_lead(app, street, **kwargs):
    from app import db

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


class TestGetMailQueue:
    def test_returns_200_with_expected_keys(self, client, app):
        with app.app_context():
            response = client.get('/api/mail-queue/', headers=_AUTH_HEADERS)
            assert response.status_code == 200
            data = json.loads(response.data)
            for key in (
                'queued_count', 'batch_minimum', 'allow_send_below_minimum',
                'can_send', 'items',
            ):
                assert key in data
            if data['items']:
                assert 'last_mailed_at' in data['items'][0]
                assert 'last_sale_at' in data['items'][0]

    def test_empty_queue(self, client, app):
        with app.app_context():
            response = client.get('/api/mail-queue/', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['items'] == []
            assert data['queued_count'] == 0

    def test_requires_auth(self, client, app):
        with app.app_context():
            response = client.get('/api/mail-queue/')
            assert response.status_code == 401

    def test_queued_item_appears_in_response(self, client, app):
        from app import db
        from app.models.mail_queue_item import MailQueueItem

        with app.app_context():
            lead = _make_lead(app, '1 Mail Queue St')
            db.session.add(MailQueueItem(
                lead_id=lead.id, user_id='test-user', status='queued',
            ))
            db.session.commit()
            response = client.get('/api/mail-queue/', headers=_AUTH_HEADERS)
            data = json.loads(response.data)
            assert data['queued_count'] >= 1
            ids = [item['lead_id'] for item in data['items']]
            assert lead.id in ids


class TestEnqueueMailQueue:
    def test_enqueue_rejects_invalid_lead_ids(self, client, app):
        with app.app_context():
            response = client.post(
                '/api/mail-queue/',
                headers=_AUTH_HEADERS,
                json={'lead_ids': ['abc']},
            )
            assert response.status_code == 400

    def test_enqueue_rejects_oversized_source_queue(self, client, app):
        with app.app_context():
            lead = _make_mail_ready_lead(app, '8 Source Queue St')
            response = client.post(
                '/api/mail-queue/',
                headers=_AUTH_HEADERS,
                json={
                    'lead_ids': [lead.id],
                    'source_queue': 'q' * 101,
                },
            )
            assert response.status_code == 400
            assert MailQueueItem.query.filter_by(lead_id=lead.id).count() == 0

    def test_enqueue_limits_batch_size(self, client, app):
        with app.app_context():
            response = client.post(
                '/api/mail-queue/',
                headers=_AUTH_HEADERS,
                json={'lead_ids': list(range(1, 1002))},
            )
            assert response.status_code == 400

    def test_enqueue_deduplicates_lead_ids(self, client, app):
        with app.app_context():
            lead = _make_mail_ready_lead(app, '8 Duplicate Request St')
            response = client.post(
                '/api/mail-queue/',
                headers=_AUTH_HEADERS,
                json={'lead_ids': [lead.id, lead.id]},
            )
            assert response.status_code == 201
            data = json.loads(response.data)
            assert data['added'] == 1
            assert len(data['results']) == 1

    def test_enqueue_rejects_other_users_lead(self, client, app):
        with app.app_context():
            lead = _make_lead(app, '9 Other Owner St', owner_user_id='other-user')
            response = client.post(
                '/api/mail-queue/',
                headers=_AUTH_HEADERS,
                json={'lead_ids': [lead.id]},
            )
            assert response.status_code == 201
            data = json.loads(response.data)
            assert data['added'] == 0
            outcome = data['results'][0]
            assert outcome == {
                'lead_id': lead.id,
                'status': 'not_authorized',
            }

    def test_enqueue_rejects_recently_sold_lead(self, client, app):
        from datetime import date, timedelta

        with app.app_context():
            recent_sale = (date.today() - timedelta(days=30)).strftime('%m/%d/%Y')
            lead = _make_lead(
                app, '10 Recent Sale St',
                most_recent_sale=recent_sale,
            )
            response = client.post(
                '/api/mail-queue/',
                headers=_AUTH_HEADERS,
                json={'lead_ids': [lead.id]},
            )
            assert response.status_code == 201
            data = json.loads(response.data)
            assert data['added'] == 0
            assert data['results'][0]['status'] == 'recently_sold'
            assert data['results'][0]['sale_date'] is not None

    def test_enqueue_persists_detailed_attempt_for_invalid_owner_mail(self, client, app):
        with app.app_context():
            lead = _make_lead(
                app,
                '11 Property Only St',
                property_city='Chicago',
                property_state='IL',
                property_zip='60601',
            )
            response = client.post(
                '/api/mail-queue/',
                headers=_AUTH_HEADERS,
                json={'lead_ids': [lead.id], 'source_queue': 'queue-todays-action'},
            )
            assert response.status_code == 201
            data = json.loads(response.data)
            assert data['invalid'] == 1
            assert data['results'][0]['status'] == 'invalid_address'
            assert data['results'][0]['property_street'] == '11 Property Only St'
            assert data['attempt_id']
            from app.models.mail_enqueue_attempt import MailEnqueueAttempt
            stored = db.session.get(MailEnqueueAttempt, data['attempt_id'])
            assert 'property_street' not in stored.results[0]
            assert 'owner_name' not in stored.results[0]

            attempt = client.get(
                f"/api/mail-queue/attempts/{data['attempt_id']}",
                headers=_AUTH_HEADERS,
            )
            assert attempt.status_code == 200
            attempt_data = json.loads(attempt.data)
            assert attempt_data['source_queue'] == 'queue-todays-action'
            assert attempt_data['results'][0]['lead_id'] == lead.id
            assert (
                attempt_data['results'][0]['property_street']
                == '11 Property Only St'
            )

            attempts = client.get('/api/mail-queue/attempts', headers=_AUTH_HEADERS)
            assert attempts.status_code == 200
            matching_attempt = next(
                row
                for row in json.loads(attempts.data)['attempts']
                if row['id'] == data['attempt_id']
            )
            assert 'results' not in matching_attempt

            unauthorized = client.get(
                f"/api/mail-queue/attempts/{data['attempt_id']}",
                headers={'X-User-Id': 'other-user'},
            )
            assert unauthorized.status_code == 404


def _make_mail_ready_lead(app, street, **kwargs):
    """Create a mail-ready lead with a valid mailable address."""
    defaults = dict(
        lead_status='mailing_no_contact_made',
        recommended_action='mail_ready',
        recommended_contact_method='direct_mail',
        mailing_address=street,
        mailing_city='Chicago',
        mailing_state='IL',
        mailing_zip='60601',
        owner_user_id='test-user',
    )
    defaults.update(kwargs)
    return _make_lead(app, street, **defaults)


class TestEnqueueCandidates:
    def test_enqueues_all_mail_ready_candidates(self, client, app):
        with app.app_context():
            lead_a = _make_mail_ready_lead(app, '1 Candidate St', lead_score=90.0)
            lead_b = _make_mail_ready_lead(app, '2 Candidate St', lead_score=80.0)
            response = client.post(
                '/api/mail-queue/enqueue-candidates',
                headers=_AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 201
            data = json.loads(response.data)
            assert data['added'] == 2
            assert data['queued_count'] == 2
            queued = client.get('/api/mail-queue/', headers=_AUTH_HEADERS)
            queued_ids = [item['lead_id'] for item in json.loads(queued.data)['items']]
            assert lead_a.id in queued_ids
            assert lead_b.id in queued_ids

    def test_respects_limit(self, client, app):
        with app.app_context():
            _make_mail_ready_lead(app, '3 Candidate St', lead_score=90.0)
            _make_mail_ready_lead(app, '4 Candidate St', lead_score=80.0)
            _make_mail_ready_lead(app, '5 Candidate St', lead_score=70.0)
            response = client.post(
                '/api/mail-queue/enqueue-candidates',
                headers=_AUTH_HEADERS,
                json={'limit': 2},
            )
            assert response.status_code == 201
            data = json.loads(response.data)
            assert data['added'] == 2
            assert data['queued_count'] == 2

    def test_skips_already_queued_and_recently_sold(self, client, app):
        from datetime import date, timedelta

        from app import db
        from app.models.mail_queue_item import MailQueueItem

        with app.app_context():
            queued = _make_mail_ready_lead(app, '6 Candidate St')
            fresh = _make_mail_ready_lead(app, '7 Candidate St')
            recent_sale = (date.today() - timedelta(days=30)).strftime('%m/%d/%Y')
            _make_mail_ready_lead(app, '8 Candidate St', most_recent_sale=recent_sale)
            db.session.add(MailQueueItem(
                lead_id=queued.id, user_id='test-user', status='queued',
            ))
            db.session.commit()
            response = client.post(
                '/api/mail-queue/enqueue-candidates',
                headers=_AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 201
            data = json.loads(response.data)
            assert data['added'] == 1
            assert data['queued_count'] == 2
            queued_ids = [r['lead_id'] for r in data['results'] if r['status'] == 'queued']
            assert fresh.id in queued_ids

    def test_returns_zero_when_no_candidates(self, client, app):
        with app.app_context():
            response = client.post(
                '/api/mail-queue/enqueue-candidates',
                headers=_AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 201
            data = json.loads(response.data)
            assert data['added'] == 0
            assert data['queued_count'] == 0

    def test_revalidates_prior_invalid_address_queue_items(self, client, app):
        from app import db
        from app.models.mail_queue_item import MailQueueItem

        with app.app_context():
            suppressed = _make_mail_ready_lead(app, '9 Invalid St')
            eligible = _make_mail_ready_lead(app, '10 Eligible St')
            db.session.add(MailQueueItem(
                lead_id=suppressed.id,
                user_id='test-user',
                status='invalid_address',
            ))
            db.session.commit()

            candidates = client.get('/api/queues/mail-candidates', headers=_AUTH_HEADERS)
            candidate_ids = [row['id'] for row in json.loads(candidates.data)['rows']]
            assert suppressed.id in candidate_ids
            assert eligible.id in candidate_ids

            response = client.post(
                '/api/mail-queue/enqueue-candidates',
                headers=_AUTH_HEADERS,
                json={},
            )
            assert response.status_code == 201
            data = json.loads(response.data)
            assert data['added'] == 2
            queued_ids = [r['lead_id'] for r in data['results'] if r['status'] == 'queued']
            assert eligible.id in queued_ids
            assert suppressed.id in queued_ids

    def test_corrected_address_can_reenter_candidates_after_invalid_attempt(
        self,
        client,
        app,
    ):
        from datetime import datetime, timedelta
        from app import db

        with app.app_context():
            lead = _make_mail_ready_lead(app, '11 Corrected Invalid St')
            invalid = MailQueueItem(
                lead_id=lead.id,
                user_id='test-user',
                status='invalid_address',
                validation_error='Incomplete owner mailing city/state/zip',
            )
            db.session.add(invalid)
            db.session.commit()

            lead.mailing_zip = '60699'
            lead.updated_at = datetime.utcnow() + timedelta(seconds=1)
            db.session.commit()

            response = client.get(
                '/api/queues/mail-candidates',
                headers=_AUTH_HEADERS,
            )
            candidate_ids = [
                row['id'] for row in json.loads(response.data)['rows']
            ]
            assert lead.id in candidate_ids

    def test_dry_run_preflight_does_not_write(self, client, app):
        with app.app_context():
            lead = _make_mail_ready_lead(app, '11 Preview St', lead_score=90.0)
            response = client.post(
                '/api/mail-queue/enqueue-candidates',
                headers=_AUTH_HEADERS,
                json={'dry_run': True},
            )
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['dry_run'] is True
            assert data['would_add'] == 1
            assert data['would_fail'] == 0
            assert data['queued_count'] == 0
            assert any(r['lead_id'] == lead.id and r['status'] == 'would_queue' for r in data['results'])

            queued = client.get('/api/mail-queue/', headers=_AUTH_HEADERS)
            assert json.loads(queued.data)['queued_count'] == 0
            assert json.loads(queued.data)['items'] == []


class TestMailCampaignAuth:
    def test_get_campaign_rejects_other_users_campaign(self, client, app):
        from app import db
        from app.models.mail_campaign import MailCampaign

        with app.app_context():
            campaign = MailCampaign(status='pending', lead_count=0, created_by='other-user')
            db.session.add(campaign)
            db.session.commit()
            response = client.get(
                f'/api/mail-queue/campaigns/{campaign.id}',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 404

    def test_campaigns_for_lead_rejects_other_users_lead(self, client, app):
        with app.app_context():
            lead = _make_lead(app, '11 Private Lead St', owner_user_id='other-user')
            response = client.get(
                f'/api/mail-queue/campaigns/for-lead/{lead.id}',
                headers=_AUTH_HEADERS,
            )
            assert response.status_code == 404
