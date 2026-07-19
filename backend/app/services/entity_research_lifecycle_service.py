"""Preemptive entity research and retirement of legacy LLC-search chores.

Keeps Illinois LLC / org research off Today's Action as manual Call Now work:
promote entity-shaped owners, queue ``ensure_researched``, and complete stale
HubSpot \"LLC search\" tasks when automation has run or is not applicable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import or_

from app import db
from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.organization import Organization
from app.models.property_organization_link import PropertyOrganizationLink
from app.services.entity_resolution_service import EntityResolutionService
from app.services.helpers.owner_organization import promote_named_owner_to_organization
from app.services.lead_task_service import complete_native_task_mirror
from app.services.plugins.owner_name_utils import contact_display_name, is_entity_name
from app.utils.call_completable_task import (
    LEGACY_ENTITY_RESEARCH_TITLE_ILIKE,
    is_legacy_entity_research_task,
)

logger = logging.getLogger(__name__)

ENTITY_RESEARCH_BATCH_SIZE = 100


def is_legacy_llc_search_task(task: LeadTask) -> bool:
    """True for open research chores that should not drive Call Now."""
    return is_legacy_entity_research_task(
        getattr(task, 'task_type', None),
        getattr(task, 'title', None),
    )


def promote_entity_owner_for_lead(lead: Lead, *, source: str = "entity_research_lifecycle") -> Organization | None:
    """Ensure an owner Organization link when flat owner name is entity-shaped."""
    if lead is None or getattr(lead, "id", None) is None:
        return None
    first = getattr(lead, "owner_first_name", None)
    last = getattr(lead, "owner_last_name", None)
    display = contact_display_name(
        (first or "").strip() or None,
        (last or "").strip() or None,
    )
    if not display or not is_entity_name(display):
        return None
    return promote_named_owner_to_organization(
        lead.id, first, last, source=source, unlink_contact=False,
    )


def retire_legacy_llc_search_tasks(
    lead_id: int,
    *,
    actor: str = "entity_research_lifecycle",
    reason: str = "entity_research_automation",
    commit: bool = False,
) -> list[int]:
    """Complete open legacy LLC-search tasks for *lead_id*. Returns completed ids."""
    tasks = (
        LeadTask.query
        .filter_by(lead_id=lead_id, status="open")
        .order_by(LeadTask.id.asc())
        .all()
    )
    now = datetime.now(timezone.utc)
    completed: list[int] = []
    for task in tasks:
        if not is_legacy_llc_search_task(task):
            continue
        task.status = "completed"
        task.completed_at = now
        complete_native_task_mirror(task, now)
        db.session.add(task)
        db.session.add(LeadTimelineEntry(
            lead_id=lead_id,
            event_type="task_completed",
            occurred_at=now,
            source="system",
            actor=actor,
            summary=f"Task completed: {task.title}",
            event_metadata={
                "task_id": task.id,
                "task_type": task.task_type,
                "title": task.title,
                "reason": reason,
            },
        ))
        completed.append(task.id)
    if commit and completed:
        db.session.commit()
    return completed


def should_retire_legacy_llc_search(lead: Lead) -> bool:
    """True when legacy LLC-search chores should leave the queue for this lead.

    Automation owns entity research; HubSpot \"LLC search\" is never a valid
    Call Now driver — retire whenever the title matches.
    """
    return lead is not None


def preempt_entity_research_for_lead(
    lead_id: int,
    *,
    actor: str = "entity_research_lifecycle",
    sync: bool = False,
    commit: bool = True,
    queue_research: bool = True,
    force_research: bool = False,
) -> dict:
    """Promote entity owner, queue research, and retire obsolete LLC-search tasks."""
    lead = db.session.get(Lead, lead_id)
    if lead is None:
        return {"lead_id": lead_id, "skipped": True, "reason": "lead_not_found"}

    promoted = promote_entity_owner_for_lead(lead, source=actor)
    if commit and promoted is not None:
        db.session.commit()

    if queue_research:
        research = EntityResolutionService().ensure_researched(
            lead_id, actor=actor, sync=sync, force=force_research,
        )
    else:
        research = {
            "queued": False,
            "skipped": True,
            "reason": "queue_disabled",
        }

    retired: list[int] = []
    # Re-load policy after promotion / research side effects.
    lead = db.session.get(Lead, lead_id)
    if lead is not None and should_retire_legacy_llc_search(lead):
        retired = retire_legacy_llc_search_tasks(
            lead_id, actor=actor, commit=False,
        )
        if commit and retired:
            db.session.commit()
            from app.services.lead_refresh import refresh_lead_scoring
            refresh_lead_scoring(lead_id)

    return {
        "lead_id": lead_id,
        "promoted_organization_id": promoted.id if promoted else None,
        "research": research,
        "retired_task_ids": retired,
    }


def reconcile_pending_entity_research(
    *,
    actor: str = "entity_research_reconcile",
    limit: int | None = None,
    commit: bool = True,
) -> dict:
    """Background pass: research pending owner orgs; retire legacy LLC-search tasks."""
    effective_limit = (
        ENTITY_RESEARCH_BATCH_SIZE if limit is None else max(limit, 0)
    )
    if effective_limit == 0:
        return {
            "processed_lead_count": 0,
            "queued_count": 0,
            "retired_task_count": 0,
            "processed_lead_ids": [],
        }

    # Leads with open legacy LLC-search tasks (queue pollution).
    legacy_lead_ids = [
        row[0]
        for row in (
            db.session.query(LeadTask.lead_id)
            .filter(
                LeadTask.status == "open",
                or_(*[
                    LeadTask.title.ilike(pattern)
                    for pattern in LEGACY_ENTITY_RESEARCH_TITLE_ILIKE
                ]),
            )
            .distinct()
            .limit(effective_limit)
            .all()
        )
    ]

    remaining = max(effective_limit - len(legacy_lead_ids), 0)
    pending_org_lead_ids: list[int] = []
    if remaining:
        pending_org_lead_ids = [
            row[0]
            for row in (
                db.session.query(PropertyOrganizationLink.property_id)
                .join(
                    Organization,
                    Organization.id == PropertyOrganizationLink.organization_id,
                )
                .filter(
                    PropertyOrganizationLink.role == "owner",
                    or_(
                        Organization.entity_lookup_status.is_(None),
                        Organization.entity_lookup_status.in_(("pending", "error")),
                    ),
                )
                .distinct()
                .limit(remaining)
                .all()
            )
        ]

    ordered_ids = list(dict.fromkeys(legacy_lead_ids + pending_org_lead_ids))
    queued = 0
    retired_total = 0
    results: list[dict] = []
    for lead_id in ordered_ids:
        outcome = preempt_entity_research_for_lead(
            lead_id,
            actor=actor,
            sync=False,
            commit=commit,
            queue_research=True,
            force_research=True,
        )
        results.append(outcome)
        if outcome.get("research", {}).get("queued") or outcome.get("research", {}).get("sync"):
            queued += 1
        retired_total += len(outcome.get("retired_task_ids") or [])

    return {
        "processed_lead_count": len(ordered_ids),
        "queued_count": queued,
        "retired_task_count": retired_total,
        "processed_lead_ids": ordered_ids,
        "results": results,
    }
