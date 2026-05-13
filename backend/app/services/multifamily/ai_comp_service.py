"""
AICompService — uses Gemini with Google Search grounding to fetch
rent comps and sale comps for a multifamily deal.

The service builds a structured prompt from the deal's address and unit mix,
calls the Gemini API with search grounding enabled (so it can look up recent
listings), parses the JSON response, and returns a list of comp dicts ready
to be inserted into the database.

Requirements: 3.2, 4.1
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, timedelta
from typing import Any

import requests

logger = logging.getLogger(__name__)

_GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)
_TIMEOUT = (10, 90)  # (connect, read) seconds
_MAX_RETRIES = 2       # retry up to 2 times after the initial attempt
_RETRY_BACKOFF = 2.0   # seconds — doubles each retry: 2s, 4s


def _get_api_key() -> str:
    key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "GOOGLE_AI_API_KEY is not set. Cannot call Gemini API."
        )
    return key


def _call_gemini(prompt: str) -> str:
    """Call Gemini with Google Search grounding and return the text response.

    Retries up to _MAX_RETRIES times on transient failures:
      - Network errors (timeout, connection reset)
      - HTTP 5xx responses (server-side errors)

    Does NOT retry on HTTP 4xx (client errors — permanent failures).
    """
    api_key = _get_api_key()

    request_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.1,
        },
    }

    last_error: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        if attempt > 0:
            wait = _RETRY_BACKOFF * (2 ** (attempt - 1))  # 2s, 4s
            logger.warning(
                "AICompService: Gemini attempt %d/%d failed, retrying in %.0fs: %s",
                attempt, _MAX_RETRIES + 1, wait, last_error,
            )
            time.sleep(wait)

        try:
            response = requests.post(
                _GEMINI_API_URL,
                params={"key": api_key},
                json=request_body,
                timeout=_TIMEOUT,
            )
        except requests.exceptions.Timeout as exc:
            last_error = RuntimeError("Gemini API request timed out.")
            continue  # retry on timeout
        except requests.exceptions.RequestException as exc:
            last_error = RuntimeError(f"Network error calling Gemini: {exc}")
            continue  # retry on network error

        # 4xx = client error — do not retry
        if 400 <= response.status_code < 500:
            raise RuntimeError(
                f"Gemini API returned HTTP {response.status_code}: {response.text[:400]}"
            )

        # 5xx = server error — retry
        if not response.ok:
            last_error = RuntimeError(
                f"Gemini API returned HTTP {response.status_code}: {response.text[:400]}"
            )
            continue

        # Success — parse and return
        try:
            resp_json = response.json()
        except ValueError as exc:
            last_error = RuntimeError("Gemini response is not valid JSON.")
            continue  # retry on parse error

        try:
            text = resp_json["candidates"][0]["content"]["parts"][0]["text"]
            return text
        except (KeyError, IndexError, TypeError) as exc:
            last_error = RuntimeError(
                f"Unexpected Gemini response structure: {exc}\n"
                f"Response: {str(resp_json)[:400]}"
            )
            continue  # retry on unexpected structure

    # All attempts exhausted
    raise last_error or RuntimeError("Gemini API call failed after all retries.")


def _extract_json_from_text(text: str) -> Any:
    """Extract a JSON array or object from Gemini's text response.

    Gemini with search grounding returns plain text, not JSON-mode output.
    We look for a JSON block (```json ... ``` or bare [...] / {...}).
    """
    # Try to find a ```json ... ``` block first
    import re
    json_block = re.search(r"```(?:json)?\s*([\[\{].*?[\]\}])\s*```", text, re.DOTALL)
    if json_block:
        try:
            return json.loads(json_block.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find a bare JSON array or object
    array_match = re.search(r"(\[[\s\S]*\])", text)
    if array_match:
        try:
            return json.loads(array_match.group(1))
        except json.JSONDecodeError:
            pass

    obj_match = re.search(r"(\{[\s\S]*\})", text)
    if obj_match:
        try:
            return json.loads(obj_match.group(1))
        except json.JSONDecodeError:
            pass

    raise RuntimeError(
        f"Could not extract JSON from Gemini response. "
        f"Raw text (first 500 chars): {text[:500]}"
    )


# ---------------------------------------------------------------------------
# Rent Comps
# ---------------------------------------------------------------------------

def _build_rent_comp_prompt(
    address: str,
    unit_mix: list[dict],
    cutoff_date: str,
) -> str:
    """Build the Gemini prompt for fetching rent comps."""
    unit_mix_lines = "\n".join(
        f"  - {row.get('unit_type', 'Unknown')}: {row.get('count', '?')} units, "
        f"{row.get('sqft', '?')} sqft each"
        for row in unit_mix
    )

    return f"""You are a commercial real estate research assistant with access to Google Search.

I need recent rental comparable data for a multifamily property.

## Subject Property
Address: {address}
Unit Mix:
{unit_mix_lines}

## Task
Search for recent rental listings or lease comps near {address} that are comparable to the unit types listed above.
Only include comps observed or listed after {cutoff_date} (within the last 12 months).
Focus on properties within a 1-mile radius when possible; expand to 2 miles if needed.

## Required Output
Return a JSON array. Each element must have exactly these fields:
{{
  "address": "full street address",
  "neighborhood": "neighborhood name or null",
  "unit_type": "e.g. 2BR/1BA",
  "observed_rent": <monthly rent as a number, no $ or commas>,
  "sqft": <square footage as integer>,
  "observation_date": "YYYY-MM-DD",
  "source_url": "URL of the listing or source, or null"
}}

Return ONLY the JSON array — no markdown, no explanation, no extra text.
If you cannot find comps for a unit type, omit it rather than guessing.
Aim for 3–5 comps per unit type.
"""


def fetch_rent_comps(deal_address: str, unit_mix: list[dict]) -> list[dict]:
    """Call Gemini to fetch rent comps for a deal.

    Args:
        deal_address: Full address of the subject property.
        unit_mix: List of dicts with keys: unit_type, count, sqft.

    Returns:
        List of rent comp dicts with keys matching the RentComp model:
        address, neighborhood, unit_type, observed_rent, sqft,
        observation_date, source_url.

    Raises:
        RuntimeError: If Gemini call fails or response cannot be parsed.
    """
    cutoff = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
    prompt = _build_rent_comp_prompt(deal_address, unit_mix, cutoff)

    logger.info("AICompService: fetching rent comps for %s", deal_address)
    text = _call_gemini(prompt)
    logger.debug("AICompService: rent comp raw response: %s", text[:500])

    data = _extract_json_from_text(text)

    if not isinstance(data, list):
        raise RuntimeError(
            f"Expected a JSON array of rent comps, got: {type(data).__name__}"
        )

    # Validate and clean each comp
    comps = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("AICompService: rent comp[%d] is not a dict, skipping", i)
            continue
        try:
            comp = {
                "address": str(item.get("address", "")).strip(),
                "neighborhood": item.get("neighborhood") or None,
                "unit_type": str(item.get("unit_type", "")).strip(),
                "observed_rent": float(item["observed_rent"]),
                "sqft": int(item["sqft"]),
                "observation_date": str(item.get("observation_date", date.today().isoformat())),
                "source_url": item.get("source_url") or None,
            }
            if not comp["address"] or not comp["unit_type"] or comp["observed_rent"] <= 0 or comp["sqft"] <= 0:
                logger.warning("AICompService: rent comp[%d] has invalid fields, skipping: %s", i, item)
                continue
            comps.append(comp)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("AICompService: rent comp[%d] parse error: %s — %s", i, exc, item)
            continue

    logger.info("AICompService: parsed %d rent comps", len(comps))
    return comps


# ---------------------------------------------------------------------------
# Sale Comps
# ---------------------------------------------------------------------------

def _build_sale_comp_prompt(
    address: str,
    unit_count: int,
    unit_mix: list[dict],
    cutoff_date: str,
) -> str:
    """Build the Gemini prompt for fetching sale comps."""
    unit_mix_lines = "\n".join(
        f"  - {row.get('unit_type', 'Unknown')}: {row.get('count', '?')} units, "
        f"{row.get('sqft', '?')} sqft each"
        for row in unit_mix
    )

    return f"""You are a commercial real estate research assistant with access to Google Search.

I need recent sale comparable data for a multifamily property.

## Subject Property
Address: {address}
Total Units: {unit_count}
Unit Mix:
{unit_mix_lines}

## Task
Search for recent multifamily property sales near {address}.
Only include sales or active listings from after {cutoff_date} (within the last 12 months).
Focus on properties within a 2-mile radius.
Include a mix of sold and active listings, but prioritize sold comps.
Target properties with similar unit counts (within 50% of {unit_count} units).

## Required Output
Return a JSON array. Each element must have exactly these fields:
{{
  "address": "full street address",
  "unit_count": <number of units as integer>,
  "status": "Sold" or "Active" or "Under Contract",
  "sale_price": <price as a number, no $ or commas>,
  "close_date": "YYYY-MM-DD (use listing date for active listings)",
  "observed_cap_rate": <cap rate as decimal e.g. 0.065 for 6.5%, or null if unknown>,
  "noi": <annual net operating income as a number, or null if unknown>,
  "distance_miles": <approximate distance from subject property as decimal, or null>
}}

Return ONLY the JSON array — no markdown, no explanation, no extra text.
Aim for 5–8 comps total.
If cap rate is not available but NOI and sale price are known, include the NOI — the system will derive the cap rate.
If neither cap rate nor NOI is available, set both to null — the comp will still be included without cap rate data.
Do NOT guess or estimate cap rates.
"""


def fetch_sale_comps(deal_address: str, unit_count: int, unit_mix: list[dict]) -> list[dict]:
    """Call Gemini to fetch sale comps for a deal.

    Args:
        deal_address: Full address of the subject property.
        unit_count: Total number of units in the subject property.
        unit_mix: List of dicts with keys: unit_type, count, sqft.

    Returns:
        List of sale comp dicts with keys matching the SaleComp model:
        address, unit_count, status, sale_price, close_date,
        observed_cap_rate, distance_miles.

    Raises:
        RuntimeError: If Gemini call fails or response cannot be parsed.
    """
    cutoff = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
    prompt = _build_sale_comp_prompt(deal_address, unit_count, unit_mix, cutoff)

    logger.info("AICompService: fetching sale comps for %s", deal_address)
    text = _call_gemini(prompt)
    logger.debug("AICompService: sale comp raw response: %s", text[:500])

    data = _extract_json_from_text(text)

    if not isinstance(data, list):
        raise RuntimeError(
            f"Expected a JSON array of sale comps, got: {type(data).__name__}"
        )

    comps = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("AICompService: sale comp[%d] is not a dict, skipping", i)
            continue
        try:
            # cap rate may be null — include the comp regardless
            cap_rate_raw = item.get("observed_cap_rate")
            cap_rate = float(cap_rate_raw) if cap_rate_raw is not None else None

            # noi may be null — used to derive cap rate when cap rate is missing
            noi_raw = item.get("noi")
            noi = float(noi_raw) if noi_raw is not None else None

            # distance may be null
            dist_raw = item.get("distance_miles")
            distance = float(dist_raw) if dist_raw is not None else None

            comp = {
                "address": str(item.get("address", "")).strip(),
                "unit_count": int(item["unit_count"]),
                "status": str(item.get("status", "Sold")).strip(),
                "sale_price": float(item["sale_price"]),
                "close_date": str(item.get("close_date", date.today().isoformat())),
                "observed_cap_rate": cap_rate,
                "noi": noi,
                "distance_miles": distance,
            }
            if not comp["address"] or comp["unit_count"] <= 0 or comp["sale_price"] <= 0:
                logger.warning("AICompService: sale comp[%d] has invalid fields, skipping: %s", i, item)
                continue

            # Log cap rate availability for transparency
            if cap_rate is not None:
                logger.debug("AICompService: sale comp[%d] has stated cap rate %.4f", i, cap_rate)
            elif noi is not None:
                logger.debug("AICompService: sale comp[%d] has NOI %.0f — cap rate will be derived", i, noi)
            else:
                logger.info("AICompService: sale comp[%d] has no cap rate or NOI — included without cap rate", i)

            comps.append(comp)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("AICompService: sale comp[%d] parse error: %s — %s", i, exc, item)
            continue

    logger.info("AICompService: parsed %d sale comps", len(comps))
    return comps
