"""Unit tests for Command Center quick-action eligibility (SoT)."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.services.action_eligibility import (
    REASON_ALREADY_AWAITING_SKIP_TRACE,
    REASON_ALREADY_SKIP_TRACE,
    REASON_DNC_BLOCKS_OUTREACH,
    REASON_MAIL_ALREADY_QUEUED,
    REASON_MAIL_INVALID_ADDRESS,
    REASON_MAIL_RECENTLY_SOLD,
    REASON_TERMINAL_STATUS,
    evaluate_add_to_mail_batch,
    evaluate_move_to_skip_trace,
    evaluate_outreach_log,
)


def test_move_to_skip_trace_ok_for_active_status():
    lead = SimpleNamespace(lead_status='mailing_no_contact_made')
    result = evaluate_move_to_skip_trace(lead)
    assert result.ok is True
    assert result.already_done is False
    assert result.reason_code is None


@pytest.mark.parametrize(
    'status,reason',
    [
        ('skip_trace', REASON_ALREADY_SKIP_TRACE),
    ],
)
def test_move_to_skip_trace_already_done(status, reason):
    lead = SimpleNamespace(lead_status=status)
    result = evaluate_move_to_skip_trace(lead)
    assert result.ok is False
    assert result.already_done is True
    assert result.reason_code == reason


def test_move_to_skip_trace_ok_for_awaiting_skip_trace():
    """Hold-ended leads still need an active handoff into Skip Trace."""
    lead = SimpleNamespace(lead_status='awaiting_skip_trace')
    result = evaluate_move_to_skip_trace(lead)
    assert result.ok is True
    assert result.already_done is False
    assert result.reason_code is None


@pytest.mark.parametrize(
    'status',
    ['deprioritize', 'deal_won', 'deal_lost', 'suppressed', 'do_not_contact'],
)
def test_move_to_skip_trace_terminal(status):
    lead = SimpleNamespace(lead_status=status)
    result = evaluate_move_to_skip_trace(lead)
    assert result.ok is False
    assert result.already_done is False
    assert result.reason_code == REASON_TERMINAL_STATUS


def test_mail_eligible_ok():
    result = evaluate_add_to_mail_batch(mail_eligible=True)
    assert result.ok is True


def test_mail_already_queued():
    result = evaluate_add_to_mail_batch(
        mail_queue_status='queued',
        mail_eligible=True,
    )
    assert result.ok is False
    assert result.already_done is True
    assert result.reason_code == REASON_MAIL_ALREADY_QUEUED


def test_mail_recently_sold_with_date():
    result = evaluate_add_to_mail_batch(
        mail_eligible=False,
        mail_ineligible_reason='recently_sold',
        mail_eligible_date=date(2027, 3, 31),
    )
    assert result.ok is False
    assert result.reason_code == REASON_MAIL_RECENTLY_SOLD
    assert '2027-03-31' in (result.message or '')


def test_mail_invalid_address():
    result = evaluate_add_to_mail_batch(mail_eligible=False)
    assert result.ok is False
    assert result.reason_code == REASON_MAIL_INVALID_ADDRESS


def test_outreach_dnc_blocks_call_and_email():
    lead = SimpleNamespace(lead_status='do_not_contact')
    for action in ('log_call', 'log_email'):
        result = evaluate_outreach_log(lead, action)
        assert result.ok is False
        assert result.reason_code == REASON_DNC_BLOCKS_OUTREACH
    note = evaluate_outreach_log(lead, 'log_note')
    assert note.ok is True
