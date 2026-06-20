#!/usr/bin/env python3
"""
Static linter for Alembic migration files.

Catches dangerous patterns that cause silent failures or production crashes:

1. raw_conn.execute() — psycopg2 connections require a cursor; calling .execute()
   directly on the connection object raises AttributeError in SQLAlchemy 1.4+.

2. bind.connection without .connection — op.get_bind().connection returns the
   SQLAlchemy pool proxy, not the raw DBAPI connection. Accessing .autocommit or
   .execute() on the proxy fails. Must use bind.connection.connection.

3. batch_op.alter_column converting ARRAY/JSONB to JSON without a USING cast —
   PostgreSQL requires explicit USING; batch_alter_table doesn't support it.

4. ALTER TABLE / batch_alter_table referencing a table not created in the
   migration chain — catches "relation does not exist" errors on fresh databases.

Idempotency convention rules (Req 8.1–8.6) — enforced on NEW revisions only
(revisions not in _LEGACY_REVISION_IDS are considered new):

5. op.create_table() — forbidden; use CREATE TABLE IF NOT EXISTS via op.execute().

6. op.create_index() — forbidden; use CREATE INDEX IF NOT EXISTS via op.execute().

7. op.add_column() — forbidden; use ALTER TABLE ... ADD COLUMN IF NOT EXISTS.

8. batch_alter_table — forbidden on PostgreSQL; use raw ALTER TABLE statements.

9. CREATE TYPE without EXCEPTION WHEN duplicate_object guard — enum creation must
   be wrapped in DO $$ BEGIN ... EXCEPTION WHEN duplicate_object THEN NULL; END $$;

10. upgrade() without a corresponding downgrade() that uses DROP ... IF EXISTS.
    A downgrade that reverses its change by re-issuing CREATE OR REPLACE
    VIEW/FUNCTION/PROCEDURE (restoring the prior definition) also satisfies this
    reversibility requirement — a bare DROP is not required and would be unsafe
    for objects other code depends on.

Usage:
    python scripts/lint_migrations.py                     # lint all migrations
    python scripts/lint_migrations.py path/to/version.py  # lint specific file

Exit code: 0 = clean, 1 = errors found.
"""
import ast
import sys
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Legacy revision IDs — revisions that predate the idempotency convention.
# These files are EXEMPT from the new idempotency rules (8.1–8.6) because
# they already exist in production and must not be rewritten.
#
# Any migration file whose ``revision`` identifier is NOT listed here is
# treated as a "new" revision and must comply with all idempotency rules.
# Add new revision IDs here ONLY when grandfathering a pre-convention file.
# ---------------------------------------------------------------------------
_LEGACY_REVISION_IDS = frozenset({
    '000000000000',
    '267725fe7017',
    'a1b2c3d4e5f6',  # add_condo_filter_schema
    'b2c3d4e5f6g7',  # add_lead_scores_table
    'c3d4e5f6g7h8',  # multifamily_schema
    'd4e5f6g7h8i9',  # commercial_om_intake_schema
    'd4e5f6g7h8i9b', # add_min_comparables_to_scoring_weights
    'e5f6g7h8i9j0',  # merge_heads
    'e5f6g7h8i9j0b', # add_completed_steps_and_step_results_to_analysis_sessions
    'f6g7h8i9j0k1',  # add_confidence_score_to_valuation_results
    'f6g7h8i9j0k1b', # rentcast_cache
    'f6g7h8i9j0k1c', # merge_confidence_and_rentcast
    'fd5451087f07',  # add_loading_column_to_analysis_session
    'g7h8i9j0k1l2',  # sale_comp_nullable_cap_rate
    'g7h8i9j0k1l2b', # add_socrata_cache_tables
    'g7h8i9j0k1l2c', # merge_sale_comp_and_socrata
    'h8i9j0k1l2m3',  # add_hubspot_crm_tables
    'i9j0k1l2m3n4',  # add_lead_suppression_and_recommended_action
    'j0k1l2m3n4o5',  # seed_hubspot_signal_dictionary
    'k1l2m3n4o5p6',  # add_contact_model
    'l2m3n4o5p6q7',  # contact_email_lower_index
    'm3n4o5p6q7r8',  # add_crm_columns_to_leads
    'n4o5p6q7r8s9',  # create_lead_tasks_table
    'o5p6q7r8s9t0',  # create_lead_timeline_entries_table
    'p6q7r8s9t0u1',  # add_lead_id_to_tasks
    'q7r8s9t0u1v2',  # create_lead_crm_flags_view
    'r8s9t0u1v2w3',  # add_hubspot_webhook_tables
    'r9s0t1u2v3w4',  # backfill_lead_enrichment_from_hubspot
    's0t1u2v3w4x5',  # expand_lead_status_to_pipeline_stages
    't0u1v2w3x4y5',  # add_is_admin_to_users
    'u1v2w3x4y5z6',  # add_suggested_comps_columns
    'v1w2x3y4z5a6',  # add_owner_user_id_to_leads
    'w2x3y4z5a6b7',  # seed_sub_users_and_reassign_leads
    'x3y4z5a6b7c8',  # add_dupage_lead_columns
    'y4z5a6b7c8d9',  # add_import_job_source_type
    'z5a6b7c8d9e0',  # drop_leads_property_street_unique
})

# ---------------------------------------------------------------------------
# Tables created by the initial schema migration (000000000000).
# Any migration that ALTERs a table not in this set (or not created by a
# prior migration in the chain) will fail on a fresh database.
# Update this set whenever 000000000000_initial_schema.py adds new tables.
# ---------------------------------------------------------------------------
_INITIAL_SCHEMA_TABLES = {
    # From 001_create_schema.sql
    'analysis_sessions', 'property_facts', 'comparable_sales',
    'ranked_comparables', 'valuation_results', 'comparable_valuations',
    'scenarios', 'wholesale_scenarios', 'fix_flip_scenarios',
    'buy_hold_scenarios',
    # From 002_lead_management.sql
    'field_mappings', 'import_jobs', 'oauth_tokens', 'scoring_weights',
    'data_sources', 'leads', 'lead_audit_trail', 'enrichment_records',
    'marketing_lists', 'marketing_list_members',
    # users — created outside Alembic before migrations were introduced
    'users',
}

# ---------------------------------------------------------------------------
# Patterns to flag as ERRORS (will block CI)
# ---------------------------------------------------------------------------

# Pattern: raw_conn.execute(  — direct .execute() on a psycopg2 connection
_RAW_CONN_EXECUTE = re.compile(r'\braw_conn\.execute\s*\(')

# Pattern: bind.connection[^.] — pool proxy used directly without unwrapping
# (bind.connection.connection is fine; bind.connection.autocommit is not)
# Also matches bind.connection at end of line (e.g. raw_conn = bind.connection)
_BIND_CONN_DIRECT = re.compile(r'bind\.connection(?!\.connection\b)(?:[\s\.,\[]|$)')

# Pattern: raw_conn.autocommit — setting autocommit on the pool proxy (not DBAPI)
# Flags any use of raw_conn.autocommit when the variable hasn't been properly
# unwrapped via bind.connection.connection.
_RAW_CONN_AUTOCOMMIT_DIRECT = re.compile(r'\braw_conn\.autocommit\b')


# Pattern: batch_op.alter_column with type_=sa.JSON() or type_=sa.JSONB() when
# existing_type is an ARRAY or JSONB — PostgreSQL requires an explicit USING cast
# for these conversions; batch_alter_table does not support postgresql_using.
_BATCH_OP_JSON_WITHOUT_USING = re.compile(
    r'\bbatch_op\.alter_column\s*\('
)

# ---------------------------------------------------------------------------
# Idempotency convention patterns (Req 8.1–8.6).
# These are only enforced on NEW revisions (not in _LEGACY_REVISION_IDS).
# ---------------------------------------------------------------------------

# Req 8.1: op.create_table() — must use CREATE TABLE IF NOT EXISTS instead
_OP_CREATE_TABLE = re.compile(r'\bop\.create_table\s*\(')

# Req 8.3: op.create_index() — must use CREATE INDEX IF NOT EXISTS instead
_OP_CREATE_INDEX = re.compile(r'\bop\.create_index\s*\(')

# Req 8.4: op.add_column() — must use ALTER TABLE ... ADD COLUMN IF NOT EXISTS instead
_OP_ADD_COLUMN = re.compile(r'\bop\.add_column\s*\(')

# Req 8.5: batch_alter_table — forbidden on PostgreSQL
_OP_BATCH_ALTER_TABLE = re.compile(r'\bop\.batch_alter_table\s*\(')

# Req 8.2: CREATE TYPE without EXCEPTION WHEN duplicate_object guard.
# We detect raw "CREATE TYPE" in op.execute() strings that are NOT inside a
# DO $$ BEGIN ... EXCEPTION WHEN duplicate_object block.
_CREATE_TYPE_RAW = re.compile(r'\bCREATE\s+TYPE\b', re.IGNORECASE)
_EXCEPTION_WHEN_DUP = re.compile(r'EXCEPTION\s+WHEN\s+duplicate_object', re.IGNORECASE)

# Req 8.6: upgrade() without downgrade() using DROP ... IF EXISTS.
_DROP_IF_EXISTS = re.compile(r'\bDROP\b.+\bIF\s+EXISTS\b', re.IGNORECASE)

# A downgrade that re-issues CREATE OR REPLACE VIEW/FUNCTION/PROCEDURE is itself a
# valid, idempotent reversal: it restores the object's prior definition in place.
# Such downgrades intentionally avoid a bare DROP (which would break dependent
# objects), so they satisfy the reversibility requirement without DROP ... IF EXISTS.
_CREATE_OR_REPLACE = re.compile(
    r'\bCREATE\s+OR\s+REPLACE\s+(VIEW|FUNCTION|PROCEDURE)\b', re.IGNORECASE
)

# Object-creating DDL whose proper reversal is a DROP ... IF EXISTS. Req 8.6's
# "downgrade must DROP ... IF EXISTS" requirement only applies when an upgrade
# creates one of these objects. A pure data migration (UPDATE/INSERT/DELETE) or
# an in-place change (ALTER COLUMN) creates nothing to drop, so requiring a
# DROP-based downgrade for it would be a false positive — its valid reversal is
# more data DML, not a DROP.
# NOTE: "CREATE OR REPLACE VIEW/FUNCTION/PROCEDURE" is deliberately NOT matched
# here (the object keyword does not immediately follow CREATE) — those are
# reversed via CREATE OR REPLACE and handled by _CREATE_OR_REPLACE above.
_CREATES_DROPPABLE_OBJECT = re.compile(
    r'\bCREATE\s+(?:UNIQUE\s+)?'
    r'(?:TABLE|INDEX|TYPE|SEQUENCE|MATERIALIZED\s+VIEW|VIEW|SCHEMA|EXTENSION|'
    r'TRIGGER|DOMAIN)\b'
    r'|\bADD\s+(?:COLUMN|CONSTRAINT)\b'
    r'|\bop\.create_\w+\s*\('
    r'|\bop\.add_column\s*\(',
    re.IGNORECASE,
)


def _extract_revision_id(text: str) -> str | None:
    """Extract the revision identifier string from migration file text."""
    m = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    return m.group(1) if m else None


def _is_legacy_revision(path: Path, text: str) -> bool:
    """Return True if this file's revision ID is in the legacy whitelist."""
    revision_id = _extract_revision_id(text)
    if revision_id is None:
        return False
    return revision_id in _LEGACY_REVISION_IDS


def _check_enum_guard(text: str, lines: list[str]) -> list[tuple[int, str, str]]:
    """
    Req 8.2: Flag CREATE TYPE statements that are not wrapped in a
    DO $$ BEGIN ... EXCEPTION WHEN duplicate_object ... END $$; block.

    Strategy: for each line containing CREATE TYPE, check if the surrounding
    op.execute() call (or DO $$ block) also contains EXCEPTION WHEN duplicate_object.
    """
    issues = []
    for i, line in enumerate(lines, start=1):
        if line.lstrip().startswith('#'):
            continue
        if not _CREATE_TYPE_RAW.search(line):
            continue

        # Walk backwards to find the opening of the enclosing op.execute() or
        # triple-quoted string block, then check forward to its closing.
        # Simple heuristic: scan the surrounding ~20 lines for the guard phrase.
        window_start = max(0, i - 15)
        window_end = min(len(lines), i + 15)
        window = '\n'.join(lines[window_start:window_end])

        if not _EXCEPTION_WHEN_DUP.search(window):
            issues.append((
                i, 'ERROR',
                "CREATE TYPE detected without EXCEPTION WHEN duplicate_object guard.\n"
                "  Wrap enum creation in:\n"
                "    DO $$ BEGIN\n"
                "        CREATE TYPE <name> AS ENUM (...);\n"
                "    EXCEPTION WHEN duplicate_object THEN NULL;\n"
                "    END $$;\n"
                "  This makes the migration safe to re-run (Req 8.2).",
            ))
    return issues


def _check_downgrade_drop_if_exists(lines: list[str]) -> list[tuple[int, str, str]]:
    """
    Req 8.6: Flag upgrade() functions that have no corresponding downgrade()
    containing at least one DROP ... IF EXISTS statement.

    A downgrade that reverses its upgrade by re-issuing CREATE OR REPLACE
    VIEW/FUNCTION/PROCEDURE is treated as a valid, self-reversing/idempotent
    downgrade and is NOT flagged: it restores the original definition in place
    (a bare DROP would be wrong, breaking objects that depend on the view/function).

    Returns issues (attached to line 1 of the file) when the rule is violated.
    """
    issues = []

    text = '\n'.join(lines)

    # Detect whether upgrade() is defined (non-trivial: has at least one op. call)
    has_upgrade = bool(re.search(r'def upgrade\s*\(\s*\)\s*:', text))
    has_downgrade = bool(re.search(r'def downgrade\s*\(\s*\)\s*:', text))

    if not has_upgrade:
        return issues  # No upgrade — nothing to check

    if not has_downgrade:
        issues.append((
            1, 'ERROR',
            "upgrade() is defined but downgrade() is missing entirely.\n"
            "  Every migration must define a downgrade() that reverses its changes\n"
            "  using DROP ... IF EXISTS statements (Req 8.6).",
        ))
        return issues

    # Check that downgrade() body contains at least one DROP ... IF EXISTS
    # Extract the downgrade() function body by finding its def and collecting
    # indented lines until the next top-level def/class or end of file.
    in_downgrade = False
    downgrade_lines: list[str] = []
    for line in lines:
        if re.match(r'^def downgrade\s*\(\s*\)\s*:', line):
            in_downgrade = True
            downgrade_lines.append(line)
            continue
        if in_downgrade:
            # Stop at the next top-level definition
            if re.match(r'^(def |class )\S', line):
                break
            downgrade_lines.append(line)

    downgrade_body = '\n'.join(downgrade_lines)

    # Strip full-line Python comments before testing for a real reversal.
    # The DROP ... IF EXISTS / CREATE OR REPLACE checks run on function text, so
    # a bare comment such as "# CREATE OR REPLACE VIEW ..." or
    # "# DROP TABLE IF EXISTS ..." inside downgrade() would otherwise satisfy the
    # check even though no executable statement reverses the upgrade — a silent
    # CI-gate false negative (Req 8.6). Only match against executable lines.
    downgrade_body_executable = '\n'.join(
        l for l in downgrade_lines if not l.lstrip().startswith('#')
    )

    # A downgrade that is only "pass" or empty is non-compliant unless the
    # upgrade itself is also a no-op (only comments/pass/empty).
    # Check whether the upgrade body performs any actual schema operations.
    in_upgrade = False
    upgrade_lines: list[str] = []
    for line in lines:
        if re.match(r'^def upgrade\s*\(\s*\)\s*:', line):
            in_upgrade = True
            upgrade_lines.append(line)
            continue
        if in_upgrade:
            if re.match(r'^(def |class )\S', line):
                break
            upgrade_lines.append(line)

    upgrade_body = '\n'.join(upgrade_lines)

    # An upgrade is a no-op if its body has only pass/comments/docstrings
    upgrade_is_noop = not re.search(r'\bop\.execute\b|\bop\.\w+\(|\bconn\.execute\b', upgrade_body)
    if upgrade_is_noop:
        return issues  # No-op upgrade — no DROP IF EXISTS requirement

    # Req 8.6's "downgrade must DROP ... IF EXISTS" requirement only applies when
    # the upgrade actually creates a droppable schema object (table/index/type/
    # column/sequence/view/...). A pure data migration (UPDATE/INSERT/DELETE) or
    # an in-place ALTER creates nothing to drop, so demanding a DROP-based
    # downgrade would be a false positive — its valid reversal is more DML.
    # Match executable lines only so a commented-out CREATE can't switch the
    # requirement back on.
    upgrade_body_executable = '\n'.join(
        l for l in upgrade_lines if not l.lstrip().startswith('#')
    )
    if not _CREATES_DROPPABLE_OBJECT.search(upgrade_body_executable):
        return issues  # Data-only / in-place upgrade — DROP IF EXISTS not applicable

    if not _DROP_IF_EXISTS.search(downgrade_body_executable) and not _CREATE_OR_REPLACE.search(downgrade_body_executable):
        issues.append((
            1, 'ERROR',
            "upgrade() performs schema changes but downgrade() contains no "
            "'DROP ... IF EXISTS' statement.\n"
            "  Add DROP TABLE IF EXISTS / DROP INDEX IF EXISTS / DROP TYPE IF EXISTS\n"
            "  statements to downgrade() to reverse the changes (Req 8.6).\n"
            "  (A downgrade that re-issues CREATE OR REPLACE VIEW/FUNCTION/PROCEDURE\n"
            "  to restore the prior definition also satisfies this requirement.)",
        ))

    return issues


def _is_array_or_jsonb_to_json(block_lines: list[str]) -> bool:
    """Return True if an alter_column block converts ARRAY or JSONB to JSON."""
    has_json_target = any('type_=sa.JSON()' in l or 'type_=sa.JSONB()' in l for l in block_lines)
    has_array_or_jsonb_source = any(
        'ARRAY(' in l or 'postgresql.JSONB(' in l or 'JSONB(astext_type' in l
        for l in block_lines
        if 'existing_type' in l
    )
    return has_json_target and has_array_or_jsonb_source


def lint_file(path: Path) -> list[tuple[int, str, str]]:
    """
    Lint a single migration file.

    Returns a list of (line_number, severity, message) tuples.
    Empty list means the file is clean.
    """
    issues = []
    lines = path.read_text(encoding='utf-8').splitlines()
    text = '\n'.join(lines)

    # Determine whether this is a legacy (pre-convention) revision.
    # Legacy revisions are exempt from the new idempotency rules (8.1–8.6).
    is_legacy = _is_legacy_revision(path, text)

    # --------------------------------------------------------------------
    # Scan for batch_op.alter_column calls that convert ARRAY/JSONB → JSON
    # without an explicit USING cast.  PostgreSQL rejects these; the fix is
    # to use a raw op.execute("ALTER TABLE ... TYPE JSON USING ...") instead.
    # --------------------------------------------------------------------
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if not stripped.startswith('#') and _BATCH_OP_JSON_WITHOUT_USING.search(line):
            # Collect this alter_column call (may span multiple lines until closing paren)
            call_start = i + 1  # 1-indexed
            call_lines = [line]
            depth = line.count('(') - line.count(')')
            j = i + 1
            while depth > 0 and j < len(lines):
                call_lines.append(lines[j])
                depth += lines[j].count('(') - lines[j].count(')')
                j += 1
            if _is_array_or_jsonb_to_json(call_lines):
                issues.append((
                    call_start, 'ERROR',
                    "batch_op.alter_column converting ARRAY or JSONB to JSON detected.\n"
                    "  PostgreSQL requires an explicit USING cast for this conversion;\n"
                    "  batch_alter_table does not support postgresql_using.\n"
                    "  Fix: replace with op.execute(\n"
                    "    'ALTER TABLE t ALTER COLUMN col TYPE JSON USING col::json'\n"
                    "  ) before the batch_alter_table block.",
                ))
            i = j
        else:
            i += 1

    for i, line in enumerate(lines, start=1):
        # Skip comment lines
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue

        if _RAW_CONN_EXECUTE.search(line):
            issues.append((
                i, 'ERROR',
                "raw_conn.execute() detected — use a cursor: "
                "with raw_conn.cursor() as cur: cur.execute(...)\n"
                "  psycopg2 connections don't support .execute() directly.",
            ))

        if _BIND_CONN_DIRECT.search(line):
            # Allow bind.connection.connection (double unwrap is correct)
            if 'bind.connection.connection' not in line:
                issues.append((
                    i, 'ERROR',
                    "bind.connection used directly — this is the SQLAlchemy pool proxy, "
                    "not the raw DBAPI connection.\n"
                    "  Use bind.connection.connection to get the psycopg2 connection.",
                ))

    # --------------------------------------------------------------------
    # Check .autocommit usage on any variable.
    #
    # A variable assigned via `x = bind.connection.connection` is safely
    # unwrapped — setting autocommit on it is correct.
    #
    # We track safe assignments at the SCOPE where they appear:
    # we scan line-by-line and maintain a running set of names that have
    # been safely assigned on a PRECEDING line in the same file.
    # A safe assignment is immediately invalidated if the same name is later
    # re-assigned without the double-unwrap (unsafe reassignment).
    # --------------------------------------------------------------------
    _UNWRAP_ASSIGN = re.compile(r'^\s*(\w+)\s*=\s*.*bind\.connection\.connection\b')
    _ANY_ASSIGN = re.compile(r'^\s*(\w+)\s*=\s*(.+)')
    _AUTOCOMMIT_USE = re.compile(r'\b(\w+)\.autocommit\b')

    # Map: var_name → True (safely unwrapped) | False (assigned unsafely / reassigned)
    var_safety: dict[str, bool] = {}

    for i, line in enumerate(lines, start=1):
        if line.lstrip().startswith('#'):
            continue

        # Track assignments first (before the autocommit check so the
        # definition on the SAME line as `.autocommit` is also caught)
        safe_m = _UNWRAP_ASSIGN.match(line)
        if safe_m:
            var_safety[safe_m.group(1)] = True
        else:
            any_m = _ANY_ASSIGN.match(line)
            if any_m:
                assigned_name = any_m.group(1)
                # Any reassignment that isn't a double-unwrap marks the var unsafe
                if assigned_name in var_safety:
                    var_safety[assigned_name] = False

        # Check .autocommit usage
        for m in _AUTOCOMMIT_USE.finditer(line):
            var_name = m.group(1)
            # Flag if the variable is either:
            # 1. Known to be unsafe (assigned without double-unwrap), or
            # 2. Never seen as a double-unwrap assignment at all
            if var_safety.get(var_name, False) is not True:
                issues.append((
                    i, 'ERROR',
                    f"'{var_name}.autocommit' detected — ensure '{var_name}' is the "
                    "unwrapped DBAPI connection (from bind.connection.connection), "
                    "not the pool proxy.\n"
                    "  Setting autocommit on the pool proxy has no effect and "
                    "silently fails.",
                ))

    # --------------------------------------------------------------------
    # Check that ALTER TABLE / batch_alter_table references only tables
    # that exist in the initial schema or are created somewhere in the
    # Alembic migration chain (by any migration's op.create_table).
    #
    # "relation does not exist" errors on fresh DBs happen when a migration
    # assumes a table was created by a prior raw SQL file rather than by
    # the Alembic chain.  This check catches that at lint time.
    # --------------------------------------------------------------------
    # Build the full set of tables known to Alembic: start with the initial
    # schema tables, then add every table created by any migration file.
    _CREATE_TABLE_RE = re.compile(
        r"op\.create_table\s*\(\s*['\"](\w+)['\"]",
    )
    # Collect tables from ALL migration files in the same directory
    all_known_tables: set[str] = set(_INITIAL_SCHEMA_TABLES)
    versions_dir = path.parent
    if versions_dir.is_dir():
        for mig_file in versions_dir.glob('*.py'):
            if mig_file.name == '__init__.py':
                continue
            try:
                mig_text = mig_file.read_text(encoding='utf-8')
                for m in _CREATE_TABLE_RE.finditer(mig_text):
                    all_known_tables.add(m.group(1).lower())
            except Exception:
                pass

    # Also collect tables created in THIS file
    for m in _CREATE_TABLE_RE.finditer('\n'.join(lines)):
        all_known_tables.add(m.group(1).lower())

    # Skip this check for the initial schema file itself
    _ALTER_TABLE_RE = re.compile(
        r"(?:op\.batch_alter_table\s*\(\s*['\"](\w+)['\"]"
        r"|ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?['\"]?(\w+)['\"]?)",
        re.IGNORECASE,
    )
    is_initial_schema = '000000000000' in path.name
    if not is_initial_schema:
        for i, line in enumerate(lines, start=1):
            if line.lstrip().startswith('#'):
                continue
            m = _ALTER_TABLE_RE.search(line)
            if m:
                tname = m.group(1) or m.group(2)
                if tname and tname.lower() not in all_known_tables:
                    issues.append((
                        i, 'ERROR',
                        f"ALTER TABLE '{tname}' references a table not created by "
                        f"any Alembic migration or the initial schema.\n"
                        f"  This will fail with 'relation \"{tname}\" does not exist' "
                        f"on a fresh database.\n"
                        f"  Add CREATE TABLE IF NOT EXISTS for '{tname}' to "
                        f"000000000000_initial_schema.py, or verify the table is "
                        f"created by a prior migration in the chain.",
                    ))

    # --------------------------------------------------------------------
    # Idempotency convention checks (Req 8.1–8.6).
    # Only applied to NEW revisions — legacy revisions are exempt.
    # --------------------------------------------------------------------
    if not is_legacy:
        for i, line in enumerate(lines, start=1):
            stripped = line.lstrip()
            if stripped.startswith('#'):
                continue

            # Req 8.1: op.create_table() is forbidden — use CREATE TABLE IF NOT EXISTS
            if _OP_CREATE_TABLE.search(line):
                issues.append((
                    i, 'ERROR',
                    "op.create_table() detected — use raw SQL instead:\n"
                    "  op.execute('CREATE TABLE IF NOT EXISTS <name> (...)')\n"
                    "  op.create_table() raises DuplicateObject on re-run (Req 8.1).",
                ))

            # Req 8.3: op.create_index() is forbidden — use CREATE INDEX IF NOT EXISTS
            if _OP_CREATE_INDEX.search(line):
                issues.append((
                    i, 'ERROR',
                    "op.create_index() detected — use raw SQL instead:\n"
                    "  op.execute('CREATE INDEX IF NOT EXISTS <name> ON <table>(<col>)')\n"
                    "  op.create_index() raises DuplicateObject on re-run (Req 8.3).",
                ))

            # Req 8.4: op.add_column() is forbidden — use ALTER TABLE ... ADD COLUMN IF NOT EXISTS
            if _OP_ADD_COLUMN.search(line):
                issues.append((
                    i, 'ERROR',
                    "op.add_column() detected — use raw SQL instead:\n"
                    "  op.execute('ALTER TABLE <t> ADD COLUMN IF NOT EXISTS <col> <type>')\n"
                    "  op.add_column() raises DuplicateColumn on re-run (Req 8.4).",
                ))

            # Req 8.5: batch_alter_table is forbidden on PostgreSQL
            if _OP_BATCH_ALTER_TABLE.search(line):
                issues.append((
                    i, 'ERROR',
                    "op.batch_alter_table() detected — forbidden on PostgreSQL.\n"
                    "  batch_alter_table creates a new table + copy + drop, which fails\n"
                    "  when enum types already exist and doesn't support USING casts.\n"
                    "  Use raw ALTER TABLE statements via op.execute() instead (Req 8.5).",
                ))

        # Req 8.2: CREATE TYPE without EXCEPTION WHEN duplicate_object guard
        issues.extend(_check_enum_guard(text, lines))

        # Req 8.6: upgrade() without downgrade() using DROP ... IF EXISTS
        issues.extend(_check_downgrade_drop_if_exists(lines))

    return issues


def lint_directory(migrations_dir: Path) -> dict[Path, list]:
    """Lint all .py files under migrations_dir/versions/."""
    versions_dir = migrations_dir / 'versions'
    if not versions_dir.exists():
        print(f"WARNING: versions dir not found: {versions_dir}")
        return {}

    results = {}
    for f in sorted(versions_dir.glob('*.py')):
        if f.name == '__init__.py':
            continue
        issues = lint_file(f)
        if issues:
            results[f] = issues
    return results


def main():
    repo_root = Path(__file__).resolve().parent.parent
    migrations_dir = repo_root / 'alembic_migrations'

    if len(sys.argv) > 1:
        # Lint specific files provided as arguments
        targets = [Path(a) for a in sys.argv[1:]]
        all_issues = {}
        for t in targets:
            issues = lint_file(t)
            if issues:
                all_issues[t] = issues
    else:
        all_issues = lint_directory(migrations_dir)

    if not all_issues:
        print("Migration lint: no issues found.")
        sys.exit(0)

    error_count = 0
    for path, issues in sorted(all_issues.items()):
        for lineno, severity, msg in issues:
            print(f"{path.name}:{lineno}: {severity}: {msg}")
            if severity == 'ERROR':
                error_count += 1

    print(f"\n{error_count} error(s) found across {len(all_issues)} file(s).")
    sys.exit(1 if error_count > 0 else 0)


if __name__ == '__main__':
    main()
