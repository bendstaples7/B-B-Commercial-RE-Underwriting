"""Canonical property address completeness (street + city + state + ZIP).

Single writer for completing ``Lead.property_*`` location fields. Reuses
address parsers, Cook County street-only GIS lookup (with suffix retries),
PIN-based situs fill, Chicago/IL market defaults when locality is still blank
after GIS, and Google/Nominatim geocoding as a last resort. Never copies owner
mailing onto property.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import and_, func, or_

from app import db
from app.models import Lead, LeadTimelineEntry
from app.services.address_parse_service import (
    parse_embedded_us_address,
    street_only_from_glued_city_state_zip,
)
from app.services.gis.routing import parse_city_state_zip_from_address

logger = logging.getLogger(__name__)

INCOMPLETE_ADDRESS_REASON = 'incomplete_property_address'

HEAL_INCOMPLETE_BATCH_SIZE = int(os.environ.get('PROPERTY_ADDRESS_HEAL_BATCH_SIZE', '300'))
HEAL_PRIORITY_BATCH_SIZE = int(os.environ.get('PROPERTY_ADDRESS_HEAL_PRIORITY_BATCH', '50'))
HEAL_GIS_WORKERS = int(os.environ.get('PROPERTY_ADDRESS_HEAL_GIS_WORKERS', '4'))
HEAL_INCOMPLETE_CURSOR_KEY = 'property_address:heal_incomplete:last_id'
HEAL_INCOMPLETE_LOCK_KEY = 'property_address:heal_incomplete_lock'

# Ben's book: blank city/state on situs → assume Chicago, IL before GIS/geocode.
DEFAULT_MARKET_CITY = 'Chicago'
DEFAULT_MARKET_STATE = 'IL'

_STREET_SUFFIX_RE = re.compile(
    r'\b(AVE|AVENUE|ST|STREET|BLVD|BOULEVARD|RD|ROAD|DR|DRIVE|CT|COURT|'
    r'LN|LANE|PL|PLACE|TER|TERRACE|WAY|CIR|CIRCLE|PKWY|PARKWAY)\b',
    re.IGNORECASE,
)
# Tried in order when the stored street has no USPS-style suffix.
# Keep this short — each miss is a Cook Socrata round-trip before geocode.
_STREET_SUFFIX_CANDIDATES = ('AVE', 'ST', 'RD', 'BLVD', 'DR', 'LN', 'CT')

_geocode_calls_this_run = 0
_geocode_halt_all = False
_geocode_skip_google = False
_geocode_circuit_reason: str | None = None

GEOCODE_CIRCUIT_REDIS_KEY = 'property_address:geocode_circuit'
GEOCODE_MONTHLY_COUNT_KEY_PREFIX = 'property_address:geocode_billable:'
# Soft-stop before Google free-tier burn (~10k Essentials/mo).
DEFAULT_GEOCODE_MONTHLY_SOFT_CAP = 9000

_GOOGLE_PAID_OR_QUOTA_STATUSES = frozenset({
    'OVER_QUERY_LIMIT',
    'RESOURCE_EXHAUSTED',
})
_GOOGLE_BILLING_HINT_RE = re.compile(
    r'billing|quota|exceeded|daily limit|enable billing|this API project is not authorized to use',
    re.IGNORECASE,
)

_ZIP_RE = re.compile(r'^\d{5}(?:-\d{4})?$')
_TRAILING_ZIP_RE = re.compile(r'[\s,]+(\d{5})(?:-\d{4})?\s*$')
_TRAILING_CITY_STATE_ZIP_RE = re.compile(
    r'[\s,]+'
    r'([A-Za-z][A-Za-z .\'-]{1,40}?)'
    r'[\s,]+'
    r'([A-Za-z]{2})'
    r'(?:[\s,]+(\d{5})(?:-\d{4})?)?'
    r'\s*$'
)


def _clean(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


def title_case_address_part(value: str | None) -> str:
    """Human-readable title case for street/city; leaves empty strings alone."""
    text = _clean(value)
    if not text:
        return ''
    # Preserve mixed-case intentional input (e.g. McDonald) unless ALL CAPS / all lower.
    if not text.isupper() and not text.islower():
        return text
    return ' '.join(
        (part[:1].upper() + part[1:].lower()) if part else part
        for part in text.split(' ')
    )


def display_street(street: str | None) -> str | None:
    """Street-only form for API/UI display.

    Defends against rows whose ``property_street`` still embeds City/State/ZIP
    (e.g. duplicate leads that can't be healed in-place because cleaning would
    collide on ``uq_leads_owner_normalized_street``). Uses the structural
    cleaner — never trusts a possibly-wrong city column — and falls back to
    the raw value if cleaning would blank it.
    """
    if not street:
        return street
    cleaned = street_only_line(street)
    return cleaned if cleaned and len(cleaned) >= 3 else street


def display_zip(street: str | None, zip_code: str | None) -> str | None:
    """ZIP for API/UI display, recovering a trailing ZIP stripped by ``display_street``."""
    text = (zip_code or '').strip()
    if text:
        return text
    raw = (street or '').strip()
    if not raw:
        return None
    match = _TRAILING_ZIP_RE.search(raw)
    return match.group(1) if match else None


_US_STATE_NAMES = {
    'ALABAMA': 'AL', 'ALASKA': 'AK', 'ARIZONA': 'AZ', 'ARKANSAS': 'AR',
    'CALIFORNIA': 'CA', 'COLORADO': 'CO', 'CONNECTICUT': 'CT', 'DELAWARE': 'DE',
    'FLORIDA': 'FL', 'GEORGIA': 'GA', 'HAWAII': 'HI', 'IDAHO': 'ID',
    'ILLINOIS': 'IL', 'INDIANA': 'IN', 'IOWA': 'IA', 'KANSAS': 'KS',
    'KENTUCKY': 'KY', 'LOUISIANA': 'LA', 'MAINE': 'ME', 'MARYLAND': 'MD',
    'MASSACHUSETTS': 'MA', 'MICHIGAN': 'MI', 'MINNESOTA': 'MN',
    'MISSISSIPPI': 'MS', 'MISSOURI': 'MO', 'MONTANA': 'MT', 'NEBRASKA': 'NE',
    'NEVADA': 'NV', 'NEW HAMPSHIRE': 'NH', 'NEW JERSEY': 'NJ',
    'NEW MEXICO': 'NM', 'NEW YORK': 'NY', 'NORTH CAROLINA': 'NC',
    'NORTH DAKOTA': 'ND', 'OHIO': 'OH', 'OKLAHOMA': 'OK', 'OREGON': 'OR',
    'PENNSYLVANIA': 'PA', 'RHODE ISLAND': 'RI', 'SOUTH CAROLINA': 'SC',
    'SOUTH DAKOTA': 'SD', 'TENNESSEE': 'TN', 'TEXAS': 'TX', 'UTAH': 'UT',
    'VERMONT': 'VT', 'VIRGINIA': 'VA', 'WASHINGTON': 'WA',
    'WEST VIRGINIA': 'WV', 'WISCONSIN': 'WI', 'WYOMING': 'WY',
    'DISTRICT OF COLUMBIA': 'DC',
}


def _state_code(state: str | None) -> str | None:
    """Normalize a state name or code to a 2-letter uppercase code."""
    text = (state or '').strip()
    if not text:
        return None
    upper = text.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    mapped = _US_STATE_NAMES.get(upper)
    if mapped:
        return mapped
    return upper[:2] if len(upper) >= 2 else upper


# Trailing ``<City> <Full State Name> [ZIP]`` — full names are unambiguous
# (never a street suffix like CT/Court), so unlike the 2-letter code case this
# may strip without also requiring a ZIP. Multi-word names first for greediness.
_TRAILING_CITY_FULLSTATE_RE = re.compile(
    r'[\s,]+'
    r'([A-Za-z][A-Za-z.\'-]{1,30})'  # single-word city (no internal spaces)
    r'[\s,]+'
    r'(?:' + '|'.join(
        re.escape(name) for name in sorted(_US_STATE_NAMES, key=len, reverse=True)
    ) + r')'
    r'(?:[\s,]+(?:\d{5})(?:-\d{4})?)?'
    r'\s*$',
    re.IGNORECASE,
)


def street_only_line(
    street: str | None,
    *,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
) -> str:
    """Strip trailing ZIP / ``City, ST`` / ``City ST ZIP`` from a street line."""
    text = _clean(street)
    if not text:
        return ''

    # Prefer the structured completer when the line still embeds locality.
    glued = street_only_from_glued_city_state_zip(text)
    if glued:
        text = glued

    parsed = parse_embedded_us_address(text)
    if parsed:
        p_street, p_city, _p_state, p_zip = parsed
        # Collapse when the raw line clearly contained locality beyond street.
        if p_street and len(p_street) < len(text) and (
            ',' in text
            or (p_city and p_city.upper() in text.upper())
            or (p_zip and p_zip in text)
        ):
            text = p_street

    # Places one-liners: ``street, City, Illinois, 60625[, USA]``
    if ',' in text:
        parts = [p.strip() for p in text.split(',') if p.strip()]
        if len(parts) >= 2:
            # Drop trailing country / ZIP / state-name / city tokens.
            while len(parts) > 1:
                tail = parts[-1].upper()
                tail_zip = _zip5(parts[-1])
                if tail in {'USA', 'US', 'UNITED STATES'} or tail_zip:
                    parts.pop()
                    continue
                if tail in _US_STATE_NAMES or (len(tail) == 2 and tail.isalpha()):
                    parts.pop()
                    continue
                city_c = _clean(city)
                if city_c and tail == city_c.upper():
                    parts.pop()
                    continue
                break
            text = parts[0]

    # Strip known trailing city/state/zip using resolved components when present.
    city_c = _clean(city)
    state_c = _clean(state).upper()
    if len(state_c) > 2:
        state_c = _US_STATE_NAMES.get(state_c, state_c[:2])
    zip_c = _zip5(zip_code) or ''
    if city_c:
        # ``, Chicago`` / `` Chicago IL`` / `` Chicago, Illinois``
        state_alt = '|'.join(
            re.escape(s) for s in ({state_c} | {n for n, c in _US_STATE_NAMES.items() if c == state_c})
            if s
        ) or re.escape(state_c or 'IL')
        pattern = re.compile(
            rf'[\s,]+{re.escape(city_c)}'
            rf'(?:\s*,?\s*(?:{state_alt}))?'
            rf'(?:\s*,?\s*{re.escape(zip_c)})?'
            rf'\s*$',
            re.IGNORECASE,
        )
        text = pattern.sub('', text).strip(' ,')
    if zip_c:
        text = re.sub(rf'[\s,]+{re.escape(zip_c)}(?:-\d{{4}})?\s*$', '', text).strip(' ,')

    # Trailing ``<City> <Full State Name> [ZIP]`` (e.g. ``… Chicago Illinois``).
    # Full state names are unambiguous, so strip even without a ZIP.
    fs_match = _TRAILING_CITY_FULLSTATE_RE.search(text)
    if fs_match:
        text = text[:fs_match.start()].strip(' ,')

    # Generic trailing ZIP cleanup (e.g. leftover ``… 60618``).
    text = _TRAILING_ZIP_RE.sub('', text).strip(' ,')

    # Generic ``City ST ZIP`` trailing locality when city still appears at end.
    # Require the trailing ZIP: a bare ``Word ST`` (e.g. ``OXFORD CT``) must never
    # be treated as ``City, <state>`` or we would amputate the street suffix
    # (CT=Court, not Connecticut). The structured ``street City ST ZIP`` case is
    # already handled above via street_only_from_glued_city_state_zip.
    match = _TRAILING_CITY_STATE_ZIP_RE.search(text)
    if match and match.group(3) and match.group(2).upper() in {
        'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
        'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
        'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
        'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
        'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
        'DC',
    }:
        text = text[:match.start()].strip(' ,')

    return text


def find_sibling_complete_locality(lead: Lead) -> dict[str, Any] | None:
    """Find a same property-owner, same-building lead with complete situs.

    Used before Cook GIS so street-only duplicates (e.g. HubSpot husks) absorb
    city/state/ZIP from the complete twin without waiting on the heal cursor.
    Matches on owner first/last name — not CRM ``owner_user_id`` (assignee).
    Never returns mailing_* fields.
    """
    street = _clean(getattr(lead, 'property_street', None))
    lead_id = getattr(lead, 'id', None)
    if not street or not isinstance(lead_id, int):
        return None
    if is_property_address_complete(lead=lead):
        return None

    from app.services.lead_merge_utils import streets_match_normalized

    first = (getattr(lead, 'owner_first_name', None) or '').strip()
    last = (getattr(lead, 'owner_last_name', None) or '').strip()
    if not first:
        return None

    q = Lead.query.filter(
        Lead.id != lead_id,
        Lead.property_street.isnot(None),
        Lead.property_street != '',
        Lead.property_city.isnot(None),
        Lead.property_city != '',
        Lead.property_state.isnot(None),
        Lead.property_state != '',
        Lead.property_zip.isnot(None),
        Lead.property_zip != '',
        func.lower(func.trim(Lead.owner_first_name)) == first.lower(),
    )
    if last:
        q = q.filter(func.lower(func.trim(Lead.owner_last_name)) == last.lower())
    else:
        q = q.filter(
            or_(Lead.owner_last_name.is_(None), Lead.owner_last_name == ''),
        )

    for sibling in q.order_by(Lead.id.asc()).all():
        if not streets_match_normalized(street, sibling.property_street):
            continue
        if not is_property_address_complete(lead=sibling):
            continue
        return {
            'sibling_id': sibling.id,
            'property_city': _clean(sibling.property_city),
            'property_state': _clean(sibling.property_state),
            'property_zip': _clean(sibling.property_zip),
            # Never copy PIN across unit/sibling variants — condo stacks share
            # owner+street loosely and would inherit the wrong unit PIN.
        }
    return None


def is_property_address_complete(
    street: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
    *,
    lead: Lead | None = None,
) -> bool:
    """True when street, city, state, and ZIP are all present."""
    if lead is not None:
        street = getattr(lead, 'property_street', None)
        city = getattr(lead, 'property_city', None)
        state = getattr(lead, 'property_state', None)
        zip_code = getattr(lead, 'property_zip', None)
    return bool(
        _clean(street)
        and _clean(city)
        and _clean(state)
        and _clean(zip_code)
    )


def _is_market_default_city(city: str | None, sources: list[str]) -> bool:
    return (
        'default_market_locality' in sources
        and _clean(city).lower() == DEFAULT_MARKET_CITY.lower()
    )


def _is_market_default_state(state: str | None, sources: list[str]) -> bool:
    return (
        'default_market_locality' in sources
        and _clean(state).upper() == DEFAULT_MARKET_STATE.upper()
    )


def _merge_gis_fill(
    street_out: str | None,
    city_out: str | None,
    state_out: str | None,
    zip_out: str | None,
    sources: list[str],
    gis_fill: Mapping[str, Any],
    *,
    source_tag: str,
    replace_market_defaults: bool = False,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Fill empty locality fields from a GIS/geocode result; optionally upgrade street.

    When ``replace_market_defaults`` is True, Chicago/IL placeholders from
    ``default_market_locality`` may be overwritten by a real GIS/geocode hit.
    """
    if gis_fill.get('property_street') and _should_replace_street(
        street_out or '', gis_fill['property_street'],
    ):
        street_out = gis_fill['property_street']
        sources.append(f'{source_tag}_street')
    fill_city = bool(gis_fill.get('property_city')) and (
        not city_out
        or (replace_market_defaults and _is_market_default_city(city_out, sources))
    )
    if fill_city:
        city_out = gis_fill['property_city']
        sources.append(source_tag)
    fill_state = bool(gis_fill.get('property_state')) and (
        not state_out
        or (replace_market_defaults and _is_market_default_state(state_out, sources))
    )
    if fill_state:
        state_out = gis_fill['property_state']
        sources.append(source_tag)
    if not zip_out and gis_fill.get('property_zip'):
        zip_out = _zip5(gis_fill['property_zip']) or zip_out
        sources.append(source_tag)
    return street_out, city_out, state_out, zip_out


def _street_has_suffix(street: str) -> bool:
    return bool(_STREET_SUFFIX_RE.search(_clean(street)))


def _street_lookup_candidates(street: str) -> list[str]:
    """Original street plus suffix variants when the street type is missing."""
    base = _clean(street)
    if not base:
        return []
    candidates = [base]
    if _street_has_suffix(base):
        return candidates
    for suffix in _STREET_SUFFIX_CANDIDATES:
        candidates.append(f'{base} {suffix}')
    return candidates


def _pick_unique_gis_row(rows: list[dict]) -> dict | None:
    """Prefer a unique Chicago (or single) GIS hit; reject conflicting ZIPs."""
    if not rows:
        return None
    chicago = [
        r for r in rows
        if _clean(r.get('property_city')).upper() == 'CHICAGO'
    ]
    pool = chicago if chicago else rows
    zip_set = {
        z for z in (_zip5(r.get('property_zip')) for r in pool) if z
    }
    if len(zip_set) > 1:
        return None
    cities = {
        _clean(r.get('property_city')).upper()
        for r in pool
        if _clean(r.get('property_city'))
    }
    if len(cities) > 1:
        return None
    return pool[0]


def _gis_row_to_fill(row: dict) -> dict[str, str]:
    return {
        'property_street': _clean(row.get('property_street')),
        'property_city': _clean(row.get('property_city')),
        'property_state': _clean(row.get('property_state')) or 'IL',
        'property_zip': _zip5(row.get('property_zip')) or '',
    }


def _sync_geocode_circuit_from_redis() -> None:
    """Honor persisted halt / skip-Google flags on every geocode path."""
    global _geocode_halt_all, _geocode_skip_google, _geocode_circuit_reason
    persisted = _load_geocode_circuit()
    if not persisted:
        return
    if persisted.get('halt_all'):
        _geocode_halt_all = True
        _geocode_skip_google = True
        _geocode_circuit_reason = (
            persisted.get('reason') or 'persisted geocode circuit'
        )
    elif persisted.get('skip_google'):
        _geocode_skip_google = True
        if not _geocode_circuit_reason:
            _geocode_circuit_reason = (
                persisted.get('reason') or 'persisted skip-google circuit'
            )


def reset_geocode_run_budget() -> None:
    """Reset per-process geocode counter and in-memory circuit for a heal batch."""
    global _geocode_calls_this_run, _geocode_halt_all, _geocode_skip_google
    global _geocode_circuit_reason
    _geocode_calls_this_run = 0
    _geocode_halt_all = False
    _geocode_skip_google = False
    _geocode_circuit_reason = None
    # Re-load persistent circuit (quota/paid halt survives across heal runs).
    _sync_geocode_circuit_from_redis()


def _geocode_budget_allows() -> bool:
    _sync_geocode_circuit_from_redis()
    if _geocode_halt_all:
        return False
    try:
        max_n = int(os.environ.get('PROPERTY_ADDRESS_GEOCODE_MAX_PER_RUN', '50'))
    except (TypeError, ValueError):
        max_n = 50
    return max_n < 0 or _geocode_calls_this_run < max_n


def _monthly_soft_cap() -> int:
    try:
        return int(os.environ.get(
            'PROPERTY_ADDRESS_GEOCODE_MONTHLY_SOFT_CAP',
            str(DEFAULT_GEOCODE_MONTHLY_SOFT_CAP),
        ))
    except (TypeError, ValueError):
        return DEFAULT_GEOCODE_MONTHLY_SOFT_CAP


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m')


def _billable_month_count() -> int:
    from app.services.deploy_sync_policy import get_redis_value

    raw = get_redis_value(f'{GEOCODE_MONTHLY_COUNT_KEY_PREFIX}{_month_key()}')
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _increment_billable_month_count() -> int:
    """Atomically increment the monthly Google geocode counter (Redis INCR)."""
    from app.services.deploy_sync_policy import _redis_client, set_redis_value

    key = f'{GEOCODE_MONTHLY_COUNT_KEY_PREFIX}{_month_key()}'
    client = _redis_client()
    if client is not None:
        try:
            next_n = int(client.incr(key))
            if next_n == 1:
                client.expire(key, 40 * 24 * 3600)
            return max(0, next_n)
        except Exception:
            pass
    # Fallback when Redis is unavailable (single-process best-effort).
    next_n = _billable_month_count() + 1
    set_redis_value(key, str(next_n))
    return next_n


def _load_geocode_circuit() -> dict[str, Any] | None:
    from app.services.deploy_sync_policy import get_redis_value
    import json

    raw = get_redis_value(GEOCODE_CIRCUIT_REDIS_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _persist_geocode_circuit(
    *,
    halt_all: bool,
    skip_google: bool,
    reason: str,
    status: str,
) -> None:
    import json
    from app.services.deploy_sync_policy import set_redis_value

    payload = {
        'halt_all': halt_all,
        'skip_google': bool(skip_google or halt_all),
        'reason': reason,
        'status': status,
        'opened_at': datetime.now(timezone.utc).isoformat(),
    }
    set_redis_value(GEOCODE_CIRCUIT_REDIS_KEY, json.dumps(payload))
    try:
        from app.services.deploy_sync_policy import _redis_client
        client = _redis_client()
        if client is not None:
            client.expire(GEOCODE_CIRCUIT_REDIS_KEY, 7 * 24 * 3600)
    except Exception:
        pass


def clear_geocode_circuit() -> bool:
    """Clear persistent paid/quota halt (ops escape hatch).

    Returns True when Redis delete succeeded. Returns False when the Redis
    client is unavailable or delete raises a Redis/client error so callers can
    tell backend unavailability from a successful clear.
    """
    global _geocode_halt_all, _geocode_skip_google, _geocode_circuit_reason
    _geocode_halt_all = False
    _geocode_skip_google = False
    _geocode_circuit_reason = None
    try:
        from app.services.deploy_sync_policy import _redis_client
        import redis as redis_lib

        client = _redis_client()
        if client is None:
            logger.warning('clear_geocode_circuit: Redis client unavailable')
            return False
        client.delete(GEOCODE_CIRCUIT_REDIS_KEY)
        return True
    except Exception as exc:
        # Prefer Redis client errors; still fail closed for unexpected types.
        try:
            import redis as redis_lib
            if not isinstance(exc, (redis_lib.RedisError, OSError, TimeoutError)):
                logger.warning(
                    'clear_geocode_circuit: unexpected error clearing Redis: %s',
                    exc,
                )
                return False
        except Exception:
            pass
        logger.warning('clear_geocode_circuit: Redis delete failed: %s', exc)
        return False


def get_geocode_circuit_status() -> dict[str, Any]:
    """Health / ops snapshot of geocode stop-gap state."""
    _sync_geocode_circuit_from_redis()
    persisted = _load_geocode_circuit() or {}
    month_count = _billable_month_count()
    soft_cap = _monthly_soft_cap()
    halt = bool(_geocode_halt_all or persisted.get('halt_all'))
    skip_google = bool(
        _geocode_skip_google or persisted.get('skip_google') or halt
    )
    reason = _geocode_circuit_reason or persisted.get('reason')
    return {
        'halt_all': halt,
        'skip_google': skip_google,
        'reason': reason,
        'status': persisted.get('status'),
        'billable_this_month': month_count,
        'monthly_soft_cap': soft_cap,
        'near_soft_cap': soft_cap > 0 and month_count >= soft_cap,
    }


def _trip_geocode_circuit(
    *,
    halt_all: bool,
    reason: str,
    status: str,
) -> None:
    """Open the stop-gap: stop geocoding and make the operator aware."""
    global _geocode_halt_all, _geocode_skip_google, _geocode_circuit_reason
    _geocode_circuit_reason = reason
    if halt_all:
        _geocode_halt_all = True
        _geocode_skip_google = True
        _persist_geocode_circuit(
            halt_all=True, skip_google=True, reason=reason, status=status,
        )
        logger.error(
            'GEOCODE CIRCUIT OPEN (halt all external geocode): status=%s reason=%s '
            '— heal will not call Google/Nominatim until cleared. '
            'Check Google billing/quota or clear via clear_geocode_circuit().',
            status,
            reason,
        )
    else:
        _geocode_skip_google = True
        _persist_geocode_circuit(
            halt_all=False, skip_google=True, reason=reason, status=status,
        )
        logger.warning(
            'GEOCODE: skipping further Google calls: status=%s reason=%s '
            '(Nominatim may still run unless halt_all)',
            status,
            reason,
        )


def _google_status_is_paid_or_quota(status: str, error_message: str = '') -> bool:
    st = (status or '').upper()
    if st in _GOOGLE_PAID_OR_QUOTA_STATUSES:
        return True
    if st == 'REQUEST_DENIED' and _GOOGLE_BILLING_HINT_RE.search(error_message or ''):
        return True
    return bool(_GOOGLE_BILLING_HINT_RE.search(error_message or '') and st not in (
        'OK', 'ZERO_RESULTS', 'CACHE_HIT', 'SKIPPED_NO_KEY',
    ))


def complete_property_address_fields(
    street: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
    *,
    try_gis: bool = True,
    try_geocode: bool | None = None,
    apply_market_defaults: bool = True,
    county_assessor_pin: str | None = None,
) -> dict[str, Any]:
    """Return completed property address components (pure helper for payloads).

    Order: parse → Cook GIS street (suffix retries) → PIN GIS → Chicago/IL
    defaults for still-blank city/state → external geocode last resort.
    Never copies owner mailing fields onto property.

    Pass ``apply_market_defaults=False`` on pre-GIS create/merge paths so a
    blank city is not invented as Chicago (which would route live Cook GIS
    enrichment for every imported row).
    """
    street_out = _clean(street)
    city_out = _clean(city)
    state_out = _clean(state)
    zip_out = _clean(zip_code)
    pin_out = _clean(county_assessor_pin)
    sources: list[str] = []
    # External geocode is opt-in only — callers must pass try_geocode=True
    # explicitly (e.g. batch heal). Never geocode on the interactive/import
    # hot path by default, since Nominatim throttles to ~1 req/sec and a
    # missed mock in a test can otherwise burn real network time.
    do_geocode = False if try_geocode is None else bool(try_geocode)

    if street_out and not is_property_address_complete(
        street_out, city_out, state_out, zip_out,
    ):
        glued = street_only_from_glued_city_state_zip(street_out)
        parsed = parse_embedded_us_address(street_out)
        if parsed:
            p_street, p_city, p_state, p_zip = parsed
            if glued and (not city_out or not state_out or not zip_out):
                street_out = glued
            elif p_street and (not city_out or not state_out or not zip_out):
                # Prefer parsed street when raw line was a one-liner with city/state.
                if street_out == _clean(street) and (
                    p_city or p_state or p_zip
                ):
                    if ',' in street_out or (
                        p_city and p_city.upper() in street_out.upper()
                    ):
                        street_out = p_street or street_out
            if not city_out and p_city:
                city_out = p_city
                sources.append('parse_embedded')
            if not state_out and p_state:
                state_out = p_state
                sources.append('parse_embedded')
            if not zip_out and p_zip:
                zip_out = p_zip
                sources.append('parse_embedded')

        if not is_property_address_complete(street_out, city_out, state_out, zip_out):
            p_city, p_state, p_zip = parse_city_state_zip_from_address(street_out)
            if not city_out and p_city:
                city_out = p_city
                sources.append('parse_places')
            if not state_out and p_state:
                state_out = p_state
                sources.append('parse_places')
            if not zip_out and p_zip:
                zip_out = p_zip
                sources.append('parse_places')

    if (
        try_gis
        and street_out
        and not is_property_address_complete(street_out, city_out, state_out, zip_out)
    ):
        gis_fill = _gis_fill_from_street(street_out)
        if gis_fill:
            street_out, city_out, state_out, zip_out = _merge_gis_fill(
                street_out, city_out, state_out, zip_out, sources, gis_fill,
                source_tag='gis',
            )

    if (
        try_gis
        and pin_out
        and not is_property_address_complete(street_out, city_out, state_out, zip_out)
    ):
        pin_fill = _gis_fill_from_pin(pin_out)
        if pin_fill:
            street_out, city_out, state_out, zip_out = _merge_gis_fill(
                street_out, city_out, state_out, zip_out, sources, pin_fill,
                source_tag='gis_pin',
            )

    # Market defaults after GIS/PIN — never invent ZIP; only blank city/state.
    # Applied here so GIS can write suburban cities before Chicago is assumed.
    # Skip when callers still plan a separate GIS enrichment pass (dedup create).
    if (
        apply_market_defaults
        and street_out
        and not is_property_address_complete(street_out, city_out, state_out, zip_out)
    ):
        if not city_out:
            city_out = DEFAULT_MARKET_CITY
            sources.append('default_market_locality')
        if not state_out:
            state_out = DEFAULT_MARKET_STATE
            sources.append('default_market_locality')

    if (
        do_geocode
        and street_out
        and not is_property_address_complete(street_out, city_out, state_out, zip_out)
    ):
        # Never feed the Chicago/IL market-default placeholder into the geocode
        # query — an assumed locality can steer Google/Nominatim to the wrong
        # match. Let the geocoder infer city/state from the street alone.
        geo_city = None if _is_market_default_city(city_out, sources) else city_out
        geo_state = None if _is_market_default_state(state_out, sources) else state_out
        geo_fill = _geocode_fill_from_street(
            street_out, city=geo_city, state=geo_state,
        )
        if geo_fill:
            street_out, city_out, state_out, zip_out = _merge_gis_fill(
                street_out, city_out, state_out, zip_out, sources, geo_fill,
                source_tag='geocode',
                replace_market_defaults=True,
            )

    # Collapse one-liners / ZIP-in-street leftovers to street-only, then title-case.
    if street_out:
        cleaned_street = street_only_line(
            street_out, city=city_out, state=state_out, zip_code=zip_out,
        )
        if cleaned_street:
            street_out = cleaned_street
        street_out = title_case_address_part(street_out)
    if city_out:
        city_out = title_case_address_part(city_out)
    if state_out:
        state_out = _state_code(state_out) or state_out.upper()
    if zip_out:
        zip_out = _zip5(zip_out) or zip_out

    complete = is_property_address_complete(street_out, city_out, state_out, zip_out)
    return {
        'property_street': street_out or None,
        'property_city': city_out or None,
        'property_state': state_out or None,
        'property_zip': zip_out or None,
        'complete': complete,
        'sources': sorted(set(sources)),
    }


def complete_property_address(
    lead: Lead,
    *,
    try_gis: bool = True,
    try_geocode: bool | None = None,
    apply_market_defaults: bool = True,
    actor: str = 'property_address_completer',
    commit: bool = False,
    write_timeline: bool = True,
    set_review_flag: bool = True,
    preserve_street: bool = False,
) -> dict[str, Any]:
    """Fill missing property city/state/ZIP on *lead*; flag if still incomplete.

    Pass ``set_review_flag=False`` (with ``write_timeline=False``) for preview
    paths that must not persist ``review_required``. ``try_geocode`` defaults
    to off (see ``complete_property_address_fields``) — pass ``True`` only for
    batch heal paths that intend to spend Google/Nominatim budget.
    Pass ``apply_market_defaults=False`` before a separate GIS enrichment pass
    so blank cities are not assumed Chicago.
    Pass ``preserve_street=True`` to fill locality only — used when cleaning a
    glued street would collide on ``uq_leads_owner_normalized_street``.
    """
    was_complete = is_property_address_complete(lead=lead)
    before = {
        'property_street': lead.property_street,
        'property_city': lead.property_city,
        'property_state': lead.property_state,
        'property_zip': lead.property_zip,
        'review_required': bool(getattr(lead, 'review_required', False)),
    }

    # Sibling locality before GIS — same-owner complete twin fills blanks.
    city_in = lead.property_city
    state_in = lead.property_state
    zip_in = lead.property_zip
    pin_in = getattr(lead, 'county_assessor_pin', None)
    sibling_sources: list[str] = []
    sibling = find_sibling_complete_locality(lead)
    if sibling:
        if not _clean(city_in) and sibling.get('property_city'):
            city_in = sibling['property_city']
            sibling_sources.append('sibling_locality')
        if not _clean(state_in) and sibling.get('property_state'):
            state_in = sibling['property_state']
            sibling_sources.append('sibling_locality')
        if not _clean(zip_in) and sibling.get('property_zip'):
            zip_in = sibling['property_zip']
            sibling_sources.append('sibling_locality')

    result = complete_property_address_fields(
        lead.property_street,
        city_in,
        state_in,
        zip_in,
        try_gis=try_gis,
        try_geocode=try_geocode,
        apply_market_defaults=apply_market_defaults,
        county_assessor_pin=pin_in,
    )
    if sibling_sources:
        sources = list(result.get('sources') or [])
        sources.extend(sibling_sources)
        result['sources'] = sorted(set(sources))
        result['sibling_id'] = sibling.get('sibling_id') if sibling else None

    changed_fields: list[str] = []
    for field in (
        'property_street',
        'property_city',
        'property_state',
        'property_zip',
    ):
        if preserve_street and field == 'property_street':
            continue
        new_val = result.get(field)
        old_val = getattr(lead, field, None)
        if new_val and _clean(new_val) != _clean(old_val):
            # Never blank out an existing structured field.
            if not _clean(old_val) or field == 'property_street':
                if field == 'property_street' and _clean(old_val):
                    old_clean = _clean(old_val)
                    # Always allow persisting a pure normalization of the same
                    # street (strip embedded City/ST/ZIP, fix casing) even when
                    # the address is already "complete" — otherwise dirty
                    # one-liners like "4414 N Campbell Ave Chicago IL 60625"
                    # survive and the UI renders the city/state twice. Use the
                    # structural cleaner (no city hint) so a corrupt city column
                    # can never amputate the real street.
                    normalized_old = title_case_address_part(street_only_line(old_clean))
                    is_pure_normalization = (
                        bool(normalized_old)
                        and _clean(new_val) == normalized_old
                        and normalized_old != old_clean
                    )
                    if not is_pure_normalization and not _should_replace_street(
                        old_clean, _clean(new_val),
                    ):
                        continue
                setattr(lead, field, new_val)
                changed_fields.append(field)

    now_complete = is_property_address_complete(lead=lead)
    flagged = False
    cleared_review = False

    if _clean(lead.property_street) and not now_complete:
        if set_review_flag and not lead.review_required:
            lead.review_required = True
            flagged = True
        if write_timeline and (
            flagged or changed_fields or not _has_recent_incomplete_timeline(lead.id)
        ):
            if lead.id is None:
                db.session.add(lead)
                db.session.flush()
            _append_incomplete_timeline(lead.id, actor=actor, result=result)
    elif (
        now_complete
        and not was_complete
        and before['review_required']
        and (
            _has_recent_incomplete_timeline(lead.id)
            or flagged
        )
    ):
        # Only clear review when incompleteness was flagged by this completer
        # (timeline present or flagged in this call) — do not wipe HubSpot /
        # other review_required causes.
        lead.review_required = False
        cleared_review = True
        if write_timeline:
            if lead.id is None:
                db.session.add(lead)
                db.session.flush()
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='property_address_completed',
                occurred_at=datetime.now(timezone.utc),
                source='system',
                actor=actor,
                summary='Property address completed (city/state/ZIP filled).',
                event_metadata={
                    'reason': 'property_address_completed',
                    'fields': changed_fields,
                    'sources': result.get('sources') or [],
                },
            ))

    if changed_fields or flagged or cleared_review:
        db.session.add(lead)

    if commit:
        db.session.commit()

    return {
        'complete': now_complete,
        'changed_fields': changed_fields,
        'sources': result.get('sources') or [],
        'review_required': bool(lead.review_required),
        'flagged_incomplete': flagged,
        'cleared_review': cleared_review,
        'property_street': lead.property_street,
        'property_city': lead.property_city,
        'property_state': lead.property_state,
        'property_zip': lead.property_zip,
    }


def apply_parcel_address_to_lead(
    lead: Lead,
    addr_row: Mapping[str, Any] | None,
    *,
    replace_street: bool = False,
) -> list[str]:
    """Null-only fill property city/state/ZIP (and optional street) from GIS addr row."""
    if not addr_row:
        return []
    changed: list[str] = []
    city = _clean(addr_row.get('property_city'))
    state = _clean(addr_row.get('property_state')) or 'IL'
    zip_code = _zip5(addr_row.get('property_zip'))
    street = _clean(addr_row.get('property_street'))

    if city and not _clean(lead.property_city):
        lead.property_city = title_case_address_part(city)
        changed.append('property_city')
    if state and not _clean(lead.property_state):
        lead.property_state = _state_code(state) or state.upper()[:2]
        changed.append('property_state')
    if zip_code and not _clean(lead.property_zip):
        lead.property_zip = zip_code
        changed.append('property_zip')
    if (
        replace_street
        and street
        and _should_replace_street(_clean(lead.property_street), street)
    ):
        lead.property_street = title_case_address_part(
            street_only_line(street, city=city, state=state, zip_code=zip_code) or street,
        )
        changed.append('property_street')
    return changed


def ensure_lead_property_address_complete(
    lead: Lead,
    *,
    actor: str,
    try_gis: bool = True,
    try_geocode: bool | None = None,
    apply_market_defaults: bool = True,
    commit: bool = False,
    write_timeline: bool = True,
    set_review_flag: bool = True,
) -> dict[str, Any] | None:
    """Run the completer when *lead* has a street but is still incomplete.

    Returns ``None`` when there is nothing to do (no street or already complete).
    """
    if not _clean(getattr(lead, 'property_street', None)):
        return None
    if is_property_address_complete(lead=lead):
        return None
    return complete_property_address(
        lead,
        try_gis=try_gis,
        try_geocode=try_geocode,
        apply_market_defaults=apply_market_defaults,
        actor=actor,
        commit=commit,
        write_timeline=write_timeline,
        set_review_flag=set_review_flag,
    )


def _decorate_heal_summary_with_geocode_circuit(summary: dict[str, Any]) -> dict[str, Any]:
    """Attach geocode circuit fields on every heal return path."""
    circuit = get_geocode_circuit_status()
    summary['geocode_circuit'] = circuit
    if circuit.get('halt_all'):
        summary['geocode_halted'] = True
        summary['status'] = 'completed_with_geocode_halt'
        logger.error(
            'property address heal finished with geocode circuit OPEN: %s',
            circuit.get('reason') or 'halt_all',
        )
    return summary


def _incomplete_property_address_clause():
    """SQL filter: non-empty street with missing city, state, or ZIP."""
    return and_(
        Lead.property_street.isnot(None),
        func.trim(Lead.property_street) != '',
        or_(
            Lead.property_city.is_(None),
            func.trim(Lead.property_city) == '',
            Lead.property_state.is_(None),
            func.trim(Lead.property_state) == '',
            Lead.property_zip.is_(None),
            func.trim(Lead.property_zip) == '',
        ),
    )


def _priority_incomplete_clause():
    """Incomplete situs on active work surfaces (TA due / skip-trace / outreach RA)."""
    from datetime import date as date_cls

    from app.models import LeadTask
    from sqlalchemy import exists

    has_due_task = exists().where(
        and_(
            LeadTask.lead_id == Lead.id,
            LeadTask.status == 'open',
            LeadTask.due_date.isnot(None),
            LeadTask.due_date <= date_cls.today(),
        )
    )
    return and_(
        _incomplete_property_address_clause(),
        or_(
            has_due_task,
            Lead.lead_status == 'skip_trace',
            Lead.recommended_action.in_(
                (
                    'mail_ready',
                    'call_ready',
                    'follow_up_now',
                    'hold',
                    'ready_for_outreach',
                )
            ),
        ),
    )


def _select_heal_batch(
    *,
    cursor: int,
    batch_limit: int,
    lead_id: int | None,
) -> tuple[list[Lead], set[int], bool]:
    """Priority incompletes first, then cursor backlog. Returns (leads, priority_ids, wrapped)."""
    wrapped = False
    if lead_id is not None:
        leads = (
            Lead.query
            .filter(_incomplete_property_address_clause(), Lead.id == lead_id)
            .limit(1)
            .all()
        )
        return leads, {lead.id for lead in leads}, False

    priority_limit = max(0, min(HEAL_PRIORITY_BATCH_SIZE, batch_limit))
    priority_leads = (
        Lead.query
        .filter(_priority_incomplete_clause())
        .order_by(Lead.id.asc())
        .limit(priority_limit)
        .all()
    ) if priority_limit else []
    priority_ids = {lead.id for lead in priority_leads}
    remaining = max(batch_limit - len(priority_leads), 0)

    cursor_leads: list[Lead] = []
    if remaining:
        query = (
            Lead.query
            .filter(
                _incomplete_property_address_clause(),
                Lead.id > cursor,
            )
            .order_by(Lead.id.asc())
        )
        if priority_ids:
            query = query.filter(~Lead.id.in_(priority_ids))
        cursor_leads = query.limit(remaining).all()
        if not cursor_leads and not priority_leads and cursor > 0:
            wrapped = True
            cursor = 0
            query = (
                Lead.query
                .filter(
                    _incomplete_property_address_clause(),
                    Lead.id > cursor,
                )
                .order_by(Lead.id.asc())
            )
            if priority_ids:
                query = query.filter(~Lead.id.in_(priority_ids))
            cursor_leads = query.limit(remaining).all()

    # Priority first so active-queue gaps heal before deep backlog.
    ordered: list[Lead] = list(priority_leads)
    seen = set(priority_ids)
    for lead in cursor_leads:
        if lead.id not in seen:
            ordered.append(lead)
            seen.add(lead.id)
    return ordered, priority_ids, wrapped


def _heal_incomplete_cursor() -> int:
    from app.services.deploy_sync_policy import get_redis_value

    raw = get_redis_value(HEAL_INCOMPLETE_CURSOR_KEY)
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _set_heal_incomplete_cursor(last_id: int) -> None:
    from app.services.deploy_sync_policy import set_redis_value

    set_redis_value(HEAL_INCOMPLETE_CURSOR_KEY, str(max(0, int(last_id))))


def heal_incomplete_property_addresses(
    *,
    last_id: int | None = None,
    limit: int = HEAL_INCOMPLETE_BATCH_SIZE,
    try_gis: bool = True,
    try_geocode: bool | None = None,
    actor: str = 'property_address_heal',
    persist_cursor: bool = True,
    commit: bool = True,
    lead_id: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Batch-complete incomplete situs addresses; advance Redis cursor.

    When ``dry_run`` is True, runs the pure field completer only (no DB writes).
    GIS is still contacted when ``try_gis`` is True — pass ``try_gis=False`` for
    offline previews. When ``lead_id`` is set, processes that lead only and does
    not touch the cursor. ``try_geocode`` defaults to ``try_gis`` (batch heal is
    the intended geocode spender) — pass ``try_geocode=False`` to keep a heal
    run GIS-only, or ``True``/``False`` explicitly to override.
    """
    reset_geocode_run_budget()
    effective_try_geocode = try_gis if try_geocode is None else try_geocode
    batch_limit = max(int(limit), 0)
    cursor = 0 if lead_id is not None else (
        _heal_incomplete_cursor() if last_id is None else max(0, int(last_id))
    )
    summary: dict[str, Any] = {
        'status': 'completed',
        'processed': 0,
        'completed': 0,
        'still_incomplete': 0,
        'errors': 0,
        'absorbed': 0,
        'flagged_duplicates': 0,
        'priority_processed': 0,
        'last_id': cursor,
        'wrapped': False,
        'dry_run': bool(dry_run),
        'lead_ids': [],
        'previews': [],
    }
    if batch_limit == 0 and lead_id is None:
        return _decorate_heal_summary_with_geocode_circuit(summary)

    leads, priority_ids, wrapped = _select_heal_batch(
        cursor=cursor,
        batch_limit=batch_limit,
        lead_id=lead_id,
    )
    summary['wrapped'] = wrapped
    summary['priority_processed'] = len(priority_ids & {lead.id for lead in leads})

    completed_ids: list[int] = []
    rescore_ids: set[int] = set()
    # Advance cursor only through non-priority backlog rows so priority re-heals
    # until complete without starving the ID walk.
    advanced_cursor = cursor
    from sqlalchemy.exc import IntegrityError

    # Prefetch GIS fills in parallel for leads that still need locality after
    # sibling lookup. Sibling DB lookup stays on the main thread; workers only
    # run pure field completion (Cook GIS HTTP).
    gis_prefetch: dict[int, dict[str, Any]] = {}
    if (
        try_gis
        and not dry_run
        and HEAL_GIS_WORKERS > 1
        and len(leads) > 1
    ):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        snapshots: list[tuple[int, str | None, str | None, str | None, str | None, str | None]] = []
        for item in leads:
            sib = find_sibling_complete_locality(item)
            city = item.property_city or (sib or {}).get('property_city')
            state = item.property_state or (sib or {}).get('property_state')
            zip_code = item.property_zip or (sib or {}).get('property_zip')
            pin = getattr(item, 'county_assessor_pin', None)
            if is_property_address_complete(
                item.property_street, city, state, zip_code,
            ):
                continue
            snapshots.append((
                item.id,
                item.property_street,
                city,
                state,
                zip_code,
                pin,
            ))

        def _prefetch_one(
            payload: tuple[int, str | None, str | None, str | None, str | None, str | None],
        ) -> tuple[int, dict[str, Any]]:
            lid, street, city, state, zip_code, pin = payload
            filled = complete_property_address_fields(
                street,
                city,
                state,
                zip_code,
                try_gis=True,
                try_geocode=False,
                apply_market_defaults=False,
                county_assessor_pin=pin,
            )
            return lid, filled

        if snapshots:
            workers = max(1, min(HEAL_GIS_WORKERS, len(snapshots)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_prefetch_one, snap) for snap in snapshots]
                for fut in as_completed(futures):
                    try:
                        lid, filled = fut.result()
                        gis_prefetch[lid] = filled
                    except Exception as exc:
                        logger.warning(
                            'property address GIS prefetch failed: %s', exc,
                        )

    for lead in leads:
        summary['processed'] += 1
        summary['lead_ids'].append(lead.id)
        try:
            if dry_run:
                sib = find_sibling_complete_locality(lead)
                city = lead.property_city or (sib or {}).get('property_city')
                state = lead.property_state or (sib or {}).get('property_state')
                zip_code = lead.property_zip or (sib or {}).get('property_zip')
                result = complete_property_address_fields(
                    lead.property_street,
                    city,
                    state,
                    zip_code,
                    try_gis=try_gis,
                    try_geocode=effective_try_geocode,
                    county_assessor_pin=getattr(lead, 'county_assessor_pin', None),
                )
                if sib:
                    sources = list(result.get('sources') or [])
                    sources.append('sibling_locality')
                    result['sources'] = sorted(set(sources))
                summary['previews'].append({
                    'lead_id': lead.id,
                    'before': {
                        'property_street': lead.property_street,
                        'property_city': lead.property_city,
                        'property_state': lead.property_state,
                        'property_zip': lead.property_zip,
                    },
                    'after': {
                        'property_street': result.get('property_street'),
                        'property_city': result.get('property_city'),
                        'property_state': result.get('property_state'),
                        'property_zip': result.get('property_zip'),
                    },
                    'complete': bool(result.get('complete')),
                    'sources': result.get('sources') or {},
                    'sibling_id': (sib or {}).get('sibling_id'),
                })
                if result.get('complete'):
                    summary['completed'] += 1
                else:
                    summary['still_incomplete'] += 1
                if lead_id is None and lead.id not in priority_ids:
                    advanced_cursor = max(advanced_cursor, lead.id)
                continue

            prefetched = gis_prefetch.get(lead.id)
            try:
                with db.session.begin_nested():
                    if prefetched and prefetched.get('complete'):
                        # Apply parallel GIS/sibling field result without a
                        # second GIS round-trip.
                        for field in (
                            'property_city',
                            'property_state',
                            'property_zip',
                        ):
                            if not _clean(getattr(lead, field, None)) and prefetched.get(field):
                                setattr(lead, field, prefetched[field])
                        result = complete_property_address(
                            lead,
                            try_gis=False,
                            try_geocode=effective_try_geocode,
                            actor=actor,
                            commit=False,
                        )
                    else:
                        result = complete_property_address(
                            lead,
                            try_gis=try_gis,
                            try_geocode=effective_try_geocode,
                            actor=actor,
                            commit=False,
                        )
                    db.session.flush()
            except IntegrityError as street_exc:
                logger.info(
                    'property address heal street collision lead=%s; '
                    'retrying locality-only: %s',
                    lead.id,
                    street_exc,
                )
                with db.session.begin_nested():
                    result = complete_property_address(
                        lead,
                        try_gis=try_gis,
                        try_geocode=effective_try_geocode,
                        actor=actor,
                        commit=False,
                        preserve_street=True,
                    )
                    db.session.flush()
            if result.get('complete'):
                summary['completed'] += 1
                completed_ids.append(lead.id)
                rescore_ids.add(lead.id)
            else:
                summary['still_incomplete'] += 1

            # Absorb clear same-building twins (or flag for Needs Review).
            absorbed_away = False
            try:
                from app.services.lead_dedup_service import try_absorb_duplicate_for_lead
                absorb = try_absorb_duplicate_for_lead(lead, changed_by=actor)
                if absorb:
                    if absorb.get('merged'):
                        summary['absorbed'] += len(absorb.get('merged_pairs') or [])
                        winner_id = absorb.get('winner_id')
                        if isinstance(winner_id, int):
                            rescore_ids.add(winner_id)
                        # Current lead may have been the loser and deleted.
                        if any(
                            pair.get('loser_id') == lead.id
                            for pair in (absorb.get('merged_pairs') or [])
                        ):
                            absorbed_away = True
                            completed_ids[:] = [
                                lid for lid in completed_ids if lid != lead.id
                            ]
                            rescore_ids.discard(lead.id)
                    if absorb.get('flagged'):
                        summary['flagged_duplicates'] += 1
            except Exception as absorb_exc:
                logger.warning(
                    'sibling absorb after heal failed lead=%s: %s',
                    lead.id,
                    absorb_exc,
                )

            if (
                lead_id is None
                and not absorbed_away
                and lead.id not in priority_ids
            ):
                advanced_cursor = max(advanced_cursor, lead.id)
        except Exception as exc:
            summary['errors'] += 1
            logger.warning(
                'property address heal failed for lead %s: %s',
                lead.id,
                exc,
            )
            if lead_id is None and lead.id not in priority_ids:
                advanced_cursor = max(advanced_cursor, lead.id)
            continue

    if commit and not dry_run and leads:
        db.session.commit()
        for completed_lead_id in sorted(rescore_ids):
            try:
                from app.services.lead_refresh import refresh_lead_scoring
                refresh_lead_scoring(completed_lead_id)
            except Exception as exc:
                logger.warning(
                    'property address heal rescore failed lead=%s: %s',
                    completed_lead_id,
                    exc,
                )

    if lead_id is None:
        if not leads:
            advanced_cursor = 0
            summary['wrapped'] = True
        summary['last_id'] = advanced_cursor
        if persist_cursor:
            _set_heal_incomplete_cursor(advanced_cursor)
    else:
        summary['last_id'] = lead_id or 0

    return _decorate_heal_summary_with_geocode_circuit(summary)


def _zip5(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    match = _ZIP_RE.match(text.split()[0] if text else '')
    if match:
        return match.group(0)[:5]
    # Assessor often returns ZIP+4 as 60622-3009
    if '-' in text:
        head = text.split('-', 1)[0]
        if _ZIP_RE.match(head):
            return head[:5]
    digits = re.sub(r'\D', '', text)
    if len(digits) >= 5:
        return digits[:5]
    return None


def _should_replace_street(current: str, assessor: str) -> bool:
    """Replace street when current lacks a street suffix the assessor has."""
    if not assessor:
        return False
    if not current:
        return True
    if current.upper() == assessor.upper():
        return False
    suffix_re = re.compile(
        r'\b(AVE|AVENUE|ST|STREET|BLVD|RD|ROAD|DR|DRIVE|CT|LN|PL|TER|WAY)\b',
        re.IGNORECASE,
    )
    return not bool(suffix_re.search(current)) and bool(suffix_re.search(assessor))


def _gis_fill_from_street(street: str) -> dict[str, str] | None:
    """Cook County street lookup with suffix retries when the street type is missing."""
    try:
        from app.services.gis.cook_county_gis_connector import (
            CookCountyGISConnector,
            lookup_all_pins_at_address,
        )

        for candidate in _street_lookup_candidates(street):
            rows = lookup_all_pins_at_address(candidate)
            picked = _pick_unique_gis_row(rows)
            if picked:
                return _gis_row_to_fill(picked)

        # Single connector fallback on the original street only (avoid N× timeouts).
        connector = CookCountyGISConnector()
        parcel = connector.lookup_by_address(street)
        if parcel is None or not parcel.county_assessor_pin:
            return None
        addr = connector.lookup_address_by_pin(parcel.county_assessor_pin)
        if not addr:
            return None
        picked = _pick_unique_gis_row([addr])
        return _gis_row_to_fill(picked) if picked else None
    except Exception as exc:
        logger.warning('GIS street fill failed for %r: %s', street, exc)
        return None


def _geocode_fill_from_street(
    street: str,
    *,
    city: str | None = None,
    state: str | None = None,
) -> dict[str, str] | None:
    """External geocode last resort for incomplete situs (never uses mailing).

    Tries Google (server key) then OpenStreetMap Nominatim when Google is
    unavailable — unless the paid/quota circuit is open (then stop entirely
    and surface the halt via logs + health).
    """
    global _geocode_calls_this_run
    if not _geocode_budget_allows():
        if _geocode_halt_all:
            logger.error(
                'Geocode situs blocked by circuit: %s',
                _geocode_circuit_reason or 'halt_all',
            )
        else:
            logger.info('Geocode situs skipped — PROPERTY_ADDRESS_GEOCODE_MAX_PER_RUN reached')
        return None

    # Soft-cap: stop Google before free tier rolls into paid usage.
    # Nominatim remains allowed (skip_google only — not halt_all).
    soft_cap = _monthly_soft_cap()
    month_count = _billable_month_count()
    if soft_cap > 0 and month_count >= soft_cap and not _geocode_skip_google:
        _trip_geocode_circuit(
            halt_all=False,
            reason=(
                f'Monthly Google geocode soft-cap reached '
                f'({month_count}/{soft_cap}). Skipping Google to avoid '
                f'paid-mode charges; Nominatim may still run. Raise '
                f'PROPERTY_ADDRESS_GEOCODE_MONTHLY_SOFT_CAP or clear circuit '
                f'after reviewing Google billing.'
            ),
            status='SOFT_CAP',
        )

    query_parts = [_clean(street)]
    if _clean(city):
        query_parts.append(_clean(city))
    if _clean(state):
        query_parts.append(_clean(state))
    query = ', '.join(query_parts)
    if not query:
        return None

    _geocode_calls_this_run += 1

    if not _geocode_skip_google:
        try:
            from app.services.property_data_service import PropertyDataService

            outcome = PropertyDataService().geocode_structured_address(
                query,
                components='country:US|administrative_area:IL',
            )
            # Count only billable Google responses toward the soft-cap.
            if outcome.billable:
                new_count = _increment_billable_month_count()
                if soft_cap > 0 and new_count >= soft_cap:
                    _trip_geocode_circuit(
                        halt_all=False,
                        reason=(
                            f'Monthly Google geocode soft-cap reached after '
                            f'billable call ({new_count}/{soft_cap}).'
                        ),
                        status='SOFT_CAP',
                    )

            if _google_status_is_paid_or_quota(outcome.status, outcome.error_message):
                _trip_geocode_circuit(
                    halt_all=True,
                    reason=(
                        f'Google Geocoding entered quota/billing mode: '
                        f'{outcome.status} {outcome.error_message}'.strip()
                    ),
                    status=outcome.status,
                )
                return None

            if outcome.status == 'REQUEST_DENIED':
                # Misconfigured / referer-restricted key — skip Google, allow Nominatim.
                _trip_geocode_circuit(
                    halt_all=False,
                    reason=(
                        f'Google REQUEST_DENIED: {outcome.error_message or "no detail"}'
                    ),
                    status=outcome.status,
                )
            elif outcome.address:
                return {
                    'property_street': _clean(outcome.address.get('property_street')),
                    'property_city': _clean(outcome.address.get('property_city')),
                    'property_state': _clean(outcome.address.get('property_state')) or 'IL',
                    'property_zip': _zip5(outcome.address.get('property_zip')) or '',
                }
        except Exception as exc:
            logger.warning('Google geocode situs fill failed for %r: %s', query, exc)

    if _geocode_halt_all:
        return None

    try:
        nominatim = _nominatim_structured_address(query)
        if nominatim:
            return nominatim
    except Exception as exc:
        logger.warning('Nominatim geocode situs fill failed for %r: %s', query, exc)
    return None


_last_nominatim_monotonic: float = 0.0
_NOMINATIM_MIN_INTERVAL_SEC = 1.05


def _nominatim_structured_address(query: str) -> dict[str, str] | None:
    """Free OSM Nominatim fallback when Google Geocoding is unavailable."""
    global _last_nominatim_monotonic
    import json
    import time
    import urllib.parse
    import urllib.request

    # OSM usage policy: ~1 request/second.
    elapsed = time.monotonic() - _last_nominatim_monotonic
    if _last_nominatim_monotonic > 0 and elapsed < _NOMINATIM_MIN_INTERVAL_SEC:
        time.sleep(_NOMINATIM_MIN_INTERVAL_SEC - elapsed)

    params = urllib.parse.urlencode({
        'q': query,
        'format': 'json',
        'addressdetails': '1',
        'limit': '1',
        'countrycodes': 'us',
    })
    url = f'https://nominatim.openstreetmap.org/search?{params}'
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'BAndBRealEstateAnalyzer/1.0 (property-address-heal)',
            'Accept': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            rows = json.loads(resp.read().decode('utf-8'))
    finally:
        _last_nominatim_monotonic = time.monotonic()
    if not rows:
        return None
    row = rows[0]
    addr = row.get('address') or {}
    # Require a road-level hit — reject city/state centroids.
    if not addr.get('road') and not addr.get('pedestrian'):
        return None
    number = (addr.get('house_number') or '').strip()
    road = (addr.get('road') or addr.get('pedestrian') or '').strip()
    street = ' '.join(p for p in (number, road) if p).strip()
    city = (
        addr.get('city')
        or addr.get('town')
        or addr.get('village')
        or addr.get('hamlet')
        or ''
    ).strip()
    state = (addr.get('state') or '').strip()
    # Prefer ISO3166-2-lvl4 US-IL style short code when present.
    state_code = (addr.get('ISO3166-2-lvl4') or '').split('-')[-1] or ''
    if len(state_code) == 2:
        state = state_code
    elif state.upper() in ('ILLINOIS', 'IL'):
        state = 'IL'
    else:
        state = _state_code(state) or state
    zip_code = _zip5(addr.get('postcode')) or ''
    if not street or not city or not state or not zip_code:
        return None
    return {
        'property_street': street,
        'property_city': city,
        'property_state': state,
        'property_zip': zip_code,
    }


def _gis_fill_from_pin(pin: str) -> dict[str, str] | None:
    """Cook County situs fill from an existing assessor PIN."""
    try:
        from app.services.gis.cook_county_gis_connector import CookCountyGISConnector

        connector = CookCountyGISConnector()
        addr = connector.lookup_address_by_pin(pin)
        if not addr:
            return None
        city = _clean(addr.get('property_city'))
        zip_code = _zip5(addr.get('property_zip')) or ''
        state = _clean(addr.get('property_state'))
        if not state and (city or zip_code):
            state = 'IL'
        street = _clean(addr.get('property_street'))
        if not city and not zip_code and not street:
            return None
        return {
            'property_street': street,
            'property_city': city,
            'property_state': state or '',
            'property_zip': zip_code,
        }
    except Exception as exc:
        logger.warning('GIS PIN fill failed for %r: %s', pin, exc)
        return None


def _has_recent_incomplete_timeline(lead_id: int | None) -> bool:
    if not lead_id:
        return False
    entry = (
        LeadTimelineEntry.query
        .filter_by(lead_id=lead_id, event_type='property_address_incomplete')
        .order_by(LeadTimelineEntry.occurred_at.desc())
        .first()
    )
    return entry is not None


def _append_incomplete_timeline(
    lead_id: int | None,
    *,
    actor: str,
    result: Mapping[str, Any],
) -> None:
    if not lead_id:
        return
    db.session.add(LeadTimelineEntry(
        lead_id=lead_id,
        event_type='property_address_incomplete',
        occurred_at=datetime.now(timezone.utc),
        source='system',
        actor=actor,
        summary='Property address incomplete — city, state, or ZIP missing.',
        event_metadata={
            'reason': INCOMPLETE_ADDRESS_REASON,
            'property_street': result.get('property_street'),
            'property_city': result.get('property_city'),
            'property_state': result.get('property_state'),
            'property_zip': result.get('property_zip'),
            'sources_tried': result.get('sources') or [],
        },
    ))
