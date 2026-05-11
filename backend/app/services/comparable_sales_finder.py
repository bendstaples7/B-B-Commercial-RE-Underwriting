"""Comparable Sales Finder with radius expansion and filtering."""
import logging
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import requests
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from math import radians, cos, sin, asin, sqrt
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeMeta
from app import db
from app.models.property_facts import PropertyFacts, PropertyType, ConstructionType
from app.models.comparable_sale import ComparableSale
from app.models.parcel_universe_cache import ParcelUniverseCache
from app.models.parcel_sales_cache import ParcelSalesCache
from app.models.improvement_characteristics_cache import ImprovementCharacteristicsCache

logger = logging.getLogger(__name__)


# Cook County Socrata dataset endpoints
_PARCEL_UNIVERSE_URL   = "https://datacatalog.cookcountyil.gov/resource/pabr-t5kh.json"
_PARCEL_SALES_URL      = "https://datacatalog.cookcountyil.gov/resource/wvhk-k5uv.json"
_IMPROVEMENT_CHARS_URL = "https://datacatalog.cookcountyil.gov/resource/bcnq-qi2z.json"

# Cook County property class → PropertyType mapping
# Single-family: 202
# Multi-family: 203–208 (2-flat through 7+ units)
# Condo/commercial: 299, 295, 278, 234, 241 — excluded from residential comps
_CLASS_TO_PROPERTY_TYPE: Dict[str, str] = {
    '202': PropertyType.SINGLE_FAMILY.value,
    '203': PropertyType.MULTI_FAMILY.value,
    '204': PropertyType.MULTI_FAMILY.value,
    '205': PropertyType.MULTI_FAMILY.value,
    '206': PropertyType.MULTI_FAMILY.value,
    '207': PropertyType.MULTI_FAMILY.value,
    '208': PropertyType.MULTI_FAMILY.value,
    '211': PropertyType.MULTI_FAMILY.value,
    '212': PropertyType.MULTI_FAMILY.value,
}

# Residential classes to include in comparable searches
_SINGLE_FAMILY_CLASSES = {'202'}
_MULTI_FAMILY_CLASSES  = {'203', '204', '205', '206', '207', '208', '211', '212'}
_ALL_RESIDENTIAL_CLASSES = _SINGLE_FAMILY_CLASSES | _MULTI_FAMILY_CLASSES

# ext_wall code → ConstructionType (same mapping as PropertyDataService)
_EXT_WALL_MAP: Dict[int, str] = {
    1: ConstructionType.FRAME.value,
    2: ConstructionType.FRAME.value,
    3: ConstructionType.BRICK.value,
    4: ConstructionType.BRICK.value,
    5: ConstructionType.MASONRY.value,
    6: ConstructionType.MASONRY.value,
    7: ConstructionType.MASONRY.value,
}

# Degrees of latitude/longitude per mile (approximate, good enough for bounding box)
_MILES_PER_DEGREE_LAT = 69.0
_MILES_PER_DEGREE_LON_AT_CHICAGO = 52.5  # cos(41.88°) * 69.0


class CookCountySalesDataSource:
    """
    Comparable sales data source backed by Cook County Assessor open datasets.

    Uses three Socrata datasets:
      - pabr-t5kh  Parcel Universe (lat/lon per PIN)
      - wvhk-k5uv  Parcel Sales (sale price, date, class, arm's-length flags)
      - bcnq-qi2z  Improvement Characteristics (sqft, beds, baths, year built, construction)

    Strategy:
      1. Query Parcel Universe with a bounding box to get PINs near the subject.
      2. Query Parcel Sales filtered by those PINs, date range, property class,
         and arm's-length filters.
      3. Query Improvement Characteristics for the matched PINs.
      4. Merge all three datasets and map to the internal comparable dict format.
    """

    # Maximum PINs to include in a single IN-clause query (Socrata path only)
    _PIN_BATCH_SIZE = 100

    # Canonical output keys — every comparable dict must contain exactly these keys.
    # Absent values are represented as None, never omitted.
    _REQUIRED_OUTPUT_KEYS = (
        'pin', 'sale_date', 'sale_price', 'property_type', 'units',
        'bedrooms', 'bathrooms', 'square_footage', 'lot_size', 'year_built',
        'construction_type', 'interior_condition', 'latitude', 'longitude',
        'similarity_notes', 'address',
    )

    def __init__(self):
        self._app_token = os.getenv('COOK_COUNTY_APP_TOKEN')

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_comparables(
        self,
        subject_facts: PropertyFacts,
        max_age_months: int,
        max_distance_miles: float,
        max_count: int,
    ) -> List[Dict[str, Any]]:
        """
        Fetch comparable sales from Cook County open datasets.

        Args:
            subject_facts:      Subject property (must have latitude and longitude).
            max_age_months:     Only include sales within this many months.
            max_distance_miles: Bounding-box half-width in miles.
            max_count:          Maximum number of comparables to return.

        Returns:
            List of comparable dicts in the internal format expected by
            ComparableSalesFinder.  Each dict has distance_miles populated.
        """
        if not subject_facts.latitude or not subject_facts.longitude:
            return []

        lat = float(subject_facts.latitude)
        lon = float(subject_facts.longitude)

        # Step 1 — bounding box → PINs with coordinates
        pin_coords = self._fetch_pins_in_bbox(lat, lon, max_distance_miles)
        if not pin_coords:
            return []

        pins = list(pin_coords.keys())

        # Step 2 — filter sales by those PINs, date, class, arm's-length
        cutoff_date = datetime.now() - timedelta(days=max_age_months * 30)
        target_classes = self._classes_for_property_type(subject_facts.property_type)
        sales = self._fetch_sales_for_pins(pins, cutoff_date, target_classes)
        if not sales:
            return []

        # Step 3 — improvement characteristics for the sold PINs
        sold_pins = list({s['pin'] for s in sales})
        chars_by_pin = self._fetch_improvement_chars(sold_pins)

        # Step 4 — merge and map to internal format
        comparables: List[Dict[str, Any]] = []
        for sale in sales:
            pin = sale['pin']
            coords = pin_coords.get(pin)
            if not coords:
                continue  # no coordinates → skip

            sale_lat, sale_lon = coords
            chars = chars_by_pin.get(pin, {})
            comp = self._map_to_comparable(sale, chars, sale_lat, sale_lon)
            comparables.append(comp)

        return comparables[:max_count]

    # ------------------------------------------------------------------
    # Cache helper
    # ------------------------------------------------------------------

    def _cache_has_rows(self, table_model) -> bool:
        """Return True if the given cache table contains at least one row."""
        try:
            table_name = table_model.__tablename__
            result = db.session.execute(
                text(f"SELECT EXISTS(SELECT 1 FROM {table_name})")
            )
            return bool(result.scalar())
        except Exception as exc:
            logger.warning(
                "CookCountySalesDataSource._cache_has_rows failed for %s: %s",
                getattr(table_model, '__tablename__', table_model),
                exc,
            )
            return False

    # ------------------------------------------------------------------
    # Step 1 — Parcel Universe bounding box query
    # ------------------------------------------------------------------

    def _fetch_pins_in_bbox(
        self,
        center_lat: float,
        center_lon: float,
        radius_miles: float,
    ) -> Dict[str, Tuple[float, float]]:
        """
        Query Parcel Universe for parcels within a bounding box.

        Queries parcel_universe_cache when the table is non-empty; falls back
        to the live Socrata API otherwise.

        Returns:
            Dict mapping PIN → (lat, lon).
        """
        lat_delta = radius_miles / _MILES_PER_DEGREE_LAT
        lon_delta = radius_miles / _MILES_PER_DEGREE_LON_AT_CHICAGO

        min_lat = center_lat - lat_delta
        max_lat = center_lat + lat_delta
        min_lon = center_lon - lon_delta
        max_lon = center_lon + lon_delta

        result: Dict[str, Tuple[float, float]] = {}

        if self._cache_has_rows(ParcelUniverseCache):
            # --- Cache path ---
            rows = db.session.execute(
                text(
                    "SELECT pin, lat, lon FROM parcel_universe_cache "
                    "WHERE lat BETWEEN :min_lat AND :max_lat "
                    "AND lon BETWEEN :min_lon AND :max_lon"
                ),
                {
                    'min_lat': min_lat,
                    'max_lat': max_lat,
                    'min_lon': min_lon,
                    'max_lon': max_lon,
                },
            ).fetchall()

            for row in rows:
                pin = row[0]
                try:
                    plat = float(row[1])
                    plon = float(row[2])
                except (TypeError, ValueError):
                    continue
                if pin:
                    result[pin] = (plat, plon)

            return result

        # --- Socrata fallback ---
        logger.warning(
            "CookCountySalesDataSource: parcel_universe_cache is empty — "
            "falling back to live Socrata API for bounding-box lookup."
        )

        where = (
            f"lat >= {min_lat} AND lat <= {max_lat} "
            f"AND lon >= {min_lon} AND lon <= {max_lon}"
        )
        url = (
            _PARCEL_UNIVERSE_URL
            + "?$select=pin,lat,lon"
            + "&$where=" + urllib.parse.quote(where)
            + "&$limit=5000"
        )

        rows_api = self._socrata_get(url)
        for row in rows_api:
            pin = row.get('pin')
            try:
                plat = float(row['lat'])
                plon = float(row['lon'])
            except (KeyError, TypeError, ValueError):
                continue
            if pin:
                result[pin] = (plat, plon)

        return result

    # ------------------------------------------------------------------
    # Step 2 — Parcel Sales query
    # ------------------------------------------------------------------

    def _fetch_sales_for_pins(
        self,
        pins: List[str],
        cutoff_date: datetime,
        target_classes: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Query Parcel Sales for the given PINs with date, class, and
        arm's-length filters applied.

        Queries parcel_sales_cache when the table is non-empty (single query,
        no batch loop); falls back to the live Socrata API otherwise.

        Returns:
            List of sale dicts with keys: pin, sale_date, sale_price, class.
        """
        if not pins or not target_classes:
            return []

        if self._cache_has_rows(ParcelSalesCache):
            # --- Cache path — single parameterised query, no batch loop ---
            cutoff_date_only = cutoff_date.date() if hasattr(cutoff_date, 'date') else cutoff_date

            from sqlalchemy import bindparam
            stmt = text(
                "SELECT pin, sale_date, sale_price, class "
                "FROM parcel_sales_cache "
                "WHERE pin IN :pins "
                "AND sale_date >= :cutoff_date "
                "AND class IN :target_classes "
                "AND sale_type = 'LAND AND BUILDING' "
                "AND (is_multisale IS NULL OR is_multisale = false) "
                "AND (sale_filter_less_than_10k IS NULL OR sale_filter_less_than_10k = false) "
                "AND (sale_filter_deed_type IS NULL OR sale_filter_deed_type = false)"
            ).bindparams(
                bindparam('pins', expanding=True),
                bindparam('target_classes', expanding=True),
            )

            rows = db.session.execute(
                stmt,
                {
                    'pins': list(pins),
                    'cutoff_date': cutoff_date_only,
                    'target_classes': list(target_classes),
                },
            ).fetchall()

            all_sales: List[Dict[str, Any]] = []
            for row in rows:
                sale_date_val = row[1]
                # Normalise date to ISO string
                if sale_date_val is not None:
                    if hasattr(sale_date_val, 'strftime'):
                        sale_date_str = sale_date_val.strftime('%Y-%m-%dT00:00:00.000')
                    else:
                        sale_date_str = str(sale_date_val)
                else:
                    sale_date_str = None

                all_sales.append({
                    'pin': row[0],
                    'sale_date': sale_date_str,
                    'sale_price': str(row[2]) if row[2] is not None else None,
                    'class': row[3],
                })

            return all_sales

        # --- Socrata fallback ---
        logger.warning(
            "CookCountySalesDataSource: parcel_sales_cache is empty — "
            "falling back to live Socrata API for sales lookup."
        )

        date_str = cutoff_date.strftime('%Y-%m-%dT00:00:00.000')
        class_list = ','.join(f"'{c}'" for c in target_classes)

        all_sales_api: List[Dict[str, Any]] = []

        # Batch PIN queries to stay within URL length limits
        for i in range(0, len(pins), self._PIN_BATCH_SIZE):
            batch = pins[i : i + self._PIN_BATCH_SIZE]
            pin_list = ','.join(f"'{p}'" for p in batch)

            where = (
                f"pin in ({pin_list})"
                f" AND sale_date >= '{date_str}'"
                f" AND class in ({class_list})"
                f" AND sale_type='LAND AND BUILDING'"
                f" AND is_multisale=false"
                f" AND sale_filter_less_than_10k=false"
                f" AND sale_filter_deed_type=false"
            )
            url = (
                _PARCEL_SALES_URL
                + "?$select=pin,sale_date,sale_price,class"
                + "&$where=" + urllib.parse.quote(where)
                + "&$limit=1000"
            )

            rows_api = self._socrata_get(url)
            all_sales_api.extend(rows_api)

        return all_sales_api

    # ------------------------------------------------------------------
    # Step 3 — Improvement Characteristics query
    # ------------------------------------------------------------------

    def _fetch_improvement_chars(
        self,
        pins: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """
        Query Improvement Characteristics for the given PINs.

        Queries improvement_characteristics_cache when the table is non-empty;
        falls back to the live Socrata API otherwise.

        Returns:
            Dict mapping PIN → parsed characteristics dict with keys:
            square_footage, bedrooms, bathrooms, year_built, construction_type.
        """
        result: Dict[str, Dict[str, Any]] = {}

        if self._cache_has_rows(ImprovementCharacteristicsCache):
            # --- Cache path ---
            from sqlalchemy import bindparam
            stmt = text(
                "SELECT pin, bldg_sf, beds, fbath, hbath, age, ext_wall, apts "
                "FROM improvement_characteristics_cache "
                "WHERE pin IN :pins"
            ).bindparams(bindparam('pins', expanding=True))

            rows = db.session.execute(stmt, {'pins': list(pins)}).fetchall()

            for row in rows:
                pin = row[0]
                if not pin:
                    continue
                raw = {
                    'pin':     row[0],
                    'bldg_sf': str(row[1]) if row[1] is not None else None,
                    'beds':    str(row[2]) if row[2] is not None else None,
                    'fbath':   str(row[3]) if row[3] is not None else None,
                    'hbath':   str(row[4]) if row[4] is not None else None,
                    'age':     str(row[5]) if row[5] is not None else None,
                    'ext_wall': str(row[6]) if row[6] is not None else None,
                    'apts':    str(row[7]) if row[7] is not None else None,
                }
                result[pin] = self._parse_improvement_chars(raw)

            return result

        # --- Socrata fallback ---
        logger.warning(
            "CookCountySalesDataSource: improvement_characteristics_cache is empty — "
            "falling back to live Socrata API for improvement characteristics lookup."
        )

        for i in range(0, len(pins), self._PIN_BATCH_SIZE):
            batch = pins[i : i + self._PIN_BATCH_SIZE]
            pin_list = ','.join(f"'{p}'" for p in batch)

            where = f"pin in ({pin_list})"
            url = (
                _IMPROVEMENT_CHARS_URL
                + "?$select=pin,bldg_sf,beds,fbath,hbath,age,ext_wall,apts"
                + "&$where=" + urllib.parse.quote(where)
                + "&$limit=1000"
            )

            rows_api = self._socrata_get(url)
            for row in rows_api:
                pin = row.get('pin')
                if not pin:
                    continue
                result[pin] = self._parse_improvement_chars(row)

        return result

    def _parse_improvement_chars(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Parse a raw improvement characteristics row into typed fields."""
        out: Dict[str, Any] = {}

        # Square footage
        bldg_sf = row.get('bldg_sf')
        if bldg_sf is not None:
            try:
                out['square_footage'] = int(float(bldg_sf))
            except (ValueError, TypeError):
                pass

        # Bedrooms
        beds = row.get('beds')
        if beds is not None:
            try:
                out['bedrooms'] = int(float(beds))
            except (ValueError, TypeError):
                pass

        # Bathrooms: full + 0.5 * half
        fbath = row.get('fbath')
        hbath = row.get('hbath')
        try:
            full = float(fbath) if fbath is not None else 0.0
            half = float(hbath) if hbath is not None else 0.0
            if fbath is not None or hbath is not None:
                out['bathrooms'] = full + 0.5 * half
        except (ValueError, TypeError):
            pass

        # Year built: 'age' is years-since-built
        age = row.get('age')
        if age is not None:
            try:
                out['year_built'] = datetime.now().year - int(float(age))
            except (ValueError, TypeError):
                pass

        # Construction type from ext_wall code
        ext_wall = row.get('ext_wall')
        if ext_wall is not None:
            try:
                code = int(float(ext_wall))
                out['construction_type'] = _EXT_WALL_MAP.get(code, ConstructionType.FRAME.value)
            except (ValueError, TypeError):
                out['construction_type'] = ConstructionType.FRAME.value
        else:
            out['construction_type'] = ConstructionType.FRAME.value

        # Unit count from 'apts' field
        apts = row.get('apts')
        if apts is not None:
            try:
                apt_count = int(float(apts))
                if apt_count > 0:
                    out['units'] = apt_count
            except (ValueError, TypeError):
                pass

        return out

    # ------------------------------------------------------------------
    # Step 4 — Map to internal comparable dict format
    # ------------------------------------------------------------------

    def _map_to_comparable(
        self,
        sale: Dict[str, Any],
        chars: Dict[str, Any],
        sale_lat: float,
        sale_lon: float,
    ) -> Dict[str, Any]:
        """
        Merge a sale record and its improvement characteristics into the
        internal comparable dict format expected by ComparableSalesFinder.

        Every key in _REQUIRED_OUTPUT_KEYS is always present; absent values
        are None rather than omitted.
        """
        # Parse sale_date — Socrata returns ISO format e.g. "2024-03-15T00:00:00.000"
        sale_date_raw = sale.get('sale_date', '')
        sale_date: Optional[str] = None
        if sale_date_raw:
            try:
                dt = datetime.fromisoformat(sale_date_raw.replace('Z', '+00:00'))
                sale_date = dt.strftime('%Y-%m-%d')
            except (ValueError, AttributeError):
                sale_date = sale_date_raw[:10] if len(sale_date_raw) >= 10 else sale_date_raw

        # Parse sale_price
        sale_price: Optional[float] = None
        raw_price = sale.get('sale_price')
        if raw_price is not None:
            try:
                sale_price = float(raw_price)
            except (ValueError, TypeError):
                pass

        # Map property class to property type
        prop_class = sale.get('class', '')
        property_type = _CLASS_TO_PROPERTY_TYPE.get(prop_class, PropertyType.SINGLE_FAMILY.value)

        comp = {
            'pin':                sale.get('pin'),
            'address':            None,                                    # not available in sales dataset
            'sale_date':          sale_date,
            'sale_price':         sale_price,
            'property_type':      property_type,
            'units':              chars.get('units'),
            'bedrooms':           chars.get('bedrooms'),
            'bathrooms':          chars.get('bathrooms'),
            'square_footage':     chars.get('square_footage'),
            'lot_size':           None,                                    # not in these datasets
            'year_built':         chars.get('year_built'),
            'construction_type':  chars.get('construction_type', ConstructionType.FRAME.value),
            'interior_condition': 'average',                               # not available; default
            'latitude':           sale_lat,
            'longitude':          sale_lon,
            'similarity_notes':   '',
        }

        # Guarantee every required key is present (None if absent)
        for key in self._REQUIRED_OUTPUT_KEYS:
            if key not in comp:
                comp[key] = None

        return comp

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classes_for_property_type(property_type: PropertyType) -> List[str]:
        """Return the Cook County class codes that match the given property type."""
        if property_type == PropertyType.SINGLE_FAMILY:
            return sorted(_SINGLE_FAMILY_CLASSES)
        elif property_type == PropertyType.MULTI_FAMILY:
            return sorted(_MULTI_FAMILY_CLASSES)
        else:
            # Commercial — return all residential classes as a fallback
            return sorted(_ALL_RESIDENTIAL_CLASSES)

    def _socrata_get(self, url: str) -> List[Dict[str, Any]]:
        """
        Fetch a Socrata JSON endpoint using urllib.request.

        Sends the URL exactly as given (no re-encoding of '$' in parameter
        names).  Returns parsed JSON list, or empty list on any error.
        """
        headers: Dict[str, str] = {}
        if self._app_token:
            headers['X-App-Token'] = self._app_token

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode('utf-8')[:200]
            except Exception:
                pass
            print(f"CookCountySalesDataSource HTTP {exc.code} for {url!r}: {body}")
        except urllib.error.URLError as exc:
            print(f"CookCountySalesDataSource URL error for {url!r}: {exc.reason}")
        except Exception as exc:
            print(f"CookCountySalesDataSource error for {url!r}: {exc}")

        return []


class MLSDataSource:
    """
    Comparable sales data source backed by an MLS API.

    Only active when the ``MLS_API_KEY`` environment variable is set.
    Wraps the original MLS placeholder logic so it can participate in the
    pluggable data-source registry alongside ``CookCountySalesDataSource``.
    """

    def __init__(self, mls_api_key: str):
        self._mls_api_key = mls_api_key

    def fetch_comparables(
        self,
        subject_facts: PropertyFacts,
        max_age_months: int,
        max_distance_miles: float,
        max_count: int,
    ) -> List[Dict[str, Any]]:
        """
        Fetch comparable sales from the MLS API.

        Returns an empty list if the API call fails or the key is not set.
        """
        if not subject_facts.latitude or not subject_facts.longitude:
            return []

        cutoff_date = datetime.now() - timedelta(days=max_age_months * 30)
        center = (subject_facts.latitude, subject_facts.longitude)

        try:
            url = "https://api.mls-provider.com/v1/sales/search"
            headers = {'Authorization': f'Bearer {self._mls_api_key}'}
            params = {
                'latitude': center[0],
                'longitude': center[1],
                'radius_miles': max_distance_miles,
                'min_sale_date': cutoff_date.strftime('%Y-%m-%d'),
                'exclude_foreclosures': True,
                'exclude_family_transfers': True,
            }

            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            return [_transform_mls_sale(sale) for sale in data.get('sales', [])]

        except Exception as exc:
            print(f"MLSDataSource sales search error: {exc}")
            return []


def _transform_mls_sale(sale_response: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a raw MLS API sale response to the internal comparable dict format."""
    return {
        'address': sale_response.get('address'),
        'sale_date': sale_response.get('saleDate'),
        'sale_price': sale_response.get('salePrice'),
        'property_type': _map_mls_property_type(sale_response.get('propertyType')),
        'units': sale_response.get('units', 1),
        'bedrooms': sale_response.get('bedrooms', 0),
        'bathrooms': sale_response.get('bathrooms', 0),
        'square_footage': sale_response.get('squareFeet'),
        'lot_size': sale_response.get('lotSize'),
        'year_built': sale_response.get('yearBuilt'),
        'construction_type': _map_mls_construction_type(sale_response.get('construction')),
        'interior_condition': _map_mls_interior_condition(sale_response.get('condition')),
        'latitude': sale_response.get('latitude'),
        'longitude': sale_response.get('longitude'),
        'similarity_notes': '',
        'pin': None,  # MLS sales have no PIN; deduplication uses address+sale_date
    }


def _map_mls_property_type(external_type: Optional[str]) -> Optional[str]:
    """Map an MLS property type string to the internal enum value."""
    if not external_type:
        return None
    type_mapping = {
        'single family': PropertyType.SINGLE_FAMILY.value,
        'single-family': PropertyType.SINGLE_FAMILY.value,
        'sfr': PropertyType.SINGLE_FAMILY.value,
        'multi family': PropertyType.MULTI_FAMILY.value,
        'multi-family': PropertyType.MULTI_FAMILY.value,
        'multifamily': PropertyType.MULTI_FAMILY.value,
        'commercial': PropertyType.COMMERCIAL.value,
        'retail': PropertyType.COMMERCIAL.value,
        'office': PropertyType.COMMERCIAL.value,
    }
    return type_mapping.get(external_type.lower())


def _map_mls_construction_type(external_construction: Optional[str]) -> Optional[str]:
    """Map an MLS construction type string to the internal enum value."""
    if not external_construction:
        return ConstructionType.FRAME.value
    construction_mapping = {
        'frame': ConstructionType.FRAME.value,
        'wood': ConstructionType.FRAME.value,
        'wood frame': ConstructionType.FRAME.value,
        'brick': ConstructionType.BRICK.value,
        'brick veneer': ConstructionType.BRICK.value,
        'masonry': ConstructionType.MASONRY.value,
        'concrete': ConstructionType.MASONRY.value,
        'stone': ConstructionType.MASONRY.value,
    }
    return construction_mapping.get(external_construction.lower(), ConstructionType.FRAME.value)


def _map_mls_interior_condition(external_condition: Optional[str]) -> Optional[str]:
    """Map an MLS interior condition string to the internal enum value."""
    from app.models.property_facts import InteriorCondition
    if not external_condition:
        return 'average'
    condition_mapping = {
        'needs gut': InteriorCondition.NEEDS_GUT.value,
        'needs_gut': InteriorCondition.NEEDS_GUT.value,
        'poor': InteriorCondition.POOR.value,
        'fair': InteriorCondition.POOR.value,
        'average': InteriorCondition.AVERAGE.value,
        'good': InteriorCondition.AVERAGE.value,
        'new renovation': InteriorCondition.NEW_RENO.value,
        'new_reno': InteriorCondition.NEW_RENO.value,
        'renovated': InteriorCondition.NEW_RENO.value,
        'high end': InteriorCondition.HIGH_END.value,
        'high_end': InteriorCondition.HIGH_END.value,
        'luxury': InteriorCondition.HIGH_END.value,
    }
    return condition_mapping.get(external_condition.lower(), InteriorCondition.AVERAGE.value)


class ComparableSalesFinder:
    """Service for finding comparable sales with radius expansion algorithm."""
    
    # Search radius sequence in miles
    RADIUS_SEQUENCE = [0.25, 0.5, 0.75, 1.0]
    MIN_COMPARABLES = 10
    MAX_AGE_MONTHS = 36
    
    def __init__(self):
        """
        Initialise the service and build the pluggable data-source registry.

        Registry order determines priority:
          1. CookCountySalesDataSource — always registered (free, no key required)
          2. MLSDataSource             — registered only when MLS_API_KEY is set
        """
        self.mls_api_key = os.getenv('MLS_API_KEY')
        self.tax_assessor_api_key = os.getenv('TAX_ASSESSOR_API_KEY')

        # Pluggable data-source registry.  Sources are queried in order;
        # results are aggregated and deduplicated by PIN.
        self._data_sources: List[Any] = [CookCountySalesDataSource()]
        if self.mls_api_key:
            self._data_sources.append(MLSDataSource(self.mls_api_key))
    
    def find_comparables(
        self,
        subject: PropertyFacts,
        min_count: int = MIN_COMPARABLES,
        max_age_months: int = MAX_AGE_MONTHS
    ) -> List[Dict[str, Any]]:
        """
        Find comparable sales using radius expansion algorithm.
        
        Algorithm:
        1. Start with 0.25 mile radius
        2. Query all registered data sources within the radius:
           - Sale date within max_age_months
           - Property type matches subject
           - Valid arm's-length sale
        3. Aggregate results from all sources; deduplicate by PIN
        4. If count < min_count, expand radius: 0.25 → 0.5 → 0.75 → 1.0 miles
        5. Return first min_count+ results or all if < min_count at max radius
        
        Args:
            subject: Subject property facts
            min_count: Minimum number of comparables required (default: 10)
            max_age_months: Maximum age of sales in months (default: 12)
            
        Returns:
            List of comparable sale dictionaries
        """
        if not subject.latitude or not subject.longitude:
            raise ValueError("Subject property must have geocoded coordinates")
        
        # Calculate cutoff date for sale filtering
        cutoff_date = datetime.now() - timedelta(days=max_age_months * 30)
        
        comparables: List[Dict[str, Any]] = []
        seen_pins: set = set()

        # Try each radius in sequence
        for radius in self.RADIUS_SEQUENCE:
            radius_comparables: List[Dict[str, Any]] = []

            # Query every registered data source
            for source in self._data_sources:
                raw_sales = source.fetch_comparables(
                    subject_facts=subject,
                    max_age_months=max_age_months,
                    max_distance_miles=radius,
                    max_count=min_count * 5,  # fetch generously; we filter below
                )

                # Filter by property type and sale date
                filtered = self.filter_by_property_type(raw_sales, subject.property_type)
                filtered = self._filter_by_sale_date(filtered, cutoff_date)

                for sale in filtered:
                    if not (sale.get('latitude') and sale.get('longitude')):
                        continue

                    # Deduplicate by PIN (None-PIN sales are always included)
                    pin = sale.get('pin')
                    if pin and pin in seen_pins:
                        continue

                    distance = self._calculate_distance(
                        (subject.latitude, subject.longitude),
                        (sale['latitude'], sale['longitude'])
                    )

                    # Enforce the radius strictly (sources may return slightly
                    # more than requested due to bounding-box approximation)
                    if distance > radius:
                        continue

                    sale['distance_miles'] = distance
                    radius_comparables.append(sale)
                    if pin:
                        seen_pins.add(pin)

            comparables.extend(radius_comparables)

            # Check if we have enough comparables
            if len(comparables) >= min_count:
                comparables.sort(key=lambda x: x['distance_miles'])
                return comparables[:min_count]
        
        # Exhausted all radii — return whatever we have
        comparables.sort(key=lambda x: x['distance_miles'])
        return comparables
    
    def expand_search_radius(self, current_radius: float) -> Optional[float]:
        """
        Get the next radius in the expansion sequence.
        
        Args:
            current_radius: Current search radius in miles
            
        Returns:
            Next radius in sequence, or None if at maximum
        """
        try:
            current_index = self.RADIUS_SEQUENCE.index(current_radius)
            if current_index < len(self.RADIUS_SEQUENCE) - 1:
                return self.RADIUS_SEQUENCE[current_index + 1]
        except ValueError:
            # Current radius not in sequence, return first radius larger than current
            for radius in self.RADIUS_SEQUENCE:
                if radius > current_radius:
                    return radius
        
        return None
    
    def filter_by_property_type(
        self,
        sales: List[Dict[str, Any]],
        property_type: PropertyType
    ) -> List[Dict[str, Any]]:
        """
        Filter sales by property type to ensure residential matches residential
        and commercial matches commercial.
        
        Args:
            sales: List of sale dictionaries
            property_type: Subject property type to match
            
        Returns:
            Filtered list of sales matching property type
        """
        return [
            sale for sale in sales
            if sale.get('property_type') == property_type.value
        ]
    
    def _filter_by_sale_date(
        self,
        sales: List[Dict[str, Any]],
        cutoff_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Filter sales by date to include only recent sales.
        
        Args:
            sales: List of sale dictionaries
            cutoff_date: Minimum sale date to include
            
        Returns:
            Filtered list of sales within date range
        """
        filtered = []
        for sale in sales:
            sale_date = sale.get('sale_date')
            if sale_date:
                # Handle both datetime and string date formats
                if isinstance(sale_date, str):
                    try:
                        sale_date = datetime.strptime(sale_date, '%Y-%m-%d')
                    except ValueError:
                        continue
                
                # Normalize date to datetime for comparison
                if hasattr(sale_date, 'year') and not isinstance(sale_date, datetime):
                    sale_date = datetime(sale_date.year, sale_date.month, sale_date.day)
                
                if sale_date >= cutoff_date:
                    filtered.append(sale)
        
        return filtered
    
    def _calculate_distance(
        self,
        point1: Tuple[float, float],
        point2: Tuple[float, float]
    ) -> float:
        """
        Calculate distance between two geographic points using Haversine formula.
        
        Args:
            point1: Tuple of (latitude, longitude) for first point
            point2: Tuple of (latitude, longitude) for second point
            
        Returns:
            Distance in miles
        """
        lat1, lon1 = point1
        lat2, lon2 = point2
        
        # Convert to radians
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        
        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        
        # Earth radius in miles
        earth_radius_miles = 3959
        
        return c * earth_radius_miles

