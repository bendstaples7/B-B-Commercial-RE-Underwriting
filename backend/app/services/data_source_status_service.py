"""DataSourceStatusService — aggregates all data source statuses into a single payload."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func

from app import db
from app.models.enrichment import DataSource, EnrichmentRecord
from app.models.import_job import ImportJob
from app.models.lead import Lead
from app.models.hubspot_config import HubSpotConfig
from app.services.cache_status_service import CacheStatusService


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

        Uses a single GROUP BY query across leads and enrichment_records to
        avoid N+1 queries.  Returns zeroed counts (not an error) when the user
        has no leads.
        """
        # All active enrichment data sources
        sources = db.session.query(DataSource).order_by(DataSource.id).all()
        if not sources:
            return []

        # Total leads owned by this user
        total_leads = (
            db.session.query(func.count(Lead.id))
            .filter(Lead.owner_user_id == user_id)
            .scalar()
        ) or 0

        # Single GROUP BY query: data_source_id × status → count
        # Joins enrichment_records through leads filtered by owner_user_id.
        rows = (
            db.session.query(
                EnrichmentRecord.data_source_id,
                EnrichmentRecord.status,
                func.count(EnrichmentRecord.id).label("cnt"),
            )
            .join(Lead, Lead.id == EnrichmentRecord.lead_id)
            .filter(Lead.owner_user_id == user_id)
            .group_by(EnrichmentRecord.data_source_id, EnrichmentRecord.status)
            .all()
        )

        # Build a lookup: { data_source_id: { status: count } }
        counts: dict[int, dict[str, int]] = {}
        for source_id, status, cnt in rows:
            counts.setdefault(source_id, {})[status] = cnt

        results = []
        for source in sources:
            source_counts = counts.get(source.id, {})
            success_count = source_counts.get("success", 0)
            failed_count = source_counts.get("failed", 0)
            pending_count = source_counts.get("pending", 0)
            not_run_count = max(
                0, total_leads - (success_count + failed_count + pending_count)
            )

            # Most recent enrichment record for this source / user
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

            results.append({
                "name": source.name,
                "source_type": "enrichment",
                "refresh_type": "on_demand",
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
