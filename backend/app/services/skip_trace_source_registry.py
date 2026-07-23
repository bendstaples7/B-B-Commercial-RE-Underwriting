"""Skip-trace source registry — ordered connected sources (canonical)."""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from app import db
from app.models.skip_trace_config import (
    DEFAULT_SKIP_TRACE_SOURCES,
    SkipTraceConfig,
)

logger = logging.getLogger(__name__)


class SkipTraceSourceRegistry:
    """Read/write ordered skip-trace sources. Single writer for skip_trace_config."""

    def ensure_defaults(self) -> SkipTraceConfig:
        row = SkipTraceConfig.query.order_by(SkipTraceConfig.id.asc()).first()
        if row is None:
            row = SkipTraceConfig(sources=deepcopy(DEFAULT_SKIP_TRACE_SOURCES))
            db.session.add(row)
            db.session.flush()
            return row
        if not isinstance(row.sources, list) or not row.sources:
            row.sources = deepcopy(DEFAULT_SKIP_TRACE_SOURCES)
            db.session.add(row)
            db.session.flush()
        return row

    def list_sources(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        row = self.ensure_defaults()
        sources = row.sources if isinstance(row.sources, list) else []
        out: list[dict[str, Any]] = []
        for raw in sources:
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get('id') or '').strip()
            if not sid:
                continue
            item = {
                'id': sid,
                'label': str(raw.get('label') or sid),
                'enabled': bool(raw.get('enabled', True)),
                'kind': str(raw.get('kind') or 'manual'),
            }
            if enabled_only and not item['enabled']:
                continue
            out.append(item)
        return out

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        for src in self.list_sources():
            if src['id'] == source_id:
                return src
        return None

    def save_sources(self, sources: list[dict[str, Any]]) -> SkipTraceConfig:
        row = self.ensure_defaults()
        cleaned: list[dict[str, Any]] = []
        for raw in sources:
            if not isinstance(raw, dict):
                continue
            sid = str(raw.get('id') or '').strip()
            if not sid:
                continue
            cleaned.append({
                'id': sid,
                'label': str(raw.get('label') or sid)[:120],
                'enabled': bool(raw.get('enabled', True)),
                'kind': str(raw.get('kind') or 'manual')[:32],
            })
        if not cleaned:
            cleaned = deepcopy(DEFAULT_SKIP_TRACE_SOURCES)
        row.sources = cleaned
        db.session.add(row)
        db.session.flush()
        return row
