"""Outcome-calibrated scoring weights from pipeline stage results.

Compares five weighted score buckets on positive vs negative outcome leads,
then nudges ``ScoringWeights`` toward buckets that correlate with wins —
without replacing the explainable rubric.

Scheduled runs default to ``sample_mode='pre_outcome'`` so late-stage
pipeline bonuses do not teach the model that interested leads "look"
interested.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from app import db
from app.models.lead import Lead
from app.models.lead_score import LeadScore
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.services.lead_scoring_engine import (
    DEFAULT_WEIGHTS,
    LeadScoringEngine,
    WEIGHT_SUM_TOLERANCE,
)

logger = logging.getLogger(__name__)

WEIGHT_KEYS = (
    "property_characteristics_weight",
    "data_completeness_weight",
    "owner_situation_weight",
    "location_desirability_weight",
    "data_enrichment_weight",
)

BUCKET_TO_WEIGHT = {
    "property_characteristics": "property_characteristics_weight",
    "data_completeness": "data_completeness_weight",
    "owner_situation": "owner_situation_weight",
    "location_desirability": "location_desirability_weight",
    "data_enrichment": "data_enrichment_weight",
}

BUCKET_DETAIL_KEYS = {
    "property_characteristics": "bucket_property_characteristics",
    "data_completeness": "bucket_data_completeness",
    "owner_situation": "bucket_owner_situation",
    "location_desirability": "bucket_location_desirability",
    "data_enrichment": "bucket_data_enrichment",
}

# Stages that indicate the lead progressed / converted.
POSITIVE_OUTCOME_STATUSES = frozenset({
    "mailing_contacted_interested",
    "negotiating_remote",
    "in_person_appointment",
    "offer_delivered",
    "deal_won",
})

# Stages that indicate dead / rejected outcomes.
NEGATIVE_OUTCOME_STATUSES = frozenset({
    "mailing_contacted_no_interest",
    "deprioritize",
    "deal_lost",
    "suppressed",
    "do_not_contact",
})

SampleMode = Literal['latest', 'pre_outcome']

MIN_WEIGHT = 0.05
MAX_WEIGHT = 0.50
DEFAULT_LEARNING_RATE = 0.15
DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_MIN_SAMPLES_PER_CLASS = 15
DEFAULT_SAMPLE_MODE: SampleMode = 'pre_outcome'


@dataclass
class CalibrationReport:
    positive_count: int = 0
    negative_count: int = 0
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    sample_mode: str = DEFAULT_SAMPLE_MODE
    mean_buckets_positive: dict[str, float] = field(default_factory=dict)
    mean_buckets_negative: dict[str, float] = field(default_factory=dict)
    lifts: dict[str, float] = field(default_factory=dict)
    current_weights: dict[str, float] = field(default_factory=dict)
    suggested_weights: dict[str, float] = field(default_factory=dict)
    applied: bool = False
    leads_rescored: int = 0
    skipped_reason: Optional[str] = None
    calibrated_at: Optional[str] = None
    stratum_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "lookback_days": self.lookback_days,
            "sample_mode": self.sample_mode,
            "mean_buckets_positive": self.mean_buckets_positive,
            "mean_buckets_negative": self.mean_buckets_negative,
            "lifts": self.lifts,
            "current_weights": self.current_weights,
            "suggested_weights": self.suggested_weights,
            "applied": self.applied,
            "leads_rescored": self.leads_rescored,
            "skipped_reason": self.skipped_reason,
            "calibrated_at": self.calibrated_at,
            "stratum_counts": self.stratum_counts,
        }


def _weights_dict(weights) -> dict[str, float]:
    return {key: float(getattr(weights, key)) for key in WEIGHT_KEYS}


def _extract_buckets(score_details: dict | None, data_quality_score: float | None) -> dict[str, float] | None:
    """Read persisted bucket snapshots, or rebuild from rubric dims when missing."""
    details = score_details if isinstance(score_details, dict) else {}
    buckets: dict[str, float] = {}
    have_all = True
    for bucket, detail_key in BUCKET_DETAIL_KEYS.items():
        val = details.get(detail_key)
        if isinstance(val, (int, float)):
            buckets[bucket] = float(val)
        else:
            have_all = False
            break
    if have_all:
        return buckets

    # Legacy score rows: rebuild from dimension keys when possible.
    from app.services import scoring_rubric as rubric

    # Need at least one real rubric dim — empty details are not usable.
    if not any(
        isinstance(details.get(k), (int, float))
        for k in (
            "property_type_fit", "neighborhood_fit", "structured_motivation",
            "public_record_distress", "contactability", "property_equity",
        )
    ):
        return None

    category = "residential"
    if details.get("condo_clarity") is not None or details.get("building_sale_possible") is not None:
        category = "commercial"
    dq = float(data_quality_score) if data_quality_score is not None else float(
        details.get("data_completeness") or 0.0
    )
    rebuilt = rubric.bucket_scores(details, dq, category)
    return {k: float(v) for k, v in rebuilt.items()}


def _mean_buckets(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {bucket: 0.0 for bucket in BUCKET_TO_WEIGHT}
    sums = {bucket: 0.0 for bucket in BUCKET_TO_WEIGHT}
    for row in rows:
        for bucket in sums:
            sums[bucket] += row.get(bucket, 0.0)
    n = float(len(rows))
    return {bucket: round(total / n, 4) for bucket, total in sums.items()}


def _normalize_weights(raw: dict[str, float]) -> dict[str, float]:
    clamped = {
        key: max(MIN_WEIGHT, min(MAX_WEIGHT, float(raw.get(key, 0.0))))
        for key in WEIGHT_KEYS
    }
    total = sum(clamped.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    normalized = {key: val / total for key, val in clamped.items()}
    # Fix residual float drift onto last key.
    drift = 1.0 - sum(normalized.values())
    if abs(drift) > 1e-9:
        last = WEIGHT_KEYS[-1]
        normalized[last] = max(MIN_WEIGHT, normalized[last] + drift)
    return {key: round(normalized[key], 4) for key in WEIGHT_KEYS}


def suggest_weights_from_lifts(
    current: dict[str, float],
    lifts: dict[str, float],
    *,
    learning_rate: float = DEFAULT_LEARNING_RATE,
) -> dict[str, float]:
    """Nudge current weights by normalized bucket lifts (sum of lifts → 0)."""
    lift_vals = [lifts.get(bucket, 0.0) for bucket in BUCKET_TO_WEIGHT]
    mean_lift = sum(lift_vals) / len(lift_vals) if lift_vals else 0.0
    centered = {
        bucket: lifts.get(bucket, 0.0) - mean_lift
        for bucket in BUCKET_TO_WEIGHT
    }
    # Scale so the largest absolute centered lift maps to learning_rate.
    max_abs = max((abs(v) for v in centered.values()), default=0.0)
    scale = (learning_rate / max_abs) if max_abs > 1e-9 else 0.0

    proposed = {}
    for bucket, weight_key in BUCKET_TO_WEIGHT.items():
        delta = centered[bucket] * scale
        proposed[weight_key] = float(current.get(weight_key, 0.0)) + delta
    return _normalize_weights(proposed)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _buckets_from_score_row(row: LeadScore | None, lead: Lead) -> dict[str, float] | None:
    if row is None:
        return None
    return _extract_buckets(row.score_details, row.data_quality_score)


def _latest_score_before(lead_id: int, before: datetime) -> LeadScore | None:
    before_aware = _aware(before)
    if before_aware is None:
        return None
    # Compare naively against DB (often naive UTC) and aware cutoff.
    before_naive = before_aware.replace(tzinfo=None)
    return (
        LeadScore.query.filter(
            LeadScore.lead_id == lead_id,
            LeadScore.created_at <= before_naive,
        )
        .order_by(LeadScore.created_at.desc(), LeadScore.id.desc())
        .first()
    )


def _outcome_transition_rows(*, lookback_days: int) -> list[LeadTimelineEntry]:
    """Status-changed timeline rows into positive/negative outcomes in window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    cutoff_naive = cutoff.replace(tzinfo=None)
    rows = (
        LeadTimelineEntry.query.filter(
            LeadTimelineEntry.event_type == 'status_changed',
            LeadTimelineEntry.occurred_at >= cutoff_naive,
        )
        .order_by(LeadTimelineEntry.occurred_at.asc(), LeadTimelineEntry.id.asc())
        .all()
    )
    outcome_statuses = POSITIVE_OUTCOME_STATUSES | NEGATIVE_OUTCOME_STATUSES
    out: list[LeadTimelineEntry] = []
    for row in rows:
        meta = row.event_metadata if isinstance(row.event_metadata, dict) else {}
        new_status = (meta.get('new_status') or '').strip()
        if new_status in outcome_statuses:
            out.append(row)
    return out


def _stratum_key(lead: Lead) -> str:
    category = (getattr(lead, 'lead_category', None) or 'residential').strip().lower()
    if category not in ('residential', 'commercial'):
        category = 'residential'
    return category


def collect_outcome_bucket_samples(
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    sample_mode: SampleMode = DEFAULT_SAMPLE_MODE,
) -> tuple[list[dict[str, float]], list[dict[str, float]], dict[str, dict[str, int]]]:
    """Load score buckets for positive/negative outcomes.

    ``pre_outcome`` (default for scheduled runs): use the newest ``lead_scores``
    row at or before the status transition into an outcome stage.

    ``latest``: use current lead_status + latest score history row (manual UI).
    """
    positive: list[dict[str, float]] = []
    negative: list[dict[str, float]] = []
    stratum_counts: dict[str, dict[str, int]] = {}

    def _record(lead: Lead, buckets: dict[str, float], positive_outcome: bool) -> None:
        key = _stratum_key(lead)
        bucket = stratum_counts.setdefault(key, {'positive': 0, 'negative': 0})
        if positive_outcome:
            positive.append(buckets)
            bucket['positive'] += 1
        else:
            negative.append(buckets)
            bucket['negative'] += 1

    if sample_mode == 'latest':
        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        cutoff_naive = cutoff.replace(tzinfo=None)
        leads = (
            Lead.query.filter(
                Lead.lead_status.in_(POSITIVE_OUTCOME_STATUSES | NEGATIVE_OUTCOME_STATUSES),
                Lead.updated_at >= cutoff_naive,
            )
            .all()
        )
        for lead in leads:
            latest = (
                LeadScore.query.filter_by(lead_id=lead.id)
                .order_by(LeadScore.created_at.desc(), LeadScore.id.desc())
                .first()
            )
            buckets = _buckets_from_score_row(latest, lead)
            if buckets is None:
                continue
            status = (lead.lead_status or "").strip()
            if status in POSITIVE_OUTCOME_STATUSES:
                _record(lead, buckets, True)
            elif status in NEGATIVE_OUTCOME_STATUSES:
                _record(lead, buckets, False)
        return positive, negative, stratum_counts

    # pre_outcome — one sample per lead (first outcome transition in window).
    seen_leads: set[int] = set()
    for entry in _outcome_transition_rows(lookback_days=lookback_days):
        lead_id = entry.lead_id
        if not isinstance(lead_id, int) or lead_id in seen_leads:
            continue
        meta = entry.event_metadata if isinstance(entry.event_metadata, dict) else {}
        new_status = (meta.get('new_status') or '').strip()
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            continue
        score_row = _latest_score_before(lead_id, entry.occurred_at)
        buckets = _buckets_from_score_row(score_row, lead)
        if buckets is None:
            continue
        seen_leads.add(lead_id)
        if new_status in POSITIVE_OUTCOME_STATUSES:
            _record(lead, buckets, True)
        elif new_status in NEGATIVE_OUTCOME_STATUSES:
            _record(lead, buckets, False)

    return positive, negative, stratum_counts


def calibrate_scoring_weights(
    user_id: str,
    *,
    apply: bool = False,
    rescore: bool = True,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    min_samples_per_class: int = DEFAULT_MIN_SAMPLES_PER_CLASS,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    sample_mode: SampleMode = DEFAULT_SAMPLE_MODE,
) -> CalibrationReport:
    """Analyze outcomes and optionally write calibrated weights + rescore."""
    engine = LeadScoringEngine()
    weights = engine.get_weights(user_id)
    current = _weights_dict(weights)
    report = CalibrationReport(
        lookback_days=lookback_days,
        sample_mode=sample_mode,
        current_weights=current,
        suggested_weights=dict(current),
        calibrated_at=datetime.now(timezone.utc).isoformat(),
    )

    positive, negative, stratum_counts = collect_outcome_bucket_samples(
        lookback_days=lookback_days,
        sample_mode=sample_mode,
    )
    report.positive_count = len(positive)
    report.negative_count = len(negative)
    report.stratum_counts = stratum_counts

    if (
        len(positive) < min_samples_per_class
        or len(negative) < min_samples_per_class
    ):
        report.skipped_reason = (
            f"Need at least {min_samples_per_class} positive and "
            f"{min_samples_per_class} negative outcomes with score history "
            f"(mode={sample_mode}; have {len(positive)} / {len(negative)}; "
            f"strata={stratum_counts})."
        )
        report.suggested_weights = dict(current)
        return report

    mean_pos = _mean_buckets(positive)
    mean_neg = _mean_buckets(negative)
    report.mean_buckets_positive = mean_pos
    report.mean_buckets_negative = mean_neg
    lifts = {
        bucket: round(mean_pos[bucket] - mean_neg[bucket], 4)
        for bucket in BUCKET_TO_WEIGHT
    }
    report.lifts = lifts
    suggested = suggest_weights_from_lifts(
        current, lifts, learning_rate=learning_rate,
    )
    report.suggested_weights = suggested

    if not apply:
        return report

    # Guard: suggested must still sum ~1.
    if abs(sum(suggested.values()) - 1.0) > WEIGHT_SUM_TOLERANCE:
        report.skipped_reason = "Suggested weights failed sum validation."
        return report

    updated = engine.update_weights(
        user_id=user_id,
        property_characteristics_weight=suggested["property_characteristics_weight"],
        data_completeness_weight=suggested["data_completeness_weight"],
        owner_situation_weight=suggested["owner_situation_weight"],
        location_desirability_weight=suggested["location_desirability_weight"],
        data_enrichment_weight=suggested["data_enrichment_weight"],
    )
    meta = {
        "positive_count": report.positive_count,
        "negative_count": report.negative_count,
        "lookback_days": lookback_days,
        "learning_rate": learning_rate,
        "sample_mode": sample_mode,
        "stratum_counts": stratum_counts,
        "lifts": lifts,
        "previous_weights": current,
        "suggested_weights": suggested,
        "calibrated_at": report.calibrated_at,
    }
    updated.calibration_meta = meta
    updated.last_calibrated_at = datetime.utcnow()
    db.session.add(updated)
    db.session.commit()

    report.applied = True
    report.current_weights = _weights_dict(updated)
    if rescore:
        report.leads_rescored = engine.bulk_rescore(user_id=user_id)
    logger.info(
        "Calibrated scoring weights for user %s (mode=%s pos=%s neg=%s rescored=%s)",
        user_id, sample_mode, report.positive_count, report.negative_count,
        report.leads_rescored,
    )
    return report


def run_scheduled_calibration(
    user_id: str = 'default',
) -> CalibrationReport:
    """Celery beat entry: pre-outcome dry-run unless SCORING_CALIBRATION_APPLY=1."""
    apply = os.environ.get('SCORING_CALIBRATION_APPLY', '').strip().lower() in (
        '1', 'true', 'yes',
    )
    lookback_days = int(os.environ.get('SCORING_CALIBRATION_LOOKBACK_DAYS', '365'))
    return calibrate_scoring_weights(
        user_id,
        apply=apply,
        rescore=apply,
        lookback_days=lookback_days,
        sample_mode='pre_outcome',
    )
