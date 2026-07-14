"""SkipTraceEnqueue — handoff from entity resolution (and future owners) to skip-trace.

v1 creates the existing manual ``skip_trace_owner`` LeadTask and sets
``needs_skip_trace``. A future ``SkipTraceService`` vendor integration should
replace only the body of :meth:`SkipTraceEnqueue.enqueue` — callers stay the same.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from sqlalchemy import text

from app import db
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.services.lead_task_service import LeadTaskService

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

    @staticmethod
    def _serialize_lead_enqueue(lead_id: int) -> None:
        bind = db.session.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return
        db.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"skip_trace_enqueue:{lead_id}"},
        )
