"""Tests for GET /api/spa-version (stale-tab recovery)."""
from __future__ import annotations

import json
from pathlib import Path


def test_spa_version_returns_build_id(client, tmp_path, monkeypatch):
    dist = tmp_path / 'frontend' / 'dist'
    dist.mkdir(parents=True)
    (dist / 'spa-version.json').write_text(
        json.dumps({'buildId': 'abc123', 'builtAt': '2026-01-01T00:00:00Z'}),
        encoding='utf-8',
    )

    # Point the route at our temp dist by monkeypatching open candidates via chdir
    # The route probes a path relative to controllers/ — patch os.path.abspath join
    # by writing into the expected relative location from controllers.
    import app.controllers.routes as routes_mod

    fake = {
        'buildId': 'abc123',
        'builtAt': '2026-01-01T00:00:00Z',
    }

    def fake_open(path, *args, **kwargs):
        if str(path).endswith('spa-version.json'):
            from io import StringIO
            return StringIO(json.dumps(fake))
        raise FileNotFoundError(path)

    monkeypatch.setattr('builtins.open', fake_open)

    resp = client.get('/api/spa-version')
    assert resp.status_code == 200
    assert resp.headers.get('Cache-Control', '').startswith('no-store')
    data = resp.get_json()
    assert data['buildId'] == 'abc123'


def test_spa_version_404_when_missing(client, monkeypatch):
    def boom(path, *args, **kwargs):
        raise FileNotFoundError(path)

    monkeypatch.setattr('builtins.open', boom)
    resp = client.get('/api/spa-version')
    assert resp.status_code == 404
    assert 'no-store' in resp.headers.get('Cache-Control', '')
