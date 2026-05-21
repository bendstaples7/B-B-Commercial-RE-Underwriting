"""Property-based tests for _map_comparable_to_model field mapping logic.

Feature: gemini-comparable-search
Tests Properties 7, 8, and 9 from the design document.
"""
import os
import sys
from datetime import date, datetime

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup — ensure celery_worker is importable without a running broker
# ---------------------------------------------------------------------------
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('FLASK_ENV', 'testing')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')
os.environ.setdefault('GOOGLE_AI_API_KEY', 'test-key-for-unit-tests')


# ---------------------------------------------------------------------------
# Import the helper under test (after env vars are set)
# ---------------------------------------------------------------------------
from celery_worker import _map_comparable_to_model  # noqa: E402
from app.models.property_facts import (  # noqa: E402
    PropertyType,
    ConstructionType,
    InteriorCondition,
)


# ---------------------------------------------------------------------------
# Helper: ISO date validator (mirrors the design doc's _is_iso_date)
# ---------------------------------------------------------------------------

def _is_iso_date(s: str) -> bool:
    """Return True iff *s* is a valid ISO-8601 date string (YYYY-MM-DD)."""
    try:
        datetime.strptime(s, '%Y-%m-%d')
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Valid enum value sets (used to build generators and exclusion filters)
# ---------------------------------------------------------------------------

_VALID_PROPERTY_TYPE_VALUES = {e.value for e in PropertyType} | {e.name for e in PropertyType}
_VALID_CONSTRUCTION_TYPE_VALUES = {e.value for e in ConstructionType} | {e.name for e in ConstructionType}
_VALID_INTERIOR_CONDITION_VALUES = {e.value for e in InteriorCondition} | {e.name for e in InteriorCondition}

# All valid enum strings across all three enum types (used for Property 8 filter)
# Include both .value and .name (case-insensitive) since _resolve_enum accepts both
_ALL_VALID_ENUM_VALUES_LOWER = {
    s.lower()
    for s in (
        _VALID_PROPERTY_TYPE_VALUES
        | _VALID_CONSTRUCTION_TYPE_VALUES
        | _VALID_INTERIOR_CONDITION_VALUES
    )
}

# Strategies for valid enum value strings (by .value, which is what Gemini returns)
_property_type_values_st = st.sampled_from([e.value for e in PropertyType])
_construction_type_values_st = st.sampled_from([e.value for e in ConstructionType])
_interior_condition_values_st = st.sampled_from([e.value for e in InteriorCondition])

# Strategy for valid ISO date strings
_iso_date_st = st.dates(
    min_value=date(1900, 1, 1),
    max_value=date(2100, 12, 31),
).map(lambda d: d.strftime('%Y-%m-%d'))


# ---------------------------------------------------------------------------
# Property 7: Field mapping preserves all valid comparable fields
# ---------------------------------------------------------------------------

# Feature: gemini-comparable-search, Property 7: Field mapping preserves all valid comparable fields

@given(
    comp=st.fixed_dictionaries({
        'address': st.text(min_size=1, max_size=200),
        'sale_price': st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False),
        'sale_date': _iso_date_st,
        'square_footage': st.integers(min_value=0, max_value=100_000),
        'bedrooms': st.integers(min_value=0, max_value=50),
        'bathrooms': st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
        'year_built': st.integers(min_value=1800, max_value=2100),
        'lot_size': st.integers(min_value=0, max_value=10_000_000),
        'property_type': _property_type_values_st,
        'construction_type': _construction_type_values_st,
        'interior_condition': _interior_condition_values_st,
        'garage': st.booleans(),
        'basement': st.booleans(),
        'distance_miles': st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        'similarity_score': st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        'similarity_notes': st.text(max_size=500),
    })
)
@settings(max_examples=100)
def test_property_7_field_mapping_preserves_all_valid_fields(comp):
    """**Validates: Requirements 3.1**

    For any comparable dict containing valid values for all 16 required fields,
    _map_comparable_to_model SHALL produce a ComparableSale instance where every
    field matches the corresponding input value (after type coercion).
    """
    result = _map_comparable_to_model(comp, session_id=1)

    # address
    assert result.address == str(comp['address'])

    # sale_date — parsed from YYYY-MM-DD string
    expected_date = datetime.strptime(comp['sale_date'], '%Y-%m-%d').date()
    assert result.sale_date == expected_date

    # sale_price
    assert result.sale_price == float(comp['sale_price'])

    # square_footage
    assert result.square_footage == int(comp['square_footage'])

    # bedrooms
    assert result.bedrooms == int(comp['bedrooms'])

    # bathrooms
    assert result.bathrooms == float(comp['bathrooms'])

    # year_built
    assert result.year_built == int(comp['year_built'])

    # lot_size
    assert result.lot_size == int(comp['lot_size'])

    # property_type — resolved from value string
    assert result.property_type == PropertyType(comp['property_type'])

    # construction_type — resolved from value string
    assert result.construction_type == ConstructionType(comp['construction_type'])

    # interior_condition — resolved from value string
    assert result.interior_condition == InteriorCondition(comp['interior_condition'])

    # distance_miles
    assert result.distance_miles == float(comp['distance_miles'])

    # similarity_notes — stored as str when non-None
    assert result.similarity_notes == str(comp['similarity_notes'])

    # session_id
    assert result.session_id == 1


# ---------------------------------------------------------------------------
# Property 8: Enum defaults are applied for all unrecognized values
# ---------------------------------------------------------------------------

# Feature: gemini-comparable-search, Property 8: Enum defaults are applied for all unrecognized values

@given(
    bad_value=st.text().filter(lambda s: s.lower() not in _ALL_VALID_ENUM_VALUES_LOWER)
)
@settings(max_examples=100)
def test_property_8_enum_defaults_on_unrecognized_values(bad_value):
    """**Validates: Requirements 3.2, 3.3, 3.4**

    For any string that does not match a known PropertyType, ConstructionType,
    or InteriorCondition enum value, the field mapping logic SHALL default to
    PropertyType.SINGLE_FAMILY, ConstructionType.FRAME, and
    InteriorCondition.AVERAGE respectively.
    """
    comp = {
        'address': '123 Test St',
        'sale_price': 100000.0,
        'sale_date': '2023-01-15',
        'square_footage': 1200,
        'bedrooms': 3,
        'bathrooms': 2.0,
        'year_built': 1990,
        'lot_size': 5000,
        'property_type': bad_value,
        'construction_type': bad_value,
        'interior_condition': bad_value,
        'distance_miles': 0.5,
        'similarity_notes': None,
    }

    result = _map_comparable_to_model(comp, session_id=1)

    assert result.property_type == PropertyType.SINGLE_FAMILY, (
        f"Expected PropertyType.SINGLE_FAMILY for unrecognized value {bad_value!r}, "
        f"got {result.property_type!r}"
    )
    assert result.construction_type == ConstructionType.FRAME, (
        f"Expected ConstructionType.FRAME for unrecognized value {bad_value!r}, "
        f"got {result.construction_type!r}"
    )
    assert result.interior_condition == InteriorCondition.AVERAGE, (
        f"Expected InteriorCondition.AVERAGE for unrecognized value {bad_value!r}, "
        f"got {result.interior_condition!r}"
    )


# ---------------------------------------------------------------------------
# Property 9: Unparseable sale dates default to today
# ---------------------------------------------------------------------------

# Feature: gemini-comparable-search, Property 9: Unparseable sale dates default to today

@given(
    bad_date=st.text().filter(lambda s: not _is_iso_date(s))
)
@settings(max_examples=100)
def test_property_9_unparseable_sale_dates_default_to_today(bad_date):
    """**Validates: Requirements 3.5**

    For any string that cannot be parsed as a valid ISO date (including empty
    strings, arbitrary text, and malformed date strings), the field mapping
    logic SHALL use date.today() as the sale_date.
    """
    comp = {
        'address': '456 Sample Ave',
        'sale_price': 200000.0,
        'sale_date': bad_date,
        'square_footage': 1500,
        'bedrooms': 3,
        'bathrooms': 2.0,
        'year_built': 2000,
        'lot_size': 6000,
        'property_type': 'single_family',
        'construction_type': 'frame',
        'interior_condition': 'average',
        'distance_miles': 1.0,
        'similarity_notes': None,
    }

    result = _map_comparable_to_model(comp, session_id=1)

    assert result.sale_date == date.today(), (
        f"Expected date.today() ({date.today()}) for unparseable date {bad_date!r}, "
        f"got {result.sale_date!r}"
    )
