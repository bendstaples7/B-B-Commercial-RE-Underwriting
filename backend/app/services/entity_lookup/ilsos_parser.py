"""Fixed-width parsers for Illinois SOS LLC Transparency Act bulk dumps.

Field layouts reference the public fixed-width exports documented by the
community (fgregg/il-corporate-filings schemas); we download files from
ilsos.gov ourselves — no interactive SOS search scraping.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional


# column, start, length — from public schema layouts
NAME_SCHEMA = (
    ("file_number", 0, 8),
    ("name", 8, 120),
)

MANAGER_SCHEMA = (
    ("file_number", 0, 8),
    ("mm_name", 8, 60),
    ("mm_street", 68, 45),
    ("mm_city", 113, 30),
    ("mm_juris", 143, 2),
    ("mm_zip", 145, 9),
    ("mm_file_date", 154, 8),
    ("mm_type_code", 162, 1),
)

AGENT_SCHEMA = (
    ("file_number", 0, 8),
    ("agent_code", 8, 1),
    ("agent_name", 9, 60),
    ("agent_street", 69, 45),
    ("agent_city", 114, 30),
    ("agent_zip", 144, 9),
    ("agent_county_code", 153, 3),
    ("agent_change_date", 156, 8),
)

MASTER_SCHEMA = (
    ("file_number", 0, 8),
    ("purpose_code", 8, 6),
    ("status_code", 14, 2),
    ("status_date", 16, 8),
    ("organized_date", 24, 8),
    ("dissolution_date", 32, 8),
    ("management_type", 40, 1),
    ("juris_organized", 41, 2),
    ("records_off_street", 43, 45),
    ("records_off_city", 88, 30),
    ("records_off_zip", 118, 9),
    ("records_off_juris", 127, 2),
)

_HEADER_PREFIXES = ("RUN DATE", "END OF FILE")
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_LLC_VARIANTS = re.compile(
    r"\b(L\.?\s*L\.?\s*C\.?|LIMITED LIABILITY COMPANY|LIMITED LIABILITY CO)\b",
    re.I,
)


def normalize_llc_name(name: str) -> str:
    """Normalize an LLC legal name for exact matching."""
    cleaned = " ".join((name or "").upper().split())
    cleaned = _LLC_VARIANTS.sub("LLC", cleaned)
    cleaned = cleaned.replace(",", " ")
    cleaned = _NON_ALNUM.sub(" ", cleaned)
    return " ".join(cleaned.split())


def parse_fixed_width_line(line: str, schema: tuple[tuple[str, int, int], ...]) -> dict[str, str]:
    """Parse one fixed-width record into a dict of stripped strings."""
    # Mainframe dumps may use Latin-1; callers should decode before this.
    raw = line.rstrip("\r\n")
    out: dict[str, str] = {}
    for field, start, length in schema:
        out[field] = raw[start:start + length].strip()
    return out


def iter_data_lines(text: str) -> Iterator[str]:
    """Yield data lines, skipping header/trailer rows."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if any(upper.startswith(p) for p in _HEADER_PREFIXES):
            continue
        yield line


def parse_records(text: str, schema: tuple[tuple[str, int, int], ...]) -> list[dict[str, str]]:
    """Parse an entire fixed-width file body into records."""
    records = []
    for line in iter_data_lines(text):
        rec = parse_fixed_width_line(line, schema)
        # Skip empty / garbage rows
        if not rec.get("file_number"):
            continue
        records.append(rec)
    return records


def format_zip(raw_zip: Optional[str]) -> Optional[str]:
    """Format a 5- or 9-digit zip from the dump."""
    digits = re.sub(r"\D", "", raw_zip or "")
    if len(digits) >= 9:
        return f"{digits[:5]}-{digits[5:9]}"
    if len(digits) >= 5:
        return digits[:5]
    return digits or None
