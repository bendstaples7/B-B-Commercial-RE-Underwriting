"""
Frozen result dataclasses for the multifamily pro forma engine.

These dataclasses form the immutable output contract of `compute_pro_forma`.
Each class provides a `to_canonical_dict()` method that serializes to a
stable JSON-friendly dict (Decimal → str, sorted keys, recursive handling
of nested dataclasses).

Requirements: 8.12, 10.1-10.7, 11.1
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal
from typing import Any


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_value(value: Any) -> Any:
    """Serialize a single value for canonical JSON output.

    - Decimal → str (not float, preserving precision)
    - None → None
    - Nested dataclass → recursive to_canonical_dict()
    - tuple/list → list of serialized values
    - dict → sorted dict of serialized values
    - Everything else → as-is
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "to_canonical_dict"):
        return value.to_canonical_dict()
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _serialize_value(v) for k, v in sorted(value.items())}
    return value


def _to_canonical_dict(obj: Any) -> dict[str, Any]:
    """Generic canonical dict builder for frozen dataclasses.

    Iterates over dataclass fields in declaration order, serializes each
    value, and returns a dict with sorted keys for stable JSON output.
    """
    result: dict[str, Any] = {}
    for f in fields(obj):
        result[f.name] = _serialize_value(getattr(obj, f.name))
    return dict(sorted(result.items()))


# ---------------------------------------------------------------------------
# OpExBreakdown
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpExBreakdown:
    """Monthly operating expense breakdown.

    The 7 fixed annual lines (divided by 12) plus management_fee (rate × EGI).
    """

    property_taxes: Decimal
    insurance: Decimal
    utilities: Decimal
    repairs_and_maintenance: Decimal
    admin_and_marketing: Decimal
    payroll: Decimal
    other_opex: Decimal
    management_fee: Decimal

    def to_canonical_dict(self) -> dict[str, Any]:
        """Serialize to a stable JSON-friendly dict."""
        return _to_canonical_dict(self)


# ---------------------------------------------------------------------------
# MonthlyRow
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonthlyRow:
    """A single month's row in the 24-month pro forma schedule.

    Contains all computed values for that month across both scenarios.
    Debt service and cash flow fields are None when the corresponding
    scenario has missing inputs.
    """

    month: int
    gsr: Decimal
    vacancy_loss: Decimal
    other_income: Decimal
    egi: Decimal
    opex_breakdown: OpExBreakdown
    opex_total: Decimal
    noi: Decimal
    replacement_reserves: Decimal
    net_cash_flow: Decimal
    debt_service_a: Decimal | None
    debt_service_b: Decimal | None
    cash_flow_after_debt_a: Decimal | None
    cash_flow_after_debt_b: Decimal | None
    capex_spend: Decimal
    cash_flow_after_capex_a: Decimal | None
    cash_flow_after_capex_b: Decimal | None

    def to_canonical_dict(self) -> dict[str, Any]:
        """Serialize to a stable JSON-friendly dict."""
        return _to_canonical_dict(self)


# ---------------------------------------------------------------------------
# ProFormaSummary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProFormaSummary:
    """Per-scenario summary metrics (Req 8.12, 11.1).

    All fields are Decimal | None. None indicates the metric could not be
    computed (e.g. missing lender for DSCR, zero equity for Cash-on-Cash).
    """

    in_place_noi: Decimal | None
    stabilized_noi: Decimal | None
    in_place_dscr_a: Decimal | None
    in_place_dscr_b: Decimal | None
    stabilized_dscr_a: Decimal | None
    stabilized_dscr_b: Decimal | None
    cash_on_cash_a: Decimal | None
    cash_on_cash_b: Decimal | None

    def to_canonical_dict(self) -> dict[str, Any]:
        """Serialize to a stable JSON-friendly dict."""
        return _to_canonical_dict(self)


# ---------------------------------------------------------------------------
# SourcesAndUses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourcesAndUses:
    """Sources & Uses for a single scenario (Req 10.1-10.7).

    Uses: purchase_price, closing_costs, rehab_budget_total,
          loan_origination_fees, funding_source_origination_fees,
          interest_reserve.
    Sources: loan_amount, cash_draw, heloc_1_draw, heloc_2_draw.
    Computed: total_uses, total_sources, initial_cash_investment.
    """

    # Uses
    purchase_price: Decimal
    closing_costs: Decimal
    rehab_budget_total: Decimal
    loan_origination_fees: Decimal
    funding_source_origination_fees: Decimal
    interest_reserve: Decimal

    # Sources
    loan_amount: Decimal
    cash_draw: Decimal
    heloc_1_draw: Decimal
    heloc_2_draw: Decimal

    # Computed
    total_uses: Decimal
    total_sources: Decimal
    initial_cash_investment: Decimal  # = total_uses - loan_amount

    def to_canonical_dict(self) -> dict[str, Any]:
        """Serialize to a stable JSON-friendly dict."""
        return _to_canonical_dict(self)


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Valuation:
    """Valuation results from cap rate and price-per-unit approaches (Req 9).

    All valuation fields are Decimal | None (None when Stabilized_NOI <= 0
    or insufficient sale comps).
    """

    valuation_at_cap_rate_min: Decimal | None
    valuation_at_cap_rate_median: Decimal | None
    valuation_at_cap_rate_average: Decimal | None
    valuation_at_cap_rate_max: Decimal | None
    valuation_at_ppu_min: Decimal | None
    valuation_at_ppu_median: Decimal | None
    valuation_at_ppu_average: Decimal | None
    valuation_at_ppu_max: Decimal | None
    valuation_at_custom_cap_rate: Decimal | None
    price_to_rent_ratio: Decimal | None
    warnings: list[str]

    def to_canonical_dict(self) -> dict[str, Any]:
        """Serialize to a stable JSON-friendly dict."""
        return _to_canonical_dict(self)


# ---------------------------------------------------------------------------
# ProFormaComputation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProFormaComputation:
    """Complete output of the pro forma engine.

    Holds the full 24-month schedule, per-unit rent schedule, summary
    metrics, sources & uses for both scenarios, valuation, and any
    missing-input or warning flags.
    """

    monthly_schedule: tuple[MonthlyRow, ...]
    per_unit_schedule: dict[str, tuple[Decimal, ...]]
    summary: ProFormaSummary
    sources_and_uses_a: SourcesAndUses | None
    sources_and_uses_b: SourcesAndUses | None
    valuation: Valuation | None
    missing_inputs_a: list[str]
    missing_inputs_b: list[str]
    warnings: list[str]

    def to_canonical_dict(self) -> dict[str, Any]:
        """Serialize to a stable JSON-friendly dict."""
        return _to_canonical_dict(self)
