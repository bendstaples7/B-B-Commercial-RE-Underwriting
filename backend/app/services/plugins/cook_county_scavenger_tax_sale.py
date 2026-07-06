"""Cook County scavenger tax sale plugin (Socrata ydgz-vkrp)."""
from __future__ import annotations

from app.services.plugins.cook_county_pin_plugin import CookCountyPinPlugin


class CookCountyScavengerTaxSalePlugin(CookCountyPinPlugin):
    """Scavenger tax sale records — complements annual tax sale data."""

    name = "cook_county_scavenger_tax_sale"
    dataset_id = "ydgz-vkrp"
    pin_field = "pin"
    pin_format = "dashed"
    result_limit = 5

    def _map_rows(self, pin: str, rows: list[dict]) -> dict:
        return {"tax_distress_data": {"scavenger_tax_sale": rows}}
