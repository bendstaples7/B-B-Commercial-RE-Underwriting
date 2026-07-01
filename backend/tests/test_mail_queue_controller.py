"""HTTP smoke tests for /api/mail-queue endpoints."""
import json

import pytest

from app.models.lead import Lead

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
            assert data['results'][0]['status'] == 'not_authorized'

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
