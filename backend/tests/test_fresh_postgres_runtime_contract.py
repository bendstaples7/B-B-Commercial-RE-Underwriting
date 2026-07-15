"""Runtime smoke tests against CI's freshly migrated PostgreSQL database."""

import os
from unittest.mock import patch

import pytest


MIGRATION_TEST_DB_URL = os.environ.get("MIGRATION_TEST_DB_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not MIGRATION_TEST_DB_URL,
        reason="MIGRATION_TEST_DB_URL is required for fresh PostgreSQL tests",
    ),
]


@pytest.fixture(scope="module")
def fresh_postgres_app():
    env = {
        "DATABASE_URL": MIGRATION_TEST_DB_URL or "",
        "FLASK_ENV": "testing",
        "SECRET_KEY": "fresh-postgres-test-secret",
        "JWT_SECRET_KEY": "fresh-postgres-test-jwt-secret",
        "KIRO_MIGRATION": "1",
    }
    with patch.dict(os.environ, env, clear=False):
        from app import create_app

        app = create_app("testing")
        app.config.update(TESTING=True)
        yield app


def test_fresh_database_satisfies_model_schema_contract(fresh_postgres_app):
    from app import db
    from app.services.schema_contract_service import (
        assert_model_schema_matches_database,
    )

    with fresh_postgres_app.app_context():
        assert_model_schema_matches_database(db.engine, db.metadata)


def test_multifamily_deal_list_runs_on_fresh_database(fresh_postgres_app):
    with fresh_postgres_app.test_client() as client:
        response = client.get(
            "/api/multifamily/deals",
            headers={"X-User-Id": "fresh-postgres-smoke-user"},
        )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.is_json
