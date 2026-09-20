"""HubSpot backup download is scoped to the requesting user."""
from unittest.mock import patch

from tests.conftest import ANON_HEADERS, seed_user


def test_backup_download_does_not_serve_another_users_file(client, app, tmp_path):
    from app.tasks import hubspot_tasks

    seed_user('test-user', is_admin=True)
    seed_user('other-user', is_admin=True)
    seed_user('stranger', is_admin=False)

    with patch.object(hubspot_tasks, 'backup_dir', return_value=str(tmp_path)):
        other = tmp_path / 'hubspot_backup_other-user_20260101_000000.json'
        mine = tmp_path / 'hubspot_backup_test-user_20260101_000001.json'
        other.write_text('{"owner":"other"}', encoding='utf-8')
        mine.write_text('{"owner":"mine"}', encoding='utf-8')

        mine_resp = client.get('/api/hubspot/export/backup/download')
        assert mine_resp.status_code == 200
        assert mine_resp.get_json() == {'owner': 'mine'}

        other_resp = client.get(
            '/api/hubspot/export/backup/download',
            headers={'X-User-Id': 'other-user'},
        )
        assert other_resp.status_code == 200
        assert other_resp.get_json() == {'owner': 'other'}

        stranger = client.get(
            '/api/hubspot/export/backup/download',
            headers={'X-User-Id': 'stranger'},
        )
        assert stranger.status_code == 403


def test_backup_download_requires_auth(client, app):
    resp = client.get(
        '/api/hubspot/export/backup/download',
        headers=ANON_HEADERS,
    )
    assert resp.status_code == 401


def test_backup_trigger_sends_registered_task_name(client, app, monkeypatch):
    from unittest.mock import MagicMock

    seed_user('test-user', is_admin=True)
    send_task = MagicMock()
    send_task.return_value.id = 'task-123'
    monkeypatch.setattr('celery.current_app.send_task', send_task)
    resp = client.post('/api/hubspot/export/backup')
    assert resp.status_code == 202
    send_task.assert_called_once_with(
        'hubspot.generate_backup',
        args=['test-user'],
    )


def test_non_admin_cannot_trigger_or_download_backup(client, app):
    seed_user('plain-user', is_admin=False)
    headers = {'X-User-Id': 'plain-user'}
    assert client.post('/api/hubspot/export/backup', headers=headers).status_code == 403
    assert client.get('/api/hubspot/export/backup/download', headers=headers).status_code == 403


def test_non_admin_cannot_test_hubspot_config(client, app):
    seed_user('plain-user', is_admin=False)
    headers = {'X-User-Id': 'plain-user'}
    with patch('app.services.hubspot_client_service.HubSpotClientService') as client_cls:
        resp = client.post('/api/hubspot/config/test', headers=headers)
    assert resp.status_code == 403
    client_cls.assert_not_called()
