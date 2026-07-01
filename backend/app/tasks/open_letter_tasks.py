"""Open Letter Connect Celery task implementations."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def submit_mail_campaign(campaign_id: int) -> None:
    """Place an OLC order for a pending campaign."""
    from app import create_app
    from app.services.mail_campaign_service import MailCampaignService

    app = create_app()
    with app.app_context():
        try:
            MailCampaignService().submit_campaign(campaign_id)
        except Exception:
            logger.exception('submit_mail_campaign failed for campaign_id=%s', campaign_id)
            raise


def sync_mail_campaign_analytics(campaign_id: int) -> None:
    """Pull delivery/scan analytics from OLC."""
    from app import create_app
    from app.services.mail_campaign_service import MailCampaignService

    app = create_app()
    with app.app_context():
        try:
            MailCampaignService().sync_campaign_analytics(campaign_id)
        except Exception:
            logger.exception('sync_mail_campaign_analytics failed for campaign_id=%s', campaign_id)
            raise
