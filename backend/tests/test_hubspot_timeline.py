"""Property-based tests for TimelineService — Properties 7 and 8.

Properties verified:
  7. Timeline is always reverse chronological
  8. Timeline completeness

Both properties require the Flask app context and an in-memory SQLite database.
"""

import pytest
from datetime import datetime, timezone
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.interaction import Interaction
from app.models.interaction_association import InteractionAssociation
from app.models.task import Task
from app.models.task_association import TaskAssociation
from app.services.timeline_service import TimelineService


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_interaction(target_type: str, target_id: int, occurred_at: datetime,
                      source: str = 'manual') -> Interaction:
    """Create and persist an Interaction with one association."""
    interaction = Interaction(
        interaction_type='note',
        body='Test interaction body',
        occurred_at=occurred_at,
        source=source,
    )
    db.session.add(interaction)
    db.session.flush()  # get the id

    assoc = InteractionAssociation(
        interaction_id=interaction.id,
        target_type=target_type,
        target_id=target_id,
    )
    db.session.add(assoc)
    return interaction


def _make_task(target_type: str, target_id: int, due_date: datetime,
               source: str = 'manual') -> Task:
    """Create and persist a Task with one association."""
    task = Task(
        title='Test task title',
        due_date=due_date,
        status='open',
        priority='medium',
        source=source,
    )
    db.session.add(task)
    db.session.flush()  # get the id

    assoc = TaskAssociation(
        task_id=task.id,
        target_type=target_type,
        target_id=target_id,
    )
    db.session.add(assoc)
    return task


# ---------------------------------------------------------------------------
# Strategy: datetimes within a reasonable range (avoids SQLite overflow)
# ---------------------------------------------------------------------------

_datetime_strategy = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2099, 12, 31),
)


# ---------------------------------------------------------------------------
# Property 7: Timeline is Always Reverse Chronological
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 7: Timeline is always reverse chronological


class TestTimelineReverseChronological:
    """Property 7: get_timeline() always returns entries sorted descending by date.

    For any set of Interactions and Tasks associated with a given target,
    the timeline must return all entries sorted in descending order by their
    occurred_at (for Interactions) or due_date (for Tasks), with no gaps or
    reorderings.

    **Validates: Requirements 4.1, 2.6**
    """

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        interaction_dates=st.lists(_datetime_strategy, min_size=0, max_size=10),
        task_dates=st.lists(_datetime_strategy, min_size=0, max_size=10),
    )
    def test_timeline_is_reverse_chronological(
        self, app, interaction_dates: list, task_dates: list
    ) -> None:
        """Timeline entries are always sorted in descending date order.

        # Feature: hubspot-crm-migration, Property 7: Timeline is always reverse chronological
        **Validates: Requirements 4.1, 2.6**
        """
        with app.app_context():
            target_type = 'lead'
            # Use a large target_id to avoid collisions across hypothesis runs
            target_id = 999_001

            # Clean up any leftover records from previous runs
            _cleanup_target(target_type, target_id)

            # Create Interaction records
            for dt in interaction_dates:
                _make_interaction(target_type, target_id, dt)

            # Create Task records
            for dt in task_dates:
                _make_task(target_type, target_id, dt)

            db.session.commit()

            # Call the service
            service = TimelineService()
            timeline = service.get_timeline(target_type, target_id)

            # Extract dates from the result (only entries with non-None dates)
            dated_entries = [e for e in timeline if e['date'] is not None]
            dates = [e['date'] for e in dated_entries]

            # Verify descending order: each date must be >= the next
            for i in range(len(dates) - 1):
                assert dates[i] >= dates[i + 1], (
                    f"Timeline not in descending order at index {i}: "
                    f"{dates[i]} < {dates[i + 1]}\n"
                    f"Full date sequence: {dates}"
                )

            # Verify total count matches what we inserted
            total_inserted = len(interaction_dates) + len(task_dates)
            assert len(timeline) == total_inserted, (
                f"Expected {total_inserted} entries, got {len(timeline)}"
            )

            # Cleanup after test
            _cleanup_target(target_type, target_id)
            db.session.commit()


# ---------------------------------------------------------------------------
# Property 8: Timeline Completeness
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 8: Timeline completeness


class TestTimelineCompleteness:
    """Property 8: Timeline returns exactly K+M entries for K manual + M hubspot records.

    For any target with K manually-created records and M HubSpot-imported
    records, the timeline endpoint must return exactly K + M entries when no
    filters are applied.

    **Validates: Requirements 4.2**
    """

    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        k=st.integers(min_value=0, max_value=20),
        m=st.integers(min_value=0, max_value=20),
    )
    def test_timeline_completeness(self, app, k: int, m: int) -> None:
        """Timeline returns exactly K+M entries for K manual and M hubspot_import records.

        # Feature: hubspot-crm-migration, Property 8: Timeline completeness
        **Validates: Requirements 4.2**
        """
        with app.app_context():
            target_type = 'lead'
            # Use a distinct target_id to avoid collisions across hypothesis runs
            target_id = 999_002

            # Clean up any leftover records from previous runs
            _cleanup_target(target_type, target_id)

            base_dt = datetime(2024, 6, 15, 12, 0, 0)

            # Create K Interactions with source='manual'
            for i in range(k):
                dt = datetime(2024, 1, 1 + (i % 28))
                _make_interaction(target_type, target_id, dt, source='manual')

            # Create M Interactions with source='hubspot_import'
            for i in range(m):
                dt = datetime(2023, 1, 1 + (i % 28))
                _make_interaction(target_type, target_id, dt, source='hubspot_import')

            db.session.commit()

            # Call the service with no filters
            service = TimelineService()
            timeline = service.get_timeline(target_type, target_id)

            expected_count = k + m
            assert len(timeline) == expected_count, (
                f"Expected {expected_count} timeline entries (K={k} manual + M={m} hubspot), "
                f"but got {len(timeline)}"
            )

            # Cleanup after test
            _cleanup_target(target_type, target_id)
            db.session.commit()


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------

def _cleanup_target(target_type: str, target_id: int) -> None:
    """Remove all Interactions and Tasks associated with the given target."""
    # Find and delete interaction associations + interactions
    interaction_assocs = InteractionAssociation.query.filter_by(
        target_type=target_type, target_id=target_id
    ).all()
    interaction_ids = [a.interaction_id for a in interaction_assocs]
    for assoc in interaction_assocs:
        db.session.delete(assoc)
    if interaction_ids:
        Interaction.query.filter(Interaction.id.in_(interaction_ids)).delete(
            synchronize_session=False
        )

    # Find and delete task associations + tasks
    task_assocs = TaskAssociation.query.filter_by(
        target_type=target_type, target_id=target_id
    ).all()
    task_ids = [a.task_id for a in task_assocs]
    for assoc in task_assocs:
        db.session.delete(assoc)
    if task_ids:
        Task.query.filter(Task.id.in_(task_ids)).delete(synchronize_session=False)
