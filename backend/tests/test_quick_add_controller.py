"""Tests for POST /api/leads/quick-add."""
import json
from datetime import date

import pytest

from app import db
from app.models import Lead, LeadTimelineEntry
from app.services.quick_add_service import merge_deal_description

_AUTH_HEADERS = {'X-User-Id': 'test-user'}


@pytest.fixture
def quick_add_client(client):
    return client


class TestQuickAddEndpoint:
    def test_creates_lead_with_defaults(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '999 Quick Add Test Ln, Chicago, IL',
                    'note': 'Looks promising',
                    'priority': 'high',
                    'capture_location_label': 'Near test intersection',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            body = response.get_json()
            assert body['created'] is True
            assert body['lead_status'] == 'skip_trace'
            assert body['deal_source'] == 'Driving For Dollars'
            assert body['date_identified'] is not None

            lead = db.session.get(Lead, body['lead_id'])
            assert lead is not None
            assert lead.source == 'walk_by'
            assert lead.data_source == 'quick_add'
            assert lead.deal_source == 'Driving For Dollars'
            assert lead.date_identified is not None
            assert lead.manual_priority == 5
            assert lead.owner_user_id == 'test-user'

            entries = LeadTimelineEntry.query.filter_by(lead_id=lead.id).all()
            assert len(entries) >= 2

    def test_custom_deal_source_and_date_identified(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '777 Custom Fields Ave, Chicago, IL',
                    'deal_source': 'Cityscape',
                    'date_identified': '2026-03-15',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            body = response.get_json()
            assert body['deal_source'] == 'Cityscape'
            assert body['date_identified'] == '2026-03-15'

            lead = db.session.get(Lead, body['lead_id'])
            assert lead.deal_source == 'Cityscape'
            assert lead.date_identified.isoformat() == '2026-03-15'
            assert 'Walk-by' in (lead.deal_description or '')

    def test_dedup_same_address(self, quick_add_client, app):
        with app.app_context():
            payload = {
                'property_street': '888 Dedup Quick Add St, Chicago, IL',
                'note': 'First pass',
            }
            r1 = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps(payload),
                content_type='application/json',
            )
            assert r1.status_code == 201
            b1 = r1.get_json()
            lead = db.session.get(Lead, b1['lead_id'])
            lead.lead_status = 'negotiating_remote'
            lead.date_identified = date(2020, 1, 15)
            lead.deal_description = 'Existing CRM notes'
            db.session.commit()

            r2 = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    **payload,
                    'note': 'Second pass',
                    'date_identified': '2026-06-01',
                }),
                content_type='application/json',
            )
            assert r2.status_code == 201
            b2 = r2.get_json()
            assert b1['created'] is True
            assert b2['created'] is False
            assert b1['lead_id'] == b2['lead_id']

            db.session.refresh(lead)
            assert lead.lead_status == 'negotiating_remote'
            assert lead.date_identified.isoformat() == '2020-01-15'
            assert 'Existing CRM notes' in (lead.deal_description or '')
            assert 'Second pass' in (lead.deal_description or '')

            imported = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id,
                event_type='lead_imported',
            ).count()
            assert imported == 1

    def test_lookup_returns_address_matches(self, quick_add_client, app):
        with app.app_context():
            quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '555 Lookup Test Blvd, Chicago, IL',
                }),
                content_type='application/json',
            )

            response = quick_add_client.get(
                '/api/leads/quick-add/lookup',
                headers=_AUTH_HEADERS,
                query_string={'q': 'Lookup Test'},
            )
            assert response.status_code == 200
            body = response.get_json()
            assert len(body['matches']) >= 1
            assert any('Lookup Test' in (m['property_street'] or '') for m in body['matches'])

    def test_lookup_requires_min_query_length(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.get(
                '/api/leads/quick-add/lookup',
                headers=_AUTH_HEADERS,
                query_string={'q': 'a'},
            )
            assert response.status_code == 400

    def test_invalid_deal_source_rejected(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '123 Bad Source St',
                    'deal_source': 'Not A Real Source',
                }),
                content_type='application/json',
            )
            assert response.status_code == 400

    def test_response_includes_hubspot_push_status(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '444 HubSpot Status Ave, Chicago, IL',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            body = response.get_json()
            assert body['hubspot_push_status'] in ('disabled', 'queued', 'queue_failed')
            assert isinstance(body['hubspot_write_back_enabled'], bool)


class TestMergeDealDescription:
    def test_appends_without_discarding_existing(self):
        merged = merge_deal_description('Existing notes', 'Walk-by · new capture')
        assert merged.startswith('Existing notes')
        assert 'Walk-by · new capture' in merged

    def test_skips_duplicate_block(self):
        block = 'Walk-by · same capture'
        merged = merge_deal_description(f'Prior\n\n---\n\n{block}', block)
        assert merged.count(block) == 1

    def test_requires_address(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({'property_street': '  '}),
                content_type='application/json',
            )
            assert response.status_code == 400

    def test_requires_auth(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                data=json.dumps({'property_street': '123 No Auth St'}),
                content_type='application/json',
            )
            assert response.status_code in (401, 403)
