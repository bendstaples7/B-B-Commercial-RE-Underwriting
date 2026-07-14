"""Tests for GIS address parsing used by quick-add and connector routing."""
import pytest

from app.services.gis.routing import (
    parse_city_state_from_address,
    parse_city_state_zip_from_address,
)


class TestParseCityStateZipFromAddress:
    @pytest.mark.parametrize(
        'address,expected',
        [
            ('123 Main St, Chicago, IL', ('Chicago', 'IL', None)),
            ('123 Main St, Chicago, IL 60647', ('Chicago', 'IL', '60647')),
            ('123 Main St, Chicago, IL 60647, USA', ('Chicago', 'IL', '60647')),
            ('123 Main St, Chicago, IL 60647-1234, US', ('Chicago', 'IL', '60647-1234')),
            ('500 Oak Ave, Naperville, Illinois', ('Naperville', 'IL', None)),
            ('500 Oak Ave, Naperville, Illinois 60540', ('Naperville', 'IL', '60540')),
        ],
    )
    def test_parses_places_shapes(self, address, expected):
        assert parse_city_state_zip_from_address(address) == expected

    def test_city_state_helper_drops_zip(self):
        assert parse_city_state_from_address(
            '123 Main St, Chicago, IL 60647, USA'
        ) == ('Chicago', 'IL')

    @pytest.mark.parametrize(
        'address',
        [
            '',
            'Just a street',
            '123 Main St, Chicago, CA',
            '123 Main St, Chicago',
        ],
    )
    def test_returns_none_when_unparseable(self, address):
        assert parse_city_state_zip_from_address(address) == (None, None, None)
