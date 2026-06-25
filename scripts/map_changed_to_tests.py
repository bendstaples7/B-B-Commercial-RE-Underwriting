#!/usr/bin/env python3
"""Map changed files (vs base branch) to targeted pytest paths and vitest files."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Path prefix -> pytest test paths (glob-style module names under backend/tests/)
BACKEND_RULES: list[tuple[str, list[str]]] = [
    ("backend/app/services/hubspot", ["tests/test_hubspot_*.py"]),
    ("backend/app/controllers/hubspot", ["tests/test_hubspot_*.py"]),
    ("backend/app/services/search", ["tests/test_search_*.py"]),
    ("backend/app/controllers/search", ["tests/test_search_*.py"]),
    ("backend/app/services/multifamily", ["tests/test_multifamily_*.py", "tests/test_pro_forma_*.py"]),
    ("backend/app/controllers/multifamily", ["tests/test_multifamily_*.py"]),
    ("backend/alembic_migrations", ["tests/test_migration_*.py"]),
    ("backend/app/models", ["tests/test_*_model*.py", "tests/test_migration_*.py"]),
    ("backend/app/services/queue", ["tests/test_queue_*.py"]),
    ("backend/app/controllers/command_center", ["tests/test_command_center_*.py"]),
    ("backend/app/services/om_intake", ["tests/test_om_intake_*.py"]),
    ("backend/app/controllers/om_intake", ["tests/test_om_intake_*.py"]),
]

# Direct file -> test mapping for common edits
BACKEND_FILE_RULES: list[tuple[str, list[str]]] = [
    ("backend/tests/", []),  # if only tests changed, run those files directly
]


def _git_changed_files(base: str) -> list[str]:
    merge_base = subprocess.run(
        ["git", "merge-base", "HEAD", base],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    paths: set[str] = set()
    for cmd in (
        ["git", "diff", "--name-only", f"{merge_base}..HEAD"],
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
    ):
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            paths.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(paths)


def _expand_globs(patterns: list[str]) -> list[str]:
    tests_dir = ROOT / "backend" / "tests"
    expanded: list[str] = []
    for pattern in patterns:
        for path in sorted(tests_dir.glob(pattern.replace("tests/", ""))):
            rel = path.relative_to(ROOT / "backend").as_posix()
            expanded.append(rel)
    return expanded


def map_backend_tests(changed: list[str]) -> list[str]:
    selected: set[str] = set()

    for path in changed:
        if path.startswith("backend/tests/") and path.endswith(".py"):
            rel = path.replace("backend/", "")
            selected.add(rel)

    for path in changed:
        for prefix, patterns in BACKEND_RULES:
            if path.startswith(prefix):
                selected.update(_expand_globs(patterns))

    if not selected and any(p.startswith("backend/") for p in changed):
        return ["tests/"]

    return sorted(selected)


def map_frontend_tests(changed: list[str]) -> list[str]:
    selected: set[str] = set()
    for path in changed:
        if not path.startswith("frontend/src/"):
            continue
        if path.endswith(".test.tsx") or path.endswith(".test.ts"):
            selected.add(path)
            continue
        stem = Path(path)
        for suffix in (".test.tsx", ".test.ts"):
            candidate = stem.with_name(stem.stem + suffix)
            if (ROOT / candidate).exists():
                selected.add(candidate.as_posix())
    return sorted(selected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    changed = _git_changed_files(args.base)
    backend = map_backend_tests(changed)
    frontend = map_frontend_tests(changed)

    if args.format == "json":
        import json

        print(json.dumps({"changed": changed, "backend": backend, "frontend": frontend}))
        return 0

    print("Changed files:")
    for path in changed:
        print(f"  {path}")
    print()
    print("Suggested backend pytest paths:")
    for path in backend:
        print(f"  {path}")
    print()
    print("Suggested frontend vitest files:")
    if frontend:
        for path in frontend:
            print(f"  {path}")
    else:
        print("  (none — run full suite if frontend src changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
