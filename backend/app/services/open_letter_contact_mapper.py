"""Map platform leads to Open Letter Connect contact payloads."""
from __future__ import annotations

import re
from typing import Any

from app.models.lead import Lead
from app.services.address_parse_service import parse_embedded_us_address


def _clean(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _complete_address(street: str, city: str, state: str, zip_code: str) -> bool:
    return bool(street and city and state and zip_code)


def _merge_parsed_fields(
    street: str,
    city: str,
    state: str,
    zip_code: str,
    raw_line: str,
) -> tuple[str, str, str, str]:
    """Fill missing components by parsing a one-line address string."""
    if _complete_address(street, city, state, zip_code) or not raw_line:
        return street, city, state, zip_code

    parsed = parse_embedded_us_address(raw_line)
    if not parsed:
        return street, city, state, zip_code

    p_street, p_city, p_state, p_zip = parsed
    use_street = street
    if p_street and (not city or not state or not zip_code):
        if not street or street == raw_line.strip():
            use_street = p_street
    return (
        use_street or p_street,
        city or p_city,
        state or p_state,
        zip_code or p_zip,
    )


_STREET_ABBREV = (
    (r'\bnorth\b', 'n'),
    (r'\bsouth\b', 's'),
    (r'\beast\b', 'e'),
    (r'\bwest\b', 'w'),
    (r'\bstreet\b', 'st'),
    (r'\bavenue\b', 'ave'),
    (r'\bboulevard\b', 'blvd'),
    (r'\bdrive\b', 'dr'),
    (r'\broad\b', 'rd'),
    (r'\blane\b', 'ln'),
    (r'\bcourt\b', 'ct'),
    (r'\bcircle\b', 'cir'),
    (r'\bplace\b', 'pl'),
    (r'\bterrace\b', 'ter'),
    (r'\bparkway\b', 'pkwy'),
    (r'\bapartment\b', 'apt'),
    (r'\bsuite\b', 'ste'),
    (r'\bunit\b', 'unit'),
)


def _normalize_address_part(value: str) -> str:
    text = _clean(value).lower()
    if not text:
        return ''
    text = re.sub(r'#\s*', 'apt ', text)
    text = re.sub(r'[.,;:/\\]+', ' ', text)
    for pattern, repl in _STREET_ABBREV:
        text = re.sub(pattern, repl, text)
    return re.sub(r'\s+', ' ', text).strip()


def _normalize_zip(value: str) -> str:
    digits = re.sub(r'\D', '', _clean(value))
    return digits[:5] if digits else ''


def _address_tuple_from_line(line: str) -> tuple[str, str, str, str]:
    cleaned = _clean(line)
    if not cleaned:
        return '', '', '', ''
    parsed = parse_embedded_us_address(cleaned)
    if parsed:
        return parsed
    return cleaned, '', '', ''


def _returned_entry_matches_target(
    returned_line: str,
    target: tuple[str, str, str, str],
) -> bool:
    """True when a returned-mail history line identifies the current mailing target."""
    t_street, t_city, t_state, t_zip = target
    norm_street = _normalize_address_part(t_street)
    if not norm_street:
        return False

    r_street, r_city, r_state, r_zip = _address_tuple_from_line(returned_line)
    if not r_street:
        r_street = returned_line
    r_street_norm = _normalize_address_part(
        re.sub(
            r'\b(returned|undeliverable|rts|bad address)\b',
            ' ',
            r_street,
            flags=re.I,
        )
    )
    if not r_street_norm or r_street_norm != norm_street:
        return False

    if r_city and _normalize_address_part(r_city) != _normalize_address_part(t_city):
        return False
    if r_state and _normalize_address_part(r_state) != _normalize_address_part(t_state):
        return False
    if r_zip and _normalize_zip(r_zip) != _normalize_zip(t_zip):
        return False
    return True


def current_owner_mailing_was_returned(lead: Lead) -> bool:
    """True when returned-mail history identifies the current owner mailing target."""
    returned = _clean(getattr(lead, 'returned_addresses', None))
    if not returned:
        return False
    target = owner_mailing_address(lead)
    if not target[0]:
        return False
    for line in returned.splitlines():
        if _clean(line) and _returned_entry_matches_target(line, target):
            return True
    return False


def is_mailable_lead(lead: Lead) -> bool:
    """True when the lead has a complete mailable address (including embedded parse)."""
    return validate_lead_mail_address(lead) is None


def owner_mailing_address(lead: Lead) -> tuple[str, str, str, str]:
    """Return the parsed owner mailing address without property fallback."""
    street = _clean(getattr(lead, 'mailing_address', None))
    city = _clean(getattr(lead, 'mailing_city', None))
    state = _clean(getattr(lead, 'mailing_state', None))
    zip_code = _clean(getattr(lead, 'mailing_zip', None))
    return _merge_parsed_fields(street, city, state, zip_code, street)


def validate_owner_mailing_address(lead: Lead) -> str | None:
    """Return an owner-mailing validation error, or None when complete."""
    if current_owner_mailing_was_returned(lead):
        return 'Current owner mailing address was previously returned'
    street, city, state, zip_code = owner_mailing_address(lead)
    if not street:
        return 'No owner mailing street address'
    if not city or not state or not zip_code:
        return 'Incomplete owner mailing city/state/zip'
    return None


def is_owner_mailable_lead(lead: Lead) -> bool:
    """True only when the owner mailing address is complete."""
    return validate_owner_mailing_address(lead) is None


# Identity / dedup keys — never mutate during mail address backfill.
_IDENTITY_FIELDS = ('property_street', 'mailing_address', 'normalized_street')


def persist_embedded_address_fields(lead: Lead) -> bool:
    """Parse one-line addresses and persist into empty structured columns.

    Only city/state/zip are written — never property_street, mailing_address,
    or normalized_street. Rewriting street text changes the dedup unique index
    and can fail enqueue when duplicate owner+building rows exist.
    Validation and OLC mapping still parse the one-line street in memory.
    """
    before = {field: getattr(lead, field, None) for field in _IDENTITY_FIELDS}
    updated = False

    mailing_street = _clean(getattr(lead, 'mailing_address', None))
    mailing_city = _clean(getattr(lead, 'mailing_city', None))
    mailing_state = _clean(getattr(lead, 'mailing_state', None))
    mailing_zip = _clean(getattr(lead, 'mailing_zip', None))

    if mailing_street and not _complete_address(mailing_street, mailing_city, mailing_state, mailing_zip):
        parsed = parse_embedded_us_address(mailing_street)
        if parsed:
            _p_street, p_city, p_state, p_zip = parsed
            if not mailing_city and p_city:
                lead.mailing_city = p_city
                updated = True
            if not mailing_state and p_state:
                lead.mailing_state = p_state
                updated = True
            if not mailing_zip and p_zip:
                lead.mailing_zip = p_zip
                updated = True

    property_street = _clean(getattr(lead, 'property_street', None))
    property_city = _clean(getattr(lead, 'property_city', None))
    property_state = _clean(getattr(lead, 'property_state', None))
    property_zip = _clean(getattr(lead, 'property_zip', None))

    if property_street and not _complete_address(property_street, property_city, property_state, property_zip):
        parsed = parse_embedded_us_address(property_street)
        if parsed:
            _p_street, p_city, p_state, p_zip = parsed
            if not property_city and p_city:
                lead.property_city = p_city
                updated = True
            if not property_state and p_state:
                lead.property_state = p_state
                updated = True
            if not property_zip and p_zip:
                lead.property_zip = p_zip
                updated = True

    for field in _IDENTITY_FIELDS:
        if getattr(lead, field, None) != before[field]:
            # Restore and fail hard — enqueue must never rewrite dedup identity.
            for restore_field, value in before.items():
                setattr(lead, restore_field, value)
            raise RuntimeError(
                f'persist_embedded_address_fields must not mutate {field}'
            )

    return updated


def validate_lead_mail_address(lead: Lead) -> str | None:
    """Return validation error message, or None if mailable."""
    contact = lead_to_olc_contact(lead)
    if not contact.get('address1'):
        return 'No mailing or property street address'
    if not contact.get('city') or not contact.get('state') or not contact.get('zip'):
        return 'Incomplete city/state/zip for mailing address'
    return None


def lead_to_olc_contact(lead: Lead, *, user_id: str | None = None) -> dict[str, Any]:
    """Build an OLC contact dict from a lead."""
    mailing_street = _clean(getattr(lead, 'mailing_address', None))
    mailing_city = _clean(getattr(lead, 'mailing_city', None))
    mailing_state = _clean(getattr(lead, 'mailing_state', None))
    mailing_zip = _clean(getattr(lead, 'mailing_zip', None))

    property_street = _clean(getattr(lead, 'property_street', None))
    property_city = _clean(getattr(lead, 'property_city', None))
    property_state = _clean(getattr(lead, 'property_state', None))
    property_zip = _clean(getattr(lead, 'property_zip', None))

    mailing_street, mailing_city, mailing_state, mailing_zip = _merge_parsed_fields(
        mailing_street, mailing_city, mailing_state, mailing_zip, mailing_street,
    )
    property_street, property_city, property_state, property_zip = _merge_parsed_fields(
        property_street, property_city, property_state, property_zip, property_street,
    )

    if _complete_address(mailing_street, mailing_city, mailing_state, mailing_zip):
        address1, city, state, zip_code = (
            mailing_street, mailing_city, mailing_state, mailing_zip,
        )
    elif _complete_address(property_street, property_city, property_state, property_zip):
        address1, city, state, zip_code = (
            property_street, property_city, property_state, property_zip,
        )
    else:
        address1 = mailing_street or property_street
        city = mailing_city or property_city
        state = mailing_state or property_state
        zip_code = mailing_zip or property_zip

    phone = None
    for slot in ('phone_1', 'phone_2', 'phone_3', 'phone_4', 'phone_5', 'phone_6', 'phone_7'):
        raw = _clean(getattr(lead, slot, None))
        if raw:
            phone = raw
            break

    meta: dict[str, Any] = {'lead_id': lead.id}
    if user_id:
        meta['platform_user_id'] = user_id

    # address_2 is often a unit/suite line, but HubSpot additional_addresses may
    # land here as a full alternate street — never print those as OLC address2.
    raw_address2 = _clean(getattr(lead, 'address_2', None))
    address2 = None
    if raw_address2:
        lines = [p.strip() for p in re.split(r'[\n;]+', raw_address2) if p.strip()]
        # Omit when any line is a full US address (alternate mailing), or when
        # multi-line (ambiguous mix of unit + street).
        if len(lines) == 1 and not parse_embedded_us_address(lines[0]):
            address2 = lines[0]

    return {
        'firstName': _clean(getattr(lead, 'owner_first_name', None)),
        'lastName': _clean(getattr(lead, 'owner_last_name', None)),
        'address1': address1,
        'address2': address2,
        'city': city,
        'state': state,
        'zip': zip_code,
        'propertyAddress': property_street,
        'propertyCity': property_city,
        'propertyState': property_state,
        'propertyZip': property_zip,
        'campaign_phone': phone,
        'meta_data': meta,
    }


def lead_to_owner_olc_contact(
    lead: Lead,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Build an OLC payload using only the owner mailing destination."""
    contact = lead_to_olc_contact(lead, user_id=user_id)
    street, city, state, zip_code = owner_mailing_address(lead)
    contact.update({
        'address1': street,
        'city': city,
        'state': state,
        'zip': zip_code,
    })
    return contact
