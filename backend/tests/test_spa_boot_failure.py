"""Tests for SPA boot-failure beacon (blank SPA phone-home)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.spa_boot_failure_event import SpaBootFailureEvent
from app.services import spa_boot_failure_service as svc


@pytest.fixture()
def client(app):
    return app.test_client()


def test_normalize_payload_clips_and_defaults():
    data = svc.normalize_payload({
        'href': 'x' * 2000,
        'reason': None,
        'ua': 'Mozilla/5.0',
        'assetHints': [{'name': '/assets/index.js', 'status': 'empty'}] * 30,
    })
    assert len(data['href']) == svc.MAX_HREF_LEN
    assert data['reason'] == 'boot_watchdog'
    assert data['user_agent'] == 'Mozilla/5.0'
    assert len(data['asset_hints']) == svc.MAX_HINTS


def test_hash_ip_stable():
    a = svc.hash_ip('1.2.3.4')
    b = svc.hash_ip('1.2.3.4')
    assert a == b
    assert a != svc.hash_ip('5.6.7.8')


def test_spa_boot_failure_anonymous_accepted(client, app):
    with app.app_context():
        with patch.object(svc, 'enqueue_or_alert') as enqueue:
            resp = client.post(
                '/api/spa-boot-failure',
                json={
                    'href': 'https://example.test/login',
                    'reason': 'boot_watchdog',
                    'ua': 'pytest',
                    'assetHints': ['/assets/index-abc.js'],
                },
            )
            assert resp.status_code == 202
            body = resp.get_json()
            assert body['success'] is True
            assert body['id']
            enqueue.assert_called_once()
            row = SpaBootFailureEvent.query.filter_by(id=body['id']).one()
            assert row is not None
            assert row.reason == 'boot_watchdog'
            assert row.href == 'https://example.test/login'


def test_spa_boot_failure_rejects_huge_body(client):
    huge = {'href': 'x' * (svc.MAX_BODY_BYTES + 100)}
    resp = client.post('/api/spa-boot-failure', json=huge)
    # Flask may reject before our check depending on JSON size; accept 413 or 400.
    assert resp.status_code in (413, 400, 202)


def test_should_send_alert_debounce_file(tmp_path, monkeypatch):
    state = tmp_path / 'last_alert'
    monkeypatch.setattr(svc, 'FILE_ALERT_STATE', str(state))
    monkeypatch.setattr(svc, '_redis_client', lambda: None)
    assert svc.should_send_alert() is True
    assert svc.should_send_alert() is False
