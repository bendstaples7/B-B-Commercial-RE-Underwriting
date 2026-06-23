"""Fetch Ronald's deal live from HubSpot and re-enrich lead."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from app import create_app, db
from app.models.hubspot_config import HubSpotConfig
from app.models.hubspot_deal import HubSpotDeal
from app.models.hubspot_match import HubSpotMatch
from app.models.lead import Lead
from app.services.hubspot_client_service import HubSpotClientService
from app.services.hubspot_matcher_service import HubSpotMatcherService
from app.tasks.hubspot_tasks import _upsert_hubspot_record

DEAL_ID = '52218559108'
LEAD_ID = 11129

app = create_app()
with app.app_context():
    config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
    client = HubSpotClientService(config)
    stage_map = client.fetch_pipeline_stage_labels('deals')

    live = client._get(
        f'/crm/v3/objects/deals/{DEAL_ID}',
        {'properties': 'dealname,dealstage,pipeline,closedate,amount'},
    )
    live_stage_id = live.get('properties', {}).get('dealstage')
    live_label = stage_map.get(live_stage_id, live_stage_id)
    print('LIVE HubSpot dealstage:', live_stage_id, '->', live_label)

    stored = HubSpotDeal.query.filter_by(hubspot_id=DEAL_ID).first()
    if stored:
        old_id = (stored.raw_payload or {}).get('properties', {}).get('dealstage')
        print('STORED dealstage:', old_id, '->', stage_map.get(old_id, old_id))
        print('STORED last_updated_at:', stored.last_updated_at)

    _upsert_hubspot_record(db, HubSpotDeal, DEAL_ID, live, run_id=None)
    db.session.commit()
    print('Upserted live deal into hubspot_deals')

    lead = Lead.query.get(LEAD_ID)
    deal = HubSpotDeal.query.filter_by(hubspot_id=DEAL_ID).first()
    matcher = HubSpotMatcherService()
    updated = matcher.enrich_lead_from_deal(lead, deal, stage_map)
    db.session.commit()
    db.session.refresh(lead)
    print('Enriched fields:', updated)
    print('Lead now:', lead.lead_status, '|', lead.hubspot_deal_stage)

    pending = (
        db.session.execute(
            db.text(
                "SELECT status, count(*) FROM hubspot_webhook_logs "
                "WHERE hubspot_object_id = :id GROUP BY status"
            ),
            {'id': DEAL_ID},
        ).fetchall()
    )
    print('Webhook log status counts:', pending)
