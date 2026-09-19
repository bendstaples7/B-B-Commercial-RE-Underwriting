"""Property-based tests for HubSpotMatcherService match confidence assignment.

Properties verified:
  5. Deal match confidence is deterministic — PIN→HIGH, address→MEDIUM, no match→UNMATCHED
  6. Contact match confidence assignment — email→HIGH, phone→HIGH, name→MEDIUM

Both properties require a Flask app context because match_deal / match_contact
write Lead and HubSpotMatch rows to the database.  The ``app`` fixture from
conftest.py provides an in-memory SQLite database with all tables created.
"""
import pytest
from unittest.mock import patch
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.lead import Lead
from app.models.hubspot_deal import HubSpotDeal
from app.models.hubspot_contact import HubSpotContact
from app.services.hubspot_matcher_service import HubSpotMatcherService

# match_deal → complete_property_address can call Cook GIS for street-only
# placeholders. Hypothesis property tests must never hit real HTTP.
@pytest.fixture(autouse=True)
def _stub_gis_street_fill_for_matcher_tests():
    with patch(
        'app.services.property_address_service._gis_fill_from_street',
        return_value=None,
    ):
        yield

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
            match = svc.match_deal(deal, stage_label_map={})
            db.session.flush()

            assert match.confidence == "HIGH", (
                f"Expected HIGH for PIN match, got {match.confidence}"
            )
            assert match.matching_criteria == "pin_match"
            assert match.status == "pending"
            assert match.internal_record_id == lead.id

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
            match = svc.match_deal(deal, stage_label_map={})
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
            match = svc.match_deal(deal, stage_label_map={})
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
            match1 = svc.match_deal(deal, stage_label_map={})
            db.session.flush()
            confidence1 = match1.confidence

            # Second call — _upsert_match updates the existing record.
            match2 = svc.match_deal(deal, stage_label_map={})
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
            match = svc.match_deal(deal, stage_label_map={})
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


class TestAmbiguousPinMatch:
    def test_duplicate_pin_stays_pending(self, app):
        """Two leads with the same PIN must not auto-attach a HubSpot deal."""
        with app.app_context():
            pin = "123456789000"
            lead_a = Lead(county_assessor_pin=pin, property_street="10 Pin A St")
            lead_b = Lead(county_assessor_pin=pin, property_street="10 Pin B St")
            db.session.add_all([lead_a, lead_b])
            db.session.flush()

            deal = _make_deal(
                hubspot_id="dup-pin-deal",
                pin=pin,
                address="10 Somewhere Else",
            )
            db.session.add(deal)
            db.session.flush()

            match = HubSpotMatcherService().match_deal(deal, stage_label_map={})
            db.session.flush()

            assert match.confidence == "HIGH"
            assert match.matching_criteria == "pin_match"
            assert match.status == "pending"
            assert match.internal_record_id is None

            db.session.rollback()

    def test_unique_pin_stays_pending_and_does_not_write_status(self, app):
        """A 1:1 PIN hit must not confirm or copy HubSpot stage onto the lead."""
        with app.app_context():
            pin = "123456789111"
            lead = Lead(
                county_assessor_pin=pin,
                property_street="10 Unique Pin St",
                lead_status="skip_trace",
                lead_score=18.0,
            )
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id

            deal = HubSpotDeal(
                hubspot_id="unique-pin-no-enrich",
                raw_payload={
                    "properties": {
                        "county_assessor_pin": pin,
                        "dealname": "999 Conflicting Blvd",
                        "dealstage": "closedwon",
                    },
                },
            )
            db.session.add(deal)
            db.session.flush()

            match = HubSpotMatcherService().match_deal(
                deal,
                stage_label_map={"closedwon": "Deal Won"},
            )
            db.session.flush()

            assert match.status == "pending"
            assert match.confidence == "HIGH"
            assert match.matching_criteria == "pin_match"
            assert match.internal_record_id == lead_id
            refreshed = db.session.get(Lead, lead_id)
            assert refreshed.lead_status == "skip_trace"
            assert refreshed.lead_score == 18.0
            assert refreshed.property_street == "10 Unique Pin St"

            db.session.rollback()

    def test_confirming_unique_pin_then_copies_hubspot_stage(self, app):
        """Pending unique PIN must not write; confirm is what applies HubSpot stage."""
        with app.app_context():
            pin = "123456789222"
            lead = Lead(
                county_assessor_pin=pin,
                property_street="11 Unique Pin Confirm St",
                lead_status="skip_trace",
                lead_score=18.0,
            )
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id
            deal = HubSpotDeal(
                hubspot_id="unique-pin-confirm-enrich",
                raw_payload={
                    "properties": {
                        "county_assessor_pin": pin,
                        "dealname": "11 Unique Pin Confirm St",
                        "dealstage": "closedwon",
                    },
                },
            )
            db.session.add(deal)
            db.session.flush()
            svc = HubSpotMatcherService()
            match = svc.match_deal(
                deal, stage_label_map={"closedwon": "Deal Won"},
            )
            db.session.flush()
            assert match.status == "pending"
            assert db.session.get(Lead, lead_id).lead_status == "skip_trace"

            match.status = "confirmed"
            svc.apply_confirmed_match(
                match, stage_label_map={"closedwon": "Deal Won"},
            )
            db.session.flush()
            assert db.session.get(Lead, lead_id).lead_status == "deal_won"
            db.session.rollback()


class TestDedupIdentityMatch:
    def test_identity_fallback_stays_pending_and_does_not_enrich(self, app):
        """Name+street identity hits must not auto-confirm or overwrite the lead."""
        with app.app_context():
            lead = Lead(
                property_street='10 Identity St',
                owner_first_name='Jane',
                owner_last_name='Doe',
                owner_user_id='other-user',
                lead_score=12.0,
            )
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id
            original_score = lead.lead_score

            deal = HubSpotDeal(
                hubspot_id='identity-fallback-deal',
                raw_payload={
                    'properties': {
                        'dealname': '10 Identity St',
                        'owner_first_name': 'Jane',
                        'owner_last_name': 'Doe',
                    },
                },
            )
            db.session.add(deal)
            db.session.flush()

            with patch.object(
                HubSpotMatcherService,
                '_address_matches_for',
                return_value=[],
            ), patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value='other-user',
            ):
                match = HubSpotMatcherService().match_deal(deal, stage_label_map={})
            db.session.flush()

            assert match.confidence == 'MEDIUM'
            assert match.matching_criteria == 'address_match'
            assert match.status == 'pending'
            assert match.internal_record_id == lead_id
            refreshed = db.session.get(Lead, lead_id)
            assert refreshed.lead_score == original_score
            assert refreshed.source is None or refreshed.source != 'hubspot_overwrite'

            db.session.rollback()


class TestAmbiguousContactPropertyMatch:
    def test_email_match_with_two_properties_stays_unattached(self, app):
        """A person linked to two leads must not auto-attach to whichever row comes first."""
        from app.models.contact import Contact
        from app.models.contact_email import ContactEmail
        from app.models.property_contact import PropertyContact

        with app.app_context():
            lead_a = Lead(property_street='10 A St', owner_user_id='user-a')
            lead_b = Lead(property_street='20 B St', owner_user_id='user-b')
            db.session.add_all([lead_a, lead_b])
            db.session.flush()

            person = Contact(first_name='Pat', last_name='Owner')
            db.session.add(person)
            db.session.flush()
            db.session.add(ContactEmail(
                contact_id=person.id, value='pat@example.com', label='work',
            ))
            db.session.add_all([
                PropertyContact(
                    property_id=lead_a.id, contact_id=person.id,
                    role='owner', is_primary=True,
                ),
                PropertyContact(
                    property_id=lead_b.id, contact_id=person.id,
                    role='owner', is_primary=False,
                ),
            ])
            db.session.flush()

            hs = _make_contact('ambig-email', 'pat@example.com', None, None, None)
            db.session.add(hs)
            db.session.flush()

            match = HubSpotMatcherService().match_contact(hs)
            db.session.flush()

            assert match.confidence == 'HIGH'
            assert match.matching_criteria == 'email_match'
            assert match.status == 'pending'
            assert match.internal_record_id is None

            db.session.rollback()

    def test_duplicate_lead_email_stays_unattached(self, app):
        """Two leads sharing email_1 must not auto-attach a HubSpot contact."""
        with app.app_context():
            lead_a = Lead(
                email_1='shared@example.com',
                property_street='10 Shared A',
                owner_user_id='user-a',
            )
            lead_b = Lead(
                email_1='shared@example.com',
                property_street='20 Shared B',
                owner_user_id='user-b',
            )
            db.session.add_all([lead_a, lead_b])
            db.session.flush()

            hs = _make_contact('dup-email', 'shared@example.com', None, None, None)
            db.session.add(hs)
            db.session.flush()

            match = HubSpotMatcherService().match_contact(hs)
            db.session.flush()

            assert match.confidence == 'HIGH'
            assert match.matching_criteria == 'email_match'
            assert match.status == 'pending'
            assert match.internal_record_id is None

            db.session.rollback()

    def test_two_contacts_same_email_stays_unattached(self, app):
        """Two people sharing an email, each on a different lead, stay unattached."""
        from app.models.contact import Contact
        from app.models.contact_email import ContactEmail
        from app.models.property_contact import PropertyContact

        with app.app_context():
            lead_a = Lead(property_street='10 A St', owner_user_id='user-a')
            lead_b = Lead(property_street='20 B St', owner_user_id='user-b')
            db.session.add_all([lead_a, lead_b])
            db.session.flush()

            pat = Contact(first_name='Pat', last_name='A')
            kim = Contact(first_name='Kim', last_name='B')
            db.session.add_all([pat, kim])
            db.session.flush()
            db.session.add_all([
                ContactEmail(contact_id=pat.id, value='shared2@example.com', label='work'),
                ContactEmail(contact_id=kim.id, value='shared2@example.com', label='work'),
                PropertyContact(
                    property_id=lead_a.id, contact_id=pat.id,
                    role='owner', is_primary=True,
                ),
                PropertyContact(
                    property_id=lead_b.id, contact_id=kim.id,
                    role='owner', is_primary=True,
                ),
            ])
            db.session.flush()

            hs = _make_contact('two-people-email', 'shared2@example.com', None, None, None)
            db.session.add(hs)
            db.session.flush()

            match = HubSpotMatcherService().match_contact(hs)
            db.session.flush()

            assert match.confidence == 'HIGH'
            assert match.matching_criteria == 'email_match'
            assert match.status == 'pending'
            assert match.internal_record_id is None

            db.session.rollback()


class TestHubSpotImportOwnership:
    def test_unmatched_placeholder_gets_import_owner(self, app):
        """New HubSpot leads must get an owner so queues can show them."""
        with app.app_context():
            deal = _make_deal(
                hubspot_id='placeholder-owner-deal',
                pin=None,
                address='88 New HubSpot Ave',
            )
            db.session.add(deal)
            db.session.flush()

            with patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value='importer-user',
            ):
                match = HubSpotMatcherService().match_deal(deal, stage_label_map={})
            db.session.flush()

            assert match.internal_record_type == 'lead'
            lead = db.session.get(Lead, match.internal_record_id)
            assert lead is not None
            assert lead.source == 'hubspot_import'
            assert lead.owner_user_id == 'importer-user'

            db.session.rollback()

    def test_unattended_import_does_not_assign_first_non_admin_user(self, app):
        """Celery matching must not dump new leads onto whichever User row is first."""
        from tests.conftest import seed_user

        with app.app_context():
            seed_user('first-user', is_admin=False, email='first-user@example.com')
            with patch(
                'app.services.cook_county_prospect_config.resolve_cook_county_prospect_owner_user_id',
                side_effect=ValueError('unset'),
            ):
                assert HubSpotMatcherService._hubspot_import_owner_user_id() is None
            db.session.rollback()

    def test_unique_address_does_not_auto_confirm_foreign_owner(self, app):
        """A 1:1 address hit on someone else's lead must not attach or write status."""
        with app.app_context():
            lead = Lead(
                property_street='10 Foreign Ave',
                owner_user_id='other-user',
                lead_status='skip_trace',
                lead_score=21.0,
            )
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id

            deal = _make_deal(
                hubspot_id='foreign-address-deal',
                pin=None,
                address='10 Foreign Ave',
            )
            db.session.add(deal)
            db.session.flush()

            with patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value='importer-user',
            ):
                match = HubSpotMatcherService().match_deal(
                    deal,
                    stage_label_map={'closedwon': 'Deal Won'},
                )
            db.session.flush()

            assert match.internal_record_id != lead_id
            refreshed = db.session.get(Lead, lead_id)
            assert refreshed.lead_status == 'skip_trace'
            assert refreshed.lead_score == 21.0
            assert refreshed.owner_user_id == 'other-user'
            placeholder = db.session.get(Lead, match.internal_record_id)
            assert placeholder is not None
            assert placeholder.owner_user_id == 'importer-user'

            db.session.rollback()

    def test_unique_address_unattended_import_does_not_auto_confirm_owned_lead(self, app):
        """Celery/unattended import must not copy HubSpot stage onto an owned lead."""
        with app.app_context():
            lead = Lead(
                property_street='11 Owned Ave',
                owner_user_id='other-user',
                lead_status='skip_trace',
                lead_score=19.0,
            )
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id

            deal = _make_deal(
                hubspot_id='unattended-address-deal',
                pin=None,
                address='11 Owned Ave',
            )
            db.session.add(deal)
            db.session.flush()

            with patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value=None,
            ):
                match = HubSpotMatcherService().match_deal(
                    deal,
                    stage_label_map={'closedwon': 'Deal Won'},
                )
            db.session.flush()

            assert match.status == 'pending'
            assert match.internal_record_id != lead_id
            refreshed = db.session.get(Lead, lead_id)
            assert refreshed.lead_status == 'skip_trace'
            assert refreshed.lead_score == 19.0
            assert refreshed.owner_user_id == 'other-user'

            db.session.rollback()

    def test_unique_address_same_owner_still_auto_confirms(self, app):
        """A 1:1 address hit on the importer's own lead may still auto-confirm."""
        with app.app_context():
            lead = Lead(
                property_street='12 Own Ave',
                owner_user_id='importer-user',
                lead_status='skip_trace',
                lead_score=22.0,
            )
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id

            deal = _make_deal(
                hubspot_id='own-address-deal',
                pin=None,
                address='12 Own Ave',
            )
            db.session.add(deal)
            db.session.flush()

            with patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value='importer-user',
            ):
                match = HubSpotMatcherService().match_deal(
                    deal,
                    stage_label_map={'closedwon': 'Deal Won'},
                )
            db.session.flush()

            assert match.status == 'confirmed'
            assert match.internal_record_id == lead_id

            db.session.rollback()

    def test_unique_address_unowned_unattended_still_auto_confirms(self, app):
        """Unowned unique address matches may auto-confirm even without an importer."""
        with app.app_context():
            lead = Lead(
                property_street='13 Open Ave',
                owner_user_id=None,
                lead_status='skip_trace',
                lead_score=11.0,
            )
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id

            deal = _make_deal(
                hubspot_id='unowned-address-deal',
                pin=None,
                address='13 Open Ave',
            )
            db.session.add(deal)
            db.session.flush()

            with patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value=None,
            ):
                match = HubSpotMatcherService().match_deal(
                    deal,
                    stage_label_map={'closedwon': 'Deal Won'},
                )
            db.session.flush()

            assert match.status == 'confirmed'
            assert match.internal_record_id == lead_id

            db.session.rollback()

    def test_confirmed_match_is_not_retargeted_or_enriched_onto_new_pin_lead(self, app):
        """A later unique PIN hit must not move a confirmed deal onto another lead."""
        with app.app_context():
            pin = '555666777888'
            lead_a = Lead(
                county_assessor_pin=pin,
                property_street='20 Locked Ave',
                owner_user_id='importer-user',
                lead_status='skip_trace',
                lead_score=30.0,
            )
            lead_b = Lead(
                county_assessor_pin=None,
                property_street='21 Other Ave',
                owner_user_id='other-user',
                lead_status='skip_trace',
                lead_score=17.0,
            )
            db.session.add_all([lead_a, lead_b])
            db.session.flush()
            a_id = lead_a.id
            b_id = lead_b.id

            deal = HubSpotDeal(
                hubspot_id='retarget-pin-deal',
                raw_payload={
                    'properties': {
                        'county_assessor_pin': pin,
                        'dealname': '20 Locked Ave',
                        'dealstage': 'closedwon',
                    },
                },
            )
            db.session.add(deal)
            db.session.flush()

            svc = HubSpotMatcherService()
            with patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value='importer-user',
            ):
                match = svc.match_deal(deal, stage_label_map={'closedwon': 'Deal Won'})
                db.session.flush()
                assert match.status == 'pending'
                assert match.internal_record_id == a_id
                match.status = 'confirmed'
                db.session.flush()

                lead_a.county_assessor_pin = '000000000001'
                lead_b.county_assessor_pin = pin
                db.session.flush()

                rematch = svc.match_deal(deal, stage_label_map={'closedwon': 'Deal Won'})
            db.session.flush()

            assert rematch.id == match.id
            assert rematch.status == 'confirmed'
            assert rematch.internal_record_id == a_id
            other = db.session.get(Lead, b_id)
            assert other.lead_status == 'skip_trace'
            assert other.lead_score == 17.0

            db.session.rollback()

    def test_confirmed_unmatched_reimport_does_not_create_placeholder(self, app):
        """A confirmed deal must not spawn a new lead when PIN/address no longer hit."""
        with app.app_context():
            pin = '111222333444'
            lead = Lead(
                county_assessor_pin=pin,
                property_street='30 Locked St',
                owner_user_id='importer-user',
                lead_status='skip_trace',
            )
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id
            lead_count = Lead.query.count()

            deal = HubSpotDeal(
                hubspot_id='orphan-placeholder-deal',
                raw_payload={
                    'properties': {
                        'county_assessor_pin': pin,
                        'dealname': '30 Locked St',
                    },
                },
            )
            db.session.add(deal)
            db.session.flush()

            svc = HubSpotMatcherService()
            with patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value='importer-user',
            ):
                match = svc.match_deal(deal)
                db.session.flush()
                match.status = 'confirmed'
                db.session.flush()

                deal.raw_payload = {
                    'properties': {
                        'county_assessor_pin': '000111222333',
                        'dealname': '99 Nowhere Blvd',
                    },
                }
                db.session.flush()

                rematch = svc.match_deal(deal)
            db.session.flush()

            assert rematch.id == match.id
            assert rematch.status == 'confirmed'
            assert rematch.internal_record_id == lead_id
            assert Lead.query.count() == lead_count

            db.session.rollback()

    def test_confirmed_person_match_does_not_enrich_lead_with_colliding_id(self, app):
        """A confirmed HubSpot person must not treat Contact.id as a Lead PK."""
        from app.models.contact import Contact
        from app.models.hubspot_match import HubSpotMatch

        with app.app_context():
            person = Contact(first_name='Unmatched', last_name='Person')
            lead = Lead(
                property_street='99 Collision Ave',
                owner_user_id='lead-owner',
                owner_first_name=None,
                phone_1=None,
            )
            db.session.add_all([person, lead])
            db.session.flush()
            assert person.id == lead.id

            hs = _make_contact(
                'orphan-person-hs',
                'orphan@example.com',
                None,
                'HubFirst',
                'HubLast',
            )
            db.session.add(hs)
            db.session.flush()

            frozen = HubSpotMatch(
                hubspot_record_type='contact',
                hubspot_id=hs.hubspot_id,
                internal_record_type='contact',
                internal_record_id=person.id,
                confidence='UNMATCHED',
                status='confirmed',
            )
            db.session.add(frozen)
            db.session.flush()

            svc = HubSpotMatcherService()
            with patch(
                'app.services.hubspot_writeback_service.hubspot_pull_enabled',
                return_value=True,
            ):
                rematch = svc.match_contact(hs)
                target = svc._lead_for_confirmed_match(frozen, lead)
            db.session.flush()

            assert rematch.id == frozen.id
            assert rematch.internal_record_type == 'contact'
            assert rematch.internal_record_id == person.id
            assert target is None
            refreshed = db.session.get(Lead, lead.id)
            assert refreshed.owner_first_name is None
            assert refreshed.phone_1 is None

            db.session.rollback()


class TestPinAndAddressOwnerScope:
    def test_unique_pin_does_not_pending_link_foreign_lead(self, app):
        with app.app_context():
            pin = '998877665544'
            theirs = Lead(
                county_assessor_pin=pin,
                property_street='82 Pin Guard St',
                owner_user_id='other-user',
            )
            db.session.add(theirs)
            db.session.flush()
            their_id = theirs.id
            deal = _make_deal(
                hubspot_id='pin-foreign-deal',
                pin=pin,
                address='999 Unrelated Blvd',
            )
            db.session.add(deal)
            db.session.flush()
            with patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value='hs-importer',
            ):
                match = HubSpotMatcherService().match_deal(deal, stage_label_map={})
            assert match.internal_record_id != their_id
            assert db.session.get(Lead, their_id).owner_user_id == 'other-user'
            db.session.rollback()

    def test_unique_pin_unattended_import_does_not_pending_link_owned_lead(self, app):
        with app.app_context():
            pin = '998877665533'
            theirs = Lead(
                county_assessor_pin=pin,
                property_street='84 Unattended Pin St',
                owner_user_id='other-user',
            )
            db.session.add(theirs)
            db.session.flush()
            their_id = theirs.id
            deal = _make_deal(
                hubspot_id='pin-unattended-deal',
                pin=pin,
                address='999 Unrelated Blvd',
            )
            db.session.add(deal)
            db.session.flush()
            with patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value=None,
            ):
                match = HubSpotMatcherService().match_deal(deal, stage_label_map={})
            assert match.internal_record_id != their_id
            assert db.session.get(Lead, their_id).owner_user_id == 'other-user'
            db.session.rollback()

    def test_unique_address_does_not_pending_link_foreign_lead(self, app):
        with app.app_context():
            theirs = Lead(
                property_street='83 Address Guard St',
                owner_user_id='other-user',
            )
            db.session.add(theirs)
            db.session.flush()
            their_id = theirs.id
            deal = _make_deal(
                hubspot_id='address-foreign-deal',
                pin=None,
                address='83 Address Guard St',
            )
            db.session.add(deal)
            db.session.flush()
            with patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value='hs-importer',
            ):
                match = HubSpotMatcherService().match_deal(deal, stage_label_map={})
            assert match.internal_record_id != their_id
            placeholder = db.session.get(Lead, match.internal_record_id)
            assert placeholder is not None
            assert placeholder.owner_user_id == 'hs-importer'
            assert db.session.get(Lead, their_id).owner_user_id == 'other-user'
            db.session.rollback()


class TestIdentityMatchOwnerScope:
    def test_does_not_pending_link_another_owners_lead(self, app):
        with app.app_context():
            theirs = Lead(
                property_street='80 Identity Guard St',
                owner_first_name='Pat',
                owner_last_name='Owner',
                owner_user_id='other-user',
            )
            db.session.add(theirs)
            db.session.flush()
            their_id = theirs.id
            deal = HubSpotDeal(
                hubspot_id='identity-foreign-deal',
                raw_payload={'properties': {
                    'dealname': '80 Identity Guard St',
                    'owner_first_name': 'Pat',
                    'owner_last_name': 'Owner',
                }},
            )
            db.session.add(deal)
            db.session.flush()
            with patch.object(
                HubSpotMatcherService, '_address_matches_for', return_value=[],
            ), patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value='hs-importer',
            ):
                match = HubSpotMatcherService().match_deal(deal)
            assert match.internal_record_id != their_id
            placeholder = db.session.get(Lead, match.internal_record_id)
            assert placeholder is not None
            assert placeholder.owner_user_id == 'hs-importer'
            assert db.session.get(Lead, their_id).owner_user_id == 'other-user'
            db.session.rollback()


class TestContactMatchOwnerScope:
    def test_unique_email_does_not_pending_link_foreign_lead(self, app):
        with app.app_context():
            theirs = Lead(
                property_street='81 Email Guard St',
                email_1='foreign.owner@example.com',
                owner_user_id='other-user',
            )
            db.session.add(theirs)
            db.session.flush()
            their_id = theirs.id
            hs = _make_contact(
                hubspot_id='email-foreign-hs',
                email='foreign.owner@example.com',
                phone=None,
                first_name='Pat',
                last_name='Owner',
            )
            db.session.add(hs)
            db.session.flush()
            with patch.object(
                HubSpotMatcherService,
                '_hubspot_import_owner_user_id',
                return_value='hs-importer',
            ):
                match = HubSpotMatcherService().match_contact(hs)
            assert not (
                match.internal_record_type == 'lead'
                and match.internal_record_id == their_id
            )
            assert db.session.get(Lead, their_id).email_1 == 'foreign.owner@example.com'
            db.session.rollback()
