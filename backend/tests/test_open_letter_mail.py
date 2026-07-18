"""Tests for Open Letter mail queue and contact mapping."""
import pytest
from cryptography.fernet import Fernet

from app.models.lead import Lead
from app.models.open_letter_config import OpenLetterConfig
from app.models.user import User
from app.services.mail_queue_service import MailQueueService
from app.services.open_letter_config_service import OpenLetterConfigService
from app.services.open_letter_contact_mapper import (
    lead_to_olc_contact,
    is_owner_mailable_lead,
    persist_embedded_address_fields,
    validate_lead_mail_address,
    validate_owner_mailing_address,
)

BEN_USER_ID = 'e5bc61c7-4db1-4307-a7b6-0a6b5a3d84c9'
OTHER_USER_ID = 'd5f4f0ce-4d5b-48e5-bdcb-6b4679f66879'


def _make_lead(**kwargs):
    defaults = {
        'id': 1,
        'owner_first_name': 'Jane',
        'owner_last_name': 'Doe',
        'mailing_address': '123 Main St',
        'mailing_city': 'Chicago',
        'mailing_state': 'IL',
        'mailing_zip': '60601',
        'property_street': '456 Oak Ave',
        'property_city': 'Evanston',
        'property_state': 'IL',
        'property_zip': '60201',
        'phone_1': '312-555-0100',
    }
    defaults.update(kwargs)
    return Lead(**defaults)


@pytest.fixture
def fernet_key():
    return Fernet.generate_key().decode()


class TestOpenLetterContactMapper:
    def test_maps_mailing_address_first(self):
        lead = _make_lead()
        contact = lead_to_olc_contact(lead, user_id='user1')
        assert contact['address1'] == '123 Main St'
        assert contact['city'] == 'Chicago'
        assert contact['meta_data']['lead_id'] == 1

    def test_falls_back_to_property_address(self):
        lead = _make_lead(mailing_address=None, mailing_city=None, mailing_state=None, mailing_zip=None)
        contact = lead_to_olc_contact(lead)
        assert contact['address1'] == '456 Oak Ave'
        assert contact['city'] == 'Evanston'

    def test_validate_rejects_missing_address(self):
        lead = _make_lead(
            mailing_address=None, property_street=None,
            mailing_city=None, mailing_state=None, mailing_zip=None,
            property_city=None, property_state=None, property_zip=None,
        )
        assert validate_lead_mail_address(lead) is not None

    def test_owner_mail_readiness_rejects_property_fallback(self):
        lead = _make_lead(
            mailing_address=None,
            mailing_city=None,
            mailing_state=None,
            mailing_zip=None,
        )
        assert is_owner_mailable_lead(lead) is False
        assert validate_owner_mailing_address(lead) == 'No owner mailing street address'

    def test_owner_mail_readiness_parses_embedded_address(self):
        lead = _make_lead(
            mailing_address='123 Main St Chicago IL 60601',
            mailing_city=None,
            mailing_state=None,
            mailing_zip=None,
        )
        assert is_owner_mailable_lead(lead) is True

    def test_owner_mail_readiness_rejects_returned_address(self):
        lead = _make_lead(returned_addresses='123 Main St Chicago IL 60601')
        assert validate_owner_mailing_address(lead) == (
            'Current owner mailing address was previously returned'
        )

    def test_owner_mail_allows_different_historical_returned_street(self):
        lead = _make_lead(
            mailing_address='198 Karen Cir',
            mailing_city='Bolingbrook',
            mailing_state='IL',
            mailing_zip='60440',
            returned_addresses='3851 W Fullerton Ave Ste 2, Bolingbrook, IL 60440',
        )
        assert validate_owner_mailing_address(lead) is None
        assert is_owner_mailable_lead(lead) is True

    def test_owner_mail_rejects_equivalent_returned_formatting(self):
        lead = _make_lead(
            mailing_address='123 Main Street',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            returned_addresses='123 Main St, Chicago, IL 60601',
        )
        assert validate_owner_mailing_address(lead) == (
            'Current owner mailing address was previously returned'
        )

    def test_owner_mail_allows_unit_mismatch_in_returned_history(self):
        lead = _make_lead(
            mailing_address='100 Oak Ave Apt 2',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            returned_addresses='100 Oak Ave Apt 5, Chicago, IL 60601',
        )
        assert validate_owner_mailing_address(lead) is None

    def test_owner_mail_rejects_when_one_of_multiple_returned_matches(self):
        lead = _make_lead(
            mailing_address='123 Main St',
            mailing_city='Chicago',
            mailing_state='IL',
            mailing_zip='60601',
            returned_addresses=(
                '999 Other Rd, Chicago, IL 60601\n'
                '123 Main St Chicago IL 60601\n'
            ),
        )
        assert validate_owner_mailing_address(lead) == (
            'Current owner mailing address was previously returned'
        )

    def test_does_not_mix_partial_mailing_with_property(self):
        lead = _make_lead(
            mailing_address='123 Main St',
            mailing_city=None,
            mailing_state=None,
            mailing_zip=None,
            property_street='456 Oak Ave',
            property_city='Chicago',
            property_state='IL',
            property_zip='60601',
        )
        contact = lead_to_olc_contact(lead)
        assert contact['address1'] == '456 Oak Ave'
        assert contact['city'] == 'Chicago'

    def test_parses_embedded_property_street_for_mail(self):
        lead = _make_lead(
            mailing_address=None,
            mailing_city=None,
            mailing_state=None,
            mailing_zip=None,
            property_street='4439 N Kimball Ave Chicago IL 60625',
            property_city=None,
            property_state=None,
            property_zip=None,
        )
        assert validate_lead_mail_address(lead) is None
        contact = lead_to_olc_contact(lead)
        assert contact['address1'] == '4439 N Kimball Ave'
        assert contact['city'] == 'Chicago'
        assert contact['state'] == 'IL'
        assert contact['zip'] == '60625'

    def test_persist_embedded_property_fields(self):
        lead = _make_lead(
            mailing_address=None,
            mailing_city=None,
            mailing_state=None,
            mailing_zip=None,
            property_street='847-849 W Sunnyside Ave Chicago IL 60640',
            property_city=None,
            property_state=None,
            property_zip=None,
        )
        assert persist_embedded_address_fields(lead) is True
        assert lead.property_street == '847-849 W Sunnyside Ave Chicago IL 60640'
        assert lead.property_city == 'Chicago'
        assert lead.property_state == 'IL'
        assert lead.property_zip == '60640'

    def test_persist_never_mutates_identity_fields(self):
        """Hard guard: street / normalized_street must stay identical after persist."""
        lead = _make_lead(
            mailing_address='1021 Saint James Pl Park Ridge IL 60068',
            mailing_city=None,
            mailing_state=None,
            mailing_zip=None,
            property_street='3446 N Harding Ave Chicago IL 60618',
            property_city=None,
            property_state=None,
            property_zip=None,
            normalized_street='3446 N HARDING AVENUE CHICAGO IL',
        )
        before_property = lead.property_street
        before_mailing = lead.mailing_address
        before_norm = lead.normalized_street

        assert persist_embedded_address_fields(lead) is True
        assert lead.property_street == before_property
        assert lead.mailing_address == before_mailing
        assert lead.normalized_street == before_norm
        assert lead.property_city == 'Chicago'
        assert lead.mailing_city == 'Park Ridge'

    def test_enqueue_isolates_per_lead_failures(self, app):
        """One lead raising during flush must soft-fail; siblings still enqueue."""
        from unittest.mock import patch

        from app import db
        from app.models.lead import Lead
        from sqlalchemy.exc import IntegrityError

        user_id = 'soft-fail-user'
        with app.app_context():
            good_a = Lead(
                owner_user_id=user_id,
                owner_first_name='Ada',
                owner_last_name='Good',
                property_street='1 Good St',
                property_city='Chicago',
                property_state='IL',
                property_zip='60601',
                mailing_address='1 Owner Mail St',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60601',
                lead_status='mailing_no_contact_made',
            )
            bad = Lead(
                owner_user_id=user_id,
                owner_first_name='Bad',
                owner_last_name='Lead',
                property_street='2 Bad St',
                property_city='Chicago',
                property_state='IL',
                property_zip='60602',
                mailing_address='2 Owner Mail St',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60602',
                lead_status='mailing_no_contact_made',
            )
            good_b = Lead(
                owner_user_id=user_id,
                owner_first_name='Bea',
                owner_last_name='Good',
                property_street='3 Good St',
                property_city='Chicago',
                property_state='IL',
                property_zip='60603',
                mailing_address='3 Owner Mail St',
                mailing_city='Chicago',
                mailing_state='IL',
                mailing_zip='60603',
                lead_status='mailing_no_contact_made',
            )
            db.session.add_all([good_a, bad, good_b])
            db.session.commit()
            ids = [good_a.id, bad.id, good_b.id]
            bad_id = bad.id

            original_flush = db.session.flush

            def flaky_flush(*args, **kwargs):
                # Raise only when inserting the bad lead's queue row.
                for obj in db.session.new:
                    if getattr(obj, 'lead_id', None) == bad_id:
                        raise IntegrityError(
                            'mocked', {}, Exception('uq collision'),
                        )
                return original_flush(*args, **kwargs)

            with patch.object(db.session, 'flush', side_effect=flaky_flush):
                result = MailQueueService().enqueue_leads(ids, user_id)

            assert result['added'] == 2
            assert result['skipped'] == 1
            by_id = {r['lead_id']: r['status'] for r in result['results']}
            assert by_id[ids[0]] == 'queued'
            assert by_id[bad_id] == 'error'
            assert by_id[ids[2]] == 'queued'

    def test_enqueue_one_line_property_without_rewriting_street(self, app):
        """Persisting parsed city/state/zip must not rewrite property_street (dedup index)."""
        from app import db
        from app.models.lead import Lead

        user_id = 'dedup-test-user'
        with app.app_context():
            existing = Lead(
                owner_user_id=user_id,
                owner_first_name='Joseph',
                owner_last_name='Zajac',
                property_street='3446 N Harding Ave 1',
                property_city='Chicago',
                property_state='IL',
                property_zip='60618',
                lead_status='mailing_no_contact_made',
            )
            embedded = Lead(
                owner_user_id=user_id,
                owner_first_name='Joseph',
                owner_last_name='Zajac',
                property_street='3446 N Harding Ave Chicago IL 60618',
                mailing_address='3446 N Harding Ave Chicago IL 60618',
                lead_status='mailing_no_contact_made',
            )
            db.session.add_all([existing, embedded])
            db.session.commit()
            embedded_id = embedded.id

            result = MailQueueService().enqueue_leads([embedded_id], user_id)
            assert result['added'] == 1
            db.session.refresh(embedded)
            assert embedded.property_street == '3446 N Harding Ave Chicago IL 60618'
            assert embedded.property_city == 'Chicago'
            assert embedded.property_state == 'IL'
            assert embedded.property_zip == '60618'
            assert embedded.mailing_address == '3446 N Harding Ave Chicago IL 60618'
            assert embedded.mailing_city == 'Chicago'


class TestOpenLetterPerUserConfig:
    def _seed_users(self, db):
        from app.models.user import User
        db.session.add(User(
            user_id=BEN_USER_ID,
            email='ben.d.staples.7@gmail.com',
            email_lower='ben.d.staples.7@gmail.com',
            password_hash='x',
            display_name='Ben',
        ))
        db.session.add(User(
            user_id=OTHER_USER_ID,
            email='other@example.com',
            email_lower='other@example.com',
            password_hash='x',
            display_name='Other',
        ))
        db.session.commit()

    def test_env_token_only_for_designated_email(self, app, fernet_key, monkeypatch):
        monkeypatch.setenv('HUBSPOT_ENCRYPTION_KEY', fernet_key)
        monkeypatch.setenv('OPEN_LETTER_API_TOKEN', 'shared-env-token')
        monkeypatch.setenv('OPEN_LETTER_ENV_TOKEN_EMAIL', 'ben.d.staples.7@gmail.com')

        with app.app_context():
            from app import db
            self._seed_users(db)
            svc = OpenLetterConfigService()
            assert svc.env_api_token_for_user(BEN_USER_ID) == 'shared-env-token'
            assert svc.env_api_token_for_user(OTHER_USER_ID) is None
            assert svc.is_configured(BEN_USER_ID) is True
            assert svc.is_configured(OTHER_USER_ID) is False

    def test_other_user_saves_database_token(self, app, fernet_key, monkeypatch):
        from app import db
        from app.services.open_letter_client_service import OpenLetterClientService

        monkeypatch.setenv('HUBSPOT_ENCRYPTION_KEY', fernet_key)
        monkeypatch.delenv('OPEN_LETTER_API_TOKEN', raising=False)

        with app.app_context():
            svc = OpenLetterConfigService()
            cfg = svc.save_config(OTHER_USER_ID, api_token='user-specific-token')
            assert cfg.user_id == OTHER_USER_ID
            assert svc.token_source(OTHER_USER_ID) == 'database'
            assert OpenLetterClientService.decrypt_token(cfg.encrypted_api_token) == 'user-specific-token'


class TestMailQueueSummary:
    def test_can_send_when_at_minimum(self, app, fernet_key, monkeypatch):
        from app import db
        from app.models.mail_queue_item import MailQueueItem
        from app.services.open_letter_client_service import OpenLetterClientService

        with app.app_context():
            monkeypatch.setenv('HUBSPOT_ENCRYPTION_KEY', fernet_key)
            token = OpenLetterClientService.encrypt_token('test-token')
            config = OpenLetterConfig(
                user_id=BEN_USER_ID,
                encrypted_api_token=token,
                batch_minimum=2,
            )
            db.session.add(config)
            db.session.add(MailQueueItem(lead_id=1, user_id=BEN_USER_ID, status='queued'))
            db.session.add(MailQueueItem(lead_id=2, user_id=BEN_USER_ID, status='queued'))
            db.session.commit()

            summary = MailQueueService().get_summary(BEN_USER_ID)
            assert summary['queued_count'] == 2
            assert summary['can_send'] is True

    def test_cannot_send_below_minimum(self, app, fernet_key, monkeypatch):
        from app import db
        from app.models.mail_queue_item import MailQueueItem
        from app.services.open_letter_client_service import OpenLetterClientService

        with app.app_context():
            monkeypatch.setenv('HUBSPOT_ENCRYPTION_KEY', fernet_key)
            config = OpenLetterConfig(
                user_id=BEN_USER_ID,
                encrypted_api_token=OpenLetterClientService.encrypt_token('test-token'),
                batch_minimum=50,
            )
            db.session.add(config)
            db.session.add(MailQueueItem(lead_id=3, user_id=BEN_USER_ID, status='queued'))
            db.session.commit()

            summary = MailQueueService().get_summary(BEN_USER_ID)
            assert summary['queued_count'] == 1
            assert summary['can_send'] is False
