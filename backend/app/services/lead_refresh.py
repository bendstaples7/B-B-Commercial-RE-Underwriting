"""Unified per-lead scoring refresh helper.

Recompute AND persist BOTH ``lead_score`` and ``recommended_action`` for a
single lead in one place, so every *non-HubSpot* mutation point (manual status
change, task create/update/complete, lead/property field edit, enrichment, and
contact link/unlink) keeps the score in parity with the recommended action —
instead of letting ``lead_score`` go stale until the nightly bulk rescore runs.

Why this exists
---------------
``recommended_action`` is already recomputed at most mutation points (via
``ActionEngineService.recompute_and_persist``), but ``lead_score`` was only
recomputed by the post-import rescore, the webhook signal-extraction chain, and
the nightly bulk job.  A manual status change (e.g. ``-> negotiating_remote``)
therefore left the score stale even though the pipeline-stage bonus changed.
This helper closes that gap by refreshing both in a single, reusable call.

Design notes
------------
* Synchronous and cheap: a single lead is inexpensive to score, so this does
  NOT enqueue a Celery job.  The bulk/nightly rescore and the HubSpot import
  pipeline keep their own (batch) paths untouched.
* Fully error-isolated: this function NEVER raises into its caller.  On any
  failure it logs a warning and rolls back only its OWN uncommitted work.
  Callers are expected to have already committed their mutation before calling
  here (it runs *after* the change commits), so a rollback here cannot undo the
  caller's change.
* Scoring logic is NOT duplicated here — it reuses ``LeadScoringEngine``
  (mirroring ``LeadScoringEngine.bulk_rescore._rescore_lead`` for a single
  lead) and ``ActionEngineService.recompute_and_persist``.
"""
import logging

logger = logging.getLogger(__name__)


def refresh_lead_scoring(lead_id: int) -> None:
    """Recompute and persist ``lead_score`` + ``recommended_action`` for one lead.

    Order matters: the score is recomputed and committed first so any
    score-threshold rule in the action engine (e.g. ``lead_score >= 70`` ->
    ``ready_for_outreach``) sees the freshly updated score.

    Parameters
    ----------
    lead_id : int
        The lead to refresh.  If the lead does not exist, this is a no-op.

    Returns
    -------
    None
        Always returns ``None``; never propagates exceptions to the caller.
    """
    # Imports are local to keep this module dependency-light and immune to
    # circular-import ordering issues (services import each other freely).
    from app import db
    from app.models.lead import Lead
    from app.models.hubspot_signal import HubSpotSignal
    from app.services.lead_scoring_engine import LeadScoringEngine
    from app.services.action_engine_service import ActionEngineService

    try:
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            return

        # --- 1. Recompute lead_score ------------------------------------
        # Mirrors LeadScoringEngine.bulk_rescore._rescore_lead for a single
        # lead: resolve the owner's weights, load the lead's signals oldest
        # -first, then compute the weighted score (which already includes the
        # pipeline-stage bonus and any HubSpot signal adjustments).
        engine = LeadScoringEngine()
        weights = engine.get_weights(lead.owner_user_id or 'default')
        signals = (
            HubSpotSignal.query
            .filter_by(lead_id=lead.id)
            .order_by(HubSpotSignal.extracted_at.asc())
            .all()
        )
        lead.lead_score = engine.compute_score(lead, weights, signals=signals)
        db.session.add(lead)
        db.session.commit()

        # --- 2. Recompute recommended_action ----------------------------
        # Done AFTER the score commit so score-threshold rules see the fresh
        # score.  recompute_and_persist commits internally only when the
        # action value actually changes (and appends a timeline entry then).
        ActionEngineService.recompute_and_persist(lead_id)
    except Exception as exc:  # noqa: BLE001 — must never raise into the caller
        logger.warning(
            "refresh_lead_scoring: failed to refresh scoring for lead_id=%s: %s",
            lead_id, exc,
        )
        # Roll back only our own uncommitted work; the caller's already-
        # committed mutation is durable and unaffected by this rollback.
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover — best-effort cleanup
            logger.debug(
                "refresh_lead_scoring: rollback after failure also failed",
                exc_info=True,
            )
