"""Integration tests for the Contact model and related API endpoints.

Tests the full HTTP request/response cycle through the Flask test client.

Covers:
  - GET /api/properties/?owner_name=<q>  — join through property_contacts → contacts
  - POST /api/properties/<id>/contacts with is_primary=true when another primary exists
    — verifies previous primary is demoted to is_primary=False
  - DELETE /api/properties/<id>/contacts/<contact_id> for primary contact
    — verifies no auto-promotion of remaining contacts
  - HubSpot matcher end-to-end: email match, phone match, name+property match
"""
import pytest

from app import db
from app.models.lead import Lead
from app.models.contact import Contact
from app.models.contact_phone import ContactPhone
from app.models.contact_email import ContactEmail
from app.models.property_contact import PropertyContact
from app.models.hubspot_contact import HubSpotContact
from app.models.hubspot_match import HubSpotMatch
from app.services.hubspot_matcher_service import HubSpotMatcherService

_AUTH_HEADERS = {'X-User-Id': 'test-user'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_property(street: str = "100 Integration St") -> Lead:
    """Create and persist a minimal Property (Lead) record."""
    prop = Lead(property_street=street, owner_user_id="test-user")
    db.session.add(prop)
    db.session.commit()
    return prop


def _make_contact(first: str, last: str, role: str = "owner") -> Contact:
    """Create and persist a minimal Contact record."""
    contact = Contact(first_name=first, last_name=last, role=role)
    db.session.add(contact)
    db.session.commit()
    return contact


def _link(property_id: int, contact_id: int, is_primary: bool = False, role: str = "owner") -> PropertyContact:
    """Create and persist a PropertyContact link."""
    pc = PropertyContact(
        property_id=property_id,
        contact_id=contact_id,
        role=role,
        is_primary=is_primary,
    )
    db.session.add(pc)
    db.session.commit()
    return pc


def _make_hubspot_contact(hubspot_id: str, **props) -> HubSpotContact:
    """Create and persist a HubSpotContact with the given properties payload."""
    hc = HubSpotContact(
        hubspot_id=hubspot_id,
        raw_payload={"properties": props},
    )
    db.session.add(hc)
    db.session.commit()
    return hc


# ---------------------------------------------------------------------------
# GET /api/properties/?owner_name=<q>
# ---------------------------------------------------------------------------

class TestOwnerNameFilter:
    """Verifies the owner_name filter joins through property_contacts → contacts."""

    def test_returns_property_with_matching_first_name(self, client, app):
        """GET /api/properties/?owner_name=Alice returns the property linked to Alice."""
        with app.app_context():
            prop = _make_property("200 Alice Ave")
            contact = _make_contact("Alice", "Wonderland")
            _link(prop.id, contact.id, is_primary=True)
            prop_id = prop.id

        resp = client.get("/api/properties/?owner_name=Alice", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        ids = [p["id"] for p in data["leads"]]
        assert prop_id in ids

    def test_returns_property_with_matching_last_name(self, client, app):
        """GET /api/properties/?owner_name=Wonderland returns the property linked to that contact."""
        with app.app_context():
            prop = _make_property("201 Last Name Ln")
            contact = _make_contact("Bob", "Wonderland")
            _link(prop.id, contact.id, is_primary=True)
            prop_id = prop.id

        resp = client.get("/api/properties/?owner_name=Wonderland", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        ids = [p["id"] for p in data["leads"]]
        assert prop_id in ids

    def test_case_insensitive_match(self, client, app):
        """owner_name filter is case-insensitive."""
        with app.app_context():
            prop = _make_property("202 Case St")
            contact = _make_contact("Charlie", "Brown")
            _link(prop.id, contact.id, is_primary=True)
            prop_id = prop.id

        resp = client.get("/api/properties/?owner_name=charlie", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        ids = [p["id"] for p in data["leads"]]
        assert prop_id in ids

    def test_partial_name_match(self, client, app):
        """owner_name filter supports partial (substring) matching."""
        with app.app_context():
            prop = _make_property("203 Partial Pl")
            contact = _make_contact("Bartholomew", "Simpson")
            _link(prop.id, contact.id, is_primary=True)
            prop_id = prop.id

        resp = client.get("/api/properties/?owner_name=artho", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        ids = [p["id"] for p in data["leads"]]
        assert prop_id in ids

    def test_does_not_return_unlinked_property(self, client, app):
        """Properties with no matching contact are excluded from results."""
        with app.app_context():
            # Property with a non-matching contact
            prop_no_match = _make_property("204 No Match Rd")
            contact_other = _make_contact("Xavier", "Nope")
            _link(prop_no_match.id, contact_other.id)

            # Property with no contacts at all
            prop_no_contacts = _make_property("205 Empty Contacts Blvd")

            prop_no_match_id = prop_no_match.id
            prop_no_contacts_id = prop_no_contacts.id

        resp = client.get("/api/properties/?owner_name=Alice", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        ids = [p["id"] for p in data["leads"]]
        assert prop_no_match_id not in ids
        assert prop_no_contacts_id not in ids

    def test_returns_only_matching_property_not_others(self, client, app):
        """When multiple properties exist, only the one with a matching contact is returned."""
        with app.app_context():
            prop_match = _make_property("206 Match St")
            prop_no_match = _make_property("207 No Match St")

            contact_match = _make_contact("Diana", "Prince")
            contact_other = _make_contact("Clark", "Kent")

            _link(prop_match.id, contact_match.id, is_primary=True)
            _link(prop_no_match.id, contact_other.id, is_primary=True)

            prop_match_id = prop_match.id
            prop_no_match_id = prop_no_match.id

        resp = client.get("/api/properties/?owner_name=Diana", headers=_AUTH_HEADERS)
        assert resp.status_code == 200
        data = resp.get_json()
        ids = [p["id"] for p in data["leads"]]
        assert prop_match_id in ids
        assert prop_no_match_id not in ids


# ---------------------------------------------------------------------------
# POST /api/properties/<id>/contacts — primary demotion
# ---------------------------------------------------------------------------

class TestPrimaryDemotion:
    """Verifies that linking a new primary contact demotes the previous primary."""

    def test_previous_primary_demoted_when_new_primary_linked(self, client, app):
        """POST /api/properties/<id>/contacts with is_primary=true demotes existing primary."""
        with app.app_context():
            prop = _make_property("300 Primary Demotion Dr")
            contact_a = _make_contact("Alpha", "First")
            contact_b = _make_contact("Beta", "Second")

            # Link contact A as primary
            _link(prop.id, contact_a.id, is_primary=True)

            prop_id = prop.id
            contact_a_id = contact_a.id
            contact_b_id = contact_b.id

        # POST contact B as primary via HTTP
        resp = client.post(
            f"/api/properties/{prop_id}/contacts",
            json={
                "contact_id": contact_b_id,
                "role": "owner",
                "is_primary": True,
            },
        )
        assert resp.status_code == 201

        # Verify via HTTP that contact B is now primary
        resp_list = client.get(f"/api/properties/{prop_id}/contacts")
        assert resp_list.status_code == 200
        contacts_data = resp_list.get_json()

        by_id = {c["id"]: c for c in contacts_data}

        assert contact_b_id in by_id
        assert by_id[contact_b_id]["is_primary"] is True

        assert contact_a_id in by_id
        assert by_id[contact_a_id]["is_primary"] is False

    def test_previous_primary_demoted_verified_in_db(self, client, app):
        """Database record confirms previous primary is_primary=False after demotion."""
        with app.app_context():
            prop = _make_property("301 DB Demotion Ave")
            contact_a = _make_contact("Gamma", "One")
            contact_b = _make_contact("Delta", "Two")
            _link(prop.id, contact_a.id, is_primary=True)

            prop_id = prop.id
            contact_a_id = contact_a.id
            contact_b_id = contact_b.id

        resp = client.post(
            f"/api/properties/{prop_id}/contacts",
            json={
                "contact_id": contact_b_id,
                "role": "owner",
                "is_primary": True,
            },
        )
        assert resp.status_code == 201

        with app.app_context():
            link_a = PropertyContact.query.filter_by(
                property_id=prop_id, contact_id=contact_a_id
            ).one()
            link_b = PropertyContact.query.filter_by(
                property_id=prop_id, contact_id=contact_b_id
            ).one()

            assert link_a.is_primary is False
            assert link_b.is_primary is True

    def test_linking_non_primary_does_not_demote_existing_primary(self, client, app):
        """Linking a non-primary contact leaves the existing primary unchanged."""
        with app.app_context():
            prop = _make_property("302 No Demotion Blvd")
            contact_a = _make_contact("Epsilon", "Primary")
            contact_b = _make_contact("Zeta", "Secondary")
            _link(prop.id, contact_a.id, is_primary=True)

            prop_id = prop.id
            contact_a_id = contact_a.id
            contact_b_id = contact_b.id

        resp = client.post(
            f"/api/properties/{prop_id}/contacts",
            json={
                "contact_id": contact_b_id,
                "role": "owner",
                "is_primary": False,
            },
        )
        assert resp.status_code == 201

        with app.app_context():
            link_a = PropertyContact.query.filter_by(
                property_id=prop_id, contact_id=contact_a_id
            ).one()
            assert link_a.is_primary is True


# ---------------------------------------------------------------------------
# DELETE /api/properties/<id>/contacts/<contact_id> — no auto-promotion
# ---------------------------------------------------------------------------

class TestDeletePrimaryNoAutoPromotion:
    """Verifies that deleting the primary contact does not auto-promote remaining contacts."""

    def test_delete_primary_leaves_remaining_contacts_non_primary(self, client, app):
        """DELETE primary contact — remaining contact stays is_primary=False."""
        with app.app_context():
            prop = _make_property("400 No Promo St")
            primary = _make_contact("Primary", "Person")
            secondary = _make_contact("Secondary", "Person")

            _link(prop.id, primary.id, is_primary=True)
            _link(prop.id, secondary.id, is_primary=False)

            prop_id = prop.id
            primary_id = primary.id
            secondary_id = secondary.id

        # DELETE the primary contact link
        resp = client.delete(f"/api/properties/{prop_id}/contacts/{primary_id}")
        assert resp.status_code == 204

        # Verify via HTTP that secondary is still not primary
        resp_list = client.get(f"/api/properties/{prop_id}/contacts")
        assert resp_list.status_code == 200
        contacts_data = resp_list.get_json()

        assert len(contacts_data) == 1
        assert contacts_data[0]["id"] == secondary_id
        assert contacts_data[0]["is_primary"] is False

    def test_delete_primary_link_removed_from_db(self, client, app):
        """After DELETE, the primary PropertyContact record is gone from the database."""
        with app.app_context():
            prop = _make_property("401 Link Gone Rd")
            primary = _make_contact("Gone", "Primary")
            secondary = _make_contact("Still", "Here")

            _link(prop.id, primary.id, is_primary=True)
            _link(prop.id, secondary.id, is_primary=False)

            prop_id = prop.id
            primary_id = primary.id
            secondary_id = secondary.id

        resp = client.delete(f"/api/properties/{prop_id}/contacts/{primary_id}")
        assert resp.status_code == 204

        with app.app_context():
            # Primary link must be gone
            assert PropertyContact.query.filter_by(
                property_id=prop_id, contact_id=primary_id
            ).first() is None

            # Secondary link must still exist and remain non-primary
            link_secondary = PropertyContact.query.filter_by(
                property_id=prop_id, contact_id=secondary_id
            ).one()
            assert link_secondary.is_primary is False

    def test_delete_primary_contact_record_still_exists(self, client, app):
        """Unlinking the primary contact does NOT delete the Contact record itself."""
        with app.app_context():
            prop = _make_property("402 Contact Preserved Ln")
            primary = _make_contact("Preserved", "Contact")
            _link(prop.id, primary.id, is_primary=True)

            prop_id = prop.id
            primary_id = primary.id

        resp = client.delete(f"/api/properties/{prop_id}/contacts/{primary_id}")
        assert resp.status_code == 204

        with app.app_context():
            # The Contact record itself must still exist
            assert Contact.query.get(primary_id) is not None

    def test_delete_nonexistent_link_returns_404(self, client, app):
        """DELETE a contact that is not linked to the property returns 404."""
        with app.app_context():
            prop = _make_property("403 Not Linked Ave")
            contact = _make_contact("Not", "Linked")

            prop_id = prop.id
            contact_id = contact.id

        resp = client.delete(f"/api/properties/{prop_id}/contacts/{contact_id}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# HubSpot matcher end-to-end
# ---------------------------------------------------------------------------

class TestHubSpotMatcherEndToEnd:
    """End-to-end tests for HubSpotMatcherService.match_contact()."""

    def test_email_match_returns_high_confidence(self, app):
        """Matcher finds Contact by email and returns HIGH confidence match."""
        with app.app_context():
            prop = _make_property("500 Email Match Blvd")
            contact = _make_contact("Email", "Matcher")
            email = ContactEmail(contact_id=contact.id, value="emailmatch@example.com", label="personal")
            db.session.add(email)
            _link(prop.id, contact.id, is_primary=True)
            db.session.commit()

            hc = _make_hubspot_contact(
                "hs-email-001",
                email="emailmatch@example.com",
                firstname="Email",
                lastname="Matcher",
            )

            svc = HubSpotMatcherService()
            match = svc.match_contact(hc)
            db.session.commit()

            assert match.confidence == "HIGH"
            assert match.matching_criteria == "email_match"
            assert match.internal_record_id == prop.id
            assert match.hubspot_id == "hs-email-001"

    def test_email_match_case_insensitive(self, app):
        """Email matching is case-insensitive."""
        with app.app_context():
            prop = _make_property("501 Case Email St")
            contact = _make_contact("Case", "Email")
            email = ContactEmail(contact_id=contact.id, value="CaseEmail@Example.COM", label="work")
            db.session.add(email)
            _link(prop.id, contact.id, is_primary=True)
            db.session.commit()

            hc = _make_hubspot_contact(
                "hs-email-002",
                email="caseemail@example.com",
            )

            svc = HubSpotMatcherService()
            match = svc.match_contact(hc)
            db.session.commit()

            assert match.confidence == "HIGH"
            assert match.matching_criteria == "email_match"

    def test_phone_match_returns_high_confidence(self, app):
        """Matcher finds Contact by phone (digits-only normalized) and returns HIGH confidence."""
        with app.app_context():
            prop = _make_property("502 Phone Match Dr")
            contact = _make_contact("Phone", "Matcher")
            phone = ContactPhone(contact_id=contact.id, value="(312) 555-7890", label="mobile")
            db.session.add(phone)
            _link(prop.id, contact.id, is_primary=True)
            db.session.commit()

            # HubSpot sends the phone in a different format — digits should still match
            hc = _make_hubspot_contact(
                "hs-phone-001",
                phone="3125557890",
            )

            svc = HubSpotMatcherService()
            match = svc.match_contact(hc)
            db.session.commit()

            assert match.confidence == "HIGH"
            assert match.matching_criteria == "phone_match"
            assert match.internal_record_id == prop.id

    def test_phone_match_with_formatted_hubspot_phone(self, app):
        """Phone match works when HubSpot phone has formatting characters."""
        with app.app_context():
            prop = _make_property("503 Formatted Phone Ave")
            contact = _make_contact("Formatted", "Phone")
            phone = ContactPhone(contact_id=contact.id, value="7735551234", label="home")
            db.session.add(phone)
            _link(prop.id, contact.id, is_primary=True)
            db.session.commit()

            hc = _make_hubspot_contact(
                "hs-phone-002",
                phone="(773) 555-1234",
            )

            svc = HubSpotMatcherService()
            match = svc.match_contact(hc)
            db.session.commit()

            assert match.confidence == "HIGH"
            assert match.matching_criteria == "phone_match"

    def test_name_property_match_returns_medium_confidence(self, app):
        """Matcher finds Contact by first+last name and returns MEDIUM confidence."""
        with app.app_context():
            prop = _make_property("504 Name Match Ln")
            contact = _make_contact("NameFirst", "NameLast")
            _link(prop.id, contact.id, is_primary=True)
            db.session.commit()

            # No email or phone — only name match
            hc = _make_hubspot_contact(
                "hs-name-001",
                firstname="NameFirst",
                lastname="NameLast",
            )

            svc = HubSpotMatcherService()
            match = svc.match_contact(hc)
            db.session.commit()

            assert match.confidence == "MEDIUM"
            assert match.matching_criteria == "name_property_match"
            assert match.internal_record_id == prop.id

    def test_name_match_is_case_insensitive(self, app):
        """Name matching is case-insensitive."""
        with app.app_context():
            prop = _make_property("505 Case Name Blvd")
            contact = _make_contact("UPPERCASE", "LASTNAME")
            _link(prop.id, contact.id, is_primary=True)
            db.session.commit()

            hc = _make_hubspot_contact(
                "hs-name-002",
                firstname="uppercase",
                lastname="lastname",
            )

            svc = HubSpotMatcherService()
            match = svc.match_contact(hc)
            db.session.commit()

            assert match.confidence == "MEDIUM"
            assert match.matching_criteria == "name_property_match"

    def test_email_match_takes_priority_over_phone(self, app):
        """When both email and phone match, email match (HIGH) is returned first."""
        with app.app_context():
            prop = _make_property("506 Priority Test Rd")
            contact = _make_contact("Priority", "Test")
            email = ContactEmail(contact_id=contact.id, value="priority@example.com", label="personal")
            phone = ContactPhone(contact_id=contact.id, value="5555550001", label="mobile")
            db.session.add(email)
            db.session.add(phone)
            _link(prop.id, contact.id, is_primary=True)
            db.session.commit()

            hc = _make_hubspot_contact(
                "hs-priority-001",
                email="priority@example.com",
                phone="5555550001",
                firstname="Priority",
                lastname="Test",
            )

            svc = HubSpotMatcherService()
            match = svc.match_contact(hc)
            db.session.commit()

            assert match.confidence == "HIGH"
            assert match.matching_criteria == "email_match"

    def test_no_match_creates_new_contact_record(self, app):
        """When no match is found, a new Contact record is created."""
        with app.app_context():
            initial_count = Contact.query.count()

            hc = _make_hubspot_contact(
                "hs-nomatch-001",
                email="totally.new.person@example.com",
                phone="9999999999",
                firstname="Brand",
                lastname="New",
            )

            svc = HubSpotMatcherService()
            match = svc.match_contact(hc)
            db.session.commit()

            final_count = Contact.query.count()
            assert final_count == initial_count + 1
            assert match.confidence == "UNMATCHED"

    def test_match_linked_to_correct_property_via_email(self, app):
        """Email match links the HubSpot contact to the correct property."""
        with app.app_context():
            prop_a = _make_property("507 Correct Property A")
            prop_b = _make_property("508 Wrong Property B")

            contact_a = _make_contact("Correct", "Owner")
            contact_b = _make_contact("Wrong", "Owner")

            email_a = ContactEmail(contact_id=contact_a.id, value="correct@example.com", label="personal")
            db.session.add(email_a)

            _link(prop_a.id, contact_a.id, is_primary=True)
            _link(prop_b.id, contact_b.id, is_primary=True)
            db.session.commit()

            hc = _make_hubspot_contact(
                "hs-correct-001",
                email="correct@example.com",
            )

            svc = HubSpotMatcherService()
            match = svc.match_contact(hc)
            db.session.commit()

            assert match.internal_record_id == prop_a.id
            assert match.internal_record_id != prop_b.id
