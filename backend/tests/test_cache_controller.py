"""Unit tests for the cache controller.

Tests cover:
  - GET /api/cache/socrata/status  → correct JSON structure for all three datasets
  - POST /api/cache/socrata/sync   → HTTP 202 with task_id (dataset='all')
  - POST /api/cache/socrata/sync   → HTTP 400 with accepted_values (invalid dataset)
  - POST /api/cache/socrata/sync   → HTTP 400 (missing / non-JSON body)

Requirements: 5.1, 5.6, 5.7, 5.8, 5.9
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.cache_status_service import DatasetStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dataset_status(
    dataset_name: str,
    row_count: int = 1000,
    last_synced_at=None,
    status: str = 'fresh',
    last_error=None,
) -> DatasetStatus:
    """Build a DatasetStatus instance for use in mocks."""
    return DatasetStatus(
        dataset_name=dataset_name,
        row_count=row_count,
        last_synced_at=last_synced_at,
        status=status,
        last_error=last_error,
    )


_THREE_DATASET_STATUSES = [
    _make_dataset_status('parcel_universe', row_count=500_000, status='fresh'),
    _make_dataset_status('parcel_sales', row_count=1_200_000, status='stale'),
    _make_dataset_status(
        'improvement_characteristics',
        row_count=0,
        status='never_synced',
        last_error=None,
    ),
]

_EXPECTED_DATASET_NAMES = {
    'parcel_universe',
    'parcel_sales',
    'improvement_characteristics',
}

_VALID_STATUSES = {'empty', 'fresh', 'stale', 'never_synced'}

_ACCEPTED_DATASETS = ['all', 'parcel_universe', 'parcel_sales', 'improvement_characteristics']


# ---------------------------------------------------------------------------
# GET /api/cache/socrata/status
# ---------------------------------------------------------------------------

class TestCacheStatus:
    """Tests for GET /api/cache/socrata/status."""

    def test_returns_200(self, client):
        """Status endpoint returns HTTP 200."""
        with patch(
            'app.controllers.cache_controller.CacheStatusService.get_status',
            return_value=_THREE_DATASET_STATUSES,
        ):
            response = client.get('/api/cache/socrata/status')

        assert response.status_code == 200

    def test_response_has_datasets_key(self, client):
        """Top-level response contains a 'datasets' key."""
        with patch(
            'app.controllers.cache_controller.CacheStatusService.get_status',
            return_value=_THREE_DATASET_STATUSES,
        ):
            response = client.get('/api/cache/socrata/status')

        data = response.get_json()
        assert 'datasets' in data

    def test_returns_three_datasets(self, client):
        """Response contains exactly three dataset entries."""
        with patch(
            'app.controllers.cache_controller.CacheStatusService.get_status',
            return_value=_THREE_DATASET_STATUSES,
        ):
            response = client.get('/api/cache/socrata/status')

        data = response.get_json()
        assert len(data['datasets']) == 3

    def test_all_three_dataset_names_present(self, client):
        """All three expected dataset names appear in the response."""
        with patch(
            'app.controllers.cache_controller.CacheStatusService.get_status',
            return_value=_THREE_DATASET_STATUSES,
        ):
            response = client.get('/api/cache/socrata/status')

        data = response.get_json()
        returned_names = {entry['dataset_name'] for entry in data['datasets']}
        assert returned_names == _EXPECTED_DATASET_NAMES

    def test_each_entry_has_required_fields(self, client):
        """Every dataset entry contains all five required fields."""
        required_fields = {'dataset_name', 'row_count', 'last_synced_at', 'status', 'last_error'}

        with patch(
            'app.controllers.cache_controller.CacheStatusService.get_status',
            return_value=_THREE_DATASET_STATUSES,
        ):
            response = client.get('/api/cache/socrata/status')

        data = response.get_json()
        for entry in data['datasets']:
            missing = required_fields - set(entry.keys())
            assert not missing, f"Entry {entry.get('dataset_name')} missing fields: {missing}"

    def test_row_count_is_integer(self, client):
        """row_count field is an integer in every entry."""
        with patch(
            'app.controllers.cache_controller.CacheStatusService.get_status',
            return_value=_THREE_DATASET_STATUSES,
        ):
            response = client.get('/api/cache/socrata/status')

        data = response.get_json()
        for entry in data['datasets']:
            assert isinstance(entry['row_count'], int), (
                f"row_count for {entry['dataset_name']} is not an int"
            )

    def test_status_field_is_valid_value(self, client):
        """status field is one of the four accepted values."""
        with patch(
            'app.controllers.cache_controller.CacheStatusService.get_status',
            return_value=_THREE_DATASET_STATUSES,
        ):
            response = client.get('/api/cache/socrata/status')

        data = response.get_json()
        for entry in data['datasets']:
            assert entry['status'] in _VALID_STATUSES, (
                f"Unexpected status '{entry['status']}' for {entry['dataset_name']}"
            )

    def test_last_synced_at_is_none_when_never_synced(self, client):
        """last_synced_at is null when the dataset has never been synced."""
        statuses = [
            _make_dataset_status('parcel_universe', row_count=0, status='never_synced', last_synced_at=None),
            _make_dataset_status('parcel_sales', row_count=0, status='never_synced', last_synced_at=None),
            _make_dataset_status('improvement_characteristics', row_count=0, status='never_synced', last_synced_at=None),
        ]

        with patch(
            'app.controllers.cache_controller.CacheStatusService.get_status',
            return_value=statuses,
        ):
            response = client.get('/api/cache/socrata/status')

        data = response.get_json()
        for entry in data['datasets']:
            assert entry['last_synced_at'] is None

    def test_last_synced_at_is_iso_string_when_present(self, client):
        """last_synced_at is an ISO 8601 string when a sync has occurred."""
        sync_time = datetime(2024, 6, 15, 2, 0, 0, tzinfo=timezone.utc)
        statuses = [
            _make_dataset_status('parcel_universe', last_synced_at=sync_time, status='fresh'),
            _make_dataset_status('parcel_sales', last_synced_at=sync_time, status='fresh'),
            _make_dataset_status('improvement_characteristics', last_synced_at=sync_time, status='fresh'),
        ]

        with patch(
            'app.controllers.cache_controller.CacheStatusService.get_status',
            return_value=statuses,
        ):
            response = client.get('/api/cache/socrata/status')

        data = response.get_json()
        for entry in data['datasets']:
            assert entry['last_synced_at'] is not None
            # Should be parseable as an ISO 8601 datetime string
            assert isinstance(entry['last_synced_at'], str)

    def test_last_error_is_none_when_no_error(self, client):
        """last_error is null when there is no error."""
        statuses = [
            _make_dataset_status('parcel_universe', last_error=None),
            _make_dataset_status('parcel_sales', last_error=None),
            _make_dataset_status('improvement_characteristics', last_error=None),
        ]

        with patch(
            'app.controllers.cache_controller.CacheStatusService.get_status',
            return_value=statuses,
        ):
            response = client.get('/api/cache/socrata/status')

        data = response.get_json()
        for entry in data['datasets']:
            assert entry['last_error'] is None

    def test_last_error_is_string_when_present(self, client):
        """last_error is a string when an error message exists."""
        statuses = [
            _make_dataset_status('parcel_universe', last_error='HTTP 503 from Socrata'),
            _make_dataset_status('parcel_sales', last_error=None),
            _make_dataset_status('improvement_characteristics', last_error=None),
        ]

        with patch(
            'app.controllers.cache_controller.CacheStatusService.get_status',
            return_value=statuses,
        ):
            response = client.get('/api/cache/socrata/status')

        data = response.get_json()
        parcel_universe_entry = next(
            e for e in data['datasets'] if e['dataset_name'] == 'parcel_universe'
        )
        assert parcel_universe_entry['last_error'] == 'HTTP 503 from Socrata'


# ---------------------------------------------------------------------------
# POST /api/cache/socrata/sync — happy path
# ---------------------------------------------------------------------------

class TestTriggerSync:
    """Tests for POST /api/cache/socrata/sync."""

    def test_dataset_all_returns_202(self, client):
        """POST with dataset='all' returns HTTP 202."""
        mock_result = MagicMock()
        mock_result.id = 'test-task-id-abc123'

        with patch(
            'celery_worker.socrata_cache_refresh_task.delay',
            return_value=mock_result,
        ):
            response = client.post(
                '/api/cache/socrata/sync',
                json={'dataset': 'all'},
            )

        assert response.status_code == 202

    def test_dataset_all_returns_task_id(self, client):
        """POST with dataset='all' returns task_id in response body."""
        mock_result = MagicMock()
        mock_result.id = 'test-task-id-abc123'

        with patch(
            'celery_worker.socrata_cache_refresh_task.delay',
            return_value=mock_result,
        ):
            response = client.post(
                '/api/cache/socrata/sync',
                json={'dataset': 'all'},
            )

        data = response.get_json()
        assert data['task_id'] == 'test-task-id-abc123'

    def test_dataset_all_returns_dataset_in_body(self, client):
        """POST with dataset='all' echoes the dataset name in the response."""
        mock_result = MagicMock()
        mock_result.id = 'test-task-id-abc123'

        with patch(
            'celery_worker.socrata_cache_refresh_task.delay',
            return_value=mock_result,
        ):
            response = client.post(
                '/api/cache/socrata/sync',
                json={'dataset': 'all'},
            )

        data = response.get_json()
        assert data['dataset'] == 'all'

    def test_specific_dataset_returns_202(self, client):
        """POST with a specific dataset name returns HTTP 202."""
        mock_result = MagicMock()
        mock_result.id = 'task-parcel-universe'

        with patch(
            'celery_worker.socrata_cache_refresh_task.delay',
            return_value=mock_result,
        ):
            response = client.post(
                '/api/cache/socrata/sync',
                json={'dataset': 'parcel_universe'},
            )

        assert response.status_code == 202

    def test_specific_dataset_echoed_in_response(self, client):
        """POST with a specific dataset name echoes that name in the response."""
        mock_result = MagicMock()
        mock_result.id = 'task-parcel-sales'

        with patch(
            'celery_worker.socrata_cache_refresh_task.delay',
            return_value=mock_result,
        ):
            response = client.post(
                '/api/cache/socrata/sync',
                json={'dataset': 'parcel_sales'},
            )

        data = response.get_json()
        assert data['dataset'] == 'parcel_sales'

    def test_delay_called_with_correct_dataset(self, client):
        """The Celery task is enqueued with the correct dataset argument."""
        mock_result = MagicMock()
        mock_result.id = 'task-improvement'

        with patch(
            'celery_worker.socrata_cache_refresh_task.delay',
            return_value=mock_result,
        ) as mock_delay:
            client.post(
                '/api/cache/socrata/sync',
                json={'dataset': 'improvement_characteristics'},
            )

        mock_delay.assert_called_once_with(dataset='improvement_characteristics')


# ---------------------------------------------------------------------------
# POST /api/cache/socrata/sync — invalid dataset
# ---------------------------------------------------------------------------

class TestTriggerSyncInvalidDataset:
    """Tests for POST /api/cache/socrata/sync with invalid dataset values."""

    def test_invalid_dataset_returns_400(self, client):
        """POST with an unrecognised dataset name returns HTTP 400."""
        response = client.post(
            '/api/cache/socrata/sync',
            json={'dataset': 'not_a_real_dataset'},
        )
        assert response.status_code == 400

    def test_invalid_dataset_response_contains_accepted_values(self, client):
        """HTTP 400 response for invalid dataset includes accepted_values list."""
        response = client.post(
            '/api/cache/socrata/sync',
            json={'dataset': 'not_a_real_dataset'},
        )
        data = response.get_json()
        # The controller explicitly returns accepted_values at the top level
        assert 'accepted_values' in data, (
            f"Expected 'accepted_values' key in error response but got: {data}"
        )
        for accepted in _ACCEPTED_DATASETS:
            assert accepted in data['accepted_values'], (
                f"Expected '{accepted}' in accepted_values but got: {data['accepted_values']}"
            )

    def test_empty_string_dataset_returns_400(self, client):
        """POST with an empty string dataset returns HTTP 400."""
        response = client.post(
            '/api/cache/socrata/sync',
            json={'dataset': ''},
        )
        assert response.status_code == 400

    def test_numeric_dataset_returns_400(self, client):
        """POST with a numeric dataset value returns HTTP 400."""
        response = client.post(
            '/api/cache/socrata/sync',
            json={'dataset': 42},
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/cache/socrata/sync — missing / non-JSON body
# ---------------------------------------------------------------------------

class TestTriggerSyncMissingBody:
    """Tests for POST /api/cache/socrata/sync with missing or malformed body."""

    def test_missing_body_returns_400(self, client):
        """POST with no body returns HTTP 400."""
        response = client.post('/api/cache/socrata/sync')
        assert response.status_code == 400

    def test_missing_body_has_error_message(self, client):
        """HTTP 400 for missing body includes a descriptive error message."""
        response = client.post('/api/cache/socrata/sync')
        data = response.get_json()
        assert 'error' in data or 'message' in data

    def test_non_json_body_returns_400(self, client):
        """POST with a plain-text body returns HTTP 400."""
        response = client.post(
            '/api/cache/socrata/sync',
            data='dataset=all',
            content_type='text/plain',
        )
        assert response.status_code == 400

    def test_empty_json_object_returns_400(self, client):
        """POST with an empty JSON object (missing required 'dataset' field) returns HTTP 400."""
        response = client.post(
            '/api/cache/socrata/sync',
            json={},
        )
        assert response.status_code == 400

    def test_missing_dataset_field_returns_400(self, client):
        """POST with a JSON body that omits the 'dataset' key returns HTTP 400."""
        response = client.post(
            '/api/cache/socrata/sync',
            json={'other_field': 'value'},
        )
        assert response.status_code == 400
