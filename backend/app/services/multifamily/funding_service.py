"""
Funding waterfall service for multifamily underwriting.

Manages funding sources (Cash, HELOC_1, HELOC_2) for a Deal and provides
pure helper functions for computing the draw waterfall, origination fees,
and HELOC carrying interest.

Requirements: 7.1-7.6
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app import db
from app.exceptions import DuplicateFundingSourceError
from app.models.funding_source import FundingSource
from app.models.pro_forma_result import ProFormaResult
from app.services.multifamily.pro_forma_constants import quantize_money
from app.services.multifamily.pro_forma_inputs import FundingSourceSnapshot


# ---------------------------------------------------------------------------
# Data structures for draw results
# ---------------------------------------------------------------------------

# Priority order for the funding waterfall (Req 7.3)
FUNDING_PRIORITY: tuple[str, ...] = ("Cash", "HELOC_1", "HELOC_2")


@dataclass(frozen=True)
class FundingDrawPlan:
    """Result of the funding waterfall computation.

    Attributes:
        draws: Mapping of source_type -> draw amount (Decimal).
        shortfall: Amount of required equity not covered by sources (>= 0).
        insufficient_funding: True when shortfall > 0 (Req 7.4).
    """

    draws: dict[str, Decimal]
    shortfall: Decimal
    insufficient_funding: bool


# ---------------------------------------------------------------------------
# Pure helper functions (no DB access)
# ---------------------------------------------------------------------------


def compute_draws(
    required_equity: Decimal,
    sources_by_type: dict[str, FundingSourceSnapshot],
) -> FundingDrawPlan:
    """Compute the funding waterfall draws in priority order Cash -> HELOC_1 -> HELOC_2.

    For any required equity amount E and any set of funding sources, the draw
    plan satisfies the five invariants defined in Property 4:

    1. sum(draws) == min(E, sum(total_available))
    2. draws[s] <= s.total_available for every source
    3. Priority ordering is preserved
    4. shortfall = max(0, E - sum(draws)), Insufficient_Funding iff shortfall > 0
    5. Origination fees = sum(draws[t] * sources[t].origination_fee_rate)

    Args:
        required_equity: The total equity needed (must be >= 0).
        sources_by_type: Mapping of source_type -> FundingSourceSnapshot.

    Returns:
        FundingDrawPlan with per-source draws, shortfall, and flag.

    Requirements: 7.3, 7.4
    """
    remaining = required_equity
    draws: dict[str, Decimal] = {}

    for source_type in FUNDING_PRIORITY:
        source = sources_by_type.get(source_type)
        if source is None or remaining <= Decimal("0"):
            draws[source_type] = Decimal("0")
            continue
        draw = min(remaining, source.total_available)
        draws[source_type] = quantize_money(draw)
        remaining -= draw

    shortfall = quantize_money(max(Decimal("0"), remaining))
    insufficient_funding = shortfall > Decimal("0")

    return FundingDrawPlan(
        draws=draws,
        shortfall=shortfall,
        insufficient_funding=insufficient_funding,
    )


def compute_origination_fees(
    draws: dict[str, Decimal],
    sources_by_type: dict[str, FundingSourceSnapshot],
) -> Decimal:
    """Compute total origination fees across all funding sources with non-zero draws.

    origination_fees = sum(draw_amount * origination_fee_rate) for each source
    with a non-zero draw.

    Args:
        draws: Mapping of source_type -> draw amount.
        sources_by_type: Mapping of source_type -> FundingSourceSnapshot.

    Returns:
        Total origination fees (Decimal, quantized to 2dp).

    Requirements: 7.5
    """
    total = Decimal("0")
    for source_type, draw_amount in draws.items():
        if draw_amount <= Decimal("0"):
            continue
        source = sources_by_type.get(source_type)
        if source is None:
            continue
        total += quantize_money(draw_amount * source.origination_fee_rate)
    return quantize_money(total)


def compute_heloc_carrying_interest(
    draws: dict[str, Decimal],
    sources_by_type: dict[str, FundingSourceSnapshot],
    month_index: int,
) -> Decimal:
    """Compute HELOC carrying interest for a given month.

    For each HELOC source with a non-zero draw, the monthly carrying interest
    is: draw_amount * interest_rate / 12.

    The outstanding balance is assumed to be the full draw amount for all months
    (no principal paydown on HELOCs during the pro forma horizon).

    Args:
        draws: Mapping of source_type -> draw amount.
        sources_by_type: Mapping of source_type -> FundingSourceSnapshot.
        month_index: The month (1-based) for which to compute interest.

    Returns:
        Total HELOC carrying interest for the month (Decimal, quantized to 2dp).

    Requirements: 7.6
    """
    total = Decimal("0")
    twelve = Decimal("12")

    for source_type in ("HELOC_1", "HELOC_2"):
        draw_amount = draws.get(source_type, Decimal("0"))
        if draw_amount <= Decimal("0"):
            continue
        source = sources_by_type.get(source_type)
        if source is None:
            continue
        monthly_interest = quantize_money(draw_amount * source.interest_rate / twelve)
        total += monthly_interest

    return quantize_money(total)


# ---------------------------------------------------------------------------
# Database-backed service class
# ---------------------------------------------------------------------------


class FundingService:
    """Service for managing funding sources attached to a Deal.

    Provides CRUD operations with duplicate detection (Req 7.2) and
    delegates pure computation to the module-level helper functions.
    """

    def add_source(self, deal_id: int, payload: dict) -> FundingSource:
        """Add a funding source to a Deal.

        Raises DuplicateFundingSourceError if the source_type already exists
        for this Deal (Req 7.2).

        Args:
            deal_id: The Deal to add the source to.
            payload: Dict with source_type, total_available, interest_rate,
                     origination_fee_rate.

        Returns:
            The created FundingSource model instance.

        Requirements: 7.1, 7.2
        """
        source_type = payload["source_type"]

        # Check for duplicate source_type on this deal
        existing = FundingSource.query.filter_by(
            deal_id=deal_id, source_type=source_type
        ).first()
        if existing is not None:
            raise DuplicateFundingSourceError(
                message=f"Funding source type '{source_type}' already exists for deal {deal_id}",
                deal_id=deal_id,
                source_type=source_type,
            )

        source = FundingSource(
            deal_id=deal_id,
            source_type=source_type,
            total_available=payload["total_available"],
            interest_rate=payload.get("interest_rate", Decimal("0")),
            origination_fee_rate=payload.get("origination_fee_rate", Decimal("0")),
        )
        db.session.add(source)
        self._invalidate_cache(deal_id)
        db.session.flush()
        return source

    def update_source(self, deal_id: int, source_id: int, payload: dict) -> FundingSource:
        """Update an existing funding source.

        Args:
            deal_id: The Deal the source belongs to.
            source_id: The ID of the FundingSource to update.
            payload: Dict with fields to update (total_available, interest_rate,
                     origination_fee_rate).

        Returns:
            The updated FundingSource model instance.
        """
        source = FundingSource.query.filter_by(
            id=source_id, deal_id=deal_id
        ).first()
        if source is None:
            raise ValueError(f"Funding source {source_id} not found for deal {deal_id}")

        if "total_available" in payload:
            source.total_available = payload["total_available"]
        if "interest_rate" in payload:
            source.interest_rate = payload["interest_rate"]
        if "origination_fee_rate" in payload:
            source.origination_fee_rate = payload["origination_fee_rate"]

        self._invalidate_cache(deal_id)
        db.session.flush()
        return source

    def delete_source(self, deal_id: int, source_id: int) -> None:
        """Delete a funding source from a Deal.

        Args:
            deal_id: The Deal the source belongs to.
            source_id: The ID of the FundingSource to delete.
        """
        source = FundingSource.query.filter_by(
            id=source_id, deal_id=deal_id
        ).first()
        if source is None:
            raise ValueError(f"Funding source {source_id} not found for deal {deal_id}")

        db.session.delete(source)
        self._invalidate_cache(deal_id)
        db.session.flush()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _invalidate_cache(self, deal_id: int) -> None:
        """Delete the cached ProFormaResult for a deal (Req 15.3).

        This runs in the same transaction as the write that triggered it.
        """
        ProFormaResult.query.filter_by(deal_id=deal_id).delete()
