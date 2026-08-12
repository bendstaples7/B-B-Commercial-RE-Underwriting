"""Shared lead status change logic for single and bulk updates."""
from __future__ import annotations

import datetime as dt
import logging

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry

logger = logging.getLogger(__name__)


def _cancel_tasks_for_terminal_status(
    lead_id: int,
    *,
    actor: str,
    status: str,
) -> set[str]:
    from app.models.task import Task
    from app.services.mail_task_lifecycle_service import is_mail_follow_up_task

    hubspot_task_ids: set[str] = set()
    open_tasks = LeadTask.query.filter(
        LeadTask.lead_id == lead_id,
        LeadTask.status == 'open',
    ).all()
    for task in open_tasks:
        if task.hubspot_task_id:
            hubspot_task_ids.add(str(task.hubspot_task_id))
        if is_mail_follow_up_task(task) and task.mirror_task_id:
            mirror = db.session.get(Task, task.mirror_task_id)
            if mirror is not None and mirror.hubspot_task_id:
                hubspot_task_ids.add(str(mirror.hubspot_task_id))
    from app.services.mail_task_lifecycle_service import cancel_mail_rematch_tasks
    cancel_mail_rematch_tasks(
        lead_id,
        actor=actor,
        reason=f'status_{status}',
    )
    LeadTask.query.filter_by(lead_id=lead_id, status='open').update(
        {'status': 'cancelled'},
    )
    return hubspot_task_ids


def _sync_cancelled_hubspot_tasks(hubspot_task_ids: set[str]) -> None:
    """Best-effort post-commit CRM sync for locally cancelled tasks."""
    if not hubspot_task_ids:
        return
    try:
        from app.services.hubspot_task_completion_service import (
            sync_pending_hubspot_completions,
        )
        sync_pending_hubspot_completions(sorted(hubspot_task_ids))
    except Exception as exc:  # noqa: BLE001 - CRM mirror must not fail status changes
        logger.warning(
            'HubSpot completion sync failed after terminal status change: %s',
            exc,
            exc_info=True,
        )


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
    if new_status == old_status:
        # Idempotent bulk DNC/suppress must still clear leftover open tasks /
        # rematch mirrors when the lead is already in that terminal status.
        if new_status in ('do_not_contact', 'suppressed'):
            lead.recommended_action = None
            cancelled_hubspot_ids = _cancel_tasks_for_terminal_status(
                lead.id,
                actor=actor,
                status=new_status,
            )
            db.session.add(lead)
            db.session.commit()
            _sync_cancelled_hubspot_tasks(cancelled_hubspot_ids)
            return
        # Do not force needs_skip_trace mid recent-sale hold.
        if new_status == 'skip_trace' and not lead.needs_skip_trace:
            from app.services.skip_trace_enqueue import SkipTraceEnqueue
            if SkipTraceEnqueue._find_open_future_recent_sale_hold(lead.id) is None:
                lead.needs_skip_trace = True
                db.session.add(lead)
                db.session.commit()
        return

    lead.lead_status = new_status

    # Entering skip_trace means skip work is still needed, unless a future
    # recent-sale hold is already parking the lead.
    if new_status == 'skip_trace':
        from app.services.skip_trace_enqueue import SkipTraceEnqueue
        if SkipTraceEnqueue._find_open_future_recent_sale_hold(lead.id) is None:
            lead.needs_skip_trace = True

    if new_status == 'do_not_contact':
        lead.recommended_action = None
        cancelled_hubspot_ids = _cancel_tasks_for_terminal_status(
            lead.id,
            actor=actor,
            status='do_not_contact',
        )
    elif new_status == 'suppressed':
        lead.recommended_action = None
        cancelled_hubspot_ids = _cancel_tasks_for_terminal_status(
            lead.id,
            actor=actor,
            status='suppressed',
        )
    else:
        cancelled_hubspot_ids: set[str] = set()

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
    _sync_cancelled_hubspot_tasks(cancelled_hubspot_ids)

    if recompute_action and new_status not in ('do_not_contact', 'suppressed'):
        from app.services.lead_refresh import refresh_lead_scoring
        refresh_lead_scoring(lead.id)
