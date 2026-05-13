"""
Market rent assumptions and rent comps service for multifamily underwriting.

Manages Market_Rent_Assumptions (target rents per unit type) and Rent_Comps
(comparable rentals used to justify those assumptions). Provides rollup
statistics and auto-fill logic from comps.

Requirements: 3.1-3.5
"""

from __future__ import annotations

from decimal import Decimal

from app import db
from app.models.market_rent_assumption import MarketRentAssumption
from app.models.pro_forma_result import ProFormaResult
from app.models.rent_comp import RentComp


# ---------------------------------------------------------------------------
# MarketRentService
# ---------------------------------------------------------------------------


class MarketRentService:
    """Service for managing market rent assumptions and rent comps.

    Provides CRUD for MarketRentAssumption and RentComp records,
    rollup statistics, and auto-fill logic from comps.
    """

    # ------------------------------------------------------------------
    # Market Rent Assumptions
    # ------------------------------------------------------------------

    def set_assumption(
        self, deal_id: int, unit_type: str, payload: dict
    ) -> MarketRentAssumption:
        """Create or update a market rent assumption keyed by (deal_id, unit_type).

        Args:
            deal_id: The Deal to set the assumption for.
            unit_type: The unit type (e.g. '1BR/1BA').
            payload: Dict with target_rent and/or post_reno_target_rent.

        Returns:
            The persisted MarketRentAssumption model instance.

        Requirements: 3.1
        """
        assumption = MarketRentAssumption.query.filter_by(
            deal_id=deal_id, unit_type=unit_type
        ).first()

        if assumption is None:
            assumption = MarketRentAssumption(
                deal_id=deal_id,
                unit_type=unit_type,
                target_rent=payload.get("target_rent"),
                post_reno_target_rent=payload.get("post_reno_target_rent"),
            )
            db.session.add(assumption)
        else:
            if "target_rent" in payload:
                assumption.target_rent = payload["target_rent"]
            if "post_reno_target_rent" in payload:
                assumption.post_reno_target_rent = payload["post_reno_target_rent"]

        self._invalidate_cache(deal_id)
        db.session.flush()
        return assumption

    # ------------------------------------------------------------------
    # Rent Comps
    # ------------------------------------------------------------------

    def add_rent_comp(self, deal_id: int, payload: dict) -> RentComp:
        """Add a rent comp and compute rent_per_sqft at write time.

        Args:
            deal_id: The Deal to add the comp to.
            payload: Dict with address, neighborhood, unit_type, observed_rent,
                     sqft, observation_date, source_url.

        Returns:
            The persisted RentComp model instance.

        Requirements: 3.2, 3.3
        """
        observed_rent = Decimal(str(payload["observed_rent"]))
        sqft = int(payload["sqft"])
        rent_per_sqft = observed_rent / Decimal(str(sqft))

        comp = RentComp(
            deal_id=deal_id,
            address=payload["address"],
            neighborhood=payload.get("neighborhood"),
            unit_type=payload["unit_type"],
            observed_rent=observed_rent,
            sqft=sqft,
            rent_per_sqft=rent_per_sqft,
            observation_date=payload.get("observation_date"),
            source_url=payload.get("source_url"),
        )
        db.session.add(comp)
        self._invalidate_cache(deal_id)
        db.session.flush()
        return comp

    def delete_rent_comp(self, deal_id: int, comp_id: int) -> None:
        """Delete a rent comp.

        Args:
            deal_id: The Deal the comp belongs to.
            comp_id: The ID of the RentComp to delete.

        Raises:
            ValueError: If the comp does not exist for this deal.
        """
        comp = RentComp.query.filter_by(id=comp_id, deal_id=deal_id).first()
        if comp is None:
            raise ValueError(
                f"Rent comp {comp_id} not found for deal {deal_id}"
            )

        db.session.delete(comp)
        self._invalidate_cache(deal_id)
        db.session.flush()

    # ------------------------------------------------------------------
    # Rollup
    # ------------------------------------------------------------------

    def get_all_comps_rollups(self, deal_id: int) -> list[dict]:
        """Return rollup statistics for all unit types in a deal.

        Queries all distinct unit types that have rent comps for the given
        deal and returns a list of rollup dicts (one per unit type), each
        containing the same fields as ``get_comps_rollup``.

        Args:
            deal_id: The Deal to query.

        Returns:
            List of rollup dicts ordered by unit_type, one per distinct
            unit type that has at least one comp.  Returns an empty list
            when no comps exist for the deal.

        Requirements: 3.4
        """
        # Fetch all comps for the deal in a single query
        all_comps = RentComp.query.filter_by(deal_id=deal_id).order_by(
            RentComp.unit_type
        ).all()

        # Group by unit_type
        comps_by_type: dict[str, list[RentComp]] = {}
        for comp in all_comps:
            comps_by_type.setdefault(comp.unit_type, []).append(comp)

        rollups = []
        for unit_type in sorted(comps_by_type.keys()):
            comps = comps_by_type[unit_type]
            observed_rents = [Decimal(str(c.observed_rent)) for c in comps]
            rent_per_sqfts = [Decimal(str(c.rent_per_sqft)) for c in comps]

            avg_rent = sum(observed_rents) / len(observed_rents)
            median_rent = self._compute_median(observed_rents)
            avg_per_sqft = sum(rent_per_sqfts) / len(rent_per_sqfts)

            rollups.append({
                "unit_type": unit_type,
                "Average_Observed_Rent": avg_rent,
                "Median_Observed_Rent": median_rent,
                "Average_Rent_Per_SqFt": avg_per_sqft,
                "comps": comps,
            })

        return rollups

    def get_comps_rollup(self, deal_id: int, unit_type: str) -> dict:
        """Return rollup statistics for rent comps of a given unit type.

        Args:
            deal_id: The Deal to query.
            unit_type: The unit type to filter by.

        Returns:
            Dict with Average_Observed_Rent, Median_Observed_Rent,
            Average_Rent_Per_SqFt, and the list of RentComp objects.

        Requirements: 3.4
        """
        comps = RentComp.query.filter_by(
            deal_id=deal_id, unit_type=unit_type
        ).all()

        if not comps:
            return {
                "Average_Observed_Rent": None,
                "Median_Observed_Rent": None,
                "Average_Rent_Per_SqFt": None,
                "comps": [],
            }

        observed_rents = [Decimal(str(c.observed_rent)) for c in comps]
        rent_per_sqfts = [Decimal(str(c.rent_per_sqft)) for c in comps]

        avg_rent = sum(observed_rents) / len(observed_rents)
        median_rent = self._compute_median(observed_rents)
        avg_per_sqft = sum(rent_per_sqfts) / len(rent_per_sqfts)

        return {
            "Average_Observed_Rent": avg_rent,
            "Median_Observed_Rent": median_rent,
            "Average_Rent_Per_SqFt": avg_per_sqft,
            "comps": comps,
        }

    # ------------------------------------------------------------------
    # Auto-fill from comps
    # ------------------------------------------------------------------

    def default_assumptions_from_comps(
        self, deal_id: int
    ) -> list[MarketRentAssumption]:
        """Auto-fill target_rent and post_reno_target_rent from comps.

        For each unit_type with >= 3 comps, sets target_rent and
        post_reno_target_rent to Average_Observed_Rent if the assumption
        doesn't already have a value set.

        Args:
            deal_id: The Deal to auto-fill assumptions for.

        Returns:
            List of MarketRentAssumption records that were created or updated.

        Requirements: 3.5
        """
        # Get all comps for this deal
        comps = RentComp.query.filter_by(deal_id=deal_id).all()

        # Group by unit_type
        comps_by_type: dict[str, list[RentComp]] = {}
        for comp in comps:
            comps_by_type.setdefault(comp.unit_type, []).append(comp)

        updated_assumptions: list[MarketRentAssumption] = []

        for unit_type, type_comps in comps_by_type.items():
            if len(type_comps) < 3:
                continue

            # Compute average observed rent
            observed_rents = [Decimal(str(c.observed_rent)) for c in type_comps]
            avg_rent = sum(observed_rents) / len(observed_rents)

            # Get or create assumption
            assumption = MarketRentAssumption.query.filter_by(
                deal_id=deal_id, unit_type=unit_type
            ).first()

            if assumption is None:
                assumption = MarketRentAssumption(
                    deal_id=deal_id,
                    unit_type=unit_type,
                    target_rent=avg_rent,
                    post_reno_target_rent=avg_rent,
                )
                db.session.add(assumption)
            else:
                if assumption.target_rent is None:
                    assumption.target_rent = avg_rent
                if assumption.post_reno_target_rent is None:
                    assumption.post_reno_target_rent = avg_rent

            updated_assumptions.append(assumption)

        if updated_assumptions:
            self._invalidate_cache(deal_id)

        db.session.flush()
        return updated_assumptions

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
