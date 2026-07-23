"""Tests for mailer_history normalization (legacy + OLC shapes)."""
from app.services.helpers.mailer_history import (
    mailer_history_summary,
    normalize_mailer_history,
    parse_mailer_sent_at,
)


def test_legacy_string_with_trailing_date():
    rows = normalize_mailer_history('Boyfriend, OLM, Blue,  6/21/2024')
    assert len(rows) == 1
    assert rows[0]['label'] == 'Boyfriend, OLM, Blue'
    assert rows[0]['sent_at'] == '6/21/2024'
    assert rows[0]['source'] == 'imported'


def test_olc_dict_entries():
    rows = normalize_mailer_history([
        {
            'sent_at': '2024-06-01T00:00:00Z',
            'template_name': 'Blue Mosaic',
            'creative': 'OLM',
            'campaign_id': 12,
            'olc_order_id': '99',
        },
    ])
    assert len(rows) == 1
    assert rows[0]['source'] == 'olc'
    assert 'Blue Mosaic' in rows[0]['label']
    assert rows[0]['campaign_id'] == 12


def test_cancelled_and_feedback():
    rows = normalize_mailer_history([
        {'address_feedback': 'RTS', 'cancelled': True},
    ])
    assert rows[0]['cancelled'] is True
    assert 'RTS' in rows[0]['label']


def test_empty_shapes():
    assert normalize_mailer_history(None) == []
    assert normalize_mailer_history('') == []
    assert normalize_mailer_history([]) == []
    summary = mailer_history_summary(None)
    assert summary['count'] == 0
    assert summary['last_sent_at'] is None


def test_last_sent_prefers_chronological_not_lexicographic():
    summary = mailer_history_summary([
        {'sent_at': '12/1/2024', 'template_name': 'Old'},
        {'sent_at': '1/1/2025', 'template_name': 'New'},
    ])
    assert summary['count'] == 2
    assert summary['last_sent_at'] == '1/1/2025'


def test_parse_mailer_sent_at_iso_and_us():
    assert parse_mailer_sent_at('2024-06-01T00:00:00Z') is not None
    assert parse_mailer_sent_at('6/21/2024').month == 6
    assert parse_mailer_sent_at('not-a-date') is None
