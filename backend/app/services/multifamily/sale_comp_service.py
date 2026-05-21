"""
Sale comp service for multifamily underwriting.

Manages Sale_Comps (closed sale comparables) for a Deal and provides
rollup statistics for cap rate and price-per-unit derivation.

Requirements: 4.1-4.5
"""

from __future__ import annotations

from decimal import Decimal

from app import db
from app.models import SaleComp, ProFormaResult


# ---------------------------------------------------------------------------
# SaleCompService
# ---------------------------------------------------------------------------


class SaleCompService:
    """Service for managing sale comps attached to a Deal.

    Provides CRUD for SaleComp records and rollup statistics
    (min/median/avg/max) for cap rates and price-per-unit.

    Cap rate handling:
      - Comps may have no cap rate (observed_cap_rate = None).
      - If noi and sale_price are both present, cap rate is derived as
        noi / sale_price with cap_rate_confidence = 0.5.
      - If cap rate is stated directly, cap_rate_confidence = 1.0.
      - If cap rate is unknown, cap_rate_confidence = 0.0.
      - Rollup statistics only include comps that have a cap rate
        (stated or derived).
    """

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_sale_comp(self, deal_id: int, payload: dict) -> SaleComp:
        """Add a sale comp and compute observed_ppu and derived cap rate.

        If observed_cap_rate is not provided but noi and sale_price are,
        the cap rate is derived as noi / sale_price with confidence 0.5.

        Args:
            deal_id: The Deal to add the comp to.
            payload: Dict with address, unit_count, status, sale_price,
                     close_date, observed_cap_rate (optional), noi (optional),
                     distance_miles (optional).

        Returns:
            The persisted SaleComp model instance.

        Requirements: 4.1
        """
        sale_price = Decimal(str(payload["sale_price"]))
        unit_count = int(payload["unit_count"])
        observed_ppu = sale_price / Decimal(str(unit_count))

        # Resolve cap rate and confidence
        cap_rate_raw = payload.get("observed_cap_rate")
        noi_raw = payload.get("noi")

        noi = Decimal(str(noi_raw)) if noi_raw is not None else None

        if cap_rate_raw is not None:
            # Cap rate stated directly
            observed_cap_rate = Decimal(str(cap_rate_raw))
            cap_rate_confidence = 1.0
        elif noi is not None and sale_price > 0:
            # Derive cap rate from NOI / sale_price
            observed_cap_rate = noi / sale_price
            cap_rate_confidence = 0.5
        else:
            # No cap rate available
            observed_cap_rate = None
            cap_rate_confidence = 0.0

        comp = SaleComp(
            deal_id=deal_id,
            address=payload["address"],
            unit_count=unit_count,
            status=payload.get("status"),
            sale_price=sale_price,
            close_date=payload.get("close_date"),
            observed_cap_rate=observed_cap_rate,
            observed_ppu=observed_ppu,
            distance_miles=payload.get("distance_miles"),
            noi=noi,
            cap_rate_confidence=cap_rate_confidence,
        )
        db.session.add(comp)
        self._invalidate_cache(deal_id)
        db.session.flush()
        return comp

    def delete_sale_comp(self, deal_id: int, comp_id: int) -> None:
        """Delete a sale comp.

        Args:
            deal_id: The Deal the comp belongs to.
            comp_id: The ID of the SaleComp to delete.

        Raises:
            ValueError: If the comp does not exist for this deal.
        """
        comp = SaleComp.query.filter_by(id=comp_id, deal_id=deal_id).first()
        if comp is None:
            raise ValueError(
                f"Sale comp {comp_id} not found for deal {deal_id}"
            )

        db.session.delete(comp)
        self._invalidate_cache(deal_id)
        db.session.flush()

    # ------------------------------------------------------------------
    # Rollup
    # ------------------------------------------------------------------

    def get_comps_rollup(self, deal_id: int) -> dict:
        """Return rollup statistics for sale comps of a Deal.

        Cap rate statistics are computed only from comps that have a cap
        rate (stated or derived). Comps without cap rates are included in
        the comps list but excluded from cap rate min/median/avg/max.

        Args:
            deal_id: The Deal to query.

        Returns:
            Dict with Cap_Rate_Min, Cap_Rate_Median, Cap_Rate_Average,
            Cap_Rate_Max, PPU_Min, PPU_Median, PPU_Average, PPU_Max,
            the full list of SaleComp objects, and a warnings list.

        Requirements: 4.4, 4.5
        """
        comps = SaleComp.query.filter_by(deal_id=deal_id).all()

        warnings: list[str] = []

        if len(comps) < 3:
            warnings.append("Sale_Comps_Insufficient")

        if not comps:
            return {
                "Cap_Rate_Min": None,
                "Cap_Rate_Median": None,
                "Cap_Rate_Average": None,
                "Cap_Rate_Max": None,
                "PPU_Min": None,
                "PPU_Median": None,
                "PPU_Average": None,
                "PPU_Max": None,
                "comps": [],
                "warnings": warnings,
            }

        # Only include comps with a cap rate in cap rate statistics
        comps_with_cap_rate = [c for c in comps if c.observed_cap_rate is not None]
        comps_without_cap_rate = [c for c in comps if c.observed_cap_rate is None]

        if comps_without_cap_rate:
            warnings.append(
                f"{len(comps_without_cap_rate)}_Comps_Missing_Cap_Rate"
            )

        ppus = [Decimal(str(c.observed_ppu)) for c in comps]

        if comps_with_cap_rate:
            cap_rates = [Decimal(str(c.observed_cap_rate)) for c in comps_with_cap_rate]
            cap_rate_stats = {
                "Cap_Rate_Min": min(cap_rates),
                "Cap_Rate_Median": self._compute_median(cap_rates),
                "Cap_Rate_Average": sum(cap_rates) / len(cap_rates),
                "Cap_Rate_Max": max(cap_rates),
            }
        else:
            cap_rate_stats = {
                "Cap_Rate_Min": None,
                "Cap_Rate_Median": None,
                "Cap_Rate_Average": None,
                "Cap_Rate_Max": None,
            }

        return {
            **cap_rate_stats,
            "PPU_Min": min(ppus),
            "PPU_Median": self._compute_median(ppus),
            "PPU_Average": sum(ppus) / len(ppus),
            "PPU_Max": max(ppus),
            "comps": comps,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_median(self, values: list[Decimal]) -> Decimal:
        """Compute the median of a list of Decimal values."""
        sorted_values = sorted(values)
        n = len(sorted_values)
        mid = n // 2

        if n % 2 == 1:
            return sorted_values[mid]
        else:
            return (sorted_values[mid - 1] + sorted_values[mid]) / Decimal("2")

    def _invalidate_cache(self, deal_id: int) -> None:
        """Delete the cached ProFormaResult for a deal (Req 15.3)."""
        ProFormaResult.query.filter_by(deal_id=deal_id).delete()
