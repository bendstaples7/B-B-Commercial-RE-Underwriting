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

        return fields

    def _fetch_most_recent_sale(self, pin: str) -> dict:
        # Prefer LAND AND BUILDING, then any sale for the PIN. Cook County often
        # leaves sale_type null on otherwise valid parcel sales (e.g. 853 W George).
        for where in (
            f"pin='{pin}' AND sale_type='LAND AND BUILDING'",
            f"pin='{pin}'",
        ):
            row = self._fetch_parcel_sale_row(pin, where)
            if row:
                return self._sale_fields_from_row(row)
        return {}

    def _fetch_parcel_sale_row(self, pin: str, where: str) -> Optional[dict]:
        url = (
            _PARCEL_SALES_URL
            + "?$select=pin,sale_date,sale_price,sale_type"
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
            return None
        if not rows:
            return None
        return rows[0]

    def _sale_fields_from_row(self, row: dict) -> dict:
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


def list_parcel_sale_history(
    pin: str | None,
    *,
    limit: int = 50,
    lead=None,
    cache_only: bool = False,
) -> list[dict]:
    """Return newest-first parcel sales for a PIN (date, price, type).

    Prefers ``parcel_sales_cache``. When that PIN has no cache rows (common for
    null ``sale_type`` sales the loader never ingested), falls back to live
    Socrata without the LAND AND BUILDING filter so history is complete.

    When external sources return nothing, seeds a single row from the lead's
    verified/imported sale fields so Info never contradicts a confirmed date.
    """
    capped = min(max(int(limit), 0), 100)
    if capped <= 0:
        return []

    history: list[dict] = []
    normalized = normalize_pin_for_socrata(pin) if pin else ''
    if normalized and normalized.isdigit():
        from app.models.parcel_sales_cache import ParcelSalesCache

        try:
            cached = (
                ParcelSalesCache.query
                .filter(ParcelSalesCache.pin == normalized)
                .order_by(ParcelSalesCache.sale_date.desc().nullslast())
                .limit(capped)
                .all()
            )
        except Exception as exc:
            logger.warning(
                "list_parcel_sale_history: cache query failed for PIN=%r: %s",
                normalized, exc,
            )
            cached = []

        if cached:
            history.extend(_serialize_sale_history_row(row) for row in cached)

        if not cache_only:
            plugin = CookCountyAssessorPlugin()
            where = f"pin='{normalized}'"
            url = (
                _PARCEL_SALES_URL
                + "?$select=pin,sale_date,sale_price,sale_type"
                + "&$where=" + quote(where)
                + "&$order=sale_date+DESC"
                + f"&$limit={capped}"
            )
            try:
                rows = plugin._cache_loader._socrata_get_with_retry(url, max_retries=2)
            except Exception as exc:
                logger.warning(
                    "list_parcel_sale_history: Socrata fetch failed for PIN=%r: %s",
                    normalized, exc,
                )
                rows = []

            for row in rows or []:
                serialized = _serialize_sale_history_dict(row)
                if serialized:
                    history.append(serialized)

    if not history and lead is not None:
        seeded = _history_from_lead(lead)
        if seeded:
            history = seeded

    unique_history: dict[tuple, dict] = {}
    for sale in history:
        key = (sale.get('sale_date'), sale.get('sale_price'), sale.get('sale_type'))
        unique_history[key] = sale
    history = sorted(
        unique_history.values(),
        key=lambda row: row.get('sale_date') or '',
        reverse=True,
    )
    return history[:capped]


def _history_from_lead(lead) -> list[dict]:
    """Single-row fallback from lead.acquisition_date / most_recent_sale."""
    from app.services.scoring_rubric import parse_sale_date_string

    acquisition = getattr(lead, 'acquisition_date', None)
    imported = parse_sale_date_string(str(getattr(lead, 'most_recent_sale', '') or ''))
    sale_date = acquisition if acquisition is not None else imported
    if sale_date is None:
        return []

    if hasattr(sale_date, 'isoformat'):
        sale_date_str = sale_date.isoformat()
    else:
        sale_date_str = str(sale_date)[:10]

    price = getattr(lead, 'most_recent_sale_price', None)
    try:
        sale_price = float(price) if price is not None else None
    except (TypeError, ValueError):
        sale_price = None

    return [{
        'sale_date': sale_date_str,
        'sale_price': sale_price,
        'sale_type': None,
    }]


def _serialize_sale_history_row(row) -> dict:
    sale_date = getattr(row, 'sale_date', None)
    if sale_date is not None and hasattr(sale_date, 'isoformat'):
        sale_date_str = sale_date.isoformat()
    elif sale_date is not None:
        sale_date_str = str(sale_date)[:10]
    else:
        sale_date_str = None

    price = getattr(row, 'sale_price', None)
    try:
        sale_price = float(price) if price is not None else None
    except (TypeError, ValueError):
        sale_price = None

    sale_type = getattr(row, 'sale_type', None)
    return {
        'sale_date': sale_date_str,
        'sale_price': sale_price,
        'sale_type': str(sale_type) if sale_type else None,
    }


def _serialize_sale_history_dict(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    sale_date_raw = row.get('sale_date')
    sale_date_str = None
    if sale_date_raw:
        try:
            dt = datetime.fromisoformat(str(sale_date_raw).replace('Z', '+00:00'))
            sale_date_str = dt.date().isoformat()
        except (ValueError, AttributeError, TypeError):
            sale_date_str = str(sale_date_raw)[:10]

    price = row.get('sale_price')
    try:
        sale_price = float(price) if price is not None else None
    except (TypeError, ValueError):
        sale_price = None

    sale_type = row.get('sale_type')
    return {
        'sale_date': sale_date_str,
        'sale_price': sale_price,
        'sale_type': str(sale_type) if sale_type else None,
    }