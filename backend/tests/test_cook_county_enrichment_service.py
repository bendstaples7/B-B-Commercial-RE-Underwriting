"""Tests for Cook County enrichment orchestration and GIS dispatch hooks."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models.lead import Property
from app.services.cook_county_enrichment_service import (
    COOK_COUNTY_MARKET,
    enrich_cook_county_lead,
    ensure_automated_data_sources,
    plugins_for_lead,
    dispatch_cook_county_enrichment,
    maybe_dispatch_after_gis_match,
)
from app.services.lead_ingestion_service import LeadIngestionService
from app.services.deduplication_engine import DeduplicationEngine
from tests.test_lead_ingestion_service import (
    USER_ID,
    _foreclosure_record,
    _make_gis_parcel,
    _make_mock_connector,
    _make_service,
)


def _cook_lead(**kwargs):
    defaults = dict(
        property_street="123 N Michigan Ave",
        property_city="Chicago",
        property_state="IL",
        county_assessor_pin="01-02-202-045-0000",
        source_type="manual_distress",
    )
    defaults.update(kwargs)
    return SimpleNamespace(id=1, **defaults)


def _ensure_source(name: str):
    from app.models.enrichment import DataSource

    source = DataSource.query.filter_by(name=name).first()
    if source is None:
        source = DataSource(name=name, is_active=True)
        db.session.add(source)
        db.session.flush()
    return source


class TestPluginsForLead:
    def test_full_plugin_list_for_cook_pin_chicago(self):
        lead = _cook_lead()
        names = plugins_for_lead(lead)
        assert "cook_county_assessor" in names
        assert "cook_county_commercial_valuation" in names
        assert "chicago_building_violations" in names
        assert "chicago_scofflaw" in names
        assert "cook_county_owner_lookup" in names

    def test_skips_non_cook_leads(self):
        lead = _cook_lead(property_city="Wheaton")
        assert plugins_for_lead(lead) == []

    def test_runs_owner_lookup_when_names_present_but_mail_incomplete(self):
        lead = _cook_lead(
            owner_first_name="Jane",
            owner_last_name="Doe",
        )
        names = plugins_for_lead(lead)
        assert "cook_county_owner_lookup" in names

    def test_skips_owner_lookup_when_owner_mail_is_complete(self):
        lead = _cook_lead(
            owner_first_name="Jane",
            owner_last_name="Doe",
            mailing_address="456 Oak St",
            mailing_city="Chicago",
            mailing_state="IL",
            mailing_zip="60601",
        )
        names = plugins_for_lead(lead)
        assert "cook_county_owner_lookup" not in names


class TestEnrichCookCountyLead:
    def test_json_safe_serializes_date_values(self):
        from datetime import date
        from app.services.data_source_connector import DataSourceConnector

        assert DataSourceConnector._json_safe({
            "acquisition_date": date(2018, 5, 23),
            "nested": {"dates": [date(2020, 1, 2)]},
        }) == {
            "acquisition_date": "2018-05-23",
            "nested": {"dates": ["2020-01-02"]},
        }

    @patch("app.services.cook_county_enrichment_service.refresh_lead_scoring")
    @patch("app.services.cook_county_enrichment_service.DataSourceConnector")
    def test_runs_plugins_and_rescores_once(self, mock_connector_cls, mock_refresh, app):
        with app.app_context():
            lead = Property(
                property_street="123 N Michigan Ave",
                property_city="Chicago",
                property_state="IL",
                county_assessor_pin="01-02-202-045-0000",
                source_type="manual_distress",
            )
            db.session.add(lead)
            db.session.commit()

            mock_connector = MagicMock()
            mock_connector_cls.return_value = mock_connector

            def _enrich(lead_id, source_name, refresh_scoring=True):
                record = MagicMock()
                record.status = "no_results"
                assert refresh_scoring is False
                return record

            mock_connector.enrich_lead.side_effect = _enrich

            result = enrich_cook_county_lead(lead.id)

            assert result["plugins_run"] > 0
            assert mock_connector.enrich_lead.call_count == result["plugins_run"]
            mock_refresh.assert_called_once_with(lead.id)

    @patch("app.services.cook_county_enrichment_service.refresh_lead_scoring")
    @patch("app.services.cook_county_enrichment_service.DataSourceConnector")
    def test_skips_non_cook_lead(self, mock_connector_cls, mock_refresh, app):
        with app.app_context():
            lead = Property(
                property_street="100 Main St",
                property_city="Wheaton",
                property_state="IL",
                source_type="foreclosure",
            )
            db.session.add(lead)
            db.session.commit()

            result = enrich_cook_county_lead(lead.id)

            assert result["skipped"] is True
            mock_connector_cls.return_value.enrich_lead.assert_not_called()
            mock_refresh.assert_not_called()


class TestDispatch:
    @patch("celery_worker.cook_county_enrich_lead_task")
    def test_dispatch_uses_apply_async(self, mock_task):
        mock_task.apply_async.return_value = MagicMock()
        assert dispatch_cook_county_enrichment(42) is True
        mock_task.apply_async.assert_called_once_with(args=[42], ignore_result=True)


class TestGisHook:
    def test_maybe_dispatch_schedules_after_commit_for_cook(self):
        lead = SimpleNamespace(id=99)
        connector = SimpleNamespace(market=COOK_COUNTY_MARKET)

        with patch(
            "app.services.cook_county_enrichment_service.schedule_cook_county_enrichment_after_commit"
        ) as mock_schedule:
            maybe_dispatch_after_gis_match(lead, connector)
            mock_schedule.assert_called_once_with(99)

    def test_maybe_dispatch_ignores_dupage(self):
        lead = SimpleNamespace(id=99)
        connector = SimpleNamespace(market="dupage_il")

        with patch(
            "app.services.cook_county_enrichment_service.schedule_cook_county_enrichment_after_commit"
        ) as mock_schedule:
            maybe_dispatch_after_gis_match(lead, connector)
            mock_schedule.assert_not_called()

    @patch(
        "app.services.cook_county_enrichment_service.schedule_cook_county_enrichment_after_commit"
    )
    def test_gis_match_triggers_dispatch_hook(self, mock_schedule, app):
        with app.app_context():
            connector = MagicMock()
            connector.connector_name = "cook_county_gis"
            connector.market = COOK_COUNTY_MARKET
            connector.lookup_by_address.return_value = _make_gis_parcel()

            lead = Property(
                property_street="123 N Michigan Ave",
                property_city="Chicago",
                property_state="IL",
                source_type="manual_distress",
            )
            db.session.add(lead)
            db.session.flush()

            svc = LeadIngestionService(
                dedup_engine=DeduplicationEngine(),
                gis_registry={COOK_COUNTY_MARKET: connector},
            )
            outcome = svc._enrich_with_gis(lead, connector, import_job_id=1)

            assert outcome["match_found"] is True
            mock_schedule.assert_called_once_with(lead.id)


class TestForeclosureGisRouting:
    def test_foreclosure_uses_connector_for_lead_not_hardcoded_dupage(self, app):
        """Regression: foreclosure GIS routing must use lead market, not dupage_il."""
        with app.app_context():
            cook_connector = _make_mock_connector(
                parcel=None,
                market=COOK_COUNTY_MARKET,
            )
            dupage_connector = _make_mock_connector(parcel=None, market="dupage_il")
            svc = _make_service(gis_registry={
                COOK_COUNTY_MARKET: cook_connector,
                "dupage_il": dupage_connector,
            })

            with patch(
                "app.services.gis.routing.connector_for_lead",
                return_value=None,
            ):
                svc.ingest_foreclosure(
                    [_foreclosure_record(property_city="Chicago")],
                    USER_ID,
                )

            cook_connector.lookup_by_address.assert_called()
            dupage_connector.lookup_by_address.assert_not_called()


class TestBackfillEnrichment:
    def test_seed_automated_data_sources_repairs_empty_catalog(self, app):
        with app.app_context():
            from app.models.enrichment import DataSource

            DataSource.query.delete()
            db.session.commit()

            rows = ensure_automated_data_sources()

            names = {row.name for row in rows}
            assert "cook_county_assessor" in names
            assert "cook_county_commercial_valuation" in names
            assert DataSource.query.filter_by(name="cook_county_assessor").first() is not None

    @patch("app.services.cook_county_enrichment_service.enrich_cook_county_lead")
    def test_backfill_respects_batch_size(self, mock_enrich, app):
        with app.app_context():
            from app.services.cook_county_enrichment_service import backfill_cook_county_enrichment
            _ensure_source("cook_county_commercial_valuation")
            for i in range(5):
                lead = Property(
                    property_street=f"{i} N Michigan Ave",
                    property_city="Chicago",
                    property_state="IL",
                    county_assessor_pin=f"01-02-202-04{i}-0000",
                    source_type="manual_distress",
                )
                db.session.add(lead)
            db.session.commit()

            mock_enrich.return_value = {"plugins_run": 3, "skipped": False}

            summary = backfill_cook_county_enrichment(batch_size=2, socrata_call_cap=200)

            assert summary["enriched"] == 2
            assert mock_enrich.call_count == 2

    @patch("app.services.cook_county_enrichment_service.enrich_cook_county_lead")
    def test_backfill_includes_chicago_leads_without_pin(self, mock_enrich, app):
        with app.app_context():
            from app.services.cook_county_enrichment_service import backfill_cook_county_enrichment
            _ensure_source("cook_county_commercial_valuation")
            lead = Property(
                property_street="2915 N Hamlin Ave",
                property_city="Chicago",
                property_state="IL",
                county_assessor_pin=None,
                source_type="manual_distress",
            )
            db.session.add(lead)
            db.session.commit()

            mock_enrich.return_value = {"plugins_run": 1, "skipped": False}

            summary = backfill_cook_county_enrichment(batch_size=1, socrata_call_cap=10)

            assert summary["enriched"] == 1
            mock_enrich.assert_called_once_with(lead.id)

    @patch("app.services.cook_county_enrichment_service.enrich_cook_county_lead")
    def test_backfill_skips_recent_no_pin_sale_check(self, mock_enrich, app):
        with app.app_context():
            from datetime import datetime
            from app.services.cook_county_enrichment_service import backfill_cook_county_enrichment
            from app.models.enrichment import EnrichmentRecord

            assessor = _ensure_source("cook_county_assessor")
            _ensure_source("cook_county_commercial_valuation")
            lead = Property(
                property_street="2915 N Hamlin Ave",
                property_city="Chicago",
                property_state="IL",
                county_assessor_pin=None,
                source_type="manual_distress",
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(EnrichmentRecord(
                lead_id=lead.id,
                data_source_id=assessor.id,
                status="no_results",
                created_at=datetime.utcnow(),
            ))
            db.session.commit()

            summary = backfill_cook_county_enrichment(batch_size=1, socrata_call_cap=10)

            assert summary["skipped"] >= 1
            mock_enrich.assert_not_called()

    @patch("app.services.cook_county_enrichment_service.enrich_cook_county_lead")
    def test_backfill_skips_recently_enriched(self, mock_enrich, app):
        with app.app_context():
            from datetime import datetime, timedelta
            from app.models.enrichment import EnrichmentRecord
            from app.services.cook_county_enrichment_service import backfill_cook_county_enrichment

            source = _ensure_source("cook_county_commercial_valuation")

            lead = Property(
                property_street="123 N Michigan Ave",
                property_city="Chicago",
                property_state="IL",
                county_assessor_pin="01-02-202-045-0000",
                source_type="manual_distress",
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(EnrichmentRecord(
                lead_id=lead.id,
                data_source_id=source.id,
                status="success",
                created_at=datetime.utcnow(),
            ))
            db.session.commit()

            summary = backfill_cook_county_enrichment(batch_size=75, socrata_call_cap=200)

            assert summary["skipped"] >= 1
            mock_enrich.assert_not_called()

    @patch("app.services.cook_county_enrichment_service.enrich_cook_county_lead")
    def test_backfill_stops_at_socrata_cap(self, mock_enrich, app):
        with app.app_context():
            from app.services.cook_county_enrichment_service import backfill_cook_county_enrichment
            _ensure_source("cook_county_commercial_valuation")
            for i in range(4):
                lead = Property(
                    property_street=f"{i} N Michigan Ave",
                    property_city="Chicago",
                    property_state="IL",
                    county_assessor_pin=f"01-02-202-04{i}-0000",
                    source_type="manual_distress",
                )
                db.session.add(lead)
            db.session.commit()

            mock_enrich.return_value = {"plugins_run": 5, "skipped": False}

            summary = backfill_cook_county_enrichment(batch_size=75, socrata_call_cap=12)

            assert summary["capped"] is True
            assert summary["socrata_calls"] == 5
            assert mock_enrich.call_count == 1

    @patch("app.services.cook_county_enrichment_service.enrich_cook_county_lead")
    def test_backfill_skips_recent_sale_without_due_task(self, mock_enrich, app):
        with app.app_context():
            from datetime import date, timedelta
            from app.services.cook_county_enrichment_service import backfill_cook_county_enrichment

            _ensure_source("cook_county_commercial_valuation")
            lead = Property(
                property_street="10 Recent Sale Ave",
                property_city="Chicago",
                property_state="IL",
                county_assessor_pin="01-02-202-099-0000",
                acquisition_date=date.today() - timedelta(days=30),
                source_type="manual_distress",
            )
            db.session.add(lead)
            db.session.commit()

            summary = backfill_cook_county_enrichment(batch_size=5, socrata_call_cap=50)

            assert summary["skipped"] >= 1
            mock_enrich.assert_not_called()

    @patch("app.services.cook_county_enrichment_service.enrich_cook_county_lead")
    def test_backfill_enriches_recent_sale_when_open_task_due(self, mock_enrich, app):
        with app.app_context():
            from datetime import date, timedelta
            from app.models.lead_task import LeadTask
            from app.services.cook_county_enrichment_service import backfill_cook_county_enrichment

            _ensure_source("cook_county_commercial_valuation")
            lead = Property(
                property_street="11 Due Task Ave",
                property_city="Chicago",
                property_state="IL",
                county_assessor_pin="01-02-202-088-0000",
                acquisition_date=date.today() - timedelta(days=30),
                source_type="manual_distress",
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(LeadTask(
                lead_id=lead.id,
                task_type='custom',
                title='Follow up',
                status='open',
                due_date=date.today(),
                created_by='test',
            ))
            db.session.commit()
            mock_enrich.return_value = {"plugins_run": 2, "skipped": False}

            summary = backfill_cook_county_enrichment(batch_size=5, socrata_call_cap=50)

            assert summary["enriched"] == 1
            mock_enrich.assert_called_once_with(lead.id)

    def test_catalog_health_heals_and_reports_ok(self, app):
        with app.app_context():
            from app.models.enrichment import DataSource
            from app.services.cook_county_enrichment_service import (
                check_enrichment_catalog_health,
            )

            DataSource.query.delete()
            db.session.commit()
            result = check_enrichment_catalog_health(heal=True)
            assert result["ok"] is True
            assert result["present_count"] == result["required_count"]

    def test_invariants_are_read_only_counts(self, app):
        with app.app_context():
            from app.services.cook_county_enrichment_service import (
                collect_enrichment_supporting_data_invariants,
            )

            summary = collect_enrichment_supporting_data_invariants()
            assert "catalog_ok" in summary
            assert "enrichment_records_last_7d" in summary
            assert "chicago_no_pin_with_sale" in summary
            assert "working_set_sale_no_enrichment" in summary
            assert isinstance(summary["catalog_missing"], list)


class TestPinRecovery:
    @patch("app.services.cook_county_enrichment_service.refresh_lead_scoring")
    @patch("app.services.cook_county_enrichment_service.DataSourceConnector")
    def test_enrich_attempts_pin_recovery_for_chicago_no_pin(
        self, mock_connector_cls, mock_refresh, app,
    ):
        with app.app_context():
            lead = Property(
                property_street="2915 N Hamlin Ave",
                property_city="Chicago",
                property_state="IL",
                county_assessor_pin=None,
                source_type="manual_distress",
            )
            db.session.add(lead)
            db.session.commit()

            mock_connector = MagicMock()
            mock_connector_cls.return_value = mock_connector
            record = MagicMock()
            record.status = "no_results"
            mock_connector.enrich_lead.return_value = record

            parcel = SimpleNamespace(county_assessor_pin="14-21-123-456-0000")
            gis = MagicMock()
            gis.lookup_by_address.return_value = parcel

            with patch(
                "app.services.gis.routing.connector_for_lead",
                return_value=gis,
            ):
                result = enrich_cook_county_lead(lead.id)

            db.session.refresh(lead)
            assert lead.county_assessor_pin == "14-21-123-456-0000"
            assert result["skipped"] is False
            assert result["plugins_run"] > 1
            gis.lookup_by_address.assert_called()


class TestScheduleAfterCommit:
    def test_deduplicates_lead_ids_in_session(self, app):
        with app.app_context():
            from app.services.cook_county_enrichment_service import (
                schedule_cook_county_enrichment_after_commit,
            )

            schedule_cook_county_enrichment_after_commit(42)
            schedule_cook_county_enrichment_after_commit(42)
            schedule_cook_county_enrichment_after_commit(43)

            pending = db.session.info.get("cook_county_enrichment_pending", set())
            assert pending == {42, 43}
