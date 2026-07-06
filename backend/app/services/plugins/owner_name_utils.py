"""Parse owner / entity names into lead owner fields."""
from __future__ import annotations

import re


_ENTITY_MARKERS = (
    "LLC", "L.L.C", "INC", "CORP", "TRUST", "LP", "LLP", "COMPANY", "CO.",
    "VILLAGE", "CITY OF", "COUNTY", "CHURCH", "SCHOOL", "UNIVERSITY",
)


def apply_owner_name_fields(fields: dict, owner_name: str) -> None:
    """Populate owner_first_name / owner_last_name / ownership_type from a raw name."""
    cleaned = re.sub(r"\s+", " ", (owner_name or "").strip())
    if not cleaned:
        return

    upper = cleaned.upper()
    if any(marker in upper for marker in _ENTITY_MARKERS):
        fields["ownership_type"] = fields.get("ownership_type") or "entity"
        fields["owner_last_name"] = cleaned
        fields["owner_first_name"] = None
        return

    parts = cleaned.split(" ", 1)
    fields["ownership_type"] = fields.get("ownership_type") or "individual"
    fields["owner_first_name"] = parts[0]
    fields["owner_last_name"] = parts[1] if len(parts) > 1 else None
