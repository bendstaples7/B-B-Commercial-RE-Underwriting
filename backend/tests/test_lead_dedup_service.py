"""Tests for DB-enforced lead dedup identity and duplicate sentinel."""
import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.hubspot_match import HubSpotMatch
from app.models.lead import Lead
from app.services.lead_dedup_service import (
    find_lead_by_identity,
    merge_confidence,
    refresh_lead_dedup_fields,
    run_duplicate_sentinel,
)
from app.services.lead_merge_utils import dedup_street_key


class TestDedupStreetKey:
    def test_schiller_variants_share_key(self):
        assert dedup_street_key('1915 W Schiller') == dedup_street_key('1915 W Schiller St')

    def test_abbreviation_variants_share_key(self):
        assert dedup_street_key('4263 W Montrose') == dedup_street_key('4263 W Montrose Ave Apt 1')


class TestLeadDedupFields:
    def test_refresh_sets_normalized_street(self, app):
        with app.app_context():
            lead = Lead(
                property_street='1915 W Schiller St',
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
            )
            refresh_lead_dedup_fields(lead)
            assert lead.normalized_street == '1915 W SCHILLER'

    def test_before_insert_sets_normalized_street(self, app):
        with app.app_context():
            lead = Lead(
                property_street='100 Main St',
                owner_first_name='Jane',
                owner_last_name='Doe',
                owner_user_id='user-1',
            )
            db.session.add(lead)
            db.session.commit()
            assert lead.normalized_street == '100 MAIN'


class TestFindLeadByIdentity:
    def test_finds_by_normalized_street_column(self, app):
        with app.app_context():
            existing = Lead(
                property_street='1915 W Schiller St',
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
                owner_user_id='user-abc',
            )
            db.session.add(existing)
            db.session.commit()

            hit = find_lead_by_identity(
                owner_user_id='user-abc',
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
                property_street='1915 W Schiller',
            )
            assert hit is not None
            assert hit.id == existing.id


class TestDuplicateSentinel:
    def test_auto_merges_clear_duplicate(self, app):
        with app.app_context():
            sheets = Lead(
                property_street='1915 W Schiller St',
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
                owner_user_id='user-1',
                lead_status='mailing_contacted_interested',
            )
            hubspot = Lead(
                property_street='1915 W Schiller',
                owner_first_name='Ronald',
                owner_last_name='Jutkins',
                owner_user_id='user-1',
                lead_status='negotiating_remote',
            )
            db.session.add_all([sheets, hubspot])
            db.session.flush()
            db.session.add(HubSpotMatch(
                hubspot_record_type='deal',
                hubspot_id='deal-1',
                internal_record_type='lead',
                internal_record_id=hubspot.id,
                confidence='MEDIUM',
                status='confirmed',
                matching_criteria='address_match',
            ))
            db.session.commit()
            loser_id = sheets.id
            winner_id = hubspot.id

            stats = run_duplicate_sentinel(dry_run=False, max_merges=10)
            assert stats['merged'] == 1
            assert Lead.query.get(loser_id) is None
            assert Lead.query.get(winner_id) is not None

    def test_flags_ambiguous_competing_hubspot_matches(self, app):
        with app.app_context():
            a = Lead(
                property_street='500 Shared St',
                owner_first_name='Pat',
                owner_last_name='Lee',
                owner_user_id='user-1',
            )
            b = Lead(
                property_street='500 Shared Street',
                owner_first_name='Pat',
                owner_last_name='Lee',
                owner_user_id='user-1',
            )
            db.session.add_all([a, b])
            db.session.flush()
            for lead_id, deal_id in ((a.id, 'd1'), (b.id, 'd2')):
                db.session.add(HubSpotMatch(
                    hubspot_record_type='deal',
                    hubspot_id=deal_id,
                    internal_record_type='lead',
                    internal_record_id=lead_id,
                    confidence='MEDIUM',
                    status='confirmed',
                    matching_criteria='address_match',
                ))
            db.session.commit()

            records = [
                {'id': a.id, 'lead_status': a.lead_status, 'has_phone': False,
                 'has_email': False, 'last_hubspot_sync_at': None},
                {'id': b.id, 'lead_status': b.lead_status, 'has_phone': False,
                 'has_email': False, 'last_hubspot_sync_at': None},
            ]
            from app.services.lead_dedup_service import confirmed_hubspot_lead_ids
            assert merge_confidence(records, confirmed_hubspot_lead_ids()) == 'ambiguous'

            stats = run_duplicate_sentinel(dry_run=False, max_merges=10)
            assert stats['flagged'] == 2
            assert stats['merged'] == 0
            db.session.refresh(a)
            db.session.refresh(b)
            assert a.review_required is True
            assert b.review_required is True
