"""
Composite Hypothesis strategies for multifamily pro forma property tests.

Generates valid DealInputs and related structures for property-based testing
of the pure computation engine.

All Decimal values use `places=6` for reproducibility as required by the design.
"""

from decimal import Decimal

from hypothesis import strategies as st, HealthCheck
from hypothesis.strategies import composite

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
# Primitive strategies
# ---------------------------------------------------------------------------

_positive_money = st.decimals(
    min_value=Decimal("100.000000"),
    max_value=Decimal("5000000.000000"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)

_rent_amount = st.decimals(
    min_value=Decimal("200.000000"),
    max_value=Decimal("10000.000000"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)

_rate = st.decimals(
    min_value=Decimal("0.010000"),
    max_value=Decimal("0.300000"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)

_vacancy_rate = st.decimals(
    min_value=Decimal("0.000000"),
    max_value=Decimal("1.000000"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)

_ltv = st.decimals(
    min_value=Decimal("0.100000"),
    max_value=Decimal("0.950000"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)

_unit_types = st.sampled_from(["Studio", "1BR", "2BR", "3BR", "4BR"])

_occupancy = st.sampled_from(["Occupied", "Vacant", "Down"])


# ---------------------------------------------------------------------------
# Composite strategies
# ---------------------------------------------------------------------------


@composite
def _deal_snapshot_st(draw, unit_count: int) -> DealSnapshot:
    """Generate a valid DealSnapshot with the given unit_count."""
    return DealSnapshot(
        deal_id=draw(st.integers(min_value=1, max_value=100000)),
        purchase_price=draw(_positive_money),
        closing_costs=draw(
            st.decimals(
                min_value=Decimal("1000.000000"),
                max_value=Decimal("100000.000000"),
                places=6,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        vacancy_rate=draw(_vacancy_rate),
        other_income_monthly=draw(
            st.decimals(
                min_value=Decimal("0.000000"),
                max_value=Decimal("5000.000000"),
                places=6,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        management_fee_rate=draw(_rate),
        reserve_per_unit_per_year=draw(
            st.decimals(
                min_value=Decimal("100.000000"),
                max_value=Decimal("1000.000000"),
                places=6,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        interest_reserve_amount=draw(
            st.decimals(
                min_value=Decimal("0.000000"),
                max_value=Decimal("50000.000000"),
                places=6,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        custom_cap_rate=None,
        unit_count=unit_count,
    )


@composite
def _unit_snapshot_st(draw, unit_id: str) -> UnitSnapshot:
    """Generate a valid UnitSnapshot with the given unit_id."""
    return UnitSnapshot(
        unit_id=unit_id,
        unit_type=draw(_unit_types),
        beds=draw(st.integers(min_value=0, max_value=5)),
        baths=draw(
            st.decimals(
                min_value=Decimal("1.0"),
                max_value=Decimal("4.0"),
                places=1,
                allow_nan=False,
                allow_infinity=False,
            )
        ),
        sqft=draw(st.integers(min_value=300, max_value=3000)),
        occupancy_status=draw(_occupancy),
    )


@composite
def _rehab_plan_snapshot_st(
    draw, unit_id: str, current_rent: Decimal, renovate: bool
) -> RehabPlanSnapshot:
    """Generate a RehabPlanSnapshot for a unit."""
    if not renovate:
        return RehabPlanSnapshot(
            unit_id=unit_id,
            renovate_flag=False,
            current_rent=current_rent,
            underwritten_post_reno_rent=None,
            rehab_start_month=None,
            downtime_months=None,
            stabilized_month=None,
            rehab_budget=Decimal("0"),
        )

    rehab_start = draw(st.integers(min_value=1, max_value=20))
    downtime = draw(st.integers(min_value=1, max_value=4))
    stabilized_month = rehab_start + downtime
    post_reno_rent = draw(
        st.decimals(
            min_value=current_rent + Decimal("100.000000"),
            max_value=current_rent + Decimal("2000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    rehab_budget = draw(
        st.decimals(
            min_value=Decimal("5000.000000"),
            max_value=Decimal("50000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        )
    )

    return RehabPlanSnapshot(
        unit_id=unit_id,
        renovate_flag=True,
        current_rent=current_rent,
        underwritten_post_reno_rent=post_reno_rent,
        rehab_start_month=rehab_start,
        downtime_months=downtime,
        stabilized_month=stabilized_month,
        rehab_budget=rehab_budget,
    )


@composite
def _opex_assumptions_st(draw) -> OpExAssumptions:
    """Generate valid OpExAssumptions with positive annual values."""
    annual = st.decimals(
        min_value=Decimal("1000.000000"),
        max_value=Decimal("100000.000000"),
        places=6,
        allow_nan=False,
        allow_infinity=False,
    )
    return OpExAssumptions(
        property_taxes_annual=draw(annual),
        insurance_annual=draw(annual),
        utilities_annual=draw(annual),
        repairs_and_maintenance_annual=draw(annual),
        admin_and_marketing_annual=draw(annual),
        payroll_annual=draw(annual),
        other_opex_annual=draw(annual),
        management_fee_rate=draw(_rate),
    )


@composite
def _lender_a_st(draw) -> LenderProfileSnapshot:
    """Generate a valid Scenario A (Construction-to-Perm) lender profile."""
    return LenderProfileSnapshot(
        lender_type="Construction_To_Perm",
        origination_fee_rate=draw(_rate),
        ltv_total_cost=draw(_ltv),
        construction_rate=draw(_rate),
        construction_io_months=draw(st.integers(min_value=1, max_value=18)),
        perm_rate=draw(_rate),
        perm_amort_years=draw(st.integers(min_value=10, max_value=30)),
        max_purchase_ltv=None,
        all_in_rate=None,
        amort_years=None,
    )


@composite
def _lender_b_st(draw) -> LenderProfileSnapshot:
    """Generate a valid Scenario B (Self-Funded Reno) lender profile."""
    return LenderProfileSnapshot(
        lender_type="Self_Funded_Reno",
        origination_fee_rate=draw(_rate),
        ltv_total_cost=None,
        construction_rate=None,
        construction_io_months=None,
        perm_rate=None,
        perm_amort_years=None,
        max_purchase_ltv=draw(_ltv),
        all_in_rate=draw(_rate),
        amort_years=draw(st.integers(min_value=10, max_value=30)),
    )


@composite
def funding_sources_st(draw) -> tuple[FundingSourceSnapshot, ...]:
    """Produce 0-3 FundingSourceSnapshot values with random total_available."""
    source_types = ["Cash", "HELOC_1", "HELOC_2"]
    count = draw(st.integers(min_value=0, max_value=3))
    selected = source_types[:count]
    sources = []
    for stype in selected:
        sources.append(
            FundingSourceSnapshot(
                source_type=stype,
                total_available=draw(
                    st.decimals(
                        min_value=Decimal("1000.000000"),
                        max_value=Decimal("500000.000000"),
                        places=6,
                        allow_nan=False,
                        allow_infinity=False,
                    )
                ),
                interest_rate=draw(_rate),
                origination_fee_rate=draw(_rate),
            )
        )
    return tuple(sources)


@composite
def cap_rate_st(draw) -> Decimal:
    """Decimal values in (0, 0.25] for cap rate testing."""
    return draw(
        st.decimals(
            min_value=Decimal("0.010000"),
            max_value=Decimal("0.250000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        )
    )


@composite
def amortization_inputs_st(draw) -> tuple[Decimal, Decimal, int]:
    """Small positive-rate amortization tuples for Property 5.

    Returns (principal, annual_rate, amort_years).
    """
    principal = draw(
        st.decimals(
            min_value=Decimal("10000.000000"),
            max_value=Decimal("2000000.000000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    annual_rate = draw(
        st.decimals(
            min_value=Decimal("0.010000"),
            max_value=Decimal("0.300000"),
            places=6,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    amort_years = draw(st.integers(min_value=5, max_value=30))
    return (principal, annual_rate, amort_years)


@composite
def deal_inputs_st(draw) -> DealInputs:
    """Generate valid DealInputs for property-based testing.

    Produces:
    - DealSnapshot with valid ranges (unit_count >= 5, purchase_price > 0,
      rates in [0, 0.30], vacancy_rate in [0, 1])
    - 5-20 UnitSnapshots with unique unit_ids
    - Matching RentRollSnapshots (one per unit)
    - RehabPlanSnapshots (some with renovate_flag=True, some False)
    - OpExAssumptions with positive values
    - ReserveAssumptions matching unit_count
    - LenderProfileSnapshots for both scenarios (valid rates)
    - 0-3 FundingSourceSnapshots
    """
    unit_count = draw(st.integers(min_value=5, max_value=20))
    deal = draw(_deal_snapshot_st(unit_count))

    # Generate unique unit IDs
    unit_ids = [f"U{i}" for i in range(1, unit_count + 1)]

    # Generate units
    units = tuple(draw(_unit_snapshot_st(uid)) for uid in unit_ids)

    # Generate rent roll (one per unit)
    rents = []
    for uid in unit_ids:
        rent = draw(_rent_amount)
        rents.append(RentRollSnapshot(unit_id=uid, current_rent=rent))
    rent_roll = tuple(rents)

    # Generate rehab plans — at least one renovated, at least one not
    rehab_plans = []
    for i, uid in enumerate(unit_ids):
        current_rent = rent_roll[i].current_rent
        # First unit always renovated, second always not, rest random
        if i == 0:
            renovate = True
        elif i == 1:
            renovate = False
        else:
            renovate = draw(st.booleans())
        plan = draw(_rehab_plan_snapshot_st(uid, current_rent, renovate))
        rehab_plans.append(plan)
    rehab_plan = tuple(rehab_plans)

    # Market rents (one per unique unit_type present)
    seen_types = set()
    market_rents_list = []
    for unit in units:
        if unit.unit_type not in seen_types:
            seen_types.add(unit.unit_type)
            market_rents_list.append(
                MarketRentSnapshot(
                    unit_type=unit.unit_type,
                    target_rent=draw(_rent_amount),
                    post_reno_target_rent=draw(_rent_amount),
                )
            )
    market_rents = tuple(market_rents_list)

    # OpEx
    opex = draw(_opex_assumptions_st())

    # Reserves
    reserves = ReserveAssumptions(
        reserve_per_unit_per_year=deal.reserve_per_unit_per_year,
        unit_count=unit_count,
    )

    # Lenders
    lender_a = draw(_lender_a_st())
    lender_b = draw(_lender_b_st())

    # Funding sources
    sources = draw(funding_sources_st())

    return DealInputs(
        deal=deal,
        units=units,
        rent_roll=rent_roll,
        rehab_plan=rehab_plan,
        market_rents=market_rents,
        opex=opex,
        reserves=reserves,
        lender_scenario_a=lender_a,
        lender_scenario_b=lender_b,
        funding_sources=sources,
        capex_allocation=LumpSumAtStart(),
    )


@composite
def deal_inputs_with_missing_st(draw) -> DealInputs:
    """Generate DealInputs with deliberately missing fields.

    Exercises Property 14 (missing inputs path never raises).
    Generates DealInputs where one or more of:
    - rent_roll is incomplete (fewer entries than unit_count)
    - rehab plan has missing start months for renovated units
    - lender_scenario_a and/or lender_scenario_b is None
    """
    unit_count = draw(st.integers(min_value=5, max_value=15))
    deal = draw(_deal_snapshot_st(unit_count))

    unit_ids = [f"U{i}" for i in range(1, unit_count + 1)]
    units = tuple(draw(_unit_snapshot_st(uid)) for uid in unit_ids)

    # Decide which inputs to make incomplete
    incomplete_rent_roll = draw(st.booleans())
    missing_rehab_start = draw(st.booleans())
    missing_lender_a = draw(st.booleans())
    missing_lender_b = draw(st.booleans())

    # Rent roll — possibly incomplete
    if incomplete_rent_roll:
        rent_count = draw(st.integers(min_value=1, max_value=unit_count - 1))
    else:
        rent_count = unit_count

    rents = []
    for i in range(rent_count):
        uid = unit_ids[i]
        rent = draw(_rent_amount)
        rents.append(RentRollSnapshot(unit_id=uid, current_rent=rent))
    rent_roll = tuple(rents)

    # Rehab plans — possibly with missing rehab_start_month
    rehab_plans = []
    for i, uid in enumerate(unit_ids[:rent_count]):
        current_rent = rent_roll[i].current_rent
        renovate = draw(st.booleans())
        if renovate and missing_rehab_start and i == 0:
            # Deliberately missing rehab_start_month
            rehab_plans.append(
                RehabPlanSnapshot(
                    unit_id=uid,
                    renovate_flag=True,
                    current_rent=current_rent,
                    underwritten_post_reno_rent=current_rent + Decimal("500"),
                    rehab_start_month=None,
                    downtime_months=None,
                    stabilized_month=None,
                    rehab_budget=Decimal("15000"),
                )
            )
        else:
            plan = draw(_rehab_plan_snapshot_st(uid, current_rent, renovate))
            rehab_plans.append(plan)
    rehab_plan = tuple(rehab_plans)

    opex = draw(_opex_assumptions_st())
    reserves = ReserveAssumptions(
        reserve_per_unit_per_year=deal.reserve_per_unit_per_year,
        unit_count=unit_count,
    )

    lender_a = None if missing_lender_a else draw(_lender_a_st())
    lender_b = None if missing_lender_b else draw(_lender_b_st())

    sources = draw(funding_sources_st())

    return DealInputs(
        deal=deal,
        units=units,
        rent_roll=rent_roll,
        rehab_plan=rehab_plan,
        market_rents=(),
        opex=opex,
        reserves=reserves,
        lender_scenario_a=lender_a,
        lender_scenario_b=lender_b,
        funding_sources=sources,
        capex_allocation=LumpSumAtStart(),
    )
