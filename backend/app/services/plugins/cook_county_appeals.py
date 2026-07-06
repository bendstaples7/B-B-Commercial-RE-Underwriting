"""Cook County assessment appeals plugin (Socrata y282-6ig3)."""
from __future__ import annotations

from app.services.plugins.cook_county_pin_plugin import CookCountyPinPlugin


class CookCountyAppealsPlugin(CookCountyPinPlugin):
    """Assessment appeal history for a parcel."""

    name = "cook_county_appeals"
    dataset_id = "y282-6ig3"
    pin_field = "pin"
    result_limit = 10

    def _map_rows(self, pin: str, rows: list[dict]) -> dict:
        return {"tax_distress_data": {"appeals": rows}}
