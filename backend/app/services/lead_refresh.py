"""Unified per-lead scoring refresh helper."""
import logging

logger = logging.getLogger(__name__)


def refresh_lead_scoring(lead_id: int, *, raise_on_error: bool = False) -> None:
    """Recompute and persist score + recommended_action for one lead.

    Most mutation callers intentionally treat scoring refresh as best-effort so
    the user's primary write is not lost. Callers that create score inputs and
    return fresh scores can opt into strict mode to keep the whole transaction
    atomic.
    """
    from app import db
    from app.services.lead_scoring_engine import LeadScoringEngine

    try:
        LeadScoringEngine().score_and_persist(lead_id)
    except Exception as exc:
        logger.warning(
            "refresh_lead_scoring: failed to refresh scoring for lead_id=%s: %s",
            lead_id, exc,
        )
        try:
            db.session.rollback()
        except Exception:
            logger.debug("refresh_lead_scoring: rollback failed", exc_info=True)
        if raise_on_error:
            raise
