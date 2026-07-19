"""Task lifecycle hooks for direct-mail queue and send flows."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, func, or_

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
from app.utils.call_completable_task import (
    is_call_completable_task,
    is_superseded_by_mail_task,
)
from app.services.lead_task_service import complete_native_task_mirror

logger = logging.getLogger(__name__)

MAIL_FOLLOW_UP_OFFSET_DAYS = 7
FOLLOW_UP_AFTER_MAIL_TITLE_RE = re.compile(r'follow up after mail', re.IGNORECASE)
SENT_RECENTLY_DAYS = 14
RECENT_SALE_RECONCILIATION_BATCH_SIZE = 500


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
    """True for due mail-batch work that should wait until mail is eligible.

    Call / follow-up chores are completed (not snoozed) via
    :func:`complete_obsolete_outreach_during_recent_sale_hold`.
    """
    if is_mail_follow_up_title(title):
        return False
    if (task_type or '').strip() == 'add_to_mail_batch':
        return True
    return (
        lead.recommended_contact_method == 'direct_mail'
        and is_superseded_by_mail_task(task_type, title)
        and not is_call_completable_task(task_type, title)
    )


def _is_obsolete_outreach_during_recent_sale_hold(
    task_type: str | None,
    title: str | None,
) -> bool:
    """True for prior-owner call/follow-up chores that must not stay due on hold."""
    ttype = (task_type or 'custom').strip()
    if ttype == 'skip_trace_owner':
        return False
    if ttype == 'add_to_mail_batch':
        return False
    if is_mail_follow_up_title(title):
        return False
    return (
        is_call_completable_task(task_type, title)
        or is_superseded_by_mail_task(task_type, title)
    )


def complete_obsolete_outreach_during_recent_sale_hold(
    lead_id: int,
    *,
    actor: str = 'recent_sale_hold',
    commit: bool = False,
) -> list[int]:
    """Complete open dated call/follow-up tasks while a recent-sale hold is active.

    Keeps Today's Action clear during Skip Trace Hold — prior-owner outreach is
    obsolete until the hold ends / new owner is confirmed. Does not touch
    ``skip_trace_owner`` hold/handoff tasks or post-mailer follow-ups.
    """
    tasks = (
        LeadTask.query
        .filter(
            LeadTask.lead_id == lead_id,
            LeadTask.status == 'open',
            LeadTask.due_date.isnot(None),
        )
        .order_by(LeadTask.id.asc())
        .all()
    )
    now = datetime.now(timezone.utc)
    completed_ids: list[int] = []
    for task in tasks:
        if not _is_obsolete_outreach_during_recent_sale_hold(task.task_type, task.title):
            continue
        task.status = 'completed'
        task.completed_at = now
        complete_native_task_mirror(task, now)
        db.session.add(task)
        db.session.add(LeadTimelineEntry(
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
                'reason': 'recent_sale_hold_obsolete_outreach',
            },
        ))
        completed_ids.append(task.id)
    if commit and completed_ids:
        db.session.commit()
    return completed_ids


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
    completed_outreach_ids = list(
        skip_trace.get('completed_obsolete_outreach_ids') or [],
    )
    for task_id in complete_obsolete_outreach_during_recent_sale_hold(
        lead.id,
        actor=actor,
        commit=False,
    ):
        if task_id not in completed_outreach_ids:
            completed_outreach_ids.append(task_id)
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
    hubspot_task_ids: set[str] = set(skip_trace.get('hubspot_task_ids', []))
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
            if mirror.hubspot_task_id:
                hubspot_task_ids.add(str(mirror.hubspot_task_id))

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

    # CRM ``tasks`` are write-through mirrors only — do not discover open work
    # from HubSpot/mirrored rows that lack a LeadTask.

    if commit:
        db.session.commit()
        if hubspot_task_ids:
            sync_recent_sale_hubspot_due_dates(hubspot_task_ids, eligible_date)

    return {
        'rescheduled_to': eligible_date.isoformat(),
        'rescheduled_task_count': rescheduled,
        'completed_obsolete_outreach_ids': completed_outreach_ids,
        'hubspot_task_ids': sorted(hubspot_task_ids),
        'skip_trace_scheduled': skip_trace['scheduled'],
        'skip_trace_task_id': skip_trace['task_id'],
        'removed_queue_item_count': len(queued_items),
        'changed': (
            bool(skip_trace.get('changed'))
            or bool(queued_items)
            or rescheduled > 0
            or bool(completed_outreach_ids)
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
        # LeadTask is the sole source of truth for open next actions.
        native = (
            LeadTask.query
            .filter_by(lead_id=lead.id, status='open')
            .order_by(LeadTask.due_date.asc().nullslast(), LeadTask.id.asc())
            .first()
        )

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
        if scheduled.get('hubspot_task_ids'):
            sync_recent_sale_hubspot_due_dates(
                scheduled['hubspot_task_ids'],
                eligible_date,
            )
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
            if mirror.hubspot_task_id:
                hubspot_ids.add(str(mirror.hubspot_task_id))
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
    effective_limit = (
        RECENT_SALE_RECONCILIATION_BATCH_SIZE
        if limit is None
        else max(limit, 0)
    )
    from app.services.skip_trace_enqueue import SkipTraceEnqueue

    if commit:
        activation = SkipTraceEnqueue().activate_due_recent_sale_tasks(
            actor=actor,
            commit=True,
            limit=effective_limit,
        )
    else:
        savepoint = db.session.begin_nested()
        try:
            activation = SkipTraceEnqueue().activate_due_recent_sale_tasks(
                actor=actor,
                commit=False,
                limit=effective_limit,
            )
            db.session.flush()
        finally:
            savepoint.rollback()
            db.session.expire_all()

    remaining_limit = max(
        effective_limit - activation.get('processed_task_count', 0),
        0,
    )
    terminal_statuses = [
        'deprioritize',
        'deal_won',
        'deal_lost',
        'suppressed',
        'do_not_contact',
    ]
    ordered_ids: list[int] = []
    activation_processed_ids = set(activation.get('processed_lead_ids', []))
    if remaining_limit:
        candidates = Lead.query.filter(
            ~sql_not_recently_sold(),
            ~Lead.lead_status.in_(terminal_statuses),
        )
        if activation_processed_ids:
            candidates = candidates.filter(~Lead.id.in_(activation_processed_ids))
        candidates = (
            candidates
            .with_entities(Lead.id)
            .order_by(Lead.id.asc())
            .limit(remaining_limit)
        )
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

    all_affected_leads = list(dict.fromkeys(
        activation.get('activated_lead_ids', []) + affected_leads
    ))
    return {
        **activation,
        'affected_lead_count': len(all_affected_leads),
        'affected_lead_ids': all_affected_leads,
        'processed_lead_ids': list(dict.fromkeys(
            activation.get('processed_lead_ids', []) + ordered_ids
        )),
        'skip_trace_scheduled_count': skip_trace_scheduled_count,
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
    """Count canonical and orphan mirrored outreach tasks superseded by mail."""
    count = 0
    for task in LeadTask.query.filter_by(lead_id=lead_id, status='open').all():
        if is_mail_follow_up_task(task):
            continue
        if is_superseded_by_mail_task(task.task_type, task.title):
            count += 1
    count += len(_orphan_superseded_crm_tasks(lead_id))
    return count


def _orphan_superseded_crm_tasks(lead_id: int) -> list[Task]:
    """CRM mirrors still open without a corresponding canonical LeadTask.

    Batches association and LeadTask lookups so mail-awaiting scans do not
    issue two queries per candidate task.
    """
    candidates = _open_hubspot_tasks_for_lead(lead_id) + _open_mirrored_tasks_for_lead(lead_id)
    seen: set[int] = set()
    tasks: list[Task] = []
    for task in candidates:
        if task.id in seen:
            continue
        seen.add(task.id)
        tasks.append(task)
    if not tasks:
        return []

    task_ids = [task.id for task in tasks]
    hs_ids = [str(task.hubspot_task_id) for task in tasks if task.hubspot_task_id]

    canonical_filters = [LeadTask.mirror_task_id.in_(task_ids)]
    if hs_ids:
        canonical_filters.append(LeadTask.hubspot_task_id.in_(hs_ids))
    canonical_rows = LeadTask.query.filter(
        LeadTask.lead_id == lead_id,
        or_(*canonical_filters),
    ).all()
    canonical_mirror_ids = {
        row.mirror_task_id for row in canonical_rows if row.mirror_task_id is not None
    }
    canonical_hs_ids = {
        str(row.hubspot_task_id) for row in canonical_rows if row.hubspot_task_id
    }

    assoc_rows = TaskAssociation.query.filter(
        TaskAssociation.task_id.in_(task_ids),
        TaskAssociation.target_type == 'lead',
    ).all()
    linked_leads_by_task: dict[int, set[int]] = {task_id: set() for task_id in task_ids}
    for row in assoc_rows:
        linked_leads_by_task[int(row.task_id)].add(int(row.target_id))
    for task in tasks:
        if task.lead_id is not None:
            linked_leads_by_task[task.id].add(int(task.lead_id))

    all_linked_lead_ids: set[int] = set()
    for lead_ids in linked_leads_by_task.values():
        all_linked_lead_ids.update(lead_ids)

    protected_hs_ids: set[str] = set()
    protected_mirror_ids: set[int] = set()
    if all_linked_lead_ids:
        open_filters = [LeadTask.mirror_task_id.in_(task_ids)]
        if hs_ids:
            open_filters.append(LeadTask.hubspot_task_id.in_(hs_ids))
        for row in LeadTask.query.filter(
            LeadTask.lead_id.in_(all_linked_lead_ids),
            LeadTask.status == 'open',
            or_(*open_filters),
        ).all():
            if row.hubspot_task_id:
                protected_hs_ids.add(str(row.hubspot_task_id))
            if row.mirror_task_id is not None:
                protected_mirror_ids.add(row.mirror_task_id)

    result: list[Task] = []
    for task in tasks:
        hs_id = str(task.hubspot_task_id) if task.hubspot_task_id else None
        if task.id in canonical_mirror_ids or (hs_id and hs_id in canonical_hs_ids):
            continue
        if (hs_id and hs_id in protected_hs_ids) or task.id in protected_mirror_ids:
            continue
        if is_mail_follow_up_task(task):
            continue
        if is_superseded_by_mail_task(task.task_type, task.title):
            result.append(task)
    return result


def _crm_task_has_open_canonical_on_linked_leads(task: Task) -> bool:
    """True when any linked lead still has an open canonical LeadTask for this mirror.

    Prefer ``_orphan_superseded_crm_tasks`` for batch paths; this remains for
    single-task checks.
    """
    from app.models import LeadTask

    lead_ids: set[int] = set()
    if task.lead_id is not None:
        lead_ids.add(int(task.lead_id))
    for row in TaskAssociation.query.filter_by(
        task_id=task.id,
        target_type='lead',
    ).all():
        lead_ids.add(int(row.target_id))
    if not lead_ids:
        return False
    query = LeadTask.query.filter(
        LeadTask.lead_id.in_(lead_ids),
        LeadTask.status == 'open',
    )
    if task.hubspot_task_id:
        query = query.filter(LeadTask.hubspot_task_id == str(task.hubspot_task_id))
    else:
        query = query.filter(LeadTask.mirror_task_id == task.id)
    return query.first() is not None


def complete_tasks_superseded_by_mail(
    lead_id: int,
    actor: str = 'system',
    *,
    commit: bool = False,
) -> tuple[int, list[str]]:
    """Complete outreach LeadTasks superseded when a lead is staged for mail.

    Returns (completed_count, hubspot_task_ids_pending_api_sync).
    Never completes follow-up-after-mailer tasks (pending or dated) or their mirrors.
    CRM ``tasks`` rows are write-through mirrors; orphan mirrors are swept so
    stale imported work cannot remain open after canonical mail staging.
    """
    now = datetime.now(timezone.utc)
    completed = 0
    hubspot_ids_to_sync: list[str] = []

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
            continue
        task.status = 'completed'
        task.completed_at = now
        db.session.add(task)
        complete_native_task_mirror(task, now)
        _append_native_task_completed_timeline(lead_id, task, actor, now)
        completed += 1

    for task in _orphan_superseded_crm_tasks(lead_id):
        _complete_native_task_mirror(task, now)
        completed += 1
        if task.hubspot_task_id:
            hubspot_ids_to_sync.append(str(task.hubspot_task_id))

    if commit and completed:
        db.session.commit()
        from app.services.next_action_invariant import ensure_next_action_after_task_change
        ensure_next_action_after_task_change(lead_id)

    return completed, hubspot_ids_to_sync


def complete_mail_prep_tasks(
    lead_id: int,
    actor: str = 'system',
    *,
    commit: bool = False,
) -> int:
    """Complete superseded outreach tasks when a lead is staged for mail.

    Delegates to canonical LeadTask completion plus orphan CRM-mirror cleanup.
    """
    count, _pending = complete_tasks_superseded_by_mail(lead_id, actor=actor, commit=commit)
    return count


def _sql_maybe_superseded_task(task_model):
    """Broad SQL prefilter for the canonical Python superseded-task rule."""
    task_type = func.coalesce(task_model.task_type, 'custom')
    title = func.lower(func.coalesce(task_model.title, ''))
    positive_title = or_(
        title.like('%call%'),
        title.like('%phone%'),
        title.like('%voicemail%'),
        title.like('%follow up%'),
        title.like('%follow-up%'),
        title.like('%followup%'),
    )
    excluded_title = or_(
        title.like('%email%'),
        title.like('%e-mail%'),
        title.like('%mail%'),
        title.like('%letter%'),
    )
    return or_(
        task_type.in_(('add_to_mail_batch', 'call_owner_today')),
        and_(
            ~task_type.in_((
                'research_missing_pin',
                'match_hubspot_deal',
                'run_property_analysis',
                'skip_trace_owner',
            )),
            positive_title,
            ~excluded_title,
        ),
    )


def find_mail_awaiting_lead_ids(
    *,
    limit: int | None = None,
    exclude_lead_ids: set[int] | None = None,
    require_superseded_tasks: bool = False,
) -> list[int]:
    """Return a bounded batch staged in mail, optionally excluding prior work."""
    queued_lead_ids = db.session.query(MailQueueItem.lead_id).filter(
        MailQueueItem.status == 'queued',
    ).distinct()
    query = Lead.query.filter(
        or_(
            Lead.up_next_to_mail.is_(True),  # legacy rows until flag cleared
            Lead.id.in_(queued_lead_ids),
        )
    )
    if exclude_lead_ids:
        query = query.filter(~Lead.id.in_(exclude_lead_ids))
    query = query.with_entities(Lead.id).order_by(Lead.id.asc())
    if not require_superseded_tasks:
        if limit is not None:
            query = query.limit(max(limit, 0))
        return [row[0] for row in query.all()]

    native_exists = db.session.query(LeadTask.id).filter(
        LeadTask.lead_id == Lead.id,
        LeadTask.status == 'open',
        _sql_maybe_superseded_task(LeadTask),
    ).exists()
    direct_crm_exists = db.session.query(Task.id).filter(
        Task.lead_id == Lead.id,
        Task.status.in_(('open', 'overdue')),
        _sql_maybe_superseded_task(Task),
    ).exists()
    associated_crm_exists = (
        db.session.query(Task.id)
        .join(TaskAssociation, TaskAssociation.task_id == Task.id)
        .filter(
            TaskAssociation.target_type == 'lead',
            TaskAssociation.target_id == Lead.id,
            Task.status.in_(('open', 'overdue')),
            _sql_maybe_superseded_task(Task),
        )
        .exists()
    )
    query = query.filter(or_(
        native_exists,
        direct_crm_exists,
        associated_crm_exists,
    ))

    target = None if limit is None else max(limit, 0)
    if target == 0:
        return []
    batch_size = max((target or 100) * 4, 100)
    offset = 0
    matched: list[int] = []
    while target is None or len(matched) < target:
        rows = query.limit(batch_size).offset(offset).all()
        if not rows:
            break
        for row in rows:
            if count_superseded_tasks_for_lead(row[0]) <= 0:
                continue
            matched.append(row[0])
            if target is not None and len(matched) >= target:
                break
        if len(rows) < batch_size:
            break
        offset += batch_size
    return matched


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
