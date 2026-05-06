"""
Lender profile management service for multifamily underwriting.

Provides CRUD operations for reusable LenderProfile records, rate/LTV
validation, attachment to Deal scenarios (with limit enforcement and
primary-flag management), and cache invalidation on attachment changes.

Requirements: 6.1-6.7
"""

from __future__ import annotations

from decimal import Decimal

from app import db
from app.exceptions import DealValidationError, LenderAttachmentLimitError
from app.models.deal_lender_selection import DealLenderSelection
from app.models.lender_profile import LenderProfile
from app.models.pro_forma_result import ProFormaResult


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RATE_MIN = Decimal("0")
_RATE_MAX = Decimal("0.30")
_LTV_MIN = Decimal("0")
_LTV_MAX = Decimal("1")
_MAX_LENDERS_PER_SCENARIO = 3

# Fields that must satisfy the rate bound [0, 0.30]
_RATE_FIELDS = (
    "construction_rate",
    "perm_rate",
    "origination_fee_rate",
    "treasury_5y_rate",
)

# Fields that must satisfy the LTV bound [0, 1]
_LTV_FIELDS = (
    "ltv_total_cost",
    "max_purchase_ltv",
)


# ---------------------------------------------------------------------------
# LenderService
# ---------------------------------------------------------------------------


class LenderService:
    """Service for managing reusable Lender Profiles and Deal attachments.

    Provides CRUD, rate/LTV validation, scenario attachment with limit
    enforcement, primary-flag management, and cache invalidation.
    """

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_profile(self, user_id: str, payload: dict) -> LenderProfile:
        """Create a new LenderProfile with rate/LTV bounds validation.

        Args:
            user_id: The authenticated user creating the profile.
            payload: Dict with company, lender_type, and type-specific fields.

        Returns:
            The persisted LenderProfile model instance.

        Raises:
            DealValidationError: If any rate is outside [0, 0.30] or any LTV
                is outside [0, 1].

        Requirements: 6.1, 6.2, 6.3, 6.4
        """
        self._validate_rate_and_ltv_bounds(payload)

        profile = LenderProfile(
            created_by_user_id=user_id,
            company=payload["company"],
            lender_type=payload["lender_type"],
            origination_fee_rate=payload["origination_fee_rate"],
            prepay_penalty_description=payload.get("prepay_penalty_description"),
            # Construction_To_Perm fields
            ltv_total_cost=payload.get("ltv_total_cost"),
            construction_rate=payload.get("construction_rate"),
            construction_io_months=payload.get("construction_io_months"),
            construction_term_months=payload.get("construction_term_months"),
            perm_rate=payload.get("perm_rate"),
            perm_amort_years=payload.get("perm_amort_years"),
            min_interest_or_yield=payload.get("min_interest_or_yield"),
            # Self_Funded_Reno fields
            max_purchase_ltv=payload.get("max_purchase_ltv"),
            treasury_5y_rate=payload.get("treasury_5y_rate"),
            spread_bps=payload.get("spread_bps"),
            term_years=payload.get("term_years"),
            amort_years=payload.get("amort_years"),
        )
        db.session.add(profile)
        db.session.flush()
        return profile

    def list_profiles(
        self, user_id: str, lender_type: str | None = None
    ) -> list[LenderProfile]:
        """List LenderProfiles owned by the user, optionally filtered by type.

        Args:
            user_id: The requesting user.
            lender_type: Optional filter ('Construction_To_Perm' or 'Self_Funded_Reno').

        Returns:
            List of LenderProfile model instances.

        Requirements: 6.1
        """
        query = LenderProfile.query.filter_by(created_by_user_id=user_id)
        if lender_type is not None:
            query = query.filter_by(lender_type=lender_type)
        return query.order_by(LenderProfile.created_at.desc()).all()

    def update_profile(
        self, user_id: str, profile_id: int, payload: dict
    ) -> LenderProfile:
        """Update an existing LenderProfile (re-validates rate/LTV bounds).

        Args:
            user_id: The requesting user.
            profile_id: The LenderProfile to update.
            payload: Dict with fields to update.

        Returns:
            The updated LenderProfile model instance.

        Raises:
            DealValidationError: If any rate is outside [0, 0.30] or any LTV
                is outside [0, 1].
            ValueError: If the profile does not exist or is not owned by the user.

        Requirements: 6.3, 6.4
        """
        profile = LenderProfile.query.filter_by(
            id=profile_id, created_by_user_id=user_id
        ).first()
        if profile is None:
            raise ValueError(
                f"Lender profile {profile_id} not found for user {user_id}"
            )

        self._validate_rate_and_ltv_bounds(payload)

        updatable_fields = {
            "company", "lender_type", "origination_fee_rate",
            "prepay_penalty_description", "ltv_total_cost",
            "construction_rate", "construction_io_months",
            "construction_term_months", "perm_rate", "perm_amort_years",
            "min_interest_or_yield", "max_purchase_ltv", "treasury_5y_rate",
            "spread_bps", "term_years", "amort_years",
        }

        for field_name, value in payload.items():
            if field_name in updatable_fields:
                setattr(profile, field_name, value)

        db.session.flush()
        return profile

    def delete_profile(self, user_id: str, profile_id: int) -> None:
        """Delete a LenderProfile owned by the user.

        Args:
            user_id: The requesting user.
            profile_id: The LenderProfile to delete.

        Raises:
            ValueError: If the profile does not exist or is not owned by the user.
        """
        profile = LenderProfile.query.filter_by(
            id=profile_id, created_by_user_id=user_id
        ).first()
        if profile is None:
            raise ValueError(
                f"Lender profile {profile_id} not found for user {user_id}"
            )

        db.session.delete(profile)
        db.session.flush()

    # ------------------------------------------------------------------
    # Deal attachment
    # ------------------------------------------------------------------

    def attach_to_deal(
        self,
        deal_id: int,
        scenario: str,
        profile_id: int,
        is_primary: bool = False,
    ) -> DealLenderSelection:
        """Attach a LenderProfile to a Deal's scenario.

        Enforces at most 3 lender profiles per (deal_id, scenario). If
        is_primary=True, unsets any existing primary for that combination.

        Args:
            deal_id: The Deal to attach to.
            scenario: 'A' or 'B'.
            profile_id: The LenderProfile to attach.
            is_primary: Whether this selection is the primary lender.

        Returns:
            The created DealLenderSelection model instance.

        Raises:
            LenderAttachmentLimitError: When > 3 profiles per scenario.

        Requirements: 6.5, 6.6, 6.7
        """
        # Enforce limit of 3 per (deal_id, scenario)
        current_count = DealLenderSelection.query.filter_by(
            deal_id=deal_id, scenario=scenario
        ).count()

        if current_count >= _MAX_LENDERS_PER_SCENARIO:
            raise LenderAttachmentLimitError(
                message=(
                    f"Cannot attach more than {_MAX_LENDERS_PER_SCENARIO} "
                    f"lender profiles to scenario {scenario} on deal {deal_id}"
                ),
                deal_id=deal_id,
                scenario=scenario,
                limit=_MAX_LENDERS_PER_SCENARIO,
            )

        # If is_primary, unset any existing primary for this (deal_id, scenario)
        if is_primary:
            DealLenderSelection.query.filter_by(
                deal_id=deal_id, scenario=scenario, is_primary=True
            ).update({"is_primary": False})

        selection = DealLenderSelection(
            deal_id=deal_id,
            lender_profile_id=profile_id,
            scenario=scenario,
            is_primary=is_primary,
        )
        db.session.add(selection)

        # Invalidate pro_forma_results cache (Req 15.3)
        self._invalidate_cache(deal_id)

        db.session.flush()
        return selection

    def detach_from_deal(self, deal_id: int, selection_id: int) -> None:
        """Remove a lender selection from a Deal.

        Args:
            deal_id: The Deal the selection belongs to.
            selection_id: The DealLenderSelection ID to remove.

        Raises:
            ValueError: If the selection does not exist for the given deal.
        """
        selection = DealLenderSelection.query.filter_by(
            id=selection_id, deal_id=deal_id
        ).first()
        if selection is None:
            raise ValueError(
                f"Lender selection {selection_id} not found for deal {deal_id}"
            )

        db.session.delete(selection)

        # Invalidate pro_forma_results cache (Req 15.3)
        self._invalidate_cache(deal_id)

        db.session.flush()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_rate_and_ltv_bounds(self, payload: dict) -> None:
        """Validate rate fields are in [0, 0.30] and LTV fields are in [0, 1].

        Only validates fields that are present in the payload.

        Raises:
            DealValidationError: On first field that violates bounds.
        """
        for field in _RATE_FIELDS:
            value = payload.get(field)
            if value is None:
                continue
            dec_value = Decimal(str(value))
            if dec_value < _RATE_MIN or dec_value > _RATE_MAX:
                raise DealValidationError(
                    message=f"{field} must be between {_RATE_MIN} and {_RATE_MAX}, got {dec_value}",
                    field=field,
                    constraint=f"[{_RATE_MIN}, {_RATE_MAX}]",
                )

        for field in _LTV_FIELDS:
            value = payload.get(field)
            if value is None:
                continue
            dec_value = Decimal(str(value))
            if dec_value < _LTV_MIN or dec_value > _LTV_MAX:
                raise DealValidationError(
                    message=f"{field} must be between {_LTV_MIN} and {_LTV_MAX}, got {dec_value}",
                    field=field,
                    constraint=f"[{_LTV_MIN}, {_LTV_MAX}]",
                )

    def _invalidate_cache(self, deal_id: int) -> None:
        """Delete the cached ProFormaResult for a deal (Req 15.3).

        This runs in the same transaction as the write that triggered it.
        """
        ProFormaResult.query.filter_by(deal_id=deal_id).delete()
