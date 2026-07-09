"""Task lifecycle hooks for direct-mail queue and send flows."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry, MailQueueItem
from app.models.task import Task

logger = logging.getLogger(__name__)

MAIL_FOLLOW_UP_OFFSET_DAYS = 7
FOLLOW_UP_AFTER_MAIL_TITLE_RE = re.compile(r'follow up after mail', re.IGNORECASE)
SENT_RECENTLY_DAYS = 14


def _lead_address_label(lead: Lead) -> str:
    street = (lead.property_street or '').strip()
    return street or f'lead {lead.id}'


def complete_mail_prep_tasks(
    lead_id: int,
    actor: str = 'system',
    *,
    commit: bool = False,
) -> int:
    """Complete open add_to_mail_batch tasks when a lead is staged for mail."""
    now = datetime.now(timezone.utc)
    tasks = LeadTask.query.filter(
        LeadTask.lead_id == lead_id,
        LeadTask.task_type == 'add_to_mail_batch',
        LeadTask.status == 'open',
    ).all()

    completed = 0
    for task in tasks:
        task.status = 'completed'
        task.completed_at = now
        db.session.add(task)
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
        completed += 1

    if completed:
        Task.query.filter(
            Task.lead_id == lead_id,
            Task.task_type == 'add_to_mail_batch',
            Task.status.in_(['open', 'overdue']),
        ).update(
            {
                'status': 'completed',
                'completion_timestamp': now,
                'updated_at': now,
            },
            synchronize_session=False,
        )

    if commit and completed:
        db.session.commit()

    return completed


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
    """Return queued, sent_recently, or None for command-center display."""
    if lead.owner_user_id and MailQueueItem.query.filter_by(
        lead_id=lead.id,
        status='queued',
        user_id=lead.owner_user_id,
    ).first():
        return 'queued'
    if lead.up_next_to_mail:
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
