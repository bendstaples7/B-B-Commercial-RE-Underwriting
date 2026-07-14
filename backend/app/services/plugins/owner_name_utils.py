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


def expand_owner_name_parts(
    first_name: str | None,
    last_name: str | None,
) -> tuple[str, str]:
    """Normalize owner fields when the full name was jammed into ``first_name``.

    ``GARCIA ADALBERTO`` + empty last → (``GARCIA``, ``ADALBERTO``) so it matches
    rows that already have split first/last. Trailing token becomes last name.
    """
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    if last or not first:
        return first, last
    parts = first.split()
    if len(parts) < 2:
        return first, last
    return " ".join(parts[:-1]), parts[-1]


def _owner_name_variants(
    first_name: str | None,
    last_name: str | None,
) -> list[tuple[str, str]]:
    """Candidate (first, last) pairs including jammed FIRST LAST and LAST FIRST."""
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    variants: list[tuple[str, str]] = [expand_owner_name_parts(first, last)]
    if not last and len(first.split()) >= 2:
        parts = first.split()
        # Assessor-style LAST FIRST jammed into first_name.
        variants.append((" ".join(parts[1:]), parts[0]))
    # Deduplicate while preserving order
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for pair in variants:
        key = (pair[0].lower(), pair[1].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(pair)
    return out


def _first_token_and_last(first: str, last: str) -> tuple[str | None, str | None]:
    last_norm = re.sub(r"[^a-z]", "", (last or "").lower()) or None
    tokens = [re.sub(r"[^a-z]", "", t) for t in (first or "").lower().split() if t]
    tokens = [t for t in tokens if t]
    first_token = tokens[0] if tokens else None
    return first_token, last_norm


def owner_names_equivalent(
    first_a: str | None,
    last_a: str | None,
    first_b: str | None,
    last_b: str | None,
) -> bool:
    """True when two person names are the same person ignoring case / middle initials.

    ``Joseph Kiferbaum`` matches ``JOSEPH A KIFERBAUM``; jammed assessor forms
    ``GARCIA ADALBERTO`` match both ``GARCIA``/``ADALBERTO`` and reverse order.
    """
    for fa, la in _owner_name_variants(first_a, last_a):
        tok_a, last_norm_a = _first_token_and_last(fa, la)
        if not last_norm_a or not tok_a:
            continue
        for fb, lb in _owner_name_variants(first_b, last_b):
            tok_b, last_norm_b = _first_token_and_last(fb, lb)
            if not last_norm_b or not tok_b:
                continue
            if last_norm_a == last_norm_b and tok_a == tok_b:
                return True
    return False


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
