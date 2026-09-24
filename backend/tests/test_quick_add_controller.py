"""Tests for POST /api/leads/quick-add."""
import json
from datetime import date
from unittest.mock import patch

import pytest

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry
from app.services.quick_add_service import merge_deal_description, quick_add_activity_note_body

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
            assert lead.owner_first_name == ''

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
            notes = [
                e for e in entries
                if e.event_type == 'note_added'
                and not e.is_deleted
                and (e.event_metadata or {}).get('source') == 'quick_add'
            ]
            assert len(notes) == 1
            assert notes[0].summary.startswith('Looks promising')
            assert (notes[0].event_metadata or {}).get('body') == 'Looks promising'
            assert lead.notes == 'Looks promising'

    def test_creates_lead_in_chosen_pipeline_status(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '12 Chosen Stage Ave, Chicago, IL',
                    'lead_status': 'negotiating_remote',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            body = response.get_json()
            assert body['lead_status'] == 'negotiating_remote'
            lead = db.session.get(Lead, body['lead_id'])
            assert lead is not None
            assert lead.lead_status == 'negotiating_remote'
            assert lead.needs_skip_trace is not True
            assert LeadTask.query.filter_by(
                lead_id=lead.id, task_type='skip_trace_owner', status='open',
            ).first() is None

    def test_rejects_unknown_pipeline_status(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '14 Bad Stage Ave, Chicago, IL',
                    'lead_status': 'not_a_stage',
                }),
                content_type='application/json',
            )
            assert response.status_code == 400

    def test_dedup_does_not_apply_requested_pipeline_status(self, quick_add_client, app):
        with app.app_context():
            payload = {'property_street': '16 Keep Stage Ave, Chicago, IL'}
            created = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps(payload),
                content_type='application/json',
            )
            assert created.status_code == 201
            lead = db.session.get(Lead, created.get_json()['lead_id'])
            lead.lead_status = 'offer_delivered'
            db.session.commit()

            again = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({**payload, 'lead_status': 'mailing_no_contact_made'}),
                content_type='application/json',
            )
            assert again.status_code == 201
            assert again.get_json()['created'] is False
            assert again.get_json()['lead_status'] == 'offer_delivered'
            lead = db.session.get(Lead, lead.id)
            assert lead.lead_status == 'offer_delivered'

    def test_lead_capture_stores_source_context_and_notes(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '55 Capture Context Ave, Chicago, IL',
                    'capture_kind': 'lead',
                    'deal_source': 'Referral',
                    'context': 'Broker sent this yesterday',
                    'note': 'Call the owner after 5',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            lead = db.session.get(Lead, response.get_json()['lead_id'])
            assert lead.source == 'manual'
            assert lead.deal_source == 'Referral'
            assert lead.notes == 'Call the owner after 5'
            assert 'Broker sent this yesterday' in (lead.deal_description or '')
            assert 'Lead capture' in (lead.deal_description or '')
            notes = [
                e for e in LeadTimelineEntry.query.filter_by(
                    lead_id=lead.id, event_type='note_added', is_deleted=False,
                ).all()
                if (e.event_metadata or {}).get('source') == 'quick_add'
            ]
            assert len(notes) == 1
            assert notes[0].summary.startswith('Broker sent this yesterday')
            assert 'Call the owner after 5' in (notes[0].event_metadata or {}).get('body')

    def test_blank_note_still_writes_walk_by_activity_note(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '321 Walk By Note St, Chicago, IL',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            lead_id = response.get_json()['lead_id']
            notes = LeadTimelineEntry.query.filter_by(
                lead_id=lead_id, event_type='note_added', is_deleted=False,
            ).all()
            capture_notes = [
                e for e in notes
                if (e.event_metadata or {}).get('source') == 'quick_add'
            ]
            assert len(capture_notes) == 1
            assert capture_notes[0].summary.startswith('Walk-by ·')
            assert '321 Walk By Note St' in capture_notes[0].summary

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
            notes = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='note_added', is_deleted=False,
            ).order_by(LeadTimelineEntry.id).all()
            capture_notes = [
                e for e in notes
                if (e.event_metadata or {}).get('source') == 'quick_add'
            ]
            assert [e.summary for e in capture_notes] == ['First pass', 'Second pass']

    def test_recapture_keeps_existing_source(self, quick_add_client, app):
        with app.app_context():
            street = '424 Source Keep St, Chicago, IL'
            r1 = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({'property_street': street}),
                content_type='application/json',
            )
            lead = db.session.get(Lead, r1.get_json()['lead_id'])
            lead.source = 'hubspot'
            db.session.commit()

            r2 = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': street,
                    'capture_kind': 'lead',
                    'note': 'Second visit',
                }),
                content_type='application/json',
            )
            assert r2.status_code == 201
            assert r2.get_json()['created'] is False
            db.session.refresh(lead)
            assert lead.source == 'hubspot'

    def test_context_only_recapture_skips_generic_import(self, quick_add_client, app):
        with app.app_context():
            street = '121 Context Only Ln, Chicago, IL'
            r1 = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({'property_street': street, 'note': 'First note'}),
                content_type='application/json',
            )
            lead_id = r1.get_json()['lead_id']
            r2 = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({'property_street': street, 'context': 'Broker sent it'}),
                content_type='application/json',
            )
            assert r2.status_code == 201
            imported = LeadTimelineEntry.query.filter_by(
                lead_id=lead_id,
                event_type='lead_imported',
            ).count()
            assert imported == 1

    def test_blank_and_mixed_case_capture_kind(self, quick_add_client, app):
        with app.app_context():
            blank = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '10 Blank Kind Ave, Chicago, IL',
                    'capture_kind': '',
                }),
                content_type='application/json',
            )
            assert blank.status_code == 201
            blank_lead = db.session.get(Lead, blank.get_json()['lead_id'])
            assert blank_lead.source == 'walk_by'

            mixed = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '11 Mixed Kind Ave, Chicago, IL',
                    'capture_kind': 'Lead',
                }),
                content_type='application/json',
            )
            assert mixed.status_code == 201
            mixed_lead = db.session.get(Lead, mixed.get_json()['lead_id'])
            assert mixed_lead.source == 'manual'

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

    def test_oversized_deal_source_rejected(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '123 Bad Source St',
                    'deal_source': 'x' * 300,
                }),
                content_type='application/json',
            )
            assert response.status_code == 400

    def test_custom_facebook_ad_deal_source_accepted(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '456 Facebook Ad St, Chicago, IL',
                    'deal_source': 'Facebook Ad',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201
            body = response.get_json()
            assert body['deal_source'] == 'Facebook Ad'
            lead = db.session.get(Lead, body['lead_id'])
            assert lead is not None
            assert lead.deal_source == 'Facebook Ad'

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

    def test_skip_trace_enqueue_failure_marks_lead_for_retry(self, quick_add_client, app):
        with app.app_context():
            with patch(
                'app.services.quick_add_service.SkipTraceEnqueue.enqueue',
                side_effect=RuntimeError('task write failed'),
            ):
                response = quick_add_client.post(
                    '/api/leads/quick-add',
                    headers=_AUTH_HEADERS,
                    data=json.dumps({
                        'property_street': '333 Skip Trace Retry Ave, Chicago, IL',
                    }),
                    content_type='application/json',
                )

            assert response.status_code == 201
            lead = db.session.get(Lead, response.get_json()['lead_id'])
            assert lead.needs_skip_trace is True
            notes = LeadTimelineEntry.query.filter_by(
                lead_id=lead.id, event_type='note_added', is_deleted=False,
            ).all()
            capture_notes = [
                e for e in notes
                if (e.event_metadata or {}).get('source') == 'quick_add'
            ]
            assert len(capture_notes) == 1
            assert capture_notes[0].summary.startswith('Walk-by ·')


    def test_locality_only_without_street(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_city': 'Chicago',
                    'property_state': 'IL',
                    'note': 'Seller interested, address TBD',
                    'deal_source': 'Driving For Dollars',
                }),
                content_type='application/json',
            )
            assert response.status_code == 201, response.get_json()
            body = response.get_json()
            lead = db.session.get(Lead, body['lead_id'])
            assert lead is not None
            assert not (lead.property_street or '').strip()
            assert lead.property_city == 'Chicago'
            assert lead.property_state == 'IL'

    def test_property_facts_and_next_task(self, quick_add_client, app):
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '88 Facts Ave, Chicago, IL',
                    'lead_status': 'mailing_contacted_interested',
                    'units': 4,
                    'asking_price': 750000,
                    'bedrooms': 6,
                    'bathrooms': 3.5,
                    'lead_subtype': 'mixed_use',
                    'lead_units': [
                        {
                            'unit_label': 'Store',
                            'unit_type': 'storefront',
                            'current_rent': 2500,
                        },
                        {
                            'unit_label': '2F',
                            'unit_type': 'residential',
                            'beds': 2,
                            'baths': 1,
                        },
                    ],
                    'next_task': {
                        'title': 'Call seller about address',
                        'task_type': 'call_owner_today',
                        'due_date': date.today().isoformat(),
                        'notes': 'Confirm street address',
                    },
                }),
                content_type='application/json',
            )
            assert response.status_code == 201, response.get_json()
            body = response.get_json()
            lead = db.session.get(Lead, body['lead_id'])
            assert lead.units == 4
            assert float(lead.asking_price) == 750000
            assert lead.bedrooms == 6
            assert float(lead.bathrooms) == 3.5
            assert lead.lead_subtype == 'mixed_use'
            from app.models.lead_unit import LeadUnit
            units = (
                LeadUnit.query.filter_by(lead_id=lead.id)
                .order_by(LeadUnit.sort_order)
                .all()
            )
            assert len(units) == 2
            assert units[0].unit_type == 'storefront'
            task = LeadTask.query.filter_by(
                lead_id=lead.id, title='Call seller about address',
            ).first()
            assert task is not None
            assert task.task_type == 'call_owner_today'
            assert task.due_date == date.today()
            assert task.notes == 'Confirm street address'

    def test_malformed_lead_units_returns_validation_error(self, quick_add_client, app):
        """QuickAddSchema keeps lead_units; replace_lead_units ValueError → 400."""
        with app.app_context():
            response = quick_add_client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '89 Bad Units Ave, Chicago, IL',
                    'lead_units': [
                        {'unit_label': 'Unit 1', 'beds': 1.5},
                    ],
                }),
                content_type='application/json',
            )
            assert response.status_code == 400
            body = response.get_json()
            # Service ValueError (not marshmallow messages) after schema load.
            assert body.get('message') == 'beds/sqft must be integers'
            assert Lead.query.filter_by(
                property_street='89 Bad Units Ave, Chicago, IL',
            ).count() == 0

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
                headers={'X-User-Id': ''},
            )
            assert response.status_code in (401, 403)


class TestMergeDealDescription:
    def test_appends_without_discarding_existing(self):
        merged = merge_deal_description('Existing notes', 'Walk-by · new capture')
        assert merged.startswith('Existing notes')
        assert 'Walk-by · new capture' in merged

    def test_skips_duplicate_block(self):
        block = 'Walk-by · same capture'
        merged = merge_deal_description(f'Prior\n\n---\n\n{block}', block)
        assert merged.count(block) == 1

    def test_appends_when_new_note_is_only_a_substring(self):
        merged = merge_deal_description('Call the owner after 5', 'after 5')
        assert merged == 'Call the owner after 5\n\n---\n\nafter 5'


class TestQuickAddActivityNoteBody:
    def test_prefers_user_note(self):
        assert quick_add_activity_note_body(
            note='  Porch light on  ',
            walk_by_context='Walk-by · 123 Main · Sep 03, 2026 11:49 PM',
        ) == 'Porch light on'

    def test_includes_why_and_note(self):
        assert quick_add_activity_note_body(
            note='Call after 5',
            context='Broker referral',
            walk_by_context='Lead capture · 123 Main',
        ) == 'Broker referral\n\nCall after 5'

    def test_falls_back_to_walk_by_context(self):
        assert quick_add_activity_note_body(
            note='   ',
            walk_by_context='Walk-by · 123 Main · Sep 03, 2026 11:49 PM',
        ) == 'Walk-by · 123 Main · Sep 03, 2026 11:49 PM'
