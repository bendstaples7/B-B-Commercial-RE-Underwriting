"""Gemini AI-powered comparable sales search service."""
import json
import os

import requests

from app.exceptions import (
    GeminiAPIError,
    GeminiConfigurationError,
    GeminiParseError,
    GeminiResponseError,
)
from app.models.property_facts import PropertyType

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

RESIDENTIAL_PROMPT_TEMPLATE = """\
You are a real estate appraisal assistant. Your task is to identify comparable \
residential property sales for the subject property described below.

IMPORTANT: You MUST respond with ONLY a single JSON object. Do NOT include any \
markdown, code fences, or explanatory text outside the JSON. The JSON object \
MUST have exactly two top-level keys: "comparables" and "narrative".

"comparables" must be a JSON array of comparable sale objects. Each object must \
contain exactly these fields:
  - "address"           (string)  — full street address of the comparable
  - "sale_date"         (string)  — sale date in YYYY-MM-DD format
  - "sale_price"        (number)  — sale price in USD
  - "property_type"     (string)  — one of: "single_family", "multi_family", "commercial"
  - "units"             (integer) — number of units
  - "bedrooms"          (integer) — number of bedrooms
  - "bathrooms"         (number)  — number of bathrooms (may be fractional)
  - "square_footage"    (integer) — gross living area in square feet
  - "lot_size"          (integer) — lot size in square feet
  - "year_built"        (integer) — year the property was built
  - "construction_type" (string)  — one of: "frame", "brick", "masonry"
  - "interior_condition"(string)  — one of: "needs_gut", "poor", "average", "new_reno", "high_end"
  - "distance_miles"    (number)  — distance from subject property in miles
  - "latitude"          (number)  — decimal latitude of the comparable
  - "longitude"         (number)  — decimal longitude of the comparable
  - "similarity_notes"  (string)  — brief explanation of why this property is comparable

"narrative" must be a single string containing a full residential appraisal \
narrative with the following sections:
  Section A: Location Analysis — neighborhood, proximity to amenities, location adjustments
  Section B: Physical Characteristics — size, age, condition, construction comparisons
  Section C: Market Conditions — current market trends, days on market, absorption rate
  Section D: Adjustments — dollar or percentage adjustments applied to each comparable
  Section E: Value Indicators — price-per-square-foot analysis, value range
  Section F: Summary — reconciliation of value indicators and final value opinion

Subject property facts:
{property_facts_json}

Respond with the JSON object only.
"""

COMMERCIAL_PROMPT_TEMPLATE = """\
You are a commercial real estate appraisal assistant. Your task is to identify \
comparable commercial property sales for the subject property described below.

IMPORTANT: You MUST respond with ONLY a single JSON object. Do NOT include any \
markdown, code fences, or explanatory text outside the JSON. The JSON object \
MUST have exactly two top-level keys: "comparables" and "narrative".

"comparables" must be a JSON array of comparable sale objects. Each object must \
contain exactly these fields:
  - "address"           (string)  — full street address of the comparable
  - "sale_date"         (string)  — sale date in YYYY-MM-DD format
  - "sale_price"        (number)  — sale price in USD
  - "property_type"     (string)  — one of: "single_family", "multi_family", "commercial"
  - "units"             (integer) — number of units (0 for non-residential)
  - "bedrooms"          (integer) — number of bedrooms (0 for non-residential)
  - "bathrooms"         (number)  — number of bathrooms (0 for non-residential)
  - "square_footage"    (integer) — gross building area in square feet
  - "lot_size"          (integer) — lot size in square feet
  - "year_built"        (integer) — year the property was built
  - "construction_type" (string)  — one of: "frame", "brick", "masonry"
  - "interior_condition"(string)  — one of: "needs_gut", "poor", "average", "new_reno", "high_end"
  - "distance_miles"    (number)  — distance from subject property in miles
  - "latitude"          (number)  — decimal latitude of the comparable
  - "longitude"         (number)  — decimal longitude of the comparable
  - "similarity_notes"  (string)  — brief explanation of why this property is comparable

"narrative" must be a single string containing a full commercial appraisal \
narrative covering: property description and use classification, market area \
analysis, highest and best use analysis, sales comparison approach (including \
unit-of-comparison analysis such as price per square foot and price per unit), \
income approach considerations where applicable, adjustments applied to each \
comparable, reconciliation of value indicators, and final value opinion with \
supporting rationale.

Subject property facts:
{property_facts_json}

Respond with the JSON object only.
"""

# Gemini API endpoint — use gemini-2.5-flash (current stable model)
_GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)


class GeminiComparableSearchService:
    """
    Calls the Gemini API with confirmed property facts and returns a structured
    dict containing comparable sales and a narrative analysis.

    Raises GeminiConfigurationError at instantiation if GOOGLE_AI_API_KEY is
    not set or is empty.
    """

    def __init__(self) -> None:
        """Read API key from environment; raise GeminiConfigurationError if missing."""
        api_key = os.environ.get("GOOGLE_AI_API_KEY", "")
        if not api_key:
            raise GeminiConfigurationError(
                "GOOGLE_AI_API_KEY is not set or is empty. "
                "Set this environment variable before instantiating GeminiComparableSearchService."
            )
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(
        self,
        property_facts: dict,
        property_type: PropertyType,
    ) -> dict:
        """
        Call Gemini and return a dict with keys "comparables" (list) and
        "narrative" (str).

        Raises:
            GeminiAPIError: if the HTTP call to Gemini fails.
            GeminiParseError: if the response body is not valid JSON.
            GeminiResponseError: if required keys are missing from the response.
        """
        prompt = self._build_prompt(property_facts, property_type)
        raw = self._call_gemini_api(prompt)
        return self._parse_response(raw)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        property_facts: dict,
        property_type: PropertyType,
    ) -> str:
        """Select and render the correct prompt template based on property_type."""
        if property_type in (PropertyType.SINGLE_FAMILY, PropertyType.MULTI_FAMILY):
            template = RESIDENTIAL_PROMPT_TEMPLATE
        else:
            # COMMERCIAL (and any future types) use the commercial template
            template = COMMERCIAL_PROMPT_TEMPLATE

        return template.format(
            property_facts_json=json.dumps(property_facts, indent=2)
        )

    def _call_gemini_api(self, prompt: str) -> str:
        """POST to the Gemini API and return the raw response text.

        Raises:
            GeminiAPIError: on any HTTP error response.
        """
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "maxOutputTokens": 16384,
            },
        }

        try:
            response = requests.post(
                _GEMINI_API_URL,
                params={"key": self._api_key},
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise GeminiAPIError(
                f"Gemini API returned HTTP {exc.response.status_code}: {exc.response.text}",
                status_code=502,
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise GeminiAPIError(
                f"Gemini API request failed: {exc}",
                status_code=502,
            ) from exc

        try:
            data = response.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError) as exc:
            raise GeminiParseError(
                f"Unexpected Gemini API response structure: {exc}. "
                f"Response body: {response.text[:500]}"
            ) from exc

        return raw_text

    def _parse_response(self, raw: str) -> dict:
        """Parse the raw JSON string from Gemini and validate required keys.

        Raises:
            GeminiParseError: if *raw* is not valid JSON.
            GeminiResponseError: if the parsed object is missing "comparables"
                or "narrative".
        """
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise GeminiParseError(
                f"Gemini response is not valid JSON: {exc}. "
                f"Raw response (first 500 chars): {raw[:500]}"
            ) from exc

        if not isinstance(data, dict):
            raise GeminiResponseError(
                f"Gemini response is not a JSON object. Got {type(data).__name__}: {raw[:200]}",
                missing_keys=["comparables", "narrative"],
            )

        missing_keys = [
            key for key in ("comparables", "narrative") if key not in data
        ]
        if missing_keys:
            raise GeminiResponseError(
                f"Gemini response is missing required key(s): {missing_keys}. "
                f"Keys present: {list(data.keys())}",
                missing_keys=missing_keys,
            )

        return {
            "comparables": data["comparables"],
            "narrative": data["narrative"],
        }
