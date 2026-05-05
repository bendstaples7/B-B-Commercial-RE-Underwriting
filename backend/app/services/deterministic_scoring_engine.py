"""Deterministic Lead Scoring Engine.

Computes separate scores for residential and commercial leads using
explicit point-based rules. No AI or machine learning is used.

Each recalculation creates a new LeadScore record (append-only history).
All scoring functions are pure (no DB access) except the recalculate_*
orchestration methods.
"""
import logging
from datetime import date, datetime
from typing import Optional

from app import db
from app.models.lead import Lead
from app.models.lead_score import LeadScore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BULK_BATCH_SIZE = 500

# Motivation keywords that indicate seller willingness
MOTIVATION_KEYWORDS = [
    "motivated", "distressed", "vacant", "abandoned", "probate",
    "divorce", "tax lien", "code violation", "fire damage",
    "behind on payments", "pre-foreclosure", "foreclosure",
    "estate", "inherited", "tired landlord", "out of state",
    "needs work", "deferred maintenance", "boarded up",
]

# Residential scoring dimension maximums
RESIDENTIAL_MAX_POINTS = {
    "property_type_fit": 20,
    "neighborhood_fit": 15,
    "unit_count_fit": 15,
    "absentee_owner": 10,
    "owner_mailing_quality": 10,
    "years_owned": 10,
    "existing_notes_motivation": 10,
    "manual_priority": 10,
}

# Commercial scoring dimension maximums
COMMERCIAL_MAX_POINTS = {
    "property_type_fit": 20,
    "condo_clarity": 20,
    "building_sale_possible": 15,
    "neighborhood_fit": 10,
    "owner_concentration": 10,
    "absentee_owner": 10,
    "building_size_fit": 5,
    "existing_notes_motivation": 5,
    "manual_priority": 5,
}

# Data quality field-to-points mapping
DATA_QUALITY_FIELDS = {
    "has_pin": 20,
    "has_property_address": 15,
    "has_normalized_address": 10,
    "has_owner_name": 15,
    "has_owner_mailing_address": 15,
    "has_property_type_or_assessor_class": 10,
    "has_estimated_unit_count_or_building_size": 10,
    "has_source_reference": 5,
}

# Missing data fields to check (superset used for the missing_data array)
MISSING_DATA_FIELDS = [
    "pin", "property_address", "normalized_address", "owner_name",
    "owner_mailing_address", "property_type", "assessor_class",
    "estimated_units", "building_sqft", "years_owned", "neighborhood",
    "condo_risk_status", "building_sale_possible", "violation_data",
    "permit_data", "tax_data", "skip_trace_data",
]

# Tier thresholds
TIER_A_MIN = 75
TIER_B_MIN = 60
TIER_C_MIN = 40

# Allowed recommended actions
ALLOWED_ACTIONS = {
    "review_now", "enrich_data", "mail_ready", "call_ready",
    "valuation_needed", "suppress", "nurture", "needs_manual_review",
}


class DeterministicScoringEngine:
    """Deterministic, explainable lead scoring engine.

    Computes separate scores for residential and commercial leads using
    point-based rules. Stores full score breakdowns in LeadScore records.
    """

    # ------------------------------------------------------------------
    # Residential Scoring
    # ------------------------------------------------------------------

    def calculate_residential_score(self, lead: Lead) -> dict:
        """Calculate the residential motivation score for a lead.

        Returns
        -------
        dict
            Keys: total_score (float), score_details (dict), score_version (str)
        """
        details = {}

        details["property_type_fit"] = self._residential_property_type_fit(lead)
        details["neighborhood_fit"] = self._residential_neighborhood_fit(lead)
        details["unit_count_fit"] = self._residential_unit_count_fit(lead)
        details["absentee_owner"] = self._absentee_owner_score(lead)
        details["owner_mailing_quality"] = self._owner_mailing_quality(lead)
        details["years_owned"] = self._years_owned_score(lead)
        details["existing_notes_motivation"] = self._notes_motivation_score(
            lead, max_points=RESIDENTIAL_MAX_POINTS["existing_notes_motivation"]
        )
        details["manual_priority"] = self._manual_priority_score(
            lead, max_points=RESIDENTIAL_MAX_POINTS["manual_priority"]
        )

        total_score = sum(details.values())

        return {
            "total_score": total_score,
            "score_details": details,
            "score_version": "residential_v1_internal_data",
        }

    # ------------------------------------------------------------------
    # Residential dimension helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _residential_property_type_fit(lead: Lead) -> float:
        """Multi-family/2-4 unit = 20, SFR = 10, other = 5, missing = 0."""
        if not lead.property_type:
            return 0.0

        pt = lead.property_type.strip().lower()
        multi_family_types = {
            "multi_family", "multi family", "multifamily",
            "duplex", "triplex", "fourplex", "2-4 unit",
        }
        sfr_types = {"single_family", "single family", "sfr"}

        if pt in multi_family_types:
            return 20.0
        elif pt in sfr_types:
            return 10.0
        else:
            return 5.0

    @staticmethod
    def _residential_neighborhood_fit(lead: Lead) -> float:
        """Based on property_city/zip matching target neighborhoods.

        Default: all locations get 8 points (configurable list not yet implemented).
        """
        if lead.property_city or lead.property_zip:
            return 8.0
        return 0.0

    @staticmethod
    def _residential_unit_count_fit(lead: Lead) -> float:
        """2-4 units = 15, 5+ = 10, 1 unit = 5, missing = 0."""
        units = lead.units
        if units is None:
            return 0.0
        if 2 <= units <= 4:
            return 15.0
        elif units >= 5:
            return 10.0
        elif units == 1:
            return 5.0
        return 0.0

    @staticmethod
    def _absentee_owner_score(lead: Lead) -> float:
        """10 points when mailing address differs from property address, else 0."""
        if not lead.mailing_address or not lead.property_street:
            return 0.0
        if lead.mailing_address.strip().lower() != lead.property_street.strip().lower():
            return 10.0
        return 0.0

    @staticmethod
    def _owner_mailing_quality(lead: Lead) -> float:
        """Full mailing address (street+city+state+zip) = 10, partial = 5, none = 0."""
        has_street = bool(lead.mailing_address and lead.mailing_address.strip())
        has_city = bool(lead.mailing_city and lead.mailing_city.strip())
        has_state = bool(lead.mailing_state and lead.mailing_state.strip())
        has_zip = bool(lead.mailing_zip and lead.mailing_zip.strip())

        parts_present = sum([has_street, has_city, has_state, has_zip])

        if parts_present == 4:
            return 10.0
        elif parts_present > 0:
            return 5.0
        return 0.0

    @staticmethod
    def _years_owned_score(lead: Lead) -> float:
        """10+ years = 10, 5-9 years = 7, 2-4 years = 4, <2 years = 2, missing = 0.

        Future acquisition dates (negative years owned) are treated as invalid
        data and score 0 — a lead cannot have been owned for a negative
        duration.
        """
        if not lead.acquisition_date:
            return 0.0

        today = date.today()
        delta = today - lead.acquisition_date
        years = delta.days / 365.25

        if years < 0:
            return 0.0
        if years >= 10:
            return 10.0
        elif years >= 5:
            return 7.0
        elif years >= 2:
            return 4.0
        else:
            return 2.0

    @staticmethod
    def _notes_motivation_score(lead: Lead, max_points: float) -> float:
        """Contains motivation keywords = max_points, has notes but no keywords = 3, no notes = 0."""
        if not lead.notes:
            return 0.0

        notes_lower = lead.notes.lower()
        for keyword in MOTIVATION_KEYWORDS:
            if keyword in notes_lower:
                return max_points

        # Has notes but no motivation keywords
        return 3.0

    @staticmethod
    def _manual_priority_score(lead: Lead, max_points: float) -> float:
        """Based on user-assigned priority value (future field, default 0)."""
        priority = getattr(lead, "manual_priority", None)
        if priority is None:
            return 0.0
        # Clamp to [0, max_points]
        return max(0.0, min(float(priority), max_points))

    # ------------------------------------------------------------------
    # Commercial Scoring
    # ------------------------------------------------------------------

    def calculate_commercial_score(self, lead: Lead) -> dict:
        """Calculate the commercial motivation score for a lead.

        Returns
        -------
        dict
            Keys: total_score (float), score_details (dict), score_version (str)
        """
        details = {}

        details["property_type_fit"] = self._commercial_property_type_fit(lead)
        details["condo_clarity"] = self._condo_clarity_score(lead)
        details["building_sale_possible"] = self._building_sale_possible_score(lead)
        details["neighborhood_fit"] = self._commercial_neighborhood_fit(lead)
        details["owner_concentration"] = self._owner_concentration_score(lead)
        details["absentee_owner"] = self._absentee_owner_score(lead)
        details["building_size_fit"] = self._building_size_fit_score(lead)
        details["existing_notes_motivation"] = self._notes_motivation_score(
            lead, max_points=COMMERCIAL_MAX_POINTS["existing_notes_motivation"]
        )
        details["manual_priority"] = self._manual_priority_score(
            lead, max_points=COMMERCIAL_MAX_POINTS["manual_priority"]
        )

        total_score = sum(details.values())

        return {
            "total_score": total_score,
            "score_details": details,
            "score_version": "commercial_v1_internal_data",
        }

    # ------------------------------------------------------------------
    # Commercial dimension helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _commercial_property_type_fit(lead: Lead) -> float:
        """Commercial/mixed-use = 20, multi-family 5+ units = 15, other = 5, missing = 0.

        Multi-family properties only qualify for the 15-point tier when the
        estimated unit count is 5 or greater; smaller multi-families fall
        through to the 5-point "other" bucket to match the design doc.
        """
        if not lead.property_type:
            return 0.0

        pt = lead.property_type.strip().lower()
        commercial_types = {
            "commercial", "mixed-use", "mixed use", "retail",
            "office", "industrial", "warehouse",
        }
        multi_family_types = {"multi_family", "multi family", "multifamily", "apartment"}

        if pt in commercial_types:
            return 20.0
        elif pt in multi_family_types:
            units = getattr(lead, "units", None)
            try:
                unit_count = int(units) if units is not None else 0
            except (TypeError, ValueError):
                unit_count = 0
            if unit_count >= 5:
                return 15.0
            return 5.0
        else:
            return 5.0

    @staticmethod
    def _condo_clarity_score(lead: Lead) -> float:
        """Score based on condo_risk_status field.

        likely_not_condo = 20, unknown = 10, partial_condo_possible = 5,
        needs_review = 2, likely_condo = 0.
        """
        status = getattr(lead, "condo_risk_status", None)
        if not status:
            return 10.0  # Unknown/missing treated as unknown

        status_lower = status.strip().lower()
        mapping = {
            "likely_not_condo": 20.0,
            "unknown": 10.0,
            "partial_condo_possible": 5.0,
            "needs_review": 2.0,
            "likely_condo": 0.0,
        }
        return mapping.get(status_lower, 10.0)

    @staticmethod
    def _building_sale_possible_score(lead: Lead) -> float:
        """yes = 15, maybe = 8, no = 0, unknown = 5."""
        value = getattr(lead, "building_sale_possible", None)
        if not value:
            return 5.0  # Missing treated as unknown

        value_lower = value.strip().lower()
        mapping = {
            "yes": 15.0,
            "maybe": 8.0,
            "no": 0.0,
            "unknown": 5.0,
        }
        return mapping.get(value_lower, 5.0)

    @staticmethod
    def _commercial_neighborhood_fit(lead: Lead) -> float:
        """Same logic as residential but max 10 points.

        Default: all locations get 5 points (configurable list not yet implemented).
        """
        if lead.property_city or lead.property_zip:
            return 5.0
        return 0.0

    @staticmethod
    def _owner_concentration_score(lead: Lead) -> float:
        """Based on number of distinct owners at same normalized address.

        1 owner = 10, 2 = 7, 3-4 = 4, 5+ = 2.
        ``owner_count`` values of 0 or less are treated as data-absent
        (no analysis run yet) and fall through to the middle default rather
        than being credited as the strongest concentration signal.

        Uses the condo_analysis relationship if available.
        """
        condo_analysis = getattr(lead, "condo_analysis", None)
        if condo_analysis and hasattr(condo_analysis, "owner_count"):
            owner_count = condo_analysis.owner_count
            if owner_count is not None and owner_count > 0:
                if owner_count == 1:
                    return 10.0
                elif owner_count == 2:
                    return 7.0
                elif owner_count <= 4:
                    return 4.0
                else:
                    return 2.0

        # No analysis data available — default to middle score
        return 5.0

    @staticmethod
    def _building_size_fit_score(lead: Lead) -> float:
        """Has sqft data and >= 2000 sqft = 5, has sqft < 2000 = 3, missing = 0."""
        sqft = lead.square_footage
        if sqft is None:
            return 0.0
        if sqft >= 2000:
            return 5.0
        return 3.0

    # ------------------------------------------------------------------
    # Data Quality Scoring
    # ------------------------------------------------------------------

    def calculate_data_quality_score(self, lead: Lead) -> tuple:
        """Calculate data quality score and identify missing fields.

        Returns
        -------
        tuple
            (data_quality_score: float, missing_fields: list[str])
        """
        score = 0.0

        # has_pin (20 points)
        if lead.county_assessor_pin and str(lead.county_assessor_pin).strip():
            score += DATA_QUALITY_FIELDS["has_pin"]

        # has_property_address (15 points)
        if lead.property_street and lead.property_street.strip():
            score += DATA_QUALITY_FIELDS["has_property_address"]

        # has_normalized_address (10 points) — use property_street as proxy
        if lead.property_street and lead.property_street.strip():
            score += DATA_QUALITY_FIELDS["has_normalized_address"]

        # has_owner_name (15 points)
        if (lead.owner_first_name and lead.owner_first_name.strip()) or \
           (lead.owner_last_name and lead.owner_last_name.strip()):
            score += DATA_QUALITY_FIELDS["has_owner_name"]

        # has_owner_mailing_address (15 points)
        if lead.mailing_address and lead.mailing_address.strip():
            score += DATA_QUALITY_FIELDS["has_owner_mailing_address"]

        # has_property_type_or_assessor_class (10 points)
        if lead.property_type and lead.property_type.strip():
            score += DATA_QUALITY_FIELDS["has_property_type_or_assessor_class"]

        # has_estimated_unit_count_or_building_size (10 points)
        if lead.units is not None or lead.square_footage is not None:
            score += DATA_QUALITY_FIELDS["has_estimated_unit_count_or_building_size"]

        # has_source_reference (5 points)
        if (lead.source and lead.source.strip()) or \
           (lead.data_source and lead.data_source.strip()):
            score += DATA_QUALITY_FIELDS["has_source_reference"]

        # Identify missing data fields (broader check per Requirement 5)
        missing_fields = self._identify_missing_data(lead)

        return (score, missing_fields)

    @staticmethod
    def _identify_missing_data(lead: Lead) -> list:
        """Identify all missing useful fields for the lead."""
        missing = []

        field_checks = {
            "pin": lambda: lead.county_assessor_pin and str(lead.county_assessor_pin).strip(),
            "property_address": lambda: lead.property_street and lead.property_street.strip(),
            "normalized_address": lambda: lead.property_street and lead.property_street.strip(),
            "owner_name": lambda: (
                (lead.owner_first_name and lead.owner_first_name.strip()) or
                (lead.owner_last_name and lead.owner_last_name.strip())
            ),
            "owner_mailing_address": lambda: lead.mailing_address and lead.mailing_address.strip(),
            "property_type": lambda: lead.property_type and lead.property_type.strip(),
            "assessor_class": lambda: lead.property_type and lead.property_type.strip(),
            "estimated_units": lambda: lead.units is not None,
            "building_sqft": lambda: lead.square_footage is not None,
            "years_owned": lambda: lead.acquisition_date is not None,
            "neighborhood": lambda: (
                (lead.property_city and lead.property_city.strip()) or
                (lead.property_zip and lead.property_zip.strip())
            ),
            "condo_risk_status": lambda: (
                getattr(lead, "condo_risk_status", None) and
                lead.condo_risk_status.strip()
            ),
            "building_sale_possible": lambda: (
                getattr(lead, "building_sale_possible", None) and
                lead.building_sale_possible.strip()
            ),
            "violation_data": lambda: False,  # Not yet available
            "permit_data": lambda: False,  # Not yet available
            "tax_data": lambda: False,  # Not yet available
            "skip_trace_data": lambda: (
                lead.date_skip_traced is not None or
                bool(lead.phone_1) or bool(lead.email_1)
            ),
        }

        for field_name in MISSING_DATA_FIELDS:
            check_fn = field_checks.get(field_name)
            if check_fn and not check_fn():
                missing.append(field_name)

        return missing

    # ------------------------------------------------------------------
    # Tier Calculation
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_score_tier(total_score: float) -> str:
        """Determine score tier from total score.

        A: 75-100, B: 60-74, C: 40-59, D: 0-39
        """
        if total_score >= TIER_A_MIN:
            return "A"
        elif total_score >= TIER_B_MIN:
            return "B"
        elif total_score >= TIER_C_MIN:
            return "C"
        else:
            return "D"

    # ------------------------------------------------------------------
    # Recommended Action
    # ------------------------------------------------------------------

    @staticmethod
    def get_recommended_action(
        lead: Lead,
        total_score: float,
        data_quality_score: float,
        score_tier: str,
    ) -> str:
        """Determine recommended next action using the decision tree.

        Priority order:
        1. do_not_contact flag -> suppress
        2. Commercial condo overrides (likely_condo -> suppress, needs_review -> needs_manual_review)
        3. Tier-based logic with data quality consideration
        """
        # 1. Do not contact override
        if getattr(lead, "do_not_contact", False):
            return "suppress"

        # 2. Commercial condo overrides (evaluated before tier-based logic)
        lead_category = getattr(lead, "lead_category", "residential")
        if lead_category == "commercial":
            condo_status = getattr(lead, "condo_risk_status", None)
            if condo_status:
                condo_lower = condo_status.strip().lower()
                if condo_lower == "likely_condo":
                    return "suppress"
                elif condo_lower == "needs_review":
                    return "needs_manual_review"

        # 3. Tier-based logic
        if score_tier == "A":
            if data_quality_score >= 70:
                return "mail_ready"
            else:
                return "enrich_data"
        elif score_tier == "B":
            if data_quality_score >= 70:
                return "review_now"
            else:
                return "enrich_data"
        elif score_tier == "C":
            return "nurture"
        else:  # D
            return "suppress"

    # ------------------------------------------------------------------
    # Top Signals Extraction
    # ------------------------------------------------------------------

    @staticmethod
    def extract_top_signals(score_details: dict) -> list:
        """Extract top contributing scoring dimensions.

        Returns a list of dicts sorted by points descending, excluding
        dimensions with zero points. Includes at least top 3 (or all
        non-zero if fewer than 3).
        """
        non_zero = [
            {"dimension": dim, "points": pts}
            for dim, pts in score_details.items()
            if pts > 0
        ]

        # Sort by points descending
        non_zero.sort(key=lambda x: x["points"], reverse=True)

        return non_zero

    # ------------------------------------------------------------------
    # Orchestration Methods (DB-touching)
    # ------------------------------------------------------------------

    def recalculate_lead_score(self, lead: Lead) -> LeadScore:
        """Compute all scores and persist a new LeadScore record.

        Dispatches to residential or commercial scoring based on lead_category.
        """
        # Determine category and compute motivation score
        category = getattr(lead, "lead_category", "residential") or "residential"

        if category == "commercial":
            score_result = self.calculate_commercial_score(lead)
        else:
            score_result = self.calculate_residential_score(lead)

        total_score = score_result["total_score"]
        score_details = score_result["score_details"]
        score_version = score_result["score_version"]

        # Calculate data quality
        data_quality_score, missing_data = self.calculate_data_quality_score(lead)

        # Calculate tier
        score_tier = self.calculate_score_tier(total_score)

        # Determine recommended action
        recommended_action = self.get_recommended_action(
            lead, total_score, data_quality_score, score_tier
        )

        # Extract top signals
        top_signals = self.extract_top_signals(score_details)

        # Persist new record
        lead_score = LeadScore(
            lead_id=lead.id,
            score_version=score_version,
            total_score=total_score,
            score_tier=score_tier,
            data_quality_score=data_quality_score,
            recommended_action=recommended_action,
            top_signals=top_signals,
            score_details=score_details,
            missing_data=missing_data,
            created_at=datetime.utcnow(),
        )

        db.session.add(lead_score)
        db.session.commit()

        logger.info(
            "Scored lead %d: tier=%s score=%.1f quality=%.1f action=%s",
            lead.id, score_tier, total_score, data_quality_score, recommended_action,
        )

        return lead_score

    def recalculate_all_lead_scores(self) -> int:
        """Recalculate scores for all leads. Returns count of scored leads."""
        scored = 0
        offset = 0

        while True:
            leads = (
                Lead.query
                .order_by(Lead.id)
                .offset(offset)
                .limit(BULK_BATCH_SIZE)
                .all()
            )
            if not leads:
                break

            for lead in leads:
                try:
                    self.recalculate_lead_score(lead)
                    scored += 1
                except Exception as e:
                    logger.error(
                        "Failed to score lead %d: %s", lead.id, str(e)
                    )
                    db.session.rollback()

            logger.info("Batch scored %d leads (offset %d)", len(leads), offset)
            offset += BULK_BATCH_SIZE

        logger.info("Bulk recalculation complete: %d leads scored", scored)
        return scored

    def recalculate_by_source_type(self, source_type: str) -> int:
        """Recalculate scores for leads matching a source_type. Returns count."""
        scored = 0
        offset = 0

        while True:
            leads = (
                Lead.query
                .filter(
                    (Lead.source == source_type) | (Lead.data_source == source_type)
                )
                .order_by(Lead.id)
                .offset(offset)
                .limit(BULK_BATCH_SIZE)
                .all()
            )
            if not leads:
                break

            for lead in leads:
                try:
                    self.recalculate_lead_score(lead)
                    scored += 1
                except Exception as e:
                    logger.error(
                        "Failed to score lead %d: %s", lead.id, str(e)
                    )
                    db.session.rollback()

            logger.info(
                "Batch scored %d leads for source_type=%s (offset %d)",
                len(leads), source_type, offset,
            )
            offset += BULK_BATCH_SIZE

        logger.info(
            "Source-type recalculation complete: %d leads scored for %s",
            scored, source_type,
        )
        return scored
