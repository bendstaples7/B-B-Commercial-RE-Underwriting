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
    "gemini-3.5-flash:generateContent"
)
_TIMEOUT = (10, 900)  # (connect, read) seconds — per attempt
_MAX_RETRIES = 2       # retry up to 2 times after the initial attempt
_RETRY_BACKOFF = 2.0   # seconds — doubles each retry: 2s, 4s
_TOTAL_BUDGET_SECONDS = 1000  # hard wall-clock ceiling for the entire call chain
                               # (connect + all retries + backoff waits)
                               # Celery task time_limit must be set higher than this


def _get_api_key() -> str:
    key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "GOOGLE_AI_API_KEY is not set. Cannot call Gemini API."
        )
    return key


def _call_gemini(prompt: str) -> str:
    """Call Gemini with Google Search grounding and return the text response.

    Enforces a hard total budget of _TOTAL_BUDGET_SECONDS across all attempts
    and retries. If the budget expires, raises RuntimeError with a clear message
    so the controller can return a proper 504 instead of dropping the connection.

    Retries up to _MAX_RETRIES times on transient failures:
      - Network errors (timeout, connection reset)
      - HTTP 5xx responses (server-side errors)

    Does NOT retry on HTTP 4xx (client errors — permanent failures).
    """
    import time as _time
    api_key = _get_api_key()
    budget_start = _time.monotonic()

    request_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.1,
        },
    }

    last_error: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        # Check total budget before each attempt
        elapsed = _time.monotonic() - budget_start
        remaining = _TOTAL_BUDGET_SECONDS - elapsed
        if remaining <= 0:
            raise RuntimeError(
                f"Gemini API call exceeded the {_TOTAL_BUDGET_SECONDS}s total time budget "
                f"after {attempt} attempt(s). The AI service is too slow right now — "
                f"please try again in a few minutes."
            )

        if attempt > 0:
            wait = _RETRY_BACKOFF * (2 ** (attempt - 1))  # 2s, 4s
            # Don't wait longer than the remaining budget
            wait = min(wait, remaining - 5)
            if wait <= 0:
                raise RuntimeError(
                    f"Gemini API call exceeded the {_TOTAL_BUDGET_SECONDS}s total time budget "
                    f"during retry backoff. Please try again in a few minutes."
                )
            logger.warning(
                "AICompService: Gemini attempt %d/%d failed, retrying in %.0fs: %s",
                attempt, _MAX_RETRIES + 1, wait, last_error,
            )
            time.sleep(wait)

        # Clamp per-attempt read timeout to remaining budget
        elapsed = _time.monotonic() - budget_start
        remaining = _TOTAL_BUDGET_SECONDS - elapsed
        allowed = max(0, remaining - 2)
        connect_timeout = min(_TIMEOUT[0], allowed)
        read_timeout = min(_TIMEOUT[1], max(0, allowed - connect_timeout))
        attempt_timeout = (connect_timeout, read_timeout)

        try:
            response = requests.post(
                _GEMINI_API_URL,
                params={"key": api_key},
                json=request_body,
                timeout=attempt_timeout,
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
    radius_miles: int = 2,
) -> str:
    """Build the Gemini prompt for fetching sale comps."""
    unit_mix_lines = "\n".join(
        f"  - {row.get('unit_type', 'Unknown')}: {row.get('count', '?')} units, "
        f"{row.get('sqft', '?')} sqft each"
        for row in unit_mix
    )

    unit_min = max(1, round(unit_count * 0.5))
    unit_max = round(unit_count * 1.5)
    cutoff_year = cutoff_date[:4]

    return f"""You are a commercial real estate research assistant with access to Google Search.

I am analyzing a multifamily investment property and need recent sale comparables.

## Subject Property
Address: {address}
Total Units: {unit_count}
Unit Mix:
{unit_mix_lines}

## Research Task
Search for recent multifamily property sales and active listings in the vicinity of {address}.

Requirements:
- No comps older than the date {cutoff_date} (going back to {cutoff_year})
- Properties must be within {radius_miles} miles of the subject property
- Include a mix of sold and active listings, but prioritize sold comps
- Target properties with similar unit counts ({unit_min}–{unit_max} units preferred, but include others if needed to reach 8+ comps)

## For each comparable, provide:
1. Full street address
2. Unit count
3. Sale status (Sold, Active, or Under Contract)
4. Closing date (or listing date for active)
5. Sale price (or list price for active)
6. Annual NOI (net operating income) if available
7. Cap rate if available or derivable from NOI and price
8. Price per unit (sale price ÷ unit count)
9. Approximate distance from subject property

## Required Output Format
Return a JSON array. Each element must have exactly these fields:
{{
  "address": "full street address",
  "unit_count": <integer>,
  "status": "Sold" or "Active" or "Under Contract",
  "sale_price": <number, no $ or commas>,
  "close_date": "YYYY-MM-DD",
  "observed_cap_rate": <decimal e.g. 0.065 for 6.5%, or null if unknown>,
  "noi": <annual NOI as a number, or null if unknown>,
  "distance_miles": <decimal, or null>
}}

Return ONLY the JSON array — no markdown, no explanation, no extra text.
Aim for 8–12 comps. Do NOT guess or estimate cap rates — only include them if you have a reliable source.
If NOI and sale price are both known, include the NOI and the system will derive the cap rate.
"""


def fetch_sale_comps(deal_address: str, unit_count: int, unit_mix: list[dict]) -> list[dict]:
    """Call Gemini to fetch sale comps for a deal.

    Uses a tiered search strategy:
      Pass 1: 2-mile radius, last 12 months
      Pass 2 (if < 5 comps returned): 5-mile radius, last 24 months

    Args:
        deal_address: Full address of the subject property.
        unit_count: Total number of units in the subject property.
        unit_mix: List of dicts with keys: unit_type, count, sqft.

    Returns:
        List of sale comp dicts with keys matching the SaleComp model.

    Raises:
        RuntimeError: If Gemini call fails or response cannot be parsed.
    """
    cutoff_12mo = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
    cutoff_24mo = (date.today() - timedelta(days=730)).strftime("%Y-%m-%d")

    logger.info("AICompService: fetching sale comps for %s (pass 1: 2mi / 12mo)", deal_address)
    prompt_pass1 = _build_sale_comp_prompt(deal_address, unit_count, unit_mix, cutoff_12mo, radius_miles=2)
    text = _call_gemini(prompt_pass1)
    comps = _parse_sale_comp_response(text, unit_count)
    logger.info("AICompService: pass 1 returned %d comps", len(comps))

    if len(comps) < 5:
        logger.info(
            "AICompService: fewer than 5 comps from pass 1 — running pass 2 (5mi / 24mo)"
        )
        prompt_pass2 = _build_sale_comp_prompt(deal_address, unit_count, unit_mix, cutoff_24mo, radius_miles=5)
        text2 = _call_gemini(prompt_pass2)
        comps2 = _parse_sale_comp_response(text2, unit_count)
        logger.info("AICompService: pass 2 returned %d comps", len(comps2))

        # Merge, deduplicating by address (pass 1 takes precedence)
        existing_addresses = {c["address"].lower() for c in comps}
        for c in comps2:
            if c["address"].lower() not in existing_addresses:
                comps.append(c)
                existing_addresses.add(c["address"].lower())

        logger.info("AICompService: merged total %d comps after pass 2", len(comps))

    return comps


def _parse_sale_comp_response(text: str, unit_count: int) -> list[dict]:
    """Parse and validate Gemini's sale comp response text into a list of comp dicts."""
    data = _extract_json_from_text(text)

    if not isinstance(data, list):
        raise RuntimeError(
            f"Expected a JSON array of sale comps, got: {type(data).__name__}"
        )

    comps = []
    unit_min = max(1, round(unit_count * 0.5))
    unit_max = round(unit_count * 1.5)

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("AICompService: sale comp[%d] is not a dict, skipping", i)
            continue
        try:
            cap_rate_raw = item.get("observed_cap_rate")
            cap_rate = float(cap_rate_raw) if cap_rate_raw is not None else None

            noi_raw = item.get("noi")
            noi = float(noi_raw) if noi_raw is not None else None

            dist_raw = item.get("distance_miles")
            distance = float(dist_raw) if dist_raw is not None else None

            comp_unit_count = int(item["unit_count"])
            out_of_range = not (unit_min <= comp_unit_count <= unit_max)

            comp = {
                "address": str(item.get("address", "")).strip(),
                "unit_count": comp_unit_count,
                "status": str(item.get("status", "Sold")).strip(),
                "sale_price": float(item["sale_price"]),
                "close_date": str(item.get("close_date", date.today().isoformat())),
                "observed_cap_rate": cap_rate,
                "noi": noi,
                "distance_miles": distance,
                "out_of_range": out_of_range,
            }
            if not comp["address"] or comp["unit_count"] <= 0 or comp["sale_price"] <= 0:
                logger.warning("AICompService: sale comp[%d] has invalid fields, skipping: %s", i, item)
                continue

            if out_of_range:
                logger.info(
                    "AICompService: sale comp[%d] unit_count=%d outside range [%d, %d] — flagging: %s",
                    i, comp_unit_count, unit_min, unit_max, comp["address"],
                )

            comps.append(comp)
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("AICompService: sale comp[%d] parse error: %s — %s", i, exc, item)
            continue

    logger.info("AICompService: parsed %d sale comps", len(comps))
    return comps
