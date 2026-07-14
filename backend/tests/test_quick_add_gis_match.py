"""Regression tests for quick-add GIS follow-up wiring."""
from unittest.mock import MagicMock, patch

from app import db
from app.models import Lead
from app.tasks.quick_add_tasks import _run_gis_match


class TestRunGisMatchWiring:
    def test_constructs_ingestion_service_with_required_deps(self, app):
        """Constructor must receive dedup_engine + gis_registry (not bare ())."""
        with app.app_context():
            lead = Lead(
                property_street='4904 North Paulina Street, Chicago, IL, USA',
                property_city='Chicago',
                property_state='IL',
                property_zip='60640',
                has_property_match=False,
                owner_user_id='test-user',
            )
            db.session.add(lead)
            db.session.commit()
            lead_id = lead.id

            mock_connector = MagicMock()
            mock_connector.connector_name = 'cook_county_il'
            mock_outcome = {
                'connector_name': 'cook_county_il',
                'match_found': True,
                'fields_populated': 1,
                'error': None,
            }

            with patch(
                'app.services.lead_ingestion_service.LeadIngestionService'
            ) as mock_cls:
                instance = MagicMock()
                instance._gis_connector_for_lead.return_value = mock_connector
                instance._enrich_with_gis.return_value = mock_outcome
                mock_cls.return_value = instance

                matched = _run_gis_match(lead_id)

                assert matched is True
                mock_cls.assert_called_once()
                kwargs = mock_cls.call_args.kwargs
                assert 'dedup_engine' in kwargs
                assert 'gis_registry' in kwargs
                assert kwargs['dedup_engine'] is not None
                assert kwargs['gis_registry'] is not None
                instance._enrich_with_gis.assert_called_once()

    def test_returns_false_when_lead_missing(self, app):
        with app.app_context():
            assert _run_gis_match(999_999_999) is False

    def test_skips_when_already_matched(self, app):
        with app.app_context():
            lead = Lead(
                property_street='1 Already Matched St',
                property_city='Chicago',
                property_state='IL',
                has_property_match=True,
                owner_user_id='test-user',
            )
            db.session.add(lead)
            db.session.commit()

            with patch(
                'app.services.lead_ingestion_service.LeadIngestionService'
            ) as mock_cls:
                assert _run_gis_match(lead.id) is True
                mock_cls.assert_not_called()
