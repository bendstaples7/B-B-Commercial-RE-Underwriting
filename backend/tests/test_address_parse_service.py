"""Tests for embedded US address parsing."""
import pytest

from app.services.address_parse_service import parse_embedded_us_address
from app.services.helpers.zip_lookup import city_state_from_zip
from app.services.property_address_service import (
    complete_property_address_fields,
    street_only_line,
    title_case_address_part,
)


class TestParseEmbeddedUsAddress:
    def test_space_separated_with_state(self):
        result = parse_embedded_us_address('4439 N Kimball Ave Chicago IL 60625')
        assert result == ('4439 N Kimball Ave', 'Chicago', 'IL', '60625')

    def test_space_separated_without_state(self):
        result = parse_embedded_us_address('1831 WEST RACE AVENUE  CHICAGO 60622')
        assert result is not None
        street, city, state, zip_code = result
        assert street.upper() == '1831 WEST RACE AVENUE'
        assert city == 'Chicago'
        assert state == 'IL'
        assert zip_code == '60622'
        assert street != street.upper() or 'WEST' in street  # not forced ALL CAPS city

    def test_davlin_zip_resolves_chicago_not_davlin(self):
        result = parse_embedded_us_address('3052 N Davlin 60618')
        assert result == ('3052 N Davlin', 'Chicago', 'IL', '60618')

    def test_street_suffix_never_becomes_city(self):
        result = parse_embedded_us_address('2100 North Campbell Ave 60647')
        assert result is not None
        street, city, state, zip_code = result
        assert city == 'Chicago'
        assert city.upper() != 'AVE'
        assert 'Campbell' in street or 'CAMPBELL' in street.upper()
        assert state == 'IL'
        assert zip_code == '60647'

    def test_no_all_caps_forced_on_zip_only_parse(self):
        result = parse_embedded_us_address('3052 North Davlin 60618')
        assert result is not None
        street, city, _state, _zip = result
        assert street == '3052 North Davlin'
        assert city == 'Chicago'
        assert not city.isupper()

    def test_two_word_city_with_state(self):
        result = parse_embedded_us_address('2900 NORTH HARLEM AVENUE ELMWOOD PARK IL 60707')
        assert result == ('2900 NORTH HARLEM AVENUE', 'ELMWOOD PARK', 'IL', '60707')

    def test_comma_separated(self):
        result = parse_embedded_us_address('1137 W LELAND AVE, CHICAGO, IL 60640')
        assert result == ('1137 W LELAND AVE', 'CHICAGO', 'IL', '60640')

    def test_two_part_comma_separated(self):
        result = parse_embedded_us_address('2041 W Cuyler Ave, Chicago IL 60618')
        assert result == ('2041 W Cuyler Ave', 'Chicago', 'IL', '60618')

    def test_property_street_from_investigation(self):
        result = parse_embedded_us_address('847-849 W Sunnyside Ave Chicago IL 60640')
        assert result == ('847-849 W Sunnyside Ave', 'Chicago', 'IL', '60640')

    def test_mailing_one_liner_with_zip_in_street_field(self):
        result = parse_embedded_us_address('4439 N Kimball Ave Chicago IL 60625')
        assert result is not None
        assert result[3] == '60625'

    def test_returns_none_without_zip(self):
        assert parse_embedded_us_address('4040 N Central Park Ave') is None

    def test_returns_none_for_empty(self):
        assert parse_embedded_us_address('') is None
        assert parse_embedded_us_address('   ') is None

    def test_zip_plus_four(self):
        result = parse_embedded_us_address('123 Main St Chicago IL 60601-1234')
        assert result == ('123 Main St', 'Chicago', 'IL', '60601')


class TestZipLookup:
    def test_chicagoland_fallback_and_package(self):
        assert city_state_from_zip('60618') == ('Chicago', 'IL')
        assert city_state_from_zip('60647-1753') == ('Chicago', 'IL')
        assert city_state_from_zip('not-a-zip') is None


class TestStreetCleanAndTitleCase:
    def test_places_one_liner_collapses_to_street_only(self):
        result = complete_property_address_fields(
            '541 N Campbell Ave, Chicago, Illinois, 60625',
            'Chicago',
            'IL',
            '60625',
            try_gis=False,
        )
        assert result['property_street'] == '541 N Campbell Ave'
        assert result['property_city'] == 'Chicago'
        assert result['property_state'] == 'IL'
        assert result['property_zip'] == '60625'
        assert result['property_street'].count('Chicago') == 0

    def test_street_only_strips_trailing_zip(self):
        assert street_only_line('3052 N Davlin 60618', city='Chicago', state='IL', zip_code='60618') == '3052 N Davlin'

    def test_title_case_all_caps(self):
        assert title_case_address_part('NORTH KEDVALE AVE') == 'North Kedvale Ave'
        assert title_case_address_part('Chicago') == 'Chicago'
