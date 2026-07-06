"""Base class for Cook County Socrata plugins that query by PIN."""
from __future__ import annotations

import logging
from typing import Optional

from app.services.data_source_connector import DataSourcePlugin, EnrichmentData
from app.services.plugins.pin_utils import extract_pin, format_pin_for_storage, normalize_pin_for_socrata
from app.services.plugins.socrata_client import socrata_get

logger = logging.getLogger(__name__)


class CookCountyPinPlugin(DataSourcePlugin):
    """Shared PIN extraction and Socrata fetch helpers."""

    dataset_id: str = ""
    portal: str = "cook_county"
    pin_field: str = "pin"
    pin_format: str = "normalized"  # "normalized" (14 digits) or "dashed"
    result_limit: int = 5

    def lookup(self, address: str, owner_name: str) -> Optional[EnrichmentData]:
        pin = extract_pin(address)
        if not pin:
            return None
        return self.lookup_by_pin(pin)

    def lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        rows = self._fetch_rows(pin)
        if not rows:
            return None
        fields = self._map_rows(pin, rows)
        if not fields:
            return None
        return EnrichmentData(fields=fields)

    def _fetch_rows(self, pin: str) -> list[dict]:
        if not self.dataset_id:
            return []
        normalized = normalize_pin_for_socrata(pin)
        dashed = format_pin_for_storage(pin)
        if self.pin_field in {"keypin", "pins"}:
            where = f"keypin='{dashed}' OR pins='{dashed}'"
        elif self.pin_format == "dashed":
            where = f"{self.pin_field}='{dashed}'"
        else:
            where = f"{self.pin_field}='{normalized}'"
        return socrata_get(
            self.dataset_id,
            params={
                "$where": where,
                "$limit": self.result_limit,
            },
            portal=self.portal,
        )

    def _map_rows(self, pin: str, rows: list[dict]) -> dict:
        raise NotImplementedError
