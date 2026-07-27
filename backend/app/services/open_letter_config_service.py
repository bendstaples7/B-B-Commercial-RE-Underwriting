"""Open Letter Connect configuration service."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func

from app import db
from app.exceptions import ExternalServiceError
from app.models.mail_campaign import MailCampaign
from app.models.open_letter_config import OpenLetterConfig
from app.models.user import User
from app.services.open_letter_client_service import OpenLetterClientService
from app.services.mail_creative import (
    apply_template_style_to_preset,
    extract_letter_body_style,
    get_active_preset,
    migrate_legacy_return_into_presets,
    normalize_presets,
    street_return_address,
    template_ink_confirmed,
)

logger = logging.getLogger(__name__)

ENV_API_TOKEN = 'OPEN_LETTER_API_TOKEN'
ENV_TOKEN_EMAIL = 'OPEN_LETTER_ENV_TOKEN_EMAIL'
DEFAULT_ENV_TOKEN_EMAIL = 'ben.d.staples.7@gmail.com'
ENV_USE_DEMO = 'OPEN_LETTER_USE_DEMO'
ENV_BATCH_MINIMUM = 'OPEN_LETTER_BATCH_MINIMUM'
ENV_PRODUCT_ID = 'OPEN_LETTER_DEFAULT_PRODUCT_ID'
ENV_TEMPLATE_ID = 'OPEN_LETTER_DEFAULT_TEMPLATE_ID'
ENV_TEMPLATE_NAME = 'OPEN_LETTER_DEFAULT_TEMPLATE_NAME'
ENV_ALLOW_BELOW_MINIMUM = 'OPEN_LETTER_ALLOW_SEND_BELOW_MINIMUM'


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_int(name: str, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class OpenLetterConfigService:
    """Per-user OLC settings.

  - ``OPEN_LETTER_API_TOKEN`` in``.env`` applies only to the user named by
    ``OPEN_LETTER_ENV_TOKEN_EMAIL`` (default: ben.d.staples.7@gmail.com).
  - All other users store their own encrypted API token in ``open_letter_config``.
    """

    def _user_email(self, user_id: str) -> str | None:
        user = User.query.filter_by(user_id=user_id).first()
        if user is None:
            return None
        return (user.email_lower or user.email or '').strip().lower()

    def _env_token_email(self) -> str:
        return (
            os.environ.get(ENV_TOKEN_EMAIL, DEFAULT_ENV_TOKEN_EMAIL).strip().lower()
        )

    def env_api_token_for_user(self, user_id: str) -> str | None:
        raw = os.environ.get(ENV_API_TOKEN)
        if not raw or not raw.strip():
            return None
        user_email = self._user_email(user_id)
        if user_email != self._env_token_email():
            return None
        return raw.strip()

    def uses_env_token(self, user_id: str) -> bool:
        return self.env_api_token_for_user(user_id) is not None

    def get_config(self, user_id: str) -> OpenLetterConfig | None:
        return OpenLetterConfig.query.filter_by(user_id=user_id).first()

    def token_source(self, user_id: str) -> str | None:
        if self.uses_env_token(user_id):
            return 'environment'
        config = self.get_config(user_id)
        if config and config.encrypted_api_token:
            return 'database'
        return None

    def is_configured(self, user_id: str) -> bool:
        return self.token_source(user_id) is not None

    def ensure_config_from_env(self, user_id: str) -> OpenLetterConfig | None:
        env_token = self.env_api_token_for_user(user_id)
        if not env_token:
            return self.get_config(user_id)

        config = self.get_config(user_id)
        if config is None:
            config = OpenLetterConfig(
                user_id=user_id,
                encrypted_api_token=OpenLetterClientService.encrypt_token(env_token),
                use_demo_api=_env_bool(ENV_USE_DEMO, False),
                batch_minimum=max(1, _env_int(ENV_BATCH_MINIMUM, 50) or 50),
                allow_send_below_minimum=_env_bool(ENV_ALLOW_BELOW_MINIMUM, False),
                default_product_id=_env_int(ENV_PRODUCT_ID),
                default_template_id=_env_int(ENV_TEMPLATE_ID),
                default_template_name=os.environ.get(ENV_TEMPLATE_NAME) or None,
            )
            db.session.add(config)
            logger.info('Open Letter config bootstrapped from env for user_id=%s', user_id)
        else:
            try:
                current = OpenLetterClientService.decrypt_token(config.encrypted_api_token)
            except Exception:
                current = None
            if current != env_token:
                config.encrypted_api_token = OpenLetterClientService.encrypt_token(env_token)

        db.session.commit()
        return config

    def save_config(
        self,
        user_id: str,
        *,
        api_token: str | None = None,
        use_demo_api: bool | None = None,
        default_product_id: int | None = None,
        default_template_id: int | None = None,
        default_template_name: str | None = None,
        batch_minimum: int | None = None,
        allow_send_below_minimum: bool | None = None,
        return_address: dict | None = None,
        creative_presets: list | None = None,
        active_creative_preset_id: str | None = None,
    ) -> OpenLetterConfig:
        if api_token and self.uses_env_token(user_id):
            raise ValueError(
                'This account uses OPEN_LETTER_API_TOKEN from .env; '
                'API keys cannot be changed in the UI.',
            )

        config = self.ensure_config_from_env(user_id) or self.get_config(user_id)
        if config is None:
            if not api_token:
                raise ValueError(
                    'Add your Open Letter API token to connect your account.',
                )
            config = OpenLetterConfig(
                user_id=user_id,
                encrypted_api_token=OpenLetterClientService.encrypt_token(api_token),
            )
            db.session.add(config)
        elif api_token:
            config.encrypted_api_token = OpenLetterClientService.encrypt_token(api_token)

        if use_demo_api is not None:
            config.use_demo_api = use_demo_api
        if default_product_id is not None:
            config.default_product_id = default_product_id
        if default_template_id is not None:
            config.default_template_id = default_template_id
        if default_template_name is not None:
            config.default_template_name = default_template_name
        if batch_minimum is not None:
            config.batch_minimum = max(1, int(batch_minimum))
        if allow_send_below_minimum is not None:
            config.allow_send_below_minimum = allow_send_below_minimum
        if return_address is not None:
            # Persist street fields only when complete; empty dict clears.
            if return_address == {} or return_address is False:
                config.return_address = None
            else:
                street = street_return_address(return_address)
                config.return_address = street
        if creative_presets is not None:
            config.creative_presets = normalize_presets(creative_presets)
        if active_creative_preset_id is not None:
            if not isinstance(active_creative_preset_id, str):
                raise ValueError('active_creative_preset_id must be a string')
            cleaned = (active_creative_preset_id or '').strip() or None
            config.active_creative_preset_id = cleaned
        if config.creative_presets:
            ids = {p['id'] for p in config.creative_presets}
            if config.active_creative_preset_id not in ids:
                config.active_creative_preset_id = config.creative_presets[0]['id']
        else:
            config.active_creative_preset_id = None

        # Auto-confirm font/ink from the selected Connect template (not user-selected).
        style = self.resolve_template_style(user_id, config.default_template_id)
        if config.creative_presets:
            config.creative_presets = self._stamp_presets_with_template_style(
                normalize_presets(config.creative_presets),
                style,
            )

        config.updated_at = datetime.utcnow()
        db.session.commit()
        return config

    def _positive_cost_per_piece(self, value) -> Decimal | None:
        """Return a positive Decimal cost, or None if missing/zero/negative."""
        if value is None:
            return None
        try:
            amount = Decimal(str(value))
        except Exception:
            return None
        if amount <= 0:
            return None
        return amount

    def _campaign_sent_at(self, campaign: MailCampaign) -> datetime | None:
        return campaign.submitted_at or campaign.created_at

    def _latest_campaign_with_cost(
        self,
        user_id: str,
        *,
        product_id: int | None = None,
        require_product_match: bool = False,
    ) -> MailCampaign | None:
        """Most recent billed campaign with a positive cost_per_piece."""
        sent_at = func.coalesce(MailCampaign.submitted_at, MailCampaign.created_at)
        q = (
            MailCampaign.query
            .filter(
                MailCampaign.created_by == user_id,
                MailCampaign.cost_per_piece.isnot(None),
                MailCampaign.cost_per_piece > 0,
                MailCampaign.status.in_(('submitted', 'processing', 'mailed')),
            )
        )
        if product_id is not None:
            matched = (
                q.filter(MailCampaign.product_id == product_id)
                .order_by(sent_at.desc())
                .first()
            )
            if matched is not None:
                return matched
            if require_product_match:
                return None
        return q.order_by(sent_at.desc()).first()

    def resolve_estimated_cost(
        self,
        user_id: str,
        *,
        persist: bool = False,
    ) -> tuple[Decimal | None, datetime | None]:
        """Effective $/piece and the send date of the campaign it came from.

        Prefers a campaign matching the default product. Falls back to any
        billed campaign for display only (never persisted for a mismatched
        product). GET/read paths should keep ``persist=False``; seeding writes
        only when config is unset and the campaign matches the default product
        (or there is no default product).
        """
        config = self.get_config(user_id)
        product_id = config.default_product_id if config is not None else None

        matched = self._latest_campaign_with_cost(
            user_id,
            product_id=product_id,
            require_product_match=product_id is not None,
        )
        if matched is not None:
            seeded = self._positive_cost_per_piece(matched.cost_per_piece)
            if seeded is not None:
                config_unset = (
                    config is not None
                    and self._positive_cost_per_piece(config.estimated_cost_per_piece) is None
                )
                if persist and config_unset:
                    config.estimated_cost_per_piece = seeded
                    config.updated_at = datetime.utcnow()
                    db.session.commit()
                    logger.info(
                        'Seeded estimated_cost_per_piece=%.4f from campaign %s for user_id=%s',
                        seeded,
                        matched.id,
                        user_id,
                    )
                return seeded, self._campaign_sent_at(matched)

        # Display-only fallback: other product's last cost (do not persist).
        if product_id is not None:
            fallback = self._latest_campaign_with_cost(
                user_id,
                product_id=None,
                require_product_match=False,
            )
            if fallback is not None:
                seeded = self._positive_cost_per_piece(fallback.cost_per_piece)
                if seeded is not None:
                    return seeded, self._campaign_sent_at(fallback)

        if config is not None:
            current = self._positive_cost_per_piece(config.estimated_cost_per_piece)
            if current is not None:
                return current, None
        return None, None

    def resolve_estimated_cost_per_piece(
        self,
        user_id: str,
        *,
        persist: bool = False,
    ) -> Decimal | None:
        """Effective $/piece only (see ``resolve_estimated_cost``)."""
        cost, _source = self.resolve_estimated_cost(user_id, persist=persist)
        return cost

    def require_config(self, user_id: str) -> OpenLetterConfig:
        config = self.ensure_config_from_env(user_id) or self.get_config(user_id)
        if config is None or not self.is_configured(user_id):
            raise ExternalServiceError(
                'Open Letter is not configured for your account — '
                'add your API token in Open Letter settings.',
                payload={'error_type': 'open_letter_not_configured'},
            )
        return config

    def get_client(self, user_id: str) -> OpenLetterClientService:
        config = self.require_config(user_id)
        env_token = self.env_api_token_for_user(user_id)
        return OpenLetterClientService(config, api_token=env_token)

    def get_readonly_settings(self, user_id: str) -> dict:
        """Return mail batch settings without writing to the DB."""
        config = self.get_config(user_id)
        cost, source_sent_at = self.resolve_estimated_cost(user_id, persist=False)
        cost_float = float(cost) if cost is not None else None
        if source_sent_at is None:
            source_iso = None
        elif source_sent_at.tzinfo is None:
            source_iso = (
                source_sent_at.replace(tzinfo=timezone.utc)
                .isoformat()
                .replace('+00:00', 'Z')
            )
        else:
            source_iso = (
                source_sent_at.astimezone(timezone.utc)
                .isoformat()
                .replace('+00:00', 'Z')
            )
        base = {
            'estimated_cost_per_piece': cost_float,
            'estimated_cost_source_sent_at': source_iso,
        }
        if config:
            return {
                'batch_minimum': config.batch_minimum,
                'allow_send_below_minimum': config.allow_send_below_minimum,
                **base,
            }
        return {
            'batch_minimum': _env_int(ENV_BATCH_MINIMUM, 50) or 50,
            'allow_send_below_minimum': _env_bool(ENV_ALLOW_BELOW_MINIMUM, False),
            **base,
        }

    def resolve_template_style(self, user_id: str, template_id: int | str | None) -> dict | None:
        """Auto-confirm body ink from the Connect template design JSON (no typeface)."""
        if template_id is None or str(template_id).strip() == '':
            return None
        try:
            client = self.get_client(user_id)
            design = client.fetch_template_design(template_id)
            style = extract_letter_body_style(design)
        except Exception as exc:  # noqa: BLE001
            logger.warning('Failed to resolve OLC template style for %s: %s', template_id, exc)
            return None
        if not template_ink_confirmed(style):
            return None
        return {
            'font_color': style.get('font_color'),
            'fill': style.get('fill'),
            'readable': True,
            'template_id': int(template_id) if str(template_id).isdigit() else template_id,
            'confirmed_from': 'olc_template',
        }

    def _stamp_presets_with_template_style(
        self,
        presets: list[dict],
        style: dict | None,
        *,
        template_id: int | None = None,
        template_name: str | None = None,
        active_id: str | None = None,
    ) -> list[dict]:
        """Stamp ink from the template onto presets (no typeface).

        Does not overwrite each preset's ``olc_template_id`` unless ``active_id``
        is provided (then only that preset gets template id/name).
        """
        if not presets:
            return presets
        stamped = []
        for preset in presets:
            item = dict(preset)
            preset_tid = item.get('olc_template_id')
            # Only stamp font/ink onto presets that use this template (or have none yet).
            same_template = (
                template_id is None
                or preset_tid is None
                or str(preset_tid) == str(template_id)
            )
            if same_template:
                item = apply_template_style_to_preset(item, style) or item
            if active_id and item.get('id') == active_id:
                if template_id is not None:
                    item['olc_template_id'] = template_id
                if template_name:
                    item['olc_template_name'] = template_name
                item = apply_template_style_to_preset(item, style) or item
            stamped.append(item)
        return stamped

    def serialize_public(self, user_id: str) -> dict:
        config = self.get_config(user_id)
        source = self.token_source(user_id)
        uses_env = self.uses_env_token(user_id)
        if not source:
            return {
                'configured': False,
                'token_source': None,
                'uses_env_token': uses_env,
                'requires_user_api_token': not uses_env,
            }

        if config is None:
            settings = self.get_readonly_settings(user_id)
            template_id = _env_int(ENV_TEMPLATE_ID)
            return {
                'configured': True,
                'token_source': source,
                'uses_env_token': uses_env,
                'requires_user_api_token': False,
                'use_demo_api': _env_bool(ENV_USE_DEMO, False),
                'default_product_id': _env_int(ENV_PRODUCT_ID),
                'default_template_id': template_id,
                'default_template_name': os.environ.get(ENV_TEMPLATE_NAME) or None,
                'batch_minimum': settings['batch_minimum'],
                'allow_send_below_minimum': settings['allow_send_below_minimum'],
                'return_address': None,
                'creative_presets': [],
                'active_creative_preset_id': None,
                # GET is read-only — use /templates/:id/style to confirm design.
                'template_style': None,
                'estimated_cost_per_piece': settings['estimated_cost_per_piece'],
                'estimated_cost_source_sent_at': settings['estimated_cost_source_sent_at'],
                'updated_at': None,
            }

        presets, active_id, street = migrate_legacy_return_into_presets(
            config.return_address,
            config.creative_presets,
            config.active_creative_preset_id,
        )

        active = get_active_preset(presets, active_id or config.active_creative_preset_id)
        style = None
        if active and active.get('font_color'):
            style = {
                'font_color': active.get('font_color'),
                'readable': True,
                'template_id': active.get('olc_template_id') or config.default_template_id,
                'confirmed_from': 'preset',
            }

        settings = self.get_readonly_settings(user_id)

        return {
            'configured': True,
            'token_source': source,
            'uses_env_token': uses_env,
            'requires_user_api_token': False,
            'use_demo_api': config.use_demo_api,
            'default_product_id': config.default_product_id,
            'default_template_id': config.default_template_id,
            'default_template_name': config.default_template_name,
            'batch_minimum': config.batch_minimum,
            'allow_send_below_minimum': config.allow_send_below_minimum,
            'return_address': street if street is not None else street_return_address(config.return_address),
            'creative_presets': presets,
            'active_creative_preset_id': active_id or (
                presets[0]['id'] if presets else None
            ),
            'template_style': style,
            'estimated_cost_per_piece': settings['estimated_cost_per_piece'],
            'estimated_cost_source_sent_at': settings['estimated_cost_source_sent_at'],
            'updated_at': config.updated_at.isoformat() if config.updated_at else None,
        }
