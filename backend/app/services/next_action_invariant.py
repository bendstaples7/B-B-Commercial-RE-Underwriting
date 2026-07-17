"""Ensure active leads never silently lose their next-action chain.

After a LeadTask is completed or cancelled, if the lead is still in an active
pipeline state and has zero open LeadTasks, refresh scoring so the
recommended action surfaces decide-next (typically ``create_task``) and the
lead can appear in No Next Action.
"""
from __future__ import annotations

import logging

from app.models import Lead, LeadTask

logger = logging.getLogger(__name__)

# Intentional park / terminal — no decide-next prompt required.
PARKED_LEAD_STATUSES = frozenset({
    'deprioritize',
    'do_not_contact',
    'suppressed',
    'deal_won',
    'deal_lost',
})


def ensure_next_action_after_task_change(lead_id: int) -> None:
    """Refresh scoring when an active lead has no open LeadTasks left."""
    if not isinstance(lead_id, int):
        return
    try:
        lead = Lead.query.get(lead_id)
        if lead is None:
            return
        if (lead.lead_status or '') in PARKED_LEAD_STATUSES:
            return
        open_count = LeadTask.query.filter_by(lead_id=lead_id, status='open').count()
        if open_count > 0:
            return
        from app.services.lead_refresh import refresh_lead_scoring
        refresh_lead_scoring(lead_id)
    except Exception as exc:
        logger.warning(
            'ensure_next_action_after_task_change failed for lead_id=%s: %s',
            lead_id, exc,
        )
