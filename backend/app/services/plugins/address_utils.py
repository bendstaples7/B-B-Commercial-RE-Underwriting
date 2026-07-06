"""Address normalization helpers for Chicago open-data lookups."""
from __future__ import annotations

import re
from typing import Optional


_DIRECTION_MAP = {
    r"\bNORTH\b": "N",
    r"\bSOUTH\b": "S",
    r"\bEAST\b": "E",
    r"\bWEST\b": "W",
}
_SUFFIX_MAP = {
    r"\bAVENUE\b": "AVE",
    r"\bBOULEVARD\b": "BLVD",
    r"\bCIRCLE\b": "CIR",
    r"\bCOURT\b": "CT",
    r"\bDRIVE\b": "DR",
    r"\bLANE\b": "LN",
    r"\bPLACE\b": "PL",
    r"\bROAD\b": "RD",
    r"\bSTREET\b": "ST",
    r"\bTERRACE\b": "TER",
}


def normalize_chicago_street(address: str) -> str:
    """Normalize a street address to Chicago open-data style (e.g. 7464 N SHERIDAN RD)."""
    street_part = (address or "").split(",")[0].strip().upper()
    for pattern, abbr in _DIRECTION_MAP.items():
        street_part = re.sub(pattern, abbr, street_part)
    for pattern, abbr in _SUFFIX_MAP.items():
        street_part = re.sub(pattern, abbr, street_part)
    street_part = re.sub(r"\s+", " ", street_part).strip()
    return street_part


def is_chicago_address(city: Optional[str] = None, address: str = "") -> bool:
    """Return True when the lead appears to be in Chicago."""
    if city and city.strip().upper() == "CHICAGO":
        return True
    return ", CHICAGO" in (address or "").upper()
