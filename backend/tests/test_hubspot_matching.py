"""Property-based tests for HubSpotMatcherService match confidence assignment.

Properties verified:
  5. Deal match confidence is deterministic — PIN→HIGH, address→MEDIUM, no match→UNMATCHED
  6. Contact match confidence assignment — email→HIGH, phone→HIGH, name→MEDIUM

Both properties require a Flask app context because match_deal / match_contact
write Lead and HubSpotMatch rows to the database.  The ``app`` fixture from
conftest.py provides an in-memory SQLite database with all tables created.
"""
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.lead import Lead
from app.models.hubspot_deal import HubSpotDeal
from app.models.hubspot_contact import HubSpotContact
from app.services.hubspot_matcher_service import HubSpotMatcherService

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ASCII-only alphabets — SQLite's lower()/upper() only handles ASCII, so all
# strategies that feed into db.func.lower() comparisons must stay ASCII.
# ---------------------------------------------------------------------------

_ASCII_ALPHA = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ASCII_LOWER = "abcdefghijklmnopqrstuvwxyz"
_ASCII_DIGITS = "0123456789"

# A PIN is a non-empty string of digits (up to 14 chars), matching the real
# Cook County format.
_pin_st = st.text(alphabet=_ASCII_DIGITS, min_size=5, max_size=14)

# A street address: "<number> <word> St"
_street_number_st = st.integers(min_value=1, max_value=9999).map(str)
_street_name_st = st.text(alphabet=_ASCII_ALPHA, min_size=3, max_size=20)
_address_st = st.builds(
    lambda num, name: f"{num} {name} St",
    _street_number_st,
    _street_name_st,
)

# Email: lowercase ASCII local-part + fixed domain.
# SQLite's lower() only handles ASCII, so we restrict to lowercase to avoid
# false negatives in the db.func.lower() comparison used by match_contact.
_local_st = st.text(alphabet=_ASCII_LOWER + _ASCII_DIGITS, min_size=3, max_size=12)
_domain_st = st.sampled_from(["example.com", "test.org", "mail.net", "foo.io"])
_email_st = st.builds(lambda local, domain: f"{local}@{domain}", _local_st, _domain_st)

# Phone: 10-digit US numbers.
_phone_digits_st = st.integers(min_value=2000000000, max_value=9999999999).map(str)
_phone_formatted_st = _phone_digits_st.map(
    lambda d: f"({d[:3]}) {d[3:6]}-{d[6:]}"
)

# Names — ASCII letters only so SQLite lower() comparisons work correctly.
_name_part_st = st.text(alphabet=_ASCII_ALPHA, min_size=2, max_size=15)


# ---------------------------------------------------------------------------
# Helper: build a minimal HubSpotDeal ORM object (not persisted)
# ---------------------------------------------------------------------------

def _make_deal(hubspot_id: str, pin: str | None, address: str | None) -> HubSpotDeal:
    """Return an unsaved HubSpotDeal with the given PIN / address in raw_payload."""
    props: dict = {}
    if pin:
        props["county_assessor_pin"] = pin
    if address:
        props["dealname"] = address
    return HubSpotDeal(
        hubspot_id=hubspot_id,
        raw_payload={"properties": props},
    )


def _make_contact(
    hubspot_id: str,
    email: str | None,
    phone: str | None,
    first_name: str | None,
    last_name: str | None,
) -> HubSpotContact:
    """Return an unsaved HubSpotContact with the given fields in raw_payload."""
    props: dict = {}
    if email:
        props["email"] = email
    if phone:
        props["phone"] = phone
    if first_name:
        props["firstname"] = first_name
    if last_name:
        props["lastname"] = last_name
    return HubSpotContact(
        hubspot_id=hubspot_id,
        raw_payload={"properties": props},
    )


# ---------------------------------------------------------------------------
# Property 5: Deal match confidence is deterministic
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 5: Match confidence assignment is deterministic


class TestDealMatchConfidence:
    """Property 5 — deal match confidence follows the PIN > address > UNMATCHED priority."""

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(pin=_pin_st, address=_address_st)
    def test_pin_match_yields_high_confidence(self, app, pin, address):
        """When a deal's PIN matches an existing Lead, confidence must be HIGH.

        **Validates: Requirements 10.1, 10.2, 10.3, 10.4**
        """
        with app.app_context():
            # Create a Lead with the matching PIN.
            lead = Lead(county_assessor_pin=pin, property_street=address)
            db.session.add(lead)
            db.session.flush()

            deal = _make_deal(hubspot_id=f"pin-{pin}", pin=pin, address=address)
            db.session.add(deal)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)
            db.session.flush()

            assert match.confidence == "HIGH", (
                f"Expected HIGH for PIN match, got {match.confidence}"
            )
            assert match.matching_criteria == "pin_match"

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(address=_address_st, unrelated_pin=_pin_st)
    def test_address_only_match_yields_medium_confidence(self, app, address, unrelated_pin):
        """When a deal has no PIN match but the address matches, confidence must be MEDIUM.

        **Validates: Requirements 10.1, 10.2, 10.3, 10.4**
        """
        with app.app_context():
            # Create a Lead with the matching address but a different PIN.
            lead = Lead(
                property_street=address,
                county_assessor_pin=unrelated_pin + "X",  # guaranteed non-match
            )
            db.session.add(lead)
            db.session.flush()

            # Deal has a different PIN (no PIN match) but the same address.
            deal = _make_deal(
                hubspot_id=f"addr-{address[:10]}",
                pin=unrelated_pin + "Y",  # different from lead's PIN
                address=address,
            )
            db.session.add(deal)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)
            db.session.flush()

            assert match.confidence == "MEDIUM", (
                f"Expected MEDIUM for address-only match, got {match.confidence}"
            )
            assert match.matching_criteria == "address_match"

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(pin=_pin_st, address=_address_st)
    def test_no_match_yields_unmatched_confidence(self, app, pin, address):
        """When a deal has no PIN or address match, confidence must be UNMATCHED.

        **Validates: Requirements 10.1, 10.2, 10.3, 10.4**
        """
        with app.app_context():
            # No Lead exists in the DB — guaranteed no match.
            deal = _make_deal(
                hubspot_id=f"nomatch-{pin}",
                pin=pin,
                address=address,
            )
            db.session.add(deal)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)
            db.session.flush()

            assert match.confidence == "UNMATCHED", (
                f"Expected UNMATCHED when no Lead exists, got {match.confidence}"
            )

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(pin=_pin_st, address=_address_st)
    def test_same_deal_always_produces_same_confidence(self, app, pin, address):
        """Calling match_deal twice on the same deal must return the same confidence.

        **Validates: Requirements 10.1, 10.2, 10.3, 10.4**
        """
        with app.app_context():
            lead = Lead(county_assessor_pin=pin, property_street=address)
            db.session.add(lead)
            db.session.flush()

            deal = _make_deal(hubspot_id=f"det-{pin}", pin=pin, address=address)
            db.session.add(deal)
            db.session.flush()

            svc = HubSpotMatcherService()
            match1 = svc.match_deal(deal)
            db.session.flush()
            confidence1 = match1.confidence

            # Second call — _upsert_match updates the existing record.
            match2 = svc.match_deal(deal)
            db.session.flush()
            confidence2 = match2.confidence

            assert confidence1 == confidence2, (
                f"Confidence changed between calls: {confidence1} → {confidence2}"
            )

            db.session.rollback()

    def test_normalize_address_used_in_address_match(self, app):
        """normalize_address is applied before comparing — abbreviated and full forms match.

        **Validates: Requirements 10.5**
        """
        with app.app_context():
            # Lead stored with abbreviated form.
            lead = Lead(property_street="123 Main St")
            db.session.add(lead)
            db.session.flush()

            # Deal uses the expanded form — should still match after normalization.
            deal = _make_deal(
                hubspot_id="abbrev-test",
                pin=None,
                address="123 Main Street",
            )
            db.session.add(deal)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)
            db.session.flush()

            assert match.confidence == "MEDIUM"
            assert match.matching_criteria == "address_match"

            db.session.rollback()


# ---------------------------------------------------------------------------
# Property 6: Contact match confidence assignment
# ---------------------------------------------------------------------------

# Feature: hubspot-crm-migration, Property 6: Contact match confidence assignment


class TestContactMatchConfidence:
    """Property 6 — contact match confidence follows the email > phone > name priority."""

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(email=_email_st, first=_name_part_st, last=_name_part_st)
    def test_email_match_yields_high_confidence(self, app, email, first, last):
        """When a contact's email matches an existing Lead's email, confidence must be HIGH.

        **Validates: Requirements 11.1, 11.2, 11.3**
        """
        with app.app_context():
            lead = Lead(email_1=email, owner_first_name=first, owner_last_name=last)
            db.session.add(lead)
            db.session.flush()

            contact = _make_contact(
                hubspot_id=f"email-{email[:10]}",
                email=email,
                phone=None,
                first_name=first,
                last_name=last,
            )
            db.session.add(contact)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_contact(contact)
            db.session.flush()

            assert match.confidence == "HIGH", (
                f"Expected HIGH for email match, got {match.confidence}"
            )
            assert match.matching_criteria == "email_match"

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(phone_digits=_phone_digits_st, first=_name_part_st, last=_name_part_st)
    def test_phone_match_yields_high_confidence(self, app, phone_digits, first, last):
        """When a contact's phone (digits only) matches an existing Lead's phone, confidence must be HIGH.

        **Validates: Requirements 11.1, 11.2, 11.3**
        """
        with app.app_context():
            # Store the phone in a formatted form on the Lead.
            formatted = f"({phone_digits[:3]}) {phone_digits[3:6]}-{phone_digits[6:]}"
            lead = Lead(
                phone_1=formatted,
                owner_first_name=first + "X",  # different name — forces phone path
                owner_last_name=last + "X",
            )
            db.session.add(lead)
            db.session.flush()

            # Contact has no email, different name, but matching phone digits.
            contact = _make_contact(
                hubspot_id=f"phone-{phone_digits}",
                email=None,
                phone=phone_digits,  # raw digits — normalize_phone will match
                first_name=first,
                last_name=last,
            )
            db.session.add(contact)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_contact(contact)
            db.session.flush()

            assert match.confidence == "HIGH", (
                f"Expected HIGH for phone match, got {match.confidence}"
            )
            assert match.matching_criteria == "phone_match"

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(first=_name_part_st, last=_name_part_st, address=_address_st)
    def test_name_only_match_yields_medium_confidence(self, app, first, last, address):
        """When only a name match is found (no email/phone), confidence must be MEDIUM.

        **Validates: Requirements 11.1, 11.2, 11.3**
        """
        with app.app_context():
            lead = Lead(
                owner_first_name=first,
                owner_last_name=last,
                property_street=address,
            )
            db.session.add(lead)
            db.session.flush()

            # Contact has no email, no phone — only name.
            contact = _make_contact(
                hubspot_id=f"name-{first[:5]}{last[:5]}",
                email=None,
                phone=None,
                first_name=first,
                last_name=last,
            )
            db.session.add(contact)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_contact(contact)
            db.session.flush()

            assert match.confidence == "MEDIUM", (
                f"Expected MEDIUM for name-only match, got {match.confidence}"
            )
            assert match.matching_criteria == "name_property_match"

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(email=_email_st)
    def test_no_match_yields_unmatched_confidence(self, app, email):
        """When no Lead matches the contact, confidence must be UNMATCHED.

        **Validates: Requirements 11.1, 11.2, 11.3**
        """
        with app.app_context():
            # No Lead in DB — guaranteed no match.
            contact = _make_contact(
                hubspot_id=f"cnomatch-{email[:10]}",
                email=email,
                phone=None,
                first_name=None,
                last_name=None,
            )
            db.session.add(contact)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_contact(contact)
            db.session.flush()

            assert match.confidence == "UNMATCHED", (
                f"Expected UNMATCHED when no Lead exists, got {match.confidence}"
            )

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(email=_email_st, first=_name_part_st, last=_name_part_st)
    def test_email_takes_priority_over_phone_and_name(self, app, email, first, last):
        """Email match must take priority over phone and name matches.

        **Validates: Requirements 11.1, 11.2, 11.3**
        """
        with app.app_context():
            phone_digits = "5551234567"
            formatted_phone = "(555) 123-4567"

            # Lead matches on all three criteria.
            lead = Lead(
                email_1=email,
                phone_1=formatted_phone,
                owner_first_name=first,
                owner_last_name=last,
            )
            db.session.add(lead)
            db.session.flush()

            contact = _make_contact(
                hubspot_id=f"eprio-{email[:8]}",
                email=email,
                phone=phone_digits,
                first_name=first,
                last_name=last,
            )
            db.session.add(contact)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_contact(contact)
            db.session.flush()

            # Email is checked first — must win.
            assert match.confidence == "HIGH"
            assert match.matching_criteria == "email_match"

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(phone_digits=_phone_digits_st, first=_name_part_st, last=_name_part_st)
    def test_phone_takes_priority_over_name(self, app, phone_digits, first, last):
        """Phone match must take priority over name-only match.

        **Validates: Requirements 11.1, 11.2, 11.3**
        """
        with app.app_context():
            formatted = f"({phone_digits[:3]}) {phone_digits[3:6]}-{phone_digits[6:]}"
            lead = Lead(
                phone_1=formatted,
                owner_first_name=first,
                owner_last_name=last,
            )
            db.session.add(lead)
            db.session.flush()

            # No email — phone should win over name.
            contact = _make_contact(
                hubspot_id=f"pprio-{phone_digits}",
                email=None,
                phone=phone_digits,
                first_name=first,
                last_name=last,
            )
            db.session.add(contact)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_contact(contact)
            db.session.flush()

            assert match.confidence == "HIGH"
            assert match.matching_criteria == "phone_match"

            db.session.rollback()
