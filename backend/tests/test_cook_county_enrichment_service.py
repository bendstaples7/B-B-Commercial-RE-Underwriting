"""Tests for Cook County enrichment orchestration and GIS dispatch hooks."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models.lead import Property
from app.services.cook_county_enrichment_service import (
    COOK_COUNTY_MARKET,
    enrich_cook_county_lead,
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

    def test_skips_owner_lookup_when_names_present(self):
        lead = _cook_lead(
            owner_first_name="Jane",
            owner_last_name="Doe",
        )
        names = plugins_for_lead(lead)
        assert "cook_county_owner_lookup" not in names


class TestEnrichCookCountyLead:
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
