"""
Deal management service for multifamily underwriting.

Provides CRUD operations for Deal records, permission checks, Lead linking,
audit trail logging, cache invalidation, and snapshot building for the
pro forma engine.

Requirements: 1.1-1.8, 14.2-14.4, 15.3-15.4
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app import db
from app.exceptions import AuthorizationException, ValidationException
from app.models.deal import Deal
from app.models.deal_audit_trail import DealAuditTrail
from app.models.deal_lender_selection import DealLenderSelection
from app.models.funding_source import FundingSource
from app.models.lead import Lead
from app.models.lead_deal_link import LeadDealLink
from app.models.lender_profile import LenderProfile
from app.models.market_rent_assumption import MarketRentAssumption
from app.models.pro_forma_result import ProFormaResult
from app.models.rehab_plan_entry import RehabPlanEntry
from app.models.rent_roll_entry import RentRollEntry
from app.models.unit import Unit
from app.services.multifamily.pro_forma_inputs import (
    DealInputs,
    DealSnapshot,
    FundingSourceSnapshot,
    LenderProfileSnapshot,
    MarketRentSnapshot,
    OpExAssumptions,
    RehabPlanSnapshot,
    RentRollSnapshot,
    ReserveAssumptions,
    UnitSnapshot,
)


# ---------------------------------------------------------------------------
# Helper: zero-safe Decimal conversion
# ---------------------------------------------------------------------------


def _dec(value: Any, default: str = "0") -> Decimal:
    """Convert a value to Decimal, defaulting to *default* when None."""
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# DealService
# ---------------------------------------------------------------------------


class DealService:
    """Service for managing multifamily Deal records.

    Provides CRUD, permission checks, Lead linking, audit logging,
    cache invalidation, and snapshot building for the pro forma engine.
    """

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_deal(self, user_id: str, payload: dict) -> Deal:
        """Create a new Deal record.

        Args:
            user_id: The authenticated user creating the deal.
            payload: Dict with property_address, unit_count, purchase_price,
                     and optional fields (closing_costs, close_date, etc.).

        Returns:
            The persisted Deal model instance.

        Requirements: 1.1
        """
        deal = Deal(
            created_by_user_id=user_id,
            property_address=payload["property_address"],
            unit_count=payload["unit_count"],
            purchase_price=payload["purchase_price"],
            closing_costs=payload.get("closing_costs", Decimal("0")),
            close_date=payload.get("close_date"),
            property_city=payload.get("property_city"),
            property_state=payload.get("property_state"),
            property_zip=payload.get("property_zip"),
            vacancy_rate=payload.get("vacancy_rate", Decimal("0.05")),
            other_income_monthly=payload.get("other_income_monthly", Decimal("0")),
            management_fee_rate=payload.get("management_fee_rate", Decimal("0.08")),
            reserve_per_unit_per_year=payload.get("reserve_per_unit_per_year", Decimal("250")),
            property_taxes_annual=payload.get("property_taxes_annual"),
            insurance_annual=payload.get("insurance_annual"),
            utilities_annual=payload.get("utilities_annual"),
            repairs_and_maintenance_annual=payload.get("repairs_and_maintenance_annual"),
            admin_and_marketing_annual=payload.get("admin_and_marketing_annual"),
            payroll_annual=payload.get("payroll_annual"),
            other_opex_annual=payload.get("other_opex_annual"),
            interest_reserve_amount=payload.get("interest_reserve_amount", Decimal("0")),
            custom_cap_rate=payload.get("custom_cap_rate"),
            status=payload.get("status", "draft"),
        )
        db.session.add(deal)
        db.session.flush()

        self._log_audit(deal.id, user_id, "create", payload)
        return deal

    def get_deal(self, user_id: str, deal_id: int) -> Deal:
        """Retrieve a Deal by ID with permission check.

        Args:
            user_id: The requesting user.
            deal_id: The Deal to retrieve.

        Returns:
            The Deal model instance.

        Raises:
            ValidationException: If the deal does not exist.
            AuthorizationException: If the user does not have access.

        Requirements: 1.4
        """
        deal = Deal.query.filter_by(id=deal_id).filter(Deal.deleted_at.is_(None)).first()
        if deal is None:
            raise ValidationException(
                message=f"Deal {deal_id} not found",
                field="deal_id",
                value=deal_id,
            )
        if not self.user_has_access(user_id, deal_id):
            raise AuthorizationException("Access denied to this deal")
        return deal

    def list_deals(self, user_id: str, filters: dict | None = None) -> list[Deal]:
        """List Deals owned by the requesting user.

        Filters out soft-deleted records.

        Args:
            user_id: The requesting user.
            filters: Optional dict with filter criteria (status, etc.).

        Returns:
            List of Deal model instances.

        Requirements: 1.5
        """
        query = Deal.query.filter_by(created_by_user_id=user_id).filter(
            Deal.deleted_at.is_(None)
        )

        if filters:
            if "status" in filters:
                query = query.filter_by(status=filters["status"])

        return query.order_by(Deal.updated_at.desc()).all()

    def update_deal(self, user_id: str, deal_id: int, payload: dict) -> Deal:
        """Update a Deal and invalidate the pro_forma_results cache.

        Args:
            user_id: The requesting user.
            deal_id: The Deal to update.
            payload: Dict with fields to update.

        Returns:
            The updated Deal model instance.

        Requirements: 1.6, 15.3
        """
        deal = self.get_deal(user_id, deal_id)

        updatable_fields = {
            "property_address", "property_city", "property_state", "property_zip",
            "unit_count", "purchase_price", "closing_costs", "close_date",
            "vacancy_rate", "other_income_monthly", "management_fee_rate",
            "reserve_per_unit_per_year", "property_taxes_annual", "insurance_annual",
            "utilities_annual", "repairs_and_maintenance_annual",
            "admin_and_marketing_annual", "payroll_annual", "other_opex_annual",
            "interest_reserve_amount", "custom_cap_rate", "status",
        }

        changed_fields = {}
        for field_name, value in payload.items():
            if field_name in updatable_fields:
                old_value = getattr(deal, field_name)
                setattr(deal, field_name, value)
                changed_fields[field_name] = {
                    "old": str(old_value) if old_value is not None else None,
                    "new": str(value) if value is not None else None,
                }

        # Invalidate pro_forma_results cache in the same transaction (Req 15.3)
        self._invalidate_cache(deal_id)

        db.session.flush()
        self._log_audit(deal_id, user_id, "update", changed_fields)
        return deal

    def soft_delete_deal(self, user_id: str, deal_id: int) -> None:
        """Soft-delete a Deal by setting deleted_at timestamp.

        Args:
            user_id: The requesting user.
            deal_id: The Deal to soft-delete.

        Requirements: 1.7
        """
        deal = self.get_deal(user_id, deal_id)
        deal.deleted_at = datetime.utcnow()
        db.session.flush()

        self._log_audit(deal_id, user_id, "soft_delete", None)

    # ------------------------------------------------------------------
    # Lead linking
    # ------------------------------------------------------------------

    def link_to_lead(self, user_id: str, deal_id: int, lead_id: int) -> None:
        """Link a Deal to a Lead for permission inheritance.

        Args:
            user_id: The requesting user.
            deal_id: The Deal to link.
            lead_id: The Lead to link to.

        Requirements: 14.2
        """
        # Verify deal access
        self.get_deal(user_id, deal_id)

        # Verify lead exists
        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ValidationException(
                message=f"Lead {lead_id} not found",
                field="lead_id",
                value=lead_id,
            )

        # Check if link already exists (idempotent)
        existing = LeadDealLink.query.filter_by(
            lead_id=lead_id, deal_id=deal_id
        ).first()
        if existing is not None:
            return

        link = LeadDealLink(lead_id=lead_id, deal_id=deal_id)
        db.session.add(link)
        db.session.flush()

        self._log_audit(deal_id, user_id, "link_to_lead", {"lead_id": lead_id})

    def suggest_lead_match(self, user_id: str, property_address: str) -> Lead | None:
        """Suggest a matching Lead based on property address.

        Args:
            user_id: The requesting user.
            property_address: The address to match against.

        Returns:
            A matching Lead or None.

        Requirements: 1.8
        """
        if not property_address:
            return None

        # Exact match on property_street
        lead = Lead.query.filter(
            Lead.property_street == property_address
        ).first()
        return lead

    # ------------------------------------------------------------------
    # Permission check
    # ------------------------------------------------------------------

    def user_has_access(self, user_id: str, deal_id: int) -> bool:
        """Check if a user has access to a Deal.

        Access is granted if:
        1. The user is the direct owner (deal.created_by_user_id == user_id), OR
        2. Any LeadDealLink for this deal points to a Lead that the user can
           access (for now, just check if the link exists).

        Args:
            user_id: The user to check.
            deal_id: The Deal to check access for.

        Returns:
            True if the user has access, False otherwise.

        Requirements: 14.3
        """
        deal = Deal.query.filter_by(id=deal_id).filter(Deal.deleted_at.is_(None)).first()
        if deal is None:
            return False

        # Check 1: Direct ownership
        if deal.created_by_user_id == user_id:
            return True

        # Check 2: Access via LeadDealLink
        link_exists = LeadDealLink.query.filter_by(deal_id=deal_id).first()
        if link_exists is not None:
            return True

        return False

    # ------------------------------------------------------------------
    # Snapshot builder
    # ------------------------------------------------------------------

    def build_inputs_snapshot(self, deal_id: int) -> DealInputs:
        """Populate frozen dataclasses from ORM rows for the pro forma engine.

        Args:
            deal_id: The Deal to build the snapshot for.

        Returns:
            A fully populated DealInputs instance.

        Requirements: 8.1-8.11
        """
        deal = Deal.query.get(deal_id)

        # DealSnapshot
        deal_snapshot = DealSnapshot(
            deal_id=deal.id,
            purchase_price=_dec(deal.purchase_price),
            closing_costs=_dec(deal.closing_costs),
            vacancy_rate=_dec(deal.vacancy_rate),
            other_income_monthly=_dec(deal.other_income_monthly),
            management_fee_rate=_dec(deal.management_fee_rate),
            reserve_per_unit_per_year=_dec(deal.reserve_per_unit_per_year),
            interest_reserve_amount=_dec(deal.interest_reserve_amount),
            custom_cap_rate=_dec(deal.custom_cap_rate) if deal.custom_cap_rate is not None else None,
            unit_count=deal.unit_count,
        )

        # UnitSnapshots
        units_orm = Unit.query.filter_by(deal_id=deal_id).all()
        unit_snapshots = tuple(
            UnitSnapshot(
                unit_id=u.unit_identifier,
                unit_type=u.unit_type or "",
                beds=u.beds or 0,
                baths=_dec(u.baths),
                sqft=u.sqft or 0,
                occupancy_status=u.occupancy_status,
            )
            for u in units_orm
        )

        # RentRollSnapshots
        rent_roll_snapshots = tuple(
            RentRollSnapshot(
                unit_id=u.unit_identifier,
                current_rent=_dec(u.rent_roll_entry.current_rent),
            )
            for u in units_orm
            if u.rent_roll_entry is not None
        )

        # RehabPlanSnapshots
        rehab_plan_snapshots = tuple(
            RehabPlanSnapshot(
                unit_id=u.unit_identifier,
                renovate_flag=u.rehab_plan_entry.renovate_flag,
                current_rent=_dec(u.rehab_plan_entry.current_rent),
                underwritten_post_reno_rent=(
                    _dec(u.rehab_plan_entry.underwritten_post_reno_rent)
                    if u.rehab_plan_entry.underwritten_post_reno_rent is not None
                    else None
                ),
                rehab_start_month=u.rehab_plan_entry.rehab_start_month,
                downtime_months=u.rehab_plan_entry.downtime_months,
                stabilized_month=u.rehab_plan_entry.stabilized_month,
                rehab_budget=_dec(u.rehab_plan_entry.rehab_budget),
            )
            for u in units_orm
            if u.rehab_plan_entry is not None
        )

        # MarketRentSnapshots
        market_rents_orm = MarketRentAssumption.query.filter_by(deal_id=deal_id).all()
        market_rent_snapshots = tuple(
            MarketRentSnapshot(
                unit_type=m.unit_type,
                target_rent=_dec(m.target_rent),
                post_reno_target_rent=_dec(m.post_reno_target_rent),
            )
            for m in market_rents_orm
        )

        # OpExAssumptions
        opex = OpExAssumptions(
            property_taxes_annual=_dec(deal.property_taxes_annual),
            insurance_annual=_dec(deal.insurance_annual),
            utilities_annual=_dec(deal.utilities_annual),
            repairs_and_maintenance_annual=_dec(deal.repairs_and_maintenance_annual),
            admin_and_marketing_annual=_dec(deal.admin_and_marketing_annual),
            payroll_annual=_dec(deal.payroll_annual),
            other_opex_annual=_dec(deal.other_opex_annual),
            management_fee_rate=_dec(deal.management_fee_rate),
        )

        # ReserveAssumptions
        reserves = ReserveAssumptions(
            reserve_per_unit_per_year=_dec(deal.reserve_per_unit_per_year),
            unit_count=deal.unit_count,
        )

        # LenderProfileSnapshots (primary lender for each scenario)
        lender_scenario_a = self._get_primary_lender_snapshot(deal_id, "A")
        lender_scenario_b = self._get_primary_lender_snapshot(deal_id, "B")

        # FundingSourceSnapshots
        funding_sources_orm = FundingSource.query.filter_by(deal_id=deal_id).all()
        funding_source_snapshots = tuple(
            FundingSourceSnapshot(
                source_type=fs.source_type,
                total_available=_dec(fs.total_available),
                interest_rate=_dec(fs.interest_rate),
                origination_fee_rate=_dec(fs.origination_fee_rate),
            )
            for fs in funding_sources_orm
        )

        return DealInputs(
            deal=deal_snapshot,
            units=unit_snapshots,
            rent_roll=rent_roll_snapshots,
            rehab_plan=rehab_plan_snapshots,
            market_rents=market_rent_snapshots,
            opex=opex,
            reserves=reserves,
            lender_scenario_a=lender_scenario_a,
            lender_scenario_b=lender_scenario_b,
            funding_sources=funding_source_snapshots,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_primary_lender_snapshot(
        self, deal_id: int, scenario: str
    ) -> LenderProfileSnapshot | None:
        """Get the primary lender profile snapshot for a scenario.

        Args:
            deal_id: The Deal ID.
            scenario: 'A' or 'B'.

        Returns:
            LenderProfileSnapshot or None if no primary lender is attached.
        """
        selection = DealLenderSelection.query.filter_by(
            deal_id=deal_id, scenario=scenario, is_primary=True
        ).first()
        if selection is None:
            return None

        lp = LenderProfile.query.get(selection.lender_profile_id)
        if lp is None:
            return None

        return LenderProfileSnapshot(
            lender_type=lp.lender_type,
            origination_fee_rate=_dec(lp.origination_fee_rate),
            ltv_total_cost=_dec(lp.ltv_total_cost) if lp.ltv_total_cost is not None else None,
            construction_rate=_dec(lp.construction_rate) if lp.construction_rate is not None else None,
            construction_io_months=lp.construction_io_months,
            perm_rate=_dec(lp.perm_rate) if lp.perm_rate is not None else None,
            perm_amort_years=lp.perm_amort_years,
            max_purchase_ltv=_dec(lp.max_purchase_ltv) if lp.max_purchase_ltv is not None else None,
            all_in_rate=_dec(lp.all_in_rate) if lp.all_in_rate is not None else None,
            amort_years=lp.amort_years,
        )

    def _invalidate_cache(self, deal_id: int) -> None:
        """Delete the cached ProFormaResult for a deal (Req 15.3).

        This runs in the same transaction as the write that triggered it.
        """
        ProFormaResult.query.filter_by(deal_id=deal_id).delete()

    @staticmethod
    def _sanitize_for_json(obj: Any) -> Any:
        """Recursively convert non-JSON-serializable types to strings.

        Handles datetime.date, datetime.datetime, and Decimal objects
        so that changed_fields dicts can be stored in the JSON column.
        """
        import datetime as _dt

        if isinstance(obj, dict):
            return {k: DealService._sanitize_for_json(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [DealService._sanitize_for_json(v) for v in obj]
        if isinstance(obj, (_dt.datetime, _dt.date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return str(obj)
        return obj

    def _log_audit(
        self, deal_id: int, user_id: str, action: str, changed_fields: Any
    ) -> None:
        """Log a mutation to the deal_audit_trails table (Req 14.4).

        Args:
            deal_id: The Deal that was mutated.
            user_id: The user who performed the action.
            action: The action name (create, update, soft_delete, link_to_lead).
            changed_fields: JSON-serializable dict of changed fields, or None.
        """
        audit = DealAuditTrail(
            deal_id=deal_id,
            user_id=user_id,
            action=action,
            changed_fields=self._sanitize_for_json(changed_fields),
        )
        db.session.add(audit)
