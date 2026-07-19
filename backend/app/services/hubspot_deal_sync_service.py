"""Refresh HubSpot deals from the API and sync linked lead status/stage."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func

from app import db
from app.models.hubspot_config import HubSpotConfig
from app.models.hubspot_deal import HubSpotDeal
from app.models.hubspot_match import HubSpotMatch
from app.models.lead import Lead
from app.services.hubspot_client_service import HubSpotClientService
from app.services.hubspot_matcher_service import HubSpotMatcherService

logger = logging.getLogger(__name__)

DEAL_API_PROPERTIES = (
    'dealname,pipeline,dealstage,closedate,amount,'
    'county_assessor_pin,pin,address,city,state,zip,hs_object_id,'
    'createdate,hs_lastmodifieddate,deal_source,description'
)

# Properties required in cached deal payload for command-center display.
DEAL_CONTEXT_PROPERTY_KEYS = ('deal_source', 'description')

TASK_API_PROPERTIES = (
    'hs_task_status,hs_task_subject,hs_timestamp,hs_task_body'
)


def hubspot_stale_threshold_hours() -> int:
    try:
        return max(1, int(os.environ.get('HUBSPOT_DEAL_STALE_HOURS', '24')))
    except ValueError:
        return 24


class HubSpotDealSyncService:
    """Live deal refresh + lead enrichment for confirmed HubSpot matches."""

    def __init__(self, client: Optional[HubSpotClientService] = None):
        self._client = client
        self._stage_label_map: Optional[dict[str, str]] = None

    def _get_client(self) -> HubSpotClientService:
        if self._client is not None:
            return self._client
        config = HubSpotConfig.query.order_by(HubSpotConfig.id.desc()).first()
        if config is None:
            raise RuntimeError('No HubSpot configuration found')
        self._client = HubSpotClientService(config)
        return self._client

    def get_stage_label_map(self) -> dict[str, str]:
        if self._stage_label_map is None:
            try:
                self._stage_label_map = self._get_client().fetch_pipeline_stage_labels('deals')
            except Exception as exc:
                logger.warning('Could not load HubSpot stage labels: %s', exc)
                self._stage_label_map = {}
        return self._stage_label_map

    def refresh_deal_from_api(self, hubspot_id: str) -> Optional[HubSpotDeal]:
        """Fetch live deal from HubSpot and upsert hubspot_deals."""
        from app.tasks.hubspot_tasks import _upsert_hubspot_record

        client = self._get_client()
        record = client._get(
            f'/crm/v3/objects/deals/{hubspot_id}',
            {'properties': DEAL_API_PROPERTIES},
        )
        _upsert_hubspot_record(
            db, HubSpotDeal, hubspot_id, record, run_id=None,
        )
        db.session.commit()
        return HubSpotDeal.query.filter_by(hubspot_id=hubspot_id).first()

    def enrich_confirmed_lead_for_deal(
        self,
        deal: HubSpotDeal,
        *,
        stage_label_map: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """Enrich the lead linked by a confirmed deal match, if any."""
        match = HubSpotMatch.query.filter_by(
            hubspot_record_type='deal',
            hubspot_id=deal.hubspot_id,
            status='confirmed',
            internal_record_type='lead',
        ).filter(HubSpotMatch.internal_record_id.isnot(None)).first()
        if match is None:
            return {'lead_id': None, 'enriched_fields': []}

        lead = Lead.query.get(match.internal_record_id)
        if lead is None:
            return {'lead_id': None, 'enriched_fields': []}

        labels = stage_label_map if stage_label_map is not None else self.get_stage_label_map()
        matcher = HubSpotMatcherService()
        enriched = matcher.enrich_lead_from_deal(
            lead, deal, labels, sync_deal_context=True,
        )
        lead.last_hubspot_sync_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.add(lead)
        db.session.commit()
        return {'lead_id': lead.id, 'enriched_fields': enriched}

    def refresh_and_enrich_deal(self, hubspot_id: str) -> dict[str, Any]:
        """Live API refresh then enrich the linked lead."""
        deal = self.refresh_deal_from_api(hubspot_id)
        if deal is None:
            return {'hubspot_id': hubspot_id, 'refreshed': False, 'lead_id': None, 'enriched_fields': []}
        result = self.enrich_confirmed_lead_for_deal(deal)
        result.update({'hubspot_id': hubspot_id, 'refreshed': True})
        return result

    def refresh_and_enrich_lead(
        self,
        lead_id: int,
        *,
        include_tasks: bool = False,
    ) -> dict[str, Any]:
        """Refresh all confirmed deals for a lead; enrich lead fields from the newest deal.

        ``include_tasks`` defaults to False so deal refresh cannot silently mutate
        open LeadTasks. Pass True only for explicit sync (POST .../hubspot-sync)
        or intentional background catch-up callers.
        """
        from app.models.hubspot_deal import HubSpotDeal

        matches = HubSpotMatch.query.filter_by(
            hubspot_record_type='deal',
            internal_record_type='lead',
            internal_record_id=lead_id,
            status='confirmed',
        ).all()
        if not matches:
            return {'lead_id': lead_id, 'synced': False, 'reason': 'no_confirmed_deal'}

        def _match_sort_key(match: HubSpotMatch) -> tuple:
            deal = HubSpotDeal.query.filter_by(hubspot_id=match.hubspot_id).first()
            updated = deal.last_updated_at if deal else None
            return (updated or datetime.min.replace(tzinfo=None), match.hubspot_id)

        ordered_matches = sorted(matches, key=_match_sort_key, reverse=True)

        labels = self.get_stage_label_map()
        all_enriched: list[str] = []
        enriched_primary = False
        for match in ordered_matches:
            deal = self.refresh_deal_from_api(match.hubspot_id)
            if deal is None:
                continue
            if not enriched_primary:
                result = self.enrich_confirmed_lead_for_deal(deal, stage_label_map=labels)
                all_enriched.extend(result.get('enriched_fields') or [])
                enriched_primary = True

        task_sync: dict[str, Any] = {}
        if include_tasks:
            task_sync = self.sync_tasks_for_lead(lead_id)

        lead = Lead.query.get(lead_id)
        return {
            'lead_id': lead_id,
            'synced': True,
            'enriched_fields': all_enriched,
            'task_sync': task_sync,
            'lead_status': lead.lead_status if lead else None,
            'hubspot_deal_stage': lead.hubspot_deal_stage if lead else None,
            'last_hubspot_sync_at': (
                lead.last_hubspot_sync_at.isoformat() if lead and lead.last_hubspot_sync_at else None
            ),
        }

    def sync_tasks_for_lead(self, lead_id: int) -> dict[str, Any]:
        """Fetch live HubSpot tasks for the lead's confirmed deal and reconcile locally."""
        from app.services.hubspot_activity_converter_service import HubSpotActivityConverterService

        match = HubSpotMatch.query.filter_by(
            hubspot_record_type='deal',
            internal_record_type='lead',
            internal_record_id=lead_id,
            status='confirmed',
        ).first()
        if match is None:
            return {'lead_id': lead_id, 'synced': False, 'reason': 'no_confirmed_deal'}

        client = self._get_client()
        converter = HubSpotActivityConverterService()
        stats = {'created': 0, 'updated': 0, 'unchanged': 0, 'errors': 0}

        try:
            assoc = client._get(
                f'/crm/v4/objects/deals/{match.hubspot_id}/associations/tasks',
                {},
            )
            task_ids = [
                str(row.get('toObjectId'))
                for row in (assoc.get('results') or [])
                if row.get('toObjectId') is not None
            ]
        except Exception as exc:
            logger.warning('sync_tasks_for_lead: association fetch failed lead_id=%s: %s', lead_id, exc)
            return {'lead_id': lead_id, 'synced': False, 'reason': 'association_fetch_failed'}

        for task_id in task_ids:
            try:
                record = client._get(
                    f'/crm/v3/objects/tasks/{task_id}',
                    {'properties': TASK_API_PROPERTIES},
                )
                outcome = converter.sync_task_from_crm_v3(record, lead_id=lead_id)
                stats[outcome] = stats.get(outcome, 0) + 1
            except Exception as exc:
                stats['errors'] += 1
                logger.warning(
                    'sync_tasks_for_lead: failed task %s for lead_id=%s: %s',
                    task_id, lead_id, exc,
                )
                db.session.rollback()

        return {'lead_id': lead_id, 'synced': True, **stats}

    def sync_task_to_linked_leads(self, task_record: dict) -> dict[str, Any]:
        """Sync a single live HubSpot CRM task onto every linked confirmed lead."""
        from app.services.hubspot_activity_converter_service import HubSpotActivityConverterService

        task_id = str(task_record.get('id', ''))
        if not task_id:
            return {'synced': False, 'reason': 'missing_task_id'}

        client = self._get_client()
        converter = HubSpotActivityConverterService()
        stats = {'leads_synced': 0, 'created': 0, 'updated': 0, 'unchanged': 0, 'errors': 0}

        try:
            assoc = client._get(
                f'/crm/v4/objects/tasks/{task_id}/associations/deals',
                {},
            )
            deal_ids = [
                str(row.get('toObjectId'))
                for row in (assoc.get('results') or [])
                if row.get('toObjectId') is not None
            ]
        except Exception as exc:
            logger.warning('sync_task_to_linked_leads: association fetch failed task=%s: %s', task_id, exc)
            return {'synced': False, 'reason': 'association_fetch_failed'}

        seen_lead_ids: set[int] = set()
        for deal_id in deal_ids:
            match = HubSpotMatch.query.filter_by(
                hubspot_record_type='deal',
                hubspot_id=deal_id,
                status='confirmed',
                internal_record_type='lead',
            ).filter(HubSpotMatch.internal_record_id.isnot(None)).first()
            if match is None or match.internal_record_id in seen_lead_ids:
                continue
            seen_lead_ids.add(match.internal_record_id)
            try:
                outcome = converter.sync_task_from_crm_v3(task_record, lead_id=match.internal_record_id)
                stats[outcome] = stats.get(outcome, 0) + 1
                stats['leads_synced'] += 1
            except Exception as exc:
                stats['errors'] += 1
                logger.warning(
                    'sync_task_to_linked_leads: failed task %s lead_id=%s: %s',
                    task_id, match.internal_record_id, exc,
                )
                db.session.rollback()

        return {'synced': True, 'task_id': task_id, **stats}

    def sync_all_confirmed_lead_tasks(self, *, limit: int = 200) -> dict[str, Any]:
        """Live-sync HubSpot tasks for every lead with a confirmed deal match."""
        lead_ids = [
            row[0]
            for row in (
                db.session.query(HubSpotMatch.internal_record_id)
                .join(Lead, Lead.id == HubSpotMatch.internal_record_id)
                .filter_by(
                    hubspot_record_type='deal',
                    status='confirmed',
                    internal_record_type='lead',
                )
                .filter(HubSpotMatch.internal_record_id.isnot(None))
                .group_by(HubSpotMatch.internal_record_id)
                .order_by(func.min(Lead.last_hubspot_sync_at).asc().nullsfirst())
                .limit(limit)
                .all()
            )
        ]
        stats = {'leads_synced': 0, 'created': 0, 'updated': 0, 'unchanged': 0, 'errors': 0}
        affected_lead_ids: list[int] = []
        for lead_id in lead_ids:
            try:
                result = self.sync_tasks_for_lead(lead_id)
                if not result.get('synced'):
                    continue
                stats['leads_synced'] += 1
                stats['created'] += result.get('created', 0)
                stats['updated'] += result.get('updated', 0)
                stats['unchanged'] += result.get('unchanged', 0)
                stats['errors'] += result.get('errors', 0)
                if result.get('created', 0) or result.get('updated', 0):
                    affected_lead_ids.append(lead_id)
            except Exception as exc:
                stats['errors'] += 1
                logger.warning('sync_all_confirmed_lead_tasks: failed lead_id=%s: %s', lead_id, exc)
                db.session.rollback()

        logger.info('sync_all_confirmed_lead_tasks complete: %s', stats)
        stats['affected_lead_ids'] = affected_lead_ids
        return stats

    def sweep_stale_open_hubspot_tasks(
        self,
        *,
        dry_run: bool = True,
        limit: int = 500,
    ) -> dict[str, int]:
        """Find HubSpot-imported tasks still open locally but completed in HubSpot.

        In dry-run mode, only reports candidates (engagement metadata COMPLETED,
        or live CRM v3 COMPLETED when not dry-run). In apply mode, reconciles via
        live CRM v3 sync so authoritative status wins.
        """
        from app.models.hubspot_engagement import HubSpotEngagement
        from app.models.task import Task
        from app.models.task_association import TaskAssociation
        from app.services.hubspot_activity_converter_service import HubSpotActivityConverterService

        stats = {
            'scanned': 0,
            'stale_found': 0,
            'fixed': 0,
            'errors': 0,
            'skipped_no_lead': 0,
        }

        tasks = (
            Task.query
            .filter(
                Task.source == 'hubspot_import',
                Task.status.in_(('open', 'overdue')),
                Task.hubspot_task_id.isnot(None),
            )
            .order_by(Task.updated_at.asc())
            .limit(limit)
            .all()
        )

        converter = HubSpotActivityConverterService()
        client = None if dry_run else self._get_client()

        for task in tasks:
            stats['scanned'] += 1
            hs_id = str(task.hubspot_task_id)

            engagement = HubSpotEngagement.query.filter_by(hubspot_id=hs_id).first()
            eng_status = ''
            if engagement and (engagement.raw_payload or {}).get('metadata'):
                eng_status = (
                    (engagement.raw_payload.get('metadata') or {}).get('status') or ''
                ).upper()

            is_stale = eng_status == 'COMPLETED'
            record = None

            if not is_stale and not dry_run and client is not None:
                try:
                    record = client._get(
                        f'/crm/v3/objects/tasks/{hs_id}',
                        {'properties': TASK_API_PROPERTIES},
                    )
                    hs_live = (
                        (record.get('properties') or {}).get('hs_task_status') or ''
                    ).upper()
                    is_stale = hs_live == 'COMPLETED'
                except Exception as exc:
                    stats['errors'] += 1
                    logger.warning(
                        'sweep_stale_open_hubspot_tasks: CRM fetch failed task=%s: %s',
                        hs_id, exc,
                    )
                    continue

            if not is_stale:
                continue

            stats['stale_found'] += 1
            if dry_run:
                logger.info(
                    'stale task (dry-run): Task(id=%s) hubspot_task_id=%s local=%s',
                    task.id, hs_id, task.status,
                )
                continue

            lead_id = task.lead_id
            if lead_id is None:
                assoc = TaskAssociation.query.filter_by(
                    task_id=task.id,
                    target_type='lead',
                ).first()
                lead_id = assoc.target_id if assoc else None
            if lead_id is None:
                stats['skipped_no_lead'] += 1
                continue

            try:
                if record is None:
                    record = client._get(
                        f'/crm/v3/objects/tasks/{hs_id}',
                        {'properties': TASK_API_PROPERTIES},
                    )
                outcome = converter.sync_task_from_crm_v3(record, lead_id=lead_id)
                if outcome in ('created', 'updated'):
                    stats['fixed'] += 1
            except Exception as exc:
                stats['errors'] += 1
                logger.warning(
                    'sweep_stale_open_hubspot_tasks: fix failed task=%s: %s',
                    hs_id, exc,
                )
                db.session.rollback()

        logger.info('sweep_stale_open_hubspot_tasks complete: %s', stats)
        return stats

    def refresh_all_confirmed_deals(self, *, limit: int = 200) -> dict[str, int]:
        """Refresh every confirmed deal match from HubSpot (batched)."""
        matches = (
            HubSpotMatch.query
            .filter_by(hubspot_record_type='deal', status='confirmed', internal_record_type='lead')
            .filter(HubSpotMatch.internal_record_id.isnot(None))
            .order_by(HubSpotMatch.updated_at.asc())
            .limit(limit)
            .all()
        )
        labels = self.get_stage_label_map()
        stats = {'deals_refreshed': 0, 'leads_enriched': 0, 'tasks_created': 0, 'tasks_updated': 0, 'errors': 0}
        seen_deals: set[str] = set()
        seen_lead_ids: set[int] = set()

        for match in matches:
            if match.hubspot_id in seen_deals:
                continue
            seen_deals.add(match.hubspot_id)
            try:
                deal = self.refresh_deal_from_api(match.hubspot_id)
                if deal is None:
                    continue
                stats['deals_refreshed'] += 1
                result = self.enrich_confirmed_lead_for_deal(deal, stage_label_map=labels)
                if result.get('enriched_fields'):
                    stats['leads_enriched'] += 1
                lead_id = result.get('lead_id')
                if lead_id and lead_id not in seen_lead_ids:
                    seen_lead_ids.add(lead_id)
                    task_result = self.sync_tasks_for_lead(lead_id)
                    stats['tasks_created'] += task_result.get('created', 0)
                    stats['tasks_updated'] += task_result.get('updated', 0)
            except Exception as exc:
                stats['errors'] += 1
                logger.warning(
                    'refresh_all_confirmed_deals: failed deal %s: %s',
                    match.hubspot_id, exc,
                )
                db.session.rollback()

        logger.info('refresh_all_confirmed_deals complete: %s', stats)
        return stats

    @staticmethod
    def get_lead_sync_health(lead_id: int) -> dict[str, Any]:
        """Return sync staleness metadata for command center UI."""
        threshold = timedelta(hours=hubspot_stale_threshold_hours())
        now = datetime.utcnow()

        match = HubSpotMatch.query.filter_by(
            hubspot_record_type='deal',
            internal_record_type='lead',
            internal_record_id=lead_id,
            status='confirmed',
        ).first()

        if match is None:
            return {
                'hubspot_has_confirmed_deal': False,
                'hubspot_sync_stale': False,
                'hubspot_deal_last_updated_at': None,
            }

        deal = HubSpotDeal.query.filter_by(hubspot_id=match.hubspot_id).first()
        lead = Lead.query.get(lead_id)
        deal_updated = deal.last_updated_at if deal else None
        last_sync = lead.last_hubspot_sync_at if lead else None

        stale = False
        if last_sync is None:
            stale = True
        elif now - last_sync > threshold:
            stale = True
        elif deal_updated and last_sync < deal_updated - timedelta(minutes=1):
            # Cached deal newer than last lead enrichment
            stale = True

        return {
            'hubspot_has_confirmed_deal': True,
            'hubspot_sync_stale': stale,
            'hubspot_deal_last_updated_at': (
                deal_updated.isoformat() if deal_updated else None
            ),
        }

    @staticmethod
    def deal_context_from_payload(raw_payload: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
        """Extract deal_source and description from a HubSpot deal raw_payload."""
        props = (raw_payload or {}).get('properties') or {}
        source = (props.get('deal_source') or '').strip() or None
        description = (props.get('description') or '').strip() or None
        return source, description

    @staticmethod
    def lead_needs_deal_context_enrichment(lead: Optional[Lead]) -> bool:
        """True when the lead is missing deal_source and/or deal_description."""
        if lead is None:
            return False
        return (
            not (lead.deal_source or '').strip()
            or not (lead.deal_description or '').strip()
        )

    @staticmethod
    def deal_missing_context_properties(deal: Optional[HubSpotDeal]) -> bool:
        """True when cached deal payload lacks deal_source/description from HubSpot."""
        if deal is None:
            return True
        props = (deal.raw_payload or {}).get('properties') or {}
        if any(key not in props for key in DEAL_CONTEXT_PROPERTY_KEYS):
            return True
        return False

    @staticmethod
    def enrich_lead_deal_context_if_needed(lead_id: int) -> bool:
        """Ensure lead.deal_source/description are populated from the linked HubSpot deal.

        Enriches from the cached deal when possible; refreshes from the HubSpot API
        when the cache is missing those properties. Handles the common case where the
        deal payload already has context but the lead columns were never backfilled.
        """
        lead = Lead.query.get(lead_id)
        if not HubSpotDealSyncService.lead_needs_deal_context_enrichment(lead):
            return False

        match = HubSpotMatch.query.filter_by(
            hubspot_record_type='deal',
            internal_record_type='lead',
            internal_record_id=lead_id,
            status='confirmed',
        ).first()
        if match is None:
            return False

        try:
            svc = HubSpotDealSyncService()
            deal = HubSpotDeal.query.filter_by(hubspot_id=match.hubspot_id).first()
            if deal is None:
                deal = svc.refresh_deal_from_api(match.hubspot_id)
            elif HubSpotDealSyncService.deal_missing_context_properties(deal):
                deal = svc.refresh_deal_from_api(match.hubspot_id)

            if deal is None:
                return False

            result = svc.enrich_confirmed_lead_for_deal(deal)
            enriched = result.get('enriched_fields') or []
            if enriched:
                logger.info(
                    'Enriched lead_id=%s deal context from HubSpot deal %s: %s',
                    lead_id, match.hubspot_id, enriched,
                )
            return bool(enriched)
        except Exception as exc:
            logger.warning(
                'enrich_lead_deal_context_if_needed failed lead_id=%s: %s',
                lead_id, exc,
            )
            db.session.rollback()
            return False

    @staticmethod
    def ensure_deal_context_for_lead(lead_id: int) -> bool:
        """Refresh linked HubSpot deal(s) when context properties are absent from cache."""
        return HubSpotDealSyncService.enrich_lead_deal_context_if_needed(lead_id)

    @staticmethod
    def auto_sync_lead_if_stale(lead_id: int) -> bool:
        """Retired: never auto-pull HubSpot from user/view paths.

        Opening Command Center, changing status, or other interactive flows must
        not refresh deals or sync tasks as a side effect. Historical catch-up
        stays on Celery Beat, webhooks, or explicit ``POST .../hubspot-sync``.

        Kept as a no-op so any leftover callers fail closed. ``lead_id`` is
        accepted for call-site compatibility.
        """
        import os
        if os.environ.get('HUBSPOT_AUTO_SYNC_ON_VIEW', 'false').lower() == 'true':
            logger.warning(
                'HUBSPOT_AUTO_SYNC_ON_VIEW=true is ignored; auto_sync_lead_if_stale '
                'is retired (lead_id=%s). Use POST .../hubspot-sync or Beat/webhooks.',
                lead_id,
            )
        return False
