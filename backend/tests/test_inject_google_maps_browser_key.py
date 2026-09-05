"""Tests for deploy-time Google Maps key injection into SPA index.html."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PATH = _ROOT / 'scripts' / 'inject_google_maps_browser_key.py'


def _load():
    spec = importlib.util.spec_from_file_location('inject_google_maps_browser_key', _PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


inj = _load()


def test_inject_adds_bootstrap_script(tmp_path: Path):
    index = tmp_path / 'index.html'
    index.write_text(
        '<!DOCTYPE html><html><body><div id="root"></div></body></html>',
        encoding='utf-8',
    )
    assert inj.inject(index, 'AIzaSyTestKey123')
    text = index.read_text(encoding='utf-8')
    assert 'window.__BB_GOOGLE_MAPS_API_KEY__="AIzaSyTestKey123"' in text
    assert 'bb-google-maps-api-key' in text


def test_inject_is_idempotent(tmp_path: Path):
    index = tmp_path / 'index.html'
    index.write_text(
        '<!DOCTYPE html><html><body><div id="root"></div></body></html>',
        encoding='utf-8',
    )
    assert inj.inject(index, 'key-one')
    assert inj.inject(index, 'key-two')
    text = index.read_text(encoding='utf-8')
    assert text.count('window.__BB_GOOGLE_MAPS_API_KEY__') == 1
    assert 'key-two' in text
    assert 'key-one' not in text


def test_resolve_key_from_dotenv(tmp_path: Path, monkeypatch):
    monkeypatch.delenv('GOOGLE_MAPS_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_MAPS_BROWSER_API_KEY', raising=False)
    monkeypatch.delenv('VITE_GOOGLE_MAPS_API_KEY', raising=False)
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'backend' / '.env').write_text(
        'GOOGLE_MAPS_API_KEY=AIzaSyFromBackendEnv\n',
        encoding='utf-8',
    )
    assert inj.resolve_key(tmp_path) == 'AIzaSyFromBackendEnv'
