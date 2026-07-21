"""Mail queue service — enqueue leads and gate batch sends."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy.orm import selectinload

from app import db
from app.exceptions import MailQueueError
from app.models import Lead, MailEnqueueAttempt, MailQueueItem
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.services.lead_timeline_service import LeadTimelineService
from app.services.open_letter_config_service import OpenLetterConfigService
from app.services.open_letter_contact_mapper import (
    is_owner_mailable_lead,
    persist_embedded_address_fields,
    validate_owner_mailing_address,
)
from app.services.action_eligibility import (
    evaluate_add_to_mail_batch,
)
from app.services.scoring_rubric import effective_acquisition_date, is_recently_sold
from app.services.mail_task_lifecycle_service import (
    cancel_pending_mail_follow_up_tasks,
    complete_tasks_superseded_by_mail,
    create_pending_mail_follow_up_task,
    reconcile_recent_sale_mail_tasks_for_lead,
    refresh_leads_after_mail_task_changes,
    sync_recent_sale_hubspot_due_dates,
)
from app.services.hubspot_task_completion_service import sync_pending_hubspot_completions

logger = logging.getLogger(__name__)

MAX_MAIL_ENQUEUE_LEADS = 1000


def _candidate_limit(limit: int | None) -> int:
    """Return a positive candidate limit capped at the enqueue maximum."""
    if limit is None or limit <= 0:
        return MAX_MAIL_ENQUEUE_LEADS
    return min(limit, MAX_MAIL_ENQUEUE_LEADS)


def _refresh_rejected_leads(user_id: str, lead_ids: list[int]) -> None:
    """Rescore rejected leads without blocking production enqueue requests."""
    if not lead_ids:
        return
    if current_app.config.get('TESTING'):
        from app.services.lead_scoring_engine import LeadScoringEngine
        LeadScoringEngine().bulk_rescore(
            user_id,
            lead_ids=lead_ids,
            continue_on_error=True,
        )
        return
    try:
        from celery_worker import bulk_rescore_task
        bulk_rescore_task.delay(user_id, lead_ids)
    except Exception as exc:
        logger.warning(
            'Could not dispatch rejected mail lead rescore for %d leads: %s',
            len(lead_ids),
            exc,
            exc_info=True,
        )


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

    def list_queued(
        self,
        user_id: str | None = None,
        *,
        page: int = 1,
        per_page: int = 100,
    ) -> tuple[list[MailQueueItem], int]:
        """Return a paginated queued batch with leads eagerly loaded."""
        query = (
            self._queued_query(user_id)
            .options(selectinload(MailQueueItem.lead))
            .order_by(MailQueueItem.created_at.asc())
        )
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()
        return items, total

    @staticmethod
    def serialize_attempt(
        attempt: MailEnqueueAttempt,
        *,
        include_results: bool = True,
    ) -> dict:
        payload = {
            'id': attempt.id,
            'source_queue': attempt.source_queue,
            'requested_count': attempt.requested_count,
            'added': attempt.added_count,
            'skipped': attempt.skipped_count,
            'invalid': attempt.invalid_count,
            'created_at': (
                attempt.created_at.replace(tzinfo=timezone.utc)
                .isoformat()
                .replace('+00:00', 'Z')
                if attempt.created_at
                else None
            ),
        }
        if include_results:
            stored_results = [dict(item) for item in (attempt.results or [])]
            lead_ids = [
                item.get('lead_id')
                for item in stored_results
                if isinstance(item.get('lead_id'), int)
            ]
            leads = (
                Lead.query
                .filter(
                    Lead.id.in_(lead_ids),
                    Lead.owner_user_id == attempt.user_id,
                )
                .all()
                if lead_ids
                else []
            )
            leads_by_id = {lead.id: lead for lead in leads}
            for item in stored_results:
                lead = leads_by_id.get(item.get('lead_id'))
                if lead is None:
                    continue
                item.update({
                    'property_street': lead.property_street,
                    'owner_name': ' '.join(filter(None, (
                        lead.owner_first_name,
                        lead.owner_last_name,
                    ))) or None,
                })
            payload['results'] = stored_results
        return payload

    def list_attempts(self, user_id: str, *, limit: int = 20) -> list[dict]:
        attempts = (
            MailEnqueueAttempt.query
            .filter_by(user_id=user_id)
            .order_by(
                MailEnqueueAttempt.created_at.desc(),
                MailEnqueueAttempt.id.desc(),
            )
            .limit(limit)
            .all()
        )
        return [
            self.serialize_attempt(attempt, include_results=False)
            for attempt in attempts
        ]

    def get_attempt(self, attempt_id: int, user_id: str) -> dict:
        attempt = MailEnqueueAttempt.query.filter_by(
            id=attempt_id,
            user_id=user_id,
        ).first()
        if attempt is None:
            raise MailQueueError('Mail enqueue attempt not found', status_code=404)
        return self.serialize_attempt(attempt)

    def enqueue_leads(
        self,
        lead_ids: list[int],
        user_id: str,
        *,
        source_queue: str | None = None,
    ) -> dict:
        lead_ids = list(dict.fromkeys(lead_ids))
        if not lead_ids:
            raise MailQueueError('lead_ids is required')
        if len(lead_ids) > MAX_MAIL_ENQUEUE_LEADS:
            raise MailQueueError(
                f'No more than {MAX_MAIL_ENQUEUE_LEADS} leads may be queued at once',
                status_code=400,
            )
        normalized_source_queue = (source_queue or '').strip() or None
        if normalized_source_queue and len(normalized_source_queue) > 100:
            raise MailQueueError(
                'source_queue must be 100 characters or fewer',
                status_code=400,
            )

        added = 0
        skipped = 0
        invalid = 0
        results = []
        queued_lead_ids: list[int] = []
        rejected_lead_ids: list[int] = []
        hubspot_sync_ids: list[str] = []
        recent_sale_hubspot_sync: dict[str, str] = {}

        for lead_id in lead_ids:
            outcome: dict | None = None
            lead: Lead | None = None
            try:
                with db.session.begin_nested():
                    lead = Lead.query.get(lead_id)
                    if lead is None:
                        outcome = {'lead_id': lead_id, 'status': 'not_found'}
                    elif lead.owner_user_id != user_id:
                        outcome = {'lead_id': lead_id, 'status': 'not_authorized'}
                    elif is_recently_sold(lead):
                        sale_date = effective_acquisition_date(lead)
                        reconciliation = reconcile_recent_sale_mail_tasks_for_lead(
                            lead,
                            actor=user_id,
                            commit=False,
                        )
                        outcome = {
                            'lead_id': lead_id,
                            'status': 'recently_sold',
                            'sale_date': sale_date.isoformat() if sale_date else None,
                            'rescheduled_to': reconciliation['rescheduled_to'],
                            'rescheduled_task_count': reconciliation[
                                'rescheduled_task_count'
                            ],
                            'skip_trace_scheduled': reconciliation[
                                'skip_trace_scheduled'
                            ],
                            'skip_trace_task_id': reconciliation[
                                'skip_trace_task_id'
                            ],
                            'removed_queue_item_count': reconciliation[
                                'removed_queue_item_count'
                            ],
                            'hubspot_due_sync': reconciliation['hubspot_task_ids'],
                        }
                    elif MailQueueItem.query.filter_by(
                        lead_id=lead_id, status='queued', user_id=user_id,
                    ).first():
                        outcome = {'lead_id': lead_id, 'status': 'already_queued'}
                    else:
                        # Recent-sale and already-queued are handled above with
                        # richer outcomes; evaluate address readiness here so the
                        # Quick Action policy cannot drift from enqueue.
                        persist_embedded_address_fields(lead)
                        mail_eligibility = evaluate_add_to_mail_batch(
                            mail_eligible=is_owner_mailable_lead(lead),
                        )
                        if not mail_eligibility.ok:
                            error = (
                                validate_owner_mailing_address(lead)
                                or mail_eligibility.message
                                or 'Owner mailing address is not ready'
                            )
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
                            item = (
                                MailQueueItem.query
                                .filter_by(
                                    lead_id=lead_id,
                                    user_id=user_id,
                                    status='invalid_address',
                                )
                                .order_by(MailQueueItem.created_at.desc())
                                .first()
                            )
                            if item is None:
                                item = MailQueueItem(
                                    lead_id=lead_id,
                                    user_id=user_id,
                                    status='queued',
                                )
                            else:
                                item.status = 'queued'
                                item.validation_error = None
                            db.session.add(item)
                            db.session.flush()
                            # Canonical readiness: recommended_action == mail_ready +
                            # MailQueueItem. Do not set legacy up_next_to_mail.
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
                            create_pending_mail_follow_up_task(lead, actor=user_id)
                            # Flush remaining writes before savepoint release so
                            # success accounting only runs if the unit commits.
                            db.session.flush()
                            outcome = {
                                'lead_id': lead_id,
                                'status': 'queued',
                                'hubspot_sync': pending_sync,
                            }

                # Savepoint released successfully — record a single outcome.
                if outcome is None:
                    continue
                if lead is not None and lead.owner_user_id == user_id:
                    outcome.update({
                        'property_street': lead.property_street,
                        'owner_name': ' '.join(filter(None, (
                            lead.owner_first_name,
                            lead.owner_last_name,
                        ))) or None,
                    })
                status = outcome['status']
                if status == 'queued':
                    added += 1
                    queued_lead_ids.append(lead_id)
                    hubspot_sync_ids.extend(outcome.get('hubspot_sync') or [])
                elif status == 'invalid_address':
                    invalid += 1
                    rejected_lead_ids.append(lead_id)
                else:
                    skipped += 1
                    if status == 'recently_sold':
                        rejected_lead_ids.append(lead_id)
                        for task_id in outcome.get('hubspot_due_sync') or []:
                            if outcome.get('rescheduled_to'):
                                recent_sale_hubspot_sync[task_id] = outcome['rescheduled_to']
                        outcome.pop('hubspot_due_sync', None)
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

        audit_result_fields = {
            'lead_id',
            'status',
            'error',
            'sale_date',
            'rescheduled_to',
            'rescheduled_task_count',
            'skip_trace_scheduled',
            'skip_trace_task_id',
            'removed_queue_item_count',
        }
        audit_results = [
            {
                key: value
                for key, value in outcome.items()
                if key in audit_result_fields
            }
            for outcome in results
        ]
        attempt = MailEnqueueAttempt(
            user_id=user_id,
            source_queue=normalized_source_queue,
            requested_count=len(lead_ids),
            added_count=added,
            skipped_count=skipped,
            invalid_count=invalid,
            results=audit_results,
        )
        db.session.add(attempt)
        db.session.commit()
        sync_pending_hubspot_completions(hubspot_sync_ids)
        for task_id, due_date in recent_sale_hubspot_sync.items():
            sync_recent_sale_hubspot_due_dates(
                [task_id],
                datetime.fromisoformat(due_date).date(),
            )
        refresh_leads_after_mail_task_changes(queued_lead_ids)
        _refresh_rejected_leads(user_id, rejected_lead_ids)
        return {
            'attempt_id': attempt.id,
            'added': added,
            'skipped': skipped,
            'invalid': invalid,
            'results': results,
        }

    def preview_enqueue_candidates(self, user_id: str, *, limit: int | None = None) -> dict:
        """Dry-run validation for recommended mail candidates (no DB writes)."""
        from app.services.queue_service import QueueService

        ids = QueueService().get_mail_candidate_ids(user_id)
        ids = ids[:_candidate_limit(limit)]

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
                sale_date = effective_acquisition_date(lead)
                results.append({
                    'lead_id': lead_id,
                    'status': 'recently_sold',
                    'sale_date': sale_date.isoformat() if sale_date else None,
                    'property_street': lead.property_street,
                })
                continue
            existing = MailQueueItem.query.filter_by(
                lead_id=lead_id, status='queued', user_id=user_id,
            ).first()
            if existing:
                would_skip += 1
                results.append({'lead_id': lead_id, 'status': 'already_queued'})
                continue

            error = validate_owner_mailing_address(lead)
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
        ids = ids[:_candidate_limit(limit)]
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
        # Clear legacy flag when no queued items remain.
        if lead and not MailQueueItem.query.filter_by(lead_id=lead.id, status='queued').count():
            lead.up_next_to_mail = False
            cancel_pending_mail_follow_up_tasks(lead.id, actor=user_id)
        db.session.commit()
        if lead:
            refresh_leads_after_mail_task_changes([lead.id])
        return item
