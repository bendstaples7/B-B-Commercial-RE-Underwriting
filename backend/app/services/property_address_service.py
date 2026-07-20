"""Canonical property address completeness (street + city + state + ZIP).

Single writer for completing ``Lead.property_*`` location fields. Reuses
address parsers and Cook County street-only GIS lookup when city/state are blank.
"""
from __future__ import annotations

import logging
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

HEAL_INCOMPLETE_BATCH_SIZE = 200
HEAL_INCOMPLETE_CURSOR_KEY = 'property_address:heal_incomplete:last_id'
HEAL_INCOMPLETE_LOCK_KEY = 'property_address:heal_incomplete_lock'

_ZIP_RE = re.compile(r'^\d{5}(?:-\d{4})?$')


def _clean(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


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


def complete_property_address_fields(
    street: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
    *,
    try_gis: bool = True,
) -> dict[str, Any]:
    """Return completed property address components (pure helper for payloads).

    Does not touch the database. GIS fill uses Cook County street lookup when
    city/state/zip are still missing after parsing.
    """
    street_out = _clean(street)
    city_out = _clean(city)
    state_out = _clean(state)
    zip_out = _clean(zip_code)
    sources: list[str] = []

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
            if gis_fill.get('property_street') and _should_replace_street(
                street_out, gis_fill['property_street'],
            ):
                street_out = gis_fill['property_street']
                sources.append('gis_street')
            if not city_out and gis_fill.get('property_city'):
                city_out = gis_fill['property_city']
                sources.append('gis')
            if not state_out and gis_fill.get('property_state'):
                state_out = gis_fill['property_state']
                sources.append('gis')
            if not zip_out and gis_fill.get('property_zip'):
                zip_out = _zip5(gis_fill['property_zip']) or zip_out
                sources.append('gis')

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
    actor: str = 'property_address_completer',
    commit: bool = False,
    write_timeline: bool = True,
    set_review_flag: bool = True,
) -> dict[str, Any]:
    """Fill missing property city/state/ZIP on *lead*; flag if still incomplete.

    Pass ``set_review_flag=False`` (with ``write_timeline=False``) for preview
    paths that must not persist ``review_required``.
    """
    was_complete = is_property_address_complete(lead=lead)
    before = {
        'property_street': lead.property_street,
        'property_city': lead.property_city,
        'property_state': lead.property_state,
        'property_zip': lead.property_zip,
        'review_required': bool(getattr(lead, 'review_required', False)),
    }

    result = complete_property_address_fields(
        lead.property_street,
        lead.property_city,
        lead.property_state,
        lead.property_zip,
        try_gis=try_gis,
    )

    changed_fields: list[str] = []
    for field in (
        'property_street',
        'property_city',
        'property_state',
        'property_zip',
    ):
        new_val = result.get(field)
        old_val = getattr(lead, field, None)
        if new_val and _clean(new_val) != _clean(old_val):
            # Never blank out an existing structured field.
            if not _clean(old_val) or field == 'property_street':
                if field == 'property_street' and _clean(old_val):
                    if not _should_replace_street(_clean(old_val), _clean(new_val)):
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
        lead.property_city = city
        changed.append('property_city')
    if state and not _clean(lead.property_state):
        lead.property_state = state
        changed.append('property_state')
    if zip_code and not _clean(lead.property_zip):
        lead.property_zip = zip_code
        changed.append('property_zip')
    if (
        replace_street
        and street
        and _should_replace_street(_clean(lead.property_street), street)
    ):
        lead.property_street = street
        changed.append('property_street')
    return changed


def ensure_lead_property_address_complete(
    lead: Lead,
    *,
    actor: str,
    try_gis: bool = True,
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
        actor=actor,
        commit=commit,
        write_timeline=write_timeline,
        set_review_flag=set_review_flag,
    )


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
    not touch the cursor.
    """
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
        'last_id': cursor,
        'wrapped': False,
        'dry_run': bool(dry_run),
        'lead_ids': [],
        'previews': [],
    }
    if batch_limit == 0 and lead_id is None:
        return summary

    if lead_id is not None:
        leads = (
            Lead.query
            .filter(_incomplete_property_address_clause(), Lead.id == lead_id)
            .limit(1)
            .all()
        )
    else:
        leads = (
            Lead.query
            .filter(_incomplete_property_address_clause(), Lead.id > cursor)
            .order_by(Lead.id.asc())
            .limit(batch_limit)
            .all()
        )
        if not leads and cursor > 0:
            cursor = 0
            summary['wrapped'] = True
            leads = (
                Lead.query
                .filter(_incomplete_property_address_clause(), Lead.id > cursor)
                .order_by(Lead.id.asc())
                .limit(batch_limit)
                .all()
            )

    completed_ids: list[int] = []
    # Advance past attempted leads only; hard errors leave the cursor so Beat
    # retries them on the next pass instead of burning the backlog once.
    advanced_cursor = cursor
    for lead in leads:
        summary['processed'] += 1
        summary['lead_ids'].append(lead.id)
        try:
            if dry_run:
                result = complete_property_address_fields(
                    lead.property_street,
                    lead.property_city,
                    lead.property_state,
                    lead.property_zip,
                    try_gis=try_gis,
                )
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
                })
                if result.get('complete'):
                    summary['completed'] += 1
                else:
                    summary['still_incomplete'] += 1
                if lead_id is None:
                    advanced_cursor = lead.id
                continue

            with db.session.begin_nested():
                result = complete_property_address(
                    lead,
                    try_gis=try_gis,
                    actor=actor,
                    commit=False,
                )
            if result.get('complete'):
                summary['completed'] += 1
                completed_ids.append(lead.id)
            else:
                summary['still_incomplete'] += 1
            if lead_id is None:
                advanced_cursor = lead.id
        except Exception as exc:
            summary['errors'] += 1
            logger.warning(
                'property address heal failed for lead %s: %s',
                lead.id,
                exc,
            )
            break

    if commit and not dry_run and leads:
        db.session.commit()
        for completed_lead_id in completed_ids:
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

    return summary


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
    """Cook County street-only lookup (no city routing required)."""
    try:
        from app.services.gis.cook_county_gis_connector import (
            CookCountyGISConnector,
            lookup_all_pins_at_address,
        )
        rows = lookup_all_pins_at_address(street)
        if not rows:
            connector = CookCountyGISConnector()
            parcel = connector.lookup_by_address(street)
            if parcel is None or not parcel.county_assessor_pin:
                return None
            addr = connector.lookup_address_by_pin(parcel.county_assessor_pin)
            if not addr:
                return None
            return {
                'property_street': _clean(addr.get('property_street')),
                'property_city': _clean(addr.get('property_city')),
                'property_state': _clean(addr.get('property_state')) or 'IL',
                'property_zip': _zip5(addr.get('property_zip')) or '',
            }
        # Prefer Chicago row when multiple
        chicago = [
            r for r in rows
            if _clean(r.get('property_city')).upper() == 'CHICAGO'
        ]
        row = chicago[0] if chicago else rows[0]
        return {
            'property_street': _clean(row.get('property_street')),
            'property_city': _clean(row.get('property_city')),
            'property_state': _clean(row.get('property_state')) or 'IL',
            'property_zip': _zip5(row.get('property_zip')) or '',
        }
    except Exception as exc:
        logger.warning('GIS street fill failed for %r: %s', street, exc)
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
