"""Lead unit inventory — replace full set of units for a lead."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app import db
from app.models.lead_unit import LEAD_UNIT_TYPES, LeadUnit


def _optional_int(raw) -> int | None:
    if raw is None or raw == '':
        return None
    if isinstance(raw, bool):
        raise ValueError('beds/sqft must be integers')
    try:
        if isinstance(raw, float):
            if not raw.is_integer():
                raise ValueError('beds/sqft must be integers')
            value = int(raw)
        elif isinstance(raw, int):
            value = raw
        else:
            text = str(raw).strip()
            # Reject fractional / scientific / oversized forms before int() truncates.
            if 'e' in text.lower() or len(text.lstrip('+-')) > 12:
                raise ValueError('beds/sqft must be integers')
            as_decimal = Decimal(text)
            if not as_decimal.is_finite() or as_decimal != as_decimal.to_integral_value():
                raise ValueError('beds/sqft must be integers')
            value = int(as_decimal)
    except (InvalidOperation, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and 'beds/sqft' in str(exc):
            raise
        raise ValueError('beds/sqft must be integers') from exc
    if value < 0:
        raise ValueError('beds/sqft must be >= 0')
    if value > 1_000_000_000:
        raise ValueError('beds/sqft must be integers')
    return value


def _optional_baths(raw) -> Decimal | None:
    if raw is None or raw == '':
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('baths must be a number') from exc
    if not value.is_finite():
        raise ValueError('baths must be a number')
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
    if not value.is_finite():
        raise ValueError('current_rent must be a number')
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

    # Validate fully before mutating so a bad row never deletes existing inventory.
    normalized: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError('Each unit must be an object')
        label = str(raw.get('unit_label') or f'Unit {index + 1}').strip() or f'Unit {index + 1}'
        if len(label) > 50:
            raise ValueError('unit_label must be 50 characters or fewer')
        label_key = label.casefold()
        if label_key in seen_labels:
            raise ValueError(f'Duplicate unit label: {label}')
        seen_labels.add(label_key)
        unit_type = str(raw.get('unit_type') or 'residential').strip().lower()
        if unit_type not in LEAD_UNIT_TYPES:
            raise ValueError(f'unit_type must be one of: {", ".join(LEAD_UNIT_TYPES)}')
        normalized.append({
            'unit_label': label,
            'unit_type': unit_type,
            'beds': _optional_int(raw.get('beds')),
            'baths': _optional_baths(raw.get('baths')),
            'sqft': _optional_int(raw.get('sqft')),
            'current_rent': _optional_rent(raw.get('current_rent')),
            'sort_order': int(raw.get('sort_order') or index),
        })

    LeadUnit.query.filter_by(lead_id=lead_id).delete(synchronize_session=False)
    created: list[LeadUnit] = []
    for row in normalized:
        unit = LeadUnit(
            lead_id=lead_id,
            unit_label=row['unit_label'],
            unit_type=row['unit_type'],
            beds=row['beds'],
            baths=row['baths'],
            sqft=row['sqft'],
            current_rent=row['current_rent'],
            sort_order=row['sort_order'],
        )
        db.session.add(unit)
        created.append(unit)
    db.session.flush()
    return created
