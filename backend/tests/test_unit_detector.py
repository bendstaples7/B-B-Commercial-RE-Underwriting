"""Unit marker detection — include letter+digit condo doors like L2."""
from app.services.helpers.unit_detector import has_unit_marker


def test_has_unit_marker_letter_digit_condo_door():
    assert has_unit_marker('717 West Bittersweet Place L2') is True
    assert has_unit_marker('717 W Bittersweet Pl Unit L2') is True


def test_has_unit_marker_digit_letter():
    assert has_unit_marker('2553 N Drake Ave 1A') is True


def test_has_unit_marker_building_only():
    assert has_unit_marker('717 West Bittersweet Place') is False
