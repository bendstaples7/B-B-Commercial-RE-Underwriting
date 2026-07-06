"""Chicago building code scofflaw list plugin (Socrata rz4d-qp2m)."""
from __future__ import annotations

import logging
from typing import Optional

from app.services.data_source_connector import DataSourcePlugin, EnrichmentData
from app.services.plugins.address_utils import is_chicago_address, normalize_chicago_street
from app.services.plugins.owner_name_utils import apply_owner_name_fields
from app.services.plugins.socrata_client import socrata_get

logger = logging.getLogger(__name__)


class ChicagoScofflawPlugin(DataSourcePlugin):
    """Chicago building scofflaw list — includes defendant_owner."""

    name = "chicago_scofflaw"
    dataset_id = "rz4d-qp2m"

    def lookup(self, address: str, owner_name: str) -> Optional[EnrichmentData]:
        street = normalize_chicago_street(address)
        if not street or not is_chicago_address(address=address):
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
        escaped = street.replace("'", "''")
        rows = socrata_get(
            self.dataset_id,
            params={
                "$where": (
                    f"upper(address)=upper('{escaped}') "
                    f"OR upper(secondary_address) like upper('{escaped}%')"
                ),
                "$limit": 5,
            },
            portal="chicago",
        )
        if not rows:
            prefix = " ".join(street.split()[:3])
            if prefix != street:
                pescaped = prefix.replace("'", "''")
                rows = socrata_get(
                    self.dataset_id,
                    params={
                        "$where": f"starts_with(upper(address), upper('{pescaped}'))",
                        "$limit": 5,
                    },
                    portal="chicago",
                )
        if not rows:
            return None

        fields: dict = {"violation_data": {"chicago_scofflaw": rows}}
        defendant = rows[0].get("defendant_owner")
        if defendant:
            apply_owner_name_fields(fields, str(defendant))
        return EnrichmentData(fields=fields)
