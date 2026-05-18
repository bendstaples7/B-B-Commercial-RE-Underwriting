"""TaskService — CRUD and lifecycle management for Task records.

Implements Requirements 3.1, 3.2, 3.3, 3.5, 3.6.
"""
import unicodedata
from datetime import datetime

from app import db
from app.models.task import Task
from app.models.task_association import TaskAssociation
from app.exceptions import TaskValidationError, ResourceNotFoundError


def _strip_invisible(value: str) -> str:
    """Strip all Unicode whitespace and control characters from *value*.

    Stricter than ``str.strip()`` — handles Unicode Zs (space separators) and
    Cc (control characters) so inputs like '\\x7f' are treated as empty.
    """
    cleaned = ''.join(
        ch for ch in value
        if not (unicodedata.category(ch).startswith('C') or unicodedata.category(ch) == 'Zs')
    )
    return cleaned.strip()


class TaskService:
    """Service class for creating, updating, completing, deleting, and querying Tasks."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, data: dict) -> Task:
        """Create a new Task with optional associations.

        Args:
            data: dict with keys:
                - title (str, required, non-empty)
                - body (str, optional)
                - due_date (datetime, optional)
                - status (str, optional, default 'open')
                - priority (str, optional, default 'medium')
                - source (str, optional, default 'manual')
                - hubspot_task_id (str, optional)
                - raw_payload (dict, optional)
                - associations (list of {target_type, target_id}, optional)

        Returns:
            The newly created Task instance.

        Raises:
            TaskValidationError: if title is absent or whitespace-only.
        """
        title = data.get('title', '')
        if not title or not _strip_invisible(title):
            raise TaskValidationError(
                "Task title is required and cannot be empty.",
                field='title',
                value=title,
            )

        task = Task(
            title=_strip_invisible(title),
            body=data.get('body'),
            due_date=data.get('due_date'),
            status=data.get('status', 'open'),
            priority=data.get('priority', 'medium'),
            source=data.get('source', 'manual'),
            hubspot_task_id=data.get('hubspot_task_id'),
            raw_payload=data.get('raw_payload'),
        )
        db.session.add(task)
        db.session.flush()  # populate task.id before creating associations

        for assoc_data in data.get('associations', []):
            assoc = TaskAssociation(
                task_id=task.id,
                target_type=assoc_data['target_type'],
                target_id=assoc_data['target_id'],
            )
            db.session.add(assoc)

        db.session.commit()
        return task

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, task_id: int, data: dict) -> Task:
        """Update mutable fields on an existing Task.

        Args:
            task_id: Primary key of the Task to update.
            data: dict of fields to update (title, body, due_date, status,
                  priority, hubspot_task_id, raw_payload).

        Returns:
            The updated Task instance.

        Raises:
            ResourceNotFoundError: if no Task with task_id exists.
            TaskValidationError: if title is explicitly set to an empty string.
        """
        task = self._get_or_404(task_id)

        if 'title' in data:
            title = data['title']
            if not title or not _strip_invisible(title):
                raise TaskValidationError(
                    "Task title cannot be set to an empty value.",
                    field='title',
                    value=title,
                )
            task.title = _strip_invisible(title)

        updatable = ('body', 'due_date', 'status', 'priority',
                     'hubspot_task_id', 'raw_payload')
        for field in updatable:
            if field in data:
                setattr(task, field, data[field])

        db.session.commit()
        return task

    # ------------------------------------------------------------------
    # Complete
    # ------------------------------------------------------------------

    def complete(self, task_id: int) -> Task:
        """Mark a Task as completed and record the completion timestamp.

        Requirement 3.2: WHEN a user marks a Task as completed, THE Platform
        SHALL record the completion timestamp.

        Args:
            task_id: Primary key of the Task to complete.

        Returns:
            The updated Task instance.

        Raises:
            ResourceNotFoundError: if no Task with task_id exists.
        """
        task = self._get_or_404(task_id)
        task.status = 'completed'
        task.completion_timestamp = datetime.utcnow()
        db.session.commit()
        return task

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, task_id: int) -> None:
        """Delete a Task and its associations (cascade handled by DB/ORM).

        Args:
            task_id: Primary key of the Task to delete.

        Raises:
            ResourceNotFoundError: if no Task with task_id exists.
        """
        task = self._get_or_404(task_id)
        db.session.delete(task)
        db.session.commit()

    # ------------------------------------------------------------------
    # Get
    # ------------------------------------------------------------------

    def get(self, task_id: int) -> Task:
        """Retrieve a single Task by ID, applying overdue check on read.

        Requirement 3.6: WHEN a Task due date passes and the Task status is
        open, THE Platform SHALL immediately mark the Task as overdue.

        Args:
            task_id: Primary key of the Task to retrieve.

        Returns:
            The Task instance (possibly with status updated to 'overdue').

        Raises:
            ResourceNotFoundError: if no Task with task_id exists.
        """
        task = self._get_or_404(task_id)
        self.mark_overdue_if_needed(task)
        return task

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list(self, filters: dict = None, page: int = 1, per_page: int = 20):
        """Return a paginated, filtered list of Tasks.

        Supported filter keys:
            - status (str): exact match on task.status
            - priority (str): exact match on task.priority
            - due_date_from (datetime): tasks with due_date >= this value
            - due_date_to (datetime): tasks with due_date <= this value
            - target_type (str): filter by association target_type
            - target_id (int): filter by association target_id (requires target_type)

        Args:
            filters: dict of filter criteria (see above).
            page: 1-based page number.
            per_page: number of results per page.

        Returns:
            Tuple of (list[Task], total_count).
        """
        filters = filters or {}
        query = Task.query

        if 'status' in filters:
            query = query.filter(Task.status == filters['status'])

        if 'priority' in filters:
            query = query.filter(Task.priority == filters['priority'])

        if 'due_date_from' in filters:
            query = query.filter(Task.due_date >= filters['due_date_from'])

        if 'due_date_to' in filters:
            query = query.filter(Task.due_date <= filters['due_date_to'])

        # Filter by association target — join TaskAssociation when needed
        if 'target_type' in filters or 'target_id' in filters:
            query = query.join(TaskAssociation, TaskAssociation.task_id == Task.id)
            if 'target_type' in filters:
                query = query.filter(TaskAssociation.target_type == filters['target_type'])
            if 'target_id' in filters:
                query = query.filter(TaskAssociation.target_id == filters['target_id'])
            query = query.distinct()

        total = query.count()
        tasks = query.order_by(Task.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

        # Apply overdue check on every returned task (Requirement 3.6)
        for task in tasks:
            self.mark_overdue_if_needed(task)

        return tasks, total

    # ------------------------------------------------------------------
    # Overdue helpers
    # ------------------------------------------------------------------

    def mark_overdue_if_needed(self, task: Task) -> None:
        """If the task is past its due date and still open, mark it overdue.

        Requirement 3.6: WHEN a Task due date passes and the Task status is
        open, THE Platform SHALL immediately mark the Task as overdue and
        reflect that status in all subsequent query responses.

        Args:
            task: The Task instance to check and potentially update.
        """
        if (
            task.due_date is not None
            and task.due_date < datetime.utcnow()
            and task.status == 'open'
        ):
            task.status = 'overdue'
            db.session.commit()

    def get_overdue_tasks(self) -> list:
        """Return all tasks that are past their due date and still open.

        These are tasks that have not yet been read (and therefore not yet
        transitioned to 'overdue' by mark_overdue_if_needed).

        Returns:
            List of Task instances where due_date < now and status == 'open'.
        """
        now = datetime.utcnow()
        return (
            Task.query
            .filter(Task.due_date < now, Task.status == 'open')
            .all()
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_404(self, task_id: int) -> Task:
        """Fetch a Task by primary key or raise ResourceNotFoundError."""
        task = Task.query.get(task_id)
        if task is None:
            raise ResourceNotFoundError(
                f"Task with id {task_id} not found.",
                payload={'task_id': task_id},
            )
        return task
