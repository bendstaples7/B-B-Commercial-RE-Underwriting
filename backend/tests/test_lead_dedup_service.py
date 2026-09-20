"""Tests for DB-enforced lead dedup identity and duplicate sentinel."""
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.hubspot_match import HubSpotMatch
from app.models.lead import Lead
from app.models.contact import Contact
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
        assert dedup_street_key('4451 N Albany Ave') == dedup_street_key('4451 N Albany Ave #1')
        assert dedup_street_key('4451 N Albany Ave') == dedup_street_key('4451 N Albany Ave 1')

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

    def test_dual_house_number_range_shares_key_with_primary(self):
        """Duplex spellings must not glue into a fake house number (18671869)."""
        primary = dedup_street_key('1867 N Howe St')
        assert primary == dedup_street_key('1867-1869 N Howe St')
        assert primary == dedup_street_key('1867/1869 N Howe')
        assert primary == dedup_street_key('1867 & 1869 N Howe St')
        assert primary == dedup_street_key('1867–1869 N Howe')
        assert primary == dedup_street_key('1867-69 N Howe St')
        # Distinct neighboring house numbers stay distinct.
        assert primary != dedup_street_key('1869 N Howe St')

    def test_dual_house_range_matches_same_situs_as_primary(self):
        from app.services.lead_merge_utils import streets_match_same_situs

        assert streets_match_same_situs('1867 N Howe St', '1867-1869 N Howe St')
        assert streets_match_same_situs('1867 N Howe St', '1867/1869 N Howe St')
        assert not streets_match_same_situs('1867 N Howe St', '1869 N Howe St')

    def test_duplicate_merge_allows_husk_vs_unit_not_two_units(self):
        from app.services.lead_merge_utils import streets_match_duplicate_merge

        assert streets_match_duplicate_merge('2834 N Drake Ave', '2834 N Drake Ave 1r')
        assert streets_match_duplicate_merge('100 Main St', '100 Main St Unit 2')
        assert streets_match_duplicate_merge('100 Main St', '100 Main St 2')
        assert streets_match_duplicate_merge('100 Main St 02', '100 Main St Unit 2')
        assert not streets_match_duplicate_merge(
            '1 Oak Brook Club Dr Unit A-30',
            '1 Oak Brook Club Dr Unit A-206',
        )
        assert not streets_match_duplicate_merge('100 Main St 2', '100 Main St Unit 3')
        assert not streets_match_duplicate_merge('2834 N Drake Ave 2', '2834 N Drake Ave 1r')
        # Same door: bare number vs number + letter. Different suffixes stay apart.
        assert streets_match_duplicate_merge(
            '4451 N Albany APt 1',
            '4451 N Albany apt 1F',
        )
        assert streets_match_duplicate_merge(
            '4451 N Albany',
            '4451-4453 N Albany',
        )
        assert streets_match_duplicate_merge(
            '4451 N Albany',
            '4451 N Albany Apt 1',
        )
        assert not streets_match_duplicate_merge(
            '4451 N Albany Apt 1F',
            '4451 N Albany Apt 1R',
        )
        assert not streets_match_duplicate_merge(
            '4451 N Albany Apt 1F',
            '4451 N Albany Apt 2F',
        )

    def test_legacy_glued_range_key_for_stale_index_rows(self):
        from app.services.lead_merge_utils import legacy_glued_house_range_key

        assert legacy_glued_house_range_key('1867-1869 N Howe St') == '18671869 N HOWE'
        assert legacy_glued_house_range_key('1867 N Howe St') == ''


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


class TestSitusUnitToken:
    def test_trailing_alphanumeric_unit_is_respected(self):
        from app.services.lead_merge_utils import (
            situs_unit_token,
            streets_match_same_situs,
        )

        assert situs_unit_token('123 Main St 1R') == '1r'
        assert situs_unit_token('123 Main St 2R') == '2r'
        assert situs_unit_token('123 Main St 2') == '2'
        assert situs_unit_token('123 Main St 02') == '2'
        assert situs_unit_token('4451 N Albany APt 1') == '1'
        assert situs_unit_token('4451 N Albany apt 1F') == '1f'
        assert not streets_match_same_situs('123 Main St 1R', '123 Main St 2R')
        assert streets_match_same_situs('4451 N Albany APt 1', '4451 N Albany apt 1F')
        assert not streets_match_same_situs('4451 N Albany Apt 1F', '4451 N Albany Apt 1R')
        assert not streets_match_same_situs('4451 N Albany', '4451 N Albany Apt 1')

    def test_zip_only_suffix_is_not_treated_as_unit(self):
        from app.services.lead_merge_utils import situs_unit_token

        assert situs_unit_token('1719 W Barry 60657') == ''


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

    def test_does_not_cluster_conflicting_middle_initials(self, app):
        from app.services.lead_dedup_service import find_duplicate_clusters

        with app.app_context():
            a = Lead(
                property_street='100 Shared St',
                owner_first_name='Gilbert E',
                owner_last_name='Janson',
                owner_user_id='user-1',
            )
            b = Lead(
                property_street='100 Shared Street',
                owner_first_name='Gilbert A',
                owner_last_name='Janson',
                owner_user_id='user-1',
            )
            db.session.add_all([a, b])
            db.session.commit()

            clusters = find_duplicate_clusters()
            for group in clusters:
                ids = {lead.id for lead in group}
                assert not ({a.id, b.id} <= ids)


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

    def test_merge_prefers_newer_sale_and_cleaner_street(self, app):
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='3052 N Davlin 60618',
                owner_first_name='Gary',
                owner_last_name='Briggs',
                lead_status='mailing_contacted_no_interest',
                most_recent_sale='5/15/2024',
            )
            loser = Lead(
                property_street='3052 N Davlin Ct 1',
                owner_first_name='Gary Briggs',
                owner_last_name=None,
                lead_status='skip_trace',
                most_recent_sale='11/8/2024',
            )
            db.session.add_all([winner, loser])
            db.session.commit()
            loser_id = loser.id

            merge_lead_into_winner(winner, loser, changed_by='test')
            db.session.commit()

            assert Lead.query.get(loser_id) is None
            refreshed = Lead.query.get(winner.id)
            assert refreshed.most_recent_sale == '11/8/2024'
            assert refreshed.property_street == '3052 N Davlin Ct 1'

    def test_merge_copies_loser_situs_parts_before_completion(self, app):
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='3052 N Davlin Ct',
                property_city=None,
                property_state=None,
                property_zip=None,
                owner_first_name='Gary',
                owner_last_name='Briggs',
            )
            loser = Lead(
                property_street='3052 N Davlin Ct',
                property_city='Chicago',
                property_state='IL',
                property_zip='60618',
                owner_first_name='Gary',
                owner_last_name='Briggs',
            )
            db.session.add_all([winner, loser])
            db.session.commit()

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
                side_effect=RuntimeError('gis down'),
            ):
                merge_lead_into_winner(winner, loser, changed_by='test')
            db.session.commit()

            refreshed = Lead.query.get(winner.id)
            assert refreshed.property_city == 'Chicago'
            assert refreshed.property_state == 'IL'
            assert refreshed.property_zip == '60618'


class TestSiblingAbsorbAndSoftMerge:
    def test_absorb_merges_clear_street_only_twin(self, app):
        from app.services.lead_dedup_service import try_absorb_duplicate_for_lead

        with app.app_context():
            complete = Lead(
                property_street='2834 N Drake Ave 1r',
                property_city='Chicago',
                property_state='IL',
                property_zip='60618',
                owner_first_name='Francisco',
                owner_last_name='R Solis',
                owner_user_id='user-solis',
                lead_status='mailing_no_contact_made',
                has_phone=True,
            )
            husk = Lead(
                property_street='2834 N Drake Ave',
                property_city=None,
                property_state=None,
                property_zip=None,
                owner_first_name='Francisco',
                owner_last_name='R Solis',
                owner_user_id='user-solis',
                lead_status='mailing_no_contact_made',
            )
            db.session.add_all([complete, husk])
            db.session.commit()

            with patch(
                'app.services.lead_dedup_service.confirmed_hubspot_lead_ids',
                return_value=set(),
            ), patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ):
                result = try_absorb_duplicate_for_lead(husk, changed_by='test')
                db.session.commit()

            assert result is not None
            assert result.get('merged') is True
            assert db.session.get(Lead, husk.id) is None
            assert db.session.get(Lead, complete.id) is not None

    def test_siblings_match_by_owner_name_not_assignee(self, app):
        """CRM assignee is shared across the book — siblings use property-owner name."""
        from app.services.lead_dedup_service import find_building_owner_siblings

        with app.app_context():
            assignee = 'shared-assignee-uid'
            decoys = [
                Lead(
                    property_street=f'{100 + i} N Decoy Ave',
                    property_city='Chicago',
                    property_state='IL',
                    property_zip='60618',
                    owner_first_name='Other',
                    owner_last_name=f'Owner{i}',
                    owner_user_id=assignee,
                    lead_status='mailing_no_contact_made',
                )
                for i in range(5)
            ]
            twin = Lead(
                property_street='2834 N Drake Ave 1r',
                property_city='Chicago',
                property_state='IL',
                property_zip='60618',
                owner_first_name='Francisco',
                owner_last_name='R Solis',
                owner_user_id=assignee,
                lead_status='mailing_no_contact_made',
                has_phone=True,
            )
            husk = Lead(
                property_street='2834 N Drake Ave',
                property_city=None,
                property_state=None,
                property_zip=None,
                owner_first_name='Francisco',
                owner_last_name='R Solis',
                owner_user_id=assignee,
                lead_status='mailing_no_contact_made',
            )
            db.session.add_all(decoys + [twin, husk])
            db.session.commit()

            siblings = find_building_owner_siblings(husk)
            assert [s.id for s in siblings] == [twin.id]

    def test_merge_loser_into_winner_api_helper(self, app):
        from app.services.lead_dedup_service import merge_loser_into_winner

        with app.app_context():
            winner = Lead(
                property_street='100 Soft Merge St',
                property_city='Chicago',
                property_state='IL',
                property_zip='60618',
                owner_first_name='Ada',
                owner_last_name='Lovelace',
                review_required=True,
                review_reason='duplicate_lead_cluster',
            )
            loser = Lead(
                property_street='100 Soft Merge Street',
                property_city=None,
                property_state=None,
                property_zip=None,
                owner_first_name='Ada',
                owner_last_name='Lovelace',
                review_required=True,
                review_reason='duplicate_lead_cluster',
            )
            db.session.add_all([winner, loser])
            db.session.commit()

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ), patch(
                'app.services.lead_refresh.refresh_lead_scoring',
            ):
                result = merge_loser_into_winner(
                    winner.id, loser.id, changed_by='test', commit=True,
                )

            assert result['merged'] is True
            assert db.session.get(Lead, loser.id) is None
            refreshed = db.session.get(Lead, winner.id)
            assert refreshed.review_required is False
            assert refreshed.review_reason is None

    def test_merge_loser_into_winner_allows_building_husk_vs_unit(self, app):
        from app.services.lead_dedup_service import merge_loser_into_winner

        with app.app_context():
            winner = Lead(
                property_street='2834 N Drake Ave 1r',
                property_city='Chicago',
                property_state='IL',
                property_zip='60618',
                owner_first_name='Francisco',
                owner_last_name='R Solis',
                review_required=True,
                review_reason='duplicate_lead_cluster',
            )
            loser = Lead(
                property_street='2834 N Drake Ave',
                property_city='Chicago',
                property_state='IL',
                property_zip='60618',
                owner_first_name='Francisco',
                owner_last_name='R Solis',
                review_required=True,
                review_reason='duplicate_lead_cluster',
            )
            db.session.add_all([winner, loser])
            db.session.commit()

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ), patch(
                'app.services.lead_refresh.refresh_lead_scoring',
            ):
                result = merge_loser_into_winner(
                    winner.id, loser.id, changed_by='test', commit=True,
                )

            assert result['merged'] is True
            assert db.session.get(Lead, loser.id) is None

    def test_merge_integrity_error_preserves_outer_transaction_when_commit_false(self, app):
        from app.services.lead_dedup_service import merge_loser_into_winner

        with app.app_context():
            winner = Lead(property_street='100 Outer Tx St', owner_first_name='Ada')
            loser = Lead(property_street='100 Outer Tx Street', owner_first_name='Ada')
            db.session.add_all([winner, loser])
            db.session.commit()

            sentinel = Lead(property_street='200 Outer Tx St', owner_first_name='Pending')
            db.session.add(sentinel)
            try:
                with patch(
                    'app.services.lead_dedup_service.merge_lead_into_winner',
                    side_effect=IntegrityError(
                        'UPDATE',
                        {},
                        Exception(
                            'duplicate key value violates unique constraint '
                            '"uq_leads_owner_normalized_street"'
                        ),
                    ),
                ), pytest.raises(ValueError, match='uq_leads_owner_normalized_street'):
                    merge_loser_into_winner(
                        winner.id,
                        loser.id,
                        changed_by='test',
                        commit=False,
                    )

                assert sentinel.id is not None
                assert db.session.get(Lead, sentinel.id) is sentinel
            finally:
                db.session.rollback()

    def test_merge_prefers_unit_street_onto_bare_winner(self, app):
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='2834 N Drake Ave',
                property_city='Chicago',
                property_state='IL',
                property_zip='60618',
                owner_first_name='Francisco',
                owner_last_name='R Solis',
            )
            loser = Lead(
                property_street='2834 N Drake Ave 1r',
                property_city='Chicago',
                property_state='IL',
                property_zip='60618',
                county_assessor_pin='13262220410000',
                owner_first_name='Francisco',
                owner_last_name='R Solis',
            )
            db.session.add_all([winner, loser])
            db.session.commit()

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ):
                merge_lead_into_winner(winner, loser, changed_by='test')
                db.session.commit()

            refreshed = db.session.get(Lead, winner.id)
            assert refreshed.property_street == '2834 N Drake Ave 1r'
            assert refreshed.county_assessor_pin == '13262220410000'


class TestSameBuildingBannerAndAdditivePeople:
    def test_find_same_building_ignores_owner_name(self, app):
        from app.services.lead_dedup_service import (
            find_same_building_leads,
            refresh_lead_dedup_fields,
        )

        with app.app_context():
            yoko = Lead(
                property_street='1110 Yoko Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
            )
            both = Lead(
                property_street='1110 Yoko Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
                owner_2_first_name='Edwin',
                owner_2_last_name='Chen',
            )
            other_block = Lead(
                property_street='2200 Different St',
                owner_first_name='Yoko',
                owner_last_name='Miller',
            )
            db.session.add_all([yoko, both, other_block])
            for item in (yoko, both, other_block):
                refresh_lead_dedup_fields(item)
            db.session.commit()

            twins = find_same_building_leads(yoko)
            ids = {item.id for item in twins}
            assert both.id in ids
            assert other_block.id not in ids

    def test_find_same_building_matches_dual_house_number_range(self, app):
        """Primary house number and duplex range spelling are the same building."""
        from app.services.lead_dedup_service import (
            find_same_building_leads,
            refresh_lead_dedup_fields,
        )

        with app.app_context():
            primary = Lead(
                property_street='1867 N Howe St',
                owner_first_name='James',
                owner_last_name='Malone',
            )
            ranged = Lead(
                property_street='1867-1869 N Howe St',
                owner_first_name='James',
                owner_last_name='Malone',
            )
            neighbor = Lead(
                property_street='1869 N Howe St',
                owner_first_name='Other',
                owner_last_name='Neighbor',
            )
            db.session.add_all([primary, ranged, neighbor])
            for item in (primary, ranged, neighbor):
                refresh_lead_dedup_fields(item)
            # Simulate a stale pre-fix index row that glued 1867-1869 → 18671869.
            ranged.normalized_street = '18671869 N HOWE'
            db.session.commit()

            twins = find_same_building_leads(primary)
            ids = {item.id for item in twins}
            assert ranged.id in ids
            assert neighbor.id not in ids

            reverse_twins = find_same_building_leads(ranged)
            assert primary.id in {item.id for item in reverse_twins}

    def test_find_same_building_not_dropped_when_many_streets_share_house_1(self, app):
        from app.services.lead_dedup_service import (
            find_same_building_leads,
            refresh_lead_dedup_fields,
        )

        with app.app_context():
            decoys = []
            for idx in range(70):
                decoys.append(Lead(
                    property_street=f'1 Dummy{idx} St',
                    owner_first_name='Decoy',
                    owner_last_name=f'Owner{idx}',
                ))
            twin_a = Lead(
                property_street='1 Oak Brook Club Dr Unit A-30',
                owner_first_name='Bonnie',
                owner_last_name='Biggerstaff',
            )
            twin_b = Lead(
                property_street='1 Oak Brook Club Dr Unit A-30',
                owner_first_name='Don',
                owner_last_name='Gorz',
            )
            db.session.add_all(decoys + [twin_a, twin_b])
            for item in decoys + [twin_a, twin_b]:
                refresh_lead_dedup_fields(item)
            db.session.commit()

            twins = find_same_building_leads(twin_a)
            ids = {item.id for item in twins}
            assert twin_b.id in ids
            assert not ids.intersection({item.id for item in decoys})

    def test_find_same_building_does_not_list_other_condo_units(self, app):
        from app.services.lead_dedup_service import (
            find_same_building_leads,
            refresh_lead_dedup_fields,
        )

        with app.app_context():
            unit_a = Lead(
                property_street='1 Oak Brook Club Dr Unit A-30',
                owner_first_name='Bonnie',
                owner_last_name='Biggerstaff',
            )
            same_unit = Lead(
                property_street='1 Oak Brook Club Dr Unit A-30',
                owner_first_name='Don',
                owner_last_name='Gorz',
            )
            other_unit = Lead(
                property_street='1 Oak Brook Club Dr Unit A-206',
                owner_first_name='Angeline',
                owner_last_name='Christou',
            )
            db.session.add_all([unit_a, same_unit, other_unit])
            for item in (unit_a, same_unit, other_unit):
                refresh_lead_dedup_fields(item)
            db.session.commit()

            twins = find_same_building_leads(unit_a)
            ids = {item.id for item in twins}
            assert same_unit.id in ids
            assert other_unit.id not in ids

    def test_find_same_building_includes_husk_next_to_unit(self, app):
        """Apt 1 should offer the bare building record, not Apt 2."""
        from app.services.lead_dedup_service import (
            find_same_building_leads,
            refresh_lead_dedup_fields,
        )

        with app.app_context():
            unit = Lead(
                property_street='4451 N Albany Ave Apt 1',
                owner_first_name='Samuel',
                owner_last_name='Marconi',
            )
            husk = Lead(
                property_street='4451 N Albany Ave',
                owner_first_name='Samuel',
                owner_last_name='Marconi',
            )
            other_unit = Lead(
                property_street='4451 N Albany Ave Apt 2',
                owner_first_name='Other',
                owner_last_name='Tenant',
            )
            db.session.add_all([unit, husk, other_unit])
            for item in (unit, husk, other_unit):
                refresh_lead_dedup_fields(item)
            db.session.commit()

            from_unit = {item.id for item in find_same_building_leads(unit)}
            assert husk.id in from_unit
            assert other_unit.id not in from_unit

            from_husk = {item.id for item in find_same_building_leads(husk)}
            assert unit.id in from_husk
            assert other_unit.id in from_husk

    def test_find_same_building_from_hash_unit_finds_husk(self, app):
        """A trailing #1 must not hide the building record."""
        from app.services.lead_dedup_service import (
            find_same_building_leads,
            refresh_lead_dedup_fields,
        )

        with app.app_context():
            numbered = Lead(
                property_street='4451 N Albany Ave #1',
                owner_first_name='Samuel',
                owner_last_name='Marconi',
            )
            husk = Lead(
                property_street='4451 N Albany Ave',
                owner_first_name='Samuel',
                owner_last_name='Marconi',
            )
            db.session.add_all([numbered, husk])
            refresh_lead_dedup_fields(husk)
            # Stale index still ends in the unit number.
            numbered.normalized_street = '4451 N ALBANY AVENUE 1'
            db.session.commit()

            found = {item.id for item in find_same_building_leads(numbered)}
            assert husk.id in found

    def test_find_same_building_prompts_albany_range_husk_and_letter_suffix(self, app):
        """The three Albany spellings the merge banner must offer, both ways."""
        from app.services.lead_dedup_service import (
            find_same_building_leads,
            refresh_lead_dedup_fields,
        )

        with app.app_context():
            bare = Lead(
                property_street='4451 N Albany',
                owner_first_name='Samuel',
                owner_last_name='Marconi',
            )
            ranged = Lead(
                property_street='4451-4453 N Albany',
                owner_first_name='Samuel',
                owner_last_name='Marconi',
            )
            unit = Lead(
                property_street='4451 N Albany APt 1',
                owner_first_name='Samuel',
                owner_last_name='Marconi',
            )
            letter = Lead(
                property_street='4451 N Albany apt 1F',
                owner_first_name='Samuel',
                owner_last_name='Marconi',
            )
            other_door = Lead(
                property_street='4451 N Albany Apt 1R',
                owner_first_name='Other',
                owner_last_name='Door',
            )
            other_unit = Lead(
                property_street='4451 N Albany Apt 2',
                owner_first_name='Other',
                owner_last_name='Unit',
            )
            rows = (bare, ranged, unit, letter, other_door, other_unit)
            db.session.add_all(rows)
            for item in rows:
                refresh_lead_dedup_fields(item)
            db.session.commit()

            def ids_for(lead: Lead) -> set[int]:
                return {item.id for item in find_same_building_leads(lead)}

            from_bare = ids_for(bare)
            assert ranged.id in from_bare
            assert unit.id in from_bare
            assert letter.id in from_bare

            from_ranged = ids_for(ranged)
            assert bare.id in from_ranged
            assert unit.id in from_ranged

            from_unit = ids_for(unit)
            assert bare.id in from_unit
            assert letter.id in from_unit
            # Bare "1" is the same door as "1F" and "1R". Those lettered doors
            # are not the same as each other, and Apt 2 stays out.
            assert other_door.id in from_unit
            assert other_unit.id not in from_unit

            from_letter = ids_for(letter)
            assert unit.id in from_letter
            assert bare.id in from_letter
            assert other_door.id not in from_letter
            assert other_unit.id not in from_letter

    def test_same_address_summaries_default_to_current_lead_owner_scope(self, app):
        from app.services.lead_dedup_service import (
            refresh_lead_dedup_fields,
            same_address_lead_summaries,
        )

        with app.app_context():
            lead = Lead(
                property_street='100 Scoped Ave',
                owner_first_name='Scoped',
                owner_last_name='Owner',
                owner_user_id='user-1',
            )
            same_owner = Lead(
                property_street='100 Scoped Ave',
                owner_first_name='Same',
                owner_last_name='Owner',
                owner_user_id='user-1',
            )
            other_owner = Lead(
                property_street='100 Scoped Ave',
                owner_first_name='Other',
                owner_last_name='Owner',
                owner_user_id='user-2',
            )
            db.session.add_all([lead, same_owner, other_owner])
            for item in (lead, same_owner, other_owner):
                refresh_lead_dedup_fields(item)
            db.session.commit()

            ids = {row['id'] for row in same_address_lead_summaries(lead)}
            assert same_owner.id in ids
            assert other_owner.id not in ids

    def test_same_address_summaries_without_owner_scope_fail_closed(self, app):
        from app.services.lead_dedup_service import (
            refresh_lead_dedup_fields,
            same_address_lead_summaries,
        )

        with app.app_context():
            lead = Lead(property_street='100 Unowned Ave')
            twin = Lead(property_street='100 Unowned Ave')
            db.session.add_all([lead, twin])
            for item in (lead, twin):
                refresh_lead_dedup_fields(item)
            db.session.commit()

            assert same_address_lead_summaries(lead) == []

    def test_cluster_preview_hides_people_names_for_other_assignees(self, app):
        from app.services.contact_service import ContactService
        from app.services.lead_dedup_service import cluster_preview_for_lead

        with app.app_context():
            lead = Lead(
                property_street='100 Scoped Ave',
                owner_first_name='Scoped',
                owner_last_name='Owner',
                owner_user_id='user-1',
            )
            same_scope = Lead(
                property_street='100 Scoped Ave Unit 1',
                owner_first_name='Scoped',
                owner_last_name='Owner',
                owner_user_id='user-1',
            )
            other_scope = Lead(
                property_street='100 Scoped Ave Unit 2',
                owner_first_name='Scoped',
                owner_last_name='Owner',
                owner_user_id='user-2',
            )
            db.session.add_all([lead, same_scope, other_scope])
            for item in (lead, same_scope, other_scope):
                refresh_lead_dedup_fields(item)
            db.session.commit()

            service = ContactService()
            visible = service.create_contact({
                'first_name': 'Visible',
                'last_name': 'Owner',
            })
            hidden = service.create_contact({
                'first_name': 'Hidden',
                'last_name': 'Owner',
            })
            service.link_contact_to_property(
                same_scope.id, visible.id, role='owner', is_primary=True,
            )
            service.link_contact_to_property(
                other_scope.id, hidden.id, role='owner', is_primary=True,
            )
            db.session.commit()

            preview = cluster_preview_for_lead(lead)

            assert preview is not None
            members = {row['id']: row for row in preview['members']}
            assert members[same_scope.id]['people_names'] == ['Visible Owner']
            assert members[other_scope.id]['people_names'] == []

    def test_merge_keeps_edwin_and_unions_yoko_phones(self, app):
        from app.models.contact_phone import ContactPhone
        from app.models.property_contact import PropertyContact
        from app.services.contact_service import ContactService
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='1110 Yoko Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
                owner_2_first_name='Edwin',
                owner_2_last_name='Chen',
            )
            loser = Lead(
                property_street='1110 Yoko Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
            )
            db.session.add_all([winner, loser])
            db.session.commit()

            service = ContactService()
            yoko_winner = service.create_contact({
                'first_name': 'Yoko',
                'last_name': 'Miller',
                'phones': [{'value': '7735551111', 'label': 'mobile'}],
                'emails': [{'value': 'yoko@example.com', 'label': 'personal'}],
            })
            edwin = service.create_contact({
                'first_name': 'Edwin',
                'last_name': 'Chen',
                'phones': [{'value': '3125552222', 'label': 'mobile'}],
            })
            yoko_loser = service.create_contact({
                'first_name': 'Yoko',
                'last_name': 'Miller',
                'phones': [{'value': '8475553333', 'label': 'home'}],
            })
            service.link_contact_to_property(
                winner.id, yoko_winner.id, role='owner', is_primary=True,
            )
            service.link_contact_to_property(
                winner.id, edwin.id, role='owner', is_primary=False,
            )
            service.link_contact_to_property(
                loser.id, yoko_loser.id, role='owner', is_primary=True,
            )
            db.session.commit()
            loser_id = loser.id

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ):
                merge_lead_into_winner(winner, loser, changed_by='test')
                db.session.commit()

            assert Lead.query.get(loser_id) is None
            owners = PropertyContact.query.filter_by(
                property_id=winner.id, role='owner',
            ).all()
            assert len(owners) == 2
            names = set()
            yoko_phones: set[str] = set()
            yoko_emails: set[str] = set()
            for link in owners:
                contact = db.session.get(Contact, link.contact_id)
                names.add(f'{contact.first_name} {contact.last_name}'.strip())
                if (contact.first_name or '').strip().lower() == 'yoko':
                    yoko_phones = {
                        p.value for p in ContactPhone.query.filter_by(
                            contact_id=contact.id,
                        ).all()
                    }
                    yoko_emails = {e.value for e in (contact.emails or [])}
            assert 'Yoko Miller' in names
            assert 'Edwin Chen' in names
            digits = {''.join(c for c in v if c.isdigit())[-10:] for v in yoko_phones}
            assert '7735551111' in digits
            assert '8475553333' in digits
            assert 'yoko@example.com' in {e.lower() for e in yoko_emails}

    def test_merge_splits_joint_edwin_and_yoyko_into_two_owners(self, app):
        """Loser jammed 'Edwin and Yoyko' must become two people on the winner."""
        from app.models.property_contact import PropertyContact
        from app.services.contact_service import ContactService
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='915 W Lawrence Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
            )
            loser = Lead(
                property_street='915 W Lawrence Ave',
                owner_first_name='Edwin and Yoyko',
                owner_last_name='Miller',
            )
            db.session.add_all([winner, loser])
            db.session.commit()

            service = ContactService()
            yoko = service.create_contact({
                'first_name': 'Yoko',
                'last_name': 'Miller',
            })
            service.link_contact_to_property(
                winner.id, yoko.id, role='owner', is_primary=True,
            )
            db.session.commit()
            loser_id = loser.id

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ):
                merge_lead_into_winner(winner, loser, changed_by='test')
                db.session.commit()

            assert Lead.query.get(loser_id) is None
            refreshed = db.session.get(Lead, winner.id)
            assert (refreshed.owner_2_first_name or '').strip().lower() == 'edwin'
            assert (refreshed.owner_2_last_name or '').strip().lower() == 'miller'
            owners = PropertyContact.query.filter_by(
                property_id=winner.id, role='owner',
            ).all()
            names = set()
            for link in owners:
                contact = db.session.get(Contact, link.contact_id)
                names.add(f'{contact.first_name} {contact.last_name}'.strip())
            assert len(owners) == 2
            assert {n.lower().strip() for n in names} == {
                'yoko miller',
                'edwin miller',
            }

    def test_merge_preserves_distinct_third_repointed_owner_contact(self, app):
        """A loser owner contact must stay active even when both flat slots are full."""
        from app.models.property_contact import PropertyContact
        from app.services.contact_service import ContactService
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='500 Three Owner Ave',
                owner_first_name='Alice',
                owner_last_name='Smith',
                owner_2_first_name='Bob',
                owner_2_last_name='Smith',
            )
            loser = Lead(
                property_street='500 Three Owner Ave',
                owner_first_name='Carol',
                owner_last_name='Smith',
            )
            db.session.add_all([winner, loser])
            db.session.commit()

            service = ContactService()
            alice = service.create_contact({'first_name': 'Alice', 'last_name': 'Smith'})
            bob = service.create_contact({'first_name': 'Bob', 'last_name': 'Smith'})
            carol = service.create_contact({'first_name': 'Carol', 'last_name': 'Smith'})
            service.link_contact_to_property(
                winner.id, alice.id, role='owner', is_primary=True,
            )
            service.link_contact_to_property(
                winner.id, bob.id, role='owner', is_primary=False,
            )
            service.link_contact_to_property(
                loser.id, carol.id, role='owner', is_primary=True,
            )
            db.session.commit()
            loser_id = loser.id

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ):
                merge_lead_into_winner(winner, loser, changed_by='test')
                db.session.commit()

            assert Lead.query.get(loser_id) is None
            owners = PropertyContact.query.filter_by(
                property_id=winner.id, role='owner',
            ).all()
            names = {
                f'{db.session.get(Contact, link.contact_id).first_name} '
                f'{db.session.get(Contact, link.contact_id).last_name}'.strip()
                for link in owners
            }
            assert names == {'Alice Smith', 'Bob Smith', 'Carol Smith'}

    def test_merge_choices_prune_unselected_people_and_methods(self, app):
        from app.models.contact_email import ContactEmail
        from app.models.contact_phone import ContactPhone
        from app.models.property_contact import PropertyContact
        from app.services.contact_service import ContactService
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='1110 Choice Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
                owner_2_first_name='Edwin',
                owner_2_last_name='Chen',
                phone_1='7735551111',
                phone_2='3125552222',
                email_1='yoko@example.com',
            )
            loser = Lead(
                property_street='1110 Choice Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
                phone_1='8475553333',
                email_1='old@example.com',
            )
            db.session.add_all([winner, loser])
            db.session.commit()

            service = ContactService()
            yoko_winner = service.create_contact({
                'first_name': 'Yoko',
                'last_name': 'Miller',
                'phones': [{'value': '7735551111', 'label': 'mobile'}],
                'emails': [{'value': 'yoko@example.com', 'label': 'personal'}],
            })
            edwin = service.create_contact({
                'first_name': 'Edwin',
                'last_name': 'Chen',
                'phones': [{'value': '3125552222', 'label': 'mobile'}],
            })
            yoko_loser = service.create_contact({
                'first_name': 'Yoko',
                'last_name': 'Miller',
                'phones': [{'value': '8475553333', 'label': 'home'}],
                'emails': [{'value': 'old@example.com', 'label': 'personal'}],
            })
            service.link_contact_to_property(winner.id, yoko_winner.id, role='owner', is_primary=True)
            service.link_contact_to_property(winner.id, edwin.id, role='owner', is_primary=False)
            service.link_contact_to_property(loser.id, yoko_loser.id, role='owner', is_primary=True)
            db.session.commit()

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ):
                merge_lead_into_winner(
                    winner,
                    loser,
                    changed_by='test',
                    choices={
                        'people_names': ['Yoko Miller'],
                        'phones': ['7735551111'],
                        'emails': ['yoko@example.com'],
                        'keep_primary_people': True,
                        'keep_incoming_people': True,
                    },
                )
                db.session.commit()

            db.session.refresh(winner)
            assert winner.owner_first_name == 'Yoko'
            assert winner.owner_last_name == 'Miller'
            assert winner.owner_2_first_name is None
            assert winner.owner_2_last_name is None
            assert winner.phone_1 == '7735551111'
            assert winner.phone_2 is None
            assert winner.email_1 == 'yoko@example.com'
            assert winner.email_2 is None

            owners = PropertyContact.query.filter_by(
                property_id=winner.id, role='owner',
            ).all()
            assert len(owners) == 1
            kept_contact = db.session.get(Contact, owners[0].contact_id)
            assert f'{kept_contact.first_name} {kept_contact.last_name}' == 'Yoko Miller'
            phones = {
                phone.value
                for phone in ContactPhone.query.filter_by(contact_id=kept_contact.id).all()
            }
            emails = {
                email.value
                for email in ContactEmail.query.filter_by(contact_id=kept_contact.id).all()
            }
            assert phones == {'7735551111'}
            assert emails == {'yoko@example.com'}

    def test_merge_choices_empty_people_clears_owner_contacts(self, app):
        from app.models.property_contact import PropertyContact
        from app.services.contact_service import ContactService
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='1111 Empty Choice Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
            )
            loser = Lead(
                property_street='1111 Empty Choice Ave',
                owner_first_name='Edwin',
                owner_last_name='Chen',
            )
            db.session.add_all([winner, loser])
            db.session.commit()
            service = ContactService()
            yoko = service.create_contact({'first_name': 'Yoko', 'last_name': 'Miller'})
            edwin = service.create_contact({'first_name': 'Edwin', 'last_name': 'Chen'})
            service.link_contact_to_property(winner.id, yoko.id, role='owner', is_primary=True)
            service.link_contact_to_property(loser.id, edwin.id, role='owner', is_primary=True)
            db.session.commit()

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ):
                merge_lead_into_winner(
                    winner,
                    loser,
                    changed_by='test',
                    choices={
                        'people_names': [],
                        'phones': [],
                        'emails': [],
                        'keep_primary_people': True,
                        'keep_incoming_people': False,
                    },
                )
                db.session.commit()

            db.session.refresh(winner)
            assert winner.owner_first_name is None
            assert winner.owner_last_name is None
            assert PropertyContact.query.filter_by(property_id=winner.id, role='owner').count() == 0

    def test_merge_choices_preserve_selected_contact_with_extra_whitespace(self, app):
        from app.models.property_contact import PropertyContact
        from app.services.contact_service import ContactService
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='1112 Whitespace Choice Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
            )
            loser = Lead(
                property_street='1112 Whitespace Choice Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
            )
            db.session.add_all([winner, loser])
            db.session.commit()
            service = ContactService()
            yoko = service.create_contact({
                'first_name': 'Yoko   Marie',
                'last_name': 'Miller',
            })
            service.link_contact_to_property(winner.id, yoko.id, role='owner', is_primary=True)
            db.session.commit()

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ):
                merge_lead_into_winner(
                    winner,
                    loser,
                    changed_by='test',
                    choices={
                        'people_names': ['Yoko Marie Miller'],
                        'keep_primary_people': True,
                        'keep_incoming_people': False,
                    },
                )
                db.session.commit()

            owner_links = PropertyContact.query.filter_by(property_id=winner.id, role='owner').all()
            assert any(link.contact_id == yoko.id for link in owner_links)

    def test_merge_choices_clone_shared_contact_before_method_pruning(self, app):
        from app.models.contact_phone import ContactPhone
        from app.models.property_contact import PropertyContact
        from app.services.contact_service import ContactService
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='1113 Shared Contact Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
                phone_1='7735551111',
            )
            loser = Lead(
                property_street='1113 Shared Contact Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
            )
            other_property = Lead(
                property_street='999 Other Shared Contact Ave',
                owner_first_name='Yoko',
                owner_last_name='Miller',
            )
            db.session.add_all([winner, loser, other_property])
            db.session.commit()
            service = ContactService()
            shared = service.create_contact({
                'first_name': 'Yoko',
                'last_name': 'Miller',
                'phones': [
                    {'value': '7735551111', 'label': 'mobile'},
                    {'value': '9995559999', 'label': 'home'},
                ],
            })
            service.link_contact_to_property(winner.id, shared.id, role='owner', is_primary=True)
            service.link_contact_to_property(other_property.id, shared.id, role='owner', is_primary=True)
            db.session.commit()

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ):
                merge_lead_into_winner(
                    winner,
                    loser,
                    changed_by='test',
                    choices={
                        'people_names': ['Yoko Miller'],
                        'phones': ['7735551111'],
                        'emails': [],
                        'keep_primary_people': True,
                        'keep_incoming_people': False,
                    },
                )
                db.session.commit()

            winner_link = PropertyContact.query.filter_by(
                property_id=winner.id,
                role='owner',
            ).one()
            other_link = PropertyContact.query.filter_by(
                property_id=other_property.id,
                role='owner',
            ).one()
            assert winner_link.contact_id != shared.id
            assert other_link.contact_id == shared.id
            winner_phones = {
                phone.value
                for phone in ContactPhone.query.filter_by(contact_id=winner_link.contact_id).all()
            }
            shared_phones = {
                phone.value
                for phone in ContactPhone.query.filter_by(contact_id=shared.id).all()
            }
            assert winner_phones == {'7735551111'}
            assert shared_phones == {'7735551111', '9995559999'}

    def test_merge_choice_street_collision_is_skipped(self, app):
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='10 Choice St',
                owner_first_name='Ada',
                owner_last_name='Lovelace',
                owner_user_id='merge-owner',
            )
            loser = Lead(
                property_street='10 Choice St 2',
                owner_first_name='Ada',
                owner_last_name='Lovelace',
                owner_user_id='merge-owner',
            )
            existing = Lead(
                property_street='99 Conflict St',
                owner_first_name='Ada',
                owner_last_name='Lovelace',
                owner_user_id='merge-owner',
            )
            db.session.add_all([winner, loser, existing])
            db.session.commit()
            for lead in (winner, loser, existing):
                refresh_lead_dedup_fields(lead)
            db.session.commit()

            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ):
                merge_lead_into_winner(
                    winner,
                    loser,
                    changed_by='test',
                    choices={'property_street': '99 Conflict St'},
                )
                db.session.commit()

            db.session.refresh(winner)
            assert winner.property_street != '99 Conflict St'
            assert winner.normalized_street != existing.normalized_street

    def test_merge_rejects_different_condo_units(self, app):
        from app.services.lead_dedup_service import merge_loser_into_winner

        with app.app_context():
            winner = Lead(property_street='1 Oak Brook Club Dr Unit A-30')
            loser = Lead(property_street='1 Oak Brook Club Dr Unit A-206')
            db.session.add_all([winner, loser])
            db.session.commit()
            try:
                merge_loser_into_winner(winner.id, loser.id, changed_by='test', commit=False)
                assert False, 'expected different-unit merge to fail'
            except ValueError as exc:
                assert 'address' in str(exc).lower() or 'unit' in str(exc).lower()

    def test_merge_allows_bare_building_vs_unit(self, app):
        from app.services.lead_dedup_service import merge_loser_into_winner

        with app.app_context():
            winner = Lead(property_street='1 Oak Brook Club Dr Unit A-30')
            loser = Lead(property_street='1 Oak Brook Club Dr')
            db.session.add_all([winner, loser])
            db.session.commit()
            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ), patch(
                'app.services.lead_refresh.refresh_lead_scoring',
            ):
                result = merge_loser_into_winner(
                    winner.id, loser.id, changed_by='test', commit=False,
                )
            assert result['merged'] is True

    def test_merge_skips_category_copy_when_winner_locked(self, app):
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            winner = Lead(
                property_street='1110 Yoko Ave',
                lead_category='residential',
                lead_category_locked=True,
                property_type=None,
            )
            loser = Lead(
                property_street='1110 Yoko Ave',
                lead_category='commercial',
                property_type='Commercial',
            )
            db.session.add_all([winner, loser])
            db.session.commit()
            with patch(
                'app.services.property_address_service.ensure_lead_property_address_complete',
            ):
                merge_lead_into_winner(winner, loser, changed_by='test')
                db.session.commit()
            refreshed = db.session.get(Lead, winner.id)
            assert refreshed.lead_category == 'residential'
            assert refreshed.property_type is None
            assert refreshed.lead_category_locked is True


def _install_prod_dedup_indexes() -> None:
    """The partial owner+street and owner+PIN indexes exist on Postgres, not create_all."""
    from sqlalchemy import text

    db.session.execute(text(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_leads_owner_normalized_street
        ON leads (
            owner_user_id,
            lower(trim(owner_first_name)),
            lower(trim(owner_last_name)),
            normalized_street
        )
        WHERE owner_user_id IS NOT NULL
          AND owner_first_name IS NOT NULL AND owner_first_name != ''
          AND owner_last_name IS NOT NULL AND owner_last_name != ''
          AND normalized_street IS NOT NULL AND normalized_street != ''
        """
    ))
    db.session.execute(text(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_leads_owner_assessor_pin
        ON leads (owner_user_id, county_assessor_pin)
        WHERE owner_user_id IS NOT NULL
          AND county_assessor_pin IS NOT NULL AND county_assessor_pin != ''
        """
    ))
    db.session.commit()


def _drop_prod_dedup_indexes() -> None:
    from sqlalchemy import text

    db.session.execute(text('DROP INDEX IF EXISTS uq_leads_owner_assessor_pin'))
    db.session.execute(text('DROP INDEX IF EXISTS uq_leads_owner_normalized_street'))
    db.session.commit()


class TestMergeUnderDedupUniqueIndexes:
    def test_combine_copies_pin_while_loser_row_still_exists(self, app):
        """Different people, same owner account: copying the PIN must not 500."""
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            _install_prod_dedup_indexes()
            try:
                winner = Lead(
                    property_street='10 Same St',
                    owner_first_name='Ada',
                    owner_last_name='Lovelace',
                    owner_user_id='owner-1',
                )
                loser = Lead(
                    property_street='10 Same St',
                    county_assessor_pin='13262220410000',
                    owner_first_name='Grace',
                    owner_last_name='Hopper',
                    owner_user_id='owner-1',
                )
                db.session.add_all([winner, loser])
                db.session.commit()
                for lead in (winner, loser):
                    refresh_lead_dedup_fields(lead)
                db.session.commit()

                with patch(
                    'app.services.property_address_service.ensure_lead_property_address_complete',
                ):
                    merge_lead_into_winner(winner, loser, changed_by='test')
                    db.session.commit()

                refreshed = db.session.get(Lead, winner.id)
                assert db.session.get(Lead, loser.id) is None
                assert refreshed.county_assessor_pin == '13262220410000'
            finally:
                db.session.rollback()
                _drop_prod_dedup_indexes()

    def test_combine_can_align_street_for_the_same_owner(self, app):
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            _install_prod_dedup_indexes()
            try:
                winner = Lead(
                    property_street='2834 N Drake',
                    owner_first_name='Francisco',
                    owner_last_name='R Solis',
                    owner_user_id='owner-1',
                )
                loser = Lead(
                    property_street='2834 N Drake Rear',
                    owner_first_name='Francisco',
                    owner_last_name='R Solis',
                    owner_user_id='owner-1',
                )
                db.session.add_all([winner, loser])
                db.session.commit()
                for lead in (winner, loser):
                    refresh_lead_dedup_fields(lead)
                db.session.commit()

                with patch(
                    'app.services.property_address_service.ensure_lead_property_address_complete',
                ):
                    merge_lead_into_winner(winner, loser, changed_by='test')
                    db.session.commit()

                refreshed = db.session.get(Lead, winner.id)
                assert refreshed.property_street == '2834 N Drake Rear'
                assert db.session.get(Lead, loser.id) is None
            finally:
                db.session.rollback()
                _drop_prod_dedup_indexes()

    def test_combine_can_take_the_other_persons_name(self, app):
        from app.services.lead_dedup_service import merge_lead_into_winner

        with app.app_context():
            _install_prod_dedup_indexes()
            try:
                winner = Lead(
                    property_street='10 Same St',
                    owner_first_name='Ada',
                    owner_last_name='Lovelace',
                    owner_user_id='owner-1',
                )
                loser = Lead(
                    property_street='10 Same St',
                    owner_first_name='Grace',
                    owner_last_name='Hopper',
                    owner_user_id='owner-1',
                )
                db.session.add_all([winner, loser])
                db.session.commit()
                for lead in (winner, loser):
                    refresh_lead_dedup_fields(lead)
                db.session.commit()

                with patch(
                    'app.services.property_address_service.ensure_lead_property_address_complete',
                ):
                    merge_lead_into_winner(
                        winner,
                        loser,
                        changed_by='test',
                        choices={
                            'people_names': ['Grace Hopper'],
                            'property_street': '10 Same St',
                        },
                    )
                    db.session.commit()

                refreshed = db.session.get(Lead, winner.id)
                assert refreshed.owner_first_name == 'Grace'
                assert refreshed.owner_last_name == 'Hopper'
                assert db.session.get(Lead, loser.id) is None
            finally:
                db.session.rollback()
                _drop_prod_dedup_indexes()
