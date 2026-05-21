"""Property-based tests for the overdue detection invariant.

Property verified:
  9. Overdue Detection Invariant — for any Task with due_date strictly in the
     past and status=open, every query response must reflect status=overdue,
     regardless of when the task was created or last updated.

This test requires a Flask app context because TaskService.get() writes to the
database (marking the task overdue on read).  The ``app`` fixture from
conftest.py provides an in-memory SQLite database with all tables created.
"""
# Feature: hubspot-crm-migration, Property 9: Overdue detection invariant

import pytest
from datetime import datetime, timedelta

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.task import Task
from app.services.task_service import TaskService


# ---------------------------------------------------------------------------
# Strategy: generate past datetimes
# ---------------------------------------------------------------------------

# Hypothesis datetimes are naive by default; we need datetimes strictly before
# "now" so we cap max_value at (now - 1 second).  We use a fixed reference
# point at strategy-definition time; the deadline=None setting on each test
# ensures slow runs don't cause flakiness.
_PAST_CUTOFF = datetime.utcnow() - timedelta(seconds=1)

_past_due_date_st = st.datetimes(
    max_value=_PAST_CUTOFF,
    # Avoid extremely ancient dates that SQLite might reject.
    min_value=datetime(2000, 1, 1),
)

# Titles: non-empty ASCII strings (SQLite-safe).
_title_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ",
    min_size=1,
    max_size=50,
).filter(lambda t: t.strip())  # ensure at least one non-space character

# Priority values allowed by the Task model enum.
_priority_st = st.sampled_from(["high", "medium", "low"])

# Source values allowed by the Task model enum.
_source_st = st.sampled_from(["manual", "hubspot_import"])


# ---------------------------------------------------------------------------
# Property 9: Overdue Detection Invariant
# ---------------------------------------------------------------------------


class TestOverdueDetectionInvariant:
    """Property 9 — any open task with a past due_date must read back as overdue."""

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        due_date=_past_due_date_st,
        title=_title_st,
        priority=_priority_st,
        source=_source_st,
    )
    def test_past_due_open_task_reads_as_overdue(
        self, app, due_date, title, priority, source
    ):
        """TaskService.get() must return status='overdue' for any open task with a past due_date.

        **Validates: Requirements 3.6, 15.4**
        """
        with app.app_context():
            # Create a Task directly (bypassing TaskService.create so we can
            # set status='open' explicitly, matching the property precondition).
            task = Task(
                title=title,
                due_date=due_date,
                status="open",
                priority=priority,
                source=source,
            )
            db.session.add(task)
            db.session.commit()
            task_id = task.id

            svc = TaskService()
            retrieved = svc.get(task_id)

            assert retrieved.status == "overdue", (
                f"Expected status='overdue' for task with due_date={due_date} "
                f"(past) and initial status='open', but got status='{retrieved.status}'"
            )

            db.session.rollback()

    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        due_date=_past_due_date_st,
        title=_title_st,
    )
    def test_overdue_status_persisted_after_first_read(
        self, app, due_date, title
    ):
        """After the first read marks a task overdue, subsequent reads must also return overdue.

        This verifies the invariant holds across multiple query responses, not
        just the first one.

        **Validates: Requirements 3.6, 15.4**
        """
        with app.app_context():
            task = Task(
                title=title,
                due_date=due_date,
                status="open",
                priority="medium",
                source="manual",
            )
            db.session.add(task)
            db.session.commit()
            task_id = task.id

            svc = TaskService()

            # First read — triggers the overdue transition.
            first_read = svc.get(task_id)
            assert first_read.status == "overdue", (
                f"First read: expected 'overdue', got '{first_read.status}'"
            )

            # Second read — must still be overdue (persisted, not transient).
            second_read = svc.get(task_id)
            assert second_read.status == "overdue", (
                f"Second read: expected 'overdue', got '{second_read.status}'"
            )

            db.session.rollback()

    def test_future_due_date_does_not_become_overdue(self, app):
        """A task with a future due_date must NOT be marked overdue on read.

        This is the complementary edge case: the invariant only applies to
        past due dates.

        **Validates: Requirements 3.6**
        """
        with app.app_context():
            future_date = datetime.utcnow() + timedelta(days=30)
            task = Task(
                title="Future task",
                due_date=future_date,
                status="open",
                priority="medium",
                source="manual",
            )
            db.session.add(task)
            db.session.commit()
            task_id = task.id

            svc = TaskService()
            retrieved = svc.get(task_id)

            assert retrieved.status == "open", (
                f"Expected status='open' for future due_date, got '{retrieved.status}'"
            )

            db.session.rollback()

    def test_completed_task_with_past_due_date_stays_completed(self, app):
        """A completed task with a past due_date must NOT be changed to overdue.

        The overdue transition only applies when status is 'open'.

        **Validates: Requirements 3.6**
        """
        with app.app_context():
            past_date = datetime.utcnow() - timedelta(days=5)
            task = Task(
                title="Already done",
                due_date=past_date,
                status="completed",
                priority="low",
                source="manual",
                completion_timestamp=datetime.utcnow() - timedelta(days=3),
            )
            db.session.add(task)
            db.session.commit()
            task_id = task.id

            svc = TaskService()
            retrieved = svc.get(task_id)

            assert retrieved.status == "completed", (
                f"Expected status='completed' to be preserved, got '{retrieved.status}'"
            )

            db.session.rollback()

    def test_cancelled_task_with_past_due_date_stays_cancelled(self, app):
        """A cancelled task with a past due_date must NOT be changed to overdue.

        **Validates: Requirements 3.6**
        """
        with app.app_context():
            past_date = datetime.utcnow() - timedelta(days=2)
            task = Task(
                title="Cancelled task",
                due_date=past_date,
                status="cancelled",
                priority="low",
                source="manual",
            )
            db.session.add(task)
            db.session.commit()
            task_id = task.id

            svc = TaskService()
            retrieved = svc.get(task_id)

            assert retrieved.status == "cancelled", (
                f"Expected status='cancelled' to be preserved, got '{retrieved.status}'"
            )

            db.session.rollback()

    def test_no_due_date_task_never_becomes_overdue(self, app):
        """A task with no due_date must never be marked overdue.

        **Validates: Requirements 3.6**
        """
        with app.app_context():
            task = Task(
                title="No due date",
                due_date=None,
                status="open",
                priority="medium",
                source="manual",
            )
            db.session.add(task)
            db.session.commit()
            task_id = task.id

            svc = TaskService()
            retrieved = svc.get(task_id)

            assert retrieved.status == "open", (
                f"Expected status='open' for task with no due_date, got '{retrieved.status}'"
            )

            db.session.rollback()
