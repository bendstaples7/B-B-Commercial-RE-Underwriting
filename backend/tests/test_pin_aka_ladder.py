"""Tests for Cook PIN range ladder, spatial fallback, and assessor AKA."""
from unittest.mock import MagicMock, patch

from app import db
from app.models import Lead
from app.services.gis.cook_county_gis_connector import (
    _house_number_range_variants,
    _house_number_step_variants,
    _normalise_address,
)
from app.services.property_match_review_service import (
    PropertyMatchReviewService,
    _rank_candidates_by_house_proximity,
    _unique_near_miss_row,
    assessor_street_differs_from_lead,
)


def test_house_number_range_includes_odd_intermediates():
    normalised = _normalise_address('3715-3721 N Leavitt St')
    variants = _house_number_range_variants(normalised)
    assert '3715 N LEAVITT ST' in variants
    assert '3721 N LEAVITT ST' in variants
    assert '3717 N LEAVITT ST' in variants
    assert '3719 N LEAVITT ST' in variants
    # Start/end first, then intermediates
    assert variants[0] == '3715 N LEAVITT ST'
    assert variants[1] == '3721 N LEAVITT ST'


def test_normalise_strips_concatenated_city_state_zip():
    assert _normalise_address(
        '3715-3721 N Leavitt St Chicago IL 60618'
    ) == '3715-3721 N LEAVITT ST'


def test_normalise_keeps_through_first_street_suffix():
    # Locality itself contains a suffix token (ST CHARLES) — do not greedily
    # truncate after the last ST.
    assert _normalise_address(
        '7 W Madison St St Charles IL 60174'
    ) == '7 W MADISON ST'


def test_house_number_range_even_step():
    variants = _house_number_range_variants('100-108 W MAIN ST')
    assert '100 W MAIN ST' in variants
    assert '108 W MAIN ST' in variants
    assert '102 W MAIN ST' in variants
    assert '104 W MAIN ST' in variants


def test_assessor_street_differs_corner_vs_range():
    assert assessor_street_differs_from_lead(
        '3715-3721 N Leavitt St',
        '2155 W BRADLEY PL',
    )
    assert not assessor_street_differs_from_lead(
        '3715-3721 N Leavitt St',
        '3715 N LEAVITT ST',
    )
    assert not assessor_street_differs_from_lead(
        '3715 N Leavitt St',
        '3715 N LEAVITT STREET',
    )


def _seed_cook_lead(**overrides) -> Lead:
    lead = Lead(
        property_street='3715-3721 N Leavitt St',
        property_city='Chicago',
        property_state='IL',
        property_zip='60618',
        has_property_match=False,
        lead_status='mailing_no_contact_made',
        owner_user_id='test-user',
    )
    for key, value in overrides.items():
        setattr(lead, key, value)
    db.session.add(lead)
    db.session.commit()
    return lead


def test_house_number_step_variants_odd_even_side():
    variants = _house_number_step_variants('1233 W FOSTER AVE')
    assert variants[0] == '1235 W FOSTER AVE'
    assert variants[1] == '1231 W FOSTER AVE'
    assert '1237 W FOSTER AVE' in variants
    assert '1239 W FOSTER AVE' in variants
    assert '1227 W FOSTER AVE' in variants


def test_unique_near_miss_picks_single_step_up():
    lead = '1233 W Foster Ave'
    rows = [
        {'pin': 'a', 'property_street': '1227 W FOSTER AVE'},
        {'pin': 'b', 'property_street': '1235 W FOSTER AVE'},
        {'pin': 'c', 'property_street': '1229 W FOSTER AVE'},
    ]
    hit = _unique_near_miss_row(lead, rows)
    assert hit is not None
    assert hit['pin'] == 'b'
    ranked = _rank_candidates_by_house_proximity(lead, rows)
    assert ranked[0]['pin'] == 'b'


def test_unique_near_miss_rejects_condo_stack_at_near_address():
    lead = '1233 W Foster Ave'
    rows = [
        {'pin': 'a', 'property_street': '1235 W FOSTER AVE'},
        {'pin': 'b', 'property_street': '1235 W FOSTER AVE'},
    ]
    assert _unique_near_miss_row(lead, rows) is None


class TestPreviewSpatialAndPin:
    def test_preview_spatial_fallback_returns_candidates(self, app):
        with app.app_context():
            lead = _seed_cook_lead()
            mock_connector = MagicMock()
            mock_connector.connector_name = 'cook_county_gis'
            mock_connector.market = 'cook_county_il'

            spatial = [{
                'pin': '14-19-122-001-0000',
                'property_street': '2155 W BRADLEY PL',
                'property_city': 'CHICAGO',
                'property_state': 'IL',
                'property_zip': '60618',
                'source': 'cook_parcel_spatial',
            }]
            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=mock_connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pin_rows_at_address',
                return_value=[],
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pin_rows_via_house_steps',
                return_value=[],
            ), patch(
                'app.services.gis.cook_county_parcel_spatial.lookup_nearby_parcel_candidates',
                return_value=spatial,
            ):
                preview = PropertyMatchReviewService().preview_match(lead.id)

            assert preview['found'] is True
            assert preview['require_explicit_apply'] is True
            assert preview['candidates'][0]['pin'] == '14-19-122-001-0000'
            assert 'BRADLEY' in (preview['candidates'][0]['property_street'] or '')
            assert preview.get('tax_situs_street')
            assert 'BRADLEY' in (preview.get('tax_situs_street') or '').upper()

    def test_preview_unique_same_situs_among_neighbors_auto_applies(self, app):
        """One exact lead-street PIN among spatial neighbors is unambiguous."""
        with app.app_context():
            lead = _seed_cook_lead(property_street='1233 W Foster Ave')
            mock_connector = MagicMock()
            mock_connector.connector_name = 'cook_county_gis'
            mock_connector.market = 'cook_county_il'

            spatial = [
                {
                    'pin': '14-08-302-030-0000',
                    'property_street': '1223 W FOSTER AVE',
                    'property_city': 'CHICAGO',
                    'property_state': 'IL',
                    'property_zip': '60640',
                    'source': 'cook_parcel_spatial',
                },
                {
                    'pin': '14-08-302-028-0000',
                    'property_street': '1233 W FOSTER AVE',
                    'property_city': 'CHICAGO',
                    'property_state': 'IL',
                    'property_zip': '60640',
                    'source': 'cook_parcel_spatial',
                },
                {
                    'pin': '14-08-302-070-1011',
                    'property_street': '1227 W FOSTER AVE',
                    'property_city': 'CHICAGO',
                    'property_state': 'IL',
                    'property_zip': '60640',
                    'source': 'cook_parcel_spatial',
                },
            ]
            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=mock_connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pin_rows_at_address',
                return_value=[],
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pin_rows_via_house_steps',
                return_value=[],
            ), patch(
                'app.services.gis.cook_county_parcel_spatial.lookup_nearby_parcel_candidates',
                return_value=spatial,
            ):
                preview = PropertyMatchReviewService().preview_match(lead.id)

            assert preview['found'] is True
            assert preview['require_explicit_apply'] is False
            assert preview['pin_count'] == 1
            assert preview['pin'] == '14-08-302-028-0000'
            assert preview['candidates'] == [spatial[1]]

    def test_preview_house_step_ladder_finds_assessor_typo(self, app):
        """Exact miss + ±2 Socrata hit auto-applies with assessor AKA."""
        with app.app_context():
            lead = _seed_cook_lead(
                property_street='1233 W Foster Ave',
                property_city='Chicago',
                property_state='IL',
                property_zip='60640',
            )
            mock_connector = MagicMock()
            mock_connector.connector_name = 'cook_county_gis'
            mock_connector.market = 'cook_county_il'

            step_hit = [{
                'pin': '14-08-302-028-0000',
                'property_street': '1235 W FOSTER AVE',
                'property_city': 'CHICAGO',
                'property_state': 'IL',
                'property_zip': '60640',
                'source': 'cook_address_step',
            }]

            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=mock_connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pin_rows_at_address',
                return_value=[],
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pin_rows_via_house_steps',
                return_value=step_hit,
            ), patch(
                'app.services.gis.cook_county_parcel_spatial.lookup_nearby_parcel_candidates',
                return_value=[],
            ):
                preview = PropertyMatchReviewService().preview_match(lead.id)

            assert preview['found'] is True
            assert preview['require_explicit_apply'] is True
            assert preview['pin'] == '14-08-302-028-0000'
            assert preview['assessor_aka']['property_street'] == '1235 W FOSTER AVE'
            assert '1235' in (preview.get('message') or '')

    def test_preview_one_sided_spatial_merges_step_ladder(self, app):
        """All-lower spatial neighbors still pick unique +2 assessor hit."""
        with app.app_context():
            lead = _seed_cook_lead(
                property_street='1233 W Foster Ave',
                property_city='Chicago',
                property_state='IL',
                property_zip='60640',
            )
            mock_connector = MagicMock()
            mock_connector.connector_name = 'cook_county_gis'
            mock_connector.market = 'cook_county_il'

            spatial_lower = [
                {
                    'pin': '14-08-302-030-0000',
                    'property_street': '1223 W FOSTER AVE',
                    'property_city': 'CHICAGO',
                    'property_state': 'IL',
                    'property_zip': '60640',
                    'source': 'cook_parcel_spatial',
                },
                {
                    'pin': '14-08-302-070-1011',
                    'property_street': '1227 W FOSTER AVE',
                    'property_city': 'CHICAGO',
                    'property_state': 'IL',
                    'property_zip': '60640',
                    'source': 'cook_parcel_spatial',
                },
            ]
            step_hit = [{
                'pin': '14-08-302-028-0000',
                'property_street': '1235 W FOSTER AVE',
                'property_city': 'CHICAGO',
                'property_state': 'IL',
                'property_zip': '60640',
                'source': 'cook_address_step',
            }]
            ladder_calls: list[str] = []

            def ladder_side_effect(address: str):
                ladder_calls.append(address)
                # First pass (exact miss) empty so spatial runs; enrich re-probes.
                if len(ladder_calls) == 1:
                    return []
                return step_hit

            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=mock_connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pin_rows_at_address',
                return_value=[],
            ), patch.object(
                PropertyMatchReviewService,
                '_cook_pin_rows_via_house_steps',
                side_effect=ladder_side_effect,
            ), patch(
                'app.services.gis.cook_county_parcel_spatial.lookup_nearby_parcel_candidates',
                return_value=spatial_lower,
            ):
                preview = PropertyMatchReviewService().preview_match(lead.id)

            assert len(ladder_calls) >= 2
            assert preview['require_explicit_apply'] is True
            assert preview['pin'] == '14-08-302-028-0000'
            assert preview['candidates'][0]['property_street'] == '1235 W FOSTER AVE'

    def test_preview_pin_hint_sets_assessor_aka(self, app):
        with app.app_context():
            lead = _seed_cook_lead()
            mock_connector = MagicMock()
            mock_connector.connector_name = 'cook_county_gis'
            mock_connector.market = 'cook_county_il'
            mock_connector.lookup_address_by_pin.return_value = {
                'property_street': '2155 W BRADLEY PL',
                'property_city': 'CHICAGO',
                'property_state': 'IL',
                'property_zip': '60618',
            }
            mock_parcel = MagicMock()
            mock_parcel.property_type = 'commercial'
            mock_parcel.property_street = '2155 W BRADLEY PL'
            mock_parcel.property_city = 'CHICAGO'
            mock_parcel.property_state = 'IL'
            mock_parcel.property_zip = '60618'
            mock_connector.lookup_by_pin.return_value = mock_parcel

            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=mock_connector,
            ):
                preview = PropertyMatchReviewService().preview_match(
                    lead.id, pin='14-19-122-001-0000',
                )

            assert preview['found'] is True
            assert preview['require_explicit_apply'] is True
            assert preview['assessor_aka']['property_street'] == '2155 W BRADLEY PL'
            assert preview['recommended_address']['property_street'] == lead.property_street


class TestApproveAka:
    def test_approve_stores_aka_keeps_marketing_street(self, app):
        with app.app_context():
            lead = _seed_cook_lead()
            mock_connector = MagicMock()
            mock_connector.connector_name = 'cook_county_gis'
            mock_connector.market = 'cook_county_il'
            mock_connector.lookup_address_by_pin.return_value = {
                'property_street': '2155 W BRADLEY PL',
                'property_city': 'CHICAGO',
                'property_state': 'IL',
                'property_zip': '60618',
            }

            with patch(
                'app.services.property_match_review_service.connector_for_lead',
                return_value=mock_connector,
            ), patch.object(
                PropertyMatchReviewService,
                '_ingestion_service',
            ) as mock_ingestion, patch(
                'app.services.property_match_review_service.refresh_lead_scoring',
            ), patch(
                'app.services.building_ownership_backfill.dispatch_building_ownership_analysis',
            ):
                svc_instance = MagicMock()
                svc_instance._enrich_with_gis.return_value = {
                    'connector_name': 'cook_county_gis',
                    'match_found': True,
                    'fields_populated': 1,
                    'parcel_pin': '14-19-122-001-0000',
                }
                mock_ingestion.return_value = svc_instance

                result = PropertyMatchReviewService().approve_match(
                    lead.id, actor='tester', pin='14191220010000',
                )

            refreshed = db.session.get(Lead, lead.id)
            assert refreshed.property_street == '3715-3721 N Leavitt St'
            assert refreshed.assessor_aka_street == '2155 W Bradley Pl'
            assert refreshed.county_assessor_pin == '14-19-122-001-0000'
            assert result['assessor_aka_street'] == '2155 W Bradley Pl'
