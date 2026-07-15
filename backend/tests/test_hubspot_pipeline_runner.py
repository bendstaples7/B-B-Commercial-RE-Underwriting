"""Tests for hubspot_pipeline_runner."""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def app_ctx(app):
    with app.app_context():
        yield app


class TestCountDanglingConfirmedLeadMatches:
    def test_counts_match_pointing_at_missing_lead(self, app_ctx, db_session):
        from app.models.hubspot_match import HubSpotMatch
        from app.services.hubspot_pipeline_runner import count_dangling_confirmed_lead_matches

        db_session.add(HubSpotMatch(
            hubspot_record_type='deal',
            hubspot_id='dangling-test-999',
            internal_record_type='lead',
            internal_record_id=999999,
            confidence='HIGH',
            status='confirmed',
        ))
        db_session.commit()

        assert count_dangling_confirmed_lead_matches() >= 1


class TestDispatchPostImportPipeline:
    def test_uses_subprocess_when_celery_unavailable(self, app_ctx):
        from app.services.hubspot_pipeline_runner import dispatch_post_import_pipeline

        with patch(
            'app.services.hubspot_pipeline_runner.try_dispatch_celery_pipeline',
            return_value=False,
        ), patch(
            'app.services.hubspot_pipeline_runner.start_pipeline_subprocess',
        ) as mock_subprocess:
            mode = dispatch_post_import_pipeline(app_ctx, run_ids=None)
            assert mode == 'subprocess'
            mock_subprocess.assert_called_once_with(None, mode='full')

    def test_uses_celery_when_available(self, app_ctx):
        from app.services.hubspot_pipeline_runner import dispatch_post_import_pipeline

        with patch(
            'app.services.hubspot_pipeline_runner.try_dispatch_celery_pipeline',
            return_value=True,
        ), patch(
            'app.services.hubspot_pipeline_runner.start_pipeline_subprocess',
        ) as mock_subprocess:
            mode = dispatch_post_import_pipeline(app_ctx, run_ids=[1, 2])
            assert mode == 'celery'
            mock_subprocess.assert_not_called()

    def test_rescore_only_uses_celery_task(self, app_ctx):
        from app.services.hubspot_pipeline_runner import try_dispatch_celery_pipeline

        with patch(
            'app.services.hubspot_pipeline_runner._celery_workers_responding',
            return_value=True,
        ), patch('celery.current_app') as mock_celery_app:
            mock_celery_app.send_task = MagicMock()
            assert try_dispatch_celery_pipeline(mode='rescore_only') is True
            mock_celery_app.send_task.assert_called_once_with('hubspot.rescore_only')

    def test_try_dispatch_returns_false_when_no_workers(self, app_ctx):
        from app.services.hubspot_pipeline_runner import try_dispatch_celery_pipeline

        with patch(
            'app.services.hubspot_pipeline_runner._celery_workers_responding',
            return_value=False,
        ):
            assert try_dispatch_celery_pipeline(run_ids=[1]) is False


class TestStartupPipelineRecovery:
    def test_skipped_when_pipeline_subprocess_env_set(self, app_ctx, monkeypatch):
        from app.services.hubspot_pipeline_runner import maybe_start_startup_pipeline_recovery

        monkeypatch.setenv('PIPELINE_SUBPROCESS', '1')
        with patch(
            'app.services.hubspot_pipeline_runner.start_pipeline_subprocess',
        ) as mock_subprocess:
            maybe_start_startup_pipeline_recovery(app_ctx, dangling_match_count=3)
            mock_subprocess.assert_not_called()

    def test_subprocess_env_set_on_detached_spawn(self, app_ctx):
        from app.services.hubspot_pipeline_runner import start_pipeline_subprocess

        with patch('app.services.hubspot_pipeline_runner.subprocess.Popen') as mock_popen:
            start_pipeline_subprocess(run_ids=[42])
            _, kwargs = mock_popen.call_args
            assert kwargs['env']['PIPELINE_SUBPROCESS'] == '1'

    def test_spawn_skipped_when_recovery_claim_fails(self, app_ctx):
        from app.services.hubspot_pipeline_runner import maybe_start_startup_pipeline_recovery

        with patch(
            'app.services.hubspot_pipeline_runner._try_claim_recovery_spawn',
            return_value=False,
        ), patch(
            'app.services.hubspot_pipeline_runner.start_pipeline_subprocess',
        ) as mock_subprocess:
            maybe_start_startup_pipeline_recovery(app_ctx, dangling_match_count=2)
            mock_subprocess.assert_not_called()

    def test_spawn_claims_guard_before_subprocess(self, app_ctx):
        from app.services.hubspot_pipeline_runner import maybe_start_startup_pipeline_recovery

        with patch(
            'app.services.hubspot_pipeline_runner._try_claim_recovery_spawn',
            return_value=True,
        ), patch(
            'app.services.hubspot_pipeline_runner._release_recovery_spawn_lock',
        ) as mock_release, patch(
            'app.services.hubspot_pipeline_runner.start_pipeline_subprocess',
        ) as mock_subprocess:
            maybe_start_startup_pipeline_recovery(app_ctx, dangling_match_count=2)
            mock_subprocess.assert_called_once_with(run_ids=[])
            mock_release.assert_called_once()


class TestRunPostImportPipelineSync:
    def test_runs_all_pipeline_steps_in_order(self, app_ctx):
        from app.services.hubspot_pipeline_runner import run_post_import_pipeline_sync

        calls = []

        def _track(name):
            def _fn():
                calls.append(name)
            return _fn

        def _track_recent_sale(**_kwargs):
            calls.append('recent_sale')
            return {'rescheduled_task_count': 0}

        with patch('app.tasks.hubspot_tasks.run_hubspot_matching', _track('matching')), \
             patch('app.tasks.hubspot_tasks.run_enrich_leads_from_hubspot', _track('enrich')), \
             patch('app.tasks.hubspot_tasks.run_sync_hubspot_tasks_for_confirmed_leads', _track('sync_tasks')), \
             patch('app.tasks.hubspot_tasks.run_convert_hubspot_activities', _track('convert')), \
             patch('app.tasks.hubspot_tasks.run_extract_hubspot_signals', _track('signals')), \
             patch(
                 'app.services.mail_task_lifecycle_service.reconcile_recent_sale_mail_tasks',
                 side_effect=_track_recent_sale,
             ), \
             patch('app.tasks.hubspot_tasks.run_rescore_leads_after_import', return_value=5), \
             patch('app.services.deploy_sync_policy.record_pipeline_completed') as mock_record:
            run_post_import_pipeline_sync()

        assert calls == [
            'matching',
            'enrich',
            'convert',
            'sync_tasks',
            'recent_sale',
            'signals',
        ]
        mock_record.assert_called_once_with(rescore_count=5)

    def test_passes_affected_lead_ids_to_rescore(self, app_ctx):
        from app.services.hubspot_pipeline_runner import (
            note_pipeline_affected_leads,
            run_post_import_pipeline_sync,
        )

        def _enrich():
            note_pipeline_affected_leads([10, 20])

        with patch('app.tasks.hubspot_tasks.run_hubspot_matching'), \
             patch('app.tasks.hubspot_tasks.run_enrich_leads_from_hubspot', side_effect=_enrich), \
             patch('app.tasks.hubspot_tasks.run_sync_hubspot_tasks_for_confirmed_leads'), \
             patch('app.tasks.hubspot_tasks.run_convert_hubspot_activities'), \
             patch('app.tasks.hubspot_tasks.run_extract_hubspot_signals'), \
             patch(
                 'app.services.mail_task_lifecycle_service.reconcile_recent_sale_mail_tasks',
                 return_value={'rescheduled_task_count': 0},
             ), \
             patch('app.tasks.hubspot_tasks.run_rescore_leads_after_import') as mock_rescore, \
             patch('app.services.deploy_sync_policy.record_pipeline_completed'):
            run_post_import_pipeline_sync()

        mock_rescore.assert_called_once_with(lead_ids=[10, 20], force_full=False)


class TestRescoreOnlySync:
    def test_run_rescore_only_sync(self, app_ctx):
        from app.services.hubspot_pipeline_runner import run_rescore_only_sync

        with patch(
            'app.tasks.hubspot_tasks.run_rescore_leads_after_import',
            return_value=99,
        ) as mock_rescore, patch(
            'app.services.deploy_sync_policy.record_pipeline_completed',
        ) as mock_record:
            run_rescore_only_sync()

        mock_rescore.assert_called_once_with(force_full=True)
        mock_record.assert_called_once_with(rescore_count=99)


class TestDeployPostDeployDispatch:
    def test_skip_mode(self, app_ctx):
        from app.services.hubspot_pipeline_runner import dispatch_tiered_post_deploy_sync

        mode = dispatch_tiered_post_deploy_sync(app_ctx, 'skip')
        assert mode == 'skipped'


class TestPipelineLock:
    def test_second_acquire_fails_while_held(self, app_ctx):
        from app.services.hubspot_pipeline_runner import (
            release_pipeline_lock,
            try_acquire_pipeline_lock,
        )

        assert try_acquire_pipeline_lock() is True
        assert try_acquire_pipeline_lock() is False
        release_pipeline_lock()

    def test_subprocess_entry_path_runs_pipeline_once(self, app_ctx):
        """run_pipeline_once must not pre-acquire the lock (same-process double acquire no-ops)."""
        from app.services.hubspot_pipeline_runner import run_pipeline_after_imports

        calls = []

        with patch(
            'app.services.hubspot_pipeline_runner.run_post_import_pipeline_sync',
            side_effect=lambda: calls.append('ran'),
        ):
            run_pipeline_after_imports(app_ctx, run_ids=[])

        assert calls == ['ran']
