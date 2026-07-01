"""Map platform leads to Open Letter Connect contact payloads."""
from __future__ import annotations

from typing import Any

from app.models.lead import Lead


def _clean(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


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
