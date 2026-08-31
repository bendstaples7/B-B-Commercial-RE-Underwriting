"""Integration-ish tests for Facebook call attribution on Channel ROI."""
from decimal import Decimal

import pytest

from app import db
from app.models.facebook_ad_campaign import FacebookAdCampaign
from app.models.facebook_campaign_lead_attribution import FacebookCampaignLeadAttribution
from app.models.lead import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.services.call_log_service import CallLogService
from app.services.channel_roi_service import ChannelRoiService


@pytest.fixture
def fb_campaign(app):
    with app.app_context():
        c = FacebookAdCampaign(
            meta_campaign_id='meta_test_1',
            name='Test FB',
            spend=Decimal('250.00'),
            link_clicks=50,
            response_count=0,
        )
        db.session.add(c)
        db.session.commit()
        cid = c.id
        yield cid
        FacebookCampaignLeadAttribution.query.filter_by(facebook_campaign_id=cid).delete()
        FacebookAdCampaign.query.filter_by(id=cid).delete()
        db.session.commit()


@pytest.fixture
def lead_id(app):
    with app.app_context():
        lead = Lead(
            property_street='100 Channel Roi Test St',
            lead_status='mailing_no_contact_made',
        )
        db.session.add(lead)
        db.session.commit()
        lid = lead.id
        yield lid


def test_facebook_attribution_bumps_once(app, fb_campaign, lead_id):
    with app.app_context():
        svc = CallLogService()
        svc.log_call(
            lead_id,
            'answered',
            None,
            'saw the ad',
            actor='test-user',
            facebook_campaign_id=fb_campaign,
        )
        camp = FacebookAdCampaign.query.get(fb_campaign)
        assert camp.response_count == 1
        assert FacebookCampaignLeadAttribution.query.filter_by(
            lead_id=lead_id, facebook_campaign_id=fb_campaign
        ).count() == 1

        svc.log_call(
            lead_id,
            'voicemail',
            None,
            'again',
            actor='test-user',
            facebook_campaign_id=fb_campaign,
        )
        camp = FacebookAdCampaign.query.get(fb_campaign)
        assert camp.response_count == 1


def test_facebook_attribution_ignores_soft_deleted_first_call(app, fb_campaign, lead_id):
    """Soft-deleting the first attributed call must not allow a second bump."""
    with app.app_context():
        svc = CallLogService()
        entry = svc.log_call(
            lead_id,
            'answered',
            None,
            'saw the ad',
            actor='test-user',
            facebook_campaign_id=fb_campaign,
        )
        entry.is_deleted = True
        db.session.add(entry)
        db.session.commit()

        svc.log_call(
            lead_id,
            'voicemail',
            None,
            'again',
            actor='test-user',
            facebook_campaign_id=fb_campaign,
        )
        camp = FacebookAdCampaign.query.get(fb_campaign)
        assert camp.response_count == 1


def test_archived_campaign_not_attributed(app, fb_campaign, lead_id):
    with app.app_context():
        camp = FacebookAdCampaign.query.get(fb_campaign)
        camp.status = 'ARCHIVED_LOCAL'
        db.session.add(camp)
        db.session.commit()

        CallLogService().log_call(
            lead_id,
            'answered',
            None,
            'stale',
            actor='test-user',
            facebook_campaign_id=fb_campaign,
        )
        camp = FacebookAdCampaign.query.get(fb_campaign)
        assert camp.response_count == 0
        entry = (
            LeadTimelineEntry.query.filter_by(lead_id=lead_id, event_type='call_logged')
            .order_by(LeadTimelineEntry.id.desc())
            .first()
        )
        assert not (entry.event_metadata or {}).get('attributed_to_facebook')


def test_dashboard_includes_facebook_row(app, fb_campaign):
    with app.app_context():
        payload = ChannelRoiService().get_dashboard()
        ids = [r['id'] for r in payload['facebook_campaigns']]
        assert fb_campaign in ids
        assert 'direct_mail' in payload['channels']
        assert 'facebook' in payload['channels']
