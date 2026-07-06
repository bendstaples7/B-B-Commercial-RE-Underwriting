"""DataSourceStatusService — aggregates all data source statuses into a single payload."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import case, func

from app import db
from app.models.enrichment import DataSource, EnrichmentRecord
from app.models.import_job import ImportJob
from app.models.lead import Lead
from app.models.hubspot_config import HubSpotConfig
from app.services.cache_status_service import CacheStatusService
from app.services.cook_county_enrichment_service import AUTOMATED_ENRICHMENT_SOURCES


def compute_days_since(dt: datetime) -> int:
    """Return the number of whole days between ``dt`` and now (UTC), always >= 0.

    Args:
        dt: A past (or present) datetime.  Naive datetimes are treated as UTC.

    Returns:
        ``max(0, floor((utcnow - dt).days))``
    """
    now = datetime.utcnow()
    # Strip timezone info for naive comparison; CacheStatusService stores naive UTC.
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    delta = now - dt
    return max(0, delta.days)


class DataSourceStatusService:
    """Assembles a unified data-source status payload for the requesting user.

    Does **not** catch ``SQLAlchemyError`` — callers (controllers) are
    responsible for mapping that to HTTP 503.
    """

    # ------------------------------------------------------------------ #
    # Public interface                                                     #
    # ------------------------------------------------------------------ #

    def get_all_statuses(self, user_id: str) -> dict:
        """Return the full data-source status payload scoped to *user_id*.

        Structure:
        {
            "socrata_datasets": [...],
            "enrichment_sources": [...],
            "import_source": {...},
            "hubspot_source": {...},
        }

        Raises:
            SQLAlchemyError: Propagated from any DB query on DB unavailability.
        """
        return {
            "socrata_datasets": self._get_socrata_statuses(),
            "enrichment_sources": self._get_enrichment_statuses(user_id),
            "import_source": self._get_import_source(user_id),
            "hubspot_source": self._get_hubspot_source(),
            "gis_connectors": self._get_gis_connector_statuses(user_id),
        }

    # ------------------------------------------------------------------ #
    # Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_socrata_statuses(self) -> list:
        """Delegate to CacheStatusService and format for the API response."""
        cache_svc = CacheStatusService()
        dataset_statuses = cache_svc.get_status()  # list[DatasetStatus]

        results = []
        for ds in dataset_statuses:
            last_refreshed_at: Optional[str] = None
            days_since_sync: Optional[int] = None

            if ds.last_synced_at is not None:
                last_refreshed_at = ds.last_synced_at.isoformat()
                days_since_sync = compute_days_since(ds.last_synced_at)

            results.append({
                "name": ds.dataset_name,
                "source_type": "socrata",
                "refresh_type": "periodic",
                "is_active": True,
                "status": ds.status,
                "last_refreshed_at": last_refreshed_at,
                "row_count": ds.row_count,
                "days_since_sync": days_since_sync,
                "last_error": ds.last_error,
            })

        return results

    def _get_enrichment_statuses(self, user_id: str) -> list:
        """Return per-enrichment-source coverage counts scoped to user_id.

        Counts are per *lead* (distinct lead_id), not per enrichment record.
        ``no_results`` runs reduce ``not_run_count`` but do not increase
        ``success_count``.
        """
        sources = db.session.query(DataSource).order_by(DataSource.id).all()
        if not sources:
            return []

        total_leads = (
            db.session.query(func.count(Lead.id))
            .filter(Lead.owner_user_id == user_id)
            .scalar()
        ) or 0

        # Per lead + source: did this lead get success and/or failed?
        lead_rows = (
            db.session.query(
                EnrichmentRecord.data_source_id,
                EnrichmentRecord.lead_id,
                func.max(
                    case((EnrichmentRecord.status == "success", 1), else_=0)
                ).label("has_success"),
                func.max(
                    case((EnrichmentRecord.status == "failed", 1), else_=0)
                ).label("has_failed"),
                func.max(
                    case((EnrichmentRecord.status == "pending", 1), else_=0)
                ).label("has_pending"),
            )
            .join(Lead, Lead.id == EnrichmentRecord.lead_id)
            .filter(Lead.owner_user_id == user_id)
            .group_by(EnrichmentRecord.data_source_id, EnrichmentRecord.lead_id)
            .all()
        )

        per_source: dict[int, dict[str, int]] = {}
        for source_id, _lead_id, has_success, has_failed, has_pending in lead_rows:
            bucket = per_source.setdefault(source_id, {
                "success": 0,
                "failed": 0,
                "pending": 0,
                "attempted": 0,
            })
            bucket["attempted"] += 1
            if has_success:
                bucket["success"] += 1
            elif has_failed:
                bucket["failed"] += 1
            elif has_pending:
                bucket["pending"] += 1

        results = []
        for source in sources:
            bucket = per_source.get(source.id, {
                "success": 0,
                "failed": 0,
                "pending": 0,
                "attempted": 0,
            })
            success_count = bucket["success"]
            failed_count = bucket["failed"]
            pending_count = bucket["pending"]
            not_run_count = max(0, total_leads - bucket["attempted"])

            latest_record = (
                db.session.query(EnrichmentRecord.created_at)
                .join(Lead, Lead.id == EnrichmentRecord.lead_id)
                .filter(
                    Lead.owner_user_id == user_id,
                    EnrichmentRecord.data_source_id == source.id,
                )
                .order_by(EnrichmentRecord.created_at.desc())
                .limit(1)
                .scalar()
            )
            last_refreshed_at: Optional[str] = (
                latest_record.isoformat() + "Z" if latest_record else None
            )

            refresh_type = (
                "automatic"
                if source.name in AUTOMATED_ENRICHMENT_SOURCES
                else "on_demand"
            )

            results.append({
                "name": source.name,
                "source_type": "enrichment",
                "refresh_type": refresh_type,
                "is_active": source.is_active,
                "last_refreshed_at": last_refreshed_at,
                "success_count": success_count,
                "failed_count": failed_count,
                "pending_count": pending_count,
                "not_run_count": not_run_count,
                "total_leads_count": total_leads,
            })

        return results

    def _get_import_source(self, user_id: str) -> dict:
        """Return most-recent completed ImportJob info for user_id.

        Returns null fields when no completed job exists for this user.
        """
        # Scoped to this user only — no cross-user fallback to prevent data leakage
        job: Optional[ImportJob] = (
            db.session.query(ImportJob)
            .filter(
                ImportJob.user_id == user_id,
                ImportJob.status == "completed",
            )
            .order_by(ImportJob.completed_at.desc())
            .limit(1)
            .first()
        )

        last_refreshed_at: Optional[str] = None
        rows_imported: Optional[int] = None
        import_status: Optional[str] = None

        if job is not None:
            last_refreshed_at = (
                job.completed_at.isoformat() + "Z" if job.completed_at else None
            )
            rows_imported = job.rows_imported
            import_status = job.status

        return {
            "name": "Google Sheets",
            "source_type": "import",
            "refresh_type": "static",
            "is_active": True,
            "last_refreshed_at": last_refreshed_at,
            "rows_imported": rows_imported,
            "import_status": import_status,
        }

    def _get_hubspot_source(self) -> dict:
        """Return HubSpot connection status.

        ``connected: false`` when no HubSpotConfig row exists.
        """
        connected: bool = (
            db.session.query(HubSpotConfig)
            .limit(1)
            .first()
        ) is not None

        return {
            "name": "HubSpot",
            "source_type": "hubspot",
            "refresh_type": "on_demand",
            "is_active": True,
            "connected": connected,
        }

    def _get_gis_connector_statuses(self, user_id: str) -> list:
        """Return status for each registered GIS connector, scoped to *user_id*.

        For each connector, reports:
        - How many of *this user's* leads are matched (has_property_match=True)
          by that connector (inferred from county/city routing)
        - How many of this user's leads in that county/city group are still
          unmatched
        - Whether the connector API is reachable (sampled via a single test query)

        Counts are filtered by ``owner_user_id`` so one user's match totals can
        never include another user's leads.
        """
        from app.services.gis.routing import _ensure_connectors_loaded, _resolve_market
        from app.services.gis.base import GISConnectorRegistry

        _ensure_connectors_loaded()

        # Connector metadata
        connector_info = {
            'dupage_il':      {'name': 'DuPage County GIS',      'counties': ['DuPage'],      'url': 'gis.dupageco.org'},
            'cook_county_il': {'name': 'Cook County Assessor',    'counties': ['Cook'],        'url': 'datacatalog.cookcountyil.gov'},
            'kane_county_il': {'name': 'Kane County GIS',         'counties': ['Kane'],        'url': 'gistech.countyofkane.org'},
            'lake_county_il': {'name': 'Lake County Open Data',   'counties': ['Lake'],        'url': 'services3.arcgis.com'},
        }

        # Count matched / unmatched per connector by routing through _resolve_market
        # Use a simplified city-to-market mapping for DB query efficiency
        from sqlalchemy import case, func
        from app.models.lead import Property as Lead

        rows = (
            db.session.query(
                Lead.property_city,
                Lead.property_state,
                func.count(Lead.id).label('total'),
                func.sum(case((Lead.has_property_match == True, 1), else_=0)).label('matched'),
            )
            .filter(
                Lead.owner_user_id == user_id,   # scope to the requesting user — no cross-user leakage
                Lead.property_street != None,    # noqa: E711
                Lead.property_street != '',
            )
            .group_by(Lead.property_city, Lead.property_state)
            .all()
        )

        # Aggregate by market key
        market_counts: dict[str, dict] = {}
        for market_key in connector_info:
            market_counts[market_key] = {'total': 0, 'matched': 0}

        class _FakeLead:
            def __init__(self, city, state):
                self.property_city = city
                self.property_state = state

        for row in rows:
            lead = _FakeLead(row.property_city, row.property_state)
            market = _resolve_market(lead)
            if market and market in market_counts:
                market_counts[market]['total'] += (row.total or 0)
                market_counts[market]['matched'] += int(row.matched or 0)

        results = []
        for market_key, info in connector_info.items():
            connector = GISConnectorRegistry.get(market_key)
            counts = market_counts.get(market_key, {'total': 0, 'matched': 0})
            matched = counts['matched']
            total = counts['total']
            unmatched = total - matched

            results.append({
                'name': info['name'],
                'market': market_key,
                'counties': info['counties'],
                'source_type': 'gis',
                'refresh_type': 'automatic',
                'is_active': connector is not None,
                'matched_count': matched,
                'unmatched_count': unmatched,
                'total_count': total,
                'api_url': info['url'],
            })

        return results
