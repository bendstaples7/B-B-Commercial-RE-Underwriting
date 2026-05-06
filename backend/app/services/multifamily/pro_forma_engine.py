"""
Pure-function pro forma engine for multifamily underwriting.

Computes a 24-month monthly schedule, per-unit rent schedule, debt service
for two scenarios (Construction-to-Perm and Self-Funded Renovation), and
summary metrics — all from frozen input dataclasses.

The engine MUST NOT raise on user-driven missing-input conditions; it
populates `missing_inputs_a` / `missing_inputs_b` and sets scenario summary
fields to None.

All math uses `Decimal` with documented quantization:
  - 2 decimal places for monetary values (quantize_money)
  - 6 decimal places for rate values (quantize_rate)

Requirements: 8.1-8.14, 10.6, 10.7
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.services.multifamily.pro_forma_constants import (
    HORIZON_MONTHS,
    STABILIZED_MONTHS,
    RENT_ROLL_INCOMPLETE,
    REHAB_PLAN_MISSING,
    OPEX_ASSUMPTIONS_MISSING,
    PRIMARY_LENDER_MISSING_A,
    PRIMARY_LENDER_MISSING_B,
    quantize_money,
    quantize_rate,
)
from app.services.multifamily.pro_forma_inputs import (
    DealInputs,
    LenderProfileSnapshot,
    RehabPlanSnapshot,
)
from app.services.multifamily.pro_forma_result_dc import (
    MonthlyRow,
    OpExBreakdown,
    ProFormaComputation,
    ProFormaSummary,
    SourcesAndUses,
)
from app.services.multifamily.sources_and_uses_service import (
    build_sources_and_uses,
    compute_loan_amount_scenario_a,
    compute_loan_amount_scenario_b,
)

ZERO = Decimal("0")
TWELVE = Decimal("12")
ONE = Decimal("1")


# ---------------------------------------------------------------------------
# Helper: amortizing payment
# ---------------------------------------------------------------------------


def _amortizing_payment(
    principal: Decimal, monthly_rate: Decimal, num_payments: int
) -> Decimal:
    """Compute the fixed monthly payment for a fully-amortizing loan.

    Uses the standard mortgage formula:
        P * (r * (1+r)^n) / ((1+r)^n - 1)

    Edge case: if monthly_rate == 0, returns principal / num_payments
    (straight-line repayment, avoids division by zero).

    Args:
        principal: Loan amount (Decimal).
        monthly_rate: Monthly interest rate as a decimal (e.g. 0.005 for 6% annual).
        num_payments: Total number of monthly payments.

    Returns:
        Monthly payment amount, quantized to 2 decimal places.
    """
    if num_payments <= 0:
        return ZERO

    if monthly_rate == ZERO:
        return quantize_money(principal / Decimal(num_payments))

    # (1 + r)^n
    one_plus_r_n = (ONE + monthly_rate) ** num_payments
    # P * r * (1+r)^n / ((1+r)^n - 1)
    payment = principal * (monthly_rate * one_plus_r_n) / (one_plus_r_n - ONE)
    return quantize_money(payment)


# ---------------------------------------------------------------------------
# Missing-inputs scanner (Req 8.14)
# ---------------------------------------------------------------------------


def _scan_missing_inputs(inputs: DealInputs) -> tuple[list[str], list[str]]:
    """Scan inputs and build missing_inputs lists for each scenario.

    Returns:
        (missing_inputs_a, missing_inputs_b) — lists of missing-input codes.
    """
    missing_a: list[str] = []
    missing_b: list[str] = []

    # RENT_ROLL_INCOMPLETE — fewer rent roll entries than unit_count
    if len(inputs.rent_roll) < inputs.deal.unit_count:
        missing_a.append(RENT_ROLL_INCOMPLETE)
        missing_b.append(RENT_ROLL_INCOMPLETE)

    # REHAB_PLAN_MISSING — any unit with renovate_flag=True lacks rehab_start_month
    for plan in inputs.rehab_plan:
        if plan.renovate_flag and plan.rehab_start_month is None:
            missing_a.append(REHAB_PLAN_MISSING)
            missing_b.append(REHAB_PLAN_MISSING)
            break

    # OPEX_ASSUMPTIONS_MISSING — any of the seven annual OpEx inputs is None
    opex = inputs.opex
    opex_fields = [
        opex.property_taxes_annual,
        opex.insurance_annual,
        opex.utilities_annual,
        opex.repairs_and_maintenance_annual,
        opex.admin_and_marketing_annual,
        opex.payroll_annual,
        opex.other_opex_annual,
    ]
    if any(v is None for v in opex_fields):
        missing_a.append(OPEX_ASSUMPTIONS_MISSING)
        missing_b.append(OPEX_ASSUMPTIONS_MISSING)

    # PRIMARY_LENDER_MISSING_A / PRIMARY_LENDER_MISSING_B
    if inputs.lender_scenario_a is None:
        missing_a.append(PRIMARY_LENDER_MISSING_A)

    if inputs.lender_scenario_b is None:
        missing_b.append(PRIMARY_LENDER_MISSING_B)

    return missing_a, missing_b


# ---------------------------------------------------------------------------
# Per-unit scheduled rent (Req 8.1)
# ---------------------------------------------------------------------------


def _scheduled_rent(
    unit_id: str,
    month: int,
    rent_roll_map: dict[str, Decimal],
    rehab_plan_map: dict[str, RehabPlanSnapshot],
) -> Decimal:
    """Compute scheduled rent for a single unit in a given month.

    Rule:
        if not unit.renovate_flag:                           current_rent
        elif M < rehab_start_month:                          current_rent
        elif rehab_start_month <= M < stabilized_month:      0
        else:                                                underwritten_post_reno_rent
    """
    current_rent = rent_roll_map.get(unit_id, ZERO)
    plan = rehab_plan_map.get(unit_id)

    if plan is None or not plan.renovate_flag:
        return current_rent

    # Unit is being renovated
    rehab_start = plan.rehab_start_month
    if rehab_start is None:
        # Missing rehab_start_month — treat as non-renovated for safety
        return current_rent

    stabilized_month = plan.stabilized_month
    if stabilized_month is None:
        # Fallback: if stabilized_month not set, use rehab_start (no downtime)
        stabilized_month = rehab_start

    if month < rehab_start:
        return current_rent
    elif month < stabilized_month:
        return ZERO
    else:
        # Post-stabilization: use underwritten post-reno rent
        post_reno = plan.underwritten_post_reno_rent
        return post_reno if post_reno is not None else current_rent


# ---------------------------------------------------------------------------
# Debt service computation (Reqs 8.7, 8.8)
# ---------------------------------------------------------------------------


def _compute_debt_service_a(
    month: int, lender: LenderProfileSnapshot, loan_amount: Decimal
) -> Decimal:
    """Compute monthly debt service for Scenario A (Construction-to-Perm).

    - For M in 1..construction_io_months: interest-only
      debt_service = loan_amount * construction_rate / 12
    - For M > construction_io_months: amortizing
      standard mortgage formula with r = perm_rate/12, n = perm_amort_years*12
    - Edge case: perm_rate == 0 → loan_amount / n
    """
    io_months = lender.construction_io_months if lender.construction_io_months is not None else 0
    construction_rate = lender.construction_rate if lender.construction_rate is not None else ZERO

    if month <= io_months:
        # Interest-only period
        return quantize_money(loan_amount * construction_rate / TWELVE)
    else:
        # Amortizing period
        perm_rate = lender.perm_rate if lender.perm_rate is not None else ZERO
        perm_amort_years = lender.perm_amort_years if lender.perm_amort_years is not None else 0
        n = perm_amort_years * 12
        if n <= 0:
            return ZERO
        monthly_rate = quantize_rate(perm_rate / TWELVE)
        return _amortizing_payment(loan_amount, monthly_rate, n)


def _compute_debt_service_b(
    lender: LenderProfileSnapshot, loan_amount: Decimal
) -> Decimal:
    """Compute monthly debt service for Scenario B (Self-Funded Renovation).

    Amortizing for all 24 months:
        r = all_in_rate / 12, n = amort_years * 12
    Same mortgage formula, same rate==0 edge case.
    """
    all_in_rate = lender.all_in_rate if lender.all_in_rate is not None else ZERO
    amort_years = lender.amort_years if lender.amort_years is not None else 0
    n = amort_years * 12
    if n <= 0:
        return ZERO
    monthly_rate = quantize_rate(all_in_rate / TWELVE)
    return _amortizing_payment(loan_amount, monthly_rate, n)


# ---------------------------------------------------------------------------
# Summary computation (Reqs 8.12, 8.13, 10.6, 10.7)
# ---------------------------------------------------------------------------


def _compute_summary(
    monthly_rows: list[MonthlyRow],
    scenario_a_has_missing: bool,
    scenario_b_has_missing: bool,
    sources_and_uses_a: Optional[SourcesAndUses],
    sources_and_uses_b: Optional[SourcesAndUses],
) -> tuple[ProFormaSummary, list[str]]:
    """Compute summary metrics from the monthly schedule.

    In_Place_NOI            = NOI(1) * 12
    Stabilized_NOI          = average(NOI(13..24)) * 12
    In_Place_DSCR(S)        = NOI(1) / debt_service(1, S)   if debt_service != 0
    Stabilized_DSCR(S)      = NOI(24) / debt_service(24, S) if debt_service != 0
    Cash_On_Cash(S)         = sum(cfad(M in 13..24)) / initial_cash_investment(S)
                              if initial_cash_investment > 0, else None

    Returns:
        Tuple of (ProFormaSummary, warnings list).
    """
    warnings: list[str] = []

    # In-Place NOI = Month 1 NOI * 12
    month_1 = monthly_rows[0]
    in_place_noi = quantize_money(month_1.noi * TWELVE)

    # Stabilized NOI = average(NOI months 13..24) * 12
    stabilized_noi_months = [
        monthly_rows[m - 1].noi for m in STABILIZED_MONTHS
    ]
    avg_stabilized_noi = sum(stabilized_noi_months) / Decimal(len(stabilized_noi_months))
    stabilized_noi = quantize_money(avg_stabilized_noi * TWELVE)

    # DSCR calculations
    month_24 = monthly_rows[23]

    # In-Place DSCR (Scenario A)
    in_place_dscr_a: Optional[Decimal] = None
    if not scenario_a_has_missing and month_1.debt_service_a is not None:
        if month_1.debt_service_a != ZERO:
            in_place_dscr_a = quantize_rate(month_1.noi / month_1.debt_service_a)

    # In-Place DSCR (Scenario B)
    in_place_dscr_b: Optional[Decimal] = None
    if not scenario_b_has_missing and month_1.debt_service_b is not None:
        if month_1.debt_service_b != ZERO:
            in_place_dscr_b = quantize_rate(month_1.noi / month_1.debt_service_b)

    # Stabilized DSCR (Scenario A)
    stabilized_dscr_a: Optional[Decimal] = None
    if not scenario_a_has_missing and month_24.debt_service_a is not None:
        if month_24.debt_service_a != ZERO:
            stabilized_dscr_a = quantize_rate(month_24.noi / month_24.debt_service_a)

    # Stabilized DSCR (Scenario B)
    stabilized_dscr_b: Optional[Decimal] = None
    if not scenario_b_has_missing and month_24.debt_service_b is not None:
        if month_24.debt_service_b != ZERO:
            stabilized_dscr_b = quantize_rate(month_24.noi / month_24.debt_service_b)

    # Cash-on-Cash (Req 10.6, 10.7)
    # cash_on_cash = sum(cash_flow_after_debt(M in 13..24)) / initial_cash_investment
    cash_on_cash_a: Optional[Decimal] = None
    if not scenario_a_has_missing and sources_and_uses_a is not None:
        initial_cash_a = sources_and_uses_a.initial_cash_investment
        if initial_cash_a > ZERO:
            stabilized_cfad_a = sum(
                (monthly_rows[m - 1].cash_flow_after_debt_a or ZERO)
                for m in STABILIZED_MONTHS
            )
            cash_on_cash_a = quantize_rate(stabilized_cfad_a / initial_cash_a)
        else:
            warnings.append("Non_Positive_Equity_A")

    cash_on_cash_b: Optional[Decimal] = None
    if not scenario_b_has_missing and sources_and_uses_b is not None:
        initial_cash_b = sources_and_uses_b.initial_cash_investment
        if initial_cash_b > ZERO:
            stabilized_cfad_b = sum(
                (monthly_rows[m - 1].cash_flow_after_debt_b or ZERO)
                for m in STABILIZED_MONTHS
            )
            cash_on_cash_b = quantize_rate(stabilized_cfad_b / initial_cash_b)
        else:
            warnings.append("Non_Positive_Equity_B")

    return ProFormaSummary(
        in_place_noi=in_place_noi,
        stabilized_noi=stabilized_noi,
        in_place_dscr_a=in_place_dscr_a,
        in_place_dscr_b=in_place_dscr_b,
        stabilized_dscr_a=stabilized_dscr_a,
        stabilized_dscr_b=stabilized_dscr_b,
        cash_on_cash_a=cash_on_cash_a,
        cash_on_cash_b=cash_on_cash_b,
    ), warnings


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


def compute_pro_forma(inputs: DealInputs) -> ProFormaComputation:
    """Compute the full 24-month pro forma from frozen inputs.

    This is a pure function — no database access, no I/O, no mutation of inputs.

    Pipeline:
        1. Scan for missing inputs
        2. Build per-unit rent schedule
        3. Compute monthly GSR
        4. Compute EGI (GSR - vacancy + other_income)
        5. Compute OpEx (fixed lines/12 + mgmt_fee_rate * EGI)
        6. Compute NOI (EGI - OpEx)
        7. Compute replacement_reserves
        8. Compute net_cash_flow (NOI - reserves)
        9. Compute debt_service_A (IO then amortizing)
        10. Compute debt_service_B (amortizing all 24)
        11. Compute cash_flow_after_debt (A/B)
        12. Compute capex_spend (lump-sum at start)
        13. Compute cash_flow_after_capex (A/B)
        14. Compute summary metrics

    Args:
        inputs: Frozen DealInputs snapshot.

    Returns:
        ProFormaComputation with full schedule, summary, and missing-input flags.
    """
    # Step 1: Scan for missing inputs (Req 8.14)
    missing_inputs_a, missing_inputs_b = _scan_missing_inputs(inputs)

    # Build lookup maps
    rent_roll_map: dict[str, Decimal] = {
        rr.unit_id: rr.current_rent for rr in inputs.rent_roll
    }
    rehab_plan_map: dict[str, RehabPlanSnapshot] = {
        rp.unit_id: rp for rp in inputs.rehab_plan
    }

    # Collect all unit_ids from rent_roll (these are the units we compute for)
    all_unit_ids = [rr.unit_id for rr in inputs.rent_roll]

    # Step 2: Per-unit scheduled rent for months 1..24 (Req 8.1)
    per_unit_schedule: dict[str, tuple[Decimal, ...]] = {}
    for unit_id in all_unit_ids:
        monthly_rents: list[Decimal] = []
        for m in range(1, HORIZON_MONTHS + 1):
            rent = _scheduled_rent(unit_id, m, rent_roll_map, rehab_plan_map)
            monthly_rents.append(quantize_money(rent))
        per_unit_schedule[unit_id] = tuple(monthly_rents)

    # Step 3-8: Monthly pipeline
    vacancy_rate = inputs.deal.vacancy_rate
    other_income_monthly = inputs.deal.other_income_monthly

    # OpEx fixed components — individual line items (annual / 12)
    opex = inputs.opex
    property_taxes_monthly = quantize_money(opex.property_taxes_annual / TWELVE)
    insurance_monthly = quantize_money(opex.insurance_annual / TWELVE)
    utilities_monthly = quantize_money(opex.utilities_annual / TWELVE)
    repairs_monthly = quantize_money(opex.repairs_and_maintenance_annual / TWELVE)
    admin_monthly = quantize_money(opex.admin_and_marketing_annual / TWELVE)
    payroll_monthly = quantize_money(opex.payroll_annual / TWELVE)
    other_opex_monthly = quantize_money(opex.other_opex_annual / TWELVE)

    # Sum of fixed OpEx lines (before management fee)
    fixed_opex_monthly = quantize_money(
        property_taxes_monthly
        + insurance_monthly
        + utilities_monthly
        + repairs_monthly
        + admin_monthly
        + payroll_monthly
        + other_opex_monthly
    )

    management_fee_rate = opex.management_fee_rate

    # Replacement reserves (Req 8.6)
    reserves = inputs.reserves
    replacement_reserves = quantize_money(
        reserves.reserve_per_unit_per_year * Decimal(reserves.unit_count) / TWELVE
    )

    # Debt service setup — Scenario A
    loan_amount_a: Optional[Decimal] = None
    lender_a = inputs.lender_scenario_a
    rehab_budget_total = sum(
        (p.rehab_budget for p in inputs.rehab_plan if p.renovate_flag), ZERO
    )
    if lender_a is not None:
        loan_amount_a = compute_loan_amount_scenario_a(
            lender_a,
            inputs.deal.purchase_price,
            inputs.deal.closing_costs,
            rehab_budget_total,
        )

    # Debt service setup — Scenario B
    loan_amount_b: Optional[Decimal] = None
    lender_b = inputs.lender_scenario_b
    if lender_b is not None:
        loan_amount_b = compute_loan_amount_scenario_b(
            lender_b, inputs.deal.purchase_price
        )

    # Pre-compute Scenario B debt service (constant for all 24 months)
    ds_b_constant: Optional[Decimal] = None
    if lender_b is not None and loan_amount_b is not None:
        ds_b_constant = _compute_debt_service_b(lender_b, loan_amount_b)

    # Build monthly rows
    monthly_rows: list[MonthlyRow] = []
    scenario_a_has_missing = len(missing_inputs_a) > 0
    scenario_b_has_missing = len(missing_inputs_b) > 0

    for m in range(1, HORIZON_MONTHS + 1):
        # Step 3: Monthly GSR (Req 8.2)
        gsr = ZERO
        for unit_id in all_unit_ids:
            gsr += per_unit_schedule[unit_id][m - 1]
        gsr = quantize_money(gsr)

        # Step 4: EGI (Req 8.3)
        vacancy_loss = quantize_money(vacancy_rate * gsr)
        egi = quantize_money(gsr - vacancy_loss + other_income_monthly)

        # Step 5: OpEx (Req 8.4)
        mgmt_fee = quantize_money(management_fee_rate * egi)
        opex_total = quantize_money(fixed_opex_monthly + mgmt_fee)

        opex_breakdown = OpExBreakdown(
            property_taxes=property_taxes_monthly,
            insurance=insurance_monthly,
            utilities=utilities_monthly,
            repairs_and_maintenance=repairs_monthly,
            admin_and_marketing=admin_monthly,
            payroll=payroll_monthly,
            other_opex=other_opex_monthly,
            management_fee=mgmt_fee,
        )

        # Step 6: NOI (Req 8.5)
        noi = quantize_money(egi - opex_total)

        # Step 7-8: Net cash flow (Req 8.6)
        net_cash_flow = quantize_money(noi - replacement_reserves)

        # Step 9: Debt service A (Req 8.7)
        debt_service_a: Optional[Decimal] = None
        if not scenario_a_has_missing and lender_a is not None and loan_amount_a is not None:
            debt_service_a = _compute_debt_service_a(m, lender_a, loan_amount_a)

        # Step 10: Debt service B (Req 8.8)
        debt_service_b: Optional[Decimal] = None
        if not scenario_b_has_missing and ds_b_constant is not None:
            debt_service_b = ds_b_constant

        # Step 11: Cash flow after debt (Req 8.9)
        cf_after_debt_a: Optional[Decimal] = None
        if debt_service_a is not None:
            cf_after_debt_a = quantize_money(net_cash_flow - debt_service_a)

        cf_after_debt_b: Optional[Decimal] = None
        if debt_service_b is not None:
            cf_after_debt_b = quantize_money(net_cash_flow - debt_service_b)

        # Step 12: CapEx spend (Req 8.10)
        capex_spend = quantize_money(
            inputs.capex_allocation.allocate(inputs.rehab_plan, m)
        )

        # Step 13: Cash flow after capex (Req 8.11)
        cf_after_capex_a: Optional[Decimal] = None
        if cf_after_debt_a is not None:
            cf_after_capex_a = quantize_money(cf_after_debt_a - capex_spend)

        cf_after_capex_b: Optional[Decimal] = None
        if cf_after_debt_b is not None:
            cf_after_capex_b = quantize_money(cf_after_debt_b - capex_spend)

        row = MonthlyRow(
            month=m,
            gsr=gsr,
            vacancy_loss=vacancy_loss,
            other_income=other_income_monthly,
            egi=egi,
            opex_breakdown=opex_breakdown,
            opex_total=opex_total,
            noi=noi,
            replacement_reserves=replacement_reserves,
            net_cash_flow=net_cash_flow,
            debt_service_a=debt_service_a,
            debt_service_b=debt_service_b,
            cash_flow_after_debt_a=cf_after_debt_a,
            cash_flow_after_debt_b=cf_after_debt_b,
            capex_spend=capex_spend,
            cash_flow_after_capex_a=cf_after_capex_a,
            cash_flow_after_capex_b=cf_after_capex_b,
        )
        monthly_rows.append(row)

    # Step 14: Sources & Uses (Reqs 10.1-10.5)
    su_a: Optional[SourcesAndUses] = None
    if not scenario_a_has_missing and lender_a is not None and loan_amount_a is not None:
        su_a = build_sources_and_uses(
            loan_amount=loan_amount_a,
            lender=lender_a,
            purchase_price=inputs.deal.purchase_price,
            closing_costs=inputs.deal.closing_costs,
            rehab_budget_total=rehab_budget_total,
            interest_reserve=inputs.deal.interest_reserve_amount,
            funding_sources=inputs.funding_sources,
        )

    su_b: Optional[SourcesAndUses] = None
    if not scenario_b_has_missing and lender_b is not None and loan_amount_b is not None:
        su_b = build_sources_and_uses(
            loan_amount=loan_amount_b,
            lender=lender_b,
            purchase_price=inputs.deal.purchase_price,
            closing_costs=inputs.deal.closing_costs,
            rehab_budget_total=rehab_budget_total,
            interest_reserve=inputs.deal.interest_reserve_amount,
            funding_sources=inputs.funding_sources,
        )

    # Step 15: Summary metrics (Reqs 8.12, 8.13, 10.6, 10.7)
    summary, su_warnings = _compute_summary(
        monthly_rows, scenario_a_has_missing, scenario_b_has_missing,
        su_a, su_b,
    )

    return ProFormaComputation(
        monthly_schedule=tuple(monthly_rows),
        per_unit_schedule=per_unit_schedule,
        summary=summary,
        sources_and_uses_a=su_a,
        sources_and_uses_b=su_b,
        valuation=None,  # Computed separately
        missing_inputs_a=missing_inputs_a,
        missing_inputs_b=missing_inputs_b,
        warnings=su_warnings,
    )
