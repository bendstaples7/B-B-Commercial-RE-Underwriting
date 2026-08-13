"""Tests for live SPA contract asset URL extraction (blank-SPA HTTP class)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "assert_live_spa_contract.py"


def _load():
    import sys

    spec = importlib.util.spec_from_file_location("assert_live_spa_contract", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    # Ensure spa_html_contract is importable the same way as the script.
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def test_asset_urls_from_html_collects_unique_assets():
    mod = _load()
    html = """<!DOCTYPE html><html><head>
<script type="module" src="/assets/index-abc.js"></script>
<link rel="modulepreload" href="/assets/vendor-xyz.js">
<link rel="modulepreload" href="/assets/vendor-xyz.js">
<link rel="icon" href="/favicon.svg">
</head><body></body></html>"""
    urls = mod.asset_urls_from_html(html, "https://example.test/")
    assert urls == [
        "https://example.test/assets/index-abc.js",
        "https://example.test/assets/vendor-xyz.js",
    ]


def test_asset_urls_from_html_requires_assets_path():
    mod = _load()
    html = '<script src="/static/app.js"></script>'
    assert mod.asset_urls_from_html(html, "https://example.test/") == []


def test_asset_urls_from_html_resolves_relative_to_index_url():
    mod = _load()
    html = '<script type="module" src="assets/index-abc.js"></script>'
    assert mod.asset_urls_from_html(html, "https://example.test/app/index.html") == [
        "https://example.test/app/assets/index-abc.js"
    ]
