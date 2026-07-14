"""Tests for POST /api/leads/quick-add."""
import json
from datetime import date
from unittest.mock import patch

import pytest

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry
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
            assert lead.property_city == 'Chicago'
            assert lead.property_state == 'IL'
            assert lead.needs_skip_trace is True
            assert LeadTask.query.filter_by(
                lead_id=lead.id, task_type='skip_trace_owner', status='open',
            ).first() is not None

            entries = LeadTimelineEntry.query.filter_by(lead_id=lead.id).all()
            assert len(entries) >= 2

    def test_parses_places_address_with_zip_and_country(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '100 W Randolph St, Chicago, IL 60601, USA',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            lead = db.session.get(Lead, response.get_json()['lead_id'])
            assert lead.property_city == 'Chicago'
            assert lead.property_state == 'IL'
            assert lead.property_zip == '60601'

    def test_accepts_structured_city_state_zip(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': 'Ambiguous capture line',
                    'property_city': 'Wheaton',
                    'property_state': 'IL',
                    'property_zip': '60187',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            lead = db.session.get(Lead, response.get_json()['lead_id'])
            assert lead.property_city == 'Wheaton'
            assert lead.property_state == 'IL'
            assert lead.property_zip == '60187'

    def test_dedup_does_not_enqueue_skip_trace(self, quick_add_client, app):
        with app.app_context():
            payload = {'property_street': '555 Dedup Skip Trace St, Chicago, IL'}
            r1 = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps(payload),
                content_type='application/json',
            )
            lead_id = r1.get_json()['lead_id']
            LeadTask.query.filter_by(lead_id=lead_id).delete()
            lead = db.session.get(Lead, lead_id)
            lead.needs_skip_trace = False
            db.session.commit()

            r2 = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({**payload, 'note': 'Second walk-by'}),
                content_type='application/json',
            )
            assert r2.status_code == 201
            assert r2.get_json()['created'] is False
            lead = db.session.get(Lead, lead_id)
            assert lead.needs_skip_trace is False
            assert LeadTask.query.filter_by(
                lead_id=lead_id, task_type='skip_trace_owner', status='open',
            ).count() == 0

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

    def test_lookup_keeps_match_after_places_selection(self, quick_add_client, app):
        """Typing may ILIKE-match briefly; Places fill must still surface the lead."""
        with app.app_context():
            lead = Lead(
                property_street='4903 N Hermitage',
                owner_user_id='test-user',
                lead_status='skip_trace',
                source='walk_by',
            )
            db.session.add(lead)
            db.session.commit()
            lead_id = lead.id

            places = '4903 N Hermitage Ave, Chicago, IL 60640, USA'
            response = quick_add_client.get(
                '/api/leads/quick-add/lookup',
                headers=_AUTH_HEADERS,
                query_string={'q': places},
            )
            assert response.status_code == 200
            matches = response.get_json()['matches']
            assert any(m['lead_id'] == lead_id for m in matches)

            north_places = '4903 North Hermitage Avenue, Chicago, IL 60640, USA'
            response = quick_add_client.get(
                '/api/leads/quick-add/lookup',
                headers=_AUTH_HEADERS,
                query_string={'q': north_places},
            )
            assert response.status_code == 200
            matches = response.get_json()['matches']
            assert any(m['lead_id'] == lead_id for m in matches)

    def test_dedup_places_address_against_abbreviated_street(self, quick_add_client, app):
        with app.app_context():
            lead = Lead(
                property_street='4903 N Hermitage',
                owner_user_id='test-user',
                lead_status='negotiating_remote',
                source='walk_by',
                deal_description='Existing CRM notes',
            )
            db.session.add(lead)
            db.session.commit()
            lead_id = lead.id

            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '4903 North Hermitage Ave, Chicago, IL 60640, USA',
                    'note': 'Walk-by after Places select',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            body = response.get_json()
            assert body['created'] is False
            assert body['lead_id'] == lead_id
            db.session.refresh(lead)
            assert lead.property_city == 'Chicago'
            assert lead.property_state == 'IL'
            assert lead.property_zip == '60640'

    def test_dedup_does_not_collide_across_cities(self, quick_add_client, app):
        with app.app_context():
            chicago = Lead(
                property_street='123 Main St',
                property_city='Chicago',
                property_state='IL',
                owner_user_id='test-user',
                lead_status='skip_trace',
                source='walk_by',
            )
            db.session.add(chicago)
            db.session.commit()
            chicago_id = chicago.id

            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '123 Main St, Evanston, IL 60201, USA',
                    'property_city': 'Evanston',
                    'property_state': 'IL',
                    'property_zip': '60201',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            body = response.get_json()
            assert body['created'] is True
            assert body['lead_id'] != chicago_id

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

    def test_costar_deal_source_accepted(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '3508 CoStar Deal Source St, Chicago, IL',
                    'deal_source': 'CoStar',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            body = response.get_json()
            assert body['deal_source'] == 'CoStar'
            lead = db.session.get(Lead, body['lead_id'])
            assert lead is not None
            assert lead.deal_source == 'CoStar'

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

    def test_enqueue_failure_reports_queue_failed_when_writeback_disabled(self, quick_add_client, app):
        with app.app_context():
            with (
                patch('app.controllers.quick_add_controller.hubspot_write_back_enabled', return_value=False),
                patch('celery_worker.run_quick_add_followup.delay', side_effect=RuntimeError('broker down')),
            ):
                response = quick_add_client.post(
                    '/api/leads/quick-add',
                    headers=_AUTH_HEADERS,
                    data=json.dumps({
                        'property_street': '222 Queue Failure Ave, Chicago, IL',
                    }),
                    content_type='application/json',
                )

            assert response.status_code == 201
            body = response.get_json()
            assert body['hubspot_write_back_enabled'] is False
            assert body['hubspot_push_status'] == 'queue_failed'


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
