"""Import / CRM signal fills for deal context (canonical with deal_source.py).

Authoritative GIS/assessor fields win when present. Blank lead fields may be
filled from HubSpot / Google Sheets deal_source + deal_description (e.g. CoStar
→ commercial, ``Units: 12`` in description → units).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.services.helpers.deal_source import normalize_imported_source_to_deal_source

# Deal sources that indicate commercial / investment inventory (not residential lists).
COMMERCIAL_DEAL_SOURCES: frozenset[str] = frozenset({
    'CoStar',
    'Cityscape',
    'Cityscape Unused Zoning Capacity',
})

_UNITS_IN_DESCRIPTION_RE = re.compile(
    r'\bunits?\s*[:=]\s*(\d{1,4})\b',
    re.IGNORECASE,
)


def is_commercial_deal_source(deal_source: str | None) -> bool:
    """True when deal_source is a known commercial inventory source."""
    text = (deal_source or '').strip()
    if not text:
        return False
    canonical = normalize_imported_source_to_deal_source(text) or text
    return canonical in COMMERCIAL_DEAL_SOURCES


def parse_units_from_deal_description(deal_description: str | None) -> int | None:
    """Extract unit count from CRM/sheet description text (e.g. ``Units: 12``)."""
    text = (deal_description or '').strip()
    if not text:
        return None
    match = _UNITS_IN_DESCRIPTION_RE.search(text)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return None
    if value < 1 or value > 5000:
        return None
    return value


def resolve_units_fill_if_blank(
    *,
    current_units: Any = None,
    deal_description: str | None = None,
) -> int | None:
    """Return units to store when the lead units field is blank."""
    if current_units is not None:
        try:
            if int(current_units) > 0:
                return None  # already set — do not overwrite
        except (TypeError, ValueError):
            pass
    return parse_units_from_deal_description(deal_description)


def resolve_commercial_category_fill_if_blank(
    *,
    current_category: str | None = None,
    deal_source: str | None = None,
) -> str | None:
    """Return ``commercial`` when category is blank/residential and deal_source says so.

    Does not downgrade an existing ``commercial`` value. Does not overwrite
    an explicit non-residential category other than the residential default.
    """
    category = (current_category or '').strip().lower() or 'residential'
    if category == 'commercial':
        return None
    if category != 'residential':
        return None
    if is_commercial_deal_source(deal_source):
        return 'commercial'
    return None


def apply_import_signal_fills(lead: Any) -> list[str]:
    """Fill blank lead fields from deal_source / deal_description. Returns changed attrs."""
    updated: list[str] = []
    deal_source = getattr(lead, 'deal_source', None)
    deal_description = getattr(lead, 'deal_description', None)

    units = resolve_units_fill_if_blank(
        current_units=getattr(lead, 'units', None),
        deal_description=deal_description,
    )
    if units is not None:
        lead.units = units
        updated.append('units')

    category_locked = bool(getattr(lead, 'lead_category_locked', False))
    category = None
    if not category_locked:
        category = resolve_commercial_category_fill_if_blank(
            current_category=getattr(lead, 'lead_category', None),
            deal_source=deal_source,
        )
        if category is not None:
            lead.lead_category = category
            updated.append('lead_category')

        # Fill blank property_type label when CoStar/commercial signals apply.
        property_type = getattr(lead, 'property_type', None)
        if (
            category == 'commercial' or is_commercial_deal_source(deal_source)
        ) and not (isinstance(property_type, str) and property_type.strip()):
            lead.property_type = 'Commercial'
            updated.append('property_type')

    return updated
