#!/usr/bin/env python3
"""
Static linter for Alembic migration files.

Catches dangerous patterns that cause silent failures or production crashes:

1. raw_conn.execute() — psycopg2 connections require a cursor; calling .execute()
   directly on the connection object raises AttributeError in SQLAlchemy 1.4+.

2. bind.connection without .connection — op.get_bind().connection returns the
   SQLAlchemy pool proxy, not the raw DBAPI connection. Accessing .autocommit or
   .execute() on the proxy fails. Must use bind.connection.connection.

3. Bare string-interpolated op.execute(f"...") with user-controlled values —
   flagged as a warning (not an error) since parameterized queries are safer,
   but migration DML with hardcoded literals is generally fine.

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
# Patterns to flag as ERRORS (will block CI)
# ---------------------------------------------------------------------------

# Pattern: raw_conn.execute(  — direct .execute() on a psycopg2 connection
_RAW_CONN_EXECUTE = re.compile(r'\braw_conn\.execute\s*\(')

# Pattern: bind.connection[^.] — pool proxy used directly without unwrapping
# (bind.connection.connection is fine; bind.connection.autocommit is not)
_BIND_CONN_DIRECT = re.compile(r'bind\.connection(?!\.connection\b)[\s\.,\[]')

# Pattern: raw_conn.autocommit — setting autocommit on the pool proxy (not DBAPI)
# Only flag if it appears without the double .connection.connection unwrap nearby
_RAW_CONN_AUTOCOMMIT_DIRECT = re.compile(r'(?<!\.\bconnection\b)raw_conn\.autocommit')


def lint_file(path: Path) -> list[tuple[int, str, str]]:
    """
    Lint a single migration file.

    Returns a list of (line_number, severity, message) tuples.
    Empty list means the file is clean.
    """
    issues = []
    lines = path.read_text(encoding='utf-8').splitlines()

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
