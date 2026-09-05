"""Tests for Google Maps browser API key resolution and client config."""
import pytest


@pytest.fixture(autouse=True)
def _clear_maps_env(monkeypatch):
    for name in (
        'GOOGLE_MAPS_BROWSER_API_KEY',
        'VITE_GOOGLE_MAPS_API_KEY',
        'GOOGLE_MAPS_API_KEY',
    ):
        monkeypatch.delenv(name, raising=False)


def test_resolve_prefers_browser_key(monkeypatch):
    from app.services.helpers.google_maps_browser_key import (
        resolve_google_maps_browser_api_key,
    )

    monkeypatch.setenv('GOOGLE_MAPS_API_KEY', 'server-key')
    monkeypatch.setenv('VITE_GOOGLE_MAPS_API_KEY', 'vite-key')
    monkeypatch.setenv('GOOGLE_MAPS_BROWSER_API_KEY', 'browser-key')
    assert resolve_google_maps_browser_api_key() == 'browser-key'


def test_resolve_skips_placeholder(monkeypatch):
    from app.services.helpers.google_maps_browser_key import (
        resolve_google_maps_browser_api_key,
    )

    monkeypatch.setenv('GOOGLE_MAPS_API_KEY', 'your-google-maps-api-key')
    assert resolve_google_maps_browser_api_key() is None


def test_resolve_falls_back_to_server_key(monkeypatch):
    from app.services.helpers.google_maps_browser_key import (
        resolve_google_maps_browser_api_key,
    )

    monkeypatch.setenv('GOOGLE_MAPS_API_KEY', 'AIzaSyServerOnlyKey')
    assert resolve_google_maps_browser_api_key() == 'AIzaSyServerOnlyKey'


def test_client_config_requires_auth(client):
    response = client.get('/api/config/client', headers={})
    assert response.status_code == 401


def test_client_config_returns_key_when_authenticated(client, monkeypatch):
    monkeypatch.setenv('GOOGLE_MAPS_BROWSER_API_KEY', 'AIzaSyBrowserKeyForPlaces')
    response = client.get(
        '/api/config/client',
        headers={'X-User-Id': 'test-user'},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body['google_maps_api_key'] == 'AIzaSyBrowserKeyForPlaces'


def test_client_config_returns_null_without_key(client):
    response = client.get(
        '/api/config/client',
        headers={'X-User-Id': 'test-user'},
    )
    assert response.status_code == 200
    assert response.get_json()['google_maps_api_key'] is None
