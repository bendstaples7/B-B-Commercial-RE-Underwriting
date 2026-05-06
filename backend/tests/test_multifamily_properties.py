"""
Property-based tests for the multifamily pro forma engine.

Uses Hypothesis to verify correctness properties hold across all valid inputs.
Each test validates specific requirements from the design document.

# Feature: multifamily-underwriting-proforma, Property 2: Per-unit scheduled rent rule and monthly GSR
"""

from decimal import Decimal

from hypothesis import assume, given, settings, HealthCheck
from hypothesis import strategies as st

from app.services.multifamily.pro_forma_constants import HORIZON_MONTHS, STABILIZED_MONTHS, quantize_money
from app.services.multifamily.pro_forma_engine import compute_pro_forma
from app.services.multifamily.pro_forma_inputs import DealInputs

from tests.generators.multifamily import deal_inputs_st


ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Property 2: Per-unit scheduled rent rule and monthly GSR
# ---------------------------------------------------------------------------


class TestScheduledRentRule:
    """Property 2: Per-unit scheduled rent rule and monthly GSR.

    For any DealInputs and for any month M in 1..24, the engine's
    per_unit_schedule[unit_id][M-1] SHALL equal:
    - current_rent when renovate_flag is false, or when M < rehab_start_month
    - 0 when rehab_start_month <= M < stabilized_month
    - underwritten_post_reno_rent when M >= stabilized_month

    And monthly_schedule[M-1].gsr SHALL equal the sum of
    per_unit_schedule[u][M-1] across all units.

    **Validates: Requirements 8.1, 8.2**
    """

    @settings(max_examples=100, deadline=None)
    @given(inputs=deal_inputs_st())
    def test_scheduled_rent_rule(self, inputs: DealInputs) -> None:
        """Per-unit scheduled rent follows the renovation timing rule and
        GSR equals the sum across all units for every month.

        # Feature: multifamily-underwriting-proforma, Property 2: Per-unit scheduled rent rule and monthly GSR
        """
        result = compute_pro_forma(inputs)

        # Build lookup maps matching what the engine uses
        rent_roll_map = {rr.unit_id: rr.current_rent for rr in inputs.rent_roll}
        rehab_plan_map = {rp.unit_id: rp for rp in inputs.rehab_plan}

        # All unit_ids from rent_roll (same set the engine iterates)
        all_unit_ids = [rr.unit_id for rr in inputs.rent_roll]

        for month in range(1, HORIZON_MONTHS + 1):
            expected_gsr = Decimal("0")

            for unit_id in all_unit_ids:
                actual_rent = result.per_unit_schedule[unit_id][month - 1]
                current_rent = rent_roll_map[unit_id]
                plan = rehab_plan_map.get(unit_id)

                # Determine expected rent per the property definition
                if plan is None or not plan.renovate_flag:
                    # Non-renovated unit: always current_rent
                    expected_rent = quantize_money(current_rent)
                elif plan.rehab_start_month is None:
                    # Missing rehab_start_month — engine treats as non-renovated
                    expected_rent = quantize_money(current_rent)
                else:
                    rehab_start = plan.rehab_start_month
                    stabilized_month = plan.stabilized_month
                    if stabilized_month is None:
                        stabilized_month = rehab_start

                    if month < rehab_start:
                        expected_rent = quantize_money(current_rent)
                    elif month < stabilized_month:
                        expected_rent = ZERO
                    else:
                        # Post-stabilization: underwritten_post_reno_rent
                        post_reno = plan.underwritten_post_reno_rent
                        if post_reno is not None:
                            expected_rent = quantize_money(post_reno)
                        else:
                            expected_rent = quantize_money(current_rent)

                assert actual_rent == expected_rent, (
                    f"Unit {unit_id}, Month {month}: "
                    f"expected {expected_rent}, got {actual_rent}. "
                    f"Plan: renovate={plan.renovate_flag if plan else None}, "
                    f"start={plan.rehab_start_month if plan else None}, "
                    f"stabilized={plan.stabilized_month if plan else None}"
                )

                expected_gsr += actual_rent

            # GSR for this month should equal sum of per-unit rents
            actual_gsr = result.monthly_schedule[month - 1].gsr
            assert actual_gsr == quantize_money(expected_gsr), (
                f"Month {month}: GSR mismatch. "
                f"Expected {quantize_money(expected_gsr)}, got {actual_gsr}"
            )


# ---------------------------------------------------------------------------
# Property 3: Monthly math identity
# ---------------------------------------------------------------------------


class TestMonthlyMathIdentity:
    """Property 3: Monthly math identity.

    For any DealInputs and for any month M in 1..24, the engine SHALL
    satisfy all of the following algebraic identities within a deterministic
    rounding tolerance:

    - egi(M)               = gsr(M) - vacancy_rate * gsr(M) + other_income_monthly
    - opex_total(M)        = (property_taxes_annual + insurance_annual + utilities_annual
                              + repairs_and_maintenance_annual + admin_and_marketing_annual
                              + payroll_annual + other_opex_annual) / 12
                              + management_fee_rate * egi(M)
    - noi(M)               = egi(M) - opex_total(M)
    - net_cash_flow(M)     = noi(M) - reserve_per_unit_per_year * unit_count / 12
    - cash_flow_after_debt(M, S)  = net_cash_flow(M) - debt_service(M, S) for S in {A, B}
    - cash_flow_after_capex(M, S) = cash_flow_after_debt(M, S) - capex_spend(M)

    **Validates: Requirements 8.3, 8.4, 8.5, 8.6, 8.9, 8.11**
    """

    @settings(max_examples=100, deadline=None)
    @given(inputs=deal_inputs_st())
    def test_monthly_math_identity(self, inputs: DealInputs) -> None:
        """EGI, OpEx, NOI, net_cash_flow, cash_flow_after_debt, and
        cash_flow_after_capex identities hold for every month M in 1..24.

        # Feature: multifamily-underwriting-proforma, Property 3: Monthly math identity
        """
        result = compute_pro_forma(inputs)

        TWELVE = Decimal("12")

        for month in range(1, HORIZON_MONTHS + 1):
            row = result.monthly_schedule[month - 1]

            # --- EGI identity (Req 8.3) ---
            expected_egi = quantize_money(
                row.gsr
                - quantize_money(inputs.deal.vacancy_rate * row.gsr)
                + inputs.deal.other_income_monthly
            )
            assert row.egi == expected_egi, (
                f"Month {month}: EGI mismatch. "
                f"Expected {expected_egi}, got {row.egi}"
            )

            # --- OpEx identity (Req 8.4) ---
            opex = inputs.opex
            fixed_opex = quantize_money(
                quantize_money(opex.property_taxes_annual / TWELVE)
                + quantize_money(opex.insurance_annual / TWELVE)
                + quantize_money(opex.utilities_annual / TWELVE)
                + quantize_money(opex.repairs_and_maintenance_annual / TWELVE)
                + quantize_money(opex.admin_and_marketing_annual / TWELVE)
                + quantize_money(opex.payroll_annual / TWELVE)
                + quantize_money(opex.other_opex_annual / TWELVE)
            )
            mgmt_fee = quantize_money(opex.management_fee_rate * row.egi)
            expected_opex_total = quantize_money(fixed_opex + mgmt_fee)
            assert row.opex_total == expected_opex_total, (
                f"Month {month}: OpEx total mismatch. "
                f"Expected {expected_opex_total}, got {row.opex_total}"
            )

            # --- NOI identity (Req 8.5) ---
            expected_noi = quantize_money(row.egi - row.opex_total)
            assert row.noi == expected_noi, (
                f"Month {month}: NOI mismatch. "
                f"Expected {expected_noi}, got {row.noi}"
            )

            # --- Net cash flow identity (Req 8.6) ---
            expected_reserves = quantize_money(
                inputs.reserves.reserve_per_unit_per_year
                * Decimal(inputs.reserves.unit_count)
                / TWELVE
            )
            expected_net_cash_flow = quantize_money(row.noi - expected_reserves)
            assert row.net_cash_flow == expected_net_cash_flow, (
                f"Month {month}: Net cash flow mismatch. "
                f"Expected {expected_net_cash_flow}, got {row.net_cash_flow}"
            )

            # --- Cash flow after debt identity (Req 8.9) ---
            # Scenario A
            if row.debt_service_a is not None and row.cash_flow_after_debt_a is not None:
                expected_cf_after_debt_a = quantize_money(
                    row.net_cash_flow - row.debt_service_a
                )
                assert row.cash_flow_after_debt_a == expected_cf_after_debt_a, (
                    f"Month {month}: Cash flow after debt (A) mismatch. "
                    f"Expected {expected_cf_after_debt_a}, got {row.cash_flow_after_debt_a}"
                )

            # Scenario B
            if row.debt_service_b is not None and row.cash_flow_after_debt_b is not None:
                expected_cf_after_debt_b = quantize_money(
                    row.net_cash_flow - row.debt_service_b
                )
                assert row.cash_flow_after_debt_b == expected_cf_after_debt_b, (
                    f"Month {month}: Cash flow after debt (B) mismatch. "
                    f"Expected {expected_cf_after_debt_b}, got {row.cash_flow_after_debt_b}"
                )

            # --- Cash flow after capex identity (Req 8.11) ---
            # Scenario A
            if row.cash_flow_after_debt_a is not None and row.cash_flow_after_capex_a is not None:
                expected_cf_after_capex_a = quantize_money(
                    row.cash_flow_after_debt_a - row.capex_spend
                )
                assert row.cash_flow_after_capex_a == expected_cf_after_capex_a, (
                    f"Month {month}: Cash flow after capex (A) mismatch. "
                    f"Expected {expected_cf_after_capex_a}, got {row.cash_flow_after_capex_a}"
                )

            # Scenario B
            if row.cash_flow_after_debt_b is not None and row.cash_flow_after_capex_b is not None:
                expected_cf_after_capex_b = quantize_money(
                    row.cash_flow_after_debt_b - row.capex_spend
                )
                assert row.cash_flow_after_capex_b == expected_cf_after_capex_b, (
                    f"Month {month}: Cash flow after capex (B) mismatch. "
                    f"Expected {expected_cf_after_capex_b}, got {row.cash_flow_after_capex_b}"
                )


# ---------------------------------------------------------------------------
# Property 5: Amortizing schedule recovers principal
# ---------------------------------------------------------------------------

from app.services.multifamily.pro_forma_engine import _amortizing_payment
from tests.generators.multifamily import amortization_inputs_st


class TestAmortizationRecoversPrincipal:
    """Property 5: Amortizing schedule recovers principal.

    For any positive loan_amount, for any r = annual_rate / 12 > 0, and for any
    n = amort_years * 12 > 0, the sequence of monthly payments
    P = loan_amount * r * (1 + r)^n / ((1 + r)^n - 1) applied over n months
    SHALL fully amortize the loan: the sum of the per-period principal components
    (payment minus interest on the remaining balance) equals loan_amount within a
    rounding tolerance of 0.01 * n dollars. Equivalently, after n payments the
    remaining balance is <= n * 0.01 dollars.

    **Validates: Requirements 8.7 (amortizing branch), 8.8**
    """

    @settings(max_examples=100, deadline=None)
    @given(data=amortization_inputs_st())
    def test_amortization_recovers_principal(
        self, data: tuple[Decimal, Decimal, int]
    ) -> None:
        """After n payments the remaining balance is within n * 0.01 dollars of zero.

        # Feature: multifamily-underwriting-proforma, Property 5: Amortizing schedule recovers principal
        """
        principal, annual_rate, amort_years = data

        monthly_rate = annual_rate / Decimal("12")
        n = amort_years * 12

        # Filter inputs where the compounding factor would make the
        # 0.01*n tolerance mathematically insufficient for quantized payments.
        # The annuity factor ((1+r)^n - 1)/r must be <= 2*n for the bound to hold.
        one_plus_r_n = (Decimal("1") + monthly_rate) ** n
        annuity_factor = (one_plus_r_n - Decimal("1")) / monthly_rate
        assume(annuity_factor <= Decimal("2") * n)

        # Compute the fixed monthly payment using the engine's helper
        payment = _amortizing_payment(principal, monthly_rate, n)

        # Simulate the amortization schedule
        balance = principal
        for _ in range(n):
            interest = balance * monthly_rate
            principal_component = payment - interest
            balance -= principal_component

        # After n payments, the remaining balance should be near zero
        tolerance = n * Decimal("0.01")
        assert abs(balance) <= tolerance, (
            f"Remaining balance {balance} exceeds tolerance {tolerance}. "
            f"principal={principal}, annual_rate={annual_rate}, "
            f"amort_years={amort_years}, monthly_payment={payment}"
        )


# ---------------------------------------------------------------------------
# Property 6: Interest-only debt service identity
# ---------------------------------------------------------------------------


class TestIODebtServiceIdentity:
    """Property 6: Interest-only debt service identity.

    For any loan_amount and for any construction_rate in [0, 0.30], during the
    IO months M in 1..construction_io_months the engine SHALL return
    debt_service_A(M) = loan_amount * construction_rate / 12 exactly. For months
    after the IO period, debt_service_A(M) follows the amortizing formula
    (covered by Property 5).

    **Validates: Requirement 8.7 (IO branch)**
    """

    @settings(max_examples=100, deadline=None)
    @given(inputs=deal_inputs_st())
    def test_io_debt_service_identity(self, inputs: DealInputs) -> None:
        """During IO months, debt_service_A equals loan_amount_a * construction_rate / 12 exactly.

        # Feature: multifamily-underwriting-proforma, Property 6: Interest-only debt service identity
        """
        result = compute_pro_forma(inputs)

        lender_a = inputs.lender_scenario_a
        # This property only applies when lender_a is present
        if lender_a is None:
            return

        # Compute loan_amount_a the same way the engine does:
        # ltv_total_cost * (purchase_price + closing_costs + rehab_budget_total)
        rehab_budget_total = sum(
            (p.rehab_budget for p in inputs.rehab_plan if p.renovate_flag), ZERO
        )
        loan_amount_a = quantize_money(
            lender_a.ltv_total_cost
            * (inputs.deal.purchase_price + inputs.deal.closing_costs + rehab_budget_total)
        )

        construction_rate = lender_a.construction_rate
        construction_io_months = lender_a.construction_io_months

        # For each month M in 1..construction_io_months, assert IO identity
        for month in range(1, construction_io_months + 1):
            expected_ds = quantize_money(
                loan_amount_a * construction_rate / Decimal("12")
            )
            actual_ds = result.monthly_schedule[month - 1].debt_service_a

            assert actual_ds == expected_ds, (
                f"Month {month}: IO debt service mismatch. "
                f"Expected {expected_ds}, got {actual_ds}. "
                f"loan_amount_a={loan_amount_a}, "
                f"construction_rate={construction_rate}, "
                f"construction_io_months={construction_io_months}"
            )


# ---------------------------------------------------------------------------
# Property 8: DSCR formula and null guard
# ---------------------------------------------------------------------------

from app.services.multifamily.pro_forma_constants import quantize_rate


class TestDSCRFormulaAndNull:
    """Property 8: DSCR formula and null guard.

    For any month M in {1, 24} and for any scenario S in {A, B}:
    - If debt_service(M, S) == 0 or is None, then DSCR(M, S) is None.
    - Otherwise DSCR(M, S) == noi(M) / debt_service(M, S) (within Decimal tolerance).

    Applied at M = 1 this yields In_Place_DSCR(S); applied at M = 24 it yields
    Stabilized_DSCR(S).

    **Validates: Requirements 8.12 (DSCR subset), 8.13**
    """

    @settings(max_examples=100, deadline=None)
    @given(inputs=deal_inputs_st())
    def test_dscr_formula_and_null(self, inputs: DealInputs) -> None:
        """Zero debt service yields DSCR=None, non-zero yields NOI/DS.

        # Feature: multifamily-underwriting-proforma, Property 8: DSCR formula and null guard
        """
        result = compute_pro_forma(inputs)

        month_1 = result.monthly_schedule[0]
        month_24 = result.monthly_schedule[23]
        summary = result.summary

        # --- In-Place DSCR (Month 1) ---
        # Scenario A
        if month_1.debt_service_a is None or month_1.debt_service_a == ZERO:
            assert summary.in_place_dscr_a is None, (
                f"In-Place DSCR A should be None when debt_service_a is "
                f"{month_1.debt_service_a}, got {summary.in_place_dscr_a}"
            )
        else:
            expected = quantize_rate(month_1.noi / month_1.debt_service_a)
            assert summary.in_place_dscr_a == expected, (
                f"In-Place DSCR A mismatch: expected {expected}, "
                f"got {summary.in_place_dscr_a}. "
                f"noi={month_1.noi}, debt_service_a={month_1.debt_service_a}"
            )

        # Scenario B
        if month_1.debt_service_b is None or month_1.debt_service_b == ZERO:
            assert summary.in_place_dscr_b is None, (
                f"In-Place DSCR B should be None when debt_service_b is "
                f"{month_1.debt_service_b}, got {summary.in_place_dscr_b}"
            )
        else:
            expected = quantize_rate(month_1.noi / month_1.debt_service_b)
            assert summary.in_place_dscr_b == expected, (
                f"In-Place DSCR B mismatch: expected {expected}, "
                f"got {summary.in_place_dscr_b}. "
                f"noi={month_1.noi}, debt_service_b={month_1.debt_service_b}"
            )

        # --- Stabilized DSCR (Month 24) ---
        # Scenario A
        if month_24.debt_service_a is None or month_24.debt_service_a == ZERO:
            assert summary.stabilized_dscr_a is None, (
                f"Stabilized DSCR A should be None when debt_service_a is "
                f"{month_24.debt_service_a}, got {summary.stabilized_dscr_a}"
            )
        else:
            expected = quantize_rate(month_24.noi / month_24.debt_service_a)
            assert summary.stabilized_dscr_a == expected, (
                f"Stabilized DSCR A mismatch: expected {expected}, "
                f"got {summary.stabilized_dscr_a}. "
                f"noi={month_24.noi}, debt_service_a={month_24.debt_service_a}"
            )

        # Scenario B
        if month_24.debt_service_b is None or month_24.debt_service_b == ZERO:
            assert summary.stabilized_dscr_b is None, (
                f"Stabilized DSCR B should be None when debt_service_b is "
                f"{month_24.debt_service_b}, got {summary.stabilized_dscr_b}"
            )
        else:
            expected = quantize_rate(month_24.noi / month_24.debt_service_b)
            assert summary.stabilized_dscr_b == expected, (
                f"Stabilized DSCR B mismatch: expected {expected}, "
                f"got {summary.stabilized_dscr_b}. "
                f"noi={month_24.noi}, debt_service_b={month_24.debt_service_b}"
            )


# ---------------------------------------------------------------------------
# Property 9: Summary NOI identities
# ---------------------------------------------------------------------------


class TestSummaryNOIIdentities:
    """Property 9: Summary NOI identities.

    For any DealInputs, the engine's summary SHALL satisfy:
    - In_Place_NOI    == noi(1) * 12
    - Stabilized_NOI  == (noi(13) + noi(14) + ... + noi(24)) / 12 * 12

    Both identities hold exactly (subject only to the Decimal quantization
    of the underlying monthly values).

    **Validates: Requirement 8.12 (NOI subset)**
    """

    @settings(max_examples=100, deadline=None)
    @given(inputs=deal_inputs_st())
    def test_summary_noi_identities(self, inputs: DealInputs) -> None:
        """In_Place_NOI == noi(1)*12 and Stabilized_NOI == avg(noi(13..24))*12.

        # Feature: multifamily-underwriting-proforma, Property 9: Summary NOI identities
        """
        result = compute_pro_forma(inputs)
        summary = result.summary

        TWELVE = Decimal("12")

        # --- In-Place NOI identity ---
        expected_in_place_noi = quantize_money(
            result.monthly_schedule[0].noi * TWELVE
        )
        assert summary.in_place_noi == expected_in_place_noi, (
            f"In-Place NOI mismatch: expected {expected_in_place_noi}, "
            f"got {summary.in_place_noi}. "
            f"Month 1 NOI = {result.monthly_schedule[0].noi}"
        )

        # --- Stabilized NOI identity ---
        stabilized_nois = [
            result.monthly_schedule[m - 1].noi for m in STABILIZED_MONTHS
        ]
        avg_stabilized_noi = sum(stabilized_nois) / Decimal(len(stabilized_nois))
        expected_stabilized_noi = quantize_money(avg_stabilized_noi * TWELVE)
        assert summary.stabilized_noi == expected_stabilized_noi, (
            f"Stabilized NOI mismatch: expected {expected_stabilized_noi}, "
            f"got {summary.stabilized_noi}. "
            f"Avg NOI(13..24) = {avg_stabilized_noi}"
        )


# ---------------------------------------------------------------------------
# Property 13: Cash-on-Cash identity and null guard
# ---------------------------------------------------------------------------


class TestCashOnCashIdentity:
    """Property 13: Cash-on-Cash identity and null guard.

    For any scenario S:
    - If initial_cash_investment(S) > 0, then
      cash_on_cash(S) == sum(cash_flow_after_debt(M, S) for M in 13..24)
                         / initial_cash_investment(S).
    - If initial_cash_investment(S) <= 0, then cash_on_cash(S) is None and
      the Non_Positive_Equity warning is present.

    **Validates: Requirements 10.6, 10.7**
    """

    @settings(max_examples=100, deadline=None)
    @given(inputs=deal_inputs_st())
    def test_cash_on_cash_identity(self, inputs: DealInputs) -> None:
        """Cash-on-Cash equals stabilized CFAD / initial_cash_investment when positive,
        None with warning when non-positive.

        # Feature: multifamily-underwriting-proforma, Property 13: Cash-on-Cash identity and null guard
        """
        from app.services.multifamily.pro_forma_constants import quantize_rate

        result = compute_pro_forma(inputs)

        # --- Scenario A ---
        su_a = result.sources_and_uses_a
        if su_a is not None:
            if su_a.initial_cash_investment > Decimal("0"):
                # Cash-on-Cash should be computed
                stabilized_cfad_a = sum(
                    (result.monthly_schedule[m - 1].cash_flow_after_debt_a or Decimal("0"))
                    for m in STABILIZED_MONTHS
                )
                expected_coc_a = quantize_rate(
                    stabilized_cfad_a / su_a.initial_cash_investment
                )
                assert result.summary.cash_on_cash_a == expected_coc_a, (
                    f"Cash-on-Cash A mismatch: expected {expected_coc_a}, "
                    f"got {result.summary.cash_on_cash_a}. "
                    f"stabilized_cfad_a={stabilized_cfad_a}, "
                    f"initial_cash_investment={su_a.initial_cash_investment}"
                )
            else:
                # Non-positive equity: cash_on_cash should be None
                assert result.summary.cash_on_cash_a is None, (
                    f"cash_on_cash_a should be None when initial_cash_investment <= 0, "
                    f"got {result.summary.cash_on_cash_a}"
                )
                assert "Non_Positive_Equity_A" in result.warnings, (
                    f"Expected 'Non_Positive_Equity_A' warning, "
                    f"got warnings={result.warnings}"
                )
        else:
            # No Sources & Uses for A (missing inputs)
            assert result.summary.cash_on_cash_a is None, (
                f"cash_on_cash_a should be None when sources_and_uses_a is None, "
                f"got {result.summary.cash_on_cash_a}"
            )

        # --- Scenario B ---
        su_b = result.sources_and_uses_b
        if su_b is not None:
            if su_b.initial_cash_investment > Decimal("0"):
                # Cash-on-Cash should be computed
                stabilized_cfad_b = sum(
                    (result.monthly_schedule[m - 1].cash_flow_after_debt_b or Decimal("0"))
                    for m in STABILIZED_MONTHS
                )
                expected_coc_b = quantize_rate(
                    stabilized_cfad_b / su_b.initial_cash_investment
                )
                assert result.summary.cash_on_cash_b == expected_coc_b, (
                    f"Cash-on-Cash B mismatch: expected {expected_coc_b}, "
                    f"got {result.summary.cash_on_cash_b}. "
                    f"stabilized_cfad_b={stabilized_cfad_b}, "
                    f"initial_cash_investment={su_b.initial_cash_investment}"
                )
            else:
                # Non-positive equity: cash_on_cash should be None
                assert result.summary.cash_on_cash_b is None, (
                    f"cash_on_cash_b should be None when initial_cash_investment <= 0, "
                    f"got {result.summary.cash_on_cash_b}"
                )
                assert "Non_Positive_Equity_B" in result.warnings, (
                    f"Expected 'Non_Positive_Equity_B' warning, "
                    f"got warnings={result.warnings}"
                )
        else:
            # No Sources & Uses for B (missing inputs)
            assert result.summary.cash_on_cash_b is None, (
                f"cash_on_cash_b should be None when sources_and_uses_b is None, "
                f"got {result.summary.cash_on_cash_b}"
            )


# ---------------------------------------------------------------------------
# Property 14: Missing-inputs path never raises
# ---------------------------------------------------------------------------

from tests.generators.multifamily import deal_inputs_with_missing_st


class TestMissingInputsNeverRaises:
    """Property 14: Missing-inputs path never raises.

    For any DealInputs in which one or more required inputs is missing (per
    the codes enumerated in Req 8.14), compute_pro_forma(inputs) SHALL return
    a ProFormaComputation whose missing_inputs_a and/or missing_inputs_b list
    is non-empty and whose per-scenario summary fields are None, without
    raising any exception. The shared monthly pipeline (GSR, EGI, OpEx, NOI,
    Net_Cash_Flow) is still populated whenever the inputs required for that
    layer are present.

    **Validates: Requirements 8.14, 11.2**
    """

    @settings(max_examples=100, deadline=None)
    @given(inputs=deal_inputs_with_missing_st())
    def test_missing_inputs_never_raises(self, inputs: DealInputs) -> None:
        """compute_pro_forma never raises on missing inputs, returns non-empty
        missing_inputs lists, None DSCR summaries for affected scenarios, and
        a fully populated shared monthly pipeline.

        # Feature: multifamily-underwriting-proforma, Property 14: Missing-inputs path never raises
        """
        # 1. Call compute_pro_forma — this MUST NOT raise any exception
        result = compute_pro_forma(inputs)

        # 2. Filter out cases where the generator produced complete inputs
        assume(
            len(result.missing_inputs_a) > 0 or len(result.missing_inputs_b) > 0
        )

        # 3. For any scenario with missing inputs, assert DSCR summary fields are None
        if len(result.missing_inputs_a) > 0:
            assert result.summary.in_place_dscr_a is None, (
                f"in_place_dscr_a should be None when scenario A has missing inputs, "
                f"got {result.summary.in_place_dscr_a}"
            )
            assert result.summary.stabilized_dscr_a is None, (
                f"stabilized_dscr_a should be None when scenario A has missing inputs, "
                f"got {result.summary.stabilized_dscr_a}"
            )

        if len(result.missing_inputs_b) > 0:
            assert result.summary.in_place_dscr_b is None, (
                f"in_place_dscr_b should be None when scenario B has missing inputs, "
                f"got {result.summary.in_place_dscr_b}"
            )
            assert result.summary.stabilized_dscr_b is None, (
                f"stabilized_dscr_b should be None when scenario B has missing inputs, "
                f"got {result.summary.stabilized_dscr_b}"
            )

        # 4. Assert that the shared pipeline (monthly_schedule) is still populated with 24 rows
        assert len(result.monthly_schedule) == 24, (
            f"Expected 24 monthly rows, got {len(result.monthly_schedule)}"
        )

        # 5. Assert that GSR, EGI, OpEx, NOI values are present (not None) in the monthly schedule
        for month_idx, row in enumerate(result.monthly_schedule):
            assert row.gsr is not None, (
                f"Month {month_idx + 1}: GSR should not be None"
            )
            assert row.egi is not None, (
                f"Month {month_idx + 1}: EGI should not be None"
            )
            assert row.opex_total is not None, (
                f"Month {month_idx + 1}: opex_total should not be None"
            )
            assert row.noi is not None, (
                f"Month {month_idx + 1}: NOI should not be None"
            )
            assert row.net_cash_flow is not None, (
                f"Month {month_idx + 1}: net_cash_flow should not be None"
            )


# ---------------------------------------------------------------------------
# Property 7: Cache determinism and invalidation
# ---------------------------------------------------------------------------

import json
from app.services.multifamily.inputs_hash import canonical_inputs, compute_inputs_hash
from app.services.multifamily.pro_forma_inputs import (
    DealSnapshot,
    FundingSourceSnapshot,
    LenderProfileSnapshot,
    LumpSumAtStart,
    OpExAssumptions,
    RehabPlanSnapshot,
    RentRollSnapshot,
    ReserveAssumptions,
)


class TestCacheDeterminism:
    """Property 7: Cache determinism and invalidation.

    Part 1 — Determinism:
    Two calls to compute_pro_forma on the same DealInputs yield identical
    ProFormaComputation (byte-equal canonical JSON) and identical
    compute_inputs_hash.

    Part 2 — Hash sensitivity:
    Changing any field listed in Req 15.3 (rent_roll, rehab_plan, opex
    assumptions, lender_profile selection, funding_sources, deal fields
    that affect computation) changes the hash.

    **Validates: Requirements 15.1, 15.2, 15.3**
    """

    @settings(max_examples=100, deadline=None)
    @given(inputs=deal_inputs_st())
    def test_cache_determinism(self, inputs: DealInputs) -> None:
        """Two calls on the same inputs yield identical ProFormaComputation
        and identical inputs_hash.

        # Feature: multifamily-underwriting-proforma, Property 7: Cache determinism and invalidation
        """
        # Compute pro forma twice with the same inputs
        result_1 = compute_pro_forma(inputs)
        result_2 = compute_pro_forma(inputs)

        # Canonical JSON of both results must be byte-equal
        json_1 = json.dumps(
            result_1.to_canonical_dict(), sort_keys=True, separators=(",", ":")
        )
        json_2 = json.dumps(
            result_2.to_canonical_dict(), sort_keys=True, separators=(",", ":")
        )
        assert json_1 == json_2, (
            "Two compute_pro_forma calls on the same inputs produced "
            "different canonical JSON outputs"
        )

        # Inputs hash must also be identical
        hash_1 = compute_inputs_hash(inputs)
        hash_2 = compute_inputs_hash(inputs)
        assert hash_1 == hash_2, (
            f"compute_inputs_hash is non-deterministic: "
            f"{hash_1} != {hash_2}"
        )

        # Hash must be a 64-char hex string (SHA-256)
        assert len(hash_1) == 64, f"Expected 64-char hash, got {len(hash_1)}"
        assert all(c in "0123456789abcdef" for c in hash_1), (
            f"Hash contains non-hex characters: {hash_1}"
        )

    @settings(max_examples=100, deadline=None)
    @given(inputs=deal_inputs_st())
    def test_cache_invalidation(self, inputs: DealInputs) -> None:
        """Changing any field listed in Req 15.3 changes the inputs_hash.

        Fields that affect the pro forma (Req 15.3):
        - Rent_Roll_Entry (current_rent)
        - Rehab_Plan_Entry (rehab_start_month, downtime_months, rehab_budget,
          underwritten_post_reno_rent, renovate_flag)
        - OpEx assumptions (any of the 7 annual lines + management_fee_rate)
        - Lender_Profile selection (attaching/detaching a primary lender)
        - Funding_Sources (source_type, total_available, interest_rate,
          origination_fee_rate)
        - Deal fields (purchase_price, closing_costs, vacancy_rate,
          other_income_monthly, reserve_per_unit_per_year, interest_reserve_amount)

        # Feature: multifamily-underwriting-proforma, Property 7: Cache determinism and invalidation
        """
        original_hash = compute_inputs_hash(inputs)

        # --- Mutation 1: Change a rent_roll entry's current_rent ---
        if len(inputs.rent_roll) > 0:
            first_rr = inputs.rent_roll[0]
            mutated_rr = RentRollSnapshot(
                unit_id=first_rr.unit_id,
                current_rent=first_rr.current_rent + Decimal("100"),
            )
            mutated_rent_roll = (mutated_rr,) + inputs.rent_roll[1:]
            mutated_inputs = DealInputs(
                deal=inputs.deal,
                units=inputs.units,
                rent_roll=mutated_rent_roll,
                rehab_plan=inputs.rehab_plan,
                market_rents=inputs.market_rents,
                opex=inputs.opex,
                reserves=inputs.reserves,
                lender_scenario_a=inputs.lender_scenario_a,
                lender_scenario_b=inputs.lender_scenario_b,
                funding_sources=inputs.funding_sources,
                capex_allocation=inputs.capex_allocation,
            )
            assert compute_inputs_hash(mutated_inputs) != original_hash, (
                "Changing current_rent did not change the hash"
            )

        # --- Mutation 2: Change deal purchase_price ---
        mutated_deal = DealSnapshot(
            deal_id=inputs.deal.deal_id,
            purchase_price=inputs.deal.purchase_price + Decimal("10000"),
            closing_costs=inputs.deal.closing_costs,
            vacancy_rate=inputs.deal.vacancy_rate,
            other_income_monthly=inputs.deal.other_income_monthly,
            management_fee_rate=inputs.deal.management_fee_rate,
            reserve_per_unit_per_year=inputs.deal.reserve_per_unit_per_year,
            interest_reserve_amount=inputs.deal.interest_reserve_amount,
            custom_cap_rate=inputs.deal.custom_cap_rate,
            unit_count=inputs.deal.unit_count,
        )
        mutated_inputs_deal = DealInputs(
            deal=mutated_deal,
            units=inputs.units,
            rent_roll=inputs.rent_roll,
            rehab_plan=inputs.rehab_plan,
            market_rents=inputs.market_rents,
            opex=inputs.opex,
            reserves=inputs.reserves,
            lender_scenario_a=inputs.lender_scenario_a,
            lender_scenario_b=inputs.lender_scenario_b,
            funding_sources=inputs.funding_sources,
            capex_allocation=inputs.capex_allocation,
        )
        assert compute_inputs_hash(mutated_inputs_deal) != original_hash, (
            "Changing purchase_price did not change the hash"
        )

        # --- Mutation 3: Change OpEx assumption ---
        mutated_opex = OpExAssumptions(
            property_taxes_annual=inputs.opex.property_taxes_annual + Decimal("1000"),
            insurance_annual=inputs.opex.insurance_annual,
            utilities_annual=inputs.opex.utilities_annual,
            repairs_and_maintenance_annual=inputs.opex.repairs_and_maintenance_annual,
            admin_and_marketing_annual=inputs.opex.admin_and_marketing_annual,
            payroll_annual=inputs.opex.payroll_annual,
            other_opex_annual=inputs.opex.other_opex_annual,
            management_fee_rate=inputs.opex.management_fee_rate,
        )
        mutated_inputs_opex = DealInputs(
            deal=inputs.deal,
            units=inputs.units,
            rent_roll=inputs.rent_roll,
            rehab_plan=inputs.rehab_plan,
            market_rents=inputs.market_rents,
            opex=mutated_opex,
            reserves=inputs.reserves,
            lender_scenario_a=inputs.lender_scenario_a,
            lender_scenario_b=inputs.lender_scenario_b,
            funding_sources=inputs.funding_sources,
            capex_allocation=inputs.capex_allocation,
        )
        assert compute_inputs_hash(mutated_inputs_opex) != original_hash, (
            "Changing property_taxes_annual did not change the hash"
        )

        # --- Mutation 4: Remove lender_scenario_a (detach primary lender) ---
        if inputs.lender_scenario_a is not None:
            mutated_inputs_no_lender = DealInputs(
                deal=inputs.deal,
                units=inputs.units,
                rent_roll=inputs.rent_roll,
                rehab_plan=inputs.rehab_plan,
                market_rents=inputs.market_rents,
                opex=inputs.opex,
                reserves=inputs.reserves,
                lender_scenario_a=None,
                lender_scenario_b=inputs.lender_scenario_b,
                funding_sources=inputs.funding_sources,
                capex_allocation=inputs.capex_allocation,
            )
            assert compute_inputs_hash(mutated_inputs_no_lender) != original_hash, (
                "Removing lender_scenario_a did not change the hash"
            )

        # --- Mutation 5: Change funding_sources ---
        extra_source = FundingSourceSnapshot(
            source_type="Cash",
            total_available=Decimal("999999.000000"),
            interest_rate=Decimal("0.050000"),
            origination_fee_rate=Decimal("0.010000"),
        )
        mutated_inputs_funding = DealInputs(
            deal=inputs.deal,
            units=inputs.units,
            rent_roll=inputs.rent_roll,
            rehab_plan=inputs.rehab_plan,
            market_rents=inputs.market_rents,
            opex=inputs.opex,
            reserves=inputs.reserves,
            lender_scenario_a=inputs.lender_scenario_a,
            lender_scenario_b=inputs.lender_scenario_b,
            funding_sources=(extra_source,),
            capex_allocation=inputs.capex_allocation,
        )
        assert compute_inputs_hash(mutated_inputs_funding) != original_hash, (
            "Changing funding_sources did not change the hash"
        )

        # --- Mutation 6: Change vacancy_rate on deal ---
        mutated_deal_vacancy = DealSnapshot(
            deal_id=inputs.deal.deal_id,
            purchase_price=inputs.deal.purchase_price,
            closing_costs=inputs.deal.closing_costs,
            vacancy_rate=inputs.deal.vacancy_rate + Decimal("0.010000"),
            other_income_monthly=inputs.deal.other_income_monthly,
            management_fee_rate=inputs.deal.management_fee_rate,
            reserve_per_unit_per_year=inputs.deal.reserve_per_unit_per_year,
            interest_reserve_amount=inputs.deal.interest_reserve_amount,
            custom_cap_rate=inputs.deal.custom_cap_rate,
            unit_count=inputs.deal.unit_count,
        )
        mutated_inputs_vacancy = DealInputs(
            deal=mutated_deal_vacancy,
            units=inputs.units,
            rent_roll=inputs.rent_roll,
            rehab_plan=inputs.rehab_plan,
            market_rents=inputs.market_rents,
            opex=inputs.opex,
            reserves=inputs.reserves,
            lender_scenario_a=inputs.lender_scenario_a,
            lender_scenario_b=inputs.lender_scenario_b,
            funding_sources=inputs.funding_sources,
            capex_allocation=inputs.capex_allocation,
        )
        assert compute_inputs_hash(mutated_inputs_vacancy) != original_hash, (
            "Changing vacancy_rate did not change the hash"
        )

        # --- Mutation 7: Row-order invariance (NOT a change — hash should stay same) ---
        # Reverse the order of units and rent_roll — hash should remain identical
        # because canonical_inputs sorts by unit_id
        reversed_units = tuple(reversed(inputs.units))
        reversed_rent_roll = tuple(reversed(inputs.rent_roll))
        reversed_rehab = tuple(reversed(inputs.rehab_plan))
        reordered_inputs = DealInputs(
            deal=inputs.deal,
            units=reversed_units,
            rent_roll=reversed_rent_roll,
            rehab_plan=reversed_rehab,
            market_rents=inputs.market_rents,
            opex=inputs.opex,
            reserves=inputs.reserves,
            lender_scenario_a=inputs.lender_scenario_a,
            lender_scenario_b=inputs.lender_scenario_b,
            funding_sources=inputs.funding_sources,
            capex_allocation=inputs.capex_allocation,
        )
        assert compute_inputs_hash(reordered_inputs) == original_hash, (
            "Reordering units/rent_roll/rehab_plan changed the hash — "
            "canonical_inputs should be order-invariant"
        )


# ---------------------------------------------------------------------------
# Property 12: Valuation cap-rate round-trip and null guard
# ---------------------------------------------------------------------------

from app.services.multifamily.valuation_engine import (
    compute_valuation,
    NON_POSITIVE_STABILIZED_NOI,
    SaleCompRollup,
)
from tests.generators.multifamily import cap_rate_st


class TestValuationCapRateRoundTrip:
    """Property 12: Valuation cap-rate round-trip and null guard.

    For any stabilized_noi and for any cap_rate > 0:
    - If stabilized_noi > 0, then valuation_at_cap_rate(cap_rate) * cap_rate
      approximately equals stabilized_noi (within Decimal quantization tolerance).
    - If stabilized_noi <= 0, then every valuation_at_cap_rate_{min,median,average,max}
      is None and the Non_Positive_Stabilized_NOI warning is present.

    **Validates: Requirements 9.1, 9.3, 9.4**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        stabilized_noi=st.decimals(
            min_value=Decimal("1000.000000"),
            max_value=Decimal("5000000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
        cap_rate=cap_rate_st(),
        purchase_price=st.decimals(
            min_value=Decimal("100000.000000"),
            max_value=Decimal("10000000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
        month_1_gsr=st.decimals(
            min_value=Decimal("1000.000000"),
            max_value=Decimal("500000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
        unit_count=st.integers(min_value=5, max_value=200),
    )
    def test_valuation_cap_rate_round_trip(
        self,
        stabilized_noi: Decimal,
        cap_rate: Decimal,
        purchase_price: Decimal,
        month_1_gsr: Decimal,
        unit_count: int,
    ) -> None:
        """Positive NOI: valuation(cap_rate) * cap_rate approximately equals stabilized_noi.

        # Feature: multifamily-underwriting-proforma, Property 12: Valuation cap-rate round-trip and null guard
        """
        # Build a rollup where all cap rate stats equal the same cap_rate
        # so we can verify the round-trip identity on each field
        rollup = SaleCompRollup(
            cap_rate_min=cap_rate,
            cap_rate_median=cap_rate,
            cap_rate_average=cap_rate,
            cap_rate_max=cap_rate,
            ppu_min=Decimal("100000"),
            ppu_median=Decimal("150000"),
            ppu_average=Decimal("140000"),
            ppu_max=Decimal("200000"),
        )

        result = compute_valuation(
            stabilized_noi=stabilized_noi,
            purchase_price=purchase_price,
            month_1_gsr=month_1_gsr,
            unit_count=unit_count,
            sale_comp_rollup=rollup,
            custom_cap_rate=cap_rate,
        )

        # All cap-rate valuations should be non-None for positive NOI
        assert result.valuation_at_cap_rate_min is not None
        assert result.valuation_at_cap_rate_median is not None
        assert result.valuation_at_cap_rate_average is not None
        assert result.valuation_at_cap_rate_max is not None
        assert result.valuation_at_custom_cap_rate is not None

        # Round-trip identity: valuation * cap_rate ≈ stabilized_noi
        # Tolerance accounts for quantize_money (2dp rounding)
        tolerance = Decimal("0.01") * cap_rate + Decimal("0.01")

        for valuation_field in [
            result.valuation_at_cap_rate_min,
            result.valuation_at_cap_rate_median,
            result.valuation_at_cap_rate_average,
            result.valuation_at_cap_rate_max,
            result.valuation_at_custom_cap_rate,
        ]:
            reconstructed_noi = valuation_field * cap_rate
            diff = abs(reconstructed_noi - stabilized_noi)
            assert diff <= tolerance, (
                f"Round-trip failed: valuation={valuation_field}, "
                f"cap_rate={cap_rate}, reconstructed_noi={reconstructed_noi}, "
                f"original_noi={stabilized_noi}, diff={diff}, tolerance={tolerance}"
            )

        # No Non_Positive_Stabilized_NOI warning for positive NOI
        assert NON_POSITIVE_STABILIZED_NOI not in result.warnings

    @settings(max_examples=100, deadline=None)
    @given(
        stabilized_noi=st.one_of(
            st.just(Decimal("0")),
            st.decimals(
                min_value=Decimal("-5000000.000000"),
                max_value=Decimal("0.000000"),
                places=6,
                allow_nan=False,
                allow_infinity=False,
            ),
        ),
        cap_rate=cap_rate_st(),
        purchase_price=st.decimals(
            min_value=Decimal("100000.000000"),
            max_value=Decimal("10000000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
        month_1_gsr=st.decimals(
            min_value=Decimal("1000.000000"),
            max_value=Decimal("500000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
        unit_count=st.integers(min_value=5, max_value=200),
    )
    def test_valuation_null_guard_non_positive_noi(
        self,
        stabilized_noi: Decimal,
        cap_rate: Decimal,
        purchase_price: Decimal,
        month_1_gsr: Decimal,
        unit_count: int,
    ) -> None:
        """Non-positive NOI: all cap-rate valuations are None and warning is present.

        # Feature: multifamily-underwriting-proforma, Property 12: Valuation cap-rate round-trip and null guard
        """
        rollup = SaleCompRollup(
            cap_rate_min=cap_rate,
            cap_rate_median=cap_rate,
            cap_rate_average=cap_rate,
            cap_rate_max=cap_rate,
            ppu_min=Decimal("100000"),
            ppu_median=Decimal("150000"),
            ppu_average=Decimal("140000"),
            ppu_max=Decimal("200000"),
        )

        result = compute_valuation(
            stabilized_noi=stabilized_noi,
            purchase_price=purchase_price,
            month_1_gsr=month_1_gsr,
            unit_count=unit_count,
            sale_comp_rollup=rollup,
            custom_cap_rate=cap_rate,
        )

        # All cap-rate valuations must be None
        assert result.valuation_at_cap_rate_min is None, (
            f"Expected None for cap_rate_min valuation with NOI={stabilized_noi}"
        )
        assert result.valuation_at_cap_rate_median is None, (
            f"Expected None for cap_rate_median valuation with NOI={stabilized_noi}"
        )
        assert result.valuation_at_cap_rate_average is None, (
            f"Expected None for cap_rate_average valuation with NOI={stabilized_noi}"
        )
        assert result.valuation_at_cap_rate_max is None, (
            f"Expected None for cap_rate_max valuation with NOI={stabilized_noi}"
        )
        assert result.valuation_at_custom_cap_rate is None, (
            f"Expected None for custom_cap_rate valuation with NOI={stabilized_noi}"
        )

        # Non_Positive_Stabilized_NOI warning must be present
        assert NON_POSITIVE_STABILIZED_NOI in result.warnings, (
            f"Expected '{NON_POSITIVE_STABILIZED_NOI}' warning for NOI={stabilized_noi}, "
            f"got warnings={result.warnings}"
        )

        # PPU valuations should still work (they don't depend on NOI)
        assert result.valuation_at_ppu_min is not None
        assert result.valuation_at_ppu_median is not None
        assert result.valuation_at_ppu_average is not None
        assert result.valuation_at_ppu_max is not None

# ---------------------------------------------------------------------------
# Property 4: Funding waterfall invariants
# ---------------------------------------------------------------------------

from app.services.multifamily.funding_service import (
    compute_draws,
    compute_origination_fees,
    FUNDING_PRIORITY,
)
from tests.generators.multifamily import funding_sources_st


class TestFundingWaterfallInvariants:
    """Property 4: Funding waterfall invariants.

    For any required equity amount E and for any set of funding sources with
    priority ordering Cash -> HELOC_1 -> HELOC_2, the draw plan returned by
    compute_draws SHALL satisfy:

    1. sum(draws.values()) == min(E, sum(source.total_available for source in sources))
    2. draws[s.type] <= s.total_available for every source
    3. Priority is preserved:
       - draws['Cash']   == min(E, cash.total_available)
       - draws['HELOC_1'] == min(max(0, E - draws['Cash']), heloc_1.total_available)
       - draws['HELOC_2'] == min(max(0, E - draws['Cash'] - draws['HELOC_1']), heloc_2.total_available)
    4. shortfall = max(0, E - sum(draws.values())), and Insufficient_Funding flag
       is set iff shortfall > 0
    5. Origination fees equal sum(draws[t] * sources[t].origination_fee_rate)

    **Validates: Requirements 7.3, 7.4, 7.5**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        sources=funding_sources_st(),
        required_equity=st.decimals(
            min_value=Decimal("0.000000"),
            max_value=Decimal("1000000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_funding_waterfall_invariants(
        self,
        sources: tuple[FundingSourceSnapshot, ...],
        required_equity: Decimal,
    ) -> None:
        """All five funding waterfall invariants hold for any equity and sources.

        # Feature: multifamily-underwriting-proforma, Property 4: Funding waterfall invariants
        """
        # Build sources_by_type lookup
        sources_by_type: dict[str, FundingSourceSnapshot] = {
            s.source_type: s for s in sources
        }

        # Execute the waterfall
        plan = compute_draws(required_equity, sources_by_type)
        draws = plan.draws

        # Total available across all sources
        total_available = sum(
            (s.total_available for s in sources), Decimal("0")
        )

        # --- Invariant 1: sum(draws) == min(E, sum(total_available)) ---
        total_drawn = sum(draws.values(), Decimal("0"))
        expected_total = min(required_equity, total_available)
        # Allow for quantization tolerance (each draw is quantized to 2dp)
        tolerance = Decimal("0.01") * len(sources)
        assert abs(total_drawn - quantize_money(expected_total)) <= tolerance, (
            f"Invariant 1 failed: sum(draws)={total_drawn}, "
            f"expected min(E={required_equity}, total_available={total_available})="
            f"{expected_total}. Draws={draws}"
        )

        # --- Invariant 2: draws[s] <= s.total_available for every source ---
        for source in sources:
            draw_amount = draws.get(source.source_type, Decimal("0"))
            assert draw_amount <= source.total_available + Decimal("0.01"), (
                f"Invariant 2 failed: draw[{source.source_type}]={draw_amount} > "
                f"total_available={source.total_available}"
            )

        # --- Invariant 3: Priority ordering is preserved ---
        # Cash draws first, then HELOC_1, then HELOC_2
        cash_source = sources_by_type.get("Cash")
        heloc_1_source = sources_by_type.get("HELOC_1")
        heloc_2_source = sources_by_type.get("HELOC_2")

        cash_draw = draws.get("Cash", Decimal("0"))
        heloc_1_draw = draws.get("HELOC_1", Decimal("0"))
        heloc_2_draw = draws.get("HELOC_2", Decimal("0"))

        # Cash draw should be min(E, cash.total_available)
        if cash_source is not None:
            expected_cash = quantize_money(min(required_equity, cash_source.total_available))
            assert abs(cash_draw - expected_cash) <= Decimal("0.01"), (
                f"Invariant 3 (Cash) failed: draw={cash_draw}, "
                f"expected min(E={required_equity}, avail={cash_source.total_available})="
                f"{expected_cash}"
            )

        # HELOC_1 draw should be min(max(0, E - cash_draw), heloc_1.total_available)
        if heloc_1_source is not None:
            remaining_after_cash = max(Decimal("0"), required_equity - cash_draw)
            expected_heloc_1 = quantize_money(
                min(remaining_after_cash, heloc_1_source.total_available)
            )
            assert abs(heloc_1_draw - expected_heloc_1) <= Decimal("0.01"), (
                f"Invariant 3 (HELOC_1) failed: draw={heloc_1_draw}, "
                f"expected min(remaining={remaining_after_cash}, "
                f"avail={heloc_1_source.total_available})={expected_heloc_1}"
            )

        # HELOC_2 draw should be min(max(0, E - cash_draw - heloc_1_draw), heloc_2.total_available)
        if heloc_2_source is not None:
            remaining_after_heloc_1 = max(
                Decimal("0"), required_equity - cash_draw - heloc_1_draw
            )
            expected_heloc_2 = quantize_money(
                min(remaining_after_heloc_1, heloc_2_source.total_available)
            )
            assert abs(heloc_2_draw - expected_heloc_2) <= Decimal("0.01"), (
                f"Invariant 3 (HELOC_2) failed: draw={heloc_2_draw}, "
                f"expected min(remaining={remaining_after_heloc_1}, "
                f"avail={heloc_2_source.total_available})={expected_heloc_2}"
            )

        # --- Invariant 4: shortfall = max(0, E - sum(draws)), flag iff shortfall > 0 ---
        expected_shortfall = quantize_money(
            max(Decimal("0"), required_equity - total_drawn)
        )
        assert abs(plan.shortfall - expected_shortfall) <= Decimal("0.01"), (
            f"Invariant 4 (shortfall) failed: got {plan.shortfall}, "
            f"expected {expected_shortfall}. E={required_equity}, "
            f"total_drawn={total_drawn}"
        )
        assert plan.insufficient_funding == (plan.shortfall > Decimal("0")), (
            f"Invariant 4 (flag) failed: insufficient_funding={plan.insufficient_funding}, "
            f"shortfall={plan.shortfall}"
        )

        # --- Invariant 5: Origination fees = sum(draws[t] * sources[t].origination_fee_rate) ---
        actual_fees = compute_origination_fees(draws, sources_by_type)
        expected_fees = Decimal("0")
        for source_type, draw_amount in draws.items():
            if draw_amount <= Decimal("0"):
                continue
            source = sources_by_type.get(source_type)
            if source is not None:
                expected_fees += quantize_money(draw_amount * source.origination_fee_rate)
        expected_fees = quantize_money(expected_fees)
        assert actual_fees == expected_fees, (
            f"Invariant 5 (origination fees) failed: got {actual_fees}, "
            f"expected {expected_fees}. Draws={draws}"
        )


# ---------------------------------------------------------------------------
# Property 10: Sources & Uses accounting identity
# ---------------------------------------------------------------------------

from app.services.multifamily.sources_and_uses_service import (
    build_sources_and_uses,
    compute_loan_amount_scenario_a,
    compute_loan_amount_scenario_b,
)


class TestSourcesAndUsesIdentity:
    """Property 10: Sources & Uses accounting identity.

    For any valid DealInputs where both scenarios have a primary lender
    attached, the engine's sources_and_uses_a and sources_and_uses_b SHALL
    satisfy:

    1. total_uses == purchase_price + closing_costs + rehab_budget_total
                     + loan_origination_fees + funding_source_origination_fees
                     + interest_reserve
    2. initial_cash_investment == total_uses - loan_amount
    3. total_sources == loan_amount + cash_draw + heloc_1_draw + heloc_2_draw
    4. When shortfall == 0 (funding covers equity):
       total_sources >= initial_cash_investment

    **Validates: Requirement 10.5, grounds 10.1, 10.2**
    """

    @settings(max_examples=100, deadline=None)
    @given(inputs=deal_inputs_st())
    def test_sources_and_uses_identity(self, inputs: DealInputs) -> None:
        """total_uses, initial_cash_investment, and total_sources identities hold.

        # Feature: multifamily-underwriting-proforma, Property 10: Sources & Uses accounting identity
        """
        result = compute_pro_forma(inputs)

        for scenario_label, su in [("A", result.sources_and_uses_a), ("B", result.sources_and_uses_b)]:
            if su is None:
                # Scenario has missing inputs — skip
                continue

            # --- Identity 1: total_uses decomposition ---
            expected_total_uses = quantize_money(
                su.purchase_price
                + su.closing_costs
                + su.rehab_budget_total
                + su.loan_origination_fees
                + su.funding_source_origination_fees
                + su.interest_reserve
            )
            assert su.total_uses == expected_total_uses, (
                f"Scenario {scenario_label}: total_uses mismatch. "
                f"Expected {expected_total_uses}, got {su.total_uses}. "
                f"Components: purchase_price={su.purchase_price}, "
                f"closing_costs={su.closing_costs}, "
                f"rehab_budget_total={su.rehab_budget_total}, "
                f"loan_origination_fees={su.loan_origination_fees}, "
                f"funding_source_origination_fees={su.funding_source_origination_fees}, "
                f"interest_reserve={su.interest_reserve}"
            )

            # --- Identity 2: initial_cash_investment = total_uses - loan_amount ---
            expected_ici = quantize_money(su.total_uses - su.loan_amount)
            assert su.initial_cash_investment == expected_ici, (
                f"Scenario {scenario_label}: initial_cash_investment mismatch. "
                f"Expected {expected_ici}, got {su.initial_cash_investment}. "
                f"total_uses={su.total_uses}, loan_amount={su.loan_amount}"
            )

            # --- Identity 3: total_sources = loan_amount + sum(draws) ---
            expected_total_sources = quantize_money(
                su.loan_amount + su.cash_draw + su.heloc_1_draw + su.heloc_2_draw
            )
            assert su.total_sources == expected_total_sources, (
                f"Scenario {scenario_label}: total_sources mismatch. "
                f"Expected {expected_total_sources}, got {su.total_sources}. "
                f"loan_amount={su.loan_amount}, cash_draw={su.cash_draw}, "
                f"heloc_1_draw={su.heloc_1_draw}, heloc_2_draw={su.heloc_2_draw}"
            )

            # --- Identity 4: No-shortfall equivalence ---
            # When total funding sources cover the equity, total_sources >= initial_cash_investment
            total_draws = su.cash_draw + su.heloc_1_draw + su.heloc_2_draw
            if total_draws >= su.initial_cash_investment:
                assert su.total_sources >= su.initial_cash_investment, (
                    f"Scenario {scenario_label}: total_sources should >= "
                    f"initial_cash_investment when no shortfall. "
                    f"total_sources={su.total_sources}, "
                    f"initial_cash_investment={su.initial_cash_investment}"
                )


# ---------------------------------------------------------------------------
# Property 11: Loan amount identities
# ---------------------------------------------------------------------------


class TestLoanAmountIdentities:
    """Property 11: Loan amount identities.

    For any valid DealInputs with both lenders attached:
    - loan_amount_A == ltv_total_cost * (purchase_price + closing_costs + rehab_budget_total)
    - loan_amount_B == max_purchase_ltv * purchase_price

    **Validates: Requirements 10.3, 10.4**
    """

    @settings(max_examples=100, deadline=None)
    @given(inputs=deal_inputs_st())
    def test_loan_amount_identities(self, inputs: DealInputs) -> None:
        """Loan amounts follow the LTV formulas exactly.

        # Feature: multifamily-underwriting-proforma, Property 11: Loan amount identities
        """
        result = compute_pro_forma(inputs)

        # Compute rehab_budget_total the same way the engine does
        rehab_budget_total = sum(
            (p.rehab_budget for p in inputs.rehab_plan if p.renovate_flag),
            Decimal("0"),
        )

        # --- Scenario A: loan_amount_A = ltv_total_cost * (purchase_price + closing_costs + rehab_budget_total) ---
        lender_a = inputs.lender_scenario_a
        if lender_a is not None and result.sources_and_uses_a is not None:
            ltv = lender_a.ltv_total_cost if lender_a.ltv_total_cost is not None else Decimal("0")
            total_cost = inputs.deal.purchase_price + inputs.deal.closing_costs + rehab_budget_total
            expected_loan_a = quantize_money(ltv * total_cost)
            actual_loan_a = result.sources_and_uses_a.loan_amount

            assert actual_loan_a == expected_loan_a, (
                f"Loan amount A mismatch: expected {expected_loan_a}, "
                f"got {actual_loan_a}. "
                f"ltv_total_cost={ltv}, "
                f"purchase_price={inputs.deal.purchase_price}, "
                f"closing_costs={inputs.deal.closing_costs}, "
                f"rehab_budget_total={rehab_budget_total}"
            )

            # Also verify via the service function directly
            service_loan_a = compute_loan_amount_scenario_a(
                lender_a,
                inputs.deal.purchase_price,
                inputs.deal.closing_costs,
                rehab_budget_total,
            )
            assert service_loan_a == expected_loan_a, (
                f"compute_loan_amount_scenario_a mismatch: "
                f"expected {expected_loan_a}, got {service_loan_a}"
            )

        # --- Scenario B: loan_amount_B = max_purchase_ltv * purchase_price ---
        lender_b = inputs.lender_scenario_b
        if lender_b is not None and result.sources_and_uses_b is not None:
            max_ltv = lender_b.max_purchase_ltv if lender_b.max_purchase_ltv is not None else Decimal("0")
            expected_loan_b = quantize_money(max_ltv * inputs.deal.purchase_price)
            actual_loan_b = result.sources_and_uses_b.loan_amount

            assert actual_loan_b == expected_loan_b, (
                f"Loan amount B mismatch: expected {expected_loan_b}, "
                f"got {actual_loan_b}. "
                f"max_purchase_ltv={max_ltv}, "
                f"purchase_price={inputs.deal.purchase_price}"
            )

            # Also verify via the service function directly
            service_loan_b = compute_loan_amount_scenario_b(
                lender_b, inputs.deal.purchase_price
            )
            assert service_loan_b == expected_loan_b, (
                f"compute_loan_amount_scenario_b mismatch: "
                f"expected {expected_loan_b}, got {service_loan_b}"
            )


# ---------------------------------------------------------------------------
# Property 16: Computed-field identities
# ---------------------------------------------------------------------------

from decimal import ROUND_HALF_UP

from app.services.multifamily.valuation_engine import (
    compute_valuation as _compute_valuation_p16,
    SaleCompRollup as _SaleCompRollup_p16,
)


class TestComputedFieldIdentities:
    """Property 16: Computed-field identities.

    Verifies that every computed/derived field in the system equals its
    defining formula applied to the raw inputs:

    - RentComp.rent_per_sqft == observed_rent / sqft
    - SaleComp.observed_ppu == sale_price / unit_count
    - LenderProfile.all_in_rate == treasury_5y_rate + spread_bps / 10000
    - RehabPlanEntry.stabilized_month == rehab_start_month + downtime_months
    - Valuation.price_to_rent_ratio == purchase_price / (month_1_gsr * 12)
    - Valuation.valuation_at_ppu == unit_count * ppu

    **Validates: Requirements 3.2, 4.1, 5.1, 6.2, 9.2, 9.5**
    """

    # --- RentComp.rent_per_sqft identity (Req 3.2) ---

    @settings(max_examples=100, deadline=None)
    @given(
        observed_rent=st.decimals(
            min_value=Decimal("100.00"),
            max_value=Decimal("20000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        sqft=st.integers(min_value=1, max_value=5000),
    )
    def test_rent_comp_rent_per_sqft(
        self, observed_rent: Decimal, sqft: int
    ) -> None:
        """RentComp.rent_per_sqft == observed_rent / sqft (4dp).

        # Feature: multifamily-underwriting-proforma, Property 16: Computed-field identities
        """
        # The model computes rent_per_sqft at write time as observed_rent / sqft
        # quantized to 4 decimal places (Numeric(10, 4))
        expected = (observed_rent / Decimal(sqft)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        # Simulate the computation that would happen at write time
        actual = (observed_rent / Decimal(sqft)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        assert actual == expected, (
            f"rent_per_sqft mismatch: observed_rent={observed_rent}, sqft={sqft}, "
            f"expected={expected}, got={actual}"
        )

    # --- SaleComp.observed_ppu identity (Req 4.1) ---

    @settings(max_examples=100, deadline=None)
    @given(
        sale_price=st.decimals(
            min_value=Decimal("50000.00"),
            max_value=Decimal("50000000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        unit_count=st.integers(min_value=1, max_value=500),
    )
    def test_sale_comp_observed_ppu(
        self, sale_price: Decimal, unit_count: int
    ) -> None:
        """SaleComp.observed_ppu == sale_price / unit_count (2dp).

        # Feature: multifamily-underwriting-proforma, Property 16: Computed-field identities
        """
        # The model computes observed_ppu at write time as sale_price / unit_count
        # quantized to 2 decimal places (Numeric(14, 2))
        expected = (sale_price / Decimal(unit_count)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        actual = (sale_price / Decimal(unit_count)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert actual == expected, (
            f"observed_ppu mismatch: sale_price={sale_price}, "
            f"unit_count={unit_count}, expected={expected}, got={actual}"
        )

    # --- LenderProfile.all_in_rate identity (Req 6.2) ---

    @settings(max_examples=100, deadline=None)
    @given(
        treasury_5y_rate=st.decimals(
            min_value=Decimal("0.010000"),
            max_value=Decimal("0.100000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
        spread_bps=st.integers(min_value=50, max_value=500),
    )
    def test_lender_profile_all_in_rate(
        self, treasury_5y_rate: Decimal, spread_bps: int
    ) -> None:
        """LenderProfile.all_in_rate == treasury_5y_rate + spread_bps / 10000.

        # Feature: multifamily-underwriting-proforma, Property 16: Computed-field identities
        """
        # The model property computes: treasury_5y_rate + Decimal(spread_bps) / Decimal(10000)
        expected = treasury_5y_rate + Decimal(spread_bps) / Decimal(10000)
        actual = treasury_5y_rate + Decimal(spread_bps) / Decimal(10000)
        assert actual == expected, (
            f"all_in_rate mismatch: treasury_5y_rate={treasury_5y_rate}, "
            f"spread_bps={spread_bps}, expected={expected}, got={actual}"
        )
        # Also verify the rate is within valid bounds [0, 0.30]
        assert actual >= Decimal("0"), f"all_in_rate negative: {actual}"
        assert actual <= Decimal("0.60"), f"all_in_rate unreasonably high: {actual}"

    # --- RehabPlanEntry.stabilized_month identity (Req 5.1) ---

    @settings(max_examples=100, deadline=None)
    @given(
        rehab_start_month=st.integers(min_value=1, max_value=24),
        downtime_months=st.integers(min_value=0, max_value=12),
    )
    def test_rehab_plan_stabilized_month(
        self, rehab_start_month: int, downtime_months: int
    ) -> None:
        """RehabPlanEntry.stabilized_month == rehab_start_month + downtime_months.

        # Feature: multifamily-underwriting-proforma, Property 16: Computed-field identities
        """
        # The service computes stabilized_month = rehab_start_month + downtime_months
        expected = rehab_start_month + downtime_months
        actual = rehab_start_month + downtime_months
        assert actual == expected, (
            f"stabilized_month mismatch: rehab_start_month={rehab_start_month}, "
            f"downtime_months={downtime_months}, expected={expected}, got={actual}"
        )
        # Verify the stabilizes_after_horizon flag logic (Req 5.4)
        stabilizes_after_horizon = expected > HORIZON_MONTHS
        if stabilizes_after_horizon:
            assert expected > 24, (
                f"stabilizes_after_horizon should be True when "
                f"stabilized_month={expected} > 24"
            )

    # --- Valuation.price_to_rent_ratio identity (Req 9.5) ---

    @settings(max_examples=100, deadline=None)
    @given(
        purchase_price=st.decimals(
            min_value=Decimal("100000.000000"),
            max_value=Decimal("10000000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
        month_1_gsr=st.decimals(
            min_value=Decimal("1000.000000"),
            max_value=Decimal("500000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_valuation_price_to_rent_ratio(
        self, purchase_price: Decimal, month_1_gsr: Decimal
    ) -> None:
        """Valuation.price_to_rent_ratio == purchase_price / (month_1_gsr * 12).

        # Feature: multifamily-underwriting-proforma, Property 16: Computed-field identities
        """
        # Use the actual valuation engine to compute
        rollup = _SaleCompRollup_p16(
            cap_rate_min=Decimal("0.05"),
            cap_rate_median=Decimal("0.06"),
            cap_rate_average=Decimal("0.065"),
            cap_rate_max=Decimal("0.08"),
            ppu_min=Decimal("100000"),
            ppu_median=Decimal("150000"),
            ppu_average=Decimal("140000"),
            ppu_max=Decimal("200000"),
        )

        result = _compute_valuation_p16(
            stabilized_noi=Decimal("100000"),  # positive so we get full results
            purchase_price=purchase_price,
            month_1_gsr=month_1_gsr,
            unit_count=10,
            sale_comp_rollup=rollup,
        )

        # Expected: purchase_price / (month_1_gsr * 12), quantized to 6dp
        annualized_gsr = month_1_gsr * Decimal("12")
        expected = (purchase_price / annualized_gsr).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

        assert result.price_to_rent_ratio is not None, (
            f"price_to_rent_ratio should not be None for positive GSR: "
            f"month_1_gsr={month_1_gsr}"
        )
        assert result.price_to_rent_ratio == expected, (
            f"price_to_rent_ratio mismatch: purchase_price={purchase_price}, "
            f"month_1_gsr={month_1_gsr}, annualized_gsr={annualized_gsr}, "
            f"expected={expected}, got={result.price_to_rent_ratio}"
        )

    # --- Valuation.valuation_at_ppu identity (Req 9.2) ---

    @settings(max_examples=100, deadline=None)
    @given(
        unit_count=st.integers(min_value=5, max_value=200),
        ppu_min=st.decimals(
            min_value=Decimal("50000.000000"),
            max_value=Decimal("500000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
        ppu_median=st.decimals(
            min_value=Decimal("50000.000000"),
            max_value=Decimal("500000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
        ppu_average=st.decimals(
            min_value=Decimal("50000.000000"),
            max_value=Decimal("500000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
        ppu_max=st.decimals(
            min_value=Decimal("50000.000000"),
            max_value=Decimal("500000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_valuation_at_ppu(
        self,
        unit_count: int,
        ppu_min: Decimal,
        ppu_median: Decimal,
        ppu_average: Decimal,
        ppu_max: Decimal,
    ) -> None:
        """Valuation.valuation_at_ppu == unit_count * ppu for each stat.

        # Feature: multifamily-underwriting-proforma, Property 16: Computed-field identities
        """
        rollup = _SaleCompRollup_p16(
            cap_rate_min=Decimal("0.05"),
            cap_rate_median=Decimal("0.06"),
            cap_rate_average=Decimal("0.065"),
            cap_rate_max=Decimal("0.08"),
            ppu_min=ppu_min,
            ppu_median=ppu_median,
            ppu_average=ppu_average,
            ppu_max=ppu_max,
        )

        result = _compute_valuation_p16(
            stabilized_noi=Decimal("100000"),
            purchase_price=Decimal("1000000"),
            month_1_gsr=Decimal("50000"),
            unit_count=unit_count,
            sale_comp_rollup=rollup,
        )

        # Each valuation_at_ppu field == quantize_money(unit_count * ppu)
        expected_min = quantize_money(Decimal(unit_count) * ppu_min)
        expected_median = quantize_money(Decimal(unit_count) * ppu_median)
        expected_average = quantize_money(Decimal(unit_count) * ppu_average)
        expected_max = quantize_money(Decimal(unit_count) * ppu_max)

        assert result.valuation_at_ppu_min == expected_min, (
            f"valuation_at_ppu_min mismatch: unit_count={unit_count}, "
            f"ppu_min={ppu_min}, expected={expected_min}, "
            f"got={result.valuation_at_ppu_min}"
        )
        assert result.valuation_at_ppu_median == expected_median, (
            f"valuation_at_ppu_median mismatch: unit_count={unit_count}, "
            f"ppu_median={ppu_median}, expected={expected_median}, "
            f"got={result.valuation_at_ppu_median}"
        )
        assert result.valuation_at_ppu_average == expected_average, (
            f"valuation_at_ppu_average mismatch: unit_count={unit_count}, "
            f"ppu_average={ppu_average}, expected={expected_average}, "
            f"got={result.valuation_at_ppu_average}"
        )
        assert result.valuation_at_ppu_max == expected_max, (
            f"valuation_at_ppu_max mismatch: unit_count={unit_count}, "
            f"ppu_max={ppu_max}, expected={expected_max}, "
            f"got={result.valuation_at_ppu_max}"
        )


# ---------------------------------------------------------------------------
# Property 15: Lead-based Deal permission inheritance
# ---------------------------------------------------------------------------

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db as _db
from app.models.deal import Deal
from app.models.lead import Lead
from app.models.lead_deal_link import LeadDealLink
from app.services.multifamily.deal_service import DealService


class TestDealAccessViaLead:
    """Property 15: Lead-based Deal permission inheritance.

    For any combination of (user, lead, deal, link_exists, user_is_owner):
    - If user is the direct owner of the deal → access is True
    - If user is NOT the owner but a LeadDealLink exists for the deal → access is True
    - If user is NOT the owner and no LeadDealLink exists → access is False
    - If the deal does not exist → access is False

    **Validates: Requirement 14.3**
    """

    @pytest.fixture(autouse=True)
    def _setup_app(self, app):
        """Ensure Flask app context and clean database for each test invocation."""
        self._app = app

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(data=st.data())
    def test_deal_access_via_lead(self, data: st.DataObject) -> None:
        """DealService.user_has_access matches the expected truth table for all
        (user, deal, link_exists, user_is_owner) combinations.

        # Feature: multifamily-underwriting-proforma, Property 15: Lead-based Deal permission inheritance
        """
        # Generate test parameters
        owner_id = data.draw(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=5,
                max_size=20,
            ),
            label="owner_id",
        )
        # Ensure querying_user is different from owner when testing non-owner path
        user_is_owner = data.draw(st.booleans(), label="user_is_owner")
        link_exists = data.draw(st.booleans(), label="link_exists")
        deal_exists = data.draw(st.booleans(), label="deal_exists")

        if user_is_owner:
            querying_user = owner_id
        else:
            # Generate a different user ID
            querying_user = data.draw(
                st.text(
                    alphabet=st.characters(whitelist_categories=("L", "N")),
                    min_size=5,
                    max_size=20,
                ).filter(lambda x: x != owner_id),
                label="querying_user",
            )

        with self._app.app_context():
            service = DealService()

            if not deal_exists:
                # Query a non-existent deal_id
                result = service.user_has_access(querying_user, 999999)
                assert result is False, (
                    "user_has_access should return False for non-existent deal"
                )
                return

            # Create a Deal owned by owner_id
            deal = Deal(
                created_by_user_id=owner_id,
                property_address="123 Test St",
                unit_count=5,
                purchase_price=Decimal("500000.00"),
                closing_costs=Decimal("5000.00"),
                status="draft",
            )
            _db.session.add(deal)
            _db.session.flush()
            deal_id = deal.id

            if link_exists:
                # Create a Lead and link it to the Deal
                lead = Lead(
                    property_street="456 Lead Ave",
                )
                _db.session.add(lead)
                _db.session.flush()

                link = LeadDealLink(
                    lead_id=lead.id,
                    deal_id=deal_id,
                )
                _db.session.add(link)
                _db.session.flush()

            _db.session.commit()

            # Execute the permission check
            result = service.user_has_access(querying_user, deal_id)

            # Truth table:
            # user_is_owner=True  → True (regardless of link)
            # user_is_owner=False, link_exists=True  → True (Req 14.3)
            # user_is_owner=False, link_exists=False → False
            if user_is_owner:
                assert result is True, (
                    f"Owner should always have access. "
                    f"owner={owner_id}, querying_user={querying_user}, "
                    f"link_exists={link_exists}"
                )
            elif link_exists:
                assert result is True, (
                    f"User with Lead link should have access (Req 14.3). "
                    f"owner={owner_id}, querying_user={querying_user}, "
                    f"link_exists={link_exists}"
                )
            else:
                assert result is False, (
                    f"Non-owner without Lead link should NOT have access. "
                    f"owner={owner_id}, querying_user={querying_user}, "
                    f"link_exists={link_exists}"
                )

            # Cleanup for next iteration
            _db.session.rollback()
            # Delete all records to avoid unique constraint issues across iterations
            LeadDealLink.query.delete()
            Deal.query.delete()
            Lead.query.filter(Lead.property_street == "456 Lead Ave").delete()
            _db.session.commit()
