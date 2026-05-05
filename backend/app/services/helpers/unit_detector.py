"""Unit marker detection for property addresses.

Identifies whether a property address contains unit, apartment, or suite
markers that indicate the address refers to a specific unit within a
building rather than the building itself.
"""
import re


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

# Pattern for trailing alphanumeric unit suffix (e.g., "123 main st 1a")
_TRAILING_UNIT_SUFFIX_PATTERN = re.compile(
    r'\s+\d+[a-zA-Z]\s*$',
)


def has_unit_marker(address: str) -> bool:
    """Return True if address contains unit/apt/suite/ste/# markers or alphanumeric suffixes.

    Patterns detected (case-insensitive):
    - "unit", "apt", "apartment", "suite", "ste" followed by a value
    - "#" followed by a value
    - Trailing alphanumeric suffix pattern (e.g., "1a", "2b", "3n")

    Parameters
    ----------
    address : str
        The property address string to check.

    Returns
    -------
    bool
        True if a unit marker pattern is detected, False otherwise.
    """
    if not address:
        return False

    # Check named unit markers
    if _UNIT_MARKER_PATTERN.search(address):
        return True

    # Check # markers
    if _HASH_UNIT_PATTERN.search(address):
        return True

    # Check trailing alphanumeric suffix
    if _TRAILING_UNIT_SUFFIX_PATTERN.search(address):
        return True

    return False
