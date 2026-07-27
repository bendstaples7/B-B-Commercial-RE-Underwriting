"""Tests for one-shot mail campaign creative backfill (admin/script path)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_backfill_campaign_creative_nearest_sibling_not_newest(app):
    with app.app_context():
        from app import db
        from app.models.mail_campaign import MailCampaign
        from app.services.mail_campaign_service import MailCampaignService

        now = datetime.now(timezone.utc)
        near = MailCampaign(
            status='submitted',
            lead_count=1,
            created_by='user-1',
            olc_order_id='100',
            submitted_at=now - timedelta(days=2),
            creative={
                'sender_display_name': 'Near Sibling',
                'envelope_color': 'A6 Blue Mosaic',
                'label': 'Near',
            },
        )
        newest = MailCampaign(
            status='submitted',
            lead_count=1,
            created_by='user-1',
            olc_order_id='101',
            submitted_at=now,
            creative={
                'sender_display_name': 'Newest Sibling',
                'envelope_color': 'Wrong Era',
                'label': 'Newest',
            },
        )
        target = MailCampaign(
            status='cancelled',
            lead_count=1,
            created_by='user-1',
            olc_order_id='99',
            submitted_at=now - timedelta(days=3),
            creative=None,
        )
        db.session.add_all([near, newest, target])
        db.session.commit()

        changed = MailCampaignService().backfill_campaign_creative(target)
        assert changed is True
        assert target.creative['sender_display_name'] == 'Near Sibling'
        assert target.creative['backfilled_from_campaign_id'] == near.id
        assert MailCampaignService().backfill_campaign_creative(target) is False


def test_backfill_campaign_creative_rejects_far_sibling(app):
    with app.app_context():
        from app import db
        from app.models.mail_campaign import MailCampaign
        from app.services.mail_campaign_service import MailCampaignService

        now = datetime.now(timezone.utc)
        far = MailCampaign(
            status='submitted',
            lead_count=1,
            created_by='user-1',
            olc_order_id='100',
            submitted_at=now - timedelta(days=90),
            creative={'sender_display_name': 'Far', 'label': 'Far'},
        )
        target = MailCampaign(
            status='cancelled',
            lead_count=1,
            created_by='user-1',
            olc_order_id='99',
            submitted_at=now,
            creative=None,
        )
        db.session.add_all([far, target])
        db.session.commit()

        # No config for user-1 → cannot fall back; nearest sibling outside window.
        changed = MailCampaignService().backfill_campaign_creative(
            target, max_sibling_age_days=30,
        )
        assert changed is False
        assert target.creative is None


def test_list_campaigns_does_not_write_creative(app):
    with app.app_context():
        from app import db
        from app.models.mail_campaign import MailCampaign
        from app.services.mail_campaign_service import MailCampaignService

        donor = MailCampaign(
            status='submitted',
            lead_count=1,
            created_by='user-1',
            olc_order_id='100',
            submitted_at=datetime.now(timezone.utc),
            creative={'sender_display_name': 'Donor', 'label': 'Donor'},
        )
        blank = MailCampaign(
            status='cancelled',
            lead_count=1,
            created_by='user-1',
            olc_order_id='99',
            submitted_at=datetime.now(timezone.utc),
            creative=None,
        )
        db.session.add_all([donor, blank])
        db.session.commit()
        blank_id = blank.id

        items, total = MailCampaignService().list_campaigns('user-1')
        assert total == 2
        assert len(items) == 2
        reloaded = MailCampaign.query.get(blank_id)
        assert reloaded.creative is None
