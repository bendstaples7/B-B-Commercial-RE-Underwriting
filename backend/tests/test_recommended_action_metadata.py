"""Tests for recommended-action display copy, including recent-sale rationale."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.services.recommended_action_metadata import (
    OWNER_MAILING_RETURNED_NO_CONTACT_EXPLANATION,
    OWNER_MAILING_RETURNED_WITH_CONTACT_EXPLANATION,
    RECENT_SALE_OUTDATED_CONTACT_EXPLANATION,
    get_recommended_action_display,
    get_winning_rule_label,
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
    ), patch(
        'app.services.recommended_action_metadata.contacts_need_post_hold_verification',
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


def test_enrich_data_recently_sold_uses_confirm_new_owner_label():
    display = get_recommended_action_display(
        'enrich_data',
        winning_rule='recently_sold',
    )
    assert display['label'] == 'Confirm New Owner'
    assert 'skip trace' in (display['explanation'] or '').lower()
    assert RECENT_SALE_OUTDATED_CONTACT_EXPLANATION in (display['explanation'] or '')


def test_enrich_data_without_recently_sold_keeps_generic_label():
    display = get_recommended_action_display('enrich_data')
    assert display['label'] == 'Enrich Data'


def test_owner_mailing_returned_with_phone_explains_usps_not_missing_contact():
    display = get_recommended_action_display(
        'call_ready',
        contact_method='phone',
        winning_rule='owner_mailing_returned',
    )
    assert display['explanation'] == OWNER_MAILING_RETURNED_WITH_CONTACT_EXPLANATION
    assert 'No reachable contact method' not in (display['explanation'] or '')
    assert get_winning_rule_label('owner_mailing_returned')
    assert 'USPS' in get_winning_rule_label('owner_mailing_returned')


def test_owner_mailing_returned_without_digital_avoids_generic_no_contact_copy():
    display = get_recommended_action_display(
        'add_contact_info',
        winning_rule='owner_mailing_returned',
    )
    assert display['explanation'] == OWNER_MAILING_RETURNED_NO_CONTACT_EXPLANATION
    assert 'No reachable contact method' not in (display['explanation'] or '')

