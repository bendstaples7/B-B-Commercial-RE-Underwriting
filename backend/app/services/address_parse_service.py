"""Parse US mailing addresses embedded in a single text field."""
from __future__ import annotations

import re

from app.services.helpers.zip_lookup import city_state_from_zip
from app.services.plugins.cook_county_sheriff_foreclosure import (
    _CITY_SECOND_WORDS,
    _STREET_SUFFIXES,
    parse_sheriff_property_address,
)

_ZIP_RE = re.compile(r'^(\d{5})(?:-\d{4})?$')
_ZIP_SHORT_RE = re.compile(r'^(\d{3,4})$')
_STATE_ZIP_RE = re.compile(r'^([A-Z]{2})\s*(\d{5})(?:-\d{4})?$', re.IGNORECASE)

# USPS state / DC / territory abbreviations — reject street suffixes like ST/DR.
_US_STATE_CODES = frozenset({
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'DC', 'PR', 'VI', 'GU', 'AS', 'MP',
})


def street_looks_tabular(street: str) -> bool:
    """True when street still embeds city/state/zip as tab or multi-space columns."""
    return bool(street) and ('\t' in street or re.search(r' {2,}', street) is not None)


def parse_embedded_us_address(raw: str) -> tuple[str, str, str, str] | None:
    """Parse (street, city, state, zip) from a one-line US address, or None if ambiguous."""
    text = (raw or '').strip()
    if not text:
        return None

    # Tab / multi-column exports (HubSpot / assessor dumps) before space heuristics.
    parsed = _parse_tabular_separated(text)
    if parsed:
        return parsed

    parsed = _parse_comma_separated(text)
    if parsed:
        return parsed

    parsed = _parse_space_separated_with_state(text)
    if parsed:
        return parsed

    return _parse_space_separated_no_state(text)


def _normalize_zip5(raw: str, *, state: str | None = None) -> str | None:
    """Return a 5-digit ZIP, zero-padding short imports when state is known."""
    text = (raw or '').strip()
    if not text:
        return None
    match = _ZIP_RE.match(text)
    if match:
        return match.group(1)
    short = _ZIP_SHORT_RE.match(text)
    if short and state and state.upper() in _US_STATE_CODES:
        padded = short.group(1).zfill(5)
        looked_up = city_state_from_zip(padded)
        if looked_up and looked_up[1].upper() == state.upper():
            return padded
        # Still accept padded ZIP when lookup has no row (offline / rare ZIPs).
        if looked_up is None:
            return padded
    return None


def _parse_tabular_separated(raw: str) -> tuple[str, str, str, str] | None:
    """Parse ``street\\tcity\\tST\\tZIP`` (and multi-space column dumps)."""
    if '\t' in raw:
        parts = [p.strip() for p in raw.split('\t') if p.strip()]
    else:
        # Two-or-more spaces often mark columns in fixed-width / pasted dumps.
        parts = [p.strip() for p in re.split(r' {2,}', raw) if p.strip()]
    if len(parts) < 4:
        return None

    # Prefer trailing state + ZIP columns when more than 4 pieces.
    state = parts[-2].upper()
    if len(state) != 2 or state not in _US_STATE_CODES:
        return None
    zip_code = _normalize_zip5(parts[-1], state=state)
    if not zip_code:
        return None
    city = parts[-3].strip()
    street = ' '.join(parts[:-3]).strip()
    # Collapse leftover internal whitespace/tabs in street.
    street = re.sub(r'\s+', ' ', street).strip()
    if not street or not city:
        return None
    return street, city, state, zip_code


def street_only_from_glued_city_state_zip(raw: str) -> str | None:
    """If ``raw`` is ``street City ST ZIP`` (state required), return street line.

    Does not use zip-only parsing — that would mis-handle ``1719 W Barry 60657``.
    """
    text = (raw or '').strip()
    if not text or ',' in text:
        return None
    parsed = _parse_space_separated_with_state(text)
    if not parsed:
        return None
    street = (parsed[0] or '').strip()
    return street or None


def _parse_comma_separated(raw: str) -> tuple[str, str, str, str] | None:
    parts = [p.strip() for p in raw.split(',') if p.strip()]
    if len(parts) < 2:
        return None

    if len(parts) == 2:
        street = parts[0].strip()
        city_state_zip = _parse_city_state_zip(parts[1])
        if street and city_state_zip:
            city, state, zip_code = city_state_zip
            return street, city, state, zip_code
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


def parse_city_state_zip_line(raw: str) -> tuple[str, str, str] | None:
    """Parse ``City ST ZIP`` or ``City, ST ZIP`` into (city, state, zip5)."""
    text = re.sub(r'[,\s]+', ' ', (raw or '').strip())
    return _parse_city_state_zip(text)


def _parse_city_state_zip(raw: str) -> tuple[str, str, str] | None:
    parts = re.sub(r'\s+', ' ', raw.strip()).split()
    if len(parts) < 3:
        return None

    zip_raw = parts[-1]
    zip_match = _ZIP_RE.match(zip_raw)
    if not zip_match:
        # Allow ZIP+4 already stripped of hyphen via split
        zip_match = re.match(r'^(\d{5})(?:-\d{4})?$', zip_raw)
    if not zip_match:
        return None

    state = parts[-2].upper().rstrip(',')
    if len(state) != 2 or not state.isalpha() or state not in _US_STATE_CODES:
        return None

    city = ' '.join(parts[:-2]).strip().rstrip(',')
    if not city:
        return None
    return city, state, zip_match.group(1)


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
    if len(state) != 2 or not state.isalpha() or state not in _US_STATE_CODES:
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
    """Parse ``street … ZIP`` with no explicit state token.

    Prefer ZIP → city/state lookup and keep everything before the ZIP as the
    street (preserves original casing). Fall back to the sheriff token-as-city
    heuristic only when ZIP lookup fails, with a street-suffix guard so
    ``AVE``/``ST``/… are never treated as cities.
    """
    parts = re.sub(r'\s+', ' ', raw.strip()).split()
    # Need street + locality + ZIP (at least 3 tokens) so "Chicago 60657" is
    # not misclassified as a street address.
    if len(parts) < 3:
        return None
    zip_match = _ZIP_RE.match(parts[-1])
    if not zip_match:
        return None

    zip_code = zip_match.group(1)
    street_parts = parts[:-1]
    if not street_parts:
        return None
    street = ' '.join(street_parts).strip()
    if not street:
        return None

    looked_up = city_state_from_zip(zip_code)
    if looked_up:
        city, state = looked_up
        # Sheriff-style lines often include the city before the ZIP
        # (``… AVENUE CHICAGO 60622``). Strip a trailing city that matches the
        # ZIP lookup so the street is street-only.
        city_tokens = city.upper().split()
        street_upper_parts = [p.upper() for p in street_parts]
        if (
            len(street_upper_parts) > len(city_tokens)
            and street_upper_parts[-len(city_tokens):] == city_tokens
        ):
            street = ' '.join(street_parts[:-len(city_tokens)]).strip()
        if not street:
            return None
        # After stripping the city, require a remaining street distinct from locality
        # so ``Chicago 60657`` does not become a street-only parse.
        if street.upper() == city.upper():
            return None
        return street, city, state, zip_code

    # ZIP unknown — fall back to sheriff heuristic, but never accept a street
    # suffix (AVE/ST/DR/…) as the city token.
    sher_street, sher_city, sher_state = parse_sheriff_property_address(raw)
    if not sher_street or not sher_city:
        return None
    if sher_city.upper() in _STREET_SUFFIXES:
        return None
    if sher_city.upper() in ('IL', 'IN', 'WI') and len(sher_city) == 2:
        return None
    # Use the sheriff-cleaned street (locality stripped) with original casing when
    # available; sher_street is already street-only after the city token was taken.
    cleaned = sher_street.strip()
    city_out = sher_city.title() if sher_city.isupper() else sher_city
    return cleaned, city_out, sher_state or 'IL', zip_code
