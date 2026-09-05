"""Tests for deploy-time Google Maps key injection into SPA index.html."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PATH = _ROOT / 'scripts' / 'inject_google_maps_browser_key.py'


def _load():
    spec = importlib.util.spec_from_file_location('inject_google_maps_browser_key', _PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_from(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
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


def test_inject_escapes_quotes_backslashes_and_script_terminator(tmp_path: Path):
    index = tmp_path / 'index.html'
    index.write_text(
        '<!DOCTYPE html><html><body><div id="root"></div></body></html>',
        encoding='utf-8',
    )
    api_key = 'key"with\\chars</script><script>alert(1)</script>'
    assert inj.inject(index, api_key)
    text = index.read_text(encoding='utf-8')
    assignment = text.split('window.__BB_GOOGLE_MAPS_API_KEY__=', 1)[1].split(
        ';</script>',
        1,
    )[0]
    assert json.loads(assignment) == api_key
    assert '<\\/script>' in assignment
    assert text.count('</script>') == 1


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
        'GOOGLE_MAPS_BROWSER_API_KEY=AIzaSyFromBackendEnv\n',
        encoding='utf-8',
    )
    assert inj.resolve_key(tmp_path) == 'AIzaSyFromBackendEnv'


def test_resolve_key_skips_deploy_placeholders_and_server_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv('GOOGLE_MAPS_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_MAPS_BROWSER_API_KEY', raising=False)
    monkeypatch.delenv('VITE_GOOGLE_MAPS_API_KEY', raising=False)
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'backend' / '.env').write_text(
        '\n'.join(
            [
                'GOOGLE_MAPS_BROWSER_API_KEY=REPLACE_ME',
                'VITE_GOOGLE_MAPS_API_KEY=your-google-maps-api-key',
                'GOOGLE_MAPS_API_KEY=AIzaSyServerOnlyKey',
            ]
        ),
        encoding='utf-8',
    )
    assert inj.resolve_key(tmp_path) is None


def test_inject_script_and_backend_helper_share_browser_key_policy():
    from app.services.helpers.google_maps_browser_key import (
        BROWSER_ENV_CANDIDATES,
        PLACEHOLDER_VALUES,
    )

    assert inj.ENV_CANDIDATES == BROWSER_ENV_CANDIDATES
    assert inj.PLACEHOLDER_VALUES == PLACEHOLDER_VALUES


def test_inject_script_loads_sidecar_policy_when_copied(tmp_path: Path):
    copied_script = tmp_path / 'inject_google_maps_browser_key.py'
    copied_script.write_text(_PATH.read_text(encoding='utf-8'), encoding='utf-8')
    (tmp_path / 'google_maps_browser_key_policy.json').write_text(
        json.dumps(
            {
                'placeholderValues': ['placeholder-from-sidecar'],
                'browserEnvCandidates': ['GOOGLE_MAPS_BROWSER_API_KEY'],
            }
        ),
        encoding='utf-8',
    )
    copied = _load_from(copied_script, 'inject_google_maps_browser_key_sidecar')
    assert copied.PLACEHOLDER_VALUES == frozenset({'placeholder-from-sidecar'})
    assert copied.ENV_CANDIDATES == ('GOOGLE_MAPS_BROWSER_API_KEY',)
