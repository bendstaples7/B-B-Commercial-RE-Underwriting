"""Property-based tests for the /api/health endpoint.

**Validates: Requirements 10.1, 10.2**

Property 1: Health check status reflects database connectivity
  For any Flask application state, the /api/health endpoint SHALL return
  HTTP 200 when the database connection succeeds and HTTP 503 when the
  database connection fails. The response body SHALL always contain a
  'status' field.
"""
import os
import pytest
import sqlalchemy.exc
from unittest.mock import patch, MagicMock
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


@given(db_available=st.booleans())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_health_status_reflects_db_connectivity(client, db_available):
    """Property 1: Health check status reflects database connectivity.

    **Validates: Requirements 10.1, 10.2**

    When db_available=True:  GET /api/health returns HTTP 200 and 'status' in body.
    When db_available=False: GET /api/health returns HTTP 503 and 'status' in body.
    """
    import app.controllers.routes as routes_module
    from app import db
    from alembic.runtime.migration import MigrationContext
    from app.services.queue_service import QueueService

    if db_available:
        # Patch non-DB checks so only DB connectivity determines the outcome.
        # MigrationContext.configure is patched to report the DB is at the
        # expected head revision; QueueService.get_counts is patched to succeed.
        original_configure = MigrationContext.configure

        def mock_configure(conn, **kwargs):
            ctx = original_configure(conn, **kwargs)
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            alembic_cfg = Config(
                os.path.join(
                    os.path.dirname(routes_module.__file__),
                    '..', '..', 'alembic_migrations', 'alembic.ini',
                )
            )
            alembic_cfg.set_main_option(
                'script_location',
                os.path.join(
                    os.path.dirname(routes_module.__file__),
                    '..', '..', 'alembic_migrations',
                ),
            )
            script = ScriptDirectory.from_config(alembic_cfg)
            expected = {s.revision for s in script.get_revisions('heads')}
            ctx.get_current_heads = lambda: expected
            return ctx

        with patch.object(MigrationContext, 'configure', staticmethod(mock_configure)), \
             patch.object(QueueService, 'get_counts', return_value={}), \
             patch(
                 'app.services.cook_county_enrichment_service.check_enrichment_catalog_health',
                 return_value={
                     'ok': True,
                     'present_count': 12,
                     'required_count': 12,
                     'missing': [],
                 },
             ):
            response = client.get('/api/health')

        assert response.status_code == 200, (
            f"Expected HTTP 200 when DB is available, got {response.status_code}. "
            f"Body: {response.get_json()}"
        )
        data = response.get_json()
        assert data is not None, "Response body must be valid JSON"
        assert 'status' in data, f"Response body must contain 'status' field, got: {data}"

    else:
        # Patch db.session.execute to raise OperationalError, simulating a
        # broken database connection.
        def raise_operational_error(*args, **kwargs):
            raise sqlalchemy.exc.OperationalError(
                statement=None,
                params=None,
                orig=Exception("DB unavailable"),
            )

        with patch.object(db.session, 'execute', side_effect=raise_operational_error):
            response = client.get('/api/health')

        assert response.status_code == 503, (
            f"Expected HTTP 503 when DB is unavailable, got {response.status_code}. "
            f"Body: {response.get_json()}"
        )
        data = response.get_json()
        assert data is not None, "Response body must be valid JSON even on DB failure"
        assert 'status' in data, f"Response body must contain 'status' field, got: {data}"
