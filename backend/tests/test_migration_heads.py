"""
test_migration_heads.py — Guard against branched Alembic migration chains.

This test fails immediately if the migration graph has more than one head,
which means two migration files share the same down_revision and Alembic
cannot determine which to apply first.  A branched chain causes the app
startup check (_assert_single_migration_head) to abort the server.

Run with:  cd backend && pytest tests/test_migration_heads.py -v
"""
import os
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory


def _get_alembic_script_dir() -> ScriptDirectory:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    migrations_dir = os.path.join(backend_dir, 'alembic_migrations')
    cfg = Config()
    cfg.set_main_option('script_location', migrations_dir)
    return ScriptDirectory.from_config(cfg)


def test_migration_chain_has_single_head():
    """The Alembic migration graph must have exactly one head.

    Multiple heads mean two migration files share the same down_revision,
    creating a branch that `upgrade head` cannot resolve automatically.
    This causes the Flask app to refuse to start.

    If this test fails:
      1. Run: cd backend && python -m flask --app app db heads
      2. Identify which revision IDs are duplicated
      3. Rename the duplicate revision in one file to a new unique ID
      4. Create a merge migration: flask db merge -m "merge branches" <rev1> <rev2>
    """
    script = _get_alembic_script_dir()
    heads = script.get_heads()

    assert len(heads) == 1, (
        f"Migration chain has {len(heads)} heads: {heads}\n"
        "Two or more migration files share the same down_revision.\n"
        "Fix: rename the duplicate revision ID in one file, then create a "
        "merge migration with `flask db merge -m 'merge branches' <rev1> <rev2>`."
    )


def test_migration_revisions_are_unique():
    """Every migration file must have a unique revision ID.

    Duplicate revision IDs cause Alembic to emit warnings and produce
    a branched graph.  This test catches the problem at the file level
    before Alembic even tries to resolve the chain.
    """
    script = _get_alembic_script_dir()
    seen = {}
    duplicates = []

    for rev in script.walk_revisions():
        if rev.revision in seen:
            duplicates.append(
                f"  revision '{rev.revision}' appears in both "
                f"'{seen[rev.revision]}' and '{rev.doc}'"
            )
        else:
            seen[rev.revision] = rev.doc

    assert not duplicates, (
        "Duplicate revision IDs found:\n" + "\n".join(duplicates) + "\n"
        "Rename the duplicate revision in one of the listed files to a new unique ID."
    )
