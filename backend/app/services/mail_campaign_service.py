"""Mail campaign service — submit OLC orders and update leads."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from app import db
from app.exceptions import ExternalServiceError, MailQueueError
from app.models import Lead, MailCampaign, MailQueueItem, MarketingListMember
from app.services.lead_timeline_service import LeadTimelineService
from app.services.open_letter_config_service import OpenLetterConfigService
from app.services.open_letter_contact_mapper import lead_to_olc_contact
from app.services.mail_task_lifecycle_service import (
    complete_tasks_superseded_by_mail,
    refresh_leads_after_mail_task_changes,
    schedule_mail_follow_up_task,
)
from app.services.hubspot_task_completion_service import sync_pending_hubspot_completions

logger = logging.getLogger(__name__)


class MailCampaignService:
    """Create and submit mail campaigns via Open Letter Connect."""

    def __init__(self):
        self._config_service = OpenLetterConfigService()
        self._timeline = LeadTimelineService()

    def create_and_dispatch_send(self, user_id: str, *, force: bool = False) -> MailCampaign:
        config = self._config_service.require_config(user_id)
        queued = MailQueueItem.query.filter_by(
            status='queued', user_id=user_id,
        ).order_by(MailQueueItem.created_at.asc()).all()

        if not queued:
            raise MailQueueError('Mail queue is empty')

        if not force and len(queued) < config.batch_minimum and not config.allow_send_below_minimum:
            raise MailQueueError(
                f'Queue has {len(queued)} leads; minimum is {config.batch_minimum}',
            )
        if not config.default_product_id or not config.default_template_id:
            raise MailQueueError('Default product and template must be configured before sending')

        campaign = MailCampaign(
            status='pending',
            lead_count=len(queued),
            product_id=config.default_product_id,
            template_id=config.default_template_id,
            template_name=config.default_template_name,
            created_by=user_id,
        )
        db.session.add(campaign)
        db.session.flush()

        for item in queued:
            item.campaign_id = campaign.id

        db.session.commit()

        from celery import current_app as celery_app  # noqa: PLC0415
        celery_app.send_task('open_letter.submit_campaign', args=[campaign.id])
        logger.info('Dispatched open_letter.submit_campaign for campaign_id=%s', campaign.id)
        return campaign

    def submit_campaign(self, campaign_id: int) -> MailCampaign:
        """Called by Celery — place OLC order and update leads."""
        campaign = MailCampaign.query.get(campaign_id)
        if campaign is None:
            raise MailQueueError(f'Campaign {campaign_id} not found', status_code=404)

        config = self._config_service.require_config(campaign.created_by)
        olc = self._config_service.get_client(campaign.created_by)

        items = MailQueueItem.query.filter_by(
            campaign_id=campaign.id, status='queued',
        ).all()
        if not items:
            campaign.status = 'failed'
            campaign.error_message = 'No queued items for campaign'
            db.session.commit()
            return campaign

        contacts = []
        lead_by_item: dict[int, Lead] = {}
        for item in items:
            lead = Lead.query.get(item.lead_id)
            if lead is None:
                item.status = 'failed'
                item.validation_error = 'Lead not found'
                continue
            contacts.append(lead_to_olc_contact(lead, user_id=item.user_id))
            lead_by_item[item.id] = lead

        if not contacts:
            campaign.status = 'failed'
            campaign.error_message = 'No valid contacts to send'
            db.session.commit()
            return campaign

        campaign.lead_count = len(contacts)

        payload = {
            'contacts': contacts,
            'productId': campaign.product_id,
            'templateId': campaign.template_id,
            'name': f'Platform batch {campaign.id}',
        }
        if config.return_address:
            payload['returnAddress'] = config.return_address

        try:
            result = olc.place_order(payload)
        except Exception as exc:
            logger.exception('OLC place_order failed for campaign %s', campaign.id)
            campaign.status = 'failed'
            campaign.error_message = str(exc)[:2000]
            for item in items:
                if item.status == 'queued':
                    item.status = 'failed'
            db.session.commit()
            raise

        data = result.get('data') or {}
        campaign.olc_order_id = str(data.get('id') or '')
        campaign.status = 'submitted'
        campaign.submitted_at = datetime.now(timezone.utc)
        cost = data.get('cost')
        if cost is not None:
            campaign.cost = Decimal(str(cost))
            if campaign.lead_count:
                campaign.cost_per_piece = campaign.cost / campaign.lead_count
                config.estimated_cost_per_piece = campaign.cost_per_piece

        now_iso = campaign.submitted_at.isoformat()
        sent_lead_ids: list[int] = []
        hubspot_sync_ids: list[str] = []
        for item in items:
            if item.status != 'queued':
                continue
            item.status = 'sent'
            item.updated_at = datetime.utcnow()
            lead = lead_by_item.get(item.id)
            if not lead:
                continue

            lead.up_next_to_mail = False
            history = lead.mailer_history
            if not isinstance(history, list):
                history = [] if history is None else [history]
            history.append({
                'campaign_id': campaign.id,
                'olc_order_id': campaign.olc_order_id,
                'sent_at': now_iso,
                'template_id': campaign.template_id,
                'template_name': campaign.template_name,
            })
            lead.mailer_history = history

            _completed, pending_sync = complete_tasks_superseded_by_mail(
                lead.id, actor=campaign.created_by, commit=False,
            )
            hubspot_sync_ids.extend(pending_sync)

            schedule_mail_follow_up_task(
                lead=lead,
                sent_at=campaign.submitted_at,
                actor=campaign.created_by,
                campaign_id=campaign.id,
            )
            sent_lead_ids.append(lead.id)

            MarketingListMember.query.filter_by(lead_id=lead.id).filter(
                MarketingListMember.outreach_status == 'not_contacted',
            ).update({'outreach_status': 'contacted'})

            self._timeline.append(
                lead_id=lead.id,
                event_type='mail_sent',
                actor=campaign.created_by,
                summary=f'Mailer sent (campaign {campaign.id})',
                metadata={
                    'campaign_id': campaign.id,
                    'olc_order_id': campaign.olc_order_id,
                    'template_name': campaign.template_name,
                },
                source='system',
            )

        db.session.commit()
        sync_pending_hubspot_completions(hubspot_sync_ids)
        refresh_leads_after_mail_task_changes(sent_lead_ids)
        return campaign

    def sync_campaign_analytics(self, campaign_id: int) -> MailCampaign:
        campaign = MailCampaign.query.get(campaign_id)
        if campaign is None or not campaign.olc_order_id:
            raise MailQueueError(f'Campaign {campaign_id} not found or not submitted', status_code=404)

        client = self._config_service.get_client(campaign.created_by)
        result = client.get_order_analytics(campaign.olc_order_id)
        data = result.get('data') or {}

        campaign.delivery_stats = data.get('orderItemStatuses')
        geo = data.get('geoChart') or {}
        campaign.scan_stats = {
            'scanned': geo.get('scannedOrderItems'),
            'not_scanned': geo.get('notScannedOrderItems'),
        }
        campaign.analytics_synced_at = datetime.now(timezone.utc)

        mailed = (campaign.delivery_stats or {}).get('Mailed', 0)
        delivered = (campaign.delivery_stats or {}).get('Delivered', 0)
        if mailed or delivered:
            campaign.status = 'mailed'

        db.session.commit()
        return campaign

    def list_campaigns(self, user_id: str, page: int = 1, per_page: int = 25) -> tuple[list[MailCampaign], int]:
        page = max(1, page)
        per_page = max(1, min(per_page, 100))
        q = (
            MailCampaign.query
            .filter_by(created_by=user_id)
            .order_by(MailCampaign.created_at.desc())
        )
        total = q.count()
        items = q.offset((page - 1) * per_page).limit(per_page).all()
        return items, total

    def get_campaign(self, campaign_id: int, user_id: str) -> MailCampaign:
        campaign = MailCampaign.query.get(campaign_id)
        if campaign is None or campaign.created_by != user_id:
            raise MailQueueError('Campaign not found', status_code=404)
        return campaign

    def get_recent_for_lead(self, lead_id: int, user_id: str, days: int = 90) -> list[MailCampaign]:
        from datetime import timedelta

        lead = Lead.query.get(lead_id)
        if lead is None or lead.owner_user_id != user_id:
            raise MailQueueError('Lead not found', status_code=404)

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return (
            MailCampaign.query
            .join(MailQueueItem, MailQueueItem.campaign_id == MailCampaign.id)
            .filter(
                MailQueueItem.lead_id == lead_id,
                MailQueueItem.status == 'sent',
                MailCampaign.created_by == user_id,
                MailCampaign.submitted_at >= cutoff,
            )
            .order_by(MailCampaign.submitted_at.desc())
            .distinct()
            .all()
        )

    def record_call_attribution(self, campaign_id: int, lead_id: int, user_id: str) -> None:
        campaign = MailCampaign.query.get(campaign_id)
        if campaign is None or campaign.created_by != user_id:
            return
        sent = MailQueueItem.query.filter_by(
            campaign_id=campaign_id, lead_id=lead_id, status='sent',
        ).first()
        if sent is None:
            return
        from app.models.lead_timeline_entry import LeadTimelineEntry
        prior_calls = LeadTimelineEntry.query.filter_by(
            lead_id=lead_id, event_type='call_logged', is_deleted=False,
        ).all()
        attributed = sum(
            1 for e in prior_calls
            if (e.event_metadata or {}).get('mail_campaign_id') == campaign_id
            and (e.event_metadata or {}).get('attributed_to_mail')
        )
        if attributed != 1:
            return
        campaign.response_count = (campaign.response_count or 0) + 1
        db.session.commit()

    @staticmethod
    def serialize_campaign(campaign: MailCampaign) -> dict:
        delivery = campaign.delivery_stats or {}
        scan = campaign.scan_stats or {}
        scanned = scan.get('scanned') or 0
        not_scanned = scan.get('not_scanned') or 0
        scan_total = scanned + not_scanned
        return {
            'id': campaign.id,
            'olc_order_id': campaign.olc_order_id,
            'status': campaign.status,
            'lead_count': campaign.lead_count,
            'cost': float(campaign.cost) if campaign.cost is not None else None,
            'cost_per_piece': float(campaign.cost_per_piece) if campaign.cost_per_piece is not None else None,
            'product_id': campaign.product_id,
            'template_id': campaign.template_id,
            'template_name': campaign.template_name,
            'delivery_stats': delivery,
            'scan_stats': scan,
            'scan_rate': round(scanned / scan_total, 4) if scan_total else None,
            'response_count': campaign.response_count,
            'response_rate': (
                round(campaign.response_count / campaign.lead_count, 4)
                if campaign.lead_count else None
            ),
            'created_by': campaign.created_by,
            'submitted_at': campaign.submitted_at.isoformat() if campaign.submitted_at else None,
            'error_message': campaign.error_message,
            'analytics_synced_at': (
                campaign.analytics_synced_at.isoformat() if campaign.analytics_synced_at else None
            ),
            'created_at': campaign.created_at.isoformat() if campaign.created_at else None,
        }
