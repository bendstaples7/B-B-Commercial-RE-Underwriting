"""Mail creative presets and OLC return-address normalization."""
from __future__ import annotations

import copy
import re
import uuid
from typing import Any

_RGBA_RE = re.compile(
    r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*[\d.]+)?\s*\)',
    re.I,
)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def fill_to_hex(fill: Any) -> str | None:
    """Normalize OLC template fill to ``#RRGGBB`` when possible."""
    raw = _clean(fill)
    if not raw:
        return None
    if raw.startswith('#') and len(raw) in (4, 7):
        if not re.fullmatch(r'#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?', raw):
            return None
        if len(raw) == 4:
            return '#' + ''.join(ch * 2 for ch in raw[1:]).upper()
        return raw.upper()
    named = {
        'black': '#000000',
        'white': '#FFFFFF',
        'grey': '#808080',
        'gray': '#808080',
    }
    if raw.casefold() in named:
        return named[raw.casefold()]
    match = _RGBA_RE.fullmatch(raw)
    if match:
        r, g, b = (int(match.group(i)) for i in (1, 2, 3))
        return f'#{r:02X}{g:02X}{b:02X}'
    return raw


def ink_label_from_fill(fill: Any) -> str | None:
    """Human label for rollups; prefer hex when the fill is a color value."""
    hex_color = fill_to_hex(fill)
    if not hex_color:
        return None
    if hex_color.startswith('#') and len(hex_color) == 7:
        return hex_color
    return _clean(fill)


def _iter_template_nodes(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_template_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_template_nodes(item)


def extract_letter_body_style(design: dict[str, Any] | None) -> dict[str, str | None]:
    """Pull body font + ink from an OLC template design JSON.

    Prefers the primary letter body text node (merge tags / longest copy),
    not footer / trim-guide chrome.
    """
    if not isinstance(design, dict):
        return {'font_name': None, 'font_color': None, 'fill': None}

    candidates: list[tuple[int, dict[str, Any]]] = []
    for node in _iter_template_nodes(design):
        if str(node.get('type') or '').lower() != 'text':
            continue
        font = _clean(node.get('fontFamily') or node.get('font_family'))
        if not font:
            continue
        text = str(node.get('text') or '')
        score = len(text)
        upper = text.upper()
        if '{{C.FIRST_NAME}}' in upper or '{{C.PROPERTY_ADDRESS}}' in upper:
            score += 10_000
        if 'TRIM' in upper or 'GREEN LINE' in upper:
            score -= 5_000
        if font.casefold() in {'roboto', 'noto sans jp'} and score < 200:
            score -= 500
        candidates.append((score, node))

    if not candidates:
        return {'font_name': None, 'font_color': None, 'fill': None}

    candidates.sort(key=lambda item: item[0], reverse=True)
    body = candidates[0][1]
    fill = _clean(body.get('fill') or body.get('color'))
    return {
        'font_name': _clean(body.get('fontFamily') or body.get('font_family')),
        'font_color': ink_label_from_fill(fill),
        'fill': fill,
    }


def format_mailer_phone(phone: str | None) -> str | None:
    """Normalize to ``(XXX) XXX-XXXX`` when 10 US digits (or 11 with leading 1)."""
    raw = _clean(phone)
    if not raw:
        return None
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    if len(digits) == 10:
        return f'({digits[:3]}) {digits[3:6]}-{digits[6:]}'
    return raw


def split_legacy_name(name: str | None) -> tuple[str | None, str | None]:
    """Split a single 'Name / company' string into first/last for OLC."""
    raw = _clean(name)
    if not raw:
        return None, None
    raw = raw.split('/', 1)[0].strip()
    if not raw:
        return None, None
    parts = raw.split(None, 1)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


def normalize_preset(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize one creative preset to the canonical shape."""
    data = dict(raw or {})
    preset_id = _clean(data.get('id')) or str(uuid.uuid4())
    first = _clean(data.get('first_name'))
    last = _clean(data.get('last_name'))
    if not first and not last:
        legacy_first, legacy_last = split_legacy_name(data.get('name') or data.get('sender_display_name'))
        first = first or legacy_first
        last = last or legacy_last
    phone = format_mailer_phone(data.get('phone'))
    email = _clean(data.get('email'))
    website = _clean(data.get('website'))
    include_email = bool(data.get('include_email', bool(email)))
    include_website = bool(data.get('include_website', bool(website)))
    display = ' '.join(p for p in (first, last) if p) or None
    label = _clean(data.get('label')) or display or 'Untitled creative'
    template_id = data.get('olc_template_id')
    try:
        template_id = int(template_id) if template_id is not None and str(template_id).strip() != '' else None
    except (TypeError, ValueError):
        template_id = None
    return {
        'id': preset_id,
        'label': label,
        'first_name': first,
        'last_name': last,
        'phone': phone,
        'email': email,
        'website': website,
        'include_email': include_email,
        'include_website': include_website,
        'envelope_color': _clean(data.get('envelope_color')),
        'font_name': _clean(data.get('font_name')),
        'font_color': _clean(data.get('font_color')),
        'olc_template_id': template_id,
        'olc_template_name': _clean(data.get('olc_template_name')),
        'sender_display_name': display,
    }


def normalize_presets(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [normalize_preset(item) for item in raw if isinstance(item, dict)]


def get_active_preset(
    presets: list[dict[str, Any]] | None,
    active_id: str | None,
) -> dict[str, Any] | None:
    items = normalize_presets(presets or [])
    if not items:
        return None
    aid = _clean(active_id)
    if aid:
        for item in items:
            if item['id'] == aid:
                return item
    return items[0]


def validate_sender_ready(preset: dict[str, Any] | None) -> str | None:
    """Return an error when the active creative cannot fill SPF / envelope name."""
    if preset is None:
        return 'Create and select a creative preset with sender name and phone'
    if not _clean(preset.get('first_name')):
        return 'Active creative preset needs a sender first name'
    if not _clean(preset.get('phone')):
        return 'Active creative preset needs a sender phone number'
    return None


def apply_template_style_to_preset(
    preset: dict[str, Any] | None,
    style: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Stamp auto-confirmed font/ink from the OLC template onto a preset."""
    if preset is None:
        return None
    out = dict(preset)
    if not style:
        return out
    font = _clean(style.get('font_name'))
    color = _clean(style.get('font_color'))
    if font:
        out['font_name'] = font
    if color:
        out['font_color'] = color
    return out


def street_return_address(raw: dict[str, Any] | None) -> dict[str, str] | None:
    """Extract street-only return address fields from config JSON."""
    if not isinstance(raw, dict):
        return None
    address1 = _clean(raw.get('address1'))
    city = _clean(raw.get('city'))
    state = _clean(raw.get('state'))
    zip_code = _clean(raw.get('zip'))
    if not (address1 and city and state and zip_code):
        return None
    out: dict[str, str] = {
        'address1': address1,
        'city': city,
        'state': state,
        'zip': zip_code,
    }
    address2 = _clean(raw.get('address2'))
    if address2:
        out['address2'] = address2
    return out


def build_olc_return_address(
    street: dict[str, str] | None,
    preset: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """OLC-shaped returnAddress for place_order (firstName/lastName/phoneNo/...)."""
    if not street:
        return None
    preset = normalize_preset(preset) if preset else {}
    email = _clean(preset.get('email')) if preset.get('include_email') else None
    website = _clean(preset.get('website')) if preset.get('include_website') else None
    payload: dict[str, Any] = {
        'firstName': _clean(preset.get('first_name')),
        'lastName': _clean(preset.get('last_name')),
        'address1': street['address1'],
        'city': street['city'],
        'state': street['state'],
        'zip': street['zip'],
        'phoneNo': format_mailer_phone(preset.get('phone')),
    }
    if street.get('address2'):
        payload['address2'] = street['address2']
    # Omit empty optional keys — OLC Place Order examples use present values only.
    if email:
        payload['email'] = email
    if website:
        payload['websiteUrl'] = website
    return payload


def default_return_address_settings() -> dict[str, bool]:
    return {
        'firstName': True,
        'lastName': True,
        'companyName': False,
        'fullAddress': True,
    }


def snapshot_creative(
    preset: dict[str, Any] | None,
    *,
    template_id: int | None = None,
    template_name: str | None = None,
    product_id: int | None = None,
    envelope_type: str | None = None,
) -> dict[str, Any] | None:
    """Frozen creative metadata stamped onto MailCampaign.creative."""
    if preset is None:
        return None
    snap = copy.deepcopy(normalize_preset(preset))
    if template_id is not None:
        snap['olc_template_id'] = template_id
    if template_name:
        snap['olc_template_name'] = template_name
    if product_id is not None:
        snap['olc_product_id'] = product_id
    # Prefer explicit OLC envelopeType string for historical grouping.
    if envelope_type:
        snap['envelope_color'] = _clean(envelope_type) or snap.get('envelope_color')
        snap['olc_envelope_type'] = _clean(envelope_type)
    elif snap.get('envelope_color'):
        snap['olc_envelope_type'] = snap['envelope_color']
    return snap


def migrate_legacy_return_into_presets(
    return_address: dict[str, Any] | None,
    presets: list[dict[str, Any]] | None,
    active_id: str | None,
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any] | None]:
    """If configs only have legacy ``name``, seed a default preset once."""
    normalized = normalize_presets(presets)
    street = street_return_address(return_address)
    legacy_name = _clean((return_address or {}).get('name')) if isinstance(return_address, dict) else None
    if normalized:
        return normalized, _clean(active_id) or normalized[0]['id'], street

    if not legacy_name and not _clean((return_address or {}).get('phone') if isinstance(return_address, dict) else None):
        return [], None, street

    first, last = split_legacy_name(legacy_name)
    phone = format_mailer_phone(
        (return_address or {}).get('phone') or (return_address or {}).get('phoneNo'),
    )
    email = _clean((return_address or {}).get('email'))
    website = _clean((return_address or {}).get('website') or (return_address or {}).get('websiteUrl'))
    preset = normalize_preset({
        'label': legacy_name or 'Default sender',
        'first_name': first,
        'last_name': last,
        'phone': phone,
        'email': email,
        'website': website,
        'include_email': bool(email),
        'include_website': bool(website),
    })
    return [preset], preset['id'], street


def format_mailing_line(street: str, city: str, state: str, zip_code: str) -> str:
    street = _clean(street) or ''
    city = _clean(city) or ''
    state = _clean(state) or ''
    zip_code = _clean(zip_code) or ''
    locality = ', '.join(p for p in (city, f'{state} {zip_code}'.strip()) if p)
    if street and locality:
        return f'{street}, {locality}'
    return street or locality


def creative_rollup_key(creative: dict[str, Any] | None) -> dict[str, Any]:
    """Dimensions used for campaign comparison tables."""
    c = creative or {}
    envelope = c.get('olc_envelope_type') or c.get('envelope_color') or '—'
    return {
        'sender_display_name': c.get('sender_display_name') or '—',
        'envelope_color': envelope,
        'font_name': c.get('font_name') or '—',
        'font_color': c.get('font_color') or '—',
        'include_email': bool(c.get('include_email')),
        'include_website': bool(c.get('include_website')),
    }
