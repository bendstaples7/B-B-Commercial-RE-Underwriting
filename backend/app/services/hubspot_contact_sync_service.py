"""Refresh HubSpot contacts from the API and sync phone confidence to leads."""
from __future__ import annotations

import logging
from typing import Optional

from app import db
from app.models.hubspot_config import HubSpotConfig
from app.models.hubspot_contact import HubSpotContact
from app.services.hubspot_client_service import HubSpotClientService, CONTACT_API_PROPERTIES

logger = logging.getLogger(__name__)


class HubSpotContactSyncService:
    """Live HubSpot contact refresh — mirrors HubSpotDealSyncService.refresh_deal_from_api."""

    def __init__(self, client: HubSpotClientService | None = None):
        self._client = client

    def _get_client(self) -> HubSpotClientService:
        if self._client is None:
            config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
            if config is None:
                raise RuntimeError('No HubSpotConfig found')
            self._client = HubSpotClientService(config)
        return self._client

    def refresh_contact_from_api(self, hubspot_id: str) -> Optional[HubSpotContact]:
        """Fetch live contact from HubSpot and upsert hubspot_contacts."""
        from app.tasks.hubspot_tasks import _upsert_hubspot_record

        client = self._get_client()
        record = client._get(
            f'/crm/v3/objects/contacts/{hubspot_id}',
            {'properties': CONTACT_API_PROPERTIES},
        )
        _upsert_hubspot_record(
            db, HubSpotContact, hubspot_id, record, run_id=None,
        )
        db.session.commit()
        return HubSpotContact.query.filter_by(hubspot_id=hubspot_id).first()
