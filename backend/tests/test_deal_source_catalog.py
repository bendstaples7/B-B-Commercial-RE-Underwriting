"""Tests for deal / capture source catalog (custom Source dropdown values)."""
import json

from app import db
from app.models.deal_source_option import DealSourceOption
from app.models.lead import Lead
from app.services.deal_source_service import DealSourceService
from app.services.helpers.deal_source import (
    DEAL_SOURCE_OPTIONS,
    hubspot_deal_source_for_writeback,
)
from app.services.hubspot_writeback_service import HubSpotWriteBackService


_AUTH_HEADERS = {'X-User-Id': 'test-user', 'Content-Type': 'application/json'}


class TestHubspotDealSourceForWriteback:
    def test_builtin_passes_through(self):
        assert hubspot_deal_source_for_writeback('CoStar') == 'CoStar'
        assert hubspot_deal_source_for_writeback('driving for dollars') == 'Driving For Dollars'

    def test_custom_maps_to_other(self):
        assert hubspot_deal_source_for_writeback('Facebook Ad') == 'Other'
        assert hubspot_deal_source_for_writeback('') == 'Other'


class TestDealSourceService:
    def test_list_includes_builtins(self, app):
        with app.app_context():
            names = [row['name'] for row in DealSourceService().list_sources()]
            for option in DEAL_SOURCE_OPTIONS:
                assert option in names

    def test_create_and_list_custom(self, app):
        with app.app_context():
            result = DealSourceService().create_source('Facebook Ad', created_by='tester')
            assert result['name'] == 'Facebook Ad'
            assert result['is_builtin'] is False
            assert result['created'] is True

            again = DealSourceService().create_source('facebook ad')
            assert again['created'] is False
            assert again['name'] == 'Facebook Ad'

            names = [row['name'] for row in DealSourceService().list_sources()]
            assert 'Facebook Ad' in names

    def test_ensure_registered_flushes_custom(self, app):
        with app.app_context():
            name = DealSourceService().ensure_registered('Instagram Ad')
            assert name == 'Instagram Ad'
            db.session.commit()
            row = DealSourceOption.query.filter_by(name='Instagram Ad').first()
            assert row is not None

    def test_discovered_from_existing_lead(self, app):
        with app.app_context():
            lead = Lead(property_street='1 Discover St', deal_source='Yard Sign')
            db.session.add(lead)
            db.session.commit()
            names = [row['name'] for row in DealSourceService().list_sources()]
            assert 'Yard Sign' in names


class TestDealSourcesApi:
    def test_list_and_create(self, client, app):
        with app.app_context():
            listed = client.get('/api/deal-sources', headers=_AUTH_HEADERS)
            assert listed.status_code == 200
            body = listed.get_json()
            assert any(s['name'] == 'Referral' for s in body['sources'])

            created = client.post(
                '/api/deal-sources',
                headers=_AUTH_HEADERS,
                data=json.dumps({'name': 'Facebook Ad'}),
                content_type='application/json',
            )
            assert created.status_code == 201
            assert created.get_json()['name'] == 'Facebook Ad'

            listed2 = client.get('/api/deal-sources', headers=_AUTH_HEADERS)
            assert any(s['name'] == 'Facebook Ad' for s in listed2.get_json()['sources'])

    def test_blank_name_rejected(self, client, app):
        with app.app_context():
            response = client.post(
                '/api/deal-sources',
                headers=_AUTH_HEADERS,
                data=json.dumps({'name': '   '}),
                content_type='application/json',
            )
            assert response.status_code == 400

    def test_non_string_name_rejected(self, client, app):
        with app.app_context():
            response = client.post(
                '/api/deal-sources',
                headers=_AUTH_HEADERS,
                data=json.dumps({'name': ['Facebook']}),
                content_type='application/json',
            )
            assert response.status_code == 400
            body = response.get_json()
            assert 'string' in (body.get('message') or body.get('error') or '').lower()
            assert DealSourceOption.query.filter_by(name="['Facebook']").first() is None


class TestQuickAddCustomDealSource:
    def test_custom_deal_source_accepted_and_registered(self, client, app):
        with app.app_context():
            response = client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '100 Facebook Ad Ave, Chicago, IL',
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
            assert DealSourceOption.query.filter_by(name='Facebook Ad').first() is not None

    def test_oversized_deal_source_rejected(self, client, app):
        with app.app_context():
            response = client.post(
                '/api/leads/quick-add',
                headers=_AUTH_HEADERS,
                data=json.dumps({
                    'property_street': '101 Too Long Source St',
                    'deal_source': 'x' * 300,
                }),
                content_type='application/json',
            )
            assert response.status_code == 400


class TestHubSpotWritebackCustomSource:
    def test_custom_source_sent_as_other(self, app):
        with app.app_context():
            lead = Lead(
                property_street='55 Custom Source St',
                deal_source='Facebook Ad',
            )
            props = HubSpotWriteBackService()._deal_properties_from_lead(
                lead, pipeline_id=None, stage_id=None, include_stage=False,
            )
            assert props['deal_source'] == 'Other'
