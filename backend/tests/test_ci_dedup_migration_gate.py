"""Tests for the CI dedup migration gate helper."""

from scripts.ci_test_dedup_migration_gate import _sqlalchemy_database_url


def test_sqlalchemy_database_url_uses_installed_psycopg2_driver():
    assert _sqlalchemy_database_url(
        "postgresql://postgres:postgres@localhost:5432/test_db"
    ) == "postgresql+psycopg2://postgres:postgres@localhost:5432/test_db"
    assert _sqlalchemy_database_url(
        "postgres://postgres:postgres@localhost:5432/test_db"
    ) == "postgresql+psycopg2://postgres:postgres@localhost:5432/test_db"
    assert _sqlalchemy_database_url(
        "postgresql+psycopg2://postgres:postgres@localhost:5432/test_db"
    ) == "postgresql+psycopg2://postgres:postgres@localhost:5432/test_db"
