# Implementation Plan: Cloud Database Migration

## Overview

Add four startup validation guards to `create_app()` in `backend/app/__init__.py`, update `backend/.env.example` with cloud-format placeholders, and write property-based and example-based tests covering all nine correctness properties. No models, controllers, services, or migration files need to change — this is purely application hardening and configuration.

## Tasks

- [x] 1. Update `backend/.env.example` with cloud-format DATABASE_URL and PROVIDER_DASHBOARD_URL
  - Replace the existing `DATABASE_URL` line with a commented cloud-format example (`postgresql://<username>:<password>@<host>:<port>/<database>?sslmode=require`) and keep the localhost fallback as a separate comment
  - Add a commented `PROVIDER_DASHBOARD_URL` placeholder line
  - Ensure no real credentials, hostnames, or database names appear anywhere in the file
  - _Requirements: 2.6, 7.7_

- [x] 2. Implement Guard 1 — `_validate_and_log_database_url()` in `backend/app/__init__.py`
  - [x] 2.1 Write `_validate_and_log_database_url(app)` helper function
    - Parse `DATABASE_URL` from `os.getenv`; raise `SystemExit(1)` if absent or empty, logging an error containing the string `"DATABASE_URL"`
    - Use `urllib.parse.urlparse` to validate the scheme is `postgresql` or `postgres`; raise `SystemExit(1)` with a log message containing `"DATABASE_URL"` for any other scheme
    - Build a credential-redacted safe host string (`scheme://hostname:port/dbname`) and log it at INFO level
    - _Requirements: 7.8, 8.1, 8.2_

  - [x] 2.2 Write property test for DATABASE_URL passthrough (Property 1)
    - **Property 1: DATABASE_URL Passthrough**
    - **Validates: Requirements 2.1, 2.2**
    - Use `hypothesis.strategies` to generate valid PostgreSQL URL strings with varying host, port, database name, user, and SSL params
    - For each generated URL, set `DATABASE_URL` in the environment, call `create_app('testing')` with a mocked DB connection, and assert `app.config['SQLALCHEMY_DATABASE_URI'] == DATABASE_URL`
    - Tag with comment: `# Feature: cloud-database-migration, Property 1: DATABASE_URL Passthrough`

  - [x] 2.3 Write property test for DATABASE_URL fallback (Property 2)
    - **Property 2: DATABASE_URL Fallback**
    - **Validates: Requirements 2.7**
    - With `DATABASE_URL` unset, call `create_app('testing')` and assert `SQLALCHEMY_DATABASE_URI == 'postgresql://localhost/real_estate_analysis'`
    - Tag with comment: `# Feature: cloud-database-migration, Property 2: DATABASE_URL Fallback`

  - [x] 2.4 Write property test for invalid DATABASE_URL causing startup abort (Property 5)
    - **Property 5: Invalid DATABASE_URL Causes Startup Abort**
    - **Validates: Requirements 7.8, 8.2**
    - Use Hypothesis to generate strings that are empty, non-URL, or use non-PostgreSQL schemes (e.g. `mysql://`, `sqlite://`, `http://`)
    - For each, set as `DATABASE_URL` and assert `SystemExit` is raised and the captured log output contains `"DATABASE_URL"`
    - Tag with comment: `# Feature: cloud-database-migration, Property 5: Invalid DATABASE_URL Causes Startup Abort`

  - [x] 2.5 Write property test for startup log credential redaction (Property 6)
    - **Property 6: Startup Log Redacts Credentials**
    - **Validates: Requirements 8.1**
    - Use Hypothesis to generate PostgreSQL URLs with arbitrary passwords (varying length, special characters)
    - For each, capture log output during `_validate_and_log_database_url` and assert the password string does not appear in any log line while the hostname does appear
    - Tag with comment: `# Feature: cloud-database-migration, Property 6: Startup Log Redacts Credentials`

- [x] 3. Implement Guard 2 — `_assert_pool_pre_ping()` in `backend/app/__init__.py`
  - [x] 3.1 Write `_assert_pool_pre_ping(app)` helper function
    - Return immediately if `app.config.get('TESTING')` is truthy
    - Read `app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {})` and raise `RuntimeError` if `pool_pre_ping` key is absent or falsy, with a message describing the missing setting
    - _Requirements: 8.4, 8.5_

  - [x] 3.2 Write property test for connection pool settings invariant (Property 3)
    - **Property 3: Connection Pool Settings Invariant**
    - **Validates: Requirements 2.5, 8.4, 8.5**
    - Use Hypothesis to generate arbitrary non-testing config name strings
    - For each, call `create_app(config_name)` with a mocked DB and assert `SQLALCHEMY_ENGINE_OPTIONS` contains `pool_size=3`, `max_overflow=0`, `pool_pre_ping=True`, and `pool_timeout=30`
    - Tag with comment: `# Feature: cloud-database-migration, Property 3: Connection Pool Settings Invariant`

- [x] 4. Implement Guard 3 — `_assert_not_superuser()` in `backend/app/__init__.py`
  - [x] 4.1 Write `_assert_not_superuser(app)` helper function
    - Skip (return) if `SQLALCHEMY_DATABASE_URI` does not contain `postgresql` (SQLite in tests)
    - Execute `SELECT usesuper FROM pg_user WHERE usename = current_user` via `db.session.execute`
    - If the result row has `usesuper=True`, raise `SystemExit` with a message identifying the superuser violation and instructing the operator to create a least-privilege application user
    - Catch all non-`SystemExit` exceptions and log a warning (do not abort startup on query failure)
    - _Requirements: 7.4, 7.5_

  - [x] 4.2 Write property test for superuser startup rejection (Property 4)
    - **Property 4: Superuser Startup Rejection**
    - **Validates: Requirements 7.4, 7.5**
    - Mock `db.session.execute` to return a row with `usesuper=True`; use Hypothesis to vary the DATABASE_URL and username
    - Assert `SystemExit` is raised during `_assert_not_superuser` for every generated input
    - Tag with comment: `# Feature: cloud-database-migration, Property 4: Superuser Startup Rejection`

- [x] 5. Implement Guard 4 — `_warn_provider_dashboard()` in `backend/app/__init__.py`
  - [x] 5.1 Write `_warn_provider_dashboard(app)` helper function
    - Read `PROVIDER_DASHBOARD_URL` from `os.getenv`
    - If set and non-empty, log a WARNING containing the URL
    - If absent or empty, log a WARNING instructing the operator to set `PROVIDER_DASHBOARD_URL` in `backend/.env`
    - _Requirements: 8.3_

- [x] 6. Wire all four guards into `create_app()` in `backend/app/__init__.py`
  - [x] 6.1 Call `_validate_and_log_database_url(app)` early in `create_app()`, before `db.init_app(app)`
    - Place the call after `app.config['SQLALCHEMY_DATABASE_URI']` is set so the URL is available for logging
    - _Requirements: 7.8, 8.1, 8.2_

  - [x] 6.2 Call `_assert_pool_pre_ping(app)` after the engine options block in `create_app()`
    - Place the call after the `if config_name == 'testing': ... else: ...` block that sets `SQLALCHEMY_ENGINE_OPTIONS`
    - _Requirements: 8.4, 8.5_

  - [x] 6.3 Call `_assert_not_superuser(app)` inside the `effective_env == 'development'` block, after `_assert_enum_values_match_db(app)`
    - Only runs in development mode against a real PostgreSQL instance; skipped automatically in tests via the SQLite check inside the function
    - _Requirements: 7.4, 7.5_

  - [x] 6.4 Call `_warn_provider_dashboard(app)` inside the `effective_env == 'development'` block alongside `_warn_missing_optional_keys(app)`
    - _Requirements: 8.3_

- [x] 7. Checkpoint — Ensure all tests pass
  - Run `cd backend && pytest` and confirm no regressions in the existing test suite
  - Confirm the four new guard functions are importable and the app starts cleanly with `config_name='testing'`
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Write property-based tests for remaining correctness properties
  - [x] 8.1 Write property test for multiple Alembic heads error message (Property 7)
    - **Property 7: Multiple Alembic Heads Error Contains Revision IDs**
    - **Validates: Requirements 4.5**
    - Use Hypothesis to generate sets of 2–5 arbitrary hex-like revision ID strings
    - Mock `ScriptDirectory.get_heads()` to return each generated set
    - Assert the `SystemExit` message raised by `_assert_single_migration_head` contains every revision ID in the set
    - Tag with comment: `# Feature: cloud-database-migration, Property 7: Multiple Alembic Heads Error Contains Revision IDs`

  - [x] 8.2 Write property test for migration idempotency (Property 8)
    - **Property 8: Migration Idempotency**
    - **Validates: Requirements 4.2**
    - For each migration file in `backend/alembic_migrations/versions/`, run `upgrade()` twice against a fresh SQLite test database
    - Assert no exception is raised on the second run and the schema state (table names, column names) is identical after both runs
    - Tag with comment: `# Feature: cloud-database-migration, Property 8: Migration Idempotency`

  - [x] 8.3 Write property test for connection pool budget (Property 9)
    - **Property 9: Connection Pool Budget**
    - **Validates: Requirements 6.5**
    - Use Hypothesis to generate combinations of process counts (1–10 Flask workers, 1–8 Celery threads, 0–1 Beat processes)
    - For each combination, compute `total = sum(pool_size * count)` with `pool_size=3`, `max_overflow=0`
    - Assert `total <= max_connections` where `max_connections` is the cloud DB's configured limit (use 100 as the conservative default for all major managed providers)
    - Tag with comment: `# Feature: cloud-database-migration, Property 9: Connection Pool Budget`

- [x] 9. Write example-based unit tests for startup behaviors
  - [x] 9.1 Write example-based tests for `.env.example` and `.gitignore` correctness
    - Assert `backend/.env.example` contains a commented cloud-format `DATABASE_URL` line with `sslmode=require`
    - Assert `backend/.env.example` contains a `PROVIDER_DASHBOARD_URL` placeholder line
    - Assert `backend/.env.example` does not contain any real hostnames, passwords, or database names (no `@` in uncommented `DATABASE_URL` lines)
    - Assert `backend/.gitignore` or root `.gitignore` includes `backend/.env`
    - _Requirements: 2.6, 7.1, 7.2, 7.7_

  - [x] 9.2 Write example-based tests for Guard 1 edge cases
    - Test: `DATABASE_URL` set to a valid `postgresql://` URL → app starts, INFO log contains hostname, no password in log
    - Test: `DATABASE_URL` set to `postgres://` scheme → app starts (both schemes accepted)
    - Test: `DATABASE_URL` absent → `SystemExit` raised, log contains `"DATABASE_URL"`
    - Test: `DATABASE_URL` set to `mysql://host/db` → `SystemExit` raised, log contains `"DATABASE_URL"`
    - _Requirements: 7.8, 8.1, 8.2_

  - [x] 9.3 Write example-based tests for Guard 2 edge cases
    - Test: `config_name='testing'` with `pool_pre_ping` absent → no `RuntimeError` (guard skipped)
    - Test: `config_name='development'` with `pool_pre_ping=True` → no `RuntimeError`
    - Test: `config_name='development'` with `pool_pre_ping` absent from engine options → `RuntimeError` raised
    - _Requirements: 8.4, 8.5_

  - [x] 9.4 Write example-based tests for Guard 4 (provider dashboard warning)
    - Test: `PROVIDER_DASHBOARD_URL` set → WARNING log contains the URL
    - Test: `PROVIDER_DASHBOARD_URL` absent → WARNING log contains `"PROVIDER_DASHBOARD_URL"`
    - _Requirements: 8.3_

- [x] 10. Final checkpoint — Ensure all tests pass
  - Run `cd backend && pytest` and confirm the full test suite passes with no regressions
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Guards 1–4 are pure helper functions; they do not touch models, services, or controllers
- Property tests use `hypothesis` (already in `requirements.txt` as `hypothesis==6.92.1`)
- All property tests must be tagged with `# Feature: cloud-database-migration, Property N: <text>`
- Guard 3 (`_assert_not_superuser`) only executes against PostgreSQL; it self-skips on SQLite so the existing test suite is unaffected
- The operational runbook is already complete in `design.md` — no code tasks are needed for it

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1", "5.1"] },
    { "id": 2, "tasks": ["6.1", "6.2", "6.3", "6.4"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.4", "2.5", "3.2", "4.2", "8.1", "8.2", "8.3", "9.1", "9.2", "9.3", "9.4"] }
  ]
}
```
