"""Open Letter Connect API client."""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

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
            retry_seconds = None
            if retry_after:
                try:
                    retry_seconds = int(retry_after)
                except ValueError:
                    retry_seconds = None
            raise OpenLetterRateLimitError(
                'Open Letter rate limit exceeded',
                retry_after=retry_seconds,
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
                payload={
                    'error_type': 'open_letter_client_error',
                    'path': path,
                    'http_status': resp.status_code,
                },
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

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Best-effort cancel/delete of an OLC order.

        OLC does not document a stable cancel API; try common paths. Callers must
        treat ``ok: False`` as non-fatal and cancel locally (Connect UI may still
        be required).
        """
        order_id = str(order_id).strip()
        attempts = (
            ('DELETE', f'/orders/{order_id}'),
            ('POST', f'/orders/{order_id}/cancel'),
            ('POST', f'/orders/cancel/{order_id}'),
            ('DELETE', f'/orders/cancel/{order_id}'),
        )
        last_detail = 'no cancel endpoint succeeded'
        for method, path in attempts:
            try:
                self._request(method, path)
                return {
                    'ok': True,
                    'detail': f'{method} {path}',
                    'path': path,
                    'method': method,
                }
            except OpenLetterAuthenticationError as exc:
                last_detail = f'{method} {path}: {exc.message}'
                logger.warning('OLC cancel auth/forbidden for %s %s', method, path)
                return {'ok': False, 'detail': last_detail, 'order_id': order_id}
            except ExternalServiceError as exc:
                last_detail = f'{method} {path}: {exc.message}'
                if (exc.payload or {}).get('http_status') == 404:
                    logger.info('OLC cancel endpoint not found for %s %s', method, path)
                    continue
                logger.warning('OLC cancel attempt failed for %s %s: %s', method, path, exc.message)
                return {'ok': False, 'detail': last_detail, 'order_id': order_id}
            except Exception as exc:  # noqa: BLE001 — best-effort; never block local cancel
                last_detail = f'{method} {path}: {exc}'
                logger.warning('OLC cancel attempt error for %s %s: %s', method, path, exc)
                return {'ok': False, 'detail': last_detail, 'order_id': order_id}
        return {'ok': False, 'detail': last_detail, 'order_id': order_id}

    def get_order_analytics(self, order_id: str) -> dict[str, Any]:
        return self._request('GET', f'/orders/detail/analytics/{order_id}')

    def find_template(self, template_id: str | int) -> dict[str, Any] | None:
        """Locate a template row by id (paginated list scan)."""
        wanted = str(template_id).strip()
        page = 0
        while page < 20:
            raw = self.list_templates(page=page, page_size=50)
            rows = raw.get('data') or []
            if not rows:
                break
            for row in rows:
                if isinstance(row, dict) and str(row.get('id')) == wanted:
                    return row
            if len(rows) < 50:
                break
            page += 1
        return None

    def fetch_template_design(self, template_id: str | int) -> dict[str, Any]:
        """Download the template design JSON used by Connect's builder."""
        row = self.find_template(template_id)
        if row is None:
            raise ExternalServiceError(
                f'Open Letter template {template_id} not found',
                payload={'error_type': 'open_letter_template_not_found'},
            )
        url = row.get('templateUrl') or row.get('template_url')
        if not url:
            raise ExternalServiceError(
                f'Open Letter template {template_id} has no templateUrl',
                payload={'error_type': 'open_letter_template_missing_url'},
            )
        if not self._is_allowed_template_url(url):
            raise ExternalServiceError(
                f'Open Letter template {template_id} has an untrusted templateUrl',
                payload={'error_type': 'open_letter_template_untrusted_url'},
            )
        try:
            # Design JSON lives on object storage — do not forward the API Bearer token.
            resp = requests.get(url, timeout=self.TIMEOUT, allow_redirects=False)
        except requests.exceptions.RequestException as exc:
            raise ExternalServiceError(
                f'Failed to download Open Letter template design: {exc}',
                payload={'error_type': 'open_letter_template_download_error'},
            ) from exc
        if 300 <= resp.status_code < 400:
            raise ExternalServiceError(
                'Open Letter template download redirected to an untrusted location',
                payload={'error_type': 'open_letter_template_untrusted_redirect'},
            )
        if resp.status_code >= 400:
            raise ExternalServiceError(
                f'Open Letter template download failed (HTTP {resp.status_code})',
                payload={'error_type': 'open_letter_template_download_error'},
            )
        try:
            design = resp.json()
        except ValueError as exc:
            raise ExternalServiceError(
                'Open Letter template design was not JSON',
                payload={'error_type': 'open_letter_template_invalid_json'},
            ) from exc
        if not isinstance(design, dict):
            raise ExternalServiceError(
                'Open Letter template design had unexpected shape',
                payload={'error_type': 'open_letter_template_invalid_json'},
            )
        return design

    @staticmethod
    def _is_allowed_template_url(url: str) -> bool:
        """Allow only HTTPS OLC and known object-storage/CDN hosts."""
        parsed = urlparse(url)
        hostname = (parsed.hostname or '').lower()
        if parsed.scheme != 'https' or not hostname:
            return False
        return (
            hostname == 'openletterconnect.com'
            or hostname.endswith('.openletterconnect.com')
            or hostname == 'amazonaws.com'
            or hostname.endswith('.amazonaws.com')
            or hostname == 'cloudfront.net'
            or hostname.endswith('.cloudfront.net')
            or hostname == 'googleapis.com'
            or hostname.endswith('.googleapis.com')
        )

    def list_order_contacts(
        self,
        order_id: str,
        *,
        page: int = 0,
        page_size: int = 100,
    ) -> dict[str, Any]:
        params = {'page': page, 'pageSize': page_size}
        return self._request(
            'GET',
            f'/orders/detail/contacts/{order_id}',
            params=params,
        )

    def iter_order_contacts(
        self,
        order_id: str,
        *,
        page_size: int = 100,
        max_pages: int = 50,
    ):
        """Yield contact rows for an order, paginating until exhausted."""
        page = 0
        seen = 0
        total = None
        while page < max_pages:
            raw = self.list_order_contacts(order_id, page=page, page_size=page_size)
            data = raw.get('data') or {}
            rows = data.get('rows') or []
            if total is None:
                try:
                    total = int(data.get('count') or 0)
                except (TypeError, ValueError):
                    total = 0
            if not rows:
                break
            for row in rows:
                yield row
            seen += len(rows)
            if total and seen >= total:
                break
            if len(rows) < page_size:
                break
            page += 1
        else:
            raise ExternalServiceError(
                f'Open Letter order {order_id} contacts exceeded {max_pages} pages',
                payload={
                    'error_type': 'open_letter_contacts_incomplete',
                    'order_id': str(order_id),
                    'max_pages': max_pages,
                },
            )
