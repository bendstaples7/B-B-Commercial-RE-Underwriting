"""Cook County Permits Plugin for the DataSourceConnector.

Fetches building/construction permit data from the Cook County Socrata API
(dataset 6yjf-dfxs).  Returns open/pending permit information mapped to
lead.violation_data and lead.permit_data.

Takes a PIN (Property Index Number) and returns an EnrichmentData dict.
"""
import logging
from typing import Optional

from app.services.data_source_connector import DataSourcePlugin, EnrichmentData
from app.services.cache_loader_service import CacheLoaderService

logger = logging.getLogger(__name__)

# Cook County Socrata permits endpoint
_PERMITS_URL = "https://datacatalog.cookcountyil.gov/resource/6yjf-dfxs.json"


class CookCountyPermitsPlugin(DataSourcePlugin):
    """Plugin that pulls building permit data from Cook County Socrata API.

    Uses a PIN (Property Index Number) to query the permits dataset
    and returns permit status, type, amount, and description.
    """

    name = "cook_county_permits"

    def __init__(self):
        self._cache_loader = CacheLoaderService()

    def lookup(self, address: str, owner_name: str) -> Optional[EnrichmentData]:
        """Query Cook County Socrata API for permit data.

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
            Enrichment payload with permit/violation fields populated,
            or None if no PIN could be resolved from the address.
        """
        # Try to extract a PIN from the address string if it looks like one
        pin = self._extract_pin(address)

        if not pin:
            logger.info(
                "CookCountyPermitsPlugin: no PIN found in address=%r — returning None",
                address,
            )
            return None

        return self._lookup_by_pin(pin)

    def lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        """Query Cook County Socrata API for a specific PIN.

        Parameters
        ----------
        pin : str
            Property Index Number (e.g. '14-28-400-008-0000').

        Returns
        -------
        EnrichmentData or None
            Enrichment payload with permit/violation fields populated.
        """
        return self._lookup_by_pin(pin)

    def _lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        """Internal method to fetch permit data for a specific PIN."""
        fields: dict = {}

        # Fetch permits
        permits = self._fetch_permits(pin)
        if permits:
            fields.update(permits)

        if not fields:
            logger.info("CookCountyPermitsPlugin: no data found for PIN=%r", pin)
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

    def _fetch_permits(self, pin: str) -> dict:
        """Fetch permit data for a PIN.

        Returns permit_data (JSON list of permits) and violation_data
        (JSON list of permits with non-closed status).
        """
        where = f"pin='{pin}'"
        url = (
            _PERMITS_URL
            + "?$where=" + self._url_quote(where)
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

        fields: dict = {}

        # Store all permit data
        fields["permit_data"] = rows

        # Filter for open/pending/violation-like statuses as violation data
        open_statuses = {"OPEN", "PENDING", "ISSUED", "ACTIVE", "PERMIT ISSUED"}
        violations = [
            r for r in rows
            if r.get("status", "").upper() in open_statuses
        ]
        if violations:
            fields["violation_data"] = violations
        else:
            # If no open permits, still store them as violations for completeness
            fields["violation_data"] = rows

        return fields

    @staticmethod
    def _url_quote(value: str) -> str:
        """URL-encode a query parameter value."""
        from urllib.parse import quote
        return quote(value)