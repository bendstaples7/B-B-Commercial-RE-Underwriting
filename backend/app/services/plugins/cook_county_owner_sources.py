"""Per-PIN owner discovery from free Cook County / Chicago public sources."""
from __future__ import annotations

import logging
import re
from typing import Optional

import requests

from app.services.plugins.owner_name_utils import apply_owner_name_fields
from app.services.plugins.pin_utils import extract_pin, format_pin_for_storage

logger = logging.getLogger(__name__)

_PROPERTY_TAX_SEARCH_URL = (
    "https://www.cookcountypropertyinfo.com/Search/SearchByPin.aspx"
)
_CLERK_SEARCH_URL = "https://crs.cookcountyclerkil.gov/Search"


def _parse_mailing_address(html: str) -> dict:
    """Best-effort parse of tax bill mailing address from portal HTML."""
    fields: dict = {}
    patterns = [
        (
            "mailing_address",
            r"Tax Bill Mailing Address[^<]*</[^>]+>\s*<[^>]+>\s*([^<]+)",
        ),
        (
            "mailing_address",
            r"Mailing Address[^<]*</[^>]+>\s*<[^>]+>\s*([^<]+)",
        ),
    ]
    for field_name, pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = re.sub(r"\s+", " ", match.group(1)).strip()
            if value and value.lower() not in {"n/a", "none"}:
                fields[field_name] = value
                break

    city_state_zip = re.search(
        r"([A-Z][A-Za-z .'-]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
        html,
    )
    if city_state_zip:
        fields.setdefault("mailing_city", city_state_zip.group(1).strip())
        fields.setdefault("mailing_state", city_state_zip.group(2).strip())
        fields.setdefault("mailing_zip", city_state_zip.group(3).strip())
    return fields


def _fetch_property_tax_portal_owner(pin: str) -> dict:
    """Attempt to read mailing address from the Cook County Property Tax Portal."""
    dashed = format_pin_for_storage(pin)
    try:
        response = requests.get(
            _PROPERTY_TAX_SEARCH_URL,
            params={"pin": dashed},
            timeout=20,
            headers={"User-Agent": "B-B-Underwriting/1.0"},
        )
        if not response.ok:
            return {}
        return _parse_mailing_address(response.text)
    except requests.RequestException as exc:
        logger.warning("Property tax portal lookup failed for PIN=%r: %s", pin, exc)
        return {}


def _fetch_clerk_grantee(pin: str) -> Optional[str]:
    """Best-effort grantee name from Cook County Clerk recorded-documents search."""
    dashed = format_pin_for_storage(pin)
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": "B-B-Underwriting/1.0"})
        search_page = session.get(_CLERK_SEARCH_URL, timeout=20)
        if not search_page.ok:
            return None
        response = session.get(
            _CLERK_SEARCH_URL,
            params={"pin": dashed, "searchType": "pin"},
            timeout=20,
        )
        if not response.ok:
            return None
        for pattern in (
            r"Grantee[^<]*</[^>]+>\s*<[^>]+>\s*([^<]+)",
            r"Buyer[^<]*</[^>]+>\s*<[^>]+>\s*([^<]+)",
            r"defendant[^<]*</[^>]+>\s*<[^>]+>\s*([^<]+)",
        ):
            match = re.search(pattern, response.text, re.IGNORECASE)
            if match:
                name = re.sub(r"\s+", " ", match.group(1)).strip()
                if name:
                    return name
    except requests.RequestException as exc:
        logger.warning("Clerk CRS lookup failed for PIN=%r: %s", pin, exc)
    return None


def lookup_owner_fields(
    *,
    pin: Optional[str],
    address: str = "",
    city: Optional[str] = None,
) -> dict:
    """Aggregate owner hints from free public sources (per-PIN / per-address)."""
    fields: dict = {}
    sources: dict = {}

    resolved_pin = pin or extract_pin(address)
    if resolved_pin:
        clerk_grantee = _fetch_clerk_grantee(resolved_pin)
        if clerk_grantee:
            sources["clerk_grantee"] = clerk_grantee
            if not fields.get("owner_last_name"):
                apply_owner_name_fields(fields, clerk_grantee)

        mailing = _fetch_property_tax_portal_owner(resolved_pin)
        if mailing:
            sources["property_tax_portal"] = mailing
            for key in (
                "mailing_address",
                "mailing_city",
                "mailing_state",
                "mailing_zip",
            ):
                if mailing.get(key) and not fields.get(key):
                    fields[key] = mailing[key]

    if sources:
        fields["permit_data"] = {"owner_lookup_sources": sources}
    return fields
