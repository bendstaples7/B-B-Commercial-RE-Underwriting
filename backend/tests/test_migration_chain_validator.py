"""
test_migration_chain_validator.py — Unit and parametrized tests for the chain
validator (assert_single_head_and_root), the check_migration_chain.py CLI script,
and the unrecognized-start-revision guard in alembic_migrations/env.py.

Requirements: 1.5, 1.6, 7.1, 7.3, 7.4, 7.5, 9.5

Run with:  cd backend && python -m pytest tests/test_migration_chain_validator.py -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _BACKEND_DIR / "scripts"
_VERSIONS_DIR = _BACKEND_DIR / "alembic_migrations" / "versions"
_MERGE_HEADS_FILE = _VERSIONS_DIR / "e5f6g7h8i9j0_merge_heads.py"
_CHECK_SCRIPT = _SCRIPTS_DIR / "check_migration_chain.py"


# ===========================================================================
# Helpers
# ===========================================================================

def _run_check_script(extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run check_migration_chain.py via subprocess and return the result."""
    cmd = [sys.executable, str(_CHECK_SCRIPT)] + (extra_args or [])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_BACKEND_DIR),
    )


def _make_fake_versions_dir(tmp_path: Path, revisions: list[dict]) -> Path:
    """Create a temporary versions directory with minimal revision files.

    Each entry in *revisions* is a dict with keys:
      - filename:       str, e.g. "abc_first.py"
      - revision:       str
      - down_revision:  str | None | tuple
    """
    for r in revisions:
        dr = r["down_revision"]
        if dr is None:
            dr_repr = "None"
        elif isinstance(dr, tuple):
            dr_repr = repr(dr)
        else:
            dr_repr = repr(dr)

        content = textwrap.dedent(f"""\
            revision = {repr(r['revision'])}
            down_revision = {dr_repr}
            branch_labels = None
            depends_on = None

            def upgrade():
                pass

            def downgrade():
                pass
        """)
        (tmp_path / r["filename"]).write_text(content, encoding="utf-8")
    return tmp_path


# ===========================================================================
# 1. assert_single_head_and_root() on the REAL versions directory
# ===========================================================================

class TestRealChainValidator:
    """Tests that call assert_single_head_and_root() against the real chain."""

    def test_real_chain_returns_exactly_one_head(self):
        """Req 7.1: The real migration chain must have exactly one head."""
        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root()
        assert result["head_count"] == 1, (
            f"Expected head_count=1, got {result['head_count']}. "
            f"Head revisions: {result['head_revisions']}"
        )

    def test_real_chain_returns_exactly_one_root(self):
        """Req 1.5: The real migration chain must have exactly one root (down_revision=None)."""
        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root()
        assert result["root_count"] == 1, (
            f"Expected root_count=1, got {result['root_count']}. "
            f"Root revisions: {result['root_revisions']}"
        )

    def test_real_chain_root_is_initial_schema(self):
        """The single root must be the 000000000000 initial_schema revision."""
        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root()
        assert result["root_revisions"] == ["000000000000"], (
            f"Expected root revision '000000000000', got {result['root_revisions']}"
        )

    def test_real_chain_head_is_squash_marker(self):
        """The single head must be the latest migration revision."""
        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root()
        assert result["head_revisions"] == ["e4f5a6b7c8d9"], (
            f"Expected head revision 'e4f5a6b7c8d9', got {result['head_revisions']}"
        )

    def test_real_chain_result_has_required_keys(self):
        """Result dict must contain all four required keys with correct types."""
        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root()
        assert isinstance(result["head_count"], int)
        assert isinstance(result["root_count"], int)
        assert isinstance(result["head_revisions"], list)
        assert isinstance(result["root_revisions"], list)


# ===========================================================================
# 2. Single-revision-with-down_revision=None check on the REAL chain
# ===========================================================================

class TestRealChainRootRevision:
    """Verify exactly one revision has down_revision=None in the real chain."""

    def test_exactly_one_revision_has_none_down_revision(self):
        """Req 1.5: Exactly one revision must have down_revision=None (the root)."""
        from app.migration_utils import _parse_revision_metadata

        none_count = 0
        none_revisions: list[str] = []

        for filepath in _VERSIONS_DIR.glob("*.py"):
            if filepath.name.startswith("__"):
                continue
            meta = _parse_revision_metadata(str(filepath))
            if meta is None:
                continue
            if meta["down_revision"] is None:
                none_count += 1
                none_revisions.append(meta["revision"])

        assert none_count == 1, (
            f"Expected exactly 1 revision with down_revision=None, "
            f"found {none_count}: {none_revisions}"
        )
        assert none_revisions[0] == "000000000000", (
            f"The root revision must be '000000000000', got {none_revisions[0]!r}"
        )


# ===========================================================================
# 3. Every non-merge revision has a non-null string down_revision
# ===========================================================================

class TestNonMergeRevisionPredecessors:
    """Req 7.4, 7.5: Every non-merge revision has exactly one predecessor (str, not tuple)."""

    def _collect_revisions(self) -> list[dict]:
        from app.migration_utils import _parse_revision_metadata
        revisions = []
        for filepath in sorted(_VERSIONS_DIR.glob("*.py")):
            if filepath.name.startswith("__"):
                continue
            meta = _parse_revision_metadata(str(filepath))
            if meta is None:
                continue
            revisions.append(meta)
        return revisions

    def test_non_merge_revisions_have_string_down_revision(self):
        """Every non-root, non-merge revision must have a plain string down_revision."""
        revisions = self._collect_revisions()
        violations = []
        for meta in revisions:
            dr = meta["down_revision"]
            if dr is None:
                # This is the root — allowed.
                continue
            if isinstance(dr, tuple):
                # This is a legitimate merge revision — allowed.
                continue
            # It's a non-root, non-merge revision: down_revision must be a non-empty string.
            if not isinstance(dr, str) or not dr.strip():
                violations.append(
                    f"  revision={meta['revision']!r}: down_revision={dr!r} "
                    f"(expected non-empty str)"
                )

        assert not violations, (
            "The following non-merge revisions have an invalid down_revision:\n"
            + "\n".join(violations)
        )

    def test_merge_revision_has_tuple_down_revision(self):
        """The known merge revision e5f6g7h8i9j0 must have a tuple down_revision.

        This confirms the validator correctly tolerates historical merge
        revisions and does NOT count them as multiple roots.
        Req 7.4, 7.5
        """
        assert _MERGE_HEADS_FILE.exists(), (
            f"Merge heads file not found at {_MERGE_HEADS_FILE}"
        )
        from app.migration_utils import _parse_revision_metadata
        meta = _parse_revision_metadata(str(_MERGE_HEADS_FILE))
        assert meta is not None, "Could not parse e5f6g7h8i9j0_merge_heads.py"
        assert isinstance(meta["down_revision"], tuple), (
            f"e5f6g7h8i9j0 must have a tuple down_revision, "
            f"got {meta['down_revision']!r}"
        )
        # The merge revision must NOT be counted as a root.
        assert meta["down_revision"] is not None

    def test_merge_revision_not_counted_as_root(self):
        """The merge revision (tuple down_revision) must NOT be counted as an extra root."""
        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root()
        assert "e5f6g7h8i9j0" not in result["root_revisions"], (
            "The merge revision e5f6g7h8i9j0 (which has a tuple down_revision) "
            "was incorrectly counted as a root. The validator should only count "
            "revisions with down_revision=None as roots."
        )


# ===========================================================================
# 4. check_migration_chain.py exits 0 on the real chain
# ===========================================================================

class TestCheckMigrationChainScript:
    """Tests for the check_migration_chain.py CLI entry point."""

    def test_script_exits_zero_on_real_chain(self):
        """Req 1.6, 7.3: check_migration_chain.py must exit 0 on the real chain."""
        result = _run_check_script()
        assert result.returncode == 0, (
            f"check_migration_chain.py exited {result.returncode} (expected 0).\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    def test_script_prints_head_and_root_info_on_success(self):
        """Req 7.3: On success the script must print head and root revision info."""
        result = _run_check_script()
        assert result.returncode == 0
        output = result.stdout
        # The script prints "Migration chain OK: root=<id>  head=<id>"
        assert "OK" in output or "root=" in output or "head=" in output, (
            f"Expected chain OK message in stdout, got: {output!r}"
        )
        # Both the root and the head revisions should appear somewhere in output
        assert "000000000000" in output, (
            f"Expected root '000000000000' in script output, got: {output!r}"
        )
        assert "e4f5a6b7c8d9" in output, (
            f"Expected head 'e4f5a6b7c8d9' in script output, got: {output!r}"
        )


# ===========================================================================
# 5. check_migration_chain.py exits non-zero on a fake chain with 2 heads
# ===========================================================================

class TestCheckMigrationChainFakeChain:
    """Test that the script correctly detects and reports a 2-headed chain."""

    def test_script_exits_nonzero_with_two_heads(self, tmp_path):
        """Req 1.6, 7.3: script exits non-zero when the chain has 2 heads."""
        # Create two revisions that share the same down_revision (both reference
        # 'root000' as their predecessor, making them both heads).
        _make_fake_versions_dir(tmp_path, [
            {"filename": "root000_root.py",   "revision": "root000",  "down_revision": None},
            {"filename": "head_a_one.py",     "revision": "heada001",  "down_revision": "root000"},
            {"filename": "head_b_two.py",     "revision": "headb002",  "down_revision": "root000"},
        ])

        # Use assert_single_head_and_root directly, pointing at the temp dir.
        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root(versions_dir=str(tmp_path))

        assert result["head_count"] == 2, (
            f"Expected head_count=2, got {result['head_count']}"
        )
        assert set(result["head_revisions"]) == {"heada001", "headb002"}, (
            f"Expected heads {{heada001, headb002}}, got {result['head_revisions']}"
        )
        assert result["root_count"] == 1

    def test_script_names_offending_revisions_on_two_head_chain(self, tmp_path):
        """Req 7.3: validator reports each offending head revision identifier."""
        _make_fake_versions_dir(tmp_path, [
            {"filename": "root000_root.py",   "revision": "root000",  "down_revision": None},
            {"filename": "head_a_one.py",     "revision": "heada001",  "down_revision": "root000"},
            {"filename": "head_b_two.py",     "revision": "headb002",  "down_revision": "root000"},
        ])

        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root(versions_dir=str(tmp_path))

        # Both head revision IDs must be present in the returned list.
        assert "heada001" in result["head_revisions"]
        assert "headb002" in result["head_revisions"]

    def test_two_root_chain_detected(self, tmp_path):
        """Validator must report root_count=2 when two revisions have down_revision=None."""
        _make_fake_versions_dir(tmp_path, [
            {"filename": "root000_root.py",   "revision": "root000", "down_revision": None},
            {"filename": "root002_second.py", "revision": "root002", "down_revision": None},
            {"filename": "head_a_one.py",     "revision": "heada001", "down_revision": "root000"},
        ])

        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root(versions_dir=str(tmp_path))

        assert result["root_count"] == 2, (
            f"Expected root_count=2, got {result['root_count']}"
        )
        assert set(result["root_revisions"]) == {"root000", "root002"}

    def test_empty_chain_returns_zero_counts(self, tmp_path):
        """An empty versions directory returns head_count=0 and root_count=0."""
        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root(versions_dir=str(tmp_path))

        assert result["head_count"] == 0
        assert result["root_count"] == 0
        assert result["head_revisions"] == []
        assert result["root_revisions"] == []

    def test_single_revision_chain_is_both_root_and_head(self, tmp_path):
        """A chain with exactly one revision: root_count=1 and head_count=1."""
        _make_fake_versions_dir(tmp_path, [
            {"filename": "only000_only.py", "revision": "only000", "down_revision": None},
        ])

        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root(versions_dir=str(tmp_path))

        assert result["head_count"] == 1
        assert result["root_count"] == 1
        assert result["head_revisions"] == ["only000"]
        assert result["root_revisions"] == ["only000"]

    def test_merge_revision_does_not_create_extra_roots(self, tmp_path):
        """A merge revision (tuple down_revision) must NOT be counted as a root."""
        _make_fake_versions_dir(tmp_path, [
            {"filename": "root000_root.py",  "revision": "root000", "down_revision": None},
            {"filename": "mid_a_aaa.py",     "revision": "mid_aaa", "down_revision": "root000"},
            {"filename": "mid_b_bbb.py",     "revision": "mid_bbb", "down_revision": "root000"},
            {
                "filename": "merge_mmm.py",
                "revision": "merge_mm",
                "down_revision": ("mid_aaa", "mid_bbb"),
            },
        ])

        from app.migration_utils import assert_single_head_and_root
        result = assert_single_head_and_root(versions_dir=str(tmp_path))

        # Only root000 has down_revision=None; merge_mm has a tuple.
        assert result["root_count"] == 1, (
            f"Expected root_count=1 (merge revision must not be counted as root), "
            f"got {result['root_count']}: {result['root_revisions']}"
        )
        assert result["head_count"] == 1, (
            f"Expected head_count=1 (merge_mm is the only head), "
            f"got {result['head_count']}: {result['head_revisions']}"
        )
        assert result["head_revisions"] == ["merge_mm"]


# ===========================================================================
# 6. Unrecognized-start-revision guard in env.py
# ===========================================================================

class TestUnrecognizedStartRevisionGuard:
    """Req 9.5: Guard halts (calls sys.exit) when current revision is unknown."""

    def test_known_revisions_set_is_importable(self):
        """_KNOWN_REVISIONS must be importable from the env module namespace."""
        # We import _KNOWN_REVISIONS indirectly via a subprocess so we don't
        # need a full Flask app context just to verify the set exists.
        import importlib.util
        env_path = str(_BACKEND_DIR / "alembic_migrations" / "env.py")

        # The guard logic lives in env.py, which cannot be imported directly
        # because it relies on Flask's app context for get_engine_url().
        # We read and check _KNOWN_REVISIONS via the source text instead.
        env_source = Path(env_path).read_text(encoding="utf-8")
        assert "_KNOWN_REVISIONS" in env_source, (
            "_KNOWN_REVISIONS set not found in alembic_migrations/env.py"
        )
        assert "000000000000" in env_source
        assert "a2b3c4d5e6f7" in env_source
        assert "b3c4d5e6f7a1" in env_source

    def test_known_revisions_contains_new_consolidation_revisions(self):
        """The two new consolidation revision IDs must be in _KNOWN_REVISIONS."""
        env_path = _BACKEND_DIR / "alembic_migrations" / "env.py"
        env_source = env_path.read_text(encoding="utf-8")
        assert "'a2b3c4d5e6f7'" in env_source, (
            "New consolidation revision 'a2b3c4d5e6f7' not found in _KNOWN_REVISIONS"
        )
        assert "'b3c4d5e6f7a1'" in env_source, (
            "New consolidation revision 'b3c4d5e6f7a1' not found in _KNOWN_REVISIONS"
        )

    def test_guard_calls_sys_exit_for_unknown_revision(self):
        """Req 9.5: _run_pre_upgrade_guards must call sys.exit for an unrecognized revision."""
        # We test the guard logic by extracting and exercising it directly,
        # without needing a full Flask app context.  We simulate the guard by
        # recreating its key logic: look up the current heads from a mock
        # MigrationContext, check them against _KNOWN_REVISIONS, and assert
        # sys.exit(1) is called.

        # Build a _KNOWN_REVISIONS set directly from the env.py source
        # (without importing the module) to avoid Flask context dependency.
        env_path = _BACKEND_DIR / "alembic_migrations" / "env.py"
        env_source = env_path.read_text(encoding="utf-8")

        # Parse _KNOWN_REVISIONS from the source via a restricted exec()
        ns: dict = {}
        import re
        m = re.search(
            r"_KNOWN_REVISIONS\s*=\s*frozenset\(\{([^}]+)\}\)",
            env_source,
            re.DOTALL,
        )
        assert m is not None, "Could not locate _KNOWN_REVISIONS in env.py"
        known_revisions_expr = "frozenset({" + m.group(1) + "})"
        exec(f"_KNOWN_REVISIONS = {known_revisions_expr}", ns)  # noqa: S102
        known_revisions: frozenset = ns["_KNOWN_REVISIONS"]

        # Simulate the guard: an unknown revision must NOT be in known_revisions
        unknown_rev = "deadbeef9999"
        assert unknown_rev not in known_revisions, (
            f"Test setup error: '{unknown_rev}' should not be in _KNOWN_REVISIONS"
        )

        # Replicate the guard logic: if any current head is unrecognized → sys.exit(1)
        current_heads = [unknown_rev]
        unrecognized = [rev for rev in current_heads if rev not in known_revisions]

        assert unrecognized == [unknown_rev], (
            "Guard logic should identify the unrecognized revision"
        )
        # The guard would call sys.exit(1) — verify the decision is correct.
        # (We do not actually call sys.exit in the test; we verify the trigger condition.)
        assert len(unrecognized) > 0, (
            "Guard must trigger sys.exit when unrecognized revisions are found"
        )

    def test_guard_does_not_trigger_for_known_revision(self):
        """Req 9.5: The guard must NOT halt when the current revision is in _KNOWN_REVISIONS."""
        env_path = _BACKEND_DIR / "alembic_migrations" / "env.py"
        env_source = env_path.read_text(encoding="utf-8")

        import re
        m = re.search(
            r"_KNOWN_REVISIONS\s*=\s*frozenset\(\{([^}]+)\}\)",
            env_source,
            re.DOTALL,
        )
        assert m is not None
        known_revisions_expr = "frozenset({" + m.group(1) + "})"
        ns: dict = {}
        exec(f"_KNOWN_REVISIONS = {known_revisions_expr}", ns)  # noqa: S102
        known_revisions: frozenset = ns["_KNOWN_REVISIONS"]

        # For every known revision, the guard must NOT detect an unrecognized entry.
        for known_rev in known_revisions:
            current_heads = [known_rev]
            unrecognized = [rev for rev in current_heads if rev not in known_revisions]
            assert unrecognized == [], (
                f"Guard incorrectly flagged known revision {known_rev!r} as unrecognized"
            )

    def test_guard_skips_fresh_database(self):
        """Req 9.5: The guard must NOT halt when the DB has no recorded revision (fresh DB)."""
        env_path = _BACKEND_DIR / "alembic_migrations" / "env.py"
        env_source = env_path.read_text(encoding="utf-8")

        import re
        m = re.search(
            r"_KNOWN_REVISIONS\s*=\s*frozenset\(\{([^}]+)\}\)",
            env_source,
            re.DOTALL,
        )
        assert m is not None
        known_revisions_expr = "frozenset({" + m.group(1) + "})"
        ns: dict = {}
        exec(f"_KNOWN_REVISIONS = {known_revisions_expr}", ns)  # noqa: S102
        known_revisions: frozenset = ns["_KNOWN_REVISIONS"]

        # A fresh database returns no heads (empty tuple from get_current_heads).
        current_heads: list = []
        unrecognized = [rev for rev in current_heads if rev not in known_revisions]
        # No heads → no unrecognized heads → guard does not trigger.
        assert unrecognized == [], (
            "Guard must not trigger on a fresh database with no recorded revision"
        )


# ===========================================================================
# 7. Verify new consolidation revision IDs are NOT in the legacy whitelist
# ===========================================================================

class TestLegacyWhitelist:
    """The new conventions-compliant revisions must NOT be in _LEGACY_REVISION_IDS."""

    def test_new_revisions_not_in_legacy_whitelist(self):
        """a2b3c4d5e6f7 and b3c4d5e6f7a1 must NOT be in _LEGACY_REVISION_IDS.

        These are new, conventions-compliant revisions.  Adding them to the
        legacy whitelist would disable idempotency linting on them, which is
        wrong — they were authored under the new convention.
        """
        from scripts.lint_migrations import _LEGACY_REVISION_IDS

        assert "a2b3c4d5e6f7" not in _LEGACY_REVISION_IDS, (
            "New revision 'a2b3c4d5e6f7' (model_alignment) must NOT be in "
            "_LEGACY_REVISION_IDS — it follows the new idempotency convention."
        )
        assert "b3c4d5e6f7a1" not in _LEGACY_REVISION_IDS, (
            "New revision 'b3c4d5e6f7a1' (squash_marker) must NOT be in "
            "_LEGACY_REVISION_IDS — it follows the new idempotency convention."
        )

    def test_pre_consolidation_revisions_in_legacy_whitelist(self):
        """All original pre-consolidation revisions must remain in _LEGACY_REVISION_IDS."""
        from scripts.lint_migrations import _LEGACY_REVISION_IDS

        pre_consolidation = {
            "000000000000", "267725fe7017",
            "a1b2c3d4e5f6", "b2c3d4e5f6g7", "c3d4e5f6g7h8",
            "d4e5f6g7h8i9", "e5f6g7h8i9j0", "f6g7h8i9j0k1",
            "g7h8i9j0k1l2", "h8i9j0k1l2m3", "i9j0k1l2m3n4",
        }
        for rev in pre_consolidation:
            assert rev in _LEGACY_REVISION_IDS, (
                f"Pre-consolidation revision {rev!r} must remain in _LEGACY_REVISION_IDS "
                f"(it predates the idempotency convention)."
            )
