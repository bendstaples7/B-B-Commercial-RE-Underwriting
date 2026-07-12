"""SkipTraceEnqueue — handoff from entity resolution (and future owners) to skip-trace.

v1 creates the existing manual ``skip_trace_owner`` LeadTask and sets
``needs_skip_trace``. A future ``SkipTraceService`` vendor integration should
replace only the body of :meth:`SkipTraceEnqueue.enqueue` — callers stay the same.
"""
from __future__ import annotations

import logging
from typing import Optional

from app import db
from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.services.lead_task_service import LeadTaskService

logger = logging.getLogger(__name__)


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
    ) -> Optional[LeadTask]:
        """Enqueue skip-trace work for *lead_id* / optional *contact_id*.

        Idempotent for open ``skip_trace_owner`` tasks: returns the existing
        open task instead of creating a duplicate.
        """
        lead = Lead.query.get(lead_id)
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
            db.session.commit()
            logger.info(
                "SkipTraceEnqueue: open skip_trace_owner task already exists "
                "task_id=%s lead_id=%s contact_id=%s",
                existing.id, lead_id, contact_id,
            )
            return existing

        title = reason
        if contact_id is not None:
            title = f"{reason} (contact_id={contact_id})"
        if len(title) > 255:
            title = title[:255]

        lead.needs_skip_trace = True
        db.session.flush()

        task = self._tasks.create(
            lead_id,
            {
                "task_type": "skip_trace_owner",
                "title": title,
            },
            actor=actor,
            recompute_action=True,
        )
        logger.info(
            "SkipTraceEnqueue: created skip_trace_owner task_id=%s lead_id=%s "
            "contact_id=%s",
            task.id, lead_id, contact_id,
        )
        return task
