"""Smoke tests for DuPage lead database migration idempotency.

Tests that both migrations run twice without error, and that all
expected columns and indexes exist after both runs.

Migrations covered:
  - x3y4z5a6b7c8_add_dupage_lead_columns.py
    * source_type, tax_distress_data, manual_priority on leads
    * ix_leads_source_type
    * ix_leads_owner_user_id_source_type
  - y4z5a6b7c8d9_add_import_job_source_type.py
    * source_type on import_jobs

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5

Design note
-----------
The conftest ``app`` fixture uses SQLite in-memory with ``db.create_all()``,
so all columns from the current models already exist when tests run.
The idempotency check therefore tests that running the schema-change SQL
a *second* time (against a DB that already has those columns/indexes) does
NOT raise an error — exactly the guarantee the ``IF NOT EXISTS`` / column
guard pattern provides.

SQLite limitations vs PostgreSQL:
  - No ``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` (SQLite only supports
    plain ``ADD COLUMN``; it raises if the column already exists).
  - No ``JSONB`` type (SQLite uses a plain text column for JSON).
  - ``CREATE INDEX IF NOT EXISTS`` *is* supported by SQLite.

The idempotency helper functions below mirror each migration's intent
using SQLite-compatible SQL so tests can run against the in-memory test DB.
They guard column addition with a PRAGMA column-existence check and use
``CREATE INDEX IF NOT EXISTS`` for indexes, matching the production
``IF NOT EXISTS`` semantics exactly.
"""
import pytest
import sqlalchemy as sa
from app import db


# ---------------------------------------------------------------------------
# SQLite-compatible upgrade helpers
# ---------------------------------------------------------------------------

def _column_exists(conn, table: str, column: str) -> bool:
    """Return True if *column* is present in *table* (SQLite PRAGMA)."""
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def _index_exists(conn, table: str, index_name: str) -> bool:
    """Return True if *index_name* exists on *table* (SQLite PRAGMA)."""
    rows = conn.execute(sa.text(f"PRAGMA index_list({table})")).fetchall()
    return any(row[1] == index_name for row in rows)


def run_add_dupage_lead_columns(conn) -> None:
    """SQLite-compatible version of x3y4z5a6b7c8 upgrade().

    Adds source_type, tax_distress_data, manual_priority to the leads
    table when they are absent, and creates both indexes if they do not
    already exist.  Safe to call multiple times.
    """
    if not _column_exists(conn, 'leads', 'source_type'):
        conn.execute(sa.text("ALTER TABLE leads ADD COLUMN source_type VARCHAR(50)"))

    if not _column_exists(conn, 'leads', 'tax_distress_data'):
        # SQLite has no JSONB — use TEXT (same semantics for test purposes)
        conn.execute(sa.text("ALTER TABLE leads ADD COLUMN tax_distress_data TEXT"))

    if not _column_exists(conn, 'leads', 'manual_priority'):
        conn.execute(sa.text("ALTER TABLE leads ADD COLUMN manual_priority INTEGER"))

    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_leads_source_type "
        "ON leads(source_type)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_leads_owner_user_id_source_type "
        "ON leads(owner_user_id, source_type)"
    ))


def run_add_import_job_source_type(conn) -> None:
    """SQLite-compatible version of y4z5a6b7c8d9 upgrade().

    Adds source_type to import_jobs when absent.  Safe to call multiple
    times.
    """
    if not _column_exists(conn, 'import_jobs', 'source_type'):
        conn.execute(sa.text(
            "ALTER TABLE import_jobs ADD COLUMN source_type VARCHAR(50)"
        ))


# ---------------------------------------------------------------------------
# Test: migration 1 — add_dupage_lead_columns
# ---------------------------------------------------------------------------

class TestAddDupageLeadColumnsMigrationIdempotency:
    """Running the add_dupage_lead_columns migration twice must not raise."""

    def test_first_run_succeeds(self, app):
        """First run of the migration completes without error."""
        with app.app_context():
            conn = db.session.connection()
            # Should not raise even though db.create_all() already added columns
            run_add_dupage_lead_columns(conn)

    def test_second_run_does_not_raise(self, app):
        """Second run on an already-migrated DB does not raise an error."""
        with app.app_context():
            conn = db.session.connection()
            run_add_dupage_lead_columns(conn)   # first run
            run_add_dupage_lead_columns(conn)   # second run — must not raise

    def test_source_type_column_exists_after_both_runs(self, app):
        """source_type column is present on leads after two upgrade runs."""
        with app.app_context():
            conn = db.session.connection()
            run_add_dupage_lead_columns(conn)
            run_add_dupage_lead_columns(conn)
            assert _column_exists(conn, 'leads', 'source_type'), (
                "source_type column missing from leads table"
            )

    def test_tax_distress_data_column_exists_after_both_runs(self, app):
        """tax_distress_data column is present on leads after two upgrade runs."""
        with app.app_context():
            conn = db.session.connection()
            run_add_dupage_lead_columns(conn)
            run_add_dupage_lead_columns(conn)
            assert _column_exists(conn, 'leads', 'tax_distress_data'), (
                "tax_distress_data column missing from leads table"
            )

    def test_manual_priority_column_exists_after_both_runs(self, app):
        """manual_priority column is present on leads after two upgrade runs."""
        with app.app_context():
            conn = db.session.connection()
            run_add_dupage_lead_columns(conn)
            run_add_dupage_lead_columns(conn)
            assert _column_exists(conn, 'leads', 'manual_priority'), (
                "manual_priority column missing from leads table"
            )

    def test_ix_leads_source_type_index_exists_after_both_runs(self, app):
        """ix_leads_source_type index exists on leads after two upgrade runs."""
        with app.app_context():
            conn = db.session.connection()
            run_add_dupage_lead_columns(conn)
            run_add_dupage_lead_columns(conn)
            assert _index_exists(conn, 'leads', 'ix_leads_source_type'), (
                "ix_leads_source_type index missing from leads table"
            )

    def test_ix_leads_owner_user_id_source_type_index_exists_after_both_runs(self, app):
        """ix_leads_owner_user_id_source_type index exists on leads after two runs."""
        with app.app_context():
            conn = db.session.connection()
            run_add_dupage_lead_columns(conn)
            run_add_dupage_lead_columns(conn)
            assert _index_exists(
                conn, 'leads', 'ix_leads_owner_user_id_source_type'
            ), (
                "ix_leads_owner_user_id_source_type index missing from leads table"
            )

    def test_all_three_columns_and_both_indexes_present(self, app):
        """All three columns and both indexes are present after two upgrade runs."""
        with app.app_context():
            conn = db.session.connection()
            run_add_dupage_lead_columns(conn)
            run_add_dupage_lead_columns(conn)

            assert _column_exists(conn, 'leads', 'source_type')
            assert _column_exists(conn, 'leads', 'tax_distress_data')
            assert _column_exists(conn, 'leads', 'manual_priority')
            assert _index_exists(conn, 'leads', 'ix_leads_source_type')
            assert _index_exists(conn, 'leads', 'ix_leads_owner_user_id_source_type')


# ---------------------------------------------------------------------------
# Test: migration 2 — add_import_job_source_type
# ---------------------------------------------------------------------------

class TestAddImportJobSourceTypeMigrationIdempotency:
    """Running the add_import_job_source_type migration twice must not raise."""

    def test_first_run_succeeds(self, app):
        """First run of the import_jobs migration completes without error."""
        with app.app_context():
            conn = db.session.connection()
            run_add_import_job_source_type(conn)

    def test_second_run_does_not_raise(self, app):
        """Second run on an already-migrated DB does not raise an error."""
        with app.app_context():
            conn = db.session.connection()
            run_add_import_job_source_type(conn)
            run_add_import_job_source_type(conn)

    def test_source_type_column_exists_after_both_runs(self, app):
        """source_type column is present on import_jobs after two upgrade runs."""
        with app.app_context():
            conn = db.session.connection()
            run_add_import_job_source_type(conn)
            run_add_import_job_source_type(conn)
            assert _column_exists(conn, 'import_jobs', 'source_type'), (
                "source_type column missing from import_jobs table"
            )


# ---------------------------------------------------------------------------
# Test: combined — both migrations run in sequence twice each
# ---------------------------------------------------------------------------

class TestBothMigrationsSequentialIdempotency:
    """Run both migrations in order twice; verify all schema changes persist."""

    def test_both_migrations_twice_no_error(self, app):
        """Running both migrations twice in sequence does not raise."""
        with app.app_context():
            conn = db.session.connection()
            # Run 1
            run_add_dupage_lead_columns(conn)
            run_add_import_job_source_type(conn)
            # Run 2
            run_add_dupage_lead_columns(conn)
            run_add_import_job_source_type(conn)

    def test_all_expected_schema_present_after_two_passes(self, app):
        """After running both migrations twice, all expected columns/indexes exist."""
        with app.app_context():
            conn = db.session.connection()
            # Pass 1
            run_add_dupage_lead_columns(conn)
            run_add_import_job_source_type(conn)
            # Pass 2
            run_add_dupage_lead_columns(conn)
            run_add_import_job_source_type(conn)

            # leads columns
            assert _column_exists(conn, 'leads', 'source_type'), \
                "leads.source_type missing (Requirement 10.1)"
            assert _column_exists(conn, 'leads', 'tax_distress_data'), \
                "leads.tax_distress_data missing (Requirement 10.2)"
            assert _column_exists(conn, 'leads', 'manual_priority'), \
                "leads.manual_priority missing (Requirement 10.3)"

            # leads indexes
            assert _index_exists(conn, 'leads', 'ix_leads_source_type'), \
                "ix_leads_source_type missing (Requirement 10.4)"
            assert _index_exists(conn, 'leads', 'ix_leads_owner_user_id_source_type'), \
                "ix_leads_owner_user_id_source_type missing (Requirement 10.5)"

            # import_jobs column
            assert _column_exists(conn, 'import_jobs', 'source_type'), \
                "import_jobs.source_type missing (Requirement 9.1)"

    def test_data_survives_second_migration_pass(self, app):
        """Existing lead data is unaffected by running migrations a second time."""
        from app.models.lead import Property

        with app.app_context():
            conn = db.session.connection()
            # Pass 1 — migrate schema
            run_add_dupage_lead_columns(conn)
            run_add_import_job_source_type(conn)

            # Insert a lead via the ORM so all NOT NULL server defaults are
            # satisfied automatically.
            lead = Property(
                property_street="123 Test St",
                source_type="foreclosure",
                manual_priority=3,
            )
            db.session.add(lead)
            db.session.flush()  # write to DB within the same connection/transaction
            lead_id = lead.id

            # Pass 2 — running migrations again must not touch existing data
            run_add_dupage_lead_columns(conn)
            run_add_import_job_source_type(conn)

            row = conn.execute(
                sa.text(
                    "SELECT source_type, manual_priority FROM leads WHERE id = :lid"
                ),
                {"lid": lead_id},
            ).fetchone()
            assert row is not None, "Lead row was deleted by second migration run"
            assert row[0] == "foreclosure", (
                f"source_type was overwritten: expected 'foreclosure', got {row[0]!r}"
            )
            assert row[1] == 3, (
                f"manual_priority was overwritten: expected 3, got {row[1]!r}"
            )
