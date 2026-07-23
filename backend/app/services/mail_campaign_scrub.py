"""Scrub false ``mail_sent`` state for cancelled campaigns that never mailed."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app import db
from app.exceptions import MailQueueError
from app.models import Lead, LeadTask, MailCampaign, MailQueueItem
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.task import Task
from app.services.mail_task_lifecycle_service import is_mail_follow_up_task

logger = logging.getLogger(__name__)

_MAILED_QUEUE_STATUSES = frozenset({'sent', 'submitted', 'delivered'})
_MAILED_HISTORY_HINTS = frozenset({
    'mailed', 'delivered', 'sent', 'submitted', 'in transit', 'in_transit',
})


def _history_matches_campaign(entry: Any, campaign: MailCampaign) -> bool:
    if not isinstance(entry, dict):
        return False
    if entry.get('campaign_id') == campaign.id:
        return True
    if campaign.olc_order_id and str(entry.get('olc_order_id') or '') == str(campaign.olc_order_id):
        return True
    return False


def _timeline_matches_campaign(meta: Any, campaign: MailCampaign) -> bool:
    if not isinstance(meta, dict):
        return False
    try:
        if int(meta.get('campaign_id')) == int(campaign.id):
            return True
    except (TypeError, ValueError):
        pass
    if campaign.olc_order_id and str(meta.get('olc_order_id') or '') == str(campaign.olc_order_id):
        return True
    return False


def _entry_looks_mailed(entry: dict) -> bool:
    for key in ('status', 'mail_status', 'delivery_status', 'olc_status'):
        raw = entry.get(key)
        if raw is None:
            continue
        if str(raw).strip().lower() in _MAILED_HISTORY_HINTS:
            return True
    return False


def _campaign_appears_mailed(campaign: MailCampaign) -> bool:
    """True when queue/history evidence suggests mail may have left the building."""
    items = MailQueueItem.query.filter_by(campaign_id=campaign.id).all()
    if any((item.status or '') in _MAILED_QUEUE_STATUSES for item in items):
        return True

    for lead in Lead.query.filter(Lead.mailer_history.isnot(None)).yield_per(500):
        history = lead.mailer_history
        entries = history if isinstance(history, list) else ([history] if history else [])
        for entry in entries:
            if not _history_matches_campaign(entry, campaign):
                continue
            if isinstance(entry, dict) and _entry_looks_mailed(entry):
                return True
    return False


def scrub_unsent_cancelled_campaign(
    campaign_id: int,
    *,
    apply: bool = False,
    force: bool = False,
    actor: str = 'system',
) -> dict[str, Any]:
    """Remove false send artifacts for a cancelled campaign that did not mail.

    Clears matching ``mailer_history`` dict entries, soft-deletes ``mail_sent``
    timeline rows, cancels **undated** mail follow-up tasks only for leads whose
    history for this campaign was removed, and restores ``up_next_to_mail`` for
    leads still in the Ready-to-Mail queue.

    Refuses when queue/history evidence suggests the campaign may have mailed,
    unless ``force=True``.
    """
    del actor  # reserved for future timeline audit rows
    campaign = db.session.get(MailCampaign, campaign_id)
    if campaign is None:
        raise MailQueueError(f'Campaign {campaign_id} not found', status_code=404)
    if campaign.status != 'cancelled':
        raise MailQueueError(
            f'Campaign {campaign_id} status is {campaign.status}; scrub requires cancelled',
            status_code=409,
        )
    if not force and _campaign_appears_mailed(campaign):
        raise MailQueueError(
            f'Campaign {campaign_id} has mailed/sent evidence; '
            'pass force=True / --force to scrub anyway',
            status_code=409,
        )

    lead_ids: set[int] = set()

    for item in MailQueueItem.query.filter_by(campaign_id=campaign.id).all():
        lead_ids.add(item.lead_id)

    candidate_leads = (
        Lead.query
        .filter(Lead.mailer_history.isnot(None))
        .yield_per(500)
    )
    for lead in candidate_leads:
        history = lead.mailer_history
        entries = history if isinstance(history, list) else ([history] if history else [])
        if any(_history_matches_campaign(e, campaign) for e in entries):
            lead_ids.add(lead.id)

    matching_timeline: list[LeadTimelineEntry] = []
    for row in (
        LeadTimelineEntry.query
        .filter_by(event_type='mail_sent', is_deleted=False)
        .order_by(LeadTimelineEntry.id.asc())
        .all()
    ):
        if _timeline_matches_campaign(row.event_metadata, campaign):
            matching_timeline.append(row)
            lead_ids.add(row.lead_id)

    history_removed = 0
    up_next_restored = 0
    follow_ups_cancelled = 0
    now = datetime.now(timezone.utc)

    for lead_id in sorted(lead_ids):
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            continue

        removed_here = 0
        history = lead.mailer_history
        if isinstance(history, list):
            kept = []
            for entry in history:
                if _history_matches_campaign(entry, campaign):
                    removed_here += 1
                else:
                    kept.append(entry)
            if removed_here:
                history_removed += removed_here
                if apply:
                    lead.mailer_history = kept

        # Only cancel undated pending follow-ups when this campaign's false
        # history was removed — do not wipe dated follow-ups from real mail.
        if removed_here:
            open_follow_ups = [
                t for t in LeadTask.query.filter_by(lead_id=lead_id, status='open').all()
                if is_mail_follow_up_task(t) and t.due_date is None
            ]
            follow_ups_cancelled += len(open_follow_ups)
            if apply:
                for task in open_follow_ups:
                    task.status = 'cancelled'
                    task.completed_at = now
                    for mirror in Task.query.filter(
                        Task.lead_id == lead_id,
                        Task.status.in_(['open', 'overdue']),
                        Task.title == task.title,
                    ).all():
                        mirror.status = 'cancelled'
                        mirror.updated_at = now

        still_queued = MailQueueItem.query.filter_by(
            lead_id=lead_id, status='queued',
        ).first()
        if still_queued is not None and not lead.up_next_to_mail:
            up_next_restored += 1
            if apply:
                lead.up_next_to_mail = True

    timeline_deleted = len(matching_timeline)
    if apply:
        for row in matching_timeline:
            row.is_deleted = True
            row.summary = '[deleted]'
        db.session.commit()

    result = {
        'campaign_id': campaign.id,
        'olc_order_id': campaign.olc_order_id,
        'apply': apply,
        'force': force,
        'leads_touched': len(lead_ids),
        'history_entries_removed': history_removed,
        'timeline_mail_sent_deleted': timeline_deleted,
        'follow_ups_cancelled': follow_ups_cancelled,
        'up_next_restored': up_next_restored,
    }
    logger.info('scrub_unsent_cancelled_campaign: %s', result)
    return result
