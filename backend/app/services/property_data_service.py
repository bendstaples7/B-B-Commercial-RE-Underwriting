"""Property Data Service — Cook County Assessor API integration with fallback logic.

All Socrata queries use urllib.request (not requests) so that $where, $limit,
and $order parameter names are never percent-encoded.  urllib.parse.quote()
with no safe override is used to encode the $where *value* — Socrata accepts
%20 for spaces, %27 for quotes, %25 for the LIKE wildcard %, etc.

Dataset schemas verified against live API responses:

  c49d-89sn  (Parcel Addresses)
    Columns: pin, property_address, property_city, property_zip, ...
    Query:   $where=property_address='1443 W FOSTER AVE'

  bcnq-qi2z  (Single & Multi-Family Improvement Characteristics)
    Columns: pin, apts, beds, fbath, hbath, bldg_sf, age, ext_wall,
             modeling_group, rooms, ...
    Query:   $where=pin='14083010190000'

  uzyt-m557  (Assessed Values)
    Columns: pin, year, certified_tot, mailed_tot, board_tot, ...
    Query:   $where=pin='14083010190000'&$order=year DESC
"""
import os
import re
import json
import redis
import requests
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from typing import Optional, Dict, Any
from app.models.property_facts import PropertyFacts, PropertyType, ConstructionType, InteriorCondition


# Cook County Socrata dataset endpoints (public, no key required)
_PARCEL_ADDRESSES_URL  = "https://datacatalog.cookcountyil.gov/resource/c49d-89sn.json"
_IMPROVEMENT_CHARS_URL = "https://datacatalog.cookcountyil.gov/resource/bcnq-qi2z.json"
_ASSESSED_VALUES_URL   = "https://datacatalog.cookcountyil.gov/resource/uzyt-m557.json"

# ext_wall code → ConstructionType value (verified from dataset)
_EXT_WALL_MAP: Dict[int, str] = {
    1: ConstructionType.FRAME.value,
    2: ConstructionType.FRAME.value,
    3: ConstructionType.BRICK.value,
    4: ConstructionType.BRICK.value,
    5: ConstructionType.MASONRY.value,
    6: ConstructionType.MASONRY.value,
    7: ConstructionType.MASONRY.value,
}

# Street-type suffixes to strip when normalising the address for lookup
_STREET_SUFFIXES = {
    'ST', 'STREET', 'AVE', 'AVENUE', 'BLVD', 'BOULEVARD', 'DR', 'DRIVE',
    'RD', 'ROAD', 'LN', 'LANE', 'CT', 'COURT', 'PL', 'PLACE', 'WAY',
    'TER', 'TERRACE', 'CIR', 'CIRCLE', 'PKWY', 'PARKWAY', 'HWY', 'HIGHWAY',
}


class PropertyDataService:
    """Service for retrieving property data from Cook County Assessor with fallback logic."""

    def __init__(self):
        self.google_maps_api_key = os.getenv('GOOGLE_MAPS_API_KEY')
        self.socrata_app_token   = os.getenv('SOCRATA_APP_TOKEN')

        # Legacy keys kept for compatibility
        self.mls_api_key          = os.getenv('MLS_API_KEY')
        self.tax_assessor_api_key = os.getenv('TAX_ASSESSOR_API_KEY')
        self.chicago_data_api_key = os.getenv('CHICAGO_DATA_API_KEY')

        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        self.redis_client = redis.from_url(redis_url, decode_responses=True)

        self.property_cache_ttl  = 86400  # 24 hours
        self.geocoding_cache_ttl = None   # permanent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_property_facts(self, address: str) -> Dict[str, Any]:
        """
        Fetch property facts from Cook County Assessor public datasets.

        Returns a dict with all known fields populated where available.
        Any field that cannot be determined is set to None.
        Never raises — all errors are caught and logged.
        """
        cache_key = "property_facts:" + address
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        result: Dict[str, Any] = {
            'address': address,
            'property_type': None,
            'units': None,
            'bedrooms': None,
            'bathrooms': None,
            'square_footage': None,
            'lot_size': None,
            'year_built': None,
            'construction_type': None,
            'basement': False,
            'parking_spaces': 0,
            'assessed_value': None,
            'annual_taxes': None,
            'zoning': None,
            'latitude': None,
            'longitude': None,
            'data_source': 'cook_county_assessor',
            'user_modified_fields': [],
            'pin': None,
        }

        # Step 1 — geocode via Google Maps (uses requests, which is fine here)
        coords = self.geocode_address(address)
        if coords:
            result['latitude']  = coords['lat']
            result['longitude'] = coords['lng']

        # Step 2 — address → PIN (14-digit)
        pin = self._lookup_pin(address)
        if not pin:
            self._set_in_cache(cache_key, result, self.property_cache_ttl)
            return result

        result['pin'] = pin

        # Step 3 — PIN → improvement characteristics
        chars = self._fetch_improvement_chars(pin)
        if chars:
            result.update(chars)

        # Step 4 — PIN → assessed value
        assessed = self._fetch_assessed_value(pin)
        if assessed:
            result.update(assessed)

        self._set_in_cache(cache_key, result, self.property_cache_ttl)
        return result

    def fetch_with_fallback(self, address: str, field: str) -> Any:
        """Return a single field from the full property facts dict."""
        return self.fetch_property_facts(address).get(field)

    def geocode_address(self, address: str) -> Optional[Dict[str, float]]:
        """Geocode via Google Maps API with permanent caching.

        Uses requests here because the Google Maps API uses standard params
        with no '$' prefix — requests encodes them correctly.
        """
        cache_key = "geocode:" + address
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        if not self.google_maps_api_key:
            return None

        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={'address': address, 'key': self.google_maps_api_key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get('status') == 'OK' and data.get('results'):
                loc = data['results'][0]['geometry']['location']
                coords = {'lat': loc['lat'], 'lng': loc['lng']}
                self._set_in_cache(cache_key, coords, self.geocoding_cache_ttl)
                return coords
        except Exception as exc:
            print("Geocoding error for " + repr(address) + ": " + str(exc))

        return None

    def validate_property_data(self, property_data: Dict[str, Any]) -> Dict[str, Any]:
        """Identify missing required fields."""
        required = [
            'property_type', 'units', 'bedrooms', 'bathrooms', 'square_footage',
            'lot_size', 'year_built', 'construction_type', 'assessed_value',
            'annual_taxes', 'zoning',
        ]
        missing = [f for f in required if not property_data.get(f)]
        return {'valid': len(missing) == 0, 'missing_fields': missing}

    def invalidate_cache(self, address: str) -> None:
        """Invalidate cached property data for an address."""
        try:
            self.redis_client.delete("property_facts:" + address)
        except Exception as exc:
            print("Cache invalidation error: " + str(exc))

    # ------------------------------------------------------------------
    # urllib-based Socrata helper
    # ------------------------------------------------------------------

    def _socrata_get(self, url: str) -> list:
        """
        Fetch a Socrata JSON endpoint using urllib.request.

        urllib.request sends the URL exactly as given — no re-encoding of
        '$' in parameter names.  The caller is responsible for encoding
        the $where *value* using urllib.parse.quote() with no safe override,
        which produces %20 for spaces, %27 for quotes, %25 for %, etc.
        Socrata decodes these correctly on its end.

        Returns parsed JSON list, or empty list on any error.
        """
        headers = {}
        if self.socrata_app_token:
            headers['X-App-Token'] = self.socrata_app_token

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode('utf-8')[:200]
            except Exception:
                pass
            print("Socrata HTTP " + str(exc.code) + " for " + repr(url) + ": " + body)
        except urllib.error.URLError as exc:
            print("Socrata URL error for " + repr(url) + ": " + str(exc.reason))
        except Exception as exc:
            print("Socrata error for " + repr(url) + ": " + str(exc))

        return []

    # ------------------------------------------------------------------
    # Address normalisation
    # ------------------------------------------------------------------

    def _normalise_address(self, address: str) -> str:
        """
        Normalise an address to match Cook County Assessor format.

        "1443 W Foster Ave, Chicago, IL 60640" → "1443 W FOSTER AVE"

        The dataset stores addresses as "NUMBER DIRECTION STREET SUFFIX"
        in uppercase, without city/state/zip.
        """
        # Take only the street portion (before the first comma)
        street_part = address.split(',')[0].strip().upper()
        return street_part

    # ------------------------------------------------------------------
    # Cook County Socrata lookups (verified column names)
    # ------------------------------------------------------------------

    def _lookup_pin(self, address: str) -> Optional[str]:
        """Step 1: address → 14-digit PIN via Cook County parcel addresses dataset.

        Dataset: c49d-89sn
        Column:  property_address (full uppercase street address, e.g. "1443 W FOSTER AVE")
        Returns: pin (14-digit string)
        """
        normalised = self._normalise_address(address)
        if not normalised:
            return None

        # Exact match first
        where = "property_address='" + normalised + "'"
        url = _PARCEL_ADDRESSES_URL + "?$where=" + urllib.parse.quote(where) + "&$limit=5"
        results = self._socrata_get(url)

        if not results:
            # Try LIKE match in case the suffix differs (e.g. AVE vs AVENUE)
            # Use just the number + direction + street name without suffix
            tokens = normalised.split()
            if len(tokens) >= 2:
                prefix = ' '.join(tokens[:3]) if len(tokens) >= 3 else ' '.join(tokens[:2])
                where2 = "property_address like '" + prefix + "%'"
                url2 = _PARCEL_ADDRESSES_URL + "?$where=" + urllib.parse.quote(where2) + "&$limit=10"
                results = self._socrata_get(url2)

        if not results:
            print("PIN lookup: no results for " + repr(address))
            return None

        # Prefer Chicago results
        chicago = [r for r in results if r.get('property_city', '').upper() == 'CHICAGO']
        row = chicago[0] if chicago else results[0]
        pin = row.get('pin')
        if pin:
            print("PIN lookup: found pin=" + str(pin) + " for " + repr(address))
        return pin

    def _fetch_improvement_chars(self, pin: str) -> Optional[Dict[str, Any]]:
        """Step 2: PIN → building characteristics.

        Dataset: bcnq-qi2z
        Column:  pin (14-digit)
        Key fields returned:
          apts          — number of apartment units
          beds          — total bedrooms across all units
          fbath/hbath   — full/half baths
          bldg_sf       — building square footage
          age           — years since built (subtract from current year)
          ext_wall      — construction type code (1-7)
          modeling_group — 'SF' or 'MF'
        """
        where = "pin='" + pin + "'"
        url = _IMPROVEMENT_CHARS_URL + "?$where=" + urllib.parse.quote(where) + "&$limit=1"
        results = self._socrata_get(url)

        if not results:
            return None

        row = results[0]
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

        # Unit count from 'apts' field
        apts = row.get('apts')
        if apts is not None:
            try:
                apt_count = int(float(apts))
                if apt_count > 0:
                    out['units'] = apt_count
            except (ValueError, TypeError):
                pass

        # Property type: modeling_group is most reliable
        modeling_group = (row.get('modeling_group') or '').upper()
        if modeling_group == 'MF':
            out['property_type'] = PropertyType.MULTI_FAMILY.value
        elif modeling_group == 'SF':
            out['property_type'] = PropertyType.SINGLE_FAMILY.value
        else:
            class_desc = (row.get('class_description') or '').upper()
            out['property_type'] = self._map_class_description(class_desc)

        return out if out else None

    def _fetch_assessed_value(self, pin: str) -> Optional[Dict[str, Any]]:
        """Step 3: PIN → most recent assessed value.

        Dataset: uzyt-m557
        Column:  pin (14-digit), year, certified_tot
        Fetches up to 5 records and picks the most recent year client-side.
        """
        where = "pin='" + pin + "'"
        url = _ASSESSED_VALUES_URL + "?$where=" + urllib.parse.quote(where) + "&$limit=5"
        results = self._socrata_get(url)

        if not results:
            return None

        def _year(r):
            try:
                return int(r.get('year', 0))
            except (ValueError, TypeError):
                return 0

        row = max(results, key=_year)

        # certified_tot is the final assessed value after board review
        assessed_value = row.get('certified_tot') or row.get('mailed_tot') or row.get('board_tot')
        if assessed_value is not None:
            try:
                return {'assessed_value': float(assessed_value)}
            except (ValueError, TypeError):
                pass

        return None

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_class_description(class_desc: str) -> str:
        """Map Cook County class_description to internal PropertyType value."""
        multi_keywords = ('2-6', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX')
        single_keywords = ('SINGLE', 'ONE')

        for kw in multi_keywords:
            if kw in class_desc:
                return PropertyType.MULTI_FAMILY.value
        for kw in single_keywords:
            if kw in class_desc:
                return PropertyType.SINGLE_FAMILY.value

        return PropertyType.SINGLE_FAMILY.value

    def _map_property_type(self, external_type: Optional[str]) -> Optional[str]:
        if not external_type:
            return None
        mapping = {
            'single family':  PropertyType.SINGLE_FAMILY.value,
            'single-family':  PropertyType.SINGLE_FAMILY.value,
            'sfr':            PropertyType.SINGLE_FAMILY.value,
            'multi family':   PropertyType.MULTI_FAMILY.value,
            'multi-family':   PropertyType.MULTI_FAMILY.value,
            'multifamily':    PropertyType.MULTI_FAMILY.value,
            'commercial':     PropertyType.COMMERCIAL.value,
            'retail':         PropertyType.COMMERCIAL.value,
            'office':         PropertyType.COMMERCIAL.value,
        }
        return mapping.get(external_type.lower())

    def _map_construction_type(self, external_construction: Optional[str]) -> Optional[str]:
        if not external_construction:
            return None
        mapping = {
            'frame':        ConstructionType.FRAME.value,
            'wood':         ConstructionType.FRAME.value,
            'wood frame':   ConstructionType.FRAME.value,
            'brick':        ConstructionType.BRICK.value,
            'brick veneer': ConstructionType.BRICK.value,
            'masonry':      ConstructionType.MASONRY.value,
            'concrete':     ConstructionType.MASONRY.value,
            'stone':        ConstructionType.MASONRY.value,
        }
        return mapping.get(external_construction.lower())

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _get_from_cache(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            cached = self.redis_client.get(key)
            if cached:
                return json.loads(cached)
        except Exception as exc:
            print("Cache retrieval error: " + str(exc))
        return None

    def _set_in_cache(self, key: str, data: Dict[str, Any], ttl: Optional[int] = None) -> None:
        try:
            serialized = json.dumps(data, default=str)
            if ttl:
                self.redis_client.setex(key, ttl, serialized)
            else:
                self.redis_client.set(key, serialized)
        except Exception as exc:
            print("Cache storage error: " + str(exc))
