"""Unit marker detection — include letter+digit condo doors like L2."""
from app.services.helpers.unit_detector import has_unit_marker
from app.services.lead_merge_utils import situs_unit_token_from_parts


def test_has_unit_marker_letter_digit_condo_door():
    assert has_unit_marker('717 West Bittersweet Place L2') is True
    assert has_unit_marker('717 W Bittersweet Pl Unit L2') is True


def test_has_unit_marker_digit_letter():
    assert has_unit_marker('2553 N Drake Ave 1A') is True


def test_has_unit_marker_building_only():
    assert has_unit_marker('717 West Bittersweet Place') is False


def test_has_unit_marker_reads_address_2():
    assert has_unit_marker('717 W Bittersweet Pl', 'Unit L2') is True
    assert has_unit_marker('717 W Bittersweet Pl', None) is False


def test_situs_unit_token_from_parts_prefers_street_then_line2():
    assert situs_unit_token_from_parts('717 W Bittersweet Pl Unit L2', None) == 'l2'
    assert situs_unit_token_from_parts('717 W Bittersweet Pl', 'Unit L2') == 'l2'
    assert situs_unit_token_from_parts('717 W Bittersweet Pl', 'Apt 3') == '3'
    assert situs_unit_token_from_parts('717 W Bittersweet Pl', None) == ''
