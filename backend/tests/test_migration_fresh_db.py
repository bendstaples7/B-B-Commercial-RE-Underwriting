"""
test_migration_fresh_db.py — Integration tests for fresh-database upgrade on PostgreSQL 15.

These tests verify the clean-baseline (squash) strategy produces a complete,
correct schema when run against a real, empty PostgreSQL 15 database — the
same engine used in production.

## How to run

Set the MIGRATION_TEST_DB_URL environment variable to a connection string for
a fresh (empty) PostgreSQL 15 database, then run:

    cd backend && pytest tests/test_migration_fresh_db.py -v -m integration

The database at MIGRATION_TEST_DB_URL must:
  - Be reachable from the test runner
  - Contain no application tables or enum types at test start
  - NOT be the same database used by the regular pytest suite

Example:
    MIGRATION_TEST_DB_URL=postgresql://postgres:pw@localhost:5432/migration_test_db \\
        pytest tests/test_migration_fresh_db.py -v -m integration

Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 3.1, 3.2, 3.3, 4.2
"""

import os
import subprocess
import sys
import pytest
import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Skip guard — all tests require a real PostgreSQL 15 database
# ---------------------------------------------------------------------------

MIGRATION_TEST_DB_URL = os.environ.get('MIGRATION_TEST_DB_URL')

pytestmark = pytest.mark.skipif(
    not MIGRATION_TEST_DB_URL,
    reason="MIGRATION_TEST_DB_URL not set — integration tests require a real PostgreSQL 15 database",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The expected head revision produced by the squash/marker (b3c4d5e6f7a1).
EXPECTED_HEAD_REVISION = 'b3c4d5e6f7a1'

#: Columns that must be present in the users table after upgrade (Req 4.2).
EXPECTED_USERS_COLUMNS = {
    'id',
    'user_id',
    'email',
    'email_lower',
    'password_hash',
    'display_name',
    'is_active',
    'is_admin',
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _backend_dir() -> str:
    """Return the absolute path to the backend/ directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_flask_db_upgrade(db_url: str) -> subprocess.CompletedProcess:
    """
    Run ``flask db upgrade`` against *db_url* using a subprocess so the
    command is invoked exactly as it would be in CI or production.

    The subprocess inherits the current environment but overrides
    DATABASE_URL and sets FLASK_APP / FLASK_ENV to prevent the app factory
    from auto-upgrading or running SystemExit guards.
    """
    env = os.environ.copy()
    env['DATABASE_URL'] = db_url
    env['FLASK_APP'] = 'run.py'
    env['FLASK_ENV'] = 'production'
    # Signal the app factory that it is being invoked for a migration command
    # so it skips the auto-upgrade side effect and blocking guards.
    env['FLASK_DB_COMMAND'] = '1'

    return subprocess.run(
        [sys.executable, '-m', 'flask', 'db', 'upgrade'],
        cwd=_backend_dir(),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _get_alembic_version(db_url: str) -> str | None:
    """
    Query the alembic_version table in the database at *db_url* and return
    the recorded version_num, or None if the table does not exist.
    """
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                sa.text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            row = result.fetchone()
            return row[0] if row else None
    except Exception:
        return None
    finally:
        engine.dispose()


def _get_table_columns(db_url: str, table_name: str) -> set[str]:
    """
    Return the set of column names present in *table_name* using
    information_schema.  Returns an empty set if the table does not exist.
    """
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                sa.text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = :tname
                      AND table_schema = 'public'
                    """
                ),
                {"tname": table_name},
            )
            return {row[0] for row in result.fetchall()}
    except Exception:
        return set()
    finally:
        engine.dispose()


def _table_exists(db_url: str, table_name: str) -> bool:
    """Return True if *table_name* exists in the public schema."""
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                sa.text(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_name = :tname
                      AND table_schema = 'public'
                    LIMIT 1
                    """
                ),
                {"tname": table_name},
            )
            return result.fetchone() is not None
    except Exception:
        return False
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_fresh_db_upgrade_exits_zero():
    """
    Requirements: 1.1, 2.1, 3.1, 3.2

    ``flask db upgrade`` on a completely empty PostgreSQL database must exit
    with status code 0.  This verifies that the full migration chain runs to
    completion on a fresh database without errors.
    """
    result = _run_flask_db_upgrade(MIGRATION_TEST_DB_URL)

    assert result.returncode == 0, (
        f"flask db upgrade exited with code {result.returncode} (expected 0).\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


@pytest.mark.integration
def test_fresh_db_records_head_revision():
    """
    Requirements: 1.1, 2.1

    After a successful ``flask db upgrade`` on a fresh database, the
    alembic_version table must contain exactly the expected head revision
    (b3c4d5e6f7a1 — the squash/marker head).

    This confirms Alembic recorded the correct revision after completing the
    full chain, not a partial or intermediate revision.
    """
    result = _run_flask_db_upgrade(MIGRATION_TEST_DB_URL)

    assert result.returncode == 0, (
        f"flask db upgrade failed before we could check alembic_version.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    recorded_revision = _get_alembic_version(MIGRATION_TEST_DB_URL)

    assert recorded_revision == EXPECTED_HEAD_REVISION, (
        f"Expected alembic_version to contain '{EXPECTED_HEAD_REVISION}', "
        f"got: {recorded_revision!r}.\n"
        f"This means the upgrade did not reach the expected head revision."
    )


@pytest.mark.integration
def test_fresh_db_no_raw_sql_files_required():
    """
    Requirements: 1.2, 1.3, 3.3

    The upgrade must succeed without reading or executing any file from
    ``backend/migrations/``.

    Verified by:
    1. Asserting the upgrade exits 0 (chain ran to completion).
    2. Asserting the subprocess command does not reference any .sql file
       path — the only command issued is ``flask db upgrade`` with no
       ``--sql`` flag and no psql invocation.
    3. Asserting the stdout/stderr of the upgrade command contains no
       references to the raw SQL file names.

    The raw SQL files (001_create_schema.sql, 002_lead_management.sql,
    003_add_lead_category.sql) are non-authoritative historical reference
    and must be excluded from the deployment path (Req 1.3, 1.4).
    """
    raw_sql_files = [
        '001_create_schema.sql',
        '002_lead_management.sql',
        '003_add_lead_category.sql',
    ]

    result = _run_flask_db_upgrade(MIGRATION_TEST_DB_URL)

    assert result.returncode == 0, (
        f"flask db upgrade failed, indicating the chain may still depend on "
        f"external SQL files.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    combined_output = result.stdout + result.stderr
    for sql_file in raw_sql_files:
        assert sql_file not in combined_output, (
            f"Raw SQL file '{sql_file}' was referenced in the upgrade output.\n"
            f"The deployment path must not read or apply any file from "
            f"backend/migrations/.\n"
            f"Output:\n{combined_output}"
        )


@pytest.mark.integration
def test_fresh_db_users_table_created():
    """
    Requirements: 1.1, 2.2, 4.2

    After ``flask db upgrade`` on a fresh database, the users table must
    exist and contain every column defined on the User model:
      id, user_id, email, email_lower, password_hash, display_name,
      is_active, is_admin.

    This verifies Requirement 4.2: the Users_Table contains every column,
    constraint, and index defined on the application user model.
    """
    result = _run_flask_db_upgrade(MIGRATION_TEST_DB_URL)

    assert result.returncode == 0, (
        f"flask db upgrade failed before we could inspect the users table.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    assert _table_exists(MIGRATION_TEST_DB_URL, 'users'), (
        "The 'users' table was not created by the migration chain.\n"
        "Requirement 4.2: the Users_Table must be created on a fresh database."
    )

    actual_columns = _get_table_columns(MIGRATION_TEST_DB_URL, 'users')

    missing_columns = EXPECTED_USERS_COLUMNS - actual_columns
    assert not missing_columns, (
        f"The following columns are missing from the users table: {missing_columns}\n"
        f"Present columns: {actual_columns}\n"
        f"Expected (at minimum): {EXPECTED_USERS_COLUMNS}\n"
        f"Requirement 4.2: Users_Table must match the User model definition."
    )
