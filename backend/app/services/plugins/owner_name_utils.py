"""Parse owner / entity names into lead owner fields."""
from __future__ import annotations

import re


_SINGLE_WORD_MARKERS = frozenset({
    "LLC", "INC", "CORP", "TRUST", "LP", "LLP", "COMPANY", "CO",
    "VILLAGE", "COUNTY", "CHURCH", "SCHOOL", "UNIVERSITY",
})
_PHRASE_MARKERS = ("CITY OF",)


def _normalize_token(token: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", token.upper())


def is_entity_name(cleaned: str) -> bool:
    """Return True when *cleaned* looks like an LLC / corp / trust / public entity."""
    upper = cleaned.upper()
    tokens = {_normalize_token(t) for t in upper.split()}
    if tokens & _SINGLE_WORD_MARKERS:
        return True
    return any(phrase in upper for phrase in _PHRASE_MARKERS)


# Back-compat alias for plugins that imported the private name.
_is_entity_name = is_entity_name


def contact_display_name(first_name: str | None, last_name: str | None) -> str:
    """Join contact name parts the same way UI display helpers do."""
    return " ".join(p for p in ((first_name or "").strip(), (last_name or "").strip()) if p)


def is_entity_contact(first_name: str | None, last_name: str | None) -> bool:
    """True when a Contact record is entity-shaped (LLC stuffed into last_name)."""
    display = contact_display_name(first_name, last_name)
    if not display:
        return False
    # Typical LLC ingest: empty first_name + full entity string in last_name.
    if not (first_name or "").strip() and is_entity_name(display):
        return True
    return is_entity_name(display)


def apply_owner_name_fields(fields: dict, owner_name: str) -> None:
    """Populate owner_first_name / owner_last_name / ownership_type from a raw name."""
    cleaned = re.sub(r"\s+", " ", (owner_name or "").strip())
    if not cleaned:
        return

    if is_entity_name(cleaned):
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
