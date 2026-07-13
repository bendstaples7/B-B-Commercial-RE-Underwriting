"""Canonical HubSpot-aligned deal source values and import normalizers."""
from __future__ import annotations

import re

# Keep in sync with frontend QUICK_ADD_DEAL_SOURCES and HubSpot deal_source enum.
# ``Listsource`` is the Master Skip Tracing list value; HubSpot often leaves
# deal_source blank and parks that text in description instead.
DEAL_SOURCE_OPTIONS: tuple[str, ...] = (
    'Driving For Dollars',
    'Cityscape',
    'Cityscape Unused Zoning Capacity',
    'Referral',
    'Direct Mail',
    'CoStar',
    'Listsource',
    'Other',
)

_COSTAR_RE = re.compile(r'co[\s_-]*star', re.IGNORECASE)
_LISTSOURCE_RE = re.compile(r'\blist[\s_-]*source\b', re.IGNORECASE)

# Exact (case-insensitive) map from common import / HubSpot values → canonical enum.
_EXACT_ALIASES: dict[str, str] = {
    option.lower(): option for option in DEAL_SOURCE_OPTIONS
}
_EXACT_ALIASES.update({
    'list source': 'Listsource',
    'list_source': 'Listsource',
    'list-source': 'Listsource',
})

_PROVENANCE_SOURCES = frozenset({'hubspot_import', 'google_sheets', 'manual'})


def normalize_imported_source_to_deal_source(raw: str | None) -> str | None:
    """Map free-text import ``source`` / description lead-in to a deal_source value.

    Returns None when the string cannot be mapped confidently.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    # Description rows often start with "Listsource Date ID: …"
    first_token = text.split(':', 1)[0].strip()
    exact = _EXACT_ALIASES.get(text.lower()) or _EXACT_ALIASES.get(first_token.lower())
    if exact:
        return exact

    if _COSTAR_RE.search(text):
        return 'CoStar'

    if _LISTSOURCE_RE.search(first_token) or _LISTSOURCE_RE.search(text[:40]):
        return 'Listsource'

    return None


def _canonical_hubspot_deal_source(raw: str | None) -> str | None:
    """Accept HubSpot deal_source enum values or map aliases."""
    text = (raw or '').strip()
    if not text:
        return None
    mapped = normalize_imported_source_to_deal_source(text)
    if mapped:
        return mapped
    # HubSpot may already store a canonical option we don't regex-map.
    return _EXACT_ALIASES.get(text.lower())


def _sheet_source_deal_source(source: str | None) -> str | None:
    """Map Google Sheet ``source`` column — equal peer to HubSpot deal_source."""
    text = (source or '').strip()
    if not text or text.lower() in _PROVENANCE_SOURCES:
        return None
    return normalize_imported_source_to_deal_source(text)


def resolve_blank_deal_source(
    *,
    current: str | None = None,
    hubspot_deal_source: str | None = None,
    sheet_source: str | None = None,
    deal_description: str | None = None,
) -> str | None:
    """Resolve deal_source when blank.

    Sheet ``source`` and HubSpot ``deal_source`` are **equal-priority** peers
    (fill-if-blank only; neither overwrites a set value). HubSpot ``description``
    is tertiary — used when Listsource was parked there with a blank HS enum.
    """
    existing = (current or '').strip() or None
    if existing:
        return existing

    sheet = _sheet_source_deal_source(sheet_source)
    hubspot = _canonical_hubspot_deal_source(hubspot_deal_source)
    # Equal peers: either may fill a blank. Prefer agreement; otherwise take the
    # first available (sheet listed first only as a stable tie-break, not rank).
    if sheet and hubspot:
        return sheet if sheet == hubspot else (sheet or hubspot)
    if sheet or hubspot:
        return sheet or hubspot

    return normalize_imported_source_to_deal_source(deal_description)


def infer_deal_source_from_lead_fields(
    *,
    source: str | None = None,
    deal_description: str | None = None,
    hubspot_deal_source: str | None = None,
) -> str | None:
    """Infer deal_source from sheet / HubSpot peers (and description if needed)."""
    return resolve_blank_deal_source(
        current=None,
        hubspot_deal_source=hubspot_deal_source,
        sheet_source=source,
        deal_description=deal_description,
    )
