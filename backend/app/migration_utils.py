"""Migration chain validation utilities.

Provides :func:`assert_single_head_and_root`, a reusable, non-terminating
validator that scans the Alembic revision files on disk and returns structured
information about the migration graph's heads and roots.

Design contract
---------------
* Does **not** call ``SystemExit``.  Callers decide how to surface failures.
* Returns a plain ``dict`` so results are easy to inspect in tests, CLI
  scripts, and the Alembic ``env.py`` pre-upgrade guard.
* Tolerates historical tuple ``down_revision`` values on merge revisions
  (e.g. ``down_revision = ('abc123', 'def456')``).  Those are not counted as
  multiple roots; only ``down_revision = None`` designates a root.

Requirements: 1.5, 7.1, 7.4, 7.5
"""
from __future__ import annotations

import ast
import os
from typing import Any


def _parse_revision_metadata(filepath: str) -> dict[str, Any] | None:
    """Parse a single Alembic revision file and return its key fields.

    Returns a dict with keys:
      ``revision``      – str revision identifier
      ``down_revision`` – None, str, or tuple[str, ...] (raw value from source)

    Returns ``None`` if the file cannot be parsed or lacks a ``revision``
    assignment (e.g. ``env.py``, ``script.py.mako``).
    """
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source, filename=filepath)
    except (OSError, SyntaxError):
        return None

    revision_val: str | None = None
    _SENTINEL = object()
    down_revision_val: Any = _SENTINEL

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id

            if name == "revision" and revision_val is None:
                val = _eval_literal(node.value)
                if isinstance(val, str):
                    revision_val = val

            elif name == "down_revision" and down_revision_val is _SENTINEL:
                val = _eval_literal(node.value)
                # Acceptable values: None, a str, a tuple of str
                if val is None or isinstance(val, str) or isinstance(val, tuple):
                    down_revision_val = val

    if revision_val is None:
        return None

    # If we never saw a down_revision assignment treat it as missing/None
    if down_revision_val is _SENTINEL:
        down_revision_val = None

    return {
        "revision": revision_val,
        "down_revision": down_revision_val,
    }


def _eval_literal(node: ast.expr) -> Any:
    """Safely evaluate an AST node that should be a literal constant.

    Handles:
    * ``ast.Constant`` (Python 3.8+) — str, int, None, bool
    * ``ast.Tuple`` — recursively evaluate elements
    * Legacy ``ast.Str`` / ``ast.Num`` / ``ast.NameConstant`` nodes
      (Python < 3.8 AST)

    Unrecognised node types return a sentinel ``_UNKNOWN`` string so the
    caller knows the value was present but not decodable as a literal.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        elts = [_eval_literal(e) for e in node.elts]
        return tuple(elts)
    # Python < 3.8 compatibility (rarely needed, but keep for safety)
    if isinstance(node, ast.Str):  # type: ignore[attr-defined]
        return node.s  # type: ignore[attr-defined]
    if isinstance(node, ast.Num):  # type: ignore[attr-defined]
        return node.n  # type: ignore[attr-defined]
    if isinstance(node, ast.NameConstant):  # type: ignore[attr-defined]
        return node.value  # type: ignore[attr-defined]
    return "_UNKNOWN"


def assert_single_head_and_root(versions_dir: str | None = None) -> dict[str, Any]:
    """Scan the Alembic versions directory and compute head/root counts.

    Parameters
    ----------
    versions_dir:
        Absolute path to the ``versions/`` directory that contains the Alembic
        revision ``.py`` files.  When ``None`` the function resolves the path
        relative to this module:
        ``<repo>/backend/alembic_migrations/versions/``

    Returns
    -------
    dict with the following keys:

    ``head_count``      – int   – number of revisions that are not referenced
                                  as ``down_revision`` by any other revision.
    ``head_revisions``  – list[str] – revision identifiers of those heads.
    ``root_count``      – int   – number of revisions whose own
                                  ``down_revision`` is ``None``.
    ``root_revisions``  – list[str] – revision identifiers of those roots.

    Algorithm
    ---------
    1. Parse every ``.py`` file in *versions_dir* for ``revision`` and
       ``down_revision`` module-level assignments.
    2. Collect the set of all revision identifiers (*all_revisions*).
    3. Collect the set of all identifiers that appear as a predecessor in some
       other revision's ``down_revision`` (*referenced*).
       - Tuple ``down_revision`` values (merge revisions) contribute all
         elements of the tuple to *referenced*.
       - ``None`` and string ``'None'`` are not counted as a referenced id.
    4. **Heads** = *all_revisions* − *referenced*.
    5. **Roots** = revisions whose ``down_revision`` is ``None`` (Python None)
       or the string ``'None'`` (historical typo sometimes present in old
       revision files).

    Note: this function does **not** call ``SystemExit``.  It is the caller's
    responsibility to act on ``head_count != 1`` or ``root_count != 1``.

    Requirements: 1.5, 7.1, 7.4, 7.5
    """
    if versions_dir is None:
        # Resolve default: this file lives at backend/app/migration_utils.py
        # so two levels up is backend/, then alembic_migrations/versions/
        _app_dir = os.path.dirname(os.path.abspath(__file__))
        _backend_dir = os.path.dirname(_app_dir)
        versions_dir = os.path.join(_backend_dir, "alembic_migrations", "versions")

    # ------------------------------------------------------------------ #
    # Step 1 – parse all revision files                                   #
    # ------------------------------------------------------------------ #
    revisions: dict[str, Any] = {}  # revision_id -> metadata dict

    try:
        entries = os.listdir(versions_dir)
    except OSError:
        # If the directory doesn't exist or can't be read, return empty counts
        return {
            "head_count": 0,
            "head_revisions": [],
            "root_count": 0,
            "root_revisions": [],
        }

    for filename in entries:
        if not filename.endswith(".py") or filename.startswith("__"):
            continue
        filepath = os.path.join(versions_dir, filename)
        meta = _parse_revision_metadata(filepath)
        if meta is None:
            continue
        rev_id = meta["revision"]
        revisions[rev_id] = meta

    # ------------------------------------------------------------------ #
    # Step 2+3 – build the referenced set                                 #
    # ------------------------------------------------------------------ #
    all_revision_ids: set[str] = set(revisions.keys())
    referenced: set[str] = set()

    for meta in revisions.values():
        dr = meta["down_revision"]
        if dr is None:
            continue
        if isinstance(dr, str):
            if dr != "None":
                referenced.add(dr)
        elif isinstance(dr, tuple):
            for element in dr:
                if isinstance(element, str) and element != "None":
                    referenced.add(element)

    # ------------------------------------------------------------------ #
    # Step 4 – heads = revisions not referenced by any other revision     #
    # ------------------------------------------------------------------ #
    head_ids = sorted(all_revision_ids - referenced)

    # ------------------------------------------------------------------ #
    # Step 5 – roots = revisions with down_revision None or 'None'        #
    # ------------------------------------------------------------------ #
    root_ids: list[str] = []
    for rev_id, meta in revisions.items():
        dr = meta["down_revision"]
        if dr is None or dr == "None":
            root_ids.append(rev_id)
    root_ids = sorted(root_ids)

    return {
        "head_count": len(head_ids),
        "head_revisions": head_ids,
        "root_count": len(root_ids),
        "root_revisions": root_ids,
    }
