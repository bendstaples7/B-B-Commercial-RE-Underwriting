"""Tests for AKA/spatial PIN collection into building ownership condo check."""
from unittest.mock import MagicMock, patch

from app import db
from app.models import Lead
from app.services.building_ownership_service import BuildingOwnershipService
from app.services.property_match_review_service import tax_situs_cluster_meta


def test_tax_situs_cluster_meta_dominant_corner_street():
    meta = tax_situs_cluster_meta(
        '3715-3721 N Leavitt St',
        [
            {'pin': '1', 'property_street': '2155 W BRADLEY PL'},
            {'pin': '2', 'property_street': '2153 W BRADLEY PL'},
            {'pin': '3', 'property_street': '2151 W BRADLEY PL'},
            {'pin': '4', 'property_street': '3740 N LEAVITT ST'},
        ],
    )
    assert meta['tax_situs_street']
    assert 'BRADLEY' in meta['tax_situs_street'].upper()
    assert meta['tax_situs_pin_count'] == 3
    assert meta['assessor_aka']['property_street']


def _seed_lead(**overrides) -> Lead:
    lead = Lead(
        property_street='3715-3721 N Leavitt St',
        property_city='Chicago',
        property_state='IL',
        property_zip='60618',
        lead_category='commercial',
        units=12,
        has_property_match=False,
        lead_status='mailing_no_contact_made',
        owner_user_id='test-user',
        owner_first_name='Test',
        owner_last_name='Owner',
    )
    for key, value in overrides.items():
        setattr(lead, key, value)
    db.session.add(lead)
    db.session.commit()
    return lead


class TestCollectAssessorPinsAka:
    def test_collect_unions_aka_street_pins(self, app):
        with app.app_context():
            lead = _seed_lead(assessor_aka_street='2155 W Bradley Pl')
            mock_connector = MagicMock()
            mock_connector.market = 'cook_county_il'
            mock_connector.lookup_address_by_pin.return_value = None

            def pins_for(street):
                if 'LEAVITT' in street.upper():
                    return []
                if 'BRADLEY' in street.upper():
                    return [
                        {'pin': '14-19-122-001-0000', 'property_street': '2155 W BRADLEY PL'},
                        {'pin': '14-19-122-002-0000', 'property_street': '2153 W BRADLEY PL'},
                        {'pin': '14-19-122-003-0000', 'property_street': '2151 W BRADLEY PL'},
                        {'pin': '14-19-122-004-0000', 'property_street': '2149 W BRADLEY PL'},
                    ]
                return []

            with patch(
                'app.services.building_ownership_service.connector_for_lead',
                return_value=mock_connector,
            ), patch(
                'app.services.building_ownership_service.lookup_all_pins_at_address',
                side_effect=pins_for,
            ), patch(
                'app.services.gis.cook_county_parcel_spatial.lookup_nearby_parcel_candidates',
                return_value=[],
            ):
                rows = BuildingOwnershipService()._collect_assessor_pins(lead)

            pins = {r['pin'] for r in rows}
            assert '14-19-122-001-0000' in pins
            assert len(pins) >= 4

    def test_analyze_with_candidate_pins_avoids_rule_7(self, app):
        with app.app_context():
            lead = _seed_lead()
            mock_connector = MagicMock()
            mock_connector.market = 'cook_county_il'
            mock_connector.lookup_address_by_pin.return_value = {
                'property_street': '2155 W BRADLEY PL',
            }

            def pins_for(street):
                if 'BRADLEY' in (street or '').upper():
                    return [
                        {'pin': '14-19-122-001-0000', 'property_street': '2155 W BRADLEY PL'},
                        {'pin': '14-19-122-002-0000', 'property_street': '2153 W BRADLEY PL'},
                        {'pin': '14-19-122-003-0000', 'property_street': '2151 W BRADLEY PL'},
                        {'pin': '14-19-122-004-0000', 'property_street': '2149 W BRADLEY PL'},
                    ]
                return []

            with patch(
                'app.services.building_ownership_service.connector_for_lead',
                return_value=mock_connector,
            ), patch(
                'app.services.building_ownership_service.lookup_all_pins_at_address',
                side_effect=pins_for,
            ), patch(
                'app.services.gis.cook_county_parcel_spatial.lookup_nearby_parcel_candidates',
                return_value=[],
            ), patch(
                'app.services.building_ownership_service.refresh_lead_scoring',
            ), patch(
                'app.services.building_ownership_backfill.lead_needs_building_ownership_analysis',
                return_value=True,
            ):
                result = BuildingOwnershipService().analyze_lead(
                    lead.id,
                    force=True,
                    tax_situs_street='2155 W Bradley Pl',
                    candidate_pins=[
                        '14-19-122-001-0000',
                        '14-19-122-002-0000',
                        '14-19-122-003-0000',
                        '14-19-122-004-0000',
                    ],
                )

            rules = result['classification']['triggered_rules']
            assert 'rule_7_missing_data' not in rules
            refreshed = db.session.get(Lead, lead.id)
            assert refreshed.assessor_aka_street
            assert 'Bradley' in refreshed.assessor_aka_street
            assert result['classification']['condo_risk_status'] in (
                'partial_condo_possible',
                'likely_condo',
                'needs_review',
            )
