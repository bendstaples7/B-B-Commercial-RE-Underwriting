"""Shared SQLAlchemy column types."""
from sqlalchemy import JSON as SaJSON, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB


class JSONBCompatible(TypeDecorator):
    """JSONB on PostgreSQL, portable JSON on other dialects (SQLite)."""
    impl = SaJSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(SaJSON())
