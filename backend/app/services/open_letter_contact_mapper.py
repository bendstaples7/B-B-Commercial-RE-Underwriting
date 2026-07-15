"""Map platform leads to Open Letter Connect contact payloads."""
from __future__ import annotations

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
    returned = _clean(getattr(lead, 'returned_addresses', None))
    if returned:
        return 'Owner mailing address was previously returned'
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

    return {
        'firstName': _clean(getattr(lead, 'owner_first_name', None)),
        'lastName': _clean(getattr(lead, 'owner_last_name', None)),
        'address1': address1,
        'address2': _clean(getattr(lead, 'address_2', None)) or None,
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
