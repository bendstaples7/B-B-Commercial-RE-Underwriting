"""Tests for scripts/assert_frontend_dist_assets lazy↔entry forbid helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ASSERT_PATH = _ROOT / "scripts" / "assert_frontend_dist_assets.py"


def _load():
    name = "assert_frontend_dist_assets"
    spec = importlib.util.spec_from_file_location(name, _ASSERT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


af = _load()


def test_shared_chunks_are_not_lazy_route_chunks():
    for name in (
        "index-abc.js",
        "vendor-abc.js",
        "mui-abc.js",
        "api-abc.js",
        "ui-shared-abc.js",
        "maps-abc.js",
        "ag-grid-abc.js",
        "recharts-abc.js",
        "dnd-abc.js",
        "helpers-abc.js",
        "formatters-abc.js",
    ):
        assert af.is_lazy_route_chunk(name) is False


def test_ulcc_and_other_routes_are_lazy():
    assert af.is_lazy_route_chunk("UnifiedLeadCommandCenter-abc.js") is True
    assert af.is_lazy_route_chunk("Dashboard-abc.js") is True


def test_find_lazy_chunks_importing_index(tmp_path: Path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "api-shared.js").write_text('from"./index-dead.js"', encoding="utf-8")
    (assets / "UnifiedLeadCommandCenter-x.js").write_text(
        'from"./index-dead.js";export default 1', encoding="utf-8"
    )
    (assets / "Dashboard-y.js").write_text(
        'import("./index-dead.js");export default 1', encoding="utf-8"
    )
    (assets / "SideEffect-z.js").write_text(
        'import"./index-dead.js";export default 1', encoding="utf-8"
    )
    (assets / "OkPage-z.js").write_text("export default 1", encoding="utf-8")
    offenders = af.find_lazy_chunks_importing_index(assets)
    assert offenders == [
        "Dashboard-y.js",
        "SideEffect-z.js",
        "UnifiedLeadCommandCenter-x.js",
    ]
