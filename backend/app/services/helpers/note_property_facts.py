"""Parse HubSpot note/call free text into structured property facts.

Assessor beds/baths on the lead are never overwritten. Note-derived unit counts
and per-unit bed/bath mixes are stored on ``lead.note_property_facts`` and may
fill blank ``lead.units`` / upgrade residential → commercial when units ≥ 5.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.helpers.import_signal_fills import parse_units_from_deal_description

# "6 unit property", "6-unit", "6 units", "12 unit building"
_UNITS_IN_PROSE_RE = re.compile(
    r'\b(\d{1,4})\s*-?\s*units?\b(?!\s+are\b)'
    r'(?:\s+(?:property|bldg|building|apt|apartment|multi[\s-]?family))?',
    re.IGNORECASE,
)

# "4 units are 2 beds" / "2 units are 3 bedrooms" / optional baths
_UNIT_MIX_RE = re.compile(
    r'\b(\d{1,4})\s*units?\s+are\s+(\d+(?:\.\d+)?)\s*beds?(?:rooms?)?'
    r'(?:\s*(?:/|,|and)?\s*(\d+(?:\.\d+)?)\s*baths?(?:rooms?)?)?',
    re.IGNORECASE,
)

NOTE_COMMERCIAL_UNIT_THRESHOLD = 5


def _clamp_units(value: int | None) -> int | None:
    if value is None:
        return None
    if value < 1 or value > 5000:
        return None
    return value


def parse_units_from_note_text(text: str | None) -> int | None:
    """Extract a whole-building unit count from note/call prose or ``Units: N``."""
    raw = (text or '').strip()
    if not raw:
        return None
    from_desc = parse_units_from_deal_description(raw)
    if from_desc is not None:
        return from_desc
    match = _UNITS_IN_PROSE_RE.search(raw)
    if not match:
        return None
    try:
        return _clamp_units(int(match.group(1)))
    except (TypeError, ValueError):
        return None


def parse_unit_mix_from_note_text(text: str | None) -> list[dict[str, Any]]:
    """Extract explicit per-unit bed(/bath) mix rows from note/call prose."""
    raw = (text or '').strip()
    if not raw:
        return []
    rows: list[dict[str, Any]] = []
    for match in _UNIT_MIX_RE.finditer(raw):
        try:
            count = int(match.group(1))
            beds = float(match.group(2))
        except (TypeError, ValueError):
            continue
        if count < 1 or count > 5000:
            continue
        if beds < 0 or beds > 50:
            continue
        if beds != int(beds):
            # Whole bedrooms only for mix rows (half-baths go in baths when present)
            continue
        entry: dict[str, Any] = {
            'units': count,
            'beds': int(beds),
        }
        baths_raw = match.group(3)
        if baths_raw is not None:
            try:
                baths = float(baths_raw)
            except (TypeError, ValueError):
                baths = None
            if baths is not None and 0 < baths <= 50:
                entry['baths'] = int(baths) if baths == int(baths) else baths
        rows.append(entry)
    return rows


def parse_note_property_facts(
    text: str | None,
    *,
    source: str = 'hubspot_note',
    hubspot_activity_id: str | None = None,
    source_occurred_at: datetime | str | None = None,
) -> dict[str, Any] | None:
    """Return a facts dict when units and/or unit_mix can be extracted."""
    units = parse_units_from_note_text(text)
    unit_mix = parse_unit_mix_from_note_text(text)
    if units is None and not unit_mix:
        return None
    if units is None and unit_mix:
        # Infer total units from mix when prose never said "N unit property"
        total = sum(int(row['units']) for row in unit_mix)
        units = _clamp_units(total)
    excerpt = (text or '').strip()
    if len(excerpt) > 240:
        excerpt = excerpt[:237] + '...'
    return {
        'units': units,
        'unit_mix': unit_mix,
        'source': source,
        'hubspot_activity_id': hubspot_activity_id,
        'source_occurred_at': _isoformat_source_time(source_occurred_at),
        'excerpt': excerpt,
        'extracted_at': datetime.now(timezone.utc).isoformat(),
    }


def _units_blank(current: Any) -> bool:
    if current is None:
        return True
    try:
        return int(current) <= 0
    except (TypeError, ValueError):
        return True


def _facts_richer(candidate: dict[str, Any], existing: dict[str, Any] | None) -> bool:
    """Prefer facts with unit_mix, else higher unit count, else newer extract."""
    if not existing:
        return True
    cand_mix = candidate.get('unit_mix') or []
    exist_mix = existing.get('unit_mix') or []
    if len(cand_mix) > len(exist_mix):
        return True
    if len(cand_mix) < len(exist_mix):
        return False
    cand_detail = _unit_mix_detail_score(cand_mix)
    exist_detail = _unit_mix_detail_score(exist_mix)
    if cand_detail > exist_detail:
        return True
    if cand_detail < exist_detail:
        return False
    cand_u = candidate.get('units')
    exist_u = existing.get('units')
    try:
        cand_n = int(cand_u) if cand_u is not None else 0
    except (TypeError, ValueError):
        cand_n = 0
    try:
        exist_n = int(exist_u) if exist_u is not None else 0
    except (TypeError, ValueError):
        exist_n = 0
    if cand_n > exist_n:
        return True
    if cand_n < exist_n:
        return False
    cand_time = _source_time(candidate)
    exist_time = _source_time(existing)
    if cand_time and exist_time:
        return cand_time > exist_time
    if cand_time and not exist_time:
        return True
    # Same or weaker — keep existing (idempotent migrations)
    return False


def _unit_mix_detail_score(unit_mix: list[dict[str, Any]]) -> int:
    """Count populated mix fields so baths/details can win ties by row count."""
    score = 0
    for row in unit_mix:
        if not isinstance(row, dict):
            continue
        for key in ('units', 'beds', 'baths'):
            if row.get(key) is not None:
                score += 1
    return score


def _isoformat_source_time(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _source_time(facts: dict[str, Any] | None) -> datetime | None:
    if not isinstance(facts, dict):
        return None
    raw = facts.get('source_occurred_at')
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def apply_note_property_facts_to_lead(
    lead: Any,
    text: str | None,
    *,
    source: str = 'hubspot_note',
    hubspot_activity_id: str | None = None,
    source_occurred_at: datetime | str | None = None,
) -> list[str]:
    """Apply parsed note facts to a lead. Never touches bedrooms/bathrooms.

    - Stores/replaces ``note_property_facts`` when richer or missing.
    - Fills blank ``units`` from note.
    - When note-derived units ≥ 5, set ``lead_category=commercial`` and blank
      ``property_type`` → ``Commercial``.
    """
    facts = parse_note_property_facts(
        text,
        source=source,
        hubspot_activity_id=hubspot_activity_id,
        source_occurred_at=source_occurred_at,
    )
    if facts is None:
        return []

    return _apply_parsed_note_property_facts_to_lead(lead, facts)


def _apply_parsed_note_property_facts_to_lead(
    lead: Any,
    facts: dict[str, Any],
) -> list[str]:
    """Apply already-parsed facts to a lead."""
    updated: list[str] = []
    existing = getattr(lead, 'note_property_facts', None)
    if isinstance(existing, dict) and not _facts_richer(facts, existing):
        # Keep existing richer payload; still may need category heal below
        facts = existing
    else:
        lead.note_property_facts = facts
        updated.append('note_property_facts')

    note_units = facts.get('units')
    try:
        note_units_i = int(note_units) if note_units is not None else None
    except (TypeError, ValueError):
        note_units_i = None
    note_units_i = _clamp_units(note_units_i)

    if note_units_i is not None and _units_blank(getattr(lead, 'units', None)):
        lead.units = note_units_i
        updated.append('units')

    trigger_commercial = (
        note_units_i is not None
        and note_units_i >= NOTE_COMMERCIAL_UNIT_THRESHOLD
    )
    if trigger_commercial:
        category = (getattr(lead, 'lead_category', None) or '').strip().lower() or 'residential'
        if category == 'residential':
            lead.lead_category = 'commercial'
            updated.append('lead_category')
        property_type = getattr(lead, 'property_type', None)
        if not (isinstance(property_type, str) and property_type.strip()):
            lead.property_type = 'Commercial'
            updated.append('property_type')

    # Deduplicate while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for key in updated:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


EMPTY_NOTE_PROPERTY_FACTS: dict[str, Any] = {
    'units': None,
    'unit_mix': [],
    'source': 'timeline_scan',
    'hubspot_activity_id': None,
    'excerpt': '',
    'scanned_empty': True,
}


def note_property_facts_needs_timeline_heal(facts: Any) -> bool:
    """True when CC should scan timeline (no facts payload yet)."""
    if not isinstance(facts, dict):
        return True
    if facts.get('scanned_empty') is True:
        return False
    # Any stored parse (units and/or mix) — do not hot-path rescan.
    if facts.get('units') is not None or (facts.get('unit_mix') or []):
        return False
    return True


def apply_note_facts_from_timeline(lead: Any) -> list[str]:
    """Scan HubSpot note/call timeline entries and apply the richest parse.

    When nothing parses, stores an empty sentinel so CC does not rescan forever.
    """
    from app.models.lead_timeline_entry import LeadTimelineEntry

    lead_id = getattr(lead, 'id', None)
    if lead_id is None:
        return []

    entries = (
        LeadTimelineEntry.query
        .filter(
            LeadTimelineEntry.lead_id == lead_id,
            LeadTimelineEntry.is_deleted.is_(False),
            LeadTimelineEntry.event_type.in_(('hubspot_note', 'hubspot_call')),
        )
        .order_by(LeadTimelineEntry.occurred_at.desc())
        .all()
    )
    best_facts: dict[str, Any] | None = None
    for entry in entries:
        meta = entry.event_metadata if isinstance(entry.event_metadata, dict) else {}
        body = meta.get('body') or entry.summary or ''
        source = (
            'hubspot_call'
            if str(entry.event_type) == 'hubspot_call'
            else 'hubspot_note'
        )
        facts = parse_note_property_facts(
            body,
            source=source,
            hubspot_activity_id=getattr(entry, 'hubspot_activity_id', None),
            source_occurred_at=getattr(entry, 'occurred_at', None),
        )
        if facts is not None and _facts_richer(facts, best_facts):
            best_facts = facts

    all_updated: list[str] = []
    if best_facts is not None:
        all_updated.extend(_apply_parsed_note_property_facts_to_lead(lead, best_facts))

    existing = getattr(lead, 'note_property_facts', None)
    if not isinstance(existing, dict) or (
        not (existing.get('unit_mix') or [])
        and existing.get('units') is None
        and not existing.get('scanned_empty')
    ):
        # No usable parse — sentinel stops repeated CC scans.
        if not isinstance(existing, dict) or existing.get('scanned_empty') is not True:
            lead.note_property_facts = dict(EMPTY_NOTE_PROPERTY_FACTS)
            all_updated.append('note_property_facts')

    seen: set[str] = set()
    ordered: list[str] = []
    for key in all_updated:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered
