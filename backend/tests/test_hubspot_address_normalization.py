"""Property-based tests for HubSpotMatcherService.normalize_address.

Properties verified:
  1. Address normalization is idempotent
  2. Address normalization is deterministic

Both properties are pure-function tests — no database or Flask app context required.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.hubspot_matcher_service import HubSpotMatcherService


# ---------------------------------------------------------------------------
# Property 1: Address Normalization is Idempotent
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 1: Address normalization is idempotent


@given(st.text(min_size=0, max_size=200))
@settings(max_examples=100)
def test_address_normalization_idempotent(s):
    """Applying normalize_address twice must produce the same result as applying it once.

    **Validates: Requirements 10.5**
    """
    result_once = HubSpotMatcherService.normalize_address(s)
    result_twice = HubSpotMatcherService.normalize_address(result_once)
    assert result_once == result_twice


# ---------------------------------------------------------------------------
# Property 2: Address Normalization is Deterministic
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 2: Address normalization is deterministic


@given(st.text(min_size=0, max_size=200))
@settings(max_examples=100)
def test_address_normalization_deterministic(s):
    """Calling normalize_address on the same input multiple times must always return
    the same result.

    **Validates: Requirements 10.5**
    """
    result_1 = HubSpotMatcherService.normalize_address(s)
    result_2 = HubSpotMatcherService.normalize_address(s)
    result_3 = HubSpotMatcherService.normalize_address(s)
    assert result_1 == result_2 == result_3
