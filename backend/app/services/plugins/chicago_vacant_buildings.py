"""Chicago vacant / abandoned building complaints (311 v6vf-nfxy)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.services.data_source_connector import DataSourcePlugin, EnrichmentData
from app.services.plugins.address_utils import is_chicago_address, normalize_chicago_street
from app.services.plugins.socrata_client import escape_soql_literal, socrata_get

logger = logging.getLogger(__name__)

VACANT_SR_TYPE = "Vacant/Abandoned Building Complaint"
DATASET_ID = "v6vf-nfxy"


class ChicagoVacantBuildingsPlugin(DataSourcePlugin):
    """Vacant and abandoned building 311 service requests."""

    name = "chicago_vacant_buildings"
    dataset_id = DATASET_ID

    def lookup(self, address: str, owner_name: str) -> Optional[EnrichmentData]:
        street = normalize_chicago_street(address)
        if not street or not is_chicago_address(address=address):
            return None
        return self._lookup_by_street(street)

    def lookup_for_lead(self, lead) -> Optional[EnrichmentData]:
        address = lead.property_street or ""
        if not is_chicago_address(city=getattr(lead, "property_city", None), address=address):
            return None
        street = normalize_chicago_street(address)
        if not street:
            return None
        return self._lookup_by_street(street)

    def lookup_by_pin(self, pin: str) -> Optional[EnrichmentData]:
        return None

    def _lookup_by_street(self, street: str) -> Optional[EnrichmentData]:
        escaped = escape_soql_literal(street)
        since = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%dT00:00:00")
        rows = socrata_get(
            self.dataset_id,
            params={
                "$where": (
                    f"sr_type = '{VACANT_SR_TYPE}' "
                    f"AND created_date > '{since}' "
                    f"AND upper(street_address) = upper('{escaped}')"
                ),
                "$order": "created_date DESC",
                "$limit": 5,
            },
            portal="chicago",
        )
        if not rows:
            return None
        return EnrichmentData(fields={"violation_data": {"chicago_vacant_buildings": rows}})
