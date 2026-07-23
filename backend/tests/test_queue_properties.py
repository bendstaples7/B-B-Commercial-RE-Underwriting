"""
Property-based tests for Queue filter logic.

Feature: actionable-lead-command-center

These tests validate the queue membership predicates as pure Python functions,
extracted from QueueService's SQL filter logic. This avoids needing a live
database while still verifying the correctness of the filter rules.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Pure-Python queue membership predicates
# (mirror the SQL filter logic in QueueService exactly)
# ---------------------------------------------------------------------------

def is_in_todays_action(lead_status, recommended_action, open_task_due_today):
    """Today's Action: lead_status in active pipeline statuses AND
    an open task has due_date <= today (recommended_action alone is not enough).

    Undated skip-trace handoffs stay out via null due_date; dated due chores
    on skip_trace can appear until promote heals them.
    """
    _TODAYS_ACTION_STATUSES = {
        'mailing_no_contact_made', 'mailing_contacted_no_interest',
        'mailing_contacted_interested', 'negotiating_remote',
        'in_person_appointment', 'offer_delivered',
        'skip_trace',
    }
    return lead_status in _TODAYS_ACTION_STATUSES and open_task_due_today


def is_in_previously_warm(lead_status, has_hubspot_activity, recent_platform_contact):
    """Previously Warm: is_warm=True (checked via has_hubspot_activity proxy here)
    and lead is in an active pipeline status.
    """
    _PREVIOUSLY_WARM_STATUSES = {
        'skip_trace', 'mailing_no_contact_made',
        'mailing_contacted_no_interest', 'mailing_contacted_interested',
        'negotiating_remote', 'in_person_appointment', 'offer_delivered',
    }
    return (
        has_hubspot_activity
        and lead_status in _PREVIOUSLY_WARM_STATUSES
        and not recent_platform_contact
    )


def is_in_follow_up_overdue(recommended_action, last_contact_date, open_task_overdue, today=None):
    """Follow-Up Overdue: open task with due_date in the past OR
    (recommended_action = 'follow_up_now' AND last_contact_date < 7 days ago).
    """
    if today is None:
        today = date.today()
    seven_days_ago = today - timedelta(days=7)
    return (
        open_task_overdue
        or (
            recommended_action == 'follow_up_now'
            and last_contact_date is not None
            and last_contact_date < seven_days_ago
        )
    )


def is_in_no_next_action(lead_status, recommended_action, has_open_tasks):
    """No Next Action: lead_status in active pipeline statuses AND
    recommended_action in (null, 'create_task', 'ready_for_outreach', 'add_contact_info')
    AND no open tasks.
    """
    _NNA_STATUSES = {
        'skip_trace', 'mailing_no_contact_made',
        'mailing_contacted_no_interest', 'mailing_contacted_interested',
        'negotiating_remote', 'in_person_appointment', 'offer_delivered',
    }
    return (
        lead_status in _NNA_STATUSES
        and recommended_action in (None, 'create_task', 'ready_for_outreach', 'add_contact_info')
        and not has_open_tasks
    )


def is_in_needs_review(review_required):
    """Needs Review: review_required = true."""
    return review_required is True


def is_in_do_not_contact(lead_status):
    """Do Not Contact: lead_status = 'do_not_contact'."""
    return lead_status == 'do_not_contact'


def is_in_missing_property_match(has_property_match, has_research_task):
    """Missing Property Match: has_property_match = false AND
    no open research_missing_pin task exists.
    """
    return not has_property_match and not has_research_task


# ---------------------------------------------------------------------------
# Active work queues (all queues except Do Not Contact)
# ---------------------------------------------------------------------------

def is_in_any_active_work_queue(
    lead_status,
    recommended_action,
    open_task_due_today,
    has_hubspot_activity,
    recent_platform_contact,
    open_task_overdue,
    last_contact_date,
    has_open_tasks,
    review_required,
    has_property_match,
    has_research_task,
    today=None,
):
    """Returns True if the lead appears in any active work queue
    (Today's Action, Previously Warm, Follow-Up Overdue, No Next Action,
    Needs Review, Missing Property Match).
    Do Not Contact queue is excluded from "active work queues" per Req 5.7.
    """
    return (
        is_in_todays_action(lead_status, recommended_action, open_task_due_today)
        or is_in_previously_warm(lead_status, has_hubspot_activity, recent_platform_contact)
        or is_in_follow_up_overdue(recommended_action, last_contact_date, open_task_overdue, today)
        or is_in_no_next_action(lead_status, recommended_action, has_open_tasks)
        or is_in_needs_review(review_required)
        or is_in_missing_property_match(has_property_match, has_research_task)
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

all_lead_statuses = st.sampled_from([
    'skip_trace', 'mailing_no_contact_made',
    'mailing_contacted_no_interest', 'mailing_contacted_interested',
    'negotiating_remote', 'in_person_appointment', 'offer_delivered',
    'deprioritize', 'deal_won', 'deal_lost', 'suppressed', 'do_not_contact',
])

all_recommended_actions = st.one_of(
    st.none(),
    st.sampled_from([
        'enrich_data', 'resolve_match', 'analyze_property', 'follow_up_now',
        'ready_for_outreach', 'add_contact_info', 'create_task', 'nurture',
        'suppress', 'do_not_contact',
    ]),
)

bool_strategy = st.booleans()

# Generate dates relative to today for last_contact_date
date_strategy = st.one_of(
    st.none(),
    st.dates(
        min_value=date(2020, 1, 1),
        max_value=date.today() + timedelta(days=30),
    ),
)


# ---------------------------------------------------------------------------
# Property 9: Suppressed/Nurture/DNC Queue Exclusion
# Feature: actionable-lead-command-center, Property 9: Suppressed/Nurture/DNC Queue Exclusion
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    recommended_action=all_recommended_actions,
    open_task_due_today=bool_strategy,
    has_hubspot_activity=bool_strategy,
    recent_platform_contact=bool_strategy,
    open_task_overdue=bool_strategy,
    last_contact_date=date_strategy,
    has_open_tasks=bool_strategy,
    review_required=bool_strategy,
    has_property_match=bool_strategy,
    has_research_task=bool_strategy,
)
def test_property_9_suppressed_nurture_dnc_queue_exclusion(
    recommended_action,
    open_task_due_today,
    has_hubspot_activity,
    recent_platform_contact,
    open_task_overdue,
    last_contact_date,
    has_open_tasks,
    review_required,
    has_property_match,
    has_research_task,
):
    """
    Property 9: Suppressed/Nurture/DNC Queue Exclusion

    Part A: Leads with lead_status='deprioritize' do NOT appear in:
      - Previously Warm Queue
      - Follow-Up Overdue Queue
      - No Next Action Queue

    Part B: Leads with lead_status in ('suppressed', 'do_not_contact') do NOT
    appear in any active work queue (Today's Action, Previously Warm,
    Follow-Up Overdue, No Next Action, Needs Review, Missing Property Match).

    Validates: Requirements 5.6, 5.7
    """
    # Feature: actionable-lead-command-center, Property 9: Suppressed/Nurture/DNC Queue Exclusion
    today = date.today()

    # --- Part A: deprioritize leads excluded from 3 specific queues ---
    nurture_in_previously_warm = is_in_previously_warm(
        'deprioritize', has_hubspot_activity, recent_platform_contact
    )
    assert not nurture_in_previously_warm, (
        f"Deprioritize lead appeared in Previously Warm queue: "
        f"has_hubspot_activity={has_hubspot_activity}, "
        f"recent_platform_contact={recent_platform_contact}"
    )

    nurture_in_no_next_action = is_in_no_next_action(
        'deprioritize', recommended_action, has_open_tasks
    )
    assert not nurture_in_no_next_action, (
        f"Deprioritize lead appeared in No Next Action queue: "
        f"recommended_action={recommended_action}, has_open_tasks={has_open_tasks}"
    )

    # --- Part B: suppressed and do_not_contact excluded from all active work queues ---
    for excluded_status in ('suppressed', 'do_not_contact'):
        # Today's Action requires lead_status in (active, follow_up) — excluded
        in_todays_action = is_in_todays_action(
            excluded_status, recommended_action, open_task_due_today
        )
        assert not in_todays_action, (
            f"Lead with status='{excluded_status}' appeared in Today's Action queue: "
            f"recommended_action={recommended_action}, open_task_due_today={open_task_due_today}"
        )

        # Previously Warm requires lead_status in (active, new) — excluded
        in_previously_warm = is_in_previously_warm(
            excluded_status, has_hubspot_activity, recent_platform_contact
        )
        assert not in_previously_warm, (
            f"Lead with status='{excluded_status}' appeared in Previously Warm queue: "
            f"has_hubspot_activity={has_hubspot_activity}"
        )

        # No Next Action requires lead_status in (active, new) — excluded
        in_no_next_action = is_in_no_next_action(
            excluded_status, recommended_action, has_open_tasks
        )
        assert not in_no_next_action, (
            f"Lead with status='{excluded_status}' appeared in No Next Action queue: "
            f"recommended_action={recommended_action}, has_open_tasks={has_open_tasks}"
        )


# ---------------------------------------------------------------------------
# Property 10: Queue Membership is a Pure Function of Lead State
# Feature: actionable-lead-command-center, Property 10: Queue Membership is a Pure Function of Lead State
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    lead_status=all_lead_statuses,
    recommended_action=all_recommended_actions,
    open_task_due_today=bool_strategy,
    has_hubspot_activity=bool_strategy,
    recent_platform_contact=bool_strategy,
    open_task_overdue=bool_strategy,
    last_contact_date=date_strategy,
    has_open_tasks=bool_strategy,
    review_required=bool_strategy,
    has_property_match=bool_strategy,
    has_research_task=bool_strategy,
)
def test_property_10_queue_membership_pure_function_of_lead_state(
    lead_status,
    recommended_action,
    open_task_due_today,
    has_hubspot_activity,
    recent_platform_contact,
    open_task_overdue,
    last_contact_date,
    has_open_tasks,
    review_required,
    has_property_match,
    has_research_task,
):
    """
    Property 10: Queue Membership is a Pure Function of Lead State

    For any lead, its membership in each of the 7 queues is fully determined
    by its current state. Calling the membership predicate twice with identical
    inputs produces identical outputs (determinism). A lead satisfying multiple
    criteria appears in each applicable queue exactly once per queue.

    Queue membership criteria (from design.md):
    - Today's Action: lead_status in active pipeline AND open task due_date <= today
    - Previously Warm: has_hubspot_activity AND lead_status in (active, new)
        AND no recent platform contact (90 days)
    - Follow-Up Overdue: open task overdue OR
        (recommended_action = 'follow_up_now' AND last_contact_date > 7 days ago)
    - No Next Action: lead_status in (active, new) AND
        recommended_action in (null, 'create_task') AND no open tasks
    - Needs Review: review_required = true
    - Do Not Contact: lead_status = 'do_not_contact'
    - Missing Property Match: has_property_match = false AND no research task

    Validates: Requirements 6.3–6.9, 22.6
    """
    # Feature: actionable-lead-command-center, Property 10: Queue Membership is a Pure Function of Lead State
    today = date.today()

    # Compute membership for all 7 queues
    in_todays_action = is_in_todays_action(lead_status, recommended_action, open_task_due_today)
    in_previously_warm = is_in_previously_warm(lead_status, has_hubspot_activity, recent_platform_contact)
    in_follow_up_overdue = is_in_follow_up_overdue(recommended_action, last_contact_date, open_task_overdue, today)
    in_no_next_action = is_in_no_next_action(lead_status, recommended_action, has_open_tasks)
    in_needs_review = is_in_needs_review(review_required)
    in_do_not_contact = is_in_do_not_contact(lead_status)
    in_missing_property_match = is_in_missing_property_match(has_property_match, has_research_task)

    # --- Determinism: calling the same predicate twice yields the same result ---
    assert is_in_todays_action(lead_status, recommended_action, open_task_due_today) == in_todays_action
    assert is_in_previously_warm(lead_status, has_hubspot_activity, recent_platform_contact) == in_previously_warm
    assert is_in_follow_up_overdue(recommended_action, last_contact_date, open_task_overdue, today) == in_follow_up_overdue
    assert is_in_no_next_action(lead_status, recommended_action, has_open_tasks) == in_no_next_action
    assert is_in_needs_review(review_required) == in_needs_review
    assert is_in_do_not_contact(lead_status) == in_do_not_contact
    assert is_in_missing_property_match(has_property_match, has_research_task) == in_missing_property_match

    # --- Structural invariants ---

    # Today's Action requires specific active pipeline statuses
    _TODAYS_ACTION_STATUSES = {
        'mailing_no_contact_made', 'mailing_contacted_no_interest',
        'mailing_contacted_interested', 'negotiating_remote',
        'in_person_appointment', 'offer_delivered',
        'skip_trace',
    }
    if in_todays_action:
        assert lead_status in _TODAYS_ACTION_STATUSES, (
            f"Today's Action contains lead with status='{lead_status}'"
        )
        assert open_task_due_today, (
            f"Today's Action contains lead with no due task: "
            f"recommended_action={recommended_action}, open_task_due_today={open_task_due_today}"
        )

    # Previously Warm requires active pipeline status AND hubspot activity
    _PREVIOUSLY_WARM_STATUSES = {
        'skip_trace', 'mailing_no_contact_made',
        'mailing_contacted_no_interest', 'mailing_contacted_interested',
        'negotiating_remote', 'in_person_appointment', 'offer_delivered',
    }
    if in_previously_warm:
        assert lead_status in _PREVIOUSLY_WARM_STATUSES, (
            f"Previously Warm contains lead with status='{lead_status}'"
        )
        assert has_hubspot_activity, (
            f"Previously Warm contains lead with no HubSpot activity"
        )
        assert not recent_platform_contact, (
            f"Previously Warm contains lead with recent platform contact"
        )

    # No Next Action requires active pipeline status
    _NNA_STATUSES = {
        'skip_trace', 'mailing_no_contact_made',
        'mailing_contacted_no_interest', 'mailing_contacted_interested',
        'negotiating_remote', 'in_person_appointment', 'offer_delivered',
    }
    if in_no_next_action:
        assert lead_status in _NNA_STATUSES, (
            f"No Next Action contains lead with status='{lead_status}'"
        )
        assert recommended_action in (None, 'create_task', 'ready_for_outreach', 'add_contact_info'), (
            f"No Next Action contains lead with recommended_action='{recommended_action}'"
        )
        assert not has_open_tasks, (
            f"No Next Action contains lead with open tasks"
        )

    # Do Not Contact is exclusively for do_not_contact status
    if in_do_not_contact:
        assert lead_status == 'do_not_contact', (
            f"Do Not Contact queue contains lead with status='{lead_status}'"
        )

    # Missing Property Match requires no property match AND no research task
    if in_missing_property_match:
        assert not has_property_match, (
            f"Missing Property Match contains lead with has_property_match=True"
        )
        assert not has_research_task, (
            f"Missing Property Match contains lead with existing research task"
        )

    # Needs Review is purely driven by review_required flag
    if in_needs_review:
        assert review_required is True, (
            f"Needs Review contains lead with review_required={review_required}"
        )

    # --- Multi-queue membership: a lead CAN appear in multiple queues ---
    # This is expected behavior per Req 6.11 — no assertion needed to prevent it.
    # We just verify the count is consistent (each queue counts the lead at most once).
    queue_memberships = [
        in_todays_action,
        in_previously_warm,
        in_follow_up_overdue,
        in_no_next_action,
        in_needs_review,
        in_do_not_contact,
        in_missing_property_match,
    ]
    membership_count = sum(queue_memberships)
    # A lead can be in 0 to 7 queues — all values are valid
    assert 0 <= membership_count <= 7, (
        f"Unexpected membership count: {membership_count}"
    )

    # --- Exclusivity invariant: suppressed/DNC leads not in active work queues ---
    if lead_status in ('suppressed', 'do_not_contact'):
        assert not in_todays_action, (
            f"Suppressed/DNC lead in Today's Action: status='{lead_status}'"
        )
        assert not in_previously_warm, (
            f"Suppressed/DNC lead in Previously Warm: status='{lead_status}'"
        )
        assert not in_no_next_action, (
            f"Suppressed/DNC lead in No Next Action: status='{lead_status}'"
        )

    # --- Nurture (deprioritize) exclusion from 3 specific queues ---
    if lead_status == 'deprioritize':
        assert not in_previously_warm, (
            "Deprioritize lead in Previously Warm queue"
        )
        assert not in_no_next_action, (
            "Deprioritize lead in No Next Action queue"
        )
        assert not in_todays_action, (
            "Deprioritize lead in Today's Action queue"
        )


# ---------------------------------------------------------------------------
# Property 4: Warm signal processing sets is_warm = True (one-way)
# Feature: source-agnostic-crm-queues, Property 4: warm signal sets is_warm (one-way)
# ---------------------------------------------------------------------------

# Signal types that mark a lead as warm — mirrors WARM_SIGNAL_TYPES in hubspot_tasks.py
_WARM_SIGNAL_TYPES = frozenset({'PRIOR_WARM_CONVERSATION', 'APPOINTMENT_OCCURRED'})

# All signal types the extractor can produce (warm + non-warm)
_ALL_SIGNAL_TYPES = [
    'PRIOR_WARM_CONVERSATION',
    'APPOINTMENT_OCCURRED',
    'DO_NOT_CONTACT',
    'WRONG_NUMBER',
    'EMAIL_OPEN',
    'FORM_SUBMISSION',
    'MEETING_SCHEDULED',
    'CALL_LOGGED',
    'NOTE_ADDED',
]


def _apply_warm_signal_logic(signals_batch: list[str], initial_is_warm: bool) -> bool:
    """Pure-Python extraction of the is_warm flag logic from run_extract_hubspot_signals.

    Given a list of signal_type strings for one interaction batch and the lead's
    initial is_warm value, returns the resulting is_warm value after processing.

    This mirrors the guarded block in hubspot_tasks.py:
        warm_signals = [s for s in signals if s.signal_type in WARM_SIGNAL_TYPES]
        if warm_signals:
            if lead_obj is not None and not lead_obj.is_warm:
                lead_obj.is_warm = True
    """
    has_warm_signal = any(sig in _WARM_SIGNAL_TYPES for sig in signals_batch)
    if has_warm_signal and not initial_is_warm:
        return True
    # No warm signal → unchanged; already warm → unchanged (one-way)
    return initial_is_warm


# Hypothesis strategy: a list of 0–10 signal types drawn from all known types
signal_batch_strategy = st.lists(
    st.sampled_from(_ALL_SIGNAL_TYPES),
    min_size=0,
    max_size=10,
)


@settings(max_examples=100)
@given(
    signals_batch=signal_batch_strategy,
    initial_is_warm=st.booleans(),
)
def test_property_4_warm_signal_sets_is_warm(signals_batch, initial_is_warm):
    """
    Property 4: Warm signal processing sets is_warm = True (one-way)

    For any lead processed by the HubSpot signal pipeline:
    1. is_warm=True after processing iff any signal in the batch is
       PRIOR_WARM_CONVERSATION or APPOINTMENT_OCCURRED (or was already True).
    2. If no warm signals are present, is_warm is unchanged.
    3. A lead that already had is_warm=True is NEVER set to False (one-way flag).

    The warm signal logic is extracted from run_extract_hubspot_signals in
    backend/app/tasks/hubspot_tasks.py and tested as a pure function so that
    db.session calls are not needed (full Celery task tested separately).

    Validates: Requirements 4.3, 9.1, 9.2, 9.3
    """
    # Feature: source-agnostic-crm-queues, Property 4: warm signal sets is_warm (one-way)

    has_warm_signal = any(sig in _WARM_SIGNAL_TYPES for sig in signals_batch)
    result_is_warm = _apply_warm_signal_logic(signals_batch, initial_is_warm)

    # --- Req 9.1: warm signal present → is_warm must be True after processing ---
    if has_warm_signal:
        assert result_is_warm is True, (
            f"Warm signal in batch but is_warm not set to True: "
            f"signals={signals_batch}, initial_is_warm={initial_is_warm}, "
            f"result={result_is_warm}"
        )

    # --- Req 9.2: no warm signal → is_warm unchanged ---
    if not has_warm_signal:
        assert result_is_warm == initial_is_warm, (
            f"No warm signals but is_warm changed: "
            f"signals={signals_batch}, initial_is_warm={initial_is_warm}, "
            f"result={result_is_warm}"
        )

    # --- Req 9.3: one-way flag — True is never set back to False ---
    if initial_is_warm:
        assert result_is_warm is True, (
            f"is_warm was True before processing but is False after: "
            f"signals={signals_batch}, initial_is_warm={initial_is_warm}, "
            f"result={result_is_warm}"
        )

    # --- Req 4.3 cross-check: result is True iff (warm signal present OR was already warm) ---
    expected = has_warm_signal or initial_is_warm
    assert result_is_warm == expected, (
        f"is_warm result does not match expected: "
        f"signals={signals_batch}, initial_is_warm={initial_is_warm}, "
        f"has_warm_signal={has_warm_signal}, expected={expected}, result={result_is_warm}"
    )


# ---------------------------------------------------------------------------
# Property 1: No Next Action filter predicate (source-agnostic-crm-queues)
# Feature: source-agnostic-crm-queues, Property 1: No Next Action filter predicate
# ---------------------------------------------------------------------------

# All valid lead statuses and recommended_action values for Property 1
_NNA_LEAD_STATUSES = [
    'skip_trace', 'mailing_no_contact_made',
    'mailing_contacted_no_interest', 'mailing_contacted_interested',
    'negotiating_remote', 'in_person_appointment', 'offer_delivered',
    'deprioritize', 'deal_won', 'deal_lost', 'suppressed', 'do_not_contact',
]
_NNA_RECOMMENDED_ACTIONS = [
    None,
    'enrich_data',
    'resolve_match',
    'analyze_property',
    'follow_up_now',
    'ready_for_outreach',
    'add_contact_info',
    'create_task',
    'nurture',
    'suppress',
    'do_not_contact',
]

# Task presence variants:
#   'none'          — no tasks at all
#   'open_lead'     — one open LeadTask
#   'open_assoc'    — one open Task linked via TaskAssociation
#   'open_direct'   — one open Task linked via Task.lead_id
#   'closed_lead'   — only completed LeadTask (should not block No Next Action)
_TASK_VARIANTS = ['none', 'open_lead', 'open_assoc', 'open_direct', 'closed_lead']

_nna_status_st = st.sampled_from(_NNA_LEAD_STATUSES)
_nna_action_st = st.sampled_from(_NNA_RECOMMENDED_ACTIONS)
_task_variant_st = st.sampled_from(_TASK_VARIANTS)

# Expected No Next Action include criteria (mirrors the updated QueueService).
# Active-pipeline statuses that can appear in No Next Action when there's
# no specific recommended action and no open tasks.
_NNA_ALLOWED_ACTIONS = {None, 'create_task', 'ready_for_outreach', 'add_contact_info'}
_NNA_ALLOWED_STATUSES = {
    'skip_trace', 'mailing_no_contact_made',
    'mailing_contacted_no_interest', 'mailing_contacted_interested',
    'negotiating_remote', 'in_person_appointment', 'offer_delivered',
}
# Only open LeadTask rows exclude No Next Action; CRM Task mirrors do not.
_OPEN_TASK_VARIANTS = {'open_lead'}


def _expected_in_nna(lead_status: str, recommended_action, task_variant: str) -> bool:
    """Pure-Python reference predicate for No Next Action (LeadTask-only)."""
    return (
        lead_status in _NNA_ALLOWED_STATUSES
        and recommended_action in _NNA_ALLOWED_ACTIONS
        and task_variant not in _OPEN_TASK_VARIANTS
    )


def _seed_nna_lead(db_session, lead_status: str, recommended_action, task_variant: str, idx: int):
    """Seed a single Lead with the given parameters and a unique street address."""
    from app.models import Lead, LeadTask, Task, TaskAssociation

    lead = Lead(
        property_street=f'{1000 + idx} Test St NNA {lead_status} {recommended_action} {task_variant}',
        lead_status=lead_status,
        recommended_action=recommended_action,
    )
    db_session.add(lead)
    db_session.flush()  # get lead.id

    if task_variant == 'open_lead':
        task = LeadTask(
            lead_id=lead.id,
            task_type='custom',
            title='Open CRM task',
            status='open',
        )
        db_session.add(task)

    elif task_variant == 'open_assoc':
        t = Task(
            title='Open HubSpot task via assoc',
            status='open',
        )
        db_session.add(t)
        db_session.flush()
        assoc = TaskAssociation(
            task_id=t.id,
            target_type='lead',
            target_id=lead.id,
        )
        db_session.add(assoc)

    elif task_variant == 'open_direct':
        t = Task(
            title='Open task direct lead_id',
            status='open',
            lead_id=lead.id,
        )
        db_session.add(t)

    elif task_variant == 'closed_lead':
        task = LeadTask(
            lead_id=lead.id,
            task_type='custom',
            title='Completed CRM task',
            status='completed',
        )
        db_session.add(task)

    # 'none' variant: no tasks created

    db_session.flush()
    return lead.id


_nna_seed_counter = 0


@pytest.mark.usefixtures('app')
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    lead_status=_nna_status_st,
    recommended_action=_nna_action_st,
    task_variant=_task_variant_st,
)
def test_property_1_no_next_action_filter_predicate(
    app,
    lead_status,
    recommended_action,
    task_variant,
):
    """
    # Feature: source-agnostic-crm-queues, Property 1: No Next Action filter predicate

    For any lead in the database, it appears in No Next Action iff:
      - lead_status in the active pipeline allow-list AND
      - recommended_action in (None, 'create_task', 'ready_for_outreach', 'add_contact_info') AND
      - has no open LeadTask (CRM Task / TaskAssociation mirrors do not count)

    Validates: Requirements 1.1, 1.3, 1.4
    """
    global _nna_seed_counter
    from app import db as _db
    from app.services.queue_service import QueueService

    with app.app_context():
        # Use a monotonically increasing counter to guarantee unique street addresses
        # across all Hypothesis examples (id() of tuples can be reused by CPython).
        _nna_seed_counter += 1
        lead_id = _seed_nna_lead(_db.session, lead_status, recommended_action, task_variant, _nna_seed_counter)
        # Use flush (not commit) so the subsequent rollback actually removes the seeded data.
        _db.session.flush()

        try:
            # Query No Next Action queue — no owner scoping so all leads visible
            service = QueueService(owner_user_id=None)
            rows, total = service.get_no_next_action(page=1, per_page=10000)
            result_ids = {row['id'] for row in rows}

            expected = _expected_in_nna(lead_status, recommended_action, task_variant)

            if expected:
                assert lead_id in result_ids, (
                    f"Lead {lead_id} EXPECTED in No Next Action but NOT found. "
                    f"lead_status={lead_status!r}, recommended_action={recommended_action!r}, "
                    f"task_variant={task_variant!r}"
                )
            else:
                assert lead_id not in result_ids, (
                    f"Lead {lead_id} NOT expected in No Next Action but WAS found. "
                    f"lead_status={lead_status!r}, recommended_action={recommended_action!r}, "
                    f"task_variant={task_variant!r}"
                )
        finally:
            # Clean up all seeded data so each Hypothesis example starts fresh
            _db.session.rollback()


# ---------------------------------------------------------------------------
# Imports needed for Property 2 (DB-backed test)
# ---------------------------------------------------------------------------
import os
import unittest

from hypothesis import HealthCheck

from app import create_app, db
from app.models import Lead
from app.services.queue_service import QueueService


# ---------------------------------------------------------------------------
# Property 2: Badge counts equal paginated totals
# Feature: source-agnostic-crm-queues, Property 2: badge counts equal paginated totals
# ---------------------------------------------------------------------------

# Strategies for lead field values
_lead_statuses = st.sampled_from([
    'skip_trace', 'mailing_no_contact_made',
    'mailing_contacted_no_interest', 'mailing_contacted_interested',
    'negotiating_remote', 'in_person_appointment', 'offer_delivered',
    'deprioritize', 'deal_won', 'deal_lost', 'suppressed', 'do_not_contact',
])

_recommended_actions = st.one_of(
    st.none(),
    st.sampled_from([
        'enrich_data', 'resolve_match', 'analyze_property', 'follow_up_now',
        'ready_for_outreach', 'add_contact_info', 'create_task', 'nurture',
        'suppress', 'do_not_contact',
    ]),
)

_lead_record = st.fixed_dictionaries({
    'lead_status':         _lead_statuses,
    'recommended_action':  _recommended_actions,
    'is_warm':             st.booleans(),
    'review_required':     st.booleans(),
    'has_property_match':  st.booleans(),
    'needs_skip_trace':    st.booleans(),
    'skip_trace_exhausted': st.booleans(),
})


@pytest.mark.usefixtures('app')
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(lead_dicts=st.lists(_lead_record, min_size=0, max_size=20))
def test_property_2_badge_counts_equal_paginated_totals(app, lead_dicts):
    """
    Property 2: Badge counts equal paginated totals.

    For any state of the leads table, QueueService.get_counts() returns a count
    for each queue that equals the `total` value returned by the
    corresponding paginated get_* method called with no pagination constraints.

    # Feature: source-agnostic-crm-queues, Property 2: badge counts equal paginated totals

    Validates: Requirements 1.5, 2.3, 3.4, 4.5, 5.5, 6.5, 12.1
    """
    with app.app_context():
        try:
            # Seed the database with the Hypothesis-generated lead population
            from datetime import datetime, timezone

            for i, ld in enumerate(lead_dicts):
                lead = Lead(
                    property_street=f'{i} Property 2 Test St',
                    lead_status=ld['lead_status'],
                    recommended_action=ld['recommended_action'],
                    is_warm=ld['is_warm'],
                    review_required=ld['review_required'],
                    has_property_match=ld['has_property_match'],
                    needs_skip_trace=(
                        True if ld['lead_status'] == 'skip_trace' and ld['needs_skip_trace']
                        else False
                    ),
                    skip_trace_exhausted_at=(
                        datetime.now(timezone.utc) if ld['skip_trace_exhausted'] else None
                    ),
                    lead_score=50.0,
                    has_phone=False,
                    has_email=False,
                    analysis_complete=False,
                    follow_up_overdue=False,
                    data_completeness_score=0.0,
                    unanswered_call_count=0,
                )
                db.session.add(lead)
            # Flush (not commit) so the per-example rollback in the finally
            # discards the seeded rows; this keeps the in-memory DB and the
            # SQLAlchemy identity map from accumulating across Hypothesis examples.
            db.session.flush()

            svc = QueueService()
            counts = svc.get_counts()

            # Assert get_counts() == total from each paginated method for all 7 queues
            _, total_todays_action = svc.get_todays_action(per_page=10000)
            assert counts['todays_action'] == total_todays_action, (
                f"todays_action count mismatch: get_counts()={counts['todays_action']}, "
                f"get_todays_action total={total_todays_action}"
            )

            _, total_previously_warm = svc.get_previously_warm(per_page=10000)
            assert counts['previously_warm'] == total_previously_warm, (
                f"previously_warm count mismatch: get_counts()={counts['previously_warm']}, "
                f"get_previously_warm total={total_previously_warm}"
            )

            _, total_follow_up_overdue = svc.get_follow_up_overdue(per_page=10000)
            assert counts['follow_up_overdue'] == total_follow_up_overdue, (
                f"follow_up_overdue count mismatch: get_counts()={counts['follow_up_overdue']}, "
                f"get_follow_up_overdue total={total_follow_up_overdue}"
            )

            _, total_no_next_action = svc.get_no_next_action(per_page=10000)
            assert counts['no_next_action'] == total_no_next_action, (
                f"no_next_action count mismatch: get_counts()={counts['no_next_action']}, "
                f"get_no_next_action total={total_no_next_action}"
            )

            _, total_needs_review = svc.get_needs_review(per_page=10000)
            assert counts['needs_review'] == total_needs_review, (
                f"needs_review count mismatch: get_counts()={counts['needs_review']}, "
                f"get_needs_review total={total_needs_review}"
            )

            _, total_skip_trace = svc.get_skip_trace(per_page=10000)
            assert counts['skip_trace'] == total_skip_trace, (
                f"skip_trace count mismatch: get_counts()={counts['skip_trace']}, "
                f"get_skip_trace total={total_skip_trace}"
            )

            _, total_skip_trace_exhausted = svc.get_skip_trace_exhausted(per_page=10000)
            assert counts['skip_trace_exhausted'] == total_skip_trace_exhausted, (
                f"skip_trace_exhausted count mismatch: "
                f"get_counts()={counts['skip_trace_exhausted']}, "
                f"get_skip_trace_exhausted total={total_skip_trace_exhausted}"
            )

            _, total_do_not_contact = svc.get_do_not_contact(per_page=10000)
            assert counts['do_not_contact'] == total_do_not_contact, (
                f"do_not_contact count mismatch: get_counts()={counts['do_not_contact']}, "
                f"get_do_not_contact total={total_do_not_contact}"
            )

            _, total_missing_property_match = svc.get_missing_property_match(per_page=10000)
            assert counts['missing_property_match'] == total_missing_property_match, (
                f"missing_property_match count mismatch: get_counts()={counts['missing_property_match']}, "
                f"get_missing_property_match total={total_missing_property_match}"
            )

        finally:
            # Discard everything this example seeded so the next example starts
            # from an empty leads table (bounds memory across examples).
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 3: Previously Warm queue is exactly the set of is_warm=True leads
# Feature: source-agnostic-crm-queues, Property 3: Previously Warm equals is_warm
# ---------------------------------------------------------------------------

# Strategy: a list of leads with varying is_warm values
_warm_lead_record = st.fixed_dictionaries({
    'is_warm': st.booleans(),
})


@pytest.mark.usefixtures('app')
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(lead_dicts=st.lists(_warm_lead_record, min_size=0, max_size=20))
def test_property_3_previously_warm_equals_is_warm(app, lead_dicts):
    """
    Property 3: Previously Warm queue is exactly the set of is_warm=True leads.

    For any population of leads, the Previously Warm queue contains EXACTLY
    those leads where is_warm=True — no more, no fewer:
      1. Every lead with is_warm=True appears in the results.
      2. No lead with is_warm=False appears in the results.

    # Feature: source-agnostic-crm-queues, Property 3: Previously Warm equals is_warm

    Validates: Requirements 4.1, 4.2
    """
    with app.app_context():
        try:
            # Seed the database with the Hypothesis-generated lead population
            warm_ids = set()
            not_warm_ids = set()

            for i, ld in enumerate(lead_dicts):
                lead = Lead(
                    property_street=f'{i} Property 3 Test St',
                    lead_status='skip_trace',
                    is_warm=ld['is_warm'],
                    lead_score=50.0,
                    has_phone=False,
                    has_email=False,
                    analysis_complete=False,
                    follow_up_overdue=False,
                    data_completeness_score=0.0,
                    unanswered_call_count=0,
                )
                db.session.add(lead)
                db.session.flush()  # get lead.id before commit

                if ld['is_warm']:
                    warm_ids.add(lead.id)
                else:
                    not_warm_ids.add(lead.id)

            # Flush (not commit) so the per-example rollback in the finally
            # discards the seeded rows; this keeps the in-memory DB and the
            # SQLAlchemy identity map from accumulating across Hypothesis examples.
            db.session.flush()

            svc = QueueService()
            rows, total = svc.get_previously_warm(per_page=10000)
            result_ids = {row['id'] for row in rows}

            # Assert 1: every lead with is_warm=True appears in the results
            for lead_id in warm_ids:
                assert lead_id in result_ids, (
                    f"Lead {lead_id} has is_warm=True but was NOT found in "
                    f"Previously Warm queue. result_ids={result_ids}, "
                    f"warm_ids={warm_ids}"
                )

            # Assert 2: no lead with is_warm=False appears in the results
            for lead_id in not_warm_ids:
                assert lead_id not in result_ids, (
                    f"Lead {lead_id} has is_warm=False but WAS found in "
                    f"Previously Warm queue. result_ids={result_ids}, "
                    f"not_warm_ids={not_warm_ids}"
                )

            # Sanity: total count returned matches the number of warm leads seeded
            assert total == len(warm_ids), (
                f"Previously Warm total={total} does not match "
                f"number of is_warm=True leads seeded={len(warm_ids)}"
            )

        finally:
            # Discard everything this example seeded so the next example starts
            # from an empty leads table (bounds memory across examples).
            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 9: Priority queues exclude No Next Action
# Feature: source-agnostic-crm-queues, Property 9: priority queues exclude No Next Action
# ---------------------------------------------------------------------------

# Updated No Next Action allowed values (mirrors the Task 1.4 QueueService expansion)
_UPDATED_NNA_ALLOWED_ACTIONS = {None, 'create_task', 'ready_for_outreach', 'add_contact_info'}


def _is_in_no_next_action_updated(lead_status, recommended_action, has_open_tasks):
    """Updated No Next Action predicate with expanded recommended_action allow-list.

    Mirrors QueueService after Task 1.4 expansion (adds 'ready_for_outreach' and
    'add_contact_info' to the allow-list alongside None and 'create_task').
    """
    return (
        lead_status in ('active', 'new')
        and recommended_action in _UPDATED_NNA_ALLOWED_ACTIONS
        and not has_open_tasks
    )


def _is_in_todays_action_or_follow_up_overdue(
    lead_status,
    recommended_action,
    open_task_due_today,
    open_task_overdue,
    last_contact_date,
    today,
):
    """Returns True if the lead is in Today's Action OR Follow-Up Overdue."""
    in_todays_action = is_in_todays_action(lead_status, recommended_action, open_task_due_today)
    in_follow_up_overdue = is_in_follow_up_overdue(
        recommended_action, last_contact_date, open_task_overdue, today
    )
    return in_todays_action or in_follow_up_overdue


# Strategy that generates consistent lead state where task booleans are coherent:
# If a lead has open_task_due_today=True or open_task_overdue=True, it necessarily
# has open tasks (has_open_tasks must be True). This mirrors real lead state.
@st.composite
def consistent_lead_state(draw):
    """Generate a lead state where task presence flags are mutually consistent.

    open_task_due_today=True  → has_open_tasks=True  (a task due today is an open task)
    open_task_overdue=True    → has_open_tasks=True  (an overdue task is an open task)
    has_open_tasks=False      → open_task_due_today=False, open_task_overdue=False
    """
    lead_status = draw(all_lead_statuses)
    recommended_action = draw(all_recommended_actions)
    last_contact_date = draw(date_strategy)

    # Draw the concrete task presence flag first
    has_open_tasks = draw(st.booleans())

    if has_open_tasks:
        # At least one open task exists; due-today and overdue are independent booleans
        open_task_due_today = draw(st.booleans())
        open_task_overdue = draw(st.booleans())
    else:
        # No open tasks at all → neither flag can be True
        open_task_due_today = False
        open_task_overdue = False

    return {
        'lead_status': lead_status,
        'recommended_action': recommended_action,
        'open_task_due_today': open_task_due_today,
        'open_task_overdue': open_task_overdue,
        'has_open_tasks': has_open_tasks,
        'last_contact_date': last_contact_date,
    }


@settings(max_examples=100)
@given(lead=consistent_lead_state())
def test_property_9_priority_queues_exclude_no_next_action(lead):
    """
    Property 9: Priority queues exclude No Next Action

    For any lead state, the intersection of (Today's Action ∪ Follow-Up Overdue)
    and No Next Action is EMPTY.  No lead can appear in both a priority queue
    (Today's Action or Follow-Up Overdue) and No Next Action simultaneously.

    The invariant holds structurally because:
    - No Next Action requires NO open tasks.
    - Today's Action and Follow-Up Overdue require open tasks (or recommended_action
      = 'follow_up_now', which is outside the No Next Action allow-list).
    - A lead with an open task has has_open_tasks=True → excluded from No Next Action.

    # Feature: source-agnostic-crm-queues, Property 9: priority queues exclude No Next Action

    Validates: Requirements 11.1, 11.2, 11.3
    """
    today = date.today()

    lead_status = lead['lead_status']
    recommended_action = lead['recommended_action']
    open_task_due_today = lead['open_task_due_today']
    open_task_overdue = lead['open_task_overdue']
    has_open_tasks = lead['has_open_tasks']
    last_contact_date = lead['last_contact_date']

    # Evaluate priority queue membership (Today's Action OR Follow-Up Overdue)
    in_priority = _is_in_todays_action_or_follow_up_overdue(
        lead_status,
        recommended_action,
        open_task_due_today,
        open_task_overdue,
        last_contact_date,
        today,
    )

    # Evaluate No Next Action membership (updated allow-list per Task 1.4)
    in_no_next_action = _is_in_no_next_action_updated(
        lead_status,
        recommended_action,
        has_open_tasks,
    )

    # --- Core invariant: no lead is in both a priority queue and No Next Action ---
    assert not (in_priority and in_no_next_action), (
        f"Lead appears in BOTH a priority queue AND No Next Action — invariant violated!\n"
        f"  lead_status={lead_status!r}\n"
        f"  recommended_action={recommended_action!r}\n"
        f"  open_task_due_today={open_task_due_today}\n"
        f"  open_task_overdue={open_task_overdue}\n"
        f"  has_open_tasks={has_open_tasks}\n"
        f"  last_contact_date={last_contact_date}\n"
        f"  in_priority (Today's Action OR Follow-Up Overdue)={in_priority}\n"
        f"  in_no_next_action={in_no_next_action}"
    )

    # --- Structural sub-assertions (document WHY the invariant holds) ---

    # If a lead is in No Next Action, it must have NO open tasks
    if in_no_next_action:
        assert not has_open_tasks, (
            f"No Next Action lead has open tasks — impossible per predicate definition: "
            f"lead_status={lead_status!r}, recommended_action={recommended_action!r}, "
            f"has_open_tasks={has_open_tasks}"
        )
        # recommended_action must be in the No Next Action allow-list
        assert recommended_action in _UPDATED_NNA_ALLOWED_ACTIONS, (
            f"No Next Action lead has disallowed recommended_action={recommended_action!r}"
        )
        # Therefore it cannot have open_task_due_today or open_task_overdue
        assert not open_task_due_today, (
            f"No Next Action lead has open_task_due_today=True (contradicts has_open_tasks=False)"
        )
        assert not open_task_overdue, (
            f"No Next Action lead has open_task_overdue=True (contradicts has_open_tasks=False)"
        )
        # And follow_up_now is not in the allow-list, so Today's Action via
        # recommended_action path is also excluded
        assert recommended_action != 'follow_up_now', (
            f"No Next Action lead has recommended_action='follow_up_now' — impossible per allow-list"
        )


# ---------------------------------------------------------------------------
# Property 10: Owner scoping is applied uniformly
# Feature: source-agnostic-crm-queues, Property 10: owner scoping is applied uniformly
# ---------------------------------------------------------------------------

# Strategy: a list of lead field dicts for owner-A and owner-B
_scoping_lead_record = st.fixed_dictionaries({
    'lead_status':        _lead_statuses,
    'recommended_action': _recommended_actions,
    'is_warm':            st.booleans(),
    'review_required':    st.booleans(),
    'has_property_match': st.booleans(),
    # last_contact_date as an ISO string or None (used to trigger follow_up_overdue)
    'last_contact_date': st.one_of(
        st.none(),
        st.dates(
            min_value=date(2020, 1, 1),
            max_value=date.today() - timedelta(days=10),  # ensure overdue for some leads
        ).map(lambda d: d.isoformat()),
    ),
    # recommended_action override for follow_up_now to trigger more queue slots
    'force_follow_up_now': st.booleans(),
})


@pytest.mark.usefixtures('app')
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    owner_a_leads=st.lists(_scoping_lead_record, min_size=0, max_size=10),
    owner_b_leads=st.lists(_scoping_lead_record, min_size=1, max_size=10),
)
def test_property_10_owner_scoping_uniform(app, owner_a_leads, owner_b_leads):
    """
    Property 10: Owner scoping is applied uniformly across all 7 queues.

    For any owner_user_id and any lead population, all 7 queues (both badge
    counts and paginated results) contain ONLY leads whose owner_user_id matches
    the scoping value. No lead owned by a different user appears in any queue.

    Verifies:
    1. No leads belonging to 'owner-B' appear in any of the 7 paginated queues
       when QueueService is scoped to 'owner-A'.
    2. Badge counts from get_counts() match the paginated totals (only owner-A
       leads are reflected in the counts).

    # Feature: source-agnostic-crm-queues, Property 10: owner scoping is applied uniformly

    Validates: Requirements 12.3, 12.4
    """
    from datetime import date as _date

    with app.app_context():
        try:
            owner_b_ids: set[int] = set()

            # Helper: seed a lead dict into the DB with a specific owner
            def _seed_lead(ld: dict, owner: str, idx: int) -> int:
                # Resolve recommended_action: optionally override to follow_up_now
                # so that some leads qualify for Today's Action / Follow-Up Overdue
                rec_action = 'follow_up_now' if ld['force_follow_up_now'] else ld['recommended_action']

                # Parse last_contact_date if present
                lcd = None
                if ld['last_contact_date']:
                    lcd = _date.fromisoformat(ld['last_contact_date'])

                lead = Lead(
                    property_street=f'{idx} Scoping Test St owner={owner}',
                    owner_user_id=owner,
                    lead_status=ld['lead_status'],
                    recommended_action=rec_action,
                    is_warm=ld['is_warm'],
                    review_required=ld['review_required'],
                    has_property_match=ld['has_property_match'],
                    last_contact_date=lcd,
                    lead_score=50.0,
                    has_phone=False,
                    has_email=False,
                    analysis_complete=False,
                    follow_up_overdue=False,
                    data_completeness_score=0.0,
                    unanswered_call_count=0,
                )
                db.session.add(lead)
                db.session.flush()
                return lead.id

            # Seed owner-A leads
            for i, ld in enumerate(owner_a_leads):
                _seed_lead(ld, 'owner-A', i)

            # Seed owner-B leads — collect their IDs for leakage checks
            base = len(owner_a_leads)
            for j, ld in enumerate(owner_b_leads):
                lead_id = _seed_lead(ld, 'owner-B', base + j)
                owner_b_ids.add(lead_id)

            # Flush (not commit) so the per-example rollback in the finally
            # discards the seeded rows; this keeps the in-memory DB and the
            # SQLAlchemy identity map from accumulating across Hypothesis examples.
            db.session.flush()

            # Create a QueueService scoped to owner-A only
            svc = QueueService(owner_user_id='owner-A')

            # ------------------------------------------------------------------
            # Check 1: Badge counts match paginated totals (owner-A scoping)
            # ------------------------------------------------------------------
            counts = svc.get_counts()

            _, total_todays_action = svc.get_todays_action(per_page=10000)
            assert counts['todays_action'] == total_todays_action, (
                f"todays_action badge count {counts['todays_action']} != "
                f"paginated total {total_todays_action}"
            )

            _, total_previously_warm = svc.get_previously_warm(per_page=10000)
            assert counts['previously_warm'] == total_previously_warm, (
                f"previously_warm badge count {counts['previously_warm']} != "
                f"paginated total {total_previously_warm}"
            )

            _, total_follow_up_overdue = svc.get_follow_up_overdue(per_page=10000)
            assert counts['follow_up_overdue'] == total_follow_up_overdue, (
                f"follow_up_overdue badge count {counts['follow_up_overdue']} != "
                f"paginated total {total_follow_up_overdue}"
            )

            _, total_no_next_action = svc.get_no_next_action(per_page=10000)
            assert counts['no_next_action'] == total_no_next_action, (
                f"no_next_action badge count {counts['no_next_action']} != "
                f"paginated total {total_no_next_action}"
            )

            _, total_needs_review = svc.get_needs_review(per_page=10000)
            assert counts['needs_review'] == total_needs_review, (
                f"needs_review badge count {counts['needs_review']} != "
                f"paginated total {total_needs_review}"
            )

            _, total_do_not_contact = svc.get_do_not_contact(per_page=10000)
            assert counts['do_not_contact'] == total_do_not_contact, (
                f"do_not_contact badge count {counts['do_not_contact']} != "
                f"paginated total {total_do_not_contact}"
            )

            _, total_missing_property_match = svc.get_missing_property_match(per_page=10000)
            assert counts['missing_property_match'] == total_missing_property_match, (
                f"missing_property_match badge count {counts['missing_property_match']} != "
                f"paginated total {total_missing_property_match}"
            )

            # ------------------------------------------------------------------
            # Check 2: No owner-B leads appear in any of the 7 paginated queues
            # ------------------------------------------------------------------
            all_queue_results = {
                'todays_action':          svc.get_todays_action(per_page=10000)[0],
                'previously_warm':        svc.get_previously_warm(per_page=10000)[0],
                'follow_up_overdue':      svc.get_follow_up_overdue(per_page=10000)[0],
                'no_next_action':         svc.get_no_next_action(per_page=10000)[0],
                'needs_review':           svc.get_needs_review(per_page=10000)[0],
                'do_not_contact':         svc.get_do_not_contact(per_page=10000)[0],
                'missing_property_match': svc.get_missing_property_match(per_page=10000)[0],
            }

            for queue_name, rows in all_queue_results.items():
                result_ids = {row['id'] for row in rows}
                leaked = result_ids & owner_b_ids
                assert not leaked, (
                    f"Owner-B lead(s) {leaked} appeared in queue '{queue_name}' "
                    f"when scoped to owner-A. owner_b_ids={owner_b_ids}"
                )

        finally:
            # Discard everything this example seeded so the next example starts
            # from an empty leads table (bounds memory across examples).
            db.session.rollback()


