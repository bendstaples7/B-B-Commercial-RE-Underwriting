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


def test_sync_hubspot_task_properties_returns_false_on_api_error(app):
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
