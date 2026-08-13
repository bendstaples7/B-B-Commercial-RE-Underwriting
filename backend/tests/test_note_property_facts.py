"""Tests for note-derived property facts helpers."""
from __future__ import annotations

from app.services.helpers.note_property_facts import apply_note_property_facts_to_lead


class _Lead:
    units = None
    lead_category = 'residential'
    property_type = None
    note_property_facts = None


def test_richer_unit_mix_with_baths_replaces_same_row_count():
    lead = _Lead()

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


def test_newer_source_time_replaces_equal_shape_unit_mix():
    lead = _Lead()

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
