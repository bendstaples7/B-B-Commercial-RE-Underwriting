"""Tests for last mailed date resolution."""
from datetime import datetime, timezone

from app.models.lead_timeline_entry import LeadTimelineEntry
from app.services.last_mailed_service import (
    get_last_mailed_at_by_lead_ids,
    last_mailed_from_mailer_history,
)


class TestLastMailedFromMailerHistory:
    def test_list_with_sent_at(self):
        history = [
            {'sent_at': '2024-01-15T10:00:00+00:00'},
            {'sent_at': '2025-06-01T10:00:00+00:00'},
        ]
        result = last_mailed_from_mailer_history(history)
        assert result == datetime(2025, 6, 1, 10, 0, tzinfo=timezone.utc)

    def test_dict_with_last_sent(self):
        result = last_mailed_from_mailer_history({'last_sent': '2023-12-01T00:00:00Z'})
        assert result == datetime(2023, 12, 1, 0, 0, tzinfo=timezone.utc)

    def test_dict_with_date_only_last_sent(self):
        result = last_mailed_from_mailer_history({'sent': 3, 'last_sent': '2024-03-15'})
        assert result == datetime(2024, 3, 15, 0, 0, tzinfo=timezone.utc)

    def test_string_with_embedded_us_date(self):
        result = last_mailed_from_mailer_history('Personal, Blue Mosaic, 12/11/2022')
        assert result == datetime(2022, 12, 11, 0, 0, tzinfo=timezone.utc)

    def test_string_bes_and_ben_format(self):
        result = last_mailed_from_mailer_history('Bes and Ben, OLM, 3/26/2024')
        assert result == datetime(2024, 3, 26, 0, 0, tzinfo=timezone.utc)

    def test_whole_string_iso_date(self):
        result = last_mailed_from_mailer_history('2024-01-01')
        assert result == datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    def test_list_dict_with_date_key(self):
        result = last_mailed_from_mailer_history([{'date': '2024-01-01', 'type': 'postcard'}])
        assert result == datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    def test_list_of_legacy_strings_picks_latest(self):
        history = ['Postcard 1/1/2023', 'OLM 3/26/2024']
        result = last_mailed_from_mailer_history(history)
        assert result == datetime(2024, 3, 26, 0, 0, tzinfo=timezone.utc)


class TestGetLastMailedAtByLeadIds:
    def test_timeline_mail_sent(self, app):
        from app import db
        from app.models import Lead

        with app.app_context():
            lead = Lead(property_street='1 Mail St', lead_status='mailing_no_contact_made')
            db.session.add(lead)
            db.session.flush()
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='mail_sent',
                occurred_at=datetime(2025, 3, 10, 12, 0, tzinfo=timezone.utc),
                source='system',
                actor='test-user',
                summary='Mail sent',
            ))
            db.session.commit()

            result = get_last_mailed_at_by_lead_ids([lead.id])
            assert result[lead.id] == datetime(2025, 3, 10, 12, 0, tzinfo=timezone.utc)

    def test_mailer_history_and_timeline_picks_latest(self, app):
        from app import db
        from app.models import Lead

        with app.app_context():
            lead = Lead(
                property_street='2 Mail St',
                lead_status='mailing_no_contact_made',
                mailer_history=[{'sent_at': '2024-05-01T00:00:00Z'}],
            )
            db.session.add(lead)
            db.session.flush()
            db.session.add(LeadTimelineEntry(
                lead_id=lead.id,
                event_type='mail_sent',
                occurred_at=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
                source='system',
                actor='test-user',
                summary='Mail sent',
            ))
            db.session.commit()

            result = get_last_mailed_at_by_lead_ids([lead.id])
            assert result[lead.id] == datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    def test_get_last_mailed_from_string_mailer_history_only(self, app):
        from app import db
        from app.models import Lead

        with app.app_context():
            lead = Lead(
                property_street='3 Mail St',
                lead_status='mailing_no_contact_made',
                mailer_history='Personal, Blue Mosaic, 12/11/2022',
            )
            db.session.add(lead)
            db.session.commit()

            result = get_last_mailed_at_by_lead_ids([lead.id])
            assert result[lead.id] == datetime(2022, 12, 11, 0, 0, tzinfo=timezone.utc)

    def test_sibling_pin_shares_mailer_history(self, app):
        from app import db
        from app.models import Lead

        with app.app_context():
            sibling = Lead(
                property_street='1910 N Leavitt St Apt 2',
                lead_status='mailing_no_contact_made',
                county_assessor_pin='14-31-303-028-0000',
                owner_first_name='Jane',
                owner_last_name='Doe',
                owner_user_id='owner-a',
                mailer_history='Standard, OLM, Grey Herringbone 3/8/2024',
            )
            main = Lead(
                property_street='1910 N Leavitt St',
                lead_status='mailing_contacted_interested',
                county_assessor_pin='14313030280000',
                owner_first_name='Jane',
                owner_last_name='Doe',
                owner_user_id='owner-a',
            )
            db.session.add_all([sibling, main])
            db.session.commit()

            result = get_last_mailed_at_by_lead_ids([main.id])
            assert result[main.id] == datetime(2024, 3, 8, 0, 0, tzinfo=timezone.utc)

    def test_sibling_pin_does_not_cross_owner_users(self, app):
        from app import db
        from app.models import Lead

        with app.app_context():
            other_owner_sibling = Lead(
                property_street='2000 N Leavitt St',
                lead_status='mailing_no_contact_made',
                county_assessor_pin='14-31-303-028-0000',
                owner_first_name='Jane',
                owner_last_name='Doe',
                owner_user_id='owner-b',
                mailer_history='Other owner mail 1/1/2025',
            )
            main = Lead(
                property_street='1910 N Leavitt St',
                lead_status='mailing_contacted_interested',
                county_assessor_pin='14313030280000',
                owner_first_name='Jane',
                owner_last_name='Doe',
                owner_user_id='owner-a',
            )
            db.session.add_all([other_owner_sibling, main])
            db.session.commit()

            result = get_last_mailed_at_by_lead_ids([main.id])
            assert result[main.id] is None
