"""Cook County Tax Sales Plugin for the DataSourceConnector."""
import logging
from typing import Optional
from urllib.parse import quote

from app.services.data_source_connector import DataSourcePlugin, EnrichmentData
from app.services.cache_loader_service import CacheLoaderService
from app.services.plugins.pin_utils import extract_pin, normalize_pin_for_socrata

logger = logging.getLogger(__name__)

_TAX_SALES_URL = "https://datacatalog.cookcountyil.gov/resource/55ju-2fs9.json"


class CookCountyTaxSalesPlugin(DataSourcePlugin):
    """Plugin that pulls tax delinquency data from Cook County Socrata API."""

    name = "cook_county_tax_sales"

    def __init__(self):
        self._cache_loader = CacheLoaderService()

    def lookup(self, address: str, owner_name: str) -> Optional[EnrichmentData]:
        pin = extract_pin(address)
        if not pin:
            logger.info(
                "CookCountyTaxSalesPlugin: no PIN found in address=%r — returning None",
                address,
            )
            return None
        return self._lookup_by_pin(pin)

    def lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        return self._lookup_by_pin(pin)

    def _lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        tax_info = self._fetch_tax_sales(normalize_pin_for_socrata(pin))
        if not tax_info:
            logger.info("CookCountyTaxSalesPlugin: no data found for PIN=%r", pin)
            return None
        return EnrichmentData(fields=tax_info)

    def _fetch_tax_sales(self, pin: str) -> dict:
        where = f"pin='{pin}'"
        url = (
            _TAX_SALES_URL
            + "?$where=" + quote(where)
            + "&$limit=5"
        )

        try:
            rows = self._cache_loader._socrata_get_with_retry(url, max_retries=2)
        except Exception as exc:
            logger.warning(
                "CookCountyTaxSalesPlugin: tax sales fetch failed for PIN=%r: %s",
                pin, exc,
            )
            return {}

        if not rows:
            return {}

        return {"tax_distress_data": rows}
