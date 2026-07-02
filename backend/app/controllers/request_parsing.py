"""Shared request parsing helpers for API controllers."""
from __future__ import annotations


def parse_bool(value, *, default: bool = False) -> bool:
    """Parse JSON/body booleans without treating the string ``\"false\"`` as true."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ('1', 'true', 'yes', 'on'):
            return True
        if normalized in ('0', 'false', 'no', 'off', ''):
            return False
    return bool(value)


def parse_positive_int(
    value,
    *,
    default: int,
    minimum: int = 1,
    maximum: int | None = None,
    field_name: str = 'value',
) -> int:
    """Parse a positive integer query/body param or raise ValueError."""
    if value is None or value == '':
        parsed = default
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{field_name} must be an integer') from exc
    if parsed < minimum:
        raise ValueError(f'{field_name} must be >= {minimum}')
    if maximum is not None and parsed > maximum:
        raise ValueError(f'{field_name} must be <= {maximum}')
    return parsed
