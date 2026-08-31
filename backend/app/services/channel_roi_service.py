"""Channel ROI — rollup spend efficiency across Direct Mail and Facebook."""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.channel_roi_config import ChannelRoiConfig
from app.models.facebook_ad_campaign import FacebookAdCampaign
from app.models.facebook_campaign_lead_attribution import FacebookCampaignLeadAttribution
from app.models.mail_campaign import MailCampaign
from app.services.meta_ads_client_service import MetaAdsClientService

logger = logging.getLogger(__name__)

_UNSET = object()
_CONFIG_KEY = 'default'


def _dec(value) -> Decimal:
    if value is None:
        return Decimal('0')
    return Decimal(str(value))


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    return float(value)


def projected_roi_multiplier(
    *,
    responses: int,
    spend: Decimal,
    expected_profit_per_deal: Decimal | None,
    assumed_close_rate: Decimal | None,
) -> float | None:
    """(responses × profit × close_rate) / spend → multiplier, or None if unset/zero spend."""
    if expected_profit_per_deal is None or assumed_close_rate is None:
        return None
    if spend <= 0:
        return None
    projected = _dec(responses) * _dec(expected_profit_per_deal) * _dec(assumed_close_rate)
    return float(projected / spend)


def cost_per_response(spend: Decimal, responses: int) -> float | None:
    if responses <= 0:
        return None
    return float(spend / Decimal(responses))


def response_rate(responses: int, denominator: int | None) -> float | None:
    if denominator is None or denominator <= 0:
        return None
    return round(responses / denominator, 4)


def _active_fb_filter():
    return or_(
        FacebookAdCampaign.status.is_(None),
        FacebookAdCampaign.status != 'ARCHIVED_LOCAL',
    )


class ChannelRoiService:
    """Company Channel ROI settings, Meta sync, and rollup payload."""

    def get_or_create_config(self) -> ChannelRoiConfig:
        config = ChannelRoiConfig.query.filter_by(config_key=_CONFIG_KEY).first()
        if config is not None:
            return config
        config = ChannelRoiConfig(config_key=_CONFIG_KEY)
        db.session.add(config)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            config = ChannelRoiConfig.query.filter_by(config_key=_CONFIG_KEY).first()
            if config is None:
                raise
        return config

    def settings_public(self, config: ChannelRoiConfig | None = None) -> dict[str, Any]:
        config = config or ChannelRoiConfig.query.filter_by(config_key=_CONFIG_KEY).first()
        if config is None:
            return {
                'meta_connected': False,
                'meta_ad_account_id': None,
                'has_meta_token': False,
                'expected_profit_per_deal': None,
                'assumed_close_rate': None,
                'last_synced_at': None,
                'last_sync_error': None,
            }
        return {
            'meta_connected': bool(config.encrypted_meta_token and config.meta_ad_account_id),
            'meta_ad_account_id': config.meta_ad_account_id,
            'has_meta_token': bool(config.encrypted_meta_token),
            'expected_profit_per_deal': _float_or_none(config.expected_profit_per_deal),
            'assumed_close_rate': _float_or_none(config.assumed_close_rate),
            'last_synced_at': (
                config.last_synced_at.isoformat() + 'Z'
                if config.last_synced_at and config.last_synced_at.tzinfo is None
                else (config.last_synced_at.isoformat() if config.last_synced_at else None)
            ),
            'last_sync_error': config.last_sync_error,
        }

    def update_settings(
        self,
        *,
        expected_profit_per_deal=_UNSET,
        assumed_close_rate=_UNSET,
        meta_ad_account_id: str | None = None,
        meta_access_token: str | None = None,
        clear_meta_token: bool = False,
    ) -> ChannelRoiConfig:
        config = self.get_or_create_config()
        if expected_profit_per_deal is not _UNSET:
            if expected_profit_per_deal is None:
                config.expected_profit_per_deal = None
            else:
                try:
                    profit = Decimal(str(expected_profit_per_deal))
                except (InvalidOperation, TypeError, ValueError) as exc:
                    raise ValueError('expected_profit_per_deal must be a number') from exc
                if profit < 0:
                    raise ValueError('expected_profit_per_deal must be >= 0')
                config.expected_profit_per_deal = profit
        if assumed_close_rate is not _UNSET:
            if assumed_close_rate is None:
                config.assumed_close_rate = None
            else:
                # API convention: percent 0–100 (UI sends the same units shown in the field).
                try:
                    percent = Decimal(str(assumed_close_rate))
                except (InvalidOperation, TypeError, ValueError) as exc:
                    raise ValueError('assumed_close_rate must be a number') from exc
                if percent < 0 or percent > 100:
                    raise ValueError('assumed_close_rate must be between 0 and 100 (percent)')
                config.assumed_close_rate = percent / Decimal('100')
        if meta_ad_account_id is not None:
            raw = meta_ad_account_id.strip()
            config.meta_ad_account_id = raw or None
        if clear_meta_token:
            config.encrypted_meta_token = None
        elif meta_access_token:
            token = meta_access_token.strip()
            if token and token != '***':
                config.encrypted_meta_token = MetaAdsClientService.encrypt_token(token)
        config.updated_at = datetime.utcnow()
        db.session.add(config)
        db.session.commit()
        return config

    def sync_facebook_campaigns(self) -> dict[str, Any]:
        config = self.get_or_create_config()
        if not config.encrypted_meta_token or not config.meta_ad_account_id:
            raise ValueError('Meta is not connected — save an access token and ad account id first')
        token = MetaAdsClientService.decrypt_token(config.encrypted_meta_token)
        client = MetaAdsClientService(token, config.meta_ad_account_id)
        try:
            rows = client.list_campaigns_with_insights()
        except Exception as exc:
            config.last_sync_error = str(exc)[:2000]
            config.updated_at = datetime.utcnow()
            db.session.add(config)
            db.session.commit()
            raise

        now = datetime.utcnow()
        seen: set[str] = set()
        for row in rows:
            mid = row['meta_campaign_id']
            seen.add(mid)
            existing = (
                FacebookAdCampaign.query.filter_by(meta_campaign_id=mid)
                .with_for_update()
                .first()
            )
            if existing is None:
                existing = FacebookAdCampaign(meta_campaign_id=mid, response_count=0)
                db.session.add(existing)
            existing.name = row['name'] or existing.name or mid
            existing.status = row.get('status')
            existing.spend = _dec(row.get('spend'))
            existing.impressions = int(row.get('impressions') or 0)
            existing.link_clicks = int(row.get('link_clicks') or 0)
            existing.synced_at = now
            existing.updated_at = now

        # Soft-archive campaigns Meta no longer returns (including empty sync).
        stale_q = FacebookAdCampaign.query
        if seen:
            stale_q = stale_q.filter(~FacebookAdCampaign.meta_campaign_id.in_(list(seen)))
        for camp in stale_q.all():
            if camp.status != 'ARCHIVED_LOCAL':
                camp.status = 'ARCHIVED_LOCAL'
                camp.spend = Decimal('0')
                camp.impressions = 0
                camp.link_clicks = 0
                camp.synced_at = now
                camp.updated_at = now
                db.session.add(camp)

        config.last_synced_at = now
        config.last_sync_error = None
        config.updated_at = now
        db.session.add(config)
        db.session.commit()
        return {'synced': len(seen), 'last_synced_at': now.isoformat() + 'Z'}

    def list_facebook_campaigns_for_attribution(self) -> list[dict[str, Any]]:
        rows = (
            FacebookAdCampaign.query.filter(_active_fb_filter())
            .order_by(FacebookAdCampaign.name.asc())
            .limit(200)
            .all()
        )
        return [
            {
                'id': r.id,
                'meta_campaign_id': r.meta_campaign_id,
                'name': r.name,
                'status': r.status,
            }
            for r in rows
        ]

    def record_facebook_call_attribution(
        self, facebook_campaign_id: int, lead_id: int
    ) -> None:
        """Bump response_count once per lead/campaign via unique ledger insert."""
        campaign = (
            FacebookAdCampaign.query.filter_by(id=facebook_campaign_id)
            .with_for_update()
            .first()
        )
        if campaign is None or campaign.status == 'ARCHIVED_LOCAL':
            return

        already = FacebookCampaignLeadAttribution.query.filter_by(
            lead_id=lead_id,
            facebook_campaign_id=facebook_campaign_id,
        ).first()
        if already is not None:
            return

        db.session.add(
            FacebookCampaignLeadAttribution(
                lead_id=lead_id,
                facebook_campaign_id=facebook_campaign_id,
            )
        )
        campaign.response_count = (campaign.response_count or 0) + 1
        campaign.updated_at = datetime.utcnow()
        db.session.add(campaign)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

    def get_dashboard(self) -> dict[str, Any]:
        config = ChannelRoiConfig.query.filter_by(config_key=_CONFIG_KEY).first()
        profit = config.expected_profit_per_deal if config else None
        close_rate = config.assumed_close_rate if config else None
        knobs_set = profit is not None and close_rate is not None

        mail_totals = (
            db.session.query(
                func.coalesce(func.sum(MailCampaign.cost), 0),
                func.coalesce(func.sum(MailCampaign.response_count), 0),
                func.coalesce(func.sum(MailCampaign.lead_count), 0),
            )
            .filter(MailCampaign.status != 'cancelled')
            .one()
        )
        mail_spend = _dec(mail_totals[0])
        mail_responses = int(mail_totals[1] or 0)
        mail_pieces = int(mail_totals[2] or 0)

        mail_rows_raw = (
            MailCampaign.query.filter(MailCampaign.status != 'cancelled')
            .order_by(MailCampaign.submitted_at.desc().nullslast(), MailCampaign.id.desc())
            .limit(200)
            .all()
        )
        mail_rows: list[dict[str, Any]] = []
        for c in mail_rows_raw:
            spend = _dec(c.cost)
            responses = int(c.response_count or 0)
            pieces = int(c.lead_count or 0)
            mail_rows.append({
                'id': c.id,
                'name': c.template_name or f'Campaign {c.id}',
                'status': c.status,
                'spend': float(spend),
                'denominator': pieces,
                'denominator_label': 'pieces',
                'responses': responses,
                'response_rate': response_rate(responses, pieces if pieces else None),
                'cost_per_response': cost_per_response(spend, responses),
                'projected_roi': projected_roi_multiplier(
                    responses=responses,
                    spend=spend,
                    expected_profit_per_deal=profit,
                    assumed_close_rate=close_rate,
                ),
                'submitted_at': c.submitted_at.isoformat() if c.submitted_at else None,
            })

        fb_totals = (
            db.session.query(
                func.coalesce(func.sum(FacebookAdCampaign.spend), 0),
                func.coalesce(func.sum(FacebookAdCampaign.response_count), 0),
                func.coalesce(func.sum(FacebookAdCampaign.link_clicks), 0),
            )
            .filter(_active_fb_filter())
            .one()
        )
        fb_spend = _dec(fb_totals[0])
        fb_responses = int(fb_totals[1] or 0)
        fb_clicks = int(fb_totals[2] or 0)

        fb_rows_raw = (
            FacebookAdCampaign.query.filter(_active_fb_filter())
            .order_by(FacebookAdCampaign.spend.desc())
            .limit(200)
            .all()
        )
        fb_rows: list[dict[str, Any]] = []
        for c in fb_rows_raw:
            spend = _dec(c.spend)
            responses = int(c.response_count or 0)
            clicks = int(c.link_clicks or 0)
            fb_rows.append({
                'id': c.id,
                'name': c.name or c.meta_campaign_id,
                'status': c.status,
                'spend': float(spend),
                'denominator': clicks if clicks > 0 else None,
                'denominator_label': 'link_clicks',
                'responses': responses,
                'response_rate': response_rate(responses, clicks if clicks > 0 else None),
                'cost_per_response': cost_per_response(spend, responses),
                'projected_roi': projected_roi_multiplier(
                    responses=responses,
                    spend=spend,
                    expected_profit_per_deal=profit,
                    assumed_close_rate=close_rate,
                ),
                'link_clicks': clicks,
                'impressions': int(c.impressions or 0),
                'synced_at': c.synced_at.isoformat() if c.synced_at else None,
            })

        def channel_summary(spend: Decimal, responses: int, denom: int | None, denom_label: str):
            return {
                'spend': float(spend),
                'responses': responses,
                'cost_per_response': cost_per_response(spend, responses),
                'response_rate': response_rate(responses, denom),
                'denominator': denom,
                'denominator_label': denom_label,
                'projected_roi': projected_roi_multiplier(
                    responses=responses,
                    spend=spend,
                    expected_profit_per_deal=profit,
                    assumed_close_rate=close_rate,
                ),
            }

        return {
            'settings': self.settings_public(config),
            'projection_knobs_set': knobs_set,
            'channels': {
                'direct_mail': channel_summary(
                    mail_spend, mail_responses, mail_pieces if mail_pieces else None, 'pieces'
                ),
                'facebook': channel_summary(
                    fb_spend, fb_responses, fb_clicks if fb_clicks else None, 'link_clicks'
                ),
            },
            'direct_mail_campaigns': mail_rows,
            'facebook_campaigns': fb_rows,
        }
