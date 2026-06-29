"""Shared PIN parsing and normalization for Cook County data source plugins."""
import re
from typing import Optional


def extract_pin(address: str) -> Optional[str]:
    """Try to extract a Cook County PIN from an address string.

    PINs look like ``14-28-400-008-0000`` or ``14284000080000`` (14 digits).
    """
    if not address:
        return None

    address_stripped = address.strip()
    parts = address_stripped.replace("-", "").split()

    dash_match = re.match(r'^(\d{2}-\d{2}-\d{3}-\d{3}-\d{4})$', address_stripped)
    if dash_match:
        return dash_match.group(1)

    digit_match = re.match(r'^(\d{14})$', address_stripped)
    if digit_match:
        return digit_match.group(1)

    for word in parts:
        if re.match(r'^\d{14}$', word):
            return word

    return None


def normalize_pin_for_socrata(pin: str) -> str:
    """Normalize a PIN to the 14-digit format used in Cook County Socrata datasets."""
    if not pin:
        return pin
    return pin.replace("-", "").replace(" ", "").strip()
