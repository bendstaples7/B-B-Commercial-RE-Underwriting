"""Task lifecycle hooks for direct-mail queue and send flows."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry, MailQueueItem
from app.models.task import Task
from app.models.task_association import TaskAssociation
from app.utils.call_completable_task import is_superseded_by_mail_task

logger = logging.getLogger(__name__)

MAIL_FOLLOW_UP_OFFSET_DAYS = 7
FOLLOW_UP_AFTER_MAIL_TITLE_RE = re.compile(r'follow up after mail', re.IGNORECASE)
SENT_RECENTLY_DAYS = 14


def _lead_address_label(lead: Lead) -> str:
    street = (lead.property_street or '').strip()
    return street or f'lead {lead.id}'


def _append_native_task_completed_timeline(
    lead_id: int,
    task: LeadTask,
    actor: str,
    now: datetime,
) -> None:
    db.session.add(
        LeadTimelineEntry(
            lead_id=lead_id,
            event_type='task_completed',
            occurred_at=now,
            source='system',
            actor=actor,
            summary=f'Task completed: {task.title}',
            event_metadata={
                'task_id': task.id,
                'task_type': task.task_type,
                'title': task.title,
                'reason': 'mail_queued',
            },
        ),
    )


def _open_hubspot_tasks_for_lead(lead_id: int) -> list[Task]:
    """Open/overdue HubSpot-imported tasks linked to a lead."""
    via_assoc = (
        Task.query.join(TaskAssociation, TaskAssociation.task_id == Task.id)
        .filter(
            TaskAssociation.target_type == 'lead',
            TaskAssociation.target_id == lead_id,
            Task.status.in_(['open', 'overdue']),
            Task.source == 'hubspot_import',
        )
        .all()
    )
    via_direct = Task.query.filter(
        Task.lead_id == lead_id,
        Task.status.in_(['open', 'overdue']),
        Task.source == 'hubspot_import',
    ).all()
    seen: set[int] = set()
    merged: list[Task] = []
    for task in via_assoc + via_direct:
        if task.id not in seen:
            seen.add(task.id)
            merged.append(task)
    return merged


def _complete_native_task_mirror(task: Task, now: datetime) -> None:
    task.status = 'completed'
    task.completion_timestamp = now
    task.updated_at = now
    db.session.add(task)


def _open_mirrored_tasks_for_lead(lead_id: int) -> list[Task]:
    """Open/overdue non-HubSpot Task rows linked to a lead (direct FK or association)."""
    via_assoc = (
        Task.query.join(TaskAssociation, TaskAssociation.task_id == Task.id)
        .filter(
            TaskAssociation.target_type == 'lead',
            TaskAssociation.target_id == lead_id,
            Task.status.in_(['open', 'overdue']),
            Task.source != 'hubspot_import',
        )
        .all()
    )
    via_direct = Task.query.filter(
        Task.lead_id == lead_id,
        Task.status.in_(['open', 'overdue']),
        Task.source != 'hubspot_import',
    ).all()
    seen: set[int] = set()
    merged: list[Task] = []
    for task in via_assoc + via_direct:
        if task.id not in seen:
            seen.add(task.id)
            merged.append(task)
    return merged


def count_superseded_tasks_for_lead(lead_id: int) -> int:
    """Count outreach tasks that would be completed when a lead enters the mail batch."""
    count = 0
    counted_hubspot_ids: set[str] = set()
    for task in LeadTask.query.filter_by(lead_id=lead_id, status='open').all():
        if is_superseded_by_mail_task(task.task_type, task.title):
            count += 1
            if task.hubspot_task_id:
                counted_hubspot_ids.add(str(task.hubspot_task_id))
    for task in _open_hubspot_tasks_for_lead(lead_id):
        # Skip CRM Task rows already represented by a LeadTask with same hubspot_task_id
        if task.hubspot_task_id and str(task.hubspot_task_id) in counted_hubspot_ids:
            continue
        if is_superseded_by_mail_task(task.task_type, task.title):
            count += 1
    for task in _open_mirrored_tasks_for_lead(lead_id):
        if is_superseded_by_mail_task(task.task_type, task.title):
            count += 1
    return count


def complete_tasks_superseded_by_mail(
    lead_id: int,
    actor: str = 'system',
    *,
    commit: bool = False,
) -> tuple[int, list[str]]:
    """Complete outreach tasks superseded when a lead is staged for mail.

    Returns (completed_count, hubspot_task_ids_pending_api_sync).
    """
    now = datetime.now(timezone.utc)
    completed = 0
    hubspot_ids_to_sync: list[str] = []
    completed_hubspot_ids: set[str] = set()

    from app.services.hubspot_task_completion_service import mark_hubspot_task_completed_local

    native_tasks = LeadTask.query.filter_by(lead_id=lead_id, status='open').all()
    for task in native_tasks:
        if not is_superseded_by_mail_task(task.task_type, task.title):
            continue
        if task.hubspot_task_id:
            local = mark_hubspot_task_completed_local(
                lead_id,
                task.id,
                actor=actor,
                reason='mail_queued',
            )
            if local:
                completed += 1
                if local.hubspot_task_id:
                    hubspot_ids_to_sync.append(local.hubspot_task_id)
                    completed_hubspot_ids.add(str(local.hubspot_task_id))
            continue
        task.status = 'completed'
        task.completed_at = now
        db.session.add(task)
        _append_native_task_completed_timeline(lead_id, task, actor, now)
        completed += 1

    hubspot_tasks = _open_hubspot_tasks_for_lead(lead_id)
    for hs_task in hubspot_tasks:
        if hs_task.hubspot_task_id and str(hs_task.hubspot_task_id) in completed_hubspot_ids:
            continue
        if not is_superseded_by_mail_task(hs_task.task_type, hs_task.title):
            continue
        local = mark_hubspot_task_completed_local(
            lead_id,
            hs_task.id,
            actor=actor,
            reason='mail_queued',
        )
        if local:
            completed += 1
            if local.hubspot_task_id:
                hubspot_ids_to_sync.append(local.hubspot_task_id)
                completed_hubspot_ids.add(str(local.hubspot_task_id))

    mirrored = _open_mirrored_tasks_for_lead(lead_id)
    for mirror in mirrored:
        if not is_superseded_by_mail_task(mirror.task_type, mirror.title):
            continue
        _complete_native_task_mirror(mirror, now)
        completed += 1

    if commit and completed:
        db.session.commit()

    return completed, hubspot_ids_to_sync


def complete_mail_prep_tasks(
    lead_id: int,
    actor: str = 'system',
    *,
    commit: bool = False,
) -> int:
    """Complete superseded outreach tasks when a lead is staged for mail.

    Delegates to complete_tasks_superseded_by_mail (native, HubSpot, mirrored).
    """
    count, _pending = complete_tasks_superseded_by_mail(lead_id, actor=actor, commit=commit)
    return count


def find_mail_awaiting_lead_ids() -> list[int]:
    """Lead IDs staged in a mail batch (MailQueueItem queued; legacy up_next_to_mail)."""
    queued_lead_ids = db.session.query(MailQueueItem.lead_id).filter(
        MailQueueItem.status == 'queued',
    ).distinct()
    rows = Lead.query.filter(
        or_(
            Lead.up_next_to_mail.is_(True),  # legacy rows until flag cleared
            Lead.id.in_(queued_lead_ids),
        )
    ).with_entities(Lead.id).all()
    return [row[0] for row in rows]


def _parse_sent_at(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if raw.endswith('Z'):
            raw = raw[:-1] + '+00:00'
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def resolve_mail_queue_status(lead: Lead) -> str | None:
    """Return queued, sent_recently, or None for command-center display.

    Canonical: MailQueueItem membership. Legacy up_next_to_mail still maps to
    queued until stale flags are cleared.
    """
    if lead.owner_user_id and MailQueueItem.query.filter_by(
        lead_id=lead.id,
        status='queued',
        user_id=lead.owner_user_id,
    ).first():
        return 'queued'
    if lead.up_next_to_mail:  # legacy
        return 'queued'

    history = lead.mailer_history
    if not isinstance(history, list) or not history:
        return None

    last_entry = history[-1]
    if not isinstance(last_entry, dict):
        return None

    sent_at = _parse_sent_at(last_entry.get('sent_at'))
    if sent_at is None:
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(days=SENT_RECENTLY_DAYS)
    if sent_at >= cutoff:
        return 'sent_recently'
    return None


def _has_equivalent_mail_follow_up(lead_id: int, due_date: date) -> bool:
    open_tasks = LeadTask.query.filter_by(lead_id=lead_id, status='open').all()
    for task in open_tasks:
        if FOLLOW_UP_AFTER_MAIL_TITLE_RE.search(task.title or ''):
            return True
        if task.task_type == 'call_owner_today' and task.due_date is not None:
            if abs((task.due_date - due_date).days) <= 1:
                return True
    return False


def schedule_mail_follow_up_task(
    lead: Lead,
    sent_at: datetime,
    actor: str,
    *,
    campaign_id: int | None = None,
    offset_days: int = MAIL_FOLLOW_UP_OFFSET_DAYS,
) -> LeadTask | None:
    """Create a call follow-up task due after assumed mail delivery."""
    due_date = sent_at.date() + timedelta(days=offset_days)
    if _has_equivalent_mail_follow_up(lead.id, due_date):
        return None

    now = datetime.now(timezone.utc)
    title = f'Follow up after mailer — {_lead_address_label(lead)}'
    task = LeadTask(
        lead_id=lead.id,
        task_type='call_owner_today',
        title=title,
        status='open',
        due_date=due_date,
        created_by=actor,
    )
    db.session.add(task)
    db.session.flush()

    db.session.add(
        Task(
            title=title,
            status='open',
            source='manual',
            lead_id=lead.id,
            task_type='call_owner_today',
            due_date=datetime.combine(due_date, datetime.min.time()),
        ),
    )
    db.session.add(
        LeadTimelineEntry(
            lead_id=lead.id,
            event_type='task_created',
            occurred_at=now,
            source='system',
            actor=actor,
            summary=f'Task created: {title}',
            event_metadata={
                'task_id': task.id,
                'task_type': task.task_type,
                'title': title,
                'source': 'mail_sent',
                'campaign_id': campaign_id,
                'due_date': due_date.isoformat(),
            },
        ),
    )
    return task


def refresh_leads_after_mail_task_changes(lead_ids: list[int]) -> None:
    """Recompute recommended actions after mail task lifecycle updates."""
    if not lead_ids:
        return
    from app.services.lead_refresh import refresh_lead_scoring

    for lead_id in lead_ids:
        try:
            refresh_lead_scoring(lead_id)
        except Exception as exc:
            logger.error(
                'refresh_lead_scoring failed for lead %s after mail task lifecycle: %s',
                lead_id,
                exc,
                exc_info=True,
            )
