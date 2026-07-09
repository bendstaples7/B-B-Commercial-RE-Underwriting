"""Complete HubSpot-imported tasks locally with best-effort HubSpot API sync."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from app import db
from app.models import LeadTimelineEntry

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


def _update_hubspot_task_completed(
    lead_id: int,
    task_id: int,
) -> HubSpotTaskLocalCompletion | None:
    now = datetime.now(timezone.utc)
    result = db.session.execute(
        db.text("""
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

    return HubSpotTaskLocalCompletion(
        task_id=result[0],
        title=result[1],
        hubspot_task_id=result[2],
    )


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
) -> HubSpotTaskLocalCompletion | None:
    """Mark a HubSpot task completed in the current session without committing."""
    local = _update_hubspot_task_completed(lead_id, task_id)
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
) -> HubSpotCompletionResult:
    """Mark a HubSpot-imported task completed locally; sync to HubSpot when possible."""
    local = _update_hubspot_task_completed(lead_id, task_id)
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

    return HubSpotCompletionResult(
        completed=True,
        hubspot_task_id=local.hubspot_task_id,
        hubspot_synced=hubspot_synced,
    )
