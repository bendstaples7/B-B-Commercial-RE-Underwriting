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

    def test_places_full_address_shares_key_with_street(self):
        assert dedup_street_key('4903 N Hermitage') == dedup_street_key(
            '4903 N Hermitage Ave, Chicago, IL 60640, USA',
        )

    def test_no_comma_city_state_zip_shares_key_with_bare_street(self):
        """City/state/zip glued into property_street (no commas) must not diverge."""
        bare = '4128 W Barry Ave'
        glued = '4128 W Barry Ave Chicago IL 60618'
        comma = '4128 W Barry Ave, Chicago, IL 60618'
        assert dedup_street_key(bare) == dedup_street_key(glued)
        assert dedup_street_key(bare) == dedup_street_key(comma)

    def test_harding_no_comma_shares_key_with_bare_street(self):
        assert dedup_street_key('3446 N Harding Ave') == dedup_street_key(
            '3446 N Harding Ave Chicago IL 60618',
        )

    def test_zip_only_suffix_does_not_strip_street_name(self):
        """``1719 W Barry 60657`` must keep Barry (no state token to strip on)."""
        assert dedup_street_key('1719 W Barry 60657') == dedup_street_key('1719 W Barry')
        assert 'BARRY' in dedup_street_key('1719 W Barry 60657')

    def test_street_suffix_st_is_not_treated_as_state(self):
        """``1719 W Barry St 60657`` must not parse ST as the US state."""
        assert 'BARRY' in dedup_street_key('1719 W Barry St 60657')
        assert dedup_street_key('1719 W Barry St 60657') == dedup_street_key('1719 W Barry St')
        assert dedup_street_key('1719 W Barry St 60657') != dedup_street_key('1719 W')

    def test_north_and_n_share_key(self):
        assert dedup_street_key('4903 North Hermitage') == dedup_street_key('4903 N Hermitage')

    def test_cardinal_street_name_is_not_collapsed(self):
        assert dedup_street_key('123 North Street') != dedup_street_key('123 N Street')


class TestCitiesCompatible:
    def test_missing_either_side_is_compatible(self):
        from app.services.lead_merge_utils import cities_compatible

        assert cities_compatible(None, 'Chicago') is True
        assert cities_compatible('Chicago', None) is True
        assert cities_compatible('', '') is True

    def test_distinct_cities_incompatible(self):
        from app.services.lead_merge_utils import cities_compatible

        assert cities_compatible('Chicago', 'Evanston') is False
        assert cities_compatible('Chicago', 'chicago') is True


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

    def test_before_update_skips_normalized_street_when_street_unchanged(self, app):
        """City/state/zip-only updates must not recompute normalized_street."""
        with app.app_context():
            lead = Lead(
                property_street='3446 N Harding Ave Chicago IL 60618',
                owner_first_name='Joseph',
                owner_last_name='Zajac',
                owner_user_id='user-1',
            )
            db.session.add(lead)
            db.session.commit()
            stale_key = '3446 N HARDING AVENUE CHICAGO IL'
            lead.normalized_street = stale_key
            db.session.commit()

            lead.property_city = 'Chicago'
            lead.property_state = 'IL'
            lead.property_zip = '60618'
            db.session.commit()

            db.session.refresh(lead)
            assert lead.normalized_street == stale_key
            assert lead.property_city == 'Chicago'

    def test_before_update_refreshes_normalized_street_when_street_changes(self, app):
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

            lead.property_street = '200 Oak Ave'
            db.session.commit()
            db.session.refresh(lead)
            assert lead.normalized_street == '200 OAK'


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

    def test_importer_identity_hit_respects_city_without_pin(self, app):
        from app.services.google_sheets_importer import GoogleSheetsImporter

        with app.app_context():
            existing = Lead(
                property_street='123 Main St',
                property_city='Chicago',
                owner_first_name='Jane',
                owner_last_name='Owner',
                owner_user_id='user-abc',
            )
            db.session.add(existing)
            db.session.commit()

            hit = GoogleSheetsImporter._find_duplicate(  # noqa: SLF001
                {
                    'property_street': '123 Main St, Evanston, IL 60201',
                    'property_city': 'Evanston',
                    'owner_first_name': 'Jane',
                    'owner_last_name': 'Owner',
                },
                owner_user_id='user-abc',
            )

            assert hit is None


class TestDuplicateClusters:
    def test_clusters_jammed_last_first_with_split_names(self, app):
        """Assessor LAST FIRST jammed into first_name must cluster with split rows."""
        from app.services.lead_dedup_service import find_duplicate_clusters

        with app.app_context():
            jammed = Lead(
                property_street='4128 W Barry Ave',
                owner_first_name='GARCIA ADALBERTO',
                owner_last_name=None,
                owner_user_id='user-1',
            )
            split = Lead(
                property_street='4128 W Barry Ave Chicago IL 60618',
                owner_first_name='ADALBERTO',
                owner_last_name='GARCIA',
                owner_user_id='user-1',
            )
            db.session.add_all([jammed, split])
            db.session.commit()

            clusters = find_duplicate_clusters()
            ids = {frozenset(lead.id for lead in group) for group in clusters}
            assert frozenset({jammed.id, split.id}) in ids


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
