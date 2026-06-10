# Implementation Plan: Migration System Simplification

## Overview

This plan moves the migration system to a single, deployable, verifiable contract using Python/Flask, Alembic via Flask-Migrate, and the existing CI on PostgreSQL 15. The work is additive to the Alembic chain (clean-baseline/squash strategy) and never rewrites the body, revision id, or down-revision of a revision already applied to production, except where the design explicitly requires making the fragile `267725fe7017` revision fresh-DB-safe via guarded, idempotent SQL.

Tasks build incrementally: first a non-blocking app factory so migration commands run at all, then a reusable chain validator, then the consolidation revisions that make a fresh PostgreSQL upgrade succeed, then the static linter, CI hardening, and documentation. Each step wires into the prior one — the validator is invoked by the upgrade guard, the new revisions are gated by the linter, and CI runs the validator and the fresh-DB round-trip end to end.

Because the design intentionally omits a Correctness Properties section (this is migration/infrastructure work over a fixed chain and fixed model set), testing uses integration tests (against real PostgreSQL 15), example/unit tests, and parametrized static checks rather than property-based tests. All test sub-tasks are marked optional with `*`.

## Tasks

- [x] 1. Make the application factory non-blocking for migration commands
  - [x] 1.1 Add a `ConfigurationError` exception and migration-context detection
    - Add `ConfigurationError(RealEstateAnalysisException)` to `backend/app/exceptions.py`
    - Add a helper in `backend/app/__init__.py` (e.g. `_is_migration_context()`) that detects a migration/CLI invocation via `FLASK_APP`/Flask CLI context or an explicit `KIRO_MIGRATION` / `FLASK_DB_COMMAND` env guard
    - _Requirements: 5.4_

  - [x] 1.2 Replace process-terminating guards and the auto-upgrade side effect
    - In `create_app()`, replace the `SECRET_KEY` `SystemExit`, `_validate_and_log_database_url` `SystemExit(1)`, and `_assert_not_superuser` `SystemExit` paths with a logged error plus a raised `ConfigurationError`/`RuntimeError` whose message is preserved in command output (no `SystemExit`)
    - Gate the development-only auto-`upgrade()` block and `_assert_single_migration_head` call so neither runs when `_is_migration_context()` is true
    - Bound the Redis ping in `_warn_missing_optional_keys` with a short socket timeout and skip it in the migration context
    - Ensure construction performs no destructive DB work, does not reconfigure logging to redirect/swallow stdout, and does not block on input/prompts
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 1.3 Write unit tests for the non-blocking app factory
    - Assert `create_app()` in a migration context returns an app, raises no `SystemExit`, performs no auto-`upgrade()`, does no destructive DB work, and completes within 5 seconds
    - Assert missing required config raises `ConfigurationError` with the originating message preserved (not `SystemExit`)
    - Assert app construction does not redirect/swallow stdout
    - Update `tests/test_cloud_database_migration.py` guard tests that currently expect `SystemExit` to reflect the new `ConfigurationError`/`RuntimeError` behavior
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 2. Build the single-root / single-head chain validator
  - [x] 2.1 Refactor head detection into a reusable structured validator
    - Refactor `_assert_single_migration_head` in `backend/app/__init__.py` into `assert_single_head_and_root()` returning `head_count`, `head_revisions`, `root_count`, `root_revisions`
    - The validator MUST NOT call `SystemExit`; callers decide how to surface failures
    - Tolerate historical tuple `down_revision` merge revisions while computing the current head count
    - _Requirements: 1.5, 7.1, 7.4, 7.5_

  - [x] 2.2 Create the CLI/CI chain-check entry point
    - Add `backend/scripts/check_migration_chain.py` that calls the validator, prints the detected head count, root count, and each offending revision id, and exits non-zero when either count is not exactly 1
    - _Requirements: 1.6, 7.2, 7.3_

  - [x] 2.3 Add the pre-upgrade guard to the migration path
    - Invoke `assert_single_head_and_root()` in `backend/alembic_migrations/env.py` before any revision is applied; on violation, halt with the chain unchanged, emit a single-root/single-head error, and exit non-zero
    - Add an unrecognized-start-revision guard that halts before any schema change when the recorded revision is absent from the documented baseline-replacement mapping (see Task 7.2)
    - _Requirements: 1.6, 7.1, 9.5_

  - [x] 2.4 Write tests for the chain validator and guards
    - Assert exactly one `down_revision = None`, exactly one head, and a non-null single predecessor for every non-merge revision
    - Assert `check_migration_chain.py` exits non-zero and names offending revisions when head/root count != 1
    - Assert the unrecognized-start-revision guard halts with schema and recorded revision unchanged
    - _Requirements: 1.5, 1.6, 7.1, 7.3, 7.4, 7.5, 9.5_

- [x] 3. Add the clean-baseline consolidation revisions
  - [x] 3.1 Add the model-alignment revision
    - Create a new revision in `backend/alembic_migrations/versions/` that converts enum types (`propertytype`, `constructiontype`, `interiorcondition`, `workflowstep`, `scenariotype`) and column types to the model-aligned form using guarded, conditional raw SQL that is a no-op when the target type already matches, so fresh and existing databases converge to the same end state
    - Follow the idempotency convention: `IF NOT EXISTS`, `DO $$ ... EXCEPTION WHEN duplicate_object`, no `batch_alter_table`, and a matching `downgrade()` with `DROP ... IF EXISTS`
    - Ensure the baseline creates all objects without referencing pre-existing types/tables, and that the `users` table and FKs referencing it are correctly ordered
    - _Requirements: 2.5, 4.4, 4.5, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 3.2 Make `267725fe7017_baseline_schema` fresh-DB-safe
    - Convert the fragile retype/cast statements in `267725fe7017_baseline_schema.py` to guarded, conditional raw SQL (using `pg_type` / `information_schema` checks) so the revision is a safe no-op on a fresh database and remains idempotent on existing databases, without changing its revision id or down-revision pointer
    - Remove any `batch_alter_table` usage on PostgreSQL in this revision per the convention
    - _Requirements: 2.5, 8.5, 8.7, 8.8, 9.1_

  - [x] 3.3 Add the squash/marker head revision
    - Create a new revision whose `down_revision` points at the current single head, producing exactly one head; thin/empty `upgrade()`/`downgrade()`
    - Host the baseline-replacement mapping reference in its docstring
    - _Requirements: 1.5, 7.1, 7.4, 7.5_

  - [x] 3.4 Write integration tests for fresh-database upgrade (PostgreSQL 15)
    - Against a fresh PostgreSQL database: `flask db upgrade` exits 0, records the head, and a schema diff against the models reports zero differences
    - Assert the upgrade succeeds with `backend/migrations/*.sql` never read or applied
    - Assert the `users` table matches the `User` model (columns, constraints, indexes) exactly
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 3.1, 3.2, 3.3, 4.2_

  - [x] 3.5 Write integration tests for round-trip and idempotency (PostgreSQL 15)
    - Full upgrade then `downgrade base` leaves zero chain-created tables and zero chain-created enum types (exit 0)
    - Upgrade → downgrade base → upgrade reaches head (exit 0) with a final schema identical to a direct fresh upgrade
    - Running upgrade twice leaves the schema identical and exits 0 both times
    - After simulating a partially-applied migration, re-running completes remaining statements with no duplicate-object errors
    - _Requirements: 2.6, 8.7, 8.8, 10.1, 10.2, 10.3, 10.5_

- [x] 4. Checkpoint - Ensure migration upgrade and round-trip pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Extend the migration idempotency linter
  - [x] 5.1 Add idempotency rules to the linter
    - Extend `backend/scripts/lint_migrations.py` to flag as errors in new baseline/consolidation revisions: `op.create_table`, `op.create_index`, `op.add_column`, any PostgreSQL `batch_alter_table`, enum creation without an `EXCEPTION WHEN duplicate_object` guard, and any `upgrade()` lacking a corresponding `downgrade()` using `DROP ... IF EXISTS`
    - Keep `_INITIAL_SCHEMA_TABLES` synchronized with the baseline
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 5.2 Write tests for the extended linter
    - Assert the linter fails on each forbidden pattern and passes on convention-compliant revisions
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 6. Harden the CI pipeline for the production engine
  - [x] 6.1 Update the backend CI job in `.github/workflows/ci.yml`
    - Run `python scripts/check_migration_chain.py` (head + root gate) before the upgrade smoke test; fail and report counts/revisions on violation
    - Target a fresh `migration_test_db` that pytest never touches, on PostgreSQL 15 matching production, with no SQLite substitution for migration validation
    - Wrap `flask db upgrade` with a 300-second timeout (`timeout 300 flask db upgrade`); terminate and fail on timeout
    - Add a round-trip step: `flask db upgrade` → `flask db downgrade base` → `flask db upgrade`, asserting exit 0 and a final complete schema
    - On any non-zero exit, fail the run, do not mark passed, surface the failing revision and error output, and block merge on PRs to `main`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.2, 7.3, 10.2, 10.3, 10.5_

- [x] 7. Document the single authoritative schema source and clean-baseline strategy
  - [x] 7.1 Mark the raw SQL files non-authoritative
    - Add/replace `backend/migrations/README` with a notice identifying `001_create_schema.sql`, `002_lead_management.sql`, `003_add_lead_category.sql` as non-authoritative historical reference not applied during deployment
    - _Requirements: 1.4, 3.3_

  - [x] 7.2 Document the baseline-replacement mapping and stamp path
    - Create the consolidation mapping (in `backend/alembic_migrations/README` or a new `MIGRATIONS.md`) listing, by revision id, every baseline revision and every prior revision it replaces, with no unmapped pre-consolidation revision remaining
    - Document the exact `flask db stamp <revision>` command, the assumed starting revision, and that stamping changes only the recorded revision and applies no schema changes
    - Document the unrecognized-starting-revision halt behavior consumed by the guard in Task 2.3
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 7.3 Update the deployment runbook
    - Update the deploy docs/runbook so the documented schema step is only `flask db upgrade`, with no `psql`, no raw SQL files, and no manual statement
    - _Requirements: 3.4, 3.5_

  - [x] 7.4 Write a test asserting the mapping covers all revisions
    - Assert every pre-consolidation revision appears in exactly one `replaces` entry and that an unrecognized recorded revision triggers the documented halt
    - _Requirements: 9.2, 9.3, 9.5_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- Each task references specific requirement clauses for traceability.
- This feature has no Correctness Properties section in the design, so there are no property-based test tasks; correctness is validated through PostgreSQL integration tests, unit tests, and parametrized static checks.
- Checkpoints ensure incremental validation against a real PostgreSQL 15 database.
- All new and modified revisions must follow `.kiro/steering/migrations.md` (raw SQL with `IF NOT EXISTS`, enum guards, no `batch_alter_table`, `DROP ... IF EXISTS` downgrades).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "5.1", "7.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "5.2", "7.3"] },
    { "id": 2, "tasks": ["1.3", "2.2", "3.1", "3.2", "3.3"] },
    { "id": 3, "tasks": ["2.3", "7.2"] },
    { "id": 4, "tasks": ["2.4", "3.4", "3.5", "6.1", "7.4"] }
  ]
}
```
