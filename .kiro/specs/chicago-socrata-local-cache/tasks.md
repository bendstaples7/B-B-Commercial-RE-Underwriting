# Implementation Plan: chicago-socrata-local-cache

## Overview

Implement a local PostgreSQL mirror of three Cook County Socrata datasets (Parcel Universe, Parcel Sales, Improvement Characteristics) with a Celery Beat refresh schedule, cache-first comparable search routing, REST status/sync endpoints, and comprehensive property-based and unit tests.

## Tasks

- [x] 1. Add custom exceptions for cache sync errors
  - [x] 1.1 Add `CacheSyncException` and `InvalidCronExpressionException` to `backend/app/exceptions.py`
    - Extend `RealEstateAnalysisException` for both classes
    - `CacheSyncException.__init__(message, dataset, page_offset=None)` sets `status_code=503` and `payload` with `error_type`, `dataset`, `page_offset`
    - `InvalidCronExpressionException.__init__(expression)` sets `status_code=500` and `payload` with `error_type`, `expression`
    - _Requirements: 2.5, 3.7_

- [x] 2. Create SQLAlchemy models for the four new tables
  - [x] 2.1 Create `backend/app/models/parcel_universe_cache.py` with `ParcelUniverseCache` model
    - Columns: `pin` VARCHAR(14) primary key, `lat` NUMERIC(10,7), `lon` NUMERIC(10,7), `last_synced_at` TIMESTAMP WITH TIME ZONE
    - Add composite index `(lat, lon)` via `__table_args__`
    - _Requirements: 1.1_

  - [x] 2.2 Create `backend/app/models/parcel_sales_cache.py` with `ParcelSalesCache` model
    - Columns: `id` SERIAL primary key, `pin` VARCHAR(14) not null, `sale_date` DATE, `sale_price` NUMERIC(14,2), `class_` mapped to DB column `class` VARCHAR(10), `sale_type` VARCHAR(50), `is_multisale` BOOLEAN, `sale_filter_less_than_10k` BOOLEAN, `sale_filter_deed_type` BOOLEAN, `last_synced_at` TIMESTAMP WITH TIME ZONE
    - Add `__table_args__` with composite index `ix_parcel_sales_pin_sale_date` on `(pin, sale_date)` and index `ix_parcel_sales_sale_date` on `(sale_date)`
    - _Requirements: 1.2, 1.6, 1.7_

  - [x] 2.3 Create `backend/app/models/improvement_characteristics_cache.py` with `ImprovementCharacteristicsCache` model
    - Columns: `pin` VARCHAR(14) primary key, `bldg_sf` INTEGER, `beds` INTEGER, `fbath` NUMERIC(4,1), `hbath` NUMERIC(4,1), `age` INTEGER, `ext_wall` INTEGER, `apts` INTEGER, `last_synced_at` TIMESTAMP WITH TIME ZONE
    - _Requirements: 1.3_

  - [x] 2.4 Create `backend/app/models/sync_log.py` with `SyncLog` model
    - Columns: `id` SERIAL primary key, `dataset_name` VARCHAR(100) not null with index, `started_at` TIMESTAMP WITH TIME ZONE not null, `completed_at` TIMESTAMP WITH TIME ZONE, `rows_upserted` INTEGER, `status` VARCHAR(10) with `CheckConstraint("status IN ('running', 'success', 'failed')", name='ck_sync_log_status')` not null, `error_message` TEXT
    - _Requirements: 1.4_

  - [x] 2.5 Re-export all four new models from `backend/app/models/__init__.py`
    - Add imports for `ParcelUniverseCache`, `ParcelSalesCache`, `ImprovementCharacteristicsCache`, `SyncLog`
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 3. Create Alembic migration for the four new tables
  - [x] 3.1 Create `backend/alembic_migrations/versions/g7h8i9j0k1l2_add_socrata_cache_tables.py`
    - Set `down_revision = 'fd5451087f07'`
    - `upgrade()`: create all four tables and their indexes in dependency order (no ALTER/DROP on existing tables)
    - `downgrade()`: drop indexes first, then tables in reverse order (`sync_log`, `improvement_characteristics_cache`, `parcel_sales_cache`, `parcel_universe_cache`)
    - _Requirements: 1.5_

- [x] 4. Checkpoint — verify models and migration
  - Ensure all four model files import cleanly and `__init__.py` re-exports are correct. Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement `CacheLoaderService`
  - [x] 5.1 Create `backend/app/services/cache_loader_service.py` with `SyncResult` dataclass and `CacheLoaderService` skeleton
    - Define `SyncResult(dataset, status, rows_upserted, error_message)` dataclass
    - Define column whitelists and `NOT NULL` column sets for each of the three datasets as class-level constants
    - _Requirements: 2.1, 2.2_

  - [x] 5.2 Implement `_socrata_get_with_retry(url, max_retries=3, wait_secs=5)` on `CacheLoaderService`
    - Retry up to 3 times on HTTP 4xx/5xx or network errors with 5-second wait between attempts
    - Raise `CacheSyncException` after all retries exhausted
    - _Requirements: 2.4, 2.5_

  - [x] 5.3 Implement `_fetch_pages(dataset_name, page_size, since_dt=None)` generator on `CacheLoaderService`
    - Build Socrata URL with `$limit`, `$offset`, and optional `$where=:updated_at >= '<since_dt>'` filter
    - For `parcel_sales` dataset, always append `AND sale_type='LAND AND BUILDING'` to the `$where` clause
    - Yield each page as `list[dict]`; stop when page length < `page_size`
    - _Requirements: 2.1, 2.7_

  - [x] 5.4 Implement `_map_row(row, column_whitelist, not_null_cols)` on `CacheLoaderService`
    - Drop keys not in `column_whitelist`
    - For missing nullable columns, insert `None`
    - For missing or type-error NOT NULL columns, log WARNING with PIN and column name, return `None` (caller skips the row)
    - For type conversion errors on nullable columns, log WARNING with PIN and field name, insert `None`
    - Log WARNING if total column count in row differs from schema column count
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 5.5 Implement `_upsert_parcel_universe(rows)`, `_upsert_parcel_sales(rows)`, `_upsert_improvement_chars(rows)` on `CacheLoaderService`
    - Use SQLAlchemy `insert(...).on_conflict_do_update(...)` (PostgreSQL upsert) keyed on `pin` for universe and improvement chars; keyed on `id` auto-increment for sales (insert-only, no conflict key needed for sales since `id` is serial — use `pin` as the natural conflict target for idempotency)
    - Each method calls `_map_row` per row, skips `None` results, and returns count of successfully upserted rows
    - _Requirements: 1.8, 2.2_

  - [x] 5.6 Implement `_write_sync_log(dataset, started_at, status, rows_upserted, error_message)` and `_get_last_success_timestamp(dataset)` on `CacheLoaderService`
    - `_write_sync_log`: insert a `SyncLog` row with `completed_at=datetime.utcnow()` (or `None` for `running` status)
    - `_get_last_success_timestamp`: query `SyncLog` for max `completed_at` where `status='success'` and `dataset_name=dataset`; return `None` if no rows
    - _Requirements: 2.3, 3.2, 3.3_

  - [x] 5.7 Implement `full_load(dataset)` and `incremental_refresh(dataset)` on `CacheLoaderService`
    - `full_load`: write `running` sync_log, paginate all records, upsert, write `success` or `failed` sync_log
    - `incremental_refresh`: call `_get_last_success_timestamp`; if `None`, delegate to `full_load`; otherwise paginate with `since_dt` watermark, upsert, write sync_log
    - On any unrecoverable error, write `failed` sync_log with `rows_upserted` = count upserted before failure; do not truncate existing rows
    - _Requirements: 2.3, 2.5, 3.2, 3.3, 3.4, 3.5_

  - [x] 5.8 Implement `load_all(mode)` on `CacheLoaderService`
    - Call `full_load` or `incremental_refresh` for each of the three datasets sequentially
    - Return `list[SyncResult]` with one entry per dataset
    - _Requirements: 2.6_

  - [x] 5.9 Re-export `CacheLoaderService` and `SyncResult` from `backend/app/services/__init__.py`
    - _Requirements: 2.1_

- [x] 6. Implement `CacheStatusService`
  - [x] 6.1 Create `backend/app/services/cache_status_service.py` with `DatasetStatus` dataclass and `CacheStatusService`
    - Define `DatasetStatus(dataset_name, row_count, last_synced_at, status, last_error)` dataclass
    - Implement `_row_count(table_model)`, `_last_successful_sync(dataset_name)`, `_last_failed_sync(dataset_name)` helpers
    - _Requirements: 5.1_

  - [x] 6.2 Implement `_classify_status(row_count, last_success, last_failure)` on `CacheStatusService`
    - `row_count == 0` and no sync ever → `never_synced`
    - `row_count == 0` → `empty`
    - `days_since_last_success <= SOCRATA_STALE_DAYS` (default 30, from env var) → `fresh`
    - `days_since_last_success > SOCRATA_STALE_DAYS` → `stale`
    - _Requirements: 5.2, 5.3, 5.4, 5.5_

  - [x] 6.3 Implement `get_dataset_status(dataset_name)` and `get_status()` on `CacheStatusService`
    - `get_dataset_status`: assemble `DatasetStatus` using helpers and `_classify_status`; populate `last_error` from most recent failed sync_log row
    - `get_status`: call `get_dataset_status` for all three datasets and return list
    - Propagate `SQLAlchemyError` on DB unavailability (controller's `@handle_errors` handles HTTP 503)
    - _Requirements: 5.1, 5.5_

  - [x] 6.4 Re-export `CacheStatusService` and `DatasetStatus` from `backend/app/services/__init__.py`
    - _Requirements: 5.1_

- [x] 7. Checkpoint — verify services
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Add Marshmallow schemas for cache endpoints
  - [x] 8.1 Append `SocrataSyncRequestSchema` and `DatasetStatusResponseSchema` to `backend/app/schemas.py`
    - `SocrataSyncRequestSchema`: `dataset` field, validates against accepted values `['all', 'parcel_universe', 'parcel_sales', 'improvement_characteristics']`, returns HTTP 400 with `accepted_values` list on invalid input
    - `DatasetStatusResponseSchema`: serializes `DatasetStatus` fields (`dataset_name`, `row_count`, `last_synced_at` as ISO 8601 string or null, `status`, `last_error`)
    - _Requirements: 5.6, 5.7, 5.8, 5.9_

- [x] 9. Implement cache controller Blueprint
  - [x] 9.1 Create `backend/app/controllers/cache_controller.py` with `cache_bp` Blueprint registered at `/api/cache`
    - `GET /api/cache/socrata/status` → `cache_status()`: call `CacheStatusService.get_status()`, serialize with `DatasetStatusResponseSchema`, return HTTP 200
    - `POST /api/cache/socrata/sync` → `trigger_sync()`: validate body with `SocrataSyncRequestSchema`, enqueue `socrata_cache_refresh_task.delay(dataset=...)`, return HTTP 202 with `{"task_id": ..., "dataset": ...}`
    - Use `@handle_errors` decorator on both routes
    - Return HTTP 400 for invalid dataset or missing/non-JSON body; HTTP 503 if Celery broker unavailable
    - _Requirements: 5.1, 5.6, 5.7, 5.8, 5.9_

  - [x] 9.2 Register `cache_bp` in `backend/app/__init__.py` (inside `create_app`)
    - Import `cache_bp` from `controllers.cache_controller` and call `app.register_blueprint(cache_bp)`
    - _Requirements: 5.1, 5.6_

- [x] 10. Add Celery Beat task and cron validation
  - [x] 10.1 Add `socrata_cache_refresh_task` to `backend/celery_worker.py`
    - Decorate with `@celery.task(name='socrata_cache.refresh')`
    - Accept `dataset: str = 'all'` parameter; call `CacheLoaderService().load_all(mode='incremental')` or `full_load`/`incremental_refresh` per dataset
    - Return serializable dict summarising results
    - _Requirements: 3.1_

  - [x] 10.2 Add `beat_schedule` entry and cron validation to `backend/celery_worker.py`
    - Read `SOCRATA_SYNC_SCHEDULE` env var; if set, validate as a 5-field cron expression (raise `InvalidCronExpressionException` / `ValueError` at startup if invalid)
    - Default schedule: `crontab(hour=2, minute=0, day_of_week='sunday')`
    - Register `beat_schedule` on `celery.conf` with the `socrata_cache.refresh` task
    - _Requirements: 3.1, 3.6, 3.7_

- [x] 11. Update `CookCountySalesDataSource` for cache-first routing
  - [x] 11.1 Add `_cache_has_rows(table_model)` helper to `CookCountySalesDataSource` in `backend/app/services/comparable_sales_finder.py`
    - Execute `SELECT EXISTS(SELECT 1 FROM <table>)` or equivalent ORM count check
    - Return `bool`
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 11.2 Update `_fetch_pins_in_bbox(lat, lon, radius_miles)` in `CookCountySalesDataSource`
    - If `_cache_has_rows(ParcelUniverseCache)` is True, query `parcel_universe_cache` with `lat BETWEEN :min_lat AND :max_lat AND lon BETWEEN :min_lon AND :max_lon` parameterized query
    - Else fall back to existing Socrata API call and log a warning naming the empty table
    - Return same `dict[str, tuple[float, float]]` structure in both paths
    - _Requirements: 4.1, 4.4, 4.5_

  - [x] 11.3 Update `_fetch_sales_for_pins(pins, cutoff_date, target_classes)` in `CookCountySalesDataSource`
    - If `_cache_has_rows(ParcelSalesCache)` is True, query `parcel_sales_cache` with single `WHERE pin = ANY(:pins)` parameterized query (eliminates 100-PIN batch loop)
    - Else fall back to existing Socrata API call and log a warning
    - Return same list structure in both paths
    - _Requirements: 4.2, 4.4, 4.6_

  - [x] 11.4 Update `_fetch_improvement_chars(pins)` in `CookCountySalesDataSource`
    - If `_cache_has_rows(ImprovementCharacteristicsCache)` is True, query `improvement_characteristics_cache` with `WHERE pin = ANY(:pins)`
    - Else fall back to existing Socrata API call and log a warning
    - Return same `dict[str, dict]` structure in both paths
    - _Requirements: 4.3, 4.4_

  - [x] 11.5 Normalise output schema in all three fetch methods
    - Ensure every returned dict contains exactly the keys: `pin`, `sale_date`, `sale_price`, `property_type`, `units`, `bedrooms`, `bathrooms`, `square_footage`, `lot_size`, `year_built`, `construction_type`, `interior_condition`, `latitude`, `longitude`, `similarity_notes`, `address`
    - Absent values must be `None`, not omitted, regardless of whether data came from cache or live API
    - _Requirements: 4.7_

- [x] 12. Checkpoint — verify end-to-end routing
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Add `db_session` fixture and property-based tests
  - [x] 13.1 Add `db_session` fixture to `backend/tests/conftest.py`
    - Fixture provides a SQLAlchemy session bound to the in-memory SQLite test database
    - Rolls back after each test to ensure isolation
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 13.2 Write property test for Property 1 — Parcel Universe round-trip data integrity
    - **Property 1: Parcel Universe round-trip data integrity**
    - **Validates: Requirements 7.1**
    - In `backend/tests/test_socrata_cache_properties.py`
    - Use `pin_strategy`, `lat_strategy`, `lon_strategy`; write row, read back, assert exact equality

  - [ ]* 13.3 Write property test for Property 2 — Parcel Sales round-trip data integrity
    - **Property 2: Parcel Sales round-trip data integrity**
    - **Validates: Requirements 7.2**
    - Generate arbitrary `ParcelSalesCache` rows; write, read back by `(pin, sale_date)`, assert all column values match

  - [ ]* 13.4 Write property test for Property 3 — Improvement Characteristics round-trip data integrity
    - **Property 3: Improvement Characteristics round-trip data integrity**
    - **Validates: Requirements 7.3**
    - Generate arbitrary `ImprovementCharacteristicsCache` rows; write, read back by `pin`, assert all column values match

  - [ ]* 13.5 Write property test for Property 4 — Upsert overwrites previous values
    - **Property 4: Upsert overwrites previous values**
    - **Validates: Requirements 1.8, 7.4**
    - Generate PIN and two distinct value sets V1, V2; upsert V1 then V2; assert read-back returns V2 for all non-PK columns

  - [ ]* 13.6 Write property test for Property 5 — NULL preservation for nullable columns
    - **Property 5: NULL preservation for nullable columns**
    - **Validates: Requirements 7.5**
    - For each nullable column in each cache table, write row with NULL, read back, assert NULL returned

  - [ ]* 13.7 Write property test for Property 6 — Schema drift: extra fields silently dropped
    - **Property 6: Schema drift — extra fields are silently dropped**
    - **Validates: Requirements 6.1**
    - Use `extra_fields_strategy`; pass row dict with extra keys to `_map_row`; assert returned dict contains only whitelisted keys

  - [ ]* 13.8 Write property test for Property 7 — Schema drift: missing nullable fields become NULL
    - **Property 7: Schema drift — missing nullable fields become NULL**
    - **Validates: Requirements 6.2, 6.3**
    - Generate subsets of nullable columns to omit; call `_map_row`; assert omitted nullable columns map to `None`

  - [ ]* 13.9 Write property test for Property 8 — Schema drift: rows with missing NOT NULL fields are skipped
    - **Property 8: Schema drift — rows with missing NOT NULL fields are skipped**
    - **Validates: Requirements 6.5**
    - Generate batch with some rows missing NOT NULL fields; call upsert method; assert only valid rows inserted

  - [ ]* 13.10 Write property test for Property 9 — Pagination termination
    - **Property 9: Pagination termination**
    - **Validates: Requirements 2.1**
    - Use `page_sequence_strategy`; mock HTTP responses; assert `_fetch_pages` makes exactly `ceil(total_rows / page_size)` requests and stops on short page

  - [ ]* 13.11 Write property test for Property 10 — Sync log written on success with correct row count
    - **Property 10: Sync log written on success with correct row count**
    - **Validates: Requirements 2.3**
    - Mock K total rows across arbitrary pages; run `full_load`; assert exactly one `sync_log` row with `status='success'` and `rows_upserted=K`

  - [ ]* 13.12 Write property test for Property 11 — Retry behavior on transient HTTP errors
    - **Property 11: Retry behavior on transient HTTP errors**
    - **Validates: Requirements 2.4**
    - For k in 0..2 consecutive failures, mock responses; assert `_socrata_get_with_retry` makes exactly k+1 total requests and succeeds

  - [ ]* 13.13 Write property test for Property 12 — Cache status classification is deterministic
    - **Property 12: Cache status classification is deterministic**
    - **Validates: Requirements 5.2, 5.3, 5.4, 5.5**
    - Generate `(row_count, days_since_last_success, has_ever_synced)` triples; call `_classify_status`; assert exactly one of the four status values returned per the documented rules

  - [ ]* 13.14 Write property test for Property 13 — Cache-first routing prevents live API calls
    - **Property 13: Cache-first routing — non-empty cache prevents live API calls**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - Populate all three cache tables with at least one row; call `fetch_comparables` with mocked HTTP; assert zero HTTP requests made

  - [ ]* 13.15 Write property test for Property 14 — Output schema consistency regardless of data source
    - **Property 14: Output schema consistency regardless of data source**
    - **Validates: Requirements 4.7**
    - Call `fetch_comparables` with cache populated and with cache empty (API fallback); assert every returned dict has exactly the same set of keys in both cases

  - [ ]* 13.16 Write property test for Property 15 — Incremental refresh uses correct watermark
    - **Property 15: Incremental refresh uses correct watermark**
    - **Validates: Requirements 3.2, 3.3**
    - Generate `sync_log` history with mixed statuses and timestamps; call `_get_last_success_timestamp`; assert returns max `completed_at` among `status='success'` rows, or `None` if none

  - [ ]* 13.17 Write property test for Property 16 — Failed refresh leaves existing cache data intact
    - **Property 16: Failed refresh leaves existing cache data intact**
    - **Validates: Requirements 3.5**
    - Pre-populate cache tables; simulate API failure during refresh; assert all pre-existing rows unchanged after failure

  - [ ]* 13.18 Write property test for Property 17 — Parcel Sales filter: only LAND AND BUILDING records loaded
    - **Property 17: Parcel Sales filter — only LAND AND BUILDING records are loaded**
    - **Validates: Requirements 2.7**
    - Generate mock Socrata response with mixed `sale_type` values; run loader; assert only `sale_type='LAND AND BUILDING'` rows present in `parcel_sales_cache`

- [x] 14. Write unit tests for `CacheLoaderService`
  - [x]* 14.1 Write unit tests in `backend/tests/test_cache_loader_service.py`
    - Full load happy path with mocked Socrata responses
    - Retry: 1 failure then success; 2 failures then success; 3 failures → `sync_log` `status='failed'`
    - `dataset='all'` writes 3 separate `sync_log` rows
    - Incremental refresh uses correct watermark from `sync_log`
    - Schema drift: extra fields dropped; missing nullable → NULL; missing NOT NULL → row skipped
    - `sale_type` filter: only `LAND AND BUILDING` rows upserted
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.2, 3.3, 6.1, 6.2, 6.5_

- [x] 15. Write unit tests for `CacheStatusService`
  - [x]* 15.1 Write unit tests in `backend/tests/test_cache_status_service.py`
    - `never_synced` when table empty and no sync_log rows
    - `empty` when table empty but sync_log has rows
    - `fresh` when last success < 30 days ago
    - `stale` when last success > 30 days ago
    - `last_error` populated from most recent failed sync_log row
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 16. Write unit tests for cache controller
  - [x]* 16.1 Write unit tests in `backend/tests/test_cache_controller.py`
    - `GET /api/cache/socrata/status` returns correct JSON structure for all three datasets
    - `POST /api/cache/socrata/sync` with `dataset='all'` returns HTTP 202 with `task_id`
    - `POST /api/cache/socrata/sync` with invalid dataset returns HTTP 400 with `accepted_values`
    - `POST /api/cache/socrata/sync` with missing body returns HTTP 400
    - _Requirements: 5.1, 5.6, 5.7, 5.8, 5.9_

- [x] 17. Add cache-routing tests to `test_comparable_sales_finder.py`
  - [x]* 17.1 Add cache-routing test cases to `backend/tests/test_comparable_sales_finder.py`
    - Cache-first routing: non-empty cache → zero HTTP calls to Socrata
    - Fallback routing: empty cache → HTTP calls made, warning logged
    - Output schema consistency: same keys returned from cache path and API fallback path
    - `pin = ANY(:pins)` used (not batched IN clauses) when cache is active
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 4.7_

- [x] 18. Final checkpoint — full test suite
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The `class` column in `parcel_sales_cache` is a Python reserved word; use `class_` as the Python attribute with `db.Column('class', ...)` as the DB column name
- The `CheckConstraint` on `sync_log.status` works with SQLite for unit tests; integration tests against PostgreSQL validate the constraint enforcement
- Property tests use `@settings(max_examples=100)` minimum and the `db_session` fixture for ORM access
- All Socrata HTTP calls in tests are mocked; integration tests (marked `@pytest.mark.integration`) are skipped in CI
- The `SOCRATA_STALE_DAYS` env var (default 30) controls the freshness threshold in `CacheStatusService`
- The `SOCRATA_SYNC_SCHEDULE` env var overrides the default `crontab(hour=2, minute=0, day_of_week='sunday')` schedule

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "2.2", "2.3", "2.4"] },
    { "id": 1, "tasks": ["2.5", "3.1"] },
    { "id": 2, "tasks": ["5.1", "6.1", "8.1"] },
    { "id": 3, "tasks": ["5.2", "5.3", "5.4", "6.2"] },
    { "id": 4, "tasks": ["5.5", "5.6", "6.3"] },
    { "id": 5, "tasks": ["5.7"] },
    { "id": 6, "tasks": ["5.8", "5.9", "6.4"] },
    { "id": 7, "tasks": ["9.1", "10.1"] },
    { "id": 8, "tasks": ["9.2", "10.2", "11.1"] },
    { "id": 9, "tasks": ["11.2", "11.3", "11.4"] },
    { "id": 10, "tasks": ["11.5", "13.1"] },
    { "id": 11, "tasks": ["13.2", "13.3", "13.4", "13.5", "13.6", "13.7", "13.8", "13.9", "13.10", "13.11", "13.12", "13.13", "13.14", "13.15", "13.16", "13.17", "13.18", "14.1"] },
    { "id": 12, "tasks": ["15.1", "16.1", "17.1"] }
  ]
}
```
