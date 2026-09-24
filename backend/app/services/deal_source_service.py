"""Deal / capture source catalog — builtins + user-created options."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.contact import Contact
from app.models.deal_source_option import DealSourceOption
from app.models.lead import Lead
from app.services.helpers.deal_source import (
    DEAL_SOURCE_MAX_LENGTH,
    DEAL_SOURCE_OPTIONS,
    builtin_deal_source,
    is_builtin_deal_source,
    normalize_deal_source_label,
)

logger = logging.getLogger(__name__)


class DealSourceService:
    """List and register deal_source / contact.source dropdown values."""

    def list_sources(self) -> list[dict[str, Any]]:
        """Return builtins first (stable order), then custom / discovered labels."""
        seen_lower: set[str] = set()
        rows: list[dict[str, Any]] = []

        for name in DEAL_SOURCE_OPTIONS:
            key = name.lower()
            if key in seen_lower:
                continue
            seen_lower.add(key)
            rows.append({'name': name, 'is_builtin': True})

        custom_names = [
            row.name
            for row in DealSourceOption.query.order_by(DealSourceOption.name.asc()).all()
            if row.name
        ]
        for name in custom_names:
            key = name.lower()
            if key in seen_lower:
                continue
            seen_lower.add(key)
            rows.append({'name': name, 'is_builtin': False})

        # Historical values written before the catalog existed still appear.
        for discovered in self._discovered_labels():
            key = discovered.lower()
            if key in seen_lower:
                continue
            seen_lower.add(key)
            rows.append({'name': discovered, 'is_builtin': False})

        return rows

    def _discovered_labels(self) -> list[str]:
        lead_values = (
            db.session.query(Lead.deal_source)
            .filter(Lead.deal_source.isnot(None), Lead.deal_source != '')
            .distinct()
            .all()
        )
        contact_values = (
            db.session.query(Contact.source)
            .filter(Contact.source.isnot(None), Contact.source != '')
            .distinct()
            .all()
        )
        labels: list[str] = []
        for (raw,) in (*lead_values, *contact_values):
            cleaned = normalize_deal_source_label(raw)
            if cleaned:
                labels.append(cleaned)
        labels.sort(key=lambda s: s.lower())
        return labels

    def _find_custom(self, cleaned: str) -> DealSourceOption | None:
        return (
            DealSourceOption.query.filter(func.lower(DealSourceOption.name) == cleaned.lower())
            .first()
        )

    def _register_custom(
        self,
        cleaned: str,
        *,
        created_by: str | None = None,
        commit: bool,
    ) -> tuple[str, bool]:
        """Insert a custom option. Returns (canonical name, created?)."""
        existing = self._find_custom(cleaned)
        if existing is not None:
            return existing.name, False

        option = DealSourceOption(name=cleaned, created_by=(created_by or None))
        try:
            if commit:
                db.session.add(option)
                db.session.commit()
            else:
                # Savepoint so a race does not roll back the caller's lead/contact txn.
                with db.session.begin_nested():
                    db.session.add(option)
                    db.session.flush()
        except IntegrityError:
            if commit:
                db.session.rollback()
            raced = self._find_custom(cleaned)
            if raced is not None:
                return raced.name, False
            raise
        return option.name, True

    def create_source(self, name: str, *, created_by: str | None = None) -> dict[str, Any]:
        """Register a custom source. Idempotent for builtins and existing customs."""
        cleaned = normalize_deal_source_label(name)
        if not cleaned:
            raise ValueError('Source name is required')
        if len(cleaned) > DEAL_SOURCE_MAX_LENGTH:
            raise ValueError(f'Source name must be {DEAL_SOURCE_MAX_LENGTH} characters or fewer')

        builtin = builtin_deal_source(cleaned)
        if builtin:
            return {'name': builtin, 'is_builtin': True, 'created': False}

        canonical, created = self._register_custom(cleaned, created_by=created_by, commit=True)
        return {'name': canonical, 'is_builtin': False, 'created': created}

    def ensure_registered(self, name: str | None, *, created_by: str | None = None) -> str | None:
        """Normalize and persist a source used on a lead/contact (no-op for blank).

        Flushes into the caller's transaction — does not commit — so quick-add /
        contact creates stay atomic.
        """
        cleaned = normalize_deal_source_label(name)
        if not cleaned:
            return None
        if len(cleaned) > DEAL_SOURCE_MAX_LENGTH:
            raise ValueError(f'Source name must be {DEAL_SOURCE_MAX_LENGTH} characters or fewer')
        if is_builtin_deal_source(cleaned):
            return builtin_deal_source(cleaned)
        canonical, _created = self._register_custom(
            cleaned, created_by=created_by, commit=False,
        )
        return canonical
