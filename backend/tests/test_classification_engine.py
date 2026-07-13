"""Unit tests for condo classification rules."""
from app.services.helpers.classification_engine import AddressGroupMetrics, classify


def _base(**overrides):
    data = dict(
        property_count=1,
        pin_count=1,
        owner_count=1,
        has_unit_number=False,
        has_condo_language=False,
        missing_pin_count=0,
        missing_owner_count=0,
        units=None,
        is_commercial=False,
    )
    data.update(overrides)
    return AddressGroupMetrics(**data)


class TestCommercialFewPinHeuristic:
    def test_commercial_two_pins_leans_not_condo(self):
        result = classify(
            _base(pin_count=2, owner_count=2, is_commercial=True, units=2),
        )
        assert result.condo_risk_status == "likely_not_condo"
        assert result.building_sale_possible == "yes"
        assert result.confidence == "medium"
        assert "rule_4b_commercial_few_pins" in result.triggered_rules

    def test_units_gte_5_two_pins_leans_not_condo(self):
        result = classify(
            _base(pin_count=2, owner_count=1, units=6, is_commercial=False),
        )
        assert result.condo_risk_status == "likely_not_condo"
        assert "rule_4b_commercial_few_pins" in result.triggered_rules

    def test_residential_two_pins_still_partial_or_review(self):
        result = classify(
            _base(pin_count=2, owner_count=1, units=2, is_commercial=False),
        )
        assert result.condo_risk_status == "partial_condo_possible"
        assert "rule_5_multiple_pins_single_owner" in result.triggered_rules

    def test_condo_language_still_wins(self):
        result = classify(
            _base(pin_count=2, owner_count=1, is_commercial=True, has_condo_language=True),
        )
        assert result.condo_risk_status == "likely_condo"
        assert "rule_2_condo_language" in result.triggered_rules
