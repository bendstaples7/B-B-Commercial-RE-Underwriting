"""
Tests for the extended migration linter (Task 5.1).

Validates Req 8.1–8.6: idempotency rules applied to new (non-legacy) revisions.
"""
from pathlib import Path
import pytest

# Import the linter module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
import lint_migrations as linter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def lint_content(content: str, tmp_path: Path, filename: str = '_test_rev.py'):
    """Write content to a temp file and lint it."""
    p = tmp_path / filename
    p.write_text(content, encoding='utf-8')
    return linter.lint_file(p)


def errors_with(issues, substring: str):
    """Return ERROR issues whose message contains substring."""
    return [(ln, msg) for ln, sev, msg in issues
            if sev == 'ERROR' and substring in msg]


# ---------------------------------------------------------------------------
# Migration builders — produce well-formed files with no leading whitespace issues
# ---------------------------------------------------------------------------

def new_migration(upgrade_body: str, downgrade_body: str, revision: str = 'new_rev_test_aaa') -> str:
    """Build a complete new (non-legacy) migration string."""
    lines = [
        "from alembic import op",
        "import sqlalchemy as sa",
        "",
        f"revision = '{revision}'",
        "down_revision = 'z5a6b7c8d9e0'",
        "branch_labels = None",
        "depends_on = None",
        "",
        "",
        "def upgrade():",
    ]
    for line in upgrade_body.splitlines():
        lines.append(f"    {line}" if line.strip() else "")
    lines += ["", "", "def downgrade():"]
    for line in downgrade_body.splitlines():
        lines.append(f"    {line}" if line.strip() else "")
    lines.append("")
    return "\n".join(lines)


def legacy_migration(upgrade_body: str, downgrade_body: str, revision: str = '267725fe7017') -> str:
    """Build a legacy migration string."""
    lines = [
        "from alembic import op",
        "import sqlalchemy as sa",
        "",
        f"revision = '{revision}'",
        "down_revision = '000000000000'",
        "branch_labels = None",
        "depends_on = None",
        "",
        "",
        "def upgrade():",
    ]
    for line in upgrade_body.splitlines():
        lines.append(f"    {line}" if line.strip() else "")
    lines += ["", "", "def downgrade():"]
    for line in downgrade_body.splitlines():
        lines.append(f"    {line}" if line.strip() else "")
    lines.append("")
    return "\n".join(lines)


_COMPLIANT_UPGRADE = (
    'op.execute("CREATE TABLE IF NOT EXISTS test_tbl (id SERIAL PRIMARY KEY)")\n'
    'op.execute("CREATE INDEX IF NOT EXISTS ix_test_tbl_id ON test_tbl(id)")'
)
_COMPLIANT_DOWNGRADE = (
    'op.execute("DROP TABLE IF EXISTS test_tbl")\n'
    'op.execute("DROP INDEX IF EXISTS ix_test_tbl_id")'
)


# ===========================================================================
# Req 8.1 — op.create_table() is forbidden in new revisions
# ===========================================================================

class TestReq81CreateTable:
    def test_op_create_table_flagged_in_new_revision(self, tmp_path):
        content = new_migration(
            upgrade_body="op.create_table('new_table', sa.Column('id', sa.Integer()))",
            downgrade_body='op.execute("DROP TABLE IF EXISTS new_table")',
        )
        issues = lint_content(content, tmp_path)
        assert errors_with(issues, 'op.create_table()'), \
            "Expected ERROR for op.create_table() in new revision"

    def test_op_create_table_not_flagged_in_legacy_revision(self, tmp_path):
        content = legacy_migration(
            upgrade_body="op.create_table('test_tbl', sa.Column('id', sa.Integer()))",
            downgrade_body="op.drop_table('test_tbl')",
        )
        issues = lint_content(content, tmp_path)
        assert not errors_with(issues, 'op.create_table()'), \
            "Legacy revision should not be flagged for op.create_table()"

    def test_create_table_if_not_exists_compliant(self, tmp_path):
        content = new_migration(_COMPLIANT_UPGRADE, _COMPLIANT_DOWNGRADE)
        issues = lint_content(content, tmp_path)
        assert not errors_with(issues, 'op.create_table()'), \
            "CREATE TABLE IF NOT EXISTS via op.execute() must not be flagged"


# ===========================================================================
# Req 8.3 — op.create_index() is forbidden in new revisions
# ===========================================================================

class TestReq83CreateIndex:
    def test_op_create_index_flagged_in_new_revision(self, tmp_path):
        content = new_migration(
            upgrade_body="op.create_index('ix_t_id', 't', ['id'])",
            downgrade_body='op.execute("DROP INDEX IF EXISTS ix_t_id")',
        )
        issues = lint_content(content, tmp_path)
        assert errors_with(issues, 'op.create_index()'), \
            "Expected ERROR for op.create_index() in new revision"

    def test_create_index_if_not_exists_compliant(self, tmp_path):
        content = new_migration(_COMPLIANT_UPGRADE, _COMPLIANT_DOWNGRADE)
        issues = lint_content(content, tmp_path)
        assert not errors_with(issues, 'op.create_index()'), \
            "CREATE INDEX IF NOT EXISTS via op.execute() must not be flagged"


# ===========================================================================
# Req 8.4 — op.add_column() is forbidden in new revisions
# ===========================================================================

class TestReq84AddColumn:
    def test_op_add_column_flagged_in_new_revision(self, tmp_path):
        content = new_migration(
            upgrade_body="op.add_column('leads', sa.Column('new_col', sa.String()))",
            downgrade_body='op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS new_col")',
        )
        issues = lint_content(content, tmp_path)
        assert errors_with(issues, 'op.add_column()'), \
            "Expected ERROR for op.add_column() in new revision"

    def test_add_column_if_not_exists_compliant(self, tmp_path):
        content = new_migration(
            upgrade_body='op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS new_col VARCHAR(50)")',
            downgrade_body='op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS new_col")',
        )
        issues = lint_content(content, tmp_path)
        assert not errors_with(issues, 'op.add_column()'), \
            "ADD COLUMN IF NOT EXISTS via op.execute() must not be flagged"


# ===========================================================================
# Req 8.5 — batch_alter_table is forbidden in new revisions
# ===========================================================================

class TestReq85BatchAlterTable:
    def test_batch_alter_table_flagged_in_new_revision(self, tmp_path):
        content = new_migration(
            upgrade_body="with op.batch_alter_table('leads') as batch_op:\n    batch_op.alter_column('x', type_=sa.String())",
            downgrade_body='op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS x")',
        )
        issues = lint_content(content, tmp_path)
        assert errors_with(issues, 'batch_alter_table'), \
            "Expected ERROR for op.batch_alter_table() in new revision"

    def test_batch_alter_table_not_flagged_in_legacy(self, tmp_path):
        content = legacy_migration(
            upgrade_body="with op.batch_alter_table('leads') as batch_op:\n    batch_op.alter_column('x', type_=sa.String())",
            downgrade_body="with op.batch_alter_table('leads') as batch_op:\n    batch_op.alter_column('x', existing_type=sa.String(), type_=sa.Text())",
        )
        issues = lint_content(content, tmp_path)
        generic_errors = errors_with(issues, 'forbidden on PostgreSQL')
        assert not generic_errors, "Legacy revision must not get generic batch_alter_table error"


# ===========================================================================
# Req 8.2 — CREATE TYPE without EXCEPTION WHEN duplicate_object guard
# ===========================================================================

class TestReq82EnumGuard:
    def test_create_type_without_guard_flagged(self, tmp_path):
        content = new_migration(
            upgrade_body="op.execute(\"CREATE TYPE my_status AS ENUM ('active', 'inactive')\")",
            downgrade_body='op.execute("DROP TYPE IF EXISTS my_status")',
        )
        issues = lint_content(content, tmp_path)
        assert errors_with(issues, 'EXCEPTION WHEN duplicate_object'), \
            "Expected ERROR for CREATE TYPE without duplicate_object guard"

    def test_create_type_with_guard_compliant(self, tmp_path):
        guarded = (
            "op.execute(\"\"\"\n"
            "    DO $$ BEGIN\n"
            "        CREATE TYPE my_status AS ENUM ('active', 'inactive');\n"
            "    EXCEPTION WHEN duplicate_object THEN NULL;\n"
            "    END $$;\n"
            "\"\"\")"
        )
        content = new_migration(
            upgrade_body=guarded,
            downgrade_body='op.execute("DROP TYPE IF EXISTS my_status")',
        )
        issues = lint_content(content, tmp_path)
        assert not errors_with(issues, 'EXCEPTION WHEN duplicate_object'), \
            "Guarded CREATE TYPE should not be flagged"

    def test_create_type_not_flagged_in_legacy(self, tmp_path):
        content = legacy_migration(
            upgrade_body="op.execute(\"CREATE TYPE legacy_enum AS ENUM ('a', 'b')\")",
            downgrade_body='op.execute("DROP TYPE IF EXISTS legacy_enum")',
        )
        issues = lint_content(content, tmp_path)
        assert not errors_with(issues, 'EXCEPTION WHEN duplicate_object'), \
            "Legacy revision must not be flagged for unguarded CREATE TYPE"


# ===========================================================================
# Req 8.6 — upgrade() without downgrade() using DROP ... IF EXISTS
# ===========================================================================

class TestReq86DowngradeDropIfExists:
    def test_missing_downgrade_flagged(self, tmp_path):
        content = (
            "from alembic import op\n"
            "\n"
            "revision = 'new_rev_test_bbb'\n"
            "down_revision = 'z5a6b7c8d9e0'\n"
            "branch_labels = None\n"
            "depends_on = None\n"
            "\n"
            "\n"
            "def upgrade():\n"
            "    op.execute('CREATE TABLE IF NOT EXISTS t (id SERIAL PRIMARY KEY)')\n"
        )
        issues = lint_content(content, tmp_path)
        assert errors_with(issues, 'downgrade()'), \
            "Expected ERROR when downgrade() is entirely missing"

    def test_downgrade_without_drop_if_exists_flagged(self, tmp_path):
        content = new_migration(
            upgrade_body='op.execute("CREATE TABLE IF NOT EXISTS t (id SERIAL PRIMARY KEY)")',
            downgrade_body='pass',
        )
        issues = lint_content(content, tmp_path)
        drop_errors = [msg for _, sev, msg in issues if sev == 'ERROR' and 'DROP' in msg]
        assert drop_errors, "Expected ERROR when downgrade() has no DROP ... IF EXISTS"

    def test_downgrade_with_drop_if_exists_compliant(self, tmp_path):
        content = new_migration(_COMPLIANT_UPGRADE, _COMPLIANT_DOWNGRADE)
        issues = lint_content(content, tmp_path)
        assert not errors_with(issues, 'DROP'), \
            "Compliant downgrade() should not produce DROP-related errors"

    def test_noop_upgrade_doesnt_require_drop_if_exists(self, tmp_path):
        content = new_migration(upgrade_body='pass', downgrade_body='pass')
        issues = lint_content(content, tmp_path)
        assert not errors_with(issues, 'DROP'), \
            "No-op upgrade() must not require DROP ... IF EXISTS"

    def test_legacy_revision_exempt_from_downgrade_rule(self, tmp_path):
        content = legacy_migration(
            upgrade_body='op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS uq_leads_property_street")',
            downgrade_body='pass',
            revision='z5a6b7c8d9e0',
        )
        issues = lint_content(content, tmp_path)
        downgrade_errors = [msg for _, sev, msg in issues
                            if sev == 'ERROR' and 'downgrade' in msg.lower()]
        assert not downgrade_errors, "Legacy revision must not be flagged for downgrade rule"


# ===========================================================================
# Existing rules still work (regression tests)
# ===========================================================================

class TestExistingRulesPreserved:
    def test_raw_conn_execute_still_flagged_in_legacy(self, tmp_path):
        content = legacy_migration(
            upgrade_body=(
                "bind = op.get_bind()\n"
                "raw_conn = bind.connection.connection\n"
                'raw_conn.execute("SELECT 1")'
            ),
            downgrade_body='pass',
            revision='z5a6b7c8d9e0',
        )
        issues = lint_content(content, tmp_path)
        assert errors_with(issues, 'raw_conn.execute()'), \
            "raw_conn.execute() must still be flagged in legacy revisions"

    def test_clean_new_revision_passes_all_checks(self, tmp_path):
        upgrade = (
            "op.execute(\"\"\"\n"
            "    DO $$ BEGIN\n"
            "        CREATE TYPE status_enum AS ENUM ('active', 'inactive');\n"
            "    EXCEPTION WHEN duplicate_object THEN NULL;\n"
            "    END $$;\n"
            "\"\"\")\n"
            "op.execute(\"CREATE TABLE IF NOT EXISTS new_tbl (id SERIAL PRIMARY KEY, status status_enum NOT NULL)\")\n"
            "op.execute(\"CREATE INDEX IF NOT EXISTS ix_new_tbl_status ON new_tbl(status)\")\n"
            "op.execute(\"ALTER TABLE leads ADD COLUMN IF NOT EXISTS new_col VARCHAR(50)\")"
        )
        downgrade = (
            'op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS new_col")\n'
            'op.execute("DROP INDEX IF EXISTS ix_new_tbl_status")\n'
            'op.execute("DROP TABLE IF EXISTS new_tbl")\n'
            'op.execute("DROP TYPE IF EXISTS status_enum")'
        )
        content = new_migration(upgrade, downgrade)
        issues = lint_content(content, tmp_path)
        error_issues = [(ln, msg) for ln, sev, msg in issues if sev == 'ERROR']
        assert not error_issues, \
            f"Fully compliant new revision should have no errors, got: {error_issues}"
