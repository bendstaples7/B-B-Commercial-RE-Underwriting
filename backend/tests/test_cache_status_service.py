"""Unit tests for CacheStatusService.

Covers:
  - never_synced: table empty, no sync_log rows
  - empty:        table empty, sync_log has rows
  - fresh:        table has rows, last success < 30 days ago
  - stale:        table has rows, last success > 30 days ago
  - last_error:   populated from most recent failed sync_log row

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.models.parcel_universe_cache import ParcelUniverseCache
from app.models.parcel_sales_cache import ParcelSalesCache
from app.models.improvement_characteristics_cache import ImprovementCharacteristicsCache
from app.models.sync_log import SyncLog
from app.services.cache_status_service import CacheStatusService, DatasetStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sync_log(
    db_session,
    dataset_name: str,
    status: str,
    completed_at: datetime | None = None,
    error_message: str | None = None,
) -> SyncLog:
    """Insert a SyncLog row and return it."""
    row = SyncLog(
        dataset_name=dataset_name,
        started_at=datetime.now(timezone.utc),
        completed_at=completed_at,
        rows_upserted=0,
        status=status,
        error_message=error_message,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _add_parcel_universe_row(db_session) -> ParcelUniverseCache:
    """Insert one row into parcel_universe_cache."""
    row = ParcelUniverseCache(
        pin='12345678901234',
        lat=41.8781,
        lon=-87.6298,
        last_synced_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _add_parcel_sales_row(db_session) -> ParcelSalesCache:
    """Insert one row into parcel_sales_cache."""
    row = ParcelSalesCache(
        pin='12345678901234',
        sale_date=None,
        sale_price=None,
        last_synced_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _add_improvement_chars_row(db_session) -> ImprovementCharacteristicsCache:
    """Insert one row into improvement_characteristics_cache."""
    row = ImprovementCharacteristicsCache(
        pin='12345678901234',
        last_synced_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    db_session.flush()
    return row


# ---------------------------------------------------------------------------
# Tests: never_synced
# ---------------------------------------------------------------------------

class TestNeverSynced:
    """Status is 'never_synced' when the table is empty and no sync_log rows exist."""

    def test_parcel_universe_never_synced(self, db_session):
        """Empty parcel_universe_cache with no sync_log → never_synced."""
        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert isinstance(result, DatasetStatus)
        assert result.dataset_name == 'parcel_universe'
        assert result.row_count == 0
        assert result.status == 'never_synced'
        assert result.last_synced_at is None
        assert result.last_error is None

    def test_parcel_sales_never_synced(self, db_session):
        """Empty parcel_sales_cache with no sync_log → never_synced."""
        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_sales')

        assert result.status == 'never_synced'
        assert result.row_count == 0
        assert result.last_synced_at is None

    def test_improvement_characteristics_never_synced(self, db_session):
        """Empty improvement_characteristics_cache with no sync_log → never_synced."""
        svc = CacheStatusService()
        result = svc.get_dataset_status('improvement_characteristics')

        assert result.status == 'never_synced'
        assert result.row_count == 0
        assert result.last_synced_at is None

    def test_get_status_all_never_synced(self, db_session):
        """get_status() returns never_synced for all three datasets when DB is empty."""
        svc = CacheStatusService()
        results = svc.get_status()

        assert len(results) == 3
        for r in results:
            assert r.status == 'never_synced'


# ---------------------------------------------------------------------------
# Tests: empty
# ---------------------------------------------------------------------------

class TestEmpty:
    """Status is 'empty' when the table has zero rows but sync_log has rows."""

    def test_parcel_universe_empty_after_failed_sync(self, db_session):
        """Table empty + failed sync_log row → empty (not never_synced)."""
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='failed',
            completed_at=datetime.now(timezone.utc),
            error_message='Connection refused',
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.status == 'empty'
        assert result.row_count == 0

    def test_parcel_universe_empty_after_success_sync(self, db_session):
        """Table empty + successful sync_log row → empty (rows were deleted externally)."""
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        # Row count is 0 but a sync has been attempted → 'empty'
        assert result.status == 'empty'
        assert result.row_count == 0

    def test_parcel_sales_empty_after_multiple_syncs(self, db_session):
        """Table empty + both failed and success sync_log rows → empty."""
        _make_sync_log(
            db_session,
            dataset_name='parcel_sales',
            status='failed',
            completed_at=datetime.now(timezone.utc) - timedelta(days=2),
            error_message='First attempt failed',
        )
        _make_sync_log(
            db_session,
            dataset_name='parcel_sales',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=1),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_sales')

        # Table is empty despite a successful sync → 'empty'
        assert result.status == 'empty'
        assert result.row_count == 0

    def test_improvement_characteristics_empty_after_failed_sync(self, db_session):
        """improvement_characteristics table empty + failed sync → empty."""
        _make_sync_log(
            db_session,
            dataset_name='improvement_characteristics',
            status='failed',
            completed_at=datetime.now(timezone.utc),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('improvement_characteristics')

        assert result.status == 'empty'
        assert result.row_count == 0

    def test_never_synced_vs_empty_distinction(self, db_session):
        """Datasets with no sync_log are never_synced; those with sync_log are empty."""
        # Only add a sync_log for parcel_universe
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='failed',
            completed_at=datetime.now(timezone.utc),
        )

        svc = CacheStatusService()
        pu = svc.get_dataset_status('parcel_universe')
        ps = svc.get_dataset_status('parcel_sales')

        assert pu.status == 'empty'
        assert ps.status == 'never_synced'


# ---------------------------------------------------------------------------
# Tests: fresh
# ---------------------------------------------------------------------------

class TestFresh:
    """Status is 'fresh' when the table has rows and last success < 30 days ago."""

    def test_parcel_universe_fresh(self, db_session):
        """Table has rows + recent success sync → fresh."""
        _add_parcel_universe_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=1),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.status == 'fresh'
        assert result.row_count == 1
        assert result.last_synced_at is not None

    def test_parcel_sales_fresh(self, db_session):
        """parcel_sales with rows + sync 15 days ago → fresh."""
        _add_parcel_sales_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_sales',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=15),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_sales')

        assert result.status == 'fresh'

    def test_improvement_characteristics_fresh(self, db_session):
        """improvement_characteristics with rows + sync today → fresh."""
        _add_improvement_chars_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='improvement_characteristics',
            status='success',
            completed_at=datetime.now(timezone.utc),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('improvement_characteristics')

        assert result.status == 'fresh'

    def test_fresh_exactly_at_threshold(self, db_session):
        """Sync exactly 30 days ago is still fresh (≤ threshold)."""
        _add_parcel_universe_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=30),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.status == 'fresh'

    def test_fresh_uses_most_recent_success(self, db_session):
        """When multiple success rows exist, the most recent one determines freshness."""
        _add_parcel_universe_row(db_session)
        # Older success (stale)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        # Newer success (fresh)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=5),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.status == 'fresh'

    def test_last_synced_at_matches_most_recent_success(self, db_session):
        """last_synced_at reflects the completed_at of the most recent success row."""
        _add_parcel_universe_row(db_session)
        recent_dt = datetime.now(timezone.utc) - timedelta(days=3)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=recent_dt,
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.last_synced_at is not None
        # SQLite strips timezone info; normalise both sides to naive UTC for comparison
        result_naive = result.last_synced_at.replace(tzinfo=None) if result.last_synced_at.tzinfo else result.last_synced_at
        recent_naive = recent_dt.replace(tzinfo=None)
        assert abs((result_naive - recent_naive).total_seconds()) < 1


# ---------------------------------------------------------------------------
# Tests: stale
# ---------------------------------------------------------------------------

class TestStale:
    """Status is 'stale' when the table has rows and last success > 30 days ago."""

    def test_parcel_universe_stale(self, db_session):
        """Table has rows + success sync 31 days ago → stale."""
        _add_parcel_universe_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=31),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.status == 'stale'
        assert result.row_count == 1

    def test_parcel_sales_stale(self, db_session):
        """parcel_sales with rows + sync 90 days ago → stale."""
        _add_parcel_sales_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_sales',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=90),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_sales')

        assert result.status == 'stale'

    def test_improvement_characteristics_stale(self, db_session):
        """improvement_characteristics with rows + sync 45 days ago → stale."""
        _add_improvement_chars_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='improvement_characteristics',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=45),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('improvement_characteristics')

        assert result.status == 'stale'

    def test_stale_just_over_threshold(self, db_session):
        """Sync 31 days ago (one day over threshold) → stale."""
        _add_parcel_universe_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=31),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.status == 'stale'

    def test_stale_uses_most_recent_success(self, db_session):
        """When multiple success rows exist, the most recent one determines staleness."""
        _add_parcel_universe_row(db_session)
        # Older success (also stale, but older)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=90),
        )
        # Newer success (still stale)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=45),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.status == 'stale'

    def test_stale_with_env_override(self, db_session, monkeypatch):
        """SOCRATA_STALE_DAYS env var overrides the 30-day default threshold."""
        # Set threshold to 7 days
        monkeypatch.setenv('SOCRATA_STALE_DAYS', '7')

        _add_parcel_universe_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=10),
        )

        # Re-import to pick up the new env var value
        import importlib
        import app.services.cache_status_service as css_module
        importlib.reload(css_module)
        from app.services.cache_status_service import CacheStatusService as ReloadedService

        svc = ReloadedService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.status == 'stale'

        # Restore module to default state
        monkeypatch.delenv('SOCRATA_STALE_DAYS', raising=False)
        importlib.reload(css_module)


# ---------------------------------------------------------------------------
# Tests: last_error
# ---------------------------------------------------------------------------

class TestLastError:
    """last_error is populated from the most recent failed sync_log row."""

    def test_last_error_populated_from_failed_sync(self, db_session):
        """last_error contains the error_message from the most recent failed row."""
        _add_parcel_universe_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='failed',
            completed_at=datetime.now(timezone.utc),
            error_message='HTTP 503 from Socrata at offset 50000',
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.last_error == 'HTTP 503 from Socrata at offset 50000'

    def test_last_error_none_when_no_failures(self, db_session):
        """last_error is None when there are no failed sync_log rows."""
        _add_parcel_universe_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=1),
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.last_error is None

    def test_last_error_uses_most_recent_failure(self, db_session):
        """When multiple failed rows exist, last_error comes from the most recent one."""
        _add_parcel_universe_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        # Older failure
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='failed',
            completed_at=datetime.now(timezone.utc) - timedelta(days=5),
            error_message='Old error message',
        )
        # Newer failure
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='failed',
            completed_at=datetime.now(timezone.utc) - timedelta(hours=2),
            error_message='Recent error message',
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.last_error == 'Recent error message'

    def test_last_error_none_when_never_synced(self, db_session):
        """last_error is None when the dataset has never been synced."""
        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.last_error is None
        assert result.status == 'never_synced'

    def test_last_error_populated_on_empty_table(self, db_session):
        """last_error is populated even when the table is empty (status='empty')."""
        _make_sync_log(
            db_session,
            dataset_name='parcel_sales',
            status='failed',
            completed_at=datetime.now(timezone.utc),
            error_message='Connection timeout at page 0',
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_sales')

        assert result.status == 'empty'
        assert result.last_error == 'Connection timeout at page 0'

    def test_last_error_isolated_per_dataset(self, db_session):
        """Failures for one dataset do not bleed into another dataset's last_error."""
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='failed',
            completed_at=datetime.now(timezone.utc),
            error_message='parcel_universe error',
        )

        svc = CacheStatusService()
        ps_result = svc.get_dataset_status('parcel_sales')

        # parcel_sales has no sync_log rows at all
        assert ps_result.last_error is None
        assert ps_result.status == 'never_synced'

    def test_last_error_null_error_message(self, db_session):
        """A failed sync_log row with NULL error_message results in last_error=None."""
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='failed',
            completed_at=datetime.now(timezone.utc),
            error_message=None,
        )

        svc = CacheStatusService()
        result = svc.get_dataset_status('parcel_universe')

        assert result.status == 'empty'
        assert result.last_error is None


# ---------------------------------------------------------------------------
# Tests: get_status() — all three datasets
# ---------------------------------------------------------------------------

class TestGetStatus:
    """get_status() returns a list of DatasetStatus for all three datasets."""

    def test_get_status_returns_three_entries(self, db_session):
        """get_status() always returns exactly three DatasetStatus objects."""
        svc = CacheStatusService()
        results = svc.get_status()

        assert len(results) == 3

    def test_get_status_dataset_names(self, db_session):
        """get_status() returns entries for all three expected dataset names."""
        svc = CacheStatusService()
        results = svc.get_status()

        names = {r.dataset_name for r in results}
        assert names == {'parcel_universe', 'parcel_sales', 'improvement_characteristics'}

    def test_get_status_mixed_states(self, db_session):
        """get_status() correctly reports different states for different datasets."""
        # parcel_universe: fresh
        _add_parcel_universe_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_universe',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=1),
        )

        # parcel_sales: stale
        _add_parcel_sales_row(db_session)
        _make_sync_log(
            db_session,
            dataset_name='parcel_sales',
            status='success',
            completed_at=datetime.now(timezone.utc) - timedelta(days=60),
        )

        # improvement_characteristics: never_synced (no rows, no sync_log)

        svc = CacheStatusService()
        results = svc.get_status()

        by_name = {r.dataset_name: r for r in results}
        assert by_name['parcel_universe'].status == 'fresh'
        assert by_name['parcel_sales'].status == 'stale'
        assert by_name['improvement_characteristics'].status == 'never_synced'

    def test_get_status_returns_datasetstatuses(self, db_session):
        """Every item returned by get_status() has the expected DatasetStatus fields."""
        svc = CacheStatusService()
        results = svc.get_status()

        expected_fields = {'dataset_name', 'row_count', 'last_synced_at', 'status', 'last_error'}
        for r in results:
            assert set(vars(r).keys()) == expected_fields

    def test_get_dataset_status_unknown_dataset_raises(self, db_session):
        """get_dataset_status() raises KeyError for an unknown dataset name."""
        svc = CacheStatusService()
        with pytest.raises(KeyError):
            svc.get_dataset_status('nonexistent_dataset')
