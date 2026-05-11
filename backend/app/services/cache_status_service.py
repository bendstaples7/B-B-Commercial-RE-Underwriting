"""CacheStatusService — reads cache state for the three Socrata datasets."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func

from app import db
from app.models.parcel_universe_cache import ParcelUniverseCache
from app.models.parcel_sales_cache import ParcelSalesCache
from app.models.improvement_characteristics_cache import ImprovementCharacteristicsCache
from app.models.sync_log import SyncLog

logger = logging.getLogger(__name__)

SOCRATA_STALE_DAYS = int(os.environ.get('SOCRATA_STALE_DAYS', '30'))


@dataclass
class DatasetStatus:
    """Status snapshot for a single cached dataset."""
    dataset_name: str
    row_count: int
    last_synced_at: Optional[datetime]   # UTC datetime or None
    status: str                           # 'empty' | 'fresh' | 'stale' | 'never_synced'
    last_error: Optional[str]


class CacheStatusService:
    """Reads cache state without modifying it.

    Propagates SQLAlchemyError on DB unavailability so the controller's
    @handle_errors decorator can return HTTP 503.
    """

    _DATASET_MODELS = {
        'parcel_universe': ParcelUniverseCache,
        'parcel_sales': ParcelSalesCache,
        'improvement_characteristics': ImprovementCharacteristicsCache,
    }

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _row_count(self, table_model) -> int:
        """Return the number of rows in the given table model."""
        return db.session.query(func.count()).select_from(table_model).scalar() or 0

    def _last_successful_sync(self, dataset_name: str) -> Optional[SyncLog]:
        """Return the most recent successful SyncLog row for the dataset, or None."""
        return (
            db.session.query(SyncLog)
            .filter(
                SyncLog.dataset_name == dataset_name,
                SyncLog.status == 'success',
            )
            .order_by(SyncLog.completed_at.desc())
            .first()
        )

    def _last_failed_sync(self, dataset_name: str) -> Optional[SyncLog]:
        """Return the most recent failed SyncLog row for the dataset, or None."""
        return (
            db.session.query(SyncLog)
            .filter(
                SyncLog.dataset_name == dataset_name,
                SyncLog.status == 'failed',
            )
            .order_by(SyncLog.completed_at.desc())
            .first()
        )

    def _classify_status(
        self,
        row_count: int,
        last_success: Optional[SyncLog],
        last_failure: Optional[SyncLog],
    ) -> str:
        """Classify the dataset status based on row count and sync history.

        Rules (evaluated in order):
          1. row_count == 0 AND no sync ever attempted → 'never_synced'
          2. row_count == 0                            → 'empty'
          3. days_since_last_success <= SOCRATA_STALE_DAYS → 'fresh'
          4. days_since_last_success >  SOCRATA_STALE_DAYS → 'stale'
        """
        if row_count == 0 and last_success is None and last_failure is None:
            return 'never_synced'

        if row_count == 0:
            return 'empty'

        # row_count > 0 — last_success must exist (rows can only come from a sync)
        days_since = (
            datetime.now(timezone.utc)
            - last_success.completed_at.replace(tzinfo=timezone.utc)
        ).days

        if days_since <= SOCRATA_STALE_DAYS:
            return 'fresh'

        return 'stale'

    # ------------------------------------------------------------------ #
    # Public interface                                                     #
    # ------------------------------------------------------------------ #

    def get_dataset_status(self, dataset_name: str) -> DatasetStatus:
        """Return a DatasetStatus snapshot for the named dataset.

        Raises KeyError if dataset_name is not one of the three known datasets.
        Propagates SQLAlchemyError on DB unavailability.
        """
        table_model = self._DATASET_MODELS[dataset_name]

        row_count = self._row_count(table_model)
        last_success = self._last_successful_sync(dataset_name)
        last_failure = self._last_failed_sync(dataset_name)

        status = self._classify_status(row_count, last_success, last_failure)
        last_synced_at = last_success.completed_at if last_success else None
        last_error = last_failure.error_message if last_failure else None

        return DatasetStatus(
            dataset_name=dataset_name,
            row_count=row_count,
            last_synced_at=last_synced_at,
            status=status,
            last_error=last_error,
        )

    def get_status(self) -> list:
        """Return DatasetStatus for all three datasets.

        Propagates SQLAlchemyError on DB unavailability (controller handles HTTP 503).
        """
        return [
            self.get_dataset_status(ds)
            for ds in ['parcel_universe', 'parcel_sales', 'improvement_characteristics']
        ]
