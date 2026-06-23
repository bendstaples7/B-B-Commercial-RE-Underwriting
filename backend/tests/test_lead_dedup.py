"""Tests for duplicate lead merge utilities, Sheets dedup, and HubSpot disambiguation."""
import pytest

from app import db
from app.models.hubspot_deal import HubSpotDeal
from app.models.hubspot_match import HubSpotMatch
from app.models.lead import Lead
from app.services.google_sheets_importer import GoogleSheetsImporter
from app.services.hubspot_matcher_service import HubSpotMatcherService
from app.services.lead_merge_utils import (
    cluster_leads_by_normalized_street,
    pick_merge_winner,
    pick_best_lead_for_deal,
)


class TestMergeWinnerSelection:
    def test_pick_merge_winner_prefers_hubspot_and_higher_stage(self):
        confirmed = {11129}
        records = [
            {
                'id': 2835,
                'lead_status': 'mailing_contacted_interested',
                'has_phone': True,
                'has_email': False,
                'last_hubspot_sync_at': None,
            },
            {
                'id': 11129,
                'lead_status': 'negotiating_remote',
                'has_phone': False,
                'has_email': False,
                'last_hubspot_sync_at': None,
            },
        ]
        winner = pick_merge_winner(records, confirmed)
        assert winner['id'] == 11129

    def test_cluster_groups_schiller_variants(self):
        rows = [
            {'id': 2835, 'property_street': '1915 W Schiller St'},
            {'id': 11129, 'property_street': '1915 W Schiller'},
        ]
        clusters = cluster_leads_by_normalized_street(rows)
        assert len(clusters) == 1
        assert {r['id'] for r in clusters[0]} == {2835, 11129}


class TestGoogleSheetsNormalizedDedup:
    def test_find_duplicate_normalized_street(self, app):
        with app.app_context():
            existing = Lead(
                property_street='1915 W Schiller St',
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
                owner_user_id='user-abc',
            )
            db.session.add(existing)
            db.session.commit()

            hit = GoogleSheetsImporter._find_duplicate(
                {
                    'property_street': '1915 W Schiller',
                    'owner_first_name': 'Ronald',
                    'owner_last_name': 'Jutkins',
                },
                owner_user_id='user-abc',
            )
            assert hit is not None
            assert hit.id == existing.id


class TestHubSpotAddressDisambiguation:
    def _make_deal(self, hubspot_id: str, address: str, **owner_props) -> HubSpotDeal:
        props = {'dealname': address, **owner_props}
        return HubSpotDeal(hubspot_id=hubspot_id, raw_payload={'properties': props})

    def test_disambiguates_multiple_address_hits_by_owner_name(self, app):
        with app.app_context():
            john = Lead(
                property_street='123 Oak St',
                owner_first_name='John',
                owner_last_name='Smith',
            )
            jane = Lead(
                property_street='123 Oak Street',
                owner_first_name='Jane',
                owner_last_name='Doe',
            )
            db.session.add_all([john, jane])
            db.session.commit()

            deal = self._make_deal(
                'deal-1',
                '123 Oak St',
                firstname='Jane',
                lastname='Doe',
            )
            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)

            assert match.status == 'confirmed'
            assert match.internal_record_id == jane.id

    def test_disambiguates_prefers_hubspot_confirmed_lead(self, app):
        with app.app_context():
            sheets_lead = Lead(
                property_street='1915 W Schiller St',
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
                lead_status='mailing_contacted_interested',
            )
            hubspot_lead = Lead(
                property_street='1915 W Schiller',
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
                lead_status='negotiating_remote',
            )
            db.session.add_all([sheets_lead, hubspot_lead])
            db.session.flush()

            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='existing-deal',
                internal_record_type='lead',
                internal_record_id=hubspot_lead.id,
                confidence='MEDIUM',
                status='confirmed',
                matching_criteria='address_match',
            ))
            db.session.commit()

            deal = self._make_deal('deal-new', '1915 W Schiller')
            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)

            assert match.status == 'confirmed'
            assert match.internal_record_id == hubspot_lead.id
            assert sheets_lead.review_required is True

    def test_no_placeholder_when_normalized_match_exists(self, app):
        """Unmatched path should link to existing lead instead of creating placeholder."""
        with app.app_context():
            existing = Lead(
                property_street='1915 W Schiller St',
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
            )
            db.session.add(existing)
            db.session.commit()
            before_count = Lead.query.count()

            deal = self._make_deal('deal-placeholder', '1915 W Schiller')
            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)

            assert Lead.query.count() == before_count
            assert match.internal_record_id == existing.id
            assert match.status == 'confirmed'
