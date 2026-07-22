"""Mail campaign service — submit OLC orders and update leads."""
from __future__ import annotations

import logging
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
    validate_sender_ready,
)
from app.services.open_letter_config_service import OpenLetterConfigService
from app.services.open_letter_contact_mapper import (
    current_owner_mailing_was_returned,
    lead_to_owner_olc_contact,
    owner_mailing_address,
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
        if not style or not style.get('font_name'):
            raise MailQueueError(
                'Could not confirm letter font from the Open Letter template. '
                'Check the template in Connect, then retry.',
            )
        preset = apply_template_style_to_preset(preset, style)

        campaign = MailCampaign(
            status='pending',
            lead_count=len(queued),
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

        olc_cancel_ok = True
        olc_cancel_detail = 'no_olc_order'
        if campaign.olc_order_id:
            olc_cancel_ok = False
            olc_cancel_detail = 'olc_cancel_not_attempted'
            try:
                client = self._config_service.get_client(campaign.created_by)
                result = client.cancel_order(str(campaign.olc_order_id))
                olc_cancel_ok = bool(result.get('ok'))
                olc_cancel_detail = str(result.get('detail') or ('ok' if olc_cancel_ok else 'failed'))
            except Exception as exc:  # noqa: BLE001
                olc_cancel_ok = False
                olc_cancel_detail = str(exc)
                logger.warning(
                    'OLC cancel_order raised for campaign %s order %s: %s',
                    campaign.id, campaign.olc_order_id, exc,
                )

        note = f'olc_cancel: {"ok" if olc_cancel_ok else "failed"}:{olc_cancel_detail}'
        if campaign.error_message:
            campaign.error_message = f'{campaign.error_message}\n{note}'
        else:
            campaign.error_message = note

        # Mark cancelled before any lead/queue mutation so in-flight Celery submit
        # can see cancelled on refresh before place_order.
        campaign.status = 'cancelled'
        db.session.flush()
        self._best_effort_revoke_submit(campaign.id)

        do_requeue = (not campaign.olc_order_id) or olc_cancel_ok
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
        preset, street = self._resolve_creative(config)
        sender_err = validate_sender_ready(preset)
        if sender_err:
            campaign.status = 'failed'
            campaign.error_message = sender_err
            db.session.commit()
            raise MailQueueError(sender_err)

        if campaign.template_id:
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
            if not (preset or {}).get('font_name'):
                msg = (
                    'Could not confirm letter font from the Open Letter template. '
                    'Check the template in Connect, then retry.'
                )
                campaign.status = 'failed'
                campaign.error_message = msg
                db.session.commit()
                raise MailQueueError(msg)
        elif not (preset or {}).get('font_name'):
            msg = 'Campaign template and confirmed font/ink are required before submit'
            campaign.status = 'failed'
            campaign.error_message = msg
            db.session.commit()
            raise MailQueueError(msg)

        seller_phone = (preset or {}).get('phone')
        campaign.creative = snapshot_creative(
            preset,
            template_id=campaign.template_id,
            template_name=campaign.template_name,
            product_id=campaign.product_id,
            envelope_type=(preset or {}).get('envelope_color'),
        )

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
        for item in items:
            lead = Lead.query.get(item.lead_id)
            if lead is None:
                item.status = 'failed'
                item.validation_error = 'Lead not found'
                continue
            persist_embedded_address_fields(lead)
            validation_error = validate_owner_mailing_address(lead)
            if validation_error:
                item.status = 'invalid_address'
                item.validation_error = validation_error
                cancel_pending_mail_follow_up_tasks(
                    lead.id,
                    actor=campaign.created_by,
                    reason='owner_mailing_address_invalid',
                )
                invalid_lead_ids.append(lead.id)
                continue
            contacts.append(lead_to_owner_olc_contact(
                lead, user_id=item.user_id, campaign_phone=seller_phone,
            ))
            lead_by_item[item.id] = lead

        if not contacts:
            campaign.status = 'failed'
            campaign.error_message = 'No valid contacts to send'
            db.session.commit()
            refresh_leads_after_mail_task_changes(invalid_lead_ids)
            return campaign

        campaign.lead_count = len(contacts)

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
            failed_lead_ids: list[int] = []
            for item in items:
                if item.status == 'queued':
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
        return campaign

    @staticmethod
    def _recipient_from_contact_row(row: dict[str, Any]) -> dict[str, Any]:
        return row.get('recipient') or row.get('contact') or row

    @staticmethod
    def _lead_id_from_recipient(recip: dict[str, Any]) -> int | None:
        meta = recip.get('meta') or {}
        data = meta.get('data') if isinstance(meta, dict) else {}
        if not isinstance(data, dict):
            data = recip.get('meta_data') if isinstance(recip.get('meta_data'), dict) else {}
        raw = data.get('lead_id') if isinstance(data, dict) else None
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

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
        history = lead.mailer_history
        if not isinstance(history, list):
            history = [] if history is None else [history]
        stamped = False
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if str(entry.get('olc_order_id') or '') != str(order_id):
                continue
            entry['address_feedback'] = status
            if extra:
                entry.update(extra)
            stamped = True
            break
        if not stamped:
            row = {
                'olc_order_id': order_id,
                'address_feedback': status,
                **(extra or {}),
            }
            history.append(row)
        lead.mailer_history = list(history)

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
        street, city, state, zip_code = owner_mailing_address(lead)
        line = format_mailing_line(street, city, state, zip_code)
        changed = False
        if item is not None and item.status == 'sent':
            item.status = 'failed'
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
        return True

    def _sync_order_address_statuses(self, campaign: MailCampaign, client) -> dict[str, int]:
        summary = {'corrected': 0, 'failed': 0, 'verified': 0, 'unchanged': 0}
        by_lead: dict[int, dict[str, Any]] = {}
        for row in client.iter_order_contacts(campaign.olc_order_id):
            recip = self._recipient_from_contact_row(row if isinstance(row, dict) else {})
            lead_id = self._lead_id_from_recipient(recip)
            if lead_id is None:
                continue
            status = (recip.get('addressStatus') or '').strip() or 'Unknown'
            prior = by_lead.get(lead_id)
            if prior is None or _STATUS_PRIORITY.get(status, 0) > _STATUS_PRIORITY.get(
                prior.get('addressStatus') or '', 0,
            ):
                by_lead[lead_id] = recip

        items_by_lead = {
            item.lead_id: item
            for item in MailQueueItem.query.filter_by(campaign_id=campaign.id).all()
        }
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

        if touch_ids:
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

        mailed = (campaign.delivery_stats or {}).get('Mailed', 0)
        delivered = (campaign.delivery_stats or {}).get('Delivered', 0)
        if mailed or delivered:
            campaign.status = 'mailed'

        try:
            address_summary = self._sync_order_address_statuses(campaign, client)
        except Exception:
            logger.exception(
                'OLC address-status sync failed for campaign %s order %s',
                campaign.id, campaign.olc_order_id,
            )
            address_summary = {'corrected': 0, 'failed': 0, 'verified': 0, 'unchanged': 0}

        campaign._address_feedback_summary = address_summary  # type: ignore[attr-defined]
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
                dims['font_name'],
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
                'font_name': bucket['font_name'],
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
