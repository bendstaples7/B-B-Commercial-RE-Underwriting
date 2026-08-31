"""Integration-ish tests for Facebook call attribution on Channel ROI."""
from decimal import Decimal

import pytest

from app import db
from app.models.facebook_ad_campaign import FacebookAdCampaign
from app.models.lead import Lead
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
        # leave lead — tests use unique street; cascade cleanup optional


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


def test_dashboard_includes_facebook_row(app, fb_campaign):
    with app.app_context():
        payload = ChannelRoiService().get_dashboard()
        ids = [r['id'] for r in payload['facebook_campaigns']]
        assert fb_campaign in ids
        assert 'direct_mail' in payload['channels']
        assert 'facebook' in payload['channels']
