"""Lead unit inventory — replace full set of units for a lead."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app import db
from app.models.lead_unit import LEAD_UNIT_TYPES, LeadUnit


def _optional_int(raw) -> int | None:
    if raw is None or raw == '':
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError('beds/sqft must be integers') from exc
    if value < 0:
        raise ValueError('beds/sqft must be >= 0')
    return value


def _optional_baths(raw) -> Decimal | None:
    if raw is None or raw == '':
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('baths must be a number') from exc
    if value < 0:
        raise ValueError('baths must be >= 0')
    return value


def _optional_rent(raw) -> Decimal | None:
    if raw is None or raw == '':
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('current_rent must be a number') from exc
    if value < 0:
        raise ValueError('current_rent must be >= 0')
    return value


def serialize_lead_unit(unit: LeadUnit) -> dict[str, Any]:
    return {
        'id': unit.id,
        'lead_id': unit.lead_id,
        'unit_label': unit.unit_label,
        'unit_type': unit.unit_type,
        'beds': unit.beds,
        'baths': float(unit.baths) if unit.baths is not None else None,
        'sqft': unit.sqft,
        'current_rent': float(unit.current_rent) if unit.current_rent is not None else None,
        'sort_order': unit.sort_order,
    }


def replace_lead_units(lead_id: int, rows: list[dict] | None) -> list[LeadUnit]:
    """Replace all units for *lead_id* with *rows* (empty list clears)."""
    if rows is None:
        return list(LeadUnit.query.filter_by(lead_id=lead_id).order_by(LeadUnit.sort_order).all())

    LeadUnit.query.filter_by(lead_id=lead_id).delete(synchronize_session=False)
    created: list[LeadUnit] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError('Each unit must be an object')
        label = str(raw.get('unit_label') or f'Unit {index + 1}').strip() or f'Unit {index + 1}'
        if len(label) > 50:
            raise ValueError('unit_label must be 50 characters or fewer')
        unit_type = str(raw.get('unit_type') or 'residential').strip().lower()
        if unit_type not in LEAD_UNIT_TYPES:
            raise ValueError(f'unit_type must be one of: {", ".join(LEAD_UNIT_TYPES)}')
        unit = LeadUnit(
            lead_id=lead_id,
            unit_label=label,
            unit_type=unit_type,
            beds=_optional_int(raw.get('beds')),
            baths=_optional_baths(raw.get('baths')),
            sqft=_optional_int(raw.get('sqft')),
            current_rent=_optional_rent(raw.get('current_rent')),
            sort_order=int(raw.get('sort_order') or index),
        )
        db.session.add(unit)
        created.append(unit)
    db.session.flush()
    return created
