"""Tests for deploy_sync_policy path classification."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.services.deploy_sync_policy import (
    apply_pipeline_cooldown,
    classify_deploy_sync_mode,
    load_changed_paths_for_deploy,
    load_changed_paths_from_file,
    paths_require_hubspot_data_pipeline,
    resolve_deploy_sync_from_manifest,
    resolve_deploy_sync_mode,
    scoring_code_changed_since_last_run,
)


class TestClassifyDeploySyncMode:
    def test_frontend_only_skips(self):
        paths = ['frontend/src/App.tsx', 'docs/deployment/plan.md']
        assert classify_deploy_sync_mode(paths) == 'skip'

    def test_scoring_paths_rescore_only(self):
        paths = ['backend/app/services/lead_scoring_engine.py']
        assert classify_deploy_sync_mode(paths) == 'rescore_only'

    def test_outreach_paths_rescore_only(self):
        paths = ['backend/app/services/outreach_method_service.py']
        assert classify_deploy_sync_mode(paths) == 'rescore_only'

    def test_queue_service_rescore_only(self):
        paths = ['backend/app/services/queue_service.py']
        assert classify_deploy_sync_mode(paths) == 'rescore_only'

    def test_celery_worker_rescore_only(self):
        paths = ['backend/celery_worker.py']
        assert classify_deploy_sync_mode(paths) == 'rescore_only'

    def test_alembic_scoring_migration_rescore_only(self):
        paths = ['backend/alembic_migrations/versions/e4f5a6b7c8d9_add_recommended_contact_method.py']
        assert classify_deploy_sync_mode(paths) == 'rescore_only'

    def test_hubspot_paths_full_pipeline(self):
        paths = ['backend/app/services/hubspot_matcher_service.py']
        assert classify_deploy_sync_mode(paths) == 'full_pipeline'

    def test_hubspot_tasks_full_pipeline(self):
        paths = ['backend/app/tasks/hubspot_tasks.py']
        assert classify_deploy_sync_mode(paths) == 'full_pipeline'

    def test_nested_hubspot_path_full_pipeline(self):
        paths = ['backend/app/foo/hubspot_bar.py']
        assert classify_deploy_sync_mode(paths) == 'full_pipeline'

    def test_hubspot_wins_over_scoring_when_both_changed(self):
        paths = [
            'backend/app/services/lead_scoring_engine.py',
            'backend/app/tasks/hubspot_tasks.py',
        ]
        assert classify_deploy_sync_mode(paths) == 'full_pipeline'

    def test_empty_paths_skip(self):
        assert classify_deploy_sync_mode([]) == 'skip'


class TestPipelineCooldown:
    def test_glue_only_full_pipeline_downgrades_to_skip_within_cooldown(self):
        recent = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        glue_paths = ['backend/app/services/hubspot_pipeline_runner.py']
        with patch(
            'app.services.deploy_sync_policy.get_redis_value',
            return_value=recent,
        ):
            mode = apply_pipeline_cooldown('full_pipeline', glue_paths)
        assert mode == 'skip'

    def test_recent_full_pipeline_kept_for_hubspot_data_paths(self):
        recent = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with patch(
            'app.services.deploy_sync_policy.get_redis_value',
            return_value=recent,
        ):
            mode = apply_pipeline_cooldown(
                'full_pipeline',
                ['backend/app/services/hubspot_matcher_service.py'],
            )
        assert mode == 'full_pipeline'

    def test_rescore_only_unaffected_by_cooldown(self):
        recent = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        with patch(
            'app.services.deploy_sync_policy.get_redis_value',
            return_value=recent,
        ):
            mode = apply_pipeline_cooldown(
                'rescore_only',
                ['backend/app/services/lead_scoring_engine.py'],
            )
        assert mode == 'rescore_only'

    def test_hubspot_data_paths_helper_excludes_glue(self):
        assert paths_require_hubspot_data_pipeline(
            ['backend/app/services/hubspot_pipeline_runner.py'],
        ) is False
        assert paths_require_hubspot_data_pipeline(
            ['backend/app/services/hubspot_matcher_service.py'],
        ) is True
        assert paths_require_hubspot_data_pipeline(
            ['backend/app/integrations/foo/hubspot_sync.py'],
        ) is True


class TestLoadChangedPaths:
    def test_loads_non_empty_lines(self, tmp_path):
        path = tmp_path / 'changed_paths.txt'
        path.write_text('frontend/a.tsx\n\nbackend/b.py\n', encoding='utf-8')
        assert load_changed_paths_from_file(str(path)) == [
            'frontend/a.tsx',
            'backend/b.py',
        ]

    def test_missing_file_returns_unknown_delta(self):
        paths, unknown = load_changed_paths_for_deploy('/nonexistent/changed_paths.txt')
        assert paths == []
        assert unknown is True

    def test_empty_file_returns_unknown_delta(self, tmp_path):
        path = tmp_path / 'changed_paths.txt'
        path.write_text('\n', encoding='utf-8')
        paths, unknown = load_changed_paths_for_deploy(str(path))
        assert paths == []
        assert unknown is True


class TestManifestFallback:
    def test_empty_manifest_defaults_to_full_pipeline(self, tmp_path):
        path = tmp_path / 'changed_paths.txt'
        path.write_text('', encoding='utf-8')
        assert resolve_deploy_sync_from_manifest(str(path)) == 'full_pipeline'

    def test_missing_manifest_defaults_to_full_pipeline(self):
        assert resolve_deploy_sync_from_manifest(None) == 'full_pipeline'


class TestScoringCodeHash:
    def test_unchanged_when_no_previous_hash(self):
        with patch('app.services.deploy_sync_policy.get_redis_value', return_value=None):
            assert scoring_code_changed_since_last_run() is False


class TestResolveDeploySyncMode:
    def test_resolves_with_cooldown(self):
        with patch(
            'app.services.deploy_sync_policy.apply_pipeline_cooldown',
            side_effect=lambda mode, _paths: mode,
        ):
            assert resolve_deploy_sync_mode(['frontend/x.tsx']) == 'skip'
