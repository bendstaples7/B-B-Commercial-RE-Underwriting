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
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f'Lead {lead_id} not found')

        entered = {
            'property_street': lead.property_street,
            'property_city': lead.property_city,
            'property_state': lead.property_state,
            'property_zip': lead.property_zip,
        }
        connector = connector_for_lead(lead)
        if connector is None:
            return {
                'found': False,
                'entered_address': entered,
                'recommended_address': None,
                'pin': None,
                'connector': None,
                'message': 'No GIS connector for this lead\'s county',
            }

        parcel: GISParcel | None = None
        if lead.property_street:
            parcel = connector.lookup_by_address(lead.property_street)
        if parcel is None and lead.county_assessor_pin:
            parcel = connector.lookup_by_pin(lead.county_assessor_pin)

        if parcel is None:
            return {
                'found': False,
                'entered_address': entered,
                'recommended_address': None,
                'pin': None,
                'connector': connector.connector_name,
                'message': 'No assessor match found',
            }

        addr_row = None
        if hasattr(connector, 'lookup_address_by_pin') and parcel.county_assessor_pin:
            addr_row = connector.lookup_address_by_pin(parcel.county_assessor_pin)

        recommended = {
            'property_street': (addr_row or {}).get('property_street') or lead.property_street,
            'property_city': (addr_row or {}).get('property_city') or lead.property_city,
            'property_state': (addr_row or {}).get('property_state') or lead.property_state or 'IL',
            'property_zip': (addr_row or {}).get('property_zip') or lead.property_zip,
            'property_type': parcel.property_type,
            'county_assessor_pin': parcel.county_assessor_pin,
        }

        return {
            'found': True,
            'entered_address': entered,
            'recommended_address': recommended,
            'pin': parcel.county_assessor_pin,
            'connector': connector.connector_name,
            'parcel_fields': {
                'property_type': parcel.property_type,
                'year_built': parcel.year_built,
                'square_footage': parcel.square_footage,
                'bedrooms': parcel.bedrooms,
                'bathrooms': parcel.bathrooms,
            },
            'message': None,
        }

    def approve_match(self, lead_id: int, *, actor: str = 'anonymous') -> dict:
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            raise ValueError(f'Lead {lead_id} not found')

        connector = connector_for_lead(lead)
        if connector is None:
            raise ValueError('No GIS connector available')

        outcome = self._ingestion_service()._enrich_with_gis(lead, connector, import_job_id=0)
        if not outcome.get('match_found'):
            raise ValueError('GIS match could not be applied')

        lead.needs_skip_trace = False
        db.session.add(lead)
        entry = LeadTimelineEntry(
            lead_id=lead_id,
            event_type='property_match_approved',
            occurred_at=dt.datetime.now(dt.timezone.utc),
            source='manual',
            actor=actor,
            summary='Property match approved from Missing Property Match queue.',
            event_metadata={'connector': outcome.get('connector_name')},
        )
        db.session.add(entry)
        db.session.commit()

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

        return {
            'lead_id': lead_id,
            'has_property_match': lead.has_property_match,
            'recommended_action': lead.recommended_action.value if lead.recommended_action else None,
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
        db.session.add(lead)
        db.session.commit()

        preview = self.preview_match(lead_id)
        preview['lead_id'] = lead_id
        return preview
