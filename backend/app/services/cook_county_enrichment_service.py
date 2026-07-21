"""Orchestrate automatic Cook County / Chicago open-data enrichment."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import event, func, or_

from app import db
from app.models.enrichment import DataSource, EnrichmentRecord
from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.services.data_source_connector import DataSourceConnector
from app.services.gis.routing import _resolve_market
from app.services.building_ownership_backfill import (
    maybe_schedule_building_ownership_after_commit,
    maybe_schedule_building_ownership_analysis,
)
from app.services.lead_refresh import refresh_lead_scoring
from app.services.open_letter_contact_mapper import is_owner_mailable_lead
from app.services.plugins.address_utils import is_chicago_address
from app.services.scoring_rubric import is_recently_sold

logger = logging.getLogger(__name__)

COOK_COUNTY_MARKET = "cook_county_il"
BACKFILL_BATCH_SIZE = 75
BACKFILL_SOCATA_CALL_CAP = 200
BACKFILL_STALE_DAYS = 30
SALE_DATE_BACKFILL_BATCH_SIZE = 200
SALE_DATE_BACKFILL_SOCRATA_CALL_CAP = 250
SALE_DATE_BACKFILL_CURSOR_KEY = "cook_county:sale_date_backfill:last_id"
COMMERCIAL_VALUATION_SOURCE = "cook_county_commercial_valuation"
ASSESSOR_SOURCE = "cook_county_assessor"

_PIN_PLUGINS = (
    "cook_county_assessor",
    "cook_county_permits",
    "cook_county_tax_sales",
    "cook_county_appeals",
    "cook_county_tax_exempt",
    "cook_county_scavenger_tax_sale",
    "cook_county_commercial_valuation",
)

_CHICAGO_PLUGINS = (
    "chicago_building_violations",
    "chicago_scofflaw",
    "chicago_vacant_buildings",
    "chicago_311_complaints",
)

AUTOMATED_ENRICHMENT_SOURCES = frozenset({
    *_PIN_PLUGINS,
    "cook_county_owner_lookup",
    *_CHICAGO_PLUGINS,
})


def _has_pin(lead: Lead) -> bool:
    pin = getattr(lead, "county_assessor_pin", None)
    return bool(pin and str(pin).strip())


def _owner_names_missing(lead: Lead) -> bool:
    first = (getattr(lead, "owner_first_name", None) or "").strip()
    last = (getattr(lead, "owner_last_name", None) or "").strip()
    return not first and not last


def plugins_for_lead(lead: Lead) -> list[str]:
    """Return ordered plugin names to run for *lead* (may be empty)."""
    if _resolve_market(lead) != COOK_COUNTY_MARKET:
        return []

    address = lead.property_street or ""
    city = getattr(lead, "property_city", None)
    has_pin = _has_pin(lead)
    chicago = is_chicago_address(city=city, address=address)

    if not has_pin and not chicago:
        return []

    plugins: list[str] = []
    if has_pin:
        plugins.extend(_PIN_PLUGINS)
        if _owner_names_missing(lead) or not is_owner_mailable_lead(lead):
            plugins.append("cook_county_owner_lookup")
    elif chicago:
        plugins.append("cook_county_assessor")

    if chicago:
        plugins.extend(_CHICAGO_PLUGINS)

    return plugins


def sale_date_plugins_for_lead(lead: Lead) -> list[str]:
    """Assessor-focused plugins for sale-date verification only."""
    full = plugins_for_lead(lead)
    if not full:
        # Still allow assessor after GIS PIN recovery for Cook County leads.
        if _resolve_market(lead) != COOK_COUNTY_MARKET:
            return []
        address = lead.property_street or ""
        city = getattr(lead, "property_city", None)
        if _has_pin(lead) or is_chicago_address(city=city, address=address):
            return [ASSESSOR_SOURCE]
        return []

    plugins: list[str] = []
    if ASSESSOR_SOURCE in full or _has_pin(lead) or is_chicago_address(
        city=getattr(lead, "property_city", None),
        address=lead.property_street or "",
    ):
        plugins.append(ASSESSOR_SOURCE)
    if COMMERCIAL_VALUATION_SOURCE in full:
        plugins.append(COMMERCIAL_VALUATION_SOURCE)
    return plugins


def is_cook_county_lead(lead: Lead) -> bool:
    return _resolve_market(lead) == COOK_COUNTY_MARKET


def ensure_automated_data_sources() -> list[DataSource]:
    """Seed/repair the enrichment catalog for all built-in automated plugins."""
    return DataSourceConnector().ensure_registered_data_sources()


def check_enrichment_catalog_health(*, heal: bool = True) -> dict:
    """Ensure required DataSource rows exist; return health summary.

    When ``heal`` is True, missing catalog rows are created from built-in plugins.
    """
    if heal:
        ensure_automated_data_sources()

    present = {
        name
        for (name,) in (
            DataSource.query
            .with_entities(DataSource.name)
            .filter(DataSource.name.in_(tuple(AUTOMATED_ENRICHMENT_SOURCES)))
            .all()
        )
    }
    missing = sorted(AUTOMATED_ENRICHMENT_SOURCES - present)
    return {
        'ok': len(missing) == 0,
        'required_count': len(AUTOMATED_ENRICHMENT_SOURCES),
        'present_count': len(present),
        'missing': missing,
    }


def _lead_has_due_open_task(lead_id: int, today: date | None = None) -> bool:
    """True when the lead has an open LeadTask due today or earlier."""
    if today is None:
        today = date.today()
    return (
        db.session.query(LeadTask.id)
        .filter(
            LeadTask.lead_id == lead_id,
            LeadTask.status == 'open',
            LeadTask.due_date.isnot(None),
            LeadTask.due_date <= today,
        )
        .first()
        is not None
    )


def _due_open_task_exists_clause(today: date):
    return (
        db.session.query(LeadTask.id)
        .filter(
            LeadTask.lead_id == Lead.id,
            LeadTask.status == 'open',
            LeadTask.due_date.isnot(None),
            LeadTask.due_date <= today,
        )
        .exists()
    )


def collect_enrichment_supporting_data_invariants() -> dict:
    """Read-only counts for catalog/enrichment gaps (observability only)."""
    catalog = check_enrichment_catalog_health(heal=False)
    since_7d = datetime.utcnow() - timedelta(days=7)
    today = date.today()
    due_exists = _due_open_task_exists_clause(today)

    enrichment_last_7d = (
        db.session.query(func.count(EnrichmentRecord.id))
        .filter(EnrichmentRecord.created_at >= since_7d)
        .scalar()
        or 0
    )
    chicago_no_pin_with_sale = (
        db.session.query(func.count(Lead.id))
        .filter(
            func.lower(Lead.property_city) == 'chicago',
            or_(Lead.county_assessor_pin.is_(None), Lead.county_assessor_pin == ''),
            or_(Lead.most_recent_sale.isnot(None), Lead.acquisition_date.isnot(None)),
        )
        .scalar()
        or 0
    )
    working_set_sale_no_enrichment = (
        db.session.query(func.count(Lead.id))
        .filter(
            due_exists,
            or_(Lead.most_recent_sale.isnot(None), Lead.acquisition_date.isnot(None)),
            ~db.session.query(EnrichmentRecord.id)
            .filter(EnrichmentRecord.lead_id == Lead.id)
            .exists(),
        )
        .scalar()
        or 0
    )

    return {
        'catalog_ok': catalog['ok'],
        'catalog_present_count': catalog['present_count'],
        'catalog_required_count': catalog['required_count'],
        'catalog_missing': catalog['missing'],
        'enrichment_records_last_7d': enrichment_last_7d,
        'chicago_no_pin_with_sale': chicago_no_pin_with_sale,
        'working_set_sale_no_enrichment': working_set_sale_no_enrichment,
    }


def _ensure_pin_from_gis(lead: Lead) -> bool:
    """Try to recover/persist Cook County PIN before PIN-based enrichments."""
    if _has_pin(lead) or _resolve_market(lead) != COOK_COUNTY_MARKET:
        return False
    try:
        from app.services.gis.routing import connector_for_lead
        connector = connector_for_lead(lead)
        if connector is None:
            return False
        parcel = connector.lookup_by_address(lead.property_street or "")
        pin = getattr(parcel, "county_assessor_pin", None) if parcel else None
        if not pin:
            return False
        lead.county_assessor_pin = str(pin).strip()
        db.session.add(lead)
        db.session.flush()
        logger.info(
            "Cook County enrichment recovered PIN for lead %s: %s",
            lead.id,
            lead.county_assessor_pin,
        )
        return True
    except Exception as exc:
        logger.warning(
            "Cook County enrichment PIN recovery failed for lead %s: %s",
            getattr(lead, "id", None),
            exc,
        )
        db.session.rollback()
        return False


def enrich_cook_county_lead(lead_id: int) -> dict:
    """Run all applicable Cook County plugins for one lead; rescore once."""
    return _enrich_cook_county_lead_with_plugins(lead_id, plugins_for_lead)


def enrich_cook_county_sale_date(lead_id: int) -> dict:
    """Run sale-date plugins only (assessor ± commercial valuation)."""
    return _enrich_cook_county_lead_with_plugins(lead_id, sale_date_plugins_for_lead)


def _enrich_cook_county_lead_with_plugins(lead_id: int, plugin_resolver) -> dict:
    """Run selected Cook County plugins for one lead; rescore once."""
    summary = {
        "lead_id": lead_id,
        "skipped": False,
        "skip_reason": None,
        "plugins_run": 0,
        "success": 0,
        "no_results": 0,
        "failed": 0,
        "sources": [],
    }

    lead = db.session.get(Lead, lead_id)
    if lead is None:
        summary["skipped"] = True
        summary["skip_reason"] = "lead_not_found"
        return summary

    _ensure_pin_from_gis(lead)
    plugin_names = plugin_resolver(lead)
    if not plugin_names:
        summary["skipped"] = True
        summary["skip_reason"] = "not_eligible"
        return summary

    connector = DataSourceConnector()

    for source_name in plugin_names:
        summary["plugins_run"] += 1
        try:
            record = connector.enrich_lead(
                lead_id,
                source_name,
                refresh_scoring=False,
            )
            summary["sources"].append({
                "source": source_name,
                "status": record.status,
            })
            if record.status == "success":
                summary["success"] += 1
            elif record.status == "no_results":
                summary["no_results"] += 1
            else:
                summary["failed"] += 1
        except Exception as exc:
            summary["failed"] += 1
            summary["sources"].append({
                "source": source_name,
                "status": "failed",
                "error": str(exc),
            })
            logger.warning(
                "Cook County enrichment: plugin %s failed for lead %s: %s",
                source_name,
                lead_id,
                exc,
            )

    if summary["plugins_run"] > 0:
        from app.services.motivation_signal_service import MotivationSignalService
        MotivationSignalService().sync_from_lead(lead, commit=False)
        refresh_lead_scoring(lead_id)

    logger.info(
        "Cook County enrichment complete for lead %s: %s",
        lead_id,
        summary,
    )
    maybe_schedule_building_ownership_analysis(lead)
    return summary


def enqueue_cook_county_enrichment(lead_id: int) -> bool:
    """Enqueue async Cook County enrichment (no sync fallback)."""
    return _enqueue_cook_county_task(
        'cook_county.enrich_lead',
        'cook_county_enrich_lead_task',
        lead_id,
    )


def enqueue_cook_county_sale_date_verification(lead_id: int) -> bool:
    """Enqueue the narrow sale-date verification task for one lead."""
    return _enqueue_cook_county_task(
        'cook_county.verify_sale_date',
        'cook_county_verify_sale_date_task',
        lead_id,
    )


def _enqueue_cook_county_task(task_name: str, attr: str, lead_id: int) -> bool:
    """Shared Celery dispatch for Cook County lead tasks."""
    try:
        import celery_worker

        task_func = getattr(celery_worker, attr)
        task_func.apply_async(args=[lead_id], ignore_result=True)
        logger.info("Dispatched %s for lead %s", task_name, lead_id)
        return True
    except Exception as exc:
        logger.warning(
            "Could not enqueue %s for lead %s: %s",
            task_name,
            lead_id,
            exc,
        )
        return False


def dispatch_cook_county_enrichment(lead_id: int) -> bool:
    """Enqueue async Cook County enrichment; fall back to sync if broker unavailable."""
    if enqueue_cook_county_enrichment(lead_id):
        return True
    try:
        enrich_cook_county_lead(lead_id)
        return True
    except Exception as sync_exc:
        logger.error(
            "Sync Cook County enrichment failed for lead %s: %s",
            lead_id,
            sync_exc,
        )
        return False


def schedule_cook_county_enrichment_after_commit(lead_id: int) -> None:
    """Dispatch enrichment only after the current DB transaction commits."""
    session = db.session()
    pending: set[int] = session.info.setdefault("cook_county_enrichment_pending", set())
    pending.add(lead_id)

    if session.info.get("cook_county_enrichment_listener"):
        return
    session.info["cook_county_enrichment_listener"] = True

    @event.listens_for(session, "after_commit", once=True)
    def _dispatch_after_commit(sess) -> None:
        lead_ids = sess.info.pop("cook_county_enrichment_pending", set())
        sess.info.pop("cook_county_enrichment_listener", None)
        for lid in lead_ids:
            enqueue_cook_county_enrichment(lid)

    @event.listens_for(session, "after_rollback", once=True)
    def _clear_after_rollback(sess) -> None:
        sess.info.pop("cook_county_enrichment_pending", None)
        sess.info.pop("cook_county_enrichment_listener", None)


def maybe_dispatch_after_gis_match(lead: Lead, connector) -> None:
    """Schedule county enrichment after a successful Cook County GIS match."""
    market = getattr(connector, "market", None)
    if market != COOK_COUNTY_MARKET:
        return
    schedule_cook_county_enrichment_after_commit(lead.id)
    # Leads ineligible for enrichment (no PIN, not Chicago) still need building ownership
    # after GIS match; enriched leads are scheduled at the end of enrich_cook_county_lead.
    if not plugins_for_lead(lead):
        maybe_schedule_building_ownership_after_commit(lead)


def _commercial_valuation_source_id() -> Optional[int]:
    ensure_automated_data_sources()
    source = DataSource.query.filter_by(name=COMMERCIAL_VALUATION_SOURCE).first()
    return source.id if source else None


def _assessor_source_id() -> Optional[int]:
    ensure_automated_data_sources()
    source = DataSource.query.filter_by(name=ASSESSOR_SOURCE).first()
    return source.id if source else None


def lead_recently_fully_enriched(lead_id: int, source_id: int, since: datetime) -> bool:
    return (
        db.session.query(EnrichmentRecord.id)
        .filter(
            EnrichmentRecord.lead_id == lead_id,
            EnrichmentRecord.data_source_id == source_id,
            EnrichmentRecord.status == "success",
            EnrichmentRecord.created_at >= since,
        )
        .first()
        is not None
    )


def lead_recently_sale_checked(lead_id: int, since: datetime) -> bool:
    """Return True when assessor sale verification was attempted recently."""
    source_id = _assessor_source_id()
    if source_id is None:
        return False
    return (
        db.session.query(EnrichmentRecord.id)
        .filter(
            EnrichmentRecord.lead_id == lead_id,
            EnrichmentRecord.data_source_id == source_id,
            EnrichmentRecord.status.in_(("success", "no_results", "failed")),
            EnrichmentRecord.created_at >= since,
        )
        .first()
        is not None
    )


def backfill_cook_county_enrichment(
    *,
    batch_size: int = BACKFILL_BATCH_SIZE,
    socrata_call_cap: int = BACKFILL_SOCATA_CALL_CAP,
    last_id: int = 0,
) -> dict:
    """Enrich Cook County leads that lack recent Cook County verification.

    Prioritizes leads with open due LeadTasks. Skips proactive enrichment for
    recently-sold leads that have no due open task (explicit Verify still runs).
    """
    since = datetime.utcnow() - timedelta(days=BACKFILL_STALE_DAYS)
    today = date.today()
    commercial_source_id = _commercial_valuation_source_id()

    summary = {
        "status": "completed",
        "processed": 0,
        "enriched": 0,
        "skipped": 0,
        "errors": 0,
        "last_id": last_id,
        "socrata_calls": 0,
        "capped": False,
    }

    if commercial_source_id is None:
        summary["status"] = "skipped"
        summary["skip_reason"] = "commercial_valuation_source_missing"
        return summary

    cursor = last_id
    enriched_count = 0

    while enriched_count < batch_size and summary["socrata_calls"] < socrata_call_cap:
        candidates = (
            db.session.query(Lead)
            .filter(
                Lead.id > cursor,
                Lead.property_state.in_(("IL", "Illinois", "il")),
                or_(
                    (
                        Lead.county_assessor_pin.isnot(None)
                        & (Lead.county_assessor_pin != "")
                    ),
                    func.lower(Lead.property_city) == "chicago",
                ),
            )
            .order_by(Lead.id)
            .limit(batch_size * 2)
            .all()
        )
        if not candidates:
            break

        # Keep ID order so last_id remains a valid exclusive pagination cursor.
        # Due-task priority is applied via skip rules below (recently sold without
        # a due task is skipped; due-task leads still run when reached).
        for lead in candidates:
            cursor = lead.id
            summary["processed"] += 1

            if _resolve_market(lead) != COOK_COUNTY_MARKET:
                summary["skipped"] += 1
                continue

            has_due = _lead_has_due_open_task(lead.id, today)
            if is_recently_sold(lead) and not has_due:
                summary["skipped"] += 1
                continue

            if lead_recently_fully_enriched(lead.id, commercial_source_id, since):
                summary["skipped"] += 1
                continue
            if not _has_pin(lead) and lead_recently_sale_checked(lead.id, since):
                summary["skipped"] += 1
                continue

            estimated_calls = len(plugins_for_lead(lead))
            if estimated_calls == 0:
                summary["skipped"] += 1
                continue
            if summary["socrata_calls"] + estimated_calls > socrata_call_cap:
                summary["capped"] = True
                summary["last_id"] = cursor
                return summary

            try:
                result = enrich_cook_county_lead(lead.id)
                summary["socrata_calls"] += result.get("plugins_run", estimated_calls)
                if result.get("skipped"):
                    summary["skipped"] += 1
                else:
                    enriched_count += 1
                    summary["enriched"] += 1
            except Exception as exc:
                summary["errors"] += 1
                logger.warning(
                    "Cook County backfill failed for lead %s: %s",
                    lead.id,
                    exc,
                )

            if enriched_count >= batch_size or summary["socrata_calls"] >= socrata_call_cap:
                summary["capped"] = True
                summary["last_id"] = cursor
                return summary

    summary["last_id"] = cursor
    return summary


def _sale_date_backfill_cursor() -> int:
    from app.services.deploy_sync_policy import get_redis_value

    raw = get_redis_value(SALE_DATE_BACKFILL_CURSOR_KEY)
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _set_sale_date_backfill_cursor(last_id: int) -> None:
    from app.services.deploy_sync_policy import set_redis_value

    set_redis_value(SALE_DATE_BACKFILL_CURSOR_KEY, str(max(0, int(last_id))))


def backfill_sale_date_verification(
    *,
    batch_size: int = SALE_DATE_BACKFILL_BATCH_SIZE,
    socrata_call_cap: int = SALE_DATE_BACKFILL_SOCRATA_CALL_CAP,
    last_id: int | None = None,
    persist_cursor: bool = True,
) -> dict:
    """Hourly assessor-focused sale-date verification for Cook County leads.

    Includes empty-sale leads never checked. Does not skip recent-sale holds.
    Persists exclusive ``last_id`` in Redis and wraps to 0 when a pass ends.
    """
    since = datetime.utcnow() - timedelta(days=BACKFILL_STALE_DAYS)
    cursor = _sale_date_backfill_cursor() if last_id is None else last_id

    summary = {
        "status": "completed",
        "processed": 0,
        "enriched": 0,
        "skipped": 0,
        "errors": 0,
        "last_id": cursor,
        "socrata_calls": 0,
        "capped": False,
        "wrapped": False,
    }

    if _assessor_source_id() is None:
        summary["status"] = "skipped"
        summary["skip_reason"] = "assessor_source_missing"
        return summary

    enriched_count = 0
    saw_candidates = False

    while enriched_count < batch_size and summary["socrata_calls"] < socrata_call_cap:
        candidates = (
            db.session.query(Lead)
            .filter(
                Lead.id > cursor,
                Lead.property_state.in_(("IL", "Illinois", "il")),
                or_(
                    (
                        Lead.county_assessor_pin.isnot(None)
                        & (Lead.county_assessor_pin != "")
                    ),
                    func.lower(Lead.property_city) == "chicago",
                ),
            )
            .order_by(Lead.id)
            .limit(batch_size * 2)
            .all()
        )
        if not candidates:
            if cursor > 0 and not saw_candidates:
                # Wrap and continue from the start of the book once per run.
                cursor = 0
                summary["wrapped"] = True
                summary["last_id"] = 0
                continue
            break

        saw_candidates = True
        for lead in candidates:
            previous_cursor = cursor
            cursor = lead.id
            summary["processed"] += 1

            if _resolve_market(lead) != COOK_COUNTY_MARKET:
                summary["skipped"] += 1
                continue

            if lead_recently_sale_checked(lead.id, since):
                summary["skipped"] += 1
                continue

            plugin_names = sale_date_plugins_for_lead(lead)
            if not plugin_names and not _has_pin(lead):
                # Attempt GIS PIN recovery path inside enrich; still count as a try.
                plugin_names = [ASSESSOR_SOURCE]
            estimated_calls = max(1, len(plugin_names) if plugin_names else 1)
            if summary["socrata_calls"] + estimated_calls > socrata_call_cap:
                summary["capped"] = True
                summary["last_id"] = previous_cursor
                if persist_cursor:
                    _set_sale_date_backfill_cursor(previous_cursor)
                return summary

            try:
                result = enrich_cook_county_sale_date(lead.id)
                summary["socrata_calls"] += result.get("plugins_run", estimated_calls)
                if result.get("skipped"):
                    summary["skipped"] += 1
                else:
                    enriched_count += 1
                    summary["enriched"] += 1
            except Exception as exc:
                summary["errors"] += 1
                logger.warning(
                    "Cook County sale-date backfill failed for lead %s: %s",
                    lead.id,
                    exc,
                )

            if enriched_count >= batch_size or summary["socrata_calls"] >= socrata_call_cap:
                summary["capped"] = True
                summary["last_id"] = cursor
                if persist_cursor:
                    _set_sale_date_backfill_cursor(cursor)
                return summary

    # Pass completed without capping — wrap cursor for the next stale window.
    if not summary["capped"]:
        cursor = 0
        summary["wrapped"] = True
    summary["last_id"] = cursor
    if persist_cursor:
        _set_sale_date_backfill_cursor(cursor)
    return summary
