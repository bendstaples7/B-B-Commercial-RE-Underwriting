"""Canonical owner-mailing normalize-on-write, heal, and readiness helpers.

Writers (HubSpot enrich, sheets import, OLC Corrected, heal, Apply Parsed UI)
should go through ``apply_owner_mailing`` / ``normalize_owner_mailing_on_lead``
so tab dumps and short ZIPs never land as incomplete street-only rows.

Enqueue-time ``persist_embedded_address_fields`` stays locality-only (no street
rewrite) for dedup identity safety during mail submit.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import and_, or_

from app import db
from app.models.lead import Lead
from app.services.address_parse_service import (
    parse_city_state_zip_line,
    parse_embedded_us_address,
    street_looks_tabular,
)
from app.services.open_letter_contact_mapper import (
    is_owner_mailable_lead,
    owner_mailing_address,
    validate_owner_mailing_address,
)

logger = logging.getLogger(__name__)

HEAL_OWNER_MAILING_CURSOR_KEY = 'heal:owner_mailing_incomplete:last_id'
HEAL_OWNER_MAILING_LOCK_KEY = 'lock:heal_owner_mailing_incomplete'
HEAL_OWNER_MAILING_BATCH_SIZE = 200


def _clean(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


def normalize_mailing_parts(
    street: str | None,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
) -> tuple[str, str, str, str]:
    """Return (street, city, state, zip) with embedded parse + ZIP padding applied."""
    s = _clean(street)
    c = _clean(city)
    st = _clean(state)
    z = _clean(zip_code)

    # City column sometimes holds ``Chicago, IL 60647`` from imports.
    if c and (',' in c or not st or not z):
        locality = parse_city_state_zip_line(c)
        if locality:
            c, loc_state, loc_zip = locality
            st = st or loc_state
            z = z or loc_zip

    if s and c and st and z and not street_looks_tabular(s):
        synthetic = f'{s}, {c}, {st} {z}'
        parsed_zip = parse_embedded_us_address(synthetic)
        if parsed_zip:
            # Prefer original street when synthetic re-parse would steal city words
            # into the street (e.g. multi-word cities). Keep structured street.
            p_street, p_city, p_state, p_zip = parsed_zip
            if p_street and (
                street_looks_tabular(s) or p_street == s or s.startswith(p_street)
            ):
                return p_street or s, p_city or c, p_state or st, p_zip or z
            return s, c, st, p_zip or z
        return s, c, st, z

    if not s and (c or st or z):
        return s, c, st, z

    parsed = parse_embedded_us_address(s) if s else None
    if not parsed and s and (c or st or z):
        glued = ', '.join(p for p in (s, c, st, z) if p)
        parsed = parse_embedded_us_address(glued)

    if not parsed:
        return s, c, st, z

    p_street, p_city, p_state, p_zip = parsed
    use_street = p_street if (
        street_looks_tabular(s) or not s or s == _clean(street)
        or (not c or not st or not z)
    ) else s
    # When locality already peeled from city column, prefer those over street-parse city.
    return (
        use_street or s,
        c or p_city,
        st or p_state,
        z or p_zip,
    )


def apply_owner_mailing(
    lead: Lead,
    *,
    street: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
    fill_empty_only: bool = True,
    rewrite_street: bool = True,
) -> list[str]:
    """Canonical writer for lead ``mailing_*`` columns.

    When ``fill_empty_only`` is True, only empty (or tabular-street) fields are
    filled — HubSpot / import. When False, normalized parts overwrite
    (OLC Corrected / Apply Parsed / heal).
    """
    cur_street = _clean(getattr(lead, 'mailing_address', None))
    cur_city = _clean(getattr(lead, 'mailing_city', None))
    cur_state = _clean(getattr(lead, 'mailing_state', None))
    cur_zip = _clean(getattr(lead, 'mailing_zip', None))

    in_street = _clean(street) if street is not None else ''
    in_city = _clean(city) if city is not None else ''
    in_state = _clean(state) if state is not None else ''
    in_zip = _clean(zip_code) if zip_code is not None else ''

    if fill_empty_only:
        use_street = cur_street
        if in_street and (not cur_street or street_looks_tabular(cur_street)):
            use_street = in_street
        use_city = cur_city or in_city
        use_state = cur_state or in_state
        use_zip = cur_zip or in_zip
    else:
        use_street = in_street or cur_street
        use_city = in_city or cur_city
        use_state = in_state or cur_state
        use_zip = in_zip or cur_zip

    n_street, n_city, n_state, n_zip = normalize_mailing_parts(
        use_street, use_city, use_state, use_zip,
    )

    updated: list[str] = []

    def _maybe_set(field: str, new_value: str, current: str, *, force: bool = False) -> None:
        if not new_value or new_value == current:
            return
        if fill_empty_only and current and not force:
            return
        setattr(lead, field, new_value)
        updated.append(field)

    street_force = street_looks_tabular(cur_street) and rewrite_street
    if rewrite_street or not cur_street:
        _maybe_set('mailing_address', n_street, cur_street, force=street_force)
    _maybe_set('mailing_city', n_city, cur_city)
    _maybe_set('mailing_state', n_state, cur_state)
    _maybe_set('mailing_zip', n_zip, cur_zip)
    return updated


def normalize_owner_mailing_on_lead(
    lead: Lead,
    *,
    rewrite_street: bool = True,
) -> list[str]:
    """Normalize whatever is already on the lead (heal / post-import)."""
    return apply_owner_mailing(
        lead,
        street=getattr(lead, 'mailing_address', None),
        city=getattr(lead, 'mailing_city', None),
        state=getattr(lead, 'mailing_state', None),
        zip_code=getattr(lead, 'mailing_zip', None),
        fill_empty_only=False,
        rewrite_street=rewrite_street,
    )


def owner_mailing_needs_normalize(lead: Lead) -> bool:
    """True when mailing text exists but structured fields / street need heal."""
    street = _clean(getattr(lead, 'mailing_address', None))
    city = _clean(getattr(lead, 'mailing_city', None))
    state = _clean(getattr(lead, 'mailing_state', None))
    zip_code = _clean(getattr(lead, 'mailing_zip', None))
    if not street and not city:
        return False
    if street_looks_tabular(street) or (city and ',' in city):
        return True
    if street and city and state and zip_code:
        if re.fullmatch(r'\d{3,4}', zip_code):
            return True
        return False
    n_street, n_city, n_state, n_zip = normalize_mailing_parts(
        street, city, state, zip_code,
    )
    return bool(n_street and n_city and n_state and n_zip) and (
        (n_street, n_city, n_state, n_zip) != (street, city, state, zip_code)
    )


def owner_mailing_readiness_detail(lead: Lead) -> dict[str, Any]:
    """Payload for command-center mail readiness UI."""
    raw_street = _clean(getattr(lead, 'mailing_address', None))
    raw_city = _clean(getattr(lead, 'mailing_city', None))
    raw_state = _clean(getattr(lead, 'mailing_state', None))
    raw_zip = _clean(getattr(lead, 'mailing_zip', None))
    reason = validate_owner_mailing_address(lead)
    mailable = reason is None
    # Prefer normalize (peels city-column locality + tabs) over read-only merge.
    n_street, n_city, n_state, n_zip = normalize_mailing_parts(
        raw_street, raw_city, raw_state, raw_zip,
    )
    if not (n_street and n_city and n_state and n_zip):
        p_street, p_city, p_state, p_zip = owner_mailing_address(lead)
    else:
        p_street, p_city, p_state, p_zip = n_street, n_city, n_state, n_zip
    parsed_complete = bool(p_street and p_city and p_state and p_zip)
    stored_complete = (
        bool(raw_street and raw_city and raw_state and raw_zip)
        and not street_looks_tabular(raw_street)
        and ',' not in raw_city
    )
    can_apply = (
        parsed_complete
        and (
            not stored_complete
            or street_looks_tabular(raw_street)
            or (raw_street, raw_city, raw_state, raw_zip)
            != (p_street, p_city, p_state, p_zip)
        )
        and (
            not mailable
            or street_looks_tabular(raw_street)
            or ',' in raw_city
            or (raw_street, raw_city, raw_state, raw_zip)
            != (p_street, p_city, p_state, p_zip)
        )
    )
    return {
        'is_mailable': mailable,
        'reason': reason,
        'raw': {
            'street': raw_street or None,
            'city': raw_city or None,
            'state': raw_state or None,
            'zip': raw_zip or None,
        },
        'parsed': (
            {
                'street': p_street,
                'city': p_city,
                'state': p_state,
                'zip': p_zip,
            }
            if parsed_complete
            else None
        ),
        'can_apply_parsed': can_apply,
    }


def apply_parsed_owner_mailing(lead: Lead) -> dict[str, Any]:
    """Persist the in-memory parsed owner mailing onto structured columns."""
    detail_before = owner_mailing_readiness_detail(lead)
    if not detail_before['can_apply_parsed'] or not detail_before['parsed']:
        return {
            'applied': False,
            'updated_fields': [],
            'detail': detail_before,
        }
    parsed = detail_before['parsed']
    updated = apply_owner_mailing(
        lead,
        street=parsed['street'],
        city=parsed['city'],
        state=parsed['state'],
        zip_code=parsed['zip'],
        fill_empty_only=False,
        rewrite_street=True,
    )
    detail_after = owner_mailing_readiness_detail(lead)
    return {
        'applied': bool(updated),
        'updated_fields': updated,
        'detail': detail_after,
        'is_mailable': is_owner_mailable_lead(lead),
    }


def _incomplete_or_tabular_mailing_clause():
    """SQLAlchemy filter: has mailing street and (incomplete / tabular / dirty city)."""
    street = Lead.mailing_address
    city = Lead.mailing_city
    return and_(
        street.isnot(None),
        street != '',
        or_(
            street.contains('\t'),
            city.is_(None),
            city == '',
            city.contains(','),  # e.g. "Chicago, IL 60647" dumped into city
            Lead.mailing_state.is_(None),
            Lead.mailing_state == '',
            Lead.mailing_zip.is_(None),
            Lead.mailing_zip == '',
        ),
    )


_mailing_heal_count_cache: tuple[float, int] | None = None
_MAILING_HEAL_COUNT_TTL_SEC = 60.0


def count_owner_mailing_heal_candidates(*, use_cache: bool = True) -> int:
    """Count leads that look like the heal target set (cheap SQL, not parse).

    Health probes pass the default ``use_cache=True`` so repeated /api/health
    hits do not re-COUNT the full table every few seconds.
    """
    global _mailing_heal_count_cache
    import time

    if use_cache and _mailing_heal_count_cache is not None:
        cached_at, cached_n = _mailing_heal_count_cache
        if time.monotonic() - cached_at < _MAILING_HEAL_COUNT_TTL_SEC:
            return cached_n

    n = (
        Lead.query
        .filter(_incomplete_or_tabular_mailing_clause())
        .count()
    )
    _mailing_heal_count_cache = (time.monotonic(), n)
    return n


def _heal_cursor() -> int:
    from app.services.deploy_sync_policy import get_redis_value

    raw = get_redis_value(HEAL_OWNER_MAILING_CURSOR_KEY)
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _set_heal_cursor(last_id: int) -> None:
    from app.services.deploy_sync_policy import set_redis_value

    set_redis_value(HEAL_OWNER_MAILING_CURSOR_KEY, str(max(0, int(last_id))))


def heal_incomplete_owner_mailings(
    *,
    last_id: int | None = None,
    limit: int = HEAL_OWNER_MAILING_BATCH_SIZE,
    persist_cursor: bool = True,
    commit: bool = True,
    lead_id: int | None = None,
    dry_run: bool = False,
    actor: str = 'owner_mailing_heal',
) -> dict[str, Any]:
    """Batch-normalize incomplete / tabular owner mailing addresses."""
    batch_limit = max(int(limit), 0)
    cursor = 0 if lead_id is not None else (
        _heal_cursor() if last_id is None else max(0, int(last_id))
    )
    summary: dict[str, Any] = {
        'status': 'completed',
        'processed': 0,
        'healed': 0,
        'unchanged': 0,
        'still_blocked': 0,
        'errors': 0,
        'last_id': cursor,
        'wrapped': False,
        'dry_run': bool(dry_run),
        'actor': actor,
        'lead_ids': [],
        'previews': [],
        'candidates_remaining': None,
    }
    if batch_limit == 0 and lead_id is None:
        return summary

    if lead_id is not None:
        leads = (
            Lead.query
            .filter(_incomplete_or_tabular_mailing_clause(), Lead.id == lead_id)
            .limit(1)
            .all()
        )
    else:
        leads = (
            Lead.query
            .filter(_incomplete_or_tabular_mailing_clause(), Lead.id > cursor)
            .order_by(Lead.id.asc())
            .limit(batch_limit)
            .all()
        )
        if not leads and cursor > 0:
            cursor = 0
            summary['wrapped'] = True
            leads = (
                Lead.query
                .filter(_incomplete_or_tabular_mailing_clause(), Lead.id > cursor)
                .order_by(Lead.id.asc())
                .limit(batch_limit)
                .all()
            )

    advanced_cursor = cursor
    for lead in leads:
        summary['processed'] += 1
        summary['lead_ids'].append(lead.id)
        before = {
            'mailing_address': lead.mailing_address,
            'mailing_city': lead.mailing_city,
            'mailing_state': lead.mailing_state,
            'mailing_zip': lead.mailing_zip,
        }
        try:
            if not owner_mailing_needs_normalize(lead):
                summary['unchanged'] += 1
                if lead_id is None:
                    advanced_cursor = lead.id
                continue
            if dry_run:
                n_street, n_city, n_state, n_zip = normalize_mailing_parts(
                    lead.mailing_address,
                    lead.mailing_city,
                    lead.mailing_state,
                    lead.mailing_zip,
                )
                summary['previews'].append({
                    'lead_id': lead.id,
                    'before': before,
                    'after': {
                        'mailing_address': n_street,
                        'mailing_city': n_city,
                        'mailing_state': n_state,
                        'mailing_zip': n_zip,
                    },
                })
                if n_city and n_state and n_zip and n_street and not street_looks_tabular(n_street):
                    summary['healed'] += 1
                else:
                    summary['still_blocked'] += 1
                if lead_id is None:
                    advanced_cursor = lead.id
                continue

            with db.session.begin_nested():
                updated = normalize_owner_mailing_on_lead(lead, rewrite_street=True)
            if updated and is_owner_mailable_lead(lead):
                summary['healed'] += 1
            elif updated:
                summary['still_blocked'] += 1
            else:
                summary['unchanged'] += 1
            if lead_id is None:
                advanced_cursor = lead.id
        except Exception:
            logger.exception('%s failed for lead_id=%s', actor, lead.id)
            summary['errors'] += 1
            # Leave cursor so Beat retries this id; do not wipe prior savepoints.
            break

    summary['last_id'] = advanced_cursor
    if persist_cursor and lead_id is None and not dry_run:
        _set_heal_cursor(advanced_cursor)
    if commit and not dry_run:
        db.session.commit()
    elif dry_run:
        db.session.rollback()

    try:
        summary['candidates_remaining'] = count_owner_mailing_heal_candidates()
    except Exception:
        summary['candidates_remaining'] = None
    return summary
