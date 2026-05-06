"""
Frozen input dataclasses for the multifamily pro forma engine.

These dataclasses form the immutable input contract for `compute_pro_forma`.
They are populated from SQLAlchemy models by `DealService.build_inputs_snapshot`
and use `Decimal` throughout — no floats, no ORM session references.

Requirements: 8.1-8.11
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Snapshot dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DealSnapshot:
    """Top-level deal parameters needed by the engine."""

    deal_id: int
    purchase_price: Decimal
    closing_costs: Decimal
    vacancy_rate: Decimal
    other_income_monthly: Decimal
    management_fee_rate: Decimal
    reserve_per_unit_per_year: Decimal
    interest_reserve_amount: Decimal
    custom_cap_rate: Decimal | None
    unit_count: int


@dataclass(frozen=True)
class UnitSnapshot:
    """Per-unit physical attributes."""

    unit_id: str
    unit_type: str
    beds: int
    baths: Decimal
    sqft: int
    occupancy_status: Literal["Occupied", "Vacant", "Down"]


@dataclass(frozen=True)
class RentRollSnapshot:
    """In-place rent for a single unit."""

    unit_id: str
    current_rent: Decimal


@dataclass(frozen=True)
class RehabPlanSnapshot:
    """Renovation plan for a single unit."""

    unit_id: str
    renovate_flag: bool
    current_rent: Decimal
    underwritten_post_reno_rent: Decimal | None
    rehab_start_month: int | None  # 1..24
    downtime_months: int | None
    stabilized_month: int | None
    rehab_budget: Decimal


@dataclass(frozen=True)
class MarketRentSnapshot:
    """Market rent assumptions for a unit type."""

    unit_type: str
    target_rent: Decimal
    post_reno_target_rent: Decimal


@dataclass(frozen=True)
class OpExAssumptions:
    """Annual operating expense assumptions (divided by 12 in the engine)."""

    property_taxes_annual: Decimal
    insurance_annual: Decimal
    utilities_annual: Decimal
    repairs_and_maintenance_annual: Decimal
    admin_and_marketing_annual: Decimal
    payroll_annual: Decimal
    other_opex_annual: Decimal
    management_fee_rate: Decimal


@dataclass(frozen=True)
class ReserveAssumptions:
    """Replacement reserve parameters."""

    reserve_per_unit_per_year: Decimal
    unit_count: int


@dataclass(frozen=True)
class LenderProfileSnapshot:
    """Lender terms snapshot for a single primary lender."""

    lender_type: Literal["Construction_To_Perm", "Self_Funded_Reno"]
    origination_fee_rate: Decimal
    # Construction_To_Perm fields
    ltv_total_cost: Decimal | None
    construction_rate: Decimal | None
    construction_io_months: int | None
    perm_rate: Decimal | None
    perm_amort_years: int | None
    # Self_Funded_Reno fields
    max_purchase_ltv: Decimal | None
    all_in_rate: Decimal | None  # treasury + spread, precomputed
    amort_years: int | None


@dataclass(frozen=True)
class FundingSourceSnapshot:
    """A single funding source (Cash, HELOC_1, or HELOC_2)."""

    source_type: Literal["Cash", "HELOC_1", "HELOC_2"]
    total_available: Decimal
    interest_rate: Decimal
    origination_fee_rate: Decimal


# ---------------------------------------------------------------------------
# CapEx allocation strategy
# ---------------------------------------------------------------------------


@runtime_checkable
class CapExAllocationStrategy(Protocol):
    """Protocol for CapEx allocation across months.

    The default implementation is lump-sum at rehab start month (Req 8.10).
    Alternative strategies (e.g. straight-line over downtime) can be plugged
    in without modifying the engine core.
    """

    def allocate(
        self, rehab_plans: tuple[RehabPlanSnapshot, ...], month: int
    ) -> Decimal:
        """Return total CapEx spend for the given month."""
        ...


class LumpSumAtStart:
    """Default CapEx allocation: full rehab_budget at rehab_start_month.

    Sums rehab_budget for all units whose rehab_start_month equals the
    given month (Req 8.10).
    """

    def allocate(
        self, rehab_plans: tuple[RehabPlanSnapshot, ...], month: int
    ) -> Decimal:
        """Return total CapEx spend for the given month."""
        return sum(
            (
                plan.rehab_budget
                for plan in rehab_plans
                if plan.renovate_flag and plan.rehab_start_month == month
            ),
            Decimal("0"),
        )


# ---------------------------------------------------------------------------
# Top-level engine input
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DealInputs:
    """Complete frozen input to the pro forma engine.

    Populated by `DealService.build_inputs_snapshot(deal_id)` from ORM models.
    The engine receives this single value and returns a `ProFormaComputation`.
    """

    deal: DealSnapshot
    units: tuple[UnitSnapshot, ...]
    rent_roll: tuple[RentRollSnapshot, ...]
    rehab_plan: tuple[RehabPlanSnapshot, ...]
    market_rents: tuple[MarketRentSnapshot, ...]
    opex: OpExAssumptions
    reserves: ReserveAssumptions
    lender_scenario_a: LenderProfileSnapshot | None  # Primary lender for Scenario A
    lender_scenario_b: LenderProfileSnapshot | None  # Primary lender for Scenario B
    funding_sources: tuple[FundingSourceSnapshot, ...]
    capex_allocation: CapExAllocationStrategy = field(default_factory=LumpSumAtStart)
