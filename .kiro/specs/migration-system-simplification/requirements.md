# Requirements Document

## Introduction

The database migration system has accumulated structural debt that makes every deploy unpredictable. The schema is currently split between three raw SQL files in `backend/migrations/` (applied manually, outside Alembic) and an Alembic chain in `backend/alembic_migrations/` that assumes those raw SQL files have already run. The Alembic chain has two root revisions (`000000000000_initial_schema` and `267725fe7017_baseline_schema`); the second renames enum types and casts array/JSONB columns in a way that only succeeds from a specific already-mutated dev database state and fails on a fresh database. The `users` table is not represented in any migration. `create_app()` performs blocking and process-terminating startup work (`SystemExit` guards plus an auto-`upgrade()`) that aborts `flask db upgrade` before it produces output. Local and CI tests run against SQLite in-memory, so PostgreSQL-specific migration failures (named enum types, array/JSONB casts) are never caught before production.

This feature simplifies the migration system toward a single, deployable, verifiable contract: **one authoritative schema source, a chain that runs cleanly on a fresh PostgreSQL database with zero manual SQL steps, an application factory that does not block or terminate migration commands, and CI that validates the same database engine and migration path that production uses.** The work must remain consistent with the existing idempotency convention in `.kiro/steering/migrations.md`, including reconciling that convention's "do not rewrite existing migration files" rule with the consolidation goal through an explicit clean-baseline (squash) strategy.

## Glossary

- **Migration_System**: The complete set of components that define and apply database schema changes — the Alembic migration scripts in `backend/alembic_migrations/`, the Alembic configuration, and the commands that run them.
- **Migration_Chain**: The ordered, linked sequence of Alembic revision files, each referencing its predecessor via `down_revision`, terminating in exactly one head revision.
- **Baseline_Migration**: A single Alembic revision with `down_revision = None` that creates the complete schema as it must exist before any subsequent revision runs.
- **Fresh_Database**: A PostgreSQL database that contains no application tables, enum types, or Alembic version history at the time migrations begin.
- **Schema_Source**: The single authoritative definition of the database schema from which deployments are built.
- **App_Factory**: The `create_app()` function in `backend/app/__init__.py` that constructs and configures the Flask application.
- **CI_Pipeline**: The automated workflow defined in `.github/workflows/ci.yml` that runs on pull requests and pushes to `main`.
- **Migration_Command**: The `flask db upgrade` command (and related Flask-Migrate / Alembic commands) used to apply migrations.
- **Idempotency_Convention**: The migration authoring rules defined in `.kiro/steering/migrations.md` (raw SQL with `IF NOT EXISTS`, enum creation guarded by `EXCEPTION WHEN duplicate_object`, no `batch_alter_table` on PostgreSQL, and `DROP ... IF EXISTS` downgrades).
- **Raw_SQL_Files**: The files `001_create_schema.sql`, `002_lead_management.sql`, and `003_add_lead_category.sql` in `backend/migrations/`.
- **Migration_Head**: A revision in the Migration_Chain that no other revision references as its `down_revision`.
- **Users_Table**: The `users` table backing application authentication and ownership relationships.

## Requirements

### Requirement 1: Single Authoritative Schema Source

**User Story:** As a developer deploying the application, I want one authoritative source of schema truth, so that I do not have to reconcile raw SQL files against the Alembic chain to know the correct schema.

#### Acceptance Criteria

1. WHEN all Alembic revision files in `backend/alembic_migrations/` are applied in chain order to an empty database, THE Migration_System SHALL produce the complete database schema such that every table, column, index, constraint, and enum type required by the application's SQLAlchemy models is present, with zero remaining schema differences when the resulting database is compared against the models.
2. WHEN the complete schema is produced by applying the Alembic revision files in `backend/alembic_migrations/` to an empty database, THE Migration_System SHALL require zero files from `backend/migrations/` to be applied, and the resulting schema SHALL be complete with no missing tables, columns, indexes, constraints, or enum types.
3. WHERE Raw_SQL_Files are retained in the repository, THE Migration_System SHALL exclude them from the deployment path such that no deployment or migration command reads, applies, or depends on any file in `backend/migrations/`.
4. WHERE Raw_SQL_Files are retained in the repository, THE Migration_System SHALL provide a written notice in the repository identifying the files in `backend/migrations/` as non-authoritative historical reference that is not applied during deployment.
5. THE Migration_Chain SHALL contain exactly one revision with `down_revision = None`.
6. IF the Migration_Chain contains zero revisions or more than one revision with `down_revision = None`, THEN THE Migration_System SHALL halt without applying any revision and SHALL emit an error indicating that the single-root chain requirement is violated, leaving the target database schema unchanged.

### Requirement 2: Clean Fresh-Database Deployment

**User Story:** As an operator provisioning a new environment, I want migrations to run cleanly on a fresh database, so that I can stand up a new environment without depending on a prior database state.

#### Acceptance Criteria

1. WHEN the Migration_Command runs against a Fresh_Database, THE Migration_System SHALL apply every revision in the Migration_Chain in dependency order up to the single Migration_Head, record the Migration_Head as the current database revision, and exit with status code 0.
2. WHEN the Migration_Command runs against a Fresh_Database, THE Migration_System SHALL create every table, enum type, index, and constraint defined by the application models, such that a subsequent schema comparison against the application models reports zero pending differences.
3. IF a migration step encounters an error while running against a Fresh_Database, THEN THE Migration_System SHALL halt before applying any further revisions, write the failing revision identifier and the underlying error description to the command output, and exit with a non-zero status code.
4. IF a migration step fails while running against a Fresh_Database, THEN THE Migration_System SHALL leave the recorded current revision pointing at the last successfully applied revision and SHALL NOT advance the recorded revision to the failed revision.
5. THE Baseline_Migration SHALL create all of its schema objects without referencing or requiring any pre-existing enum type, column type, table, index, or constraint in the target database.
6. WHEN the Migration_Command runs a second time against a database whose recorded current revision already equals the Migration_Head, THE Migration_System SHALL apply zero additional revisions, make no changes to existing tables, enum types, indexes, or constraints, and exit with status code 0.

### Requirement 3: No Manual SQL Deployment Steps

**User Story:** As an operator, I want deployment to require no manual SQL execution, so that deploys are repeatable and not dependent on undocumented steps.

#### Acceptance Criteria

1. WHEN the Migration_Command is run against a Fresh_Database, THE Migration_System SHALL apply every defined migration in order and produce a schema containing all tables, columns, indexes, constraints, and enum types defined by the application's migration set, with no additional manual step required.
2. WHEN the Migration_Command completes against a Fresh_Database, THE Migration_System SHALL report a success indication (zero error exit status) and record the latest migration revision as the current database version.
3. THE Migration_System SHALL NOT require an operator to run `psql`, execute Raw_SQL_Files, or apply any manual SQL statement as part of a deployment.
4. IF the Migration_Command fails to apply any migration, THEN THE Migration_System SHALL halt with a non-zero error exit status, surface an error indication identifying the failing migration, and leave the database recoverable for a repeat run without manual SQL intervention.
5. THE deployment documentation SHALL specify the Migration_Command as the only schema step required to deploy, and SHALL NOT reference `psql`, Raw_SQL_Files, or any manual SQL statement as a required deployment step.

### Requirement 4: Users Table Represented in a Migration

**User Story:** As a developer, I want the users table created by a migration, so that authentication and ownership relationships exist on a freshly deployed database.

#### Acceptance Criteria

1. THE Migration_Chain SHALL include exactly one revision whose upgrade operation creates the Users_Table.
2. WHEN the Migration_Command runs to completion against a Fresh_Database, THE Migration_System SHALL create the Users_Table containing every column, constraint, and index defined on the application user model, such that the resulting table schema matches the user model definition with zero missing or extra columns, constraints, or indexes.
3. IF the Migration_Command runs against a Fresh_Database and any column, constraint, or index defined on the application user model is absent from the created Users_Table, THEN THE Migration_System SHALL halt the Migration_Command, leave the database in its pre-migration state, and return an error indicating which schema element could not be created.
4. WHERE a subsequent revision adds a column to the Users_Table, THE Migration_Chain SHALL order that revision so its down-revision dependency resolves, directly or transitively, to the revision that creates the Users_Table.
5. WHEN the Migration_Command runs to completion against a Fresh_Database, THE Migration_System SHALL create every foreign key that references the Users_Table only after the Users_Table and its primary key exist, such that no foreign key creation step executes before the Users_Table is present.
6. IF the Migration_Command runs against a Fresh_Database and a foreign key that references the Users_Table is created before the Users_Table exists, THEN THE Migration_System SHALL halt the Migration_Command, leave the database in its pre-migration state, and return an error indicating the unresolved Users_Table reference.

### Requirement 5: Non-Blocking Application Factory

**User Story:** As a developer running migration commands, I want the application factory to avoid blocking or process-terminating startup work, so that `flask db upgrade` produces output and completes.

#### Acceptance Criteria

1. WHEN the App_Factory is invoked to support a Migration_Command, THE App_Factory SHALL return a usable application instance and SHALL complete construction without invoking `SystemExit` or otherwise terminating the host process.
2. WHEN the App_Factory is invoked to support a Migration_Command, THE App_Factory SHALL NOT apply migrations as a startup side effect.
3. THE App_Factory SHALL NOT perform destructive database operations during construction.
4. IF a required configuration value is absent when the App_Factory is invoked, THEN THE App_Factory SHALL report the missing configuration through a logged error and a raised exception that preserves the originating message in the command output, and SHALL NOT terminate the host process via `SystemExit`.
5. WHEN the Migration_Command runs after the App_Factory completes construction, THE App_Factory SHALL NOT suppress or redirect the command's console output, so that the command's progress and completion messages are written to standard output.
6. WHEN the App_Factory is invoked to support a Migration_Command, THE App_Factory SHALL complete construction within 5 seconds and SHALL NOT block on input, prompts, or indefinite waits.

### Requirement 6: CI Validates the Production Database Engine

**User Story:** As a developer, I want CI to run migrations against PostgreSQL, so that PostgreSQL-specific migration failures are caught before they reach production.

#### Acceptance Criteria

1. WHEN the CI_Pipeline runs the Migration_Command, THE CI_Pipeline SHALL apply the Migration_Chain from the base (empty schema) through the latest Migration_Head against a PostgreSQL database whose major version matches the production PostgreSQL version.
2. WHEN the CI_Pipeline runs the Migration_Command, THE CI_Pipeline SHALL target a Fresh_Database that contains no application schema objects and that no test has created, modified, or seeded.
3. IF the Migration_Command exits with a non-success status code in the CI_Pipeline, THEN THE CI_Pipeline SHALL fail the run, SHALL NOT mark the run as passed, and SHALL report the failing revision identifier and error output.
4. WHEN the CI_Pipeline validates migrations, THE CI_Pipeline SHALL execute every revision against PostgreSQL with no SQLite substitution, so that PostgreSQL-specific constructs are exercised on PostgreSQL.
5. IF the Migration_Command does not complete within 300 seconds in the CI_Pipeline, THEN THE CI_Pipeline SHALL terminate the command and fail the run.
6. WHEN a pull request targets `main`, THE CI_Pipeline SHALL run the PostgreSQL migration validation and SHALL block the merge if the validation fails.

### Requirement 7: Single Linear Migration Head

**User Story:** As a developer, I want the migration chain to resolve to a single head, so that `flask db upgrade` reaches one unambiguous target without branch resolution.

#### Acceptance Criteria

1. WHEN the Migration_System computes the set of head revisions for the Migration_Chain, THE Migration_System SHALL resolve the Migration_Chain to exactly one Migration_Head (a count of 1).
2. WHEN the CI_Pipeline executes, THE CI_Pipeline SHALL validate that the Migration_Chain resolves to exactly one Migration_Head before any deployment step proceeds.
3. IF the Migration_Chain resolves to a head count other than 1 (zero heads or two or more heads), THEN THE CI_Pipeline SHALL fail the run, report the detected head count, and report each detected head revision identifier in the failure output.
4. THE Migration_System SHALL link every revision in the Migration_Chain other than the Baseline_Migration to exactly one immediate predecessor revision through a non-null `down_revision` value.
5. THE Migration_System SHALL define the Baseline_Migration with a `down_revision` value of null, identifying it as the single root of the Migration_Chain.

### Requirement 8: Consistency with the Idempotency Convention

**User Story:** As a developer authoring migrations, I want the simplified migrations to follow the established idempotency convention, so that partial-application failures remain recoverable.

#### Acceptance Criteria

1. WHERE a migration creates a table, THE Migration_System SHALL create it using a raw `CREATE TABLE IF NOT EXISTS` statement rather than the `op.create_table` DDL helper.
2. WHERE a migration creates an enum type, THE Migration_System SHALL guard creation with an `EXCEPTION WHEN duplicate_object` block so that re-creation does not raise an error.
3. WHERE a migration creates an index, THE Migration_System SHALL create it using a raw `CREATE INDEX IF NOT EXISTS` statement rather than the `op.create_index` DDL helper.
4. WHERE a migration adds a column, THE Migration_System SHALL add it using an `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` statement.
5. THE Migration_System SHALL NOT use `batch_alter_table` in any migration that targets PostgreSQL.
6. WHERE a migration defines an `upgrade` function, THE Migration_System SHALL define a corresponding `downgrade` function that reverses each object the upgrade created using `DROP ... IF EXISTS` statements.
7. WHEN a migration is applied twice in sequence against the same database, THE Migration_System SHALL leave the schema in a state identical to a single application and SHALL exit with a success status code on both runs.
8. WHEN a migration is re-run against a database where the migration was previously applied only partially, THE Migration_System SHALL complete the remaining statements and exit with a success status code without raising duplicate-object errors.

### Requirement 9: Clean-Baseline Strategy Reconciled with Existing Migrations

**User Story:** As a maintainer, I want the consolidation to reconcile with the "do not rewrite existing migration files" rule, so that production databases already at the current head are not broken by the simplification.

#### Acceptance Criteria

1. THE Migration_System SHALL consolidate the schema through a documented clean-baseline strategy that adds new revision files without modifying the body, revision identifier, or down-revision pointer of any revision file already applied to production.
2. WHERE a production database is recorded at any revision in the pre-consolidation chain, THE Migration_System SHALL provide a documented upgrade path that advances that database to the single Migration_Head while executing zero CREATE statements against database objects that already exist.
3. THE Migration_System SHALL maintain documentation that lists, by revision identifier, every revision constituting the consolidated baseline and every prior revision identifier each baseline revision replaces, such that the mapping accounts for all pre-consolidation revisions with no unmapped revision remaining.
4. IF the clean-baseline strategy stamps an existing database to a baseline revision, THEN THE Migration_System SHALL document the exact stamp command and the assumed starting revision identifier, AND THE Migration_System SHALL document that the stamp operation alters only the recorded revision and applies no schema changes.
5. IF an upgrade path is executed against a database whose recorded revision is not present in the documented baseline-replacement mapping, THEN THE Migration_System SHALL halt before applying any schema change and produce an error indicating the unrecognized starting revision, leaving the database schema and recorded revision unchanged.

### Requirement 10: Reversibility and Verifiable Round-Trip

**User Story:** As a developer, I want migrations to be reversible and verifiable, so that I can validate the chain in both directions and recover from a bad deploy.

#### Acceptance Criteria

1. WHEN the Migration_Command downgrades the Baseline_Migration on a database currently at the Baseline_Migration revision, THE Migration_System SHALL drop every schema object (tables, enum types, and indexes) that the Baseline_Migration created and SHALL exit with process exit code 0.
2. WHEN the Migration_System applies the full chain to the Migration_Head and then downgrades to the base revision on a Fresh_Database, THE Migration_System SHALL leave zero application tables and zero enum types that were created by the chain (downgrade round-trip).
3. WHEN the Migration_System applies the full chain, downgrades to the base revision, and re-applies the full chain on the same database, THE Migration_System SHALL reach the Migration_Head revision and SHALL exit with process exit code 0 (upgrade-downgrade-upgrade round-trip).
4. IF any downgrade step fails during a round-trip operation, THEN THE Migration_System SHALL halt at the failing revision, SHALL leave the schema objects of all not-yet-downgraded revisions intact, and SHALL exit with a non-zero process exit code and an error message identifying the failing revision.
5. WHEN the Migration_System completes the upgrade-downgrade-upgrade round-trip, THE Migration_System SHALL produce a final schema identical to the schema produced by applying the full chain directly to a Fresh_Database, with no residual tables, enum types, or indexes from the intermediate downgrade.
