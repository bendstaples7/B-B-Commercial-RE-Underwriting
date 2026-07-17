"""Complete HubSpot-imported tasks locally with best-effort HubSpot API sync.

Canonical local store is ``LeadTask`` (keyed by ``hubspot_task_id``). The
parallel CRM ``tasks`` row is updated when present so queue/association
consumers stay consistent until they migrate fully to LeadTask.
"""
from __future__ import annotations

import logging
from hashlib import sha1
from dataclasses import dataclass
from datetime import datetime, time, timezone

from app import db
from app.models import LeadTask, LeadTimelineEntry
from app.models.task import Task

logger = logging.getLogger(__name__)


@dataclass
class HubSpotCompletionResult:
    completed: bool
    hubspot_task_id: str | None = None
    hubspot_synced: bool = False


@dataclass
class HubSpotTaskLocalCompletion:
    task_id: int
    title: str
    hubspot_task_id: str | None


def _complete_crm_task_by_hubspot_id(hubspot_task_id: str, now: datetime) -> None:
    """Best-effort mirror completion onto the parallel CRM ``tasks`` row."""
    if not hubspot_task_id:
        return
    crm_task = Task.query.filter_by(hubspot_task_id=str(hubspot_task_id)).first()
    if crm_task is None:
        return
    if crm_task.status in ('open', 'overdue'):
        crm_task.status = 'completed'
        crm_task.completion_timestamp = now
        crm_task.updated_at = now
        db.session.add(crm_task)


def _complete_legacy_crm_task(
    lead_id: int,
    task_id: int,
    now: datetime,
) -> HubSpotTaskLocalCompletion | None:
    """Complete by CRM ``tasks.id`` (legacy ``hs-{id}`` clients)."""
    from sqlalchemy import text as sa_text

    result = db.session.execute(
        sa_text("""
            UPDATE tasks
            SET status = 'completed',
                updated_at = :now,
                completion_timestamp = :now
            WHERE id = :task_id
              AND status IN ('open', 'overdue')
              AND source = 'hubspot_import'
              AND (
                lead_id = :lead_id
                OR EXISTS (
                    SELECT 1 FROM task_associations ta
                    WHERE ta.task_id = tasks.id
                      AND ta.target_type = 'lead'
                      AND ta.target_id = :lead_id
                )
              )
            RETURNING id, title, hubspot_task_id
        """),
        {'task_id': task_id, 'lead_id': lead_id, 'now': now},
    ).fetchone()

    if result is None:
        return None

    hs_id = result[2]
    if hs_id:
        lt = LeadTask.query.filter_by(hubspot_task_id=str(hs_id), lead_id=lead_id).first()
        if lt is not None and lt.status == 'open':
            lt.status = 'completed'
            lt.completed_at = now
            db.session.add(lt)

    return HubSpotTaskLocalCompletion(
        task_id=result[0],
        title=result[1],
        hubspot_task_id=hs_id,
    )


def _crm_task_linked_to_lead(crm_task: Task, lead_id: int) -> bool:
    if crm_task.lead_id == lead_id:
        return True
    from app.models.task_association import TaskAssociation
    return (
        TaskAssociation.query.filter_by(
            task_id=crm_task.id,
            target_type='lead',
            target_id=lead_id,
        ).first()
        is not None
    )


def _complete_lead_task_by_id(
    lead_id: int,
    task_id: int,
    now: datetime,
) -> HubSpotTaskLocalCompletion | None:
    """Atomically complete an open HubSpot-linked LeadTask by id.

    Uses ``UPDATE ... WHERE status='open' RETURNING`` so concurrent completers
    cannot both succeed (avoids duplicate timeline / HubSpot sync).
    """
    from sqlalchemy import text as sa_text

    result = db.session.execute(
        sa_text("""
            UPDATE lead_tasks
            SET status = 'completed',
                completed_at = :now
            WHERE id = :task_id
              AND lead_id = :lead_id
              AND status = 'open'
              AND hubspot_task_id IS NOT NULL
            RETURNING id, title, hubspot_task_id
        """),
        {'task_id': task_id, 'lead_id': lead_id, 'now': now},
    ).fetchone()

    if result is None:
        return None

    hs_id = result[2]
    _complete_crm_task_by_hubspot_id(hs_id, now)
    return HubSpotTaskLocalCompletion(
        task_id=result[0],
        title=result[1],
        hubspot_task_id=hs_id,
    )


def _update_hubspot_task_completed(
    lead_id: int,
    task_id: int,
    *,
    id_namespace: str = 'lead_task',
) -> HubSpotTaskLocalCompletion | None:
    """Complete a HubSpot-linked task for a lead.

    ``id_namespace`` must be ``lead_task`` (Command Center / LeadTask PK) or
    ``crm_task`` (legacy CRM ``tasks.id`` / ``hs-{id}``). The two tables use
    independent sequences, so the caller must disambiguate.
    """
    now = datetime.now(timezone.utc)
    namespace = (id_namespace or 'lead_task').strip().lower()
    if namespace not in ('lead_task', 'crm_task'):
        namespace = 'lead_task'

    if namespace == 'crm_task':
        crm_match = Task.query.filter_by(id=task_id, source='hubspot_import').first()
        if crm_match is None or not _crm_task_linked_to_lead(crm_match, lead_id):
            return None
        return _complete_legacy_crm_task(lead_id, task_id, now)

    return _complete_lead_task_by_id(lead_id, task_id, now)


def _append_hubspot_task_timeline(
    lead_id: int,
    local: HubSpotTaskLocalCompletion,
    actor: str,
    *,
    hubspot_synced: bool,
    reason: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    if hubspot_synced:
        summary = f'HubSpot task completed: {local.title}'
        metadata_note = 'Marked done in HubSpot and locally'
    elif reason == 'mail_queued':
        summary = f'HubSpot task marked done locally: {local.title} (HubSpot sync pending)'
        metadata_note = 'Local completion — HubSpot sync pending after mail queue'
    elif local.hubspot_task_id:
        summary = f'HubSpot task marked done locally: {local.title} (HubSpot sync failed)'
        metadata_note = 'Local only — HubSpot sync failed'
    else:
        summary = f'HubSpot task marked done locally: {local.title}'
        metadata_note = 'Marked done locally — no HubSpot config'

    metadata = {
        'task_id': local.task_id,
        'hubspot_task_id': local.hubspot_task_id,
        'title': local.title,
        'hubspot_synced': hubspot_synced,
        'note': metadata_note,
    }
    if reason:
        metadata['reason'] = reason

    db.session.add(
        LeadTimelineEntry(
            lead_id=lead_id,
            event_type='task_completed',
            occurred_at=now,
            source='system' if reason == 'mail_queued' else 'manual',
            actor=actor,
            summary=summary,
            event_metadata=metadata,
        ),
    )


def mark_hubspot_task_completed_local(
    lead_id: int,
    task_id: int,
    actor: str = 'system',
    *,
    reason: str | None = None,
    id_namespace: str = 'lead_task',
) -> HubSpotTaskLocalCompletion | None:
    """Mark a HubSpot task completed in the current session without committing."""
    local = _update_hubspot_task_completed(
        lead_id, task_id, id_namespace=id_namespace,
    )
    if local is None:
        return None

    _append_hubspot_task_timeline(
        lead_id,
        local,
        actor,
        hubspot_synced=False,
        reason=reason,
    )
    return local


def sync_hubspot_task_to_hubspot(hubspot_task_id: str) -> bool:
    """Best-effort HubSpot API sync after local completion is committed."""
    try:
        from app.models.hubspot_config import HubSpotConfig
        from app.services.hubspot_client_service import HubSpotClientService

        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if not config:
            return False
        HubSpotClientService(config).complete_task(hubspot_task_id)
        logger.info('HubSpot task %s marked COMPLETED via API', hubspot_task_id)
        return True
    except Exception as exc:
        logger.warning(
            'Failed to mark HubSpot task %s as completed via API: %s',
            hubspot_task_id,
            exc,
        )
        return False


def _record_task_platform_write(hubspot_task_id: str) -> int:
    """Record outbound task write so webhook loop guard can suppress echo."""
    from app.models.hubspot_platform_write import HubSpotPlatformWrite

    write = HubSpotPlatformWrite(
        object_type='task',
        hubspot_id=str(hubspot_task_id),
    )
    db.session.add(write)
    db.session.commit()
    return write.id


def sync_hubspot_task_properties(
    hubspot_task_id: str,
    *,
    title: str | None = None,
    due_date=None,
    clear_due_date: bool = False,
) -> bool:
    """Best-effort push of title/due_date to HubSpot; records platform write on success.

    Local edits always win in the UI — callers should treat False as non-fatal.
    """
    if not hubspot_task_id:
        return False
    if title is None and due_date is None and not clear_due_date:
        return False
    try:
        from app.models.hubspot_config import HubSpotConfig
        from app.services.hubspot_client_service import HubSpotClientService

        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if not config:
            return False
        _record_task_platform_write(str(hubspot_task_id))
        HubSpotClientService(config).update_task(
            str(hubspot_task_id),
            subject=title,
            due_date=None if clear_due_date else due_date,
            clear_due_date=clear_due_date,
        )
        logger.info(
            'HubSpot task %s properties updated via API (title=%s due=%s clear=%s)',
            hubspot_task_id,
            title is not None,
            due_date is not None,
            clear_due_date,
        )
        return True
    except Exception as exc:
        db.session.rollback()
        logger.warning(
            'Failed to update HubSpot task %s properties via API: %s',
            hubspot_task_id,
            exc,
        )
        return False


def mirror_crm_task_from_lead_task(
    lead_task,
    hubspot_task_ids_to_sync: set[str] | None = None,
) -> bool:
    """Keep parallel CRM ``tasks`` row in sync when present (best-effort)."""
    crm_task = None
    mirror_task_id = getattr(lead_task, 'mirror_task_id', None)
    if mirror_task_id is not None:
        candidate = db.session.get(Task, mirror_task_id)
        if candidate is not None and _crm_task_linked_to_lead(
            candidate,
            lead_task.lead_id,
        ):
            crm_task = candidate
    if crm_task is None:
        hs_id = getattr(lead_task, 'hubspot_task_id', None)
        if not hs_id:
            return False
        for candidate in Task.query.filter_by(hubspot_task_id=str(hs_id)).all():
            if _crm_task_linked_to_lead(candidate, lead_task.lead_id):
                crm_task = candidate
                break
    if crm_task is None:
        return False
    expected_due = (
        None
        if lead_task.due_date is None
        else datetime.combine(lead_task.due_date, time(13, 0, 0))
    )
    changed = (
        crm_task.title != lead_task.title
        or crm_task.due_date != expected_due
    )
    if not changed:
        return False
    crm_task.title = lead_task.title
    crm_task.due_date = expected_due
    crm_task.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.add(crm_task)
    if hubspot_task_ids_to_sync is not None and crm_task.hubspot_task_id:
        hubspot_task_ids_to_sync.add(str(crm_task.hubspot_task_id))
    return True


def sync_pending_hubspot_completions(hubspot_task_ids: list[str]) -> None:
    """Sync HubSpot tasks after a surrounding transaction has committed."""
    for hubspot_task_id in hubspot_task_ids:
        if hubspot_task_id:
            sync_hubspot_task_to_hubspot(hubspot_task_id)


def complete_hubspot_task(
    lead_id: int,
    task_id: int,
    actor: str = 'system',
    *,
    reason: str | None = None,
    skip_scoring_refresh: bool = False,
    id_namespace: str = 'lead_task',
) -> HubSpotCompletionResult:
    """Mark a HubSpot-imported task completed locally; sync to HubSpot when possible."""
    local = _update_hubspot_task_completed(
        lead_id, task_id, id_namespace=id_namespace,
    )
    if local is None:
        db.session.rollback()
        return HubSpotCompletionResult(completed=False)

    db.session.commit()

    hubspot_synced = False
    if local.hubspot_task_id:
        hubspot_synced = sync_hubspot_task_to_hubspot(local.hubspot_task_id)

    _append_hubspot_task_timeline(
        lead_id,
        local,
        actor,
        hubspot_synced=hubspot_synced,
        reason=reason,
    )
    db.session.commit()

    if not skip_scoring_refresh:
        try:
            from app.services.lead_scoring_engine import LeadScoringEngine

            LeadScoringEngine.recompute_and_persist(lead_id)
        except Exception as exc:
            logger.exception(
                'LeadScoringEngine.recompute_and_persist failed for lead %s after hubspot task done: %s',
                lead_id,
                exc,
            )
        else:
            return HubSpotCompletionResult(
                completed=True,
                hubspot_task_id=local.hubspot_task_id,
                hubspot_synced=hubspot_synced,
            )

    from app.services.next_action_invariant import ensure_next_action_after_task_change
    ensure_next_action_after_task_change(lead_id)

    return HubSpotCompletionResult(
        completed=True,
        hubspot_task_id=local.hubspot_task_id,
        hubspot_synced=hubspot_synced,
    )


def _inbound_timeline_activity_id(lead_id: int, hubspot_task_id: str) -> str:
    """Lead-scoped idempotency key that fits the 50-character DB column."""
    raw = f'hs-task-completed:{lead_id}:{hubspot_task_id}'
    if len(raw) <= 50:
        return raw
    digest = sha1(str(hubspot_task_id).encode('utf-8')).hexdigest()[:20]
    return f'hs-task-completed:{lead_id}:{digest}'


def ensure_inbound_hubspot_task_completed_timeline(
    lead_id: int,
    *,
    hubspot_task_id: str,
    title: str,
    occurred_at: datetime | None = None,
    task_id: int | None = None,
) -> bool:
    """Append a task_completed timeline row for a HubSpot-side completion.

    Idempotent via ``hubspot_activity_id`` / metadata ``hubspot_task_id``.
    Returns True when a new row was inserted.
    """
    hs_id = str(hubspot_task_id).strip()
    if not hs_id:
        return False

    activity_id = _inbound_timeline_activity_id(lead_id, hs_id)
    existing = LeadTimelineEntry.query.filter_by(
        hubspot_activity_id=activity_id,
    ).first()
    if existing is not None:
        return False

    # Also skip when an older row already recorded this HubSpot task id.
    for row in (
        LeadTimelineEntry.query.filter_by(
            lead_id=lead_id,
            event_type='task_completed',
            is_deleted=False,
        ).all()
    ):
        meta = row.event_metadata or {}
        if str(meta.get('hubspot_task_id') or '') == hs_id:
            return False

    when = occurred_at or datetime.utcnow()
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc).replace(tzinfo=None)

    lead_task = LeadTask.query.filter_by(
        lead_id=lead_id,
        hubspot_task_id=hs_id,
    ).first()
    db.session.add(
        LeadTimelineEntry(
            lead_id=lead_id,
            event_type='task_completed',
            occurred_at=when,
            source='hubspot',
            actor='HubSpot',
            summary=f'HubSpot task completed: {title}',
            hubspot_activity_id=activity_id,
            event_metadata={
                'crm_task_id': task_id,
                'lead_task_id': lead_task.id if lead_task is not None else None,
                'hubspot_task_id': hs_id,
                'title': title,
                'hubspot_synced': True,
                'note': 'Completed in HubSpot (inbound sync)',
            },
        ),
    )
    return True


def _crm_task_completed_in_hubspot(crm_task: Task) -> bool:
    """True when the CRM mirror reflects a HubSpot-side completion, not a local mirror."""
    if crm_task.status != 'completed' or crm_task.source != 'hubspot_import':
        return False
    payload = crm_task.raw_payload if isinstance(crm_task.raw_payload, dict) else {}
    props = payload.get('properties', {}) if isinstance(payload.get('properties'), dict) else {}
    hs_status = str(props.get('hs_task_status') or '').upper()
    if hs_status == 'COMPLETED':
        return True
    metadata = payload.get('metadata', {}) if isinstance(payload.get('metadata'), dict) else {}
    for key in ('status', 'taskStatus'):
        if str(metadata.get(key) or '').upper() in ('COMPLETED', 'DONE'):
            return True
    return False


def _lead_task_completed_locally(lead_task: LeadTask) -> bool:
    """True when a native completion timeline already exists for this LeadTask."""
    for row in LeadTimelineEntry.query.filter_by(
        lead_id=lead_task.lead_id,
        event_type='task_completed',
        is_deleted=False,
    ).all():
        meta = row.event_metadata or {}
        if meta.get('lead_task_id') == lead_task.id and row.source in ('manual', 'system'):
            return True
        if meta.get('task_id') == lead_task.id and row.source in ('manual', 'system'):
            return True
    return False


def backfill_missing_hubspot_task_completed_timelines(
    *,
    dry_run: bool = True,
    limit: int | None = None,
    lead_id: int | None = None,
) -> dict:
    """Insert missing task_completed timeline rows for completed HubSpot LeadTasks.

    Returns counts: scanned, missing, applied, skipped.
    """
    q = LeadTask.query.filter(
        LeadTask.hubspot_task_id.isnot(None),
        LeadTask.status == 'completed',
    ).order_by(LeadTask.id.asc())
    if lead_id is not None:
        q = q.filter_by(lead_id=lead_id)
    if limit is not None:
        q = q.limit(limit)

    scanned = 0
    missing = 0
    applied = 0
    skipped = 0

    for lt in q.yield_per(100):
        scanned += 1
        hs_id = str(lt.hubspot_task_id)
        crm_task = Task.query.filter_by(hubspot_task_id=hs_id).first()
        # A local LeadTask completion is not proof that HubSpot completed it.
        # Only backfill inbound history when the canonical CRM payload agrees.
        if (
            crm_task is None
            or not _crm_task_completed_in_hubspot(crm_task)
            or _lead_task_completed_locally(lt)
        ):
            skipped += 1
            continue
        activity_id = _inbound_timeline_activity_id(lt.lead_id, hs_id)
        if LeadTimelineEntry.query.filter_by(hubspot_activity_id=activity_id).first():
            skipped += 1
            continue
        has_meta_match = False
        for row in LeadTimelineEntry.query.filter_by(
            lead_id=lt.lead_id,
            event_type='task_completed',
            is_deleted=False,
        ).all():
            meta = row.event_metadata or {}
            if str(meta.get('hubspot_task_id') or '') == hs_id:
                has_meta_match = True
                break
        if has_meta_match:
            skipped += 1
            continue

        missing += 1
        occurred = _resolve_backfill_occurred_at(lt)
        if dry_run:
            logger.info(
                'dry-run: would add task_completed timeline lead_id=%s hubspot_task_id=%s occurred_at=%s',
                lt.lead_id,
                hs_id,
                occurred,
            )
            continue

        created = ensure_inbound_hubspot_task_completed_timeline(
            lt.lead_id,
            hubspot_task_id=hs_id,
            title=lt.title or '(No Subject)',
            occurred_at=occurred,
            task_id=crm_task.id,
        )
        if created:
            applied += 1
            if applied % 100 == 0:
                db.session.commit()

    if not dry_run and applied:
        db.session.commit()

    return {
        'scanned': scanned,
        'missing': missing,
        'applied': applied,
        'skipped': skipped,
        'dry_run': dry_run,
    }


def _resolve_backfill_occurred_at(lt: LeadTask) -> datetime:
    """Prefer HubSpot completion stamps over local upsert times."""
    from app.models.task import Task
    from app.services.hubspot_activity_converter_service import (
        HubSpotActivityConverterService,
    )

    crm = Task.query.filter_by(hubspot_task_id=str(lt.hubspot_task_id)).first()
    if crm is not None:
        props = (crm.raw_payload or {}).get('properties') or {}
        if props:
            parsed = HubSpotActivityConverterService._parse_hubspot_completion_time(props)
            if parsed is not None:
                return parsed
        if crm.completion_timestamp is not None:
            return crm.completion_timestamp
    if lt.completed_at is not None:
        return lt.completed_at
    return datetime.utcnow()
