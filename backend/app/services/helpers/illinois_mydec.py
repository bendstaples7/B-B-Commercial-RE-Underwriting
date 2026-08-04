"""Illinois MyDec PTAX-203 open-data helpers (data.illinois.gov).

Shared by DuPage bulk enrichment and Cook County sale-date resolve order.
Coverage starts ~2013 — pre-2013 deeds are out of reach of this feed.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Optional
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

PTAX_DATASET = "it54-y4c6"
PTAX_API = f"https://data.illinois.gov/resource/{PTAX_DATASET}.json"
PTAX_FIELDS = (
    "line_1_primary_pin,line_4_instrument_date,step_4_buyer_name,"
    "line_1_city,line_5_instrument_type"
)


def normalize_mydec_pin(pin: str, *, keep_digits: int | None = None) -> str:
    """Strip dashes/spaces from a PTAX or assessor PIN.

    DuPage GIS often stores 10-digit PINs; Cook Assessor uses 14 digits.
    When *keep_digits* is set, truncate to that many leading digits.
    """
    if not pin:
        return ""
    clean = pin.replace("-", "").replace(" ", "").strip()
    if keep_digits is not None and keep_digits > 0:
        return clean[:keep_digits]
    return clean


def parse_instrument_date(raw: str | None) -> Optional[date]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).split("T")[0]).date()
    except (ValueError, TypeError, AttributeError):
        return None


def fetch_most_recent_transfer_for_pin(
    pin: str,
    *,
    county: str,
    timeout: int = 30,
) -> Optional[dict]:
    """Return newest MyDec transfer for *pin* in *county*, or None.

    Result keys: ``acquisition_date`` (date), ``pin`` (normalized), optional
    ``buyer_name`` / ``instrument_type`` / ``raw_pin``.
    """
    normalized = normalize_mydec_pin(pin)
    if not normalized or not county:
        return None

    county_lit = county.replace("'", "''")
    # Try full digit string and (for Cook) common dashed form; also 10-digit prefix.
    candidates = [normalized]
    if len(normalized) == 14 and normalized.isdigit():
        dashed = (
            f"{normalized[0:2]}-{normalized[2:4]}-{normalized[4:7]}-"
            f"{normalized[7:10]}-{normalized[10:14]}"
        )
        candidates.append(dashed)
        candidates.append(normalized[:10])
    elif len(normalized) >= 10:
        candidates.append(normalized[:10])

    best: Optional[dict] = None
    seen_candidates: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen_candidates:
            continue
        seen_candidates.add(candidate)
        where = (
            f"line_1_county='{county_lit}' "
            f"AND line_4_instrument_date IS NOT NULL "
            f"AND line_1_primary_pin='{candidate}'"
        )
        url = (
            f"{PTAX_API}"
            f"?$select={PTAX_FIELDS}"
            f"&$where={quote(where)}"
            f"&$order=line_4_instrument_date+DESC"
            f"&$limit=5"
        )
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            rows = response.json()
        except Exception as exc:
            logger.warning(
                "MyDec fetch failed for county=%s pin=%r: %s",
                county, candidate, exc,
            )
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            deed = parse_instrument_date(row.get("line_4_instrument_date"))
            if deed is None:
                continue
            if best is None or deed > best["acquisition_date"]:
                best = {
                    "acquisition_date": deed,
                    "pin": normalize_mydec_pin(row.get("line_1_primary_pin") or candidate),
                    "raw_pin": row.get("line_1_primary_pin"),
                    "buyer_name": row.get("step_4_buyer_name"),
                    "instrument_type": row.get("line_5_instrument_type"),
                }
        if best is not None:
            break
    return best


def fetch_county_pin_to_date_map(
    county: str,
    *,
    pin_digits: int = 10,
    limit: Optional[int] = None,
    page_size: int = 5000,
) -> dict[str, date]:
    """Bulk-fetch MyDec transfers for *county* → PIN → newest deed date.

    Used by the DuPage weekly script. *pin_digits* defaults to 10 (DuPage GIS).
    """
    where = (
        f"line_1_county='{county.replace(chr(39), chr(39) * 2)}' "
        "AND line_4_instrument_date IS NOT NULL"
    )
    count_resp = requests.get(
        PTAX_API,
        params={"$select": "count(*)", "$where": where},
        timeout=30,
    )
    count_resp.raise_for_status()
    total = int(count_resp.json()[0]["count"])
    if limit is not None:
        total = min(total, limit)

    pin_to_date: dict[str, date] = {}
    offset = 0
    while offset < total:
        fetch_count = min(page_size, total - offset)
        records = None
        for attempt in range(3):
            try:
                response = requests.get(
                    PTAX_API,
                    params={
                        "$select": PTAX_FIELDS,
                        "$where": where,
                        "$limit": fetch_count,
                        "$offset": offset,
                        "$order": "line_4_instrument_date DESC",
                    },
                    timeout=45,
                )
                response.raise_for_status()
                records = response.json()
                break
            except Exception as exc:
                if attempt < 2:
                    logger.warning(
                        "MyDec fetch attempt %d failed: %s — retrying in 10s",
                        attempt + 1,
                        exc,
                    )
                    time.sleep(10)
                else:
                    raise
        if not records:
            break
        for rec in records:
            normalized = normalize_mydec_pin(
                rec.get("line_1_primary_pin", ""),
                keep_digits=pin_digits,
            )
            if not normalized:
                continue
            deed = parse_instrument_date(rec.get("line_4_instrument_date"))
            if deed is None:
                continue
            existing = pin_to_date.get(normalized)
            if existing is None or deed > existing:
                pin_to_date[normalized] = deed
        offset += len(records)
        time.sleep(0.1)  # polite rate limiting for bulk pulls
    return pin_to_date
