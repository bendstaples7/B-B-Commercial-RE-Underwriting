"""Property match review — preview, approve, and reject GIS matches for leads."""
from __future__ import annotations

import datetime as dt
import logging
import re

from app import db
from app.models import Lead, LeadTimelineEntry
from app.services.gis.base import GISParcel
from app.services.gis.routing import connector_for_lead
from app.services.lead_ingestion_service import LeadIngestionService
from app.services.lead_refresh import refresh_lead_scoring
from app.services.lead_status_service import apply_lead_status_change

logger = logging.getLogger(__name__)

RESOLVE_UNAMBIGUOUS_PINS_LOCK_KEY = 'property_match:resolve_unambiguous_pins_lock'
RESOLVE_UNAMBIGUOUS_PINS_CURSOR_KEY = 'property_match:resolve_unambiguous_pins_cursor'

_SUFFIX_CANON = {
    'AVENUE': 'AVE', 'AVE': 'AVE', 'BOULEVARD': 'BLVD', 'BLVD': 'BLVD',
    'CIRCLE': 'CIR', 'CIR': 'CIR', 'COURT': 'CT', 'CT': 'CT',
    'DRIVE': 'DR', 'DR': 'DR', 'LANE': 'LN', 'LN': 'LN',
    'PLACE': 'PL', 'PL': 'PL', 'ROAD': 'RD', 'RD': 'RD',
    'STREET': 'ST', 'ST': 'ST', 'TERRACE': 'TER', 'TER': 'TER',
    'PARKWAY': 'PKWY', 'PKWY': 'PKWY', 'HIGHWAY': 'HWY', 'HWY': 'HWY',
    'WAY': 'WAY', 'SQUARE': 'SQ', 'SQ': 'SQ', 'TRAIL': 'TRL', 'TRL': 'TRL',
}

_DIRECTION_CANON = {
    'N': 'N', 'NORTH': 'N', 'S': 'S', 'SOUTH': 'S',
    'E': 'E', 'EAST': 'E', 'W': 'W', 'WEST': 'W',
    'NE': 'NE', 'NORTHEAST': 'NE', 'NW': 'NW', 'NORTHWEST': 'NW',
    'SE': 'SE', 'SOUTHEAST': 'SE', 'SW': 'SW', 'SOUTHWEST': 'SW',
}


def _normalize_street_compare(street: str | None) -> str:
    """Uppercase, collapse spaces, canonicalize directions + street suffixes."""
    if street is None or not isinstance(street, str):
        return ''
    text = street.split(',')[0].strip().upper()
    text = re.sub(r'[^\w\s\-]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    tokens = []
    for tok in text.split():
        tokens.append(_DIRECTION_CANON.get(tok, _SUFFIX_CANON.get(tok, tok)))
    return ' '.join(tokens)


def street_name_key(street: str | None) -> str:
    """Street name without house number (for same-situs clustering)."""
    normalized = _normalize_street_compare(street)
    if not normalized:
        return ''
    m = re.match(r'^(\d+)(?:-(\d+))?\s+(.+)$', normalized)
    if m:
        return m.group(3)
    return normalized


def assessor_street_differs_from_lead(
    lead_street: str | None,
    assessor_street: str | None,
) -> bool:
    """True when assessor situs is a meaningfully different street (set AKA).

    Range vs single house on the same street name/suffix is treated as the same
    (e.g. ``3715-3721 N LEAVITT ST`` vs ``3715 N LEAVITT ST``).
    """
    lead_n = _normalize_street_compare(lead_street)
    assessor_n = _normalize_street_compare(assessor_street)
    if not lead_n or not assessor_n:
        return False
    if lead_n == assessor_n:
        return False

    lead_m = re.match(r'^(\d+)(?:-(\d+))?\s+(.+)$', lead_n)
    assessor_m = re.match(r'^(\d+)(?:-(\d+))?\s+(.+)$', assessor_n)
    if lead_m and assessor_m and lead_m.group(3) == assessor_m.group(3):
        a0 = int(assessor_m.group(1))
        a1 = int(assessor_m.group(2) or assessor_m.group(1))
        l0 = int(lead_m.group(1))
        l1 = int(lead_m.group(2) or lead_m.group(1))
        lo, hi = (l0, l1) if l0 <= l1 else (l1, l0)
        # Overlap or containment of house numbers on the same street → same situs.
        if not (a1 < lo or a0 > hi):
            return False
    return True


def _candidate_from_row(row: dict) -> dict:
    return {
        'pin': (row.get('pin') or '').strip() or None,
        'property_street': (row.get('property_street') or '').strip() or None,
        'property_city': (row.get('property_city') or '').strip() or None,
        'property_state': (row.get('property_state') or '').strip() or None,
        'property_zip': (row.get('property_zip') or '').strip() or None,
        'source': row.get('source'),
    }


def _street_name_key(street: str | None) -> str:
    """Normalize to direction + name + suffix (ignore house number / unit)."""
    norm = _normalize_street_compare(street)
    if not norm:
        return ''
    return re.sub(r'^\d+(?:-\d+)?\s+', '', norm).strip()


def tax_situs_cluster_meta(
    lead_street: str | None,
    candidates: list[dict],
) -> dict:
    """Dominant assessor street-name among candidates when it differs from lead street."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for row in candidates or []:
        street = (row.get('property_street') or '').strip()
        if not street:
            continue
        key = _street_name_key(street)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
        # Prefer the first (usually closest) full street as display.
        display.setdefault(key, street)
    if not counts:
        return {
            'tax_situs_street': None,
            'tax_situs_pin_count': 0,
            'assessor_aka': None,
        }
    dominant_key = max(counts.keys(), key=lambda k: (counts[k], -len(k)))
    dominant_street = display[dominant_key]
    pin_count = counts[dominant_key]
    differs = assessor_street_differs_from_lead(lead_street, dominant_street)
    aka = None
    if differs:
        aka = {'property_street': dominant_street}
    return {
        'tax_situs_street': dominant_street if differs else None,
        'tax_situs_pin_count': pin_count if differs else 0,
        'assessor_aka': aka,
    }


def _apply_assessor_aka(lead: Lead, addr_row: dict | None) -> None:
    """Keep marketing street; store assessor situs as AKA when it differs."""
    if not isinstance(addr_row, dict):
        return
    raw_street = addr_row.get('property_street')
    assessor_street = raw_street.strip() if isinstance(raw_street, str) else None
    if not assessor_street:
        return
    if not assessor_street_differs_from_lead(lead.property_street, assessor_street):
        # Clear stale AKA when assessor matches marketing street.
        lead.assessor_aka_street = None
        lead.assessor_aka_city = None
        lead.assessor_aka_state = None
        lead.assessor_aka_zip = None
        return

    from app.services.property_address_service import (
        _clean,
        _state_code,
        _zip5,
        title_case_address_part,
    )

    lead.assessor_aka_street = title_case_address_part(assessor_street)
    city = _clean(addr_row.get('property_city'))
    state = _clean(addr_row.get('property_state'))
    zip_code = _zip5(addr_row.get('property_zip'))
    lead_city = _clean(lead.property_city)
    # Store locality only when it differs from the lead (or lead locality empty).
    if city and (not lead_city or city.upper() != lead_city.upper()):
        lead.assessor_aka_city = title_case_address_part(city)
    else:
        lead.assessor_aka_city = None
    if state:
        code = _state_code(state) or state.upper()[:2]
        if not _clean(lead.property_state) or code != (_clean(lead.property_state) or '').upper():
            lead.assessor_aka_state = code
        else:
            lead.assessor_aka_state = None
    else:
        lead.assessor_aka_state = None
    if zip_code and zip_code != (_zip5(lead.property_zip) or ''):
        lead.assessor_aka_zip = zip_code
    else:
        lead.assessor_aka_zip = None


def _resolve_pins_cursor() -> int:
    from app.services.deploy_sync_policy import get_redis_value

    raw = get_redis_value(RESOLVE_UNAMBIGUOUS_PINS_CURSOR_KEY)
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _set_resolve_pins_cursor(last_id: int) -> None:
    from app.services.deploy_sync_policy import set_redis_value

    set_redis_value(RESOLVE_UNAMBIGUOUS_PINS_CURSOR_KEY, str(max(0, int(last_id))))


class PropertyMatchReviewService:
    """GIS match preview and confirmation for missing-property-match queue."""

    def _ingestion_service(self) -> LeadIngestionService:
        from app.services.deduplication_engine import DeduplicationEngine
        from app.services.gis.base import GISConnectorRegistry
        return LeadIngestionService(
            dedup_engine=DeduplicationEngine(),
            gis_registry=GISConnectorRegistry,
        )

    @staticmethod
    def _cook_pin_rows_at_address(address: str) -> list[dict]:
        """Return distinct Cook County PIN rows for a situs address."""
        from app.services.gis.cook_county_gis_connector import lookup_all_pins_at_address

        rows_out: list[dict] = []
        seen: set[str] = set()
        for row in lookup_all_pins_at_address(address):
            pin = str((row or {}).get('pin') or '').strip()
            if pin and pin not in seen:
                seen.add(pin)
                rows_out.append(_candidate_from_row({**(row or {}), 'source': 'cook_address'}))
        return rows_out

    @staticmethod
    def _cook_pins_at_address(address: str) -> list[str]:
        """Return distinct Cook County PINs reported for a situs address."""
        return [
            row['pin']
            for row in PropertyMatchReviewService._cook_pin_rows_at_address(address)
            if row.get('pin')
        ]

    def preview_match(self, lead_id: int, pin: str | None = None) -> dict:
        from app.services.property_address_service import (
            complete_property_address,
            is_property_address_complete,
        )

        lead = db.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f'Lead {lead_id} not found')

        # Parse-only soft-heal (no GIS / no review flag) so preview stays side-effect-free.
        if lead.property_street and not is_property_address_complete(lead=lead):
            complete_property_address(
                lead,
                try_gis=False,
                actor='property_match_preview',
                commit=False,
                write_timeline=False,
                set_review_flag=False,
            )
            lead = db.session.get(Lead, lead_id)

        entered = {
            'property_street': lead.property_street,
            'property_city': lead.property_city,
            'property_state': lead.property_state,
            'property_zip': lead.property_zip,
        }
        address_complete = is_property_address_complete(lead=lead)
        if not address_complete and not (pin or '').strip():
            return {
                'found': False,
                'entered_address': entered,
                'recommended_address': None,
                'pin': None,
                'connector': None,
                'address_complete': False,
                'reason': 'incomplete_address',
                'message': 'Add city, state, and ZIP before looking up a PIN',
            }

        connector = connector_for_lead(lead)
        parcel: GISParcel | None = None
        connector_name = connector.connector_name if connector else None
        is_cook = getattr(connector, 'market', None) == 'cook_county_il'
        pin_hint = (pin or '').strip() or None

        # PIN-first verify: resolve situs from pasted PIN without requiring ladder hit.
        if pin_hint and is_cook and connector is not None:
            from app.services.plugins.pin_utils import (
                format_pin_for_storage,
                normalize_pin_for_socrata,
            )
            digits = normalize_pin_for_socrata(pin_hint)
            if len(digits) != 14 or not digits.isdigit():
                return {
                    'found': False,
                    'entered_address': entered,
                    'recommended_address': None,
                    'pin': None,
                    'candidates': [],
                    'connector': connector_name,
                    'address_complete': address_complete,
                    'reason': 'invalid_pin',
                    'message': 'Invalid Cook County PIN',
                }
            formatted = format_pin_for_storage(digits)
            addr_row = None
            if hasattr(connector, 'lookup_address_by_pin'):
                addr_row = connector.lookup_address_by_pin(formatted)
            parcel = connector.lookup_by_pin(formatted)
            assessor_street = (
                (addr_row or {}).get('property_street')
                or getattr(parcel, 'property_street', None)
            )
            if not assessor_street and parcel is None:
                return {
                    'found': False,
                    'entered_address': entered,
                    'recommended_address': None,
                    'pin': formatted,
                    'candidates': [],
                    'connector': connector_name,
                    'address_complete': address_complete,
                    'reason': 'no_match',
                    'message': 'No assessor match for that PIN',
                }
            differs = assessor_street_differs_from_lead(
                lead.property_street, assessor_street,
            )
            candidate = {
                'pin': formatted,
                'property_street': assessor_street,
                'property_city': (addr_row or {}).get('property_city')
                    or getattr(parcel, 'property_city', None),
                'property_state': (addr_row or {}).get('property_state')
                    or getattr(parcel, 'property_state', None)
                    or 'IL',
                'property_zip': (addr_row or {}).get('property_zip')
                    or getattr(parcel, 'property_zip', None),
                'source': 'pin_verify',
            }
            recommended = {
                'property_street': lead.property_street if differs else (
                    assessor_street or lead.property_street
                ),
                'property_city': lead.property_city or candidate['property_city'],
                'property_state': lead.property_state or candidate['property_state'],
                'property_zip': lead.property_zip or candidate['property_zip'],
                'property_type': getattr(parcel, 'property_type', None),
                'county_assessor_pin': formatted,
            }
            aka = None
            if differs and assessor_street:
                aka = {
                    'property_street': assessor_street,
                    'property_city': candidate['property_city'],
                    'property_state': candidate['property_state'],
                    'property_zip': candidate['property_zip'],
                }
            return {
                'found': True,
                'entered_address': entered,
                'recommended_address': recommended,
                'pin': formatted,
                'pins': [formatted],
                'pin_count': 1,
                'candidates': [candidate],
                'assessor_aka': aka,
                'require_explicit_apply': bool(differs),
                'connector': connector_name,
                'address_complete': address_complete,
                'reason': None,
                'parcel_fields': None,
                'message': (
                    'Assessor situs differs from lead street — apply to confirm'
                    if differs else None
                ),
            }

        cook_rows = self._cook_pin_rows_at_address(lead.property_street) if (
            is_cook and lead.property_street
        ) else []
        aka_street = (getattr(lead, 'assessor_aka_street', None) or '').strip()
        # When marketing street misses (corner lots), try stored assessor AKA —
        # Socrata is more reliable than the flaky MapServer spatial path.
        if is_cook and not cook_rows and aka_street:
            cook_rows = self._cook_pin_rows_at_address(aka_street)

        # Enrich thin AKA/marketing hits via spatial around the best known situs.
        need_spatial = is_cook and lead.property_street and (
            len(cook_rows) == 0 or (aka_street and len(cook_rows) < 3)
        )
        if need_spatial:
            try:
                from app.services.gis.cook_county_parcel_spatial import (
                    lookup_nearby_parcel_candidates,
                )
                seen = {r['pin'] for r in cook_rows if r.get('pin')}
                for probe in (aka_street, lead.property_street):
                    if not (probe or '').strip():
                        continue
                    spatial_rows = lookup_nearby_parcel_candidates(
                        probe,
                        city=lead.property_city,
                        state=lead.property_state,
                        zip_code=lead.property_zip,
                        limit=8,
                    )
                    for r in spatial_rows:
                        cand = _candidate_from_row(r)
                        pin = cand.get('pin')
                        if pin and pin not in seen:
                            seen.add(pin)
                            cook_rows.append(cand)
                    if len(cook_rows) >= 3:
                        break
            except Exception:
                logger.exception('Cook spatial PIN fallback failed for lead %s', lead_id)

        cook_pins = [r['pin'] for r in cook_rows if r.get('pin')]
        pin_count = len(cook_pins) if is_cook else None

        if is_cook and pin_count and pin_count >= 1:
            # Prefer multi-candidate / AKA framing when tax situs differs.
            candidates = cook_rows[:5]
            situs = tax_situs_cluster_meta(lead.property_street, candidates)
            differs = bool(situs.get('tax_situs_street')) or (
                pin_count == 1 and assessor_street_differs_from_lead(
                    lead.property_street, candidates[0].get('property_street'),
                )
            )
            if pin_count >= 2 or differs:
                aka = situs.get('assessor_aka')
                if not aka and candidates[0].get('property_street'):
                    if assessor_street_differs_from_lead(
                        lead.property_street, candidates[0].get('property_street'),
                    ):
                        aka = {'property_street': candidates[0].get('property_street')}
                return {
                    'found': True,
                    'entered_address': entered,
                    'recommended_address': (
                        None if pin_count >= 2 else {
                            'property_street': lead.property_street,
                            'property_city': lead.property_city,
                            'property_state': lead.property_state,
                            'property_zip': lead.property_zip,
                            'property_type': None,
                            'county_assessor_pin': cook_pins[0],
                        }
                    ),
                    'pin': None if pin_count >= 2 else cook_pins[0],
                    'pins': cook_pins,
                    'pin_count': pin_count,
                    'candidates': candidates,
                    'tax_situs_street': (
                        situs.get('tax_situs_street')
                        or (aka or {}).get('property_street')
                    ),
                    'tax_situs_pin_count': (
                        situs.get('tax_situs_pin_count')
                        if situs.get('tax_situs_street')
                        else 0
                    ),
                    'assessor_aka': aka,
                    'require_explicit_apply': True,
                    'connector': connector_name,
                    'address_complete': address_complete,
                    'reason': None,
                    'parcel_fields': None,
                    'message': (
                        'Nearby parcel candidates found; review and apply the match.'
                        if situs.get('tax_situs_street') or differs
                        else 'Multiple assessor PINs found; review and apply the property match.'
                    ),
                }
            # Unique same-street PIN — FE may auto-apply.
            return {
                'found': True,
                'entered_address': entered,
                'recommended_address': {
                    'property_street': lead.property_street,
                    'property_city': lead.property_city,
                    'property_state': lead.property_state,
                    'property_zip': lead.property_zip,
                    'property_type': None,
                    'county_assessor_pin': cook_pins[0],
                },
                'pin': cook_pins[0],
                'pins': cook_pins,
                'pin_count': 1,
                'candidates': candidates,
                'require_explicit_apply': False,
                'connector': connector_name,
                'address_complete': address_complete,
                'reason': None,
                'parcel_fields': None,
                'message': None,
            }
        if connector is not None:
            if lead.property_street:
                parcel = connector.lookup_by_address(lead.property_street)
            if parcel is None and lead.county_assessor_pin:
                parcel = connector.lookup_by_pin(lead.county_assessor_pin)
        # No Cook street-only fallback on preview — incomplete situs already returned
        # above; out-of-market leads must not attach a Cook parcel.

        if connector is None and parcel is None:
            return {
                'found': False,
                'entered_address': entered,
                'recommended_address': None,
                'pin': None,
                'pin_count': pin_count,
                'candidates': [],
                'connector': None,
                'address_complete': address_complete,
                'reason': 'no_connector',
                'message': 'No GIS connector for this lead\'s county',
            }

        if parcel is None:
            return {
                'found': False,
                'entered_address': entered,
                'recommended_address': None,
                'pin': None,
                'pin_count': pin_count,
                'candidates': [],
                'connector': connector_name,
                'address_complete': address_complete,
                'reason': 'no_match',
                'message': 'No assessor match found',
            }

        addr_row = None
        if hasattr(connector, 'lookup_address_by_pin') and parcel.county_assessor_pin:
            addr_row = connector.lookup_address_by_pin(parcel.county_assessor_pin)

        recommended = {
            'property_street': (addr_row or {}).get('property_street') or lead.property_street,
            'property_city': (
                (addr_row or {}).get('property_city')
                or getattr(parcel, 'property_city', None)
                or lead.property_city
            ),
            'property_state': (
                (addr_row or {}).get('property_state')
                or getattr(parcel, 'property_state', None)
                or lead.property_state
                or 'IL'
            ),
            'property_zip': (
                (addr_row or {}).get('property_zip')
                or getattr(parcel, 'property_zip', None)
                or lead.property_zip
            ),
            'property_type': parcel.property_type,
            'county_assessor_pin': parcel.county_assessor_pin,
        }
        differs = assessor_street_differs_from_lead(
            lead.property_street,
            recommended.get('property_street'),
        )
        if differs:
            # Keep marketing street in recommended; surface assessor as AKA.
            recommended['property_street'] = lead.property_street
        aka = None
        if differs and (addr_row or {}).get('property_street'):
            aka = {
                'property_street': (addr_row or {}).get('property_street'),
                'property_city': (addr_row or {}).get('property_city'),
                'property_state': (addr_row or {}).get('property_state'),
                'property_zip': (addr_row or {}).get('property_zip'),
            }

        return {
            'found': True,
            'entered_address': entered,
            'recommended_address': recommended,
            'pin': parcel.county_assessor_pin,
            'pin_count': pin_count,
            'candidates': [{
                'pin': parcel.county_assessor_pin,
                'property_street': (addr_row or {}).get('property_street'),
                'property_city': recommended['property_city'],
                'property_state': recommended['property_state'],
                'property_zip': recommended['property_zip'],
                'source': 'connector',
            }],
            'assessor_aka': aka,
            'require_explicit_apply': bool(differs),
            'connector': connector_name,
            'address_complete': address_complete,
            'reason': None,
            'parcel_fields': {
                'property_type': parcel.property_type,
                'year_built': parcel.year_built,
                'square_footage': parcel.square_footage,
                'bedrooms': parcel.bedrooms,
                'bathrooms': parcel.bathrooms,
            },
            'message': None,
        }

    def resolve_unambiguous_pins_batch(
        self,
        *,
        limit: int = 100,
        dry_run: bool = False,
        actor: str = 'property_match.resolve_unambiguous_pins',
        last_id: int | None = None,
        persist_cursor: bool = True,
    ) -> dict:
        """Persist only Cook County PINs with exactly one address-level result.

        Scans PIN-empty leads in ascending id order from an exclusive cursor
        (``last_id`` > cursor), so unresolvable head rows (non-Cook, incomplete,
        ambiguous, no-match) do not monopolize the window every run. The cursor
        advances past every scanned id and wraps to 0 when a pass ends, so the
        job eventually reaches eligible Cook leads further down the table.
        """
        from sqlalchemy import or_
        from app.services.property_address_service import is_property_address_complete

        batch_size = max(1, int(limit))
        cursor = _resolve_pins_cursor() if last_id is None else max(0, int(last_id))

        candidates = (
            Lead.query
            .filter(
                or_(
                    Lead.county_assessor_pin.is_(None),
                    db.func.trim(Lead.county_assessor_pin) == '',
                ),
                Lead.id > cursor,
            )
            .order_by(Lead.id.asc())
            .limit(batch_size)
            .all()
        )
        # Empty window past a non-zero cursor means we reached the end — wrap so
        # the next run re-scans from the top (picking up newly-eligible rows).
        if not candidates and cursor > 0:
            if persist_cursor and not dry_run:
                _set_resolve_pins_cursor(0)
            candidates = (
                Lead.query
                .filter(
                    or_(
                        Lead.county_assessor_pin.is_(None),
                        db.func.trim(Lead.county_assessor_pin) == '',
                    ),
                )
                .order_by(Lead.id.asc())
                .limit(batch_size)
                .all()
            )
            cursor = 0
        result = {
            'processed': 0,
            'resolved': 0,
            'skipped_incomplete': 0,
            'skipped_no_connector': 0,
            'skipped_ambiguous': 0,
            'skipped_no_match': 0,
            'errors': 0,
            'lead_ids': [],
            'previews': [],
            'last_id': cursor,
        }
        max_scanned_id = cursor
        for lead in candidates:
            result['processed'] += 1
            max_scanned_id = max(max_scanned_id, lead.id)
            if not is_property_address_complete(lead=lead):
                result['skipped_incomplete'] += 1
                continue
            connector = connector_for_lead(lead)
            if getattr(connector, 'market', None) != 'cook_county_il':
                result['skipped_no_connector'] += 1
                continue
            try:
                pins = self._cook_pins_at_address(lead.property_street)
            except Exception:
                logger.exception('PIN batch lookup failed for lead %s', lead.id)
                result['errors'] += 1
                continue
            if not pins:
                result['skipped_no_match'] += 1
                continue
            if len(pins) != 1:
                result['skipped_ambiguous'] += 1
                continue
            pin = pins[0]
            if dry_run:
                result['previews'].append({'lead_id': lead.id, 'pin': pin})
                continue
            try:
                self.approve_match(lead.id, actor=actor, pin=pin)
                result['resolved'] += 1
                result['lead_ids'].append(lead.id)
            except Exception:
                logger.exception('PIN batch approval failed for lead %s', lead.id)
                result['errors'] += 1

        # Advance past everything scanned this run. A short page means the pass
        # ended — wrap to 0 so the next run restarts from the top.
        next_cursor = 0 if len(candidates) < batch_size else max_scanned_id
        result['last_id'] = next_cursor
        if persist_cursor and not dry_run:
            _set_resolve_pins_cursor(next_cursor)
        return result

    def approve_match(
        self,
        lead_id: int,
        *,
        actor: str = 'anonymous',
        pin: str | None = None,
        use_assessor_street: bool = False,
    ) -> dict:
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f'Lead {lead_id} not found')

        from app.services.property_address_service import complete_property_address

        complete_property_address(
            lead,
            try_gis=True,
            actor=actor,
            commit=False,
            write_timeline=False,
        )
        connector = connector_for_lead(lead)
        if connector is None:
            from app.services.property_address_service import is_property_address_complete
            reason = (
                'incomplete_address'
                if not is_property_address_complete(lead=lead)
                else 'no_connector'
            )
            message = (
                'Add city, state, and ZIP before looking up a PIN'
                if reason == 'incomplete_address'
                else 'No GIS connector for this lead\'s county'
            )
            raise ValueError(message)

        # Preserve skip-trace handoff when the lead is already in that pipeline
        # (Command Center "Look up PIN" / Apply must not wipe needs_skip_trace).
        # Missing-property-match queue leads often have needs_skip_trace=True from
        # a prior GIS miss — those still clear the flag on approve.
        preserve_skip_trace = lead.lead_status == 'skip_trace'

        # Sidebar Apply may pass a previewed PIN for lookup_by_pin fallback when
        # address lookup is flaky — do not persist it until GIS confirms the parcel.
        pin_value = (pin or '').strip() or None
        is_cook = getattr(connector, 'market', None) == 'cook_county_il'
        if pin_value and is_cook:
            from app.services.plugins.pin_utils import normalize_pin_for_socrata
            digits = normalize_pin_for_socrata(pin_value)
            if len(digits) != 14 or not digits.isdigit():
                raise ValueError('Invalid Cook County PIN')

        try:
            outcome = self._ingestion_service()._enrich_with_gis(
                lead, connector, import_job_id=None, pin_hint=pin_value,
            )
            if not outcome.get('match_found'):
                db.session.rollback()
                raise ValueError('GIS match could not be applied')

            from app.services.plugins.pin_utils import (
                format_pin_for_storage,
                normalize_pin_for_socrata,
            )
            parcel_pin = outcome.get('parcel_pin') or lead.county_assessor_pin
            if pin_value:
                resolved = normalize_pin_for_socrata(parcel_pin or '')
                submitted = normalize_pin_for_socrata(pin_value)
                if resolved and submitted and resolved != submitted:
                    db.session.rollback()
                    raise ValueError('Submitted PIN does not match the resolved parcel')
                # Persist connector PIN (preferred) or the validated submitted PIN.
                store_raw = parcel_pin or pin_value
                if is_cook:
                    lead.county_assessor_pin = format_pin_for_storage(store_raw)
                else:
                    lead.county_assessor_pin = (store_raw or '').strip() or None

            if not preserve_skip_trace:
                lead.needs_skip_trace = False

            # Backfill locality from parcel address; keep marketing street and
            # persist assessor situs as AKA when it differs (corner / range cases).
            if (
                hasattr(connector, 'lookup_address_by_pin')
                and lead.county_assessor_pin
            ):
                from app.services.property_address_service import (
                    apply_parcel_address_to_lead,
                    complete_property_address,
                )
                addr_row = connector.lookup_address_by_pin(lead.county_assessor_pin)
                apply_parcel_address_to_lead(
                    lead, addr_row, replace_street=bool(use_assessor_street),
                )
                _apply_assessor_aka(lead, addr_row)
                complete_property_address(
                    lead,
                    try_gis=False,
                    actor=actor,
                    commit=False,
                    write_timeline=False,
                )

            db.session.add(lead)
            entry = LeadTimelineEntry(
                lead_id=lead_id,
                event_type='property_match_approved',
                occurred_at=dt.datetime.now(dt.timezone.utc),
                source='manual',
                actor=actor,
                summary='Property match approved from Missing Property Match queue.',
                event_metadata={
                    'connector': outcome.get('connector_name'),
                    'pin': lead.county_assessor_pin,
                },
            )
            db.session.add(entry)
            db.session.commit()
        except ValueError:
            raise
        except Exception:
            db.session.rollback()
            raise

        refresh_lead_scoring(lead_id)
        db.session.refresh(lead)

        if getattr(lead, 'lead_category', None) == 'commercial':
            try:
                from app.services.building_ownership_backfill import (
                    dispatch_building_ownership_analysis,
                )
                dispatch_building_ownership_analysis(lead_id)
            except Exception as exc:
                logger.warning(
                    'Building ownership dispatch after match approve failed for lead %s: %s',
                    lead_id, exc,
                )

        recommended = lead.recommended_action
        if recommended is not None and hasattr(recommended, 'value'):
            recommended = recommended.value

        return {
            'lead_id': lead_id,
            'has_property_match': lead.has_property_match,
            'county_assessor_pin': lead.county_assessor_pin,
            'assessor_aka_street': getattr(lead, 'assessor_aka_street', None),
            'assessor_aka_city': getattr(lead, 'assessor_aka_city', None),
            'assessor_aka_state': getattr(lead, 'assessor_aka_state', None),
            'assessor_aka_zip': getattr(lead, 'assessor_aka_zip', None),
            'recommended_action': recommended,
            'removed_from_queue': True,
        }

    def reject_match(
        self,
        lead_id: int,
        action: str,
        *,
        actor: str = 'anonymous',
        note: str | None = None,
    ) -> dict:
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f'Lead {lead_id} not found')

        if action == 'skip_trace':
            apply_lead_status_change(
                lead, 'skip_trace', reason=note or 'Match rejected — sent to skip trace', actor=actor,
            )
            lead.needs_skip_trace = True
            db.session.add(lead)
        elif action == 'manual_edit':
            pass
        elif action == 'research_pin':
            from app.services.lead_task_service import LeadTaskService
            LeadTaskService().create(
                lead_id,
                {'title': 'Research missing PIN', 'task_type': 'research_missing_pin'},
                actor=actor,
            )
        else:
            raise ValueError(f'Unknown reject action: {action}')

        entry = LeadTimelineEntry(
            lead_id=lead_id,
            event_type='property_match_rejected',
            occurred_at=dt.datetime.now(dt.timezone.utc),
            source='manual',
            actor=actor,
            summary=note or f'Property match rejected ({action}).',
            event_metadata={'action': action},
        )
        db.session.add(entry)
        db.session.commit()

        return {'lead_id': lead_id, 'action': action}

    def update_property_address(
        self,
        lead_id: int,
        *,
        property_street: str | None = None,
        property_city: str | None = None,
        property_state: str | None = None,
        property_zip: str | None = None,
        actor: str = 'anonymous',
    ) -> dict:
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f'Lead {lead_id} not found')

        if property_street is not None:
            lead.property_street = property_street
        if property_city is not None:
            lead.property_city = property_city
        if property_state is not None:
            lead.property_state = property_state
        if property_zip is not None:
            lead.property_zip = property_zip
        lead.has_property_match = False
        from app.services.property_address_service import complete_property_address
        complete_property_address(
            lead,
            try_gis=True,
            actor=actor,
            commit=False,
        )
        db.session.add(lead)
        db.session.commit()

        preview = self.preview_match(lead_id)
        preview['lead_id'] = lead_id
        return preview
