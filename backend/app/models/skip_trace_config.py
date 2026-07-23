"""Skip-trace platform config — ordered connected sources (one writer)."""
from __future__ import annotations

from datetime import datetime

from app import db

# v1 seed — single manual source; vendors plug in later without schema rewrite.
DEFAULT_SKIP_TRACE_SOURCES: list[dict] = [
    {
        'id': 'manual_default',
        'label': 'Manual skip trace',
        'enabled': True,
        'kind': 'manual',
    },
]


class SkipTraceConfig(db.Model):
    """Singleton-ish platform config for ordered skip-trace sources."""

    __tablename__ = 'skip_trace_config'

    id = db.Column(db.Integer, primary_key=True)
    # Ordered list of {id, label, enabled, kind}
    sources = db.Column(db.JSON, nullable=False, default=list)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )
