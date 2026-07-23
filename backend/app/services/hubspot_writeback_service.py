"""HubSpot write-back — push platform leads to HubSpot as deals (quick-add slice)."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from app import db
from app.models.hubspot_config import HubSpotConfig
from app.models.hubspot_deal import HubSpotDeal
from app.models.hubspot_match import HubSpotMatch
from app.models.hubspot_platform_write import HubSpotPlatformWrite
from app.models.lead import Lead
from app.services.hubspot_client_service import HubSpotClientService
from app.services.hubspot_stage_mapping import hubspot_stage_label_for_lead_status
from app.tasks.hubspot_tasks import _upsert_hubspot_record

logger = logging.getLogger(__name__)

# HubSpot deal_source is an enum; walk-by quick-adds default to this value.
HUBSPOT_WALK_BY_DEAL_SOURCE = 'Driving For Dollars'
DEFAULT_QUICK_ADD_DEAL_SOURCE = HUBSPOT_WALK_BY_DEAL_SOURCE
DEFAULT_DEAL_STAGE_LABEL = 'Skip Trace'


def hubspot_write_back_enabled() -> bool:
    """True when platform→HubSpot writes are allowed (quick-add deals, stage push, tasks)."""
    return os.getenv('HUBSPOT_WRITE_BACK_ENABLED', 'false').lower() in ('1', 'true', 'yes')


def hubspot_pull_enabled() -> bool:
    """True when HubSpot→platform inbound sync is allowed.

    Default is false — the platform is the source of truth for pipeline status.
    Set HUBSPOT_PULL_ENABLED=true only when actively using HubSpot as CRM.
    """
    return os.getenv('HUBSPOT_PULL_ENABLED', 'false').lower() in ('1', 'true', 'yes')


class HubSpotWriteBackService:
    """Create or update HubSpot deals from platform leads."""

    def __init__(self, client: HubSpotClientService | None = None):
        self._client = client

    def _get_client(self) -> HubSpotClientService:
        if self._client is not None:
            return self._client
        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if config is None:
            raise RuntimeError('No HubSpot configuration found')
        return HubSpotClientService(config)

    @staticmethod
    def _record_platform_write(object_type: str, hubspot_id: str) -> None:
        db.session.add(HubSpotPlatformWrite(
            object_type=object_type,
            hubspot_id=str(hubspot_id),
        ))
        db.session.flush()

    @staticmethod
    def _confirmed_deal_match(lead_id: int) -> HubSpotMatch | None:
        return HubSpotMatch.query.filter_by(
            hubspot_record_type='deal',
            internal_record_type='lead',
            internal_record_id=lead_id,
            status='confirmed',
        ).first()

    def resolve_deal_stage(self, stage_label: str = DEFAULT_DEAL_STAGE_LABEL) -> tuple[str | None, str | None]:
        """Return (pipeline_id, stage_id) for a stage display label."""
        client = self._get_client()
        response = client._get('/crm/v3/pipelines/deals')
        target = stage_label.strip().lower()
        for pipeline in response.get('results', []):
            pipeline_id = pipeline.get('id')
            for stage in pipeline.get('stages', []):
                label = (stage.get('label') or '').strip().lower()
                if label == target:
                    return pipeline_id, stage.get('id')
        return None, None

    def resolve_deal_stage_in_pipeline(
        self,
        stage_label: str,
        pipeline_id: str,
    ) -> str | None:
        """Return stage_id for *stage_label* within a specific pipeline."""
        client = self._get_client()
        response = client._get('/crm/v3/pipelines/deals')
        target = stage_label.strip().lower()
        for pipeline in response.get('results', []):
            if pipeline.get('id') != pipeline_id:
                continue
            for stage in pipeline.get('stages', []):
                label = (stage.get('label') or '').strip().lower()
                if label == target:
                    return stage.get('id')
        return None

    @staticmethod
    def _merged_deal_raw_payload(
        hubspot_deal_id: str,
        record: dict | None,
        sent_properties: dict[str, str],
    ) -> dict:
        """Preserve cached deal properties when HubSpot returns a partial update."""
        if isinstance(record, dict) and record.get('properties'):
            return record

        existing = HubSpotDeal.query.filter_by(hubspot_id=hubspot_deal_id).first()
        base: dict[str, Any] = dict(existing.raw_payload) if existing and existing.raw_payload else {
            'id': hubspot_deal_id,
        }
        merged_props = dict((base.get('properties') or {}))
        merged_props.update(sent_properties)
        base['id'] = hubspot_deal_id
        base['properties'] = merged_props
        return base

    def _deal_properties_from_lead(
        self,
        lead: Lead,
        pipeline_id: str | None,
        stage_id: str | None,
        *,
        include_stage: bool = True,
    ) -> dict[str, str]:
        address = (lead.property_street or '').strip()
        props: dict[str, str] = {
            'dealname': address or f'Lead {lead.id}',
            'address': address,
            'deal_source': (lead.deal_source or '').strip() or HUBSPOT_WALK_BY_DEAL_SOURCE,
        }
        if (lead.deal_description or '').strip():
            props['description'] = lead.deal_description.strip()[:65536]
        if include_stage and stage_id:
            props['dealstage'] = stage_id
        if include_stage and pipeline_id:
            props['pipeline'] = pipeline_id
        pin = (lead.county_assessor_pin or '').strip()
        if pin:
            props['county_assessor_pin'] = pin
        return props

    def push_lead_as_deal(self, lead_id: int) -> dict[str, Any]:
        """Create or update a HubSpot deal for *lead_id*."""
        if not hubspot_write_back_enabled():
            return {'synced': False, 'action': 'skipped', 'reason': 'write_back_disabled'}

        lead = db.session.get(Lead, lead_id)
        if lead is None:
            return {'synced': False, 'action': 'skipped', 'reason': 'lead_not_found'}

        if not (lead.property_street or '').strip():
            return {'synced': False, 'action': 'skipped', 'reason': 'missing_address'}

        try:
            client = self._get_client()
        except Exception as exc:
            logger.warning('HubSpot write-back: no client for lead %s: %s', lead_id, exc)
            return {'synced': False, 'action': 'skipped', 'reason': 'no_hubspot_config', 'error': str(exc)}

        existing_match = self._confirmed_deal_match(lead_id)
        pipeline_id: str | None = None
        stage_id: str | None = None
        if existing_match is None:
            try:
                pipeline_id, stage_id = self.resolve_deal_stage()
            except Exception as exc:
                logger.warning('HubSpot write-back: stage lookup failed for lead %s: %s', lead_id, exc)
                return {
                    'synced': False,
                    'action': 'skipped',
                    'reason': 'stage_lookup_failed',
                    'error': str(exc),
                }
            if not stage_id:
                return {
                    'synced': False,
                    'action': 'skipped',
                    'reason': 'stage_not_found',
                    'error': f'Could not resolve HubSpot stage "{DEFAULT_DEAL_STAGE_LABEL}"',
                }

        properties = self._deal_properties_from_lead(
            lead,
            pipeline_id,
            stage_id,
            include_stage=existing_match is None,
        )

        hubspot_deal_id = ''
        action: str | None = None
        try:
            if existing_match:
                hubspot_deal_id = existing_match.hubspot_id
                self._record_platform_write('deal', hubspot_deal_id)
                record = client.update_deal(hubspot_deal_id, properties)
                action = 'updated'
            else:
                record = client.create_deal(properties)
                hubspot_deal_id = str(record.get('id', ''))
                if not hubspot_deal_id:
                    raise RuntimeError('HubSpot deal create returned no id')
                self._record_platform_write('deal', hubspot_deal_id)
                action = 'created'

            raw_payload = record if isinstance(record, dict) and record.get('properties') else {
                'id': hubspot_deal_id,
                'properties': properties,
            }
            _upsert_hubspot_record(
                db=db,
                model_class=HubSpotDeal,
                hubspot_id=hubspot_deal_id,
                raw_payload=raw_payload,
                run_id=None,
            )

            match = HubSpotMatch.query.filter_by(
                hubspot_record_type='deal',
                hubspot_id=hubspot_deal_id,
            ).first()
            if match is None:
                match = HubSpotMatch(
                    hubspot_record_type='deal',
                    hubspot_id=hubspot_deal_id,
                    internal_record_type='lead',
                    internal_record_id=lead_id,
                    confidence='HIGH',
                    status='confirmed',
                    matching_criteria='quick_add_writeback',
                )
                db.session.add(match)
            else:
                match.internal_record_type = 'lead'
                match.internal_record_id = lead_id
                match.confidence = 'HIGH'
                match.status = 'confirmed'
                match.matching_criteria = 'quick_add_writeback'
                match.updated_at = datetime.utcnow()

            if action == 'created':
                # Mirror HubSpot default stage; canonical status remains lead_status.
                lead.hubspot_deal_stage = DEFAULT_DEAL_STAGE_LABEL
            lead.last_hubspot_sync_at = datetime.utcnow()
            db.session.commit()

            return {
                'synced': True,
                'action': action,
                'hubspot_deal_id': hubspot_deal_id,
                'lead_id': lead_id,
            }
        except Exception as exc:
            db.session.rollback()
            if action == 'created' and hubspot_deal_id:
                try:
                    recovery_match = HubSpotMatch(
                        hubspot_record_type='deal',
                        hubspot_id=hubspot_deal_id,
                        internal_record_type='lead',
                        internal_record_id=lead_id,
                        confidence='HIGH',
                        status='confirmed',
                        matching_criteria='quick_add_writeback_recovery',
                    )
                    db.session.add(recovery_match)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
            logger.exception('HubSpot write-back failed for lead %s', lead_id)
            return {
                'synced': False,
                'action': 'failed',
                'lead_id': lead_id,
                'error': str(exc),
            }

    def push_deal_stage_for_lead(self, lead_id: int, lead_status: str | None = None) -> dict[str, Any]:
        """Push a platform lead_status to the linked HubSpot deal stage.

        Gated by ``HUBSPOT_WRITE_BACK_ENABLED`` (same as quick-add deal create).
        """
        if not hubspot_write_back_enabled():
            return {
                'synced': False,
                'action': 'skipped',
                'reason': 'write_back_disabled',
            }

        lead = db.session.get(Lead, lead_id)
        if lead is None:
            return {'synced': False, 'action': 'skipped', 'reason': 'lead_not_found'}

        if lead_status is not None and lead_status != lead.lead_status:
            return {
                'synced': False,
                'action': 'skipped',
                'reason': 'status_mismatch',
                'lead_status': lead.lead_status,
            }

        effective_status = lead.lead_status
        stage_label = hubspot_stage_label_for_lead_status(effective_status)
        if not stage_label:
            return {
                'synced': False,
                'action': 'skipped',
                'reason': 'unmapped_lead_status',
                'lead_status': effective_status,
            }

        existing_match = self._confirmed_deal_match(lead_id)
        if existing_match is None:
            return {'synced': False, 'action': 'skipped', 'reason': 'no_confirmed_deal_match'}

        try:
            client = self._get_client()
        except Exception as exc:
            logger.warning(
                'HubSpot stage push: no client for lead %s: %s', lead_id, exc,
            )
            return {
                'synced': False,
                'action': 'skipped',
                'reason': 'no_hubspot_config',
                'error': str(exc),
            }

        hubspot_deal_id = existing_match.hubspot_id
        cached_deal = HubSpotDeal.query.filter_by(hubspot_id=hubspot_deal_id).first()
        cached_pipeline_id = (
            (cached_deal.raw_payload or {}).get('properties', {}).get('pipeline')
            if cached_deal and cached_deal.raw_payload
            else None
        )

        try:
            resolved_pipeline_id: str | None = None
            if cached_pipeline_id:
                stage_id = self.resolve_deal_stage_in_pipeline(
                    stage_label,
                    str(cached_pipeline_id),
                )
            else:
                resolved_pipeline_id, stage_id = self.resolve_deal_stage(stage_label)
        except Exception as exc:
            logger.warning(
                'HubSpot stage push: stage lookup failed for lead %s: %s', lead_id, exc,
            )
            return {
                'synced': False,
                'action': 'skipped',
                'reason': 'stage_lookup_failed',
                'error': str(exc),
            }

        if not stage_id:
            return {
                'synced': False,
                'action': 'skipped',
                'reason': 'stage_not_found',
                'error': f'Could not resolve HubSpot stage "{stage_label}"',
            }

        # Existing deals: update dealstage only so we do not move the deal across pipelines.
        properties: dict[str, str] = {'dealstage': stage_id}
        if not cached_pipeline_id and resolved_pipeline_id:
            properties['pipeline'] = resolved_pipeline_id

        try:
            self._record_platform_write('deal', hubspot_deal_id)
            record = client.update_deal(hubspot_deal_id, properties)
            raw_payload = self._merged_deal_raw_payload(hubspot_deal_id, record, properties)
            _upsert_hubspot_record(
                db=db,
                model_class=HubSpotDeal,
                hubspot_id=hubspot_deal_id,
                raw_payload=raw_payload,
                run_id=None,
            )
            lead.hubspot_deal_stage = stage_label  # read-only HubSpot mirror
            lead.last_hubspot_sync_at = datetime.utcnow()
            db.session.add(lead)
            db.session.commit()

            return {
                'synced': True,
                'action': 'stage_updated',
                'hubspot_deal_id': hubspot_deal_id,
                'lead_id': lead_id,
                'hubspot_deal_stage': stage_label,
            }
        except Exception as exc:
            db.session.rollback()
            logger.warning(
                'HubSpot stage push failed for lead %s: %s', lead_id, exc,
            )
            return {
                'synced': False,
                'action': 'failed',
                'lead_id': lead_id,
                'error': str(exc),
            }
