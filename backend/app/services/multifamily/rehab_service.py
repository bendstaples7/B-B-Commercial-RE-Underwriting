"""
Rehab plan service for multifamily underwriting.

Manages per-unit renovation plans (RehabPlanEntry) for a Deal.
Provides set_plan_entry (create/update), monthly rollup, and budget total.

Requirements: 5.1-5.7
"""

from __future__ import annotations

from decimal import Decimal

from app import db
from app.models.pro_forma_result import ProFormaResult
from app.models.rehab_plan_entry import RehabPlanEntry
from app.models.unit import Unit


# ---------------------------------------------------------------------------
# RehabService
# ---------------------------------------------------------------------------


class RehabService:
    """Service for managing Rehab Plan Entries within a Deal.

    Provides one-to-one rehab plan entry management per unit,
    monthly rollup statistics, and total budget computation.
    """

    # ------------------------------------------------------------------
    # Plan entry management
    # ------------------------------------------------------------------

    def set_plan_entry(self, deal_id: int, unit_id: int, payload: dict) -> RehabPlanEntry:
        """Create or update the Rehab Plan Entry for a Unit (one-to-one).

        Computes stabilized_month = rehab_start_month + downtime_months.
        Sets stabilizes_after_horizon = True when stabilized_month > 24 (Req 5.4).
        When renovate_flag=False, ignores rehab_start_month/downtime/budget and
        sets stabilized_month=NULL (Req 5.5).

        Args:
            deal_id: The Deal the unit belongs to.
            unit_id: The ID of the Unit.
            payload: Dict with renovate_flag, current_rent,
                     suggested_post_reno_rent, underwritten_post_reno_rent,
                     rehab_start_month, downtime_months, rehab_budget,
                     scope_notes.

        Returns:
            The created or updated RehabPlanEntry model instance.

        Raises:
            ValueError: If the unit is not found for the given deal.

        Requirements: 5.1, 5.4, 5.5
        """
        unit = Unit.query.filter_by(id=unit_id, deal_id=deal_id).first()
        if unit is None:
            raise ValueError(f"Unit {unit_id} not found for deal {deal_id}")

        renovate_flag = payload.get("renovate_flag", False)

        # Compute derived fields based on renovate_flag (Req 5.5)
        if renovate_flag:
            rehab_start_month = payload.get("rehab_start_month")
            downtime_months = payload.get("downtime_months")
            rehab_budget = payload.get("rehab_budget")

            # Compute stabilized_month (Req 5.1)
            if rehab_start_month is not None and downtime_months is not None:
                stabilized_month = rehab_start_month + downtime_months
            else:
                stabilized_month = None

            # Set stabilizes_after_horizon flag (Req 5.4)
            if stabilized_month is not None and stabilized_month > 24:
                stabilizes_after_horizon = True
            else:
                stabilizes_after_horizon = False
        else:
            # Renovate_Flag=False: ignore rehab timing/budget fields (Req 5.5)
            rehab_start_month = None
            downtime_months = None
            stabilized_month = None
            rehab_budget = None
            stabilizes_after_horizon = False

        entry = RehabPlanEntry.query.filter_by(unit_id=unit_id).first()

        if entry is None:
            entry = RehabPlanEntry(
                unit_id=unit_id,
                renovate_flag=renovate_flag,
                current_rent=payload.get("current_rent"),
                suggested_post_reno_rent=payload.get("suggested_post_reno_rent"),
                underwritten_post_reno_rent=payload.get("underwritten_post_reno_rent"),
                rehab_start_month=rehab_start_month,
                downtime_months=downtime_months,
                stabilized_month=stabilized_month,
                rehab_budget=rehab_budget,
                scope_notes=payload.get("scope_notes"),
                stabilizes_after_horizon=stabilizes_after_horizon,
            )
            db.session.add(entry)
        else:
            entry.renovate_flag = renovate_flag
            entry.current_rent = payload.get("current_rent", entry.current_rent)
            entry.suggested_post_reno_rent = payload.get(
                "suggested_post_reno_rent", entry.suggested_post_reno_rent
            )
            entry.underwritten_post_reno_rent = payload.get(
                "underwritten_post_reno_rent", entry.underwritten_post_reno_rent
            )
            entry.rehab_start_month = rehab_start_month
            entry.downtime_months = downtime_months
            entry.stabilized_month = stabilized_month
            entry.rehab_budget = rehab_budget
            entry.scope_notes = payload.get("scope_notes", entry.scope_notes)
            entry.stabilizes_after_horizon = stabilizes_after_horizon

        db.session.flush()

        # Invalidate pro forma cache
        self._invalidate_cache(deal_id)

        return entry

    # ------------------------------------------------------------------
    # Rollup queries
    # ------------------------------------------------------------------

    def get_monthly_rollup(self, deal_id: int) -> list[dict]:
        """Return a monthly rehab rollup for months 1-24.

        For each month M in 1..24:
        - Units_Starting_Rehab_Count: count of units where rehab_start_month == M
        - Units_Offline_Count: count of units where rehab_start_month <= M < stabilized_month
        - Units_Stabilizing_Count: count of units where stabilized_month == M
        - CapEx_Spend: sum of rehab_budget for units where rehab_start_month == M

        Args:
            deal_id: The Deal to compute the rollup for.

        Returns:
            A list of 24 dicts, one per month.

        Requirements: 5.6
        """
        # Fetch all rehab plan entries for units in this deal where renovate_flag=True
        entries = (
            RehabPlanEntry.query
            .join(Unit)
            .filter(Unit.deal_id == deal_id)
            .filter(RehabPlanEntry.renovate_flag.is_(True))
            .all()
        )

        rollup: list[dict] = []

        for month in range(1, 25):
            units_starting = 0
            units_offline = 0
            units_stabilizing = 0
            capex_spend = Decimal("0")

            for entry in entries:
                start = entry.rehab_start_month
                stabilized = entry.stabilized_month

                if start is None:
                    continue

                # Units_Starting_Rehab_Count: rehab_start_month == M
                if start == month:
                    units_starting += 1
                    # CapEx_Spend: sum of rehab_budget where rehab_start_month == M
                    if entry.rehab_budget is not None:
                        capex_spend += Decimal(str(entry.rehab_budget))

                # Units_Offline_Count: rehab_start_month <= M < stabilized_month
                if stabilized is not None and start <= month < stabilized:
                    units_offline += 1

                # Units_Stabilizing_Count: stabilized_month == M
                if stabilized is not None and stabilized == month:
                    units_stabilizing += 1

            rollup.append({
                "month": month,
                "Units_Starting_Rehab_Count": units_starting,
                "Units_Offline_Count": units_offline,
                "Units_Stabilizing_Count": units_stabilizing,
                "CapEx_Spend": capex_spend,
            })

        return rollup

    def get_rehab_budget_total(self, deal_id: int) -> Decimal:
        """Return the total rehab budget across units where renovate_flag=True.

        Args:
            deal_id: The Deal to compute the total for.

        Returns:
            Sum of rehab_budget across renovating units.

        Requirements: 5.7
        """
        entries = (
            RehabPlanEntry.query
            .join(Unit)
            .filter(Unit.deal_id == deal_id)
            .filter(RehabPlanEntry.renovate_flag.is_(True))
            .all()
        )

        total = Decimal("0")
        for entry in entries:
            if entry.rehab_budget is not None:
                total += Decimal(str(entry.rehab_budget))

        return total

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _invalidate_cache(self, deal_id: int) -> None:
        """Delete the cached ProFormaResult for a deal (Req 15.3).

        This runs in the same transaction as the write that triggered it.
        """
        ProFormaResult.query.filter_by(deal_id=deal_id).delete()
