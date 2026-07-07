"""Resolve prospect candidate coordinates from Cook County parcel cache."""
from __future__ import annotations

from typing import Optional

from app.models.parcel_universe_cache import ParcelUniverseCache
from app.services.plugins.pin_utils import format_pin_for_storage, normalize_pin_for_socrata


def resolve_coords_from_pin(pin: Optional[str]) -> tuple[Optional[float], Optional[float]]:
    """Look up lat/lon for a PIN from parcel_universe_cache."""
    if not pin:
        return None, None
    pin_digits = normalize_pin_for_socrata(pin)
    if not pin_digits:
        return None, None
    candidates = {
        pin_digits,
        format_pin_for_storage(pin_digits),
        pin.strip(),
    }
    for candidate_pin in candidates:
        row = ParcelUniverseCache.query.filter_by(pin=candidate_pin).first()
        if row and row.lat is not None and row.lon is not None:
            try:
                return float(row.lat), float(row.lon)
            except (TypeError, ValueError):
                continue
    return None, None
