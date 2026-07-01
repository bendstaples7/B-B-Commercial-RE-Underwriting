"""Unit tests for outreach contact-method selection."""
from unittest.mock import MagicMock

import pytest

from app.services.outreach_method_service import (
    evaluate_contact_method,
    refine_outreach_action,
    outreach_action_label,
    resolve_outreach_contact,
    resolve_outreach_contacts_for_leads,
    outreach_contact_task_title,
    RESIDENTIAL_DIRECT_MAIL_STATUSES,
)


def _lead(**kwargs):
    lead = MagicMock()
    lead.lead_category = kwargs.get('lead_category', 'residential')
    lead.lead_status = kwargs.get('lead_status', 'mailing_no_contact_made')
    lead.is_warm = kwargs.get('is_warm', False)
    lead.follow_up_overdue = kwargs.get('follow_up_overdue', False)
    lead.unanswered_call_count = kwargs.get('unanswered_call_count', 0)
    return lead


@pytest.mark.parametrize('status', sorted(RESIDENTIAL_DIRECT_MAIL_STATUSES))
def test_residential_early_stage_always_direct_mail(status):
    lead = _lead(lead_status=status, is_warm=True, follow_up_overdue=True)
    method = evaluate_contact_method(
        lead, 'follow_up_now',
        has_phone=True, has_email=True, recent_email=True,
    )
    assert method == 'direct_mail'


def test_residential_warm_post_mailing_prefers_phone():
    lead = _lead(lead_status='mailing_contacted_interested', is_warm=True)
    method = evaluate_contact_method(
        lead, 'follow_up_now',
        has_phone=True, has_email=True, recent_email=False,
    )
    assert method == 'phone'


def test_residential_recent_email_prefers_email():
    lead = _lead(lead_status='negotiating_remote')
    method = evaluate_contact_method(
        lead, 'ready_for_outreach',
        has_phone=True, has_email=True, recent_email=True,
    )
    assert method == 'email'


def test_residential_many_unanswered_calls_prefers_text():
    lead = _lead(lead_status='negotiating_remote', unanswered_call_count=3)
    method = evaluate_contact_method(
        lead, 'ready_for_outreach',
        has_phone=True, has_email=False, recent_email=False,
    )
    assert method == 'text'


def test_commercial_with_phone_prefers_call():
    lead = _lead(lead_category='commercial', unanswered_call_count=0)
    method = evaluate_contact_method(
        lead, 'ready_for_outreach',
        has_phone=True, has_email=True, recent_email=False,
    )
    assert method == 'phone'


def test_commercial_no_phone_falls_back_to_mail():
    lead = _lead(lead_category='commercial')
    method = evaluate_contact_method(
        lead, 'ready_for_outreach',
        has_phone=False, has_email=True, recent_email=False,
    )
    assert method == 'direct_mail'


def test_commercial_many_unanswered_falls_back_to_mail():
    lead = _lead(lead_category='commercial', unanswered_call_count=3)
    method = evaluate_contact_method(
        lead, 'ready_for_outreach',
        has_phone=True, has_email=True, recent_email=False,
    )
    assert method == 'direct_mail'


def test_non_outreach_action_returns_none():
    lead = _lead()
    assert evaluate_contact_method(
        lead, 'analyze_property',
        has_phone=True, has_email=True, recent_email=False,
    ) is None


def test_refine_follow_up_phone_to_call_ready():
    assert refine_outreach_action('follow_up_now', 'phone') == 'call_ready'


def test_refine_ready_for_outreach_mail_to_mail_ready():
    assert refine_outreach_action('ready_for_outreach', 'direct_mail') == 'mail_ready'


def test_outreach_action_label_call_now():
    assert outreach_action_label('follow_up_now', 'phone') == 'Call Now'


def test_outreach_action_label_mail_now():
    assert outreach_action_label('follow_up_now', 'direct_mail') == 'Mail Now'


def _lead_with_contact(**kwargs):
    lead = _lead(**kwargs)
    lead.id = kwargs.get('id', None)
    for slot in range(1, 8):
        setattr(lead, f'phone_{slot}', kwargs.get(f'phone_{slot}'))
    for slot in range(1, 6):
        setattr(lead, f'email_{slot}', kwargs.get(f'email_{slot}'))
    lead.email_1 = kwargs.get('email_1')
    lead.mailing_address = kwargs.get('mailing_address')
    lead.mailing_city = kwargs.get('mailing_city')
    lead.mailing_state = kwargs.get('mailing_state')
    lead.mailing_zip = kwargs.get('mailing_zip')
    lead.property_street = kwargs.get('property_street')
    lead.property_city = kwargs.get('property_city')
    lead.property_state = kwargs.get('property_state')
    lead.property_zip = kwargs.get('property_zip')
    lead.recommended_contact_method = kwargs.get('recommended_contact_method')
    return lead


def test_resolve_outreach_contact_phone_from_flat():
    lead = _lead_with_contact(phone_1='5551234567')
    result = resolve_outreach_contact(lead, 'phone')
    assert result is not None
    assert result['channel'] == 'phone'
    assert result['label'] == 'Call'
    assert result['display'] == '(555) 123-4567'
    assert result['href'] == 'tel:+15551234567'
    assert result['value'] == '5551234567'


def test_resolve_outreach_contact_text_uses_phone():
    lead = _lead_with_contact(phone_1='5559876543')
    result = resolve_outreach_contact(lead, 'text')
    assert result is not None
    assert result['channel'] == 'text'
    assert result['label'] == 'Text'
    assert result['href'] == 'sms:+15559876543'


def test_resolve_outreach_contact_email():
    lead = _lead_with_contact(email_1='owner@example.com')
    result = resolve_outreach_contact(lead, 'email')
    assert result is not None
    assert result['channel'] == 'email'
    assert result['display'] == 'owner@example.com'
    assert result['href'] == 'mailto:owner@example.com'


def test_resolve_outreach_contact_mail_prefers_mailing():
    lead = _lead_with_contact(
        mailing_address='123 Mail St',
        mailing_city='Springfield',
        mailing_state='IL',
        mailing_zip='62701',
        property_street='456 Property Ave',
    )
    result = resolve_outreach_contact(lead, 'direct_mail')
    assert result is not None
    assert result['lines'] == ['123 Mail St', 'Springfield, IL 62701']


def test_resolve_outreach_contact_mail_falls_back_to_property():
    lead = _lead_with_contact(
        property_street='789 Oak Rd',
        property_city='Chicago',
        property_state='IL',
        property_zip='60601',
    )
    result = resolve_outreach_contact(lead, 'direct_mail')
    assert result is not None
    assert result['lines'][0] == '789 Oak Rd'


def test_resolve_outreach_contact_none_for_missing_channel():
    lead = _lead_with_contact(phone_1='5551234567')
    assert resolve_outreach_contact(lead, None) is None
    assert resolve_outreach_contact(lead, 'invalid') is None


def test_resolve_outreach_contact_none_when_no_phone():
    lead = _lead_with_contact()
    assert resolve_outreach_contact(lead, 'phone') is None


def test_outreach_contact_task_title():
    contact = {
        'label': 'Call',
        'display': '(555) 123-4567',
        'value': '5551234567',
    }
    assert outreach_contact_task_title(contact) == 'Call (555) 123-4567'
    assert outreach_contact_task_title(None) is None


def test_resolve_outreach_contacts_for_leads_batch(monkeypatch):
    """Batch resolver uses flat columns when relational queries return no rows."""

    class _EmptyResult:
        def fetchall(self):
            return []

    monkeypatch.setattr('app.db.session.execute', lambda *args, **kwargs: _EmptyResult())

    phone_lead = _lead_with_contact(
        id=101,
        phone_1='5551112222',
        recommended_contact_method='phone',
    )
    email_lead = _lead_with_contact(
        id=102,
        email_1='owner@example.com',
        recommended_contact_method='email',
    )

    resolved = resolve_outreach_contacts_for_leads([phone_lead, email_lead])

    assert resolved[101]['channel'] == 'phone'
    assert resolved[101]['display'] == '(555) 111-2222'
    assert resolved[102]['channel'] == 'email'
    assert resolved[102]['display'] == 'owner@example.com'
