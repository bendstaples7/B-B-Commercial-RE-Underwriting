"""Parse owner / entity names into lead owner fields."""
from __future__ import annotations

import re


# Legal-entity suffixes / holding vehicles (investor LLCs, corps, trusts).
_ENTITY_MARKERS = frozenset({
    "LLC", "INC", "CORP", "TRUST", "LP", "LLP", "COMPANY", "CO",
})

# High-precision institutional markers — safe to auto-mark as nonprofit.
_DEFINITE_INSTITUTIONAL_MARKERS = frozenset({
    "VILLAGE", "COUNTY", "CHURCH", "HOSPITAL", "MINISTRY",
    "NFP", "NONPROFIT",
})
_DEFINITE_INSTITUTIONAL_PHRASES = (
    "CITY OF",
    "PARK DISTRICT",
    "HOUSING AUTHORITY",
    "NOT FOR PROFIT",
    "NON PROFIT",
    "NON-PROFIT",
)

# Softer markers — block cold mail, but do not auto-upsert nonprofit
# (investor names like "Rock Foundation LLC" / "Old School Properties LLC").
_SOFT_INSTITUTIONAL_MARKERS = frozenset({
    "SCHOOL", "UNIVERSITY", "FOUNDATION", "ASSOCIATION",
})

_INSTITUTIONAL_MARKERS = _DEFINITE_INSTITUTIONAL_MARKERS | _SOFT_INSTITUTIONAL_MARKERS
_INSTITUTIONAL_PHRASES = _DEFINITE_INSTITUTIONAL_PHRASES

# Back-compat: entity detection historically included public markers.
_SINGLE_WORD_MARKERS = _ENTITY_MARKERS | _INSTITUTIONAL_MARKERS
_PHRASE_MARKERS = _INSTITUTIONAL_PHRASES


def _normalize_token(token: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", token.upper())


def _name_has_markers(
    cleaned: str,
    *,
    tokens: frozenset[str],
    phrases: tuple[str, ...] = (),
) -> bool:
    if not cleaned:
        return False
    upper = cleaned.upper()
    name_tokens = {_normalize_token(t) for t in upper.split()}
    if name_tokens & tokens:
        return True
    return any(phrase in upper for phrase in phrases)


def is_definite_institutional_name(cleaned: str) -> bool:
    """True for high-confidence public / nonprofit names safe to auto-classify."""
    return _name_has_markers(
        cleaned,
        tokens=_DEFINITE_INSTITUTIONAL_MARKERS,
        phrases=_DEFINITE_INSTITUTIONAL_PHRASES,
    )


def is_institutional_name(cleaned: str) -> bool:
    """Return True when *cleaned* looks like a public / nonprofit institution.

    Includes softer markers (foundation/school/association) used for cold-mail
    deprioritization. Prefer ``is_definite_institutional_name`` before auto-marking
    an Organization as nonprofit.
    """
    if is_definite_institutional_name(cleaned):
        return True
    return _name_has_markers(cleaned, tokens=_SOFT_INSTITUTIONAL_MARKERS)


def is_entity_name(cleaned: str) -> bool:
    """Return True when *cleaned* looks like an LLC / corp / trust / institution."""
    if not cleaned:
        return False
    if is_institutional_name(cleaned):
        return True
    upper = cleaned.upper()
    tokens = {_normalize_token(t) for t in upper.split()}
    return bool(tokens & _ENTITY_MARKERS)


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
    return is_entity_name(display)


_STREET_TOKENS = frozenset({
    "ST", "STREET", "AVE", "AVENUE", "RD", "ROAD", "BLVD", "BOULEVARD",
    "DR", "DRIVE", "LN", "LANE", "CT", "COURT", "PL", "PLACE", "WAY",
    "CIR", "CIRCLE", "PKWY", "PARKWAY", "HWY", "HIGHWAY", "TER", "TERRACE",
})


def is_address_like_name(cleaned: str) -> bool:
    """True when *cleaned* looks like a street address stuffed into a name field.

    Mirrors frontend ``isAddressLikeContactName`` (e.g. ``3508SACRAMENTO MAYNARD``).
    Address-like names must stay Contacts — never promote to Organization.
    """
    name = re.sub(r"\s+", " ", (cleaned or "").strip())
    if not name:
        return False
    upper = name.upper()
    if not re.search(r"\d", upper):
        return False
    if is_entity_name(upper):
        return False

    tokens = [t.replace(".", "") for t in re.split(r"[\s,]+", upper) if t]
    if any(t in _STREET_TOKENS for t in tokens):
        return True
    # Mashed house-number + street fragment: "3508SACRAMENTO"
    if re.search(r"\d[A-Z]{3,}", upper.replace(" ", "")):
        return True
    if re.match(r"^\d+\s+[A-Z]", upper):
        return True
    return False


def is_address_like_contact(first_name: str | None, last_name: str | None) -> bool:
    """True when a Contact name looks like an address mash."""
    display = contact_display_name(first_name, last_name)
    if not display:
        return False
    return is_address_like_name(display)


def owner_names_equivalent(
    first_a: str | None,
    last_a: str | None,
    first_b: str | None,
    last_b: str | None,
) -> bool:
    """True when two person names are the same person ignoring case / middle initials.

    ``Joseph Kiferbaum`` matches ``JOSEPH A KIFERBAUM``; does not match a different
    last name or a different first given name.
    """
    last_norm_a = re.sub(r"[^a-z]", "", (last_a or "").lower())
    last_norm_b = re.sub(r"[^a-z]", "", (last_b or "").lower())
    if not last_norm_a or last_norm_a != last_norm_b:
        return False

    tokens_a = [re.sub(r"[^a-z]", "", t) for t in (first_a or "").lower().split() if t]
    tokens_b = [re.sub(r"[^a-z]", "", t) for t in (first_b or "").lower().split() if t]
    tokens_a = [t for t in tokens_a if t]
    tokens_b = [t for t in tokens_b if t]
    if not tokens_a and not tokens_b:
        return True
    if not tokens_a or not tokens_b:
        return False
    return tokens_a[0] == tokens_b[0]


def is_institutional_contact(first_name: str | None, last_name: str | None) -> bool:
    """True when a Contact record looks like a public / nonprofit institution."""
    display = contact_display_name(first_name, last_name)
    if not display:
        return False
    return is_institutional_name(display)


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
