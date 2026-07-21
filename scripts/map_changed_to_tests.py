#!/usr/bin/env python3
"""Map changed files (vs base branch) to targeted pytest paths and vitest files."""
from __future__ import annotations

import argparse
import json
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
    ("scripts/map_changed_to_tests.py", ["tests/test_map_changed_to_tests.py"]),
]


def _git_changed_files(base: str, *, staged_only: bool = False) -> list[str]:
    paths: set[str] = set()

    if staged_only:
        # Pre-commit: only the index (what this commit is about to include).
        result = subprocess.run(
            ["git", "diff", "--name-only", "--cached", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            paths.update(
                p.decode("utf-8", errors="replace")
                for p in result.stdout.split(b"\0")
                if p
            )
        return sorted(paths)

    merge_base = subprocess.run(
        ["git", "merge-base", "HEAD", base],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    for cmd in (
        ["git", "diff", "--name-only", "-z", f"{merge_base}..HEAD"],
        ["git", "diff", "--name-only", "-z"],
        ["git", "diff", "--name-only", "--cached", "-z"],
    ):
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, check=False)
        if result.returncode == 0 and result.stdout:
            paths.update(
                p.decode("utf-8", errors="replace")
                for p in result.stdout.split(b"\0")
                if p
            )
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
            if path.startswith(prefix) or path == prefix:
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


def build_mapping(changed: list[str]) -> dict:
    return {
        "changed": changed,
        "backend": map_backend_tests(changed),
        "frontend": map_frontend_tests(changed),
        "has_backend": any(p.startswith("backend/") for p in changed)
        or any(p.startswith("scripts/map_changed_to_tests") for p in changed),
        "has_frontend": any(p.startswith("frontend/") for p in changed),
        "has_frontend_src": any(p.startswith("frontend/src/") for p in changed),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/main")
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Only map staged (index) files — used by the pre-commit hook",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    changed = _git_changed_files(args.base, staged_only=args.staged)
    mapping = build_mapping(changed)

    if args.format == "json":
        print(json.dumps(mapping))
        return 0

    print("Changed files:")
    for path in mapping["changed"]:
        print(f"  {path}")
    print()
    print("Suggested backend pytest paths:")
    for path in mapping["backend"]:
        print(f"  {path}")
    print()
    print("Suggested frontend vitest files:")
    if mapping["frontend"]:
        for path in mapping["frontend"]:
            print(f"  {path}")
    else:
        print("  (none — run full suite if frontend src changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
