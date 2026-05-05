"""Address normalization for building-level grouping.

Strips unit/suite/apartment identifiers from property addresses to produce
a building-level normalized address used as the grouping key for condo
filter analysis.
"""
import re


# Patterns for unit markers followed by a value (e.g., "unit 4", "apt 2b", "#301")
_UNIT_MARKER_PATTERN = re.compile(
    r'\b(?:unit|apt|apartment|suite|ste)\s*[#.]?\s*\S+',
    re.IGNORECASE,
)

# Pattern for # followed by a value (e.g., "#4", "# 301")
_HASH_UNIT_PATTERN = re.compile(
    r'#\s*\S+',
    re.IGNORECASE,
)

# Pattern for trailing alphanumeric unit suffix (e.g., "123 main st 1a")
# Matches a trailing token that is a digit followed by a letter
_TRAILING_UNIT_SUFFIX_PATTERN = re.compile(
    r'\s+\d+[a-zA-Z]$',
)


def normalize_address(address: str) -> str:
    """Strip unit markers, normalize case/whitespace, return building-level address.

    Strips: unit, apt, apartment, suite, ste, # (and their values)
    Strips: alphanumeric unit suffixes (e.g., "1a", "2b", "3r")
    Normalizes: lowercase, collapse whitespace, strip leading/trailing

    Idempotent: normalize(normalize(x)) == normalize(x)

    Parameters
    ----------
    address : str
        The raw property address string.

    Returns
    -------
    str
        The normalized building-level address.
    """
    if not address:
        return ""

    result = address

    # Strip unit markers with their values
    result = _UNIT_MARKER_PATTERN.sub('', result)

    # Strip # markers with their values
    result = _HASH_UNIT_PATTERN.sub('', result)

    # Normalize to lowercase
    result = result.lower()

    # Strip trailing alphanumeric unit suffixes (e.g., "1a", "2b")
    result = _TRAILING_UNIT_SUFFIX_PATTERN.sub('', result)

    # Collapse whitespace and strip
    result = re.sub(r'\s+', ' ', result).strip()

    return result
