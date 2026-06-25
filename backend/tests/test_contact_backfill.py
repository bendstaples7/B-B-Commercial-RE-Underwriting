"""Unit tests for the flat->relational contact backfill.

Covers ``app.services.contact_backfill``:
  - repairs missing phones/emails on an existing primary owner contact
  - creates a contact + primary link when a lead has flat data but no contact
  - de-dupes phones by digits and emails by ``lower()`` (idempotent on re-run)
  - routes around a synthetic ("junk") primary by creating a real owner contact
  - the ``DeJana 4414``-shaped case (real primary w/ 0 phones + junk contact)
  - ``dry_run`` makes no writes
  - ``lead_ids`` restricts the run
  - the ``looks_synthetic_name`` / ``phone_digits`` heuristics used by cleanup

Strategy mirrors ``test_migration_contact.py``: seed via ORM against the
in-memory SQLite test DB (``app`` fixture), run the helper on
``db.session.connection()``, then assert via ORM queries.
"""
import pytest
from marshmallow import ValidationError

from app import db
from app.models.lead import Lead
from app.models.contact import Contact
from app.models.contact_phone import ContactPhone
from app.models.contact_email import ContactEmail
from app.models.property_contact import PropertyContact
from app.schemas import ContactEmailSchema, ContactPhoneSchema
from app.services.contact_backfill import (
    backfill_contacts_from_flat_fields,
    contact_methods,
    looks_synthetic_name,
    phone_digits,
    preservation_gaps,
    split_email_field,
    split_phone_field,
)

# The exact value from the production deploy failure (lead 1880): a single
# legacy phone_N field holding seven numbers as free text. contact_phones.value
# is VARCHAR(50), so inserting this verbatim raised StringDataRightTruncation
# and aborted the migration. Kept here as a permanent regression fixture.
PROD_MULTINUMBER_BLOB = (
    "1) (773) 558-1863  2) (510) 685-0838  3) (773) 370-5668  "
    "4) (773) 370-3207  5) (323) 376-9028  6) (773) 279-1469  "
    "7) (773) 279-0000"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_lead(**kwargs) -> Lead:
    lead = Lead(**kwargs)
    db.session.add(lead)
    db.session.commit()
    return lead


def _link_contact(lead_id, first, last, *, is_primary=True, phones=(), emails=()) -> Contact:
    contact = Contact(first_name=first, last_name=last, role="owner")
    db.session.add(contact)
    db.session.flush()
    for value in phones:
        db.session.add(ContactPhone(contact_id=contact.id, value=value, label="other"))
    for value in emails:
        db.session.add(ContactEmail(contact_id=contact.id, value=value, label="other"))
    db.session.add(
        PropertyContact(
            property_id=lead_id, contact_id=contact.id, role="owner", is_primary=is_primary
        )
    )
    db.session.commit()
    return contact


def _run(**kwargs) -> dict:
    return backfill_contacts_from_flat_fields(db.session.connection(), **kwargs)


def _phone_digits_for(contact_id) -> set:
    return {
        phone_digits(p.value)
        for p in ContactPhone.query.filter_by(contact_id=contact_id).all()
    }


def _emails_for(contact_id) -> set:
    return {
        e.value.lower()
        for e in ContactEmail.query.filter_by(contact_id=contact_id).all()
    }


# ---------------------------------------------------------------------------
# Repair an existing primary owner contact
# ---------------------------------------------------------------------------

class TestRepairExistingPrimary:
    def test_adds_missing_phones_and_emails_to_existing_primary(self, app):
        with app.app_context():
            lead = _seed_lead(
                property_street="1 Repair St",
                owner_first_name="Dejauna",
                owner_last_name="Mitchell",
                phone_1="(815) 524-4599",
                phone_2="773-454-5062",
                email_1="deJana@example.com",
            )
            contact = _link_contact(lead.id, "Dejauna", "Mitchell")

            stats = _run()

            assert Contact.query.count() == 1  # no new contact created
            assert _phone_digits_for(contact.id) == {"8155244599", "7734545062"}
            assert _emails_for(contact.id) == {"dejana@example.com"}
            assert stats["phones_added"] == 2
            assert stats["emails_added"] == 1
            assert stats["contacts_created"] == 0
            assert stats["leads_processed"] == 1

    def test_idempotent_on_rerun(self, app):
        with app.app_context():
            lead = _seed_lead(
                property_street="2 Repair St",
                owner_first_name="Dejauna",
                owner_last_name="Mitchell",
                phone_1="8155244599",
                email_1="a@example.com",
            )
            _link_contact(lead.id, "Dejauna", "Mitchell")

            _run()
            second = _run()

            assert second["phones_added"] == 0
            assert second["emails_added"] == 0
            assert ContactPhone.query.count() == 1
            assert ContactEmail.query.count() == 1


# ---------------------------------------------------------------------------
# De-duplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_phone_deduped_by_digits_and_email_by_lowercase(self, app):
        with app.app_context():
            lead = _seed_lead(
                property_street="3 Dedup St",
                owner_first_name="Sam",
                owner_last_name="Jones",
                phone_1="(815) 524-4599",   # same digits as existing
                email_1="A@X.com",           # same email, different case
            )
            contact = _link_contact(
                lead.id, "Sam", "Jones",
                phones=["8155244599"], emails=["a@x.com"],
            )

            stats = _run()

            assert _phone_digits_for(contact.id) == {"8155244599"}
            assert _emails_for(contact.id) == {"a@x.com"}
            assert stats["phones_added"] == 0
            assert stats["emails_added"] == 0


# ---------------------------------------------------------------------------
# Create a contact when none exists
# ---------------------------------------------------------------------------

class TestCreateWhenMissing:
    def test_creates_primary_owner_contact_from_owner_name(self, app):
        with app.app_context():
            lead = _seed_lead(
                property_street="4 Create St",
                owner_first_name="New",
                owner_last_name="Owner",
                phone_1="312-555-0001",
                email_1="new.owner@example.com",
            )

            stats = _run()

            assert Contact.query.count() == 1
            contact = Contact.query.one()
            assert (contact.first_name, contact.last_name) == ("New", "Owner")
            link = PropertyContact.query.filter_by(property_id=lead.id).one()
            assert bool(link.is_primary) is True
            assert _phone_digits_for(contact.id) == {"3125550001"}
            assert _emails_for(contact.id) == {"new.owner@example.com"}
            assert stats["contacts_created"] == 1
            assert stats["phones_added"] == 1
            assert stats["emails_added"] == 1

    def test_skips_lead_with_flat_data_but_no_owner_name_and_no_contact(self, app):
        with app.app_context():
            _seed_lead(
                property_street="5 NoName St",
                phone_1="312-555-0002",
            )

            stats = _run()

            assert Contact.query.count() == 0
            assert stats["leads_skipped"] == 1
            assert stats["leads_processed"] == 0


# ---------------------------------------------------------------------------
# Synthetic ("junk") primary handling
# ---------------------------------------------------------------------------

class TestSyntheticPrimary:
    def test_creates_real_contact_and_demotes_synthetic_primary(self, app):
        with app.app_context():
            lead = _seed_lead(
                property_street="6 Junk St",
                owner_first_name="Real",
                owner_last_name="Owner",
                phone_1="815-524-4599",
            )
            junk = _link_contact(
                lead.id, "BOmjhdXntqoKgbsGCyPhUFZd", None,
                is_primary=True, phones=["8155244599"],
            )

            stats = _run()

            real = Contact.query.filter_by(first_name="Real", last_name="Owner").one()
            real_link = PropertyContact.query.filter_by(
                property_id=lead.id, contact_id=real.id
            ).one()
            junk_link = PropertyContact.query.filter_by(
                property_id=lead.id, contact_id=junk.id
            ).one()

            assert bool(real_link.is_primary) is True
            assert bool(junk_link.is_primary) is False
            assert _phone_digits_for(real.id) == {"8155244599"}
            assert stats["contacts_created"] == 1

    def test_promotes_existing_real_contact_over_synthetic_primary(self, app):
        """A real (non-primary) contact must be promoted over a synthetic primary.

        Regression: ``has_primary`` previously counted the synthetic ``is_primary``
        link, so the real contact was never promoted -- leaving the junk contact as
        the dropdown default while the repaired contact silently got the data.
        """
        with app.app_context():
            lead = _seed_lead(
                property_street="10 Junk Primary St",
                owner_first_name="Real",
                owner_last_name="Owner",
                phone_1="815-524-4599",
            )
            junk = _link_contact(
                lead.id, "BOmjhdXntqoKgbsGCyPhUFZd", None, is_primary=True
            )
            real = _link_contact(lead.id, "Real", "Owner", is_primary=False)

            stats = _run()

            real_link = PropertyContact.query.filter_by(
                property_id=lead.id, contact_id=real.id
            ).one()
            junk_link = PropertyContact.query.filter_by(
                property_id=lead.id, contact_id=junk.id
            ).one()

            assert bool(real_link.is_primary) is True
            assert bool(junk_link.is_primary) is False
            assert _phone_digits_for(real.id) == {"8155244599"}
            assert stats["contacts_created"] == 0  # reused the existing real contact

    def test_4414_shaped_real_primary_with_zero_phones_plus_junk(self, app):
        """DeJana 4414: real primary has 0 phones; a junk contact holds 1 number."""
        with app.app_context():
            lead = _seed_lead(
                property_street="4414 DeJana St",
                owner_first_name="Dejauna",
                owner_last_name="Mitchell",
                phone_1="8155244599",
                phone_2="773-454-5062",
            )
            primary = _link_contact(lead.id, "Dejauna", "Mitchell", is_primary=True)
            _link_contact(
                lead.id, "BOmjhdXntqoKgbsGCyPhUFZd", None,
                is_primary=False, phones=["8155244599"],
            )

            _run()

            assert _phone_digits_for(primary.id) == {"8155244599", "7734545062"}


# ---------------------------------------------------------------------------
# dry_run and lead_ids
# ---------------------------------------------------------------------------

class TestDryRunAndScope:
    def test_dry_run_makes_no_writes_but_reports_counts(self, app):
        with app.app_context():
            _seed_lead(
                property_street="7 Dry St",
                owner_first_name="Dry",
                owner_last_name="Run",
                phone_1="312-555-0003",
                email_1="dry@example.com",
            )

            stats = _run(dry_run=True)

            assert Contact.query.count() == 0
            assert ContactPhone.query.count() == 0
            assert ContactEmail.query.count() == 0
            assert stats["contacts_created"] == 1
            assert stats["phones_added"] == 1
            assert stats["emails_added"] == 1

    def test_lead_ids_restricts_scope(self, app):
        with app.app_context():
            target = _seed_lead(
                property_street="8 Scoped St",
                owner_first_name="In",
                owner_last_name="Scope",
                phone_1="312-555-0004",
            )
            other = _seed_lead(
                property_street="9 Other St",
                owner_first_name="Out",
                owner_last_name="Scope",
                phone_1="312-555-0005",
            )

            stats = _run(lead_ids=[target.id])

            assert stats["leads_processed"] == 1
            assert Contact.query.count() == 1
            assert PropertyContact.query.filter_by(property_id=other.id).count() == 0


# ---------------------------------------------------------------------------
# Heuristics shared with cleanup_junk_contacts
# ---------------------------------------------------------------------------

class TestSyntheticNameHeuristic:
    def test_real_names_not_flagged(self):
        assert looks_synthetic_name("Dejauna", "Mitchell") is False
        assert looks_synthetic_name("Maria", "Hernandez") is False
        # Real surname that lost its spaces during import: long, low vowel ratio,
        # but normally capitalized (no internal caps) -- must NOT be flagged, or
        # cleanup would delete a real backfilled primary contact.
        assert looks_synthetic_name(None, "Bichnguyenfranzen") is False
        # Long all-lowercase concatenations are likewise real, not fuzz.
        assert looks_synthetic_name(None, "vanderveldennielsen") is False
        # CamelCase real names have too few internal caps to trip the threshold.
        assert looks_synthetic_name("McDonald", "Fitzgerald") is False
        assert looks_synthetic_name("Schwarzenegger", None) is False
        assert looks_synthetic_name(None, None) is False

    def test_synthetic_tokens_flagged(self):
        # Random mixed-case fuzz: long single token with many internal capitals.
        assert looks_synthetic_name("BOmjhdXntqoKgbsGCyPhUFZd", None) is True
        assert looks_synthetic_name("WBozLJoAwjbcWOCLFBRT", None) is True
        assert looks_synthetic_name(None, "aXbYcZdWeVfUgThSiR") is True


class TestPhoneDigits:
    def test_strips_non_digits(self):
        assert phone_digits("(815) 524-4599") == "8155244599"
        assert phone_digits("773-454-5062") == "7734545062"
        assert phone_digits("") == ""
        assert phone_digits(None) == ""


# ---------------------------------------------------------------------------
# Shared cleanup helpers: contact_methods / preservation_gaps
# ---------------------------------------------------------------------------

def _make_contact(first, last, *, phones=(), emails=()) -> Contact:
    contact = Contact(first_name=first, last_name=last, role="owner")
    db.session.add(contact)
    db.session.flush()
    for value in phones:
        db.session.add(ContactPhone(contact_id=contact.id, value=value, label="other"))
    for value in emails:
        db.session.add(ContactEmail(contact_id=contact.id, value=value, label="other"))
    db.session.commit()
    return contact


def _link(contact_id, lead_id, *, is_primary=False) -> None:
    db.session.add(
        PropertyContact(
            property_id=lead_id, contact_id=contact_id,
            role="owner", is_primary=is_primary,
        )
    )
    db.session.commit()


class TestContactMethods:
    def test_returns_normalized_phone_digits_and_lowercased_emails(self, app):
        with app.app_context():
            contact = _make_contact(
                "A", "B", phones=["(815) 524-4599"], emails=["X@Y.com"]
            )
            phones, emails = contact_methods(db.session.connection(), contact.id)
            assert phones == {"8155244599"}
            assert emails == {"x@y.com"}


class TestPreservationGaps:
    def test_safe_when_value_preserved_on_real_contact_same_property(self, app):
        with app.app_context():
            lead = _seed_lead(property_street="P Safe St")
            junk = _make_contact("BOmjhdXntqoKgbsGCyPhUFZd", None, phones=["815-524-4599"])
            _link(junk.id, lead.id)
            real = _make_contact("Real", "Owner", phones=["8155244599"])
            _link(real.id, lead.id, is_primary=True)

            gaps = preservation_gaps(db.session.connection(), junk.id)

            assert gaps["safe"] is True
            assert gaps["missing_by_property"] == {}

    def test_unsafe_when_value_not_on_any_real_contact(self, app):
        with app.app_context():
            lead = _seed_lead(property_street="P Unsafe St")
            junk = _make_contact("BOmjhdXntqoKgbsGCyPhUFZd", None, phones=["815-524-4599"])
            _link(junk.id, lead.id)

            gaps = preservation_gaps(db.session.connection(), junk.id)

            assert gaps["safe"] is False
            assert gaps["missing_by_property"][lead.id][0] == {"8155244599"}

    def test_multi_property_requires_each_property_preserved(self, app):
        """Per-property check: a value kept on one property must not green-light
        deletion when another linked property would lose it (the old global union
        bug)."""
        with app.app_context():
            lead1 = _seed_lead(property_street="P1 St")
            lead2 = _seed_lead(property_street="P2 St")
            junk = _make_contact("BOmjhdXntqoKgbsGCyPhUFZd", None, phones=["815-524-4599"])
            _link(junk.id, lead1.id)
            _link(junk.id, lead2.id)
            # P1 keeps the value on a real contact; P2 does NOT.
            kept = _make_contact("Real", "One", phones=["8155244599"])
            _link(kept.id, lead1.id, is_primary=True)
            other = _make_contact("Real", "Two", phones=["3120000000"])
            _link(other.id, lead2.id, is_primary=True)

            gaps = preservation_gaps(db.session.connection(), junk.id)

            assert gaps["safe"] is False
            assert set(gaps["property_ids"]) == {lead1.id, lead2.id}
            assert lead1.id not in gaps["missing_by_property"]
            assert gaps["missing_by_property"][lead2.id][0] == {"8155244599"}

    def test_synthetic_other_contact_does_not_count_as_preserved(self, app):
        with app.app_context():
            lead = _seed_lead(property_street="P Synthetic St")
            junk = _make_contact("BOmjhdXntqoKgbsGCyPhUFZd", None, phones=["815-524-4599"])
            _link(junk.id, lead.id)
            # Another *synthetic* contact holding the same number must not count.
            other_junk = _make_contact("WBozLJoAwjbcWOCLFBRT", None, phones=["8155244599"])
            _link(other_junk.id, lead.id)

            gaps = preservation_gaps(db.session.connection(), junk.id)

            assert gaps["safe"] is False
            assert gaps["missing_by_property"][lead.id][0] == {"8155244599"}

    def test_orphan_contact_with_methods_is_not_safe(self, app):
        with app.app_context():
            junk = _make_contact("BOmjhdXntqoKgbsGCyPhUFZd", None, phones=["815-524-4599"])

            gaps = preservation_gaps(db.session.connection(), junk.id)

            assert gaps["property_ids"] == []
            assert gaps["orphan_with_methods"] is True
            assert gaps["safe"] is False


# ---------------------------------------------------------------------------
# Parsing legacy flat fields: split_phone_field / split_email_field
# ---------------------------------------------------------------------------

class TestSplitPhoneField:
    def test_single_clean_value_passes_through(self):
        assert split_phone_field("(815) 524-4599") == ["(815) 524-4599"]

    def test_seven_digit_local_number_falls_back_to_whole_value(self):
        assert split_phone_field("558-1863") == ["558-1863"]

    def test_multi_number_blob_is_split_into_individual_numbers(self):
        result = split_phone_field(PROD_MULTINUMBER_BLOB)
        assert result == [
            "(773) 558-1863",
            "(510) 685-0838",
            "(773) 370-5668",
            "(773) 370-3207",
            "(323) 376-9028",
            "(773) 279-1469",
            "(773) 279-0000",
        ]
        # Every extracted value fits contact_phones.value VARCHAR(50).
        assert all(len(v) <= 50 for v in result)

    def test_label_text_around_number_is_dropped(self):
        assert split_phone_field("cell (773) 558-1863") == ["(773) 558-1863"]

    def test_duplicate_numbers_deduped_by_digits(self):
        assert split_phone_field("(773) 558-1863  773.558.1863") == ["(773) 558-1863"]

    def test_unparseable_or_too_short_value_returns_empty(self):
        assert split_phone_field("n/a") == []
        assert split_phone_field("123") == []  # too few digits
        assert split_phone_field("") == []
        assert split_phone_field(None) == []

    def test_too_many_digits_with_no_phone_pattern_dropped(self):
        # 16 single digits separated so there is no 3-digit run for the regex;
        # falls back to the whole value, whose 16 digits aren't a plausible phone.
        assert split_phone_field("-".join(list("1234567890123456"))) == []

    def test_value_too_long_for_column_is_dropped(self):
        # 7 digits (plausible) but separated by long runs so there's no 3-digit
        # group: it falls back to the whole value, which exceeds VARCHAR(50) and
        # must be dropped rather than truncated.
        too_long = ("-" * 10).join(list("1234567"))
        assert len(too_long) > 50
        assert split_phone_field(too_long) == []


class TestSplitEmailField:
    def test_single_value_passes_through(self):
        assert split_email_field("a@example.com") == ["a@example.com"]

    def test_multiple_emails_split_on_separators(self):
        assert split_email_field("a@x.com, b@y.com; c@z.com") == [
            "a@x.com", "b@y.com", "c@z.com",
        ]

    def test_non_email_tokens_dropped_and_deduped(self):
        assert split_email_field("notanemail  A@X.com  a@x.com") == ["A@X.com"]

    def test_too_long_email_dropped(self):
        too_long = ("x" * 250) + "@example.com"  # > 255 chars
        assert split_email_field(too_long) == []

    def test_empty_returns_empty(self):
        assert split_email_field("") == []
        assert split_email_field(None) == []


# ---------------------------------------------------------------------------
# Backfill end-to-end with dirty data (the deploy-failure regression)
# ---------------------------------------------------------------------------

class TestBackfillDirtyData:
    def test_multinumber_blob_recovered_without_truncation(self, app):
        """Regression for the prod deploy failure: a phone_N holding 7 numbers
        must be split into 7 ContactPhones, none exceeding VARCHAR(50)."""
        with app.app_context():
            _seed_lead(
                property_street="1880 Truncation Ave",
                owner_first_name="Multi",
                owner_last_name="Number",
                phone_1=PROD_MULTINUMBER_BLOB,
            )

            stats = _run()

            contact = Contact.query.filter_by(
                first_name="Multi", last_name="Number"
            ).one()
            stored = [
                p.value
                for p in ContactPhone.query.filter_by(contact_id=contact.id).all()
            ]
            assert len(stored) == 7
            assert all(len(v) <= 50 for v in stored)
            assert _phone_digits_for(contact.id) == {
                "7735581863", "5106850838", "7733705668", "7733703207",
                "3233769028", "7732791469", "7732790000",
            }
            assert stats["phones_added"] == 7

    def test_unparseable_phone_is_skipped_and_counted(self, app):
        """A non-empty but unusable phone field must be skipped (counted), and
        the run must still complete (no exception)."""
        with app.app_context():
            _seed_lead(
                property_street="2 Garbage St",
                owner_first_name="Junk",
                owner_last_name="Phone",
                phone_1="x" * 80,          # no digits -> not a plausible phone
                email_1="real@example.com",
            )

            stats = _run()

            contact = Contact.query.filter_by(
                first_name="Junk", last_name="Phone"
            ).one()
            assert _phone_digits_for(contact.id) == set()
            assert stats["phones_skipped_malformed"] == 1
            assert _emails_for(contact.id) == {"real@example.com"}

    def test_multi_email_blob_recovered(self, app):
        with app.app_context():
            _seed_lead(
                property_street="3 Many Emails St",
                owner_first_name="Many",
                owner_last_name="Emails",
                email_1="one@example.com; two@example.com",
            )

            _run()

            contact = Contact.query.filter_by(
                first_name="Many", last_name="Emails"
            ).one()
            assert _emails_for(contact.id) == {
                "one@example.com", "two@example.com",
            }


# ---------------------------------------------------------------------------
# Write-boundary validation: schema length matches the DB columns
# ---------------------------------------------------------------------------

class TestContactSchemaLengthValidation:
    def test_phone_over_50_chars_rejected(self):
        with pytest.raises(ValidationError):
            ContactPhoneSchema().load({"value": "1" * 51, "label": "other"})

    def test_phone_at_limit_accepted(self):
        loaded = ContactPhoneSchema().load({"value": "1" * 50, "label": "other"})
        assert loaded["value"] == "1" * 50

    def test_empty_phone_rejected(self):
        with pytest.raises(ValidationError):
            ContactPhoneSchema().load({"value": "", "label": "other"})

    def test_email_over_255_chars_rejected(self):
        long_email = ("x" * 250) + "@example.com"
        with pytest.raises(ValidationError):
            ContactEmailSchema().load({"value": long_email, "label": "other"})

    def test_email_at_limit_accepted(self):
        value = ("x" * 245) + "@a.com"  # 251 chars, within 255
        loaded = ContactEmailSchema().load({"value": value, "label": "other"})
        assert loaded["value"] == value
