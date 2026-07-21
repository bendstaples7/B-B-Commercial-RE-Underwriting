"""Smoke tests for scripts/map_changed_to_tests.py mapping helpers."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "map_changed_to_tests.py"

sys.path.insert(0, str(ROOT / "scripts"))
import map_changed_to_tests as mapper  # noqa: E402


def test_build_mapping_flags_and_backend_rule_for_mapper_script():
    changed = ["scripts/map_changed_to_tests.py"]
    mapping = mapper.build_mapping(changed)
    assert mapping["has_backend"] is True
    assert mapping["has_frontend"] is False
    assert "tests/test_map_changed_to_tests.py" in mapping["backend"]


def test_build_mapping_frontend_colocated(tmp_path, monkeypatch):
    # Use real repo paths: UnifiedLeadCommandCenter has a co-located test.
    changed = ["frontend/src/components/UnifiedLeadCommandCenter.tsx"]
    mapping = mapper.build_mapping(changed)
    assert mapping["has_frontend"] is True
    assert mapping["has_frontend_src"] is True
    assert any(
        p.endswith("UnifiedLeadCommandCenter.test.tsx") for p in mapping["frontend"]
    )


def test_staged_json_cli_smoke():
    """CLI --staged --format json returns a parseable mapping object."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--staged", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert set(data) >= {
        "changed",
        "backend",
        "frontend",
        "has_backend",
        "has_frontend",
        "has_frontend_src",
    }
    assert isinstance(data["changed"], list)
    assert isinstance(data["backend"], list)
    assert isinstance(data["frontend"], list)


def test_map_backend_falls_back_to_full_suite_for_unmapped_backend_paths():
    mapping = mapper.build_mapping(["backend/app/services/totally_unmapped_widget.py"])
    assert mapping["backend"] == ["tests/"]
