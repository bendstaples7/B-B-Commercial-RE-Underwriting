"""Cook County per-PIN owner lookup plugin (tax portal, clerk, tax-exempt, scofflaw)."""
from __future__ import annotations

import logging
from typing import Optional

from app.services.data_source_connector import DataSourcePlugin, EnrichmentData
from app.services.plugins.cook_county_owner_sources import lookup_owner_fields
from app.services.plugins.pin_utils import extract_pin

logger = logging.getLogger(__name__)


class CookCountyOwnerLookupPlugin(DataSourcePlugin):
    """Aggregate free owner hints for high-value leads with a known PIN."""

    name = "cook_county_owner_lookup"

    def lookup(self, address: str, owner_name: str) -> Optional[EnrichmentData]:
        pin = extract_pin(address)
        if not pin:
            return None
        return self.lookup_by_pin(pin)

    def lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        fields = lookup_owner_fields(pin=pin, address="")
        if not fields:
            return None
        return EnrichmentData(fields=fields)

    def lookup_for_lead(self, lead) -> Optional[EnrichmentData]:
        pin = getattr(lead, "county_assessor_pin", None) or extract_pin(
            lead.property_street or ""
        )
        if not pin:
            logger.info(
                "CookCountyOwnerLookupPlugin: no PIN on lead id=%s",
                getattr(lead, "id", None),
            )
            return None
        fields = lookup_owner_fields(
            pin=str(pin).strip(),
            address=lead.property_street or "",
            city=getattr(lead, "property_city", None),
        )
        if not fields:
            return None
        return EnrichmentData(fields=fields)
