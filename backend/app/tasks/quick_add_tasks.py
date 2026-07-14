"""Celery tasks for quick-add post-processing (GIS match, enrichment + HubSpot push)."""
import logging

logger = logging.getLogger(__name__)


def _run_gis_match(lead_id: int) -> bool:
    """Attempt county GIS parcel match; returns True when a parcel was found."""
    from app import db
    from app.models import Lead
    from app.services.deduplication_engine import DeduplicationEngine
    from app.services.gis.base import GISConnectorRegistry
    from app.services.lead_ingestion_service import LeadIngestionService

    lead = db.session.get(Lead, lead_id)
    if lead is None:
        return False
    if lead.has_property_match:
        return True

    ingestion = LeadIngestionService(
        dedup_engine=DeduplicationEngine(),
        gis_registry=GISConnectorRegistry,
    )
    connector = ingestion._gis_connector_for_lead(lead)  # noqa: SLF001
    if connector is None:
        logger.info(
            'Quick-add GIS: no connector for lead %s city=%r state=%r',
            lead_id,
            lead.property_city,
            lead.property_state,
        )
        db.session.commit()  # persist any city/state/zip backfill from parser
        return False

    outcome = ingestion._enrich_with_gis(lead, connector, import_job_id=None)  # noqa: SLF001
    db.session.commit()
    matched = bool(outcome.get('match_found'))
    logger.info(
        'Quick-add GIS for lead %s: match_found=%s connector=%s',
        lead_id,
        matched,
        outcome.get('connector_name'),
    )
    return matched


def run_quick_add_followup_inner(lead_id: int) -> dict:
    """Match property via GIS, enrich, and push to HubSpot when write-back is enabled."""
    from app import create_app, db
    from app.models import Lead, LeadTimelineEntry
    from app.services.hubspot_writeback_service import HubSpotWriteBackService
    from datetime import datetime, timezone

    app = create_app()
    with app.app_context():
        gis_matched = False
        try:
            gis_matched = _run_gis_match(lead_id)
        except Exception as exc:
            logger.warning('Quick-add GIS match failed for lead %s: %s', lead_id, exc)
            db.session.rollback()

        enrich_result = False
        try:
            from app.services.cook_county_enrichment_service import (
                dispatch_cook_county_enrichment,
            )
            enrich_result = dispatch_cook_county_enrichment(lead_id)
        except Exception as exc:
            logger.warning('Quick-add Cook County enrichment failed for lead %s: %s', lead_id, exc)
            db.session.rollback()

        try:
            push_result = HubSpotWriteBackService().push_lead_as_deal(lead_id)
        except Exception as exc:
            logger.exception('Quick-add HubSpot push failed for lead %s', lead_id)
            db.session.rollback()
            push_result = {
                'synced': False,
                'action': 'failed',
                'lead_id': lead_id,
                'error': str(exc),
            }

        if push_result.get('action') in ('failed', 'skipped') and push_result.get('reason') != 'write_back_disabled':
            lead = db.session.get(Lead, lead_id)
            if lead is not None:
                error_msg = push_result.get('error') or push_result.get('reason') or 'unknown'
                db.session.add(LeadTimelineEntry(
                    lead_id=lead_id,
                    event_type='note_added',
                    occurred_at=datetime.now(timezone.utc),
                    source='system',
                    actor='System',
                    summary=f'HubSpot deal push failed: {error_msg}'[:500],
                    event_metadata={'hubspot_push': push_result},
                ))
                db.session.commit()
        elif push_result.get('synced'):
            lead = db.session.get(Lead, lead_id)
            if lead is not None:
                db.session.add(LeadTimelineEntry(
                    lead_id=lead_id,
                    event_type='hubspot_deal_stage',
                    occurred_at=datetime.now(timezone.utc),
                    source='system',
                    actor='System',
                    summary=f"HubSpot deal {push_result.get('action')}: Skip Trace",
                    event_metadata={'hubspot_push': push_result},
                ))
                db.session.commit()

        return {
            'lead_id': lead_id,
            'gis_matched': gis_matched,
            'enriched': enrich_result is True,
            'hubspot': push_result,
        }
