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
from app.services.scoring_rubric import (
    RECENT_SALE_SUPPRESSION_DAYS,
    effective_acquisition_date,
    is_recently_sold,
    sql_not_recently_sold,
)
from app.utils.call_completable_task import is_superseded_by_mail_task

logger = logging.getLogger(__name__)

MAIL_FOLLOW_UP_OFFSET_DAYS = 7
FOLLOW_UP_AFTER_MAIL_TITLE_RE = re.compile(r'follow up after mail', re.IGNORECASE)
SENT_RECENTLY_DAYS = 14


def recent_sale_mail_eligible_date(lead: Lead) -> date | None:
    """Return the first date direct mail is allowed after a recent sale."""
    sale_date = effective_acquisition_date(lead)
    if sale_date is None or not is_recently_sold(lead):
        return None
    return sale_date + timedelta(days=RECENT_SALE_SUPPRESSION_DAYS)


def _is_recent_sale_defer_task(
    lead: Lead,
    task_type: str | None,
    title: str | None,
) -> bool:
    """True for due outreach work that should wait until mail is eligible."""
    if is_mail_follow_up_title(title):
        return False
    if task_type == 'add_to_mail_batch':
        return True
    return (
        lead.recommended_contact_method == 'direct_mail'
        and is_superseded_by_mail_task(task_type, title)
    )


def _append_recent_sale_snooze_timeline(
    lead_id: int,
    *,
    task_id: int,
    task_type: str | None,
    title: str,
    old_due_date: date | None,
    eligible_date: date,
    actor: str,
    hubspot_task_id: str | None = None,
) -> None:
    db.session.add(
        LeadTimelineEntry(
            lead_id=lead_id,
            event_type='task_snoozed',
            occurred_at=datetime.now(timezone.utc),
            source='system',
            actor=actor,
            summary=f'Task deferred after recent sale: {title}',
            event_metadata={
                'task_id': task_id,
                'task_type': task_type,
                'title': title,
                'reason': 'recently_sold',
                'old_due_date': old_due_date.isoformat() if old_due_date else None,
                'due_date': eligible_date.isoformat(),
                'hubspot_task_id': hubspot_task_id,
            },
        ),
    )


def reconcile_recent_sale_mail_tasks_for_lead(
    lead: Lead,
    *,
    actor: str = 'recent_sale_mail_reconciliation',
    commit: bool = False,
) -> dict:
    """Move due direct-mail work to the end of the recent-sale hold.

    LeadTask and CRM Task mirrors are updated as one logical operation. The
    returned HubSpot IDs must be synced only after the surrounding transaction
    commits.
    """
    eligible_date = recent_sale_mail_eligible_date(lead)
    if eligible_date is None:
        return {
            'rescheduled_to': None,
            'rescheduled_task_count': 0,
            'hubspot_task_ids': [],
            'skip_trace_scheduled': False,
            'skip_trace_task_id': None,
            'removed_queue_item_count': 0,
            'changed': False,
        }

    today = date.today()
    from app.services.skip_trace_enqueue import SkipTraceEnqueue

    skip_trace = SkipTraceEnqueue().schedule_recent_sale(
        lead.id,
        due_date=eligible_date,
        actor=actor,
        commit=False,
    )
    queued_items = MailQueueItem.query.filter_by(
        lead_id=lead.id,
        status='queued',
    ).all()
    for item in queued_items:
        item.status = 'removed'
        item.updated_at = datetime.utcnow()
        db.session.add(item)
    if queued_items:
        lead.up_next_to_mail = False
        db.session.add(lead)
        cancel_pending_mail_follow_up_tasks(
            lead.id,
            actor=actor,
            reason='recent_sale_hold',
        )
    due_at = datetime.combine(eligible_date, datetime.min.time())
    represented_crm_ids: set[int] = set()
    represented_hubspot_ids: set[str] = set()
    hubspot_task_ids: set[str] = set()
    rescheduled = 0

    native_tasks = LeadTask.query.filter(
        LeadTask.lead_id == lead.id,
        LeadTask.status == 'open',
        LeadTask.due_date.isnot(None),
        LeadTask.due_date <= today,
    ).all()
    for task in native_tasks:
        if not _is_recent_sale_defer_task(lead, task.task_type, task.title):
            continue
        old_due_date = task.due_date
        task.due_date = eligible_date
        db.session.add(task)
        rescheduled += 1
        if task.mirror_task_id:
            represented_crm_ids.add(task.mirror_task_id)
        if task.hubspot_task_id:
            hs_id = str(task.hubspot_task_id)
            represented_hubspot_ids.add(hs_id)
            hubspot_task_ids.add(hs_id)

        mirrors: list[Task] = []
        if task.mirror_task_id:
            mirror = Task.query.get(task.mirror_task_id)
            if mirror is not None:
                mirrors.append(mirror)
        if task.hubspot_task_id:
            mirror = Task.query.filter_by(
                hubspot_task_id=str(task.hubspot_task_id),
            ).first()
            if mirror is not None and mirror not in mirrors:
                mirrors.append(mirror)
        for mirror in mirrors:
            represented_crm_ids.add(mirror.id)
            mirror.due_date = due_at
            if mirror.status == 'overdue':
                mirror.status = 'open'
            mirror.updated_at = datetime.utcnow()
            db.session.add(mirror)

        _append_recent_sale_snooze_timeline(
            lead.id,
            task_id=task.id,
            task_type=task.task_type,
            title=task.title,
            old_due_date=old_due_date,
            eligible_date=eligible_date,
            actor=actor,
            hubspot_task_id=task.hubspot_task_id,
        )

    for task in _open_hubspot_tasks_for_lead(lead.id) + _open_mirrored_tasks_for_lead(lead.id):
        if task.id in represented_crm_ids:
            continue
        if task.due_date is None or task.due_date.date() > today:
            continue
        hs_id = str(task.hubspot_task_id) if task.hubspot_task_id else None
        if hs_id and hs_id in represented_hubspot_ids:
            continue
        if not _is_recent_sale_defer_task(lead, task.task_type, task.title):
            continue
        old_due_date = task.due_date.date()
        task.due_date = due_at
        if task.status == 'overdue':
            task.status = 'open'
        task.updated_at = datetime.utcnow()
        db.session.add(task)
        rescheduled += 1
        if hs_id:
            represented_hubspot_ids.add(hs_id)
            hubspot_task_ids.add(hs_id)
        _append_recent_sale_snooze_timeline(
            lead.id,
            task_id=task.id,
            task_type=task.task_type,
            title=task.title,
            old_due_date=old_due_date,
            eligible_date=eligible_date,
            actor=actor,
            hubspot_task_id=hs_id,
        )

    if commit:
        db.session.commit()
        if hubspot_task_ids:
            sync_recent_sale_hubspot_due_dates(hubspot_task_ids, eligible_date)

    return {
        'rescheduled_to': eligible_date.isoformat(),
        'rescheduled_task_count': rescheduled,
        'hubspot_task_ids': sorted(hubspot_task_ids),
        'skip_trace_scheduled': skip_trace['scheduled'],
        'skip_trace_task_id': skip_trace['task_id'],
        'removed_queue_item_count': len(queued_items),
        'changed': (
            bool(skip_trace.get('changed'))
            or bool(queued_items)
            or rescheduled > 0
        ),
    }


def sync_recent_sale_hubspot_due_dates(
    hubspot_task_ids: set[str] | list[str],
    eligible_date: date,
) -> dict[str, bool]:
    """Push reconciled due dates to HubSpot after local commit."""
    from app.services.hubspot_task_completion_service import sync_hubspot_task_properties

    return {
        task_id: sync_hubspot_task_properties(task_id, due_date=eligible_date)
        for task_id in sorted(set(hubspot_task_ids))
    }


def adjust_earliest_task_for_recent_sale(
    lead: Lead,
    *,
    actor: str,
    task_id: int | None = None,
    hubspot_task_id: str | None = None,
) -> dict:
    """Move one selected/earliest open task to the recent-sale eligibility date."""
    eligible_date = recent_sale_mail_eligible_date(lead)
    if eligible_date is None:
        raise ValueError('Lead does not have an active recent-sale hold')

    native: LeadTask | None = None
    crm_task: Task | None = None
    selector_requested = task_id is not None or bool(hubspot_task_id)
    if hubspot_task_id:
        native = LeadTask.query.filter_by(
            lead_id=lead.id,
            hubspot_task_id=str(hubspot_task_id),
            status='open',
        ).first()
        if native is None:
            crm_task = Task.query.filter_by(
                lead_id=lead.id,
                hubspot_task_id=str(hubspot_task_id),
            ).filter(Task.status.in_(['open', 'overdue'])).first()
    if native is None and crm_task is None and task_id is not None:
        native = LeadTask.query.filter_by(
            id=task_id,
            lead_id=lead.id,
            status='open',
        ).first()
        if native is None:
            crm_task = Task.query.filter(
                Task.id == task_id,
                Task.lead_id == lead.id,
                Task.status.in_(['open', 'overdue']),
            ).first()

    if native is None and crm_task is None and selector_requested:
        raise ValueError('Selected task is not open or does not belong to this lead')

    if native is None and crm_task is None:
        native = (
            LeadTask.query
            .filter_by(lead_id=lead.id, status='open')
            .order_by(LeadTask.due_date.asc().nullslast(), LeadTask.id.asc())
            .first()
        )
        crm_candidates = (
            _open_hubspot_tasks_for_lead(lead.id)
            + _open_mirrored_tasks_for_lead(lead.id)
        )
        if crm_candidates:
            earliest_crm = min(
                crm_candidates,
                key=lambda task: (
                    task.due_date is None,
                    task.due_date or datetime.max,
                    task.id,
                ),
            )
            native_due = (
                datetime.combine(native.due_date, datetime.min.time())
                if native is not None and native.due_date is not None
                else None
            )
            if native is None or (
                earliest_crm.due_date is not None
                and (native_due is None or earliest_crm.due_date < native_due)
            ):
                native = None
                crm_task = earliest_crm

    if native is None and crm_task is None:
        from app.services.skip_trace_enqueue import SkipTraceEnqueue

        scheduled = SkipTraceEnqueue().schedule_recent_sale(
            lead.id,
            due_date=eligible_date,
            actor=actor,
            commit=False,
        )
        if scheduled['task_id'] is None:
            db.session.rollback()
            raise ValueError('Lead cannot be moved into a recent-sale hold')
        db.session.commit()
        return {
            'task_id': scheduled['task_id'],
            'task_created': True,
            'due_date': eligible_date.isoformat(),
            'title': 'Recent-sale hold ended — verify new owner and contact information',
        }

    hubspot_ids: set[str] = set()
    if native is not None:
        old_due_date = native.due_date
        native.due_date = eligible_date
        db.session.add(native)
        if native.hubspot_task_id:
            hubspot_ids.add(str(native.hubspot_task_id))
        mirrors: list[Task] = []
        if native.mirror_task_id:
            mirror = db.session.get(Task, native.mirror_task_id)
            if mirror is not None:
                mirrors.append(mirror)
        if native.hubspot_task_id:
            mirror = Task.query.filter_by(
                hubspot_task_id=str(native.hubspot_task_id),
            ).first()
            if mirror is not None and mirror not in mirrors:
                mirrors.append(mirror)
        for mirror in mirrors:
            mirror.due_date = datetime.combine(eligible_date, datetime.min.time())
            if mirror.status == 'overdue':
                mirror.status = 'open'
            mirror.updated_at = datetime.utcnow()
            db.session.add(mirror)
        selected_id = native.id
        selected_type = native.task_type
        selected_title = native.title
    else:
        assert crm_task is not None
        old_due_date = crm_task.due_date.date() if crm_task.due_date else None
        crm_task.due_date = datetime.combine(eligible_date, datetime.min.time())
        if crm_task.status == 'overdue':
            crm_task.status = 'open'
        crm_task.updated_at = datetime.utcnow()
        db.session.add(crm_task)
        if crm_task.hubspot_task_id:
            hubspot_ids.add(str(crm_task.hubspot_task_id))
        selected_id = crm_task.id
        selected_type = crm_task.task_type
        selected_title = crm_task.title

    _append_recent_sale_snooze_timeline(
        lead.id,
        task_id=selected_id,
        task_type=selected_type,
        title=selected_title,
        old_due_date=old_due_date,
        eligible_date=eligible_date,
        actor=actor,
        hubspot_task_id=next(iter(hubspot_ids), None),
    )
    db.session.commit()
    if hubspot_ids:
        sync_recent_sale_hubspot_due_dates(hubspot_ids, eligible_date)
    return {
        'task_id': selected_id,
        'task_created': False,
        'due_date': eligible_date.isoformat(),
        'title': selected_title,
    }


def reconcile_recent_sale_mail_tasks(
    *,
    actor: str = 'recent_sale_mail_reconciliation',
    limit: int | None = None,
    commit: bool = True,
) -> dict:
    """Reconcile all due direct-mail work; safe to run repeatedly."""
    terminal_statuses = [
        'deprioritize',
        'deal_won',
        'deal_lost',
        'suppressed',
        'do_not_contact',
    ]
    candidates = (
        Lead.query
        .filter(
            ~sql_not_recently_sold(),
            ~Lead.lead_status.in_(terminal_statuses),
        )
        .with_entities(Lead.id)
        .order_by(Lead.id.asc())
    )
    if limit is not None:
        candidates = candidates.limit(max(limit, 0))
    ordered_ids = [row[0] for row in candidates.all()]

    affected_leads: list[int] = []
    skip_trace_scheduled_count = 0
    task_count = 0
    hubspot_due_dates: dict[str, date] = {}
    results: list[dict] = []

    def record_outcome(lead_id: int, outcome: dict) -> None:
        nonlocal skip_trace_scheduled_count, task_count
        if outcome['changed']:
            affected_leads.append(lead_id)
            task_count += outcome['rescheduled_task_count']
            if outcome['skip_trace_scheduled']:
                skip_trace_scheduled_count += 1
            if commit:
                eligible = date.fromisoformat(outcome['rescheduled_to'])
                for task_id in outcome['hubspot_task_ids']:
                    hubspot_due_dates[task_id] = eligible
            results.append({'lead_id': lead_id, **outcome})

    for lead_id in ordered_ids:
        if commit:
            lead = db.session.get(Lead, lead_id)
            if lead is None:
                continue
            outcome = reconcile_recent_sale_mail_tasks_for_lead(
                lead, actor=actor, commit=False,
            )
            record_outcome(lead_id, outcome)
            continue

        savepoint = db.session.begin_nested()
        try:
            lead = db.session.get(Lead, lead_id)
            if lead is None:
                outcome = None
            else:
                outcome = reconcile_recent_sale_mail_tasks_for_lead(
                    lead, actor=actor, commit=False,
                )
                db.session.flush()
        finally:
            savepoint.rollback()
            db.session.expire_all()
        if outcome is not None:
            record_outcome(lead_id, outcome)

    if commit and affected_leads:
        db.session.commit()
        for task_id, due_date in hubspot_due_dates.items():
            sync_recent_sale_hubspot_due_dates([task_id], due_date)
        refresh_leads_after_mail_task_changes(affected_leads)

    from app.services.skip_trace_enqueue import SkipTraceEnqueue

    activation_limit = (
        None
        if limit is None
        else max(limit - len(ordered_ids), 0)
    )
    if commit:
        activation = SkipTraceEnqueue().activate_due_recent_sale_tasks(
            actor=actor,
            commit=True,
            limit=activation_limit,
        )
    else:
        savepoint = db.session.begin_nested()
        try:
            activation = SkipTraceEnqueue().activate_due_recent_sale_tasks(
                actor=actor,
                commit=False,
                limit=activation_limit,
            )
            db.session.flush()
        finally:
            savepoint.rollback()
            db.session.expire_all()

    return {
        'affected_lead_count': len(affected_leads),
        'skip_trace_scheduled_count': skip_trace_scheduled_count,
        **activation,
        'rescheduled_task_count': task_count,
        'results': results,
    }


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
        if is_mail_follow_up_task(task):
            continue
        if is_superseded_by_mail_task(task.task_type, task.title):
            count += 1
            if task.hubspot_task_id:
                counted_hubspot_ids.add(str(task.hubspot_task_id))
    for task in _open_hubspot_tasks_for_lead(lead_id):
        # Skip CRM Task rows already represented by a LeadTask with same hubspot_task_id
        if task.hubspot_task_id and str(task.hubspot_task_id) in counted_hubspot_ids:
            continue
        if is_mail_follow_up_title(task.title):
            continue
        if is_superseded_by_mail_task(task.task_type, task.title):
            count += 1
    for task in _open_mirrored_tasks_for_lead(lead_id):
        if is_mail_follow_up_title(task.title):
            continue
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
    Never completes follow-up-after-mailer tasks (pending or dated) or their mirrors.
    """
    now = datetime.now(timezone.utc)
    completed = 0
    hubspot_ids_to_sync: list[str] = []
    completed_hubspot_ids: set[str] = set()

    from app.services.hubspot_task_completion_service import mark_hubspot_task_completed_local

    native_tasks = LeadTask.query.filter_by(lead_id=lead_id, status='open').all()
    for task in native_tasks:
        # Keep scheduled post-mailer follow-up (pending until send, or dated after send).
        if is_mail_follow_up_task(task):
            continue
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
        if is_mail_follow_up_title(hs_task.title):
            continue
        if not is_superseded_by_mail_task(hs_task.task_type, hs_task.title):
            continue
        local = mark_hubspot_task_completed_local(
                lead_id,
                hs_task.id,
                actor=actor,
                reason='mail_queued',
                id_namespace='crm_task',
            )
        if local:
            completed += 1
            if local.hubspot_task_id:
                hubspot_ids_to_sync.append(local.hubspot_task_id)
                completed_hubspot_ids.add(str(local.hubspot_task_id))

    mirrored = _open_mirrored_tasks_for_lead(lead_id)
    for mirror in mirrored:
        if is_mail_follow_up_title(mirror.title):
            continue
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


def is_mail_follow_up_title(title: str | None) -> bool:
    """True when the title is the post-mailer call follow-up (pending or dated)."""
    return bool(FOLLOW_UP_AFTER_MAIL_TITLE_RE.search(title or ''))


def is_mail_follow_up_task(task: LeadTask) -> bool:
    """True when the task is the post-mailer call follow-up (pending or dated)."""
    return is_mail_follow_up_title(task.title)


def find_open_mail_follow_up_task(lead_id: int) -> LeadTask | None:
    """Open follow-up-after-mailer task for a lead, if any."""
    for task in LeadTask.query.filter_by(lead_id=lead_id, status='open').all():
        if is_mail_follow_up_task(task):
            return task
    return None


def lead_is_awaiting_mail_batch(lead_id: int) -> bool:
    """True when the lead is staged in the owner's mail batch (or legacy flag).

    Matches Today's Action mail-awaiting exclusion: queued item must belong to
    ``Lead.owner_user_id``.
    """
    lead = Lead.query.get(lead_id)
    if lead is None:
        return False
    if lead.up_next_to_mail:
        return True
    if not lead.owner_user_id:
        return False
    return bool(
        MailQueueItem.query.filter_by(
            lead_id=lead_id,
            status='queued',
            user_id=lead.owner_user_id,
        ).first()
    )


def lead_has_mail_work_in_flight(lead_id: int) -> bool:
    """Queued for mail or has a pending (undated) follow-up-after-mailer task."""
    if lead_is_awaiting_mail_batch(lead_id):
        return True
    pending = find_open_mail_follow_up_task(lead_id)
    return bool(pending and pending.due_date is None)


def _mail_follow_up_title(lead: Lead) -> str:
    return f'Follow up after mailer — {_lead_address_label(lead)}'


def create_pending_mail_follow_up_task(
    lead: Lead,
    actor: str,
) -> LeadTask:
    """Ensure an open follow-up-after-mailer task with due_date=NULL (awaiting send).

    If an open follow-up already exists (pending or dated from a prior send), leave
    it alone — do not clear a scheduled due date.
    """
    existing = find_open_mail_follow_up_task(lead.id)
    if existing is not None:
        return existing

    now = datetime.now(timezone.utc)
    title = _mail_follow_up_title(lead)
    task = LeadTask(  # cancelled if campaign submission fails before send
        lead_id=lead.id,
        task_type='call_owner_today',
        title=title,
        status='open',
        due_date=None,
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
            due_date=None,
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
                'source': 'mail_queued',
                'due_date': None,
            },
        ),
    )
    return task


def cancel_pending_mail_follow_up_tasks(
    lead_id: int,
    actor: str = 'system',
    *,
    reason: str = 'mail_batch_removed',
) -> int:
    """Cancel undated follow-up-after-mailer tasks when mail is no longer in flight."""
    now = datetime.now(timezone.utc)
    cancelled = 0
    for task in LeadTask.query.filter_by(lead_id=lead_id, status='open').all():
        if not is_mail_follow_up_task(task) or task.due_date is not None:
            continue
        task.status = 'cancelled'
        task.completed_at = now
        db.session.add(task)
        cancelled += 1
        for mirror in Task.query.filter_by(
            lead_id=lead_id, status='open', title=task.title,
        ).all():
            mirror.status = 'cancelled'
            mirror.updated_at = now
            db.session.add(mirror)
        db.session.add(
            LeadTimelineEntry(
                lead_id=lead_id,
                event_type='task_completed',
                occurred_at=now,
                source='system',
                actor=actor,
                summary=f'Task cancelled: {task.title}',
                event_metadata={
                    'task_id': task.id,
                    'task_type': task.task_type,
                    'title': task.title,
                    'reason': reason,
                    'status': 'cancelled',
                },
            ),
        )
    return cancelled


def _has_equivalent_dated_mail_follow_up(lead_id: int, due_date: date) -> bool:
    """True when an open call task already has a due date near the mail follow-up."""
    open_tasks = LeadTask.query.filter_by(lead_id=lead_id, status='open').all()
    for task in open_tasks:
        if is_mail_follow_up_task(task):
            continue  # handled by update path
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
    """Set or create a call follow-up task due after assumed mail delivery.

    Prefer updating a pending (undated) follow-up-after-mailer task created at enqueue.
    """
    due_date = sent_at.date() + timedelta(days=offset_days)
    now = datetime.now(timezone.utc)
    title = _mail_follow_up_title(lead)

    existing = find_open_mail_follow_up_task(lead.id)
    if existing is not None:
        old_title = existing.title
        existing.due_date = due_date
        existing.title = title
        db.session.add(existing)
        for mirror in Task.query.filter(
            Task.lead_id == lead.id,
            Task.status.in_(['open', 'overdue']),
        ).all():
            mirror_matches = (
                mirror.title == old_title
                or mirror.title == title
                or (
                    mirror.task_type == 'call_owner_today'
                    and mirror.due_date is None
                    and FOLLOW_UP_AFTER_MAIL_TITLE_RE.search(mirror.title or '')
                )
            )
            if not mirror_matches:
                continue
            mirror.due_date = datetime.combine(due_date, datetime.min.time())
            mirror.title = title
            mirror.updated_at = now
            db.session.add(mirror)
        db.session.add(
            LeadTimelineEntry(
                lead_id=lead.id,
                event_type='task_snoozed',
                occurred_at=now,
                source='system',
                actor=actor,
                summary=f'Task due date set: {title}',
                event_metadata={
                    'task_id': existing.id,
                    'task_type': existing.task_type,
                    'title': title,
                    'source': 'mail_sent',
                    'campaign_id': campaign_id,
                    'due_date': due_date.isoformat(),
                },
            ),
        )
        return existing

    if _has_equivalent_dated_mail_follow_up(lead.id, due_date):
        return None

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


def ensure_due_today_call_task(
    lead: Lead,
    *,
    actor: str = 'system',
    title: str | None = None,
) -> LeadTask | None:
    """Create a due-today call task when urgency has no dated open work.

    Skips when mail work is in flight (queued batch or pending mail follow-up)
    or an open task already has a due date.
    """
    lead_id = lead.id
    if lead_has_mail_work_in_flight(lead_id):
        return None
    if find_open_mail_follow_up_task(lead_id):
        return None
    has_dated = LeadTask.query.filter(
        LeadTask.lead_id == lead_id,
        LeadTask.status == 'open',
        LeadTask.due_date.isnot(None),
    ).first()
    if has_dated is not None:
        return None

    now = datetime.now(timezone.utc)
    today = date.today()
    street = (lead.property_street or '').strip()
    task_title = title or (
        f'Call owner — {street}' if street else f'Call owner — lead {lead_id}'
    )
    task = LeadTask(
        lead_id=lead_id,
        task_type='call_owner_today',
        title=task_title,
        status='open',
        due_date=today,
        created_by=actor,
    )
    db.session.add(task)
    db.session.flush()
    db.session.add(
        Task(
            title=task_title,
            status='open',
            source='manual',
            lead_id=lead_id,
            task_type='call_owner_today',
            due_date=datetime.combine(today, datetime.min.time()),
        ),
    )
    db.session.add(
        LeadTimelineEntry(
            lead_id=lead_id,
            event_type='task_created',
            occurred_at=now,
            source='system',
            actor=actor,
            summary=f'Task created: {task_title}',
            event_metadata={
                'task_id': task.id,
                'task_type': task.task_type,
                'title': task_title,
                'source': 'urgency_scoring',
                'due_date': today.isoformat(),
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
