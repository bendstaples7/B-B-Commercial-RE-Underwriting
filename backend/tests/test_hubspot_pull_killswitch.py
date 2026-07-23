"""HUBSPOT_PULL_ENABLED / writeback gates — platform is source of truth."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models.hubspot_deal import HubSpotDeal
from app.models.lead import Lead
from app.services.hubspot_matcher_service import HubSpotMatcherService
from app.services.hubspot_writeback_service import (
    HubSpotWriteBackService,
    hubspot_pull_enabled,
    hubspot_write_back_enabled,
)


@pytest.fixture
def pull_disabled(monkeypatch):
    monkeypatch.setenv('HUBSPOT_PULL_ENABLED', 'false')
    yield
    monkeypatch.setenv('HUBSPOT_PULL_ENABLED', 'true')


@pytest.fixture
def writeback_disabled(monkeypatch):
    monkeypatch.setenv('HUBSPOT_WRITE_BACK_ENABLED', 'false')
    yield


class TestHubSpotPullFlags:
    def test_pull_defaults_false_when_unset(self, monkeypatch):
        monkeypatch.delenv('HUBSPOT_PULL_ENABLED', raising=False)
        assert hubspot_pull_enabled() is False

    def test_pull_true_when_enabled(self, monkeypatch):
        monkeypatch.setenv('HUBSPOT_PULL_ENABLED', 'true')
        assert hubspot_pull_enabled() is True

    def test_writeback_defaults_false(self, monkeypatch):
        monkeypatch.delenv('HUBSPOT_WRITE_BACK_ENABLED', raising=False)
        assert hubspot_write_back_enabled() is False


class TestEnrichNoOpWhenPullDisabled:
    def test_enrich_lead_from_deal_does_not_overwrite_status(self, app, pull_disabled):
        with app.app_context():
            lead = Lead(
                property_street='1023 W WELLINGTON AVE',
                lead_status='mailing_no_contact_made',
                hubspot_deal_stage='Mailing, no contact made',
            )
            db.session.add(lead)
            db.session.flush()

            deal = HubSpotDeal(
                hubspot_id='deal_pull_off_4171',
                raw_payload={
                    'properties': {
                        'dealstage': 'awaiting',
                        'dealname': '1023 W Wellington',
                    }
                },
            )
            db.session.add(deal)
            db.session.flush()

            updated = HubSpotMatcherService().enrich_lead_from_deal(
                lead,
                deal,
                stage_label_map={'awaiting': 'Awaiting Skip Trace'},
            )
            db.session.flush()

            assert updated == []
            assert lead.lead_status == 'mailing_no_contact_made'
            assert lead.hubspot_deal_stage == 'Mailing, no contact made'


class TestPipelineAndBeatSkipWhenPullDisabled:
    def test_post_import_pipeline_sync_returns_early(self, app, pull_disabled):
        with app.app_context():
            with patch(
                'app.tasks.hubspot_tasks.run_hubspot_matching',
            ) as matching:
                from app.services.hubspot_pipeline_runner import (
                    run_post_import_pipeline_sync,
                )
                run_post_import_pipeline_sync()
                matching.assert_not_called()

    def test_refresh_confirmed_deals_beat_skips(self, pull_disabled):
        from celery_worker import refresh_confirmed_hubspot_deals

        with patch(
            'app.tasks.hubspot_tasks.run_refresh_confirmed_hubspot_deals',
        ) as run:
            result = refresh_confirmed_hubspot_deals.run(limit=10)
            assert result == {'skipped': True, 'reason': 'hubspot_pull_disabled'}
            run.assert_not_called()

    def test_scheduled_engagement_sync_skips(self, pull_disabled):
        from celery_worker import scheduled_engagement_sync

        with patch('app.create_app') as create_app:
            scheduled_engagement_sync.run()
            create_app.assert_not_called()


class TestOutboundStagePushGated:
    def test_push_deal_stage_skipped_when_writeback_off(self, app, writeback_disabled):
        with app.app_context():
            lead = Lead(property_street='1 Test St', lead_status='skip_trace')
            db.session.add(lead)
            db.session.flush()

            result = HubSpotWriteBackService().push_deal_stage_for_lead(lead.id)
            assert result['synced'] is False
            assert result['reason'] == 'write_back_disabled'


class TestWebhookAckWhenPullDisabled:
    def test_webhook_returns_disabled_and_persists_skipped(self, app, pull_disabled, client):
        with app.app_context():
            with patch(
                'app.controllers.hubspot_webhook_controller.HubSpotWebhookService',
            ) as svc_cls:
                svc = MagicMock()
                svc.verify_signature.return_value = True
                svc_cls.return_value = svc

                resp = client.post(
                    '/api/hubspot/webhook',
                    json=[{'subscriptionType': 'deal.propertyChange', 'objectId': 1}],
                    content_type='application/json',
                    headers={
                        'X-HubSpot-Signature-v3': 'test',
                        'X-HubSpot-Request-Timestamp': '123',
                    },
                )
                assert resp.status_code == 200
                body = resp.get_json()
                assert body['status'] == 'disabled'
                assert body['reason'] == 'hubspot_pull_disabled'
                svc.handle_batch.assert_not_called()
                svc.handle_batch_skipped_disabled.assert_called_once()


class TestCeleryInboundTasksSkipWhenPullDisabled:
    def test_enrich_leads_task_skips(self, pull_disabled):
        from celery_worker import enrich_leads_from_hubspot

        with patch('app.tasks.hubspot_tasks.run_enrich_leads_from_hubspot') as run:
            result = enrich_leads_from_hubspot.run()
            assert result == {'skipped': True, 'reason': 'hubspot_pull_disabled'}
            run.assert_not_called()

    def test_convert_activities_task_skips(self, pull_disabled):
        from celery_worker import convert_hubspot_activities

        with patch('app.tasks.hubspot_tasks.run_convert_hubspot_activities') as run:
            result = convert_hubspot_activities.run()
            assert result == {'skipped': True, 'reason': 'hubspot_pull_disabled'}
            run.assert_not_called()

    def test_run_matching_task_skips(self, pull_disabled):
        from celery_worker import run_hubspot_matching

        with patch('app.tasks.hubspot_tasks.run_hubspot_matching') as run:
            result = run_hubspot_matching.run()
            assert result == {'skipped': True, 'reason': 'hubspot_pull_disabled'}
            run.assert_not_called()

    def test_run_enrich_function_skips_early(self, pull_disabled):
        from app.tasks.hubspot_tasks import run_enrich_leads_from_hubspot
        result = run_enrich_leads_from_hubspot()
        assert result == {'skipped': True, 'reason': 'hubspot_pull_disabled'}
