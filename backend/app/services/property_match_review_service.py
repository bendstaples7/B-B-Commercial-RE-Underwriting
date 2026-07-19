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


class PropertyMatchReviewService:
    """GIS match preview and confirmation for missing-property-match queue."""

    def _ingestion_service(self) -> LeadIngestionService:
        from app.services.deduplication_engine import DeduplicationEngine
        from app.services.gis.base import GISConnectorRegistry
        return LeadIngestionService(
            dedup_engine=DeduplicationEngine(),
            gis_registry=GISConnectorRegistry,
        )

    def preview_match(self, lead_id: int) -> dict:
        from app.services.property_address_service import (
            complete_property_address,
            is_property_address_complete,
        )

        lead = db.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f'Lead {lead_id} not found')

        # Soft-heal incomplete situs before routing / PIN lookup (no commit —
        # preview must not persist GIS fills until the user applies).
        if lead.property_street and not is_property_address_complete(lead=lead):
            complete_property_address(
                lead,
                try_gis=True,
                actor='property_match_preview',
                commit=False,
                write_timeline=False,
            )
            lead = db.session.get(Lead, lead_id)

        entered = {
            'property_street': lead.property_street,
            'property_city': lead.property_city,
            'property_state': lead.property_state,
            'property_zip': lead.property_zip,
        }
        address_complete = is_property_address_complete(lead=lead)
        connector = connector_for_lead(lead)

        parcel: GISParcel | None = None
        connector_name = connector.connector_name if connector else None
        if connector is not None:
            if lead.property_street:
                parcel = connector.lookup_by_address(lead.property_street)
            if parcel is None and lead.county_assessor_pin:
                parcel = connector.lookup_by_pin(lead.county_assessor_pin)
        elif lead.property_street:
            # Street-only Cook fallback when city/state still blank after completer.
            from app.services.gis.cook_county_gis_connector import CookCountyGISConnector
            cook = CookCountyGISConnector()
            parcel = cook.lookup_by_address(lead.property_street)
            if parcel is not None:
                connector = cook
                connector_name = cook.connector_name

        if connector is None and parcel is None:
            reason = (
                'incomplete_address' if not address_complete else 'no_connector'
            )
            message = (
                'Add city, state, and ZIP before looking up a PIN'
                if reason == 'incomplete_address'
                else 'No GIS connector for this lead\'s county'
            )
            return {
                'found': False,
                'entered_address': entered,
                'recommended_address': None,
                'pin': None,
                'connector': None,
                'address_complete': address_complete,
                'reason': reason,
                'message': message,
            }

        if parcel is None:
            return {
                'found': False,
                'entered_address': entered,
                'recommended_address': None,
                'pin': None,
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
        preserve_skip_trace = lead.lead_status in (
            'skip_trace',
            'awaiting_skip_trace',
        )

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
