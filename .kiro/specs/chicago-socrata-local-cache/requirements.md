# Requirements Document

## Introduction

This feature adds a local PostgreSQL mirror of three Cook County Socrata datasets — Parcel Universe (pabr-t5kh), Parcel Sales (wvhk-k5uv), and Improvement Characteristics (bcnq-qi2z) — to the B and B Real Estate Analyzer platform. The local mirror eliminates live Socrata HTTP calls at comparable-search time, replacing them with indexed PostgreSQL queries. A Celery Beat scheduled task keeps the local copy fresh on a configurable cadence (weekly or monthly). The existing `CookCountySalesDataSource` is updated to query the local cache instead of the Socrata API, with an optional fallback to the live API when the cache is empty or stale.

## Glossary

- **Cache_Loader**: The Celery task responsible for performing the initial bulk load and scheduled refresh of all three Socrata datasets into PostgreSQL.
- **Cache_Status_Service**: The backend service that tracks the state of each dataset table (row count, last sync timestamp, staleness).
- **CookCountySalesDataSource**: The existing service class in `comparable_sales_finder.py` that fetches comparable sales data. After this feature, it queries the local cache tables instead of the Socrata API.
- **Dataset**: One of the three Cook County Socrata datasets being mirrored: Parcel Universe, Parcel Sales, or Improvement Characteristics.
- **Improvement_Characteristics_Cache**: The PostgreSQL table mirroring the Improvement Characteristics dataset (bcnq-qi2z), storing building attributes per PIN.
- **Parcel_Sales_Cache**: The PostgreSQL table mirroring the Parcel Sales dataset (wvhk-k5uv), storing sale transactions per PIN.
- **Parcel_Universe_Cache**: The PostgreSQL table mirroring the Parcel Universe dataset (pabr-t5kh), storing latitude/longitude per PIN.
- **PIN**: A 14-digit Cook County parcel identification number that uniquely identifies a parcel.
- **Socrata_API**: The Cook County open data portal REST API at `datacatalog.cookcountyil.gov`, the authoritative source for all three datasets.
- **Sync_Job**: A single execution of the Cache_Loader task for one or all datasets.
- **Sync_Log**: The PostgreSQL table that records the outcome of each Sync_Job (dataset name, start time, end time, rows upserted, status, error message).

---

## Requirements

### Requirement 1: Local Cache Tables

**User Story:** As a developer, I want the three Cook County datasets stored in PostgreSQL tables, so that comparable search queries can run against the local database without making HTTP calls to the Socrata API.

#### Acceptance Criteria

1. THE System SHALL create a `parcel_universe_cache` table with columns: `pin` (VARCHAR primary key), `lat` (NUMERIC), `lon` (NUMERIC), `last_synced_at` (TIMESTAMP WITH TIME ZONE).
2. THE System SHALL create a `parcel_sales_cache` table with columns: `id` (SERIAL primary key), `pin` (VARCHAR), `sale_date` (DATE), `sale_price` (NUMERIC), `class` (VARCHAR), `sale_type` (VARCHAR), `is_multisale` (BOOLEAN), `sale_filter_less_than_10k` (BOOLEAN), `sale_filter_deed_type` (BOOLEAN), `last_synced_at` (TIMESTAMP WITH TIME ZONE).
3. THE System SHALL create an `improvement_characteristics_cache` table with columns: `pin` (VARCHAR primary key), `bldg_sf` (INTEGER), `beds` (INTEGER), `fbath` (NUMERIC), `hbath` (NUMERIC), `age` (INTEGER), `ext_wall` (INTEGER), `apts` (INTEGER), `last_synced_at` (TIMESTAMP WITH TIME ZONE).
4. THE System SHALL create a `sync_log` table with columns: `id` (SERIAL primary key), `dataset_name` (VARCHAR), `started_at` (TIMESTAMP WITH TIME ZONE), `completed_at` (TIMESTAMP WITH TIME ZONE), `rows_upserted` (INTEGER), `status` (VARCHAR constrained to exactly `running`, `success`, or `failed`), `error_message` (TEXT).
5. THE System SHALL create an Alembic migration that adds all four tables to the existing PostgreSQL schema without issuing any ALTER or DROP statements on pre-existing tables, and SHALL include a downgrade function that drops the four new tables and their indexes.
6. THE System SHALL create a composite index on `parcel_sales_cache(pin, sale_date)` to support the PIN-filtered, date-range queries used by comparable search.
7. THE System SHALL create an index on `parcel_sales_cache(sale_date)` to support date-range scans during sync and staleness checks.
8. WHEN a row is upserted into `parcel_universe_cache` or `improvement_characteristics_cache` with a `pin` that already exists, THE System SHALL overwrite all non-primary-key columns with the new values.

---

### Requirement 2: Initial Bulk Load

**User Story:** As a developer, I want a one-time bulk load task that pulls all records from each Socrata dataset into the local cache tables, so that the cache is populated before the first comparable search runs.

#### Acceptance Criteria

1. WHEN the Cache_Loader task is invoked with `mode='full'`, THE Cache_Loader SHALL fetch all records from the Socrata_API for the specified dataset using paginated requests with a configurable page size between 1 and 100,000 rows (default: 50,000), stopping pagination when a page returns fewer rows than the requested page size.
2. WHEN a page of records is fetched from the Socrata_API, THE Cache_Loader SHALL upsert those records into the corresponding cache table using `INSERT ... ON CONFLICT (pin) DO UPDATE`.
3. WHEN the bulk load for a dataset completes successfully, THE Cache_Loader SHALL write one `sync_log` row per dataset with `status='success'`, `rows_upserted` equal to the total count of upserted rows for that dataset, and `completed_at` set to the current UTC timestamp.
4. IF the Socrata_API returns an HTTP error during a bulk load page fetch, THEN THE Cache_Loader SHALL retry the request up to 3 times with a 5-second wait between attempts before treating the page as failed.
5. IF all retry attempts for a page fail, THEN THE Cache_Loader SHALL log the error, write a `sync_log` row with `status='failed'`, `rows_upserted` reflecting the count of rows successfully upserted before the failure, and an `error_message` that includes the failed page offset, and SHALL stop processing that dataset without truncating any previously loaded rows.
6. WHEN the Cache_Loader is invoked with `dataset='all'`, THE Cache_Loader SHALL load all three datasets sequentially and write a separate `sync_log` row for each dataset.
7. WHEN loading Parcel_Sales_Cache, THE Cache_Loader SHALL fetch only records where `sale_type='LAND AND BUILDING'` to limit storage to relevant sales records.

---

### Requirement 3: Scheduled Incremental Refresh

**User Story:** As a developer, I want a Celery Beat scheduled task that refreshes the local cache on a configurable cadence, so that the local data stays reasonably current without manual intervention.

#### Acceptance Criteria

1. THE System SHALL register a Celery Beat periodic task named `socrata_cache.refresh` that runs on a configurable schedule (default: weekly, every Sunday at 02:00 UTC).
2. WHEN the `socrata_cache.refresh` task runs, THE Cache_Loader SHALL fetch records from the Socrata_API modified since the `completed_at` timestamp of the most recent successful `sync_log` row for each configured dataset.
3. WHEN no prior successful sync exists for a dataset, THE Cache_Loader SHALL perform a full load for that dataset instead of an incremental refresh.
4. WHEN an incremental refresh completes successfully, THE Cache_Loader SHALL upsert the fetched records and update the `sync_log` with the count of records upserted and the completion timestamp.
5. IF the Socrata_API is unreachable or returns a non-retryable HTTP error (4xx/5xx) during a scheduled refresh, THEN THE Cache_Loader SHALL log the failure, write a `sync_log` row with `status='failed'`, and leave the existing cache data intact without partial modification.
6. IF the `SOCRATA_SYNC_SCHEDULE` environment variable is set, THEN THE System SHALL use its value to override the default Celery Beat cron schedule for the refresh task.
7. IF the `SOCRATA_SYNC_SCHEDULE` environment variable is set to an invalid cron expression, THEN THE System SHALL refuse to start the Celery worker and emit an error message identifying the invalid value.

---

### Requirement 4: Cache-Backed Comparable Search

**User Story:** As a real estate analyst, I want comparable search to query the local PostgreSQL cache instead of the Socrata API, so that comparable searches complete in under one second without network latency or rate-limit risk.

#### Acceptance Criteria

1. WHEN `CookCountySalesDataSource.fetch_comparables` is called and the Parcel_Universe_Cache table contains at least one row, THE CookCountySalesDataSource SHALL execute the bounding-box PIN lookup against `parcel_universe_cache` instead of the Socrata_API.
2. WHEN `CookCountySalesDataSource.fetch_comparables` is called and the Parcel_Sales_Cache table contains at least one row, THE CookCountySalesDataSource SHALL execute the PIN-filtered sales query against `parcel_sales_cache` instead of the Socrata_API.
3. WHEN `CookCountySalesDataSource.fetch_comparables` is called and the Improvement_Characteristics_Cache table contains at least one row, THE CookCountySalesDataSource SHALL execute the improvement characteristics lookup against `improvement_characteristics_cache` instead of the Socrata_API.
4. IF a cache table is empty, THEN THE CookCountySalesDataSource SHALL fall back to the live Socrata_API for that specific dataset only, log a warning that includes the name of the empty table, and continue using the local cache for any non-empty tables.
5. WHEN querying `parcel_universe_cache` for a bounding box, THE CookCountySalesDataSource SHALL use a parameterized SQL query with `lat BETWEEN :min_lat AND :max_lat AND lon BETWEEN :min_lon AND :max_lon`.
6. WHEN querying `parcel_sales_cache` for a list of PINs, THE CookCountySalesDataSource SHALL use a parameterized SQL query with `pin = ANY(:pins)` to avoid SQL injection and eliminate the 100-PIN batch loop required by the Socrata URL-length limit.
7. THE CookCountySalesDataSource SHALL return the same named output fields (`pin`, `sale_date`, `sale_price`, `class`, `latitude`, `longitude`, and all improvement characteristics) regardless of whether data comes from the local cache or the live Socrata_API, with absent fields represented as `null` rather than omitted from the response.
8. WHEN `CookCountySalesDataSource.fetch_comparables` is called and all three cache tables are non-empty, THE CookCountySalesDataSource SHALL complete the full comparable fetch in under 1000 milliseconds as measured from method entry to return.

---

### Requirement 5: Cache Status API

**User Story:** As a developer, I want a REST endpoint that reports the current state of each cache table, so that I can monitor sync health and trigger manual refreshes without connecting directly to the database.

#### Acceptance Criteria

1. THE System SHALL expose a `GET /api/cache/socrata/status` endpoint that returns a JSON object with one entry per dataset containing: `dataset_name`, `row_count`, `last_synced_at` (ISO 8601 string or null), `status` (one of `empty`, `fresh`, `stale`, `never_synced`), and `last_error` (string or null).
2. WHEN the most recent successful sync for a dataset occurred more than 30 days ago and the table contains at least one row, THE Cache_Status_Service SHALL report `status='stale'` for that dataset.
3. WHEN a dataset table contains at least one row and the most recent successful sync occurred within the last 30 days, THE Cache_Status_Service SHALL report `status='fresh'` for that dataset.
4. WHEN a dataset table contains zero rows, THE Cache_Status_Service SHALL report `status='empty'` for that dataset regardless of sync history.
5. WHEN a dataset table contains zero rows and no sync has ever been attempted, THE Cache_Status_Service SHALL report `status='never_synced'` for that dataset.
6. THE System SHALL expose a `POST /api/cache/socrata/sync` endpoint that enqueues a Cache_Loader Celery task for the dataset(s) specified in the request body (`{"dataset": "all" | "parcel_universe" | "parcel_sales" | "improvement_characteristics"}`).
7. WHEN a sync task is successfully enqueued, THE System SHALL return HTTP 202 with a JSON body containing `{"task_id": "<celery_task_id>", "dataset": "<dataset_name>"}`.
8. IF an invalid dataset name is provided to `POST /api/cache/socrata/sync`, THEN THE System SHALL return HTTP 400 with an error message that identifies the invalid value and lists the accepted values.
9. IF the request body is missing or not valid JSON on `POST /api/cache/socrata/sync`, THEN THE System SHALL return HTTP 400 with a descriptive error message.

---

### Requirement 6: Schema Drift Resilience

**User Story:** As a developer, I want the cache loader to handle unexpected fields from the Socrata API gracefully, so that a schema change in the upstream dataset does not crash the sync job or break comparable search.

#### Acceptance Criteria

1. WHEN the Socrata_API returns a row containing fields not present in the cache table schema, THE Cache_Loader SHALL ignore the extra fields and insert only the columns defined in the cache table.
2. WHEN the Socrata_API returns a row where an expected nullable column is missing, THE Cache_Loader SHALL insert `NULL` for that column rather than raising an exception.
3. IF a type conversion error occurs while mapping a Socrata field value to its PostgreSQL column type, THEN THE Cache_Loader SHALL log a warning with the PIN and field name, insert `NULL` for that field, and continue processing the remaining rows in the page.
4. WHEN the total number of columns returned by the Socrata_API for a dataset differs from the count of columns defined in the cache table schema, THE Cache_Loader SHALL log a warning identifying the dataset and the column count discrepancy so that schema drift is detectable without causing a failure.
5. IF a missing or type-conversion-failed field maps to a NOT NULL column in the cache table schema, THEN THE Cache_Loader SHALL skip that row entirely, log a warning with the PIN and column name, and continue processing the remaining rows in the page.

---

### Requirement 7: Round-Trip Data Integrity

**User Story:** As a developer, I want to verify that data written to the cache tables can be read back with the same values, so that the cache does not silently corrupt comparable search inputs.

#### Acceptance Criteria

1. WHEN a row with a 14-character PIN, a NUMERIC `lat`, and a NUMERIC `lon` is written to `parcel_universe_cache` and then read back by that PIN, THE System SHALL return the exact same `pin`, `lat`, and `lon` values with no numeric coercion or precision loss.
2. WHEN a row is written to `parcel_sales_cache` and then read back by `(pin, sale_date)`, THE System SHALL return the exact same `sale_price`, `class`, `is_multisale`, `sale_filter_less_than_10k`, and `sale_filter_deed_type` values with no coercion or precision loss.
3. WHEN a row is written to `improvement_characteristics_cache` and then read back by its PIN, THE System SHALL return the exact same `bldg_sf`, `beds`, `fbath`, `hbath`, `age`, `ext_wall`, and `apts` values with no numeric coercion or precision loss.
4. WHEN a PIN is upserted into a cache table with updated values and the upsert transaction has committed, THE System SHALL return the updated values for all stored columns on the next read of that PIN.
5. WHEN a row containing a NULL value for a nullable column is written to a cache table and then read back, THE System SHALL return NULL for that column rather than a default or coerced value.
