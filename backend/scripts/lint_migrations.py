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
