"""
Property-based tests for Lead Task and Call Log services.

Feature: actionable-lead-command-center
"""
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app.services.lead_task_service import LeadTaskService
from app.services.call_log_service import CallLogService
from app.exceptions import LeadTaskValidationError, InvalidTaskStatusTransitionError


# ---------------------------------------------------------------------------
# Helpers / mock factories
# ---------------------------------------------------------------------------

def make_mock_lead(lead_id=1, lead_status='active'):
    """Create a minimal mock Lead object."""
    lead = MagicMock()
    lead.id = lead_id
    lead.lead_status = lead_status
    lead.unanswered_call_count = 0
    lead.has_phone = True
    lead.last_contact_date = None
    return lead


def make_mock_task(task_id=1, lead_id=1, status='open', title='Test Task'):
    """Create a minimal mock LeadTask object."""
    task = MagicMock()
    task.id = task_id
    task.lead_id = lead_id
    task.status = status
    task.title = title
    task.task_type = 'custom'
    task.due_date = None
    task.completed_at = None
    return task


def make_mock_timeline_entry():
    """Create a minimal mock LeadTimelineEntry."""
    entry = MagicMock()
    entry.id = 1
    return entry


# ActionEngineService is imported lazily inside service methods, so we patch
# it at its source module to prevent real DB calls during tests.
_AES_PATCH = 'app.services.action_engine_service.ActionEngineService.recompute_and_persist'


# ---------------------------------------------------------------------------
# Property 4: Task Title Validation Boundary
# Feature: actionable-lead-command-center, Property 4: Task Title Validation Boundary
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(title=st.text(min_size=1, max_size=255))
def test_property_4_valid_title_accepted(title):
    """
    Property 4: Task Title Validation Boundary (valid case)
    Strings of length 1–255 (after strip) are accepted when non-empty after stripping.

    Validates: Requirements 3.2
    """
    # Feature: actionable-lead-command-center, Property 4: Task Title Validation Boundary
    assume(title.strip())  # must be non-empty after stripping

    service = LeadTaskService()
    mock_lead = make_mock_lead()
    mock_entry = make_mock_timeline_entry()

    with patch('app.services.lead_task_service.Lead') as MockLead, \
         patch('app.services.lead_task_service.LeadTask') as MockLeadTask, \
         patch('app.services.lead_task_service.LeadTimelineEntry') as MockEntry, \
         patch('app.services.lead_task_service.db') as mock_db, \
         patch(_AES_PATCH):

        MockLead.query.get.return_value = mock_lead
        mock_task_instance = make_mock_task(title=title.strip())
        MockLeadTask.return_value = mock_task_instance
        MockEntry.return_value = mock_entry
        mock_db.session = MagicMock()

        result = service.create(lead_id=1, data={'title': title}, actor='test')

        # Should succeed — no exception raised, task returned
        assert result is mock_task_instance


@settings(max_examples=100)
@given(title=st.text(min_size=256, max_size=500))
def test_property_4_title_too_long_rejected(title):
    """
    Property 4: Task Title Validation Boundary (too long)
    Strings of length > 255 are rejected with LeadTaskValidationError.
    Task list is unchanged after rejected creation.

    Validates: Requirements 3.2
    """
    # Feature: actionable-lead-command-center, Property 4: Task Title Validation Boundary
    service = LeadTaskService()
    mock_lead = make_mock_lead()

    with patch('app.services.lead_task_service.Lead') as MockLead, \
         patch('app.services.lead_task_service.db') as mock_db:

        MockLead.query.get.return_value = mock_lead
        mock_db.session = MagicMock()

        with pytest.raises(LeadTaskValidationError):
            service.create(lead_id=1, data={'title': title}, actor='test')

        # Task list unchanged: no commit should have occurred
        mock_db.session.commit.assert_not_called()


@settings(max_examples=100)
@given(title=st.one_of(
    st.just(''),
    st.text(max_size=50).filter(lambda s: not s.strip()),
))
def test_property_4_empty_title_rejected(title):
    """
    Property 4: Task Title Validation Boundary (empty)
    Empty strings (or whitespace-only) are rejected with LeadTaskValidationError.

    Validates: Requirements 3.2
    """
    # Feature: actionable-lead-command-center, Property 4: Task Title Validation Boundary
    assume(not title.strip())  # must be empty after stripping

    service = LeadTaskService()
    mock_lead = make_mock_lead()

    with patch('app.services.lead_task_service.Lead') as MockLead, \
         patch('app.services.lead_task_service.db') as mock_db:

        MockLead.query.get.return_value = mock_lead
        mock_db.session = MagicMock()

        with pytest.raises(LeadTaskValidationError):
            service.create(lead_id=1, data={'title': title}, actor='test')

        # Task list unchanged: no commit should have occurred
        mock_db.session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Property 5: Task State Machine Validity
# Feature: actionable-lead-command-center, Property 5: Task State Machine Validity
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(n=st.integers(min_value=0, max_value=100))
def test_property_5_open_to_completed_is_valid(n):
    """
    Property 5: Task State Machine Validity — open → completed is the only valid transition.

    Validates: Requirements 3.4, 21.5, 21.6
    """
    # Feature: actionable-lead-command-center, Property 5: Task State Machine Validity
    service = LeadTaskService()
    mock_task = make_mock_task(status='open')

    with patch('app.services.lead_task_service.LeadTask') as MockLeadTask, \
         patch('app.services.lead_task_service.LeadTimelineEntry') as MockEntry, \
         patch('app.services.lead_task_service.db') as mock_db, \
         patch(_AES_PATCH):

        MockLeadTask.query.filter_by.return_value.first.return_value = mock_task
        MockEntry.return_value = make_mock_timeline_entry()
        mock_db.session = MagicMock()

        result = service.complete(task_id=1, lead_id=1, actor='test')

        # Task should now be completed
        assert mock_task.status == 'completed'
        assert mock_task.completed_at is not None


@settings(max_examples=100)
@given(n=st.integers(min_value=0, max_value=100))
def test_property_5_completing_completed_task_is_noop(n):
    """
    Property 5: Task State Machine Validity — completing a completed task is a no-op.

    Validates: Requirements 3.4, 21.5, 21.6
    """
    # Feature: actionable-lead-command-center, Property 5: Task State Machine Validity
    service = LeadTaskService()
    mock_task = make_mock_task(status='completed')

    with patch('app.services.lead_task_service.LeadTask') as MockLeadTask, \
         patch('app.services.lead_task_service.db') as mock_db:

        MockLeadTask.query.filter_by.return_value.first.return_value = mock_task
        mock_db.session = MagicMock()

        result = service.complete(task_id=1, lead_id=1, actor='test')

        # Should return the task unchanged (no-op)
        assert result is mock_task
        assert mock_task.status == 'completed'
        # db.session.add should NOT have been called (no mutation)
        mock_db.session.add.assert_not_called()
        mock_db.session.commit.assert_not_called()


@settings(max_examples=100)
@given(n=st.integers(min_value=0, max_value=100))
def test_property_5_cancelled_task_cannot_be_completed(n):
    """
    Property 5: Task State Machine Validity — a cancelled task cannot be completed.
    Attempting to complete a 'cancelled' task raises InvalidTaskStatusTransitionError.

    Validates: Requirements 3.4, 21.5, 21.6
    """
    # Feature: actionable-lead-command-center, Property 5: Task State Machine Validity
    service = LeadTaskService()
    mock_task = make_mock_task(status='cancelled')

    with patch('app.services.lead_task_service.LeadTask') as MockLeadTask, \
         patch('app.services.lead_task_service.db') as mock_db:

        MockLeadTask.query.filter_by.return_value.first.return_value = mock_task
        mock_db.session = MagicMock()

        with pytest.raises(InvalidTaskStatusTransitionError):
            service.complete(task_id=1, lead_id=1, actor='test')


# ---------------------------------------------------------------------------
# Property 6: Task Snooze Date Validation
# Feature: actionable-lead-command-center, Property 6: Task Snooze Date Validation
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(days_ahead=st.integers(min_value=1, max_value=3650))
def test_property_6_future_date_accepted(days_ahead):
    """
    Property 6: Task Snooze Date Validation — dates strictly after today are accepted.
    due_date is updated to the new future date.

    Validates: Requirements 3.5
    """
    # Feature: actionable-lead-command-center, Property 6: Task Snooze Date Validation
    service = LeadTaskService()
    mock_task = make_mock_task(status='open')
    future_date = date.today() + timedelta(days=days_ahead)

    with patch('app.services.lead_task_service.LeadTask') as MockLeadTask, \
         patch('app.services.lead_task_service.LeadTimelineEntry') as MockEntry, \
         patch('app.services.lead_task_service.db') as mock_db:

        MockLeadTask.query.filter_by.return_value.first.return_value = mock_task
        MockEntry.return_value = make_mock_timeline_entry()
        mock_db.session = MagicMock()

        result = service.snooze(task_id=1, lead_id=1, new_due_date=future_date, actor='test')

        # due_date should be updated to the future date
        assert mock_task.due_date == future_date


@settings(max_examples=100)
@given(days_offset=st.integers(min_value=0, max_value=3650))
def test_property_6_today_or_past_date_rejected(days_offset):
    """
    Property 6: Task Snooze Date Validation — dates on or before today are rejected.
    due_date is unchanged after rejection.

    Validates: Requirements 3.5
    """
    # Feature: actionable-lead-command-center, Property 6: Task Snooze Date Validation
    service = LeadTaskService()
    original_due_date = date(2025, 1, 1)
    mock_task = make_mock_task(status='open')
    mock_task.due_date = original_due_date

    # date on or before today
    invalid_date = date.today() - timedelta(days=days_offset)

    with patch('app.services.lead_task_service.LeadTask') as MockLeadTask, \
         patch('app.services.lead_task_service.db') as mock_db:

        MockLeadTask.query.filter_by.return_value.first.return_value = mock_task
        mock_db.session = MagicMock()

        with pytest.raises(LeadTaskValidationError):
            service.snooze(task_id=1, lead_id=1, new_due_date=invalid_date, actor='test')

        # due_date must be unchanged
        assert mock_task.due_date == original_due_date


# ---------------------------------------------------------------------------
# Property 14: Unanswered Call Count Monotonically Increments
# Feature: actionable-lead-command-center, Property 14: Unanswered Call Count Monotonically Increments
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    n_calls=st.integers(min_value=1, max_value=20),
    outcome=st.sampled_from(['voicemail', 'no_answer']),
    initial_count=st.integers(min_value=0, max_value=100),
)
def test_property_14_unanswered_call_count_increments(n_calls, outcome, initial_count):
    """
    Property 14: Unanswered Call Count Monotonically Increments
    Logging N calls with outcome 'voicemail' or 'no_answer' increments
    unanswered_call_count by exactly N.

    Validates: Requirements 9.4
    """
    # Feature: actionable-lead-command-center, Property 14: Unanswered Call Count Monotonically Increments
    service = CallLogService()

    mock_lead = make_mock_lead()
    mock_lead.unanswered_call_count = initial_count

    with patch('app.services.call_log_service.Lead') as MockLead, \
         patch('app.services.call_log_service.LeadTimelineEntry') as MockEntry, \
         patch('app.services.call_log_service.db') as mock_db, \
         patch(_AES_PATCH):

        # Each call to Lead.query.get returns the same mock_lead so the
        # service mutates it in place across all N iterations.
        MockLead.query.get.return_value = mock_lead
        MockEntry.return_value = make_mock_timeline_entry()
        mock_db.session = MagicMock()

        # Log N calls — the real service code increments unanswered_call_count
        for _ in range(n_calls):
            service.log_call(
                lead_id=1,
                outcome=outcome,
                duration_minutes=None,
                notes=None,
                actor='test',
            )

        # unanswered_call_count should have incremented by exactly N
        expected_count = initial_count + n_calls
        assert mock_lead.unanswered_call_count == expected_count, (
            f"Expected unanswered_call_count={expected_count}, "
            f"got {mock_lead.unanswered_call_count} after {n_calls} '{outcome}' calls "
            f"(initial={initial_count})"
        )


# ---------------------------------------------------------------------------
# Property 15: Note Length Validation Boundary
# Feature: actionable-lead-command-center, Property 15: Note Length Validation Boundary
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(body=st.text(min_size=1, max_size=5000))
def test_property_15_valid_note_accepted(body):
    """
    Property 15: Note Length Validation Boundary (valid case)
    Strings of length 1–5,000 are accepted.

    Validates: Requirements 9.1
    """
    # Feature: actionable-lead-command-center, Property 15: Note Length Validation Boundary
    assume(body.strip())  # must be non-empty after stripping

    service = CallLogService()
    mock_lead = make_mock_lead()
    mock_entry = make_mock_timeline_entry()

    with patch('app.services.call_log_service.Lead') as MockLead, \
         patch('app.services.call_log_service.LeadTimelineEntry') as MockEntry, \
         patch('app.services.call_log_service.db') as mock_db, \
         patch(_AES_PATCH):

        MockLead.query.get.return_value = mock_lead
        MockEntry.return_value = mock_entry
        mock_db.session = MagicMock()

        result = service.log_note(lead_id=1, body=body, actor='test')

        # Should succeed — entry returned
        assert result is mock_entry


@settings(max_examples=100)
@given(extra_chars=st.integers(min_value=1, max_value=1000))
def test_property_15_note_too_long_rejected(extra_chars):
    """
    Property 15: Note Length Validation Boundary (too long)
    Strings exceeding 5,000 characters are rejected with LeadTaskValidationError.
    Timeline is unchanged after rejection.

    Validates: Requirements 9.1
    """
    # Feature: actionable-lead-command-center, Property 15: Note Length Validation Boundary
    # Build a string that is guaranteed to exceed 5,000 chars
    body = 'x' * (5000 + extra_chars)
    assert len(body) > 5000

    service = CallLogService()
    mock_lead = make_mock_lead()

    with patch('app.services.call_log_service.Lead') as MockLead, \
         patch('app.services.call_log_service.db') as mock_db:

        MockLead.query.get.return_value = mock_lead
        mock_db.session = MagicMock()

        with pytest.raises(LeadTaskValidationError):
            service.log_note(lead_id=1, body=body, actor='test')

        # Timeline unchanged: no commit should have occurred
        mock_db.session.commit.assert_not_called()


@settings(max_examples=100)
@given(body=st.one_of(
    st.just(''),
    st.text(max_size=50).filter(lambda s: not s.strip()),
))
def test_property_15_empty_note_rejected(body):
    """
    Property 15: Note Length Validation Boundary (empty)
    Empty strings are rejected with LeadTaskValidationError.
    Timeline is unchanged after rejection.

    Validates: Requirements 9.1
    """
    # Feature: actionable-lead-command-center, Property 15: Note Length Validation Boundary
    assume(not body.strip())

    service = CallLogService()
    mock_lead = make_mock_lead()

    with patch('app.services.call_log_service.Lead') as MockLead, \
         patch('app.services.call_log_service.db') as mock_db:

        MockLead.query.get.return_value = mock_lead
        mock_db.session = MagicMock()

        with pytest.raises(LeadTaskValidationError):
            service.log_note(lead_id=1, body=body, actor='test')

        # Timeline unchanged: no commit should have occurred
        mock_db.session.commit.assert_not_called()
