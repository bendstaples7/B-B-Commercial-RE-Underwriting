"""Unit tests for HubSpot task property write-back helpers."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.hubspot_client_service import HubSpotClientService


def test_update_task_builds_subject_and_timestamp_properties():
    client = HubSpotClientService.__new__(HubSpotClientService)
    client._patch = MagicMock(return_value={})

    client.update_task('402073870862', subject='Follow up sooner', due_date=date(2026, 7, 13))

    client._patch.assert_called_once()
    path, body = client._patch.call_args.args
    assert path == '/crm/v3/objects/tasks/402073870862'
    props = body['properties']
    assert props['hs_task_subject'] == 'Follow up sooner'
    expected_ms = str(
        int(datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    )
    assert props['hs_timestamp'] == expected_ms


def test_update_task_clear_due_date():
    client = HubSpotClientService.__new__(HubSpotClientService)
    client._patch = MagicMock(return_value={})

    client.update_task('1', clear_due_date=True)

    props = client._patch.call_args.args[1]['properties']
    assert props == {'hs_timestamp': ''}


def test_sync_hubspot_task_properties_records_platform_write(app):
    from app.models.hubspot_platform_write import HubSpotPlatformWrite
    from app.services.hubspot_task_completion_service import sync_hubspot_task_properties

    with app.app_context():
        mock_client = MagicMock()
        mock_config = MagicMock()
        with patch(
            'app.models.hubspot_config.HubSpotConfig.query'
        ) as mock_query, patch(
            'app.services.hubspot_client_service.HubSpotClientService',
            return_value=mock_client,
        ):
            mock_query.order_by.return_value.first.return_value = mock_config
            ok = sync_hubspot_task_properties(
                '402073870862',
                title='Follow up sooner',
                due_date=date(2026, 7, 13),
            )

        assert ok is True
        mock_client.update_task.assert_called_once()
        write = HubSpotPlatformWrite.query.filter_by(
            object_type='task',
            hubspot_id='402073870862',
        ).first()
        assert write is not None


def test_sync_hubspot_task_properties_keeps_loop_guard_on_api_error(app):
    from app.models.hubspot_platform_write import HubSpotPlatformWrite
    from app.services.hubspot_task_completion_service import sync_hubspot_task_properties

    with app.app_context():
        mock_client = MagicMock()
        mock_client.update_task.side_effect = RuntimeError('boom')
        mock_config = MagicMock()
        with patch(
            'app.models.hubspot_config.HubSpotConfig.query'
        ) as mock_query, patch(
            'app.services.hubspot_client_service.HubSpotClientService',
            return_value=mock_client,
        ):
            mock_query.order_by.return_value.first.return_value = mock_config
            ok = sync_hubspot_task_properties('bad-id', title='x')

        assert ok is False
        assert HubSpotPlatformWrite.query.filter_by(
            object_type='task',
            hubspot_id='bad-id',
        ).first() is not None


def test_mirror_crm_task_from_lead_task_clears_due_date(app):
    from app import db
    from app.models.lead import Lead
    from app.models.lead_task import LeadTask
    from app.models.task import Task
    from app.services.hubspot_task_completion_service import mirror_crm_task_from_lead_task

    with app.app_context():
        lead = Lead(property_street='1 Due Clear St', lead_status='awaiting_skip_trace')
        db.session.add(lead)
        db.session.flush()

        lead_task = LeadTask(
            lead_id=lead.id,
            task_type='custom',
            title='Follow up without date',
            status='open',
            due_date=None,
            hubspot_task_id='hs-clear-due-1',
        )
        crm_task = Task(
            title='Old follow up',
            due_date=datetime(2026, 7, 13, 13, 0, 0),
            status='open',
            hubspot_task_id='hs-clear-due-1',
        )
        db.session.add_all([lead_task, crm_task])
        db.session.flush()

        mirror_crm_task_from_lead_task(lead_task)
        db.session.flush()

        assert crm_task.title == 'Follow up without date'
        assert crm_task.due_date is None
        assert crm_task.updated_at is not None
