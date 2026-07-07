"""Mark property analysis complete and keep lead scoring in sync."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app import db
from app.models.lead import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry

logger = logging.getLogger(__name__)

ANALYSIS_COMPLETE_STEP = 'WEIGHTED_SCORING'


def _session_reached_weighted_scoring(session) -> bool:
    if session is None:
        return False
    completed = session.completed_steps or []
    return ANALYSIS_COMPLETE_STEP in completed


def session_reached_weighted_scoring(session) -> bool:
    """True when the analysis session completed the weighted-scoring step."""
    return _session_reached_weighted_scoring(session)


def query_lead_ids_for_analysis_complete_backfill() -> list[int]:
    """Lead IDs with completed weighted-scoring session but analysis_complete=false."""
    from sqlalchemy.orm import joinedload

    from app.models import AnalysisSession

    bind = db.session.get_bind()
    if bind.dialect.name == 'postgresql':
        from sqlalchemy import text

        rows = db.session.execute(
            text("""
                SELECT l.id
                FROM leads l
                JOIN analysis_sessions s ON l.analysis_session_id = s.id
                WHERE l.analysis_complete = FALSE
                  AND s.completed_steps::jsonb ? :step
            """),
            {'step': ANALYSIS_COMPLETE_STEP},
        ).fetchall()
        return [row[0] for row in rows]

    leads = (
        Lead.query.options(joinedload(Lead.analysis_session))
        .join(AnalysisSession, Lead.analysis_session_id == AnalysisSession.id)
        .filter(Lead.analysis_complete.is_(False))
        .all()
    )
    return [
        lead.id for lead in leads
        if _session_reached_weighted_scoring(lead.analysis_session)
    ]


def resolve_analysis_complete(lead: Lead) -> bool:
    """True when analysis is done — DB flag or linked session reached weighted scoring."""
    if getattr(lead, 'analysis_complete', False):
        return True
    session = getattr(lead, 'analysis_session', None)
    return _session_reached_weighted_scoring(session)


def mark_lead_analysis_complete(
    lead_id: int,
    *,
    source: str = 'system',
    actor: str = 'System',
    recompute_action: bool = True,
    commit: bool = True,
) -> Lead | None:
    """Set analysis_complete, log timeline, and optionally rescore the lead."""
    lead = db.session.get(Lead, lead_id)
    if lead is None:
        logger.warning("mark_lead_analysis_complete: lead %s not found", lead_id)
        return None

    already_complete = lead.analysis_complete
    if not already_complete:
        lead.analysis_complete = True
        db.session.add(lead)

        entry = LeadTimelineEntry(
            lead_id=lead_id,
            event_type='property_analysis_completed',
            occurred_at=datetime.now(timezone.utc),
            source=source,
            actor=actor,
            summary='Property analysis completed.',
            event_metadata={'analysis_session_id': lead.analysis_session_id},
        )
        db.session.add(entry)

    if recompute_action:
        from app.services.lead_scoring_engine import LeadScoringEngine
        LeadScoringEngine().score_and_persist(lead_id, commit=commit)
    elif commit and not already_complete:
        db.session.commit()

    return lead


def mark_lead_analysis_complete_for_session(
    analysis_session_id: int,
    *,
    source: str = 'workflow',
    actor: str = 'System',
) -> Lead | None:
    """Mark analysis complete for the lead linked to an analysis session."""
    lead = Lead.query.filter_by(analysis_session_id=analysis_session_id).first()
    if lead is None:
        logger.debug(
            "No lead linked to analysis_session_id=%s; skipping analysis_complete",
            analysis_session_id,
        )
        return None
    return mark_lead_analysis_complete(
        lead.id,
        source=source,
        actor=actor,
        recompute_action=True,
        commit=True,
    )
