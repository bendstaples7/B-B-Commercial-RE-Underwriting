"""Celery tasks for quick-add post-processing (enrichment + HubSpot push)."""
import logging

logger = logging.getLogger(__name__)


def run_quick_add_followup_inner(lead_id: int) -> dict:
    """Enrich a quick-added lead and push to HubSpot when write-back is enabled."""
    from app import create_app, db
    from app.models import Lead, LeadTimelineEntry
    from app.services.hubspot_writeback_service import HubSpotWriteBackService
    from datetime import datetime, timezone

    app = create_app()
    with app.app_context():
        enrich_result = None
        try:
            from app.services.data_source_connector import DataSourceConnector
            connector = DataSourceConnector()
            enrich_result = connector.enrich_lead(lead_id, 'cook_county_assessor')
        except Exception as exc:
            logger.warning('Quick-add assessor enrichment failed for lead %s: %s', lead_id, exc)

        try:
            push_result = HubSpotWriteBackService().push_lead_as_deal(lead_id)
        except Exception as exc:
            logger.exception('Quick-add HubSpot push failed for lead %s', lead_id)
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
            'enriched': enrich_result is not None,
            'hubspot': push_result,
        }
