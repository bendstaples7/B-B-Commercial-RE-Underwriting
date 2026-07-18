"""Tests for recommended-action display copy, including recent-sale rationale."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.services.recommended_action_metadata import (
    RECENT_SALE_OUTDATED_CONTACT_EXPLANATION,
    get_recommended_action_display,
)


def test_hold_explanation_includes_outdated_contact_rationale():
    display = get_recommended_action_display('hold')
    assert RECENT_SALE_OUTDATED_CONTACT_EXPLANATION in (display['explanation'] or '')


def test_skip_trace_nurture_gets_recent_sale_rationale_when_contacts_stale():
    lead = SimpleNamespace(
        lead_status='skip_trace',
        needs_skip_trace=True,
        most_recent_sale='7/17/2024',
        acquisition_date=date.today() - timedelta(days=400),
    )
    with patch(
        'app.services.recommended_action_metadata.contacts_likely_prior_owner',
        return_value=True,
    ):
        display = get_recommended_action_display('nurture', lead=lead)
    assert display['explanation'] == RECENT_SALE_OUTDATED_CONTACT_EXPLANATION


def test_skip_trace_nurture_without_stale_contacts_stays_blank():
    lead = SimpleNamespace(
        lead_status='skip_trace',
        needs_skip_trace=True,
        most_recent_sale='7/17/2024',
        acquisition_date=date.today() - timedelta(days=800),
    )
    with patch(
        'app.services.recommended_action_metadata.contacts_likely_prior_owner',
        return_value=False,
    ):
        display = get_recommended_action_display('nurture', lead=lead)
    assert display['explanation'] in (None, '')


def test_mailing_nurture_without_sale_context_stays_blank():
    lead = SimpleNamespace(
        lead_status='mailing_no_contact_made',
        needs_skip_trace=False,
        most_recent_sale=None,
        acquisition_date=None,
    )
    display = get_recommended_action_display('nurture', lead=lead)
    assert display['explanation'] in (None, '')
