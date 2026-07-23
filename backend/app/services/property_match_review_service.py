"""Property match review — preview, approve, and reject GIS matches for leads."""
from __future__ import annotations

import datetime as dt
import logging

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
    def _cook_pins_at_address(address: str) -> list[str]:
        """Return distinct Cook County PINs reported for a situs address."""
        from app.services.gis.cook_county_gis_connector import lookup_all_pins_at_address

        pins: list[str] = []
        seen: set[str] = set()
        for row in lookup_all_pins_at_address(address):
            pin = str((row or {}).get('pin') or '').strip()
            if pin and pin not in seen:
                seen.add(pin)
                pins.append(pin)
        return pins

    def preview_match(self, lead_id: int) -> dict:
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
        if not address_complete:
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
        cook_pins = self._cook_pins_at_address(lead.property_street) if (
            is_cook and lead.property_street
        ) else []
        pin_count = len(cook_pins) if is_cook else None
        if is_cook and pin_count >= 2:
            return {
                'found': True,
                'entered_address': entered,
                'recommended_address': None,
                'pin': None,
                'pins': cook_pins,
                'pin_count': pin_count,
                'connector': connector_name,
                'address_complete': address_complete,
                'reason': None,
                'parcel_fields': None,
                'message': 'Multiple assessor PINs found; review and apply the property match.',
            }
        if is_cook and pin_count == 1:
            pin = cook_pins[0]
            return {
                'found': True,
                'entered_address': entered,
                'recommended_address': {
                    'property_street': lead.property_street,
                    'property_city': lead.property_city,
                    'property_state': lead.property_state,
                    'property_zip': lead.property_zip,
                    'property_type': None,
                    'county_assessor_pin': pin,
                },
                'pin': pin,
                'pins': cook_pins,
                'pin_count': pin_count,
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

        return {
            'found': True,
            'entered_address': entered,
            'recommended_address': recommended,
            'pin': parcel.county_assessor_pin,
            'pin_count': pin_count,
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

            # Backfill situs from parcel address when approve resolves a PIN.
            if (
                hasattr(connector, 'lookup_address_by_pin')
                and lead.county_assessor_pin
            ):
                from app.services.property_address_service import (
                    apply_parcel_address_to_lead,
                    complete_property_address,
                )
                addr_row = connector.lookup_address_by_pin(lead.county_assessor_pin)
                apply_parcel_address_to_lead(lead, addr_row, replace_street=True)
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
