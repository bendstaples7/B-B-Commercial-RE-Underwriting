"""
Unit tests for pro_forma_result_dc.py frozen dataclasses and to_canonical_dict().

Validates:
- Frozen immutability
- Decimal serialization via str() (not float)
- None handling
- Sorted keys for stable JSON output
- Nested dataclass recursion
- Tuple/list and dict serialization
"""

import json
from decimal import Decimal

import pytest

from app.services.multifamily.pro_forma_result_dc import (
    MonthlyRow,
    OpExBreakdown,
    ProFormaComputation,
    ProFormaSummary,
    SourcesAndUses,
    Valuation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_opex_breakdown() -> OpExBreakdown:
    return OpExBreakdown(
        property_taxes=Decimal("500.00"),
        insurance=Decimal("200.00"),
        utilities=Decimal("150.00"),
        repairs_and_maintenance=Decimal("100.00"),
        admin_and_marketing=Decimal("75.00"),
        payroll=Decimal("300.00"),
        other_opex=Decimal("50.00"),
        management_fee=Decimal("320.00"),
    )


def _make_monthly_row(month: int = 1) -> MonthlyRow:
    return MonthlyRow(
        month=month,
        gsr=Decimal("10000.00"),
        vacancy_loss=Decimal("500.00"),
        other_income=Decimal("200.00"),
        egi=Decimal("9700.00"),
        opex_breakdown=_make_opex_breakdown(),
        opex_total=Decimal("1695.00"),
        noi=Decimal("8005.00"),
        replacement_reserves=Decimal("104.17"),
        net_cash_flow=Decimal("7900.83"),
        debt_service_a=Decimal("3500.00"),
        debt_service_b=Decimal("2800.00"),
        cash_flow_after_debt_a=Decimal("4400.83"),
        cash_flow_after_debt_b=Decimal("5100.83"),
        capex_spend=Decimal("0.00"),
        cash_flow_after_capex_a=Decimal("4400.83"),
        cash_flow_after_capex_b=Decimal("5100.83"),
    )


def _make_summary() -> ProFormaSummary:
    return ProFormaSummary(
        in_place_noi=Decimal("96060.00"),
        stabilized_noi=Decimal("120000.00"),
        in_place_dscr_a=Decimal("2.287"),
        in_place_dscr_b=Decimal("2.859"),
        stabilized_dscr_a=Decimal("2.857"),
        stabilized_dscr_b=Decimal("3.571"),
        cash_on_cash_a=Decimal("0.1523"),
        cash_on_cash_b=Decimal("0.1890"),
    )


def _make_sources_and_uses() -> SourcesAndUses:
    return SourcesAndUses(
        purchase_price=Decimal("500000.00"),
        closing_costs=Decimal("15000.00"),
        rehab_budget_total=Decimal("100000.00"),
        loan_origination_fees=Decimal("4620.00"),
        funding_source_origination_fees=Decimal("1500.00"),
        interest_reserve=Decimal("10000.00"),
        loan_amount=Decimal("462000.00"),
        cash_draw=Decimal("100000.00"),
        heloc_1_draw=Decimal("50000.00"),
        heloc_2_draw=Decimal("19120.00"),
        total_uses=Decimal("631120.00"),
        total_sources=Decimal("631120.00"),
        initial_cash_investment=Decimal("169120.00"),
    )


def _make_valuation() -> Valuation:
    return Valuation(
        valuation_at_cap_rate_min=Decimal("2000000.00"),
        valuation_at_cap_rate_median=Decimal("1714285.71"),
        valuation_at_cap_rate_average=Decimal("1600000.00"),
        valuation_at_cap_rate_max=Decimal("1500000.00"),
        valuation_at_ppu_min=Decimal("750000.00"),
        valuation_at_ppu_median=Decimal("900000.00"),
        valuation_at_ppu_average=Decimal("850000.00"),
        valuation_at_ppu_max=Decimal("1100000.00"),
        valuation_at_custom_cap_rate=Decimal("1846153.85"),
        price_to_rent_ratio=Decimal("4.17"),
        warnings=[],
    )


# ---------------------------------------------------------------------------
# Tests: Frozen immutability
# ---------------------------------------------------------------------------


class TestFrozenImmutability:
    def test_opex_breakdown_is_frozen(self):
        obj = _make_opex_breakdown()
        with pytest.raises(AttributeError):
            obj.property_taxes = Decimal("999.99")  # type: ignore[misc]

    def test_monthly_row_is_frozen(self):
        obj = _make_monthly_row()
        with pytest.raises(AttributeError):
            obj.gsr = Decimal("999.99")  # type: ignore[misc]

    def test_pro_forma_summary_is_frozen(self):
        obj = _make_summary()
        with pytest.raises(AttributeError):
            obj.in_place_noi = Decimal("999.99")  # type: ignore[misc]

    def test_sources_and_uses_is_frozen(self):
        obj = _make_sources_and_uses()
        with pytest.raises(AttributeError):
            obj.loan_amount = Decimal("999.99")  # type: ignore[misc]

    def test_valuation_is_frozen(self):
        obj = _make_valuation()
        with pytest.raises(AttributeError):
            obj.price_to_rent_ratio = Decimal("999.99")  # type: ignore[misc]

    def test_pro_forma_computation_is_frozen(self):
        comp = ProFormaComputation(
            monthly_schedule=(_make_monthly_row(),),
            per_unit_schedule={"U1": (Decimal("1000.00"),)},
            summary=_make_summary(),
            sources_and_uses_a=_make_sources_and_uses(),
            sources_and_uses_b=None,
            valuation=_make_valuation(),
            missing_inputs_a=[],
            missing_inputs_b=["PRIMARY_LENDER_MISSING_B"],
            warnings=[],
        )
        with pytest.raises(AttributeError):
            comp.warnings = ["new"]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tests: to_canonical_dict() serialization
# ---------------------------------------------------------------------------


class TestCanonicalDict:
    def test_decimal_serialized_as_str(self):
        obj = _make_opex_breakdown()
        d = obj.to_canonical_dict()
        assert d["property_taxes"] == "500.00"
        assert isinstance(d["property_taxes"], str)

    def test_none_values_preserved(self):
        summary = ProFormaSummary(
            in_place_noi=None,
            stabilized_noi=None,
            in_place_dscr_a=None,
            in_place_dscr_b=None,
            stabilized_dscr_a=None,
            stabilized_dscr_b=None,
            cash_on_cash_a=None,
            cash_on_cash_b=None,
        )
        d = summary.to_canonical_dict()
        assert d["in_place_noi"] is None
        assert d["stabilized_noi"] is None

    def test_keys_are_sorted(self):
        obj = _make_opex_breakdown()
        d = obj.to_canonical_dict()
        keys = list(d.keys())
        assert keys == sorted(keys)

    def test_nested_dataclass_serialized_recursively(self):
        row = _make_monthly_row()
        d = row.to_canonical_dict()
        # opex_breakdown should be a dict, not an OpExBreakdown instance
        assert isinstance(d["opex_breakdown"], dict)
        assert d["opex_breakdown"]["property_taxes"] == "500.00"

    def test_tuple_serialized_as_list(self):
        comp = ProFormaComputation(
            monthly_schedule=(_make_monthly_row(1), _make_monthly_row(2)),
            per_unit_schedule={"U1": (Decimal("1000.00"), Decimal("1100.00"))},
            summary=_make_summary(),
            sources_and_uses_a=_make_sources_and_uses(),
            sources_and_uses_b=None,
            valuation=None,
            missing_inputs_a=[],
            missing_inputs_b=[],
            warnings=["test_warning"],
        )
        d = comp.to_canonical_dict()
        # monthly_schedule should be a list
        assert isinstance(d["monthly_schedule"], list)
        assert len(d["monthly_schedule"]) == 2
        # per_unit_schedule values should be lists of str
        assert d["per_unit_schedule"]["U1"] == ["1000.00", "1100.00"]

    def test_dict_keys_sorted(self):
        comp = ProFormaComputation(
            monthly_schedule=(),
            per_unit_schedule={
                "U3": (Decimal("900.00"),),
                "U1": (Decimal("1000.00"),),
                "U2": (Decimal("1100.00"),),
            },
            summary=_make_summary(),
            sources_and_uses_a=None,
            sources_and_uses_b=None,
            valuation=None,
            missing_inputs_a=[],
            missing_inputs_b=[],
            warnings=[],
        )
        d = comp.to_canonical_dict()
        per_unit_keys = list(d["per_unit_schedule"].keys())
        assert per_unit_keys == ["U1", "U2", "U3"]

    def test_none_sources_and_uses_serialized(self):
        comp = ProFormaComputation(
            monthly_schedule=(),
            per_unit_schedule={},
            summary=_make_summary(),
            sources_and_uses_a=None,
            sources_and_uses_b=None,
            valuation=None,
            missing_inputs_a=["PRIMARY_LENDER_MISSING_A"],
            missing_inputs_b=["PRIMARY_LENDER_MISSING_B"],
            warnings=[],
        )
        d = comp.to_canonical_dict()
        assert d["sources_and_uses_a"] is None
        assert d["sources_and_uses_b"] is None

    def test_warnings_list_serialized(self):
        val = Valuation(
            valuation_at_cap_rate_min=None,
            valuation_at_cap_rate_median=None,
            valuation_at_cap_rate_average=None,
            valuation_at_cap_rate_max=None,
            valuation_at_ppu_min=None,
            valuation_at_ppu_median=None,
            valuation_at_ppu_average=None,
            valuation_at_ppu_max=None,
            valuation_at_custom_cap_rate=None,
            price_to_rent_ratio=Decimal("4.17"),
            warnings=["Non_Positive_Stabilized_NOI"],
        )
        d = val.to_canonical_dict()
        assert d["warnings"] == ["Non_Positive_Stabilized_NOI"]

    def test_canonical_dict_is_json_serializable(self):
        """The output of to_canonical_dict() must be JSON-serializable."""
        comp = ProFormaComputation(
            monthly_schedule=(_make_monthly_row(1),),
            per_unit_schedule={"U1": (Decimal("1000.00"),)},
            summary=_make_summary(),
            sources_and_uses_a=_make_sources_and_uses(),
            sources_and_uses_b=None,
            valuation=_make_valuation(),
            missing_inputs_a=[],
            missing_inputs_b=["PRIMARY_LENDER_MISSING_B"],
            warnings=["test"],
        )
        d = comp.to_canonical_dict()
        # Should not raise
        json_str = json.dumps(d, sort_keys=True)
        assert isinstance(json_str, str)
        # Round-trip: parse back and verify structure
        parsed = json.loads(json_str)
        assert parsed["missing_inputs_b"] == ["PRIMARY_LENDER_MISSING_B"]

    def test_stable_json_output(self):
        """Two serializations of the same object produce identical JSON."""
        comp = ProFormaComputation(
            monthly_schedule=(_make_monthly_row(1),),
            per_unit_schedule={"U1": (Decimal("1000.00"),)},
            summary=_make_summary(),
            sources_and_uses_a=_make_sources_and_uses(),
            sources_and_uses_b=None,
            valuation=_make_valuation(),
            missing_inputs_a=[],
            missing_inputs_b=[],
            warnings=[],
        )
        json1 = json.dumps(comp.to_canonical_dict(), sort_keys=True)
        json2 = json.dumps(comp.to_canonical_dict(), sort_keys=True)
        assert json1 == json2
