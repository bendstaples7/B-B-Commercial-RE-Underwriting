"""Tests for HubSpotDealSyncService."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models.hubspot_deal import HubSpotDeal
from app.models.hubspot_match import HubSpotMatch
from app.models.lead import Lead
from app.services.hubspot_deal_sync_service import HubSpotDealSyncService


class TestHubSpotDealSyncService:
    def test_get_lead_sync_health_stale_when_never_synced(self, app):
        with app.app_context():
            lead = Lead(
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
                property_street='1915 W Schiller',
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(HubSpotDeal(
                hubspot_id='deal-1',
                raw_payload={'properties': {'dealstage': 'stage1'}},
            ))
            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='deal-1',
                internal_record_type='lead',
                internal_record_id=lead.id,
                confidence='HIGH',
                status='confirmed',
            ))
            db.session.commit()

            health = HubSpotDealSyncService.get_lead_sync_health(lead.id)
            assert health['hubspot_has_confirmed_deal'] is True
            assert health['hubspot_sync_stale'] is True

    def test_get_lead_sync_health_fresh_after_sync(self, app):
        with app.app_context():
            lead = Lead(
                owner_first_name='A',
                owner_last_name='B',
                last_hubspot_sync_at=datetime.utcnow(),
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(HubSpotDeal(
                hubspot_id='deal-2',
                raw_payload={'properties': {}},
            ))
            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='deal-2',
                internal_record_type='lead',
                internal_record_id=lead.id,
                confidence='HIGH',
                status='confirmed',
            ))
            db.session.commit()

            health = HubSpotDealSyncService.get_lead_sync_health(lead.id)
            assert health['hubspot_sync_stale'] is False

    @patch.object(HubSpotDealSyncService, 'refresh_and_enrich_lead')
    def test_auto_sync_lead_if_stale_triggers_refresh(self, mock_refresh, app):
        with app.app_context():
            lead = Lead(owner_first_name='A', owner_last_name='B')
            db.session.add(lead)
            db.session.flush()
            db.session.add(HubSpotDeal(
                hubspot_id='deal-stale',
                raw_payload={'properties': {'dealstage': 'stage1'}},
            ))
            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='deal-stale',
                internal_record_type='lead',
                internal_record_id=lead.id,
                confidence='HIGH',
                status='confirmed',
            ))
            db.session.commit()

            mock_refresh.return_value = {'synced': True}
            assert HubSpotDealSyncService.auto_sync_lead_if_stale(lead.id) is True
            mock_refresh.assert_called_once_with(lead.id, include_tasks=False)

    @patch.object(HubSpotDealSyncService, 'refresh_and_enrich_lead')
    def test_auto_sync_skips_when_fresh(self, mock_refresh, app):
        with app.app_context():
            lead = Lead(
                owner_first_name='A',
                owner_last_name='B',
                last_hubspot_sync_at=datetime.utcnow(),
                deal_source='Cityscape',
                deal_description='Zoning lead',
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(HubSpotDeal(
                hubspot_id='deal-fresh',
                raw_payload={'properties': {'deal_source': 'Cityscape', 'description': 'Zoning lead'}},
            ))
            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='deal-fresh',
                internal_record_type='lead',
                internal_record_id=lead.id,
                confidence='HIGH',
                status='confirmed',
            ))
            db.session.commit()

            assert HubSpotDealSyncService.auto_sync_lead_if_stale(lead.id) is False
            mock_refresh.assert_not_called()

    def test_deal_missing_context_properties_when_keys_absent(self, app):
        with app.app_context():
            deal = HubSpotDeal(
                hubspot_id='deal-partial',
                raw_payload={'properties': {'dealname': 'Test'}},
            )
            assert HubSpotDealSyncService.deal_missing_context_properties(deal) is True

            deal2 = HubSpotDeal(
                hubspot_id='deal-full',
                raw_payload={'properties': {'deal_source': 'Cityscape', 'description': 'Zoning lead'}},
            )
            assert HubSpotDealSyncService.deal_missing_context_properties(deal2) is False

            deal3 = HubSpotDeal(
                hubspot_id='deal-empty',
                raw_payload={'properties': {'deal_source': '', 'description': ''}},
            )
            assert HubSpotDealSyncService.deal_missing_context_properties(deal3) is True

    @patch.object(HubSpotDealSyncService, 'refresh_and_enrich_lead')
    def test_auto_sync_when_deal_context_properties_missing(self, mock_refresh, app):
        with app.app_context():
            lead = Lead(
                owner_first_name='A',
                owner_last_name='B',
                last_hubspot_sync_at=datetime.utcnow(),
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(HubSpotDeal(
                hubspot_id='deal-missing-ctx',
                raw_payload={'properties': {'dealname': '1915 W Schiller'}},
            ))
            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='deal-missing-ctx',
                internal_record_type='lead',
                internal_record_id=lead.id,
                confidence='HIGH',
                status='confirmed',
            ))
            db.session.commit()

            mock_refresh.return_value = {'synced': True}
            assert HubSpotDealSyncService.auto_sync_lead_if_stale(lead.id) is True
            mock_refresh.assert_called_once_with(lead.id, include_tasks=False)

    @patch.object(HubSpotDealSyncService, 'refresh_deal_from_api')
    @patch('app.services.hubspot_deal_sync_service.HubSpotDealSyncService._get_client')
    def test_refresh_and_enrich_lead_updates_status(
        self, mock_get_client, mock_refresh, app,
    ):
        with app.app_context():
            lead = Lead(
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
                property_street='1915 W Schiller',
                lead_status='negotiating_remote',
                hubspot_deal_stage='Negotiating Remote',
            )
            db.session.add(lead)
            db.session.flush()
            deal = HubSpotDeal(
                hubspot_id='52218559108',
                raw_payload={
                    'properties': {
                        'dealname': '1915 W Schiller',
                        'dealstage': 'contractsent',
                    }
                },
            )
            db.session.add(deal)
            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='52218559108',
                internal_record_type='lead',
                internal_record_id=lead.id,
                confidence='HIGH',
                status='confirmed',
            ))
            db.session.commit()

            mock_client = MagicMock()
            mock_client.fetch_pipeline_stage_labels.return_value = {
                'contractsent': 'Mailing, contact made, no interest',
            }
            mock_get_client.return_value = mock_client
            mock_refresh.return_value = deal

            svc = HubSpotDealSyncService()
            result = svc.refresh_and_enrich_lead(lead.id)

            assert result['synced'] is True
            db.session.refresh(lead)
            assert lead.lead_status == 'mailing_contacted_no_interest'
            assert lead.hubspot_deal_stage == 'Mailing, contact made, no interest'
            assert lead.last_hubspot_sync_at is not None

    def test_enrich_lead_from_deal_sets_last_hubspot_sync_at(self, app):
        with app.app_context():
            lead = Lead(property_street='1 Main', lead_status='awaiting_skip_trace')
            deal = HubSpotDeal(
                hubspot_id='d1',
                raw_payload={'properties': {'dealstage': 'unknown_id'}},
            )
            db.session.add_all([lead, deal])
            db.session.commit()

            from app.services.hubspot_matcher_service import HubSpotMatcherService
            matcher = HubSpotMatcherService()
            matcher.enrich_lead_from_deal(lead, deal, stage_label_map={})
            db.session.commit()
            db.session.refresh(lead)
            assert lead.last_hubspot_sync_at is not None

    def test_enrich_lead_deal_context_from_cached_deal(self, app):
        """Lead columns empty but cached deal has context — enrich without API refresh."""
        with app.app_context():
            lead = Lead(
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
                property_street='1915 W Schiller',
                last_hubspot_sync_at=datetime.utcnow(),
            )
            db.session.add(lead)
            db.session.flush()
            deal = HubSpotDeal(
                hubspot_id='52218559108',
                raw_payload={
                    'properties': {
                        'dealname': '1915 W Schiller',
                        'deal_source': 'Cityscape Unused Zoning Capacity',
                        'description': '3 units currently zoned by right for 4',
                    }
                },
            )
            db.session.add(deal)
            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='52218559108',
                internal_record_type='lead',
                internal_record_id=lead.id,
                confidence='HIGH',
                status='confirmed',
            ))
            db.session.commit()

            with patch.object(HubSpotDealSyncService, 'refresh_deal_from_api') as mock_refresh:
                assert HubSpotDealSyncService.enrich_lead_deal_context_if_needed(lead.id) is True
                mock_refresh.assert_not_called()

            db.session.refresh(lead)
            assert lead.deal_source == 'Cityscape Unused Zoning Capacity'
            assert lead.deal_description == '3 units currently zoned by right for 4'

    @patch.object(HubSpotDealSyncService, 'refresh_and_enrich_lead')
    def test_auto_sync_when_lead_missing_deal_context(self, mock_refresh, app):
        with app.app_context():
            lead = Lead(
                owner_first_name='A',
                owner_last_name='B',
                last_hubspot_sync_at=datetime.utcnow(),
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(HubSpotDeal(
                hubspot_id='deal-has-ctx',
                raw_payload={
                    'properties': {
                        'deal_source': 'Cityscape',
                        'description': 'Zoning lead',
                    }
                },
            ))
            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='deal-has-ctx',
                internal_record_type='lead',
                internal_record_id=lead.id,
                confidence='HIGH',
                status='confirmed',
            ))
            db.session.commit()

            mock_refresh.return_value = {'synced': True}
            assert HubSpotDealSyncService.auto_sync_lead_if_stale(lead.id) is True
            mock_refresh.assert_called_once_with(lead.id, include_tasks=False)
