"""test_migration_mapping.py — Assert the baseline-replacement mapping is complete.

Tests that:
  1. Every revision file in ``backend/alembic_migrations/versions/`` has its
     revision ID present in the ``_KNOWN_REVISIONS`` set defined in ``env.py``
     (Req 9.2, 9.3 — no unmapped revision remains).
  2. The ``_KNOWN_REVISIONS`` set covers every actual revision file — no revision
     file has an ID missing from the set (Req 9.3).
  3. An unrecognized recorded revision triggers the documented halt: calling
     ``_run_pre_upgrade_guards`` with a fake revision ID not in ``_KNOWN_REVISIONS``
     causes ``sys.exit(1)`` (Req 9.5).
  4. The documentation (``alembic_migrations/README.md``) mentions the
     ``flask db stamp b3c4d5e6f7a1`` command format (Req 9.4).

Run with:
    cd backend && python -m pytest tests/test_migration_mapping.py -v
"""
from __future__ import annotations

import os
import sys
import types
import unittest.mock as mock

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
# Import helpers — avoid triggering the full Alembic env.py (which requires
# a Flask app + DB connection) by importing only the pieces we need.
# ---------------------------------------------------------------------------

def _import_parse_revision_metadata():
    """Import ``_parse_revision_metadata`` from ``app.migration_utils``."""
    # app/ is already importable because backend/ is on sys.path for tests.
    from app.migration_utils import _parse_revision_metadata
    return _parse_revision_metadata


def _load_known_revisions() -> frozenset:
    """Parse ``_KNOWN_REVISIONS`` from ``env.py`` without executing the module.

    ``env.py`` imports Flask internals and connects to a database when executed
    normally.  We parse out just the ``_KNOWN_REVISIONS`` frozenset using the
    AST-based ``_parse_revision_metadata`` approach but for the env.py source,
    rather than importing it directly.

    Strategy: exec only the relevant assignment by extracting the lines between
    ``_KNOWN_REVISIONS = frozenset({`` and the closing ``})``, then eval in a
    clean namespace.
    """
    import ast
    import re

    env_path = _env_py_path()
    with open(env_path, "r", encoding="utf-8") as fh:
        source = fh.read()

    # Locate the frozenset literal via a simple regex scan.
    # Pattern: _KNOWN_REVISIONS = frozenset({ ... })
    # We extract everything between the first frozenset({ and the matching })
    match = re.search(r"_KNOWN_REVISIONS\s*=\s*frozenset\(\{([^}]+)\}\)", source, re.DOTALL)
    if not match:
        raise RuntimeError(
            f"Could not locate '_KNOWN_REVISIONS = frozenset({{...}})' in {env_path}"
        )

    inner = match.group(1)
    # Parse the comma-separated quoted strings into a Python set
    revision_ids = re.findall(r"'([^']+)'", inner)
    return frozenset(revision_ids)


def _collect_file_revision_ids() -> dict[str, str]:
    """Return a mapping of {revision_id: filename} for all revision files.

    Uses ``_parse_revision_metadata`` to extract the ``revision`` variable
    from each ``.py`` file in the ``versions/`` directory.
    """
    parse = _import_parse_revision_metadata()
    versions = _versions_dir()
    result: dict[str, str] = {}

    for filename in sorted(os.listdir(versions)):
        if not filename.endswith(".py") or filename.startswith("__"):
            continue
        filepath = os.path.join(versions, filename)
        meta = parse(filepath)
        if meta is None:
            continue
        rev_id = meta["revision"]
        result[rev_id] = filename

    return result


# ---------------------------------------------------------------------------
# Test 1: every revision file ID is in _KNOWN_REVISIONS
# ---------------------------------------------------------------------------

class TestAllRevisionFilesAreMapped:
    """Every revision file in versions/ must appear in _KNOWN_REVISIONS.

    Req 9.2, 9.3 — no pre-consolidation revision may remain unmapped.
    """

    def test_every_file_revision_id_in_known_revisions(self):
        """Each revision ID found in a .py file is present in _KNOWN_REVISIONS.

        If this fails, a newly-added revision file was not added to the
        _KNOWN_REVISIONS set in env.py.  Add the new revision ID to
        _KNOWN_REVISIONS to fix.
        """
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
            + "\n".join(
                f"  revision='{rev_id}'  file='{fname}'"
                for rev_id, fname in sorted(unmapped.items())
            )
        )

    def test_versions_directory_contains_revision_files(self):
        """The versions/ directory exists and contains at least one revision file.

        Guards against a misconfigured path returning a false-positive empty set.
        """
        file_revisions = _collect_file_revision_ids()
        assert len(file_revisions) > 0, (
            f"No revision files found in {_versions_dir()} — "
            "check the versions/ directory path."
        )

    @pytest.mark.parametrize("rev_id,filename", sorted(_collect_file_revision_ids().items()))
    def test_parametrized_each_revision_in_known_set(self, rev_id, filename):
        """Parametrized: each individual revision file ID is in _KNOWN_REVISIONS.

        Req 9.3 — no unmapped revision remains.
        """
        known = _load_known_revisions()
        assert rev_id in known, (
            f"Revision ID '{rev_id}' (from file '{filename}') is not in "
            f"_KNOWN_REVISIONS in env.py.\n"
            f"Add '{rev_id}' to the _KNOWN_REVISIONS frozenset to fix."
        )


# ---------------------------------------------------------------------------
# Test 2: _KNOWN_REVISIONS covers every actual revision file
# ---------------------------------------------------------------------------

class TestKnownRevisionsSetIsAccurate:
    """The _KNOWN_REVISIONS set must account for every actual revision file.

    Req 9.3 — the mapping must account for all pre-consolidation revisions
    with no unmapped revision remaining.

    Note: _KNOWN_REVISIONS MAY contain IDs that have no corresponding file
    (e.g. historical aliases documented in the README), but every FILE must
    be covered.  This is the same check as Test 1 from the opposite direction.
    """

    def test_known_revisions_set_is_nonempty(self):
        """_KNOWN_REVISIONS must contain at least the baseline revision IDs."""
        known = _load_known_revisions()
        assert len(known) > 0, (
            "_KNOWN_REVISIONS is empty — the frozenset in env.py could not be "
            "parsed or contains no entries."
        )

    def test_known_revisions_covers_baseline_ids(self):
        """_KNOWN_REVISIONS must include the root and squash-marker revisions."""
        known = _load_known_revisions()
        required = {"000000000000", "267725fe7017", "b3c4d5e6f7a1"}
        missing = required - known
        assert not missing, (
            f"These baseline revision IDs are missing from _KNOWN_REVISIONS: "
            f"{missing}"
        )

    def test_known_revisions_includes_consolidation_revisions(self):
        """_KNOWN_REVISIONS must include the new consolidation revision IDs."""
        known = _load_known_revisions()
        # a2b3c4d5e6f7 = model_alignment, b3c4d5e6f7a1 = squash_marker
        assert "a2b3c4d5e6f7" in known, (
            "Consolidation revision 'a2b3c4d5e6f7' (model_alignment) is missing "
            "from _KNOWN_REVISIONS."
        )
        assert "b3c4d5e6f7a1" in known, (
            "Consolidation revision 'b3c4d5e6f7a1' (squash_marker / head) is "
            "missing from _KNOWN_REVISIONS."
        )

    def test_all_file_revisions_covered_by_known_set(self):
        """No revision file has an ID that is absent from _KNOWN_REVISIONS.

        This is the set-containment check: file_revision_ids ⊆ _KNOWN_REVISIONS.
        """
        known = _load_known_revisions()
        file_revisions = _collect_file_revision_ids()
        file_ids = set(file_revisions.keys())

        not_covered = file_ids - known
        assert not not_covered, (
            f"The following revision IDs exist in files but are NOT in "
            f"_KNOWN_REVISIONS:\n"
            + "\n".join(
                f"  '{rev_id}'  (file: '{file_revisions[rev_id]}')"
                for rev_id in sorted(not_covered)
            )
        )


# ---------------------------------------------------------------------------
# Test 3: unrecognized recorded revision triggers sys.exit(1)
# ---------------------------------------------------------------------------

class TestUnrecognizedRevisionTriggersHalt:
    """An unrecognized recorded revision must trigger a halt (sys.exit(1)).

    Req 9.5 — if the upgrade path is executed against a DB whose recorded
    revision is not in the documented mapping, the upgrade guard halts before
    any schema change and emits an error identifying the unrecognized revision.
    """

    def _make_mock_connection(self, recorded_revision: str):
        """Return a mock DB connection whose get_current_heads() returns the given revision."""
        mock_conn = mock.MagicMock()
        # AlembicMigrationContext.configure(connection) is called inside the guard.
        # We patch AlembicMigrationContext.configure to return an object whose
        # get_current_heads() yields our fake revision.
        mock_mc = mock.MagicMock()
        mock_mc.get_current_heads.return_value = (recorded_revision,)
        return mock_conn, mock_mc

    def _call_run_pre_upgrade_guards_with_fake_revision(self, fake_revision: str):
        """Invoke ``_run_pre_upgrade_guards`` with a connection that reports
        ``fake_revision`` as the current recorded revision.

        Patches:
          - ``alembic_migrations.env.AlembicMigrationContext.configure`` to return
            a mock whose ``get_current_heads()`` returns the fake revision.
          - ``alembic_migrations.env.assert_single_head_and_root`` to return a
            valid (head_count=1, root_count=1) result so the first guard passes
            and only the start-revision guard fires.

        Returns the ``SystemExit`` raised, or raises ``AssertionError`` if
        ``sys.exit`` was not called.
        """
        # We need to import _run_pre_upgrade_guards from env.py without executing
        # the module-level code (which connects to a DB).  We do this by
        # exec-importing the function in isolation.
        #
        # Strategy: load env.py source, compile it, then extract just the function
        # we need by exec-ing it into a controlled namespace.
        env_path = _env_py_path()
        with open(env_path, "r", encoding="utf-8") as fh:
            source = fh.read()

        # Build a minimal namespace that satisfies the top-level imports env.py
        # needs just to define _run_pre_upgrade_guards.
        fake_module = types.ModuleType("alembic_migrations.env")
        fake_module.__file__ = env_path
        fake_module.__name__ = "alembic_migrations.env"

        # Provide stubs for the names that are used at module level before the
        # function definitions.  We only need enough to let the source compile and
        # for the function body to run.
        import logging as _logging

        stub_assert = mock.MagicMock(return_value={
            "head_count": 1, "root_count": 1,
            "head_revisions": [], "root_revisions": [],
        })

        mock_mc_instance = mock.MagicMock()
        mock_mc_instance.get_current_heads.return_value = (fake_revision,)
        stub_alembic_mc = mock.MagicMock()
        stub_alembic_mc.configure.return_value = mock_mc_instance

        namespace: dict = {
            # Standard library
            "logging": _logging,
            "os": os,
            "sys": sys,
            # Alembic stubs — just enough for the function body
            "AlembicMigrationContext": stub_alembic_mc,
            "assert_single_head_and_root": stub_assert,
            # The logger used inside the function
            "logger": _logging.getLogger("alembic.env"),
            # _KNOWN_REVISIONS — we inject the real one
            "_KNOWN_REVISIONS": _load_known_revisions(),
        }

        # Exec the source to populate the namespace with _run_pre_upgrade_guards
        # and _KNOWN_REVISIONS (our injection above will be overwritten by the
        # exec, which is fine — we want the real _KNOWN_REVISIONS from env.py).
        #
        # We cannot exec the full source (it tries to connect to DB at module
        # level), so we compile only up to and including the function definition.
        # Instead, use a targeted approach: extract the function source and exec it.
        import ast as _ast
        import inspect as _inspect

        tree = _ast.parse(source, filename=env_path)
        func_source_lines = []
        in_func = False
        source_lines = source.splitlines()

        # Find the _run_pre_upgrade_guards function definition using AST
        target_func_node = None
        for node in _ast.walk(tree):
            if isinstance(node, _ast.FunctionDef) and node.name == "_run_pre_upgrade_guards":
                target_func_node = node
                break

        if target_func_node is None:
            raise RuntimeError(
                "_run_pre_upgrade_guards not found in env.py — "
                "the guard function may have been renamed."
            )

        # Extract the function source by line numbers (AST gives 1-based line numbers)
        start_line = target_func_node.lineno - 1   # 0-based
        end_line = target_func_node.end_lineno      # exclusive in slice

        func_lines = source_lines[start_line:end_line]
        func_source = "\n".join(func_lines)

        # Also extract _KNOWN_REVISIONS assignment so the function sees the real set
        known_revisions_assignment = None
        for node in _ast.walk(tree):
            if (isinstance(node, _ast.Assign)
                    and any(
                        isinstance(t, _ast.Name) and t.id == "_KNOWN_REVISIONS"
                        for t in node.targets
                    )):
                kr_start = node.lineno - 1
                kr_end = node.end_lineno
                known_revisions_assignment = "\n".join(source_lines[kr_start:kr_end])
                break

        combined_source = (
            (known_revisions_assignment + "\n\n" if known_revisions_assignment else "")
            + func_source
        )

        exec(compile(combined_source, env_path, "exec"), namespace)  # noqa: S102

        guard_fn = namespace["_run_pre_upgrade_guards"]

        # Call the guard with a fake connection object.  The function will call
        # AlembicMigrationContext.configure(connection) which our stub intercepts.
        mock_connection = mock.MagicMock()

        with pytest.raises(SystemExit) as exc_info:
            guard_fn(connection=mock_connection)

        return exc_info.value

    def test_unrecognized_revision_calls_sys_exit(self):
        """Passing a fake revision to _run_pre_upgrade_guards causes sys.exit(1).

        Req 9.5 — the halt behavior must be triggered for any revision ID not
        present in _KNOWN_REVISIONS.
        """
        fake_rev = "deadbeef0000"
        known = _load_known_revisions()
        assert fake_rev not in known, (
            f"Test setup error: '{fake_rev}' is unexpectedly in _KNOWN_REVISIONS. "
            "Choose a different fake revision ID."
        )

        exc = self._call_run_pre_upgrade_guards_with_fake_revision(fake_rev)
        assert exc.code == 1, (
            f"Expected sys.exit(1) for unrecognized revision '{fake_rev}', "
            f"but got sys.exit({exc.code!r})."
        )

    def test_unrecognized_revision_another_fake_id(self):
        """A second distinct fake revision also triggers sys.exit(1).

        Guards against the halt being accidentally tied to a specific value.
        """
        fake_rev = "ffffffffffffffff_not_a_real_revision"
        known = _load_known_revisions()
        assert fake_rev not in known

        exc = self._call_run_pre_upgrade_guards_with_fake_revision(fake_rev)
        assert exc.code == 1

    def test_known_revision_does_not_trigger_halt(self):
        """A recognized revision does NOT cause sys.exit.

        Req 9.5 — the guard must only halt for *unrecognized* revisions.
        A revision that IS in _KNOWN_REVISIONS must pass through cleanly.
        """
        import logging as _logging
        import ast as _ast

        env_path = _env_py_path()
        with open(env_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        source_lines = source.splitlines()

        tree = _ast.parse(source, filename=env_path)

        # Extract _KNOWN_REVISIONS assignment
        known_revisions_assignment = None
        for node in _ast.walk(tree):
            if (isinstance(node, _ast.Assign)
                    and any(
                        isinstance(t, _ast.Name) and t.id == "_KNOWN_REVISIONS"
                        for t in node.targets
                    )):
                kr_start = node.lineno - 1
                kr_end = node.end_lineno
                known_revisions_assignment = "\n".join(source_lines[kr_start:kr_end])
                break

        # Extract _run_pre_upgrade_guards function
        target_func_node = None
        for node in _ast.walk(tree):
            if isinstance(node, _ast.FunctionDef) and node.name == "_run_pre_upgrade_guards":
                target_func_node = node
                break
        assert target_func_node is not None

        start_line = target_func_node.lineno - 1
        end_line = target_func_node.end_lineno
        func_source = "\n".join(source_lines[start_line:end_line])

        # Use a KNOWN revision — the squash marker head
        known_rev = "b3c4d5e6f7a1"

        mock_mc_instance = mock.MagicMock()
        mock_mc_instance.get_current_heads.return_value = (known_rev,)
        stub_alembic_mc = mock.MagicMock()
        stub_alembic_mc.configure.return_value = mock_mc_instance

        stub_assert = mock.MagicMock(return_value={
            "head_count": 1, "root_count": 1,
            "head_revisions": [], "root_revisions": [],
        })

        namespace: dict = {
            "logging": _logging,
            "os": os,
            "sys": sys,
            "AlembicMigrationContext": stub_alembic_mc,
            "assert_single_head_and_root": stub_assert,
            "logger": _logging.getLogger("alembic.env"),
        }

        combined_source = (
            (known_revisions_assignment + "\n\n" if known_revisions_assignment else "")
            + func_source
        )

        exec(compile(combined_source, env_path, "exec"), namespace)  # noqa: S102
        guard_fn = namespace["_run_pre_upgrade_guards"]

        mock_connection = mock.MagicMock()
        # Should NOT raise SystemExit — a known revision must pass through
        try:
            guard_fn(connection=mock_connection)
        except SystemExit:
            pytest.fail(
                f"_run_pre_upgrade_guards raised SystemExit for the known "
                f"revision '{known_rev}', but it should pass through cleanly."
            )

    def test_fresh_database_no_recorded_revision_does_not_trigger_halt(self):
        """A fresh DB (no recorded revision) must not trigger the halt.

        Req 9.5 only fires when there IS a recorded revision that is not in
        the mapping.  An empty/new database has no recorded revision and must
        proceed normally.
        """
        import logging as _logging
        import ast as _ast

        env_path = _env_py_path()
        with open(env_path, "r", encoding="utf-8") as fh:
            source = fh.read()
        source_lines = source.splitlines()

        tree = _ast.parse(source, filename=env_path)

        known_revisions_assignment = None
        for node in _ast.walk(tree):
            if (isinstance(node, _ast.Assign)
                    and any(
                        isinstance(t, _ast.Name) and t.id == "_KNOWN_REVISIONS"
                        for t in node.targets
                    )):
                kr_start = node.lineno - 1
                kr_end = node.end_lineno
                known_revisions_assignment = "\n".join(source_lines[kr_start:kr_end])
                break

        target_func_node = None
        for node in _ast.walk(tree):
            if isinstance(node, _ast.FunctionDef) and node.name == "_run_pre_upgrade_guards":
                target_func_node = node
                break
        assert target_func_node is not None

        start_line = target_func_node.lineno - 1
        end_line = target_func_node.end_lineno
        func_source = "\n".join(source_lines[start_line:end_line])

        # Fresh DB: get_current_heads returns empty tuple
        mock_mc_instance = mock.MagicMock()
        mock_mc_instance.get_current_heads.return_value = ()
        stub_alembic_mc = mock.MagicMock()
        stub_alembic_mc.configure.return_value = mock_mc_instance

        stub_assert = mock.MagicMock(return_value={
            "head_count": 1, "root_count": 1,
            "head_revisions": [], "root_revisions": [],
        })

        namespace: dict = {
            "logging": _logging,
            "os": os,
            "sys": sys,
            "AlembicMigrationContext": stub_alembic_mc,
            "assert_single_head_and_root": stub_assert,
            "logger": _logging.getLogger("alembic.env"),
        }

        combined_source = (
            (known_revisions_assignment + "\n\n" if known_revisions_assignment else "")
            + func_source
        )

        exec(compile(combined_source, env_path, "exec"), namespace)  # noqa: S102
        guard_fn = namespace["_run_pre_upgrade_guards"]

        mock_connection = mock.MagicMock()
        try:
            guard_fn(connection=mock_connection)
        except SystemExit:
            pytest.fail(
                "A fresh database (no recorded revision) should not trigger "
                "the unrecognized-revision halt, but sys.exit was called."
            )


# ---------------------------------------------------------------------------
# Test 4: stamp command format is documented
# ---------------------------------------------------------------------------

class TestStampCommandDocumented:
    """The README must document the ``flask db stamp b3c4d5e6f7a1`` command.

    Req 9.4 — the documentation must specify the exact stamp command, the
    assumed starting revision, and that stamping changes only the recorded
    revision.
    """

    def _read_readme(self) -> str:
        path = _readme_path()
        assert os.path.exists(path), (
            f"README not found at {path} — the documentation file is missing."
        )
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_readme_mentions_stamp_command(self):
        """README.md contains the ``flask db stamp b3c4d5e6f7a1`` command.

        Req 9.4 — the exact stamp command must be documented.
        """
        content = self._read_readme()
        assert "flask db stamp b3c4d5e6f7a1" in content, (
            "README.md does not contain the stamp command "
            "'flask db stamp b3c4d5e6f7a1'.\n"
            f"README path: {_readme_path()}"
        )

    def test_readme_explains_stamp_does_not_apply_schema_changes(self):
        """README.md must state that stamping does not apply schema changes.

        Req 9.4 — the documentation must clarify the stamp operation only
        alters the recorded revision and applies no schema changes.
        """
        content = self._read_readme().lower()
        # Look for language explaining no schema changes
        assert "no schema changes" in content or "only the recorded revision" in content, (
            "README.md does not explain that stamping applies no schema changes "
            "and only changes the recorded revision.\n"
            f"README path: {_readme_path()}"
        )

    def test_readme_contains_known_revisions_list(self):
        """README.md must list the known revision IDs for the upgrade guard.

        Req 9.3 — every revision constituting the consolidated baseline must
        be listed, with no unmapped revision remaining.
        """
        content = self._read_readme()
        # At minimum the three baseline/head revisions must appear
        for rev in ("000000000000", "267725fe7017", "b3c4d5e6f7a1"):
            assert rev in content, (
                f"README.md does not mention baseline revision '{rev}'.\n"
                f"README path: {_readme_path()}"
            )
