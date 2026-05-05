"""Condo language detection for property type and assessor class fields.

Identifies whether property_type or assessor_class fields contain
terminology indicating condominium ownership structures.
"""
import re


# Condo-related terms to detect (case-insensitive)
# Order matters: check longer phrases first to avoid partial matches
_CONDO_TERMS = [
    "commercial condo",
    "condominium",
    "condo unit",
    "condo",
    "unit",
]

# Compiled pattern matching any condo term as a word boundary match
_CONDO_PATTERN = re.compile(
    r'\b(?:' + '|'.join(re.escape(term) for term in _CONDO_TERMS) + r')\b',
    re.IGNORECASE,
)


def has_condo_language(property_type: str | None, assessor_class: str | None) -> bool:
    """Return True if either field contains condo-related terminology.

    Terms detected (case-insensitive):
    - "condo", "condominium", "commercial condo", "condo unit", "unit"

    Parameters
    ----------
    property_type : str or None
        The property type field value.
    assessor_class : str or None
        The assessor class field value.

    Returns
    -------
    bool
        True if at least one field contains a recognized condo term,
        False otherwise.
    """
    if property_type and _CONDO_PATTERN.search(property_type):
        return True

    if assessor_class and _CONDO_PATTERN.search(assessor_class):
        return True

    return False
