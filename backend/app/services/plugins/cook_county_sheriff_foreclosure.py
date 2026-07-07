"""Cook County Sheriff foreclosure auction listings (HTML scrape)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_SHERIFF_URL = "https://foreclosure.ccsheriff.org/"
_OPEN_STATUSES = frozenset({"OPEN", "ACTIVE", "PENDING"})
_CACHE: tuple[datetime, list[dict]] | None = None
_CACHE_TTL = timedelta(hours=6)


_STREET_SUFFIXES = frozenset({
    "AVE", "AVENUE", "ST", "STREET", "DR", "DRIVE", "RD", "ROAD", "LN", "LANE",
    "BLVD", "BOULEVARD", "CT", "COURT", "CIR", "CIRCLE", "TER", "TERRACE", "WAY",
})
_CITY_SECOND_WORDS = frozenset({
    "PARK", "FOREST", "GROVE", "HILLS", "RIDGE", "LAKE", "HEIGHTS", "GARDENS",
    "BEACH", "LAWN", "CITY", "WOODS", "DALE",
})


def parse_sheriff_property_address(raw: str) -> tuple[str, str, str]:
    """Parse 'STREET  CITY  ZIP' from sheriff listing text."""
    text = re.sub(r"\s+", " ", (raw or "").strip().upper())
    if not text:
        return "", "", "IL"
    parts = text.split()
    if len(parts) < 3 or not parts[-1].isdigit() or len(parts[-1]) != 5:
        return (raw or "").strip(), "", "IL"

    if len(parts) >= 4 and parts[-2] in _CITY_SECOND_WORDS and parts[-3] not in _STREET_SUFFIXES:
        city = f"{parts[-3]} {parts[-2]}"
        street = " ".join(parts[:-3])
    else:
        city = parts[-2]
        street = " ".join(parts[:-2])
    return street.strip(), city.strip(), "IL"


def _parse_sale_date(raw: str) -> Optional[str]:
    text = (raw or "").strip()
    if not text or text.lower() == "not set":
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


def _parse_html_table(html: str) -> list[dict]:
    rows: list[dict] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(cells) < 7:
            continue
        clean = [re.sub(r"<[^>]+>", "", cell).strip() for cell in cells]
        case_number, file_number, address_raw, _bid, _attorney, sale_raw, status = clean[:7]
        if not case_number or case_number.lower() == "case number":
            continue
        street, city, state = parse_sheriff_property_address(address_raw)
        rows.append({
            "case_number": case_number,
            "sheriff_file_number": file_number,
            "property_address": address_raw,
            "property_street": street,
            "property_city": city,
            "property_state": state,
            "sale_date": _parse_sale_date(sale_raw),
            "case_status": status,
            "address": street or address_raw,
            "city": city or "",
        })
    return rows


def fetch_cook_county_foreclosure_listings(*, force_refresh: bool = False) -> list[dict]:
    """Return open sheriff foreclosure auction rows."""
    global _CACHE
    now = datetime.utcnow()
    if not force_refresh and _CACHE is not None:
        cached_at, cached_rows = _CACHE
        if now - cached_at < _CACHE_TTL:
            return list(cached_rows)

    try:
        response = requests.get(_SHERIFF_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Cook County sheriff foreclosure fetch failed: %s", exc)
        if _CACHE is not None:
            return list(_CACHE[1])
        return []

    parsed = _parse_html_table(response.text)
    open_rows = [
        row for row in parsed
        if (row.get("case_status") or "").strip().upper() in _OPEN_STATUSES
    ]
    _CACHE = (now, open_rows)
    return list(open_rows)
