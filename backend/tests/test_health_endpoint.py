"""Example-based unit tests for the /api/health endpoint.

Validates: Requirements 10.1, 10.2
"""
import json
import pytest
import sqlalchemy.exc


def test_health_returns_200_when_db_connected(client, monkeypatch):
    """GET /api/health with a working DB returns HTTP 200 and 'status' in body.

    The migration head check and queue checks always fail in the SQLite test
    environment (no alembic_version table, no leads table schema match, etc.).
    To isolate the DB connectivity contract (Req 10.1), we patch the non-DB
    checks so only the DB connectivity check runs — confirming that a healthy
    DB connection produces HTTP 200.

    Validates: Requirement 10.1
    """
    import app.controllers.routes as routes_module

    # Patch the alembic Config import so the migration head check raises an
    # exception that is caught and recorded as a FAIL — but we also need to
    # prevent it from setting degraded=True.  The cleanest approach is to
    # monkeypatch the entire health_check view to skip non-DB checks by
    # patching the MigrationContext so it returns the expected heads, and
    # patching QueueService so it succeeds.
    from alembic.runtime.migration import MigrationContext
    from app.services.queue_service import QueueService

    # Make MigrationContext.configure return a context whose get_current_heads
    # matches whatever the script directory reports as heads.
    original_configure = MigrationContext.configure

    def mock_configure(conn, **kwargs):
        ctx = original_configure(conn, **kwargs)
        # Patch get_current_heads to return the expected heads dynamically
        import os
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

    monkeypatch.setattr(MigrationContext, 'configure', staticmethod(mock_configure))

    # Make QueueService.get_counts succeed
    monkeypatch.setattr(QueueService, 'get_counts', lambda self: {})

    response = client.get('/api/health')
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None, "Response body must be valid JSON"
    assert 'status' in data


def test_health_returns_503_when_db_unavailable(client, monkeypatch):
    """GET /api/health with DB patched to raise OperationalError returns HTTP 503.

    Validates: Requirement 10.2
    """
    from app import db

    def raise_operational_error(*args, **kwargs):
        raise sqlalchemy.exc.OperationalError(
            statement=None,
            params=None,
            orig=Exception("DB unavailable"),
        )

    monkeypatch.setattr(db.session, "execute", raise_operational_error)

    response = client.get('/api/health')
    assert response.status_code == 503
    data = response.get_json()
    assert data is not None, "Response body must be valid JSON even on DB failure"
    assert 'status' in data


def test_health_response_is_always_valid_json(client):
    """GET /api/health response body is always valid JSON (never plain text).

    Validates: Requirements 10.1, 10.2
    """
    response = client.get('/api/health')

    # Content-Type must indicate JSON
    assert response.content_type is not None
    assert 'application/json' in response.content_type, (
        f"Expected application/json content type, got: {response.content_type}"
    )

    # Body must be parseable as JSON
    try:
        data = json.loads(response.data)
    except (json.JSONDecodeError, ValueError) as exc:
        pytest.fail(f"Response body is not valid JSON: {exc}\nBody: {response.data!r}")

    assert isinstance(data, dict), f"Expected JSON object, got: {type(data)}"


def test_health_includes_enrichment_catalog_check(client, app, monkeypatch):
    """Health heals/seeds the enrichment catalog and reports status."""
    from alembic.runtime.migration import MigrationContext
    from app.services.queue_service import QueueService
    import app.controllers.routes as routes_module

    original_configure = MigrationContext.configure

    def mock_configure(conn, **kwargs):
        ctx = original_configure(conn, **kwargs)
        import os
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

    monkeypatch.setattr(MigrationContext, 'configure', staticmethod(mock_configure))
    monkeypatch.setattr(QueueService, 'get_counts', lambda self: {})

    with app.app_context():
        from app.models.enrichment import DataSource
        from app import db
        DataSource.query.delete()
        db.session.commit()

    response = client.get('/api/health')
    data = response.get_json()
    assert 'enrichment_catalog' in data['checks']
    assert data['checks']['enrichment_catalog'].startswith('ok')
    assert response.status_code == 200


def test_health_fails_when_catalog_still_missing(client, monkeypatch):
    """Catalog health FAIL degrades /api/health after heal cannot recover."""
    from alembic.runtime.migration import MigrationContext
    from app.services.queue_service import QueueService
    import app.controllers.routes as routes_module

    original_configure = MigrationContext.configure

    def mock_configure(conn, **kwargs):
        ctx = original_configure(conn, **kwargs)
        import os
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

    monkeypatch.setattr(MigrationContext, 'configure', staticmethod(mock_configure))
    monkeypatch.setattr(QueueService, 'get_counts', lambda self: {})
    monkeypatch.setattr(
        'app.services.cook_county_enrichment_service.check_enrichment_catalog_health',
        lambda heal=True: {
            'ok': False,
            'required_count': 12,
            'present_count': 0,
            'missing': ['cook_county_assessor'],
        },
    )
    monkeypatch.setattr(
        'app.services.cook_county_enrichment_service.collect_enrichment_supporting_data_invariants',
        lambda: {
            'catalog_ok': False,
            'enrichment_records_last_7d': 0,
            'chicago_no_pin_with_sale': 0,
            'working_set_sale_no_enrichment': 0,
        },
    )

    response = client.get('/api/health')
    data = response.get_json()
    assert response.status_code == 503
    assert data['status'] == 'degraded'
    assert data['checks']['enrichment_catalog'].startswith('FAIL')
