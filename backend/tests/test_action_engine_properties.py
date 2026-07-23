"""
Property-based tests for the Action Engine.

Feature: actionable-lead-command-center
"""
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from unittest.mock import MagicMock, patch

from app.services.action_engine_service import ActionEngineService


@pytest.fixture(autouse=True)
def _mock_action_engine_db(monkeypatch):
    """Avoid Flask app context in property-based unit tests."""

    def _flags(lead):
        return (
            bool(getattr(lead, 'has_phone', False)),
            bool(getattr(lead, 'has_email', False)),
            bool(getattr(lead, 'has_property_match', False)),
        )

    monkeypatch.setattr('app.services.lead_scoring_engine._resolve_crm_flags', _flags)
    monkeypatch.setattr(
        'app.services.lead_scoring_engine._has_overdue_lead_task',
        lambda _lead_id: False,
    )
    monkeypatch.setattr(
        'app.services.lead_scoring_engine.LeadScoringEngine._has_recent_email',
        staticmethod(lambda _lead_id: False),
    )
    monkeypatch.setattr(
        'app.services.lead_scoring_engine.is_mailable_lead',
        lambda _lead: False,
    )
    monkeypatch.setattr(
        'app.services.lead_scoring_engine._has_mailing_address',
        lambda lead: isinstance(getattr(lead, 'mailing_address', None), str)
        and bool(str(lead.mailing_address).strip()),
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

lead_status_strategy = st.sampled_from([
    'skip_trace', 'mailing_no_contact_made',
    'mailing_contacted_no_interest', 'mailing_contacted_interested',
    'negotiating_remote', 'in_person_appointment', 'offer_delivered',
    'deprioritize', 'deal_won', 'deal_lost', 'suppressed', 'do_not_contact',
])
active_lead_status_strategy = st.sampled_from([
    'skip_trace',
    'mailing_no_contact_made', 'mailing_contacted_no_interest',
    'mailing_contacted_interested', 'negotiating_remote',
    'in_person_appointment', 'offer_delivered',
])
bool_strategy = st.booleans()
score_strategy = st.floats(min_value=0, max_value=100, allow_nan=False)
completeness_strategy = st.floats(min_value=0, max_value=100, allow_nan=False)


def make_mock_lead(
    lead_status='mailing_no_contact_made',
    has_phone=True,
    has_email=True,
    has_property_match=True,
    analysis_complete=True,
    follow_up_overdue=False,
    is_warm=False,
    lead_score=50.0,
    data_completeness_score=60.0,
    property_street='123 Main St',
):
    """Create a mock Lead object with the given signal values."""
    lead = MagicMock()
    lead.id = 1
    lead.lead_status = lead_status
    lead.has_phone = has_phone
    lead.has_email = has_email
    lead.has_property_match = has_property_match
    lead.analysis_complete = analysis_complete
    lead.follow_up_overdue = follow_up_overdue
    lead.is_warm = is_warm
    lead.lead_score = lead_score
    lead.data_completeness_score = data_completeness_score
    lead.property_street = property_street
    lead.do_not_contact = False
    lead.suppression_flag = False
    lead.lead_category = 'residential'
    lead.unanswered_call_count = 0
    lead.acquisition_date = None
    lead.most_recent_sale = None
    lead.mailing_address = None
    lead.condo_risk_status = None
    lead.motivation_score = 0
    return lead


# ---------------------------------------------------------------------------
# Property 1: Active Lead Actionability Invariant
# Feature: actionable-lead-command-center, Property 1: Active Lead Actionability Invariant
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    lead_status=active_lead_status_strategy,
    has_phone=bool_strategy,
    has_email=bool_strategy,
    has_property_match=bool_strategy,
    analysis_complete=bool_strategy,
    follow_up_overdue=bool_strategy,
    is_warm=bool_strategy,
    lead_score=score_strategy,
    data_completeness_score=completeness_strategy,
    property_street=st.one_of(st.none(), st.just('123 Main St')),
    open_task_count=st.integers(min_value=0, max_value=5),
)
def test_property_1_active_lead_actionability_invariant(
    lead_status, has_phone, has_email, has_property_match, analysis_complete,
    follow_up_overdue, is_warm, lead_score, data_completeness_score,
    property_street, open_task_count,
):
    """
    Property 1: Active Lead Actionability Invariant
    For any lead with lead_status in (new, active, follow_up), after
    compute_recommended_action runs, recommended_action is non-null OR
    at least one open LeadTask exists.

    Validates: Requirements 1.1, 21.7
    """
    # Feature: actionable-lead-command-center, Property 1: Active Lead Actionability Invariant
    lead = make_mock_lead(
        lead_status=lead_status,
        has_phone=has_phone,
        has_email=has_email,
        has_property_match=has_property_match,
        analysis_complete=analysis_complete,
        follow_up_overdue=follow_up_overdue,
        is_warm=is_warm,
        lead_score=lead_score,
        data_completeness_score=data_completeness_score,
        property_street=property_street,
    )

    with patch('app.services.lead_scoring_engine._count_open_tasks', return_value=open_task_count):
        result = ActionEngineService.compute_recommended_action(lead)

    # Invariant: for active leads, RA must be non-null OR open tasks exist
    assert result is not None or open_task_count > 0, (
        f"Invariant violated: lead_status={lead_status}, result={result}, "
        f"open_task_count={open_task_count}"
    )


# ---------------------------------------------------------------------------
# Property 2: Action Engine Determinism
# Feature: actionable-lead-command-center, Property 2: Action Engine Determinism
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    lead_status=lead_status_strategy,
    has_phone=bool_strategy,
    has_email=bool_strategy,
    has_property_match=bool_strategy,
    analysis_complete=bool_strategy,
    follow_up_overdue=bool_strategy,
    is_warm=bool_strategy,
    lead_score=score_strategy,
    data_completeness_score=completeness_strategy,
    property_street=st.one_of(st.none(), st.just('123 Main St')),
    open_task_count=st.integers(min_value=0, max_value=5),
)
def test_property_2_action_engine_determinism(
    lead_status, has_phone, has_email, has_property_match, analysis_complete,
    follow_up_overdue, is_warm, lead_score, data_completeness_score,
    property_street, open_task_count,
):
    """
    Property 2: Action Engine Determinism
    For any combination of signal values, calling compute_recommended_action
    twice with identical inputs produces identical outputs.

    Validates: Requirements 2.2, 20.6
    """
    # Feature: actionable-lead-command-center, Property 2: Action Engine Determinism
    lead = make_mock_lead(
        lead_status=lead_status,
        has_phone=has_phone,
        has_email=has_email,
        has_property_match=has_property_match,
        analysis_complete=analysis_complete,
        follow_up_overdue=follow_up_overdue,
        is_warm=is_warm,
        lead_score=lead_score,
        data_completeness_score=data_completeness_score,
        property_street=property_street,
    )

    with patch('app.services.lead_scoring_engine._count_open_tasks', return_value=open_task_count):
        result_1 = ActionEngineService.compute_recommended_action(lead)
        result_2 = ActionEngineService.compute_recommended_action(lead)

    assert result_1 == result_2, (
        f"Non-determinism detected: first={result_1}, second={result_2}"
    )


# ---------------------------------------------------------------------------
# Property 3: Action Engine Priority Ordering
# Feature: actionable-lead-command-center, Property 3: Action Engine Priority Ordering
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    analysis_complete=bool_strategy,
    follow_up_overdue=bool_strategy,
    is_warm=bool_strategy,
    lead_score=score_strategy,
    data_completeness_score=completeness_strategy,
    property_street=st.one_of(st.none(), st.just('123 Main St')),
    open_task_count=st.integers(min_value=0, max_value=5),
)
def test_property_3_action_engine_priority_ordering(
    analysis_complete, follow_up_overdue, is_warm, lead_score,
    data_completeness_score, property_street, open_task_count,
):
    """
    Property 3: Action Engine Priority Ordering
    For any signal combination, compute_recommended_action returns the action
    corresponding to the first matching rule. No lower-priority rule fires when
    a higher-priority rule matches.

    Specifically: Priority 3 (no contact info → add_contact_info) fires before
    Priority 4 (no property match), Priority 5 (no analysis), etc. When both
    has_phone=False AND has_email=False, the result must always be 'add_contact_info'
    regardless of all other signal values.

    Validates: Requirements 16.1
    """
    # Feature: actionable-lead-command-center, Property 3: Action Engine Priority Ordering
    # Priority 3 (no contact info) should fire before Priority 4 (no property match)
    # when both conditions are true
    lead = make_mock_lead(
        lead_status='mailing_no_contact_made',
        has_phone=False,
        has_email=False,
        has_property_match=False,
        analysis_complete=analysis_complete,
        follow_up_overdue=follow_up_overdue,
        is_warm=is_warm,
        lead_score=lead_score,
        data_completeness_score=data_completeness_score,
        property_street=property_street,
    )

    with patch('app.services.lead_scoring_engine._count_open_tasks', return_value=open_task_count):
        result = ActionEngineService.compute_recommended_action(lead)

    # Priority 3 fires first: no phone AND no email → add_contact_info
    # This must hold regardless of has_property_match, analysis_complete, etc.
    assert result == 'add_contact_info', (
        f"Priority ordering violated: expected 'add_contact_info' when no phone/email, "
        f"got '{result}' (analysis_complete={analysis_complete}, "
        f"follow_up_overdue={follow_up_overdue}, is_warm={is_warm})"
    )


# ---------------------------------------------------------------------------
# Property 11: DNC Status Invariants
# Feature: actionable-lead-command-center, Property 11: DNC Status Invariants
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    has_phone=bool_strategy,
    has_email=bool_strategy,
    has_property_match=bool_strategy,
    analysis_complete=bool_strategy,
    follow_up_overdue=bool_strategy,
    is_warm=bool_strategy,
    lead_score=score_strategy,
    data_completeness_score=completeness_strategy,
)
def test_property_11_dnc_status_invariants(
    has_phone, has_email, has_property_match, analysis_complete,
    follow_up_overdue, is_warm, lead_score, data_completeness_score,
):
    """
    Property 11: DNC Status Invariants
    For any lead with lead_status='do_not_contact', recommended_action is
    do_not_contact regardless of all other signal values.

    Validates: Requirements 2.1, 5.4, 14.2, 21.2, 21.3
    """
    # Feature: actionable-lead-command-center, Property 11: DNC Status Invariants
    lead = make_mock_lead(
        lead_status='do_not_contact',
        has_phone=has_phone,
        has_email=has_email,
        has_property_match=has_property_match,
        analysis_complete=analysis_complete,
        follow_up_overdue=follow_up_overdue,
        is_warm=is_warm,
        lead_score=lead_score,
        data_completeness_score=data_completeness_score,
    )

    with patch('app.services.lead_scoring_engine._count_open_tasks', return_value=0):
        result = ActionEngineService.compute_recommended_action(lead)

    assert result == 'do_not_contact', (
        f"DNC invariant violated: expected do_not_contact for do_not_contact lead, got '{result}'"
    )


# ---------------------------------------------------------------------------
# Property 16: Action Engine Timeline Entry Idempotency
# Feature: actionable-lead-command-center, Property 16: Action Engine Timeline Entry Idempotency
# ---------------------------------------------------------------------------

@settings(max_examples=50)
@given(
    lead_status=active_lead_status_strategy,
    has_phone=bool_strategy,
    has_email=bool_strategy,
    has_property_match=bool_strategy,
    analysis_complete=bool_strategy,
    follow_up_overdue=bool_strategy,
    is_warm=bool_strategy,
    lead_score=score_strategy,
    data_completeness_score=completeness_strategy,
)
def test_property_16_action_engine_timeline_idempotency(
    lead_status, has_phone, has_email, has_property_match, analysis_complete,
    follow_up_overdue, is_warm, lead_score, data_completeness_score,
):
    """
    Property 16: Action Engine Timeline Entry Idempotency
    Running compute_recommended_action twice with no signal changes between runs
    produces the same result both times (the pure function is idempotent).

    This validates that recompute_and_persist would produce at most one
    recommended_action_changed timeline entry: the second call finds the same
    RA value and appends no new entry.

    Validates: Requirements 16.5
    """
    # Feature: actionable-lead-command-center, Property 16: Action Engine Timeline Entry Idempotency
    lead = make_mock_lead(
        lead_status=lead_status,
        has_phone=has_phone,
        has_email=has_email,
        has_property_match=has_property_match,
        analysis_complete=analysis_complete,
        follow_up_overdue=follow_up_overdue,
        is_warm=is_warm,
        lead_score=lead_score,
        data_completeness_score=data_completeness_score,
    )

    with patch('app.services.lead_scoring_engine._count_open_tasks', return_value=0):
        result_1 = ActionEngineService.compute_recommended_action(lead)
        result_2 = ActionEngineService.compute_recommended_action(lead)

    # The pure function must return the same value both times.
    # If result_1 == result_2, then recompute_and_persist would detect no change
    # on the second call and append zero new timeline entries.
    assert result_1 == result_2, (
        f"Idempotency violated: first call returned '{result_1}', "
        f"second call returned '{result_2}' with identical inputs"
    )


