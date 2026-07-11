"""Unit tests for ContactService.

Covers:
  - create_contact: valid payload, both-names-empty, first_name only, last_name only
  - update_contact: atomic phone/email replacement, non-existent ID → 404
  - delete_contact: cascade to phones, emails, property_contacts
  - link_contact_to_property: primary demotion, duplicate → 409
  - unlink_contact_from_property: primary removed, no auto-promotion
  - get_contacts_for_property: returns contacts with join record metadata
"""
import pytest

from app import db
from app.models.lead import Lead
from app.models.contact import Contact
from app.models.contact_phone import ContactPhone
from app.models.contact_email import ContactEmail
from app.models.property_contact import PropertyContact
from app.services.contact_service import ContactService
from app.exceptions import ValidationException, ResourceNotFoundError, ConflictError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_property(street: str = "123 Test St") -> Lead:
    """Create and persist a minimal Property (Lead) record."""
    prop = Lead(property_street=street)
    db.session.add(prop)
    db.session.commit()
    return prop


def _make_contact(service: ContactService, first: str = "Alice", last: str = "Smith") -> Contact:
    """Create and persist a minimal Contact via the service."""
    return service.create_contact({"first_name": first, "last_name": last})


# ---------------------------------------------------------------------------
# create_contact
# ---------------------------------------------------------------------------

class TestCreateContact:
    def test_create_with_valid_payload(self, app):
        """create_contact with name + phones + emails persists all records."""
        with app.app_context():
            service = ContactService()
            data = {
                "first_name": "Jane",
                "last_name": "Doe",
                "role": "owner",
                "phones": [
                    {"value": "555-1234", "label": "mobile"},
                    {"value": "555-5678", "label": "home"},
                ],
                "emails": [
                    {"value": "jane@example.com", "label": "personal"},
                ],
            }
            contact = service.create_contact(data)

            assert contact.id is not None
            assert contact.first_name == "Jane"
            assert contact.last_name == "Doe"
            assert contact.role == "owner"

            phones = ContactPhone.query.filter_by(contact_id=contact.id).all()
            assert len(phones) == 2
            phone_values = {p.value for p in phones}
            assert "555-1234" in phone_values
            assert "555-5678" in phone_values

            emails = ContactEmail.query.filter_by(contact_id=contact.id).all()
            assert len(emails) == 1
            assert emails[0].value == "jane@example.com"

    def test_create_both_names_empty_raises_validation_error(self, app):
        """create_contact with both names empty/null raises ValidationException."""
        with app.app_context():
            service = ContactService()
            with pytest.raises(ValidationException):
                service.create_contact({"first_name": "", "last_name": ""})

    def test_create_both_names_whitespace_raises_validation_error(self, app):
        """create_contact with both names whitespace-only raises ValidationException."""
        with app.app_context():
            service = ContactService()
            with pytest.raises(ValidationException):
                service.create_contact({"first_name": "   ", "last_name": "\t"})

    def test_create_both_names_absent_raises_validation_error(self, app):
        """create_contact with neither name key present raises ValidationException."""
        with app.app_context():
            service = ContactService()
            with pytest.raises(ValidationException):
                service.create_contact({})

    def test_create_with_only_first_name_succeeds(self, app):
        """create_contact with only first_name set succeeds."""
        with app.app_context():
            service = ContactService()
            contact = service.create_contact({"first_name": "Bob"})
            assert contact.id is not None
            assert contact.first_name == "Bob"
            assert contact.last_name is None

    def test_create_with_only_last_name_succeeds(self, app):
        """create_contact with only last_name set succeeds."""
        with app.app_context():
            service = ContactService()
            contact = service.create_contact({"last_name": "Smith"})
            assert contact.id is not None
            assert contact.first_name is None
            assert contact.last_name == "Smith"


# ---------------------------------------------------------------------------
# update_contact
# ---------------------------------------------------------------------------

class TestUpdateContact:
    def test_update_replaces_phones_and_emails_atomically(self, app):
        """update_contact replaces all phones and emails with the new set."""
        with app.app_context():
            service = ContactService()
            contact = service.create_contact({
                "first_name": "Alice",
                "phones": [{"value": "111-1111"}, {"value": "222-2222"}],
                "emails": [{"value": "old@example.com"}],
            })

            updated = service.update_contact(contact.id, {
                "phones": [{"value": "333-3333", "label": "work"}],
                "emails": [
                    {"value": "new1@example.com", "label": "personal"},
                    {"value": "new2@example.com", "label": "work"},
                ],
            })

            phones = ContactPhone.query.filter_by(contact_id=updated.id).all()
            assert len(phones) == 1
            assert phones[0].value == "333-3333"

            emails = ContactEmail.query.filter_by(contact_id=updated.id).all()
            assert len(emails) == 2
            email_values = {e.value for e in emails}
            assert "new1@example.com" in email_values
            assert "new2@example.com" in email_values
            # Old email must be gone
            assert "old@example.com" not in email_values

    def test_update_clears_phones_when_empty_list_provided(self, app):
        """update_contact with phones=[] removes all existing phones."""
        with app.app_context():
            service = ContactService()
            contact = service.create_contact({
                "first_name": "Alice",
                "phones": [{"value": "111-1111"}],
            })
            service.update_contact(contact.id, {"phones": []})
            phones = ContactPhone.query.filter_by(contact_id=contact.id).all()
            assert phones == []

    def test_update_nonexistent_id_raises_404(self, app):
        """update_contact with a non-existent ID raises ResourceNotFoundError."""
        with app.app_context():
            service = ContactService()
            with pytest.raises(ResourceNotFoundError):
                service.update_contact(99999, {"first_name": "Ghost"})

    def test_update_scalar_fields(self, app):
        """update_contact updates scalar fields correctly."""
        with app.app_context():
            service = ContactService()
            contact = service.create_contact({"first_name": "Alice", "last_name": "Old"})
            updated = service.update_contact(contact.id, {
                "last_name": "New",
                "role": "attorney",
                "notes": "Updated notes",
            })
            assert updated.last_name == "New"
            assert updated.role == "attorney"
            assert updated.notes == "Updated notes"


# ---------------------------------------------------------------------------
# delete_contact
# ---------------------------------------------------------------------------

class TestDeleteContact:
    def test_delete_cascades_to_phones_emails_property_contacts(self, app):
        """delete_contact removes the contact and all related phones, emails, and property_contacts."""
        with app.app_context():
            service = ContactService()
            prop = _make_property("456 Cascade Ave")

            contact = service.create_contact({
                "first_name": "Delete",
                "last_name": "Me",
                "phones": [{"value": "999-9999"}],
                "emails": [{"value": "delete@example.com"}],
            })
            service.link_contact_to_property(
                property_id=prop.id,
                contact_id=contact.id,
                role="owner",
                is_primary=True,
            )

            contact_id = contact.id

            # Verify records exist before deletion
            assert ContactPhone.query.filter_by(contact_id=contact_id).count() == 1
            assert ContactEmail.query.filter_by(contact_id=contact_id).count() == 1
            assert PropertyContact.query.filter_by(contact_id=contact_id).count() == 1

            service.delete_contact(contact_id)

            # All related records must be gone
            assert Contact.query.get(contact_id) is None
            assert ContactPhone.query.filter_by(contact_id=contact_id).count() == 0
            assert ContactEmail.query.filter_by(contact_id=contact_id).count() == 0
            assert PropertyContact.query.filter_by(contact_id=contact_id).count() == 0

    def test_delete_nonexistent_id_raises_404(self, app):
        """delete_contact with a non-existent ID raises ResourceNotFoundError."""
        with app.app_context():
            service = ContactService()
            with pytest.raises(ResourceNotFoundError):
                service.delete_contact(99999)


# ---------------------------------------------------------------------------
# link_contact_to_property
# ---------------------------------------------------------------------------

class TestLinkContactToProperty:
    def test_primary_demotion_when_new_primary_added(self, app):
        """Linking a new primary contact demotes the previous primary to is_primary=False."""
        with app.app_context():
            service = ContactService()
            prop = _make_property("789 Primary St")
            contact_a = _make_contact(service, "Alice", "A")
            contact_b = _make_contact(service, "Bob", "B")

            # Link A as primary
            service.link_contact_to_property(
                property_id=prop.id,
                contact_id=contact_a.id,
                role="owner",
                is_primary=True,
            )

            link_a = PropertyContact.query.filter_by(
                property_id=prop.id, contact_id=contact_a.id
            ).one()
            assert link_a.is_primary is True

            # Link B as primary — A should be demoted
            service.link_contact_to_property(
                property_id=prop.id,
                contact_id=contact_b.id,
                role="owner",
                is_primary=True,
            )

            db.session.refresh(link_a)
            assert link_a.is_primary is False

            link_b = PropertyContact.query.filter_by(
                property_id=prop.id, contact_id=contact_b.id
            ).one()
            assert link_b.is_primary is True

    def test_duplicate_link_raises_conflict_error(self, app):
        """Linking the same contact to the same property twice raises ConflictError."""
        with app.app_context():
            service = ContactService()
            prop = _make_property("101 Duplicate Ln")
            contact = _make_contact(service, "Carol", "C")

            service.link_contact_to_property(
                property_id=prop.id,
                contact_id=contact.id,
                role="owner",
                is_primary=False,
            )

            with pytest.raises(ConflictError):
                service.link_contact_to_property(
                    property_id=prop.id,
                    contact_id=contact.id,
                    role="owner",
                    is_primary=False,
                )

    def test_link_nonexistent_property_raises_404(self, app):
        """Linking to a non-existent property raises ResourceNotFoundError."""
        with app.app_context():
            service = ContactService()
            contact = _make_contact(service, "Dave", "D")
            with pytest.raises(ResourceNotFoundError):
                service.link_contact_to_property(
                    property_id=99999,
                    contact_id=contact.id,
                    role="owner",
                    is_primary=False,
                )

    def test_link_nonexistent_contact_raises_404(self, app):
        """Linking a non-existent contact raises ResourceNotFoundError."""
        with app.app_context():
            service = ContactService()
            prop = _make_property("202 Ghost Rd")
            with pytest.raises(ResourceNotFoundError):
                service.link_contact_to_property(
                    property_id=prop.id,
                    contact_id=99999,
                    role="owner",
                    is_primary=False,
                )


# ---------------------------------------------------------------------------
# unlink_contact_from_property
# ---------------------------------------------------------------------------

class TestUnlinkContactFromProperty:
    def test_unlink_primary_no_auto_promotion(self, app):
        """Removing the primary contact leaves remaining contacts with is_primary=False."""
        with app.app_context():
            service = ContactService()
            prop = _make_property("303 Unlink Ave")
            primary = _make_contact(service, "Primary", "P")
            secondary = _make_contact(service, "Secondary", "S")

            service.link_contact_to_property(
                property_id=prop.id,
                contact_id=primary.id,
                role="owner",
                is_primary=True,
            )
            service.link_contact_to_property(
                property_id=prop.id,
                contact_id=secondary.id,
                role="owner",
                is_primary=False,
            )

            # Remove the primary contact
            service.unlink_contact_from_property(
                property_id=prop.id,
                contact_id=primary.id,
            )

            # Primary link must be gone
            assert PropertyContact.query.filter_by(
                property_id=prop.id, contact_id=primary.id
            ).first() is None

            # Secondary must still be is_primary=False (no auto-promotion)
            link_secondary = PropertyContact.query.filter_by(
                property_id=prop.id, contact_id=secondary.id
            ).one()
            assert link_secondary.is_primary is False

    def test_unlink_nonexistent_link_raises_404(self, app):
        """Unlinking a contact that is not linked raises ResourceNotFoundError."""
        with app.app_context():
            service = ContactService()
            prop = _make_property("404 Missing Blvd")
            contact = _make_contact(service, "Eve", "E")

            with pytest.raises(ResourceNotFoundError):
                service.unlink_contact_from_property(
                    property_id=prop.id,
                    contact_id=contact.id,
                )


# ---------------------------------------------------------------------------
# get_contacts_for_property
# ---------------------------------------------------------------------------

class TestGetContactsForProperty:
    def test_returns_contacts_with_join_metadata(self, app):
        """get_contacts_for_property returns (Contact, PropertyContact) tuples with correct metadata."""
        with app.app_context():
            service = ContactService()
            prop = _make_property("505 Query St")
            contact_a = _make_contact(service, "Frank", "F")
            contact_b = _make_contact(service, "Grace", "G")

            service.link_contact_to_property(
                property_id=prop.id,
                contact_id=contact_a.id,
                role="owner",
                is_primary=True,
            )
            service.link_contact_to_property(
                property_id=prop.id,
                contact_id=contact_b.id,
                role="property_manager",
                is_primary=False,
            )

            rows = service.get_contacts_for_property(prop.id)

            assert len(rows) == 2

            # Build a lookup by contact id for easy assertions
            by_id = {contact.id: (contact, pc) for contact, pc in rows}

            assert contact_a.id in by_id
            assert contact_b.id in by_id

            _, pc_a = by_id[contact_a.id]
            assert pc_a.is_primary is True
            assert pc_a.role == "owner"

            _, pc_b = by_id[contact_b.id]
            assert pc_b.is_primary is False
            assert pc_b.role == "property_manager"

    def test_returns_empty_list_for_property_with_no_contacts(self, app):
        """get_contacts_for_property returns an empty list when no contacts are linked."""
        with app.app_context():
            service = ContactService()
            prop = _make_property("606 Empty Rd")
            rows = service.get_contacts_for_property(prop.id)
            assert rows == []

    def test_raises_404_for_nonexistent_property(self, app):
        """get_contacts_for_property raises ResourceNotFoundError for unknown property."""
        with app.app_context():
            service = ContactService()
            with pytest.raises(ResourceNotFoundError):
                service.get_contacts_for_property(99999)


# ---------------------------------------------------------------------------
# get_ordered_contacts_payload / batch_owner_display_for_leads
# ---------------------------------------------------------------------------

class TestOrderedContactsPayload:
    def test_payload_primary_first_with_nested_channels(self, app):
        """get_ordered_contacts_payload orders primary first and nests phones/emails."""
        with app.app_context():
            from app.services.contact_service import batch_owner_display_for_leads

            service = ContactService()
            prop = _make_property("707 Payload Ave")
            secondary = service.create_contact({
                'first_name': 'Sec',
                'last_name': 'Ond',
                'phones': [{'value': '111', 'label': 'other'}],
            })
            primary = service.create_contact({
                'first_name': 'Pri',
                'last_name': 'Mary',
                'emails': [{'value': 'pri@ex.com', 'label': 'other'}],
            })
            service.link_contact_to_property(prop.id, secondary.id, role='owner', is_primary=False)
            service.link_contact_to_property(prop.id, primary.id, role='owner', is_primary=True)

            payload = service.get_ordered_contacts_payload(prop.id)
            assert [c['first_name'] for c in payload] == ['Pri', 'Sec']
            assert payload[0]['is_primary'] is True
            assert payload[0]['emails'][0]['value'] == 'pri@ex.com'
            assert set(payload[0].keys()) >= {
                'id', 'first_name', 'last_name', 'role', 'is_primary', 'phones', 'emails',
            }

            display = batch_owner_display_for_leads([prop.id])
            assert display[prop.id]['owner_display_name'] == 'Pri Mary'
            assert display[prop.id]['best_email'] == 'pri@ex.com'
            assert display[prop.id]['best_phone'] == '111'
