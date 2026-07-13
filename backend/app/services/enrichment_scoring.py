"""Shared data-enrichment sub-score helpers for lead scoring engines.

Both ``LeadScoringEngine`` and ``DeterministicScoringEngine`` delegate to
these functions so enrichment dimensions stay consistent across scoring paths.
"""
from datetime import date, datetime

from app.models.lead import Lead

_SAFE_TYPES = (int, float, str, bool, date, datetime, dict, list, tuple, set)


def safe_attr(obj, name: str, default=None):
    """Get attribute, returning default for sentinel/mock objects."""
    val = getattr(obj, name, default)
    if val is not None and not isinstance(val, _SAFE_TYPES):
        return default
    return val


def contactability_score(lead: Lead, max_points: float = 20.0) -> float:
    """Enrichment depth beyond contact presence (phones/emails live in data quality).

    Segments: skip-trace recency and socials. Phone/email presence is scored in
    ``calculate_data_quality_score`` so lead_score does not double-count reachability.
    """
    segments = 0

    if safe_attr(lead, "date_skip_traced") is not None:
        segments += 1

    if safe_attr(lead, "socials"):
        segments += 1

    return (segments / 2.0) * max_points


def property_equity_score(lead: Lead, max_points: float = 25.0) -> float:
    """Score estimated property equity based on property characteristics."""
    score = 0.0

    yb = safe_attr(lead, "year_built")
    if yb is not None:
        if yb < 1960:
            score += max_points * 0.40
        elif yb <= 1990:
            score += max_points * 0.30
        else:
            score += max_points * 0.15

    ls = safe_attr(lead, "lot_size")
    if ls is not None and ls > 0:
        score += max_points * 0.30

    sf = safe_attr(lead, "square_footage")
    if sf is not None and sf > 0:
        score += max_points * 0.30

    return min(score, max_points)


def ownership_duration_score(lead: Lead, max_points: float = 15.0) -> float:
    """Score based on how long the owner has held the property."""
    from app.services.scoring_rubric import effective_acquisition_date

    acquisition = effective_acquisition_date(lead)
    if acquisition is None:
        return 0.0

    today = date.today()
    if acquisition > today:
        return 0.0

    years = (today - acquisition).days / 365.25

    if years >= 20:
        return max_points * 1.0
    if years >= 10:
        return max_points * 0.80
    if years >= 5:
        return max_points * 0.55
    if years >= 2:
        return max_points * 0.35
    return max_points * 0.15


def engagement_score(lead: Lead, max_points: float = 10.0) -> float:
    """Score based on lead engagement signals."""
    score = 0.0

    mh = safe_attr(lead, "mailer_history")
    if mh is not None and (isinstance(mh, list) and len(mh) > 0):
        score += max_points * 0.30

    if safe_attr(lead, "has_phone", False):
        score += max_points * 0.25

    if safe_attr(lead, "has_email", False):
        score += max_points * 0.25

    if safe_attr(lead, "follow_up_date") is not None:
        score += max_points * 0.20

    return min(score, max_points)


def scale_subscore_to_100(score: float, max_points: float) -> float:
    """Scale a capped sub-score to a 0–100 range for weighted scoring."""
    if max_points <= 0:
        return 0.0
    return min(100.0, (score / max_points) * 100.0)
