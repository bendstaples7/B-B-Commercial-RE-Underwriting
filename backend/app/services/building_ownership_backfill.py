"""Backfill building ownership / condo analysis for commercial Cook County leads."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app import db
from app.models.address_group_analysis import AddressGroupAnalysis
from app.models.lead import Lead
from app.services.building_ownership_service import BuildingOwnershipService
from app.services.gis.routing import _resolve_market, _COOK_COUNTY_CITIES

logger = logging.getLogger(__name__)

COOK_COUNTY_MARKET = 'cook_county_il'
BACKFILL_BATCH_SIZE = 50
BACKFILL_PER_RUN_CAP = 100
BACKFILL_STALE_DAYS = 30
TERMINAL_STATUSES = frozenset({'suppressed', 'do_not_contact', 'deal_won', 'deal_lost'})


def dispatch_building_ownership_analysis(lead_id: int) -> bool:
    """Enqueue async building ownership analysis; fall back to sync if broker unavailable."""
    try:
        from celery_worker import building_ownership_analyze_lead_task
        building_ownership_analyze_lead_task.apply_async(args=[lead_id], ignore_result=True)
        logger.info('Dispatched building_ownership.analyze_lead for lead %s', lead_id)
        return True
    except Exception as exc:
        logger.warning(
            'Could not enqueue building_ownership.analyze_lead for lead %s, running sync: %s',
            lead_id,
            exc,
        )
        try:
            BuildingOwnershipService().analyze_lead(lead_id)
            return True
        except Exception as sync_exc:
            logger.error(
                'Sync building ownership analysis failed for lead %s: %s',
                lead_id,
                sync_exc,
            )
            return False


def maybe_schedule_building_ownership_analysis(lead: Lead) -> None:
    """Enqueue building ownership analysis when a commercial Cook County lead needs it."""
    if not lead_needs_building_ownership_analysis(lead):
        return
    dispatch_building_ownership_analysis(lead.id)


def is_commercial_cook_county_lead(lead: Lead) -> bool:
    if getattr(lead, 'lead_category', None) != 'commercial':
        return False
    if not (lead.property_street or '').strip():
        return False
    return _resolve_market(lead) == COOK_COUNTY_MARKET


def lead_needs_building_ownership_analysis(
    lead: Lead,
    *,
    stale_days: int = BACKFILL_STALE_DAYS,
) -> bool:
    """True when lead should be analyzed (never run, or stale non-overridden analysis)."""
    if not is_commercial_cook_county_lead(lead):
        return False
    if lead.lead_status in TERMINAL_STATUSES:
        return False
    if not lead.condo_analysis_id:
        return True

    analysis = db.session.get(AddressGroupAnalysis, lead.condo_analysis_id)
    if analysis is None:
        return True
    if analysis.manually_reviewed and analysis.manual_override_status:
        return False

    if not analysis.analyzed_at:
        return True
    analyzed_at = analysis.analyzed_at
    if analyzed_at.tzinfo is None:
        analyzed_at = analyzed_at.replace(tzinfo=timezone.utc)
    stale_before = datetime.now(timezone.utc) - timedelta(days=stale_days)
    return analyzed_at < stale_before


def query_lead_ids_for_building_ownership_backfill(
    *,
    last_id: int = 0,
    limit: int = 200,
) -> list[int]:
    """Return commercial Cook County lead ids after *last_id* that may need ownership analysis."""
    cook_cities = {city.upper() for city in _COOK_COUNTY_CITIES} | {'CHICAGO'}
    rows = (
        db.session.query(Lead.id)
        .filter(
            Lead.id > last_id,
            Lead.lead_category == 'commercial',
            Lead.property_street.isnot(None),
            Lead.property_street != '',
            Lead.property_city.isnot(None),
            db.func.upper(Lead.property_city).in_(cook_cities),
            ~Lead.lead_status.in_(TERMINAL_STATUSES),
        )
        .order_by(Lead.id)
        .limit(limit)
        .all()
    )
    return [row[0] for row in rows]


def backfill_building_ownership_analysis(
    *,
    batch_size: int = BACKFILL_BATCH_SIZE,
    per_run_cap: int = BACKFILL_PER_RUN_CAP,
    last_id: int = 0,
    enqueue_async: bool = False,
    stale_days: int = BACKFILL_STALE_DAYS,
) -> dict:
    """Analyze commercial Cook County leads missing or stale building ownership data.

    When *enqueue_async* is True, dispatches per-lead Celery tasks instead of
    running synchronously (useful for large manual backfills).
    """
    summary = {
        'status': 'completed',
        'processed': 0,
        'analyzed': 0,
        'enqueued': 0,
        'skipped': 0,
        'errors': 0,
        'last_id': last_id,
        'capped': False,
    }

    service = BuildingOwnershipService()
    cursor = last_id
    analyzed_count = 0

    while analyzed_count < per_run_cap:
        candidate_ids = query_lead_ids_for_building_ownership_backfill(
            last_id=cursor,
            limit=batch_size * 3,
        )
        if not candidate_ids:
            break

        for lead_id in candidate_ids:
            cursor = lead_id
            summary['processed'] += 1
            lead = db.session.get(Lead, lead_id)
            if lead is None:
                summary['skipped'] += 1
                continue
            if not lead_needs_building_ownership_analysis(lead, stale_days=stale_days):
                summary['skipped'] += 1
                continue

            try:
                if enqueue_async:
                    if dispatch_building_ownership_analysis(lead_id):
                        summary['enqueued'] += 1
                        analyzed_count += 1
                    else:
                        summary['errors'] += 1
                else:
                    service.analyze_lead(lead_id)
                    summary['analyzed'] += 1
                    analyzed_count += 1
            except Exception as exc:
                db.session.rollback()
                summary['errors'] += 1
                logger.warning(
                    'building ownership backfill failed for lead %s: %s',
                    lead_id,
                    exc,
                )

            if analyzed_count >= per_run_cap:
                summary['capped'] = True
                summary['last_id'] = cursor
                return summary

    summary['last_id'] = cursor
    return summary
