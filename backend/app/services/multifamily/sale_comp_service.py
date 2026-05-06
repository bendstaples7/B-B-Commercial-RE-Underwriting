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
    """

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_sale_comp(self, deal_id: int, payload: dict) -> SaleComp:
        """Add a sale comp and compute observed_ppu at write time.

        Args:
            deal_id: The Deal to add the comp to.
            payload: Dict with address, unit_count, status, sale_price,
                     close_date, observed_cap_rate, distance_miles.

        Returns:
            The persisted SaleComp model instance.

        Requirements: 4.1
        """
        sale_price = Decimal(str(payload["sale_price"]))
        unit_count = int(payload["unit_count"])
        observed_ppu = sale_price / Decimal(str(unit_count))

        comp = SaleComp(
            deal_id=deal_id,
            address=payload["address"],
            unit_count=unit_count,
            status=payload.get("status"),
            sale_price=sale_price,
            close_date=payload.get("close_date"),
            observed_cap_rate=Decimal(str(payload["observed_cap_rate"])),
            observed_ppu=observed_ppu,
            distance_miles=payload.get("distance_miles"),
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

        Returns min/median/avg/max for both observed cap rates and
        observed price-per-unit, plus the full list of comps and any
        warnings.

        Args:
            deal_id: The Deal to query.

        Returns:
            Dict with Cap_Rate_Min, Cap_Rate_Median, Cap_Rate_Average,
            Cap_Rate_Max, PPU_Min, PPU_Median, PPU_Average, PPU_Max,
            the list of SaleComp objects, and a warnings list.

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

        cap_rates = [Decimal(str(c.observed_cap_rate)) for c in comps]
        ppus = [Decimal(str(c.observed_ppu)) for c in comps]

        return {
            "Cap_Rate_Min": min(cap_rates),
            "Cap_Rate_Median": self._compute_median(cap_rates),
            "Cap_Rate_Average": sum(cap_rates) / len(cap_rates),
            "Cap_Rate_Max": max(cap_rates),
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
        """Compute the median of a list of Decimal values.

        Sorts the values and picks the middle value (odd count) or
        the average of the two middle values (even count).

        Args:
            values: Non-empty list of Decimal values.

        Returns:
            The median as a Decimal.
        """
        sorted_values = sorted(values)
        n = len(sorted_values)
        mid = n // 2

        if n % 2 == 1:
            return sorted_values[mid]
        else:
            return (sorted_values[mid - 1] + sorted_values[mid]) / Decimal("2")

    def _invalidate_cache(self, deal_id: int) -> None:
        """Delete the cached ProFormaResult for a deal (Req 15.3).

        This runs in the same transaction as the write that triggered it.
        """
        ProFormaResult.query.filter_by(deal_id=deal_id).delete()
