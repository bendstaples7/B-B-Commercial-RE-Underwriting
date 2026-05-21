"""Tests for GeminiComparableSearchService.

Covers:
  - Property 1: Search result always has required keys (Tasks 2.4)
  - Property 2: Prompt template selection is correct for all property types (Task 2.5)
  - Property 3: Invalid JSON always raises a parse error (Task 2.6)
  - Property 4: Missing required keys always raise a response error (Task 2.7)
  - Example unit tests for GeminiComparableSearchService (Task 2.8)
"""
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.exceptions import (
    GeminiConfigurationError,
    GeminiParseError,
    GeminiResponseError,
)
from app.models.property_facts import PropertyType
from app.services.gemini_comparable_search_service import (
    COMMERCIAL_PROMPT_TEMPLATE,
    RESIDENTIAL_PROMPT_TEMPLATE,
    GeminiComparableSearchService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_valid_json(s: str) -> bool:
    """Return True if *s* is parseable as JSON, False otherwise."""
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def _make_service(api_key: str = "test-api-key") -> GeminiComparableSearchService:
    """Instantiate the service with a dummy API key set in the environment."""
    with patch.dict(os.environ, {"GOOGLE_AI_API_KEY": api_key}):
        return GeminiComparableSearchService()


def _well_formed_raw_response(comparables: list | None = None) -> str:
    """Return a well-formed JSON string that _parse_response accepts."""
    return json.dumps({
        "comparables": comparables if comparables is not None else [],
        "narrative": "Test narrative.",
    })


def _gemini_api_response_body(raw_text: str) -> dict:
    """Wrap *raw_text* in the Gemini API response envelope."""
    return {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": raw_text}]
                }
            }
        ]
    }


# ---------------------------------------------------------------------------
# Property 1: Search result always has required keys
# Feature: gemini-comparable-search, Property 1: Search result always has required keys
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    property_facts=st.dictionaries(st.text(), st.text()),
    property_type=st.sampled_from(PropertyType),
)
def test_property1_search_result_always_has_required_keys(property_facts, property_type):
    """**Validates: Requirements 1.1, 1.4**

    For any property_facts dict and any PropertyType, when the Gemini API
    returns a well-formed response, search() must return a dict containing
    "comparables" (list) and "narrative" (str).
    """
    # Feature: gemini-comparable-search, Property 1: Search result always has required keys
    raw = _well_formed_raw_response()
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = _gemini_api_response_body(raw)

    with patch.dict(os.environ, {"GOOGLE_AI_API_KEY": "test-key"}):
        service = GeminiComparableSearchService()

    with patch("app.services.gemini_comparable_search_service.requests.post",
               return_value=mock_response):
        result = service.search(property_facts, property_type)

    assert "comparables" in result, "Result must contain 'comparables' key"
    assert "narrative" in result, "Result must contain 'narrative' key"
    assert isinstance(result["comparables"], list), "'comparables' must be a list"
    assert isinstance(result["narrative"], str), "'narrative' must be a str"


# ---------------------------------------------------------------------------
# Property 2: Prompt template selection is correct for all property types
# Feature: gemini-comparable-search, Property 2: Prompt template selection is correct for all property types
# ---------------------------------------------------------------------------

# Unique markers that appear in one template but not the other.
_RESIDENTIAL_MARKER = "Section A: Location Analysis"
_COMMERCIAL_MARKER = "commercial real estate appraisal assistant"


@settings(max_examples=100)
@given(property_type=st.sampled_from(PropertyType))
def test_property2_prompt_template_selection(property_type):
    """**Validates: Requirements 1.2, 1.3**

    Residential-prompt markers appear iff property_type is SINGLE_FAMILY or
    MULTI_FAMILY; commercial-prompt markers appear iff property_type is
    COMMERCIAL.
    """
    # Feature: gemini-comparable-search, Property 2: Prompt template selection is correct for all property types
    with patch.dict(os.environ, {"GOOGLE_AI_API_KEY": "test-key"}):
        service = GeminiComparableSearchService()

    prompt = service._build_prompt({}, property_type)

    is_residential = property_type in (PropertyType.SINGLE_FAMILY, PropertyType.MULTI_FAMILY)
    is_commercial = property_type == PropertyType.COMMERCIAL

    if is_residential:
        assert _RESIDENTIAL_MARKER in prompt, (
            f"Residential marker missing for {property_type}"
        )
        assert _COMMERCIAL_MARKER not in prompt, (
            f"Commercial marker should not appear for {property_type}"
        )
    elif is_commercial:
        assert _COMMERCIAL_MARKER in prompt, (
            f"Commercial marker missing for {property_type}"
        )
        assert _RESIDENTIAL_MARKER not in prompt, (
            f"Residential marker should not appear for {property_type}"
        )


# ---------------------------------------------------------------------------
# Property 3: Invalid JSON always raises a parse error
# Feature: gemini-comparable-search, Property 3: Invalid JSON always raises a parse error
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(raw=st.text().filter(lambda s: not _is_valid_json(s)))
def test_property3_invalid_json_raises_parse_error(raw):
    """**Validates: Requirements 1.5**

    _parse_response must raise GeminiParseError for any string that is not
    valid JSON.
    """
    # Feature: gemini-comparable-search, Property 3: Invalid JSON always raises a parse error
    with patch.dict(os.environ, {"GOOGLE_AI_API_KEY": "test-key"}):
        service = GeminiComparableSearchService()

    with pytest.raises(GeminiParseError):
        service._parse_response(raw)


# ---------------------------------------------------------------------------
# Property 4: Missing required keys always raise a response error
# Feature: gemini-comparable-search, Property 4: Missing required keys always raise a response error
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(missing_key=st.sampled_from(["comparables", "narrative", "both"]))
def test_property4_missing_required_keys_raises_response_error(missing_key):
    """**Validates: Requirements 1.6**

    _parse_response must raise GeminiResponseError when "comparables",
    "narrative", or both keys are absent from the parsed JSON object.
    The exception payload must identify the missing field(s).
    """
    # Feature: gemini-comparable-search, Property 4: Missing required keys always raise a response error
    with patch.dict(os.environ, {"GOOGLE_AI_API_KEY": "test-key"}):
        service = GeminiComparableSearchService()

    if missing_key == "comparables":
        raw = json.dumps({"narrative": "some text"})
        expected_missing = ["comparables"]
    elif missing_key == "narrative":
        raw = json.dumps({"comparables": []})
        expected_missing = ["narrative"]
    else:  # "both"
        raw = json.dumps({"other_key": "value"})
        expected_missing = ["comparables", "narrative"]

    with pytest.raises(GeminiResponseError) as exc_info:
        service._parse_response(raw)

    # The exception must identify the missing field(s)
    error = exc_info.value
    for key in expected_missing:
        assert key in error.payload.get("missing_keys", []), (
            f"Expected '{key}' in missing_keys payload, got: {error.payload}"
        )


# ---------------------------------------------------------------------------
# Task 2.8 — Example unit tests for GeminiComparableSearchService
# ---------------------------------------------------------------------------

class TestGeminiComparableSearchServiceInit:
    """Unit tests for __init__ configuration validation."""

    def test_raises_configuration_error_when_api_key_unset(self):
        """GeminiConfigurationError is raised when GOOGLE_AI_API_KEY is not in env."""
        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_AI_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(GeminiConfigurationError):
                GeminiComparableSearchService()

    def test_raises_configuration_error_when_api_key_empty(self):
        """GeminiConfigurationError is raised when GOOGLE_AI_API_KEY is an empty string."""
        with patch.dict(os.environ, {"GOOGLE_AI_API_KEY": ""}):
            with pytest.raises(GeminiConfigurationError):
                GeminiComparableSearchService()

    def test_instantiates_successfully_with_valid_api_key(self):
        """Service instantiates without error when GOOGLE_AI_API_KEY is set."""
        with patch.dict(os.environ, {"GOOGLE_AI_API_KEY": "valid-key-abc123"}):
            service = GeminiComparableSearchService()
        assert service is not None


class TestGeminiComparableSearchServiceSearch:
    """Unit tests for the search() method."""

    def _make_mock_response(self, raw_text: str) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = _gemini_api_response_body(raw_text)
        return mock_resp

    def test_search_uses_residential_prompt_for_single_family(self):
        """search() builds a residential prompt when property_type is SINGLE_FAMILY."""
        service = _make_service()
        raw = _well_formed_raw_response()

        with patch("app.services.gemini_comparable_search_service.requests.post",
                   return_value=self._make_mock_response(raw)) as mock_post:
            service.search({"address": "123 Main St"}, PropertyType.SINGLE_FAMILY)

        call_kwargs = mock_post.call_args
        posted_payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        prompt_text = posted_payload["contents"][0]["parts"][0]["text"]
        assert _RESIDENTIAL_MARKER in prompt_text
        assert _COMMERCIAL_MARKER not in prompt_text

    def test_search_uses_residential_prompt_for_multi_family(self):
        """search() builds a residential prompt when property_type is MULTI_FAMILY."""
        service = _make_service()
        raw = _well_formed_raw_response()

        with patch("app.services.gemini_comparable_search_service.requests.post",
                   return_value=self._make_mock_response(raw)) as mock_post:
            service.search({"address": "456 Oak Ave"}, PropertyType.MULTI_FAMILY)

        call_kwargs = mock_post.call_args
        posted_payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        prompt_text = posted_payload["contents"][0]["parts"][0]["text"]
        assert _RESIDENTIAL_MARKER in prompt_text

    def test_search_uses_commercial_prompt_for_commercial(self):
        """search() builds a commercial prompt when property_type is COMMERCIAL."""
        service = _make_service()
        raw = _well_formed_raw_response()

        with patch("app.services.gemini_comparable_search_service.requests.post",
                   return_value=self._make_mock_response(raw)) as mock_post:
            service.search({"address": "789 Commerce Blvd"}, PropertyType.COMMERCIAL)

        call_kwargs = mock_post.call_args
        posted_payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        prompt_text = posted_payload["contents"][0]["parts"][0]["text"]
        assert _COMMERCIAL_MARKER in prompt_text
        assert _RESIDENTIAL_MARKER not in prompt_text

    def test_search_returns_correct_dict_shape_on_valid_response(self):
        """search() returns a dict with 'comparables' (list) and 'narrative' (str)."""
        service = _make_service()
        comparables = [
            {
                "address": "100 Elm St",
                "sale_date": "2024-01-15",
                "sale_price": 350000,
                "property_type": "single_family",
                "units": 1,
                "bedrooms": 3,
                "bathrooms": 2.0,
                "square_footage": 1500,
                "lot_size": 6000,
                "year_built": 1985,
                "construction_type": "frame",
                "interior_condition": "average",
                "distance_miles": 0.5,
                "latitude": 41.88,
                "longitude": -87.63,
                "similarity_notes": "Similar size and age.",
            }
        ]
        narrative = "Section A: Good location.\nSection B: Average condition."
        raw = json.dumps({"comparables": comparables, "narrative": narrative})

        with patch("app.services.gemini_comparable_search_service.requests.post",
                   return_value=self._make_mock_response(raw)):
            result = service.search({"address": "123 Main St"}, PropertyType.SINGLE_FAMILY)

        assert isinstance(result, dict)
        assert "comparables" in result
        assert "narrative" in result
        assert isinstance(result["comparables"], list)
        assert len(result["comparables"]) == 1
        assert result["comparables"][0]["address"] == "100 Elm St"
        assert isinstance(result["narrative"], str)
        assert result["narrative"] == narrative

    def test_search_returns_empty_comparables_list(self):
        """search() handles a valid response with zero comparables."""
        service = _make_service()
        raw = json.dumps({"comparables": [], "narrative": "No comparables found."})

        with patch("app.services.gemini_comparable_search_service.requests.post",
                   return_value=self._make_mock_response(raw)):
            result = service.search({}, PropertyType.SINGLE_FAMILY)

        assert result["comparables"] == []
        assert result["narrative"] == "No comparables found."

    def test_search_embeds_property_facts_in_prompt(self):
        """search() serialises property_facts as JSON inside the prompt."""
        service = _make_service()
        facts = {"address": "42 Wallaby Way", "year_built": 1990}
        raw = _well_formed_raw_response()

        with patch("app.services.gemini_comparable_search_service.requests.post",
                   return_value=self._make_mock_response(raw)) as mock_post:
            service.search(facts, PropertyType.SINGLE_FAMILY)

        call_kwargs = mock_post.call_args
        posted_payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        prompt_text = posted_payload["contents"][0]["parts"][0]["text"]
        assert "42 Wallaby Way" in prompt_text
        assert "1990" in prompt_text
