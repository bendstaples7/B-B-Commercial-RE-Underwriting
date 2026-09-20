"""Shared text cleanup for CRM create/update validation."""
from __future__ import annotations

import unicodedata


def strip_invisible(value: str) -> str:
    """Remove control/format characters, then trim ends.

    Keeps real spaces in the middle so notes, names, and titles stay readable.
    All-whitespace or control-only input becomes empty (callers reject that).
    """
    cleaned = ''.join(
        ch for ch in value
        if ch in '\n\r\t' or not unicodedata.category(ch).startswith('C')
    )
    return cleaned.strip()
