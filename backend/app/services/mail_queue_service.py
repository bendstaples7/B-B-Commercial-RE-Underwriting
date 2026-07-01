"""Mail queue service — enqueue leads and gate batch sends."""
from __future__ import annotations

import logging
from datetime import datetime

from app import db
from app.exceptions import MailQueueError
from app.models import Lead, MailQueueItem
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.services.lead_timeline_service import LeadTimelineService
from app.services.open_letter_config_service import OpenLetterConfigService
from app.services.open_letter_contact_mapper import validate_lead_mail_address
from app.services.scoring_rubric import is_recently_sold

logger = logging.getLogger(__name__)


class MailQueueService:
    """Manage the direct-mail queue."""

    def __init__(self):
        self._config_service = OpenLetterConfigService()
        self._timeline = LeadTimelineService()

    def _queued_query(self, user_id: str | None = None):
        q = MailQueueItem.query.filter_by(status='queued')
        if user_id:
            q = q.filter_by(user_id=user_id)
        return q

    def get_summary(self, user_id: str | None = None) -> dict:
        if not user_id:
            batch_minimum, allow_below, cost_per_piece = 50, False, None
        else:
            settings = self._config_service.get_readonly_settings(user_id)
            batch_minimum = settings['batch_minimum']
            allow_below = settings['allow_send_below_minimum']
            cost_per_piece = settings['estimated_cost_per_piece']
        queued_count = self._queued_query(user_id).count()
        can_send = bool(
            user_id
            and self._config_service.is_configured(user_id)
            and queued_count > 0
            and (queued_count >= batch_minimum or allow_below)
        )
        return {
            'queued_count': queued_count,
            'batch_minimum': batch_minimum,
            'allow_send_below_minimum': allow_below,
            'can_send': can_send,
            'estimated_cost_per_piece': cost_per_piece,
            'estimated_total': (
                round(queued_count * cost_per_piece, 2)
                if cost_per_piece is not None else None
            ),
        }

    def list_queued(self, user_id: str | None = None) -> list[MailQueueItem]:
        return (
            self._queued_query(user_id)
            .order_by(MailQueueItem.created_at.asc())
            .all()
        )

    def enqueue_leads(self, lead_ids: list[int], user_id: str) -> dict:
        if not lead_ids:
            raise MailQueueError('lead_ids is required')

        added = 0
        skipped = 0
        invalid = 0
        results = []

        for lead_id in lead_ids:
            lead = Lead.query.get(lead_id)
            if lead is None:
                skipped += 1
                results.append({'lead_id': lead_id, 'status': 'not_found'})
                continue

            if lead.owner_user_id != user_id:
                skipped += 1
                results.append({'lead_id': lead_id, 'status': 'not_authorized'})
                continue

            if is_recently_sold(lead):
                skipped += 1
                results.append({'lead_id': lead_id, 'status': 'recently_sold'})
                continue

            existing = MailQueueItem.query.filter_by(
                lead_id=lead_id, status='queued', user_id=user_id,
            ).first()
            if existing:
                skipped += 1
                results.append({'lead_id': lead_id, 'status': 'already_queued'})
                continue

            error = validate_lead_mail_address(lead)
            if error:
                item = MailQueueItem(
                    lead_id=lead_id,
                    user_id=user_id,
                    status='invalid_address',
                    validation_error=error,
                )
                db.session.add(item)
                invalid += 1
                results.append({'lead_id': lead_id, 'status': 'invalid_address', 'error': error})
                continue

            item = MailQueueItem(lead_id=lead_id, user_id=user_id, status='queued')
            db.session.add(item)
            lead.up_next_to_mail = True
            self._timeline.append(
                lead_id=lead_id,
                event_type='mail_queued',
                actor=user_id,
                summary='Added to mail queue',
                metadata={'queue_item_id': None},
                source='system',
            )
            added += 1
            results.append({'lead_id': lead_id, 'status': 'queued'})

        db.session.commit()
        return {'added': added, 'skipped': skipped, 'invalid': invalid, 'results': results}

    def remove_item(self, item_id: int, user_id: str) -> MailQueueItem:
        item = MailQueueItem.query.get(item_id)
        if item is None:
            raise MailQueueError('Queue item not found', status_code=404)
        if item.user_id != user_id:
            raise MailQueueError('Queue item not found', status_code=404)
        if item.status != 'queued':
            raise MailQueueError('Only queued items can be removed')

        item.status = 'removed'
        item.updated_at = datetime.utcnow()
        lead = Lead.query.get(item.lead_id)
        if lead and not self._queued_query(user_id).filter_by(lead_id=lead.id).count():
            lead.up_next_to_mail = False
        db.session.commit()
        return item
