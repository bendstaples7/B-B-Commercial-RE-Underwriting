"""Property-based tests for HubSpotClientService GET-only enforcement.

Property verified:
  17. HubSpot Client Enforces GET-Only — for any call with an HTTP method
      other than GET, the service must raise HubSpotReadOnlyViolation and
      must not execute the API call.

This is a pure-function test — no Flask app context or database needed.
The enforce_get_only() method is a pure guard that raises an exception
based solely on the method string; no I/O is involved.
"""
# Feature: hubspot-crm-migration, Property 17: HubSpot client enforces GET-only

from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.exceptions import HubSpotReadOnlyViolation
from app.services.hubspot_client_service import HubSpotClientService


# ---------------------------------------------------------------------------
# Helper: build a HubSpotClientService without a real HubSpotConfig
# ---------------------------------------------------------------------------

def _make_service() -> HubSpotClientService:
    """Return a HubSpotClientService with a mocked token (no DB or encryption needed)."""
    svc = object.__new__(HubSpotClientService)
    svc._token = "fake-token-for-testing"
    return svc


# ---------------------------------------------------------------------------
# Strategy: non-GET HTTP methods
# ---------------------------------------------------------------------------

_NON_GET_METHODS = [
    "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS",
    "post", "put", "delete",
]

_non_get_method_st = st.sampled_from(_NON_GET_METHODS)


# ---------------------------------------------------------------------------
# Property 17: HubSpot Client Enforces GET-Only
# ---------------------------------------------------------------------------


class TestProperty17HubSpotEnforcesGetOnly:
    """Property 17 — enforce_get_only raises HubSpotReadOnlyViolation for any non-GET method.

    **Validates: Requirements 19.1, 19.2, 19.3**
    """

    @given(method=_non_get_method_st)
    @settings(max_examples=100)
    def test_non_get_method_raises_readonly_violation(self, method: str) -> None:
        """Any non-GET method must raise HubSpotReadOnlyViolation.

        # Feature: hubspot-crm-migration, Property 17: HubSpot client enforces GET-only
        **Validates: Requirements 19.1, 19.2, 19.3**
        """
        svc = _make_service()
        with pytest.raises(HubSpotReadOnlyViolation):
            svc.enforce_get_only(method)

    @given(method=_non_get_method_st)
    @settings(max_examples=100)
    def test_non_get_method_does_not_execute_http_call(self, method: str) -> None:
        """When enforce_get_only raises, no HTTP call must be made.

        We patch requests.get to verify it is never called when a non-GET
        method is passed.

        # Feature: hubspot-crm-migration, Property 17: HubSpot client enforces GET-only
        **Validates: Requirements 19.1, 19.2, 19.3**
        """
        svc = _make_service()
        with patch("app.services.hubspot_client_service.requests.get") as mock_get:
            with pytest.raises(HubSpotReadOnlyViolation):
                svc.enforce_get_only(method)
            mock_get.assert_not_called()

    def test_get_uppercase_does_not_raise(self) -> None:
        """'GET' (uppercase) must NOT raise HubSpotReadOnlyViolation.

        # Feature: hubspot-crm-migration, Property 17: HubSpot client enforces GET-only
        **Validates: Requirements 19.1, 19.2, 19.3**
        """
        svc = _make_service()
        # Should not raise — returns None
        result = svc.enforce_get_only("GET")
        assert result is None

    def test_get_lowercase_does_not_raise(self) -> None:
        """'get' (lowercase) must NOT raise HubSpotReadOnlyViolation.

        The method comparison is case-insensitive (method.upper() == 'GET').

        # Feature: hubspot-crm-migration, Property 17: HubSpot client enforces GET-only
        **Validates: Requirements 19.1, 19.2, 19.3**
        """
        svc = _make_service()
        result = svc.enforce_get_only("get")
        assert result is None

    def test_get_mixed_case_does_not_raise(self) -> None:
        """'Get' (mixed case) must NOT raise HubSpotReadOnlyViolation.

        # Feature: hubspot-crm-migration, Property 17: HubSpot client enforces GET-only
        **Validates: Requirements 19.1, 19.2, 19.3**
        """
        svc = _make_service()
        result = svc.enforce_get_only("Get")
        assert result is None

    def test_violation_exception_has_correct_type(self) -> None:
        """HubSpotReadOnlyViolation must be raised (not a generic exception).

        # Feature: hubspot-crm-migration, Property 17: HubSpot client enforces GET-only
        **Validates: Requirements 19.3**
        """
        svc = _make_service()
        exc = None
        try:
            svc.enforce_get_only("POST")
        except HubSpotReadOnlyViolation as e:
            exc = e
        assert exc is not None, "Expected HubSpotReadOnlyViolation to be raised"
        assert exc.status_code == 500
        assert exc.payload.get("error_type") == "hubspot_readonly_violation"
