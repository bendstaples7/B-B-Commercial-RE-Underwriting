"""
GeminiOMExtractorService — sends extracted PDF text to the Gemini API and
returns a structured ``ExtractedOMData`` object with per-field confidence
scores.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.8, 3.9, 3.10
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

from app.exceptions import (
    GeminiAPIError,
    GeminiConfigurationError,
    GeminiParseError,
    GeminiResponseError,
)
from app.services.om_intake.om_intake_dataclasses import ExtractedOMData

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)
_TIMEOUT_SECONDS = (10, 60)  # (connect_timeout, read_timeout) — caps both phases

# All scalar fields that should appear in the Gemini response as
# {"value": ..., "confidence": ...} dicts.
_SCALAR_FIELDS: list[str] = [
    # Property fields
    "property_address",
    "property_city",
    "property_state",
    "property_zip",
    "neighborhood",
    "asking_price",
    "price_per_unit",
    "price_per_sqft",
    "building_sqft",
    "year_built",
    "lot_size",
    "zoning",
    "unit_count",
    # Broker_Current metrics
    "current_noi",
    "current_cap_rate",
    "current_grm",
    "current_gross_potential_income",
    "current_effective_gross_income",
    "current_vacancy_rate",
    "current_gross_expenses",
    # Broker_Pro_Forma metrics
    "proforma_noi",
    "proforma_cap_rate",
    "proforma_grm",
    "proforma_gross_potential_income",
    "proforma_effective_gross_income",
    "proforma_vacancy_rate",
    "proforma_gross_expenses",
    # Income line items (scalar)
    "apartment_income_current",
    "apartment_income_proforma",
    # Financing fields
    "down_payment_pct",
    "loan_amount",
    "interest_rate",
    "amortization_years",
    "debt_service_annual",
    "current_dscr",
    "proforma_dscr",
    "current_cash_on_cash",
    "proforma_cash_on_cash",
    # Broker / listing fields
    "listing_broker_name",
    "listing_broker_company",
    "listing_broker_phone",
    "listing_broker_email",
]

# Required unit_mix sub-fields (Req 3.6)
_UNIT_MIX_REQUIRED_SUBFIELDS: list[str] = [
    "unit_type_label",
    "unit_count",
    "sqft",
    "current_avg_rent",
    "proforma_rent",
]


def _build_prompt(raw_text: str, tables: list) -> str:
    """Build the structured extraction prompt sent to Gemini."""

    # Summarise tables so the prompt doesn't balloon in size
    table_summary_lines: list[str] = []
    for i, table in enumerate(tables or []):
        if not isinstance(table, list):
            continue
        row_count = len(table)
        col_count = len(table[0]) if row_count > 0 and isinstance(table[0], list) else 0
        # Include up to the first 5 rows verbatim for context
        preview_rows = table[:5]
        table_summary_lines.append(
            f"Table {i + 1} ({row_count} rows × {col_count} cols):\n"
            + "\n".join(
                "  " + " | ".join(str(cell) for cell in row)
                for row in preview_rows
                if isinstance(row, list)
            )
        )
    table_section = (
        "\n\n".join(table_summary_lines)
        if table_summary_lines
        else "(no structured tables extracted)"
    )

    scalar_field_list = "\n".join(f"  - {f}" for f in _SCALAR_FIELDS)

    prompt = f"""You are a commercial real estate data extraction assistant.

Extract all financial and property data from the Offering Memorandum (OM) text below and return a single JSON object.

## Output format

Every field must be returned as:
  {{"value": <extracted_value_or_null>, "confidence": <float_0.0_to_1.0>}}

Where:
- "value" is the extracted value (number, string, or null if not found)
- "confidence" is 1.0 if found verbatim, lower if inferred or ambiguous, 0.0 if absent

## Required scalar fields (return each as {{"value": ..., "confidence": ...}}):
{scalar_field_list}

## Required array fields:

### unit_mix (REQUIRED — must be a non-empty array if the OM contains unit information)
Each item must contain these sub-fields, each as {{"value": ..., "confidence": ...}}:
  - unit_type_label  (e.g. "1BR/1BA", "2BR/2BA", "Studio")
  - unit_count       (integer number of units of this type)
  - sqft             (average square footage per unit)
  - current_avg_rent (current average monthly rent, or null)
  - proforma_rent    (broker pro forma monthly rent, or null)

### other_income_items (array, may be empty)
Each item: {{"label": {{"value": ..., "confidence": ...}}, "annual_amount": {{"value": ..., "confidence": ...}}}}

### expense_items (array, may be empty)
Each item:
  {{
    "label": {{"value": ..., "confidence": ...}},
    "current_annual_amount": {{"value": ..., "confidence": ...}},
    "proforma_annual_amount": {{"value": ..., "confidence": ...}}
  }}

## Important rules
- Return ONLY valid JSON — no markdown fences, no commentary.
- If a field is not present in the OM, set its value to null and confidence to 0.0.
- Monetary values should be plain numbers (no $ signs or commas).
- Rates (cap_rate, vacancy_rate, interest_rate) should be decimals (e.g. 0.065 for 6.5%).
- asking_price is REQUIRED — extract it even if labelled "List Price", "Sale Price", etc.

## OM Text
{raw_text}

## Extracted Tables
{table_section}
"""
    return prompt


def _clamp_confidence(value: Any) -> float:
    """Return a float confidence clamped to [0.0, 1.0]."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


def _normalise_field(raw: Any) -> dict[str, Any]:
    """Ensure a field is a dict with 'value' and 'confidence' keys.

    If the raw value is already a well-formed dict, clamp the confidence.
    Otherwise wrap it as {"value": null, "confidence": 0.0}.
    """
    if isinstance(raw, dict) and "value" in raw and "confidence" in raw:
        return {
            "value": raw["value"],
            "confidence": _clamp_confidence(raw["confidence"]),
        }
    # Absent or malformed → default
    return {"value": None, "confidence": 0.0}


def _parse_response(response_json: dict) -> dict[str, Any]:
    """Extract the text content from a Gemini generateContent response dict."""
    try:
        candidates = response_json.get("candidates", [])
        if not candidates:
            raise GeminiParseError(
                "Gemini response contained no candidates",
                payload={"raw_response": str(response_json)[:500]},
            )
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            raise GeminiParseError(
                "Gemini response candidate had no content parts",
                payload={"raw_response": str(response_json)[:500]},
            )
        text = parts[0].get("text", "")
        return text
    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiParseError(
            f"Unexpected Gemini response structure: {exc}",
            payload={"raw_response": str(response_json)[:500]},
        ) from exc


def _build_extracted_om_data(parsed: dict[str, Any]) -> ExtractedOMData:
    """Map a parsed Gemini JSON dict to an ``ExtractedOMData`` instance.

    - All scalar fields are normalised via ``_normalise_field``.
    - Absent scalar fields default to ``{"value": null, "confidence": 0.0}``.
    - ``unit_mix``, ``other_income_items``, and ``expense_items`` are handled
      separately.
    """
    kwargs: dict[str, Any] = {}

    # --- Scalar fields ---
    for field_name in _SCALAR_FIELDS:
        raw = parsed.get(field_name)
        kwargs[field_name] = _normalise_field(raw)

    # --- unit_mix ---
    raw_unit_mix = parsed.get("unit_mix")
    if not isinstance(raw_unit_mix, list):
        raw_unit_mix = []

    normalised_unit_mix: list[dict[str, Any]] = []
    for row in raw_unit_mix:
        if not isinstance(row, dict):
            continue
        normalised_row: dict[str, Any] = {}
        for subfield in _UNIT_MIX_REQUIRED_SUBFIELDS:
            normalised_row[subfield] = _normalise_field(row.get(subfield))
        # Preserve any extra sub-fields (e.g. market_rent_estimate) if present
        for key, val in row.items():
            if key not in normalised_row:
                normalised_row[key] = _normalise_field(val)
        normalised_unit_mix.append(normalised_row)
    kwargs["unit_mix"] = normalised_unit_mix

    # --- other_income_items ---
    raw_other = parsed.get("other_income_items")
    if not isinstance(raw_other, list):
        raw_other = []
    normalised_other: list[dict[str, Any]] = []
    for item in raw_other:
        if not isinstance(item, dict):
            continue
        normalised_other.append(
            {
                "label": _normalise_field(item.get("label")),
                "annual_amount": _normalise_field(item.get("annual_amount")),
            }
        )
    kwargs["other_income_items"] = normalised_other

    # --- expense_items ---
    raw_expenses = parsed.get("expense_items")
    if not isinstance(raw_expenses, list):
        raw_expenses = []
    normalised_expenses: list[dict[str, Any]] = []
    for item in raw_expenses:
        if not isinstance(item, dict):
            continue
        normalised_expenses.append(
            {
                "label": _normalise_field(item.get("label")),
                "current_annual_amount": _normalise_field(
                    item.get("current_annual_amount")
                ),
                "proforma_annual_amount": _normalise_field(
                    item.get("proforma_annual_amount")
                ),
            }
        )
    kwargs["expense_items"] = normalised_expenses

    return ExtractedOMData(**kwargs)


def _validate_extracted_data(data: ExtractedOMData) -> None:
    """Validate required fields in the extracted data.

    Raises ``GeminiResponseError`` if:
    - ``unit_mix`` is absent, not a list, or any item is missing required sub-fields.
    - ``asking_price`` is absent from the response.

    Requirements: 3.6
    """
    # Validate unit_mix
    if not isinstance(data.unit_mix, list):
        raise GeminiResponseError(
            "Gemini response missing required field: unit_mix must be an array",
            payload={"missing_field": "unit_mix"},
        )

    for i, row in enumerate(data.unit_mix):
        if not isinstance(row, dict):
            raise GeminiResponseError(
                f"unit_mix[{i}] is not a dict",
                payload={"unit_mix_index": i},
            )
        for subfield in _UNIT_MIX_REQUIRED_SUBFIELDS:
            if subfield not in row:
                raise GeminiResponseError(
                    f"unit_mix[{i}] missing required sub-field: {subfield}",
                    payload={"unit_mix_index": i, "missing_subfield": subfield},
                )

    # Validate asking_price is present (value may be null, but the key must exist)
    # Per Req 3.6: "asking_price field is absent" → FAILED
    # The field is always present after _build_extracted_om_data, but we check
    # that it was actually in the Gemini response (i.e. not just defaulted).
    # We treat a confidence of 0.0 AND value of None as "absent from response".
    # However, the spec says "absent" — we check the raw parsed dict upstream.
    # Since _build_extracted_om_data always populates asking_price (defaulting
    # absent fields), we rely on the raw parsed dict check done before calling
    # this function.  The caller passes the raw dict for this check.


class GeminiOMExtractorService:
    """Calls the Gemini API to extract structured OM data from PDF text.

    Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.8, 3.9, 3.10
    """

    def __init__(self) -> None:
        api_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
        if not api_key:
            raise GeminiConfigurationError(
                "GOOGLE_AI_API_KEY is not set or is empty. "
                "Configure this environment variable to enable AI field extraction.",
                payload={"missing_env_var": "GOOGLE_AI_API_KEY"},
            )
        self._api_key = api_key

    def extract(self, raw_text: str, tables: list) -> ExtractedOMData:
        """Extract structured OM data from PDF text using the Gemini API.

        Parameters
        ----------
        raw_text:
            Full UTF-8 text extracted from the OM PDF.
        tables:
            List of tables extracted from the PDF; each table is a list of
            rows; each row is a list of cell strings.

        Returns
        -------
        ExtractedOMData
            Structured extraction result with per-field confidence scores.

        Raises
        ------
        GeminiAPIError
            On network errors, timeouts, or non-2xx HTTP responses.
        GeminiParseError
            When the Gemini response body is not valid JSON or has an
            unexpected structure.
        GeminiResponseError
            When the JSON response is valid but missing required fields
            (``unit_mix`` or ``asking_price``).
        """
        # Req 3.10 — do not call Gemini if raw_text is empty/None
        if not raw_text or not raw_text.strip():
            raise GeminiAPIError(
                "No text available for extraction: raw_text is empty or null. "
                "Cannot call Gemini API without input text.",
                payload={"reason": "empty_raw_text"},
            )

        prompt = _build_prompt(raw_text, tables)

        request_body = {
            "contents": [
                {
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        # --- Call Gemini API (Req 3.8 — 60-second timeout) ---
        try:
            response = requests.post(
                _GEMINI_API_URL,
                params={"key": self._api_key},
                json=request_body,
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.exceptions.Timeout as exc:
            raise GeminiAPIError(
                "Gemini API request timed out (connect: 10s, read: 60s).",
                payload={"timeout": _TIMEOUT_SECONDS},
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise GeminiAPIError(
                f"Network error communicating with Gemini API: {exc}",
                payload={"error": str(exc)},
            ) from exc

        # Req 3.5 — non-2xx HTTP response
        if not response.ok:
            raise GeminiAPIError(
                f"Gemini API returned HTTP {response.status_code}: {response.text[:500]}",
                payload={
                    "status_code": response.status_code,
                    "response_body": response.text[:500],
                },
            )

        # --- Parse JSON response (Req 3.5) ---
        try:
            response_json = response.json()
        except ValueError as exc:
            raise GeminiParseError(
                "Gemini API response is not valid JSON.",
                payload={"raw_response": response.text[:500]},
            ) from exc

        # Extract the text content from the Gemini response envelope
        text_content = _parse_response(response_json)

        # The text_content itself should be a JSON string (we requested
        # responseMimeType: application/json).  Parse it.
        try:
            parsed: dict[str, Any] = json.loads(text_content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise GeminiParseError(
                f"Gemini response content is not valid JSON: {exc}",
                payload={"raw_content": str(text_content)[:500]},
            ) from exc

        if not isinstance(parsed, dict):
            raise GeminiParseError(
                "Gemini response JSON is not an object (expected a dict).",
                payload={"type": type(parsed).__name__},
            )

        # Req 3.6 — validate asking_price is present in the raw parsed dict
        if "asking_price" not in parsed:
            raise GeminiResponseError(
                "Gemini response missing required field: asking_price",
                payload={"missing_field": "asking_price"},
            )

        # Req 3.6 — validate unit_mix is present and is a list
        if "unit_mix" not in parsed or not isinstance(parsed.get("unit_mix"), list):
            raise GeminiResponseError(
                "Gemini response missing required field: unit_mix must be an array",
                payload={"missing_field": "unit_mix"},
            )

        # Validate unit_mix items have required sub-fields
        for i, row in enumerate(parsed["unit_mix"]):
            if not isinstance(row, dict):
                raise GeminiResponseError(
                    f"unit_mix[{i}] is not an object",
                    payload={"unit_mix_index": i},
                )
            for subfield in _UNIT_MIX_REQUIRED_SUBFIELDS:
                if subfield not in row:
                    raise GeminiResponseError(
                        f"unit_mix[{i}] missing required sub-field: {subfield}",
                        payload={"unit_mix_index": i, "missing_subfield": subfield},
                    )

        # Build and return the ExtractedOMData
        extracted = _build_extracted_om_data(parsed)

        logger.info(
            "GeminiOMExtractorService: extraction complete, "
            "%d unit_mix rows, asking_price confidence=%.2f",
            len(extracted.unit_mix),
            extracted.asking_price.get("confidence", 0.0),
        )

        return extracted
