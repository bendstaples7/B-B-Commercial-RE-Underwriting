"""Chicago building violations plugin (Socrata 22u3-xenr)."""
from __future__ import annotations

import logging
from typing import Optional

from app.services.data_source_connector import DataSourcePlugin, EnrichmentData
from app.services.plugins.address_utils import is_chicago_address, normalize_chicago_street
from app.services.plugins.socrata_client import socrata_get

logger = logging.getLogger(__name__)


class ChicagoBuildingViolationsPlugin(DataSourcePlugin):
    """City of Chicago Dept. of Buildings violation records."""

    name = "chicago_building_violations"
    dataset_id = "22u3-xenr"

    def lookup(self, address: str, owner_name: str) -> Optional[EnrichmentData]:
        street = normalize_chicago_street(address)
        if not street or not is_chicago_address(address=address):
            logger.info(
                "ChicagoBuildingViolationsPlugin: skipping non-Chicago address=%r",
                address,
            )
            return None
        return self._lookup_by_street(street)

    def lookup_for_lead(self, lead) -> Optional[EnrichmentData]:
        address = lead.property_street or ""
        if not is_chicago_address(
            city=getattr(lead, "property_city", None),
            address=address,
        ):
            return None
        street = normalize_chicago_street(address)
        if not street:
            return None
        return self._lookup_by_street(street)

    def lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        return None

    def _lookup_by_street(self, street: str) -> Optional[EnrichmentData]:
        where = f"upper(address)=upper('{street.replace(chr(39), chr(39)+chr(39))}')"
        rows = socrata_get(
            self.dataset_id,
            params={
                "$where": where,
                "$order": "violation_date DESC",
                "$limit": 10,
            },
            portal="chicago",
        )
        if not rows:
            prefix = " ".join(street.split()[:3])
            if prefix != street:
                escaped = prefix.replace("'", "''")
                rows = socrata_get(
                    self.dataset_id,
                    params={
                        "$where": f"starts_with(upper(address), upper('{escaped}'))",
                        "$order": "violation_date DESC",
                        "$limit": 10,
                    },
                    portal="chicago",
                )
        if not rows:
            return None
        return EnrichmentData(fields={"violation_data": {"chicago_building_violations": rows}})
