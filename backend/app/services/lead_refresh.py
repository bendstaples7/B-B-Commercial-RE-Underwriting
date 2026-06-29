"""Unified per-lead scoring refresh helper."""
import logging

logger = logging.getLogger(__name__)


def refresh_lead_scoring(lead_id: int) -> None:
    """Recompute and persist score + recommended_action for one lead."""
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
