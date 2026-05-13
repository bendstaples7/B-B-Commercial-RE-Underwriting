"""
GeminiComparableSearchService — stub for market rent research via Gemini.

TODO: Implement full Gemini-based comparable rent search.
      This stub returns None estimates so the pipeline can proceed without
      blocking on market rent research.  Replace with a real implementation
      that calls the Gemini API with property facts and returns comparable
      rent data.

Requirements: 4.1, 4.2
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from app.exceptions import GeminiAPIError, GeminiConfigurationError, GeminiParseError

logger = logging.getLogger(__name__)

_GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)
_TIMEOUT_SECONDS = 60


class GeminiComparableSearchService:
    """Searches for comparable market rents using the Gemini API.

    Given property location and unit type details, returns a market rent
    estimate with low/high range.

    Requirements: 4.1, 4.2
    """

    def __init__(self) -> None:
        api_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
        if not api_key:
            raise GeminiConfigurationError(
                "GOOGLE_AI_API_KEY is not set or is empty. "
                "Configure this environment variable to enable market rent research.",
                payload={"missing_env_var": "GOOGLE_AI_API_KEY"},
            )
        self._api_key = api_key

    def search_comparable_rents(
        self,
        property_city: str | None,
        property_state: str | None,
        neighborhood: str | None,
        unit_type_label: str,
        sqft: float | None,
    ) -> dict[str, Any]:
        """Search for comparable market rents for a given unit type.

        Parameters
        ----------
        property_city:
            City where the property is located.
        property_state:
            State where the property is located.
        neighborhood:
            Neighborhood or submarket name (optional).
        unit_type_label:
            Unit type label, e.g. "2BR/1BA", "Studio".
        sqft:
            Average square footage of the unit type (optional).

        Returns
        -------
        dict with keys:
            - ``market_rent_estimate``: Point estimate (float or None)
            - ``market_rent_low``: Low end of range (float or None)
            - ``market_rent_high``: High end of range (float or None)

        Raises
        ------
        GeminiAPIError
            On network errors, timeouts, or non-2xx HTTP responses.
        GeminiParseError
            When the Gemini response cannot be parsed.
        """
        location_parts = [p for p in [neighborhood, property_city, property_state] if p]
        location_str = ", ".join(location_parts) if location_parts else "unknown location"
        sqft_str = f"{sqft:.0f} sq ft" if sqft else "unknown size"

        prompt = f"""You are a commercial real estate market analyst.

Provide a market rent estimate for the following unit type:
- Location: {location_str}
- Unit type: {unit_type_label}
- Size: {sqft_str}

Return ONLY a JSON object with these fields (no markdown, no commentary):
{{
  "market_rent_estimate": <monthly rent as a number, or null if unknown>,
  "market_rent_low": <low end of range as a number, or null if unknown>,
  "market_rent_high": <high end of range as a number, or null if unknown>
}}

Base your estimate on current market conditions for comparable multifamily units in the area.
If you cannot provide a reliable estimate, return null for all fields.
"""

        request_body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        try:
            response = requests.post(
                _GEMINI_API_URL,
                params={"key": self._api_key},
                json=request_body,
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.exceptions.Timeout as exc:
            raise GeminiAPIError(
                f"Gemini API request timed out after {_TIMEOUT_SECONDS} seconds "
                f"during market rent research for unit type '{unit_type_label}'.",
                payload={"timeout_seconds": _TIMEOUT_SECONDS, "unit_type": unit_type_label},
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise GeminiAPIError(
                f"Network error communicating with Gemini API: {exc}",
                payload={"error": str(exc), "unit_type": unit_type_label},
            ) from exc

        if not response.ok:
            raise GeminiAPIError(
                f"Gemini API returned HTTP {response.status_code} during market rent research.",
                payload={
                    "status_code": response.status_code,
                    "response_body": response.text[:500],
                    "unit_type": unit_type_label,
                },
            )

        try:
            response_json = response.json()
        except ValueError as exc:
            raise GeminiParseError(
                "Gemini API response is not valid JSON during market rent research.",
                payload={"raw_response": response.text[:500]},
            ) from exc

        # Extract text content from Gemini response envelope
        try:
            candidates = response_json.get("candidates", [])
            text_content = candidates[0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiParseError(
                f"Unexpected Gemini response structure during market rent research: {exc}",
                payload={"raw_response": str(response_json)[:500]},
            ) from exc

        import json

        try:
            parsed = json.loads(text_content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise GeminiParseError(
                f"Gemini market rent response content is not valid JSON: {exc}",
                payload={"raw_content": str(text_content)[:500]},
            ) from exc

        if not isinstance(parsed, dict):
            raise GeminiParseError(
                "Gemini market rent response JSON is not an object.",
                payload={"type": type(parsed).__name__},
            )

        logger.info(
            "GeminiComparableSearchService: market rent research complete for "
            "unit_type='%s', estimate=%s",
            unit_type_label,
            parsed.get("market_rent_estimate"),
        )

        return {
            "market_rent_estimate": parsed.get("market_rent_estimate"),
            "market_rent_low": parsed.get("market_rent_low"),
            "market_rent_high": parsed.get("market_rent_high"),
        }
