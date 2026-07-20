"""Tests for property address completeness."""
from datetime import date
from unittest.mock import patch

from app.models.lead import Lead
from app.services.property_address_service import (
    complete_property_address,
    complete_property_address_fields,
    heal_incomplete_property_addresses,
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


class TestHealIncompletePropertyAddresses:
    def test_heals_street_only_batch_and_advances_cursor(self, app):
        with app.app_context():
            incomplete = _make_lead(
                app,
                property_street='1239 N Hoyne',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            complete = _make_lead(
                app,
                property_street='500 W Madison St',
                property_city='Chicago',
                property_state='IL',
                property_zip='60661',
            )
            with patch(
                'app.services.property_address_service._heal_incomplete_cursor',
                return_value=0,
            ), patch(
                'app.services.property_address_service._set_heal_incomplete_cursor',
            ) as set_cursor, patch(
                'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            ) as mock_lookup:
                mock_lookup.return_value = [{
                    'pin': '17061270060000',
                    'property_street': '1239 N HOYNE AVE',
                    'property_city': 'Chicago',
                    'property_state': 'IL',
                    'property_zip': '60622',
                }]
                result = heal_incomplete_property_addresses(
                    last_id=0,
                    limit=50,
                    persist_cursor=True,
                    commit=True,
                    actor='test',
                )
            assert incomplete.id in result['lead_ids']
            assert complete.id not in result['lead_ids']
            assert result['completed'] >= 1
            assert is_property_address_complete(lead=incomplete)
            set_cursor.assert_called_once_with(incomplete.id)

    def test_dry_run_does_not_mutate(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                property_street='1239 N Hoyne Ave Chicago IL 60622',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            result = heal_incomplete_property_addresses(
                lead_id=lead.id,
                dry_run=True,
                persist_cursor=False,
                commit=False,
                try_gis=False,
            )
            assert result['processed'] == 1
            assert result['completed'] == 1
            assert lead.property_city is None

    def test_wraps_cursor_when_no_candidates_after_cursor(self, app):
        with app.app_context():
            with patch(
                'app.services.property_address_service._set_heal_incomplete_cursor',
            ) as set_cursor:
                result = heal_incomplete_property_addresses(
                    last_id=999999,
                    limit=10,
                    persist_cursor=True,
                    commit=False,
                    dry_run=True,
                    try_gis=False,
                )
            assert result['wrapped'] is True
            assert result['last_id'] == 0
            set_cursor.assert_called_with(0)

    def test_heal_includes_whitespace_only_address_parts(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                property_street='1239 N Hoyne',
                property_city='   ',
                property_state=' ',
                property_zip='',
            )
            with patch(
                'app.services.property_address_service._set_heal_incomplete_cursor',
            ), patch(
                'app.services.gis.cook_county_gis_connector.lookup_all_pins_at_address',
            ) as mock_lookup:
                mock_lookup.return_value = [{
                    'pin': '17061270060000',
                    'property_street': '1239 N HOYNE AVE',
                    'property_city': 'Chicago',
                    'property_state': 'IL',
                    'property_zip': '60622',
                }]
                result = heal_incomplete_property_addresses(
                    last_id=0,
                    limit=10,
                    persist_cursor=True,
                    commit=True,
                    actor='test',
                )
            assert lead.id in result['lead_ids']
            assert is_property_address_complete(lead=lead)

    def test_heal_does_not_advance_cursor_on_hard_error(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                property_street='999 Error Only St',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            with patch(
                'app.services.property_address_service._heal_incomplete_cursor',
                return_value=0,
            ), patch(
                'app.services.property_address_service._set_heal_incomplete_cursor',
            ) as set_cursor, patch(
                'app.services.property_address_service.complete_property_address',
                side_effect=RuntimeError('gis down'),
            ):
                result = heal_incomplete_property_addresses(
                    last_id=0,
                    limit=10,
                    persist_cursor=True,
                    commit=True,
                    try_gis=True,
                    actor='test',
                )
            assert lead.id in result['lead_ids']
            assert result['errors'] >= 1
            assert result['last_id'] == 0
            set_cursor.assert_called_with(0)

    def test_heal_stops_on_hard_error_before_advancing_past_failed_lead(self, app):
        with app.app_context():
            first = _make_lead(
                app,
                property_street='100 First St',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            failed = _make_lead(
                app,
                property_street='200 Failed St',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            later = _make_lead(
                app,
                property_street='300 Later St',
                property_city=None,
                property_state=None,
                property_zip=None,
            )

            def complete_or_fail(lead, **_kwargs):
                if lead.id == failed.id:
                    raise RuntimeError('gis down')
                lead.property_city = 'Chicago'
                lead.property_state = 'IL'
                lead.property_zip = '60601'
                return {'complete': True}

            with patch(
                'app.services.property_address_service._set_heal_incomplete_cursor',
            ) as set_cursor, patch(
                'app.services.property_address_service.complete_property_address',
                side_effect=complete_or_fail,
            ):
                result = heal_incomplete_property_addresses(
                    last_id=0,
                    limit=10,
                    persist_cursor=True,
                    commit=True,
                    try_gis=True,
                    actor='test',
                )

            assert result['lead_ids'] == [first.id, failed.id]
            assert result['errors'] == 1
            assert result['last_id'] == first.id
            set_cursor.assert_called_with(first.id)
            assert later.property_city is None

    def test_dry_run_includes_before_after_previews(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                property_street='1239 N Hoyne Ave Chicago IL 60622',
                property_city=None,
                property_state=None,
                property_zip=None,
            )
            result = heal_incomplete_property_addresses(
                lead_id=lead.id,
                dry_run=True,
                persist_cursor=False,
                commit=False,
                try_gis=False,
            )
            assert result['previews']
            preview = result['previews'][0]
            assert preview['lead_id'] == lead.id
            assert preview['complete'] is True
            assert preview['after']['property_city'] == 'Chicago'
            assert lead.property_city is None
