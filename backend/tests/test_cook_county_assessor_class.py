"""Unit tests for Cook County assessor class condo mapping."""
from app.services.helpers.cook_county_assessor_class import assessor_class_to_condo_language


def test_commercial_condo_class_detected():
    assert assessor_class_to_condo_language('299') is True
    assert assessor_class_to_condo_language('202') is False
    assert assessor_class_to_condo_language(None) is False
