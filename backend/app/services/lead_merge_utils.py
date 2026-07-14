"""Helpers for merging duplicate leads (normalized address + winner selection)."""
from __future__ import annotations

from typing import Any, Optional, Sequence

from app.services.hubspot_matcher_service import HubSpotMatcherService

# Trailing street-type tokens stripped for building-level dedup identity.
_STREET_TYPE_SUFFIXES = (
    'BOULEVARD', 'PARKWAY', 'HIGHWAY', 'AVENUE', 'CIRCLE',
    'STREET', 'DRIVE', 'ROAD', 'COURT', 'LANE', 'PLACE',
)

# Cardinal direction as the token immediately after the house number.
_CARDINAL_TO_ABBREV = {
    'NORTH': 'N',
    'SOUTH': 'S',
    'EAST': 'E',
    'WEST': 'W',
}

# Higher rank = more advanced pipeline stage (winner preference).
LEAD_STATUS_RANK: dict[str, int] = {
    'deal_won': 100,
    'deal_lost': 5,
    'offer_delivered': 95,
    'in_person_appointment': 90,
    'negotiating_remote': 85,
    'mailing_contacted_interested': 70,
    'mailing_contacted_no_interest': 60,
    'mailing_no_contact_made': 50,
    'awaiting_skip_trace': 40,
    'skip_trace': 35,
    'deprioritize': 20,
    'suppressed': 10,
    'do_not_contact': 0,
}


def street_line_from_address(address: Optional[str]) -> str:
    """Return the street line from a Places-style or glued full address.

    Prefer the segment before the first comma (``street, city, state ZIP``).
    When commas are missing, strip a trailing ``City ST ZIP`` only when a
    2-letter US state is present — do not use zip-only parsing (that would
    turn ``1719 W Barry 60657`` into ``1719 W``).
    """
    text = (address or '').strip()
    if not text:
        return ''
    if ',' in text:
        return text.split(',', 1)[0].strip()
    from app.services.address_parse_service import street_only_from_glued_city_state_zip

    street = street_only_from_glued_city_state_zip(text)
    if street:
        return street
    return text


def cities_compatible(a: Optional[str], b: Optional[str]) -> bool:
    """True when cities match, or when either side is missing (incomplete data)."""
    left = (a or '').strip().lower()
    right = (b or '').strip().lower()
    if not left or not right:
        return True
    return left == right


def _collapse_cardinal_after_house(norm: str) -> str:
    """Collapse NORTH/SOUTH/EAST/WEST when it is the token after the house number."""
    parts = norm.split()
    if (
        len(parts) >= 3
        and parts[1] in _CARDINAL_TO_ABBREV
        and parts[2] not in _STREET_TYPE_SUFFIXES
    ):
        parts[1] = _CARDINAL_TO_ABBREV[parts[1]]
        return ' '.join(parts)
    return norm


def normalized_street_key(street: Optional[str]) -> str:
    """Return normalized address for grouping duplicate leads."""
    return HubSpotMatcherService.normalize_address(street or '')


def dedup_street_key(street: Optional[str]) -> str:
    """Building-level street key used for DB uniqueness (strips trailing street type)."""
    # Prefer the street line when callers pass a Places "street, city, state ZIP" value.
    line = street_line_from_address(street) or (street or '')
    norm = _collapse_cardinal_after_house(normalized_street_key(line))
    if not norm:
        return ''
    for suffix in _STREET_TYPE_SUFFIXES:
        token = ' ' + suffix
        if norm.endswith(token):
            return norm[:-len(token)].strip()
    return norm


def streets_match_normalized(a: Optional[str], b: Optional[str]) -> bool:
    """True when two street strings normalize to the same building-level address."""
    ka = dedup_street_key(a)
    kb = dedup_street_key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    # Unit-suffix variants (e.g. bare building vs "Apt 1")
    return ka.startswith(kb + ' ') or kb.startswith(ka + ' ')


def owner_group_key(
    first: Optional[str],
    last: Optional[str],
    street: Optional[str],
    owner_user_id: Optional[str],
) -> tuple[str, str, Optional[str]]:
    """Grouping key for owner-scoped duplicate detection (street clustered separately)."""
    return (
        (first or '').strip().lower(),
        (last or '').strip().lower(),
        owner_user_id,
    )


def cluster_leads_by_normalized_street(
    records: Sequence[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Cluster leads whose streets normalize to the same address."""
    clusters: list[list[dict[str, Any]]] = []
    for row in records:
        street = row.get('property_street')
        placed = False
        for cluster in clusters:
            if streets_match_normalized(street, cluster[0].get('property_street')):
                cluster.append(row)
                placed = True
                break
        if not placed:
            clusters.append([row])
    return [c for c in clusters if len(c) >= 2]


def winner_sort_key(
    record: dict[str, Any],
    confirmed_hubspot_lead_ids: set[int],
) -> tuple[int, int, int, int, int]:
    """Sort key for picking merge winner (higher is better)."""
    lead_id = int(record['id'])
    status_rank = LEAD_STATUS_RANK.get(record.get('lead_status') or '', 0)
    hubspot_bonus = 10_000 if lead_id in confirmed_hubspot_lead_ids else 0
    contact_bonus = 0
    if record.get('has_phone'):
        contact_bonus += 10
    if record.get('has_email'):
        contact_bonus += 10
    sync_bonus = 5 if record.get('last_hubspot_sync_at') else 0
    # Negative id so lower id wins ties
    return (hubspot_bonus, status_rank, contact_bonus + sync_bonus, 0, -lead_id)


def pick_merge_winner(
    records: Sequence[dict[str, Any]],
    confirmed_hubspot_lead_ids: set[int],
) -> dict[str, Any]:
    """Pick the canonical lead to keep when merging duplicates."""
    if not records:
        raise ValueError('pick_merge_winner requires at least one record')
    return max(records, key=lambda r: winner_sort_key(r, confirmed_hubspot_lead_ids))


def merge_mailer_history(winner_val: Any, loser_val: Any) -> Any:
    """Union mailer_history from duplicate leads without dropping loser events."""

    def _to_entries(value: Any) -> list[Any]:
        if value is None or value == '':
            return []
        if isinstance(value, list):
            return list(value)
        return [value]

    winner_entries = _to_entries(winner_val)
    loser_entries = _to_entries(loser_val)
    if not loser_entries:
        return winner_val if winner_entries else None
    if not winner_entries:
        return loser_val
    return winner_entries + loser_entries


def owner_names_from_deal_props(props: dict) -> tuple[str, str]:
    """Extract owner first/last from HubSpot deal properties when present."""
    first = (
        props.get('firstname')
        or props.get('contact_first_name')
        or props.get('owner_first_name')
        or ''
    ).strip()
    last = (
        props.get('lastname')
        or props.get('contact_last_name')
        or props.get('owner_last_name')
        or ''
    ).strip()
    return first, last


def filter_leads_by_owner_name(
    leads: Sequence[Any],
    owner_first: str,
    owner_last: str,
) -> list[Any]:
    """Narrow address matches to leads with matching owner name."""
    if not owner_first and not owner_last:
        return list(leads)
    first_l = owner_first.lower()
    last_l = owner_last.lower()
    matched = []
    for lead in leads:
        lf = (getattr(lead, 'owner_first_name', None) or '').strip().lower()
        ll = (getattr(lead, 'owner_last_name', None) or '').strip().lower()
        if first_l and lf != first_l:
            continue
        if last_l and ll != last_l:
            continue
        matched.append(lead)
    return matched if matched else list(leads)


def pick_best_lead_for_deal(
    leads: Sequence[Any],
    confirmed_hubspot_lead_ids: set[int],
    deal_props: Optional[dict] = None,
) -> Any:
    """Pick the best lead from address matches for a HubSpot deal."""
    props = deal_props or {}
    owner_first, owner_last = owner_names_from_deal_props(props)
    narrowed = filter_leads_by_owner_name(leads, owner_first, owner_last)
    rows = [
        {
            'id': lead.id,
            'lead_status': getattr(lead, 'lead_status', None),
            'has_phone': getattr(lead, 'has_phone', False),
            'has_email': getattr(lead, 'has_email', False),
            'last_hubspot_sync_at': getattr(lead, 'last_hubspot_sync_at', None),
        }
        for lead in narrowed
    ]
    winner_row = pick_merge_winner(rows, confirmed_hubspot_lead_ids)
    winner_id = winner_row['id']
    for lead in narrowed:
        if lead.id == winner_id:
            return lead
    return narrowed[0]
