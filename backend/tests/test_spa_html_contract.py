"""Unit tests for SPA HTML contract helpers (blank-UI chunk regression)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "spa_html_contract.py"


def _load():
    import sys

    spec = importlib.util.spec_from_file_location("spa_html_contract", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # dataclasses need the module registered before class body runs
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def spa():
    return _load()


GOOD_HTML = """<!DOCTYPE html>
<html><head>
<script type="module" crossorigin src="/assets/index-abc.js"></script>
<link rel="modulepreload" crossorigin href="/assets/vendor-xyz.js">
<link rel="modulepreload" crossorigin href="/assets/mui-1.js">
</head><body>
<div id="root"></div>
<script>var el = document.getElementById('spa-boot-failure');</script>
</body></html>
"""

BAD_REACT_SPLIT = """<!DOCTYPE html>
<html><head>
<script type="module" src="/assets/index-abc.js"></script>
<link rel="modulepreload" href="/assets/vendor-xyz.js">
<link rel="modulepreload" href="/assets/react-Dy14kWe3.js">
</head><body><div id="root"></div>
<script>spa-boot-failure</script>
</body></html>
"""


def test_good_html_passes(spa):
    result = spa.check_spa_html_contract(GOOD_HTML)
    assert result.ok, result.errors


def test_separate_react_chunk_fails(spa):
    result = spa.check_spa_html_contract(BAD_REACT_SPLIT)
    assert not result.ok
    assert any("standalone" in e or "react-" in e for e in result.errors)


def test_react_router_chunk_does_not_false_positive(spa):
    html = GOOD_HTML.replace(
        'href="/assets/mui-1.js"',
        'href="/assets/react-router-AbCdEfGh.js"',
    )
    result = spa.check_spa_html_contract(html)
    assert result.ok, result.errors


def test_missing_vendor_fails(spa):
    html = GOOD_HTML.replace("/assets/vendor-xyz.js", "/assets/other-xyz.js")
    result = spa.check_spa_html_contract(html)
    assert not result.ok
    assert any("vendor" in e for e in result.errors)


def test_missing_watchdog_fails(spa):
    html = GOOD_HTML.replace("spa-boot-failure", "nope")
    result = spa.check_spa_html_contract(html)
    assert not result.ok
    assert any("spa-boot-failure" in e for e in result.errors)


def test_shas_match_helpers():
    drift = importlib.util.spec_from_file_location(
        "check_main_prod_drift",
        REPO_ROOT / "scripts" / "check_main_prod_drift.py",
    )
    assert drift and drift.loader
    mod = importlib.util.module_from_spec(drift)
    drift.loader.exec_module(mod)
    assert mod.shas_match("abcdef1234567890", "abcdef1234567890")
    assert mod.shas_match("abcdef1234567890", "abcdef1")
    assert not mod.shas_match("abcdef1234567890", "deadbeef")
