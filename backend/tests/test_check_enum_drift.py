"""Tests for the enum drift checker helper."""
from unittest.mock import MagicMock

from scripts import check_enum_drift


def test_check_enum_drift_uses_installed_psycopg2_driver(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/migration_test_db",
    )
    monkeypatch.setattr(check_enum_drift, "_build_registry", lambda: [])

    engine = MagicMock()
    monkeypatch.setattr(check_enum_drift, "create_engine", MagicMock(return_value=engine))

    assert check_enum_drift.main() == 0
    check_enum_drift.create_engine.assert_called_once_with(
        "postgresql+psycopg2://postgres:postgres@localhost:5432/migration_test_db"
    )
    engine.dispose.assert_called_once()
