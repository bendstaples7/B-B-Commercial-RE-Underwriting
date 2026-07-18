"""Contact-method selection for outreach recommended actions.

Used by LeadScoringEngine after evaluate_recommended_action to pick
phone / email / text / direct_mail, and by API serializers to resolve
the concrete contact value for UI callouts.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from app.models.lead import Lead
from app.services.open_letter_contact_mapper import (
    is_owner_mailable_lead,
    owner_mailing_address,
)

OUTREACH_ACTIONS = frozenset({
    'follow_up_now',
    'ready_for_outreach',
    'mail_ready',
    'call_ready',
    'review_now',
    'nurture',
})

RESIDENTIAL_DIRECT_MAIL_STATUSES = frozenset({
    'mailing_no_contact_made',
    'mailing_contacted_no_interest',
})

CONTACT_METHOD_LABELS = {
    'phone': 'Call',
    'email': 'Email',
    'text': 'Text',
    'direct_mail': 'Direct Mail',
}

METHOD_EXPLANATIONS = {
    'phone': 'Reach out by phone — cold call or follow-up call.',
    'email': 'Send an email to continue the conversation.',
    'text': 'Send a text message to the owner.',
    'direct_mail': 'Add to a direct mail batch or send a letter.',
}

VALID_CONTACT_CHANNELS = frozenset(CONTACT_METHOD_LABELS.keys())


ENGAGED_PIPELINE_STATUSES = frozenset({
    'in_person_appointment',
    'negotiating_remote',
    'mailing_contacted_interested',
})


def evaluate_contact_method(
    lead: Lead,
    recommended_action: str | None,
    *,
    has_phone: bool,
    has_email: bool,
    recent_email: bool,
) -> str | None:
    """Return the best outreach channel, or None for non-outreach actions."""
    if not recommended_action or recommended_action not in OUTREACH_ACTIONS:
        return None
    if recommended_action == 'nurture':
        from app.services.scoring_rubric import is_recently_sold
        if is_recently_sold(lead):
            return None

    category = getattr(lead, 'lead_category', 'residential') or 'residential'
    if category == 'commercial':
        return _commercial_contact_method(lead, has_phone=has_phone)
    return _residential_contact_method(
        lead,
        has_phone=has_phone,
        has_email=has_email,
        recent_email=recent_email,
    )


def _commercial_contact_method(lead: Lead, *, has_phone: bool) -> str | None:
    unanswered = getattr(lead, 'unanswered_call_count', 0) or 0
    if has_phone and unanswered < 3:
        return 'phone'
    return 'direct_mail' if is_owner_mailable_lead(lead) else None


def _residential_contact_method(
    lead: Lead,
    *,
    has_phone: bool,
    has_email: bool,
    recent_email: bool,
) -> str | None:
    status = getattr(lead, 'lead_status', None)
    engaged_or_follow_up = (
        status in ENGAGED_PIPELINE_STATUSES
        or getattr(lead, 'follow_up_overdue', False)
        or getattr(lead, 'is_warm', False)
    )

    # Engaged / overdue / warm: prefer phone before cold-mail status lock.
    if engaged_or_follow_up:
        if has_phone:
            return 'phone'
        if has_email:
            return 'email'
        return 'direct_mail' if is_owner_mailable_lead(lead) else None

    if status in RESIDENTIAL_DIRECT_MAIL_STATUSES and is_owner_mailable_lead(lead):
        return 'direct_mail'

    if recent_email and has_email:
        return 'email'
    unanswered = getattr(lead, 'unanswered_call_count', 0) or 0
    if has_phone and unanswered < 3:
        return 'phone'
    if has_email:
        return 'email'
    if has_phone:
        return 'text'
    return 'direct_mail' if is_owner_mailable_lead(lead) else None


# Only these nurture outcomes should surface as Call Ready after channel refine.
# Hold / score-band nurture (mail in flight, tier C, etc.) must stay nurture.
NURTURE_TO_CALL_RULES = frozenset({
    'engaged_pipeline_nurture',
    'tier_d_contactable',
})


def refine_outreach_action(
    action: str | None,
    method: str | None,
    *,
    winning_rule: str | None = None,
) -> str | None:
    """Map generic outreach actions to channel-specific actions where enums exist."""
    if not action or not method:
        return action

    if action == 'mail_ready':
        return action

    if method == 'phone' and action in ('follow_up_now', 'ready_for_outreach'):
        return 'call_ready'
    if (
        method == 'phone'
        and action == 'nurture'
        and winning_rule in NURTURE_TO_CALL_RULES
    ):
        return 'call_ready'
    if method == 'direct_mail' and action in ('follow_up_now', 'ready_for_outreach'):
        return 'mail_ready'

    return action


def contact_method_label(method: str | None) -> str | None:
    if not method:
        return None
    return CONTACT_METHOD_LABELS.get(method, method.replace('_', ' ').title())


def outreach_action_label(action: str | None, method: str | None) -> str | None:
    """Human-readable label combining action intent and contact channel."""
    if not action:
        return None

    method_label = contact_method_label(method)

    if method == 'direct_mail':
        return 'Direct Mail'
    if action == 'call_ready' or (action == 'follow_up_now' and method == 'phone'):
        return 'Call Now'
    if action == 'follow_up_now' and method == 'email':
        return 'Email Now'
    if action == 'follow_up_now' and method == 'text':
        return 'Text Now'
    if action == 'ready_for_outreach' and method == 'phone':
        return 'Ready to Call'
    if action == 'ready_for_outreach' and method == 'email':
        return 'Ready to Email'
    if action == 'ready_for_outreach' and method == 'text':
        return 'Ready to Text'
    if action == 'review_now' and method_label:
        return f'Review — {method_label}'
    if action == 'nurture' and method_label:
        return f'Nurture — {method_label}'

    return None


def outreach_action_explanation(
    action: str | None,
    method: str | None,
    base_explanation: str | None,
) -> str | None:
    """Build channel-specific explanation from base metadata."""
    if not action or not method:
        return base_explanation

    method_hint = METHOD_EXPLANATIONS.get(method)
    if not method_hint:
        return base_explanation

    category = None
    if method == 'direct_mail':
        category = 'Residential leads in early mailing stages use direct mail until contact is made.'
    elif method == 'phone':
        category = 'Commercial leads are cold-called when a phone number is on file.'

    parts = [p for p in (base_explanation, method_hint, category) if p]
    if not parts:
        return method_hint
    if base_explanation and method_hint and base_explanation != method_hint:
        return f'{base_explanation} Recommended channel: {method_hint}'
    return parts[0]


def _format_phone_display(phone_number: str | None) -> str | None:
    if not phone_number:
        return None
    digits = re.sub(r'\D', '', phone_number)
    if len(digits) == 10:
        return f'({digits[:3]}) {digits[3:6]}-{digits[6:]}'
    if len(digits) == 11 and digits.startswith('1'):
        return f'({digits[1:4]}) {digits[4:7]}-{digits[7:]}'
    return phone_number


def _phone_tel_href(phone_number: str) -> str:
    digits = re.sub(r'\D', '', phone_number)
    if len(digits) == 10:
        return f'tel:+1{digits}'
    if len(digits) == 11 and digits.startswith('1'):
        return f'tel:+{digits}'
    if digits:
        return f'tel:{digits}'
    return f'tel:{phone_number}'


def _phone_sms_href(phone_number: str) -> str:
    digits = re.sub(r'\D', '', phone_number)
    if len(digits) == 10:
        return f'sms:+1{digits}'
    if len(digits) == 11 and digits.startswith('1'):
        return f'sms:+{digits}'
    if digits:
        return f'sms:{digits}'
    return f'sms:{phone_number}'


def _first_flat_phone(lead: Lead) -> str | None:
    for slot in range(1, 8):
        raw = getattr(lead, f'phone_{slot}', None)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _collect_emails_for_lead(lead_id: int | None, lead: Lead) -> list[str]:
    flat_emails = []
    for slot in ('email_1', 'email_2', 'email_3', 'email_4', 'email_5'):
        e = getattr(lead, slot, None)
        if isinstance(e, str) and e.strip():
            flat_emails.append(e.strip())
    relational_emails: list[str] = []
    if isinstance(lead_id, int):
        from sqlalchemy import text

        from app import db

        relational_emails = [
            row[0] for row in db.session.execute(
                text("""
                    SELECT ce.value FROM contact_emails ce
                    JOIN property_contacts pc ON pc.contact_id = ce.contact_id
                    WHERE pc.property_id = :lead_id
                      AND (pc.role IS NULL OR pc.role <> 'former_owner')
                """),
                {'lead_id': lead_id},
            ).fetchall()
            if row[0]
        ]

    seen: set[str] = set()
    emails: list[str] = []
    for e in flat_emails + relational_emails:
        normalized = str(e).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            emails.append(str(e).strip())
    return emails


def _format_address_lines(
    street: str | None,
    city: str | None,
    state: str | None,
    zip_code: str | None,
) -> list[str]:
    lines: list[str] = []
    if street and str(street).strip():
        lines.append(str(street).strip())
    locality_parts = [p for p in (city, state) if p and str(p).strip()]
    locality = ', '.join(str(p).strip() for p in locality_parts)
    if zip_code and str(zip_code).strip():
        locality = f'{locality} {str(zip_code).strip()}'.strip() if locality else str(zip_code).strip()
    if locality:
        lines.append(locality)
    return lines


def _phone_contact_dict(raw: str, channel: str) -> dict:
    display = _format_phone_display(raw) or raw
    digits = re.sub(r'\D', '', raw)
    href = _phone_sms_href(raw) if channel == 'text' else _phone_tel_href(raw)
    return {
        'channel': channel,
        'label': CONTACT_METHOD_LABELS.get(channel, 'Call'),
        'value': digits or raw,
        'display': display,
        'href': href,
    }


def _email_contact_dict(email: str) -> dict:
    return {
        'channel': 'email',
        'label': CONTACT_METHOD_LABELS['email'],
        'value': email,
        'display': email,
        'href': f'mailto:{email}',
    }


def _collect_flat_emails(lead: Lead) -> list[str]:
    emails: list[str] = []
    for slot in ('email_1', 'email_2', 'email_3', 'email_4', 'email_5'):
        e = getattr(lead, slot, None)
        if isinstance(e, str) and e.strip():
            emails.append(e.strip())
    return emails


def _batch_best_phone_by_lead(leads: list[Lead]) -> dict[int, str]:
    """Best phone per lead_id using one relational query + flat columns."""
    lead_ids = [lead.id for lead in leads if isinstance(getattr(lead, 'id', None), int)]
    if not lead_ids:
        return {}

    from sqlalchemy import bindparam, text

    from app import db
    from app.services.phone_confidence_service import (
        DEFAULT_CONFIDENCE,
        MIN_VIABLE_CONFIDENCE,
        PhoneConfidenceService,
    )

    statement = text("""
            SELECT pc.property_id, cp.value, cp.confidence_score, cp.notes, cp.label, cp.source
            FROM contact_phones cp
            JOIN property_contacts pc ON pc.contact_id = cp.contact_id
            WHERE pc.property_id IN :lead_ids
              AND (pc.role IS NULL OR pc.role <> 'former_owner')
        """).bindparams(bindparam('lead_ids', expanding=True))
    rows = db.session.execute(
        statement,
        {'lead_ids': lead_ids},
    ).fetchall()

    # (score, preferred_rank, value) — preferred_rank 0 = HubSpot primary / phone_1
    candidates: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
    for property_id, value, confidence, notes, label, source in rows:
        if not value or not str(value).strip():
            continue
        score = confidence if confidence is not None else DEFAULT_CONFIDENCE
        notes_l = (notes or '').lower()
        label_l = (str(label) if label is not None else '').lower()
        source_l = (str(source) if source is not None else '').lower()
        is_primary = (
            'hubspot primary' in notes_l
            or label_l == 'mobile'
            or (source_l.startswith('hubspot') and 'hubspot primary' in notes_l)
        )
        preferred = 0 if is_primary else 1
        candidates[property_id].append((score, preferred, str(value).strip()))

    result: dict[int, str] = {}
    for lead in leads:
        lead_id = getattr(lead, 'id', None)
        if not isinstance(lead_id, int):
            continue
        ranked = list(candidates.get(lead_id, []))
        for slot in range(1, 8):
            raw = getattr(lead, f'phone_{slot}', None)
            if isinstance(raw, str) and raw.strip():
                # phone_1 is preferred over later flat slots; never sort by digits.
                preferred = 0 if slot == 1 else 2
                ranked.append((DEFAULT_CONFIDENCE, preferred, raw.strip()))
        if not ranked:
            continue
        # Dedupe by normalized digits, keeping best score/preferred.
        by_digits: dict[str, tuple[int, int, str]] = {}
        for score, preferred, value in ranked:
            digits = PhoneConfidenceService.normalize_phone(value)
            if len(digits) < 7:
                continue
            existing = by_digits.get(digits)
            if existing is None or (score, -preferred) > (existing[0], -existing[1]):
                by_digits[digits] = (score, preferred, value)
        ranked = list(by_digits.values())
        ranked.sort(key=lambda item: (-item[0], item[1]))
        viable = [item for item in ranked if item[0] >= MIN_VIABLE_CONFIDENCE]
        if viable:
            result[lead_id] = viable[0][2]
        elif len(ranked) == 1:
            result[lead_id] = ranked[0][2]
        # Multiple numbers all below viable confidence → skip auto-pick.
    return result


def _batch_first_email_by_lead(leads: list[Lead]) -> dict[int, str]:
    """First email per lead_id using one relational query + flat columns."""
    lead_ids = [lead.id for lead in leads if isinstance(getattr(lead, 'id', None), int)]
    if not lead_ids:
        return {}

    from sqlalchemy import bindparam, text

    from app import db

    statement = text("""
            SELECT pc.property_id, ce.value
            FROM contact_emails ce
            JOIN property_contacts pc ON pc.contact_id = ce.contact_id
            WHERE pc.property_id IN :lead_ids
              AND (pc.role IS NULL OR pc.role <> 'former_owner')
            ORDER BY pc.property_id, ce.id
        """).bindparams(bindparam('lead_ids', expanding=True))
    rows = db.session.execute(
        statement,
        {'lead_ids': lead_ids},
    ).fetchall()

    relational: dict[int, list[str]] = defaultdict(list)
    for property_id, value in rows:
        if value and str(value).strip():
            relational[property_id].append(str(value).strip())

    result: dict[int, str] = {}
    for lead in leads:
        lead_id = getattr(lead, 'id', None)
        if not isinstance(lead_id, int):
            continue
        seen: set[str] = set()
        for email in relational.get(lead_id, []) + _collect_flat_emails(lead):
            normalized = email.lower()
            if normalized not in seen:
                seen.add(normalized)
                result[lead_id] = email
                break
    return result


def resolve_outreach_contacts_for_leads(leads: list[Lead]) -> dict[int, dict | None]:
    """Batch-resolve outreach contact payloads for a page of leads (queue views)."""
    if not leads:
        return {}

    phone_leads = [
        lead for lead in leads
        if lead.recommended_contact_method in ('phone', 'text')
    ]
    email_leads = [
        lead for lead in leads
        if lead.recommended_contact_method == 'email'
    ]

    phone_by_lead = _batch_best_phone_by_lead(phone_leads) if phone_leads else {}
    email_by_lead = _batch_first_email_by_lead(email_leads) if email_leads else {}

    resolved: dict[int, dict | None] = {}
    for lead in leads:
        lead_id = getattr(lead, 'id', None)
        if not isinstance(lead_id, int):
            continue
        method = lead.recommended_contact_method
        if not method or method not in VALID_CONTACT_CHANNELS:
            resolved[lead_id] = None
            continue
        if method in ('phone', 'text'):
            raw = phone_by_lead.get(lead_id) or _first_flat_phone(lead)
            resolved[lead_id] = _phone_contact_dict(raw, method) if raw else None
        elif method == 'email':
            email = email_by_lead.get(lead_id)
            resolved[lead_id] = _email_contact_dict(email) if email else None
        elif method == 'direct_mail':
            resolved[lead_id] = _resolve_mail_contact(lead)
        else:
            resolved[lead_id] = None
    return resolved


def _resolve_phone_contact(lead: Lead, *, channel: str) -> dict | None:
    lead_id = getattr(lead, 'id', None)
    if isinstance(lead_id, int):
        if lead.recommended_contact_method in ('phone', 'text'):
            cached = resolve_outreach_contacts_for_leads([lead]).get(lead_id)
            if lead.recommended_contact_method == channel:
                return cached
        raw = _batch_best_phone_by_lead([lead]).get(lead_id) or _first_flat_phone(lead)
    else:
        raw = _first_flat_phone(lead)
    if not raw:
        return None
    return _phone_contact_dict(raw, channel)


def _resolve_email_contact(lead: Lead) -> dict | None:
    lead_id = getattr(lead, 'id', None)
    if isinstance(lead_id, int):
        if lead.recommended_contact_method == 'email':
            cached = resolve_outreach_contacts_for_leads([lead]).get(lead_id)
            return cached
        email = _batch_first_email_by_lead([lead]).get(lead_id)
        if not email:
            emails = _collect_emails_for_lead(lead_id, lead)
            email = emails[0] if emails else None
        return _email_contact_dict(email) if email else None
    emails = _collect_emails_for_lead(None, lead)
    if not emails:
        return None
    return _email_contact_dict(emails[0])


def _resolve_mail_contact(lead: Lead) -> dict | None:
    if not is_owner_mailable_lead(lead):
        return None
    street, city, state, zip_code = owner_mailing_address(lead)
    lines = _format_address_lines(street, city, state, zip_code)
    if not lines:
        return None
    display = lines[0] if len(lines) == 1 else ' — '.join(lines)
    return {
        'channel': 'direct_mail',
        'label': CONTACT_METHOD_LABELS['direct_mail'],
        'value': display,
        'display': display,
        'lines': lines,
    }


def resolve_outreach_contact(lead: Lead, contact_method: str | None) -> dict | None:
    """Pick the concrete phone, email, or address for an outreach channel."""
    if not contact_method or contact_method not in VALID_CONTACT_CHANNELS:
        return None
    if contact_method in ('phone', 'text'):
        return _resolve_phone_contact(lead, channel=contact_method)
    if contact_method == 'email':
        return _resolve_email_contact(lead)
    if contact_method == 'direct_mail':
        return _resolve_mail_contact(lead)
    return None


def outreach_contact_task_title(contact: dict | None) -> str | None:
    """Default native task title from a resolved outreach contact."""
    if not contact:
        return None
    label = contact.get('label') or 'Follow up'
    display = contact.get('display') or contact.get('value')
    if not display:
        return None
    return f'{label} {display}'
