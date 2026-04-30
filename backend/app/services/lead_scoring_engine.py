"""Lead Scoring Engine for computing lead quality scores.

Computes a 0-100 score for each lead based on four configurable weighted
criteria: property characteristics, data completeness, owner situation,
and location desirability.  Weights are stored per-user in the
``scoring_weights`` table and must sum to 1.0.
"""
import logging
from datetime import datetime, date
from typing import Optional

from app import db
from app.models.lead import Lead
from app.models.lead_scoring import ScoringWeights

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default weights when no user-specific weights exist
DEFAULT_WEIGHTS = {
    "property_characteristics_weight": 0.30,
    "data_completeness_weight": 0.20,
    "owner_situation_weight": 0.30,
    "location_desirability_weight": 0.20,
}

# Weight sum tolerance for floating-point comparison
WEIGHT_SUM_TOLERANCE = 0.01

# Batch size for bulk rescoring
BULK_RESCORE_BATCH_SIZE = 500

# Property types considered desirable for scoring
DESIRABLE_PROPERTY_TYPES = {
    "single_family", "single family", "sfr",
    "multi_family", "multi family", "multifamily",
    "duplex", "triplex", "fourplex",
}

# All lead fields tracked for data completeness scoring
COMPLETENESS_FIELDS = [
    "property_street", "property_city", "property_state", "property_zip",
    "property_type", "bedrooms", "bathrooms",
    "square_footage", "lot_size", "year_built",
    "owner_first_name", "owner_last_name", "ownership_type", "acquisition_date",
    "phone_1", "phone_2", "email_1",
    "mailing_address", "mailing_city", "mailing_state", "mailing_zip",
    "source", "notes", "units_allowed", "zoning", "county_assessor_pin",
    "owner_2_first_name", "phone_4", "email_3", "socials",
]

# Years of ownership that indicate a long-term holder (higher motivation)
LONG_OWNERSHIP_YEARS = 10


class LeadScoringEngine:
    """Computes lead scores based on configurable weighted criteria.

    Each sub-score is calculated on a 0-100 scale, then combined using
    user-configurable weights that must sum to 1.0.  The final score
    is clamped to [0, 100].
    """

    # ------------------------------------------------------------------
    # Sub-score: Property Characteristics (0-100)
    # ------------------------------------------------------------------

    def score_property_characteristics(self, lead: Lead) -> float:
        """Score based on property type, size, and condition indicators.

        Heuristics (each contributes points up to 100 total):
        - Desirable property type: +25
        - Has bedrooms info: +10, 2-4 beds sweet spot: +10
        - Has bathrooms info: +10
        - Has square footage: +10, 800-3000 sqft sweet spot: +10
        - Has lot size: +10
        - Has year built: +5, built after 1950: +10

        Parameters
        ----------
        lead : Lead

        Returns
        -------
        float
            Sub-score between 0 and 100.
        """
        score = 0.0

        # Property type
        if lead.property_type:
            score += 15.0
            if lead.property_type.strip().lower() in DESIRABLE_PROPERTY_TYPES:
                score += 10.0

        # Bedrooms
        if lead.bedrooms is not None:
            score += 10.0
            if 2 <= lead.bedrooms <= 4:
                score += 10.0

        # Bathrooms
        if lead.bathrooms is not None:
            score += 10.0

        # Square footage
        if lead.square_footage is not None:
            score += 10.0
            if 800 <= lead.square_footage <= 3000:
                score += 10.0

        # Lot size
        if lead.lot_size is not None:
            score += 10.0

        # Year built
        if lead.year_built is not None:
            score += 5.0
            if lead.year_built >= 1950:
                score += 10.0

        return min(score, 100.0)

    # ------------------------------------------------------------------
    # Sub-score: Data Completeness (0-100)
    # ------------------------------------------------------------------

    def score_data_completeness(self, lead: Lead) -> float:
        """Score based on the percentage of lead fields that are populated.

        Parameters
        ----------
        lead : Lead

        Returns
        -------
        float
            Sub-score between 0 and 100.
        """
        if not COMPLETENESS_FIELDS:
            return 0.0

        populated = 0
        for field_name in COMPLETENESS_FIELDS:
            value = getattr(lead, field_name, None)
            if value is not None and value != "":
                populated += 1

        return (populated / len(COMPLETENESS_FIELDS)) * 100.0

    # ------------------------------------------------------------------
    # Sub-score: Owner Situation (0-100)
    # ------------------------------------------------------------------

    def score_owner_situation(self, lead: Lead) -> float:
        """Score based on owner indicators that suggest motivation to sell.

        Heuristics:
        - Has owner name: +15
        - Has ownership type: +10
        - Has acquisition date: +15
        - Long-term ownership (>= LONG_OWNERSHIP_YEARS): +25
        - Absentee owner (mailing address differs from property address): +20
        - Has contact info (phone or email): +15

        Parameters
        ----------
        lead : Lead

        Returns
        -------
        float
            Sub-score between 0 and 100.
        """
        score = 0.0

        # Owner name present
        if lead.owner_first_name or lead.owner_last_name:
            score += 15.0

        # Ownership type present
        if lead.ownership_type:
            score += 10.0

        # Acquisition date and long-term ownership
        if lead.acquisition_date:
            score += 15.0
            years_owned = self._years_since(lead.acquisition_date)
            if years_owned is not None and years_owned >= LONG_OWNERSHIP_YEARS:
                score += 25.0

        # Absentee owner indicator
        if self._is_absentee_owner(lead):
            score += 20.0

        # Contact information available
        if lead.phone_1 or lead.phone_2 or lead.phone_3 or lead.email_1 or lead.email_2:
            score += 15.0

        return min(score, 100.0)

    # ------------------------------------------------------------------
    # Sub-score: Location Desirability (0-100)
    # ------------------------------------------------------------------

    def score_location_desirability(self, lead: Lead) -> float:
        """Score based on location data availability.

        Since we don't have external geo-scoring data, this sub-score
        rewards leads that have complete location information (which
        enables future enrichment and analysis).

        Heuristics:
        - Has property address: +25
        - Has mailing city: +20
        - Has mailing state: +20
        - Has mailing zip: +20
        - Has mailing address: +15

        Parameters
        ----------
        lead : Lead

        Returns
        -------
        float
            Sub-score between 0 and 100.
        """
        score = 0.0

        if lead.property_street:
            score += 25.0
        if lead.mailing_city:
            score += 20.0
        if lead.mailing_state:
            score += 20.0
        if lead.mailing_zip:
            score += 20.0
        if lead.mailing_address:
            score += 15.0

        return min(score, 100.0)

    # ------------------------------------------------------------------
    # Composite score
    # ------------------------------------------------------------------

    def compute_score(self, lead: Lead, weights: ScoringWeights) -> float:
        """Compute the overall lead score as a weighted sum of sub-scores.

        Parameters
        ----------
        lead : Lead
            The lead to score.
        weights : ScoringWeights
            User-configured scoring weights (must sum to 1.0).

        Returns
        -------
        float
            Final score clamped to [0, 100].
        """
        property_sub = self.score_property_characteristics(lead)
        completeness_sub = self.score_data_completeness(lead)
        owner_sub = self.score_owner_situation(lead)
        location_sub = self.score_location_desirability(lead)

        total = (
            property_sub * weights.property_characteristics_weight
            + completeness_sub * weights.data_completeness_weight
            + owner_sub * weights.owner_situation_weight
            + location_sub * weights.location_desirability_weight
        )

        return max(0.0, min(round(total, 2), 100.0))

    # ------------------------------------------------------------------
    # Weight management
    # ------------------------------------------------------------------

    def get_weights(self, user_id: str) -> ScoringWeights:
        """Retrieve scoring weights for a user, creating defaults if needed.

        Parameters
        ----------
        user_id : str

        Returns
        -------
        ScoringWeights
        """
        weights = ScoringWeights.query.filter_by(user_id=user_id).first()
        if not weights:
            weights = ScoringWeights(
                user_id=user_id,
                **DEFAULT_WEIGHTS,
            )
            db.session.add(weights)
            db.session.commit()
        return weights

    def update_weights(
        self,
        user_id: str,
        property_characteristics_weight: float,
        data_completeness_weight: float,
        owner_situation_weight: float,
        location_desirability_weight: float,
    ) -> ScoringWeights:
        """Update scoring weights for a user.

        Validates that the four weights sum to 1.0 (within tolerance).

        Parameters
        ----------
        user_id : str
        property_characteristics_weight : float
        data_completeness_weight : float
        owner_situation_weight : float
        location_desirability_weight : float

        Returns
        -------
        ScoringWeights
            The updated weights record.

        Raises
        ------
        ValueError
            If the weights do not sum to 1.0 (within tolerance) or any
            weight is negative.
        """
        weight_values = [
            property_characteristics_weight,
            data_completeness_weight,
            owner_situation_weight,
            location_desirability_weight,
        ]

        # Validate non-negative
        for w in weight_values:
            if w < 0:
                raise ValueError(f"Weights must be non-negative, got {w}")

        # Validate sum
        weight_sum = sum(weight_values)
        if abs(weight_sum - 1.0) > WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"Weights must sum to 1.0 (got {weight_sum:.4f})"
            )

        weights = ScoringWeights.query.filter_by(user_id=user_id).first()
        if weights:
            weights.property_characteristics_weight = property_characteristics_weight
            weights.data_completeness_weight = data_completeness_weight
            weights.owner_situation_weight = owner_situation_weight
            weights.location_desirability_weight = location_desirability_weight
            weights.updated_at = datetime.utcnow()
        else:
            weights = ScoringWeights(
                user_id=user_id,
                property_characteristics_weight=property_characteristics_weight,
                data_completeness_weight=data_completeness_weight,
                owner_situation_weight=owner_situation_weight,
                location_desirability_weight=location_desirability_weight,
            )
            db.session.add(weights)

        db.session.commit()
        return weights

    # ------------------------------------------------------------------
    # Bulk rescoring
    # ------------------------------------------------------------------

    def bulk_rescore(self, user_id: str, lead_ids: Optional[list[int]] = None) -> int:
        """Rescore leads in batches.

        This is the Celery task entry point.  If *lead_ids* is ``None``,
        all leads are rescored.

        Parameters
        ----------
        user_id : str
            The user whose weights to use.
        lead_ids : list[int] or None
            Specific lead IDs to rescore, or ``None`` for all leads.

        Returns
        -------
        int
            Number of leads rescored.
        """
        weights = self.get_weights(user_id)
        rescored = 0

        if lead_ids is not None:
            # Process specific leads in batches
            for i in range(0, len(lead_ids), BULK_RESCORE_BATCH_SIZE):
                batch_ids = lead_ids[i : i + BULK_RESCORE_BATCH_SIZE]
                leads = Lead.query.filter(Lead.id.in_(batch_ids)).all()
                for lead in leads:
                    lead.lead_score = self.compute_score(lead, weights)
                    rescored += 1
                db.session.commit()
                logger.info(
                    "Rescored batch %d-%d (%d leads)",
                    i, i + len(batch_ids), len(leads),
                )
        else:
            # Process all leads in batches
            offset = 0
            while True:
                leads = (
                    Lead.query
                    .order_by(Lead.id)
                    .offset(offset)
                    .limit(BULK_RESCORE_BATCH_SIZE)
                    .all()
                )
                if not leads:
                    break
                for lead in leads:
                    lead.lead_score = self.compute_score(lead, weights)
                    rescored += 1
                db.session.commit()
                logger.info(
                    "Rescored batch at offset %d (%d leads)",
                    offset, len(leads),
                )
                offset += BULK_RESCORE_BATCH_SIZE

        logger.info("Bulk rescore complete: %d leads rescored", rescored)
        return rescored

    # ------------------------------------------------------------------
    # Score a single lead (convenience for create/update flows)
    # ------------------------------------------------------------------

    def score_lead(self, lead: Lead, user_id: str = "default") -> float:
        """Compute and persist the score for a single lead.

        Intended to be called during lead creation or update.

        Parameters
        ----------
        lead : Lead
        user_id : str

        Returns
        -------
        float
            The computed score.
        """
        weights = self.get_weights(user_id)
        score = self.compute_score(lead, weights)
        lead.lead_score = score
        return score

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _years_since(d: date) -> Optional[float]:
        """Return the number of years between *d* and today, or None."""
        if d is None:
            return None
        today = date.today()
        delta = today - d
        return delta.days / 365.25

    @staticmethod
    def _is_absentee_owner(lead: Lead) -> bool:
        """Heuristic: owner is absentee if mailing address is present and
        differs from the property address."""
        if not lead.mailing_address or not lead.property_street:
            return False
        return (
            lead.mailing_address.strip().lower()
            != lead.property_street.strip().lower()
        )
