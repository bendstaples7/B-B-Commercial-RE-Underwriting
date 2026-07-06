"""Parse owner / entity names into lead owner fields."""
from __future__ import annotations

import re


_SINGLE_WORD_MARKERS = frozenset({
    "LLC", "L.L.C", "INC", "CORP", "TRUST", "LP", "LLP", "COMPANY", "CO.",
    "VILLAGE", "COUNTY", "CHURCH", "SCHOOL", "UNIVERSITY",
})
_PHRASE_MARKERS = ("CITY OF",)


def _normalize_token(token: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", token.upper())


def _is_entity_name(cleaned: str) -> bool:
    upper = cleaned.upper()
    tokens = {_normalize_token(t) for t in upper.split()}
    if tokens & _SINGLE_WORD_MARKERS:
        return True
    return any(phrase in upper for phrase in _PHRASE_MARKERS)


def apply_owner_name_fields(fields: dict, owner_name: str) -> None:
    """Populate owner_first_name / owner_last_name / ownership_type from a raw name."""
    cleaned = re.sub(r"\s+", " ", (owner_name or "").strip())
    if not cleaned:
        return

    if _is_entity_name(cleaned):
        fields["ownership_type"] = fields.get("ownership_type") or "entity"
        fields["owner_last_name"] = cleaned
        fields["owner_first_name"] = None
        return

    if "," in cleaned:
        last, _, first = cleaned.partition(",")
        last = last.strip()
        first = first.strip()
        if last and first:
            fields["ownership_type"] = fields.get("ownership_type") or "individual"
            fields["owner_first_name"] = first
            fields["owner_last_name"] = last
            return

    parts = cleaned.rsplit(" ", 1)
    fields["ownership_type"] = fields.get("ownership_type") or "individual"
    if len(parts) == 1:
        fields["owner_first_name"] = parts[0]
        fields["owner_last_name"] = None
    else:
        fields["owner_first_name"] = parts[0]
        fields["owner_last_name"] = parts[1]
