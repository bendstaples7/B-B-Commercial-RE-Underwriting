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


class TestPinPreviewAndBatchResolve:
    def test_preview_reports_multiple_cook_pins_without_selecting_one(self, app):
        with app.app_context():
            lead = _seed_lead()
            connector = MagicMock()
            connector.market = 'cook_county_il'
            connector.connector_name = 'cook_county_gis'

            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pins_at_address',
                return_value=['14-21-123-456-0000', '14-21-123-456-0001'],
            ):
                preview = PropertyMatchReviewService().preview_match(lead.id)

            assert preview['found'] is True
            assert preview['pin'] is None
            assert preview['pin_count'] == 2
            assert preview['pins'] == ['14-21-123-456-0000', '14-21-123-456-0001']

    def test_batch_resolves_only_unique_cook_pin(self, app):
        with app.app_context():
            unique = _seed_lead(property_street='1 Unique St')
            ambiguous = _seed_lead(property_street='2 Ambiguous St')
            connector = MagicMock()
            connector.market = 'cook_county_il'

            def pins_for_address(address):
                if address == '1 Unique St':
                    return ['14-21-123-456-0000']
                return ['14-21-123-456-0001', '14-21-123-456-0002']

            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pins_at_address',
                side_effect=pins_for_address,
            ), patch.object(
                PropertyMatchReviewService,
                'approve_match',
                return_value={},
            ) as approve:
                result = PropertyMatchReviewService().resolve_unambiguous_pins_batch(limit=10)

            assert result['resolved'] == 1
            assert result['skipped_ambiguous'] == 1
            assert result['lead_ids'] == [unique.id]
            approve.assert_called_once_with(
                unique.id,
                actor='property_match.resolve_unambiguous_pins',
                pin='14-21-123-456-0000',
            )
            assert ambiguous.id not in result['lead_ids']

    def test_cursor_advances_past_unresolvable_head_row(self, app):
        """An ambiguous head row must not monopolize a small batch forever."""
        with app.app_context():
            ambiguous = _seed_lead(property_street='2 Ambiguous St')
            unique = _seed_lead(property_street='1 Unique St')
            connector = MagicMock()
            connector.market = 'cook_county_il'

            def pins_for_address(address):
                if address == '1 Unique St':
                    return ['14-21-123-456-0000']
                return ['14-21-123-456-0001', '14-21-123-456-0002']

            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pins_at_address',
                side_effect=pins_for_address,
            ), patch.object(
                PropertyMatchReviewService,
                'approve_match',
                return_value={},
            ):
                svc = PropertyMatchReviewService()
                # First run: limit 1 only sees the ambiguous head, resolves
                # nothing, but the cursor advances past it.
                first = svc.resolve_unambiguous_pins_batch(
                    limit=1, last_id=0, persist_cursor=False,
                )
                assert first['resolved'] == 0
                assert first['skipped_ambiguous'] == 1
                assert first['last_id'] == ambiguous.id

                # Second run resumes past the head and reaches the unique lead.
                second = svc.resolve_unambiguous_pins_batch(
                    limit=1, last_id=first['last_id'], persist_cursor=False,
                )
                assert second['resolved'] == 1
                assert second['lead_ids'] == [unique.id]

    def test_short_page_wraps_cursor_to_zero(self, app):
        """Reaching the end of the table resets the cursor for the next pass."""
        with app.app_context():
            _seed_lead(property_street='1 Unique St', county_assessor_pin=None)
            connector = MagicMock()
            connector.market = 'cook_county_il'

            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pins_at_address',
                return_value=['14-21-123-456-0000'],
            ), patch.object(
                PropertyMatchReviewService,
                'approve_match',
                return_value={},
            ):
                result = PropertyMatchReviewService().resolve_unambiguous_pins_batch(
                    limit=100, last_id=0, persist_cursor=False,
                )
            # Fewer rows than the batch size means the pass ended → wrap to 0.
            assert result['last_id'] == 0
