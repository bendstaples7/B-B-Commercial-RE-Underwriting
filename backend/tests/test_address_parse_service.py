"""Tests for embedded US address parsing."""
import pytest

from app.services.address_parse_service import parse_embedded_us_address


class TestParseEmbeddedUsAddress:
    def test_space_separated_with_state(self):
        result = parse_embedded_us_address('4439 N Kimball Ave Chicago IL 60625')
        assert result == ('4439 N Kimball Ave', 'Chicago', 'IL', '60625')

    def test_space_separated_without_state(self):
        result = parse_embedded_us_address('1831 WEST RACE AVENUE  CHICAGO 60622')
        assert result == ('1831 WEST RACE AVENUE', 'CHICAGO', 'IL', '60622')

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
