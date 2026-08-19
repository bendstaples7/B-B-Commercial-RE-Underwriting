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
            if (
                mirror is not None
                and mirror.lead_id == lead_id
                and mirror.hubspot_task_id
            ):
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


def lead_has_active_outreach_work(lead_id: int) -> bool:
    """True when the lead has queued mail or an open call/follow-up/mail task."""
    from app.models.mail_queue_item import MailQueueItem
    from app.utils.call_completable_task import (
        is_call_completable_task,
        is_legacy_entity_research_task,
    )

    queued = MailQueueItem.query.filter_by(lead_id=lead_id, status='queued').first()
    if queued is not None:
        return True
    open_tasks = LeadTask.query.filter_by(lead_id=lead_id, status='open').all()
    for task in open_tasks:
        if is_legacy_entity_research_task(task.task_type, task.title):
            continue
        if task.task_type == 'add_to_mail_batch':
            return True
        if is_call_completable_task(task.task_type, task.title):
            return True
    return False


def mailing_status_for_unpark(lead_id: int) -> str:
    """Mailing stage after unparking: contacted if a call/email already happened."""
    contact_row = (
        LeadTimelineEntry.query.filter(
            LeadTimelineEntry.lead_id == lead_id,
            LeadTimelineEntry.event_type.in_(
                ('call_logged', 'hubspot_call', 'email_logged'),
            ),
            LeadTimelineEntry.is_deleted.is_(False),
        )
        .first()
    )
    if contact_row is not None:
        return 'mailing_contacted_no_interest'
    return 'mailing_no_contact_made'


def _has_manual_deprioritize(lead_id: int) -> bool:
    rows = (
        LeadTimelineEntry.query.filter(
            LeadTimelineEntry.lead_id == lead_id,
            LeadTimelineEntry.event_type == 'status_changed',
            LeadTimelineEntry.source == 'manual',
            LeadTimelineEntry.is_deleted.is_(False),
        )
        .all()
    )
    for row in rows:
        meta = row.event_metadata or {}
        if meta.get('new_status') == 'deprioritize':
            return True
    return False


def unpark_deprioritize_for_active_work(
    lead: Lead,
    *,
    actor: str,
    reason: str,
    source: str = 'system',
    commit: bool = True,
    recompute_action: bool = True,
    push_hubspot: bool = False,
) -> bool:
    """Move a parked working lead back onto a mailing status. Returns True if changed."""
    if lead.lead_status != 'deprioritize':
        return False
    new_status = mailing_status_for_unpark(lead.id)
    apply_lead_status_change(
        lead,
        new_status,
        reason=reason,
        actor=actor,
        source=source,
        recompute_action=recompute_action,
        commit=commit,
    )
    if push_hubspot:
        try:
            from app.services.hubspot_writeback_service import (
                HubSpotWriteBackService,
                hubspot_write_back_enabled,
            )
            if hubspot_write_back_enabled():
                HubSpotWriteBackService().push_deal_stage_for_lead(lead.id, new_status)
        except Exception as exc:  # noqa: BLE001 — unpark must not fail on CRM
            logger.warning(
                'HubSpot stage push failed after unpark lead_id=%s: %s',
                lead.id, exc, exc_info=True,
            )
    return True


def heal_working_deprioritize_leads(
    *,
    commit: bool = True,
    push_hubspot: bool = False,
    recompute_action: bool = True,
) -> int:
    """Unpark deprioritize leads that still have follow-up or mail work."""
    from datetime import date

    from app.models.mail_queue_item import MailQueueItem
    from app.utils.call_completable_task import (
        is_call_completable_task,
        is_legacy_entity_research_task,
    )

    today = date.today()
    parked = Lead.query.filter_by(lead_status='deprioritize').all()
    healed = 0
    for lead in parked:
        if _has_manual_deprioritize(lead.id):
            continue
        queued = MailQueueItem.query.filter_by(
            lead_id=lead.id, status='queued',
        ).first()
        overdue_work = False
        if queued is None:
            open_tasks = LeadTask.query.filter_by(lead_id=lead.id, status='open').all()
            for task in open_tasks:
                if is_legacy_entity_research_task(task.task_type, task.title):
                    continue
                is_mail_follow = task.task_type == 'add_to_mail_batch'
                is_call = is_call_completable_task(task.task_type, task.title)
                if not is_mail_follow and not is_call:
                    continue
                due = task.due_date
                if is_mail_follow or due is None or due <= today:
                    overdue_work = True
                    break
        if queued is None and not overdue_work:
            continue
        if unpark_deprioritize_for_active_work(
            lead,
            actor='System',
            reason=(
                'Restored from HubSpot Deprioritize because follow-up or mail '
                'work is still open'
            ),
            source='system',
            commit=False,
            recompute_action=recompute_action,
            push_hubspot=push_hubspot,
        ):
            healed += 1
    if commit:
        db.session.commit()
    return healed


def apply_lead_status_change(
    lead: Lead,
    new_status: str,
    *,
    reason: str = '',
    actor: str = 'anonymous',
    source: str = 'manual',
    recompute_action: bool = True,
    commit: bool = True,
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
        source=source if source in ('manual', 'system', 'hubspot') else 'system',
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
    if commit:
        db.session.commit()
        _sync_cancelled_hubspot_tasks(cancelled_hubspot_ids)
    elif cancelled_hubspot_ids:
        # Caller owns the transaction; sync after they commit.
        pass

    if recompute_action and new_status not in ('do_not_contact', 'suppressed'):
        from app.services.lead_refresh import refresh_lead_scoring
        refresh_lead_scoring(lead.id)
