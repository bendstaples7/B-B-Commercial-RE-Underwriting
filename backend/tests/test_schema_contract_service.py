"""Tests for fail-fast model schema validation."""

import pytest
import sqlalchemy as sa

from app.services.schema_contract_service import (
    assert_model_schema_matches_database,
    find_missing_model_schema,
)


def test_reports_missing_model_column():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table(
        "deals",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("priority_score", sa.Numeric(10, 2), nullable=False),
    )
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE deals (id INTEGER PRIMARY KEY)"))

    missing = find_missing_model_schema(engine, metadata)

    assert [(item.relation, item.column) for item in missing] == [
        ("deals", "priority_score")
    ]
    with pytest.raises(RuntimeError, match=r"deals\.priority_score"):
        assert_model_schema_matches_database(engine, metadata)


def test_accepts_matching_table_and_columns():
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    sa.Table(
        "deals",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("priority_score", sa.Numeric(10, 2), nullable=False),
    )
    metadata.create_all(engine)

    assert find_missing_model_schema(engine, metadata) == []
    assert_model_schema_matches_database(engine, metadata)
