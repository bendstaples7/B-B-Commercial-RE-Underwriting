"""Cook County / Chicago Socrata prospect feeders for review-queue candidates."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from app import db
from app.models.lead import Property
from app.models.motivation_signal import ProspectCandidate, ProspectFeedState
from app.services.motivation_signal_service import (
    ExtractedSignal,
    POINTS_RESIDENTIAL,
    SIGNAL_LABELS,
    _signal_with_recency,
    _violation_severity,
    compute_structured_motivation_score,
)
from app.services.plugins.cook_county_permits import VIOLATION_STATUSES, is_permit_violation_row
from app.services.plugins.cook_county_sheriff_foreclosure import fetch_cook_county_foreclosure_listings
from app.services.plugins.chicago_vacant_buildings import VACANT_SR_TYPE
from app.services.cook_county_prospect_config import (
    chicago_data_api_configured,
    get_prospect_min_motivation_pct,
    min_motivation_score_for_queue,
    motivation_pct,
)
from app.services.plugins.pin_utils import format_pin_for_storage, normalize_pin_for_socrata
from app.services.plugins.socrata_client import socrata_get
from app.services.prospect_coords_service import resolve_coords_from_pin

logger = logging.getLogger(__name__)

SOCATA_CALL_CAP = 200
STACKED_SOURCE_FEED = 'stacked'

FEEDS = (
    'scavenger_tax_sale',
    'annual_tax_sale',
    'chicago_scofflaw',
    'chicago_violations',
    'cook_county_permit_violations',
    'chicago_vacant_buildings',
    'cook_county_foreclosure',
    'chicago_311_complaints',
)

FEED_DATASETS = {
    'scavenger_tax_sale': ('ydgz-vkrp', 'cook_county'),
    'annual_tax_sale': ('55ju-2fs9', 'cook_county'),
    'chicago_scofflaw': ('rz4d-qp2m', 'chicago'),
    'chicago_violations': ('22u3-xenr', 'chicago'),
    'cook_county_permit_violations': ('6yjf-dfxs', 'cook_county'),
    'chicago_vacant_buildings': ('v6vf-nfxy', 'chicago'),
    'chicago_311_complaints': ('v6vf-nfxy', 'chicago'),
}

CHICAGO_FEEDS = frozenset({
    'chicago_scofflaw',
    'chicago_violations',
    'chicago_vacant_buildings',
    'chicago_311_complaints',
})

_CHICAGO_311_COMPLAINT_TYPES = (
    'Buildings - Plumbing Violation',
    'No Air Conditioning',
    'No Building Permit and Construction Violation',
    'Porch Inspection Request',
)


@dataclass
class ProspectContribution:
    feed: str
    row: dict
    external_key: str
    pin: Optional[str]
    street: str
    city: str
    state: str
    township_hint: Optional[str]
    signals: list[ExtractedSignal] = field(default_factory=list)


def _normalize_street(value: str) -> str:
    import re
    text = (value or '').upper().strip()
    text = re.sub(r'[^\w\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _external_key(feed: str, row: dict) -> str:
    for key in (
        'id', ':id', 'case_no', 'case_number', 'violation_id', 'sr_number',
        'pin', 'address', 'street_address', 'property_address',
    ):
        if row.get(key):
            return f"{feed}:{row.get(key)}"
    return f"{feed}:{hash(frozenset(row.items()))}"


def _row_pin(row: dict) -> Optional[str]:
    for key in ('pin', 'keypin', 'pins', 'parcel_pin'):
        val = row.get(key)
        if val and str(val).strip():
            return format_pin_for_storage(str(val).strip())
    return None


def _row_address(feed: str, row: dict) -> tuple[str, str, str, Optional[str]]:
    """Return street, city, state, and optional township/area hint for display."""
    township_hint = None
    if feed in ('annual_tax_sale', 'scavenger_tax_sale'):
        township_hint = (row.get('township_name') or row.get('township') or '').strip() or None
        street = (
            row.get('address')
            or row.get('property_address')
            or row.get('secondary_address')
            or ''
        )
        city = row.get('city') or row.get('property_city') or ''
        state = row.get('state') or row.get('property_state') or 'IL'
        return str(street).strip(), str(city).strip(), str(state).strip(), township_hint

    if feed == 'cook_county_foreclosure':
        street = row.get('property_street') or row.get('address') or ''
        city = row.get('property_city') or row.get('city') or ''
        state = row.get('property_state') or 'IL'
        return str(street).strip(), str(city).strip(), str(state).strip(), None

    if feed in ('chicago_vacant_buildings', 'chicago_311_complaints'):
        street = row.get('street_address') or row.get('address') or ''
        city = row.get('city') or 'Chicago'
        state = row.get('state') or 'IL'
        return str(street).strip(), str(city).strip(), str(state).strip(), None

    street = (
        row.get('address')
        or row.get('property_address')
        or row.get('secondary_address')
        or ''
    )
    city = row.get('city') or row.get('property_city') or 'Chicago'
    state = row.get('state') or row.get('property_state') or 'IL'
    return str(street).strip(), str(city).strip(), str(state).strip(), None


def _resolve_pin_from_address(street: str, city: str, state: str) -> Optional[str]:
    """Address → Cook County PIN for stacking Chicago-only feed rows."""
    if not street:
        return None
    from app.services.gis.cook_county_gis_connector import CookCountyGISConnector

    connector = CookCountyGISConnector()
    full_address = f"{street}, {city or 'Chicago'}, {state or 'IL'}"
    parcel = connector.lookup_by_address(full_address)
    if parcel and parcel.county_assessor_pin:
        return format_pin_for_storage(parcel.county_assessor_pin)
    return None


def _resolve_pin_for_row(feed: str, row: dict) -> Optional[str]:
    pin = _row_pin(row)
    if pin:
        return pin
    street, city, state_code, _ = _row_address(feed, row)
    if street:
        return _resolve_pin_from_address(street, city, state_code)
    return None


def _stack_external_key(pin: str) -> str:
    return f"pin:{normalize_pin_for_socrata(pin)}"


def _load_known_evidence_keys() -> set[str]:
    keys: set[str] = set()
    for candidate in ProspectCandidate.query.all():
        for sig in candidate.signals or []:
            key = sig.get('evidence_key')
            if key:
                keys.add(str(key))
    return keys


def _dedupe_signals(signals: list[ExtractedSignal]) -> list[ExtractedSignal]:
    by_key: dict[tuple[str, str], ExtractedSignal] = {}
    for sig in signals:
        by_key[(sig.signal_type, sig.evidence_key or '')] = sig
    return list(by_key.values())


def _signals_to_payload(signals: list[ExtractedSignal]) -> list[dict]:
    payload: list[dict] = []
    for s in signals:
        item = {
            'signal_type': s.signal_type,
            'severity': s.severity,
            'points': s.points,
            'evidence_key': s.evidence_key,
            'evidence': s.evidence,
            'label': SIGNAL_LABELS.get(s.signal_type, s.signal_type),
        }
        if s.base_points is not None:
            item['base_points'] = s.base_points
        if s.recency_multiplier is not None:
            item['recency_multiplier'] = s.recency_multiplier
        if s.event_date:
            item['event_date'] = s.event_date
        payload.append(item)
    return payload


def _primary_signal_type(signals: list[ExtractedSignal]) -> str:
    if not signals:
        return 'UNKNOWN'
    return max(signals, key=lambda s: s.points).signal_type


def _best_address_from_group(group: list[ProspectContribution]) -> tuple[str, str, str, Optional[str]]:
    for contrib in group:
        if contrib.street:
            return contrib.street, contrib.city, contrib.state, contrib.township_hint
    if group:
        first = group[0]
        return first.street, first.city, first.state, first.township_hint
    return '', '', 'IL', None


def _combined_raw_record(group: list[ProspectContribution]) -> dict:
    payload: dict = {'feeds': {}}
    for contrib in group:
        feed_payload = dict(contrib.row)
        if contrib.township_hint:
            feed_payload['township_name'] = contrib.township_hint
        payload['feeds'][contrib.feed] = feed_payload
    return payload


def _find_stacked_candidate(owner_user_id: str, pin_storage: str) -> Optional[ProspectCandidate]:
    ext_key = _stack_external_key(pin_storage)
    candidate = ProspectCandidate.query.filter_by(
        owner_user_id=owner_user_id,
        source_feed=STACKED_SOURCE_FEED,
        external_key=ext_key,
    ).first()
    if candidate:
        return candidate
    return (
        ProspectCandidate.query.filter_by(owner_user_id=owner_user_id, pin=pin_storage)
        .filter(ProspectCandidate.status.in_(('pending', 'duplicate', 'rejected')))
        .order_by(ProspectCandidate.id.desc())
        .first()
    )


def _set_candidate_coords(candidate: ProspectCandidate, pin: Optional[str]) -> None:
    lat, lon = resolve_coords_from_pin(pin)
    if lat is not None and lon is not None:
        candidate.latitude = lat
        candidate.longitude = lon


def _resolve_address_from_pin(pin: Optional[str]) -> tuple[str, str, str]:
    """Populate street/city/state from Cook County parcel addresses when PIN is known."""
    if not pin:
        return '', '', ''
    from app.services.gis.cook_county_gis_connector import CookCountyGISConnector

    connector = CookCountyGISConnector()
    resolved = connector.lookup_address_by_pin(pin)
    if not resolved:
        return '', '', ''
    return (
        resolved.get('property_street') or '',
        resolved.get('property_city') or '',
        resolved.get('property_state') or 'IL',
    )


def _apply_pin_address(
    pin: Optional[str],
    street: str,
    city: str,
    state_code: str,
) -> tuple[str, str, str]:
    """Use GIS PIN lookup when the feed row has no street address."""
    if street:
        return street, city or 'Chicago', state_code or 'IL'
    if not pin:
        return street, city, state_code or 'IL'
    resolved_street, resolved_city, resolved_state = _resolve_address_from_pin(pin)
    if resolved_street:
        return resolved_street, resolved_city or city, resolved_state or state_code or 'IL'
    return street, city or None, state_code or 'IL'


def _find_duplicate_lead(pin: Optional[str], street: str, city: str) -> Optional[int]:
    if pin:
        normalized = normalize_pin_for_socrata(pin)
        dashed = format_pin_for_storage(pin)
        for candidate_pin in {pin, normalized, dashed}:
            lead = (
                Property.query.filter(Property.county_assessor_pin == candidate_pin)
                .limit(1)
                .first()
            )
            if lead:
                return lead.id
    if street:
        norm = _normalize_street(street)
        leads = Property.query.filter(
            Property.property_state.in_(('IL', 'Illinois', 'il')),
        ).all()
        for lead in leads:
            if _normalize_street(lead.property_street or '') == norm:
                if not city or (lead.property_city or '').upper() == city.upper():
                    return lead.id
    return None


def _building_violation_signal(
    feed: str,
    row: dict,
    *,
    dataset_id: str,
    code_field: str = 'violation_code',
) -> ExtractedSignal:
    severe = _violation_severity(row.get(code_field))
    return _signal_with_recency(
        signal_type='BUILDING_VIOLATION',
        severity='high' if severe else 'medium',
        lead_category='residential',
        source='prospect_feed',
        source_dataset=dataset_id,
        evidence_key=_external_key(feed, row),
        evidence=row,
        severe=severe,
    )


def _signals_for_feed(feed: str, row: dict) -> list[ExtractedSignal]:
    if feed == 'scavenger_tax_sale':
        return [ExtractedSignal(
            signal_type='TAX_SCAVENGER_SALE',
            severity='high',
            points=POINTS_RESIDENTIAL['TAX_SCAVENGER_SALE'],
            source='prospect_feed',
            source_dataset='ydgz-vkrp',
            evidence_key=_external_key(feed, row),
            evidence=row,
        )]
    if feed == 'annual_tax_sale':
        return [ExtractedSignal(
            signal_type='TAX_ANNUAL_SALE',
            severity='high',
            points=POINTS_RESIDENTIAL['TAX_ANNUAL_SALE'],
            source='prospect_feed',
            source_dataset='55ju-2fs9',
            evidence_key=_external_key(feed, row),
            evidence=row,
        )]
    if feed == 'chicago_scofflaw':
        return [ExtractedSignal(
            signal_type='CHICAGO_SCOFFLAW',
            severity='high',
            points=POINTS_RESIDENTIAL['CHICAGO_SCOFFLAW'],
            source='prospect_feed',
            source_dataset='rz4d-qp2m',
            evidence_key=_external_key(feed, row),
            evidence=row,
        )]
    if feed == 'chicago_violations':
        return [_building_violation_signal(feed, row, dataset_id='22u3-xenr')]
    if feed == 'cook_county_permit_violations':
        if not is_permit_violation_row(row):
            return []
        return [_building_violation_signal(feed, row, dataset_id='6yjf-dfxs', code_field='job_code_primary')]
    if feed == 'chicago_vacant_buildings':
        return [_signal_with_recency(
            signal_type='VACANT_BUILDING',
            severity='high',
            lead_category='residential',
            source='prospect_feed',
            source_dataset='v6vf-nfxy',
            evidence_key=_external_key(feed, row),
            evidence=row,
        )]
    if feed == 'cook_county_foreclosure':
        return [ExtractedSignal(
            signal_type='FORECLOSURE_AUCTION',
            severity='high',
            points=POINTS_RESIDENTIAL['FORECLOSURE_AUCTION'],
            source='prospect_feed',
            source_dataset='cook_county_sheriff',
            evidence_key=_external_key(feed, row),
            evidence=row,
        )]
    if feed == 'chicago_311_complaints':
        return [_signal_with_recency(
            signal_type='BUILDING_COMPLAINT',
            severity='medium',
            lead_category='residential',
            source='prospect_feed',
            source_dataset='v6vf-nfxy',
            evidence_key=_external_key(feed, row),
            evidence=row,
        )]
    return []


class _ProspectLead:
    """Minimal lead-like object for scoring extracted prospect signals."""

    def __init__(self, *, lead_category: str = 'residential'):
        self.lead_category = lead_category
        self.tax_distress_data = None
        self.violation_data = None
        self.permit_data = None
        self.notes = None
        self.source_type = None
        self.manual_priority = None


def _score_signals(signals: list[ExtractedSignal]) -> float:
    stub = _ProspectLead()
    if any(s.signal_type == 'TAX_SCAVENGER_SALE' for s in signals):
        stub.tax_distress_data = {'scavenger_tax_sale': [s.evidence for s in signals]}
    elif any(s.signal_type == 'TAX_ANNUAL_SALE' for s in signals):
        stub.tax_distress_data = [s.evidence for s in signals]
    if any(s.signal_type == 'CHICAGO_SCOFFLAW' for s in signals):
        stub.violation_data = {'chicago_scofflaw': [s.evidence for s in signals]}
    if any(s.signal_type == 'BUILDING_VIOLATION' for s in signals):
        stub.violation_data = {'chicago_building_violations': [s.evidence for s in signals]}
    return compute_structured_motivation_score(stub, signals=signals)


def _fetch_feed_rows(feed: str, *, since: Optional[datetime], call_budget: int) -> list[dict]:
    if feed == 'cook_county_foreclosure':
        return fetch_cook_county_foreclosure_listings()[:call_budget]

    dataset_id, portal = FEED_DATASETS[feed]
    params: dict[str, Any] = {'$limit': min(100, call_budget)}
    if feed == 'scavenger_tax_sale' and since:
        params['$where'] = f"tax_sale_year >= '{since.year}'"
    elif feed == 'annual_tax_sale':
        params['$order'] = 'tax_sale_year DESC'
    elif feed == 'chicago_violations':
        params['$order'] = 'violation_date DESC'
    elif feed == 'cook_county_permit_violations':
        status_list = "', '".join(sorted(VIOLATION_STATUSES))
        params['$where'] = f"status in ('{status_list}')"
        params['$order'] = 'date_issued DESC'
    elif feed == 'chicago_vacant_buildings':
        since_iso = (since or (datetime.utcnow() - timedelta(days=365))).strftime('%Y-%m-%dT00:00:00')
        params['$where'] = (
            f"sr_type = '{VACANT_SR_TYPE}' AND created_date > '{since_iso}'"
        )
        params['$order'] = 'created_date DESC'
    elif feed == 'chicago_311_complaints':
        since_iso = (since or (datetime.utcnow() - timedelta(days=365))).strftime('%Y-%m-%dT00:00:00')
        type_clause = ' OR '.join(f"sr_type = '{t}'" for t in _CHICAGO_311_COMPLAINT_TYPES)
        params['$where'] = (
            f"owner_department = 'DOB - Buildings' "
            f"AND created_date > '{since_iso}' "
            f"AND ({type_clause})"
        )
        params['$order'] = 'created_date DESC'
    rows = socrata_get(dataset_id, params=params, portal=portal)
    if feed == 'cook_county_permit_violations':
        return [row for row in rows if is_permit_violation_row(row)]
    return rows


def _get_feed_state(feed: str) -> ProspectFeedState:
    state = ProspectFeedState.query.filter_by(feed_name=feed).first()
    if state is None:
        state = ProspectFeedState(feed_name=feed)
        db.session.add(state)
        db.session.flush()
    return state


def collect_feed_contributions(
    feed: str,
    *,
    known_evidence_keys: set[str],
    socrata_call_cap: int = SOCATA_CALL_CAP,
) -> tuple[dict, list[ProspectContribution]]:
    """Fetch one feed and return signal contributions (no per-row admission gate)."""
    summary = {
        'feed': feed,
        'fetched': 0,
        'contributions': 0,
        'skipped': 0,
        'skipped_no_pin': 0,
        'skipped_duplicate_evidence': 0,
        'socrata_calls': 0 if feed == 'cook_county_foreclosure' else 1,
        'chicago_api_configured': chicago_data_api_configured() if feed in CHICAGO_FEEDS else True,
    }
    if feed in CHICAGO_FEEDS and not chicago_data_api_configured():
        logger.info(
            'Chicago feed %s using unauthenticated Socrata access (optional App Token: '
            'https://data.cityofchicago.org/profile/app_tokens)',
            feed,
        )

    state = _get_feed_state(feed)
    since = state.last_synced_at or (datetime.utcnow() - timedelta(days=365))
    rows = _fetch_feed_rows(feed, since=since, call_budget=socrata_call_cap)
    summary['fetched'] = len(rows)

    contributions: list[ProspectContribution] = []
    for row in rows:
        signals = _signals_for_feed(feed, row)
        if not signals:
            summary['skipped'] += 1
            continue

        external_key = _external_key(feed, row)
        if external_key in known_evidence_keys:
            summary['skipped_duplicate_evidence'] += 1
            continue

        pin = _resolve_pin_for_row(feed, row)
        if not pin:
            summary['skipped_no_pin'] += 1
            continue

        street, city, state_code, township_hint = _row_address(feed, row)
        contributions.append(ProspectContribution(
            feed=feed,
            row=row,
            external_key=external_key,
            pin=pin,
            street=street,
            city=city,
            state=state_code,
            township_hint=township_hint,
            signals=signals,
        ))
        known_evidence_keys.add(external_key)
        summary['contributions'] += 1

    state.last_synced_at = datetime.utcnow()
    state.rows_processed += summary['contributions']
    state.updated_at = datetime.utcnow()
    db.session.commit()
    return summary, contributions


def upsert_pin_stacked_candidates(
    contributions: list[ProspectContribution],
    owner_user_id: str,
) -> dict:
    """Merge contributions by PIN, apply admission gates, upsert one candidate per PIN."""
    summary = {
        'pins_considered': 0,
        'created': 0,
        'updated': 0,
        'reopened': 0,
        'duplicate': 0,
        'skipped_low_motivation': 0,
        'skipped_no_address': 0,
    }
    by_pin: dict[str, list[ProspectContribution]] = defaultdict(list)
    for contrib in contributions:
        pin_digits = normalize_pin_for_socrata(contrib.pin or '')
        if pin_digits:
            by_pin[pin_digits].append(contrib)

    min_pct = get_prospect_min_motivation_pct()
    for pin_digits, group in by_pin.items():
        summary['pins_considered'] += 1
        pin_storage = format_pin_for_storage(pin_digits)
        merged = _dedupe_signals([sig for c in group for sig in c.signals])
        score = _score_signals(merged)
        pct = motivation_pct(score)
        if pct < min_pct:
            summary['skipped_low_motivation'] += 1
            continue

        street, city, state_code, township_hint = _best_address_from_group(group)
        street, city, state_code = _apply_pin_address(pin_storage, street, city, state_code)
        if not street:
            summary['skipped_no_address'] += 1
            continue

        duplicate_lead_id = _find_duplicate_lead(pin_storage, street, city)
        status = 'duplicate' if duplicate_lead_id else 'pending'
        signal_payload = _signals_to_payload(merged)
        ext_key = _stack_external_key(pin_storage)
        raw_record = _combined_raw_record(group)
        if township_hint:
            raw_record['township_name'] = township_hint

        candidate = _find_stacked_candidate(owner_user_id, pin_storage)
        if candidate:
            was_rejected = candidate.status == 'rejected'
            candidate.pin = pin_storage
            candidate.property_street = street
            candidate.property_city = city or None
            candidate.property_state = state_code or 'IL'
            candidate.primary_signal_type = _primary_signal_type(merged)
            candidate.motivation_score = score
            candidate.signals = signal_payload
            candidate.source_feed = STACKED_SOURCE_FEED
            candidate.external_key = ext_key
            candidate.raw_record = raw_record
            candidate.duplicate_lead_id = duplicate_lead_id
            candidate.rejection_reason = None
            _set_candidate_coords(candidate, pin_storage)
            if was_rejected and status == 'pending':
                candidate.status = 'pending'
                summary['reopened'] += 1
            elif candidate.status not in ('imported',):
                candidate.status = status
            summary['updated'] += 1
            if status == 'duplicate':
                summary['duplicate'] += 1
        else:
            candidate = ProspectCandidate(
                owner_user_id=owner_user_id,
                pin=pin_storage,
                property_street=street,
                property_city=city or None,
                property_state=state_code or 'IL',
                primary_signal_type=_primary_signal_type(merged),
                motivation_score=score,
                signals=signal_payload,
                source_feed=STACKED_SOURCE_FEED,
                external_key=ext_key,
                status=status,
                duplicate_lead_id=duplicate_lead_id,
                raw_record=raw_record,
            )
            _set_candidate_coords(candidate, pin_storage)
            db.session.add(candidate)
            summary['created'] += 1
            if status == 'duplicate':
                summary['duplicate'] += 1

    db.session.commit()
    return summary


def sync_prospect_feed(
    feed: str,
    owner_user_id: str,
    *,
    socrata_call_cap: int = SOCATA_CALL_CAP,
    known_evidence_keys: Optional[set[str]] = None,
) -> dict:
    """Pull one feed and return contribution summary (stacking happens in sync_all)."""
    keys = known_evidence_keys if known_evidence_keys is not None else _load_known_evidence_keys()
    summary, contributions = collect_feed_contributions(
        feed,
        known_evidence_keys=keys,
        socrata_call_cap=socrata_call_cap,
    )
    summary['owner_user_id'] = owner_user_id
    summary['contributions_collected'] = len(contributions)
    return summary


def sync_all_prospect_feeds(owner_user_id: str, *, socrata_call_cap: int = SOCATA_CALL_CAP) -> dict:
    """Run all Cook County prospect feeds, stack signals by PIN, upsert candidates."""
    summary = {
        'status': 'completed',
        'feeds': [],
        'socrata_calls': 0,
        'capped': False,
        'chicago_api_configured': chicago_data_api_configured(),
    }
    known_keys = _load_known_evidence_keys()
    all_contributions: list[ProspectContribution] = []
    calls = 0
    for feed in FEEDS:
        if calls >= socrata_call_cap:
            summary['capped'] = True
            break
        remaining = socrata_call_cap - calls
        feed_summary, contributions = collect_feed_contributions(
            feed,
            known_evidence_keys=known_keys,
            socrata_call_cap=remaining,
        )
        calls += feed_summary.get('socrata_calls', 1)
        feed_summary['contributions_collected'] = len(contributions)
        summary['feeds'].append(feed_summary)
        all_contributions.extend(contributions)

    summary['socrata_calls'] = calls
    summary['stack'] = upsert_pin_stacked_candidates(all_contributions, owner_user_id)
    backfill_summary = backfill_prospect_candidate_addresses()
    summary['address_backfill'] = backfill_summary
    coord_summary = backfill_prospect_candidate_coords()
    summary['coord_backfill'] = coord_summary
    reconcile_summary = reconcile_ineligible_pending_candidates()
    summary['reconcile'] = reconcile_summary
    return summary


def reconcile_ineligible_pending_candidates() -> dict:
    """Move pending rows that fail admission rules out of the review queue."""
    min_score = min_motivation_score_for_queue()
    summary = {'reconciled': 0, 'skipped_low_motivation': 0, 'skipped_no_address': 0}
    pending = ProspectCandidate.query.filter_by(status='pending').all()
    changed = False
    for candidate in pending:
        street_ok = bool((candidate.property_street or '').strip())
        score_ok = (candidate.motivation_score or 0) >= min_score
        if street_ok and score_ok:
            continue
        if not score_ok:
            candidate.status = 'rejected'
            candidate.rejection_reason = 'auto:below_min_motivation'
            summary['skipped_low_motivation'] += 1
        else:
            candidate.status = 'rejected'
            candidate.rejection_reason = 'auto:no_address'
            summary['skipped_no_address'] += 1
        summary['reconciled'] += 1
        changed = True
    if changed:
        db.session.commit()
    return summary


def backfill_prospect_candidate_addresses(*, limit: int = 500) -> dict:
    """Re-resolve PIN → street for candidates missing a street address."""
    summary = {
        'checked': 0,
        'updated': 0,
        'skipped': 0,
        'marked_no_address': 0,
    }
    min_score = min_motivation_score_for_queue()
    candidates = (
        ProspectCandidate.query.filter(
            ProspectCandidate.pin.isnot(None),
            db.or_(
                ProspectCandidate.property_street.is_(None),
                ProspectCandidate.property_street == '',
            ),
        )
        .limit(limit)
        .all()
    )
    changed = False
    for candidate in candidates:
        summary['checked'] += 1
        street, city, state_code = _apply_pin_address(
            candidate.pin,
            candidate.property_street or '',
            candidate.property_city or '',
            candidate.property_state or 'IL',
        )
        if street and street != (candidate.property_street or ''):
            candidate.property_street = street
            candidate.property_city = city or None
            candidate.property_state = state_code or 'IL'
            summary['updated'] += 1
            changed = True
        elif not street:
            if (candidate.property_city or '').strip().lower() == 'chicago':
                candidate.property_city = None
                changed = True
            if candidate.status == 'pending':
                candidate.status = 'rejected'
                if candidate.motivation_score < min_score:
                    candidate.rejection_reason = 'auto:below_min_motivation'
                else:
                    candidate.rejection_reason = 'auto:no_address'
                summary['marked_no_address'] += 1
                changed = True
            else:
                summary['skipped'] += 1
        else:
            summary['skipped'] += 1
    if changed:
        db.session.commit()
    return summary


def backfill_prospect_candidate_coords(*, limit: int = 500) -> dict:
    """Populate latitude/longitude from parcel_universe_cache for prospects with PINs."""
    summary = {'checked': 0, 'updated': 0, 'skipped': 0}
    candidates = (
        ProspectCandidate.query.filter(
            ProspectCandidate.pin.isnot(None),
            db.or_(
                ProspectCandidate.latitude.is_(None),
                ProspectCandidate.longitude.is_(None),
            ),
        )
        .limit(limit)
        .all()
    )
    changed = False
    for candidate in candidates:
        summary['checked'] += 1
        lat, lon = resolve_coords_from_pin(candidate.pin)
        if lat is None or lon is None:
            summary['skipped'] += 1
            continue
        if candidate.latitude != lat or candidate.longitude != lon:
            candidate.latitude = lat
            candidate.longitude = lon
            summary['updated'] += 1
            changed = True
        else:
            summary['skipped'] += 1
    if changed:
        db.session.commit()
    return summary
