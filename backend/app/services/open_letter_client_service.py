"""Open Letter Connect API client."""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

from app.exceptions import (
    ExternalServiceError,
    OpenLetterAuthenticationError,
    OpenLetterRateLimitError,
)
from app.models.open_letter_config import OpenLetterConfig

logger = logging.getLogger(__name__)

PRODUCTION_BASE_URL = 'https://api.openletterconnect.com/api/v1'
DEMO_BASE_URL = 'https://demoapi.openletterconnect.com/api/v1'


class OpenLetterClientService:
    """HTTP client for Open Letter Connect REST API."""

    TIMEOUT = 60

    @classmethod
    def decrypt_token(cls, encrypted_token: str) -> str:
        """Decrypt a stored token (also used for env sync checks)."""
        return cls._decrypt_token(encrypted_token)

    def __init__(self, config: OpenLetterConfig, *, api_token: str | None = None):
        if api_token:
            self._token = api_token
        else:
            self._token = self._decrypt_token(config.encrypted_api_token)
        self._base_url = DEMO_BASE_URL if config.use_demo_api else PRODUCTION_BASE_URL

    @staticmethod
    def _encryption_key() -> str:
        raw_key = os.environ.get('HUBSPOT_ENCRYPTION_KEY')
        if not raw_key:
            raise ExternalServiceError(
                'HUBSPOT_ENCRYPTION_KEY environment variable is not set',
                payload={'error_type': 'open_letter_config_error'},
            )
        return raw_key

    @classmethod
    def _decrypt_token(cls, encrypted_token: str) -> str:
        from cryptography.fernet import Fernet, InvalidToken

        try:
            f = Fernet(cls._encryption_key().encode())
            return f.decrypt(encrypted_token.encode()).decode()
        except (InvalidToken, Exception) as exc:
            raise ExternalServiceError(
                f'Failed to decrypt Open Letter API token: {exc}',
                payload={'error_type': 'open_letter_config_error'},
            ) from exc

    @classmethod
    def encrypt_token(cls, raw_token: str) -> str:
        from cryptography.fernet import Fernet

        f = Fernet(cls._encryption_key().encode())
        return f.encrypt(raw_token.encode()).decode()

    def _headers(self) -> dict[str, str]:
        return {
            'Authorization': f'Bearer {self._token}',
            'Content-Type': 'application/json',
        }

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        url = f'{self._base_url}{path}'
        try:
            resp = requests.request(
                method,
                url,
                headers=self._headers(),
                timeout=self.TIMEOUT,
                **kwargs,
            )
        except requests.exceptions.Timeout as exc:
            raise ExternalServiceError(
                f'Open Letter API timed out after {self.TIMEOUT}s: {path}',
                payload={'error_type': 'open_letter_timeout', 'path': path},
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ExternalServiceError(
                f'Open Letter API request failed: {exc}',
                payload={'error_type': 'open_letter_request_error', 'path': path},
            ) from exc

        if resp.status_code in (401, 403):
            raise OpenLetterAuthenticationError(
                f'Open Letter authentication failed (HTTP {resp.status_code})',
            )
        if resp.status_code == 429:
            retry_after = resp.headers.get('Retry-After')
            raise OpenLetterRateLimitError(
                'Open Letter rate limit exceeded',
                payload={'retry_after': int(retry_after) if retry_after else None},
            )
        if resp.status_code >= 500:
            raise ExternalServiceError(
                f'Open Letter server error (HTTP {resp.status_code})',
                payload={'error_type': 'open_letter_server_error', 'path': path},
            )
        if resp.status_code >= 400:
            body = resp.text[:500]
            raise ExternalServiceError(
                f'Open Letter API error (HTTP {resp.status_code}): {body}',
                payload={'error_type': 'open_letter_client_error', 'path': path},
            )

        if not resp.content:
            return {}
        return resp.json()

    @staticmethod
    def _normalize_list_payload(result: dict[str, Any]) -> dict[str, Any]:
        """OLC list endpoints return paginated ``data.rows``; expose a flat ``data`` array."""
        data = result.get('data')
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get('rows') or []
        else:
            rows = []
        return {**result, 'data': rows}

    def test_connection(self) -> dict[str, Any]:
        """Verify token by listing products."""
        result = self.list_products()
        items = result.get('data') or []
        return {'success': True, 'product_count': len(items)}

    def list_products(self) -> dict[str, Any]:
        return self._normalize_list_payload(self._request('GET', '/products'))

    def list_templates(
        self,
        *,
        page: int = 0,
        page_size: int = 50,
        product_types: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            'page': page,
            'pageSize': page_size,
        }
        if product_types:
            params['productTypes'] = product_types
        return self._normalize_list_payload(
            self._request('GET', '/templates', params=params),
        )

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request('POST', '/orders', json=payload)

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._request('GET', f'/orders/{order_id}')

    def get_order_analytics(self, order_id: str) -> dict[str, Any]:
        return self._request('GET', f'/orders/detail/analytics/{order_id}')
