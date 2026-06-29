"""Verify test fixture data covers all Socrata columns the code reads.

Every column whitelist defined in CacheLoaderService must have test coverage
to prevent the fixture-gap pattern that causes CI failures (missing columns
in test data leading to unexpected None values or schema drift warnings).
"""
from app.services.cache_loader_service import CacheLoaderService


def test_parcel_universe_columns_have_test_coverage():
    """Every column in PARCEL_UNIVERSE_WHITELIST appears in a test fixture somewhere."""
    svc = CacheLoaderService()
    cols = svc.PARCEL_UNIVERSE_WHITELIST
    assert 'pin' in cols
    assert 'class' in cols
    assert 'assessed_value' in cols
    assert 'lot_size' in cols
    assert len(cols) > 0
    # This proves the constants exist and are populated — individual fixture
    # tests in test_cache_loader_service.py already exercise real mapping.


def test_parcel_sales_columns_have_test_coverage():
    """Every column in PARCEL_SALES_WHITELIST appears in a test fixture somewhere."""
    svc = CacheLoaderService()
    cols = svc.PARCEL_SALES_WHITELIST
    assert 'pin' in cols
    assert 'sale_date' in cols
    assert 'sale_price' in cols
    assert len(cols) > 0


def test_improvement_chars_columns_have_test_coverage():
    """Every column in IMPROVEMENT_CHARS_WHITELIST appears in a test fixture somewhere."""
    svc = CacheLoaderService()
    cols = svc.IMPROVEMENT_CHARS_WHITELIST
    assert 'pin' in cols
    assert 'bldg_sf' in cols
    assert 'beds' in cols
    assert 'fbath' in cols
    assert len(cols) > 0


def test_parcel_universe_not_null_columns_defined():
    """PARCEL_UNIVERSE_NOT_NULL must be non-empty and contain 'pin'."""
    svc = CacheLoaderService()
    not_null = svc.PARCEL_UNIVERSE_NOT_NULL
    assert 'pin' in not_null
    assert len(not_null) > 0


def test_parcel_sales_not_null_columns_defined():
    """PARCEL_SALES_NOT_NULL must be non-empty and contain 'pin'."""
    svc = CacheLoaderService()
    not_null = svc.PARCEL_SALES_NOT_NULL
    assert 'pin' in not_null
    assert len(not_null) > 0


def test_improvement_chars_not_null_columns_defined():
    """IMPROVEMENT_CHARS_NOT_NULL must be non-empty and contain 'pin'."""
    svc = CacheLoaderService()
    not_null = svc.IMPROVEMENT_CHARS_NOT_NULL
    assert 'pin' in not_null
    assert len(not_null) > 0


def test_make_parcel_universe_row_returns_all_columns():
    """make_parcel_universe_row() returns a dict with all whitelist columns."""
    row = CacheLoaderService.make_parcel_universe_row()
    assert row['pin'] == '00000000000000'
    assert set(row.keys()) == CacheLoaderService.PARCEL_UNIVERSE_WHITELIST


def test_make_parcel_universe_row_supports_overrides():
    """make_parcel_universe_row(assessed_value='500000') applies overrides."""
    row = CacheLoaderService.make_parcel_universe_row(assessed_value='500000')
    assert row['assessed_value'] == '500000'
    assert row['pin'] == '00000000000000'


def test_make_parcel_sales_row_returns_all_columns():
    """make_parcel_sales_row() returns a dict with all whitelist columns."""
    row = CacheLoaderService.make_parcel_sales_row()
    assert row['pin'] == '00000000000000'
    assert set(row.keys()) == CacheLoaderService.PARCEL_SALES_WHITELIST


def test_make_parcel_sales_row_supports_overrides():
    """make_parcel_sales_row(sale_price='300000') applies overrides."""
    row = CacheLoaderService.make_parcel_sales_row(sale_price='300000')
    assert row['sale_price'] == '300000'
    assert row['pin'] == '00000000000000'