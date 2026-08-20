#!/usr/bin/env python3
"""Fail CI when Alembic revisions nest app factories / second DB sessions.

Banned (never allowlisted), detected via AST over the full module:
  - create_app(...) including qualified ``app.create_app()`` / aliases
  - ContactService

Other ``import app`` / ``from app...`` in historical revisions may appear in
``backend/alembic_migrations/purity_allowlist.txt`` (one basename per line).

Usage:
  python scripts/check_migration_purity.py
  python scripts/check_migration_purity.py --versions-dir PATH --allowlist PATH
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSIONS = REPO_ROOT / 'backend' / 'alembic_migrations' / 'versions'
DEFAULT_ALLOWLIST = REPO_ROOT / 'backend' / 'alembic_migrations' / 'purity_allowlist.txt'


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


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        if base:
            return f'{base}.{node.attr}'
        return node.attr
    return None


class _PurityVisitor(ast.NodeVisitor):
    def __init__(self, allowlisted: bool) -> None:
        self.allowlisted = allowlisted
        self.violations: list[tuple[int, str]] = []
        self._seen_violations: set[tuple[int, str]] = set()
        # names that alias create_app
        self._create_app_aliases: set[str] = {'create_app'}
        self._contact_service_aliases: set[str] = {'ContactService'}

    def _add_violation(self, lineno: int, key: str, message: str) -> None:
        marker = (lineno, key)
        if marker in self._seen_violations:
            return
        self._seen_violations.add(marker)
        self.violations.append((lineno, message))

    def _add_contact_service_violation(self, lineno: int, name: str) -> None:
        self._add_violation(
            lineno,
            'ContactService',
            f'banned ContactService use: {name}',
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split('.', 1)[0]
            if root == 'app' and not self.allowlisted:
                self._add_violation(
                    node.lineno,
                    f'app-import:{alias.name}',
                    f'app import not on purity allowlist: import {alias.name}',
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ''
        if mod == 'app' or mod.startswith('app.'):
            for alias in node.names:
                if alias.name == 'create_app' or (alias.asname and alias.name == 'create_app'):
                    bound = alias.asname or 'create_app'
                    self._create_app_aliases.add(bound)
                    self._add_violation(
                        node.lineno,
                        'create_app',
                        f'banned create_app import: from {mod} import {alias.name}',
                    )
                elif alias.name == 'ContactService' or (
                    alias.asname == 'ContactService' or alias.name.endswith('ContactService')
                ):
                    bound = alias.asname or alias.name
                    self._contact_service_aliases.add(bound)
                    self._add_contact_service_violation(
                        node.lineno,
                        f'from {mod} import {alias.name}',
                    )
                elif not self.allowlisted:
                    self._add_violation(
                        node.lineno,
                        f'app-import:{mod}.{alias.name}',
                        f'app import not on purity allowlist: from {mod} import {alias.name}',
                    )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        value_name = _call_name(node.value)
        if value_name and (
            value_name.endswith('.ContactService')
            or value_name in self._contact_service_aliases
        ):
            self._add_contact_service_violation(node.lineno, value_name)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._contact_service_aliases.add(target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name:
            leaf = name.rsplit('.', 1)[-1]
            if leaf == 'create_app' or name in self._create_app_aliases:
                self._add_violation(
                    node.lineno,
                    'create_app',
                    f'banned create_app() call: {name}(...)',
                )
            if (
                leaf == 'ContactService'
                or name.endswith('.ContactService')
                or name in self._contact_service_aliases
            ):
                self._add_contact_service_violation(node.lineno, f'{name}(...)')
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        name = _call_name(node)
        if isinstance(node.ctx, ast.Load) and name and name.endswith('.ContactService'):
            self._add_contact_service_violation(node.lineno, name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and node.id in self._contact_service_aliases:
            self._add_contact_service_violation(node.lineno, node.id)
        self.generic_visit(node)


def check_file(path: Path, allowlisted: bool) -> list[str]:
    text = path.read_text(encoding='utf-8')
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [f'{path.name}: syntax error: {exc}']
    visitor = _PurityVisitor(allowlisted=allowlisted)
    visitor.visit(tree)
    return [f'{path.name}:{lineno}: {msg}' for lineno, msg in visitor.violations]


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
