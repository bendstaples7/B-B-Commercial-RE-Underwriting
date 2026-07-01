"""Open Letter Connect configuration service."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from decimal import Decimal

from app import db
from app.exceptions import ExternalServiceError
from app.models.open_letter_config import OpenLetterConfig
from app.models.user import User
from app.services.open_letter_client_service import OpenLetterClientService

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
                batch_minimum=_env_int(ENV_BATCH_MINIMUM, 50) or 50,
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
        estimated_cost_per_piece: Decimal | float | None = None,
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
            config.return_address = return_address
        if estimated_cost_per_piece is not None:
            config.estimated_cost_per_piece = Decimal(str(estimated_cost_per_piece))

        config.updated_at = datetime.utcnow()
        db.session.commit()
        return config

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
        """Return mail batch settings without bootstrapping or writing to the DB."""
        config = self.get_config(user_id)
        if config:
            return {
                'batch_minimum': config.batch_minimum,
                'allow_send_below_minimum': config.allow_send_below_minimum,
                'estimated_cost_per_piece': (
                    float(config.estimated_cost_per_piece)
                    if config.estimated_cost_per_piece is not None else None
                ),
            }
        return {
            'batch_minimum': _env_int(ENV_BATCH_MINIMUM, 50) or 50,
            'allow_send_below_minimum': _env_bool(ENV_ALLOW_BELOW_MINIMUM, False),
            'estimated_cost_per_piece': None,
        }

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
            return {
                'configured': True,
                'token_source': source,
                'uses_env_token': uses_env,
                'requires_user_api_token': False,
                'use_demo_api': _env_bool(ENV_USE_DEMO, False),
                'default_product_id': _env_int(ENV_PRODUCT_ID),
                'default_template_id': _env_int(ENV_TEMPLATE_ID),
                'default_template_name': os.environ.get(ENV_TEMPLATE_NAME) or None,
                'batch_minimum': settings['batch_minimum'],
                'allow_send_below_minimum': settings['allow_send_below_minimum'],
                'return_address': None,
                'estimated_cost_per_piece': settings['estimated_cost_per_piece'],
                'updated_at': None,
            }

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
            'return_address': config.return_address,
            'estimated_cost_per_piece': (
                float(config.estimated_cost_per_piece)
                if config.estimated_cost_per_piece is not None else None
            ),
            'updated_at': config.updated_at.isoformat() if config.updated_at else None,
        }
