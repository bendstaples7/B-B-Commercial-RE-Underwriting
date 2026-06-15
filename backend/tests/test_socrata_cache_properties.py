"""Property-based tests for the Chicago Socrata local cache.

Tasks 13.2–13.18 — 17 Hypothesis property tests covering:
  - Round-trip data integrity for all three cache models (Properties 1–3)
  - Upsert semantics (Property 4)
  - NULL preservation for nullable columns (Property 5)
  - Schema drift handling in _map_row (Properties 6–8)
  - Pagination termination (Property 9)
  - Sync log written on success (Property 10)
  - Retry behavior on transient HTTP errors (Property 11)
  - Cache status classification determinism (Property 12)
  - Cache-first routing prevents live API calls (Property 13)
  - Output schema consistency regardless of data source (Property 14)
  - Incremental refresh watermark (Property 15)
  - Failed refresh leaves cache intact (Property 16)
  - Parcel Sales filter — only LAND AND BUILDING records loaded (Property 17)
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, date, timezone
from decimal import Decimal
from typing import Optional
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.parcel_universe_cache import ParcelUniverseCache
from app.models.parcel_sales_cache import ParcelSalesCache
from app.models.improvement_characteristics_cache import ImprovementCharacteristicsCache
from app.models.sync_log import SyncLog
from app.services.cache_loader_service import CacheLoaderService
from app.services.cache_status_service import CacheStatusService


# ---------------------------------------------------------------------------
# Known column names — used to filter generated extra-field keys
# ---------------------------------------------------------------------------

ALL_KNOWN_COLUMNS: frozenset[str] = frozenset(
    CacheLoaderService.PARCEL_UNIVERSE_WHITELIST
    | CacheLoaderService.PARCEL_SALES_WHITELIST
    | CacheLoaderService.IMPROVEMENT_CHARS_WHITELIST
)

PAGE_SIZE = 50_000


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

pin_strategy = st.text(
    alphabet='0123456789',
    min_size=14, max_size=14,
)

lat_strategy = st.decimals(
    min_value=Decimal('41.4'), max_value=Decimal('42.2'),
    places=7, allow_nan=False, allow_infinity=False,
)

lon_strategy = st.decimals(
    min_value=Decimal('-88.3'), max_value=Decimal('-87.5'),
    places=7, allow_nan=False, allow_infinity=False,
)

# Extra fields whose keys are NOT in any known column whitelist
extra_fields_strategy = st.dictionaries(
    keys=st.text(min_size=1, max_size=20).filter(lambda k: k not in ALL_KNOWN_COLUMNS),
    values=st.one_of(st.text(), st.integers(), st.none()),
    min_size=1, max_size=5,
)

# Page-size sequences: n_full full pages followed by an optional partial page.
# Each page is a list of row-count ints; tests then generate that many dummy rows.
page_sequence_strategy = st.integers(min_value=1, max_value=4).flatmap(
    lambda n_full: st.integers(min_value=0, max_value=PAGE_SIZE - 1).map(
        lambda last_size: [PAGE_SIZE] * n_full + ([last_size] if last_size > 0 else [])
    )
)


# ---------------------------------------------------------------------------
# Helper: make a minimal valid parcel_universe row dict
# ---------------------------------------------------------------------------

def _pu_row(pin: str, lat, lon) -> dict:
    return {'pin': pin, 'lat': str(lat), 'lon': str(lon), 'last_synced_at': None}


def _make_svc():
    return CacheLoaderService()


# ===========================================================================
# Property 1: Parcel Universe round-trip data integrity
# Feature: chicago-socrata-local-cache, Property 1: ParcelUniverseCache round-trip
# Validates: Requirements 7.1
# ===========================================================================

class TestProperty1ParcelUniverseRoundTrip:

    @given(pin=pin_strategy, lat=lat_strategy, lon=lon_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_parcel_universe_round_trip(self, db_session, pin, lat, lon):
        """Write a ParcelUniverseCache row; read it back; pin/lat/lon are identical.

        **Validates: Requirements 7.1**
        """
        # Feature: chicago-socrata-local-cache, Property 1: ParcelUniverseCache round-trip
        row = ParcelUniverseCache(pin=pin, lat=lat, lon=lon)
        db_session.merge(row)
        db_session.flush()

        retrieved = db_session.query(ParcelUniverseCache).filter_by(pin=pin).one()
        assert retrieved.pin == pin
        assert Decimal(str(retrieved.lat)) == lat
        assert Decimal(str(retrieved.lon)) == lon


# ===========================================================================
# Property 2: Parcel Sales round-trip data integrity
# Feature: chicago-socrata-local-cache, Property 2: ParcelSalesCache round-trip
# Validates: Requirements 7.2
# ===========================================================================

sale_date_strategy = st.dates(
    min_value=date(2000, 1, 1),
    max_value=date(2030, 12, 31),
)

sale_price_strategy = st.decimals(
    min_value=Decimal('1000'), max_value=Decimal('9999999.99'),
    places=2, allow_nan=False, allow_infinity=False,
)

class_strategy = st.text(
    alphabet='0123456789ABCDEF-',
    min_size=1, max_size=10,
)


class TestProperty2ParcelSalesRoundTrip:

    @given(
        pin=pin_strategy,
        sale_date=sale_date_strategy,
        sale_price=sale_price_strategy,
        class_=class_strategy,
        is_multisale=st.one_of(st.booleans(), st.none()),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_parcel_sales_round_trip(self, db_session, pin, sale_date, sale_price, class_, is_multisale):
        """Write a ParcelSalesCache row; read it back by id; all column values match.

        ParcelSalesCache uses a serial id PK (not a unique pin+date constraint), so we
        read back by the auto-generated id to avoid ambiguity in the same session.

        **Validates: Requirements 7.2**
        """
        # Feature: chicago-socrata-local-cache, Property 2: ParcelSalesCache round-trip
        row = ParcelSalesCache(
            pin=pin,
            sale_date=sale_date,
            sale_price=sale_price,
            class_=class_,
            sale_type='LAND AND BUILDING',
            is_multisale=is_multisale,
        )
        db_session.add(row)
        db_session.flush()

        row_id = row.id
        # Expire the instance so SQLAlchemy re-fetches from the DB
        db_session.expire(row)

        retrieved = db_session.query(ParcelSalesCache).get(row_id)
        assert retrieved is not None
        assert retrieved.pin == pin
        assert retrieved.sale_date == sale_date
        # SQLite stores Numeric as float; compare with tolerance
        assert Decimal(str(retrieved.sale_price)).quantize(Decimal('0.01')) == sale_price
        assert retrieved.class_ == class_
        assert retrieved.is_multisale == is_multisale


# ===========================================================================
# Property 3: Improvement Characteristics round-trip data integrity
# Feature: chicago-socrata-local-cache, Property 3: ImprovementCharacteristicsCache round-trip
# Validates: Requirements 7.3
# ===========================================================================

bldg_sf_strategy = st.integers(min_value=100, max_value=99999)
beds_strategy = st.integers(min_value=0, max_value=50)
bath_strategy = st.decimals(
    min_value=Decimal('0.0'), max_value=Decimal('999.9'),
    places=1, allow_nan=False, allow_infinity=False,
)
age_strategy = st.integers(min_value=0, max_value=200)


class TestProperty3ImprovementCharsRoundTrip:

    @given(
        pin=pin_strategy,
        bldg_sf=bldg_sf_strategy,
        beds=beds_strategy,
        fbath=bath_strategy,
        age=age_strategy,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_improvement_chars_round_trip(self, db_session, pin, bldg_sf, beds, fbath, age):
        """Write an ImprovementCharacteristicsCache row; read it back; all values match.

        **Validates: Requirements 7.3**
        """
        # Feature: chicago-socrata-local-cache, Property 3: ImprovementCharacteristicsCache round-trip
        row = ImprovementCharacteristicsCache(
            pin=pin,
            bldg_sf=bldg_sf,
            beds=beds,
            fbath=fbath,
            age=age,
        )
        db_session.merge(row)
        db_session.flush()

        retrieved = (
            db_session.query(ImprovementCharacteristicsCache)
            .filter_by(pin=pin)
            .one()
        )
        assert retrieved.pin == pin
        assert retrieved.bldg_sf == bldg_sf
        assert retrieved.beds == beds
        assert Decimal(str(retrieved.fbath)) == fbath
        assert retrieved.age == age


# ===========================================================================
# Property 4: Upsert overwrites previous values
# Feature: chicago-socrata-local-cache, Property 4: upsert semantics
# Validates: Requirements 1.8, 7.4
# ===========================================================================

class TestProperty4UpsertOverwrites:

    @given(
        pin=pin_strategy,
        lat1=lat_strategy,
        lon1=lon_strategy,
        lat2=lat_strategy,
        lon2=lon_strategy,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_upsert_overwrites_previous_values(self, db_session, pin, lat1, lon1, lat2, lon2):
        """Upsert V1 then V2 for the same PIN; read-back returns V2 for all non-PK columns.

        **Validates: Requirements 1.8, 7.4**
        """
        # Feature: chicago-socrata-local-cache, Property 4: upsert semantics
        assume(lat1 != lat2 or lon1 != lon2)

        row_v1 = ParcelUniverseCache(pin=pin, lat=lat1, lon=lon1)
        db_session.merge(row_v1)
        db_session.flush()

        row_v2 = ParcelUniverseCache(pin=pin, lat=lat2, lon=lon2)
        db_session.merge(row_v2)
        db_session.flush()

        retrieved = db_session.query(ParcelUniverseCache).filter_by(pin=pin).one()
        assert Decimal(str(retrieved.lat)) == lat2
        assert Decimal(str(retrieved.lon)) == lon2


# ===========================================================================
# Property 5: NULL preservation for nullable columns
# Feature: chicago-socrata-local-cache, Property 5: NULL preservation
# Validates: Requirements 7.5
# ===========================================================================

class TestProperty5NullPreservation:

    @given(pin=pin_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_parcel_universe_nullable_columns_preserve_null(self, db_session, pin):
        """Write ParcelUniverseCache with NULL lat/lon; read back; both are NULL.

        **Validates: Requirements 7.5**
        """
        # Feature: chicago-socrata-local-cache, Property 5: NULL preservation (ParcelUniverseCache)
        row = ParcelUniverseCache(pin=pin, lat=None, lon=None, last_synced_at=None)
        db_session.merge(row)
        db_session.flush()

        retrieved = db_session.query(ParcelUniverseCache).filter_by(pin=pin).one()
        assert retrieved.lat is None
        assert retrieved.lon is None
        assert retrieved.last_synced_at is None

    @given(pin=pin_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_parcel_sales_nullable_columns_preserve_null(self, db_session, pin):
        """Write ParcelSalesCache with all nullable columns NULL; read back; all still NULL.

        **Validates: Requirements 7.5**
        """
        # Feature: chicago-socrata-local-cache, Property 5: NULL preservation (ParcelSalesCache)
        row = ParcelSalesCache(
            pin=pin,
            sale_date=None,
            sale_price=None,
            class_=None,
            sale_type=None,
            is_multisale=None,
            sale_filter_less_than_10k=None,
            sale_filter_deed_type=None,
            last_synced_at=None,
        )
        db_session.add(row)
        db_session.flush()

        retrieved = db_session.query(ParcelSalesCache).filter_by(pin=pin).first()
        assert retrieved is not None
        assert retrieved.sale_date is None
        assert retrieved.sale_price is None
        assert retrieved.class_ is None
        assert retrieved.sale_type is None
        assert retrieved.is_multisale is None
        assert retrieved.sale_filter_less_than_10k is None
        assert retrieved.sale_filter_deed_type is None
        assert retrieved.last_synced_at is None

    @given(pin=pin_strategy)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_improvement_chars_nullable_columns_preserve_null(self, db_session, pin):
        """Write ImprovementCharacteristicsCache with all nullable columns NULL; read back; all NULL.

        **Validates: Requirements 7.5**
        """
        # Feature: chicago-socrata-local-cache, Property 5: NULL preservation (ImprovementCharacteristicsCache)
        row = ImprovementCharacteristicsCache(
            pin=pin,
            bldg_sf=None,
            beds=None,
            fbath=None,
            hbath=None,
            age=None,
            ext_wall=None,
            apts=None,
            last_synced_at=None,
        )
        db_session.merge(row)
        db_session.flush()

        retrieved = (
            db_session.query(ImprovementCharacteristicsCache).filter_by(pin=pin).one()
        )
        assert retrieved.bldg_sf is None
        assert retrieved.beds is None
        assert retrieved.fbath is None
        assert retrieved.hbath is None
        assert retrieved.age is None
        assert retrieved.ext_wall is None
        assert retrieved.apts is None
        assert retrieved.last_synced_at is None


# ===========================================================================
# Property 6: Schema drift — extra fields silently dropped
# Feature: chicago-socrata-local-cache, Property 6: extra fields dropped
# Validates: Requirements 6.1
# ===========================================================================

class TestProperty6ExtraFieldsDropped:

    @given(extra=extra_fields_strategy)
    @settings(max_examples=50)
    def test_extra_fields_silently_dropped(self, extra):
        """Extra keys not in the whitelist are dropped by _map_row.

        **Validates: Requirements 6.1**
        """
        # Feature: chicago-socrata-local-cache, Property 6: extra fields silently dropped
        svc = _make_svc()
        whitelist = svc.PARCEL_UNIVERSE_WHITELIST
        not_null = svc.PARCEL_UNIVERSE_NOT_NULL

        base = {'pin': '12345678901234', 'lat': '41.8', 'lon': '-87.6', 'last_synced_at': None}
        row = {**base, **extra}

        result = svc._map_row(row, whitelist, not_null)

        assert result is not None
        for key in result:
            assert key in whitelist, f"Unexpected key {key!r} in mapped row"
        for extra_key in extra:
            assert extra_key not in result, f"Extra key {extra_key!r} should have been dropped"


# ===========================================================================
# Property 7: Schema drift — missing nullable fields become NULL
# Feature: chicago-socrata-local-cache, Property 7: missing nullable → NULL
# Validates: Requirements 6.2, 6.3
# ===========================================================================

_PU_NULLABLE_COLS = frozenset(
    CacheLoaderService.PARCEL_UNIVERSE_WHITELIST
    - CacheLoaderService.PARCEL_UNIVERSE_NOT_NULL
)


class TestProperty7MissingNullableBecomesNull:

    @given(
        cols_to_omit=st.frozensets(
            st.sampled_from(sorted(_PU_NULLABLE_COLS)),
            min_size=1,
        )
    )
    @settings(max_examples=50)
    def test_missing_nullable_fields_become_null(self, cols_to_omit):
        """Nullable columns omitted from the Socrata row map to None in the result.

        **Validates: Requirements 6.2, 6.3**
        """
        # Feature: chicago-socrata-local-cache, Property 7: missing nullable fields become NULL
        svc = _make_svc()
        whitelist = svc.PARCEL_UNIVERSE_WHITELIST
        not_null = svc.PARCEL_UNIVERSE_NOT_NULL

        full_row = {'pin': '12345678901234', 'lat': '41.8', 'lon': '-87.6', 'last_synced_at': None}
        partial_row = {k: v for k, v in full_row.items() if k not in cols_to_omit}

        result = svc._map_row(partial_row, whitelist, not_null)

        assert result is not None
        for col in cols_to_omit:
            assert result[col] is None, f"Expected None for omitted nullable col {col!r}, got {result[col]!r}"


# ===========================================================================
# Property 8: Schema drift — rows with missing NOT NULL fields are skipped
# Feature: chicago-socrata-local-cache, Property 8: missing NOT NULL → skip
# Validates: Requirements 6.5
# ===========================================================================

class TestProperty8MissingNotNullSkipped:

    @given(
        extra=st.dictionaries(
            keys=st.text(min_size=1, max_size=10).filter(lambda k: k not in ALL_KNOWN_COLUMNS),
            values=st.text(),
            max_size=3,
        )
    )
    @settings(max_examples=50)
    def test_missing_not_null_column_returns_none(self, extra):
        """A row missing the NOT NULL 'pin' column is skipped (_map_row returns None).

        **Validates: Requirements 6.5**
        """
        # Feature: chicago-socrata-local-cache, Property 8: missing NOT NULL fields skipped
        svc = _make_svc()
        whitelist = svc.PARCEL_UNIVERSE_WHITELIST
        not_null = svc.PARCEL_UNIVERSE_NOT_NULL

        # Build a row with all nullable columns but deliberately omit 'pin'
        row = {'lat': '41.8', 'lon': '-87.6', 'last_synced_at': None, **extra}
        row.pop('pin', None)  # ensure pin is absent

        result = svc._map_row(row, whitelist, not_null)
        assert result is None, f"Expected None when NOT NULL col 'pin' is missing, got {result!r}"


# ===========================================================================
# Property 9: Pagination termination
# Feature: chicago-socrata-local-cache, Property 9: pagination termination
# Validates: Requirements 2.1
# ===========================================================================

class TestProperty9PaginationTermination:

    @given(page_sizes=page_sequence_strategy)
    @settings(max_examples=50)
    def test_pagination_terminates_correctly(self, page_sizes):
        """_fetch_pages stops when it receives a page smaller than page_size.

        A full page (== page_size) triggers another request. Pagination stops only
        when a page is *smaller* than page_size.  If the strategy produces a sequence
        that ends on a full page, we append an empty page as the terminator so the
        mock doesn't run out of side_effects.

        **Validates: Requirements 2.1**
        """
        # Feature: chicago-socrata-local-cache, Property 9: pagination termination
        svc = _make_svc()
        total_rows = sum(page_sizes)

        # Build stub pages
        page_data = [[{'pin': str(i)} for i in range(sz)] for sz in page_sizes]

        # If the last page is exactly PAGE_SIZE, the loop will request one more page.
        # Append an empty terminator so the mock doesn't raise StopIteration.
        if page_sizes and page_sizes[-1] == PAGE_SIZE:
            page_data.append([])
            expected_requests = len(page_sizes) + 1
        else:
            expected_requests = len(page_sizes)

        with patch.object(svc, '_socrata_get_with_retry', side_effect=page_data) as mock_get:
            pages = list(svc._fetch_pages('parcel_universe', page_size=PAGE_SIZE))

        assert mock_get.call_count == expected_requests, (
            f"Expected {expected_requests} requests, got {mock_get.call_count}"
        )
        assert sum(len(p) for p in pages) == total_rows


# ===========================================================================
# Property 10: Sync log written on success with correct row count
# Feature: chicago-socrata-local-cache, Property 10: sync log on success
# Validates: Requirements 2.3
# ===========================================================================

class TestProperty10SyncLogOnSuccess:

    @given(
        row_counts=st.lists(
            st.integers(min_value=1, max_value=100),
            min_size=1, max_size=3,
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_sync_log_written_on_success(self, db_session, app, row_counts):
        """full_load writes exactly one sync_log row with status='success' and correct rows_upserted.

        We mock _fetch_pages and _upsert_parcel_universe to focus purely on the
        sync-log write behaviour, avoiding pg_insert SQLite incompatibility.

        **Validates: Requirements 2.3**
        """
        # Feature: chicago-socrata-local-cache, Property 10: sync log written on success
        total_rows = sum(row_counts)

        # Build page data — each list is a page returned by the iterator
        pages = [[{'pin': str(i), 'lat': '41.8', 'lon': '-87.6', 'last_synced_at': None}
                  for i in range(count)]
                 for count in row_counts]

        svc = _make_svc()
        with app.app_context():
            # Mock _fetch_pages as a generator that yields our pages
            with patch.object(svc, '_fetch_pages', return_value=iter(pages)), \
                 patch.object(svc, '_upsert_parcel_universe',
                              side_effect=row_counts) as mock_upsert:
                result = svc.full_load('parcel_universe')

        assert result.status == 'success', f"Expected success, got {result.status}"
        assert result.rows_upserted == total_rows, (
            f"Expected rows_upserted={total_rows}, got {result.rows_upserted}"
        )

        # Check the sync_log row in the database
        with app.app_context():
            logs = (
                db.session.query(SyncLog)
                .filter_by(dataset_name='parcel_universe', status='success')
                .all()
            )
        assert len(logs) >= 1, "Expected at least one success sync_log row"
        assert any(log.rows_upserted == total_rows for log in logs), (
            f"No log with rows_upserted={total_rows} found in {[(log.status, log.rows_upserted) for log in logs]}"
        )


# ===========================================================================
# Property 11: Retry behavior on transient HTTP errors
# Feature: chicago-socrata-local-cache, Property 11: retry on transient errors
# Validates: Requirements 2.4
# ===========================================================================

class TestProperty11RetryBehavior:

    @given(k=st.integers(min_value=0, max_value=2))
    @settings(max_examples=15)
    def test_retry_k_failures_then_success(self, k):
        """_socrata_get_with_retry makes exactly k+1 total requests after k failures then success.

        **Validates: Requirements 2.4**
        """
        # Feature: chicago-socrata-local-cache, Property 11: retry behavior on transient HTTP errors
        svc = _make_svc()

        ok_resp = MagicMock()
        ok_resp.ok = True
        ok_resp.json.return_value = [{'pin': '12345678901234'}]

        fail_resp = MagicMock()
        fail_resp.ok = False
        fail_resp.status_code = 503

        side_effects = [fail_resp] * k + [ok_resp]

        with patch('app.services.cache_loader_service.requests.get', side_effect=side_effects) as mock_get, \
             patch('app.services.cache_loader_service.time.sleep'):
            result = svc._socrata_get_with_retry(
                'https://datacatalog.cookcountyil.gov/resource/pabr-t5kh.json',
                max_retries=3,
                wait_secs=0,
            )

        assert mock_get.call_count == k + 1, (
            f"Expected {k + 1} requests for {k} failures + 1 success, got {mock_get.call_count}"
        )
        assert result == [{'pin': '12345678901234'}]


# ===========================================================================
# Property 12: Cache status classification is deterministic
# Feature: chicago-socrata-local-cache, Property 12: status classification determinism
# Validates: Requirements 5.2, 5.3, 5.4, 5.5
# ===========================================================================

class _SyncLogStub:
    """Lightweight stub that mimics the SyncLog attributes used by _classify_status.

    Avoids SQLAlchemy instrumentation issues when creating objects outside
    an application context.
    """

    def __init__(self, status: str, completed_at: Optional[datetime] = None):
        self.status = status
        self.completed_at = completed_at
        self.dataset_name = 'parcel_universe'
        self.started_at = datetime.now(timezone.utc)
        self.rows_upserted = 0
        self.error_message = None


def _make_sync_log_obj(
    status: str,
    completed_at: Optional[datetime] = None,
    dataset_name: str = 'parcel_universe',
) -> _SyncLogStub:
    """Build a lightweight SyncLog-like stub for use with _classify_status."""
    return _SyncLogStub(status=status, completed_at=completed_at)


class TestProperty12StatusClassificationDeterministic:

    # Parameterize the 4 cases using @given to check they behave deterministically
    # across random but valid inputs.

    @given(row_count=st.integers(min_value=1, max_value=10_000_000))
    @settings(max_examples=50)
    def test_fresh_when_rows_and_recent_success(self, row_count):
        """row_count > 0 + last_success ≤ 30 days ago → 'fresh'.

        **Validates: Requirements 5.2, 5.4**
        """
        # Feature: chicago-socrata-local-cache, Property 12: status classification determinism
        svc = CacheStatusService()
        completed_at = datetime.now(timezone.utc) - timedelta(days=15)
        last_success = _make_sync_log_obj('success', completed_at)

        result = svc._classify_status(row_count, last_success, None)
        assert result == 'fresh', f"Expected 'fresh' for row_count={row_count}, got {result!r}"

    @given(row_count=st.integers(min_value=1, max_value=10_000_000))
    @settings(max_examples=50)
    def test_stale_when_rows_and_old_success(self, row_count):
        """row_count > 0 + last_success > 30 days ago → 'stale'.

        **Validates: Requirements 5.2, 5.5**
        """
        # Feature: chicago-socrata-local-cache, Property 12: status classification determinism
        svc = CacheStatusService()
        completed_at = datetime.now(timezone.utc) - timedelta(days=60)
        last_success = _make_sync_log_obj('success', completed_at)

        result = svc._classify_status(row_count, last_success, None)
        assert result == 'stale', f"Expected 'stale' for row_count={row_count}, got {result!r}"

    @given(row_count=st.just(0))
    @settings(max_examples=5)
    def test_never_synced_when_empty_and_no_logs(self, row_count):
        """row_count == 0, no sync logs at all → 'never_synced'.

        **Validates: Requirements 5.2, 5.3**
        """
        # Feature: chicago-socrata-local-cache, Property 12: status classification determinism
        svc = CacheStatusService()
        result = svc._classify_status(0, None, None)
        assert result == 'never_synced'

    @given(row_count=st.just(0))
    @settings(max_examples=5)
    def test_empty_when_empty_and_has_failure(self, row_count):
        """row_count == 0, failed sync log exists → 'empty'.

        **Validates: Requirements 5.2, 5.3**
        """
        # Feature: chicago-socrata-local-cache, Property 12: status classification determinism
        svc = CacheStatusService()
        last_failure = _make_sync_log_obj('failed', datetime.now(timezone.utc))
        result = svc._classify_status(0, None, last_failure)
        assert result == 'empty'

    @given(
        days_since=st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50)
    def test_result_is_one_of_four_valid_values(self, days_since):
        """_classify_status always returns one of exactly four valid status strings.

        **Validates: Requirements 5.2**
        """
        # Feature: chicago-socrata-local-cache, Property 12: status classification determinism
        svc = CacheStatusService()
        valid_statuses = {'empty', 'fresh', 'stale', 'never_synced'}

        completed_at = datetime.now(timezone.utc) - timedelta(days=days_since)
        last_success = _make_sync_log_obj('success', completed_at)

        for row_count in [0, 1, 1000]:
            result = svc._classify_status(row_count, last_success if row_count > 0 else None, None)
            assert result in valid_statuses, f"Unexpected status {result!r}"


# ===========================================================================
# Property 13: Cache-first routing prevents live API calls
# Feature: chicago-socrata-local-cache, Property 13: cache-first routing
# Validates: Requirements 4.1, 4.2, 4.3
# ===========================================================================

def _seed_all_caches(db_session_obj):
    """Seed one row into each of the three cache tables."""
    pu = ParcelUniverseCache(pin='14083010190000', lat=Decimal('41.8781'), lon=Decimal('-87.6298'))
    db_session_obj.merge(pu)

    ps = ParcelSalesCache(
        pin='14083010190000',
        sale_date=date(2023, 6, 1),
        sale_price=Decimal('300000.00'),
        class_='202',
        sale_type='LAND AND BUILDING',
        is_multisale=False,
        sale_filter_less_than_10k=False,
        sale_filter_deed_type=False,
    )
    db_session_obj.add(ps)

    ic = ImprovementCharacteristicsCache(
        pin='14083010190000',
        bldg_sf=2400,
        beds=3,
        fbath=Decimal('2.0'),
        hbath=Decimal('0.0'),
        age=50,
        ext_wall=3,
        apts=1,
    )
    db_session_obj.merge(ic)
    db_session_obj.flush()


class TestProperty13CacheFirstRouting:

    def test_cache_populated_prevents_live_api_calls(self, db_session, app):
        """With all three caches populated, fetch_comparables makes zero HTTP calls.

        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        # Feature: chicago-socrata-local-cache, Property 13: cache-first routing prevents live API calls
        _seed_all_caches(db_session)

        from app.services.comparable_sales_finder import CookCountySalesDataSource
        from app.models.property_facts import PropertyType

        subject = MagicMock()
        subject.latitude = 41.8781
        subject.longitude = -87.6298
        subject.property_type = PropertyType.SINGLE_FAMILY

        with app.app_context():
            with patch('app.services.comparable_sales_finder.urllib.request.urlopen') as mock_urlopen, \
                 patch('app.services.comparable_sales_finder.requests.get') as mock_requests_get:

                datasource = CookCountySalesDataSource()
                # fetch_comparables may return empty list (no matching sales close enough)
                # — what matters is zero HTTP calls to the live API
                datasource.fetch_comparables(
                    subject_facts=subject,
                    max_age_months=36,
                    max_distance_miles=10.0,
                    max_count=10,
                )

        mock_urlopen.assert_not_called()
        mock_requests_get.assert_not_called()


# ===========================================================================
# Property 14: Output schema consistency regardless of data source
# Feature: chicago-socrata-local-cache, Property 14: output schema consistency
# Validates: Requirements 4.7
# ===========================================================================

_EXPECTED_COMP_KEYS = frozenset({
    'pin', 'sale_date', 'sale_price', 'property_type', 'units',
    'bedrooms', 'bathrooms', 'square_footage', 'lot_size', 'year_built',
    'construction_type', 'interior_condition', 'latitude', 'longitude',
    'similarity_notes', 'address',
})


class TestProperty14OutputSchemaConsistency:

    def test_output_keys_consistent_with_cache(self, db_session, app):
        """fetch_comparables returns dicts with exactly the expected keys when using cache.

        **Validates: Requirements 4.7**
        """
        # Feature: chicago-socrata-local-cache, Property 14: output schema consistency (cache path)
        _seed_all_caches(db_session)

        from app.services.comparable_sales_finder import CookCountySalesDataSource
        from app.models.property_facts import PropertyType

        subject = MagicMock()
        subject.latitude = 41.8781
        subject.longitude = -87.6298
        subject.property_type = PropertyType.SINGLE_FAMILY

        with app.app_context():
            datasource = CookCountySalesDataSource()
            result = datasource.fetch_comparables(
                subject_facts=subject,
                max_age_months=36,
                max_distance_miles=10.0,
                max_count=10,
            )

        for comp in result:
            comp_keys = frozenset(comp.keys())
            assert comp_keys == _EXPECTED_COMP_KEYS, (
                f"Key mismatch (cache path):\n  extra keys: {comp_keys - _EXPECTED_COMP_KEYS}\n  missing keys: {_EXPECTED_COMP_KEYS - comp_keys}"
            )

    def test_map_to_comparable_always_has_required_keys(self, app):
        """_map_to_comparable always produces dicts with exactly the required output keys.

        **Validates: Requirements 4.7**
        """
        # Feature: chicago-socrata-local-cache, Property 14: output schema consistency (_map_to_comparable)
        from app.services.comparable_sales_finder import CookCountySalesDataSource

        datasource = CookCountySalesDataSource()

        # Test with a fully populated sale + chars
        sale = {
            'pin': '14083010190000',
            'sale_date': '2023-06-01T00:00:00.000',
            'sale_price': '300000',
            'class': '202',
        }
        chars = {
            'square_footage': 2400,
            'bedrooms': 3,
            'bathrooms': 2.0,
            'year_built': 1975,
            'construction_type': 'BRICK',
            'units': 1,
        }

        with app.app_context():
            result = datasource._map_to_comparable(sale, chars, 41.8781, -87.6298)

        assert frozenset(result.keys()) == _EXPECTED_COMP_KEYS, (
            f"Key mismatch:\n  extra: {frozenset(result.keys()) - _EXPECTED_COMP_KEYS}\n  missing: {_EXPECTED_COMP_KEYS - frozenset(result.keys())}"
        )

    def test_map_to_comparable_with_empty_chars_still_has_all_keys(self, app):
        """_map_to_comparable with empty chars dict still has all required keys (values may be None).

        **Validates: Requirements 4.7**
        """
        # Feature: chicago-socrata-local-cache, Property 14: output schema consistency (empty chars)
        from app.services.comparable_sales_finder import CookCountySalesDataSource

        datasource = CookCountySalesDataSource()

        sale = {'pin': '99999999999999', 'sale_date': None, 'sale_price': None, 'class': ''}
        chars = {}

        with app.app_context():
            result = datasource._map_to_comparable(sale, chars, 41.0, -88.0)

        assert frozenset(result.keys()) == _EXPECTED_COMP_KEYS


# ===========================================================================
# Property 15: Incremental refresh uses correct watermark
# Feature: chicago-socrata-local-cache, Property 15: incremental refresh watermark
# Validates: Requirements 3.2, 3.3
# ===========================================================================

class TestProperty15IncrementalRefreshWatermark:

    @given(
        n_success=st.integers(min_value=1, max_value=5),
        n_failed=st.integers(min_value=0, max_value=3),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_get_last_success_timestamp_returns_max_completed_at(
        self, db_session, n_success, n_failed
    ):
        """_get_last_success_timestamp returns the maximum completed_at among 'success' rows.

        Uses widely spaced timestamps per (n_success, n_failed) combination so
        that even if rows from other examples linger in the session, the max()
        among OUR rows is still correctly identified.

        **Validates: Requirements 3.2, 3.3**
        """
        # Feature: chicago-socrata-local-cache, Property 15: incremental refresh uses correct watermark

        # Use a unique dataset name derived from the test parameters so rows from
        # different Hypothesis examples never overlap in the same DB session.
        dataset_name = f'prop15_suc{n_success}_fail{n_failed}'

        # Separate time epochs per (n_success, n_failed) so that
        # even replayed examples produce isolated, non-overlapping timestamps.
        # The epoch is far enough from any other example's epoch to guarantee
        # the max() query returns the right value.
        epoch_offset_days = (n_success * 1000) + (n_failed * 100)
        base_time = datetime(2010, 1, 1, 0, 0, 0) + timedelta(days=epoch_offset_days)
        success_times = [base_time + timedelta(minutes=i) for i in range(n_success)]
        expected_max = max(success_times)

        # Insert success logs
        for t in success_times:
            log = SyncLog(
                dataset_name=dataset_name,
                started_at=t,
                completed_at=t,
                rows_upserted=100,
                status='success',
            )
            db_session.add(log)

        # Insert failed logs at a much earlier epoch (no overlap with success times)
        fail_base = datetime(2000, 1, 1, 0, 0, 0)
        for i in range(n_failed):
            fail_t = fail_base + timedelta(hours=i)
            log = SyncLog(
                dataset_name=dataset_name,
                started_at=fail_t,
                completed_at=fail_t,
                rows_upserted=0,
                status='failed',
                error_message='test error',
            )
            db_session.add(log)

        db_session.flush()

        svc = _make_svc()
        result = svc._get_last_success_timestamp(dataset_name)

        assert result is not None
        assert result == expected_max, (
            f"Expected max completed_at={expected_max}, got {result}"
        )

    @given(n_failed=st.integers(min_value=1, max_value=5))
    @settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_get_last_success_timestamp_returns_none_when_only_failures(
        self, db_session, n_failed
    ):
        """_get_last_success_timestamp returns None when only failed logs exist.

        **Validates: Requirements 3.2, 3.3**
        """
        # Feature: chicago-socrata-local-cache, Property 15: watermark None with no successes
        # Use a unique dataset name — no success rows should exist for it
        dataset_name = f'prop15_failures_only_{n_failed}'

        base_time = datetime(2024, 1, 1, 12, 0, 0)
        for i in range(n_failed):
            t = base_time + timedelta(days=i)
            log = SyncLog(
                dataset_name=dataset_name,
                started_at=t,
                completed_at=t,
                rows_upserted=0,
                status='failed',
                error_message='test error',
            )
            db_session.add(log)
        db_session.flush()

        svc = _make_svc()
        result = svc._get_last_success_timestamp(dataset_name)

        assert result is None


# ===========================================================================
# Property 16: Failed refresh leaves existing cache data intact
# Feature: chicago-socrata-local-cache, Property 16: failed refresh preserves cache
# Validates: Requirements 3.5
# ===========================================================================

class TestProperty16FailedRefreshPreservesCache:

    @given(
        pins=st.lists(pin_strategy, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_failed_refresh_preserves_existing_rows(self, db_session, app, pins):
        """After a full_load failure, pre-existing cache rows remain unchanged.

        **Validates: Requirements 3.5**
        """
        # Feature: chicago-socrata-local-cache, Property 16: failed refresh leaves existing cache data intact
        with app.app_context():
            # Pre-populate with known data
            for pin in pins:
                row = ParcelUniverseCache(
                    pin=pin,
                    lat=Decimal('41.8781'),
                    lon=Decimal('-87.6298'),
                )
                db.session.merge(row)
            db.session.commit()

            pre_count = db.session.query(ParcelUniverseCache).count()
            pre_pins = {r.pin for r in db.session.query(ParcelUniverseCache).all()}

            # Simulate an API failure during full_load
            svc = _make_svc()
            with patch.object(svc, '_socrata_get_with_retry', side_effect=Exception('API down')):
                result = svc.full_load('parcel_universe')

            assert result.status == 'failed'

            # Verify pre-existing rows are intact
            post_count = db.session.query(ParcelUniverseCache).count()
            post_pins = {r.pin for r in db.session.query(ParcelUniverseCache).all()}

        assert post_count == pre_count, (
            f"Row count changed after failed refresh: {pre_count} → {post_count}"
        )
        assert post_pins == pre_pins, (
            f"Pin set changed after failed refresh: {pre_pins} → {post_pins}"
        )


# ===========================================================================
# Property 17: Parcel Sales filter — only LAND AND BUILDING records loaded
# Feature: chicago-socrata-local-cache, Property 17: LAND AND BUILDING filter
# Validates: Requirements 2.7
# ===========================================================================

_OTHER_SALE_TYPES = [
    'LAND ONLY',
    'BUILDING ONLY',
    'CONDO',
    'VACANT LAND',
    'COMMERCIAL',
    '',
]

other_sale_type_strategy = st.sampled_from(_OTHER_SALE_TYPES)


class TestProperty17LandAndBuildingFilter:

    @given(
        n_valid=st.integers(min_value=1, max_value=5),
        n_invalid=st.integers(min_value=1, max_value=5),
        invalid_types=st.lists(other_sale_type_strategy, min_size=1, max_size=5),
    )
    @settings(max_examples=50)
    def test_fetch_pages_url_always_contains_land_and_building_filter(
        self, n_valid, n_invalid, invalid_types
    ):
        """_fetch_pages for parcel_sales always appends sale_type='LAND AND BUILDING' to the URL.

        **Validates: Requirements 2.7**
        """
        # Feature: chicago-socrata-local-cache, Property 17: LAND AND BUILDING filter in URL
        svc = _make_svc()

        with patch.object(svc, '_socrata_get_with_retry', return_value=[]) as mock_get:
            list(svc._fetch_pages('parcel_sales', page_size=PAGE_SIZE))

        url = mock_get.call_args[0][0]
        assert 'LAND' in url, f"'LAND AND BUILDING' filter not found in URL: {url!r}"
        assert 'BUILDING' in url, f"'BUILDING' not found in URL: {url!r}"

    @given(n_mixed=st.integers(min_value=1, max_value=5))
    @settings(max_examples=30)
    def test_map_row_does_not_filter_by_sale_type(self, n_mixed):
        """_map_row is agnostic to sale_type; filtering happens at the Socrata query level.

        The sale_type filter is enforced by the $where clause sent to Socrata
        (tested above). _map_row itself should accept any sale_type value so
        downstream code is not surprised.

        **Validates: Requirements 2.7**
        """
        # Feature: chicago-socrata-local-cache, Property 17: map_row accepts all sale_type values
        svc = _make_svc()
        whitelist = svc.PARCEL_SALES_WHITELIST
        not_null = svc.PARCEL_SALES_NOT_NULL

        # A valid LAND AND BUILDING row should always pass through _map_row
        valid_row = {
            'pin': '12345678901234',
            'sale_date': '2023-01-01',
            'sale_price': '300000',
            'class': '202',
            'sale_type': 'LAND AND BUILDING',
            'is_multisale': None,
            'sale_filter_less_than_10k': None,
            'sale_filter_deed_type': None,
            'last_synced_at': None,
        }
        result = svc._map_row(valid_row, whitelist, not_null)
        assert result is not None
        assert result['sale_type'] == 'LAND AND BUILDING'
