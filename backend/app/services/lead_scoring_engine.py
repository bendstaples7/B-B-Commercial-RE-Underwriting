"""Lead Scoring Engine for computing lead quality scores.

Computes a 0-100 score for each lead based on four configurable weighted
criteria: property characteristics, data completeness, owner situation,
and location desirability.  Weights are stored per-user in the
``scoring_weights`` table and must sum to 1.0.
"""
import logging
from datetime import datetime, date, timedelta
from typing import Optional, List, Union

from app import db
from app.models.lead import Lead
from app.models.lead_scoring import ScoringWeights
from app.models.property_contact import PropertyContact
from app.models.contact_phone import ContactPhone
from app.models.contact_email import ContactEmail

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

# Lead fields tracked for data completeness scoring (non-contact fields only).
# Contact-related completeness (linked contacts, phones, emails) is checked
# dynamically via the PropertyContact / ContactPhone / ContactEmail tables.
COMPLETENESS_FIELDS = [
    "property_street", "property_city", "property_state", "property_zip",
    "property_type", "bedrooms", "bathrooms",
    "square_footage", "lot_size", "year_built",
    "ownership_type", "acquisition_date",
    "mailing_address", "mailing_city", "mailing_state", "mailing_zip",
    "source", "notes", "units_allowed", "zoning", "county_assessor_pin",
    "socials",
]

# Number of contact-related "slots" counted toward completeness:
#   1 = has at least one linked Contact
#   1 = has at least one ContactPhone
#   1 = has at least one ContactEmail
_CONTACT_COMPLETENESS_SLOTS = 3

# Years of ownership that indicate a long-term holder (higher motivation)
LONG_OWNERSHIP_YEARS = 10

# Engagement modifier caps and values (native timeline activity)
ENGAGEMENT_MODIFIER_CAP = 25.0
ENGAGEMENT_MODIFIERS = {
    "call_answered": +10.0,
    "call_not_interested": -40.0,
    "call_wrong_number": -30.0,
    "email_logged": +5.0,
    "note_motivation": +10.0,
    "stale_outreach": -5.0,
    "recent_contact": +5.0,
}
ENGAGEMENT_LOOKBACK_DAYS = 90
RECENT_CONTACT_DAYS = 14


class LeadScoringEngine:
    """Computes lead scores based on configurable weighted criteria.

    Each sub-score is calculated on a 0-100 scale, then combined using
    user-configurable weights that must sum to 1.0.  The final score
    is clamped to [0, 100].

    When HubSpot signals are provided to ``compute_score``, the signal
    adjustments below are applied to the base weighted score before
    clamping.  If the lead has ``suppression_flag=True``, the score is
    additionally capped at 10.0 before the final [0, 100] clamp.
    """

    # Minimum score threshold for active outreach eligibility.
    ACTIVE_OUTREACH_THRESHOLD: float = 30.0

    # Score adjustments applied per HubSpot signal type.
    # Keys match the ``signal_type`` values on ``HubSpotSignal``.
    SIGNAL_ADJUSTMENTS: dict = {
        "PRIOR_WARM_CONVERSATION": +15.0,
        "APPOINTMENT_OCCURRED": +20.0,
        "OFFER_PREVIOUSLY_SENT": +10.0,
        "SELLER_SAID_MAYBE_LATER": -5.0,
        "SELLER_NOT_INTERESTED": -40.0,
        "DO_NOT_CONTACT": -50.0,
        "WRONG_NUMBER": -30.0,
    }

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

        Non-contact fields are checked directly on the lead record.
        Contact-related completeness is checked via the relational tables:
          - Has at least one linked Contact (via PropertyContact): +1 slot
          - Has at least one ContactPhone (via linked contacts): +1 slot
          - Has at least one ContactEmail (via linked contacts): +1 slot

        Parameters
        ----------
        lead : Lead

        Returns
        -------
        float
            Sub-score between 0 and 100.
        """
        total_slots = len(COMPLETENESS_FIELDS) + _CONTACT_COMPLETENESS_SLOTS
        if total_slots == 0:
            return 0.0

        populated = 0

        # --- Non-contact field checks ---
        for field_name in COMPLETENESS_FIELDS:
            value = getattr(lead, field_name, None)
            if value is not None and value != "":
                populated += 1

        # --- Contact-based checks via relational tables ---
        # Skip if lead has no real DB id (e.g. mock objects in unit tests)
        if not isinstance(getattr(lead, 'id', None), int):
            return (populated / total_slots) * 100.0

        # Check for at least one linked contact
        pc = PropertyContact.query.filter_by(property_id=lead.id).first()
        if pc is not None:
            populated += 1  # has at least one linked Contact

            # Check for at least one ContactPhone across all linked contacts
            has_phone = (
                db.session.query(ContactPhone)
                .join(PropertyContact, PropertyContact.contact_id == ContactPhone.contact_id)
                .filter(PropertyContact.property_id == lead.id)
                .first()
            )
            if has_phone is not None:
                populated += 1

            # Check for at least one ContactEmail across all linked contacts
            has_email = (
                db.session.query(ContactEmail)
                .join(PropertyContact, PropertyContact.contact_id == ContactEmail.contact_id)
                .filter(PropertyContact.property_id == lead.id)
                .first()
            )
            if has_email is not None:
                populated += 1

        return (populated / total_slots) * 100.0

    # ------------------------------------------------------------------
    # Sub-score: Owner Situation (0-100)
    # ------------------------------------------------------------------

    def score_owner_situation(self, lead: Lead) -> float:
        """Score based on owner indicators that suggest motivation to sell.

        Heuristics:
        - Has at least one linked Contact (via PropertyContact): +15
        - Has ownership type: +10
        - Has acquisition date: +15
        - Long-term ownership (>= LONG_OWNERSHIP_YEARS): +25
        - Absentee owner (mailing address differs from property address): +20
        - Has contact info (at least one ContactPhone or ContactEmail): +15

        Parameters
        ----------
        lead : Lead

        Returns
        -------
        float
            Sub-score between 0 and 100.
        """
        score = 0.0

        # Check for linked contacts via PropertyContact
        # Skip if lead has no real DB id (e.g. mock objects in unit tests)
        if not isinstance(getattr(lead, 'id', None), int):
            # Only score non-contact fields for mock leads
            if lead.ownership_type:
                score += 10.0
            if lead.acquisition_date:
                score += 15.0
                years_owned = self._years_since(lead.acquisition_date)
                if years_owned is not None and years_owned >= LONG_OWNERSHIP_YEARS:
                    score += 25.0
            if self._is_absentee_owner(lead):
                score += 20.0
            return min(score, 100.0)

        pc = PropertyContact.query.filter_by(property_id=lead.id).first()
        if pc is not None:
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

        # Contact information available via relational tables
        has_phone = (
            db.session.query(ContactPhone)
            .join(PropertyContact, PropertyContact.contact_id == ContactPhone.contact_id)
            .filter(PropertyContact.property_id == lead.id)
            .first()
        )
        has_email = (
            db.session.query(ContactEmail)
            .join(PropertyContact, PropertyContact.contact_id == ContactEmail.contact_id)
            .filter(PropertyContact.property_id == lead.id)
            .first()
        )
        if has_phone is not None or has_email is not None:
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

    def compute_score(
        self,
        lead: Lead,
        weights: ScoringWeights,
        signals: Optional[List] = None,
    ) -> float:
        """Compute the overall lead score as a weighted sum of sub-scores.

        Optionally applies HubSpot signal adjustments to the base score.
        Each signal in *signals* may be either a ``HubSpotSignal`` model
        instance (with a ``.signal_type`` attribute) or a plain string
        signal-type name.  Unrecognised signal types are silently ignored.

        After signal adjustments, if ``lead.suppression_flag`` is ``True``
        the score is clamped to a maximum of 10.0.  The final score is
        always clamped to [0.0, 100.0] and rounded to 2 decimal places.

        Parameters
        ----------
        lead : Lead
            The lead to score.
        weights : ScoringWeights
            User-configured scoring weights (must sum to 1.0).
        signals : list or None
            Optional list of ``HubSpotSignal`` instances or signal-type
            strings to apply as score adjustments.

        Returns
        -------
        float
            Final score clamped to [0.0, 100.0], rounded to 2 decimal places.
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

        # Apply pipeline stage bonus — leads farther along the pipeline are
        # more valuable and should rank higher in outreach queues.
        pipeline_stage_bonus = self._pipeline_stage_bonus(lead)
        total += pipeline_stage_bonus

        total += self._score_engagement(lead)

        # Apply signal adjustments when signals are provided.
        #
        # Signals represent boolean STATES, not counters: a given signal_type
        # contributes its SIGNAL_ADJUSTMENTS value AT MOST ONCE, even when
        # multiple rows of the same type are present (e.g. the same
        # PRIOR_WARM_CONVERSATION re-extracted across several sync runs). We
        # therefore collect the set of recognised signal_types present and add
        # each type's adjustment exactly once. DISTINCT signal_types still each
        # apply (dedup is WITHIN a type, never across types).
        if signals:
            present_signal_types = set()
            for signal in signals:
                # Accept both HubSpotSignal model instances and plain strings
                if isinstance(signal, str):
                    signal_type = signal
                else:
                    signal_type = getattr(signal, "signal_type", None)

                if signal_type and signal_type in self.SIGNAL_ADJUSTMENTS:
                    present_signal_types.add(signal_type)

            for signal_type in present_signal_types:
                total += self.SIGNAL_ADJUSTMENTS[signal_type]

        # Suppression flag: cap score at 10.0 before final clamp
        if getattr(lead, "suppression_flag", False):
            total = min(total, 10.0)

        return max(0.0, min(round(total, 2), 100.0))

    # ------------------------------------------------------------------
    # Recommended action
    # ------------------------------------------------------------------

    def compute_recommended_action(
        self,
        signals: Optional[List],
    ) -> Optional[str]:
        """Determine the recommended action from a list of signals.

        Signals are evaluated in priority order using the *most recently
        extracted* signal (i.e. the last element in the list that matches
        a priority tier).  Priority tiers, from highest to lowest:

        1. DO_NOT_CONTACT → ``'DO_NOT_CONTACT'``
        2. SELLER_NOT_INTERESTED → ``'DO_NOT_CONTACT'``
        3. SELLER_SAID_MAYBE_LATER → ``'FOLLOW_UP_LATER'``
        4. OFFER_PREVIOUSLY_SENT → ``'REVISIT_OFFER'``

        If no signal in the list matches any of the above tiers, ``None``
        is returned.

        Parameters
        ----------
        signals : list or None
            List of ``HubSpotSignal`` model instances (with a
            ``.signal_type`` attribute) or plain signal-type strings.
            The list is assumed to be ordered oldest-first so that the
            last matching signal is the most recently extracted one.

        Returns
        -------
        str or None
            One of ``'DO_NOT_CONTACT'``, ``'FOLLOW_UP_LATER'``,
            ``'REVISIT_OFFER'``, or ``None``.
        """
        if not signals:
            return None

        # Priority map: signal_type → (priority_rank, action)
        # Lower rank number = higher priority.
        PRIORITY_MAP = {
            "DO_NOT_CONTACT": (1, "DO_NOT_CONTACT"),
            "SELLER_NOT_INTERESTED": (1, "DO_NOT_CONTACT"),
            "SELLER_SAID_MAYBE_LATER": (2, "FOLLOW_UP_LATER"),
            "OFFER_PREVIOUSLY_SENT": (3, "REVISIT_OFFER"),
        }

        best_rank: Optional[int] = None
        best_action: Optional[str] = None

        for signal in signals:
            if isinstance(signal, str):
                signal_type = signal
            else:
                signal_type = getattr(signal, "signal_type", None)

            if signal_type and signal_type in PRIORITY_MAP:
                rank, action = PRIORITY_MAP[signal_type]
                # Use this signal if it has higher priority (lower rank)
                # or equal priority (most recently seen wins for same rank).
                if best_rank is None or rank <= best_rank:
                    best_rank = rank
                    best_action = action

        return best_action

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
        """Rescore leads in batches, incorporating HubSpot signals.

        For each lead, queries its associated ``HubSpotSignal`` records,
        passes them to ``compute_score``, computes the recommended action
        via ``compute_recommended_action``, and persists both
        ``lead.lead_score`` and ``lead.recommended_action``.

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
        # Lazy import to avoid circular imports at module load time.
        from app.models.hubspot_signal import HubSpotSignal  # noqa: PLC0415

        weights = self.get_weights(user_id)
        rescored = 0

        def _rescore_lead(lead: Lead) -> None:
            signals = (
                HubSpotSignal.query
                .filter_by(lead_id=lead.id)
                .order_by(HubSpotSignal.extracted_at.asc())
                .all()
            )
            # Only update lead_score here — recommended_action is managed
            # exclusively by ActionEngineService to keep enum values consistent.
            lead.lead_score = self.compute_score(lead, weights, signals=signals)

        if lead_ids is not None:
            # Process specific leads in batches
            for i in range(0, len(lead_ids), BULK_RESCORE_BATCH_SIZE):
                batch_ids = lead_ids[i : i + BULK_RESCORE_BATCH_SIZE]
                leads = Lead.query.filter(Lead.id.in_(batch_ids)).all()
                for lead in leads:
                    _rescore_lead(lead)
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
                    _rescore_lead(lead)
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

    def _score_engagement(self, lead: Lead) -> float:
        """Apply additive modifiers from recent native timeline activity."""
        lead_id = getattr(lead, 'id', None)
        if not isinstance(lead_id, int):
            return 0.0

        from app.models.lead_timeline_entry import LeadTimelineEntry
        from app.services.hubspot_signal_extractor_service import HubSpotSignalExtractorService

        cutoff = datetime.utcnow() - timedelta(days=ENGAGEMENT_LOOKBACK_DAYS)
        entries = (
            LeadTimelineEntry.query
            .filter(
                LeadTimelineEntry.lead_id == lead_id,
                LeadTimelineEntry.source == 'manual',
                LeadTimelineEntry.is_deleted.is_(False),
                LeadTimelineEntry.occurred_at >= cutoff,
            )
            .order_by(LeadTimelineEntry.occurred_at.desc())
            .all()
        )

        applied: set[str] = set()
        modifier = 0.0

        for entry in entries:
            meta = entry.event_metadata or {}
            if entry.event_type == 'call_logged':
                outcome = meta.get('outcome')
                if outcome == 'answered' and 'call_answered' not in applied:
                    applied.add('call_answered')
                    modifier += ENGAGEMENT_MODIFIERS['call_answered']
                elif outcome == 'not_interested' and 'call_not_interested' not in applied:
                    applied.add('call_not_interested')
                    modifier += ENGAGEMENT_MODIFIERS['call_not_interested']
                elif outcome == 'wrong_number' and 'call_wrong_number' not in applied:
                    applied.add('call_wrong_number')
                    modifier += ENGAGEMENT_MODIFIERS['call_wrong_number']
            elif entry.event_type == 'email_logged' and 'email_logged' not in applied:
                applied.add('email_logged')
                modifier += ENGAGEMENT_MODIFIERS['email_logged']
            elif entry.event_type == 'note_added' and 'note_motivation' not in applied:
                body = meta.get('body') or entry.summary or ''
                if HubSpotSignalExtractorService.text_has_motivation_signal(body):
                    applied.add('note_motivation')
                    modifier += ENGAGEMENT_MODIFIERS['note_motivation']

        if (lead.unanswered_call_count or 0) >= 3 and 'stale_outreach' not in applied:
            applied.add('stale_outreach')
            modifier += ENGAGEMENT_MODIFIERS['stale_outreach']

        if lead.last_contact_date:
            days_since = (date.today() - lead.last_contact_date).days
            if days_since <= RECENT_CONTACT_DAYS and 'recent_contact' not in applied:
                applied.add('recent_contact')
                modifier += ENGAGEMENT_MODIFIERS['recent_contact']

        return max(-ENGAGEMENT_MODIFIER_CAP, min(modifier, ENGAGEMENT_MODIFIER_CAP))

    @staticmethod
    def _pipeline_stage_bonus(lead: Lead) -> float:
        """Return a score bonus based on how far along the pipeline the lead is.

        Leads that have been contacted, are in active negotiation, or have had
        an offer delivered are worth more attention and should rank higher.
        Leads awaiting skip trace have insufficient contact info and are
        slightly deprioritised relative to uncontacted leads.

        Stage bonuses (additive on top of the base weighted score):
          skip_trace / awaiting_skip_trace : -5  (contact info not yet acquired)
          mailing_no_contact_made          :   0  (baseline — no adjustment)
          mailing_contacted_no_interest    : -10  (explicit "no interest" — minor
                                                   penalty so a disinterested lead
                                                   ranks slightly BELOW an
                                                   uncontacted one, instead of being
                                                   rewarded for having been reached)
          mailing_contacted_interested     : +15 (active interest expressed)
          negotiating_remote               : +25 (in active negotiation)
          in_person_appointment            : +30 (high-commitment stage)
          offer_delivered                  : +35 (offer on the table)

        All other statuses return 0 (suppressed/terminal leads are filtered
        out before scoring runs, so they never hit this method in practice).
        """
        STAGE_BONUS: dict = {
            'skip_trace': -5.0,
            'awaiting_skip_trace': -5.0,
            'mailing_no_contact_made': 0.0,
            'mailing_contacted_no_interest': -10.0,
            'mailing_contacted_interested': 15.0,
            'negotiating_remote': 25.0,
            'in_person_appointment': 30.0,
            'offer_delivered': 35.0,
        }
        status = getattr(lead, 'lead_status', None)
        return STAGE_BONUS.get(status, 0.0)

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
