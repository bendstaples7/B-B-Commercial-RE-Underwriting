"""
Rent roll service for multifamily underwriting.

Manages Units and their associated Rent Roll Entries for a Deal.
Provides CRUD operations for units, rent roll entry management,
and summary statistics including occupancy and in-place rent totals.

Requirements: 2.1-2.6
"""

from __future__ import annotations

from decimal import Decimal

from app import db
from app.exceptions import DuplicateUnitIdentifierError
from app.models.pro_forma_result import ProFormaResult
from app.models.rent_roll_entry import RentRollEntry
from app.models.unit import Unit
from app.models.deal import Deal


# ---------------------------------------------------------------------------
# RentRollService
# ---------------------------------------------------------------------------


class RentRollService:
    """Service for managing Units and Rent Roll Entries within a Deal.

    Provides CRUD for units, one-to-one rent roll entry management,
    cache invalidation on mutations, and rent roll summary statistics.
    """

    # ------------------------------------------------------------------
    # Unit CRUD
    # ------------------------------------------------------------------

    def add_unit(self, deal_id: int, payload: dict) -> Unit:
        """Add a Unit to a Deal.

        Raises DuplicateUnitIdentifierError if the unit_identifier already
        exists for this Deal (Req 2.2).

        Args:
            deal_id: The Deal to add the unit to.
            payload: Dict with unit_identifier, unit_type, beds, baths, sqft,
                     occupancy_status.

        Returns:
            The created Unit model instance.

        Requirements: 2.1, 2.2
        """
        unit_identifier = payload["unit_identifier"]

        # Check for duplicate unit_identifier on this deal
        existing = Unit.query.filter_by(
            deal_id=deal_id, unit_identifier=unit_identifier
        ).first()
        if existing is not None:
            raise DuplicateUnitIdentifierError(
                message=f"Unit identifier '{unit_identifier}' already exists for deal {deal_id}",
                deal_id=deal_id,
                unit_identifier=unit_identifier,
            )

        unit = Unit(
            deal_id=deal_id,
            unit_identifier=unit_identifier,
            unit_type=payload.get("unit_type"),
            beds=payload.get("beds"),
            baths=payload.get("baths"),
            sqft=payload.get("sqft"),
            occupancy_status=payload["occupancy_status"],
        )
        db.session.add(unit)
        db.session.flush()

        # Invalidate pro forma cache
        self._invalidate_cache(deal_id)

        return unit

    def update_unit(self, deal_id: int, unit_id: int, payload: dict) -> Unit:
        """Update an existing Unit.

        Args:
            deal_id: The Deal the unit belongs to.
            unit_id: The ID of the Unit to update.
            payload: Dict with fields to update (unit_identifier, unit_type,
                     beds, baths, sqft, occupancy_status).

        Returns:
            The updated Unit model instance.

        Raises:
            ValueError: If the unit is not found for the given deal.
        """
        unit = Unit.query.filter_by(id=unit_id, deal_id=deal_id).first()
        if unit is None:
            raise ValueError(f"Unit {unit_id} not found for deal {deal_id}")

        updatable_fields = {
            "unit_identifier", "unit_type", "beds", "baths", "sqft",
            "occupancy_status",
        }

        for field_name, value in payload.items():
            if field_name in updatable_fields:
                setattr(unit, field_name, value)

        db.session.flush()

        # Invalidate pro forma cache
        self._invalidate_cache(deal_id)

        return unit

    def delete_unit(self, deal_id: int, unit_id: int) -> None:
        """Delete a Unit and its associated rent_roll_entry and rehab_plan_entry.

        Args:
            deal_id: The Deal the unit belongs to.
            unit_id: The ID of the Unit to delete.

        Raises:
            ValueError: If the unit is not found for the given deal.
        """
        unit = Unit.query.filter_by(id=unit_id, deal_id=deal_id).first()
        if unit is None:
            raise ValueError(f"Unit {unit_id} not found for deal {deal_id}")

        # Cascade handles rent_roll_entry and rehab_plan_entry deletion
        db.session.delete(unit)
        db.session.flush()

        # Invalidate pro forma cache
        self._invalidate_cache(deal_id)

    # ------------------------------------------------------------------
    # Rent Roll Entry management
    # ------------------------------------------------------------------

    def set_rent_roll_entry(self, deal_id: int, unit_id: int, payload: dict) -> RentRollEntry:
        """Create or update the Rent Roll Entry for a Unit (one-to-one).

        Args:
            deal_id: The Deal the unit belongs to.
            unit_id: The ID of the Unit.
            payload: Dict with current_rent, lease_start_date, lease_end_date,
                     notes.

        Returns:
            The created or updated RentRollEntry model instance.

        Raises:
            ValueError: If the unit is not found for the given deal.

        Requirements: 2.3
        """
        unit = Unit.query.filter_by(id=unit_id, deal_id=deal_id).first()
        if unit is None:
            raise ValueError(f"Unit {unit_id} not found for deal {deal_id}")

        entry = RentRollEntry.query.filter_by(unit_id=unit_id).first()

        if entry is None:
            entry = RentRollEntry(
                unit_id=unit_id,
                current_rent=payload["current_rent"],
                lease_start_date=payload.get("lease_start_date"),
                lease_end_date=payload.get("lease_end_date"),
                notes=payload.get("notes"),
            )
            db.session.add(entry)
        else:
            if "current_rent" in payload:
                entry.current_rent = payload["current_rent"]
            if "lease_start_date" in payload:
                entry.lease_start_date = payload["lease_start_date"]
            if "lease_end_date" in payload:
                entry.lease_end_date = payload["lease_end_date"]
            if "notes" in payload:
                entry.notes = payload["notes"]

        db.session.flush()

        # Invalidate pro forma cache
        self._invalidate_cache(deal_id)

        return entry

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_rent_roll_summary(self, deal_id: int) -> dict:
        """Return rent roll summary statistics for a Deal.

        Returns a dict with:
            - Total_Unit_Count
            - Occupied_Unit_Count
            - Vacant_Unit_Count
            - Occupancy_Rate (Occupied / Total, or 0 if no units)
            - Total_In_Place_Rent (sum of current_rent for Occupied units with entries)
            - Average_Rent_Per_Occupied_Unit (Total_In_Place_Rent / Occupied, or 0)
            - warnings: list that includes 'Rent_Roll_Incomplete' when
              rent_roll_entries count < deal.unit_count (Req 2.6)

        Args:
            deal_id: The Deal to summarize.

        Returns:
            Dict with summary statistics.

        Requirements: 2.5, 2.6
        """
        deal = Deal.query.get(deal_id)

        units = Unit.query.filter_by(deal_id=deal_id).all()

        total_unit_count = len(units)
        occupied_units = [u for u in units if u.occupancy_status == "Occupied"]
        occupied_unit_count = len(occupied_units)
        vacant_unit_count = total_unit_count - occupied_unit_count

        # Occupancy rate
        if total_unit_count > 0:
            occupancy_rate = Decimal(str(occupied_unit_count)) / Decimal(str(total_unit_count))
        else:
            occupancy_rate = Decimal("0")

        # Total in-place rent: sum of current_rent across Occupied units with rent_roll_entries
        total_in_place_rent = Decimal("0")
        for unit in occupied_units:
            if unit.rent_roll_entry is not None:
                total_in_place_rent += Decimal(str(unit.rent_roll_entry.current_rent))

        # Average rent per occupied unit
        if occupied_unit_count > 0:
            average_rent_per_occupied_unit = total_in_place_rent / Decimal(str(occupied_unit_count))
        else:
            average_rent_per_occupied_unit = Decimal("0")

        # Warnings
        warnings: list[str] = []
        rent_roll_entry_count = RentRollEntry.query.join(Unit).filter(
            Unit.deal_id == deal_id
        ).count()

        if deal is not None and rent_roll_entry_count < deal.unit_count:
            warnings.append("Rent_Roll_Incomplete")

        return {
            "Total_Unit_Count": total_unit_count,
            "Occupied_Unit_Count": occupied_unit_count,
            "Vacant_Unit_Count": vacant_unit_count,
            "Occupancy_Rate": occupancy_rate,
            "Total_In_Place_Rent": total_in_place_rent,
            "Average_Rent_Per_Occupied_Unit": average_rent_per_occupied_unit,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _invalidate_cache(self, deal_id: int) -> None:
        """Delete the cached ProFormaResult for a deal (Req 15.3).

        This runs in the same transaction as the write that triggered it.
        """
        ProFormaResult.query.filter_by(deal_id=deal_id).delete()
