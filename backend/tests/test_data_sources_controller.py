"""Unit tests for DataSourcesController.

Tests cover:
  - GET /api/data-sources/status → 401 when no Bearer token (or X-User-Id) is provided
  - GET /api/data-sources/status → 503 when DataSourceStatusService raises SQLAlchemyError

Requirements: 5.5, 5.6
"""
from unittest.mock import patch

import pytest
from sqlalchemy.exc import SQLAlchemyError


# ---------------------------------------------------------------------------
# Auth headers — X-User-Id is allowed in test config (ALLOW_LEGACY_X_USER_ID=True)
# ---------------------------------------------------------------------------
_AUTH_HEADERS = {'X-User-Id': 'test-user'}


# ---------------------------------------------------------------------------
# GET /api/data-sources/status
# ---------------------------------------------------------------------------

class TestDataSourcesControllerAuth:
    """Tests for authentication enforcement on GET /api/data-sources/status."""

    def test_returns_401_when_no_auth_header(self, client):
        """Unauthenticated request (no Authorization header, no X-User-Id) returns 401.

        Requirements: 5.5
        """
        # Explicitly pass empty headers so neither Authorization nor X-User-Id
        # is present — the require_auth decorator must reject the request.
        response = client.get(
            '/api/data-sources/status',
            headers={},
        )
        assert response.status_code == 401

    def test_returns_401_response_has_error_key(self, client):
        """401 response body contains an 'error' key.

        Requirements: 5.5
        """
        response = client.get('/api/data-sources/status', headers={})
        data = response.get_json()
        assert 'error' in data


class TestDataSourcesControllerErrors:
    """Tests for error handling on GET /api/data-sources/status."""

    def test_returns_503_when_service_raises_sqlalchemy_error(self, client):
        """SQLAlchemyError propagated from the service is caught and returns 503.

        Requirements: 5.6
        """
        with patch(
            'app.controllers.data_sources_controller.DataSourceStatusService.get_all_statuses',
            side_effect=SQLAlchemyError('DB unavailable'),
        ):
            response = client.get(
                '/api/data-sources/status',
                headers=_AUTH_HEADERS,
            )

        assert response.status_code == 503

    def test_503_response_has_error_key(self, client):
        """503 response body contains an 'error' key.

        Requirements: 5.6
        """
        with patch(
            'app.controllers.data_sources_controller.DataSourceStatusService.get_all_statuses',
            side_effect=SQLAlchemyError('DB unavailable'),
        ):
            response = client.get(
                '/api/data-sources/status',
                headers=_AUTH_HEADERS,
            )

        data = response.get_json()
        assert 'error' in data

    def test_503_response_has_message_key(self, client):
        """503 response body includes a human-readable 'message' field.

        Requirements: 5.6
        """
        with patch(
            'app.controllers.data_sources_controller.DataSourceStatusService.get_all_statuses',
            side_effect=SQLAlchemyError('DB unavailable'),
        ):
            response = client.get(
                '/api/data-sources/status',
                headers=_AUTH_HEADERS,
            )

        data = response.get_json()
        assert 'message' in data
