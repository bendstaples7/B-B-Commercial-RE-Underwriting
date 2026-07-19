"""Tests for property address completeness."""
from datetime import date
from unittest.mock import patch

from app.models.lead import Lead
from app.services.property_address_service import (
    complete_property_address,
    complete_property_address_fields,
    is_property_address_complete,
)


def _make_lead(app, **kwargs):
    from app import db

    defaults = dict(
        property_street='1239 N Hoyne',
        lead_status='mailing_no_contact_made',
        has_property_match=True,
        review_required=False,
    )
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.commit()
    return lead


class TestCompletePropertyAddressFields:
    def test_already_complete_is_noop(self):
        result = complete_property_address_fields(
            '1239 N Hoyne Ave',
            'Chicago',
            'IL',
            '60622',
            try_gis=False,
        )
        assert result['complete'] is True
        assert result['property_city'] == 'Chicago'
        assert result['sources'] == []

    def test_glued_one_liner_parse(self):
        result = complete_property_address_fields(
            '1239 N Hoyne Ave Chicago IL 60622',
            try_gis=False,
        )
        assert result['complete'] is True
        assert result['property_city'] == 'Chicago'
        assert result['property_state'] == 'IL'
        assert result['property_zip'] == '60622'
        assert 'parse_embedded' in result['sources'] or 'parse_places' in result['sources']

    def test_street_only_hoyne_gis_fill(self):
        with patch(
            'app.services.property_address_service.lookup_all_pins_at_address',
            create=True,
        ):
            pass
        with patch(
            'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
        ) as mock_lookup:
            mock_lookup.return_value = [{
                'pin': '17061270060000',
                'property_street': '1239 N HOYNE AVE',
                'property_city': 'CHICAGO',
                'property_state': 'IL',
                'property_zip': '60622-3009',
            }]
            result = complete_property_address_fields(
                '1239 N Hoyne',
                try_gis=True,
            )
        assert result['complete'] is True
        assert result['property_city'] == 'CHICAGO'
        assert result['property_state'] == 'IL'
        assert result['property_zip'] == '60622'
        assert result['property_street'] == '1239 N HOYNE AVE'
        assert 'gis' in result['sources']


class TestCompletePropertyAddressLead:
    def test_fills_lead_and_clears_review_when_complete(self, app):
        with app.app_context():
            from datetime import datetime, timezone

            from app import db
            from app.models.lead_timeline_entry import LeadTimelineEntry

            lead = _make_lead(app, review_required=True)
            # Review was set by the address completer (not HubSpot / other causes).
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='property_address_incomplete',
                occurred_at=datetime.now(timezone.utc),
                source='system',
                actor='test',
                summary='Property address incomplete',
                event_metadata={'reason': 'incomplete_address'},
            ))
            db.session.commit()
            with patch(
                'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            ) as mock_lookup:
                mock_lookup.return_value = [{
                    'pin': '17061270060000',
                    'property_street': '1239 N HOYNE AVE',
                    'property_city': 'Chicago',
                    'property_state': 'IL',
                    'property_zip': '60622',
                }]
                result = complete_property_address(
                    lead,
                    actor='test',
                    commit=True,
                )
            assert result['complete'] is True
            assert lead.property_city == 'Chicago'
            assert lead.property_zip == '60622'
            assert lead.review_required is False
            assert is_property_address_complete(lead=lead)

    def test_flags_review_when_still_incomplete(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                property_street='Unknown Dirt Road',
                review_required=False,
            )
            with patch(
                'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
                return_value=[],
            ), patch(
                'app.services.gis.cook_county_gis_connector.CookCountyGISConnector.lookup_by_address',
                return_value=None,
            ):
                result = complete_property_address(
                    lead,
                    actor='test',
                    commit=True,
                    try_gis=True,
                )
            assert result['complete'] is False
            assert result['flagged_incomplete'] is True
            assert lead.review_required is True
