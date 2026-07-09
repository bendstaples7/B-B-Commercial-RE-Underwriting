"""Parse US mailing addresses embedded in a single text field."""
from __future__ import annotations

import re

from app.services.plugins.cook_county_sheriff_foreclosure import (
    _CITY_SECOND_WORDS,
    _STREET_SUFFIXES,
    parse_sheriff_property_address,
)

_ZIP_RE = re.compile(r'^(\d{5})(?:-\d{4})?$')
_STATE_ZIP_RE = re.compile(r'^([A-Z]{2})\s*(\d{5})(?:-\d{4})?$', re.IGNORECASE)


def parse_embedded_us_address(raw: str) -> tuple[str, str, str, str] | None:
    """Parse (street, city, state, zip) from a one-line US address, or None if ambiguous."""
    text = (raw or '').strip()
    if not text:
        return None

    parsed = _parse_comma_separated(text)
    if parsed:
        return parsed

    parsed = _parse_space_separated_with_state(text)
    if parsed:
        return parsed

    return _parse_space_separated_no_state(text)


def _parse_comma_separated(raw: str) -> tuple[str, str, str, str] | None:
    parts = [p.strip() for p in raw.split(',') if p.strip()]
    if len(parts) < 3:
        return None

    last = parts[-1].upper()
    state_zip = _STATE_ZIP_RE.match(last.replace(' ', ''))
    if state_zip:
        state = state_zip.group(1).upper()
        zip_code = state_zip.group(2)
        city = parts[-2].strip()
        street = ', '.join(parts[:-2]).strip()
        if street and city:
            return street, city, state, zip_code
        return None

    state_zip_spaced = _STATE_ZIP_RE.match(last)
    if state_zip_spaced and len(parts) >= 3:
        state = state_zip_spaced.group(1).upper()
        zip_code = state_zip_spaced.group(2)
        city = parts[-2].strip()
        street = ', '.join(parts[:-2]).strip()
        if street and city:
            return street, city, state, zip_code

    return None


def _parse_space_separated_with_state(raw: str) -> tuple[str, str, str, str] | None:
    parts = re.sub(r'\s+', ' ', raw.strip()).split()
    if len(parts) < 4:
        return None

    zip_part = parts[-1]
    zip_match = _ZIP_RE.match(zip_part)
    if not zip_match:
        return None
    zip_code = zip_match.group(1)

    state = parts[-2].upper()
    if len(state) != 2 or not state.isalpha():
        return None

    if (
        len(parts) >= 5
        and parts[-3].upper() in _CITY_SECOND_WORDS
        and parts[-4].upper() not in _STREET_SUFFIXES
    ):
        city = f'{parts[-4]} {parts[-3]}'
        street_parts = parts[:-4]
    else:
        city = parts[-3]
        street_parts = parts[:-3]

    if not street_parts:
        return None

    street = ' '.join(street_parts).strip()
    city = city.strip()
    if not street or not city:
        return None
    return street, city, state, zip_code


def _parse_space_separated_no_state(raw: str) -> tuple[str, str, str, str] | None:
    parts = re.sub(r'\s+', ' ', raw.strip()).split()
    if len(parts) < 3:
        return None
    if not _ZIP_RE.match(parts[-1]):
        return None

    zip_code = parts[-1][:5]
    street, city, state = parse_sheriff_property_address(raw)
    if not street or not city:
        return None
    if city.upper() in ('IL', 'IN', 'WI') and len(city) == 2:
        return None
    return street, city, state or 'IL', zip_code
