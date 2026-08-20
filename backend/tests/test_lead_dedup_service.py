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

    def test_merge_rejects_bare_building_vs_unit(self, app):
        from app.services.lead_dedup_service import merge_loser_into_winner

        with app.app_context():
            winner = Lead(property_street='1 Oak Brook Club Dr')
            loser = Lead(property_street='1 Oak Brook Club Dr Unit A-30')
            db.session.add_all([winner, loser])
            db.session.commit()
            try:
                merge_loser_into_winner(winner.id, loser.id, changed_by='test', commit=False)
                assert False, 'expected bare↔unit merge to fail'
            except ValueError as exc:
                assert 'address' in str(exc).lower() or 'unit' in str(exc).lower()

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
