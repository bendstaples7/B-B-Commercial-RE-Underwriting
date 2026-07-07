"""Per-user geographic area filter for Prospect Review (display only)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from app import db
from app.models.motivation_signal import ProspectAreaFilter, ProspectCandidate

logger = logging.getLogger(__name__)

_SCHEMA_ENSURED = False


def ensure_prospect_geo_schema() -> None:
    """Idempotent DDL for prospect geo columns and area-filter table."""
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return
    try:
        from sqlalchemy import text

        db.session.execute(
            text(
                'ALTER TABLE prospect_candidates '
                'ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION'
            )
        )
        db.session.execute(
            text(
                'ALTER TABLE prospect_candidates '
                'ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION'
            )
        )
        db.session.commit()
        db.create_all()
        _SCHEMA_ENSURED = True
    except Exception as exc:
        db.session.rollback()
        logger.warning('Could not ensure prospect geo schema: %s', exc)


def get_area_filter(user_id: str) -> Optional[ProspectAreaFilter]:
    ensure_prospect_geo_schema()
    return ProspectAreaFilter.query.filter_by(user_id=user_id).first()


def serialize_area_filter(row: Optional[ProspectAreaFilter]) -> dict:
    if row is None:
        return {
            'enabled': False,
            'label': None,
            'geometry': None,
            'updated_at': None,
        }
    return {
        'enabled': bool(row.enabled),
        'label': row.label,
        'geometry': row.geometry,
        'updated_at': row.updated_at.isoformat() + 'Z' if row.updated_at else None,
    }


def save_area_filter(
    user_id: str,
    *,
    enabled: bool,
    geometry: Optional[dict],
    label: Optional[str] = None,
) -> ProspectAreaFilter:
    ensure_prospect_geo_schema()
    if enabled and not geometry:
        raise ValueError('geometry is required when the area filter is enabled')

    row = get_area_filter(user_id)
    if row is None:
        row = ProspectAreaFilter(user_id=user_id)
        db.session.add(row)
    row.enabled = enabled
    row.geometry = geometry
    row.label = (label or '').strip() or None
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return row


def clear_area_filter(user_id: str) -> None:
    ensure_prospect_geo_schema()
    row = get_area_filter(user_id)
    if row is None:
        return
    row.enabled = False
    row.geometry = None
    row.label = None
    row.updated_at = datetime.utcnow()
    db.session.commit()


def polygon_ring(geometry: Optional[dict]) -> Optional[list[tuple[float, float]]]:
    """Extract exterior ring as (lat, lon) tuples from GeoJSON Polygon."""
    if not geometry or geometry.get('type') != 'Polygon':
        return None
    coords = geometry.get('coordinates')
    if not coords or not coords[0]:
        return None
    ring: list[tuple[float, float]] = []
    for pair in coords[0]:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        lng, lat = float(pair[0]), float(pair[1])
        ring.append((lat, lng))
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def point_in_polygon(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test. Ring vertices are (lat, lon)."""
    inside = False
    n = len(ring)
    if n < 4:
        return False
    j = n - 1
    for i in range(n):
        lat_i, lon_i = ring[i]
        lat_j, lon_j = ring[j]
        intersects = (
            (lon_i > lon) != (lon_j > lon)
            and lat < (lat_j - lat_i) * (lon - lon_i) / ((lon_j - lon_i) or 1e-12) + lat_i
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def geometry_from_google_path(path: list[dict[str, float]]) -> dict:
    """Convert Google Maps LatLngLiteral list to GeoJSON Polygon."""
    if len(path) < 3:
        raise ValueError('A polygon needs at least 3 points')
    coordinates = [[pt['lng'], pt['lat']] for pt in path]
    if coordinates[0] != coordinates[-1]:
        coordinates.append(coordinates[0])
    return {'type': 'Polygon', 'coordinates': [coordinates]}


def candidate_matches_area_filter(candidate: ProspectCandidate, user_id: str) -> bool:
    row = get_area_filter(user_id)
    if row is None or not row.enabled:
        return True
    ring = polygon_ring(row.geometry)
    if ring is None:
        return True
    if candidate.latitude is None or candidate.longitude is None:
        return False
    return point_in_polygon(float(candidate.latitude), float(candidate.longitude), ring)


class AreaFilterStats:
    def __init__(
        self,
        *,
        filter_enabled: bool,
        total_unfiltered: int,
        total_filtered: int,
        hidden_outside_area: int,
        hidden_no_coords: int,
    ):
        self.filter_enabled = filter_enabled
        self.total_unfiltered = total_unfiltered
        self.total_filtered = total_filtered
        self.hidden_outside_area = hidden_outside_area
        self.hidden_no_coords = hidden_no_coords

    def as_dict(self) -> dict[str, Any]:
        return {
            'filter_enabled': self.filter_enabled,
            'total_unfiltered': self.total_unfiltered,
            'total_filtered': self.total_filtered,
            'hidden_outside_area': self.hidden_outside_area,
            'hidden_no_coords': self.hidden_no_coords,
        }


def apply_area_filter_to_candidates(
    candidates: list[ProspectCandidate],
    user_id: str,
) -> tuple[list[ProspectCandidate], AreaFilterStats]:
    row = get_area_filter(user_id)
    total_unfiltered = len(candidates)
    if row is None or not row.enabled:
        return candidates, AreaFilterStats(
            filter_enabled=False,
            total_unfiltered=total_unfiltered,
            total_filtered=total_unfiltered,
            hidden_outside_area=0,
            hidden_no_coords=0,
        )

    ring = polygon_ring(row.geometry)
    if ring is None:
        return candidates, AreaFilterStats(
            filter_enabled=False,
            total_unfiltered=total_unfiltered,
            total_filtered=total_unfiltered,
            hidden_outside_area=0,
            hidden_no_coords=0,
        )

    inside: list[ProspectCandidate] = []
    hidden_outside = 0
    hidden_no_coords = 0
    for candidate in candidates:
        if candidate.latitude is None or candidate.longitude is None:
            hidden_no_coords += 1
            continue
        if point_in_polygon(float(candidate.latitude), float(candidate.longitude), ring):
            inside.append(candidate)
        else:
            hidden_outside += 1

    return inside, AreaFilterStats(
        filter_enabled=True,
        total_unfiltered=total_unfiltered,
        total_filtered=len(inside),
        hidden_outside_area=hidden_outside,
        hidden_no_coords=hidden_no_coords,
    )
