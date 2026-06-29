"""Cook County Permits Plugin for the DataSourceConnector."""
import logging
from typing import Optional
from urllib.parse import quote

from app.services.data_source_connector import DataSourcePlugin, EnrichmentData
from app.services.cache_loader_service import CacheLoaderService
from app.services.plugins.pin_utils import extract_pin, normalize_pin_for_socrata

logger = logging.getLogger(__name__)

_PERMITS_URL = "https://datacatalog.cookcountyil.gov/resource/6yjf-dfxs.json"

# Statuses that indicate an active permit (not a code violation).
_OPEN_PERMIT_STATUSES = {"OPEN", "PENDING", "ISSUED", "ACTIVE", "PERMIT ISSUED"}

# Statuses that indicate an actual code violation / enforcement action.
_VIOLATION_STATUSES = {
    "VIOLATION", "CODE VIOLATION", "OPEN VIOLATION", "ENFORCEMENT",
    "FAIL", "FAILED", "NON-COMPLIANT", "NONCOMPLIANT",
}


class CookCountyPermitsPlugin(DataSourcePlugin):
    """Plugin that pulls building permit data from Cook County Socrata API."""

    name = "cook_county_permits"

    def __init__(self):
        self._cache_loader = CacheLoaderService()

    def lookup(self, address: str, owner_name: str) -> Optional[EnrichmentData]:
        pin = extract_pin(address)
        if not pin:
            logger.info(
                "CookCountyPermitsPlugin: no PIN found in address=%r — returning None",
                address,
            )
            return None
        return self._lookup_by_pin(pin)

    def lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        return self._lookup_by_pin(pin)

    def _lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        permits = self._fetch_permits(normalize_pin_for_socrata(pin))
        if not permits:
            logger.info("CookCountyPermitsPlugin: no data found for PIN=%r", pin)
            return None
        return EnrichmentData(fields=permits)

    def _fetch_permits(self, pin: str) -> dict:
        where = f"pin='{pin}'"
        url = (
            _PERMITS_URL
            + "?$where=" + quote(where)
            + "&$limit=5"
        )

        try:
            rows = self._cache_loader._socrata_get_with_retry(url, max_retries=2)
        except Exception as exc:
            logger.warning(
                "CookCountyPermitsPlugin: permits fetch failed for PIN=%r: %s",
                pin, exc,
            )
            return {}

        if not rows:
            return {}

        fields: dict = {"permit_data": rows}

        violations = [
            r for r in rows
            if r.get("status", "").upper() in _VIOLATION_STATUSES
        ]
        if violations:
            fields["violation_data"] = violations

        return fields
