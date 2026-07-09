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
from app.services.open_letter_contact_mapper import (
    persist_embedded_address_fields,
    validate_lead_mail_address,
)
from app.services.scoring_rubric import is_recently_sold
from app.services.mail_task_lifecycle_service import (
    complete_tasks_superseded_by_mail,
    refresh_leads_after_mail_task_changes,
)
from app.services.hubspot_task_completion_service import sync_pending_hubspot_completions

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
        queued_lead_ids: list[int] = []
        hubspot_sync_ids: list[str] = []

        for lead_id in lead_ids:
            outcome: dict | None = None
            try:
                with db.session.begin_nested():
                    lead = Lead.query.get(lead_id)
                    if lead is None:
                        outcome = {'lead_id': lead_id, 'status': 'not_found'}
                    elif lead.owner_user_id != user_id:
                        outcome = {'lead_id': lead_id, 'status': 'not_authorized'}
                    elif is_recently_sold(lead):
                        outcome = {'lead_id': lead_id, 'status': 'recently_sold'}
                    elif MailQueueItem.query.filter_by(
                        lead_id=lead_id, status='queued', user_id=user_id,
                    ).first():
                        outcome = {'lead_id': lead_id, 'status': 'already_queued'}
                    else:
                        persist_embedded_address_fields(lead)
                        error = validate_lead_mail_address(lead)
                        if error:
                            item = MailQueueItem(
                                lead_id=lead_id,
                                user_id=user_id,
                                status='invalid_address',
                                validation_error=error,
                            )
                            db.session.add(item)
                            db.session.flush()
                            outcome = {
                                'lead_id': lead_id,
                                'status': 'invalid_address',
                                'error': error,
                            }
                        else:
                            item = MailQueueItem(
                                lead_id=lead_id, user_id=user_id, status='queued',
                            )
                            db.session.add(item)
                            db.session.flush()
                            lead.up_next_to_mail = True
                            self._timeline.append(
                                lead_id=lead_id,
                                event_type='mail_queued',
                                actor=user_id,
                                summary='Added to mail queue',
                                metadata={'queue_item_id': item.id},
                                source='system',
                                commit=False,
                            )
                            _completed, pending_sync = complete_tasks_superseded_by_mail(
                                lead_id, actor=user_id, commit=False,
                            )
                            hubspot_sync_ids.extend(pending_sync)
                            # Flush remaining writes before savepoint release so
                            # success accounting only runs if the unit commits.
                            db.session.flush()
                            outcome = {'lead_id': lead_id, 'status': 'queued'}

                # Savepoint released successfully — record a single outcome.
                if outcome is None:
                    continue
                status = outcome['status']
                if status == 'queued':
                    added += 1
                    queued_lead_ids.append(lead_id)
                elif status == 'invalid_address':
                    invalid += 1
                else:
                    skipped += 1
                results.append(outcome)
            except Exception as exc:
                # Soft-fail: one bad lead must never 500 the whole batch.
                logger.warning('Failed to enqueue lead %s: %s', lead_id, exc, exc_info=True)
                skipped += 1
                results.append({
                    'lead_id': lead_id,
                    'status': 'error',
                    'error': 'Could not queue lead',
                })

        db.session.commit()
        sync_pending_hubspot_completions(hubspot_sync_ids)
        refresh_leads_after_mail_task_changes(queued_lead_ids)
        return {'added': added, 'skipped': skipped, 'invalid': invalid, 'results': results}

    def preview_enqueue_candidates(self, user_id: str, *, limit: int | None = None) -> dict:
        """Dry-run validation for recommended mail candidates (no DB writes)."""
        from app.services.queue_service import QueueService

        ids = QueueService().get_mail_candidate_ids(user_id)
        if limit is not None:
            ids = ids[:limit]

        would_add = 0
        would_skip = 0
        would_fail = 0
        results: list[dict] = []

        for lead_id in ids:
            lead = Lead.query.get(lead_id)
            if lead is None:
                would_skip += 1
                results.append({'lead_id': lead_id, 'status': 'not_found'})
                continue
            if lead.owner_user_id != user_id:
                would_skip += 1
                results.append({'lead_id': lead_id, 'status': 'not_authorized'})
                continue
            if is_recently_sold(lead):
                would_skip += 1
                results.append({'lead_id': lead_id, 'status': 'recently_sold'})
                continue
            existing = MailQueueItem.query.filter_by(
                lead_id=lead_id, status='queued', user_id=user_id,
            ).first()
            if existing:
                would_skip += 1
                results.append({'lead_id': lead_id, 'status': 'already_queued'})
                continue

            error = validate_lead_mail_address(lead)
            if error:
                would_fail += 1
                results.append({
                    'lead_id': lead_id,
                    'status': 'invalid_address',
                    'error': error,
                })
                continue

            would_add += 1
            results.append({'lead_id': lead_id, 'status': 'would_queue'})

        return {
            'dry_run': True,
            'would_add': would_add,
            'would_skip': would_skip,
            'would_fail': would_fail,
            'candidate_count': len(ids),
            'results': results,
            **self.get_summary(user_id),
        }

    def enqueue_candidates(
        self,
        user_id: str,
        *,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Enqueue recommended mail-ready leads, optionally capped by limit."""
        if dry_run:
            return self.preview_enqueue_candidates(user_id, limit=limit)

        from app.services.queue_service import QueueService

        ids = QueueService().get_mail_candidate_ids(user_id)
        if limit is not None:
            ids = ids[:limit]
        if not ids:
            return {
                'added': 0,
                'skipped': 0,
                'invalid': 0,
                'results': [],
                **self.get_summary(user_id),
            }
        return {**self.enqueue_leads(ids, user_id), **self.get_summary(user_id)}

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
        if lead and not MailQueueItem.query.filter_by(lead_id=lead.id, status='queued').count():
            lead.up_next_to_mail = False
        db.session.commit()
        return item
