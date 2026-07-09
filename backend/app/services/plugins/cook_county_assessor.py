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
from urllib.parse import quote

from app.services.data_source_connector import DataSourcePlugin, EnrichmentData
from app.services.cache_loader_service import CacheLoaderService
from app.services.plugins.pin_utils import extract_pin, normalize_pin_for_socrata

logger = logging.getLogger(__name__)

_PARCEL_UNIVERSE_URL = "https://datacatalog.cookcountyil.gov/resource/pabr-t5kh.json"
_PARCEL_SALES_URL = "https://datacatalog.cookcountyil.gov/resource/wvhk-k5uv.json"
_IMPROVEMENT_CHARS_URL = "https://datacatalog.cookcountyil.gov/resource/bcnq-qi2z.json"


class CookCountyAssessorPlugin(DataSourcePlugin):
    """Plugin that pulls free property data from Cook County Socrata APIs."""

    name = "cook_county_assessor"

    def __init__(self):
        self._cache_loader = CacheLoaderService()

    def lookup(self, address: str, owner_name: str) -> Optional[EnrichmentData]:
        pin = extract_pin(address)
        if not pin:
            logger.info(
                "CookCountyAssessorPlugin: no PIN found in address=%r — returning None",
                address,
            )
            return None
        return self._lookup_by_pin(pin)

    def lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        return self._lookup_by_pin(pin)

    def _lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        fields: dict = {}
        normalized_pin = normalize_pin_for_socrata(pin)

        imp_chars = self._fetch_improvement_characteristics(normalized_pin)
        if imp_chars:
            fields.update(imp_chars)

        parcel_info = self._fetch_parcel_universe(normalized_pin)
        if parcel_info:
            fields.update(parcel_info)

        sale_info = self._fetch_most_recent_sale(normalized_pin)
        if sale_info:
            fields.update(sale_info)

        if not fields:
            logger.info("CookCountyAssessorPlugin: no data found for PIN=%r", pin)
            return None

        return EnrichmentData(fields=fields)

    def _fetch_improvement_characteristics(self, pin: str) -> dict:
        where = f"pin='{pin}'"
        url = (
            _IMPROVEMENT_CHARS_URL
            + "?$select=pin,bldg_sf,beds,fbath,hbath,age"
            + "&$where=" + quote(where)
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

        bldg_sf = row.get("bldg_sf")
        if bldg_sf is not None:
            try:
                fields["square_footage"] = int(float(bldg_sf))
            except (ValueError, TypeError):
                pass

        beds = row.get("beds")
        if beds is not None:
            try:
                fields["bedrooms"] = int(float(beds))
            except (ValueError, TypeError):
                pass

        fbath = row.get("fbath")
        hbath = row.get("hbath")
        try:
            full = float(fbath) if fbath is not None else 0.0
            half = float(hbath) if hbath is not None else 0.0
            if fbath is not None or hbath is not None:
                fields["bathrooms"] = full + 0.5 * half
        except (ValueError, TypeError):
            pass

        age = row.get("age")
        if age is not None:
            try:
                fields["year_built"] = datetime.now().year - int(float(age))
            except (ValueError, TypeError):
                pass

        return fields

    def _fetch_parcel_universe(self, pin: str) -> dict:
        where = f"pin='{pin}'"
        url = (
            _PARCEL_UNIVERSE_URL
            + "?$select=pin,lat,lon,class,lot_size,assessed_value"
            + "&$where=" + quote(where)
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

        assessed_value = row.get("assessed_value")
        if assessed_value is not None:
            try:
                fields["assessed_value"] = float(assessed_value)
            except (ValueError, TypeError):
                pass

        lot_size = row.get("lot_size")
        if lot_size is not None:
            try:
                fields["lot_size"] = int(float(lot_size))
            except (ValueError, TypeError):
                pass

        prop_class = row.get("class")
        if prop_class is not None:
            fields["assessor_class"] = str(prop_class)
            from app.services.helpers.cook_county_assessor_class import map_assessor_class_to_property_type
            mapped_type = map_assessor_class_to_property_type(str(prop_class))
            if mapped_type:
                fields["property_type"] = mapped_type
            else:
                class_map = {
                    "202": "single_family",
                    "203": "multi_family", "204": "multi_family", "205": "multi_family",
                    "206": "multi_family", "207": "multi_family", "208": "multi_family",
                    "211": "multi_family", "212": "multi_family",
                }
                if str(prop_class) in class_map:
                    fields["property_type"] = class_map[str(prop_class)]

        return fields

    def _fetch_most_recent_sale(self, pin: str) -> dict:
        where = f"pin='{pin}' AND sale_type='LAND AND BUILDING'"
        url = (
            _PARCEL_SALES_URL
            + "?$select=pin,sale_date,sale_price"
            + "&$where=" + quote(where)
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

        sale_date_raw = row.get("sale_date")
        if sale_date_raw:
            try:
                dt = datetime.fromisoformat(sale_date_raw.replace("Z", "+00:00"))
                fields["acquisition_date"] = dt.date()
            except (ValueError, AttributeError):
                fields["acquisition_date"] = str(sale_date_raw)[:10]

        sale_price = row.get("sale_price")
        if sale_price is not None:
            try:
                fields["most_recent_sale_price"] = float(sale_price)
            except (ValueError, TypeError):
                pass

        return fields
