"""Tests for ContactService related_properties and cross-property contact reuse."""
import pytest

from app import db
from app.models.lead import Lead
from app.models.contact import Contact
from app.models.contact_phone import ContactPhone
from app.models.contact_email import ContactEmail
from app.models.property_contact import PropertyContact
from app.services.contact_service import ContactService
from app.services.lead_merge_utils import dedup_street_key


def _make_lead(**kwargs) -> Lead:
    street = kwargs.pop('property_street', '100 Test St')
    lead = Lead(
        property_street=street,
        normalized_street=dedup_street_key(street),
        **kwargs,
    )
    db.session.add(lead)
    db.session.flush()
    return lead


class TestContactReuseAcrossProperties:
    def test_reuses_contact_by_shared_phone(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='2623 N Southport Ave',
                owner_user_id='user-1',
                owner_first_name='GILBERT',
                owner_last_name='JANSON',
                phone_1='(773) 555-0100',
            )
            b = _make_lead(
                property_street='5339 N Winthrop Ave',
                owner_user_id='user-1',
                owner_first_name='GILBERT E',
                owner_last_name='JANSON',
                phone_1='773-555-0100',
            )
            db.session.commit()

            rows_a = svc.upsert_owners_from_lead(a, commit=True)
            rows_b = svc.upsert_owners_from_lead(b, commit=True)

            assert rows_a[0][0].id == rows_b[0][0].id
            assert PropertyContact.query.filter_by(contact_id=rows_a[0][0].id).count() == 2

    def test_reuses_contact_by_shared_email(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='1 Maple St',
                owner_user_id='user-1',
                owner_first_name='Ada',
                owner_last_name='Lovelace',
                email_1='ada@example.com',
            )
            b = _make_lead(
                property_street='2 Oak St',
                owner_user_id='user-1',
                owner_first_name='ADA',
                owner_last_name='LOVELACE',
                email_1='Ada@Example.com',
            )
            db.session.commit()

            ca = svc.upsert_owners_from_lead(a, commit=True)[0][0]
            cb = svc.upsert_owners_from_lead(b, commit=True)[0][0]
            assert ca.id == cb.id

    def test_does_not_reuse_across_users(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='1 Maple St',
                owner_user_id='user-a',
                owner_first_name='Ada',
                owner_last_name='Lovelace',
                phone_1='5551112222',
            )
            b = _make_lead(
                property_street='2 Oak St',
                owner_user_id='user-b',
                owner_first_name='Ada',
                owner_last_name='Lovelace',
                phone_1='5551112222',
            )
            db.session.commit()
            ca = svc.upsert_owners_from_lead(a, commit=True)[0][0]
            cb = svc.upsert_owners_from_lead(b, commit=True)[0][0]
            assert ca.id != cb.id


class TestRelatedProperties:
    def test_generic_owner_name_does_not_link_by_name(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='10 Alpha St',
                owner_user_id='user-1',
                owner_first_name='Current',
                owner_last_name='Resident',
            )
            b = _make_lead(
                property_street='20 Beta St',
                owner_user_id='user-1',
                owner_first_name='Current',
                owner_last_name='Resident',
            )
            db.session.commit()

            assert svc.get_related_properties(a.id) == []
            assert svc.person_identity_for_lead(a)['person_key'] == f'lead:{a.id}'
            enrichment = svc.portfolio_enrichment_for_leads([a.id])
            assert enrichment[a.id]['person_key'] == f'lead:{a.id}'
            assert enrichment[a.id]['property_count'] == 1

    def test_generic_owner_name_keeps_shared_contact_links(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='10 Alpha St',
                owner_user_id='user-1',
                owner_first_name='For Sale By',
                owner_last_name='Owner',
            )
            b = _make_lead(
                property_street='20 Beta St',
                owner_user_id='user-1',
                owner_first_name='For Sale By',
                owner_last_name='Owner',
            )
            db.session.commit()
            contact = svc.create_contact({'first_name': 'Pat', 'last_name': 'Lee'})
            svc.link_contact_to_property(a.id, contact.id, role='owner', is_primary=True)
            svc.link_contact_to_property(b.id, contact.id, role='owner', is_primary=True)

            assert [row['id'] for row in svc.get_related_properties(a.id)] == [b.id]

    def test_related_by_owner_name_different_streets(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='2623 N Southport Ave',
                owner_user_id='user-1',
                owner_first_name='GILBERT',
                owner_last_name='JANSON',
                lead_score=68.89,
            )
            b = _make_lead(
                property_street='5339 N Winthrop Ave',
                owner_user_id='user-1',
                owner_first_name='GILBERT E',
                owner_last_name='JANSON',
                lead_score=68.89,
            )
            db.session.commit()

            related = svc.get_related_properties(a.id)
            assert len(related) == 1
            assert related[0]['id'] == b.id
            assert related[0]['property_street'] == '5339 N Winthrop Ave'
            assert svc.property_count_for_lead(a.id) == 2

    def test_related_by_jammed_owner_first_name(self, app):
        """Assessor-style ``GILBERT JANSON`` all in first_name with empty last."""
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='2623 N Southport Ave',
                owner_user_id='user-1',
                owner_first_name='GILBERT JANSON',
                owner_last_name=None,
            )
            b = _make_lead(
                property_street='5339 N Winthrop Ave',
                owner_user_id='user-1',
                owner_first_name='GILBERT E JANSON',
                owner_last_name=None,
            )
            db.session.commit()
            related = svc.get_related_properties(a.id)
            assert len(related) == 1
            assert related[0]['id'] == b.id

    def test_excludes_same_building_address_variants(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='4128 W Barry Ave',
                owner_user_id='user-1',
                owner_first_name='ADALBERTO',
                owner_last_name='GARCIA',
            )
            b = _make_lead(
                property_street='4128 W Barry Ave Chicago IL 60618',
                owner_user_id='user-1',
                owner_first_name='ADALBERTO',
                owner_last_name='GARCIA',
            )
            db.session.commit()

            # Same building after street-key normalize — not "other properties"
            assert svc.get_related_properties(a.id) == []
            assert svc.property_count_for_lead(a.id) == 1

    def test_related_via_shared_contact(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='10 Alpha St',
                owner_user_id='user-1',
                owner_first_name='Pat',
                owner_last_name='Lee',
            )
            b = _make_lead(
                property_street='20 Beta St',
                owner_user_id='user-1',
                # Different flat names so name fallback alone would miss —
                # shared Contact should still link them.
                owner_first_name='Other',
                owner_last_name='Name',
            )
            db.session.commit()
            contact = svc.create_contact({'first_name': 'Pat', 'last_name': 'Lee'})
            svc.link_contact_to_property(a.id, contact.id, role='owner', is_primary=True)
            svc.link_contact_to_property(b.id, contact.id, role='owner', is_primary=False)

            related = svc.get_related_properties(a.id)
            assert any(r['id'] == b.id for r in related)

    def test_shared_contact_excludes_same_building_variant(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='4128 W Barry Ave',
                owner_user_id='user-1',
                owner_first_name='Pat',
                owner_last_name='Lee',
            )
            b = _make_lead(
                property_street='4128 W Barry Ave Chicago IL 60618',
                owner_user_id='user-1',
                owner_first_name='Pat',
                owner_last_name='Lee',
            )
            db.session.commit()
            contact = svc.create_contact({'first_name': 'Pat', 'last_name': 'Lee'})
            svc.link_contact_to_property(a.id, contact.id, role='owner', is_primary=True)
            svc.link_contact_to_property(b.id, contact.id, role='owner', is_primary=False)
            assert svc.get_related_properties(a.id) == []

    def test_attorney_role_does_not_create_related_properties(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='10 Alpha St',
                owner_user_id='user-1',
                owner_first_name='Pat',
                owner_last_name='Lee',
            )
            b = _make_lead(
                property_street='20 Beta St',
                owner_user_id='user-1',
                owner_first_name='Other',
                owner_last_name='Name',
            )
            db.session.commit()
            contact = svc.create_contact({'first_name': 'Pat', 'last_name': 'Lee'})
            svc.link_contact_to_property(a.id, contact.id, role='owner', is_primary=True)
            svc.link_contact_to_property(b.id, contact.id, role='attorney', is_primary=False)
            assert svc.get_related_properties(a.id) == []

    def test_shared_owner_contact_does_not_leak_other_user_property(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='10 Alpha St',
                owner_user_id='user-1',
                owner_first_name='Pat',
                owner_last_name='Lee',
            )
            b = _make_lead(
                property_street='20 Beta St',
                owner_user_id='user-2',
                owner_first_name='Pat',
                owner_last_name='Lee',
            )
            db.session.commit()
            contact = svc.create_contact({'first_name': 'Pat', 'last_name': 'Lee'})
            svc.link_contact_to_property(a.id, contact.id, role='owner', is_primary=True)
            svc.link_contact_to_property(b.id, contact.id, role='owner', is_primary=True)
            assert svc.get_related_properties(a.id) == []
            assert all(r['id'] != b.id for r in svc.get_related_properties(a.id))

    def test_reuse_already_linked_contact_does_not_raise(self, app):
        with app.app_context():
            svc = ContactService()
            a = _make_lead(
                property_street='1 Maple St',
                owner_user_id='user-1',
                owner_first_name='Ada',
                owner_last_name='Lovelace',
                phone_1='5559998888',
            )
            db.session.commit()
            contact, _ = svc.upsert_owners_from_lead(a, commit=True)[0]
            # Idempotent re-upsert on the same property must not IntegrityError.
            again = svc.upsert_owners_from_lead(a, commit=True)
            assert again[0][0].id == contact.id
            assert PropertyContact.query.filter_by(property_id=a.id).count() == 1
