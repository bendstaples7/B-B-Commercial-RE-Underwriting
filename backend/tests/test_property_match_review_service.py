"""Regression tests for property match approve / PIN apply."""
from unittest.mock import MagicMock, patch

from app import db
from app.models import Lead
from app.services.property_match_review_service import PropertyMatchReviewService


def _seed_lead(**overrides) -> Lead:
    lead = Lead(
        property_street='123 Test St',
        property_city='Chicago',
        property_state='IL',
        property_zip='60601',
        has_property_match=False,
        needs_skip_trace=True,
        lead_status='awaiting_skip_trace',
        recommended_action='call_ready',  # plain str — must not call .value
        owner_user_id='test-user',
    )
    for key, value in overrides.items():
        setattr(lead, key, value)
    db.session.add(lead)
    db.session.commit()
    return lead


class TestApproveMatch:
    def test_approve_serializes_string_recommended_action(self, app):
        with app.app_context():
            lead = _seed_lead()
            mock_connector = MagicMock()
            mock_connector.connector_name = 'cook_county_gis'
            mock_connector.market = 'cook_county_il'

            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=mock_connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_ingestion_service',
            ) as mock_ingestion, patch(
                'app.services.property_match_review_service.refresh_lead_scoring',
            ):
                svc_instance = MagicMock()
                svc_instance._enrich_with_gis.return_value = {
                    'connector_name': 'cook_county_gis',
                    'match_found': True,
                    'fields_populated': 1,
                    'parcel_pin': '14-21-123-456-0000',
                }
                mock_ingestion.return_value = svc_instance

                result = PropertyMatchReviewService().approve_match(
                    lead.id, actor='tester', pin='14211234560000',
                )

            assert result['recommended_action'] == 'call_ready'
            assert result['county_assessor_pin'] == '14-21-123-456-0000'
            refreshed = db.session.get(Lead, lead.id)
            assert refreshed.needs_skip_trace is True
            assert refreshed.county_assessor_pin == '14-21-123-456-0000'
            assert svc_instance._enrich_with_gis.call_args.kwargs['pin_hint'] == (
                '14211234560000'
            )

    def test_approve_clears_needs_skip_trace_outside_skip_pipeline(self, app):
        with app.app_context():
            lead = _seed_lead(
                lead_status='mailing_no_contact_made',
                needs_skip_trace=True,
                recommended_action=None,
            )
            mock_connector = MagicMock()
            mock_connector.connector_name = 'cook_county_gis'
            mock_connector.market = 'cook_county_il'

            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=mock_connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_ingestion_service',
            ) as mock_ingestion, patch(
                'app.services.property_match_review_service.refresh_lead_scoring',
            ):
                svc_instance = MagicMock()
                svc_instance._enrich_with_gis.return_value = {
                    'connector_name': 'cook_county_gis',
                    'match_found': True,
                    'fields_populated': 1,
                    'parcel_pin': None,
                }
                mock_ingestion.return_value = svc_instance

                PropertyMatchReviewService().approve_match(lead.id, actor='tester')

            refreshed = db.session.get(Lead, lead.id)
            assert refreshed.needs_skip_trace is False

    def test_approve_rolls_back_when_gis_misses(self, app):
        with app.app_context():
            lead = _seed_lead(county_assessor_pin=None, needs_skip_trace=False)
            mock_connector = MagicMock()
            mock_connector.connector_name = 'cook_county_gis'
            mock_connector.market = 'cook_county_il'

            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=mock_connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_ingestion_service',
            ) as mock_ingestion:
                svc_instance = MagicMock()

                def _enrich(lead_obj, *_args, **_kwargs):
                    lead_obj.needs_skip_trace = True
                    lead_obj.has_property_match = False
                    return {
                        'connector_name': 'cook_county_gis',
                        'match_found': False,
                        'parcel_pin': None,
                    }

                svc_instance._enrich_with_gis.side_effect = _enrich
                mock_ingestion.return_value = svc_instance

                try:
                    PropertyMatchReviewService().approve_match(lead.id, actor='tester')
                    assert False, 'expected ValueError'
                except ValueError as exc:
                    assert 'could not be applied' in str(exc)

            refreshed = db.session.get(Lead, lead.id)
            assert refreshed.needs_skip_trace is False
            assert refreshed.county_assessor_pin is None
