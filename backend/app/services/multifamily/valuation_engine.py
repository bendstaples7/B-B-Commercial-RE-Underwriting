"""
Pure valuation engine for multifamily underwriting.

Computes stabilized valuation at cap rate and price-per-unit from sale comp
rollup statistics. Returns a frozen Valuation dataclass with all computed
fields and any applicable warnings.

This module is a pure function — no database access, no I/O, no mutation.

Requirements: 9.1-9.5
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from app.services.multifamily.pro_forma_constants import quantize_money
from app.services.multifamily.pro_forma_result_dc import Valuation


# ---------------------------------------------------------------------------
# Sale comp rollup input dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SaleCompRollup:
    """Aggregated sale comp statistics for valuation.

    All fields are Decimal | None. None indicates insufficient comps
    (fewer than required to compute that statistic).
    """

    cap_rate_min: Decimal | None
    cap_rate_median: Decimal | None
    cap_rate_average: Decimal | None
    cap_rate_max: Decimal | None
    ppu_min: Decimal | None
    ppu_median: Decimal | None
    ppu_average: Decimal | None
    ppu_max: Decimal | None


# ---------------------------------------------------------------------------
# Warning constants
# ---------------------------------------------------------------------------

NON_POSITIVE_STABILIZED_NOI = "Non_Positive_Stabilized_NOI"


# ---------------------------------------------------------------------------
# Pure valuation function
# ---------------------------------------------------------------------------


def compute_valuation(
    stabilized_noi: Decimal | None,
    purchase_price: Decimal,
    month_1_gsr: Decimal,
    unit_count: int,
    sale_comp_rollup: SaleCompRollup,
    custom_cap_rate: Decimal | None = None,
) -> Valuation:
    """Compute valuation from stabilized NOI, sale comp rollup, and deal params.

    Parameters
    ----------
    stabilized_noi : Decimal | None
        Annualized stabilized NOI (average of months 13-24 * 12).
        None if the pro forma could not compute it.
    purchase_price : Decimal
        Deal purchase price for price-to-rent ratio.
    month_1_gsr : Decimal
        Month 1 gross scheduled rent for price-to-rent ratio.
    unit_count : int
        Number of units in the deal for PPU valuation.
    sale_comp_rollup : SaleCompRollup
        Aggregated cap rate and PPU statistics from sale comps.
    custom_cap_rate : Decimal | None
        Optional user-supplied cap rate override (Req 9.3).

    Returns
    -------
    Valuation
        Frozen dataclass with all valuation fields and warnings.
    """
    warnings: list[str] = []

    # --- Cap-rate valuations (Req 9.1, 9.3, 9.4) ---
    # If stabilized_noi is None or <= 0, all cap-rate valuations are None
    noi_positive = stabilized_noi is not None and stabilized_noi > Decimal("0")

    if not noi_positive:
        if stabilized_noi is not None:
            warnings.append(NON_POSITIVE_STABILIZED_NOI)
        valuation_at_cap_rate_min = None
        valuation_at_cap_rate_median = None
        valuation_at_cap_rate_average = None
        valuation_at_cap_rate_max = None
        valuation_at_custom_cap_rate = None
    else:
        # Compute valuation = stabilized_noi / cap_rate for each stat
        valuation_at_cap_rate_min = _valuation_at_cap(stabilized_noi, sale_comp_rollup.cap_rate_min)
        valuation_at_cap_rate_median = _valuation_at_cap(stabilized_noi, sale_comp_rollup.cap_rate_median)
        valuation_at_cap_rate_average = _valuation_at_cap(stabilized_noi, sale_comp_rollup.cap_rate_average)
        valuation_at_cap_rate_max = _valuation_at_cap(stabilized_noi, sale_comp_rollup.cap_rate_max)

        # Custom cap rate (Req 9.3)
        if custom_cap_rate is not None and custom_cap_rate > Decimal("0"):
            valuation_at_custom_cap_rate = quantize_money(stabilized_noi / custom_cap_rate)
        else:
            valuation_at_custom_cap_rate = None

    # --- PPU valuations (Req 9.2) ---
    # valuation_at_ppu = unit_count * PPU for each stat
    valuation_at_ppu_min = _valuation_at_ppu(unit_count, sale_comp_rollup.ppu_min)
    valuation_at_ppu_median = _valuation_at_ppu(unit_count, sale_comp_rollup.ppu_median)
    valuation_at_ppu_average = _valuation_at_ppu(unit_count, sale_comp_rollup.ppu_average)
    valuation_at_ppu_max = _valuation_at_ppu(unit_count, sale_comp_rollup.ppu_max)

    # --- Price-to-rent ratio (Req 9.5) ---
    # price_to_rent_ratio = purchase_price / (month_1_gsr * 12)
    annualized_gsr = month_1_gsr * Decimal("12")
    if annualized_gsr > Decimal("0"):
        price_to_rent_ratio = (purchase_price / annualized_gsr).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )
    else:
        price_to_rent_ratio = None

    return Valuation(
        valuation_at_cap_rate_min=valuation_at_cap_rate_min,
        valuation_at_cap_rate_median=valuation_at_cap_rate_median,
        valuation_at_cap_rate_average=valuation_at_cap_rate_average,
        valuation_at_cap_rate_max=valuation_at_cap_rate_max,
        valuation_at_ppu_min=valuation_at_ppu_min,
        valuation_at_ppu_median=valuation_at_ppu_median,
        valuation_at_ppu_average=valuation_at_ppu_average,
        valuation_at_ppu_max=valuation_at_ppu_max,
        valuation_at_custom_cap_rate=valuation_at_custom_cap_rate,
        price_to_rent_ratio=price_to_rent_ratio,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _valuation_at_cap(stabilized_noi: Decimal, cap_rate: Decimal | None) -> Decimal | None:
    """Compute valuation = stabilized_noi / cap_rate, or None if cap_rate is missing/zero."""
    if cap_rate is None or cap_rate <= Decimal("0"):
        return None
    return quantize_money(stabilized_noi / cap_rate)


def _valuation_at_ppu(unit_count: int, ppu: Decimal | None) -> Decimal | None:
    """Compute valuation = unit_count * ppu, or None if ppu is missing."""
    if ppu is None:
        return None
    return quantize_money(Decimal(unit_count) * ppu)
