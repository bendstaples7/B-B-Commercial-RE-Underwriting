"""Mail campaign service — submit OLC orders and update leads."""
from __future__ import annotations

import copy
import logging
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app import db
from app.exceptions import MailQueueError
from app.models import Lead, MailCampaign, MailQueueItem, MarketingListMember
from app.services.lead_timeline_service import LeadTimelineService
from app.services.mail_creative import (
    apply_template_style_to_preset,
    build_olc_return_address,
    creative_rollup_key,
    default_return_address_settings,
    extract_letter_body_style,
    format_mailing_line,
    get_active_preset,
    migrate_legacy_return_into_presets,
    snapshot_creative,
    street_return_address,
    template_ink_confirmed,
    validate_sender_ready,
)
from app.services.open_letter_config_service import OpenLetterConfigService
from app.services.open_letter_contact_mapper import (
    DUPLICATE_MAILING_REASON,
    OLC_OMIT_TWICE_REASON,
    OLC_SUPPORT_WORKFLOW_KEY,
    current_owner_mailing_was_returned,
    lead_has_open_olc_support_escalation,
    lead_to_owner_olc_contact,
    open_olc_support_escalation_lead_ids,
    owner_mailing_address,
    owner_mailing_dedupe_key,
    persist_embedded_address_fields,
    validate_owner_mailing_address,
)
from app.services.mail_task_lifecycle_service import (
    cancel_pending_mail_follow_up_tasks,
    complete_tasks_superseded_by_mail,
    refresh_leads_after_mail_task_changes,
    schedule_mail_follow_up_task,
)
from app.services.hubspot_task_completion_service import sync_pending_hubspot_completions

logger = logging.getLogger(__name__)

_STATUS_PRIORITY = {'Failed': 3, 'Corrected': 2, 'Verified': 1}
_FEEDBACK_QUEUE_STATUSES = ('queued', 'sent', 'failed', 'invalid_address')


def _lead_id_from_olc_recipient(recip: dict[str, Any]) -> int | None:
    """Extract lead_id from OLC recipient meta shapes (meta.data or meta_data)."""
    meta = recip.get('meta') if isinstance(recip.get('meta'), dict) else {}
    data = meta.get('data') if isinstance(meta.get('data'), dict) else {}
    lead_raw = data.get('lead_id') if isinstance(data, dict) else None
    if lead_raw is None:
        meta_data = recip.get('meta_data') if isinstance(recip.get('meta_data'), dict) else {}
        lead_raw = meta_data.get('lead_id')
    if lead_raw is None and isinstance(meta, dict):
        # Some payloads nest lead_id directly under meta
        lead_raw = meta.get('lead_id')
    try:
        return int(lead_raw) if lead_raw is not None else None
    except (TypeError, ValueError):
        return None


def collapse_recipients_by_lead(
    recipients: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Collapse OLC contact rows to one recipient per lead_id (Failed > Corrected > Verified)."""
    by_lead: dict[int, dict[str, Any]] = {}
    for recip in recipients:
        if not isinstance(recip, dict):
            continue
        lead_id = _lead_id_from_olc_recipient(recip)
        if lead_id is None:
            continue
        status = (recip.get('addressStatus') or '').strip() or 'Unknown'
        prior = by_lead.get(lead_id)
        if prior is None or _STATUS_PRIORITY.get(status, 0) > _STATUS_PRIORITY.get(
            prior.get('addressStatus') or '', 0,
        ):
            by_lead[lead_id] = recip
    return by_lead


class MailCampaignService:
    """Create and submit mail campaigns via Open Letter Connect."""

    def __init__(self):
        self._config_service = OpenLetterConfigService()
        self._timeline = LeadTimelineService()

    def _resolve_creative(self, config) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
        presets, active_id, street = migrate_legacy_return_into_presets(
            config.return_address,
            getattr(config, 'creative_presets', None),
            getattr(config, 'active_creative_preset_id', None),
        )
        if presets and not config.creative_presets:
            config.creative_presets = presets
            config.active_creative_preset_id = active_id
            if street is not None:
                config.return_address = street
        preset = get_active_preset(presets, active_id or config.active_creative_preset_id)
        street = street or street_return_address(config.return_address)
        return preset, street

    def _nearest_sibling_creative(
        self,
        campaign: MailCampaign,
        *,
        max_age_days: int = 30,
    ) -> tuple[MailCampaign, dict[str, Any]] | None:
        """Pick a same-user creative snapshot closest in time (not merely newest)."""
        from datetime import timedelta
        from sqlalchemy import and_, or_

        anchor = campaign.submitted_at or campaign.created_at
        if anchor is None:
            return None
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        window = timedelta(days=max(1, int(max_age_days)))
        window_start = anchor - window
        window_end = anchor + window
        candidates = (
            MailCampaign.query
            .filter(
                MailCampaign.created_by == campaign.created_by,
                MailCampaign.id != campaign.id,
                MailCampaign.creative.isnot(None),
            )
            .filter(or_(
                and_(
                    MailCampaign.submitted_at.isnot(None),
                    MailCampaign.submitted_at.between(window_start, window_end),
                ),
                and_(
                    MailCampaign.submitted_at.is_(None),
                    MailCampaign.created_at.isnot(None),
                    MailCampaign.created_at.between(window_start, window_end),
                ),
            ))
            .all()
        )
        best: tuple[float, MailCampaign, dict[str, Any]] | None = None
        for sibling in candidates:
            creative = sibling.creative
            if not isinstance(creative, dict) or not creative:
                continue
            sibling_ts = sibling.submitted_at or sibling.created_at
            if sibling_ts is None:
                continue
            if sibling_ts.tzinfo is None:
                sibling_ts = sibling_ts.replace(tzinfo=timezone.utc)
            delta = abs((sibling_ts - anchor).total_seconds())
            if delta > window.total_seconds():
                continue
            if best is None or delta < best[0]:
                best = (delta, sibling, creative)
        if best is None:
            return None
        return best[1], best[2]

    def backfill_campaign_creative(
        self,
        campaign: MailCampaign,
        *,
        commit: bool = True,
        max_sibling_age_days: int = 30,
    ) -> bool:
        """One-shot fill for missing ``campaign.creative`` (admin/script only).

        Prefer a same-user sibling within ``max_sibling_age_days`` of this campaign's
        submit/create time (nearest, not newest). Otherwise snapshot current config
        without persisting config migrations. Never call from list/get — those stay
        read-only.
        """
        if isinstance(campaign.creative, dict) and campaign.creative:
            return False

        source: dict[str, Any] | None = None
        nearest = self._nearest_sibling_creative(
            campaign, max_age_days=max_sibling_age_days,
        )
        if nearest is not None:
            sibling, creative = nearest
            source = copy.deepcopy(creative)
            source['backfilled_from_campaign_id'] = sibling.id
        else:
            try:
                config = self._config_service.require_config(campaign.created_by)
            except Exception:
                logger.exception(
                    'Cannot backfill creative for campaign %s — config unavailable',
                    campaign.id,
                )
                return False
            # Read-only resolve: do not mutate open_letter_config on this path.
            presets, active_id, street = migrate_legacy_return_into_presets(
                config.return_address,
                getattr(config, 'creative_presets', None),
                getattr(config, 'active_creative_preset_id', None),
            )
            preset = get_active_preset(
                presets, active_id or getattr(config, 'active_creative_preset_id', None),
            )
            street = street or street_return_address(config.return_address)
            source = snapshot_creative(
                preset,
                template_id=campaign.template_id or config.default_template_id,
                template_name=campaign.template_name or config.default_template_name,
                product_id=campaign.product_id or config.default_product_id,
                envelope_type=(preset or {}).get('envelope_color'),
            )
            if source is not None and street is not None:
                source['return_address'] = dict(street)
            if source is not None:
                source['backfilled_from'] = 'open_letter_config'

        if not source:
            return False

        campaign.creative = source
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(campaign, 'creative')
        if commit:
            db.session.commit()
        logger.info(
            'Backfilled creative for campaign %s (keys=%s)',
            campaign.id, sorted(source.keys()),
        )
        return True

    # Back-compat alias for scripts/tests that still import the old name.
    ensure_campaign_creative = backfill_campaign_creative

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

        preset, street = self._resolve_creative(config)
        sender_err = validate_sender_ready(preset)
        if sender_err:
            raise MailQueueError(sender_err)
        if not street:
            raise MailQueueError(
                'Set a complete return street address (street, city, state, ZIP) before sending',
            )

        template_id = config.default_template_id
        template_name = config.default_template_name
        if preset and preset.get('olc_template_id'):
            template_id = preset['olc_template_id']
            template_name = preset.get('olc_template_name') or template_name

        style = None
        if template_id:
            try:
                client = self._config_service.get_client(user_id)
                design = client.fetch_template_design(template_id)
                style = extract_letter_body_style(design)
            except Exception as exc:  # noqa: BLE001
                logger.warning('Could not auto-confirm template style for send: %s', exc)
                style = None
        if not template_ink_confirmed(style):
            raise MailQueueError(
                'Could not confirm letter ink from the Open Letter template. '
                'Check the template in Connect, then retry.',
            )
        preset = apply_template_style_to_preset(preset, style)
        if not (preset or {}).get('font_color'):
            raise MailQueueError(
                'Could not confirm letter ink from the Open Letter template. '
                'Check the template in Connect, then retry.',
            )

        staged = len(queued)
        campaign = MailCampaign(
            status='pending',
            lead_count=staged,
            staged_count=staged,
            submitted_count=None,
            invalid_at_submit_count=None,
            product_id=config.default_product_id,
            template_id=template_id,
            template_name=template_name,
            creative=snapshot_creative(
                preset,
                template_id=template_id,
                template_name=template_name,
                product_id=config.default_product_id,
                envelope_type=(preset or {}).get('envelope_color'),
            ),
            created_by=user_id,
        )
        if campaign.creative is not None:
            # Freeze the full sender payload, including the street address, before
            # dispatching. A later config edit must not alter an in-flight order.
            campaign.creative['return_address'] = dict(street)
        db.session.add(campaign)
        db.session.flush()

        for item in queued:
            item.campaign_id = campaign.id

        db.session.commit()

        from celery import current_app as celery_app  # noqa: PLC0415
        async_result = celery_app.send_task('open_letter.submit_campaign', args=[campaign.id])
        logger.info(
            'Dispatched open_letter.submit_campaign for campaign_id=%s task_id=%s',
            campaign.id, getattr(async_result, 'id', None),
        )
        return campaign

    _CANCELABLE_STATUSES = frozenset({'pending', 'failed', 'submitted', 'processing'})

    def cancel_campaign(
        self,
        campaign_id: int,
        user_id: str,
        *,
        release_queue: bool = False,
    ) -> tuple[MailCampaign, dict[str, Any]]:
        """Soft-cancel a campaign; re-queue only when OLC cancel is confirmed (or no order).

        If the campaign is already cancelled and ``release_queue`` is true, re-queue
        any remaining attached items (after the user cancelled the OLC order in Connect).
        """
        campaign = (
            MailCampaign.query
            .filter_by(id=campaign_id, created_by=user_id)
            .with_for_update()
            .first()
        )
        if campaign is None:
            raise MailQueueError('Campaign not found', status_code=404)

        if campaign.status == 'cancelled':
            if release_queue:
                return self._release_cancelled_campaign_queue(campaign, user_id)
            raise MailQueueError(
                f'Campaign {campaign_id} is already cancelled',
                status_code=409,
            )

        if campaign.status == 'mailed':
            raise MailQueueError(
                f'Campaign {campaign_id} is already mailed; cannot cancel',
                status_code=409,
            )
        if campaign.status not in self._CANCELABLE_STATUSES:
            raise MailQueueError(
                f'Campaign {campaign_id} status is {campaign.status}; cannot cancel',
                status_code=409,
            )

        # Commit the local cancellation before any network or Celery work. This
        # releases the row lock quickly and lets an in-flight submit see the
        # cancellation before it can place an order.
        prior_status = campaign.status
        order_id = str(campaign.olc_order_id) if campaign.olc_order_id else None
        campaign.status = 'cancelled'
        db.session.flush()
        db.session.commit()

        # All slow external work occurs outside the FOR UPDATE transaction.
        self._best_effort_revoke_submit(campaign_id)
        olc_cancel_ok = True
        olc_cancel_detail = 'no_olc_order'
        if order_id:
            olc_cancel_ok = False
            olc_cancel_detail = 'olc_cancel_not_attempted'
            try:
                client = self._config_service.get_client(user_id)
                result = client.cancel_order(order_id)
                olc_cancel_ok = bool(result.get('ok'))
                olc_cancel_detail = str(result.get('detail') or ('ok' if olc_cancel_ok else 'failed'))
            except Exception as exc:  # noqa: BLE001
                olc_cancel_ok = False
                olc_cancel_detail = str(exc)
                logger.warning(
                    'OLC cancel_order raised for campaign %s order %s: %s',
                    campaign_id, order_id, exc,
                )

        # A missing OLC ID is only safe to release when the job had not started
        # (pending) or already failed. submitted/processing may still be in
        # place_order, which can create an order after this local cancellation.
        do_requeue = (
            (bool(order_id) and olc_cancel_ok)
            or (not order_id and prior_status in ('pending', 'failed'))
        )
        note = f'olc_cancel: {"ok" if olc_cancel_ok else "failed"}:{olc_cancel_detail}'
        campaign = (
            MailCampaign.query
            .filter_by(id=campaign_id, created_by=user_id)
            .with_for_update()
            .first()
        )
        if campaign is None:
            raise MailQueueError('Campaign not found', status_code=404)
        if campaign.error_message:
            campaign.error_message = f'{campaign.error_message}\n{note}'
        else:
            campaign.error_message = note

        requeued_count = 0
        if do_requeue:
            requeued_count = self._requeue_campaign_items(campaign, user_id)
        else:
            self._annotate_mailer_history_cancelled(
                campaign,
                note='olc_cancel_pending_connect',
            )

        db.session.commit()

        meta = {
            'olc_cancel_ok': olc_cancel_ok,
            'olc_cancel_detail': olc_cancel_detail,
            'requeued_count': requeued_count,
            'queue_held': not do_requeue,
            'warning': (
                None
                if do_requeue
                else (
                    'Campaign cancelled locally, but the Open Letter order could not be '
                    'cancelled via API. Cancel it in Connect UI, then use Release to queue '
                    'so leads are not double-mailed.'
                )
            ),
        }
        campaign._cancel_meta = meta  # type: ignore[attr-defined]
        return campaign, meta

    @staticmethod
    def _best_effort_revoke_submit(campaign_id: int) -> None:
        """Revoke in-flight / queued ``open_letter.submit_campaign`` for this id."""
        try:
            from celery import current_app as celery_app

            inspect = celery_app.control.inspect(timeout=0.5)
            task_ids: list[str] = []
            if inspect is not None:
                for mapping in (
                    inspect.active() or {},
                    inspect.reserved() or {},
                    inspect.scheduled() or {},
                ):
                    for _worker, tasks in (mapping or {}).items():
                        for task in tasks or []:
                            if not isinstance(task, dict):
                                continue
                            req = task.get('request') or task
                            if not isinstance(req, dict):
                                continue
                            name = req.get('name') or req.get('task') or ''
                            if name != 'open_letter.submit_campaign':
                                continue
                            args = req.get('args') or []
                            kwargs = req.get('kwargs') or {}
                            try:
                                matches = (
                                    (args and int(args[0]) == campaign_id)
                                    or int(kwargs.get('campaign_id', -1)) == campaign_id
                                )
                            except (TypeError, ValueError):
                                matches = False
                            tid = req.get('id')
                            if matches and tid:
                                task_ids.append(str(tid))
            for tid in dict.fromkeys(task_ids):
                celery_app.control.revoke(tid, terminate=False)
                logger.info(
                    'Revoked open_letter.submit_campaign task_id=%s for campaign_id=%s',
                    tid, campaign_id,
                )
        except Exception:
            logger.debug(
                'Best-effort revoke of submit_campaign for %s failed',
                campaign_id,
                exc_info=True,
            )

    def _release_cancelled_campaign_queue(
        self,
        campaign: MailCampaign,
        user_id: str,
    ) -> tuple[MailCampaign, dict[str, Any]]:
        """Re-queue items for an already-cancelled campaign (after Connect cancel)."""
        requeued_count = self._requeue_campaign_items(campaign, user_id)
        db.session.commit()
        meta = {
            'olc_cancel_ok': True,
            'olc_cancel_detail': 'release_queue',
            'requeued_count': requeued_count,
            'queue_held': False,
            'warning': None,
        }
        campaign._cancel_meta = meta  # type: ignore[attr-defined]
        return campaign, meta

    def _requeue_campaign_items(self, campaign: MailCampaign, user_id: str) -> int:
        items = MailQueueItem.query.filter(
            MailQueueItem.campaign_id == campaign.id,
            MailQueueItem.status.in_(('queued', 'sent', 'failed', 'invalid_address')),
        ).all()
        lead_ids: list[int] = []
        for item in items:
            item.status = 'queued'
            item.campaign_id = None
            item.validation_error = None
            lead_ids.append(item.lead_id)

        for lead_id in dict.fromkeys(lead_ids):
            cancel_pending_mail_follow_up_tasks(lead_id, actor=user_id)
            lead = Lead.query.get(lead_id)
            if lead is not None:
                lead.up_next_to_mail = True
                self._annotate_lead_history_cancelled(lead, campaign)

        return len(items)

    def _annotate_mailer_history_cancelled(
        self,
        campaign: MailCampaign,
        *,
        note: str,
    ) -> None:
        items = MailQueueItem.query.filter_by(campaign_id=campaign.id).all()
        for item in items:
            lead = Lead.query.get(item.lead_id)
            if lead is not None:
                self._annotate_lead_history_cancelled(lead, campaign, note=note)

    @staticmethod
    def _annotate_lead_history_cancelled(
        lead: Lead,
        campaign: MailCampaign,
        *,
        note: str = 'cancelled',
    ) -> None:
        history = lead.mailer_history
        if not isinstance(history, list):
            history = [] if history is None else [history]
        updated = False
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if entry.get('campaign_id') == campaign.id or (
                campaign.olc_order_id
                and str(entry.get('olc_order_id') or '') == str(campaign.olc_order_id)
            ):
                entry['cancelled'] = True
                entry['cancel_note'] = note
                updated = True
        if not updated:
            history.append({
                'campaign_id': campaign.id,
                'olc_order_id': campaign.olc_order_id,
                'cancelled': True,
                'cancel_note': note,
            })
        lead.mailer_history = list(history)

    def redispatch_submit(self, campaign_id: int) -> MailCampaign:
        """Re-queue Celery submit for a stuck pending/failed-without-order campaign."""
        campaign = MailCampaign.query.get(campaign_id)
        if campaign is None:
            raise MailQueueError(f'Campaign {campaign_id} not found', status_code=404)
        if campaign.status == 'cancelled':
            raise MailQueueError(
                f'Campaign {campaign_id} is cancelled; cannot redispatch',
                status_code=409,
            )
        if campaign.olc_order_id:
            if campaign.status != 'submitted':
                campaign.status = 'submitted'
                campaign.error_message = None
                db.session.commit()
            return campaign
        if campaign.status not in ('pending', 'failed'):
            raise MailQueueError(
                f'Campaign {campaign_id} status is {campaign.status}; cannot redispatch',
                status_code=409,
            )
        failed_items = MailQueueItem.query.filter_by(
            campaign_id=campaign.id, status='failed',
        ).all()
        for item in failed_items:
            item.status = 'queued'
            item.validation_error = None
        queued = MailQueueItem.query.filter_by(
            campaign_id=campaign.id, status='queued',
        ).count()
        if queued == 0:
            raise MailQueueError(
                f'Campaign {campaign_id} has no queued items to submit',
                status_code=409,
            )
        campaign.status = 'pending'
        campaign.error_message = None
        db.session.commit()
        from celery import current_app as celery_app  # noqa: PLC0415
        async_result = celery_app.send_task('open_letter.submit_campaign', args=[campaign.id])
        logger.info(
            'Redispatched open_letter.submit_campaign for campaign_id=%s task_id=%s',
            campaign.id, getattr(async_result, 'id', None),
        )
        return campaign

    def submit_campaign(self, campaign_id: int) -> MailCampaign:
        """Called by Celery — place OLC order and update leads."""
        campaign = MailCampaign.query.get(campaign_id)
        if campaign is None:
            raise MailQueueError(f'Campaign {campaign_id} not found', status_code=404)

        if campaign.status == 'cancelled':
            raise MailQueueError(
                f'Campaign {campaign_id} is cancelled; refusing submit',
                status_code=409,
            )

        # Idempotent: never re-place an order or clobber a successful submit.
        if campaign.olc_order_id:
            if campaign.status in ('pending', 'failed', 'processing'):
                campaign.status = 'submitted'
                campaign.error_message = None
                if campaign.submitted_at is None:
                    campaign.submitted_at = datetime.now(timezone.utc)
                db.session.commit()
                logger.info(
                    'Repaired campaign %s to submitted (olc_order_id=%s already set)',
                    campaign.id, campaign.olc_order_id,
                )
            return campaign
        if campaign.status in ('submitted', 'processing', 'mailed'):
            return campaign

        config = self._config_service.require_config(campaign.created_by)
        olc = self._config_service.get_client(campaign.created_by)
        frozen_creative = campaign.creative if isinstance(campaign.creative, dict) else None
        if frozen_creative is not None:
            preset = dict(frozen_creative)
            frozen_return = (
                frozen_creative.get('return_address')
                or frozen_creative.get('returnAddress')
            )
            street = street_return_address(frozen_return)
        else:
            preset, street = self._resolve_creative(config)
        sender_err = validate_sender_ready(preset)
        if sender_err:
            campaign.status = 'failed'
            campaign.error_message = sender_err
            db.session.commit()
            raise MailQueueError(sender_err)

        if campaign.template_id and not (preset or {}).get('font_color'):
            try:
                style = extract_letter_body_style(
                    olc.fetch_template_design(campaign.template_id),
                )
                preset = apply_template_style_to_preset(preset, style)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    'Submit: could not refresh template style for campaign %s: %s',
                    campaign.id, exc,
                )
                style = None
            if not (preset or {}).get('font_color'):
                msg = (
                    'Could not confirm letter ink from the Open Letter template. '
                    'Check the template in Connect, then retry.'
                )
                campaign.status = 'failed'
                campaign.error_message = msg
                db.session.commit()
                raise MailQueueError(msg)
        elif not (preset or {}).get('font_color'):
            msg = 'Campaign template and confirmed ink are required before submit'
            campaign.status = 'failed'
            campaign.error_message = msg
            db.session.commit()
            raise MailQueueError(msg)

        seller_phone = (preset or {}).get('phone')
        if frozen_creative is None:
            campaign.creative = snapshot_creative(
                preset,
                template_id=campaign.template_id,
                template_name=campaign.template_name,
                product_id=campaign.product_id,
                envelope_type=(preset or {}).get('envelope_color'),
            )
            if campaign.creative is not None and street is not None:
                campaign.creative['return_address'] = dict(street)

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
        invalid_lead_ids: list[int] = []
        drop_reasons: Counter[str] = Counter()
        # Local invalids only (exclude address-dedupe requeues from invalid_at_submit).
        local_invalid_count = 0
        seen_mailing_keys: dict[str, int] = {}
        # Process lowest queue-item id first so dedupe keeps a stable winner.
        items = sorted(items, key=lambda it: it.id)
        staged_at_submit = len(items)
        if campaign.staged_count is None:
            campaign.staged_count = staged_at_submit
        support_blocked = open_olc_support_escalation_lead_ids(
            [it.lead_id for it in items],
        )
        for item in items:
            lead = Lead.query.get(item.lead_id)
            if lead is None:
                item.status = 'failed'
                item.validation_error = 'Lead not found'
                drop_reasons['Lead not found'] += 1
                local_invalid_count += 1
                continue
            persist_embedded_address_fields(lead)
            validation_error = validate_owner_mailing_address(
                lead,
                support_blocked_lead_ids=support_blocked,
            )
            if validation_error:
                item.status = 'invalid_address'
                item.validation_error = validation_error
                drop_reasons[validation_error] += 1
                local_invalid_count += 1
                cancel_pending_mail_follow_up_tasks(
                    lead.id,
                    actor=campaign.created_by,
                    reason='owner_mailing_address_invalid',
                )
                invalid_lead_ids.append(lead.id)
                from app.services.skip_trace_escalation_helpers import escalate_invalid_mail_safe
                escalate_invalid_mail_safe(
                    lead.id,
                    actor=campaign.created_by,
                    mail_queue_item_id=item.id,
                    validation_error=validation_error,
                    commit=False,
                )
                continue
            mailing_key = owner_mailing_dedupe_key(lead)
            if mailing_key and mailing_key in seen_mailing_keys:
                # Duplicate address in this batch — requeue for next send; no skip-trace.
                drop_reasons[DUPLICATE_MAILING_REASON] += 1
                item.status = 'queued'
                item.campaign_id = None
                item.validation_error = None
                item.updated_at = datetime.utcnow()
                self._timeline.append(
                    lead_id=lead.id,
                    event_type='note_added',
                    actor=campaign.created_by,
                    summary=(
                        f'Duplicate mailing address in batch {campaign.id}; '
                        'returned to mail queue'
                    ),
                    metadata={
                        'campaign_id': campaign.id,
                        'duplicate_of_queue_item_id': seen_mailing_keys[mailing_key],
                        'reason': DUPLICATE_MAILING_REASON,
                    },
                    source='system',
                    commit=False,
                )
                continue
            if mailing_key:
                seen_mailing_keys[mailing_key] = item.id
            contacts.append(lead_to_owner_olc_contact(
                lead, user_id=item.user_id, campaign_phone=seller_phone,
            ))
            lead_by_item[item.id] = lead

        # Accumulate across redispatches: invalid_address rows stay off the queued
        # query on later attempts, so overwriting would drop earlier local invalids.
        campaign.invalid_at_submit_count = (
            (campaign.invalid_at_submit_count or 0) + local_invalid_count
        )
        if drop_reasons:
            merged_summary = dict(campaign.submit_drop_summary or {})
            for reason, count in drop_reasons.items():
                merged_summary[reason] = merged_summary.get(reason, 0) + count
            campaign.submit_drop_summary = merged_summary
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(campaign, 'submit_drop_summary')

        if not contacts:
            campaign.status = 'failed'
            campaign.error_message = 'No valid contacts to send'
            campaign.submitted_count = 0
            campaign.lead_count = 0
            db.session.commit()
            refresh_leads_after_mail_task_changes(invalid_lead_ids)
            return campaign

        # Do not set submitted_count / final lead_count until place_order succeeds.
        contact_count = len(contacts)

        payload: dict[str, Any] = {
            'contacts': contacts,
            'productId': campaign.product_id,
            'templateId': campaign.template_id,
            'name': f'Platform batch {campaign.id}',
        }
        olc_return = build_olc_return_address(street, preset)
        if olc_return:
            payload['returnAddress'] = olc_return
            payload['returnAddressSettings'] = default_return_address_settings()

        # Flush local drop tallies before the cancel re-read so refresh does not
        # discard uncommitted invalid_at_submit / submit_drop_summary updates.
        db.session.flush()

        # Re-check cancel under a fresh DB read before placing the OLC order.
        db.session.refresh(campaign)
        if campaign.status == 'cancelled':
            raise MailQueueError(
                f'Campaign {campaign_id} was cancelled before place_order',
                status_code=409,
            )

        try:
            result = olc.place_order(payload)
        except Exception as exc:
            logger.exception('OLC place_order failed for campaign %s', campaign.id)
            campaign.status = 'failed'
            campaign.error_message = str(exc)[:2000]
            campaign.submitted_count = None
            failed_lead_ids: list[int] = []
            for item in items:
                if item.status == 'queued' and item.campaign_id == campaign.id:
                    item.status = 'failed'
                    lead = lead_by_item.get(item.id)
                    if lead is not None:
                        cancel_pending_mail_follow_up_tasks(
                            lead.id,
                            actor=campaign.created_by,
                            reason='mail_batch_failed',
                        )
                        failed_lead_ids.append(lead.id)
            db.session.commit()
            refresh_leads_after_mail_task_changes(failed_lead_ids + invalid_lead_ids)
            raise

        db.session.refresh(campaign)
        if campaign.status == 'cancelled':
            # Order may already exist at OLC; do not mark leads sent.
            logger.error(
                'Campaign %s cancelled during place_order; leaving queue items untouched',
                campaign.id,
            )
            if not campaign.olc_order_id:
                data = (result.get('data') or {}) if isinstance(result, dict) else {}
                oid = data.get('id')
                if oid:
                    campaign.olc_order_id = str(oid)
                    campaign.error_message = (
                        (campaign.error_message or '')
                        + '\nolc_order_placed_after_cancel — cancel in Connect'
                    ).strip()
            db.session.commit()
            raise MailQueueError(
                f'Campaign {campaign_id} was cancelled during place_order',
                status_code=409,
            )

        data = result.get('data') or {}
        campaign.olc_order_id = str(data.get('id') or '')
        campaign.status = 'submitted'
        campaign.submitted_at = datetime.now(timezone.utc)
        campaign.lead_count = contact_count
        campaign.submitted_count = contact_count
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
            if item.status != 'queued' or item.campaign_id != campaign.id:
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
                'creative': campaign.creative,
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
                    'creative': campaign.creative,
                },
                source='system',
                commit=False,
            )

        db.session.commit()
        sync_pending_hubspot_completions(hubspot_sync_ids)
        refresh_leads_after_mail_task_changes(sent_lead_ids + invalid_lead_ids)
        self._schedule_post_submit_analytics_sync(campaign.id)
        return campaign

    @staticmethod
    def _schedule_post_submit_analytics_sync(campaign_id: int) -> None:
        """Enqueue a delayed OLC analytics/address sync after successful place_order."""
        try:
            from celery import current_app as celery_app  # noqa: PLC0415
            celery_app.send_task(
                'open_letter.sync_campaign_analytics',
                args=[campaign_id],
                countdown=20 * 60,
            )
            logger.info(
                'Scheduled open_letter.sync_campaign_analytics for campaign_id=%s in 20m',
                campaign_id,
            )
        except Exception:
            logger.exception(
                'Failed to schedule post-submit analytics sync for campaign %s',
                campaign_id,
            )

    @staticmethod
    def _recipient_from_contact_row(row: Any) -> dict[str, Any]:
        if not isinstance(row, dict):
            return {}
        recip = row.get('recipient') or row.get('contact') or row
        return recip if isinstance(recip, dict) else {}

    @staticmethod
    def _lead_id_from_recipient(recip: dict[str, Any]) -> int | None:
        return _lead_id_from_olc_recipient(recip)

    @staticmethod
    def _history_has_address_feedback(lead: Lead, order_id: str, status: str) -> bool:
        history = lead.mailer_history
        if not isinstance(history, list):
            return False
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if str(entry.get('olc_order_id') or '') != str(order_id):
                continue
            if entry.get('address_feedback') == status:
                return True
        return False

    @staticmethod
    def _stamp_address_feedback(lead: Lead, order_id: str, status: str, extra: dict | None = None) -> None:
        from sqlalchemy.orm.attributes import flag_modified

        history = lead.mailer_history
        if not isinstance(history, list):
            history = [] if history is None else [history]
        else:
            history = list(history)
        stamped = False
        for idx, entry in enumerate(history):
            if not isinstance(entry, dict):
                continue
            if str(entry.get('olc_order_id') or '') != str(order_id):
                continue
            updated = dict(entry)
            updated['address_feedback'] = status
            if extra:
                updated.update(extra)
            history[idx] = updated
            stamped = True
            break
        if not stamped:
            history.append({
                'olc_order_id': order_id,
                'address_feedback': status,
                **(extra or {}),
            })
        lead.mailer_history = history
        flag_modified(lead, 'mailer_history')

    def _apply_corrected(
        self,
        lead: Lead,
        recip: dict[str, Any],
        campaign: MailCampaign,
    ) -> bool:
        street = (recip.get('address1') or '').strip()
        city = (recip.get('city') or '').strip()
        state = (recip.get('state') or '').strip()
        zip_code = (recip.get('zip') or '').strip()
        if not (street and city and state and zip_code):
            return False
        if self._history_has_address_feedback(lead, campaign.olc_order_id, 'Corrected'):
            return False
        before = {
            'mailing_address': lead.mailing_address,
            'mailing_city': lead.mailing_city,
            'mailing_state': lead.mailing_state,
            'mailing_zip': lead.mailing_zip,
        }
        changed = (
            (lead.mailing_address or '') != street
            or (lead.mailing_city or '') != city
            or (lead.mailing_state or '') != state
            or (lead.mailing_zip or '') != zip_code
        )
        if not changed:
            # Fields already match (e.g. prior partial apply) — stamp only, no new timeline
            self._stamp_address_feedback(lead, campaign.olc_order_id, 'Corrected')
            return False
        lead.mailing_address = street
        lead.mailing_city = city
        lead.mailing_state = state
        lead.mailing_zip = zip_code
        self._stamp_address_feedback(
            lead,
            campaign.olc_order_id,
            'Corrected',
            {'corrected_mailing': {'address1': street, 'city': city, 'state': state, 'zip': zip_code}},
        )
        self._timeline.append(
            lead_id=lead.id,
            event_type='note_added',
            actor=campaign.created_by,
            summary='Mail address corrected by Open Letter',
            metadata={
                'campaign_id': campaign.id,
                'olc_order_id': campaign.olc_order_id,
                'address_status': 'Corrected',
                'before': before,
                'after': {
                    'mailing_address': street,
                    'mailing_city': city,
                    'mailing_state': state,
                    'mailing_zip': zip_code,
                },
            },
            source='system',
            commit=False,
        )
        return True

    def _append_returned_line(self, lead: Lead, line: str) -> bool:
        if not line:
            return False
        if current_owner_mailing_was_returned(lead):
            return False
        existing = (lead.returned_addresses or '').strip()
        lead.returned_addresses = f'{existing}\n{line}'.strip() if existing else line
        return True

    def _queue_items_by_lead_for_feedback(
        self,
        campaign: MailCampaign,
        lead_ids: list[int],
    ) -> dict[int, MailQueueItem]:
        """Resolve queue rows for OLC feedback by lead_id.

        Prefer an item still attached to this campaign; otherwise only an
        unattached (campaign_id IS NULL) requeue row — never another campaign's item.
        """
        if not lead_ids:
            return {}
        items_by_lead: dict[int, MailQueueItem] = {}
        for item in MailQueueItem.query.filter(
            MailQueueItem.campaign_id == campaign.id,
            MailQueueItem.lead_id.in_(lead_ids),
            MailQueueItem.status.in_(_FEEDBACK_QUEUE_STATUSES),
        ).all():
            existing = items_by_lead.get(item.lead_id)
            if existing is None or item.id > existing.id:
                items_by_lead[item.lead_id] = item

        missing = [lid for lid in lead_ids if lid not in items_by_lead]
        if not missing:
            return items_by_lead
        # Only fall back to unattached requeue rows — never mutate another
        # campaign's queue item when syncing an older OLC order.
        for item in MailQueueItem.query.filter(
            MailQueueItem.lead_id.in_(missing),
            MailQueueItem.campaign_id.is_(None),
            MailQueueItem.status.in_(_FEEDBACK_QUEUE_STATUSES),
        ).all():
            existing = items_by_lead.get(item.lead_id)
            if existing is None or item.id > existing.id:
                items_by_lead[item.lead_id] = item
        return items_by_lead

    def _apply_failed(
        self,
        lead: Lead,
        item: MailQueueItem | None,
        recip: dict[str, Any],
        campaign: MailCampaign,
    ) -> bool:
        if self._history_has_address_feedback(lead, campaign.olc_order_id, 'Failed'):
            return False
        reason = (recip.get('addressFailureReason') or 'Address failed USPS validation')[:500]

        # Partial prior apply (queue flipped / returned stamped, history miss) — stamp only
        if item is not None and item.status in ('failed', 'invalid_address') and item.validation_error:
            self._stamp_address_feedback(
                lead,
                campaign.olc_order_id,
                'Failed',
                {'address_failure_reason': reason},
            )
            return False

        street, city, state, zip_code = owner_mailing_address(lead)
        line = format_mailing_line(street, city, state, zip_code)
        changed = False
        if item is not None:
            if item.status == 'sent':
                item.status = 'failed'
                item.validation_error = reason
                item.updated_at = datetime.utcnow()
                changed = True
            elif item.status == 'queued':
                # Post-cancel requeue: drop out of Ready-to-Mail into invalids UX
                item.status = 'invalid_address'
                item.validation_error = reason
                item.updated_at = datetime.utcnow()
                changed = True
                if lead.up_next_to_mail:
                    lead.up_next_to_mail = False
            elif item.status in ('failed', 'invalid_address') and not item.validation_error:
                item.validation_error = reason
                item.updated_at = datetime.utcnow()
                changed = True
        if line:
            changed = self._append_returned_line(lead, line) or changed
        self._stamp_address_feedback(
            lead,
            campaign.olc_order_id,
            'Failed',
            {'address_failure_reason': reason},
        )
        cancel_pending_mail_follow_up_tasks(
            lead.id,
            actor=campaign.created_by,
            reason='olc_address_failed',
        )
        self._timeline.append(
            lead_id=lead.id,
            event_type='note_added',
            actor=campaign.created_by,
            summary='Mail address failed USPS validation',
            metadata={
                'campaign_id': campaign.id,
                'olc_order_id': campaign.olc_order_id,
                'address_status': 'Failed',
                'reason': reason,
            },
            source='system',
            commit=False,
        )
        from app.services.skip_trace_escalation_helpers import escalate_invalid_mail_safe
        escalate_invalid_mail_safe(
            lead.id,
            actor=campaign.created_by,
            mail_queue_item_id=item.id if item is not None else None,
            olc_order_id=str(campaign.olc_order_id) if campaign.olc_order_id else None,
            validation_error=reason,
            commit=False,
        )
        return True

    @staticmethod
    def _history_has_silent_omit(lead: Lead, order_id: str) -> bool:
        history = lead.mailer_history
        if not isinstance(history, list):
            return False
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if str(entry.get('olc_order_id') or '') != str(order_id):
                continue
            if entry.get('olc_silent_omit'):
                return True
        return False

    @staticmethod
    def _silent_omit_order_ids(lead: Lead) -> set[str]:
        history = lead.mailer_history
        if not isinstance(history, list):
            return set()
        out: set[str] = set()
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if not entry.get('olc_silent_omit'):
                continue
            oid = str(entry.get('olc_order_id') or '').strip()
            if oid:
                out.add(oid)
        return out

    @staticmethod
    def _stamp_silent_omit(
        lead: Lead,
        *,
        order_id: str,
        campaign_id: int,
    ) -> None:
        from sqlalchemy.orm.attributes import flag_modified

        history = lead.mailer_history
        if not isinstance(history, list):
            history = [] if history is None else [history]
        else:
            history = list(history)
        history.append({
            'olc_order_id': str(order_id),
            'campaign_id': campaign_id,
            'olc_silent_omit': True,
            'at': datetime.now(timezone.utc).isoformat(),
        })
        lead.mailer_history = history
        flag_modified(lead, 'mailer_history')

    def _ensure_olc_support_task(self, lead: Lead, *, actor: str, campaign: MailCampaign) -> None:
        from app.models.lead_task import LeadTask

        existing = (
            LeadTask.query
            .filter_by(
                lead_id=lead.id,
                workflow_key=OLC_SUPPORT_WORKFLOW_KEY,
                status='open',
            )
            .first()
        )
        if existing is not None:
            return
        task = LeadTask(
            lead_id=lead.id,
            task_type='custom',
            title='Contact Open Letter support — address omitted twice',
            status='open',
            workflow_key=OLC_SUPPORT_WORKFLOW_KEY,
            created_by=actor or 'system',
        )
        db.session.add(task)
        self._timeline.append(
            lead_id=lead.id,
            event_type='note_added',
            actor=actor,
            summary='OLC omitted this mailing address twice — escalate to Open Letter support',
            metadata={
                'campaign_id': campaign.id,
                'olc_order_id': campaign.olc_order_id,
                'workflow_key': OLC_SUPPORT_WORKFLOW_KEY,
            },
            source='system',
            commit=False,
        )

    def _ensure_ready_to_mail_queue_item(
        self,
        lead: Lead,
        campaign: MailCampaign,
        item: MailQueueItem | None,
    ) -> MailQueueItem:
        """Return a queued, unattached queue row for the lead (create if needed)."""
        if item is not None:
            item.status = 'queued'
            item.campaign_id = None
            item.validation_error = None
            item.updated_at = datetime.utcnow()
            return item

        existing = (
            MailQueueItem.query
            .filter_by(
                lead_id=lead.id,
                user_id=campaign.created_by,
                status='queued',
            )
            .filter(MailQueueItem.campaign_id.is_(None))
            .order_by(MailQueueItem.id.desc())
            .first()
        )
        if existing is not None:
            existing.validation_error = None
            existing.updated_at = datetime.utcnow()
            return existing

        created = MailQueueItem(
            lead_id=lead.id,
            user_id=campaign.created_by,
            status='queued',
            campaign_id=None,
        )
        db.session.add(created)
        return created

    def _apply_silent_omit(
        self,
        lead: Lead,
        item: MailQueueItem | None,
        campaign: MailCampaign,
    ) -> str:
        """Handle a newly detected silent OLC omit. Returns disposition."""
        order_id = str(campaign.olc_order_id or '')
        if not order_id or self._history_has_silent_omit(lead, order_id):
            prior = len(self._silent_omit_order_ids(lead))
            if prior >= 2:
                return 'support'
            return 'requeued' if item is not None and item.status == 'queued' else 'known'

        prior_orders = self._silent_omit_order_ids(lead)
        is_second = len(prior_orders) >= 1
        self._stamp_silent_omit(lead, order_id=order_id, campaign_id=campaign.id)

        if is_second:
            if item is not None:
                item.status = 'failed'
                item.validation_error = OLC_OMIT_TWICE_REASON
                item.updated_at = datetime.utcnow()
                # Keep campaign_id for audit trail on the failed row.
            self._ensure_olc_support_task(
                lead, actor=campaign.created_by, campaign=campaign,
            )
            return 'support'

        # First omit — return to Ready-to-Mail for the next batch.
        self._ensure_ready_to_mail_queue_item(lead, campaign, item)
        self._timeline.append(
            lead_id=lead.id,
            event_type='note_added',
            actor=campaign.created_by,
            summary=(
                f'OLC omitted from order {order_id}; returned to mail queue'
            ),
            metadata={
                'campaign_id': campaign.id,
                'olc_order_id': order_id,
                'olc_silent_omit': True,
            },
            source='system',
            commit=False,
        )
        return 'requeued'

    @staticmethod
    def _tracked_reliable_for_silent_omit_heal(
        campaign: MailCampaign,
        tracked_lead_ids: set[int],
    ) -> bool:
        """Refuse heal when the OLC contact walk looks incomplete."""
        if not tracked_lead_ids:
            logger.warning(
                'Skipping silent-omit heal for campaign %s: empty tracked set',
                campaign.id,
            )
            return False
        expected = int(campaign.submitted_count or campaign.lead_count or 0)
        if expected <= 20:
            return True
        minimum = max(1, int(expected * 0.8))
        if len(tracked_lead_ids) < minimum:
            logger.warning(
                'Skipping silent-omit heal for campaign %s: tracked=%s expected>=%s '
                '(submitted_count=%s)',
                campaign.id,
                len(tracked_lead_ids),
                minimum,
                expected,
            )
            return False
        return True

    def _detect_and_heal_silent_omits(
        self,
        campaign: MailCampaign,
        tracked_lead_ids: set[int],
    ) -> list[int]:
        """Persist tracked/omitted ids and heal newly detected silent omits.

        Returns lead ids touched (for scoring refresh).
        """
        from sqlalchemy.orm.attributes import flag_modified

        tracked_list = sorted(tracked_lead_ids)
        campaign.olc_tracked_lead_ids = tracked_list
        flag_modified(campaign, 'olc_tracked_lead_ids')

        # Candidates: items we believed submitted on this campaign.
        candidates = MailQueueItem.query.filter(
            MailQueueItem.campaign_id == campaign.id,
            MailQueueItem.status.in_(('sent', 'failed')),
        ).all()
        # Also include leads already known omitted (may have been requeued).
        known_omitted = {
            int(x) for x in (campaign.olc_omitted_lead_ids or [])
            if x is not None
        }
        candidate_lead_ids = {item.lead_id for item in candidates} | known_omitted
        omitted_now = sorted(lid for lid in candidate_lead_ids if lid not in tracked_lead_ids)

        # Drop ids that are on the order now — omitted list must shrink when healed.
        campaign.olc_omitted_lead_ids = omitted_now
        flag_modified(campaign, 'olc_omitted_lead_ids')

        items_by_lead = self._queue_items_by_lead_for_feedback(campaign, omitted_now)
        # For requeued omits, campaign_id may already be null — also look up unattached.
        touch_ids: list[int] = []
        for lead_id in omitted_now:
            lead = Lead.query.get(lead_id)
            if lead is None:
                continue
            item = items_by_lead.get(lead_id)
            # Prefer sent item still on this campaign for first-omit requeue.
            if item is None or item.status not in ('sent', 'failed', 'queued', 'invalid_address'):
                item = (
                    MailQueueItem.query
                    .filter_by(lead_id=lead_id, campaign_id=campaign.id)
                    .order_by(MailQueueItem.id.desc())
                    .first()
                )
            disposition = self._apply_silent_omit(lead, item, campaign)
            if disposition in ('requeued', 'support'):
                touch_ids.append(lead_id)
        return touch_ids

    def heal_silent_omits(
        self,
        campaign_id: int,
        tracked_lead_ids: set[int],
        *,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Public entry for admin/scripts: persist + heal silent OLC omits.

        When ``dry_run`` is True, computes the omitted set without mutating and
        rolls back the session.
        """
        campaign = MailCampaign.query.get(campaign_id)
        if campaign is None:
            raise MailQueueError(f'Campaign {campaign_id} not found', status_code=404)
        if not campaign.olc_order_id:
            raise MailQueueError(
                f'Campaign {campaign_id} has no OLC order',
                status_code=400,
            )
        tracked = {int(x) for x in tracked_lead_ids}
        if not self._tracked_reliable_for_silent_omit_heal(campaign, tracked):
            return {
                'campaign_id': campaign.id,
                'dry_run': dry_run,
                'skipped': True,
                'reason': 'tracked_set_unreliable',
                'tracked': len(tracked),
                'omitted': 0,
                'touched': 0,
            }

        if dry_run:
            candidates = MailQueueItem.query.filter(
                MailQueueItem.campaign_id == campaign.id,
                MailQueueItem.status.in_(('sent', 'failed')),
            ).all()
            known = {
                int(x) for x in (campaign.olc_omitted_lead_ids or [])
                if x is not None
            }
            omitted = sorted(({i.lead_id for i in candidates} | known) - tracked)
            return {
                'campaign_id': campaign.id,
                'dry_run': True,
                'skipped': False,
                'tracked': len(tracked),
                'omitted': len(omitted),
                'omitted_lead_ids': omitted,
                'touched': 0,
            }

        touched = self._detect_and_heal_silent_omits(campaign, tracked)
        db.session.commit()
        if touched:
            refresh_leads_after_mail_task_changes(list(dict.fromkeys(touched)))
        return {
            'campaign_id': campaign.id,
            'dry_run': False,
            'skipped': False,
            'tracked': len(tracked),
            'omitted': len(campaign.olc_omitted_lead_ids or []),
            'touched': len(touched),
        }

    def _sync_order_address_statuses(
        self,
        campaign: MailCampaign,
        client,
        *,
        refresh_scoring: bool = True,
    ) -> dict[str, int]:
        summary = {'corrected': 0, 'failed': 0, 'verified': 0, 'unchanged': 0}
        recipients: list[dict[str, Any]] = []
        for row in client.iter_order_contacts(campaign.olc_order_id):
            recip = self._recipient_from_contact_row(row)
            if recip:
                recipients.append(recip)
        by_lead = collapse_recipients_by_lead(recipients)
        # Expose tracked lead ids for silent-omit detection (same contact walk).
        campaign._olc_tracked_lead_ids_computed = set(by_lead.keys())  # type: ignore[attr-defined]

        items_by_lead = self._queue_items_by_lead_for_feedback(
            campaign, list(by_lead.keys()),
        )
        touch_ids: list[int] = []
        for lead_id, recip in by_lead.items():
            status = (recip.get('addressStatus') or '').strip()
            if status == 'Verified':
                summary['verified'] += 1
                continue
            lead = Lead.query.get(lead_id)
            if lead is None:
                summary['unchanged'] += 1
                continue
            if status == 'Corrected':
                if self._apply_corrected(lead, recip, campaign):
                    summary['corrected'] += 1
                    touch_ids.append(lead_id)
                else:
                    summary['unchanged'] += 1
            elif status == 'Failed':
                if self._apply_failed(lead, items_by_lead.get(lead_id), recip, campaign):
                    summary['failed'] += 1
                    touch_ids.append(lead_id)
                else:
                    summary['unchanged'] += 1
            else:
                summary['unchanged'] += 1

        # Defer scoring refresh until after the caller commits so dry-runs can roll back
        campaign._address_feedback_touch_ids = touch_ids  # type: ignore[attr-defined]
        if refresh_scoring and touch_ids:
            refresh_leads_after_mail_task_changes(touch_ids)
        return summary

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

        # Do not resurrect cancelled campaigns from delivery stats
        if campaign.status != 'cancelled':
            mailed = (campaign.delivery_stats or {}).get('Mailed', 0)
            delivered = (campaign.delivery_stats or {}).get('Delivered', 0)
            if mailed or delivered:
                campaign.status = 'mailed'

        touch_ids: list[int] = []
        address_summary = {'corrected': 0, 'failed': 0, 'verified': 0, 'unchanged': 0}
        try:
            address_summary = self._sync_order_address_statuses(
                campaign, client, refresh_scoring=False,
            )
            touch_ids = list(getattr(campaign, '_address_feedback_touch_ids', None) or [])
        except Exception:
            logger.exception(
                'OLC address-status sync failed for campaign %s order %s',
                campaign.id, campaign.olc_order_id,
            )
            address_summary = {'corrected': 0, 'failed': 0, 'verified': 0, 'unchanged': 0}

        tracked = getattr(campaign, '_olc_tracked_lead_ids_computed', None)
        if (
            isinstance(tracked, set)
            and self._tracked_reliable_for_silent_omit_heal(campaign, tracked)
        ):
            try:
                with db.session.begin_nested():
                    healed = self._detect_and_heal_silent_omits(campaign, tracked)
                touch_ids.extend(healed)
            except Exception:
                logger.exception(
                    'OLC silent-omit heal failed for campaign %s order %s',
                    campaign.id, campaign.olc_order_id,
                )

        campaign._address_feedback_summary = address_summary  # type: ignore[attr-defined]
        campaign.address_feedback_summary = address_summary
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(campaign, 'address_feedback_summary')
        db.session.commit()
        if touch_ids:
            refresh_leads_after_mail_task_changes(list(dict.fromkeys(touch_ids)))
        return campaign

    def sync_due_campaign_analytics(self, *, limit: int = 25) -> dict[str, int]:
        """Fan-out sync for recent campaigns that need a fresh OLC pull (hourly beat)."""
        from datetime import timedelta
        from sqlalchemy import and_, or_

        limit = max(1, min(int(limit or 25), 100))
        now = datetime.now(timezone.utc)
        recent_cutoff = now - timedelta(days=90)
        terminal_cutoff = now - timedelta(days=14)
        stale_before = now - timedelta(hours=12)
        q = (
            MailCampaign.query
            .filter(MailCampaign.olc_order_id.isnot(None))
            .filter(MailCampaign.olc_order_id != '')
            .filter(MailCampaign.submitted_at.isnot(None))
            .filter(MailCampaign.submitted_at >= recent_cutoff)
            .filter(or_(
                MailCampaign.status.in_(('submitted', 'processing')),
                and_(
                    MailCampaign.status.in_(('mailed', 'cancelled')),
                    MailCampaign.submitted_at >= terminal_cutoff,
                ),
            ))
            .filter(or_(
                MailCampaign.analytics_synced_at.is_(None),
                MailCampaign.analytics_synced_at < stale_before,
            ))
            .order_by(
                MailCampaign.analytics_synced_at.asc().nullsfirst(),
                MailCampaign.submitted_at.desc().nullslast(),
            )
            .limit(limit)
        )
        synced = 0
        failed = 0
        for campaign in q.all():
            try:
                self.sync_campaign_analytics(campaign.id)
                synced += 1
            except Exception:
                logger.exception(
                    'Scheduled analytics sync failed for campaign %s', campaign.id,
                )
                failed += 1
        return {'synced': synced, 'failed': failed, 'attempted': synced + failed}

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

    def creative_rollup(self, user_id: str) -> list[dict[str, Any]]:
        """Aggregate scan/response rates by creative dimensions for the user."""
        campaigns = (
            MailCampaign.query
            .filter_by(created_by=user_id)
            .filter(MailCampaign.status.in_(('submitted', 'processing', 'mailed')))
            .all()
        )
        buckets: dict[tuple, dict[str, Any]] = {}
        for campaign in campaigns:
            dims = creative_rollup_key(campaign.creative if isinstance(campaign.creative, dict) else None)
            key = (
                dims['sender_display_name'],
                dims['envelope_color'],
                dims['font_color'],
                dims['include_email'],
                dims['include_website'],
            )
            bucket = buckets.get(key)
            if bucket is None:
                bucket = {
                    **dims,
                    'campaign_count': 0,
                    'lead_count': 0,
                    'response_count': 0,
                    'scanned': 0,
                    'scan_denom': 0,
                }
                buckets[key] = bucket
            bucket['campaign_count'] += 1
            bucket['lead_count'] += campaign.lead_count or 0
            bucket['response_count'] += campaign.response_count or 0
            scan = campaign.scan_stats or {}
            scanned = scan.get('scanned') or 0
            not_scanned = scan.get('not_scanned') or 0
            bucket['scanned'] += scanned
            bucket['scan_denom'] += scanned + not_scanned

        rows = []
        for bucket in buckets.values():
            lead_count = bucket['lead_count']
            scan_denom = bucket['scan_denom']
            rows.append({
                'sender_display_name': bucket['sender_display_name'],
                'envelope_color': bucket['envelope_color'],
                'font_color': bucket['font_color'],
                'include_email': bucket['include_email'],
                'include_website': bucket['include_website'],
                'campaign_count': bucket['campaign_count'],
                'lead_count': lead_count,
                'response_count': bucket['response_count'],
                'response_rate': (
                    round(bucket['response_count'] / lead_count, 4) if lead_count else None
                ),
                'scan_rate': (
                    round(bucket['scanned'] / scan_denom, 4) if scan_denom else None
                ),
            })
        rows.sort(key=lambda r: (-(r['lead_count'] or 0), r['sender_display_name']))
        return rows

    def get_campaign(self, campaign_id: int, user_id: str) -> MailCampaign:
        campaign = MailCampaign.query.get(campaign_id)
        if campaign is None or campaign.created_by != user_id:
            raise MailQueueError('Campaign not found', status_code=404)
        return campaign

    def list_gap_leads(
        self,
        campaign_id: int,
        user_id: str,
        *,
        kind: str,
    ) -> list[dict[str, Any]]:
        """Return lead rows for campaign gap drill-downs (invalid / OLC omitted)."""
        campaign = self.get_campaign(campaign_id, user_id)
        kind_norm = (kind or '').strip().lower()
        if kind_norm not in ('invalid_local', 'olc_omitted'):
            raise MailQueueError(
                "kind must be 'invalid_local' or 'olc_omitted'",
                status_code=400,
            )

        if kind_norm == 'invalid_local':
            items = (
                MailQueueItem.query
                .filter_by(campaign_id=campaign.id, status='invalid_address')
                .order_by(MailQueueItem.id.asc())
                .all()
            )
            rows: list[dict[str, Any]] = []
            for item in items:
                lead = Lead.query.get(item.lead_id)
                rows.append(self._serialize_gap_lead_row(
                    lead,
                    lead_id=item.lead_id,
                    reason=item.validation_error or 'Invalid address',
                    disposition='invalid_local',
                    queue_status=item.status,
                ))
            return rows

        omitted_ids = campaign.olc_omitted_lead_ids
        # Never call sync_campaign_analytics here — that walks OLC contacts and can
        # hang the dialog for minutes (or forever without a token). Prefer cache.
        if not isinstance(omitted_ids, list):
            omitted_ids = self._compute_omitted_lead_ids_from_cache(campaign)
        if not isinstance(omitted_ids, list):
            omitted_ids = []

        lids: list[int] = []
        for lead_id in omitted_ids:
            try:
                lids.append(int(lead_id))
            except (TypeError, ValueError):
                continue
        if not lids:
            return []

        leads_by_id = {
            lead.id: lead
            for lead in Lead.query.filter(Lead.id.in_(lids)).all()
        }
        queue_items = (
            MailQueueItem.query
            .filter(MailQueueItem.lead_id.in_(lids))
            .order_by(MailQueueItem.id.desc())
            .all()
        )
        # Prefer unattached queued, then this campaign, then any latest row.
        best_item: dict[int, MailQueueItem] = {}
        for item in queue_items:
            cur = best_item.get(item.lead_id)
            if cur is None:
                best_item[item.lead_id] = item
                continue
            cur_score = (
                2 if cur.status == 'queued' and cur.campaign_id is None else
                1 if cur.campaign_id == campaign.id else
                0
            )
            new_score = (
                2 if item.status == 'queued' and item.campaign_id is None else
                1 if item.campaign_id == campaign.id else
                0
            )
            if new_score > cur_score:
                best_item[item.lead_id] = item

        from app.models.lead_task import LeadTask

        support_lead_ids = {
            row.lead_id
            for row in LeadTask.query.filter(
                LeadTask.lead_id.in_(lids),
                LeadTask.workflow_key == OLC_SUPPORT_WORKFLOW_KEY,
                LeadTask.status == 'open',
            ).all()
        }
        ready_lead_ids = {
            item.lead_id
            for item in queue_items
            if item.status == 'queued' and item.campaign_id is None
        }

        rows = []
        for lid in lids:
            lead = leads_by_id.get(lid)
            omit_count = len(self._silent_omit_order_ids(lead)) if lead else 0
            item = best_item.get(lid)
            if omit_count >= 2 or (
                item is not None
                and item.status == 'failed'
                and (item.validation_error or '').startswith('OLC omitted twice')
            ):
                disposition = 'support'
                reason = OLC_OMIT_TWICE_REASON
            elif item is not None and item.status == 'queued' and item.campaign_id is None:
                disposition = 'requeued'
                reason = 'OLC omitted — returned to mail queue'
            else:
                disposition = 'omitted'
                reason = 'Not on OLC order'
            queue_status = item.status if item else None
            resolution = self._gap_lead_resolution_cached(
                lead,
                disposition=disposition,
                queue_status=queue_status,
                has_support=lid in support_lead_ids,
                is_ready=lid in ready_lead_ids,
            )
            rows.append(self._serialize_gap_lead_row(
                lead,
                lead_id=lid,
                reason=reason,
                disposition=disposition,
                queue_status=queue_status,
                omit_count=omit_count or 1,
                resolution=resolution,
            ))
        return rows

    @staticmethod
    def _compute_omitted_lead_ids_from_cache(campaign: MailCampaign) -> list[int] | None:
        """Derive omitted lead ids without calling OLC (DB cache / history only)."""
        order_id = str(campaign.olc_order_id or '')
        tracked_raw = campaign.olc_tracked_lead_ids
        tracked: set[int] = set()
        if isinstance(tracked_raw, list):
            try:
                tracked = {int(x) for x in tracked_raw if x is not None}
            except (TypeError, ValueError):
                tracked = set()

        # Leads still attached as sent/failed on this campaign.
        attached = {
            item.lead_id
            for item in MailQueueItem.query.filter(
                MailQueueItem.campaign_id == campaign.id,
                MailQueueItem.status.in_(('sent', 'failed')),
            ).all()
        }

        # Recover requeued omits via mailer_history stamps for this order.
        history_omitted: set[int] = set()
        if order_id:
            probe_ids = set(attached)
            # Only probe this campaign owner's unattached queued rows; the
            # mailer_history match below keeps recovery tied to this order.
            for item in MailQueueItem.query.filter(
                MailQueueItem.status == 'queued',
                MailQueueItem.campaign_id.is_(None),
                MailQueueItem.user_id == campaign.created_by,
            ).all():
                probe_ids.add(item.lead_id)
            if probe_ids:
                for lead in Lead.query.filter(Lead.id.in_(list(probe_ids))).all():
                    hist = lead.mailer_history
                    if not isinstance(hist, list):
                        continue
                    for entry in hist:
                        if not isinstance(entry, dict):
                            continue
                        if str(entry.get('olc_order_id') or '') != order_id:
                            continue
                        if entry.get('olc_silent_omit'):
                            history_omitted.add(lead.id)
                            break

        if tracked:
            return sorted((attached | history_omitted) - tracked)
        if history_omitted:
            return sorted(history_omitted)
        return []

    @staticmethod
    def _gap_lead_resolution_cached(
        lead: Lead | None,
        *,
        disposition: str,
        queue_status: str | None = None,
        has_support: bool = False,
        is_ready: bool = False,
    ) -> str:
        """Human label for where the lead is now (no per-row queries)."""
        if disposition == 'support' or has_support:
            return 'OLC support escalation'
        if is_ready or disposition == 'requeued':
            return 'Ready to Mail'
        if lead is not None:
            if getattr(lead, 'skip_trace_exhausted_at', None) is not None:
                return 'Skip Trace exhausted'
            if lead.lead_status == 'skip_trace' or bool(getattr(lead, 'needs_skip_trace', False)):
                return 'Skip Trace'
            status = (lead.lead_status or '').strip()
            if status:
                return status.replace('_', ' ').title()
        if queue_status == 'invalid_address':
            return 'Invalid on this batch'
        if queue_status == 'failed':
            return 'Failed on this batch'
        if queue_status == 'sent':
            return 'Still on this batch (sent)'
        return '—'

    @staticmethod
    def _gap_lead_resolution(
        lead: Lead | None,
        *,
        lead_id: int,
        disposition: str,
        queue_status: str | None = None,
    ) -> str:
        """Human label for where the lead is now (work queue / outcome)."""
        has_support = (
            disposition == 'support'
            or (lead is not None and lead_has_open_olc_support_escalation(lead_id))
        )
        is_ready = disposition == 'requeued' or (
            MailQueueItem.query
            .filter_by(lead_id=lead_id, status='queued')
            .filter(MailQueueItem.campaign_id.is_(None))
            .first()
            is not None
        )
        return MailCampaignService._gap_lead_resolution_cached(
            lead,
            disposition=disposition,
            queue_status=queue_status,
            has_support=has_support,
            is_ready=is_ready,
        )

    @staticmethod
    def _serialize_gap_lead_row(
        lead: Lead | None,
        *,
        lead_id: int,
        reason: str,
        disposition: str,
        queue_status: str | None = None,
        omit_count: int | None = None,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        owner = ''
        mailing = None
        property_street = None
        lead_status = None
        if lead is not None:
            parts = [lead.owner_first_name or '', lead.owner_last_name or '']
            owner = ' '.join(p for p in parts if p).strip()
            street, city, state, zip_code = owner_mailing_address(lead)
            mailing = format_mailing_line(street, city, state, zip_code) or None
            property_street = lead.property_street
            lead_status = lead.lead_status
        if resolution is None:
            resolution = MailCampaignService._gap_lead_resolution(
                lead,
                lead_id=lead_id,
                disposition=disposition,
                queue_status=queue_status,
            )
        payload: dict[str, Any] = {
            'lead_id': lead_id,
            'owner_name': owner or None,
            'property_street': property_street,
            'mailing_address': mailing,
            'lead_status': lead_status,
            'reason': reason,
            'disposition': disposition,
            'queue_status': queue_status,
            'resolution': resolution,
        }
        if omit_count is not None:
            payload['omit_count'] = omit_count
        return payload

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
        payload = {
            'id': campaign.id,
            'olc_order_id': campaign.olc_order_id,
            'status': campaign.status,
            'lead_count': campaign.lead_count,
            'staged_count': campaign.staged_count,
            'submitted_count': (
                campaign.submitted_count
                if campaign.submitted_count is not None
                else campaign.lead_count
            ),
            'invalid_at_submit_count': campaign.invalid_at_submit_count,
            'submit_drop_summary': campaign.submit_drop_summary,
            'olc_omitted_count': (
                len(campaign.olc_omitted_lead_ids)
                if isinstance(campaign.olc_omitted_lead_ids, list)
                else None
            ),
            'cost': float(campaign.cost) if campaign.cost is not None else None,
            'cost_per_piece': float(campaign.cost_per_piece) if campaign.cost_per_piece is not None else None,
            'product_id': campaign.product_id,
            'template_id': campaign.template_id,
            'template_name': campaign.template_name,
            'creative': campaign.creative,
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
        address_summary = getattr(campaign, '_address_feedback_summary', None)
        if address_summary is None:
            address_summary = campaign.address_feedback_summary
        if address_summary is not None:
            payload['address_feedback'] = address_summary
        cancel_meta = getattr(campaign, '_cancel_meta', None)
        if isinstance(cancel_meta, dict):
            payload['olc_cancel_ok'] = cancel_meta.get('olc_cancel_ok')
            payload['olc_cancel_detail'] = cancel_meta.get('olc_cancel_detail')
            payload['requeued_count'] = cancel_meta.get('requeued_count')
            payload['queue_held'] = cancel_meta.get('queue_held')
            if cancel_meta.get('warning'):
                payload['warning'] = cancel_meta['warning']
        return payload
