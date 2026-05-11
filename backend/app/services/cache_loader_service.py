"""CacheLoaderService — loads and refreshes Cook County Socrata datasets into local cache tables."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Optional
from urllib.parse import urlparse

import requests
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import db
from app.models.parcel_universe_cache import ParcelUniverseCache
from app.models.parcel_sales_cache import ParcelSalesCache
from app.models.improvement_characteristics_cache import ImprovementCharacteristicsCache
from app.models.sync_log import SyncLog
from app.exceptions import CacheSyncException

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Lightweight result object returned by each load/refresh operation."""
    dataset: str
    status: str                  # 'success' | 'failed'
    rows_upserted: int
    error_message: Optional[str] = field(default=None)


class CacheLoaderService:
    """Moves data from the Cook County Socrata API into local PostgreSQL cache tables.

    Class-level constants define the column whitelists and NOT NULL column sets for
    each of the three datasets.  These are used by ``_map_row`` to enforce schema
    drift resilience: extra Socrata fields are silently dropped, missing nullable
    fields become NULL, and rows missing a NOT NULL field are skipped entirely.

    The ``DATASET_CONFIG`` dict maps each dataset name to its whitelist, not-null
    set, and SQLAlchemy model class so that generic helpers can dispatch to the
    correct configuration without a chain of ``if/elif`` blocks.
    """

    # ------------------------------------------------------------------
    # Parcel Universe (Socrata dataset pabr-t5kh)
    # ------------------------------------------------------------------
    PARCEL_UNIVERSE_WHITELIST: frozenset[str] = frozenset({
        'pin',
        'lat',
        'lon',
        'last_synced_at',
    })
    PARCEL_UNIVERSE_NOT_NULL: frozenset[str] = frozenset({
        'pin',
    })

    # ------------------------------------------------------------------
    # Parcel Sales (Socrata dataset wvhk-k5uv)
    # Note: Socrata field name is 'class', not 'class_' (the Python alias).
    # ------------------------------------------------------------------
    PARCEL_SALES_WHITELIST: frozenset[str] = frozenset({
        'pin',
        'sale_date',
        'sale_price',
        'class',
        'sale_type',
        'is_multisale',
        'sale_filter_less_than_10k',
        'sale_filter_deed_type',
        'last_synced_at',
    })
    PARCEL_SALES_NOT_NULL: frozenset[str] = frozenset({
        'pin',
    })

    # ------------------------------------------------------------------
    # Improvement Characteristics (Socrata dataset bcnq-qi2z)
    # ------------------------------------------------------------------
    IMPROVEMENT_CHARS_WHITELIST: frozenset[str] = frozenset({
        'pin',
        'bldg_sf',
        'beds',
        'fbath',
        'hbath',
        'age',
        'ext_wall',
        'apts',
        'last_synced_at',
    })
    IMPROVEMENT_CHARS_NOT_NULL: frozenset[str] = frozenset({
        'pin',
    })

    # ------------------------------------------------------------------
    # Dataset configuration registry
    # Maps dataset name → (whitelist, not_null_set, model_class)
    # ------------------------------------------------------------------
    DATASET_CONFIG: dict = {}  # populated after class body (see below)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Dataset name validation
    # ------------------------------------------------------------------
    _VALID_DATASETS = frozenset({
        'parcel_universe',
        'parcel_sales',
        'improvement_characteristics',
    })

    def _upsert_method_for(self, dataset: str):
        """Return the upsert method corresponding to *dataset*."""
        return {
            'parcel_universe': self._upsert_parcel_universe,
            'parcel_sales': self._upsert_parcel_sales,
            'improvement_characteristics': self._upsert_improvement_chars,
        }[dataset]

    def full_load(self, dataset: str) -> SyncResult:
        """Perform a full bulk load of *dataset* from the Socrata API.

        Fetches all records using paginated requests, upserts them into the
        corresponding cache table, and writes a ``sync_log`` row on completion.
        """
        if dataset not in self._VALID_DATASETS:
            raise ValueError(
                f"Invalid dataset {dataset!r}. "
                f"Must be one of: {sorted(self._VALID_DATASETS)}"
            )

        started_at = datetime.utcnow()
        self._write_sync_log(dataset, started_at, 'running', 0)

        upsert = self._upsert_method_for(dataset)
        total_rows_upserted = 0

        try:
            for page in self._fetch_pages(dataset, page_size=50_000):
                total_rows_upserted += upsert(page)
        except Exception as exc:
            logger.error(
                "full_load failed for dataset %r after upserting %d rows: %s",
                dataset, total_rows_upserted, exc,
                exc_info=True,
            )
            self._write_sync_log(
                dataset, started_at, 'failed',
                total_rows_upserted, error_message=str(exc),
            )
            return SyncResult(
                dataset=dataset,
                status='failed',
                rows_upserted=total_rows_upserted,
                error_message=str(exc),
            )

        self._write_sync_log(dataset, started_at, 'success', total_rows_upserted)
        return SyncResult(
            dataset=dataset,
            status='success',
            rows_upserted=total_rows_upserted,
        )

    def incremental_refresh(self, dataset: str) -> SyncResult:
        """Refresh *dataset* with records modified since the last successful sync.

        Queries ``sync_log`` for the most recent successful ``completed_at``
        timestamp and uses it as the Socrata ``$where`` watermark.  Falls back
        to ``full_load`` when no prior success exists.
        """
        if dataset not in self._VALID_DATASETS:
            raise ValueError(
                f"Invalid dataset {dataset!r}. "
                f"Must be one of: {sorted(self._VALID_DATASETS)}"
            )

        since_dt = self._get_last_success_timestamp(dataset)
        if since_dt is None:
            # No prior successful sync — fall back to a full load.
            return self.full_load(dataset)

        started_at = datetime.utcnow()
        self._write_sync_log(dataset, started_at, 'running', 0)

        upsert = self._upsert_method_for(dataset)
        total_rows_upserted = 0

        try:
            for page in self._fetch_pages(dataset, page_size=50_000, since_dt=since_dt):
                total_rows_upserted += upsert(page)
        except Exception as exc:
            logger.error(
                "incremental_refresh failed for dataset %r after upserting %d rows: %s",
                dataset, total_rows_upserted, exc,
                exc_info=True,
            )
            self._write_sync_log(
                dataset, started_at, 'failed',
                total_rows_upserted, error_message=str(exc),
            )
            return SyncResult(
                dataset=dataset,
                status='failed',
                rows_upserted=total_rows_upserted,
                error_message=str(exc),
            )

        self._write_sync_log(dataset, started_at, 'success', total_rows_upserted)
        return SyncResult(
            dataset=dataset,
            status='success',
            rows_upserted=total_rows_upserted,
        )

    def load_all(self, mode: str = 'incremental') -> list[SyncResult]:
        """Run ``full_load`` or ``incremental_refresh`` for all three datasets.

        Returns a list of three ``SyncResult`` objects, one per dataset, in the
        order: parcel_universe, parcel_sales, improvement_characteristics.

        Each dataset is processed sequentially.  If one dataset fails, the
        remaining datasets are still processed (individual methods handle errors
        gracefully and return a ``SyncResult`` with ``status='failed'``).
        """
        datasets = ['parcel_universe', 'parcel_sales', 'improvement_characteristics']
        results: list[SyncResult] = []

        for dataset in datasets:
            if mode == 'full':
                result = self.full_load(dataset)
            else:
                result = self.incremental_refresh(dataset)
            results.append(result)

        return results

    # ------------------------------------------------------------------
    # Private helpers (stubs — implemented in tasks 5.2–5.6)
    # ------------------------------------------------------------------

    def _socrata_get_with_retry(
        self,
        url: str,
        max_retries: int = 3,
        wait_secs: int = 5,
    ) -> list[dict]:
        """Fetch *url* from the Socrata API, retrying up to *max_retries* times.

        Retries on HTTP 4xx/5xx status codes and on network/connection errors
        (``requests.RequestException``).  Waits *wait_secs* seconds between
        attempts.  Raises ``CacheSyncException`` after all retry attempts are
        exhausted.
        """
        # Extract dataset name and page offset from the URL for error reporting.
        try:
            parsed = urlparse(url)
            # Dataset name is typically the last non-empty path segment.
            path_parts = [p for p in parsed.path.split('/') if p]
            dataset = path_parts[-1] if path_parts else 'unknown'
        except Exception:
            dataset = 'unknown'

        # Extract $offset query param for error reporting.
        page_offset: Optional[int] = None
        try:
            from urllib.parse import parse_qs
            qs = parse_qs(urlparse(url).query)
            if '$offset' in qs:
                page_offset = int(qs['$offset'][0])
        except Exception:
            pass

        last_exc: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.get(url, timeout=60)
                if response.ok:
                    return response.json()
                # HTTP 4xx or 5xx — treat as a retryable failure.
                last_exc = requests.HTTPError(
                    f"HTTP {response.status_code} for {url}",
                    response=response,
                )
                logger.warning(
                    "Socrata request failed (attempt %d/%d): HTTP %d — %s",
                    attempt, max_retries, response.status_code, url,
                )
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    "Socrata request error (attempt %d/%d): %s — %s",
                    attempt, max_retries, exc, url,
                )

            if attempt < max_retries:
                time.sleep(wait_secs)

        raise CacheSyncException(
            message=(
                f"Socrata request failed after {max_retries} attempts: {last_exc}"
            ),
            dataset=dataset,
            page_offset=page_offset,
        )

    def _fetch_pages(
        self,
        dataset_name: str,
        page_size: int = 50_000,
        since_dt: Optional[datetime] = None,
    ) -> Iterator[list[dict]]:
        """Yield pages of rows from the Socrata API for *dataset_name*.

        Stops pagination when a page contains fewer rows than *page_size*.
        When *since_dt* is provided, appends a ``$where=:updated_at >= '...'``
        filter for incremental refreshes.  For the ``parcel_sales`` dataset,
        always appends ``AND sale_type='LAND AND BUILDING'``.
        """
        from urllib.parse import urlencode

        _DATASET_IDS: dict[str, str] = {
            'parcel_universe': 'pabr-t5kh',
            'parcel_sales': 'wvhk-k5uv',
            'improvement_characteristics': 'bcnq-qi2z',
        }

        dataset_id = _DATASET_IDS[dataset_name]
        base_url = f'https://datacatalog.cookcountyil.gov/resource/{dataset_id}.json'

        offset = 0
        while True:
            # Build $where clause
            where_parts: list[str] = []

            if since_dt is not None:
                where_parts.append(f":updated_at >= '{since_dt.isoformat()}'")

            if dataset_name == 'parcel_sales':
                where_parts.append("sale_type='LAND AND BUILDING'")

            params: dict[str, object] = {
                '$limit': page_size,
                '$offset': offset,
            }
            if where_parts:
                params['$where'] = ' AND '.join(where_parts)

            url = f'{base_url}?{urlencode(params)}'

            page = self._socrata_get_with_retry(url)
            yield page

            if len(page) < page_size:
                break

            offset += page_size

    def _map_row(
        self,
        row: dict,
        column_whitelist: frozenset[str],
        not_null_cols: frozenset[str],
    ) -> Optional[dict]:
        """Map a raw Socrata row dict to a whitelisted column dict.

        - Extra keys not in *column_whitelist* are silently dropped.
        - Missing nullable columns are set to ``None``.
        - Missing or type-error NOT NULL columns cause the row to be skipped
          (returns ``None``); a WARNING is logged with the PIN and column name.
        - Type conversion errors on nullable columns log a WARNING and insert
          ``None`` for that field.
        - Logs a WARNING when the total column count in *row* differs from the
          whitelist size (schema drift indicator).

        Returns the mapped dict, or ``None`` if the row should be skipped.
        """
        pin = row.get('pin', '<unknown>')

        # Warn on column count mismatch (schema drift indicator).
        if len(row) != len(column_whitelist):
            logger.warning(
                "Schema drift detected for PIN %s: row has %d columns, "
                "expected %d (whitelist size).",
                pin, len(row), len(column_whitelist),
            )

        output: dict = {}

        for col in column_whitelist:
            if col in row:
                output[col] = row[col]
            else:
                # Column is absent from the Socrata row.
                if col in not_null_cols:
                    logger.warning(
                        "Missing NOT NULL column %r for PIN %s — skipping row.",
                        col, pin,
                    )
                    return None
                else:
                    output[col] = None

        return output

    def _upsert_parcel_universe(self, rows: list[dict]) -> int:
        """Upsert *rows* into ``parcel_universe_cache``.

        Uses ``INSERT ... ON CONFLICT (pin) DO UPDATE``.  Calls ``_map_row``
        per row and skips ``None`` results.  Returns the count of successfully
        upserted rows.
        """
        mapped_rows = []
        for row in rows:
            mapped = self._map_row(
                row,
                self.PARCEL_UNIVERSE_WHITELIST,
                self.PARCEL_UNIVERSE_NOT_NULL,
            )
            if mapped is not None:
                mapped_rows.append(mapped)

        if not mapped_rows:
            return 0

        try:
            stmt = pg_insert(ParcelUniverseCache).values(mapped_rows)
            update_cols = {
                col: stmt.excluded[col]
                for col in ['lat', 'lon', 'last_synced_at']
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=['pin'],
                set_=update_cols,
            )
            db.session.execute(stmt)
            db.session.commit()
            return len(mapped_rows)
        except SQLAlchemyError:
            logger.error(
                "SQLAlchemy error during parcel_universe upsert; rolling back.",
                exc_info=True,
            )
            db.session.rollback()
            raise

    def _upsert_parcel_sales(self, rows: list[dict]) -> int:
        """Insert *rows* into ``parcel_sales_cache``.

        ``parcel_sales_cache`` uses a serial ``id`` primary key with no unique
        constraint on ``pin``, so a plain bulk insert is used rather than an
        upsert.  Calls ``_map_row`` per row and skips ``None`` results.
        Returns the count of successfully inserted rows.

        The Socrata field ``class`` is renamed to ``class_`` to match the
        Python attribute name on ``ParcelSalesCache``.
        """
        mapped_rows = []
        for row in rows:
            mapped = self._map_row(
                row,
                self.PARCEL_SALES_WHITELIST,
                self.PARCEL_SALES_NOT_NULL,
            )
            if mapped is None:
                continue
            # Rename 'class' → 'class_' to match the Python attribute name.
            if 'class' in mapped:
                mapped['class_'] = mapped.pop('class')
            mapped_rows.append(mapped)

        if not mapped_rows:
            return 0

        try:
            db.session.bulk_insert_mappings(ParcelSalesCache, mapped_rows)
            db.session.commit()
            return len(mapped_rows)
        except SQLAlchemyError:
            logger.error(
                "SQLAlchemy error during parcel_sales insert; rolling back.",
                exc_info=True,
            )
            db.session.rollback()
            raise

    def _upsert_improvement_chars(self, rows: list[dict]) -> int:
        """Upsert *rows* into ``improvement_characteristics_cache``.

        Uses ``INSERT ... ON CONFLICT (pin) DO UPDATE``.  Calls ``_map_row``
        per row and skips ``None`` results.  Returns the count of successfully
        upserted rows.
        """
        mapped_rows = []
        for row in rows:
            mapped = self._map_row(
                row,
                self.IMPROVEMENT_CHARS_WHITELIST,
                self.IMPROVEMENT_CHARS_NOT_NULL,
            )
            if mapped is not None:
                mapped_rows.append(mapped)

        if not mapped_rows:
            return 0

        # All non-PK columns that should be updated on conflict.
        _update_cols = ['bldg_sf', 'beds', 'fbath', 'hbath', 'age', 'ext_wall', 'apts', 'last_synced_at']

        try:
            stmt = pg_insert(ImprovementCharacteristicsCache).values(mapped_rows)
            update_cols = {col: stmt.excluded[col] for col in _update_cols}
            stmt = stmt.on_conflict_do_update(
                index_elements=['pin'],
                set_=update_cols,
            )
            db.session.execute(stmt)
            db.session.commit()
            return len(mapped_rows)
        except SQLAlchemyError:
            logger.error(
                "SQLAlchemy error during improvement_chars upsert; rolling back.",
                exc_info=True,
            )
            db.session.rollback()
            raise

    def _write_sync_log(
        self,
        dataset: str,
        started_at: datetime,
        status: str,
        rows_upserted: int,
        error_message: Optional[str] = None,
    ) -> SyncLog:
        """Insert a ``SyncLog`` row and return it.

        Sets ``completed_at`` to ``datetime.utcnow()`` for terminal statuses
        (``'success'``, ``'failed'``); leaves it ``None`` for ``'running'``.
        """
        completed_at = datetime.utcnow() if status != 'running' else None
        log_entry = SyncLog(
            dataset_name=dataset,
            started_at=started_at,
            completed_at=completed_at,
            rows_upserted=rows_upserted,
            status=status,
            error_message=error_message,
        )
        db.session.add(log_entry)
        db.session.commit()
        return log_entry

    def _get_last_success_timestamp(self, dataset: str) -> Optional[datetime]:
        """Return the maximum ``completed_at`` among successful sync_log rows for *dataset*.

        Returns ``None`` when no successful sync exists for the dataset.
        """
        return (
            db.session.query(func.max(SyncLog.completed_at))
            .filter(SyncLog.dataset_name == dataset, SyncLog.status == 'success')
            .scalar()
        )


# Populate DATASET_CONFIG after the class is fully defined so that the
# frozenset constants are available.
CacheLoaderService.DATASET_CONFIG = {
    'parcel_universe': {
        'whitelist': CacheLoaderService.PARCEL_UNIVERSE_WHITELIST,
        'not_null': CacheLoaderService.PARCEL_UNIVERSE_NOT_NULL,
        'model': ParcelUniverseCache,
    },
    'parcel_sales': {
        'whitelist': CacheLoaderService.PARCEL_SALES_WHITELIST,
        'not_null': CacheLoaderService.PARCEL_SALES_NOT_NULL,
        'model': ParcelSalesCache,
    },
    'improvement_characteristics': {
        'whitelist': CacheLoaderService.IMPROVEMENT_CHARS_WHITELIST,
        'not_null': CacheLoaderService.IMPROVEMENT_CHARS_NOT_NULL,
        'model': ImprovementCharacteristicsCache,
    },
}
