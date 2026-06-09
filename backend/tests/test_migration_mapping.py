"""test_migration_mapping.py — Assert the baseline-replacement mapping is complete.

Tests that:
  1. Every revision file in ``backend/alembic_migrations/versions/`` has its
     revision ID present in the ``_KNOWN_REVISIONS`` set defined in ``env.py``
     (Req 9.2, 9.3 — no unmapped revision remains).
  2. The ``_KNOWN_REVISIONS`` set covers every actual revision file — no revision
     file has an ID missing from the set (Req 9.3).
  3. An unrecognized recorded revision triggers the documented halt: calling
     ``_assert_known_start_revision`` with a revision ID not in ``_KNOWN_REVISIONS``
     causes ``sys.exit(1)`` (Req 9.5).
  4. The documentation (``alembic_migrations/README.md``) mentions the
     ``flask db stamp b3c4d5e6f7a1`` command format (Req 9.4).

Run with:
    cd backend && python -m pytest tests/test_migration_mapping.py -v
"""
from __future__ import annotations

import ast as _ast
import logging as _logging
import os
import sys

import pytest


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _backend_dir() -> str:
    """Return the absolute path to the ``backend/`` directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _versions_dir() -> str:
    """Return the absolute path to ``backend/alembic_migrations/versions/``."""
    return os.path.join(_backend_dir(), "alembic_migrations", "versions")


def _env_py_path() -> str:
    """Return the absolute path to ``backend/alembic_migrations/env.py``."""
    return os.path.join(_backend_dir(), "alembic_migrations", "env.py")


def _readme_path() -> str:
    """Return the absolute path to ``backend/alembic_migrations/README.md``."""
    return os.path.join(_backend_dir(), "alembic_migrations", "README.md")


# ---------------------------------------------------------------------------
# Import helpers — env.py cannot be imported directly (it runs migration code
# at module load that needs a Flask app + DB), so we parse/extract pieces.
# ---------------------------------------------------------------------------

def _import_parse_revision_metadata():
    """Import ``_parse_revision_metadata`` from ``app.migration_utils``."""
    from app.migration_utils import _parse_revision_metadata
    return _parse_revision_metadata


def _load_known_revisions() -> frozenset:
    """Parse ``_KNOWN_REVISIONS`` from ``env.py`` without executing the module."""
    import re
    with open(_env_py_path(), "r", encoding="utf-8") as fh:
        source = fh.read()
    match = re.search(r"_KNOWN_REVISIONS\s*=\s*frozenset\(\{([^}]+)\}\)", source, re.DOTALL)
    if not match:
        raise RuntimeError(
            f"Could not locate '_KNOWN_REVISIONS = frozenset({{...}})' in {_env_py_path()}"
        )
    revision_ids = re.findall(r"'([^']+)'", match.group(1))
    return frozenset(revision_ids)


def _extract_source_block(source: str, predicate) -> str | None:
    """Return the source text of the first top-level node matching *predicate*."""
    lines = source.splitlines()
    tree = _ast.parse(source, filename=_env_py_path())
    for node in _ast.walk(tree):
        if predicate(node):
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return None


def _load_assert_known_start_revision():
    """Extract and exec ``_assert_known_start_revision`` + ``_KNOWN_REVISIONS``
    from env.py source, returning the callable.

    This avoids importing env.py (which runs migration bootstrap at import).
    """
    with open(_env_py_path(), "r", encoding="utf-8") as fh:
        source = fh.read()

    known_block = _extract_source_block(
        source,
        lambda n: isinstance(n, _ast.Assign)
        and any(isinstance(t, _ast.Name) and t.id == "_KNOWN_REVISIONS" for t in n.targets),
    )
    func_block = _extract_source_block(
        source,
        lambda n: isinstance(n, _ast.FunctionDef) and n.name == "_assert_known_start_revision",
    )
    assert known_block is not None, "_KNOWN_REVISIONS not found in env.py"
    assert func_block is not None, (
        "_assert_known_start_revision not found in env.py — guard helper may have been renamed."
    )

    namespace: dict = {
        "logging": _logging,
        "os": os,
        "sys": sys,
        "logger": _logging.getLogger("alembic.env"),
    }
    exec(compile(known_block + "\n\n" + func_block, _env_py_path(), "exec"), namespace)  # noqa: S102
    return namespace["_assert_known_start_revision"]


def _collect_file_revision_ids() -> dict:
    """Return a mapping of {revision_id: filename} for all revision files."""
    parse = _import_parse_revision_metadata()
    versions = _versions_dir()
    result: dict = {}
    for filename in sorted(os.listdir(versions)):
        if not filename.endswith(".py") or filename.startswith("__"):
            continue
        meta = parse(os.path.join(versions, filename))
        if meta is None:
            continue
        result[meta["revision"]] = filename
    return result


# ---------------------------------------------------------------------------
# Test 1: every revision file ID is in _KNOWN_REVISIONS
# ---------------------------------------------------------------------------

class TestAllRevisionFilesAreMapped:
    """Every revision file in versions/ must appear in _KNOWN_REVISIONS (Req 9.2, 9.3)."""

    def test_every_file_revision_id_in_known_revisions(self):
        known = _load_known_revisions()
        file_revisions = _collect_file_revision_ids()
        unmapped = {
            rev_id: filename
            for rev_id, filename in file_revisions.items()
            if rev_id not in known
        }
        assert not unmapped, (
            "The following revision IDs are present in files but MISSING from "
            "_KNOWN_REVISIONS in env.py — add them to fix:\n"
            + "\n".join(f"  revision='{r}'  file='{f}'" for r, f in sorted(unmapped.items()))
        )

    def test_versions_directory_contains_revision_files(self):
        assert len(_collect_file_revision_ids()) > 0, (
            f"No revision files found in {_versions_dir()}"
        )

    @pytest.mark.parametrize("rev_id,filename", sorted(_collect_file_revision_ids().items()))
    def test_parametrized_each_revision_in_known_set(self, rev_id, filename):
        known = _load_known_revisions()
        assert rev_id in known, (
            f"Revision ID '{rev_id}' (from file '{filename}') is not in _KNOWN_REVISIONS."
        )


# ---------------------------------------------------------------------------
# Test 2: _KNOWN_REVISIONS covers every actual revision file
# ---------------------------------------------------------------------------

class TestKnownRevisionsSetIsAccurate:
    """The _KNOWN_REVISIONS set must account for every actual revision file (Req 9.3)."""

    def test_known_revisions_set_is_nonempty(self):
        assert len(_load_known_revisions()) > 0

    def test_known_revisions_covers_baseline_ids(self):
        known = _load_known_revisions()
        required = {"000000000000", "267725fe7017", "b3c4d5e6f7a1"}
        missing = required - known
        assert not missing, f"Missing baseline IDs from _KNOWN_REVISIONS: {missing}"

    def test_known_revisions_includes_consolidation_revisions(self):
        known = _load_known_revisions()
        assert "a2b3c4d5e6f7" in known
        assert "b3c4d5e6f7a1" in known

    def test_all_file_revisions_covered_by_known_set(self):
        known = _load_known_revisions()
        file_revisions = _collect_file_revision_ids()
        not_covered = set(file_revisions) - known
        assert not not_covered, (
            "Revision IDs in files but NOT in _KNOWN_REVISIONS:\n"
            + "\n".join(f"  '{r}'  (file: '{file_revisions[r]}')" for r in sorted(not_covered))
        )


# ---------------------------------------------------------------------------
# Test 3: unrecognized recorded revision triggers sys.exit(1)
# ---------------------------------------------------------------------------

class TestUnrecognizedRevisionTriggersHalt:
    """An unrecognized recorded revision must trigger a halt (sys.exit(1)) — Req 9.5."""

    def test_unrecognized_revision_calls_sys_exit(self):
        assert_known = _load_assert_known_start_revision()
        fake_rev = "deadbeef0000"
        assert fake_rev not in _load_known_revisions()
        with pytest.raises(SystemExit) as exc_info:
            assert_known([fake_rev])
        assert exc_info.value.code == 1

    def test_unrecognized_revision_another_fake_id(self):
        assert_known = _load_assert_known_start_revision()
        fake_rev = "ffffffffffff_not_real"
        assert fake_rev not in _load_known_revisions()
        with pytest.raises(SystemExit) as exc_info:
            assert_known([fake_rev])
        assert exc_info.value.code == 1

    def test_known_revision_does_not_trigger_halt(self):
        assert_known = _load_assert_known_start_revision()
        # A known revision must pass through cleanly (no SystemExit).
        assert_known(["b3c4d5e6f7a1"])

    def test_empty_heads_does_not_trigger_halt(self):
        assert_known = _load_assert_known_start_revision()
        # Fresh DB (no recorded revision) must not halt.
        assert_known([])


# ---------------------------------------------------------------------------
# Test 4: stamp command format is documented
# ---------------------------------------------------------------------------

class TestStampCommandDocumented:
    """The README must document the ``flask db stamp b3c4d5e6f7a1`` command (Req 9.4)."""

    def _read_readme(self) -> str:
        path = _readme_path()
        assert os.path.exists(path), f"README not found at {path}"
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_readme_mentions_stamp_command(self):
        assert "flask db stamp b3c4d5e6f7a1" in self._read_readme(), (
            "README.md does not contain 'flask db stamp b3c4d5e6f7a1'."
        )

    def test_readme_explains_stamp_does_not_apply_schema_changes(self):
        content = self._read_readme().lower()
        assert "no schema changes" in content or "only the recorded revision" in content, (
            "README.md does not explain that stamping applies no schema changes."
        )

    def test_readme_contains_known_revisions_list(self):
        content = self._read_readme()
        for rev in ("000000000000", "267725fe7017", "b3c4d5e6f7a1"):
            assert rev in content, f"README.md does not mention baseline revision '{rev}'."
