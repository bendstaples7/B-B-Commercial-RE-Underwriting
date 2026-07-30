"""Cook County parcel proximity lookup via CookViewer3Parcels MapServer.

Used as a fallback when Socrata address ladder returns no PIN — e.g. corner
parcels whose tax situs street differs from the marketing / CoStar range.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_PARCEL_MAPSERVER_URL = (
    'https://gis12.cookcountyil.gov/traditional/rest/services/'
    'CookViewer3Parcels/MapServer/0'
)
TIMEOUT_SECONDS = 12
# ~100 m box around geocode point (degrees at Chicago latitude ≈ 41.9°).
_DEFAULT_RADIUS_M = 100.0


def _meters_to_deg(lat: float, meters: float) -> tuple[float, float]:
    """Approximate (dlat, dlng) for a meter radius at the given latitude."""
    dlat = meters / 111_320.0
    cos_lat = max(0.2, abs(math.cos(math.radians(lat))))
    dlng = meters / (111_320.0 * cos_lat)
    return dlat, dlng


def _geocode_lat_lng(
    street: str,
    *,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
) -> tuple[float, float] | None:
    """Geocode lead situs to lat/lng, respecting the property-address geocode budget."""
    from app.services.property_address_service import _geocode_budget_allows

    if not _geocode_budget_allows():
        logger.info('Cook parcel spatial: geocode skipped (budget/circuit)')
        return None

    # Prefer a single house number for geocoders that choke on ranges.
    # Also strip city/state/ZIP that may have been concatenated into street.
    from app.services.gis.cook_county_gis_connector import _normalise_address

    street_q = _normalise_address(street or '') or (street or '').strip()
    import re as _re
    range_m = _re.match(r'^(\d+)-\d+\s+(.+)$', street_q)
    if range_m:
        street_q = f'{range_m.group(1)} {range_m.group(2)}'

    parts = [p for p in (street_q, city, state, zip_code) if (p or '').strip()]
    query = ', '.join(parts)
    if not query:
        return None

    try:
        from app.services.property_data_service import PropertyDataService

        coords = PropertyDataService().geocode_address(query)
        if coords and coords.get('lat') is not None and coords.get('lng') is not None:
            return float(coords['lat']), float(coords['lng'])
    except Exception as exc:
        logger.warning('Cook parcel spatial: Google geocode failed for %r: %s', query, exc)

    try:
        import urllib.parse

        url = (
            'https://nominatim.openstreetmap.org/search?'
            + urllib.parse.urlencode({
                'q': query,
                'format': 'json',
                'limit': 1,
                'countrycodes': 'us',
            })
        )
        resp = requests.get(
            url,
            headers={'User-Agent': 'BB-Real-Estate-Analyzer/1.0 (pin-spatial)'},
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        rows = resp.json() or []
        if rows:
            return float(rows[0]['lat']), float(rows[0]['lon'])
    except Exception as exc:
        logger.warning('Cook parcel spatial: Nominatim geocode failed for %r: %s', query, exc)

    return None


def query_parcels_near(
    lat: float,
    lng: float,
    *,
    radius_m: float = _DEFAULT_RADIUS_M,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Query CookViewer3Parcels by attribute lat/lng box (more reliable than geometry)."""
    base = os.environ.get(
        'COOK_COUNTY_PARCEL_MAPSERVER_URL',
        _DEFAULT_PARCEL_MAPSERVER_URL,
    ).rstrip('/')
    dlat, dlng = _meters_to_deg(lat, radius_m)
    where = (
        f'latitude BETWEEN {lat - dlat} AND {lat + dlat} '
        f'AND longitude BETWEEN {lng - dlng} AND {lng + dlng}'
    )
    params = {
        'where': where,
        'outFields': 'PIN14_dash,street_address,latitude,longitude',
        'returnGeometry': 'false',
        'f': 'json',
        # Fetch a wide page then distance-sort locally — server orderBy + limit
        # truncates away nearby corner parcels (PIN sort ≠ proximity).
        'resultRecordCount': max(25, min(int(limit), 200)),
    }
    url = f'{base}/query'
    last_error: Any = None
    for attempt in range(2):
        try:
            response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
            response.raise_for_status()
            data = response.json()
            if 'error' in data:
                last_error = data['error']
                logger.warning(
                    'CookViewer3Parcels error (attempt %s): %s', attempt + 1, data['error'],
                )
                continue
            rows: list[dict[str, Any]] = []
            for feature in data.get('features') or []:
                attrs = feature.get('attributes') or {}
                pin = (attrs.get('PIN14_dash') or '').strip()
                street = (attrs.get('street_address') or '').strip()
                if not pin:
                    continue
                rows.append({
                    'pin': pin,
                    'property_street': street or None,
                    'property_city': None,
                    'property_state': 'IL',
                    'property_zip': None,
                    'latitude': attrs.get('latitude'),
                    'longitude': attrs.get('longitude'),
                    'source': 'cook_parcel_spatial',
                })
            # Prefer closer parcels when coords exist.
            def _dist(row: dict[str, Any]) -> float:
                try:
                    return (
                        (float(row['latitude']) - lat) ** 2
                        + (float(row['longitude']) - lng) ** 2
                    )
                except (TypeError, ValueError, KeyError):
                    return 1e9

            rows.sort(key=_dist)
            return rows
        except Exception as exc:
            last_error = exc
            logger.warning(
                'CookViewer3Parcels query failed (attempt %s): %s', attempt + 1, exc,
            )
    if last_error:
        logger.error('CookViewer3Parcels query exhausted retries: %s', last_error)
    return []


def lookup_nearby_parcel_candidates(
    street: str,
    *,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
    radius_m: float = _DEFAULT_RADIUS_M,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Geocode situs then return nearby MapServer parcel candidates (deduped by PIN)."""
    coords = _geocode_lat_lng(street, city=city, state=state, zip_code=zip_code)
    if not coords:
        return []
    lat, lng = coords
    # Fetch a wider pool so distance-sort can surface the true corner parcel.
    rows = query_parcels_near(lat, lng, radius_m=radius_m, limit=200)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        pin = (row.get('pin') or '').strip()
        if not pin or pin in seen:
            continue
        seen.add(pin)
        out.append(row)
        if len(out) >= limit:
            break
    return out
