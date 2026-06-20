"""LeadTaskService — CRM task lifecycle management for leads."""
import logging
from datetime import datetime, date, timezone

from sqlalchemy import asc, nullslast

from app import db
from app.models import Lead, LeadTask, LeadTimelineEntry
from app.models.task import Task
from app.exceptions import (
    LeadTaskValidationError,
    InvalidTaskStatusTransitionError,
    DoNotContactViolationError,
)

logger = logging.getLogger(__name__)


class LeadTaskService:
    """Manages the lifecycle of LeadTask records."""

    def create(self, lead_id: int, data: dict, actor: str = 'anonymous',
               recompute_action: bool = True) -> LeadTask:
        """Create a new LeadTask for a lead.

        - Validates title (1–255 chars)
        - Sets status='open'
        - Appends task_created timeline entry
        - Triggers RA recomputation (unless ``recompute_action=False``)
        - Auto-transitions lead_status from 'new' → 'active'

        ``recompute_action`` lets a caller that will refresh the lead itself
        afterwards (e.g. via ``refresh_lead_scoring``) suppress the in-service
        recomputation, so the recommended action is recomputed exactly once per
        operation instead of twice.
        """
        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} not found")

        title = (data.get('title') or '').strip()
        if not title or len(title) > 255:
            raise LeadTaskValidationError(
                "Task title must be between 1 and 255 characters.",
                field='title',
            )

        task = LeadTask(
            lead_id=lead_id,
            task_type=data.get('task_type', 'custom'),
            title=title,
            status='open',
            due_date=data.get('due_date'),
            created_by=actor,
        )
        db.session.add(task)

        # Auto-transition new → active
        if lead.lead_status == 'new':
            lead.lead_status = 'active'
            db.session.add(lead)

        db.session.flush()  # get task.id

        # Mirror to tasks table so queue queries using tasks.lead_id pick it up
        mirror_task = Task(
            title=title,
            status='open',
            source='manual',
            lead_id=lead_id,
            task_type=data.get('task_type', 'custom'),
            due_date=datetime.combine(data['due_date'], datetime.min.time()) if data.get('due_date') else None,
        )
        db.session.add(mirror_task)

        # Append timeline entry
        entry = LeadTimelineEntry(
            lead_id=lead_id,
            event_type='task_created',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor=actor,
            summary=f"Task created: {title}",
            event_metadata={'task_id': task.id, 'task_type': task.task_type, 'title': title},
        )
        db.session.add(entry)
        db.session.commit()

        # Trigger RA recomputation (skipped when the caller will refresh the
        # lead itself, so the action is recomputed once per op rather than twice).
        if recompute_action:
            try:
                from app.services.action_engine_service import ActionEngineService
                ActionEngineService.recompute_and_persist(lead_id)
            except Exception as exc:
                logger.error(
                    "ActionEngineService.recompute_and_persist failed for lead %s: %s",
                    lead_id, exc, exc_info=True,
                )  # RA recomputation failure should not block task creation

        return task

    def complete(self, task_id: int, lead_id: int, actor: str = 'anonymous',
                 recompute_action: bool = True) -> LeadTask:
        """Complete an open LeadTask.

        - Validates task is 'open' (raises InvalidTaskStatusTransitionError if already completed)
        - Sets status='completed', records completed_at
        - Appends task_completed timeline entry
        - Triggers RA recomputation (unless ``recompute_action=False``)

        ``recompute_action`` lets a caller that will refresh the lead itself
        afterwards (e.g. via ``refresh_lead_scoring``) suppress the in-service
        recomputation, so the recommended action is recomputed exactly once per
        operation instead of twice.
        """
        task = LeadTask.query.filter_by(id=task_id, lead_id=lead_id).first()
        if task is None:
            raise ValueError(f"Task {task_id} not found for lead {lead_id}")

        if task.status == 'completed':
            # No-op per spec: completing a completed task is a no-op
            return task

        if task.status != 'open':
            raise InvalidTaskStatusTransitionError(
                task_id=task_id,
                current_status=task.status,
                attempted_status='completed',
            )

        task.status = 'completed'
        task.completed_at = datetime.now(timezone.utc)
        db.session.add(task)

        entry = LeadTimelineEntry(
            lead_id=lead_id,
            event_type='task_completed',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor=actor,
            summary=f"Task completed: {task.title}",
            event_metadata={'task_id': task_id, 'task_type': task.task_type, 'title': task.title},
        )
        db.session.add(entry)
        db.session.commit()

        # Trigger RA recomputation (skipped when the caller will refresh the
        # lead itself, so the action is recomputed once per op rather than twice).
        if recompute_action:
            try:
                from app.services.action_engine_service import ActionEngineService
                ActionEngineService.recompute_and_persist(lead_id)
            except Exception as exc:
                logger.error(
                    "ActionEngineService.recompute_and_persist failed for lead %s: %s",
                    lead_id, exc, exc_info=True,
                )

        return task

    def snooze(self, task_id: int, lead_id: int, new_due_date: date, actor: str = 'anonymous') -> LeadTask:
        """Snooze a LeadTask to a future date.

        - Validates new_due_date is strictly after today
        - Updates due_date
        - Appends task_snoozed timeline entry
        """
        task = LeadTask.query.filter_by(id=task_id, lead_id=lead_id).first()
        if task is None:
            raise ValueError(f"Task {task_id} not found for lead {lead_id}")

        today = date.today()
        if new_due_date <= today:
            raise LeadTaskValidationError(
                "Snooze date must be strictly after today.",
                field='new_due_date',
            )

        old_due_date = task.due_date
        task.due_date = new_due_date
        db.session.add(task)

        entry = LeadTimelineEntry(
            lead_id=lead_id,
            event_type='task_snoozed',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor=actor,
            summary=f"Task snoozed to {new_due_date.isoformat()}: {task.title}",
            event_metadata={
                'task_id': task_id,
                'title': task.title,
                'old_due_date': old_due_date.isoformat() if old_due_date else None,
                'new_due_date': new_due_date.isoformat(),
            },
        )
        db.session.add(entry)
        db.session.commit()

        return task

    def list_open(self, lead_id: int) -> list:
        """Return open tasks for a lead ordered by due_date asc, nulls last."""
        return (
            LeadTask.query
            .filter_by(lead_id=lead_id, status='open')
            .order_by(nullslast(asc(LeadTask.due_date)))
            .all()
        )
