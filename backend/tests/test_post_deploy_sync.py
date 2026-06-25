"""Tests for non-blocking post-deploy HubSpot sync dispatch."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestPostDeploySyncDispatch:
    def test_skips_when_hubspot_not_configured(self, app):
        from scripts.post_deploy_sync import dispatch_post_deploy_sync

        with patch('app.models.hubspot_config.HubSpotConfig') as mock_config:
            mock_config.query.first.return_value = None
            mode = dispatch_post_deploy_sync(app)

        assert mode == 'skipped'

    def test_dispatch_via_celery(self, app):
        from scripts.post_deploy_sync import dispatch_post_deploy_sync

        with patch('app.models.hubspot_config.HubSpotConfig') as mock_config:
            mock_config.query.first.return_value = MagicMock()
            with patch(
                'app.services.hubspot_pipeline_runner.dispatch_post_import_pipeline',
                return_value='celery',
            ) as mock_dispatch:
                with patch(
                    'app.services.hubspot_pipeline_runner.count_dangling_confirmed_lead_matches',
                    return_value=0,
                ):
                    with patch('celery.current_app') as mock_celery_app:
                        mock_celery_app.send_task = MagicMock()
                        mode = dispatch_post_deploy_sync(app)

        assert mode == 'celery'
        mock_dispatch.assert_called_once_with(app, run_ids=None)

    def test_dispatch_via_subprocess(self, app):
        from scripts.post_deploy_sync import dispatch_post_deploy_sync

        with patch('app.models.hubspot_config.HubSpotConfig') as mock_config:
            mock_config.query.first.return_value = MagicMock()
            with patch(
                'app.services.hubspot_pipeline_runner.dispatch_post_import_pipeline',
                return_value='subprocess',
            ):
                with patch(
                    'app.services.hubspot_pipeline_runner.count_dangling_confirmed_lead_matches',
                    return_value=2,
                ):
                    with patch('celery.current_app') as mock_celery_app:
                        mock_celery_app.send_task = MagicMock()
                        mode = dispatch_post_deploy_sync(app)

        assert mode == 'subprocess'

    def test_main_returns_zero_for_subprocess_dispatch(self, app):
        with patch('app.create_app', return_value=app):
            with patch(
                'scripts.post_deploy_sync.dispatch_post_deploy_sync',
                return_value='subprocess',
            ):
                from scripts import post_deploy_sync

                assert post_deploy_sync.main() == 0

    def test_main_returns_one_on_dispatch_exception(self, app):
        with patch('app.create_app', return_value=app):
            with patch(
                'scripts.post_deploy_sync.dispatch_post_deploy_sync',
                side_effect=RuntimeError('dispatch failed'),
            ):
                from scripts import post_deploy_sync

                assert post_deploy_sync.main() == 1


class TestDeployContractPostDeploy:
    def test_post_deploy_sync_uses_async_dispatch(self):
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        text = (repo_root / 'backend' / 'scripts' / 'post_deploy_sync.py').read_text(
            encoding='utf-8',
        )
        assert 'dispatch_post_import_pipeline' in text
        assert 'run_post_import_pipeline_sync' not in text

        deploy_sh = (repo_root / 'scripts' / 'deploy.sh').read_text(encoding='utf-8')
        assert 'Post-deploy HubSpot sync dispatched' in deploy_sh
