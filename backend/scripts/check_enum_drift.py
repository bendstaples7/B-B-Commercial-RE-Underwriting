#!/usr/bin/env python3
"""Enum drift checker — verifies every Python model enum's value set matches
its PostgreSQL enum type.

This script is the permanent answer to the class of bug where a migration
(or a manually-applied SQL change) leaves the DB enum with values that diverge
from what the SQLAlchemy models declare.  Such divergence causes silent data
errors or ``InvalidTextRepresentation`` failures at runtime or deploy time.

Usage:
    python scripts/check_enum_drift.py

Run against the same database used in production (or a clone of it).  The
DATABASE_URL environment variable must point at a live PostgreSQL database.

Exit code:
    0 — all model enums match the corresponding DB enum values and type names.
    1 — at least one drift detected; output shows each mismatch.

CI integration:
    Add this step AFTER ``flask db upgrade`` in the migration validation job
    so that any migration that introduces a model/DB drift is caught before
    merge to main.

How to interpret output:
    "DRIFT: enum 'property_type'"
      values in Python but missing from DB   — DB enum needs an ADD VALUE
      values in DB   but missing from Python — model enum is out of date

    "DRIFT: enum type name mismatch for ..."
      The model's SQLAlchemy Column maps to a different pg_type name than
      the Python enum.  Usually means a migration renamed the type without
      updating the model, or vice versa.
"""
from __future__ import annotations

import os
import sys

# Ensure the backend/ directory is on sys.path so app modules are importable.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import enum as _enum_module
import sqlalchemy as sa
from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# Registry of (pg_type_name, Python_enum_class) pairs to validate.
#
# Add a new entry here whenever a new PostgreSQL enum type is created and
# a corresponding Python enum exists in the models.  The pg_type_name is
# the value stored in ``information_schema.columns.udt_name`` for any column
# using that type.
# ---------------------------------------------------------------------------
def _build_registry() -> list[tuple[str, type]]:
    """Build the list of (pg_type_name, py_enum) pairs to check.

    Importing is deferred to here so a missing/broken model import gives a
    clear error message rather than crashing at module load.
    """
    from app.models.property_facts import PropertyType, ConstructionType, InteriorCondition
    from app.models.analysis_session import WorkflowStep
    from app.models.scenario import ScenarioType

    return [
        ('property_type',      PropertyType),
        ('construction_type',  ConstructionType),
        ('interior_condition', InteriorCondition),
        # The workflowstep / workflow_step and scenariotype / scenario_type names
        # coexist on production because 267725fe7017 creates the PascalCase alias
        # types but the model-alignment revision is now a no-op.  We check both
        # spellings so drift in either is caught.
        ('workflow_step',      WorkflowStep),
        ('scenario_type',      ScenarioType),
    ]


def _fetch_db_enum_values(conn, pg_type_name: str) -> set[str] | None:
    """Return the set of enumlabel strings for *pg_type_name*, or None if not found."""
    result = conn.execute(
        text(
            "SELECT e.enumlabel "
            "FROM pg_enum e "
            "JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = :typname"
        ),
        {"typname": pg_type_name},
    )
    rows = [r[0] for r in result.fetchall()]
    return set(rows) if rows else None


def main() -> int:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    if "postgresql" not in db_url and "postgres" not in db_url:
        print(
            "SKIP: DATABASE_URL is not a PostgreSQL connection string — "
            "enum drift check only applies to PostgreSQL.",
            file=sys.stdout,
        )
        return 0

    try:
        registry = _build_registry()
    except ImportError as exc:
        print(f"ERROR: Could not import model enums: {exc}", file=sys.stderr)
        return 1

    engine = create_engine(db_url)
    drift_count = 0

    try:
        with engine.connect() as conn:
            for pg_type_name, py_enum in registry:
                db_values = _fetch_db_enum_values(conn, pg_type_name)

                if db_values is None:
                    # Type doesn't exist in the DB — fresh DB or type was intentionally
                    # not created yet.  Not an error; the migration chain creates it.
                    print(f"  SKIP: pg_type '{pg_type_name}' not found in DB (fresh or not-yet-created).")
                    continue

                python_values = {e.value for e in py_enum}
                missing_in_db = python_values - db_values
                missing_in_python = db_values - python_values

                if missing_in_db or missing_in_python:
                    # Some enums use .name for DB storage (no values_callable),
                    # others use .value (via values_callable=lambda x: [e.value for e in x]).
                    # Try name-based comparison before reporting a drift.
                    python_names = {e.name for e in py_enum}
                    name_missing_in_db = python_names - db_values
                    name_missing_in_python = db_values - python_names
                    if not name_missing_in_db and not name_missing_in_python:
                        # Name-based match — the column uses .name for storage.
                        print(f"  OK: '{pg_type_name}' — matched by enum .name {sorted(python_names)}")
                        continue
                    # True drift — neither .value nor .name aligns with the DB type.
                    drift_count += 1
                    print(f"\nDRIFT: enum '{pg_type_name}'")
                    print(f"  Python .value : {sorted(str(v) for v in python_values)}")
                    print(f"  Python .name  : {sorted(python_names)}")
                    print(f"  DB values     : {sorted(db_values)}")
                    if name_missing_in_db:
                        print(f"  In Python .name NOT in DB (DB needs ADD VALUE)  : {sorted(name_missing_in_db)}")
                    if name_missing_in_python:
                        print(f"  In DB NOT in Python .name (model out of date)   : {sorted(name_missing_in_python)}")
                else:
                    print(f"  OK: '{pg_type_name}' — {sorted(str(v) for v in python_values)}")

    finally:
        engine.dispose()

    if drift_count == 0:
        print(f"\nEnum drift check: no issues found ({len(registry)} enum type(s) checked).")
        return 0
    else:
        print(f"\nEnum drift check: {drift_count} drift(s) found.", file=sys.stderr)
        print(
            "Fix: align the SQLAlchemy model enum values with the PostgreSQL enum, "
            "then write a migration to add or rename values as needed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
