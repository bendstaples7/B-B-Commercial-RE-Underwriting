"""
Unit tests for the multifamily pro forma engine.

Tests the pure function compute_pro_forma and its helpers:
- _amortizing_payment
- _scan_missing_inputs
- _scheduled_rent
- Full pipeline with complete and incomplete inputs
"""

from decimal import Decimal

import pytest

from app.services.multifamily.pro_forma_constants import (
    HORIZON_MONTHS,
    PRIMARY_LENDER_MISSING_A,
    PRIMARY_LENDER_MISSING_B,
    RENT_ROLL_INCOMPLETE,
    REHAB_PLAN_MISSING,
    OPEX_ASSUMPTIONS_MISSING,
    quantize_money,
)
from app.services.multifamily.pro_forma_engine import (
    _amortizing_payment,
    _scan_missing_inputs,
    _scheduled_rent,
    compute_pro_forma,
)
from app.services.multifamily.pro_forma_inputs import (
    DealInputs,
    DealSnapshot,
    FundingSourceSnapshot,
    LenderProfileSnapshot,
    LumpSumAtStart,
    MarketRentSnapshot,
    OpExAssumptions,
    RehabPlanSnapshot,
    RentRollSnapshot,
    ReserveAssumptions,
    UnitSnapshot,
)


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------

ZERO = Decimal("0")


def _make_deal(unit_count: int = 5) -> DealSnapshot:
    return DealSnapshot(
        deal_id=1,
        purchase_price=Decimal("500000.00"),
        closing_costs=Decimal("15000.00"),
        vacancy_rate=Decimal("0.05"),
        other_income_monthly=Decimal("200.00"),
        management_fee_rate=Decimal("0.08"),
        reserve_per_unit_per_year=Decimal("250.00"),
        interest_reserve_amount=Decimal("10000.00"),
        custom_cap_rate=None,
        unit_count=unit_count,
    )


def _make_units(count: int = 5) -> tuple[UnitSnapshot, ...]:
    return tuple(
        UnitSnapshot(
            unit_id=f"U{i}",
            unit_type="2BR",
            beds=2,
            baths=Decimal("1.0"),
            sqft=900,
            occupancy_status="Occupied",
        )
        for i in range(1, count + 1)
    )


def _make_rent_roll(count: int = 5, rent: Decimal = Decimal("1000.00")) -> tuple[RentRollSnapshot, ...]:
    return tuple(
        RentRollSnapshot(unit_id=f"U{i}", current_rent=rent)
        for i in range(1, count + 1)
    )


def _make_rehab_plan_no_reno(count: int = 5) -> tuple[RehabPlanSnapshot, ...]:
    return tuple(
        RehabPlanSnapshot(
            unit_id=f"U{i}",
            renovate_flag=False,
            current_rent=Decimal("1000.00"),
            underwritten_post_reno_rent=None,
            rehab_start_month=None,
            downtime_months=None,
            stabilized_month=None,
            rehab_budget=ZERO,
        )
        for i in range(1, count + 1)
    )


def _make_opex() -> OpExAssumptions:
    return OpExAssumptions(
        property_taxes_annual=Decimal("12000.00"),
        insurance_annual=Decimal("6000.00"),
        utilities_annual=Decimal("3600.00"),
        repairs_and_maintenance_annual=Decimal("2400.00"),
        admin_and_marketing_annual=Decimal("1800.00"),
        payroll_annual=Decimal("7200.00"),
        other_opex_annual=Decimal("1200.00"),
        management_fee_rate=Decimal("0.08"),
    )


def _make_reserves(unit_count: int = 5) -> ReserveAssumptions:
    return ReserveAssumptions(
        reserve_per_unit_per_year=Decimal("250.00"),
        unit_count=unit_count,
    )


def _make_lender_a() -> LenderProfileSnapshot:
    return LenderProfileSnapshot(
        lender_type="Construction_To_Perm",
        origination_fee_rate=Decimal("0.01"),
        ltv_total_cost=Decimal("0.75"),
        construction_rate=Decimal("0.07"),
        construction_io_months=12,
        perm_rate=Decimal("0.06"),
        perm_amort_years=30,
        max_purchase_ltv=None,
        all_in_rate=None,
        amort_years=None,
    )


def _make_lender_b() -> LenderProfileSnapshot:
    return LenderProfileSnapshot(
        lender_type="Self_Funded_Reno",
        origination_fee_rate=Decimal("0.01"),
        ltv_total_cost=None,
        construction_rate=None,
        construction_io_months=None,
        perm_rate=None,
        perm_amort_years=None,
        max_purchase_ltv=Decimal("0.75"),
        all_in_rate=Decimal("0.065"),
        amort_years=30,
    )


def _make_complete_inputs() -> DealInputs:
    """Build a complete DealInputs with no missing data."""
    return DealInputs(
        deal=_make_deal(),
        units=_make_units(),
        rent_roll=_make_rent_roll(),
        rehab_plan=_make_rehab_plan_no_reno(),
        market_rents=(
            MarketRentSnapshot(
                unit_type="2BR",
                target_rent=Decimal("1100.00"),
                post_reno_target_rent=Decimal("1300.00"),
            ),
        ),
        opex=_make_opex(),
        reserves=_make_reserves(),
        lender_scenario_a=_make_lender_a(),
        lender_scenario_b=_make_lender_b(),
        funding_sources=(),
        capex_allocation=LumpSumAtStart(),
    )


# ---------------------------------------------------------------------------
# Tests: _amortizing_payment
# ---------------------------------------------------------------------------


class TestAmortizingPayment:
    def test_normal_rate(self):
        """Standard 30-year mortgage at 6% annual."""
        principal = Decimal("100000.00")
        monthly_rate = Decimal("0.005000")  # 6% / 12
        n = 360
        payment = _amortizing_payment(principal, monthly_rate, n)
        # Expected ~$599.55
        assert payment == Decimal("599.55")

    def test_zero_rate(self):
        """Zero rate falls back to principal / n."""
        principal = Decimal("120000.00")
        payment = _amortizing_payment(principal, ZERO, 360)
        assert payment == Decimal("333.33")

    def test_zero_payments(self):
        """Zero num_payments returns zero."""
        payment = _amortizing_payment(Decimal("100000.00"), Decimal("0.005"), 0)
        assert payment == ZERO

    def test_negative_payments(self):
        """Negative num_payments returns zero."""
        payment = _amortizing_payment(Decimal("100000.00"), Decimal("0.005"), -1)
        assert payment == ZERO

    def test_small_loan(self):
        """Small loan with short term."""
        principal = Decimal("10000.00")
        monthly_rate = Decimal("0.004167")  # ~5% / 12
        n = 12
        payment = _amortizing_payment(principal, monthly_rate, n)
        # Should be around $856
        assert payment > Decimal("850.00")
        assert payment < Decimal("860.00")


# ---------------------------------------------------------------------------
# Tests: _scan_missing_inputs
# ---------------------------------------------------------------------------


class TestScanMissingInputs:
    def test_complete_inputs_no_missing(self):
        inputs = _make_complete_inputs()
        missing_a, missing_b = _scan_missing_inputs(inputs)
        assert missing_a == []
        assert missing_b == []

    def test_rent_roll_incomplete(self):
        """Fewer rent roll entries than unit_count triggers RENT_ROLL_INCOMPLETE."""
        inputs = DealInputs(
            deal=_make_deal(unit_count=5),
            units=_make_units(5),
            rent_roll=_make_rent_roll(3),  # Only 3 of 5
            rehab_plan=_make_rehab_plan_no_reno(3),
            market_rents=(),
            opex=_make_opex(),
            reserves=_make_reserves(),
            lender_scenario_a=_make_lender_a(),
            lender_scenario_b=_make_lender_b(),
            funding_sources=(),
            capex_allocation=LumpSumAtStart(),
        )
        missing_a, missing_b = _scan_missing_inputs(inputs)
        assert RENT_ROLL_INCOMPLETE in missing_a
        assert RENT_ROLL_INCOMPLETE in missing_b

    def test_rehab_plan_missing(self):
        """Unit with renovate_flag=True but no rehab_start_month."""
        rehab = (
            RehabPlanSnapshot(
                unit_id="U1",
                renovate_flag=True,
                current_rent=Decimal("1000.00"),
                underwritten_post_reno_rent=Decimal("1300.00"),
                rehab_start_month=None,  # Missing!
                downtime_months=None,
                stabilized_month=None,
                rehab_budget=Decimal("20000.00"),
            ),
        )
        inputs = DealInputs(
            deal=_make_deal(unit_count=1),
            units=_make_units(1),
            rent_roll=_make_rent_roll(1),
            rehab_plan=rehab,
            market_rents=(),
            opex=_make_opex(),
            reserves=_make_reserves(1),
            lender_scenario_a=_make_lender_a(),
            lender_scenario_b=_make_lender_b(),
            funding_sources=(),
            capex_allocation=LumpSumAtStart(),
        )
        missing_a, missing_b = _scan_missing_inputs(inputs)
        assert REHAB_PLAN_MISSING in missing_a
        assert REHAB_PLAN_MISSING in missing_b

    def test_lender_missing_a(self):
        """No lender for scenario A."""
        inputs = DealInputs(
            deal=_make_deal(),
            units=_make_units(),
            rent_roll=_make_rent_roll(),
            rehab_plan=_make_rehab_plan_no_reno(),
            market_rents=(),
            opex=_make_opex(),
            reserves=_make_reserves(),
            lender_scenario_a=None,
            lender_scenario_b=_make_lender_b(),
            funding_sources=(),
            capex_allocation=LumpSumAtStart(),
        )
        missing_a, missing_b = _scan_missing_inputs(inputs)
        assert PRIMARY_LENDER_MISSING_A in missing_a
        assert PRIMARY_LENDER_MISSING_B not in missing_b

    def test_lender_missing_b(self):
        """No lender for scenario B."""
        inputs = DealInputs(
            deal=_make_deal(),
            units=_make_units(),
            rent_roll=_make_rent_roll(),
            rehab_plan=_make_rehab_plan_no_reno(),
            market_rents=(),
            opex=_make_opex(),
            reserves=_make_reserves(),
            lender_scenario_a=_make_lender_a(),
            lender_scenario_b=None,
            funding_sources=(),
            capex_allocation=LumpSumAtStart(),
        )
        missing_a, missing_b = _scan_missing_inputs(inputs)
        assert PRIMARY_LENDER_MISSING_A not in missing_a
        assert PRIMARY_LENDER_MISSING_B in missing_b


# ---------------------------------------------------------------------------
# Tests: compute_pro_forma (full pipeline)
# ---------------------------------------------------------------------------


class TestComputeProForma:
    def test_returns_24_monthly_rows(self):
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        assert len(result.monthly_schedule) == HORIZON_MONTHS

    def test_no_missing_inputs_with_complete_data(self):
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        assert result.missing_inputs_a == []
        assert result.missing_inputs_b == []

    def test_gsr_equals_sum_of_unit_rents(self):
        """GSR for month 1 should equal sum of all unit rents (no reno)."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        # 5 units * $1000 = $5000
        assert result.monthly_schedule[0].gsr == Decimal("5000.00")

    def test_egi_formula(self):
        """EGI = GSR - vacancy_loss + other_income."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        row = result.monthly_schedule[0]
        expected_vacancy = quantize_money(Decimal("0.05") * Decimal("5000.00"))
        expected_egi = quantize_money(
            Decimal("5000.00") - expected_vacancy + Decimal("200.00")
        )
        assert row.vacancy_loss == expected_vacancy
        assert row.egi == expected_egi

    def test_noi_formula(self):
        """NOI = EGI - OpEx."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        row = result.monthly_schedule[0]
        assert row.noi == quantize_money(row.egi - row.opex_total)

    def test_net_cash_flow_formula(self):
        """Net cash flow = NOI - replacement_reserves."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        row = result.monthly_schedule[0]
        assert row.net_cash_flow == quantize_money(row.noi - row.replacement_reserves)

    def test_debt_service_a_io_period(self):
        """During IO period, debt service A = loan * construction_rate / 12."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        # Loan A = 0.75 * (500000 + 15000 + 0) = 386250
        loan_a = Decimal("0.75") * (Decimal("500000") + Decimal("15000") + ZERO)
        expected_io = quantize_money(loan_a * Decimal("0.07") / Decimal("12"))
        # Month 1 is in IO period (io_months=12)
        assert result.monthly_schedule[0].debt_service_a == expected_io

    def test_debt_service_a_amortizing_period(self):
        """After IO period, debt service A uses amortizing formula."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        # Month 13 should be amortizing (io_months=12, so month 13 is first amortizing)
        ds_month_13 = result.monthly_schedule[12].debt_service_a
        # Should be different from IO payment
        ds_month_1 = result.monthly_schedule[0].debt_service_a
        assert ds_month_13 is not None
        assert ds_month_1 is not None
        assert ds_month_13 != ds_month_1

    def test_debt_service_b_constant(self):
        """Scenario B debt service is constant for all 24 months."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        ds_values = [row.debt_service_b for row in result.monthly_schedule]
        assert all(v is not None for v in ds_values)
        assert all(v == ds_values[0] for v in ds_values)

    def test_cash_flow_after_debt(self):
        """cash_flow_after_debt = net_cash_flow - debt_service."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        row = result.monthly_schedule[0]
        assert row.cash_flow_after_debt_a == quantize_money(
            row.net_cash_flow - row.debt_service_a
        )
        assert row.cash_flow_after_debt_b == quantize_money(
            row.net_cash_flow - row.debt_service_b
        )

    def test_capex_spend_zero_no_reno(self):
        """No renovation → capex_spend is zero for all months."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        for row in result.monthly_schedule:
            assert row.capex_spend == ZERO

    def test_cash_flow_after_capex(self):
        """cash_flow_after_capex = cash_flow_after_debt - capex_spend."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        row = result.monthly_schedule[0]
        assert row.cash_flow_after_capex_a == quantize_money(
            row.cash_flow_after_debt_a - row.capex_spend
        )

    def test_summary_in_place_noi(self):
        """In-Place NOI = Month 1 NOI * 12."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        expected = quantize_money(result.monthly_schedule[0].noi * Decimal("12"))
        assert result.summary.in_place_noi == expected

    def test_summary_stabilized_noi(self):
        """Stabilized NOI = average(NOI months 13..24) * 12."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        noi_13_24 = [result.monthly_schedule[m - 1].noi for m in range(13, 25)]
        avg = sum(noi_13_24) / Decimal("12")
        expected = quantize_money(avg * Decimal("12"))
        assert result.summary.stabilized_noi == expected

    def test_summary_dscr_a(self):
        """DSCR A computed correctly."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        assert result.summary.in_place_dscr_a is not None
        assert result.summary.stabilized_dscr_a is not None

    def test_missing_lender_a_sets_debt_to_none(self):
        """Missing lender A → debt_service_a and downstream are None."""
        inputs = DealInputs(
            deal=_make_deal(),
            units=_make_units(),
            rent_roll=_make_rent_roll(),
            rehab_plan=_make_rehab_plan_no_reno(),
            market_rents=(),
            opex=_make_opex(),
            reserves=_make_reserves(),
            lender_scenario_a=None,
            lender_scenario_b=_make_lender_b(),
            funding_sources=(),
            capex_allocation=LumpSumAtStart(),
        )
        result = compute_pro_forma(inputs)
        assert PRIMARY_LENDER_MISSING_A in result.missing_inputs_a
        for row in result.monthly_schedule:
            assert row.debt_service_a is None
            assert row.cash_flow_after_debt_a is None
            assert row.cash_flow_after_capex_a is None
        # Summary DSCR A should be None
        assert result.summary.in_place_dscr_a is None
        assert result.summary.stabilized_dscr_a is None

    def test_sources_and_uses_are_computed(self):
        """Sources & Uses are computed when inputs are complete."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        # S&U should be populated when lender profiles are present
        assert result.sources_and_uses_a is not None
        assert result.sources_and_uses_b is not None
        # Basic sanity: total_uses > 0
        assert result.sources_and_uses_a.total_uses > 0
        assert result.sources_and_uses_b.total_uses > 0

    def test_valuation_is_none(self):
        """Valuation not computed in this engine — should be None."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        assert result.valuation is None

    def test_cash_on_cash_is_computed(self):
        """Cash-on-Cash is computed when inputs are complete."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        # Cash-on-cash should be computed (may be negative if deal is underwater)
        assert result.summary.cash_on_cash_a is not None
        assert result.summary.cash_on_cash_b is not None


# ---------------------------------------------------------------------------
# Tests: Per-unit scheduled rent with renovation
# ---------------------------------------------------------------------------


class TestScheduledRentWithReno:
    def test_renovated_unit_schedule(self):
        """Renovated unit: current → 0 during downtime → post-reno after stabilized."""
        rehab = (
            RehabPlanSnapshot(
                unit_id="U1",
                renovate_flag=True,
                current_rent=Decimal("1000.00"),
                underwritten_post_reno_rent=Decimal("1400.00"),
                rehab_start_month=3,
                downtime_months=2,
                stabilized_month=5,  # 3 + 2
                rehab_budget=Decimal("20000.00"),
            ),
        )
        rent_roll = (_make_rent_roll(1)[0],)
        inputs = DealInputs(
            deal=_make_deal(unit_count=1),
            units=_make_units(1),
            rent_roll=rent_roll,
            rehab_plan=rehab,
            market_rents=(),
            opex=_make_opex(),
            reserves=_make_reserves(1),
            lender_scenario_a=_make_lender_a(),
            lender_scenario_b=_make_lender_b(),
            funding_sources=(),
            capex_allocation=LumpSumAtStart(),
        )
        result = compute_pro_forma(inputs)

        schedule = result.per_unit_schedule["U1"]
        # Months 1-2: current_rent
        assert schedule[0] == Decimal("1000.00")
        assert schedule[1] == Decimal("1000.00")
        # Months 3-4: downtime (zero)
        assert schedule[2] == ZERO
        assert schedule[3] == ZERO
        # Months 5+: post-reno rent
        assert schedule[4] == Decimal("1400.00")
        assert schedule[23] == Decimal("1400.00")

    def test_capex_at_rehab_start(self):
        """CapEx spend appears at rehab_start_month."""
        rehab = (
            RehabPlanSnapshot(
                unit_id="U1",
                renovate_flag=True,
                current_rent=Decimal("1000.00"),
                underwritten_post_reno_rent=Decimal("1400.00"),
                rehab_start_month=3,
                downtime_months=2,
                stabilized_month=5,
                rehab_budget=Decimal("20000.00"),
            ),
        )
        inputs = DealInputs(
            deal=_make_deal(unit_count=1),
            units=_make_units(1),
            rent_roll=_make_rent_roll(1),
            rehab_plan=rehab,
            market_rents=(),
            opex=_make_opex(),
            reserves=_make_reserves(1),
            lender_scenario_a=_make_lender_a(),
            lender_scenario_b=_make_lender_b(),
            funding_sources=(),
            capex_allocation=LumpSumAtStart(),
        )
        result = compute_pro_forma(inputs)

        # Month 3 should have capex
        assert result.monthly_schedule[2].capex_spend == Decimal("20000.00")
        # Other months should be zero
        assert result.monthly_schedule[0].capex_spend == ZERO
        assert result.monthly_schedule[1].capex_spend == ZERO
        assert result.monthly_schedule[3].capex_spend == ZERO

    def test_gsr_reflects_renovation_downtime(self):
        """GSR drops during renovation downtime."""
        rehab = (
            RehabPlanSnapshot(
                unit_id="U1",
                renovate_flag=True,
                current_rent=Decimal("1000.00"),
                underwritten_post_reno_rent=Decimal("1400.00"),
                rehab_start_month=1,
                downtime_months=2,
                stabilized_month=3,
                rehab_budget=Decimal("20000.00"),
            ),
        )
        inputs = DealInputs(
            deal=_make_deal(unit_count=1),
            units=_make_units(1),
            rent_roll=_make_rent_roll(1),
            rehab_plan=rehab,
            market_rents=(),
            opex=_make_opex(),
            reserves=_make_reserves(1),
            lender_scenario_a=_make_lender_a(),
            lender_scenario_b=_make_lender_b(),
            funding_sources=(),
            capex_allocation=LumpSumAtStart(),
        )
        result = compute_pro_forma(inputs)

        # Month 1-2: unit offline, GSR = 0
        assert result.monthly_schedule[0].gsr == ZERO
        assert result.monthly_schedule[1].gsr == ZERO
        # Month 3+: post-reno rent
        assert result.monthly_schedule[2].gsr == Decimal("1400.00")


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_perm_rate_zero_scenario_a(self):
        """perm_rate=0 uses straight-line repayment."""
        lender_a = LenderProfileSnapshot(
            lender_type="Construction_To_Perm",
            origination_fee_rate=Decimal("0.01"),
            ltv_total_cost=Decimal("0.75"),
            construction_rate=Decimal("0.07"),
            construction_io_months=6,
            perm_rate=ZERO,  # Zero rate!
            perm_amort_years=30,
            max_purchase_ltv=None,
            all_in_rate=None,
            amort_years=None,
        )
        inputs = DealInputs(
            deal=_make_deal(),
            units=_make_units(),
            rent_roll=_make_rent_roll(),
            rehab_plan=_make_rehab_plan_no_reno(),
            market_rents=(),
            opex=_make_opex(),
            reserves=_make_reserves(),
            lender_scenario_a=lender_a,
            lender_scenario_b=_make_lender_b(),
            funding_sources=(),
            capex_allocation=LumpSumAtStart(),
        )
        result = compute_pro_forma(inputs)
        # Month 7 (first amortizing month): loan / (30*12)
        loan_a = Decimal("0.75") * (Decimal("500000") + Decimal("15000"))
        expected = quantize_money(loan_a / Decimal("360"))
        assert result.monthly_schedule[6].debt_service_a == expected

    def test_engine_does_not_raise_on_missing_inputs(self):
        """Engine gracefully handles missing lenders without raising."""
        inputs = DealInputs(
            deal=_make_deal(),
            units=_make_units(),
            rent_roll=_make_rent_roll(),
            rehab_plan=_make_rehab_plan_no_reno(),
            market_rents=(),
            opex=_make_opex(),
            reserves=_make_reserves(),
            lender_scenario_a=None,
            lender_scenario_b=None,
            funding_sources=(),
            capex_allocation=LumpSumAtStart(),
        )
        # Should not raise
        result = compute_pro_forma(inputs)
        assert PRIMARY_LENDER_MISSING_A in result.missing_inputs_a
        assert PRIMARY_LENDER_MISSING_B in result.missing_inputs_b
        # Shared pipeline still computed
        assert result.monthly_schedule[0].gsr == Decimal("5000.00")
        assert result.monthly_schedule[0].noi is not None

    def test_per_unit_schedule_has_all_units(self):
        """per_unit_schedule contains an entry for each rent roll unit."""
        inputs = _make_complete_inputs()
        result = compute_pro_forma(inputs)
        assert len(result.per_unit_schedule) == 5
        for uid in ["U1", "U2", "U3", "U4", "U5"]:
            assert uid in result.per_unit_schedule
            assert len(result.per_unit_schedule[uid]) == HORIZON_MONTHS
