"""
Pure helper functions for computing Sources & Uses in multifamily underwriting.

Computes loan amounts for each scenario, builds the full Sources & Uses
breakdown, and derives initial_cash_investment.

All functions are pure (no DB access, no I/O) and operate on Decimal values
with documented quantization (2dp money via quantize_money).

Requirements: 10.1-10.5
"""

from __future__ import annotations

from decimal import Decimal

from app.services.multifamily.pro_forma_constants import quantize_money
from app.services.multifamily.pro_forma_inputs import (
    FundingSourceSnapshot,
    LenderProfileSnapshot,
)
from app.services.multifamily.pro_forma_result_dc import SourcesAndUses
from app.services.multifamily.funding_service import (
    compute_draws,
    compute_origination_fees,
)

ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Loan amount computation (Reqs 10.3, 10.4)
# ---------------------------------------------------------------------------


def compute_loan_amount_scenario_a(
    lender: LenderProfileSnapshot,
    purchase_price: Decimal,
    closing_costs: Decimal,
    rehab_budget_total: Decimal,
) -> Decimal:
    """Compute Loan_Amount for Scenario A (Construction-to-Perm).

    Formula: Loan_Amount_A = LTV_Total_Cost × (Purchase_Price + Closing_Costs + Rehab_Budget_Total)

    Args:
        lender: The primary lender profile for Scenario A.
        purchase_price: Deal purchase price.
        closing_costs: Deal closing costs.
        rehab_budget_total: Sum of rehab budgets across renovated units.

    Returns:
        Loan amount quantized to 2 decimal places.

    Requirements: 10.3
    """
    ltv = lender.ltv_total_cost if lender.ltv_total_cost is not None else ZERO
    total_cost = purchase_price + closing_costs + rehab_budget_total
    return quantize_money(ltv * total_cost)


def compute_loan_amount_scenario_b(
    lender: LenderProfileSnapshot,
    purchase_price: Decimal,
) -> Decimal:
    """Compute Loan_Amount for Scenario B (Self-Funded Renovation).

    Formula: Loan_Amount_B = Max_Purchase_LTV × Purchase_Price

    Args:
        lender: The primary lender profile for Scenario B.
        purchase_price: Deal purchase price.

    Returns:
        Loan amount quantized to 2 decimal places.

    Requirements: 10.4
    """
    max_ltv = lender.max_purchase_ltv if lender.max_purchase_ltv is not None else ZERO
    return quantize_money(max_ltv * purchase_price)


# ---------------------------------------------------------------------------
# Sources & Uses builder (Reqs 10.1, 10.2, 10.5)
# ---------------------------------------------------------------------------


def build_sources_and_uses(
    loan_amount: Decimal,
    lender: LenderProfileSnapshot,
    purchase_price: Decimal,
    closing_costs: Decimal,
    rehab_budget_total: Decimal,
    interest_reserve: Decimal,
    funding_sources: tuple[FundingSourceSnapshot, ...],
) -> SourcesAndUses:
    """Build the full Sources & Uses breakdown for a single scenario.

    Uses (Req 10.1):
        - purchase_price
        - closing_costs
        - rehab_budget_total
        - loan_origination_fees (loan_amount × lender.origination_fee_rate)
        - funding_source_origination_fees (from funding waterfall draws)
        - interest_reserve

    Sources (Req 10.2):
        - loan_amount
        - cash_draw, heloc_1_draw, heloc_2_draw (from funding waterfall)

    Computed (Req 10.5):
        - total_uses = sum of all uses
        - initial_cash_investment = total_uses - loan_amount
        - total_sources = loan_amount + sum(draws)

    The funding waterfall is computed with required_equity = initial_cash_investment
    (excluding funding_source_origination_fees in the first pass to break the
    circular dependency).

    Args:
        loan_amount: Pre-computed loan amount for this scenario.
        lender: The primary lender profile for this scenario.
        purchase_price: Deal purchase price.
        closing_costs: Deal closing costs.
        rehab_budget_total: Sum of rehab budgets across renovated units.
        interest_reserve: Deal-level interest reserve amount.
        funding_sources: Tuple of funding source snapshots.

    Returns:
        SourcesAndUses dataclass with all fields populated.
    """
    # Loan origination fees
    loan_origination_fees = quantize_money(loan_amount * lender.origination_fee_rate)

    # To avoid circular dependency between funding_source_origination_fees and
    # the waterfall draws (which depend on required_equity, which depends on
    # total_uses), we compute in two passes:
    #
    # Pass 1: Compute base uses without funding_source_origination_fees,
    #          derive initial equity, run waterfall, compute fees.
    # Pass 2: Add fees to total_uses.

    # Pass 1: Uses without funding_source_origination_fees
    base_uses = quantize_money(
        purchase_price
        + closing_costs
        + rehab_budget_total
        + loan_origination_fees
        + interest_reserve
    )
    base_initial_cash_investment = quantize_money(base_uses - loan_amount)

    # Required equity for the funding waterfall is the initial cash investment
    required_equity = max(ZERO, base_initial_cash_investment)

    # Build sources_by_type lookup for the waterfall
    sources_by_type: dict[str, FundingSourceSnapshot] = {
        s.source_type: s for s in funding_sources
    }

    # Run the funding waterfall
    draw_plan = compute_draws(required_equity, sources_by_type)
    draws = draw_plan.draws

    # Compute funding source origination fees from draws
    funding_source_origination_fees = compute_origination_fees(draws, sources_by_type)

    # Final total_uses includes funding_source_origination_fees
    total_uses = quantize_money(base_uses + funding_source_origination_fees)

    # Final initial_cash_investment
    initial_cash_investment = quantize_money(total_uses - loan_amount)

    # Total sources = loan_amount + all draws
    cash_draw = draws.get("Cash", ZERO)
    heloc_1_draw = draws.get("HELOC_1", ZERO)
    heloc_2_draw = draws.get("HELOC_2", ZERO)
    total_sources = quantize_money(loan_amount + cash_draw + heloc_1_draw + heloc_2_draw)

    return SourcesAndUses(
        purchase_price=purchase_price,
        closing_costs=closing_costs,
        rehab_budget_total=rehab_budget_total,
        loan_origination_fees=loan_origination_fees,
        funding_source_origination_fees=funding_source_origination_fees,
        interest_reserve=interest_reserve,
        loan_amount=loan_amount,
        cash_draw=cash_draw,
        heloc_1_draw=heloc_1_draw,
        heloc_2_draw=heloc_2_draw,
        total_uses=total_uses,
        total_sources=total_sources,
        initial_cash_investment=initial_cash_investment,
    )
