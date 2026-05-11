"""Comprehensive unit tests for CacheLoaderService."""
import pytest
from datetime import datetime, timedelta, date
from unittest.mock import patch, MagicMock, call
import requests

from app.services.cache_loader_service import CacheLoaderService, SyncResult
from app.models.sync_log import SyncLog
from app.models.parcel_universe_cache import ParcelUniverseCache
from app.models.parcel_sales_cache import ParcelSalesCache
from app.models.improvement_characteristics_cache import ImprovementCharacteristicsCache
from app.exceptions import CacheSyncException
from app import db


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def service(app):
    """Return a CacheLoaderService instance inside the app context."""
    with app.app_context():
        yield CacheLoaderService()


# ============================================================
# SyncResult dataclass
# ============================================================


class TestSyncResult:
    def test_success_result_defaults(self):
        r = SyncResult(dataset="parcel_universe", status="success", rows_upserted=42)
        assert r.dataset == "parcel_universe"
        assert r.status == "success"
        assert r.rows_upserted == 42
        assert r.error_message is None

    def test_failed_result_with_message(self):
        r = SyncResult(
            dataset="parcel_sales",
            status="failed",
            rows_upserted=0,
            error_message="timeout",
        )
        assert r.status == "failed"
        assert r.error_message == "timeout"

    def test_rows_upserted_zero(self):
        r = SyncResult(dataset="improvement_characteristics", status="success", rows_upserted=0)
        assert r.rows_upserted == 0


# ============================================================
# _map_row
# ============================================================


class TestMapRow:
    """Tests for CacheLoaderService._map_row."""

    def setup_method(self):
        self.svc = CacheLoaderService()
        self.whitelist = frozenset({"pin", "lat", "lon", "last_synced_at"})
        self.not_null = frozenset({"pin"})

    def test_maps_all_whitelisted_columns(self):
        row = {"pin": "12345", "lat": "41.8", "lon": "-87.6", "last_synced_at": None, "extra": "ignored"}
        result = self.svc._map_row(row, self.whitelist, self.not_null)
        assert result is not None
        assert result["pin"] == "12345"
        assert result["lat"] == "41.8"
        assert result["lon"] == "-87.6"
        assert "extra" not in result

    def test_drops_extra_keys(self):
        row = {"pin": "12345", "lat": "41.8", "lon": "-87.6", "last_synced_at": None, "unknown_col": "x"}
        result = self.svc._map_row(row, self.whitelist, self.not_null)
        assert "unknown_col" not in result

    def test_missing_nullable_column_becomes_none(self):
        row = {"pin": "12345", "lat": "41.8"}  # lon and last_synced_at missing
        result = self.svc._map_row(row, self.whitelist, self.not_null)
        assert result is not None
        assert result["lon"] is None
        assert result["last_synced_at"] is None

    def test_missing_not_null_column_returns_none(self):
        row = {"lat": "41.8", "lon": "-87.6", "last_synced_at": None}  # pin missing
        result = self.svc._map_row(row, self.whitelist, self.not_null)
        assert result is None

    def test_schema_drift_warning_logged(self, caplog):
        import logging
        row = {"pin": "12345", "lat": "41.8"}  # only 2 cols vs whitelist of 4
        with caplog.at_level(logging.WARNING, logger="app.services.cache_loader_service"):
            self.svc._map_row(row, self.whitelist, self.not_null)
        assert any("Schema drift" in r.message for r in caplog.records)

    def test_no_warning_when_column_count_matches(self, caplog):
        import logging
        row = {"pin": "12345", "lat": "41.8", "lon": "-87.6", "last_synced_at": None}
        with caplog.at_level(logging.WARNING, logger="app.services.cache_loader_service"):
            self.svc._map_row(row, self.whitelist, self.not_null)
        drift_warnings = [r for r in caplog.records if "Schema drift" in r.message]
        assert len(drift_warnings) == 0

    def test_empty_row_missing_not_null_returns_none(self):
        result = self.svc._map_row({}, self.whitelist, self.not_null)
        assert result is None

    def test_all_nullable_columns_missing_returns_mapped(self):
        whitelist = frozenset({"pin", "lat"})
        not_null = frozenset({"pin"})
        row = {"pin": "99999"}
        result = self.svc._map_row(row, whitelist, not_null)
        assert result == {"pin": "99999", "lat": None}

    def test_parcel_sales_whitelist_mapping(self):
        svc = CacheLoaderService()
        row = {
            "pin": "14083010190000",
            "sale_date": date(2023, 1, 15),
            "sale_price": "250000",
            "class": "2-11",
            "sale_type": "LAND AND BUILDING",
            "is_multisale": None,
            "sale_filter_less_than_10k": None,
            "sale_filter_deed_type": None,
            "last_synced_at": None,
        }
        result = svc._map_row(row, svc.PARCEL_SALES_WHITELIST, svc.PARCEL_SALES_NOT_NULL)
        assert result is not None
        assert result["pin"] == "14083010190000"
        assert result["class"] == "2-11"

    def test_improvement_chars_whitelist_mapping(self):
        svc = CacheLoaderService()
        row = {
            "pin": "14083010190000",
            "bldg_sf": "2400",
            "beds": "3",
            "fbath": "2",
            "hbath": "1",
            "age": "50",
            "ext_wall": "1",
            "apts": "2",
            "last_synced_at": None,
        }
        result = svc._map_row(row, svc.IMPROVEMENT_CHARS_WHITELIST, svc.IMPROVEMENT_CHARS_NOT_NULL)
        assert result is not None
        assert result["bldg_sf"] == "2400"


# ============================================================
# _socrata_get_with_retry
# ============================================================


class TestSocrataGetWithRetry:
    """Tests for CacheLoaderService._socrata_get_with_retry."""

    def setup_method(self):
        self.svc = CacheLoaderService()

    @patch("app.services.cache_loader_service.requests.get")
    def test_returns_json_on_200(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = [{"pin": "123"}]
        mock_get.return_value = mock_resp

        result = self.svc._socrata_get_with_retry("https://example.com/resource/abc.json")
        assert result == [{"pin": "123"}]
        mock_get.assert_called_once()

    @patch("app.services.cache_loader_service.time.sleep")
    @patch("app.services.cache_loader_service.requests.get")
    def test_retries_on_http_error_then_succeeds(self, mock_get, mock_sleep):
        fail_resp = MagicMock()
        fail_resp.ok = False
        fail_resp.status_code = 503

        ok_resp = MagicMock()
        ok_resp.ok = True
        ok_resp.json.return_value = [{"pin": "456"}]

        mock_get.side_effect = [fail_resp, ok_resp]

        result = self.svc._socrata_get_with_retry(
            "https://example.com/resource/abc.json", max_retries=3, wait_secs=1
        )
        assert result == [{"pin": "456"}]
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(1)

    @patch("app.services.cache_loader_service.time.sleep")
    @patch("app.services.cache_loader_service.requests.get")
    def test_raises_cache_sync_exception_after_all_retries(self, mock_get, mock_sleep):
        fail_resp = MagicMock()
        fail_resp.ok = False
        fail_resp.status_code = 500

        mock_get.return_value = fail_resp

        with pytest.raises(CacheSyncException):
            self.svc._socrata_get_with_retry(
                "https://example.com/resource/abc.json", max_retries=3, wait_secs=0
            )
        assert mock_get.call_count == 3

    @patch("app.services.cache_loader_service.time.sleep")
    @patch("app.services.cache_loader_service.requests.get")
    def test_retries_on_request_exception(self, mock_get, mock_sleep):
        ok_resp = MagicMock()
        ok_resp.ok = True
        ok_resp.json.return_value = []

        mock_get.side_effect = [requests.ConnectionError("conn refused"), ok_resp]

        result = self.svc._socrata_get_with_retry(
            "https://example.com/resource/abc.json", max_retries=3, wait_secs=0
        )
        assert result == []

    @patch("app.services.cache_loader_service.time.sleep")
    @patch("app.services.cache_loader_service.requests.get")
    def test_raises_after_all_network_errors(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.ConnectionError("no route")

        with pytest.raises(CacheSyncException) as exc_info:
            self.svc._socrata_get_with_retry(
                "https://example.com/resource/abc.json", max_retries=2, wait_secs=0
            )
        assert mock_get.call_count == 2
        assert "2 attempts" in str(exc_info.value)

    @patch("app.services.cache_loader_service.time.sleep")
    @patch("app.services.cache_loader_service.requests.get")
    def test_sleep_called_between_retries_not_after_last(self, mock_get, mock_sleep):
        fail_resp = MagicMock()
        fail_resp.ok = False
        fail_resp.status_code = 429
        mock_get.return_value = fail_resp

        with pytest.raises(CacheSyncException):
            self.svc._socrata_get_with_retry(
                "https://example.com/resource/abc.json", max_retries=3, wait_secs=5
            )
        # sleep called between attempt 1->2 and 2->3, but NOT after attempt 3
        assert mock_sleep.call_count == 2

    @patch("app.services.cache_loader_service.requests.get")
    def test_cache_sync_exception_contains_dataset_name(self, mock_get):
        fail_resp = MagicMock()
        fail_resp.ok = False
        fail_resp.status_code = 500
        mock_get.return_value = fail_resp

        with pytest.raises(CacheSyncException) as exc_info:
            self.svc._socrata_get_with_retry(
                "https://datacatalog.cookcountyil.gov/resource/pabr-t5kh.json?$limit=50000",
                max_retries=1,
                wait_secs=0,
            )
        assert exc_info.value.payload["dataset"] == "pabr-t5kh.json"

    @patch("app.services.cache_loader_service.requests.get")
    def test_single_retry_max(self, mock_get):
        ok_resp = MagicMock()
        ok_resp.ok = True
        ok_resp.json.return_value = [{"pin": "789"}]
        mock_get.return_value = ok_resp

        result = self.svc._socrata_get_with_retry(
            "https://example.com/resource/abc.json", max_retries=1, wait_secs=0
        )
        assert result == [{"pin": "789"}]
        mock_get.assert_called_once()


# ============================================================
# _fetch_pages
# ============================================================


class TestFetchPages:
    """Tests for CacheLoaderService._fetch_pages."""

    def setup_method(self):
        self.svc = CacheLoaderService()

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_single_page_stops_when_less_than_page_size(self, mock_get):
        mock_get.return_value = [{"pin": str(i)} for i in range(10)]

        pages = list(self.svc._fetch_pages("parcel_universe", page_size=50))
        assert len(pages) == 1
        assert len(pages[0]) == 10

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_multiple_pages_until_partial(self, mock_get):
        full_page = [{"pin": str(i)} for i in range(5)]
        partial_page = [{"pin": "99"}]
        mock_get.side_effect = [full_page, partial_page]

        pages = list(self.svc._fetch_pages("parcel_universe", page_size=5))
        assert len(pages) == 2
        assert mock_get.call_count == 2

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_offset_increments_correctly(self, mock_get):
        full_page = [{"pin": str(i)} for i in range(3)]
        empty_page = []
        mock_get.side_effect = [full_page, empty_page]

        list(self.svc._fetch_pages("parcel_universe", page_size=3))

        first_url = mock_get.call_args_list[0][0][0]
        second_url = mock_get.call_args_list[1][0][0]
        assert "%24offset=0" in first_url or "$offset=0" in first_url
        assert "%24offset=3" in second_url or "$offset=3" in second_url

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_since_dt_appended_to_where_clause(self, mock_get):
        mock_get.return_value = []
        since = datetime(2024, 1, 1, 12, 0, 0)

        list(self.svc._fetch_pages("parcel_universe", page_size=100, since_dt=since))

        url = mock_get.call_args[0][0]
        assert "updated_at" in url or "%3Aupdated_at" in url

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_parcel_sales_always_has_sale_type_filter(self, mock_get):
        mock_get.return_value = []

        list(self.svc._fetch_pages("parcel_sales", page_size=100))

        url = mock_get.call_args[0][0]
        assert "LAND+AND+BUILDING" in url or "LAND%20AND%20BUILDING" in url or "LAND AND BUILDING" in url

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_parcel_universe_no_sale_type_filter(self, mock_get):
        mock_get.return_value = []

        list(self.svc._fetch_pages("parcel_universe", page_size=100))

        url = mock_get.call_args[0][0]
        assert "LAND AND BUILDING" not in url
        assert "sale_type" not in url

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_correct_dataset_id_used_for_parcel_universe(self, mock_get):
        mock_get.return_value = []
        list(self.svc._fetch_pages("parcel_universe", page_size=10))
        url = mock_get.call_args[0][0]
        assert "pabr-t5kh" in url

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_correct_dataset_id_used_for_parcel_sales(self, mock_get):
        mock_get.return_value = []
        list(self.svc._fetch_pages("parcel_sales", page_size=10))
        url = mock_get.call_args[0][0]
        assert "wvhk-k5uv" in url

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_correct_dataset_id_used_for_improvement_chars(self, mock_get):
        mock_get.return_value = []
        list(self.svc._fetch_pages("improvement_characteristics", page_size=10))
        url = mock_get.call_args[0][0]
        assert "bcnq-qi2z" in url

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_empty_first_page_yields_one_empty_page(self, mock_get):
        mock_get.return_value = []
        pages = list(self.svc._fetch_pages("parcel_universe", page_size=100))
        assert len(pages) == 1
        assert pages[0] == []

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_parcel_sales_with_since_dt_has_both_filters(self, mock_get):
        mock_get.return_value = []
        since = datetime(2024, 6, 1)
        list(self.svc._fetch_pages("parcel_sales", page_size=100, since_dt=since))
        url = mock_get.call_args[0][0]
        # Both the updated_at filter and sale_type filter should be present
        assert "updated_at" in url or "%3Aupdated_at" in url
        assert "LAND" in url


# ============================================================
# _write_sync_log
# ============================================================


class TestWriteSyncLog:
    """Tests for CacheLoaderService._write_sync_log."""

    def test_creates_running_log_without_completed_at(self, service, app):
        with app.app_context():
            started = datetime.utcnow()
            log = service._write_sync_log("parcel_universe", started, "running", 0)
            assert log.id is not None
            assert log.status == "running"
            assert log.completed_at is None
            assert log.rows_upserted == 0
            assert log.dataset_name == "parcel_universe"

    def test_creates_success_log_with_completed_at(self, service, app):
        with app.app_context():
            started = datetime.utcnow()
            log = service._write_sync_log("parcel_sales", started, "success", 500)
            assert log.status == "success"
            assert log.completed_at is not None
            assert log.rows_upserted == 500

    def test_creates_failed_log_with_error_message(self, service, app):
        with app.app_context():
            started = datetime.utcnow()
            log = service._write_sync_log(
                "improvement_characteristics", started, "failed", 10, error_message="timeout"
            )
            assert log.status == "failed"
            assert log.error_message == "timeout"
            assert log.completed_at is not None

    def test_running_log_has_no_completed_at(self, service, app):
        with app.app_context():
            started = datetime.utcnow()
            log = service._write_sync_log("parcel_universe", started, "running", 0)
            assert log.completed_at is None

    def test_log_persisted_to_db(self, service, app):
        with app.app_context():
            started = datetime.utcnow()
            service._write_sync_log("parcel_universe", started, "success", 100)
            count = db.session.query(SyncLog).filter_by(
                dataset_name="parcel_universe", status="success"
            ).count()
            assert count == 1

    def test_multiple_logs_for_same_dataset(self, service, app):
        with app.app_context():
            started = datetime.utcnow()
            service._write_sync_log("parcel_universe", started, "success", 100)
            service._write_sync_log("parcel_universe", started, "success", 200)
            count = db.session.query(SyncLog).filter_by(dataset_name="parcel_universe").count()
            assert count == 2


# ============================================================
# _get_last_success_timestamp
# ============================================================


class TestGetLastSuccessTimestamp:
    """Tests for CacheLoaderService._get_last_success_timestamp."""

    def test_returns_none_when_no_logs(self, service, app):
        with app.app_context():
            result = service._get_last_success_timestamp("parcel_universe")
            assert result is None

    def test_returns_none_when_only_failed_logs(self, service, app):
        with app.app_context():
            started = datetime.utcnow()
            service._write_sync_log("parcel_universe", started, "failed", 0, error_message="err")
            result = service._get_last_success_timestamp("parcel_universe")
            assert result is None

    def test_returns_max_completed_at_for_success(self, service, app):
        with app.app_context():
            t1 = datetime(2024, 1, 1, 12, 0, 0)
            t2 = datetime(2024, 6, 1, 12, 0, 0)
            # Insert two success logs with different completed_at values
            log1 = SyncLog(
                dataset_name="parcel_universe",
                started_at=t1,
                completed_at=t1,
                rows_upserted=100,
                status="success",
            )
            log2 = SyncLog(
                dataset_name="parcel_universe",
                started_at=t2,
                completed_at=t2,
                rows_upserted=200,
                status="success",
            )
            db.session.add_all([log1, log2])
            db.session.commit()

            result = service._get_last_success_timestamp("parcel_universe")
            assert result == t2

    def test_ignores_other_datasets(self, service, app):
        with app.app_context():
            t = datetime(2024, 3, 15, 8, 0, 0)
            log = SyncLog(
                dataset_name="parcel_sales",
                started_at=t,
                completed_at=t,
                rows_upserted=50,
                status="success",
            )
            db.session.add(log)
            db.session.commit()

            result = service._get_last_success_timestamp("parcel_universe")
            assert result is None

    def test_ignores_running_status(self, service, app):
        with app.app_context():
            t = datetime(2024, 3, 15, 8, 0, 0)
            log = SyncLog(
                dataset_name="parcel_universe",
                started_at=t,
                completed_at=None,
                rows_upserted=0,
                status="running",
            )
            db.session.add(log)
            db.session.commit()

            result = service._get_last_success_timestamp("parcel_universe")
            assert result is None


# ============================================================
# _upsert_parcel_universe
# ============================================================


class TestUpsertParcelUniverse:
    """Tests for CacheLoaderService._upsert_parcel_universe."""

    def test_upserts_valid_rows(self, service, app):
        with app.app_context():
            rows = [
                {"pin": "14083010190000", "lat": "41.8781", "lon": "-87.6298", "last_synced_at": None},
                {"pin": "14083010200000", "lat": "41.8790", "lon": "-87.6300", "last_synced_at": None},
            ]
            count = service._upsert_parcel_universe(rows)
            assert count == 2
            db_count = db.session.query(ParcelUniverseCache).count()
            assert db_count == 2

    def test_returns_zero_for_empty_input(self, service, app):
        with app.app_context():
            count = service._upsert_parcel_universe([])
            assert count == 0

    def test_skips_rows_missing_pin(self, service, app):
        with app.app_context():
            rows = [
                {"lat": "41.8781", "lon": "-87.6298", "last_synced_at": None},  # no pin
                {"pin": "14083010200000", "lat": "41.8790", "lon": "-87.6300", "last_synced_at": None},
            ]
            count = service._upsert_parcel_universe(rows)
            assert count == 1

    def test_upsert_updates_existing_row(self, service, app):
        with app.app_context():
            rows = [{"pin": "14083010190000", "lat": "41.8781", "lon": "-87.6298", "last_synced_at": None}]
            service._upsert_parcel_universe(rows)

            updated_rows = [{"pin": "14083010190000", "lat": "41.9000", "lon": "-87.7000", "last_synced_at": None}]
            count = service._upsert_parcel_universe(updated_rows)
            assert count == 1

            record = db.session.query(ParcelUniverseCache).filter_by(pin="14083010190000").one()
            assert float(record.lat) == pytest.approx(41.9000, abs=0.0001)

    def test_returns_count_of_mapped_rows(self, service, app):
        with app.app_context():
            rows = [
                {"pin": "11111111111111", "lat": "41.0", "lon": "-87.0", "last_synced_at": None},
                {"lat": "41.0", "lon": "-87.0", "last_synced_at": None},  # skipped
                {"pin": "22222222222222", "lat": "42.0", "lon": "-88.0", "last_synced_at": None},
            ]
            count = service._upsert_parcel_universe(rows)
            assert count == 2

    def test_all_rows_missing_pin_returns_zero(self, service, app):
        with app.app_context():
            rows = [
                {"lat": "41.0", "lon": "-87.0", "last_synced_at": None},
                {"lat": "42.0", "lon": "-88.0", "last_synced_at": None},
            ]
            count = service._upsert_parcel_universe(rows)
            assert count == 0
            assert db.session.query(ParcelUniverseCache).count() == 0


# ============================================================
# _upsert_parcel_sales
# ============================================================


class TestUpsertParcelSales:
    """Tests for CacheLoaderService._upsert_parcel_sales."""

    def _make_row(self, pin="14083010190000", **kwargs):
        base = {
            "pin": pin,
            "sale_date": date(2023, 1, 15),
            "sale_price": "250000",
            "class": "2-11",
            "sale_type": "LAND AND BUILDING",
            "is_multisale": None,
            "sale_filter_less_than_10k": None,
            "sale_filter_deed_type": None,
            "last_synced_at": None,
        }
        base.update(kwargs)
        return base

    def test_inserts_valid_rows(self, service, app):
        with app.app_context():
            rows = [self._make_row("11111111111111"), self._make_row("22222222222222")]
            count = service._upsert_parcel_sales(rows)
            assert count == 2
            assert db.session.query(ParcelSalesCache).count() == 2

    def test_returns_zero_for_empty_input(self, service, app):
        with app.app_context():
            count = service._upsert_parcel_sales([])
            assert count == 0

    def test_skips_rows_missing_pin(self, service, app):
        with app.app_context():
            row_no_pin = {
                "sale_date": date(2023, 1, 15),
                "sale_price": "250000",
                "class": "2-11",
                "sale_type": "LAND AND BUILDING",
                "is_multisale": None,
                "sale_filter_less_than_10k": None,
                "sale_filter_deed_type": None,
                "last_synced_at": None,
            }
            count = service._upsert_parcel_sales([row_no_pin])
            assert count == 0

    def test_renames_class_to_class_underscore(self, service, app):
        with app.app_context():
            rows = [self._make_row()]
            service._upsert_parcel_sales(rows)
            record = db.session.query(ParcelSalesCache).first()
            assert record is not None
            assert record.class_ == "2-11"

    def test_multiple_sales_for_same_pin_allowed(self, service, app):
        with app.app_context():
            rows = [
                self._make_row("14083010190000"),
                self._make_row("14083010190000"),
            ]
            count = service._upsert_parcel_sales(rows)
            assert count == 2
            assert db.session.query(ParcelSalesCache).filter_by(pin="14083010190000").count() == 2

    def test_all_rows_missing_pin_returns_zero(self, service, app):
        with app.app_context():
            rows = [
                {"sale_date": "2023-01-15", "sale_price": "100000", "class": "2-11",
                 "sale_type": "LAND AND BUILDING", "is_multisale": "false",
                 "sale_filter_less_than_10k": "false", "sale_filter_deed_type": "false",
                 "last_synced_at": None},
            ]
            count = service._upsert_parcel_sales(rows)
            assert count == 0


# ============================================================
# _upsert_improvement_chars
# ============================================================


class TestUpsertImprovementChars:
    """Tests for CacheLoaderService._upsert_improvement_chars."""

    def _make_row(self, pin="14083010190000", **kwargs):
        base = {
            "pin": pin,
            "bldg_sf": "2400",
            "beds": "3",
            "fbath": "2",
            "hbath": "1",
            "age": "50",
            "ext_wall": "1",
            "apts": "2",
            "last_synced_at": None,
        }
        base.update(kwargs)
        return base

    def test_upserts_valid_rows(self, service, app):
        with app.app_context():
            rows = [self._make_row("11111111111111"), self._make_row("22222222222222")]
            count = service._upsert_improvement_chars(rows)
            assert count == 2
            assert db.session.query(ImprovementCharacteristicsCache).count() == 2

    def test_returns_zero_for_empty_input(self, service, app):
        with app.app_context():
            count = service._upsert_improvement_chars([])
            assert count == 0

    def test_skips_rows_missing_pin(self, service, app):
        with app.app_context():
            row_no_pin = {
                "bldg_sf": "2400", "beds": "3", "fbath": "2", "hbath": "1",
                "age": "50", "ext_wall": "1", "apts": "2", "last_synced_at": None,
            }
            count = service._upsert_improvement_chars([row_no_pin])
            assert count == 0

    def test_upsert_updates_existing_row(self, service, app):
        with app.app_context():
            rows = [self._make_row("14083010190000", bldg_sf="2400")]
            service._upsert_improvement_chars(rows)

            updated = [self._make_row("14083010190000", bldg_sf="3000")]
            count = service._upsert_improvement_chars(updated)
            assert count == 1

            record = db.session.query(ImprovementCharacteristicsCache).filter_by(
                pin="14083010190000"
            ).one()
            assert record.bldg_sf == 3000

    def test_nullable_fields_can_be_none(self, service, app):
        with app.app_context():
            rows = [{"pin": "14083010190000", "bldg_sf": None, "beds": None,
                     "fbath": None, "hbath": None, "age": None, "ext_wall": None,
                     "apts": None, "last_synced_at": None}]
            count = service._upsert_improvement_chars(rows)
            assert count == 1
            record = db.session.query(ImprovementCharacteristicsCache).first()
            assert record.bldg_sf is None


# ============================================================
# full_load
# ============================================================


class TestFullLoad:
    """Tests for CacheLoaderService.full_load."""

    def _parcel_universe_row(self, pin):
        return {"pin": pin, "lat": "41.8781", "lon": "-87.6298", "last_synced_at": None}

    def test_raises_value_error_for_invalid_dataset(self, service, app):
        with app.app_context():
            with pytest.raises(ValueError, match="Invalid dataset"):
                service.full_load("nonexistent_dataset")

    @patch.object(CacheLoaderService, "_fetch_pages")
    def test_returns_success_result(self, mock_pages, service, app):
        with app.app_context():
            mock_pages.return_value = iter([[self._parcel_universe_row("11111111111111")]])
            result = service.full_load("parcel_universe")
            assert result.status == "success"
            assert result.dataset == "parcel_universe"
            assert result.rows_upserted == 1
            assert result.error_message is None

    @patch.object(CacheLoaderService, "_fetch_pages")
    def test_writes_running_then_success_sync_log(self, mock_pages, service, app):
        with app.app_context():
            mock_pages.return_value = iter([[self._parcel_universe_row("11111111111111")]])
            service.full_load("parcel_universe")
            logs = db.session.query(SyncLog).filter_by(dataset_name="parcel_universe").all()
            statuses = {log.status for log in logs}
            assert "success" in statuses

    @patch.object(CacheLoaderService, "_fetch_pages")
    def test_accumulates_rows_across_pages(self, mock_pages, service, app):
        with app.app_context():
            page1 = [self._parcel_universe_row("11111111111111"), self._parcel_universe_row("22222222222222")]
            page2 = [self._parcel_universe_row("33333333333333")]
            mock_pages.return_value = iter([page1, page2])
            result = service.full_load("parcel_universe")
            assert result.rows_upserted == 3

    @patch.object(CacheLoaderService, "_fetch_pages")
    def test_returns_failed_result_on_exception(self, mock_pages, service, app):
        with app.app_context():
            mock_pages.side_effect = CacheSyncException(
                "API down", dataset="parcel_universe"
            )
            result = service.full_load("parcel_universe")
            assert result.status == "failed"
            assert result.error_message is not None

    @patch.object(CacheLoaderService, "_fetch_pages")
    def test_writes_failed_sync_log_on_exception(self, mock_pages, service, app):
        with app.app_context():
            mock_pages.side_effect = RuntimeError("unexpected error")
            service.full_load("parcel_universe")
            log = db.session.query(SyncLog).filter_by(
                dataset_name="parcel_universe", status="failed"
            ).first()
            assert log is not None
            assert "unexpected error" in log.error_message

    @patch.object(CacheLoaderService, "_fetch_pages")
    def test_zero_rows_on_empty_pages(self, mock_pages, service, app):
        with app.app_context():
            mock_pages.return_value = iter([[]])
            result = service.full_load("parcel_universe")
            assert result.status == "success"
            assert result.rows_upserted == 0

    @patch.object(CacheLoaderService, "_fetch_pages")
    def test_full_load_parcel_sales(self, mock_pages, service, app):
        with app.app_context():
            rows = [{
                "pin": "14083010190000",
                "sale_date": date(2023, 1, 15),
                "sale_price": "250000",
                "class": "2-11",
                "sale_type": "LAND AND BUILDING",
                "is_multisale": None,
                "sale_filter_less_than_10k": None,
                "sale_filter_deed_type": None,
                "last_synced_at": None,
            }]
            mock_pages.return_value = iter([rows])
            result = service.full_load("parcel_sales")
            assert result.status == "success"
            assert result.rows_upserted == 1

    @patch.object(CacheLoaderService, "_fetch_pages")
    def test_full_load_improvement_characteristics(self, mock_pages, service, app):
        with app.app_context():
            rows = [{
                "pin": "14083010190000",
                "bldg_sf": "2400", "beds": "3", "fbath": "2", "hbath": "1",
                "age": "50", "ext_wall": "1", "apts": "2", "last_synced_at": None,
            }]
            mock_pages.return_value = iter([rows])
            result = service.full_load("improvement_characteristics")
            assert result.status == "success"
            assert result.rows_upserted == 1

    def test_all_three_valid_dataset_names_accepted(self, service, app):
        with app.app_context():
            for dataset in ["parcel_universe", "parcel_sales", "improvement_characteristics"]:
                with patch.object(CacheLoaderService, "_fetch_pages", return_value=iter([[]])):
                    result = service.full_load(dataset)
                    assert result.dataset == dataset


# ============================================================
# incremental_refresh
# ============================================================


class TestIncrementalRefresh:
    """Tests for CacheLoaderService.incremental_refresh."""

    def _parcel_universe_row(self, pin):
        return {"pin": pin, "lat": "41.8781", "lon": "-87.6298", "last_synced_at": None}

    def test_raises_value_error_for_invalid_dataset(self, service, app):
        with app.app_context():
            with pytest.raises(ValueError, match="Invalid dataset"):
                service.incremental_refresh("bad_dataset")

    @patch.object(CacheLoaderService, "_get_last_success_timestamp")
    @patch.object(CacheLoaderService, "full_load")
    def test_falls_back_to_full_load_when_no_prior_success(self, mock_full, mock_ts, service, app):
        with app.app_context():
            mock_ts.return_value = None
            mock_full.return_value = SyncResult(
                dataset="parcel_universe", status="success", rows_upserted=100
            )
            result = service.incremental_refresh("parcel_universe")
            mock_full.assert_called_once_with("parcel_universe")
            assert result.status == "success"

    @patch.object(CacheLoaderService, "_fetch_pages")
    @patch.object(CacheLoaderService, "_get_last_success_timestamp")
    def test_uses_since_dt_when_prior_success_exists(self, mock_ts, mock_pages, service, app):
        with app.app_context():
            since = datetime(2024, 1, 1, 12, 0, 0)
            mock_ts.return_value = since
            mock_pages.return_value = iter([[self._parcel_universe_row("11111111111111")]])

            result = service.incremental_refresh("parcel_universe")

            assert result.status == "success"
            mock_pages.assert_called_once_with(
                "parcel_universe", page_size=50_000, since_dt=since
            )

    @patch.object(CacheLoaderService, "_fetch_pages")
    @patch.object(CacheLoaderService, "_get_last_success_timestamp")
    def test_returns_success_result(self, mock_ts, mock_pages, service, app):
        with app.app_context():
            mock_ts.return_value = datetime(2024, 1, 1)
            mock_pages.return_value = iter([[self._parcel_universe_row("11111111111111")]])
            result = service.incremental_refresh("parcel_universe")
            assert result.status == "success"
            assert result.rows_upserted == 1

    @patch.object(CacheLoaderService, "_fetch_pages")
    @patch.object(CacheLoaderService, "_get_last_success_timestamp")
    def test_returns_failed_result_on_exception(self, mock_ts, mock_pages, service, app):
        with app.app_context():
            mock_ts.return_value = datetime(2024, 1, 1)
            mock_pages.side_effect = CacheSyncException(
                "timeout", dataset="parcel_universe"
            )
            result = service.incremental_refresh("parcel_universe")
            assert result.status == "failed"
            assert result.error_message is not None

    @patch.object(CacheLoaderService, "_fetch_pages")
    @patch.object(CacheLoaderService, "_get_last_success_timestamp")
    def test_writes_success_sync_log(self, mock_ts, mock_pages, service, app):
        with app.app_context():
            mock_ts.return_value = datetime(2024, 1, 1)
            mock_pages.return_value = iter([[self._parcel_universe_row("11111111111111")]])
            service.incremental_refresh("parcel_universe")
            log = db.session.query(SyncLog).filter_by(
                dataset_name="parcel_universe", status="success"
            ).first()
            assert log is not None

    @patch.object(CacheLoaderService, "_fetch_pages")
    @patch.object(CacheLoaderService, "_get_last_success_timestamp")
    def test_writes_failed_sync_log_on_exception(self, mock_ts, mock_pages, service, app):
        with app.app_context():
            mock_ts.return_value = datetime(2024, 1, 1)
            mock_pages.side_effect = RuntimeError("boom")
            service.incremental_refresh("parcel_universe")
            log = db.session.query(SyncLog).filter_by(
                dataset_name="parcel_universe", status="failed"
            ).first()
            assert log is not None

    @patch.object(CacheLoaderService, "_fetch_pages")
    @patch.object(CacheLoaderService, "_get_last_success_timestamp")
    def test_zero_rows_when_no_new_data(self, mock_ts, mock_pages, service, app):
        with app.app_context():
            mock_ts.return_value = datetime(2024, 1, 1)
            mock_pages.return_value = iter([[]])
            result = service.incremental_refresh("parcel_universe")
            assert result.status == "success"
            assert result.rows_upserted == 0


# ============================================================
# load_all
# ============================================================


class TestLoadAll:
    """Tests for CacheLoaderService.load_all."""

    def test_returns_three_results(self, service, app):
        with app.app_context():
            with patch.object(CacheLoaderService, "incremental_refresh") as mock_inc:
                mock_inc.return_value = SyncResult(
                    dataset="x", status="success", rows_upserted=0
                )
                results = service.load_all(mode="incremental")
                assert len(results) == 3

    def test_incremental_mode_calls_incremental_refresh(self, service, app):
        with app.app_context():
            with patch.object(CacheLoaderService, "incremental_refresh") as mock_inc:
                mock_inc.return_value = SyncResult(
                    dataset="x", status="success", rows_upserted=0
                )
                service.load_all(mode="incremental")
                assert mock_inc.call_count == 3

    def test_full_mode_calls_full_load(self, service, app):
        with app.app_context():
            with patch.object(CacheLoaderService, "full_load") as mock_full:
                mock_full.return_value = SyncResult(
                    dataset="x", status="success", rows_upserted=0
                )
                service.load_all(mode="full")
                assert mock_full.call_count == 3

    def test_default_mode_is_incremental(self, service, app):
        with app.app_context():
            with patch.object(CacheLoaderService, "incremental_refresh") as mock_inc:
                mock_inc.return_value = SyncResult(
                    dataset="x", status="success", rows_upserted=0
                )
                service.load_all()
                assert mock_inc.call_count == 3

    def test_processes_all_three_datasets_in_order(self, service, app):
        with app.app_context():
            called_datasets = []

            def fake_incremental(dataset):
                called_datasets.append(dataset)
                return SyncResult(dataset=dataset, status="success", rows_upserted=0)

            with patch.object(CacheLoaderService, "incremental_refresh", side_effect=fake_incremental):
                service.load_all(mode="incremental")

            assert called_datasets == [
                "parcel_universe",
                "parcel_sales",
                "improvement_characteristics",
            ]

    def test_continues_after_one_dataset_fails(self, service, app):
        with app.app_context():
            def fake_incremental(dataset):
                if dataset == "parcel_universe":
                    return SyncResult(dataset=dataset, status="failed", rows_upserted=0, error_message="err")
                return SyncResult(dataset=dataset, status="success", rows_upserted=10)

            with patch.object(CacheLoaderService, "incremental_refresh", side_effect=fake_incremental):
                results = service.load_all(mode="incremental")

            assert len(results) == 3
            assert results[0].status == "failed"
            assert results[1].status == "success"
            assert results[2].status == "success"

    def test_result_datasets_match_expected_names(self, service, app):
        with app.app_context():
            def fake_incremental(dataset):
                return SyncResult(dataset=dataset, status="success", rows_upserted=0)

            with patch.object(CacheLoaderService, "incremental_refresh", side_effect=fake_incremental):
                results = service.load_all()

            dataset_names = [r.dataset for r in results]
            assert "parcel_universe" in dataset_names
            assert "parcel_sales" in dataset_names
            assert "improvement_characteristics" in dataset_names

    def test_full_mode_passes_correct_dataset_names(self, service, app):
        with app.app_context():
            called_datasets = []

            def fake_full(dataset):
                called_datasets.append(dataset)
                return SyncResult(dataset=dataset, status="success", rows_upserted=0)

            with patch.object(CacheLoaderService, "full_load", side_effect=fake_full):
                service.load_all(mode="full")

            assert called_datasets == [
                "parcel_universe",
                "parcel_sales",
                "improvement_characteristics",
            ]


# ============================================================
# DATASET_CONFIG class constant
# ============================================================


class TestDatasetConfig:
    """Tests for CacheLoaderService.DATASET_CONFIG class constant."""

    def test_all_three_datasets_present(self):
        cfg = CacheLoaderService.DATASET_CONFIG
        assert "parcel_universe" in cfg
        assert "parcel_sales" in cfg
        assert "improvement_characteristics" in cfg

    def test_parcel_universe_config_has_correct_model(self):
        cfg = CacheLoaderService.DATASET_CONFIG["parcel_universe"]
        assert cfg["model"] is ParcelUniverseCache

    def test_parcel_sales_config_has_correct_model(self):
        cfg = CacheLoaderService.DATASET_CONFIG["parcel_sales"]
        assert cfg["model"] is ParcelSalesCache

    def test_improvement_chars_config_has_correct_model(self):
        cfg = CacheLoaderService.DATASET_CONFIG["improvement_characteristics"]
        assert cfg["model"] is ImprovementCharacteristicsCache

    def test_parcel_universe_whitelist_contains_pin(self):
        cfg = CacheLoaderService.DATASET_CONFIG["parcel_universe"]
        assert "pin" in cfg["whitelist"]

    def test_parcel_universe_not_null_contains_pin(self):
        cfg = CacheLoaderService.DATASET_CONFIG["parcel_universe"]
        assert "pin" in cfg["not_null"]

    def test_parcel_sales_whitelist_contains_class(self):
        cfg = CacheLoaderService.DATASET_CONFIG["parcel_sales"]
        assert "class" in cfg["whitelist"]

    def test_improvement_chars_whitelist_contains_bldg_sf(self):
        cfg = CacheLoaderService.DATASET_CONFIG["improvement_characteristics"]
        assert "bldg_sf" in cfg["whitelist"]


# ============================================================
# _upsert_method_for
# ============================================================


class TestUpsertMethodFor:
    """Tests for CacheLoaderService._upsert_method_for dispatch."""

    def setup_method(self):
        self.svc = CacheLoaderService()

    def test_parcel_universe_returns_correct_method(self):
        method = self.svc._upsert_method_for("parcel_universe")
        assert method == self.svc._upsert_parcel_universe

    def test_parcel_sales_returns_correct_method(self):
        method = self.svc._upsert_method_for("parcel_sales")
        assert method == self.svc._upsert_parcel_sales

    def test_improvement_characteristics_returns_correct_method(self):
        method = self.svc._upsert_method_for("improvement_characteristics")
        assert method == self.svc._upsert_improvement_chars

    def test_invalid_dataset_raises_key_error(self):
        with pytest.raises(KeyError):
            self.svc._upsert_method_for("nonexistent")


# ============================================================
# Integration: full_load writes data to DB and sync_log
# ============================================================


class TestFullLoadIntegration:
    """End-to-end integration tests for full_load with real DB writes."""

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_full_load_parcel_universe_end_to_end(self, mock_get, service, app):
        with app.app_context():
            page1 = [
                {"pin": "11111111111111", "lat": "41.8", "lon": "-87.6", "last_synced_at": None},
                {"pin": "22222222222222", "lat": "41.9", "lon": "-87.7", "last_synced_at": None},
            ]
            # Return full page then empty to stop pagination
            mock_get.side_effect = [page1, []]

            result = service.full_load("parcel_universe")

            assert result.status == "success"
            assert result.rows_upserted == 2
            assert db.session.query(ParcelUniverseCache).count() == 2
            log = db.session.query(SyncLog).filter_by(
                dataset_name="parcel_universe", status="success"
            ).first()
            assert log is not None
            assert log.rows_upserted == 2

    @patch.object(CacheLoaderService, "_socrata_get_with_retry")
    def test_incremental_refresh_uses_watermark(self, mock_get, service, app):
        with app.app_context():
            # Seed a prior success log
            t = datetime(2024, 1, 1, 0, 0, 0)
            log = SyncLog(
                dataset_name="parcel_universe",
                started_at=t,
                completed_at=t,
                rows_upserted=10,
                status="success",
            )
            db.session.add(log)
            db.session.commit()

            mock_get.return_value = []

            result = service.incremental_refresh("parcel_universe")

            assert result.status == "success"
            # Verify the URL contained the since_dt watermark
            url = mock_get.call_args[0][0]
            assert "updated_at" in url or "%3Aupdated_at" in url
