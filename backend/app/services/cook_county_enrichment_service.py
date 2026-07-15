"""Orchestrate automatic Cook County / Chicago open-data enrichment."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import event

from app import db
from app.models.enrichment import DataSource, EnrichmentRecord
from app.models.lead import Lead
from app.services.data_source_connector import DataSourceConnector
from app.services.gis.routing import _resolve_market
from app.services.building_ownership_backfill import (
    maybe_schedule_building_ownership_after_commit,
    maybe_schedule_building_ownership_analysis,
)
from app.services.lead_refresh import refresh_lead_scoring
from app.services.open_letter_contact_mapper import is_owner_mailable_lead
from app.services.plugins.address_utils import is_chicago_address

logger = logging.getLogger(__name__)

COOK_COUNTY_MARKET = "cook_county_il"
BACKFILL_BATCH_SIZE = 75
BACKFILL_SOCATA_CALL_CAP = 200
BACKFILL_STALE_DAYS = 30
COMMERCIAL_VALUATION_SOURCE = "cook_county_commercial_valuation"

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


def is_cook_county_lead(lead: Lead) -> bool:
    return _resolve_market(lead) == COOK_COUNTY_MARKET


def enrich_cook_county_lead(lead_id: int) -> dict:
    """Run all applicable Cook County plugins for one lead; rescore once."""
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

    plugin_names = plugins_for_lead(lead)
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
    try:
        from celery_worker import cook_county_enrich_lead_task
        cook_county_enrich_lead_task.apply_async(args=[lead_id], ignore_result=True)
        logger.info("Dispatched cook_county.enrich_lead for lead %s", lead_id)
        return True
    except Exception as exc:
        logger.warning(
            "Could not enqueue cook_county.enrich_lead for lead %s: %s",
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
    source = DataSource.query.filter_by(name=COMMERCIAL_VALUATION_SOURCE).first()
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


def backfill_cook_county_enrichment(
    *,
    batch_size: int = BACKFILL_BATCH_SIZE,
    socrata_call_cap: int = BACKFILL_SOCATA_CALL_CAP,
    last_id: int = 0,
) -> dict:
    """Enrich Cook County leads that lack a recent commercial-valuation run."""
    since = datetime.utcnow() - timedelta(days=BACKFILL_STALE_DAYS)
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
                Lead.county_assessor_pin.isnot(None),
                Lead.county_assessor_pin != "",
                Lead.property_state.in_(("IL", "Illinois", "il")),
            )
            .order_by(Lead.id)
            .limit(batch_size * 2)
            .all()
        )
        if not candidates:
            break

        for lead in candidates:
            cursor = lead.id
            summary["processed"] += 1

            if _resolve_market(lead) != COOK_COUNTY_MARKET:
                summary["skipped"] += 1
                continue

            if lead_recently_fully_enriched(lead.id, commercial_source_id, since):
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
