"""SkipTraceEnqueue — handoff from entity resolution (and future owners) to skip-trace.

v1 creates the existing manual ``skip_trace_owner`` LeadTask and sets
``needs_skip_trace``. A future ``SkipTraceService`` vendor integration should
replace only the body of :meth:`SkipTraceEnqueue.enqueue` — callers stay the same.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import text

from app import db
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.task import Task
from app.exceptions import InvalidLeadStatusTransitionError
from app.services.lead_task_service import (
    LeadTaskService,
    complete_native_task_mirror,
)

logger = logging.getLogger(__name__)


def _contact_display_name(contact_id: int) -> Optional[str]:
    contact = Contact.query.filter_by(id=contact_id).first()
    if contact is None:
        return None
    parts = [
        str(part).strip()
        for part in (contact.first_name, contact.last_name)
        if part and str(part).strip()
    ]
    return " ".join(parts) if parts else None


class SkipTraceEnqueue:
    """Queue a contact/lead for skip tracing without calling a skip-trace vendor."""

    def __init__(self, task_service: Optional[LeadTaskService] = None) -> None:
        self._tasks = task_service or LeadTaskService()

    def enqueue(
        self,
        lead_id: int,
        contact_id: Optional[int] = None,
        *,
        actor: str = "entity_resolution",
        reason: str = "Entity manager resolved — run skip trace on person",
        due_date: Optional[date] = None,
        recompute_action: bool = True,
    ) -> Optional[LeadTask]:
        """Enqueue skip-trace work for *lead_id* / optional *contact_id*.

        Idempotent for open ``skip_trace_owner`` tasks: returns the existing
        open task instead of creating a duplicate.
        """
        self._serialize_lead_enqueue(lead_id)
        lead = Lead.query.filter_by(id=lead_id).with_for_update().first()
        if lead is None:
            logger.warning("SkipTraceEnqueue: lead %s not found", lead_id)
            return None

        existing = (
            LeadTask.query
            .filter_by(lead_id=lead_id, task_type="skip_trace_owner", status="open")
            .first()
        )
        if existing is not None:
            lead.needs_skip_trace = True
            if due_date is not None:
                existing.due_date = due_date
            db.session.commit()
            logger.info(
                "SkipTraceEnqueue: open skip_trace_owner task already exists "
                "task_id=%s lead_id=%s contact_id=%s",
                existing.id, lead_id, contact_id,
            )
            return existing

        title = reason
        if contact_id is not None:
            display_name = _contact_display_name(contact_id)
            suffix = display_name or f"contact_id={contact_id}"
            title = f"{reason} ({suffix})"
        if len(title) > 255:
            title = title[:255]

        lead.needs_skip_trace = True
        db.session.flush()

        task = self._tasks.create(
            lead_id,
            {
                "task_type": "skip_trace_owner",
                "title": title,
                "due_date": due_date,
            },
            actor=actor,
            recompute_action=recompute_action,
        )
        logger.info(
            "SkipTraceEnqueue: created skip_trace_owner task_id=%s lead_id=%s "
            "contact_id=%s",
            task.id, lead_id, contact_id,
        )
        return task

    def move_to_skip_trace(
        self,
        lead_id: int,
        *,
        actor: str,
        complete_task_id: Optional[int] = None,
    ) -> dict:
        """Atomically complete current work and hand the lead to skip trace."""
        self._serialize_lead_enqueue(lead_id)
        lead = Lead.query.filter_by(id=lead_id).with_for_update().first()
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")
        if lead.lead_status in {
            "deprioritize",
            "deal_won",
            "deal_lost",
            "suppressed",
            "do_not_contact",
        }:
            raise InvalidLeadStatusTransitionError(
                lead.lead_status,
                "skip_trace",
            )

        completed_task: Optional[LeadTask] = None
        if complete_task_id is not None:
            completed_task = LeadTask.query.filter(
                LeadTask.id == complete_task_id,
                LeadTask.lead_id == lead_id,
                LeadTask.task_type != 'skip_trace_owner',
            ).first()
            if completed_task is None:
                raise ValueError(
                    f"Task {complete_task_id} not found for lead {lead_id}"
                )
        else:
            completed_task = (
                LeadTask.query
                .filter(
                    LeadTask.lead_id == lead_id,
                    LeadTask.status == "open",
                    LeadTask.task_type != "skip_trace_owner",
                )
                .order_by(
                    LeadTask.due_date.asc().nullslast(),
                    LeadTask.id.asc(),
                )
                .first()
            )

        now = datetime.now(timezone.utc)
        completed_task_id_out: Optional[int] = None
        pending_hubspot_id: Optional[str] = None
        if completed_task is not None and completed_task.status == "open":
            completed_task_id_out = completed_task.id
            if completed_task.hubspot_task_id:
                from app.services.hubspot_task_completion_service import (
                    mark_hubspot_task_completed_local,
                )

                local_completion = mark_hubspot_task_completed_local(
                    lead_id,
                    completed_task.id,
                    actor=actor,
                    reason="moved_to_skip_trace",
                )
                if local_completion is not None:
                    pending_hubspot_id = local_completion.hubspot_task_id
                else:
                    self._complete_task_and_log(completed_task, now, actor)
            else:
                self._complete_task_and_log(completed_task, now, actor)
            if completed_task.task_type == 'run_property_analysis':
                from app.services.analysis_completion_service import (
                    mark_lead_analysis_complete,
                )
                mark_lead_analysis_complete(
                    lead_id,
                    source='manual',
                    actor=actor,
                    recompute_action=False,
                    commit=False,
                )

        old_status = lead.lead_status
        lead.lead_status = "skip_trace"
        lead.needs_skip_trace = True
        if old_status != "skip_trace":
            db.session.add(LeadTimelineEntry(
                lead_id=lead_id,
                event_type="status_changed",
                occurred_at=now,
                source="manual",
                actor=actor,
                summary=(
                    f"Status changed from '{old_status}' to 'skip_trace'. "
                    "Moved to skip trace from quick actions."
                ),
                event_metadata={
                    "previous_status": old_status,
                    "new_status": "skip_trace",
                    "reason": "quick_action_move_to_skip_trace",
                },
            ))

        skip_trace_task = (
            LeadTask.query
            .filter_by(
                lead_id=lead_id,
                task_type="skip_trace_owner",
                status="open",
            )
            .first()
        )
        if skip_trace_task is None:
            skip_trace_task = self._tasks.create(
                lead_id,
                {
                    "task_type": "skip_trace_owner",
                    "title": "Awaiting skip trace",
                    "due_date": None,
                },
                actor=actor,
                recompute_action=False,
                commit=False,
            )

        db.session.commit()

        if pending_hubspot_id:
            from app.services.hubspot_task_completion_service import (
                sync_pending_hubspot_completions,
            )
            sync_pending_hubspot_completions([pending_hubspot_id])

        from app.services.lead_refresh import refresh_lead_scoring
        from app.services.queue_order_cache import queue_order_cache

        refresh_lead_scoring(lead_id)
        queue_order_cache.clear()
        return {
            "lead_id": lead_id,
            "lead_status": "skip_trace",
            "completed_task_id": completed_task_id_out,
            "skip_trace_task_id": skip_trace_task.id,
        }

    def schedule_recent_sale(
        self,
        lead_id: int,
        *,
        due_date: date,
        actor: str = "recent_sale_reconciliation",
        commit: bool = True,
    ) -> dict:
        """Schedule owner re-verification for the end of a recent-sale hold.

        The lead does not enter skip trace until ``due_date``. The hourly task
        activator performs that transition when the two-year hold expires.
        """
        self._serialize_lead_enqueue(lead_id)
        lead = Lead.query.filter_by(id=lead_id).with_for_update().first()
        if lead is None:
            return {'scheduled': False, 'task_id': None, 'changed': False}
        if lead.lead_status in {
            "deprioritize",
            "deal_won",
            "deal_lost",
            "suppressed",
            "do_not_contact",
        }:
            return {'scheduled': False, 'task_id': None, 'changed': False}

        task = (
            LeadTask.query
            .filter_by(
                lead_id=lead_id,
                task_type="skip_trace_owner",
                status="open",
                workflow_key="recent_sale_hold",
            )
            .first()
        )
        title = "Recent-sale hold ended — verify new owner and contact information"
        task_changed = (
            task is None
            or task.due_date != due_date
            or task.title != title
        )
        scheduled = task is None or task.due_date != due_date
        if task is None:
            task = self._tasks.create(
                lead_id,
                {
                    "task_type": "skip_trace_owner",
                    "title": title,
                    "due_date": due_date,
                },
                actor=actor,
                recompute_action=False,
                commit=False,
            )
            task.workflow_key = "recent_sale_hold"
            db.session.add(task)
        else:
            task.title = title
            task.due_date = due_date
            db.session.add(task)
        from app.services.hubspot_task_completion_service import (
            mirror_crm_task_from_lead_task,
        )
        hubspot_task_ids: set[str] = set()
        mirror_changed = mirror_crm_task_from_lead_task(
            task,
            hubspot_task_ids,
        )

        # ``skip_trace`` is the holding stage. ``awaiting_skip_trace`` means the
        # hold has matured and manual skip tracing should be performed.
        lead_changed = lead.needs_skip_trace or lead.lead_status != "skip_trace"
        lead.needs_skip_trace = False
        old_status = lead.lead_status
        lead.lead_status = "skip_trace"
        db.session.add(lead)

        if scheduled:
            db.session.add(LeadTimelineEntry(
                lead_id=lead_id,
                event_type="task_snoozed",
                occurred_at=datetime.now(timezone.utc),
                source="system",
                actor=actor,
                summary=(
                    "Skip trace scheduled for the end of the recent-sale hold "
                    f"on {due_date.isoformat()}."
                ),
                event_metadata={
                    "task_id": task.id,
                    "task_type": "skip_trace_owner",
                    "due_date": due_date.isoformat(),
                    "reason": "recent_sale_hold_expiration",
                },
            ))
        if old_status != "skip_trace":
            db.session.add(LeadTimelineEntry(
                lead_id=lead_id,
                event_type="status_changed",
                occurred_at=datetime.now(timezone.utc),
                source="system",
                actor=actor,
                summary=(
                    f"Status changed from '{old_status}' to 'skip_trace' "
                    "for the recent-sale holding period."
                ),
                event_metadata={
                    "previous_status": old_status,
                    "new_status": "skip_trace",
                    "reason": "recent_sale_hold",
                    "due_date": due_date.isoformat(),
                },
            ))

        if commit:
            db.session.commit()
            if hubspot_task_ids:
                from app.services.mail_task_lifecycle_service import (
                    sync_recent_sale_hubspot_due_dates,
                )
                sync_recent_sale_hubspot_due_dates(hubspot_task_ids, due_date)
            from app.services.lead_refresh import refresh_lead_scoring
            from app.services.queue_order_cache import queue_order_cache

            refresh_lead_scoring(lead_id)
            queue_order_cache.clear()

        return {
            'scheduled': scheduled,
            'task_id': task.id,
            'changed': task_changed or mirror_changed or lead_changed,
            'hubspot_task_ids': sorted(hubspot_task_ids),
        }

    def activate_due_recent_sale_tasks(
        self,
        *,
        actor: str = "recent_sale_skip_trace_activation",
        commit: bool = True,
        limit: int | None = None,
    ) -> dict:
        """Move matured recent-sale tasks into active skip-trace work."""
        query = (
            LeadTask.query
            .filter(
                LeadTask.task_type == "skip_trace_owner",
                LeadTask.status == "open",
                LeadTask.due_date.isnot(None),
                LeadTask.due_date <= date.today(),
                LeadTask.workflow_key == "recent_sale_hold",
            )
            .order_by(LeadTask.due_date.asc(), LeadTask.id.asc())
        )
        if limit is not None:
            query = query.limit(limit)

        tasks = query.all()
        activated_ids: list[int] = []
        retired_task_ids: list[int] = []
        hubspot_task_ids: set[str] = set()
        now = datetime.now(timezone.utc)
        for task in tasks:
            lead = Lead.query.filter_by(id=task.lead_id).with_for_update().first()
            if lead is None or lead.lead_status in {
                "deprioritize",
                "deal_won",
                "deal_lost",
                "suppressed",
                "do_not_contact",
            }:
                task.status = "completed"
                task.completed_at = now
                db.session.add(task)
                if task.hubspot_task_id:
                    hubspot_task_ids.add(str(task.hubspot_task_id))
                if task.mirror_task_id:
                    mirror = db.session.get(Task, task.mirror_task_id)
                    if mirror is not None and mirror.hubspot_task_id:
                        hubspot_task_ids.add(str(mirror.hubspot_task_id))
                complete_native_task_mirror(task, now)
                retired_task_ids.append(task.id)
                continue
            if lead.lead_status != "awaiting_skip_trace" or not lead.needs_skip_trace:
                old_status = lead.lead_status
                lead.lead_status = "awaiting_skip_trace"
                lead.needs_skip_trace = True
                db.session.add(lead)
                db.session.add(LeadTimelineEntry(
                    lead_id=lead.id,
                    event_type="status_changed",
                    occurred_at=now,
                    source="system",
                    actor=actor,
                    summary=(
                        f"Status changed from '{old_status}' to 'awaiting_skip_trace' "
                        "when the recent-sale hold expired."
                    ),
                    event_metadata={
                        "previous_status": old_status,
                        "new_status": "awaiting_skip_trace",
                        "reason": "recent_sale_hold_expired",
                        "task_id": task.id,
                    },
                ))
                activated_ids.append(lead.id)

        if commit and (activated_ids or retired_task_ids):
            db.session.commit()
            if hubspot_task_ids:
                from app.services.hubspot_task_completion_service import (
                    sync_pending_hubspot_completions,
                )
                sync_pending_hubspot_completions(sorted(hubspot_task_ids))
            from app.services.lead_refresh import refresh_lead_scoring
            from app.services.queue_order_cache import queue_order_cache

            for lead_id in activated_ids:
                refresh_lead_scoring(lead_id)
            queue_order_cache.clear()

        return {
            "activated_lead_count": len(activated_ids),
            "activated_lead_ids": activated_ids,
            "retired_task_count": len(retired_task_ids),
            "retired_task_ids": retired_task_ids,
            "processed_task_count": len(tasks),
            "processed_lead_ids": list(dict.fromkeys(
                task.lead_id for task in tasks
            )),
        }

    @staticmethod
    def _complete_task_and_log(
        task: LeadTask,
        completed_at: datetime,
        actor: str,
    ) -> None:
        """Complete native/mirrored work and preserve task side effects."""
        task.status = 'completed'
        task.completed_at = completed_at
        complete_native_task_mirror(task, completed_at)
        db.session.add(LeadTimelineEntry(
            lead_id=task.lead_id,
            event_type='task_completed',
            occurred_at=completed_at,
            source='manual',
            actor=actor,
            summary=f'Task completed: {task.title}',
            event_metadata={
                'task_id': task.id,
                'task_type': task.task_type,
                'title': task.title,
                'reason': 'moved_to_skip_trace',
            },
        ))

    @staticmethod
    def _serialize_lead_enqueue(lead_id: int) -> None:
        bind = db.session.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return
        db.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"skip_trace_enqueue:{lead_id}"},
        )
