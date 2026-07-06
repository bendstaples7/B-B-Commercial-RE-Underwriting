"""Cook County tax-exempt parcels plugin (Socrata vgzx-68gb)."""
from __future__ import annotations

from app.services.plugins.cook_county_pin_plugin import CookCountyPinPlugin
from app.services.plugins.owner_name_utils import apply_owner_name_fields


class CookCountyTaxExemptPlugin(CookCountyPinPlugin):
    """Tax-exempt status and owner name when published by the Assessor."""

    name = "cook_county_tax_exempt"
    dataset_id = "vgzx-68gb"
    pin_field = "pin"
    result_limit = 1

    def _map_rows(self, pin: str, rows: list[dict]) -> dict:
        row = rows[0]
        fields: dict = {
            "permit_data": {"tax_exempt": row},
            "ownership_type": "tax_exempt",
        }
        owner_name = row.get("owner_name")
        if owner_name:
            apply_owner_name_fields(fields, str(owner_name))
        return fields
