#!/usr/bin/env python3
"""CLI/CI entry point for validating the Alembic migration chain.

Checks that the chain has exactly one root (``down_revision = None``) and
exactly one head revision.  Exits non-zero and prints the offending revision
identifiers when either invariant is violated.

Usage (from the ``backend/`` directory)::

    python scripts/check_migration_chain.py

Exit codes:
    0 — head_count == 1 AND root_count == 1 (chain is valid)
    1 — head_count != 1 OR root_count != 1 (chain is invalid)

Requirements: 1.6, 7.2, 7.3
"""
from __future__ import annotations

import sys
import os

# ---------------------------------------------------------------------------
# Ensure ``backend/`` is on sys.path so ``app.migration_utils`` can be imported
# regardless of which directory the script is invoked from.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.migration_utils import assert_single_head_and_root  # noqa: E402


def main() -> int:
    """Run the chain validation and return the process exit code."""
    result = assert_single_head_and_root()

    head_count: int = result["head_count"]
    head_revisions: list[str] = result["head_revisions"]
    root_count: int = result["root_count"]
    root_revisions: list[str] = result["root_revisions"]

    valid = head_count == 1 and root_count == 1

    if valid:
        print(
            f"Migration chain OK: "
            f"root={root_revisions[0]}  head={head_revisions[0]}"
        )
        return 0

    # ------------------------------------------------------------------ #
    # Report each violation                                               #
    # ------------------------------------------------------------------ #
    print("ERROR: Migration chain invariant violated.", file=sys.stderr)
    print(
        f"  Expected head_count=1, root_count=1  "
        f"—  got head_count={head_count}, root_count={root_count}",
        file=sys.stderr,
    )

    if head_count != 1:
        if head_count == 0:
            print("  No head revision found (empty chain?).", file=sys.stderr)
        else:
            print(
                f"  {head_count} head revision(s) detected:", file=sys.stderr
            )
            for rev in head_revisions:
                print(f"    - {rev}", file=sys.stderr)

    if root_count != 1:
        if root_count == 0:
            print(
                "  No root revision found (no revision with down_revision=None).",
                file=sys.stderr,
            )
        else:
            print(
                f"  {root_count} root revision(s) detected:", file=sys.stderr
            )
            for rev in root_revisions:
                print(f"    - {rev}", file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
