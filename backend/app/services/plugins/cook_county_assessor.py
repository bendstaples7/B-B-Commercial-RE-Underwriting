"""Cook County Assessor Plugin for the DataSourceConnector.

Fetches free property data from 3 existing Cook County Socrata APIs:
1. Parcel Universe (pabr-t5kh) — assessed_value, lot_size, property_class, lat/lon
2. Parcel Sales (wvhk-k5uv) — sale_date, sale_price
3. Improvement Characteristics (bcnq-qi2z) — year_built, sqft, bedrooms, bathrooms

Takes a PIN (Property Index Number) and returns an EnrichmentData dict.
"""
import logging
from datetime import datetime
from typing import Optional

from app.services.data_source_connector import DataSourcePlugin, EnrichmentData
from app.services.cache_loader_service import CacheLoaderService

logger = logging.getLogger(__name__)

# Cook County Socrata dataset endpoints
_PARCEL_UNIVERSE_URL = "https://datacatalog.cookcountyil.gov/resource/pabr-t5kh.json"
_PARCEL_SALES_URL = "https://datacatalog.cookcountyil.gov/resource/wvhk-k5uv.json"
_IMPROVEMENT_CHARS_URL = "https://datacatalog.cookcountyil.gov/resource/bcnq-qi2z.json"


class CookCountyAssessorPlugin(DataSourcePlugin):
    """Plugin that pulls free property data from Cook County Socrata APIs.

    Uses a PIN (Property Index Number) to query three datasets:
    - Parcel Universe: assessed_value, lot_size, property_class, lat, lon
    - Parcel Sales: most recent sale_date, sale_price (to derive ownership duration)
    - Improvement Characteristics: year_built, sqft, bedrooms, bathrooms
    """

    name = "cook_county_assessor"

    def __init__(self):
        self._cache_loader = CacheLoaderService()

    def lookup(self, address: str, owner_name: str) -> Optional[EnrichmentData]:
        """Query Cook County Socrata APIs for enrichment data.

        Parameters
        ----------
        address : str
            Property address — not directly used; PIN lookup is preferred.
            The caller must set the PIN on the lead (county_assessor_pin)
            before calling this plugin for best results.
        owner_name : str
            Owner name — currently not used for PIN-based lookup but
            available for future owner-based searches.

        Returns
        -------
        EnrichmentData or None
            Enrichment payload with fields populated, or None if no PIN
            could be resolved from the address.
        """
        # Try to extract a PIN from the address string if it looks like one
        pin = self._extract_pin(address)

        if not pin:
            logger.info(
                "CookCountyAssessorPlugin: no PIN found in address=%r — returning None",
                address,
            )
            return None

        return self._lookup_by_pin(pin)

    def lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        """Query Cook County Socrata APIs for a specific PIN.

        Parameters
        ----------
        pin : str
            Property Index Number (e.g. '14-28-400-008-0000').

        Returns
        -------
        EnrichmentData or None
            Enrichment payload with fields populated.
        """
        return self._lookup_by_pin(pin)

    def _lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        """Internal method to fetch data for a specific PIN from all 3 datasets."""
        fields: dict = {}

        # 1. Fetch Improvement Characteristics (year_built, sqft, bedrooms, bathrooms)
        imp_chars = self._fetch_improvement_characteristics(pin)
        if imp_chars:
            fields.update(imp_chars)

        # 2. Fetch Parcel Universe (assessed_value, lot_size, property_class, lat, lon)
        parcel_info = self._fetch_parcel_universe(pin)
        if parcel_info:
            fields.update(parcel_info)

        # 3. Fetch most recent Parcel Sale (sale_date, sale_price)
        sale_info = self._fetch_most_recent_sale(pin)
        if sale_info:
            fields.update(sale_info)

        if not fields:
            logger.info("CookCountyAssessorPlugin: no data found for PIN=%r", pin)
            return None

        return EnrichmentData(fields=fields)

    def _extract_pin(self, address: str) -> Optional[str]:
        """Try to extract a PIN from the address string.

        PINs in Cook County typically look like '14-28-400-008-0000'
        or '14284000080000' (14 digits). Attempts to find the first
        segment that looks like a PIN.
        """
        if not address:
            return None

        # Check if the address itself is a PIN (dashed format)
        address_stripped = address.strip()
        parts = address_stripped.replace("-", "").split()

        # If address looks like a clean PIN (digits and dashes only)
        import re
        # Match dashed PIN format: e.g. 14-28-400-008-0000
        dash_match = re.match(r'^(\d{2}-\d{2}-\d{3}-\d{3}-\d{4})$', address_stripped)
        if dash_match:
            return dash_match.group(1)

        # Match condensed 14-digit PIN
        digit_match = re.match(r'^(\d{14})$', address_stripped)
        if digit_match:
            return digit_match.group(1)

        # Try to find PIN-like pattern anywhere in address
        for word in parts:
            if re.match(r'^\d{14}$', word):
                return word

        return None

    def _fetch_improvement_characteristics(self, pin: str) -> dict:
        """Fetch improvement characteristics for a PIN.

        Returns year_built, square_footage, bedrooms, bathrooms.
        """
        where = f"pin='{pin}'"
        url = (
            _IMPROVEMENT_CHARS_URL
            + "?$select=pin,bldg_sf,beds,fbath,hbath,age"
            + "&$where=" + self._url_quote(where)
            + "&$limit=1"
        )

        try:
            rows = self._cache_loader._socrata_get_with_retry(url, max_retries=2)
        except Exception as exc:
            logger.warning(
                "CookCountyAssessorPlugin: improvement chars fetch failed for PIN=%r: %s",
                pin, exc,
            )
            return {}

        if not rows:
            return {}

        row = rows[0]
        fields: dict = {}

        # Square footage
        bldg_sf = row.get("bldg_sf")
        if bldg_sf is not None:
            try:
                fields["square_footage"] = int(float(bldg_sf))
            except (ValueError, TypeError):
                pass

        # Bedrooms
        beds = row.get("beds")
        if beds is not None:
            try:
                fields["bedrooms"] = int(float(beds))
            except (ValueError, TypeError):
                pass

        # Bathrooms: full + 0.5 * half
        fbath = row.get("fbath")
        hbath = row.get("hbath")
        try:
            full = float(fbath) if fbath is not None else 0.0
            half = float(hbath) if hbath is not None else 0.0
            if fbath is not None or hbath is not None:
                fields["bathrooms"] = full + 0.5 * half
        except (ValueError, TypeError):
            pass

        # Year built: 'age' is years-since-built
        age = row.get("age")
        if age is not None:
            try:
                fields["year_built"] = datetime.now().year - int(float(age))
            except (ValueError, TypeError):
                pass

        return fields

    def _fetch_parcel_universe(self, pin: str) -> dict:
        """Fetch parcel universe data for a PIN.

        Returns lot_size, property_class (as property_type),
        assessed_value, lat, lon.
        """
        where = f"pin='{pin}'"
        url = (
            _PARCEL_UNIVERSE_URL
            + "?$select=pin,lat,lon,class,lot_size,assessed_value"
            + "&$where=" + self._url_quote(where)
            + "&$limit=1"
        )

        try:
            rows = self._cache_loader._socrata_get_with_retry(url, max_retries=2)
        except Exception as exc:
            logger.warning(
                "CookCountyAssessorPlugin: parcel universe fetch failed for PIN=%r: %s",
                pin, exc,
            )
            return {}

        if not rows:
            return {}

        row = rows[0]
        fields: dict = {}

        # Assessed value
        assessed_value = row.get("assessed_value")
        if assessed_value is not None:
            try:
                fields["assessed_value"] = float(assessed_value)
            except (ValueError, TypeError):
                pass

        # Lot size
        lot_size = row.get("lot_size")
        if lot_size is not None:
            try:
                fields["lot_size"] = int(float(lot_size))
            except (ValueError, TypeError):
                pass

        # Property class — map to property_type hint
        prop_class = row.get("class")
        if prop_class is not None:
            fields["assessor_class"] = str(prop_class)
            # Map common property classes
            class_map = {
                "202": "single_family",
                "203": "multi_family",
                "204": "multi_family",
                "205": "multi_family",
                "206": "multi_family",
                "207": "multi_family",
                "208": "multi_family",
                "211": "multi_family",
                "212": "multi_family",
            }
            if str(prop_class) in class_map:
                fields["property_type"] = class_map[str(prop_class)]

        # Latitude/Longitude (stored in enrichment for geo-scoring)
        lat = row.get("lat")
        if lat is not None:
            try:
                fields["latitude"] = float(lat)
            except (ValueError, TypeError):
                pass

        lon = row.get("lon")
        if lon is not None:
            try:
                fields["longitude"] = float(lon)
            except (ValueError, TypeError):
                pass

        return fields

    def _fetch_most_recent_sale(self, pin: str) -> dict:
        """Fetch the most recent parcel sale for a PIN.

        Returns sale_date, sale_price (to derive ownership duration).
        Uses sale_date descending to get most recent.
        """
        where = f"pin='{pin}' AND sale_type='LAND AND BUILDING'"
        url = (
            _PARCEL_SALES_URL
            + "?$select=pin,sale_date,sale_price"
            + "&$where=" + self._url_quote(where)
            + "&$order=sale_date+DESC"
            + "&$limit=1"
        )

        try:
            rows = self._cache_loader._socrata_get_with_retry(url, max_retries=2)
        except Exception as exc:
            logger.warning(
                "CookCountyAssessorPlugin: parcel sales fetch failed for PIN=%r: %s",
                pin, exc,
            )
            return {}

        if not rows:
            return {}

        row = rows[0]
        fields: dict = {}

        # Sale date
        sale_date_raw = row.get("sale_date")
        if sale_date_raw:
            try:
                # Parse ISO format date → datetime.date
                dt = datetime.fromisoformat(sale_date_raw.replace("Z", "+00:00"))
                fields["acquisition_date"] = dt.date()
            except (ValueError, AttributeError):
                fields["acquisition_date"] = str(sale_date_raw)[:10]

        # Sale price
        sale_price = row.get("sale_price")
        if sale_price is not None:
            try:
                fields["most_recent_sale_price"] = float(sale_price)
            except (ValueError, TypeError):
                pass

        return fields

    @staticmethod
    def _url_quote(value: str) -> str:
        """URL-encode a query parameter value."""
        from urllib.parse import quote
        return quote(value)