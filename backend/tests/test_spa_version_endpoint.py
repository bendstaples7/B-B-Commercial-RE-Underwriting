"""Tests for GET /api/spa-version (stale-tab recovery)."""
from __future__ import annotations

import json


def test_spa_version_returns_build_id(client, tmp_path, monkeypatch):
    dist = tmp_path / 'spa-version.json'
    dist.write_text(
        json.dumps({'buildId': 'abc123', 'builtAt': '2026-01-01T00:00:00Z'}),
        encoding='utf-8',
    )

    import app.controllers.routes as routes_mod

    monkeypatch.setattr(
        routes_mod,
        '_spa_version_candidates',
        lambda: [str(dist)],
    )

    resp = client.get('/api/spa-version')
    assert resp.status_code == 200
    assert resp.headers.get('Cache-Control', '').startswith('no-store')
    data = resp.get_json()
    assert data['buildId'] == 'abc123'


def test_spa_version_404_when_missing(client, monkeypatch):
    import app.controllers.routes as routes_mod

    monkeypatch.setattr(
        routes_mod,
        '_spa_version_candidates',
        lambda: ['/tmp/definitely-missing-spa-version.json'],
    )

    resp = client.get('/api/spa-version')
    assert resp.status_code == 404
    assert 'no-store' in resp.headers.get('Cache-Control', '')
