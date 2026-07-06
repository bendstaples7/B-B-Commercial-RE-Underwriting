"""Cook County Commercial Valuation plugin (Socrata csik-bsws)."""
from __future__ import annotations

import logging

from app.services.plugins.cook_county_pin_plugin import CookCountyPinPlugin

logger = logging.getLogger(__name__)


class CookCountyCommercialValuationPlugin(CookCountyPinPlugin):
    """Income/expense commercial valuation data for CRE parcels."""

    name = "cook_county_commercial_valuation"
    dataset_id = "csik-bsws"
    pin_field = "keypin"
    result_limit = 3

    def _map_rows(self, pin: str, rows: list[dict]) -> dict:
        row = self._best_valuation_row(rows)
        fields: dict = {
            "permit_data": {"commercial_valuation": rows},
        }

        property_use = row.get("property_type_use")
        if property_use:
            fields["property_type"] = str(property_use).lower().replace(" ", "_")

        for src_key, dest_key, cast in (
            ("bldgsf", "square_footage", int),
            ("finalmarketvalue", "assessed_value", float),
            ("yearbuilt", "year_built", int),
        ):
            raw = row.get(src_key)
            if raw is None:
                continue
            try:
                fields[dest_key] = cast(float(raw))
            except (TypeError, ValueError):
                logger.debug(
                    "CookCountyCommercialValuationPlugin: could not cast %s=%r",
                    src_key,
                    raw,
                )

        return fields

    @staticmethod
    def _best_valuation_row(rows: list[dict]) -> dict:
        value_keys = ("bldgsf", "finalmarketvalue", "yearbuilt", "property_type_use")
        for row in rows:
            if any(row.get(key) not in (None, "") for key in value_keys):
                return row
        return rows[0]
