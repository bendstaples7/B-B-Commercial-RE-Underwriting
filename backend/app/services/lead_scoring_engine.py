"""Unified Lead Scoring Engine.

Single canonical scorer: weighted rubric + modifiers + recommended action.
Writes ``leads.lead_score``, ``leads.recommended_action``, and append-only
``lead_scores`` history in one pipeline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app import db
from app.models.hubspot_signal import HubSpotSignal
from app.models.lead import Lead
from app.models.lead_score import LeadScore
from app.models.lead_scoring import ScoringWeights
from app.models.lead_task import LeadTask
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.lead_crm_flags_view import LeadCRMFlagsView
from app.services import scoring_rubric as rubric
from app.services.outreach_method_service import (
    evaluate_contact_method,
    refine_outreach_action,
    OUTREACH_ACTIONS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "property_characteristics_weight": 0.25,
    "data_completeness_weight": 0.15,
    "owner_situation_weight": 0.25,
    "location_desirability_weight": 0.15,
    "data_enrichment_weight": 0.20,
}

WEIGHT_SUM_TOLERANCE = 0.01
BULK_RESCORE_BATCH_SIZE = 500

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

SCORING_ATTRIBUTES = rubric.SCORING_ATTRIBUTES


def get_scoring_attributes() -> frozenset:
    return SCORING_ATTRIBUTES


@dataclass
class ScoringResult:
    total_score: float
    score_tier: str
    data_quality_score: float
    recommended_action: str | None
    recommended_contact_method: str | None
    winning_rule: str
    action_signals: dict
    score_details: dict
    top_signals: list
    missing_data: list
    score_version: str
    base_score: float = 0.0


# ---------------------------------------------------------------------------
# Action-engine helpers (task counts, CRM flags)
# ---------------------------------------------------------------------------

def _count_open_tasks(lead_id: int) -> int:
    from sqlalchemy import text as _text
    try:
        native = LeadTask.query.filter_by(lead_id=lead_id, status='open').count()
        hs = db.session.execute(_text("""
            SELECT COUNT(*) FROM tasks t
            JOIN task_associations ta ON ta.task_id = t.id
            WHERE ta.target_type = 'lead' AND ta.target_id = :lid
              AND t.status IN ('open', 'overdue')
              AND t.source = 'hubspot_import'
            UNION ALL
            SELECT COUNT(*) FROM tasks
            WHERE lead_id = :lid
              AND status IN ('open', 'overdue')
              AND source = 'hubspot_import'
        """), {'lid': lead_id}).fetchall()
        hs_counts = [r[0] for r in hs]
        hs_total = max(hs_counts) if hs_counts else 0
        return native + hs_total
    except Exception as exc:
        logger.warning("open task count query failed for lead_id=%s: %s", lead_id, exc)
        db.session.rollback()
        return 0


def _has_overdue_hubspot_task(lead_id: int) -> bool:
    from sqlalchemy import text as _hs_text
    try:
        row = db.session.execute(_hs_text("""
            SELECT 1 FROM tasks t
            JOIN task_associations ta ON ta.task_id = t.id
            WHERE ta.target_type = 'lead' AND ta.target_id = :lid
              AND t.status IN ('open', 'overdue')
              AND (t.due_date <= :now OR (t.due_date IS NULL AND t.status = 'overdue'))
              AND t.source = 'hubspot_import'
            LIMIT 1
        """), {'lid': lead_id, 'now': datetime.utcnow()}).fetchone()
        if not row:
            row = db.session.execute(_hs_text("""
                SELECT 1 FROM tasks
                WHERE lead_id = :lid
                  AND status IN ('open', 'overdue')
                  AND (due_date <= :now OR (due_date IS NULL AND status = 'overdue'))
                  AND source = 'hubspot_import'
                LIMIT 1
            """), {'lid': lead_id, 'now': datetime.utcnow()}).fetchone()
        return row is not None
    except Exception as exc:
        logger.warning("overdue HubSpot task query failed for lead_id=%s: %s", lead_id, exc)
        db.session.rollback()
        return False


def _resolve_crm_flags(lead: Lead) -> tuple[bool, bool, bool]:
    if not isinstance(getattr(lead, 'id', None), int):
        return (
            bool(getattr(lead, 'has_phone', False)),
            bool(getattr(lead, 'has_email', False)),
            bool(getattr(lead, 'has_property_match', False)),
        )
    try:
        flags = LeadCRMFlagsView.query.filter_by(lead_id=lead.id).first()
        if flags:
            return (
                flags.has_phone_computed,
                flags.has_email_computed,
                flags.has_property_match_computed,
            )
    except Exception as exc:
        logger.warning(
            "CRM flags view unavailable for lead_id=%s, using lead columns: %s",
            lead.id, exc,
        )
    return lead.has_phone, lead.has_email, lead.has_property_match


def _timeline_signals(signals: dict) -> dict:
    safe = dict(signals)
    safe.pop('property_street', None)
    return safe


class LeadScoringEngine:
    """Unified scoring + recommended-action engine."""

    SCORING_ATTRIBUTES = SCORING_ATTRIBUTES
    ACTIVE_OUTREACH_THRESHOLD: float = 30.0

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
    # Core unified compute
    # ------------------------------------------------------------------

    def compute(
        self,
        lead: Lead,
        weights: ScoringWeights,
        signals: Optional[list] = None,
    ) -> ScoringResult:
        category = getattr(lead, "lead_category", "residential") or "residential"
        if category == "commercial":
            rubric_result = rubric.calculate_commercial_score(lead)
        else:
            rubric_result = rubric.calculate_residential_score(lead)

        score_details = dict(rubric_result["score_details"])
        score_version = rubric_result["score_version"]

        data_quality_score, missing_data = rubric.calculate_data_quality_score(lead)
        buckets = rubric.bucket_scores(score_details, data_quality_score, category)

        base_score = (
            buckets["property_characteristics"] * weights.property_characteristics_weight
            + buckets["data_completeness"] * weights.data_completeness_weight
            + buckets["owner_situation"] * weights.owner_situation_weight
            + buckets["location_desirability"] * weights.location_desirability_weight
            + buckets["data_enrichment"] * weights.data_enrichment_weight
        )

        pipeline_bonus = self._pipeline_stage_bonus(lead)
        engagement_mod = self._score_engagement(lead)
        hubspot_mod = self._hubspot_signal_adjustment(signals)

        score_details["pipeline_stage_bonus"] = pipeline_bonus
        score_details["timeline_engagement"] = engagement_mod
        score_details["hubspot_signals"] = hubspot_mod

        total = base_score + pipeline_bonus + engagement_mod + hubspot_mod
        if getattr(lead, "suppression_flag", False):
            total = min(total, 10.0)
        total = max(0.0, min(round(total, 2), 100.0))

        score_tier = rubric.calculate_score_tier(total)
        recommended_action, winning_rule, action_signals = self.evaluate_recommended_action(
            lead, total, data_quality_score, score_tier,
        )
        recommended_action, recommended_contact_method = self._apply_outreach_method(
            lead, recommended_action, action_signals,
        )
        if recommended_contact_method:
            action_signals['recommended_contact_method'] = recommended_contact_method
        top_signals = rubric.extract_top_signals(score_details)

        return ScoringResult(
            total_score=total,
            score_tier=score_tier,
            data_quality_score=data_quality_score,
            recommended_action=recommended_action,
            recommended_contact_method=recommended_contact_method,
            winning_rule=winning_rule,
            action_signals=action_signals,
            score_details=score_details,
            top_signals=top_signals,
            missing_data=missing_data,
            score_version=score_version,
            base_score=round(base_score, 2),
        )

    def compute_score(
        self,
        lead: Lead,
        weights: ScoringWeights,
        signals: Optional[list] = None,
    ) -> float:
        """Backward-compatible: return only the 0–100 total score."""
        return self.compute(lead, weights, signals=signals).total_score

    @staticmethod
    def evaluate_recommended_action(
        lead: Lead,
        total_score: float,
        data_quality_score: float,
        score_tier: str,
    ) -> tuple[str | None, str, dict]:
        """Unified priority tree: workflow blockers, then score-derived actions."""
        if lead.lead_status == 'do_not_contact':
            return 'do_not_contact', 'do_not_contact', {'lead_status': 'do_not_contact'}

        if lead.lead_status in ('suppressed', 'deprioritize', 'deal_won', 'deal_lost'):
            return 'suppress', 'terminal_status', {'lead_status': lead.lead_status}

        lead_category = getattr(lead, "lead_category", "residential")
        if lead_category == "commercial":
            condo_status = getattr(lead, "condo_risk_status", None)
            if condo_status:
                condo_lower = condo_status.strip().lower()
                if condo_lower == "likely_condo":
                    return 'suppress', 'likely_condo', {'condo_risk_status': condo_status}
                if condo_lower == "needs_review":
                    return 'needs_manual_review', 'condo_needs_review', {'condo_risk_status': condo_status}

        if getattr(lead, "do_not_contact", False) is True:
            return 'suppress', 'do_not_contact_flag', {'do_not_contact': True}

        if lead.lead_status in ('skip_trace', 'awaiting_skip_trace'):
            return (
                'add_contact_info', 'skip_trace_status',
                {'lead_status': lead.lead_status, 'requires_skip_trace': True},
            )

        has_phone, has_email, has_property_match = _resolve_crm_flags(lead)
        if not has_phone and not has_email:
            return 'add_contact_info', 'no_contact_info', {'has_phone': False, 'has_email': False}

        if not has_property_match and lead.property_street:
            return (
                'resolve_match', 'no_property_match_with_address',
                {'has_property_match': False, 'property_street': lead.property_street},
            )
        if not has_property_match and not lead.property_street:
            return (
                'enrich_data', 'no_property_match_no_address',
                {'has_property_match': False, 'property_street': lead.property_street},
            )

        if has_property_match and not getattr(lead, 'analysis_complete', False):
            return 'analyze_property', 'no_analysis', {'analysis_complete': False}

        lead_id = getattr(lead, 'id', None)
        has_overdue_hs_task = _has_overdue_hubspot_task(lead_id) if isinstance(lead_id, int) else False
        if lead.follow_up_overdue or has_overdue_hs_task:
            return 'follow_up_now', 'follow_up_overdue', {
                'follow_up_overdue': bool(lead.follow_up_overdue),
                'has_overdue_hs_task': has_overdue_hs_task,
            }

        if lead.is_warm:
            return 'follow_up_now', 'is_warm', {'is_warm': True}

        open_tasks = _count_open_tasks(lead_id) if isinstance(lead_id, int) else 0

        if score_tier == "A" and data_quality_score >= 70:
            return 'mail_ready', 'tier_a_high_quality', {
                'score_tier': score_tier, 'data_quality_score': data_quality_score,
            }
        if score_tier == "B" and data_quality_score >= 70:
            return 'review_now', 'tier_b_high_quality', {
                'score_tier': score_tier, 'data_quality_score': data_quality_score,
            }
        if total_score >= 70 and open_tasks == 0:
            return 'ready_for_outreach', 'high_score_no_tasks', {
                'lead_score': total_score, 'open_task_count': open_tasks,
            }
        if score_tier == "C":
            return 'nurture', 'tier_c', {'score_tier': score_tier}
        if score_tier == "D":
            return 'enrich_data', 'tier_d', {'score_tier': score_tier}
        if open_tasks == 0:
            return 'create_task', 'no_tasks_create_one', {
                'lead_status': lead.lead_status, 'open_task_count': open_tasks,
            }
        return 'nurture', 'has_open_tasks', {
            'open_task_count': open_tasks, 'lead_score': total_score,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def persist(
        self,
        lead: Lead,
        result: ScoringResult,
        *,
        write_history: bool = True,
        commit: bool = True,
    ) -> LeadScore | None:
        """Update live lead fields; optionally append ``lead_scores`` history."""
        previous_action = lead.recommended_action
        previous_method = lead.recommended_contact_method
        lead.lead_score = result.total_score
        lead.recommended_action = result.recommended_action
        lead.recommended_contact_method = result.recommended_contact_method
        db.session.add(lead)

        lead_score: LeadScore | None = None
        if write_history:
            lead_score = LeadScore(
                lead_id=lead.id,
                score_version=result.score_version,
                total_score=result.total_score,
                score_tier=result.score_tier,
                data_quality_score=result.data_quality_score,
                recommended_action=result.recommended_action,
                top_signals=result.top_signals,
                score_details=result.score_details,
                missing_data=result.missing_data,
                created_at=datetime.utcnow(),
            )
            db.session.add(lead_score)

        if result.recommended_action != previous_action:
            entry = LeadTimelineEntry(
                lead_id=lead.id,
                event_type='recommended_action_changed',
                occurred_at=datetime.now(timezone.utc),
                source='system',
                actor='System',
                summary=(
                    f"Recommended action changed from '{previous_action}' "
                    f"to '{result.recommended_action}'."
                ),
                event_metadata={
                    'previous_action': previous_action,
                    'new_action': result.recommended_action,
                    'previous_contact_method': previous_method,
                    'new_contact_method': result.recommended_contact_method,
                    'winning_rule': result.winning_rule,
                    'lead_score': result.total_score,
                    'is_warm': lead.is_warm,
                    'signals': _timeline_signals(result.action_signals),
                },
            )
            db.session.add(entry)
        elif result.recommended_contact_method != previous_method:
            entry = LeadTimelineEntry(
                lead_id=lead.id,
                event_type='recommended_action_changed',
                occurred_at=datetime.now(timezone.utc),
                source='system',
                actor='System',
                summary=(
                    f"Recommended contact method changed from '{previous_method}' "
                    f"to '{result.recommended_contact_method}'."
                ),
                event_metadata={
                    'previous_action': previous_action,
                    'new_action': result.recommended_action,
                    'previous_contact_method': previous_method,
                    'new_contact_method': result.recommended_contact_method,
                    'winning_rule': result.winning_rule,
                    'lead_score': result.total_score,
                    'is_warm': lead.is_warm,
                    'signals': _timeline_signals(result.action_signals),
                },
            )
            db.session.add(entry)

        if commit:
            db.session.commit()
            logger.info(
                "Scored lead %d: tier=%s score=%.1f quality=%.1f action=%s history=%s",
                lead.id, result.score_tier, result.total_score,
                result.data_quality_score, result.recommended_action, write_history,
            )
        return lead_score

    def score_and_persist(self, lead_id: int) -> LeadScore | None:
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            return None
        weights = self.get_weights(lead.owner_user_id or 'default')
        signals = (
            HubSpotSignal.query
            .filter_by(lead_id=lead.id)
            .order_by(HubSpotSignal.extracted_at.asc())
            .all()
        )
        result = self.compute(lead, weights, signals=signals)
        return self.persist(lead, result)

    # ------------------------------------------------------------------
    # Bulk / recalculate (formerly DeterministicScoringEngine)
    # ------------------------------------------------------------------

    @staticmethod
    def score_needs_refresh(lead: Lead, score: Optional[LeadScore]) -> bool:
        if score is None:
            return True
        if lead.updated_at and score.created_at and score.created_at < lead.updated_at:
            return True
        details = score.score_details or {}
        if lead.property_type and details.get('property_type_fit', 0) == 0:
            return True
        acquisition = rubric.effective_acquisition_date(lead)
        if acquisition and acquisition <= date.today() and details.get('ownership_duration', 0) == 0:
            return True
        return False

    def recalculate_lead_score(
        self,
        lead: Lead,
        signals: Optional[list] = None,
    ) -> LeadScore:
        weights = self.get_weights(lead.owner_user_id or 'default')
        if signals is None:
            signals = (
                HubSpotSignal.query
                .filter_by(lead_id=lead.id)
                .order_by(HubSpotSignal.extracted_at.asc())
                .all()
            )
        result = self.compute(lead, weights, signals=signals)
        row = self.persist(lead, result)
        assert row is not None
        return row

    def recalculate_all_lead_scores(self) -> int:
        scored = 0
        offset = 0
        while True:
            leads = (
                Lead.query.order_by(Lead.id)
                .offset(offset).limit(BULK_RESCORE_BATCH_SIZE).all()
            )
            if not leads:
                break
            for lead in leads:
                try:
                    self.recalculate_lead_score(lead)
                    scored += 1
                except Exception as e:
                    logger.error("Failed to score lead %d: %s", lead.id, e)
                    db.session.rollback()
            offset += BULK_RESCORE_BATCH_SIZE
        return scored

    def recalculate_by_source_type(self, source_type: str) -> int:
        scored = 0
        offset = 0
        while True:
            leads = (
                Lead.query
                .filter((Lead.source == source_type) | (Lead.data_source == source_type))
                .order_by(Lead.id)
                .offset(offset).limit(BULK_RESCORE_BATCH_SIZE).all()
            )
            if not leads:
                break
            for lead in leads:
                try:
                    self.recalculate_lead_score(lead)
                    scored += 1
                except Exception as e:
                    logger.error("Failed to score lead %d: %s", lead.id, e)
                    db.session.rollback()
            offset += BULK_RESCORE_BATCH_SIZE
        return scored

    # ------------------------------------------------------------------
    # Weight management
    # ------------------------------------------------------------------

    def get_weights(self, user_id: str) -> ScoringWeights:
        weights = ScoringWeights.query.filter_by(user_id=user_id).first()
        if not weights:
            weights = ScoringWeights(user_id=user_id, **DEFAULT_WEIGHTS)
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
        data_enrichment_weight: float,
    ) -> ScoringWeights:
        weight_values = [
            property_characteristics_weight, data_completeness_weight,
            owner_situation_weight, location_desirability_weight, data_enrichment_weight,
        ]
        for w in weight_values:
            if w < 0:
                raise ValueError(f"Weights must be non-negative, got {w}")
        weight_sum = sum(weight_values)
        if abs(weight_sum - 1.0) > WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"Weights must sum to 1.0 (got {weight_sum:.4f})")

        weights = ScoringWeights.query.filter_by(user_id=user_id).first()
        if weights:
            weights.property_characteristics_weight = property_characteristics_weight
            weights.data_completeness_weight = data_completeness_weight
            weights.owner_situation_weight = owner_situation_weight
            weights.location_desirability_weight = location_desirability_weight
            weights.data_enrichment_weight = data_enrichment_weight
            weights.updated_at = datetime.utcnow()
        else:
            weights = ScoringWeights(
                user_id=user_id,
                property_characteristics_weight=property_characteristics_weight,
                data_completeness_weight=data_completeness_weight,
                owner_situation_weight=owner_situation_weight,
                location_desirability_weight=location_desirability_weight,
                data_enrichment_weight=data_enrichment_weight,
            )
            db.session.add(weights)
        db.session.commit()
        return weights

    # ------------------------------------------------------------------
    # Bulk rescoring
    # ------------------------------------------------------------------

    def bulk_rescore(self, user_id: str, lead_ids: Optional[list[int]] = None) -> int:
        """Refresh live scores without append-only history rows (batched commits)."""
        rescored = 0
        pending_commits = 0

        def _flush_batch() -> None:
            nonlocal pending_commits
            if pending_commits:
                db.session.commit()
                pending_commits = 0

        def _rescore_one(lead: Lead) -> None:
            nonlocal rescored, pending_commits
            weights = self.get_weights(lead.owner_user_id or user_id)
            signals = (
                HubSpotSignal.query
                .filter_by(lead_id=lead.id)
                .order_by(HubSpotSignal.extracted_at.asc())
                .all()
            )
            result = self.compute(lead, weights, signals=signals)
            self.persist(lead, result, write_history=False, commit=False)
            rescored += 1
            pending_commits += 1
            if pending_commits >= BULK_RESCORE_BATCH_SIZE:
                _flush_batch()

        try:
            if lead_ids is not None:
                for i in range(0, len(lead_ids), BULK_RESCORE_BATCH_SIZE):
                    batch_ids = lead_ids[i:i + BULK_RESCORE_BATCH_SIZE]
                    for lead in Lead.query.filter(Lead.id.in_(batch_ids)).all():
                        _rescore_one(lead)
            else:
                offset = 0
                while True:
                    leads = (
                        Lead.query.order_by(Lead.id)
                        .offset(offset).limit(BULK_RESCORE_BATCH_SIZE).all()
                    )
                    if not leads:
                        break
                    for lead in leads:
                        _rescore_one(lead)
                    offset += BULK_RESCORE_BATCH_SIZE
            _flush_batch()
        except Exception:
            db.session.rollback()
            raise

        logger.info("Bulk rescore complete: %d leads rescored", rescored)
        return rescored

    def bulk_recompute_actions(self, lead_ids: list[int] | None = None) -> int:
        """Re-score leads (score + action are unified)."""
        if lead_ids is None:
            return self.bulk_rescore('default')
        return self.bulk_rescore('default', lead_ids=lead_ids)

    @staticmethod
    def recompute_and_persist(lead_id: int):
        """Backward-compatible ActionEngine entry point."""
        engine = LeadScoringEngine()
        result = engine.score_and_persist(lead_id)
        if result is None:
            raise ValueError(f"Lead {lead_id} not found")
        return db.session.get(Lead, lead_id)

    @staticmethod
    def bulk_recompute(lead_ids: list[int] | None = None) -> int:
        return LeadScoringEngine().bulk_recompute_actions(lead_ids)

    # ------------------------------------------------------------------
    # Rubric delegates (backward-compatible with DeterministicScoringEngine tests)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_sale_date_string(value: Optional[str]) -> Optional[date]:
        return rubric.parse_sale_date_string(value)

    @staticmethod
    def effective_acquisition_date(lead: Lead) -> Optional[date]:
        return rubric.effective_acquisition_date(lead)

    def calculate_residential_score(self, lead: Lead) -> dict:
        return rubric.calculate_residential_score(lead)

    def calculate_commercial_score(self, lead: Lead) -> dict:
        return rubric.calculate_commercial_score(lead)

    def calculate_data_quality_score(self, lead: Lead) -> tuple:
        return rubric.calculate_data_quality_score(lead)

    @staticmethod
    def calculate_score_tier(total_score: float) -> str:
        return rubric.calculate_score_tier(total_score)

    @staticmethod
    def get_recommended_action(
        lead: Lead,
        total_score: float,
        data_quality_score: float,
        score_tier: str,
    ) -> str:
        action, _rule, _signals = LeadScoringEngine.evaluate_recommended_action(
            lead, total_score, data_quality_score, score_tier,
        )
        return action or 'enrich_data'

    @staticmethod
    def extract_top_signals(score_details: dict) -> list:
        return rubric.extract_top_signals(score_details)

    @staticmethod
    def _normalize_for_tier(raw_total: float, category: str) -> float:
        """Legacy helper — unified engine uses 0–100 scores directly."""
        return min(100.0, max(0.0, raw_total))

    # ------------------------------------------------------------------
    # Legacy helpers (backward-compatible with pre-unification tests/API)
    # ------------------------------------------------------------------

    _LEGACY_BUCKET_DIMS = {
        "property_characteristics": ["property_type_fit"],
        "data_completeness": ["neighborhood_fit"],
        "owner_situation": ["absentee_owner"],
        "location_desirability": ["neighborhood_fit"],
    }

    _LEGACY_SIGNAL_ACTIONS = {
        "DO_NOT_CONTACT": (1, "DO_NOT_CONTACT"),
        "SELLER_NOT_INTERESTED": (1, "DO_NOT_CONTACT"),
        "SELLER_SAID_MAYBE_LATER": (2, "FOLLOW_UP_LATER"),
        "OFFER_PREVIOUSLY_SENT": (3, "REVISIT_OFFER"),
    }

    def apply_signal_adjustments(
        self,
        score: float,
        signals: Optional[list] = None,
        lead: Optional[Lead] = None,
    ) -> float:
        """Apply HubSpot signal deltas to a base score (legacy API)."""
        adjusted = score + self._hubspot_signal_adjustment(signals)
        if lead is not None and getattr(lead, "suppression_flag", False):
            adjusted = min(adjusted, 10.0)
        return round(max(0.0, min(adjusted, 100.0)), 2)

    def apply_configurable_weights(
        self,
        base_score: float,
        details: dict,
        weights: Optional[dict] = None,
    ) -> float:
        """Re-weight rubric dimensions into bucket totals (legacy API)."""
        if weights is None:
            return base_score

        norm_weights: dict[str, float] = {}
        for key, value in weights.items():
            bucket = key[:-7] if key.endswith("_weight") else key
            norm_weights[bucket] = value

        total = 0.0
        for bucket, dim_keys in self._LEGACY_BUCKET_DIMS.items():
            bucket_weight = norm_weights.get(bucket, 0.0)
            dim_sum = sum(details.get(dim, 0.0) for dim in dim_keys)
            total += dim_sum * bucket_weight
        return round(total, 2)

    def _compute_recommended_action_from_signals(
        self,
        signals: Optional[list],
    ) -> str | None:
        """Map HubSpot signal types to legacy action labels (pre-unification API)."""
        if not signals:
            return None

        best_action: str | None = None
        best_key: tuple[int, int] | None = None
        for index, signal in enumerate(signals):
            signal_type = (
                signal if isinstance(signal, str)
                else getattr(signal, "signal_type", None)
            )
            mapped = self._LEGACY_SIGNAL_ACTIONS.get(signal_type)
            if mapped is None:
                continue
            rank, action = mapped
            key = (rank, -index)
            if best_key is None or key < best_key:
                best_key = key
                best_action = action
        return best_action

    # ------------------------------------------------------------------
    # Static helpers for API / tests
    # ------------------------------------------------------------------

    @staticmethod
    def compute_recommended_action(lead: Lead) -> str | None:
        total = float(getattr(lead, 'lead_score', 0) or 0)
        data_quality = float(getattr(lead, 'data_completeness_score', 0) or 0)
        tier = rubric.calculate_score_tier(total)
        action, _, signals = LeadScoringEngine.evaluate_recommended_action(
            lead, total, data_quality, tier,
        )
        refined, _method = LeadScoringEngine()._apply_outreach_method(lead, action, signals)
        return refined

    @staticmethod
    def get_winning_rule_signals(lead: Lead) -> dict:
        total = float(getattr(lead, 'lead_score', 0) or 0)
        data_quality = float(getattr(lead, 'data_completeness_score', 0) or 0)
        tier = rubric.calculate_score_tier(total)
        action, _, signals = LeadScoringEngine.evaluate_recommended_action(
            lead, total, data_quality, tier,
        )
        _refined, method = LeadScoringEngine()._apply_outreach_method(lead, action, signals)
        if method:
            signals = {**signals, 'recommended_contact_method': method}
        return signals

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_outreach_method(
        self,
        lead: Lead,
        recommended_action: str | None,
        action_signals: dict,
    ) -> tuple[str | None, str | None]:
        """Resolve contact channel and refine outreach action."""
        if not recommended_action:
            return recommended_action, None

        if recommended_action == 'mail_ready':
            return recommended_action, 'direct_mail'
        if recommended_action == 'call_ready':
            return recommended_action, 'phone'

        if recommended_action not in OUTREACH_ACTIONS:
            return recommended_action, None

        has_phone, has_email, _has_match = _resolve_crm_flags(lead)
        lead_id = getattr(lead, 'id', None)
        recent_email = (
            self._has_recent_email(lead_id)
            if isinstance(lead_id, int)
            else False
        )

        method = evaluate_contact_method(
            lead,
            recommended_action,
            has_phone=has_phone,
            has_email=has_email,
            recent_email=recent_email,
        )
        refined = refine_outreach_action(recommended_action, method)
        if refined == 'mail_ready':
            method = 'direct_mail'
        elif refined == 'call_ready':
            method = 'phone'
        return refined, method

    @staticmethod
    def _has_recent_email(lead_id: int) -> bool:
        cutoff = datetime.utcnow() - timedelta(days=ENGAGEMENT_LOOKBACK_DAYS)
        row = (
            LeadTimelineEntry.query
            .filter(
                LeadTimelineEntry.lead_id == lead_id,
                LeadTimelineEntry.event_type == 'email_logged',
                LeadTimelineEntry.is_deleted.is_(False),
                LeadTimelineEntry.occurred_at >= cutoff,
            )
            .limit(1)
            .first()
        )
        return row is not None

    def _hubspot_signal_adjustment(self, signals: Optional[list]) -> float:
        if not signals:
            return 0.0
        present = set()
        for signal in signals:
            signal_type = signal if isinstance(signal, str) else getattr(signal, "signal_type", None)
            if signal_type and signal_type in self.SIGNAL_ADJUSTMENTS:
                present.add(signal_type)
        return sum(self.SIGNAL_ADJUSTMENTS[t] for t in present)

    def _score_engagement(self, lead: Lead) -> float:
        lead_id = getattr(lead, 'id', None)
        if not isinstance(lead_id, int):
            return 0.0

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
        STAGE_BONUS = {
            'skip_trace': -5.0, 'awaiting_skip_trace': -5.0,
            'mailing_no_contact_made': 0.0,
            'mailing_contacted_no_interest': -10.0,
            'mailing_contacted_interested': 15.0,
            'negotiating_remote': 25.0,
            'in_person_appointment': 30.0,
            'offer_delivered': 35.0,
        }
        return STAGE_BONUS.get(getattr(lead, 'lead_status', None), 0.0)


# Deprecated alias — use LeadScoringEngine directly.
ActionEngineService = LeadScoringEngine

# Module-level helpers for scripts/tests
def evaluate_recommended_action(lead: Lead) -> tuple[str | None, str, dict]:
    """Backward-compatible wrapper returning (action, winning_rule, signals)."""
    engine = LeadScoringEngine()
    weights = engine.get_weights(lead.owner_user_id or 'default')
    result = engine.compute(lead, weights)
    return result.recommended_action, result.winning_rule, result.action_signals

# Re-export rubric utilities used by tests
parse_sale_date_string = rubric.parse_sale_date_string
effective_acquisition_date = rubric.effective_acquisition_date
calculate_score_tier = rubric.calculate_score_tier
TIER_A_MIN = rubric.TIER_A_MIN
TIER_B_MIN = rubric.TIER_B_MIN
TIER_C_MIN = rubric.TIER_C_MIN
RESIDENTIAL_MAX_POINTS = rubric.RESIDENTIAL_MAX_POINTS
COMMERCIAL_MAX_POINTS = rubric.COMMERCIAL_MAX_POINTS
ALLOWED_ACTIONS = {
    "review_now", "enrich_data", "mail_ready", "call_ready",
    "valuation_needed", "suppress", "nurture", "needs_manual_review",
    "follow_up_now", "ready_for_outreach", "add_contact_info", "create_task",
    "resolve_match", "analyze_property", "do_not_contact",
}
