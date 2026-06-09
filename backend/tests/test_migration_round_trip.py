"""
test_migration_round_trip.py — Integration tests for Alembic migration round-trip
and idempotency verification against a real PostgreSQL 15 database.

These tests are skipped unless the MIGRATION_TEST_DB_URL environment variable is
set to a valid PostgreSQL 15 connection URL pointing to a *clean* test database.
They MUST NOT run against the application database.

Usage (requires a real PostgreSQL 15 instance):

    export MIGRATION_TEST_DB_URL="postgresql://postgres:postgres@localhost:5432/migration_test"
    cd backend && pytest tests/test_migration_round_trip.py -v -m integration

Each test invokes ``flask db upgrade`` / ``flask db downgrade base`` as a
subprocess against the test database and inspects the result (exit code, schema
state) via direct psycopg2 queries.

Requirements: 2.6, 8.7, 8.8, 10.1, 10.2, 10.3, 10.5
"""
import os
import subprocess
import sys
import textwrap

import pytest
import psycopg2
import psycopg2.extras


# ---------------------------------------------------------------------------
# Skip guard — all tests in this module require a real PostgreSQL 15 database
# ---------------------------------------------------------------------------

MIGRATION_TEST_DB_URL = os.environ.get("MIGRATION_TEST_DB_URL")

pytestmark = pytest.mark.skipif(
    not MIGRATION_TEST_DB_URL,
    reason="MIGRATION_TEST_DB_URL not set — integration tests require a real PostgreSQL 15 database",
)

# Expected final head revision after a complete upgrade (squash/marker revision).
_EXPECTED_HEAD = "b3c4d5e6f7a1"

# Key application tables that must be created by the chain on upgrade
# and must be absent after a full downgrade to base.
_KEY_APPLICATION_TABLES = [
    "analysis_sessions",
    "leads",
    "users",
    "property_facts",
    "comparable_sales",
    "comparable_valuations",
    "ranked_comparables",
    "valuation_results",
    "scenarios",
]

# Enum types created by the chain (model-aligned names, lower-cased for pg_type).
_CHAIN_ENUM_TYPES = [
    "propertytype",
    "constructiontype",
    "interiorcondition",
    "workflowstep",
    "scenariotype",
]

# A mid-chain revision to stamp when simulating a partial application.
# Using the model-alignment revision; the squash-marker (b3c4d5e6f7a1) is
# left un-applied so re-running upgrade must complete it.
_MID_CHAIN_REVISION = "a2b3c4d5e6f7"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backend_dir() -> str:
    """Absolute path to the backend/ directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_flask_db(command: str, *, db_url: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a ``flask db <command>`` subprocess against *db_url*.

    Returns the CompletedProcess so callers can inspect returncode / output.
    The command runs with a copy of the current environment that has
    DATABASE_URL, FLASK_APP, KIRO_MIGRATION, and SECRET_KEY set.
    """
    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    env["FLASK_APP"] = "app"
    env["KIRO_MIGRATION"] = "1"
    # A dummy secret key is sufficient — migrations do not use session signing.
    env.setdefault("SECRET_KEY", "migration-test-secret-key")

    result = subprocess.run(
        [sys.executable, "-m", "flask", "db"] + command.split(),
        cwd=_backend_dir(),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def _connect(db_url: str):
    """Return a psycopg2 connection to *db_url* (autocommit=True)."""
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    return conn


def _get_tables(conn) -> set:
    """Return the set of non-system table names visible in information_schema."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            """
        )
        return {row[0] for row in cur.fetchall()}


def _get_enum_types(conn) -> set:
    """Return the set of custom enum type names in the public schema."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.typname
            FROM pg_type t
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE t.typtype = 'e'
              AND n.nspname = 'public'
            """
        )
        return {row[0] for row in cur.fetchall()}


def _get_alembic_head(conn) -> str | None:
    """Return the currently recorded Alembic revision, or None if no table/rows."""
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
            row = cur.fetchone()
            return row[0] if row else None
        except psycopg2.errors.UndefinedTable:
            return None


def _drop_all_tables(conn) -> None:
    """Drop every non-system table in the public schema (including alembic_version).

    Used to ensure the database is completely empty before a fresh-upgrade test.
    """
    # Disable FK checks temporarily via CASCADE
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            """
        )
        tables = [row[0] for row in cur.fetchall()]

    for table in tables:
        with conn.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')

    # Drop all enum types too
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.typname
            FROM pg_type t
            JOIN pg_namespace n ON n.oid = t.typnamespace
            WHERE t.typtype = 'e'
              AND n.nspname = 'public'
            """
        )
        enum_types = [row[0] for row in cur.fetchall()]

    for etype in enum_types:
        with conn.cursor() as cur:
            cur.execute(f'DROP TYPE IF EXISTS "{etype}" CASCADE')


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def clean_db():
    """Yield a clean (empty) test database URL.

    Drops all tables and enum types before and after each test so every test
    starts from a truly empty slate and leaves the database clean.
    """
    db_url = MIGRATION_TEST_DB_URL
    conn = _connect(db_url)
    try:
        _drop_all_tables(conn)
        yield db_url
    finally:
        _drop_all_tables(conn)
        conn.close()


# ---------------------------------------------------------------------------
# Test 1: test_downgrade_base_exits_zero
#
# Full upgrade then ``flask db downgrade base`` must exit 0.
# Requirements: 10.1, 10.2
# ---------------------------------------------------------------------------

class TestDowngradeBaseExitsZero:
    """Requirement 10.1 — downgrade to base exits with status code 0."""

    def test_downgrade_base_exits_zero(self, clean_db):
        """Upgrade then downgrade base; both commands must exit 0.

        Requirements: 10.1, 10.2
        """
        # Step 1: full upgrade
        result_up = _run_flask_db("upgrade", db_url=clean_db)
        assert result_up.returncode == 0, (
            f"flask db upgrade failed (exit {result_up.returncode}):\n"
            f"stdout: {result_up.stdout}\n"
            f"stderr: {result_up.stderr}"
        )

        # Step 2: downgrade to base
        result_down = _run_flask_db("downgrade base", db_url=clean_db)
        assert result_down.returncode == 0, (
            f"flask db downgrade base failed (exit {result_down.returncode}):\n"
            f"stdout: {result_down.stdout}\n"
            f"stderr: {result_down.stderr}"
        )


# ---------------------------------------------------------------------------
# Test 2: test_downgrade_removes_tables
#
# After downgrade base, key application tables must no longer exist.
# Requirements: 10.1, 10.2
# ---------------------------------------------------------------------------

class TestDowngradeRemovesTables:
    """Requirement 10.2 — downgrade to base leaves zero chain-created tables."""

    def test_downgrade_removes_tables(self, clean_db):
        """After upgrade then downgrade base, key tables must be absent.

        Verifies that the chain's downgrade() functions properly DROP all
        tables created during upgrade, leaving no residual application schema.

        Requirements: 10.1, 10.2
        """
        # Upgrade first
        result_up = _run_flask_db("upgrade", db_url=clean_db)
        assert result_up.returncode == 0, (
            f"Prerequisite upgrade failed (exit {result_up.returncode}):\n"
            f"stderr: {result_up.stderr}"
        )

        # Downgrade to base
        result_down = _run_flask_db("downgrade base", db_url=clean_db)
        assert result_down.returncode == 0, (
            f"flask db downgrade base failed (exit {result_down.returncode}):\n"
            f"stderr: {result_down.stderr}"
        )

        # Verify key application tables are gone
        conn = _connect(clean_db)
        try:
            remaining_tables = _get_tables(conn)
        finally:
            conn.close()

        residual = set(_KEY_APPLICATION_TABLES) & remaining_tables
        assert not residual, (
            f"These tables should have been dropped by downgrade base, "
            f"but are still present: {sorted(residual)}\n"
            f"Requirement 10.2: downgrade round-trip must leave zero "
            f"chain-created tables."
        )

    def test_downgrade_removes_enum_types(self, clean_db):
        """After upgrade then downgrade base, chain-created enum types must be absent.

        Requirements: 10.1, 10.2
        """
        # Upgrade first
        result_up = _run_flask_db("upgrade", db_url=clean_db)
        assert result_up.returncode == 0, (
            f"Prerequisite upgrade failed (exit {result_up.returncode}):\n"
            f"stderr: {result_up.stderr}"
        )

        # Downgrade to base
        result_down = _run_flask_db("downgrade base", db_url=clean_db)
        assert result_down.returncode == 0, (
            f"flask db downgrade base failed (exit {result_down.returncode}):\n"
            f"stderr: {result_down.stderr}"
        )

        # Verify enum types are gone
        conn = _connect(clean_db)
        try:
            remaining_enums = _get_enum_types(conn)
        finally:
            conn.close()

        residual_enums = set(_CHAIN_ENUM_TYPES) & remaining_enums
        assert not residual_enums, (
            f"These enum types should have been dropped by downgrade base, "
            f"but are still present: {sorted(residual_enums)}\n"
            f"Requirement 10.2: downgrade round-trip must leave zero "
            f"chain-created enum types."
        )


# ---------------------------------------------------------------------------
# Test 3: test_upgrade_downgrade_upgrade_round_trip
#
# upgrade → downgrade base → upgrade reaches head b3c4d5e6f7a1, exit 0.
# Requirements: 10.3, 10.5
# ---------------------------------------------------------------------------

class TestUpgradeDowngradeUpgradeRoundTrip:
    """Requirement 10.3, 10.5 — upgrade → downgrade → upgrade reaches the head."""

    def test_upgrade_downgrade_upgrade_round_trip(self, clean_db):
        """Three-step round-trip must reach head revision with exit 0.

        Steps:
          1. flask db upgrade   → exit 0, head = b3c4d5e6f7a1
          2. flask db downgrade base → exit 0
          3. flask db upgrade   → exit 0, head = b3c4d5e6f7a1

        The final schema must match a direct fresh upgrade (same tables,
        same enum types, same recorded revision).

        Requirements: 10.3, 10.5
        """
        # --- Step 1: initial upgrade ---
        result1 = _run_flask_db("upgrade", db_url=clean_db)
        assert result1.returncode == 0, (
            f"Step 1 (initial upgrade) failed (exit {result1.returncode}):\n"
            f"stderr: {result1.stderr}"
        )

        conn = _connect(clean_db)
        try:
            head_after_first_upgrade = _get_alembic_head(conn)
        finally:
            conn.close()

        assert head_after_first_upgrade == _EXPECTED_HEAD, (
            f"Expected head {_EXPECTED_HEAD!r} after first upgrade, "
            f"got {head_after_first_upgrade!r}"
        )

        # --- Step 2: downgrade to base ---
        result2 = _run_flask_db("downgrade base", db_url=clean_db)
        assert result2.returncode == 0, (
            f"Step 2 (downgrade base) failed (exit {result2.returncode}):\n"
            f"stderr: {result2.stderr}"
        )

        # --- Step 3: re-upgrade ---
        result3 = _run_flask_db("upgrade", db_url=clean_db)
        assert result3.returncode == 0, (
            f"Step 3 (re-upgrade after downgrade) failed (exit {result3.returncode}):\n"
            f"stdout: {result3.stdout}\n"
            f"stderr: {result3.stderr}"
        )

        # Verify head revision matches expected
        conn = _connect(clean_db)
        try:
            head_after_round_trip = _get_alembic_head(conn)
            final_tables = _get_tables(conn)
            final_enums = _get_enum_types(conn)
        finally:
            conn.close()

        assert head_after_round_trip == _EXPECTED_HEAD, (
            f"Expected head {_EXPECTED_HEAD!r} after round-trip upgrade, "
            f"got {head_after_round_trip!r}\n"
            f"Requirement 10.3: must reach Migration_Head after round-trip."
        )

        # Verify all key application tables are present
        missing_tables = set(_KEY_APPLICATION_TABLES) - final_tables
        assert not missing_tables, (
            f"Tables missing after round-trip upgrade: {sorted(missing_tables)}\n"
            f"Requirement 10.5: final schema must match a direct fresh upgrade."
        )

        # Verify all chain enum types are present
        missing_enums = set(_CHAIN_ENUM_TYPES) - final_enums
        assert not missing_enums, (
            f"Enum types missing after round-trip upgrade: {sorted(missing_enums)}\n"
            f"Requirement 10.5: no residual objects from intermediate downgrade."
        )


# ---------------------------------------------------------------------------
# Test 4: test_idempotent_upgrade
#
# Running ``flask db upgrade`` twice leaves the schema unchanged and exits 0
# on both runs.
# Requirements: 2.6, 8.7
# ---------------------------------------------------------------------------

class TestIdempotentUpgrade:
    """Requirements 2.6, 8.7 — upgrade twice leaves schema unchanged, both exit 0."""

    def test_idempotent_upgrade_both_runs_exit_zero(self, clean_db):
        """Both the first and second upgrade runs must exit 0.

        Requirements: 2.6, 8.7
        """
        # First run
        result1 = _run_flask_db("upgrade", db_url=clean_db)
        assert result1.returncode == 0, (
            f"First upgrade failed (exit {result1.returncode}):\n"
            f"stderr: {result1.stderr}"
        )

        # Second run (already at head — should be a no-op)
        result2 = _run_flask_db("upgrade", db_url=clean_db)
        assert result2.returncode == 0, (
            f"Second upgrade (idempotent re-run) failed (exit {result2.returncode}):\n"
            f"stdout: {result2.stdout}\n"
            f"stderr: {result2.stderr}\n"
            f"Requirement 8.7: re-running upgrade at head must exit 0."
        )

    def test_idempotent_upgrade_schema_unchanged_between_runs(self, clean_db):
        """Schema (tables and enum types) must be identical after both runs.

        Requirements: 2.6, 8.7
        """
        # First run
        result1 = _run_flask_db("upgrade", db_url=clean_db)
        assert result1.returncode == 0, (
            f"First upgrade failed (exit {result1.returncode}):\n"
            f"stderr: {result1.stderr}"
        )

        # Snapshot schema after first run
        conn = _connect(clean_db)
        try:
            tables_after_run1 = _get_tables(conn)
            enums_after_run1 = _get_enum_types(conn)
            head_after_run1 = _get_alembic_head(conn)
        finally:
            conn.close()

        # Second run
        result2 = _run_flask_db("upgrade", db_url=clean_db)
        assert result2.returncode == 0

        # Snapshot schema after second run
        conn = _connect(clean_db)
        try:
            tables_after_run2 = _get_tables(conn)
            enums_after_run2 = _get_enum_types(conn)
            head_after_run2 = _get_alembic_head(conn)
        finally:
            conn.close()

        # Tables must be identical
        assert tables_after_run1 == tables_after_run2, (
            f"Schema changed between first and second upgrade run.\n"
            f"Tables added on run 2: {tables_after_run2 - tables_after_run1}\n"
            f"Tables removed on run 2: {tables_after_run1 - tables_after_run2}\n"
            f"Requirement 8.7: upgrade twice must leave schema identical."
        )

        # Enum types must be identical
        assert enums_after_run1 == enums_after_run2, (
            f"Enum types changed between first and second upgrade run.\n"
            f"Added on run 2: {enums_after_run2 - enums_after_run1}\n"
            f"Removed on run 2: {enums_after_run1 - enums_after_run2}\n"
            f"Requirement 8.7: upgrade twice must leave schema identical."
        )

        # Head revision must be identical
        assert head_after_run1 == head_after_run2 == _EXPECTED_HEAD, (
            f"Recorded revision mismatch: run1={head_after_run1!r}, "
            f"run2={head_after_run2!r}, expected={_EXPECTED_HEAD!r}\n"
            f"Requirement 2.6: no new revisions applied on second run."
        )


# ---------------------------------------------------------------------------
# Test 5: test_partial_application_recovery
#
# Stamp the database to a mid-chain revision, then run upgrade.  The command
# must complete the remaining revisions with exit 0 and no duplicate-object errors.
# Requirements: 8.8
# ---------------------------------------------------------------------------

class TestPartialApplicationRecovery:
    """Requirement 8.8 — partial application is recovered by re-running upgrade."""

    def test_partial_application_recovery(self, clean_db):
        """Simulate a partial migration by stamping to a mid-chain revision.

        After stamping to ``{_MID_CHAIN_REVISION}`` (model_alignment), the schema
        already reflects all revisions up to that point.  Running ``flask db
        upgrade`` must complete the remaining revision (b3c4d5e6f7a1 squash-marker)
        with exit 0 and no duplicate-object errors.

        Requirements: 8.8
        """
        # Step 1: Full upgrade to establish the complete schema
        result_up = _run_flask_db("upgrade", db_url=clean_db)
        assert result_up.returncode == 0, (
            f"Initial upgrade failed (exit {result_up.returncode}):\n"
            f"stderr: {result_up.stderr}"
        )

        # Step 2: Stamp to mid-chain revision to simulate partial application.
        # The schema remains fully applied; only the alembic_version row is
        # rewound, mirroring a scenario where the last revision ran but the
        # version table update was not committed.
        result_stamp = _run_flask_db(
            f"stamp {_MID_CHAIN_REVISION}", db_url=clean_db
        )
        assert result_stamp.returncode == 0, (
            f"flask db stamp {_MID_CHAIN_REVISION} failed "
            f"(exit {result_stamp.returncode}):\n"
            f"stderr: {result_stamp.stderr}"
        )

        # Confirm the version is now the mid-chain revision
        conn = _connect(clean_db)
        try:
            stamped_version = _get_alembic_head(conn)
        finally:
            conn.close()
        assert stamped_version == _MID_CHAIN_REVISION, (
            f"Stamp did not take effect: expected {_MID_CHAIN_REVISION!r}, "
            f"got {stamped_version!r}"
        )

        # Step 3: Re-run upgrade from the mid-chain revision.
        # This exercises the partial-application recovery path: the chain
        # resumes from the stamped revision and applies the remaining step(s).
        result_resume = _run_flask_db("upgrade", db_url=clean_db)
        assert result_resume.returncode == 0, (
            f"flask db upgrade (from mid-chain stamp) failed "
            f"(exit {result_resume.returncode}):\n"
            f"stdout: {result_resume.stdout}\n"
            f"stderr: {result_resume.stderr}\n"
            f"Requirement 8.8: re-run must complete remaining statements "
            f"with no duplicate-object errors."
        )

        # Verify no duplicate-object error in output
        combined_output = result_resume.stdout + result_resume.stderr
        assert "duplicate_object" not in combined_output.lower(), (
            f"Duplicate-object error detected in upgrade output:\n{combined_output}\n"
            f"Requirement 8.8: no duplicate-object errors on re-run."
        )
        assert "DuplicateObject" not in combined_output, (
            f"DuplicateObject error in upgrade output:\n{combined_output}\n"
            f"Requirement 8.8: no duplicate-object errors on re-run."
        )

        # Verify the database is now at the expected head
        conn = _connect(clean_db)
        try:
            final_head = _get_alembic_head(conn)
        finally:
            conn.close()

        assert final_head == _EXPECTED_HEAD, (
            f"Expected head {_EXPECTED_HEAD!r} after partial-application recovery, "
            f"got {final_head!r}\n"
            f"Requirement 8.8: upgrade must complete all remaining statements."
        )
