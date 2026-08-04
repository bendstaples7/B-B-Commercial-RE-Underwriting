"""Tests for mailer_history normalization (legacy + OLC shapes)."""
from datetime import datetime, timezone

from app import db
from app.models.lead import Lead
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.services.helpers.mailer_history import (
    consolidate_mailer_history,
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


def _make_lead(app, **kwargs):
    defaults = dict(
        owner_first_name='Test',
        owner_last_name='Owner',
        property_street='1 Test St',
        property_city='Chicago',
        property_state='IL',
        property_zip='60618',
        lead_category='residential',
        lead_status='mailing_no_contact_made',
        lead_score=50,
        has_property_match=True,
        source_type='import',
    )
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.flush()
    return lead


def _add_mail_sent_entry(lead_id, *, occurred_at, metadata):
    entry = LeadTimelineEntry(
        lead_id=lead_id,
        event_type='mail_sent',
        occurred_at=occurred_at,
        source='system',
        actor='system',
        summary='Mailer sent',
        event_metadata=metadata,
    )
    db.session.add(entry)
    return entry


class TestConsolidateMailerHistory:
    """Part C — union JSONB mailer_history with timeline mail_sent rows."""

    def test_union_dedupes_by_campaign_id(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                mailer_history=[
                    {'campaign_id': 5, 'template_name': 'Blue', 'sent_at': '2024-01-01'},
                ],
            )
            _add_mail_sent_entry(
                lead.id,
                occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                metadata={'campaign_id': 5, 'template_name': 'Blue'},
            )
            db.session.commit()

            summary = consolidate_mailer_history(lead)
            assert summary['count'] == 1
            assert summary['healed_count'] == 0

    def test_union_dedupes_campaign_only_jsonb_against_timeline_order(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                mailer_history=[
                    {'campaign_id': 5, 'template_name': 'Blue', 'sent_at': '2024-01-01'},
                ],
            )
            _add_mail_sent_entry(
                lead.id,
                occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                metadata={'campaign_id': 5, 'olc_order_id': '77', 'template_name': 'Blue'},
            )
            db.session.commit()

            summary = consolidate_mailer_history(lead)
            assert summary['count'] == 1
            assert summary['healed_count'] == 0

    def test_union_dedupes_olc_order_id_across_json_types(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                mailer_history=[
                    {'olc_order_id': 77, 'template_name': 'Blue', 'sent_at': '2024-01-01'},
                ],
            )
            _add_mail_sent_entry(
                lead.id,
                occurred_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                metadata={'olc_order_id': '77', 'template_name': 'Blue'},
            )
            db.session.commit()

            summary = consolidate_mailer_history(lead)
            assert summary['count'] == 1
            assert summary['healed_count'] == 0

    def test_import_string_plus_timeline_mail_sent_heals_and_counts_gt_1(self, app):
        """10305-class: import free-text history undercounts a mailer that
        the timeline recorded — union must surface both and heal the gap.
        """
        with app.app_context():
            lead = _make_lead(
                app,
                mailer_history='Boyfriend, OLM, Blue,  6/21/2024',
            )
            _add_mail_sent_entry(
                lead.id,
                occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                metadata={
                    'campaign_id': 9,
                    'olc_order_id': '77',
                    'template_name': 'Green',
                },
            )
            db.session.commit()

            summary = consolidate_mailer_history(lead)
            assert summary['count'] > 1
            assert summary['count'] == 2
            assert summary['healed_count'] == 1

            db.session.commit()
            db.session.refresh(lead)
            assert isinstance(lead.mailer_history, list)
            healed = [
                e for e in lead.mailer_history
                if isinstance(e, dict) and e.get('campaign_id') == 9
            ]
            assert len(healed) == 1
            assert healed[0]['olc_order_id'] == '77'

            # Re-running normalize directly on the healed JSONB column now
            # finds the entry without needing the timeline union.
            assert mailer_history_summary(lead.mailer_history)['count'] == 2

    def test_no_timeline_entries_matches_plain_summary(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                mailer_history=[{'campaign_id': 1, 'sent_at': '1/1/2024'}],
            )
            db.session.commit()

            summary = consolidate_mailer_history(lead)
            plain = mailer_history_summary(lead.mailer_history)
            assert summary['count'] == plain['count'] == 1
            assert summary['healed_count'] == 0

    def test_dedupe_falls_back_to_sent_at_label_without_olc_ids(self, app):
        with app.app_context():
            lead = _make_lead(
                app,
                mailer_history=['Legacy note, 1/1/2024'],
            )
            db.session.commit()

            summary = consolidate_mailer_history(lead)
            assert summary['count'] == 1
            assert summary['healed_count'] == 0

    def test_heal_false_does_not_write_jsonb(self, app):
        with app.app_context():
            lead = _make_lead(app, mailer_history=None)
            _add_mail_sent_entry(
                lead.id,
                occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                metadata={'campaign_id': 3},
            )
            db.session.commit()

            summary = consolidate_mailer_history(lead, heal=False)
            assert summary['count'] == 1
            assert summary['healed_count'] == 1

            db.session.refresh(lead)
            assert not lead.mailer_history
