"""Tests for HubSpotWriteBackService."""
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models import HubSpotMatch, HubSpotPlatformWrite, Lead


def _make_lead(**overrides):
    defaults = {
        'property_street': '100 Writeback Test Ave',
        'owner_user_id': 'test-user',
        'deal_description': 'Walk-by note',
    }
    defaults.update(overrides)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


class TestHubSpotWriteBackService:
    @patch.dict('os.environ', {'HUBSPOT_WRITE_BACK_ENABLED': 'true'})
    def test_create_deal_from_lead(self, app):
        from app.services.hubspot_writeback_service import HubSpotWriteBackService

        with app.app_context():
            lead = _make_lead()
            mock_client = MagicMock()
            mock_client._get.return_value = {
                'results': [{
                    'id': 'default',
                    'stages': [{'id': 'stage1', 'label': 'Skip Trace'}],
                }],
            }
            mock_client.create_deal.return_value = {
                'id': 'hs-deal-99',
                'properties': {'dealname': lead.property_street},
            }

            with patch('app.services.hubspot_writeback_service._upsert_hubspot_record'):
                result = HubSpotWriteBackService(client=mock_client).push_lead_as_deal(lead.id)

            assert result['synced'] is True
            assert result['action'] == 'created'
            assert result['hubspot_deal_id'] == 'hs-deal-99'

            match = HubSpotMatch.query.filter_by(hubspot_id='hs-deal-99').first()
            assert match is not None
            assert match.status == 'confirmed'
            assert match.internal_record_id == lead.id

            writes = HubSpotPlatformWrite.query.filter_by(
                object_type='deal',
                hubspot_id='hs-deal-99',
            ).all()
            assert len(writes) == 1

    @patch.dict('os.environ', {'HUBSPOT_WRITE_BACK_ENABLED': 'false'})
    def test_skipped_when_disabled(self, app):
        from app.services.hubspot_writeback_service import HubSpotWriteBackService

        with app.app_context():
            lead = _make_lead()
            result = HubSpotWriteBackService().push_lead_as_deal(lead.id)
            assert result['synced'] is False
            assert result['reason'] == 'write_back_disabled'

    @patch.dict('os.environ', {'HUBSPOT_WRITE_BACK_ENABLED': 'true'})
    def test_update_existing_deal_skips_stage(self, app):
        from app.services.hubspot_writeback_service import HubSpotWriteBackService

        with app.app_context():
            lead = _make_lead()
            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='hs-deal-existing',
                internal_record_type='lead',
                internal_record_id=lead.id,
                confidence='HIGH',
                status='confirmed',
                matching_criteria='manual',
            ))
            db.session.commit()

            mock_client = MagicMock()
            mock_client.update_deal.return_value = {
                'id': 'hs-deal-existing',
                'properties': {'dealname': lead.property_street},
            }

            with patch.object(HubSpotWriteBackService, 'resolve_deal_stage') as mock_resolve:
                with patch('app.services.hubspot_writeback_service._upsert_hubspot_record'):
                    result = HubSpotWriteBackService(client=mock_client).push_lead_as_deal(lead.id)

            mock_resolve.assert_not_called()
            assert result['synced'] is True
            assert result['action'] == 'updated'

            update_props = mock_client.update_deal.call_args[0][1]
            assert 'dealstage' not in update_props
            assert 'pipeline' not in update_props

    def test_push_deal_stage_for_confirmed_match(self, app):
        from app.models.hubspot_deal import HubSpotDeal
        from app.services.hubspot_writeback_service import HubSpotWriteBackService

        with app.app_context():
            lead = _make_lead(lead_status='mailing_no_contact_made')
            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='hs-deal-stage',
                internal_record_type='lead',
                internal_record_id=lead.id,
                confidence='HIGH',
                status='confirmed',
                matching_criteria='manual',
            ))
            db.session.commit()

            mock_client = MagicMock()
            mock_client.update_deal.return_value = {
                'id': 'hs-deal-stage',
                'properties': {'dealstage': 'stage_skip'},
            }

            with patch.object(
                HubSpotWriteBackService,
                'resolve_deal_stage',
                return_value=('pipeline1', 'stage_skip'),
            ):
                with patch('app.services.hubspot_writeback_service._upsert_hubspot_record'):
                    result = HubSpotWriteBackService(client=mock_client).push_deal_stage_for_lead(
                        lead.id,
                        'skip_trace',
                    )

            assert result['synced'] is True
            assert result['action'] == 'stage_updated'
            update_props = mock_client.update_deal.call_args[0][1]
            assert update_props['dealstage'] == 'stage_skip'
            assert update_props['pipeline'] == 'pipeline1'

            db.session.refresh(lead)
            assert lead.hubspot_deal_stage == 'Skip Trace'
            assert lead.last_hubspot_sync_at is not None
