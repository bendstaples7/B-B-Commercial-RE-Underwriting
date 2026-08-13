"""Tests for SPA boot-failure beacon (blank SPA phone-home)."""
from __future__ import annotations

import builtins
from unittest.mock import patch

import pytest

from app.models.spa_boot_failure_event import SpaBootFailureEvent
from app.services import spa_boot_failure_service as svc


@pytest.fixture()
def client(app):
    return app.test_client()


def test_normalize_payload_clips_and_defaults():
    data = svc.normalize_payload({
        'href': 'https://example.test/oauth/callback?code=secret#token',
        'reason': None,
        'ua': 'Mozilla/5.0',
        'assetHints': [{'name': '/assets/index.js', 'status': 'empty'}] * 30,
    })
    assert data['href'] == 'https://example.test/oauth/callback'
    assert data['reason'] == 'boot_watchdog'
    assert data['user_agent'] == 'Mozilla/5.0'
    assert len(data['asset_hints']) == svc.MAX_HINTS


def test_hash_ip_stable(monkeypatch):
    monkeypatch.setenv('SPA_BOOT_FAILURE_IP_SALT', 'test-salt')
    a = svc.hash_ip('1.2.3.4')
    b = svc.hash_ip('1.2.3.4')
    assert a == b
    assert a != svc.hash_ip('5.6.7.8')


def test_hash_ip_without_salt_omits_hash(monkeypatch):
    monkeypatch.delenv('SPA_BOOT_FAILURE_IP_SALT', raising=False)
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.delenv('FLASK_SECRET_KEY', raising=False)
    assert svc.hash_ip('1.2.3.4') is None


def test_spa_boot_failure_anonymous_accepted(client, app):
    with app.app_context():
        with patch.object(svc, 'enqueue_or_alert') as enqueue:
            resp = client.post(
                '/api/spa-boot-failure',
                json={
                    'href': 'https://example.test/login?code=secret#token',
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
    # Raw JSON body must exceed MAX_BODY_BYTES before parsing.
    raw = b'{"href":"' + (b'x' * (svc.MAX_BODY_BYTES + 64)) + b'"}'
    assert len(raw) > svc.MAX_BODY_BYTES
    resp = client.post(
        '/api/spa-boot-failure',
        data=raw,
        content_type='application/json',
    )
    assert resp.status_code == 413


def test_should_send_alert_debounce_file(tmp_path, monkeypatch):
    state = tmp_path / 'last_alert'
    monkeypatch.setattr(svc, 'FILE_ALERT_STATE', str(state))
    monkeypatch.setattr(svc, '_redis_client', lambda: None)
    assert svc.should_send_alert() is True
    assert svc.should_send_alert() is False


def test_enqueue_or_alert_catches_celery_worker_system_exit(app):
    event = SpaBootFailureEvent(id=123, href='https://example.test/', reason='boot_watchdog')
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'celery_worker':
            raise SystemExit('missing REDIS_URL')
        return real_import(name, *args, **kwargs)

    with patch('builtins.__import__', side_effect=fake_import):
        with patch.object(svc, 'send_ops_alert_sync') as send_sync:
            svc.enqueue_or_alert(event)
            send_sync.assert_called_once_with(event.id, event.href, event.reason)
