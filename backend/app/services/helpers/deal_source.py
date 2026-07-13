"""Canonical HubSpot-aligned deal source values and import normalizers."""
from __future__ import annotations

import re

# Keep in sync with frontend QUICK_ADD_DEAL_SOURCES and HubSpot deal_source enum.
DEAL_SOURCE_OPTIONS: tuple[str, ...] = (
    'Driving For Dollars',
    'Cityscape',
    'Cityscape Unused Zoning Capacity',
    'Referral',
    'Direct Mail',
    'CoStar',
    'Other',
)

_COSTAR_RE = re.compile(r'co[\s_-]*star', re.IGNORECASE)

# Exact (case-insensitive) map from common import / HubSpot values → canonical enum.
_EXACT_ALIASES: dict[str, str] = {
    option.lower(): option for option in DEAL_SOURCE_OPTIONS
}


def normalize_imported_source_to_deal_source(raw: str | None) -> str | None:
    """Map free-text import ``source`` to a HubSpot deal_source enum value.

    Returns None when the string cannot be mapped confidently.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    exact = _EXACT_ALIASES.get(text.lower())
    if exact:
        return exact

    if _COSTAR_RE.search(text):
        return 'CoStar'

    return None
