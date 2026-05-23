# Requirements Document

## Introduction

This feature migrates the B&B Real Estate Analysis Platform's database from a local PostgreSQL instance (`postgresql://localhost/real_estate_analysis`) to a hosted, cloud-based PostgreSQL service. The migration enables multiple team members and end users to access a shared, live database concurrently, eliminates the single-machine dependency, and establishes a redundant automated backup strategy to prevent catastrophic data loss.

The platform uses Flask-SQLAlchemy with Alembic migrations and a Celery/Redis task queue. The migration must preserve all existing schema, data, and migration history while requiring minimal changes to application code — primarily a `DATABASE_URL` swap in `backend/.env`.

## Glossary

- **Application**: The B&B Real Estate Analysis Platform (Flask backend + React frontend).
- **Cloud_Database**: The hosted PostgreSQL instance running on a managed cloud provider (e.g., Supabase, Neon, Railway, AWS RDS, or equivalent).
- **Local_Database**: The current PostgreSQL instance running on `localhost`.
- **DATABASE_URL**: The connection string environment variable read by the Application from `backend/.env`, used by Flask-SQLAlchemy to connect to the database.
- **Migration_Script**: An Alembic migration file stored in `backend/alembic_migrations/`.
- **Connection_Pool**: The SQLAlchemy connection pool configured in `create_app()` (`pool_size=3`, `max_overflow=0`).
- **Backup**: A point-in-time snapshot of the Cloud_Database that can be used to restore data.
- **Backup_Retention_Window**: The period for which Backups are retained and restorable.
- **Team_Member**: A developer or operator with credentials to access the Cloud_Database directly (e.g., via a database client or admin panel).
- **End_User**: A person accessing the Application through the web interface.
- **Data_Export**: A `pg_dump`-format file containing the full schema and data of the Local_Database.
- **SSL**: Transport Layer Security used to encrypt connections between the Application and the Cloud_Database.

---

## Requirements

### Requirement 1: Cloud Database Provisioning

**User Story:** As a team member, I want the database hosted on a managed cloud provider, so that all team members and end users can connect to a single shared database without needing a local PostgreSQL instance.

#### Acceptance Criteria

1. THE Cloud_Database SHALL be a PostgreSQL instance (version 14 or higher) hosted on a managed cloud provider.
2. THE Cloud_Database SHALL be accessible over the public internet via a hostname and port using standard PostgreSQL wire protocol.
3. THE Cloud_Database SHALL support a minimum of 10 concurrent connections to accommodate the Application's Connection_Pool across multiple processes (Flask + Celery worker + Celery Beat).
4. IF a connection attempt originates from an IP address not on the configured allowlist, THEN THE Cloud_Database SHALL refuse the connection before the PostgreSQL authentication handshake begins.
5. THE Cloud_Database SHALL refuse non-SSL connection attempts; any connection that does not present a valid TLS handshake SHALL be terminated before authentication.
6. IF a connection attempt presents invalid credentials, THEN THE Cloud_Database SHALL refuse the connection with an authentication error and SHALL NOT grant any database access.

---

### Requirement 2: Application Configuration Update

**User Story:** As a developer, I want the Application to connect to the Cloud_Database via an environment variable, so that no code changes are required and local development can still use a local database by overriding the variable.

#### Acceptance Criteria

1. THE Application SHALL read the database connection string exclusively from the `DATABASE_URL` environment variable defined in `backend/.env`.
2. WHEN `DATABASE_URL` is set to a connection string whose host is not `localhost` or `127.0.0.1`, THE Application SHALL connect to the Cloud_Database without any code changes beyond the `.env` file.
3. IF the `DATABASE_URL` connection string includes SSL parameters (e.g., `?sslmode=require`), THEN THE Application SHALL negotiate an SSL connection to the Cloud_Database before executing any queries.
4. IF the SSL handshake fails, THEN THE Application SHALL refuse to start, SHALL log an error message that includes the word "SSL" and the target host, and SHALL NOT retry the connection without SSL.
5. THE Application SHALL maintain the existing Connection_Pool configuration (`pool_size=3`, `max_overflow=0`, `pool_pre_ping=True`, `pool_timeout=30`) when connecting to the Cloud_Database.
6. THE `backend/.env.example` file SHALL be updated to include a commented example of a cloud-format `DATABASE_URL` with SSL parameters.
7. IF `DATABASE_URL` is not set, THEN THE Application SHALL fall back to `postgresql://localhost/real_estate_analysis` to preserve local development behavior.
8. THE Application SHALL NOT attempt to connect to any database through any means other than the `DATABASE_URL` environment variable.

---

### Requirement 3: Data Migration from Local to Cloud

**User Story:** As a team member, I want all existing data migrated from the local database to the cloud database, so that no historical leads, analysis sessions, or configuration data is lost during the transition.

#### Acceptance Criteria

1. WHEN the migration is performed, THE Data_Export SHALL contain the complete schema and all rows from the Local_Database at the time of export, verified by a row count that equals the Local_Database row count for every table.
2. WHEN the Data_Export is loaded into the Cloud_Database, THE Cloud_Database SHALL contain all tables, indexes, sequences, enum types, and constraints present in the Local_Database.
3. WHEN the Data_Export is loaded into the Cloud_Database, THE Cloud_Database SHALL contain the Alembic version table (`alembic_version`) with the current head revision, so that no Migration_Scripts are re-applied.
4. WHEN the Application is started against the Cloud_Database after the data load, THE Application SHALL respond to a health-check HTTP request with status 200 within 30 seconds and SHALL report zero pending Alembic migrations.
5. WHEN the test suite is run after the data load, THE Application SHALL pass all tests that passed against the Local_Database schema (using the test SQLite configuration, not the live cloud DB), with no regression in the pass count.
6. IF the Data_Export load fails or is interrupted, THEN THE Cloud_Database SHALL be rolled back to its pre-load state and THE team SHALL be notified of the failure before any Application traffic is redirected to the Cloud_Database.

---

### Requirement 4: Schema Migration Compatibility

**User Story:** As a developer, I want future Alembic migrations to apply cleanly to the Cloud_Database, so that schema changes can be deployed without manual intervention.

#### Acceptance Criteria

1. WHEN `flask db upgrade head` is run against the Cloud_Database, THE Migration_Script chain SHALL apply without errors.
2. WHEN a Migration_Script is run against the Cloud_Database a second time, THE Migration_Script SHALL complete without errors and SHALL NOT alter the schema state produced by the first run.
3. WHEN the Application starts with `DEBUG=True` against the Cloud_Database, THE Application SHALL automatically apply any pending migrations before accepting any requests.
4. IF the `upgrade()` call raises an exception during startup, THEN THE Application SHALL log the exception and SHALL abort startup without accepting any requests.
5. IF the Cloud_Database has multiple Alembic heads, THEN THE Application SHALL raise a startup error whose message includes the conflicting revision identifiers and SHALL NOT continue starting up.

---

### Requirement 5: Automated Backup Strategy

**User Story:** As a team member, I want the cloud database to be backed up automatically and redundantly, so that a hardware failure, accidental deletion, or data corruption event does not result in catastrophic data loss.

#### Acceptance Criteria

1. THE Cloud_Database SHALL be configured with automated daily backups retained for a minimum of 7 days (Backup_Retention_Window).
2. THE Cloud_Database SHALL support point-in-time recovery (PITR) within the Backup_Retention_Window with a recovery granularity of no greater than 5 minutes, allowing restoration to any 5-minute interval within the last 7 days.
3. THE Cloud_Database provider SHALL store Backups in a geographically redundant location — explicitly a different physical data center or availability zone than the primary database instance, not merely a different rack or storage volume within the same facility.
4. WHEN a Backup is triggered (automatically or manually), THE Cloud_Database provider SHALL update a status indicator in the provider's admin console or API that distinguishes between a successfully completed Backup and a failed or incomplete Backup.
5. IF a scheduled Backup fails, THEN THE Cloud_Database provider SHALL notify the team via email or an equivalent alerting channel within 24 hours of the failure.
6. THE project's operational runbook or README SHALL contain a restore procedure that includes: (a) the commands or UI steps required to initiate a restore from a Backup, and (b) the steps to verify that the restored database is consistent and accessible to the Application.

---

### Requirement 6: Multi-User Concurrent Access

**User Story:** As an end user, I want my requests to be processed correctly even when other users are simultaneously using the platform, so that concurrent usage does not cause data corruption or errors.

#### Acceptance Criteria

1. WHILE multiple End_Users are submitting requests simultaneously, THE Application SHALL process each request in an isolated database transaction, preventing dirty reads and lost updates.
2. THE Cloud_Database SHALL be configured to use `READ COMMITTED` isolation level for all Application connections.
3. WHEN two concurrent requests attempt to modify the same row, THE Cloud_Database SHALL serialize the writes using row-level locking, ensuring that one write completes and is committed before the other proceeds.
4. WHEN a write is blocked by a row-level lock and the lock is not released within the Application's configured statement timeout, THE Application SHALL roll back the blocked transaction and SHALL return a retryable error response (HTTP 409 or 503) to the caller rather than silently dropping the write.
5. THE Application's Connection_Pool SHALL limit total connections to the Cloud_Database to a value within the Cloud_Database's `max_connections` limit, accounting for all running processes (Flask, Celery worker, Celery Beat).
6. WHEN the Connection_Pool is exhausted, THE Application SHALL wait up to 30 seconds for a free connection; IF no connection becomes available within 30 seconds, THEN THE Application SHALL return a 503 error to the caller, consistent with the existing `pool_timeout=30` setting.

---

### Requirement 7: Security and Credential Management

**User Story:** As a team member, I want database credentials stored securely and never committed to version control, so that the cloud database is not exposed to unauthorized access.

#### Acceptance Criteria

1. THE `DATABASE_URL` (including username, password, host, and database name) SHALL be stored exclusively in `backend/.env` and SHALL NOT be committed to the git repository.
2. THE `.gitignore` file SHALL include `backend/.env` to prevent accidental credential commits.
3. THE Cloud_Database SHALL require password authentication for all connections; anonymous or trust-based connections SHALL NOT be permitted.
4. THE Application SHALL NOT use a superuser account for database connections under any circumstances, including initial setup and emergency situations.
5. IF the Application's configured database user has superuser privileges, THEN THE Application SHALL refuse to perform any database operations and SHALL emit a startup error identifying the superuser violation.
6. WHERE the cloud provider supports it, THE team SHALL create a dedicated database user for the Application with the minimum required privileges (SELECT, INSERT, UPDATE, DELETE, and schema modification for migrations) rather than using a superuser account.
7. THE `backend/.env.example` file SHALL contain a placeholder `DATABASE_URL` in the format `postgresql://<username>:<password>@<host>/<database>?sslmode=require` and SHALL NOT contain any real credentials, hostnames, or database names.
8. IF `DATABASE_URL` is absent from the environment or is not a valid PostgreSQL connection string, THEN THE Application SHALL log an error identifying `DATABASE_URL` as the missing or malformed variable and SHALL abort startup.

---

### Requirement 8: Operational Observability

**User Story:** As a team member, I want visibility into database connection health and query performance, so that I can detect and diagnose issues before they affect end users.

#### Acceptance Criteria

1. WHEN the Application starts, THE Application SHALL log the resolved database host (with credentials redacted) so that operators can confirm which database instance is in use.
2. WHEN a database connection attempt fails at startup, THE Application SHALL log an error message that includes the unreachable host and the text "`DATABASE_URL`", and SHALL exit with a non-zero status code.
3. WHERE the cloud provider offers a query performance dashboard or slow-query log, THE Application SHALL log a warning at startup indicating that the performance dashboard is available and identifying the provider's admin URL.
4. WHEN `TESTING` is not `True`, THE Application SHALL enforce `pool_pre_ping=True` in the SQLAlchemy engine options in `create_app()` so that stale connections are detected and recycled before use.
5. IF `pool_pre_ping` is absent from the engine options when `TESTING` is not `True`, THEN THE Application SHALL raise a `RuntimeError` during startup before accepting any requests.
