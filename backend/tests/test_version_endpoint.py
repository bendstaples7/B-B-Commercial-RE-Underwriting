"""Tests for GET /api/version deploy SHA resolution."""

from app.controllers.routes import resolve_deploy_sha


def test_version_returns_sha_from_deploy_sha_file(client, monkeypatch, tmp_path):
    app_dir = tmp_path / 'app'
    app_dir.mkdir()
    (app_dir / 'DEPLOY_SHA').write_text(
        'abc123def456789012345678901234567890abcd\n', encoding='utf-8'
    )
    monkeypatch.setenv('DEPLOY_APP_DIR', str(app_dir))

    response = client.get('/api/version')
    assert response.status_code == 200
    assert response.get_json()['sha'] == 'abc123def456789012345678901234567890abcd'


def test_deploy_sha_file_takes_priority_over_git_head(client, monkeypatch, tmp_path):
    app_dir = tmp_path / 'app'
    git_dir = app_dir / '.git'
    git_dir.mkdir(parents=True)
    (git_dir / 'HEAD').write_text(
        '1111111111111111111111111111111111111111\n', encoding='utf-8'
    )
    (app_dir / 'DEPLOY_SHA').write_text(
        'abc123def456789012345678901234567890abcd\n', encoding='utf-8'
    )
    monkeypatch.setenv('DEPLOY_APP_DIR', str(app_dir))

    assert resolve_deploy_sha(str(app_dir)) == 'abc123def456789012345678901234567890abcd'


def test_version_parses_detached_git_head(client, monkeypatch, tmp_path):
    app_dir = tmp_path / 'app'
    git_dir = app_dir / '.git'
    git_dir.mkdir(parents=True)
    (git_dir / 'HEAD').write_text(
        'fedcba9876543210fedcba9876543210fedcba98\n', encoding='utf-8'
    )
    monkeypatch.setenv('DEPLOY_APP_DIR', str(app_dir))

    response = client.get('/api/version')
    assert response.status_code == 200
    assert response.get_json()['sha'] == 'fedcba9876543210fedcba9876543210fedcba98'


def test_version_parses_git_ref_head(client, monkeypatch, tmp_path):
    app_dir = tmp_path / 'app'
    git_dir = app_dir / '.git'
    refs_dir = git_dir / 'refs' / 'heads' / 'main'
    refs_dir.parent.mkdir(parents=True)
    refs_dir.write_text('aaaabbbbccccddddeeeeffffaaaabbbbccccdddd\n', encoding='utf-8')
    (git_dir / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
    monkeypatch.setenv('DEPLOY_APP_DIR', str(app_dir))

    response = client.get('/api/version')
    assert response.status_code == 200
    assert response.get_json()['sha'] == 'aaaabbbbccccddddeeeeffffaaaabbbbccccdddd'


def test_version_returns_unknown_when_nothing_resolvable(client, monkeypatch, tmp_path):
    app_dir = tmp_path / 'empty'
    app_dir.mkdir()
    monkeypatch.setenv('DEPLOY_APP_DIR', str(app_dir))

    response = client.get('/api/version')
    assert response.status_code == 200
    assert response.get_json()['sha'] == 'unknown'


def test_resolve_deploy_sha_accepts_explicit_app_dir(tmp_path):
    app_dir = tmp_path / 'explicit'
    app_dir.mkdir()
    (app_dir / 'DEPLOY_SHA').write_text('deadbeef' * 5 + '\n', encoding='utf-8')

    assert resolve_deploy_sha(str(app_dir)) == 'deadbeef' * 5
