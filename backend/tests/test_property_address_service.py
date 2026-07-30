"""Tests for property address completeness."""
from datetime import date
from unittest.mock import patch

import pytest

from app.models.lead import Lead
from app.services.property_address_service import (
    apply_parcel_address_to_lead,
    clear_geocode_circuit,
    complete_property_address,
    complete_property_address_fields,
    display_street,
    heal_incomplete_property_addresses,
    is_property_address_complete,
    reset_geocode_run_budget,
    street_only_line,
)


@pytest.fixture(autouse=True)
def _reset_geocode_stopgap():
    """Geocode budget/circuit are process-global — isolate every test."""
    clear_geocode_circuit()
    reset_geocode_run_budget()
    yield
    clear_geocode_circuit()
    reset_geocode_run_budget()


class TestStreetOnlyLine:
    """Street-only cleaner must strip embedded locality without eating suffixes."""

    def test_strips_glued_city_state_zip(self):
        assert (
            street_only_line('4414 N Campbell Ave Chicago IL 60625')
            == '4414 N Campbell Ave'
        )

    def test_strips_trailing_zip_only(self):
        assert street_only_line('3819 N Troy 60618') == '3819 N Troy'

    def test_strips_full_state_name(self):
        assert (
            street_only_line('2834 N Drake Ave Chicago Illinois 60618')
            == '2834 N Drake Ave'
        )

    def test_preserves_court_suffix(self):
        # "CT" is Court, not Connecticut — must never be stripped as a state.
        assert street_only_line('1369 OXFORD CT') == '1369 OXFORD CT'
        assert street_only_line('WAKE ROBIN CT') == 'WAKE ROBIN CT'
        assert street_only_line('309-D MILTON CT') == '309-D MILTON CT'

    def test_preserves_clean_street(self):
        assert street_only_line('500 W Madison St') == '500 W Madison St'

    def test_keeps_unit_before_locality(self):
        assert (
            street_only_line('2430 N Avers Ave 2 Chicago IL 60647')
            == '2430 N Avers Ave 2'
        )


class TestDisplayStreet:
    def test_display_street_cleans_dirty_one_liner(self):
        assert (
            display_street('3745 W Addison St 1 Chicago IL 60618')
            == '3745 W Addison St 1'
        )

    def test_display_street_preserves_clean_street(self):
        assert display_street('500 W Madison St') == '500 W Madison St'

    def test_display_zip_recovers_trailing_from_street(self):
        from app.services.property_address_service import display_zip

        assert display_zip('3745 W Addison St Chicago IL 60618', None) == '60618'
        assert display_zip('500 W Madison St', '60661') == '60661'


def _make_lead(app, **kwargs):
    from app import db

    defaults = dict(
        property_street='1239 N Hoyne',
        lead_status='mailing_no_contact_made',
        has_property_match=True,
        review_required=False,
    )
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


class TestCompletePropertyAddressFields:
    def test_already_complete_is_noop(self):
        result = complete_property_address_fields(
            '1239 N Hoyne Ave',
            'Chicago',
            'IL',
            '60622',
            try_gis=False,
        )
        assert result['complete'] is True
        assert result['property_city'] == 'Chicago'
        assert result['sources'] == []

    def test_full_state_name_maps_to_postal_code(self):
        result = complete_property_address_fields(
            '123 Peach St',
            'Atlanta',
            'Georgia',
            '30303',
            try_gis=False,
        )
        assert result['complete'] is True
        assert result['property_state'] == 'GA'

    def test_glued_one_liner_parse(self):
        result = complete_property_address_fields(
            '1239 N Hoyne Ave Chicago IL 60622',
            try_gis=False,
        )
        assert result['complete'] is True
        assert result['property_city'] == 'Chicago'
        assert result['property_state'] == 'IL'
        assert result['property_zip'] == '60622'
        assert 'parse_embedded' in result['sources'] or 'parse_places' in result['sources']

    def test_street_only_hoyne_gis_fill(self):
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
        ) as mock_lookup:
            mock_lookup.return_value = [{
                'pin': '17061270060000',
                'property_street': '1239 N HOYNE AVE',
                'property_city': 'CHICAGO',
                'property_state': 'IL',
                'property_zip': '60622-3009',
            }]
            result = complete_property_address_fields(
                '1239 N Hoyne',
                try_gis=True,
            )
        assert result['complete'] is True
        # GIS output is title-cased for human display (no ALL CAPS).
        assert result['property_city'] == 'Chicago'
        assert result['property_state'] == 'IL'
        assert result['property_zip'] == '60622'
        assert result['property_street'] == '1239 N Hoyne Ave'
        assert 'gis' in result['sources']

    def test_pin_fill_when_street_gis_misses(self):
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            return_value=[],
        ), patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_by_address',
            return_value=None,
        ), patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_address_by_pin',
        ) as mock_pin:
            mock_pin.return_value = {
                'property_street': '3111 W PALMER BLVD',
                'property_city': 'CHICAGO',
                'property_state': 'IL',
                'property_zip': '60647',
            }
            result = complete_property_address_fields(
                '3111 W Palmer Blvd',
                try_gis=True,
                county_assessor_pin='13361130320000',
            )
        assert result['complete'] is True
        assert result['property_city'] == 'Chicago'
        assert result['property_state'] == 'IL'
        assert result['property_zip'] == '60647'
        assert 'gis_pin' in result['sources']

    def test_pin_fill_does_not_overwrite_existing_city(self):
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            return_value=[],
        ), patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_by_address',
            return_value=None,
        ), patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_address_by_pin',
        ) as mock_pin:
            mock_pin.return_value = {
                'property_street': '3111 W PALMER BLVD',
                'property_city': 'CHICAGO',
                'property_state': 'IL',
                'property_zip': '60647',
            }
            result = complete_property_address_fields(
                '3111 W Palmer Blvd',
                'Oak Park',
                None,
                None,
                try_gis=True,
                county_assessor_pin='13361130320000',
            )
        assert result['property_city'] == 'Oak Park'
        assert result['property_state'] == 'IL'
        assert result['property_zip'] == '60647'
        assert 'gis_pin' in result['sources']

    def test_street_gis_preferred_before_pin(self):
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
        ) as mock_lookup, patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_address_by_pin',
        ) as mock_pin:
            mock_lookup.return_value = [{
                'pin': '13361130320000',
                'property_street': '3111 W PALMER BLVD',
                'property_city': 'CHICAGO',
                'property_state': 'IL',
                'property_zip': '60647',
            }]
            mock_pin.return_value = {
                'property_street': 'SHOULD NOT USE',
                'property_city': 'EVANSTON',
                'property_state': 'IL',
                'property_zip': '60201',
            }
            result = complete_property_address_fields(
                '3111 W Palmer',
                try_gis=True,
                county_assessor_pin='13361130320000',
            )
        assert result['property_city'] == 'Chicago'
        assert 'gis' in result['sources']
        assert 'gis_pin' not in result['sources']

    def test_suffix_retry_fills_foster_class_street(self):
        """Bare street without Ave — GIS hits on AVE candidate only."""
        def _lookup(addr: str):
            if addr.upper().endswith(' AVE'):
                return [{
                    'pin': '14081234560000',
                    'property_street': '1233 W FOSTER AVE',
                    'property_city': 'CHICAGO',
                    'property_state': 'IL',
                    'property_zip': '60640',
                }]
            return []

        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            side_effect=_lookup,
        ), patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_by_address',
            return_value=None,
        ):
            result = complete_property_address_fields(
                '1233 W Foster',
                'Chicago',
                'IL',
                None,
                try_gis=True,
                try_geocode=False,
            )
        assert result['complete'] is True
        assert result['property_zip'] == '60640'
        assert result['property_street'] == '1233 W Foster Ave'
        assert 'gis' in result['sources']

    def test_ambiguous_gis_zips_rejected(self):
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            return_value=[
                {
                    'pin': '1',
                    'property_street': '100 MAIN ST',
                    'property_city': 'CHICAGO',
                    'property_state': 'IL',
                    'property_zip': '60601',
                },
                {
                    'pin': '2',
                    'property_street': '100 MAIN ST',
                    'property_city': 'CHICAGO',
                    'property_state': 'IL',
                    'property_zip': '60602',
                },
            ],
        ), patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_by_address',
            return_value=None,
        ):
            result = complete_property_address_fields(
                '100 Main',
                'Chicago',
                'IL',
                None,
                try_gis=True,
                try_geocode=False,
            )
        assert result['complete'] is False
        assert result['property_zip'] is None

    def test_default_market_locality_when_gis_misses(self):
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            return_value=[],
        ), patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_by_address',
            return_value=None,
        ):
            result = complete_property_address_fields(
                '2834 N Drake Ave',
                try_gis=True,
                try_geocode=False,
            )
        assert result['complete'] is False
        assert result['property_city'] == 'Chicago'
        assert result['property_state'] == 'IL'
        assert 'default_market_locality' in result['sources']

    def test_apply_market_defaults_false_leaves_city_blank(self):
        """Pre-GIS create/merge must not invent Chicago (avoids live Cook routing)."""
        result = complete_property_address_fields(
            '2834 N Drake Ave',
            try_gis=False,
            try_geocode=False,
            apply_market_defaults=False,
        )
        assert result['property_city'] is None
        assert result['property_state'] is None
        assert 'default_market_locality' not in result['sources']

    def test_gis_suburban_city_not_stuck_as_chicago(self):
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            return_value=[{
                'pin': '16000000000000',
                'property_street': '123 MAIN ST',
                'property_city': 'OAK PARK',
                'property_state': 'IL',
                'property_zip': '60302',
            }],
        ):
            result = complete_property_address_fields(
                '123 Main',
                try_gis=True,
                try_geocode=False,
            )
        assert result['complete'] is True
        assert result['property_city'] == 'Oak Park'
        assert result['property_zip'] == '60302'
        assert 'default_market_locality' not in result['sources']
        assert 'gis' in result['sources']

    def test_gis_fills_chicago_without_needing_defaults(self):
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            return_value=[{
                'pin': '13262220410000',
                'property_street': '2834 N DRAKE AVE',
                'property_city': 'CHICAGO',
                'property_state': 'IL',
                'property_zip': '60618',
            }],
        ):
            result = complete_property_address_fields(
                '2834 N Drake Ave',
                try_gis=True,
                try_geocode=False,
            )
        assert result['complete'] is True
        assert result['property_city'] == 'Chicago'
        assert result['property_state'] == 'IL'
        assert result['property_zip'] == '60618'
        assert 'gis' in result['sources']
        assert 'default_market_locality' not in result['sources']

    def test_geocode_last_resort_when_gis_misses(self):
        from app.services.property_data_service import StructuredGeocodeOutcome

        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            return_value=[],
        ), patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_by_address',
            return_value=None,
        ), patch(
            'app.services.property_data_service.PropertyDataService'
            '.geocode_structured_address',
            return_value=StructuredGeocodeOutcome(
                address=None,
                status='SKIPPED_NO_KEY',
                billable=False,
            ),
        ), patch(
            'app.services.property_address_service._nominatim_structured_address',
        ) as mock_nom:
            mock_nom.return_value = {
                'property_street': '1233 W Foster Ave',
                'property_city': 'Chicago',
                'property_state': 'IL',
                'property_zip': '60640',
            }
            result = complete_property_address_fields(
                '1233 W Foster',
                'Chicago',
                'IL',
                None,
                try_gis=True,
                try_geocode=True,
            )
        assert result['complete'] is True
        assert result['property_zip'] == '60640'
        assert 'geocode' in result['sources']
        mock_nom.assert_called()

    def test_geocode_circuit_halts_on_over_query_limit(self):
        from app.services.property_address_service import (
            clear_geocode_circuit,
            get_geocode_circuit_status,
            reset_geocode_run_budget,
        )
        from app.services.property_data_service import StructuredGeocodeOutcome

        clear_geocode_circuit()
        reset_geocode_run_budget()
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            return_value=[],
        ), patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_by_address',
            return_value=None,
        ), patch(
            'app.services.property_data_service.PropertyDataService'
            '.geocode_structured_address',
            return_value=StructuredGeocodeOutcome(
                address=None,
                status='OVER_QUERY_LIMIT',
                error_message='You have exceeded your daily request quota',
                billable=True,
            ),
        ), patch(
            'app.services.property_address_service._increment_billable_month_count',
            return_value=1,
        ), patch(
            'app.services.property_address_service._billable_month_count',
            return_value=0,
        ), patch(
            'app.services.property_address_service._nominatim_structured_address',
        ) as mock_nom, patch(
            'app.services.property_address_service._persist_geocode_circuit',
        ):
            result = complete_property_address_fields(
                '1233 W Foster',
                'Chicago',
                'IL',
                None,
                try_gis=True,
                try_geocode=True,
            )
        assert result['complete'] is False
        mock_nom.assert_not_called()
        status = get_geocode_circuit_status()
        assert status['halt_all'] is True
        clear_geocode_circuit()
        reset_geocode_run_budget()

    def test_geocode_request_denied_still_allows_nominatim(self):
        from app.services.property_address_service import (
            clear_geocode_circuit,
            get_geocode_circuit_status,
            reset_geocode_run_budget,
        )
        from app.services.property_data_service import StructuredGeocodeOutcome

        clear_geocode_circuit()
        reset_geocode_run_budget()
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            return_value=[],
        ), patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_by_address',
            return_value=None,
        ), patch(
            'app.services.property_data_service.PropertyDataService'
            '.geocode_structured_address',
            return_value=StructuredGeocodeOutcome(
                address=None,
                status='REQUEST_DENIED',
                error_message='API keys with referer restrictions cannot be used',
                billable=False,
            ),
        ), patch(
            'app.services.property_address_service._increment_billable_month_count',
        ) as mock_incr, patch(
            'app.services.property_address_service._billable_month_count',
            return_value=0,
        ), patch(
            'app.services.property_address_service._nominatim_structured_address',
        ) as mock_nom, patch(
            'app.services.property_address_service._persist_geocode_circuit',
        ):
            mock_nom.return_value = {
                'property_street': '1233 W Foster Ave',
                'property_city': 'Chicago',
                'property_state': 'IL',
                'property_zip': '60640',
            }
            result = complete_property_address_fields(
                '1233 W Foster',
                'Chicago',
                'IL',
                None,
                try_gis=True,
                try_geocode=True,
            )
        assert result['complete'] is True
        assert result['property_zip'] == '60640'
        mock_nom.assert_called()
        mock_incr.assert_not_called()
        status = get_geocode_circuit_status()
        assert status['halt_all'] is False
        assert status['skip_google'] is True
        clear_geocode_circuit()
        reset_geocode_run_budget()

    def test_geocode_soft_cap_skips_google_allows_nominatim(self):
        from app.services.property_address_service import (
            clear_geocode_circuit,
            get_geocode_circuit_status,
            reset_geocode_run_budget,
        )

        clear_geocode_circuit()
        reset_geocode_run_budget()
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            return_value=[],
        ), patch(
            'app.services.gis.cook_county_gis_connector.CookCountyGISConnector'
            '.lookup_by_address',
            return_value=None,
        ), patch(
            'app.services.property_address_service._billable_month_count',
            return_value=9000,
        ), patch(
            'app.services.property_address_service._monthly_soft_cap',
            return_value=9000,
        ), patch(
            'app.services.property_data_service.PropertyDataService'
            '.geocode_structured_address',
        ) as mock_google, patch(
            'app.services.property_address_service._nominatim_structured_address',
        ) as mock_nom, patch(
            'app.services.property_address_service._persist_geocode_circuit',
        ):
            mock_nom.return_value = {
                'property_street': '1233 W Foster Ave',
                'property_city': 'Chicago',
                'property_state': 'IL',
                'property_zip': '60640',
            }
            result = complete_property_address_fields(
                '1233 W Foster',
                'Chicago',
                'IL',
                None,
                try_gis=True,
                try_geocode=True,
            )
        assert result['complete'] is True
        assert result['property_zip'] == '60640'
        mock_google.assert_not_called()
        mock_nom.assert_called()
        status = get_geocode_circuit_status()
        assert status['halt_all'] is False
        assert status['skip_google'] is True
        clear_geocode_circuit()
        reset_geocode_run_budget()

    def test_never_uses_mailing_fields(self):
        """Completer signature has no mailing args — regression guard."""
        import inspect
        params = inspect.signature(complete_property_address_fields).parameters
        assert 'mailing_zip' not in params
        assert 'mailing_address' not in params


class TestCompletePropertyAddressLead:
    def test_fills_lead_and_clears_review_when_complete(self, app):
        with app.app_context():
            from datetime import datetime, timezone

            from app import db
            from app.models.lead_timeline_entry import LeadTimelineEntry

            lead = _make_lead(app, review_required=True)
            # Review was set by the address completer (not HubSpot / other causes).
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='property_address_incomplete',
                occurred_at=datetime.now(timezone.utc),
                source='system',
                actor='test',
                summary='Property address incomplete',
                event_metadata={'reason': 'incomplete_address'},
            ))
            db.session.commit()
            with patch(
                'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            ) as mock_lookup:
                mock_lookup.return_value = [{
                    'pin': '17061270060000',
                    'property_street': '1239 N HOYNE AVE',
                    'property_city': 'Chicago',
                    'property_state': 'IL',
                    'property_zip': '60622',
                }]
                result = complete_property_address(
                    lead,
                    actor='test',
                    commit=True,
                )
            assert result['complete'] is True
            assert lead.property_city == 'Chicago'
            assert lead.property_zip == '60622'
            assert lead.review_required is False
            assert is_property_address_complete(lead=lead)

    def test_normalizes_dirty_street_on_complete_lead(self, app):
        # Complete row whose street still embeds the locality — the writer must
        # persist the street-only form so the UI stops rendering city/state twice.
        with app.app_context():
            lead = _make_lead(
                app,
                property_street='4414 N Campbell Ave Chicago IL 60625',
                property_city='Chicago',
                property_state='IL',
                property_zip='60625',
            )
            result = complete_property_address(
                lead,
                actor='test',
                commit=True,
                try_gis=False,
            )
            assert result['complete'] is True
            assert lead.property_street == '4414 N Campbell Ave'
            assert lead.property_city == 'Chicago'

    def test_flags_review_when_still_incomplete(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                property_street='Unknown Dirt Road',
                review_required=False,
            )
            with patch(
                'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
                return_value=[],
            ), patch(
                'app.services.gis.cook_county_gis_connector.CookCountyGISConnector.lookup_by_address',
                return_value=None,
            ):
                result = complete_property_address(
                    lead,
                    actor='test',
                    commit=True,
                    try_gis=True,
                )
            assert result['complete'] is False
            assert result['flagged_incomplete'] is True
            assert lead.review_required is True

    def test_apply_parcel_address_maps_full_state_name(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                property_city=None,
                property_state=None,
                property_zip=None,
            )

            changed = apply_parcel_address_to_lead(lead, {
                'property_city': 'Atlanta',
                'property_state': 'Georgia',
                'property_zip': '30303',
            })

            assert 'property_state' in changed
            assert lead.property_state == 'GA'


class TestHealIncompletePropertyAddresses:
    def test_zero_limit_still_includes_geocode_circuit(self, app):
        with app.app_context():
            result = heal_incomplete_property_addresses(
                last_id=0,
                limit=0,
                persist_cursor=False,
                commit=False,
                actor='test',
            )
            assert result['processed'] == 0
            assert 'geocode_circuit' in result
            assert isinstance(result['geocode_circuit'], dict)

    def test_heals_street_only_batch_and_advances_cursor(self, app):
        with app.app_context():
            incomplete = _make_lead(
                app,
                property_street='1239 N Hoyne',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            complete = _make_lead(
                app,
                property_street='500 W Madison St',
                property_city='Chicago',
                property_state='IL',
                property_zip='60661',
            )
            with patch(
                'app.services.property_address_service._heal_incomplete_cursor',
                return_value=0,
            ), patch(
                'app.services.property_address_service._set_heal_incomplete_cursor',
            ) as set_cursor, patch(
                'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            ) as mock_lookup:
                mock_lookup.return_value = [{
                    'pin': '17061270060000',
                    'property_street': '1239 N HOYNE AVE',
                    'property_city': 'Chicago',
                    'property_state': 'IL',
                    'property_zip': '60622',
                }]
                result = heal_incomplete_property_addresses(
                    last_id=0,
                    limit=50,
                    persist_cursor=True,
                    commit=True,
                    actor='test',
                )
            assert incomplete.id in result['lead_ids']
            assert complete.id not in result['lead_ids']
            assert result['completed'] >= 1
            assert is_property_address_complete(lead=incomplete)
            set_cursor.assert_called_once_with(incomplete.id)

    def test_dry_run_does_not_mutate(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                property_street='1239 N Hoyne Ave Chicago IL 60622',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            result = heal_incomplete_property_addresses(
                lead_id=lead.id,
                dry_run=True,
                persist_cursor=False,
                commit=False,
                try_gis=False,
            )
            assert result['processed'] == 1
            assert result['completed'] == 1
            assert lead.property_city is None

    def test_wraps_cursor_when_no_candidates_after_cursor(self, app):
        with app.app_context():
            with patch(
                'app.services.property_address_service._set_heal_incomplete_cursor',
            ) as set_cursor:
                result = heal_incomplete_property_addresses(
                    last_id=999999,
                    limit=10,
                    persist_cursor=True,
                    commit=False,
                    dry_run=True,
                    try_gis=False,
                )
            assert result['wrapped'] is True
            assert result['last_id'] == 0
            set_cursor.assert_called_with(0)

    def test_heal_includes_whitespace_only_address_parts(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                property_street='1239 N Hoyne',
                property_city='   ',
                property_state=' ',
                property_zip='',
            )
            with patch(
                'app.services.property_address_service._set_heal_incomplete_cursor',
            ), patch(
                'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            ) as mock_lookup:
                mock_lookup.return_value = [{
                    'pin': '17061270060000',
                    'property_street': '1239 N HOYNE AVE',
                    'property_city': 'Chicago',
                    'property_state': 'IL',
                    'property_zip': '60622',
                }]
                result = heal_incomplete_property_addresses(
                    last_id=0,
                    limit=10,
                    persist_cursor=True,
                    commit=True,
                    actor='test',
                )
            assert lead.id in result['lead_ids']
            assert is_property_address_complete(lead=lead)

    def test_heal_advances_cursor_past_hard_error(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                property_street='999 Error Only St',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            with patch(
                'app.services.property_address_service._heal_incomplete_cursor',
                return_value=0,
            ), patch(
                'app.services.property_address_service._set_heal_incomplete_cursor',
            ) as set_cursor, patch(
                'app.services.property_address_service.complete_property_address',
                side_effect=RuntimeError('gis down'),
            ):
                result = heal_incomplete_property_addresses(
                    last_id=0,
                    limit=10,
                    persist_cursor=True,
                    commit=True,
                    try_gis=True,
                    actor='test',
                )
            assert lead.id in result['lead_ids']
            assert result['errors'] >= 1
            assert result['last_id'] == lead.id
            set_cursor.assert_called_with(lead.id)

    def test_heal_advances_past_hard_error_and_continues_batch(self, app):
        with app.app_context():
            first = _make_lead(
                app,
                property_street='100 First St',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            failed = _make_lead(
                app,
                property_street='200 Failed St',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            later = _make_lead(
                app,
                property_street='300 Later St',
                property_city=None,
                property_state=None,
                property_zip=None,
            )

            def complete_or_fail(lead, **_kwargs):
                if lead.id == failed.id:
                    raise RuntimeError('gis down')
                lead.property_city = 'Chicago'
                lead.property_state = 'IL'
                lead.property_zip = '60601'
                return {'complete': True}

            with patch(
                'app.services.property_address_service._set_heal_incomplete_cursor',
            ) as set_cursor, patch(
                'app.services.property_address_service.complete_property_address',
                side_effect=complete_or_fail,
            ):
                result = heal_incomplete_property_addresses(
                    last_id=0,
                    limit=10,
                    persist_cursor=True,
                    commit=True,
                    try_gis=True,
                    actor='test',
                )

            assert result['lead_ids'] == [first.id, failed.id, later.id]
            assert result['errors'] == 1
            assert result['completed'] == 2
            assert result['last_id'] == later.id
            set_cursor.assert_called_with(later.id)
            assert later.property_city == 'Chicago'

    def test_heal_retries_locality_only_after_street_integrity_error(self, app):
        with app.app_context():
            twin = _make_lead(
                app,
                property_street='1116 W Wellington',
                property_city='Chicago',
                property_state='IL',
                property_zip='60657',
            )
            jammed = _make_lead(
                app,
                property_street='1116 W Wellington Chicago IL',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            # Same owner scope so unique street key can collide after clean.
            twin.owner_first_name = 'Jay'
            twin.owner_last_name = 'Hausler'
            jammed.owner_first_name = 'Jay'
            jammed.owner_last_name = 'Hausler'
            from app import db
            db.session.commit()

            calls = {'n': 0}

            def complete_side_effect(lead, **kwargs):
                calls['n'] += 1
                if not kwargs.get('preserve_street') and lead.id == jammed.id:
                    from sqlalchemy.exc import IntegrityError
                    raise IntegrityError('stmt', {}, Exception('uq'))
                lead.property_city = 'Chicago'
                lead.property_state = 'IL'
                lead.property_zip = '60657'
                if not kwargs.get('preserve_street'):
                    lead.property_street = '1116 W Wellington'
                return {'complete': True, 'changed_fields': ['property_city']}

            with patch(
                'app.services.property_address_service._set_heal_incomplete_cursor',
            ), patch(
                'app.services.property_address_service.complete_property_address',
                side_effect=complete_side_effect,
            ):
                result = heal_incomplete_property_addresses(
                    lead_id=jammed.id,
                    persist_cursor=False,
                    commit=True,
                    try_gis=False,
                    try_geocode=False,
                    actor='test',
                )

            assert result['errors'] == 0
            assert result['completed'] == 1
            assert calls['n'] >= 2
            assert jammed.property_city == 'Chicago'
            # Locality-only retry must not rewrite street into the twin's key.
            assert 'Chicago' in (jammed.property_street or '')

    def test_dry_run_includes_before_after_previews(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                property_street='1239 N Hoyne Ave Chicago IL 60622',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            result = heal_incomplete_property_addresses(
                lead_id=lead.id,
                dry_run=True,
                persist_cursor=False,
                commit=False,
                try_gis=False,
            )
            assert result['previews']
            preview = result['previews'][0]
            assert preview['lead_id'] == lead.id
            assert preview['complete'] is True
            assert preview['after']['property_city'] == 'Chicago'
            assert lead.property_city is None
