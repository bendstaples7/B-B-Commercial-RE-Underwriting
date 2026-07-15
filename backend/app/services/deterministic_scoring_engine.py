"""Backward-compatible DeterministicScoringEngine facade.

Logic lives in scoring_rubric.py and lead_scoring_engine.py. This module
preserves the old API surface for tests and scripts.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from app import db
from app.models.lead import Lead
from app.models.lead_score import LeadScore
from app.services import scoring_rubric as rubric
from app.services.enrichment_scoring import (
    contactability_score,
    engagement_score,
    ownership_duration_score,
    property_equity_score,
)
from app.services.lead_scoring_engine import LeadScoringEngine

ALLOWED_ACTIONS = {
    "review_now", "enrich_data", "mail_ready", "call_ready",
    "valuation_needed", "suppress", "nurture", "hold", "needs_manual_review",
    "follow_up_now", "ready_for_outreach", "add_contact_info", "create_task",
    "resolve_match", "analyze_property", "do_not_contact",
}
TIER_A_MIN = rubric.TIER_A_MIN
TIER_B_MIN = rubric.TIER_B_MIN
TIER_C_MIN = rubric.TIER_C_MIN
RESIDENTIAL_MAX_POINTS = rubric.RESIDENTIAL_MAX_POINTS
COMMERCIAL_MAX_POINTS = rubric.COMMERCIAL_MAX_POINTS
MOTIVATION_KEYWORDS = rubric.MOTIVATION_KEYWORDS
SOURCE_TYPE_DISTRESS_QUALIFYING = rubric.SOURCE_TYPE_DISTRESS_QUALIFYING
SOURCE_TYPE_DISTRESS_BASE_POINTS = rubric.SOURCE_TYPE_DISTRESS_BASE_POINTS
SOURCE_TYPE_DISTRESS_TAX_BONUS = rubric.SOURCE_TYPE_DISTRESS_TAX_BONUS
SOURCE_TYPE_DISTRESS_COMBINED_CAP = rubric.SOURCE_TYPE_DISTRESS_COMBINED_CAP
DATA_QUALITY_FIELDS = rubric.DATA_QUALITY_FIELDS
MISSING_DATA_FIELDS = rubric.MISSING_DATA_FIELDS
TAX_DISTRESS_FORBIDDEN_TERMS = rubric.TAX_DISTRESS_FORBIDDEN_TERMS
SCORING_ATTRIBUTES = rubric.SCORING_ATTRIBUTES
parse_sale_date_string = rubric.parse_sale_date_string
effective_acquisition_date = rubric.effective_acquisition_date
calculate_score_tier = rubric.calculate_score_tier
get_scoring_attributes = rubric.get_scoring_attributes
calculate_residential_score = rubric.calculate_residential_score
calculate_commercial_score = rubric.calculate_commercial_score
calculate_data_quality_score = rubric.calculate_data_quality_score
extract_top_signals = rubric.extract_top_signals


class DeterministicScoringEngine:
    """Facade delegating to unified LeadScoringEngine + scoring_rubric."""

    SCORING_ATTRIBUTES = SCORING_ATTRIBUTES
    BULK_BATCH_SIZE = 500

    _unified = LeadScoringEngine()

    parse_sale_date_string = staticmethod(parse_sale_date_string)
    effective_acquisition_date = staticmethod(effective_acquisition_date)
    calculate_score_tier = staticmethod(calculate_score_tier)
    extract_top_signals = staticmethod(extract_top_signals)

    @staticmethod
    def score_needs_refresh(lead: Lead, score: Optional[LeadScore]) -> bool:
        return LeadScoringEngine.score_needs_refresh(lead, score)

    def calculate_residential_score(self, lead: Lead) -> dict:
        return rubric.calculate_residential_score(lead)

    def calculate_commercial_score(self, lead: Lead) -> dict:
        return rubric.calculate_commercial_score(lead)

    def calculate_data_quality_score(self, lead: Lead) -> tuple:
        return rubric.calculate_data_quality_score(lead)

    @staticmethod
    def get_recommended_action(lead, total_score, data_quality_score, score_tier):
        action, _, _ = LeadScoringEngine.evaluate_recommended_action(
            lead, total_score, data_quality_score, score_tier,
        )
        return action or 'enrich_data'

    def recalculate_lead_score(self, lead: Lead) -> LeadScore:
        return self._unified.recalculate_lead_score(lead)

    def recalculate_all_lead_scores(self) -> int:
        return self._unified.recalculate_all_lead_scores()

    def recalculate_by_source_type(self, source_type: str) -> int:
        return self._unified.recalculate_by_source_type(source_type)

    # Rubric dimension helpers (tests call these on the engine instance)
    _residential_property_type_fit = staticmethod(rubric.residential_property_type_fit)
    _residential_neighborhood_fit = staticmethod(rubric.residential_neighborhood_fit)
    _residential_unit_count_fit = staticmethod(rubric.residential_unit_count_fit)
    _absentee_owner_score = staticmethod(rubric.absentee_owner_score)
    _owner_mailing_quality = staticmethod(rubric.owner_mailing_quality)
    _notes_motivation_score = staticmethod(rubric.notes_motivation_score)
    _manual_priority_score = staticmethod(rubric.manual_priority_score)
    _source_type_distress_score = staticmethod(rubric.source_type_distress_score)
    _commercial_property_type_fit = staticmethod(rubric.commercial_property_type_fit)
    _condo_clarity_score = staticmethod(rubric.condo_clarity_score)
    _building_sale_possible_score = staticmethod(rubric.building_sale_possible_score)
    _commercial_neighborhood_fit = staticmethod(rubric.commercial_neighborhood_fit)
    _owner_concentration_score = staticmethod(rubric.owner_concentration_score)
    _building_size_fit_score = staticmethod(rubric.building_size_fit_score)
    _contactability_score = staticmethod(
        lambda lead, max_points=20.0: contactability_score(lead, max_points=max_points)
    )
    _property_equity_score = staticmethod(
        lambda lead, max_points=25.0: property_equity_score(lead, max_points=max_points)
    )
    _ownership_duration_score = staticmethod(
        lambda lead, max_points=15.0: ownership_duration_score(lead, max_points=max_points)
    )
    _engagement_score = staticmethod(
        lambda lead, max_points=10.0: engagement_score(lead, max_points=max_points)
    )

    @staticmethod
    def _years_owned_score(lead: Lead) -> float:
        acquisition = rubric.effective_acquisition_date(lead)
        if not acquisition:
            return 0.0
        years = (date.today() - acquisition).days / 365.25
        if years < 0:
            return 0.0
        if years >= 10:
            return 10.0
        if years >= 5:
            return 7.0
        if years >= 2:
            return 4.0
        return 2.0

    @staticmethod
    def _normalize_for_tier(raw_total: float, category: str) -> float:
        if category == "commercial":
            theoretical_max = float(sum(COMMERCIAL_MAX_POINTS.values()))
        else:
            theoretical_max = float(
                sum(RESIDENTIAL_MAX_POINTS.values()) - RESIDENTIAL_MAX_POINTS["years_owned"]
            )
        if theoretical_max <= 0:
            return 0.0
        return min(100.0, raw_total * 100.0 / theoretical_max)

    @staticmethod
    def _identify_missing_data(lead: Lead) -> list:
        _, missing, _ = rubric.calculate_data_quality_score(lead)
        return missing
