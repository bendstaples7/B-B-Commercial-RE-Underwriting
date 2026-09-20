"""Quick-add workflow — create leads from mobile field capture."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from app import db
from app.models import Lead, LeadTimelineEntry
from app.services.gis.routing import parse_city_state_zip_from_address
from app.services.google_sheets_importer import GoogleSheetsImporter
from app.services.helpers.deal_source import DEAL_SOURCE_OPTIONS
from app.services.helpers.sql_like import escape_like_pattern
from app.services.hubspot_writeback_service import DEFAULT_QUICK_ADD_DEAL_SOURCE
from app.services.skip_trace_enqueue import SkipTraceEnqueue

logger = logging.getLogger(__name__)

QUICK_ADD_DATA_SOURCE = 'quick_add'
QUICK_ADD_SOURCE = 'walk_by'
QUICK_ADD_STATUS = 'skip_trace'

QUICK_ADD_DEAL_SOURCE_OPTIONS: tuple[str, ...] = DEAL_SOURCE_OPTIONS

PRIORITY_TO_MANUAL: dict[str, int] = {
    'high': 5,
    'medium': 3,
    'low': 1,
}

def _format_capture_timestamp(when: datetime | None = None) -> str:
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone()
    return local.strftime('%b %d, %Y %I:%M %p')


def build_walk_by_context_line(
    *,
    property_street: str,
    capture_location_label: str | None = None,
    captured_at: datetime | None = None,
    label: str = 'Walk-by',
) -> str:
    where = (capture_location_label or property_street or '').strip()
    when = _format_capture_timestamp(captured_at)
    prefix = (label or 'Walk-by').strip() or 'Walk-by'
    if where:
        return f'{prefix} · {where} · {when}'
    return f'{prefix} · {when}'


def build_deal_description(
    *,
    note: str | None,
    capture_location_label: str | None,
    capture_latitude: float | None,
    capture_longitude: float | None,
    property_street: str,
    walk_by_context: str | None = None,
    context: str | None = None,
) -> str | None:
    parts: list[str] = []
    if walk_by_context and walk_by_context.strip():
        parts.append(walk_by_context.strip())
    why = (context or '').strip()
    if why:
        parts.append(why)
    if note and note.strip():
        parts.append(note.strip())
    meta_lines: list[str] = []
    if capture_location_label:
        meta_lines.append(f'Location: {capture_location_label}')
    elif property_street:
        meta_lines.append(f'Address: {property_street.strip()}')
    if capture_latitude is not None and capture_longitude is not None:
        meta_lines.append(f'GPS: {capture_latitude:.6f}, {capture_longitude:.6f}')
    if meta_lines:
        parts.append('\n'.join(meta_lines))
    combined = '\n\n'.join(parts).strip()
    return combined or None


def merge_deal_description(existing: str | None, new_block: str | None) -> str | None:
    """Append a capture block unless that exact block is already present."""
    new_block = (new_block or '').strip()
    if not new_block:
        return (existing or '').strip() or None
    existing_text = (existing or '').strip()
    if not existing_text:
        return new_block
    existing_blocks = [
        block.strip()
        for block in existing_text.split('\n\n---\n\n')
        if block.strip()
    ]
    if new_block in existing_blocks:
        return existing_text
    return f'{existing_text}\n\n---\n\n{new_block}'


def quick_add_activity_note_body(
    *,
    note: str | None,
    walk_by_context: str | None,
    context: str | None = None,
) -> str:
    """Body shown in Activity for a quick-add capture.

    Prefer the user's why and optional note. When both are blank, still
    surface the capture line so the visit appears as a Note Added row instead
    of only a generic lead_imported event buried under later system activity.
    """
    parts: list[str] = []
    why = (context or '').strip()
    user_note = (note or '').strip()
    if why:
        parts.append(why)
    if user_note and user_note not in parts:
        parts.append(user_note)
    if parts:
        return '\n\n'.join(parts)
    capture_line = (walk_by_context or '').strip()
    return capture_line or 'Walk-by capture'


class QuickAddService:
    """Orchestrates quick-add lead creation."""

    def __init__(self):
        self._importer = GoogleSheetsImporter()

    def lookup_existing_leads(
        self,
        *,
        user_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Find leads owned by the user whose address matches the query."""
        from app.services.gis.routing import parse_city_state_zip_from_address
        from app.services.lead_merge_utils import (
            cities_compatible,
            dedup_street_key,
            street_line_from_address,
        )

        needle = query.strip()
        if len(needle) < 2:
            return []

        street_line = street_line_from_address(needle) or needle
        query_city, _, _ = parse_city_state_zip_from_address(needle)
        search_needles = [needle]
        if street_line != needle:
            search_needles.append(street_line)

        seen_ids: set[int] = set()
        rows: list[Lead] = []

        def _extend(candidates: list[Lead]) -> None:
            for lead in candidates:
                if lead.id in seen_ids:
                    continue
                if not cities_compatible(query_city, lead.property_city):
                    continue
                seen_ids.add(lead.id)
                rows.append(lead)
                if len(rows) >= limit:
                    return

        for search in search_needles:
            if len(rows) >= limit:
                break
            matches = (
                Lead.query.filter(Lead.owner_user_id == user_id)
                .filter(Lead.property_street.isnot(None))
                .filter(Lead.property_street.ilike(f'%{escape_like_pattern(search)}%', escape='\\'))
                .order_by(Lead.updated_at.desc())
                .limit(limit * 3)
                .all()
            )
            _extend(matches)

        street_key = dedup_street_key(street_line)
        if street_key and len(rows) < limit:
            norm_matches = (
                Lead.query.filter(Lead.owner_user_id == user_id)
                .filter(Lead.normalized_street == street_key)
                .order_by(Lead.updated_at.desc())
                .limit(limit * 3)
                .all()
            )
            _extend(norm_matches)

        exact = self._importer._find_duplicate(  # noqa: SLF001
            {
                'property_street': needle,
                'property_city': query_city,
            },
            owner_user_id=user_id,
        )
        if exact and exact.id not in seen_ids:
            rows = [exact, *rows[: max(limit - 1, 0)]]

        return [
            {
                'lead_id': lead.id,
                'property_street': lead.property_street,
                'lead_status': lead.lead_status,
                'deal_source': lead.deal_source,
                'date_identified': lead.date_identified.isoformat() if lead.date_identified else None,
            }
            for lead in rows[:limit]
        ]

    def create_lead(
        self,
        *,
        user_id: str,
        property_street: str,
        note: str | None = None,
        context: str | None = None,
        priority: str | None = None,
        deal_source: str | None = None,
        date_identified: date | None = None,
        capture_latitude: float | None = None,
        capture_longitude: float | None = None,
        capture_location_label: str | None = None,
        property_city: str | None = None,
        property_state: str | None = None,
        property_zip: str | None = None,
        capture_kind: str | None = None,
    ) -> tuple[Lead, bool]:
        """Create or update a lead from a quick-add submission."""
        street = property_street.strip()
        if not street:
            raise ValueError('property_street is required')

        now = datetime.now(timezone.utc)
        identified_on = date_identified or now.date()
        resolved_kind = (capture_kind or '').strip().lower()
        if resolved_kind not in ('', 'property', 'lead'):
            raise ValueError('capture_kind must be property or lead')
        resolved_deal_source = (deal_source or '').strip() or DEFAULT_QUICK_ADD_DEAL_SOURCE
        provenance = 'manual' if resolved_kind == 'lead' else QUICK_ADD_SOURCE
        capture_label = 'Lead capture' if resolved_kind == 'lead' else 'Walk-by'
        walk_by_context = build_walk_by_context_line(
            property_street=street,
            capture_location_label=capture_location_label,
            captured_at=now,
            label=capture_label,
        )
        capture_description = build_deal_description(
            note=note,
            context=context,
            capture_location_label=capture_location_label,
            capture_latitude=capture_latitude,
            capture_longitude=capture_longitude,
            property_street=street,
            walk_by_context=walk_by_context,
        )
        cleaned_note = (note or '').strip() or None

        manual_priority = None
        if priority:
            manual_priority = PRIORITY_TO_MANUAL.get(priority.strip().lower())

        from app.services.property_address_service import complete_property_address_fields

        # Cook street-only GIS only when situs is blank/IL — never for out-of-state.
        state_norm = (property_state or '').strip().upper()
        city_blank = not (property_city or '').strip()
        try_gis = (not state_norm or state_norm == 'IL') and (
            city_blank or not state_norm
        )
        completed = complete_property_address_fields(
            street,
            property_city,
            property_state,
            property_zip,
            try_gis=try_gis,
        )
        street = completed.get('property_street') or street
        city = completed.get('property_city')
        state = completed.get('property_state')
        zip_code = completed.get('property_zip')

        existing = self._importer._find_duplicate(  # noqa: SLF001
            {
                'property_street': street,
                'property_city': city,
                'property_state': state,
                'property_zip': zip_code,
            },
            owner_user_id=user_id,
        )
        created = existing is None

        if created:
            payload: dict[str, Any] = {
                'property_street': street,
                'source': provenance,
                'deal_source': resolved_deal_source,
                'deal_description': capture_description,
                'lead_status': QUICK_ADD_STATUS,
                'date_identified': identified_on,
            }
            if city:
                payload['property_city'] = city
            if state:
                payload['property_state'] = state
            if zip_code:
                payload['property_zip'] = zip_code
            if manual_priority is not None:
                payload['manual_priority'] = manual_priority
            # Initial schema keeps owner_first_name NOT NULL. A walk-by often
            # has no owner yet; store '' instead of omitting the column.
            if not (payload.get('owner_first_name') or '').strip():
                payload['owner_first_name'] = ''

            lead = self._importer.upsert_lead(
                payload,
                data_source=QUICK_ADD_DATA_SOURCE,
                owner_user_id=user_id,
            )
            lead.deal_source = resolved_deal_source
            lead.lead_status = QUICK_ADD_STATUS
            if capture_description and not (lead.deal_description or '').strip():
                lead.deal_description = capture_description
            if manual_priority is not None and lead.manual_priority is None:
                lead.manual_priority = manual_priority
            from app.services.helpers.import_signal_fills import apply_import_signal_fills
            apply_import_signal_fills(lead)
        else:
            lead = existing
            assert lead is not None
            upsert_payload: dict[str, Any] = {
                'property_street': street,
            }
            if not (lead.source or '').strip():
                upsert_payload['source'] = provenance
            if city and not lead.property_city:
                upsert_payload['property_city'] = city
            if state and not lead.property_state:
                upsert_payload['property_state'] = state
            if zip_code and not lead.property_zip:
                upsert_payload['property_zip'] = zip_code
            self._importer._update_lead_fields(lead, upsert_payload, changed_by='quick_add')  # noqa: SLF001
            lead.data_source = QUICK_ADD_DATA_SOURCE
            lead.deal_source = resolved_deal_source
            lead.deal_description = merge_deal_description(lead.deal_description, capture_description)
            if lead.date_identified is None:
                lead.date_identified = identified_on
            if manual_priority is not None:
                lead.manual_priority = manual_priority
            lead.owner_user_id = user_id
            lead.updated_at = datetime.utcnow()
            from app.services.helpers.import_signal_fills import apply_import_signal_fills
            apply_import_signal_fills(lead)

        if cleaned_note:
            lead.notes = merge_deal_description(lead.notes, cleaned_note)

        from app.services.property_address_service import complete_property_address
        # GIS already attempted above when allowed — avoid a second Cook lookup.
        complete_property_address(
            lead,
            try_gis=False,
            actor='quick_add',
            commit=False,
        )
        capture_meta = {
            'source': QUICK_ADD_DATA_SOURCE,
            'capture_location_label': capture_location_label,
            'capture_latitude': capture_latitude,
            'capture_longitude': capture_longitude,
        }
        db.session.flush()
        self._add_timeline_entries(
            lead_id=lead.id,
            user_id=user_id,
            note=note,
            context=context,
            capture_meta=capture_meta,
            created=created,
            capture_kind=resolved_kind,
        )
        db.session.commit()

        if created:
            try:
                SkipTraceEnqueue().enqueue(
                    lead.id,
                    actor='quick_add',
                    reason='Quick add — run skip trace on owner',
                )
            except Exception:
                logger.exception('Could not enqueue skip trace for quick-add lead %s', lead.id)
                db.session.rollback()
                fallback_lead = db.session.get(Lead, lead.id)
                if fallback_lead is not None:
                    fallback_lead.needs_skip_trace = True
                    try:
                        db.session.commit()
                    except Exception:
                        logger.exception('Could not mark quick-add lead %s for skip trace retry', lead.id)
                        db.session.rollback()
            lead = db.session.get(Lead, lead.id) or lead

        # Write the Activity note *after* skip-trace side effects so it is not
        # immediately sorted under task_created at the same timestamp.
        try:
            self._add_capture_note(
                lead_id=lead.id,
                user_id=user_id,
                body=quick_add_activity_note_body(
                    note=note,
                    context=context,
                    walk_by_context=walk_by_context,
                ),
                capture_meta=capture_meta,
            )
            db.session.commit()
        except Exception:
            logger.exception('Could not write quick-add activity note for lead %s', lead.id)
            db.session.rollback()

        return lead, created

    @staticmethod
    def _add_timeline_entries(
        *,
        lead_id: int,
        user_id: str,
        note: str | None,
        context: str | None = None,
        capture_meta: dict[str, Any],
        created: bool,
        capture_kind: str = '',
    ) -> None:
        now = datetime.now(timezone.utc)
        has_user_content = bool((note or '').strip() or (context or '').strip())
        if capture_kind == 'property':
            created_summary = 'Quick-add: new property captured'
        elif capture_kind == 'lead':
            created_summary = 'Quick-add: new lead captured'
        else:
            created_summary = 'Quick-add: new lead captured in the field'

        if created:
            db.session.add(LeadTimelineEntry(
                lead_id=lead_id,
                event_type='lead_imported',
                occurred_at=now,
                source='manual',
                actor=user_id,
                summary=created_summary[:500],
                event_metadata=capture_meta,
            ))
        elif not has_user_content:
            db.session.add(LeadTimelineEntry(
                lead_id=lead_id,
                event_type='lead_imported',
                occurred_at=now,
                source='manual',
                actor=user_id,
                summary='Quick-add: walk-by capture appended to existing lead'[:500],
                event_metadata=capture_meta,
            ))

    @staticmethod
    def _add_capture_note(
        *,
        lead_id: int,
        user_id: str,
        body: str,
        capture_meta: dict[str, Any],
    ) -> None:
        text = (body or '').strip()
        if not text:
            return
        db.session.add(LeadTimelineEntry(
            lead_id=lead_id,
            event_type='note_added',
            occurred_at=datetime.now(timezone.utc),
            source='manual',
            actor=user_id,
            summary=text[:500],
            event_metadata={'body': text, **capture_meta},
        ))
