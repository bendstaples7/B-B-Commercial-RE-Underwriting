"""Meta Marketing API client for Channel ROI campaign spend sync."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import requests

from app.exceptions import ExternalServiceError
from app.services.hubspot_client_service import HubSpotClientService

logger = logging.getLogger(__name__)

GRAPH_VERSION = 'v21.0'
GRAPH_BASE = f'https://graph.facebook.com/{GRAPH_VERSION}'


class MetaAdsClientService:
    """Thin Graph API client for ad account campaigns + lifetime insights."""

    TIMEOUT = 45

    def __init__(self, access_token: str, ad_account_id: str):
        self._token = (access_token or '').strip()
        if not self._token:
            raise ExternalServiceError(
                'Meta access token is empty',
                payload={'error_type': 'meta_config_error'},
            )
        raw = (ad_account_id or '').strip()
        if not raw:
            raise ExternalServiceError(
                'Meta ad account id is empty',
                payload={'error_type': 'meta_config_error'},
            )
        self._account = raw if raw.startswith('act_') else f'act_{raw}'

    @staticmethod
    def encrypt_token(raw_token: str) -> str:
        """Fernet-encrypt via shared HubSpot/OLC key helper."""
        try:
            return HubSpotClientService.encrypt_token(raw_token)
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise ExternalServiceError(
                f'Failed to encrypt Meta token: {exc}',
                payload={'error_type': 'meta_config_error'},
            ) from exc

    @staticmethod
    def decrypt_token(encrypted_token: str) -> str:
        """Decrypt using the same Fernet path as HubSpot client secrets."""
        try:
            return HubSpotClientService.decrypt_client_secret(encrypted_token)
        except ExternalServiceError:
            raise
        except Exception as exc:
            raise ExternalServiceError(
                'Failed to decrypt Meta token',
                payload={'error_type': 'meta_config_error'},
            ) from exc

    def _auth_headers(self) -> dict[str, str]:
        return {'Authorization': f'Bearer {self._token}'}

    def _request_json(self, url: str, params: dict[str, Any] | None = None) -> dict:
        try:
            resp = requests.get(
                url,
                params=params,
                headers=self._auth_headers(),
                timeout=self.TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ExternalServiceError(
                f'Meta API request failed: {exc}',
                payload={'error_type': 'meta_api_error'},
            ) from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise ExternalServiceError(
                f'Meta API returned non-JSON ({resp.status_code})',
                payload={'error_type': 'meta_api_error'},
            ) from exc
        if resp.status_code >= 400:
            err = data.get('error') if isinstance(data, dict) else None
            msg = err.get('message') if isinstance(err, dict) else resp.text
            raise ExternalServiceError(
                f'Meta API error: {msg}',
                payload={'error_type': 'meta_api_error', 'status': resp.status_code},
            )
        return data if isinstance(data, dict) else {}

    def _paginate(self, url: str, params: dict[str, Any] | None) -> list[dict]:
        rows: list[dict] = []
        while url:
            page = self._request_json(url, params)
            params = None
            rows.extend(page.get('data') or [])
            url = (page.get('paging') or {}).get('next')
        return rows

    @staticmethod
    def _link_clicks_from_actions(actions: list | None) -> int:
        # Prefer Meta link_click only (avoid double-counting outbound_click).
        for action in actions or []:
            if action.get('action_type') == 'link_click':
                return int(action.get('value') or 0)
        return 0

    def list_campaigns_with_insights(self) -> list[dict[str, Any]]:
        """Return campaigns with lifetime spend / impressions / link_clicks.

        Uses one paginated campaigns list plus one paginated account-level
        insights request (``level=campaign``) — not per-campaign insights.
        Insight rows for campaigns missing from the campaigns edge are ignored
        so soft-archive can still clear campaigns Meta no longer lists.
        """
        campaign_rows = self._paginate(
            f'{GRAPH_BASE}/{self._account}/campaigns',
            {
                'fields': 'id,name,status',
                'limit': 100,
            },
        )
        by_id: dict[str, dict[str, Any]] = {}
        for row in campaign_rows:
            cid = str(row.get('id') or '')
            if not cid:
                continue
            by_id[cid] = {
                'meta_campaign_id': cid,
                'name': str(row.get('name') or ''),
                'status': row.get('status'),
                'spend': Decimal('0'),
                'impressions': 0,
                'link_clicks': 0,
            }

        insight_rows = self._paginate(
            f'{GRAPH_BASE}/{self._account}/insights',
            {
                'fields': 'campaign_id,spend,impressions,actions',
                'level': 'campaign',
                'date_preset': 'maximum',
                'limit': 100,
            },
        )
        for row in insight_rows:
            cid = str(row.get('campaign_id') or '')
            if not cid or cid not in by_id:
                continue
            by_id[cid]['spend'] = Decimal(str(row.get('spend') or '0'))
            by_id[cid]['impressions'] = int(row.get('impressions') or 0)
            by_id[cid]['link_clicks'] = self._link_clicks_from_actions(row.get('actions'))

        return list(by_id.values())
