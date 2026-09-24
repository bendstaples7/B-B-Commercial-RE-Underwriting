"""Unit marker detection for property addresses.

Identifies whether a property address contains unit, apartment, or suite
markers that indicate the address refers to a specific unit within a
building rather than the building itself.

Prefer :func:`situs_unit_token_from_parts` when you need the comparable
token; this helper is the boolean “does this situs name a unit?” gate for
condo / building-ownership paths.
"""
from __future__ import annotations

import re
from typing import Optional


# Patterns for named unit markers followed by a value
_UNIT_MARKER_PATTERN = re.compile(
    r'\b(?:unit|apt|apartment|suite|ste)\s*[#.]?\s*\S+',
    re.IGNORECASE,
)

# Pattern for # followed by a value
_HASH_UNIT_PATTERN = re.compile(
    r'#\s*\S+',
    re.IGNORECASE,
)

# Pattern for trailing alphanumeric unit suffix (e.g., "123 main st 1a", "… Place L2")
_TRAILING_UNIT_SUFFIX_PATTERN = re.compile(
    r'\s+(?:\d+[a-zA-Z][a-zA-Z0-9-]*|[a-zA-Z]\d+[a-zA-Z0-9-]*)\s*$',
)


def _line_has_unit_marker(address: str) -> bool:
    if not address:
        return False
    if _UNIT_MARKER_PATTERN.search(address):
        return True
    if _HASH_UNIT_PATTERN.search(address):
        return True
    if _TRAILING_UNIT_SUFFIX_PATTERN.search(address):
        return True
    return False


def has_unit_marker(
    address: Optional[str],
    address_2: Optional[str] = None,
) -> bool:
    """Return True if street and/or address line 2 names a unit.

    Patterns detected (case-insensitive):
    - "unit", "apt", "apartment", "suite", "ste" followed by a value
    - "#" followed by a value
    - Trailing alphanumeric suffix pattern (e.g. "1a", "2b", "L2")
    - Tokens found by :func:`situs_unit_token_from_parts` (keeps GIS / condo
      gates aligned when the unit lives only on ``address_2``)
    """
    street = address if isinstance(address, str) else ''
    line2 = address_2 if isinstance(address_2, str) else ''
    if _line_has_unit_marker(street) or _line_has_unit_marker(line2):
        return True
    from app.services.lead_merge_utils import situs_unit_token_from_parts

    return bool(situs_unit_token_from_parts(street or None, line2 or None))
