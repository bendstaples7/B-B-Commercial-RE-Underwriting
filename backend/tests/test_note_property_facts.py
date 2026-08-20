"""Tests for HubSpot note/call → units / commercial / unit-mix parsing."""
from types import SimpleNamespace

from app.services.helpers.note_property_facts import (
    apply_note_property_facts_to_lead,
    parse_note_property_facts,
    parse_unit_mix_from_note_text,
    parse_units_from_note_text,
)

FOSTER_NOTE = (
    '6 unit property 4 units are 2 beds 2 units are 3 bedrooms: '
    'Separate living and dining room 2.25M asking Had a vacancy $2400 '
    'Long term tenants all been there 10-15 years Most are around $2000-2150 '
    '2 units are 1650 Older condition Proof of funds Sam owner name'
)


class TestParseUnitsFromNoteText:
    def test_foster_six_unit_property(self):
        assert parse_units_from_note_text(FOSTER_NOTE) == 6

    def test_hyphenated(self):
        assert parse_units_from_note_text('Nice 12-unit building downtown') == 12

    def test_units_colon_still_works(self):
        assert parse_units_from_note_text('Units: 8 walkup') == 8

    def test_mix_rows_do_not_become_whole_building_units(self):
        text = '4 units are 2 beds and 2 units are 3 beds'
        assert parse_units_from_note_text(text) is None
        facts = parse_note_property_facts(text, source='hubspot_note')
        assert facts is not None
        assert facts['units'] == 6

    def test_status_are_clause_still_counts_building_units(self):
        assert parse_units_from_note_text('6 units are occupied') == 6
        assert parse_units_from_note_text('8 units are available for lease') == 8

    def test_missing(self):
        assert parse_units_from_note_text('Called owner, no answer') is None


class TestParseUnitMix:
    def test_foster_mix(self):
        mix = parse_unit_mix_from_note_text(FOSTER_NOTE)
        assert mix == [
            {'units': 4, 'beds': 2},
            {'units': 2, 'beds': 3},
        ]


class TestApplyToLead:
    def test_foster_4490_shape(self):
        lead = SimpleNamespace(
            units=None,
            bedrooms=6,
            bathrooms=6.0,
            lead_category='residential',
            property_type=None,
            note_property_facts=None,
        )
        updated = apply_note_property_facts_to_lead(
            lead,
            FOSTER_NOTE,
            source='hubspot_note',
            hubspot_activity_id='81143827371',
        )
        assert 'units' in updated
        assert 'lead_category' in updated
        assert 'property_type' in updated
        assert 'note_property_facts' in updated
        assert lead.units == 6
        assert lead.lead_category == 'commercial'
        assert lead.property_type == 'Commercial'
        # Assessor beds/baths untouched
        assert lead.bedrooms == 6
        assert lead.bathrooms == 6.0
        assert lead.note_property_facts['unit_mix'] == [
            {'units': 4, 'beds': 2},
            {'units': 2, 'beds': 3},
        ]

    def test_does_not_overwrite_existing_units(self):
        lead = SimpleNamespace(
            units=3,
            bedrooms=None,
            bathrooms=None,
            lead_category='residential',
            property_type=None,
            note_property_facts=None,
        )
        apply_note_property_facts_to_lead(lead, FOSTER_NOTE, source='hubspot_note')
        assert lead.units == 3
        # Note still says 6 → commercial flip (1B) from note-derived units
        assert lead.lead_category == 'commercial'
        assert lead.note_property_facts['units'] == 6

    def test_commercial_only_from_note_units_not_existing(self):
        """Existing units≥5 with a low note unit count must not flip commercial."""
        lead = SimpleNamespace(
            units=8,
            bedrooms=None,
            bathrooms=None,
            lead_category='residential',
            property_type=None,
            note_property_facts=None,
        )
        apply_note_property_facts_to_lead(
            lead,
            'Spoke with owner — 2 unit duplex',
            source='hubspot_note',
        )
        assert lead.units == 8
        assert lead.lead_category == 'residential'
        assert lead.note_property_facts['units'] == 2

    def test_locked_residential_category_does_not_get_commercial_label(self):
        lead = SimpleNamespace(
            units=None,
            bedrooms=None,
            bathrooms=None,
            lead_category='residential',
            lead_category_locked=True,
            property_type=None,
            note_property_facts=None,
        )
        updated = apply_note_property_facts_to_lead(lead, FOSTER_NOTE, source='hubspot_note')
        assert 'lead_category' not in updated
        assert 'property_type' not in updated
        assert lead.lead_category == 'residential'
        assert lead.property_type is None

    def test_locked_commercial_category_gets_blank_display_label(self):
        lead = SimpleNamespace(
            units=None,
            bedrooms=None,
            bathrooms=None,
            lead_category='commercial',
            lead_category_locked=True,
            property_type=None,
            note_property_facts=None,
        )
        updated = apply_note_property_facts_to_lead(lead, FOSTER_NOTE, source='hubspot_note')
        assert 'lead_category' not in updated
        assert 'property_type' in updated
        assert lead.lead_category == 'commercial'
        assert lead.property_type == 'Commercial'

    def test_heal_gate_and_empty_sentinel(self):
        from app.services.helpers.note_property_facts import (
            EMPTY_NOTE_PROPERTY_FACTS,
            note_property_facts_needs_timeline_heal,
        )
        assert note_property_facts_needs_timeline_heal(None) is True
        assert note_property_facts_needs_timeline_heal({'scanned_empty': True}) is False
        assert note_property_facts_needs_timeline_heal({'units': 6, 'unit_mix': []}) is False
        assert EMPTY_NOTE_PROPERTY_FACTS['scanned_empty'] is True

    def test_idempotent_same_facts(self):
        lead = SimpleNamespace(
            units=None,
            bedrooms=None,
            bathrooms=None,
            lead_category='residential',
            property_type=None,
            note_property_facts=None,
        )
        first = apply_note_property_facts_to_lead(lead, FOSTER_NOTE, source='hubspot_note')
        second = apply_note_property_facts_to_lead(lead, FOSTER_NOTE, source='hubspot_note')
        assert 'note_property_facts' in first
        assert 'note_property_facts' not in second

    def test_parse_bundle(self):
        facts = parse_note_property_facts(FOSTER_NOTE, source='hubspot_note')
        assert facts is not None
        assert facts['units'] == 6
        assert len(facts['unit_mix']) == 2

    def test_timeline_heal_applies_one_chosen_fact_source(self, monkeypatch):
        from app.models import lead_timeline_entry as timeline_entry_module
        from app.services.helpers.note_property_facts import apply_note_facts_from_timeline

        class FakeColumn:
            def __eq__(self, _other):
                return True

            def is_(self, _other):
                return True

            def in_(self, _other):
                return True

            def desc(self):
                return True

        class FakeQuery:
            def filter(self, *_args):
                return self

            def order_by(self, *_args):
                return self

            def all(self):
                return [
                    SimpleNamespace(
                        event_type='hubspot_note',
                        event_metadata={'body': '6 unit property'},
                        summary='',
                        hubspot_activity_id='newer',
                    ),
                    SimpleNamespace(
                        event_type='hubspot_note',
                        event_metadata={
                            'body': '12 unit property 8 units are 1 beds and 4 units are 2 beds',
                        },
                        summary='',
                        hubspot_activity_id='older',
                    ),
                ]

        class FakeLeadTimelineEntry:
            lead_id = FakeColumn()
            is_deleted = FakeColumn()
            event_type = FakeColumn()
            occurred_at = FakeColumn()
            query = FakeQuery()

        lead = SimpleNamespace(
            id=4490,
            units=None,
            bedrooms=None,
            bathrooms=None,
            lead_category='residential',
            property_type=None,
            note_property_facts=None,
        )
        monkeypatch.setattr(
            timeline_entry_module,
            'LeadTimelineEntry',
            FakeLeadTimelineEntry,
        )

        updated = apply_note_facts_from_timeline(lead)

        assert 'units' in updated
        assert lead.units == 12
        assert lead.note_property_facts['units'] == 12
        assert lead.note_property_facts['hubspot_activity_id'] == 'older'


class TestRicherFactsPreferDetailAndRecency:
    """Main (#154) richer-mix / source_occurred_at tie-breakers."""

    def test_richer_unit_mix_with_baths_replaces_same_row_count(self):
        lead = SimpleNamespace(
            units=None,
            lead_category='residential',
            property_type=None,
            note_property_facts=None,
        )

        apply_note_property_facts_to_lead(
            lead,
            '6 unit property. 4 units are 2 beds. 2 units are 3 beds.',
            hubspot_activity_id='note-1',
        )
        apply_note_property_facts_to_lead(
            lead,
            '6 unit property. 4 units are 2 beds and 1 baths. 2 units are 3 beds and 2 baths.',
            hubspot_activity_id='note-2',
        )

        assert lead.note_property_facts['hubspot_activity_id'] == 'note-2'
        assert lead.note_property_facts['unit_mix'] == [
            {'units': 4, 'beds': 2, 'baths': 1},
            {'units': 2, 'beds': 3, 'baths': 2},
        ]

    def test_newer_source_time_replaces_equal_shape_unit_mix(self):
        lead = SimpleNamespace(
            units=None,
            lead_category='residential',
            property_type=None,
            note_property_facts=None,
        )

        apply_note_property_facts_to_lead(
            lead,
            '6 unit property. 4 units are 2 beds and 1 baths. 2 units are 3 beds and 2 baths.',
            hubspot_activity_id='note-older',
            source_occurred_at='2026-01-01T00:00:00+00:00',
        )
        apply_note_property_facts_to_lead(
            lead,
            '6 unit property. 4 units are 1 beds and 1 baths. 2 units are 4 beds and 2 baths.',
            hubspot_activity_id='note-newer',
            source_occurred_at='2026-01-02T00:00:00+00:00',
        )

        assert lead.note_property_facts['hubspot_activity_id'] == 'note-newer'
        assert lead.note_property_facts['unit_mix'] == [
            {'units': 4, 'beds': 1, 'baths': 1},
            {'units': 2, 'beds': 4, 'baths': 2},
        ]

    def test_locked_category_stays_residential_when_note_says_six_units(self):
        lead = SimpleNamespace(
            units=None,
            bedrooms=None,
            bathrooms=None,
            lead_category='residential',
            lead_category_locked=True,
            property_type=None,
            note_property_facts=None,
        )
        apply_note_property_facts_to_lead(lead, FOSTER_NOTE, source='hubspot_note')
        assert lead.units == 6
        assert lead.lead_category == 'residential'
        assert lead.property_type is None
