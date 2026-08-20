#!/usr/bin/env python3
"""Fail CI when Alembic revisions nest app factories / second DB sessions.

Banned (never allowlisted):
  - create_app( / from app import create_app
  - ContactService (nested service heal class that opens app work mid-migration)

Other ``from app...`` / ``import app...`` in historical revisions may appear in
``backend/alembic_migrations/purity_allowlist.txt`` (one basename per line).

Usage:
  python scripts/check_migration_purity.py
  python scripts/check_migration_purity.py --versions-dir PATH --allowlist PATH
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSIONS = REPO_ROOT / 'backend' / 'alembic_migrations' / 'versions'
DEFAULT_ALLOWLIST = REPO_ROOT / 'backend' / 'alembic_migrations' / 'purity_allowlist.txt'

# Never escapable via allowlist
BANNED_ALWAYS = [
    re.compile(r'from\s+app\s+import\s+create_app\b'),
    re.compile(r'(?<![\w.])create_app\s*\('),
    re.compile(r'\bContactService\b'),
]

APP_IMPORT = re.compile(
    r'^\s*(?:from\s+app(?:\.|\s)|import\s+app(?:\.|\s|$))'
)


def _strip_line_comment(line: str) -> str:
    """Remove # comments outside of simple quotes (good enough for migrations)."""
    in_single = False
    in_double = False
    out: list[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
        elif ch == '#' and not in_single and not in_double:
            break
        else:
            out.append(ch)
        i += 1
    return ''.join(out)


def load_allowlist(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    names: set[str] = set()
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        names.add(Path(line).name)
    return names


def check_file(path: Path, allowlisted: bool) -> list[str]:
    """Return human-readable violation strings for one revision file."""
    text = path.read_text(encoding='utf-8')
    violations: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        code = _strip_line_comment(raw)
        if not code.strip():
            continue
        for pat in BANNED_ALWAYS:
            if pat.search(code):
                violations.append(
                    f'{path.name}:{lineno}: banned pattern {pat.pattern!r}: {raw.strip()}'
                )
        if not allowlisted and APP_IMPORT.search(code):
            violations.append(
                f'{path.name}:{lineno}: app import not on purity allowlist: {raw.strip()}'
            )
    return violations


def check_tree(versions_dir: Path, allowlist_path: Path) -> list[str]:
    allow = load_allowlist(allowlist_path)
    violations: list[str] = []
    if not versions_dir.is_dir():
        return [f'versions dir missing: {versions_dir}']
    for path in sorted(versions_dir.glob('*.py')):
        if path.name == '__init__.py':
            continue
        violations.extend(check_file(path, allowlisted=path.name in allow))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--versions-dir', type=Path, default=DEFAULT_VERSIONS)
    parser.add_argument('--allowlist', type=Path, default=DEFAULT_ALLOWLIST)
    args = parser.parse_args(argv)

    violations = check_tree(args.versions_dir, args.allowlist)
    if violations:
        print('Migration purity check FAILED:', file=sys.stderr)
        for v in violations:
            print(f'  {v}', file=sys.stderr)
        print(
            '\nSchema-only Alembic revisions. Data heals belong in backend/scripts/.',
            file=sys.stderr,
        )
        return 1
    print('Migration purity check OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
