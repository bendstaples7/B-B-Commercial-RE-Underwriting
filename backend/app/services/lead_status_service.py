"""Shared lead status change logic for single and bulk updates."""
from __future__ import annotations

import datetime as dt

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry


def apply_lead_status_change(
    lead: Lead,
    new_status: str,
    *,
    reason: str = '',
    actor: str = 'anonymous',
    recompute_action: bool = True,
) -> None:
    """Update lead status with DNC/suppress side effects and timeline entry."""
    old_status = lead.lead_status
    lead.lead_status = new_status

    if new_status == 'do_not_contact':
        lead.recommended_action = None
        LeadTask.query.filter_by(lead_id=lead.id, status='open').update({'status': 'cancelled'})
    elif new_status == 'suppressed':
        lead.recommended_action = None

    if reason:
        summary = f"Status changed from '{old_status}' to '{new_status}'. {reason}"
    else:
        summary = f"Status changed from '{old_status}' to '{new_status}'."

    entry = LeadTimelineEntry(
        lead_id=lead.id,
        event_type='status_changed',
        occurred_at=dt.datetime.now(dt.timezone.utc),
        source='manual',
        actor=actor,
        summary=summary,
        event_metadata={
            'previous_status': old_status,
            'new_status': new_status,
            'reason': reason or None,
        },
    )
    db.session.add(lead)
    db.session.add(entry)
    db.session.commit()

    if recompute_action and new_status not in ('do_not_contact', 'suppressed'):
        from app.services.lead_refresh import refresh_lead_scoring
        refresh_lead_scoring(lead.id)
