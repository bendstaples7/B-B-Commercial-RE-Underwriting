"""Quick-action eligibility — source of truth for Command Center Quick Actions.

Frontend mirrors reason codes in ``frontend/src/utils/actionEligibility.ts``.
Keep both in sync when adding actions or reason codes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Protocol


TERMINAL_LEAD_STATUSES = frozenset({
    'deprioritize',
    'deal_won',
    'deal_lost',
    'suppressed',
    'do_not_contact',
})

SKIP_TRACE_PIPELINE_STATUSES = frozenset({
    'skip_trace',
    'awaiting_skip_trace',
})

# Stable reason codes — mirrored in frontend actionEligibility.ts
REASON_ALREADY_SKIP_TRACE = 'already_skip_trace'
REASON_ALREADY_AWAITING_SKIP_TRACE = 'already_awaiting_skip_trace'
REASON_TERMINAL_STATUS = 'terminal_status'
REASON_DNC_BLOCKS_OUTREACH = 'dnc_blocks_outreach'
REASON_MAIL_RECENTLY_SOLD = 'mail_recently_sold'
REASON_MAIL_INVALID_ADDRESS = 'mail_invalid_address'
REASON_MAIL_ALREADY_QUEUED = 'mail_already_queued'


class _LeadStatusLike(Protocol):
    lead_status: Optional[str]


@dataclass(frozen=True)
class ActionEligibilityResult:
    ok: bool
    reason_code: Optional[str] = None
    message: Optional[str] = None
    already_done: bool = False


def _ok() -> ActionEligibilityResult:
    return ActionEligibilityResult(ok=True)


def _blocked(
    reason_code: str,
    message: str,
    *,
    already_done: bool = False,
) -> ActionEligibilityResult:
    return ActionEligibilityResult(
        ok=False,
        reason_code=reason_code,
        message=message,
        already_done=already_done,
    )


def evaluate_move_to_skip_trace(lead: _LeadStatusLike) -> ActionEligibilityResult:
    """Whether Move to Skip Trace may mutate this lead.

    ``skip_trace`` is already on the Skip Trace work column (already done).
    ``awaiting_skip_trace`` (e.g. recent-sale hold ended) still needs an active
    handoff into that queue — Move to Skip Trace must stay available.
    """
    status = lead.lead_status
    if status == 'skip_trace':
        return _blocked(
            REASON_ALREADY_SKIP_TRACE,
            'Already in Skip Trace',
            already_done=True,
        )
    if status in TERMINAL_LEAD_STATUSES:
        return _blocked(
            REASON_TERMINAL_STATUS,
            'Not available for this lead status',
        )
    return _ok()


def evaluate_add_to_mail_batch(
    *,
    mail_queue_status: Optional[str] = None,
    mail_eligible: bool = False,
    mail_ineligible_reason: Optional[str] = None,
    mail_eligible_date: Optional[date | str] = None,
) -> ActionEligibilityResult:
    """Whether Add to Mail Queue should be enabled (UI) / treated as ready.

    Soft enqueue still returns per-lead outcomes; this gates the Quick Action.
    """
    if mail_queue_status == 'queued':
        return _blocked(
            REASON_MAIL_ALREADY_QUEUED,
            'Already staged for the next mail batch',
            already_done=True,
        )
    if mail_eligible:
        return _ok()
    if mail_ineligible_reason == 'recently_sold':
        if mail_eligible_date:
            if isinstance(mail_eligible_date, date):
                when = mail_eligible_date.isoformat()
            else:
                when = str(mail_eligible_date)
            return _blocked(
                REASON_MAIL_RECENTLY_SOLD,
                f'Held after recent sale until {when}',
            )
        return _blocked(
            REASON_MAIL_RECENTLY_SOLD,
            'Held after recent sale until the two-year hold ends',
        )
    return _blocked(
        REASON_MAIL_INVALID_ADDRESS,
        'Owner mailing address is not ready for the mail queue',
    )


def evaluate_outreach_log(
    lead: _LeadStatusLike,
    action: str,
) -> ActionEligibilityResult:
    """Log Call / Log Email blocked on DNC; Log Note always ok."""
    if action == 'log_note':
        return _ok()
    if action in {'log_call', 'log_email'} and lead.lead_status == 'do_not_contact':
        return _blocked(
            REASON_DNC_BLOCKS_OUTREACH,
            'Outreach is blocked — lead is Do Not Contact',
        )
    return _ok()
