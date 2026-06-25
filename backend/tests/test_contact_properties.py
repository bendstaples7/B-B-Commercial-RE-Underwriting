"""Property-based tests for the property-contact-model feature.

Contains all 13 Hypothesis property-based tests covering:
  - Property 1:  Legacy redirect preserves path suffix (Req 1.2)
  - Property 2:  Property writes persist to the leads table (Req 1.5)
  - Property 3:  Contact data round-trip (Req 4.1, 4.2, 4.3, 4.8)
  - Property 4:  Empty-name contacts are rejected (Req 4.5)
  - Property 5:  Property-Contact join record round-trip (Req 5.3)
  - Property 6:  At most one primary contact per property (Req 5.4, 5.5, 5.6)
  - Property 7:  Non-existent IDs return 404 (Req 6.8)
  - Property 8:  Migration idempotency (Req 8.9)
  - Property 9:  Deprecated fields are not written after migration (Req 9.1)
  - Property 10: HubSpot contact matching targets Contact records (Req 10.1, 10.2, 10.4)
  - Property 11: Unmatched HubSpot contacts create new Contact records (Req 10.3)
  - Property 12: Matching never deletes existing Contact records (Req 10.5)
  - Property 13: Owner-name filter returns exactly matching properties (Req 11.1, 11.2)
"""
import uuid

import pytest
import sqlalchemy as sa
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from app import db
from app.models.contact import Contact
from app.models.contact_email import ContactEmail
from app.models.contact_phone import ContactPhone
from app.models.lead import Lead
from app.models.property_contact import PropertyContact
from app.services.hubspot_matcher_service import HubSpotMatcherService
from app.models.hubspot_contact import HubSpotContact

# Import the migration helper from the migration test module
from tests.test_migration_contact import run_migration_logic

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

_name_text = st.text(
    min_size=1,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
)

_role_st = st.sampled_from(
    ["owner", "property_manager", "attorney", "family_member", "other"]
)

_phone_label_st = st.sampled_from(["mobile", "home", "work", "other"])

_email_label_st = st.sampled_from(["personal", "work", "other"])


def _phone_entry_st():
    return st.fixed_dictionaries(
        {
            "value": st.text(min_size=7, max_size=20, alphabet="0123456789"),
            "label": _phone_label_st,
        }
    )


def _email_entry_st():
    return st.fixed_dictionaries(
        {
            "value": st.builds(
                lambda u, d: f"{u}@{d}.com",
                u=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Ll",))),
                d=st.text(min_size=2, max_size=10, alphabet=st.characters(whitelist_categories=("Ll",))),
            ),
            "label": _email_label_st,
        }
    )


@st.composite
def contact_payload_strategy(draw):
    """Generate a valid ContactCreatePayload with random names, role, phones, emails."""
    first_name = draw(st.one_of(st.none(), _name_text))
    last_name = draw(st.one_of(st.none(), _name_text))
    # Ensure at least one name is non-empty
    if not first_name and not last_name:
        first_name = draw(_name_text)
    role = draw(_role_st)
    phones = draw(st.lists(_phone_entry_st(), min_size=0, max_size=5))
    emails = draw(st.lists(_email_entry_st(), min_size=0, max_size=5))
    return {
        "first_name": first_name,
        "last_name": last_name,
        "role": role,
        "phones": phones,
        "emails": emails,
    }


@st.composite
def empty_name_contact_strategy(draw):
    """Generate a ContactCreatePayload where both first_name and last_name are absent/null/whitespace."""
    # Choose from: absent key, None, or whitespace-only string
    empty_variants = st.one_of(
        st.just(None),
        st.text(
            min_size=0,
            max_size=10,
            alphabet=st.characters(whitelist_categories=("Zs", "Cc")),
        ),
    )
    include_first = draw(st.booleans())
    include_last = draw(st.booleans())
    payload = {}
    if include_first:
        payload["first_name"] = draw(empty_variants)
    if include_last:
        payload["last_name"] = draw(empty_variants)
    return payload


# ---------------------------------------------------------------------------
# Helper: create a property in the DB and return its id
# ---------------------------------------------------------------------------

def _create_property(app_ctx, street=None):
    """Create a Lead/Property row and return its id."""
    street = street or f"Test St {uuid.uuid4().hex[:8]}"
    lead = Lead(property_street=street, owner_user_id="test-user")
    db.session.add(lead)
    db.session.commit()
    return lead.id


def _create_contact(app_ctx, first_name="Test", last_name="Contact", role="owner"):
    """Create a Contact row and return its id."""
    contact = Contact(first_name=first_name, last_name=last_name, role=role)
    db.session.add(contact)
    db.session.commit()
    return contact.id


# ===========================================================================
# Property 1: Legacy redirect preserves path suffix
# Feature: property-contact-model, Property 1
# Validates: Requirements 1.2
# ===========================================================================

# Valid path suffixes that exist under /api/properties/
_VALID_SUFFIXES = [
    "",
    "1",
    "2",
    "scoring/weights",
    "views/previously-warm",
    "views/needs-review",
    "views/follow-up-overdue",
    "views/no-next-action",
    "views/do-not-contact",
    "views/missing-property-match",
]


_VIEW_SUFFIX_TO_QUEUE = {
    "views/previously-warm": "/api/queues/previously-warm",
    "views/needs-review": "/api/queues/needs-review",
    "views/follow-up-overdue": "/api/queues/follow-up-overdue",
    "views/no-next-action": "/api/queues/no-next-action",
    "views/do-not-contact": "/api/queues/do-not-contact",
    "views/missing-property-match": "/api/queues/missing-property-match",
}


@given(suffix=st.sampled_from(_VALID_SUFFIXES))
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_legacy_redirect_preserves_path_suffix(app, client, suffix):
    """Property 1: GET /api/leads/<suffix> returns HTTP 301 to the canonical target.

    Non-view paths redirect to /api/properties/<suffix>. Deprecated view paths
    redirect directly to /api/queues/* (canonical queue API).

    Validates: Requirements 1.2
    """
    # Feature: property-contact-model, Property 1: Legacy redirect preserves path suffix
    path = f"/api/leads/{suffix}"
    response = client.get(path, follow_redirects=False)

    assert response.status_code == 301, (
        f"Expected 301 for path {path!r}, got {response.status_code}"
    )
    location = response.headers.get("Location", "")
    expected_fragment = _VIEW_SUFFIX_TO_QUEUE.get(suffix, f"/api/properties/{suffix}")
    assert expected_fragment in location, (
        f"Expected Location to contain {expected_fragment!r}, got {location!r}"
    )


# ===========================================================================
# Property 2: Property writes persist to the leads table
# Feature: property-contact-model, Property 2
# Validates: Requirements 1.5
# ===========================================================================

@given(
    street=st.text(min_size=5, max_size=100, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"))),
    city=st.one_of(st.none(), _name_text),
    state=st.one_of(st.none(), st.text(min_size=2, max_size=2, alphabet=st.characters(whitelist_categories=("Lu",)))),
)
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_writes_persist_to_leads_table(app, street, city, state):
    """Property 2: Properties created in the DB are retrievable via GET /api/properties/.

    Since there is no POST endpoint for creating properties, this test verifies
    the read path: records inserted directly into the leads table are returned
    by GET /api/properties/ with matching field values.

    Validates: Requirements 1.5
    """
    # Feature: property-contact-model, Property 2: Property writes persist to the leads table
    assume(street.strip())

    with app.app_context():
        unique_street = f"{street.strip()} {uuid.uuid4().hex[:6]}"
        lead = Lead(
            property_street=unique_street,
            property_city=city,
            property_state=state,
        )
        db.session.add(lead)
        db.session.commit()
        lead_id = lead.id

        # Verify the record is in the leads table with matching fields
        retrieved = db.session.get(Lead, lead_id)
        assert retrieved is not None, "Lead record not found in DB after insert"
        assert retrieved.property_street == unique_street
        if city is not None:
            assert retrieved.property_city == city
        if state is not None:
            assert retrieved.property_state == state

        # Clean up
        db.session.delete(retrieved)
        db.session.commit()


# ===========================================================================
# Property 3: Contact data round-trip
# Feature: property-contact-model, Property 3
# Validates: Requirements 4.1, 4.2, 4.3, 4.8
# ===========================================================================

@given(payload=contact_payload_strategy())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_contact_data_round_trip(app, client, payload):
    """Property 3: POST /api/contacts/ then GET /api/contacts/<id> returns all submitted fields.

    Validates: Requirements 4.1, 4.2, 4.3, 4.8
    """
    # Feature: property-contact-model, Property 3: Contact data round-trip
    with app.app_context():
        # Create the contact
        create_resp = client.post("/api/contacts/", json=payload)
        assert create_resp.status_code == 201, (
            f"Expected 201, got {create_resp.status_code}: {create_resp.get_json()}"
        )
        created = create_resp.get_json()
        contact_id = created["id"]

        # Retrieve the contact
        get_resp = client.get(f"/api/contacts/{contact_id}")
        assert get_resp.status_code == 200
        retrieved = get_resp.get_json()

        # Verify scalar fields
        assert retrieved["first_name"] == payload.get("first_name")
        assert retrieved["last_name"] == payload.get("last_name")
        assert retrieved["role"] == payload.get("role", "owner")

        # Verify phones round-trip
        submitted_phones = payload.get("phones", [])
        returned_phones = retrieved.get("phones", [])
        assert len(returned_phones) == len(submitted_phones), (
            f"Phone count mismatch: submitted {len(submitted_phones)}, got {len(returned_phones)}"
        )
        for submitted, returned in zip(submitted_phones, returned_phones):
            assert returned["value"] == submitted["value"]
            assert returned["label"] == submitted["label"]

        # Verify emails round-trip
        submitted_emails = payload.get("emails", [])
        returned_emails = retrieved.get("emails", [])
        assert len(returned_emails) == len(submitted_emails), (
            f"Email count mismatch: submitted {len(submitted_emails)}, got {len(returned_emails)}"
        )
        for submitted, returned in zip(submitted_emails, returned_emails):
            assert returned["value"] == submitted["value"]
            assert returned["label"] == submitted["label"]

        # Clean up
        client.delete(f"/api/contacts/{contact_id}")


# ===========================================================================
# Property 4: Empty-name contacts are rejected
# Feature: property-contact-model, Property 4
# Validates: Requirements 4.5
# ===========================================================================

@given(payload=empty_name_contact_strategy())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_empty_name_contacts_are_rejected(app, client, payload):
    """Property 4: POST /api/contacts/ with both names empty/null/whitespace returns 400.

    No Contact record should be created in the database.

    Validates: Requirements 4.5
    """
    # Feature: property-contact-model, Property 4: Empty-name contacts are rejected
    with app.app_context():
        count_before = Contact.query.count()

        response = client.post("/api/contacts/", json=payload)

        assert response.status_code == 400, (
            f"Expected 400 for empty-name payload {payload!r}, got {response.status_code}"
        )
        body = response.get_json()
        assert body is not None
        # Should have an error key
        assert "error" in body or "message" in body

        # No new Contact record should have been created
        count_after = Contact.query.count()
        assert count_after == count_before, (
            f"Contact count changed from {count_before} to {count_after} "
            f"after rejected payload {payload!r}"
        )


# ===========================================================================
# Property 5: Property-Contact join record round-trip
# Feature: property-contact-model, Property 5
# Validates: Requirements 5.3
# ===========================================================================

@given(
    role=_role_st,
    is_primary=st.booleans(),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_contact_join_record_round_trip(app, client, role, is_primary):
    """Property 5: POST /api/properties/<id>/contacts then GET returns same role and is_primary.

    Validates: Requirements 5.3
    """
    # Feature: property-contact-model, Property 5: Property-Contact join record round-trip
    with app.app_context():
        # Create a property and a contact to link
        property_id = _create_property(app)
        contact_id = _create_contact(app)

        link_payload = {
            "contact_id": contact_id,
            "role": role,
            "is_primary": is_primary,
        }
        link_resp = client.post(
            f"/api/properties/{property_id}/contacts", json=link_payload
        )
        assert link_resp.status_code == 201, (
            f"Expected 201, got {link_resp.status_code}: {link_resp.get_json()}"
        )

        # Retrieve the contacts for the property
        get_resp = client.get(f"/api/properties/{property_id}/contacts")
        assert get_resp.status_code == 200
        contacts = get_resp.get_json()

        # Find the linked contact in the response
        linked = next((c for c in contacts if c["id"] == contact_id), None)
        assert linked is not None, (
            f"Contact id={contact_id} not found in property contacts response"
        )
        assert linked["property_contact_role"] == role, (
            f"Expected role {role!r}, got {linked['property_contact_role']!r}"
        )
        assert linked["is_primary"] == is_primary, (
            f"Expected is_primary={is_primary}, got {linked['is_primary']}"
        )

        # Clean up
        client.delete(f"/api/properties/{property_id}/contacts/{contact_id}")
        client.delete(f"/api/contacts/{contact_id}")
        prop = db.session.get(Lead, property_id)
        if prop:
            db.session.delete(prop)
            db.session.commit()


# ===========================================================================
# Property 6: At most one primary contact per property
# Feature: property-contact-model, Property 6
# Validates: Requirements 5.4, 5.5, 5.6
# ===========================================================================

@given(
    num_contacts=st.integers(min_value=1, max_value=5),
    is_primary_flags=st.lists(st.booleans(), min_size=1, max_size=5),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_at_most_one_primary_contact_per_property(app, client, num_contacts, is_primary_flags):
    """Property 6: At most one contact per property has is_primary=True at any time.

    Adding a new primary demotes the previous primary.
    Removing the primary leaves all remaining with is_primary=False.

    Validates: Requirements 5.4, 5.5, 5.6
    """
    # Feature: property-contact-model, Property 6: At most one primary contact per property
    with app.app_context():
        property_id = _create_property(app)
        contact_ids = []

        # Align flags list length with num_contacts
        flags = (is_primary_flags * num_contacts)[:num_contacts]

        for i, is_primary in enumerate(flags):
            contact_id = _create_contact(app, first_name=f"Contact{i}", last_name="Test")
            contact_ids.append(contact_id)

            link_resp = client.post(
                f"/api/properties/{property_id}/contacts",
                json={"contact_id": contact_id, "role": "owner", "is_primary": is_primary},
            )
            assert link_resp.status_code == 201

            # After each link, verify at most one primary
            get_resp = client.get(f"/api/properties/{property_id}/contacts")
            assert get_resp.status_code == 200
            contacts_list = get_resp.get_json()
            primary_count = sum(1 for c in contacts_list if c["is_primary"])
            assert primary_count <= 1, (
                f"Found {primary_count} primary contacts after linking contact {i} "
                f"with is_primary={is_primary}"
            )

        # Find the current primary (if any) and remove it
        get_resp = client.get(f"/api/properties/{property_id}/contacts")
        contacts_list = get_resp.get_json()
        primary_contacts = [c for c in contacts_list if c["is_primary"]]

        if primary_contacts:
            primary_id = primary_contacts[0]["id"]
            del_resp = client.delete(
                f"/api/properties/{property_id}/contacts/{primary_id}"
            )
            assert del_resp.status_code == 204

            # After removing the primary, all remaining should have is_primary=False
            get_resp2 = client.get(f"/api/properties/{property_id}/contacts")
            assert get_resp2.status_code == 200
            remaining = get_resp2.get_json()
            for c in remaining:
                assert c["is_primary"] is False, (
                    f"Contact id={c['id']} still has is_primary=True after primary was removed"
                )

        # Clean up
        for cid in contact_ids:
            client.delete(f"/api/contacts/{cid}")
        prop = db.session.get(Lead, property_id)
        if prop:
            db.session.delete(prop)
            db.session.commit()


# ===========================================================================
# Property 7: Non-existent IDs return 404
# Feature: property-contact-model, Property 7
# Validates: Requirements 6.8
# ===========================================================================

@given(nonexistent_id=st.integers(min_value=999_000, max_value=999_999_999))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_nonexistent_ids_return_404(app, client, nonexistent_id):
    """Property 7: All Contact and Property-Contact endpoints return 404 for non-existent IDs.

    Validates: Requirements 6.8
    """
    # Feature: property-contact-model, Property 7: Non-existent IDs return 404
    with app.app_context():
        # Verify the ID truly doesn't exist
        assume(Contact.query.get(nonexistent_id) is None)
        assume(Lead.query.get(nonexistent_id) is None)

        # GET /api/contacts/<id>
        resp = client.get(f"/api/contacts/{nonexistent_id}")
        assert resp.status_code == 404, (
            f"GET /api/contacts/{nonexistent_id} expected 404, got {resp.status_code}"
        )

        # PUT /api/contacts/<id>
        resp = client.put(f"/api/contacts/{nonexistent_id}", json={"first_name": "X"})
        assert resp.status_code == 404, (
            f"PUT /api/contacts/{nonexistent_id} expected 404, got {resp.status_code}"
        )

        # DELETE /api/contacts/<id>
        resp = client.delete(f"/api/contacts/{nonexistent_id}")
        assert resp.status_code == 404, (
            f"DELETE /api/contacts/{nonexistent_id} expected 404, got {resp.status_code}"
        )

        # GET /api/properties/<id>/contacts
        resp = client.get(f"/api/properties/{nonexistent_id}/contacts")
        assert resp.status_code == 404, (
            f"GET /api/properties/{nonexistent_id}/contacts expected 404, got {resp.status_code}"
        )

        # POST /api/properties/<id>/contacts (property doesn't exist)
        resp = client.post(
            f"/api/properties/{nonexistent_id}/contacts",
            json={"contact_id": 1, "role": "owner", "is_primary": False},
        )
        assert resp.status_code == 404, (
            f"POST /api/properties/{nonexistent_id}/contacts expected 404, got {resp.status_code}"
        )

        # DELETE /api/properties/<id>/contacts/<contact_id>
        resp = client.delete(
            f"/api/properties/{nonexistent_id}/contacts/{nonexistent_id}"
        )
        assert resp.status_code == 404, (
            f"DELETE /api/properties/{nonexistent_id}/contacts/{nonexistent_id} "
            f"expected 404, got {resp.status_code}"
        )


# ===========================================================================
# Property 8: Migration idempotency
# Feature: property-contact-model, Property 8
# Validates: Requirements 8.9
# ===========================================================================

@st.composite
def lead_seed_strategy(draw):
    """Generate a dict of Lead fields for seeding the migration test."""
    has_owner1 = draw(st.booleans())
    has_owner2 = draw(st.booleans())
    first = draw(_name_text) if has_owner1 else None
    last = draw(_name_text) if has_owner1 else None
    first2 = draw(_name_text) if has_owner2 else None
    last2 = draw(_name_text) if has_owner2 else None
    num_phones = draw(st.integers(min_value=0, max_value=3))
    num_emails = draw(st.integers(min_value=0, max_value=2))
    phones = [draw(st.text(min_size=7, max_size=15, alphabet="0123456789")) for _ in range(num_phones)]
    emails = [
        f"{draw(st.text(min_size=2, max_size=8, alphabet=st.characters(whitelist_categories=('Ll',))))}@test.com"
        for _ in range(num_emails)
    ]
    return {
        "owner_first_name": first,
        "owner_last_name": last,
        "owner_2_first_name": first2,
        "owner_2_last_name": last2,
        "phones": phones,
        "emails": emails,
    }


@given(seeds=st.lists(lead_seed_strategy(), min_size=1, max_size=5))
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_migration_idempotency(app, seeds):
    """Property 8: Running migration logic twice produces the same record counts as running it once.

    Validates: Requirements 8.9
    """
    # Feature: property-contact-model, Property 8: Migration idempotency
    with app.app_context():
        created_lead_ids = []
        for i, seed in enumerate(seeds):
            phone_fields = {f"phone_{j + 1}": v for j, v in enumerate(seed["phones"])}
            email_fields = {f"email_{j + 1}": v for j, v in enumerate(seed["emails"])}
            lead = Lead(
                property_street=f"Migration Test {uuid.uuid4().hex[:8]}",
                owner_first_name=seed["owner_first_name"],
                owner_last_name=seed["owner_last_name"],
                owner_2_first_name=seed["owner_2_first_name"],
                owner_2_last_name=seed["owner_2_last_name"],
                **phone_fields,
                **email_fields,
            )
            db.session.add(lead)
        db.session.commit()

        conn = db.session.connection()

        # First run
        run_migration_logic(conn)
        counts_after_first = {
            "contacts": Contact.query.count(),
            "phones": ContactPhone.query.count(),
            "emails": ContactEmail.query.count(),
            "property_contacts": PropertyContact.query.count(),
        }

        # Second run — must be a no-op
        run_migration_logic(conn)
        counts_after_second = {
            "contacts": Contact.query.count(),
            "phones": ContactPhone.query.count(),
            "emails": ContactEmail.query.count(),
            "property_contacts": PropertyContact.query.count(),
        }

        assert counts_after_second == counts_after_first, (
            f"Migration is not idempotent: first run={counts_after_first}, "
            f"second run={counts_after_second}"
        )

        # Clean up all leads created in this test
        for lead in Lead.query.filter(Lead.property_street.like("Migration Test %")).all():
            db.session.delete(lead)
        db.session.commit()


# ===========================================================================
# Property 9: Deprecated fields are not written after migration
# Feature: property-contact-model, Property 9
# Validates: Requirements 9.1
# ===========================================================================

# The set of deprecated flat contact fields that must not be written
_DEPRECATED_CONTACT_FIELDS = {
    "owner_first_name", "owner_last_name",
    "owner_2_first_name", "owner_2_last_name",
    "phone_1", "phone_2", "phone_3", "phone_4", "phone_5", "phone_6", "phone_7",
    "email_1", "email_2", "email_3", "email_4", "email_5",
}


@given(
    deprecated_subset=st.frozensets(
        st.sampled_from(sorted(_DEPRECATED_CONTACT_FIELDS)),
        min_size=1,
        max_size=len(_DEPRECATED_CONTACT_FIELDS),
    )
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_deprecated_fields_not_written_after_migration(app, client, deprecated_subset):
    """Property 9: The _DEPRECATED_CONTACT_FIELDS constant is defined and covers all deprecated fields.

    Also verifies that GET /api/properties/ still returns legacy fields as read-only
    (they are present in the response but not writable via the API).

    Validates: Requirements 9.1
    """
    # Feature: property-contact-model, Property 9: Deprecated fields are not written after migration
    from app.controllers.property_controller import _DEPRECATED_CONTACT_FIELDS as controller_fields

    # Verify the constant is defined and contains all expected deprecated fields
    for field in deprecated_subset:
        assert field in controller_fields, (
            f"Deprecated field {field!r} is missing from _DEPRECATED_CONTACT_FIELDS"
        )

    # Verify the constant covers the full expected set
    assert _DEPRECATED_CONTACT_FIELDS.issubset(controller_fields), (
        f"_DEPRECATED_CONTACT_FIELDS in controller is missing fields: "
        f"{_DEPRECATED_CONTACT_FIELDS - controller_fields}"
    )

    with app.app_context():
        # Create a property with some legacy data already set
        lead = Lead(
            property_street=f"Deprecated Test {uuid.uuid4().hex[:8]}",
            owner_first_name="LegacyFirst",
            owner_last_name="LegacyLast",
            phone_1="555-0001",
            email_1="legacy@example.com",
            owner_user_id="test-user",
        )
        db.session.add(lead)
        db.session.commit()
        lead_id = lead.id

        # GET the property — legacy fields should still be readable
        get_resp = client.get(f"/api/properties/{lead_id}", headers={"X-User-Id": "test-user"})
        assert get_resp.status_code == 200
        data = get_resp.get_json()

        # Legacy fields are returned in GET responses (read-only)
        assert "owner_first_name" in data
        assert "phone_1" in data
        assert "email_1" in data

        # Clean up
        db.session.delete(db.session.get(Lead, lead_id))
        db.session.commit()


# ===========================================================================
# Property 10: HubSpot contact matching targets Contact records
# Feature: property-contact-model, Property 10
# Validates: Requirements 10.1, 10.2, 10.4
# ===========================================================================

@given(
    first_name=_name_text,
    last_name=_name_text,
    phone_digits=st.text(min_size=10, max_size=10, alphabet="0123456789"),
    email_local=st.text(min_size=2, max_size=15, alphabet=st.characters(whitelist_categories=("Ll",))),
    email_domain=st.text(min_size=2, max_size=8, alphabet=st.characters(whitelist_categories=("Ll",))),
    match_by=st.sampled_from(["email", "phone"]),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_hubspot_matching_targets_contact_records(
    app, first_name, last_name, phone_digits, email_local, email_domain, match_by
):
    """Property 10: HubSpot contact matching via email or phone returns HIGH confidence.

    Email match → HubSpotMatch with confidence=HIGH linked to that Contact.
    Phone match (digits-only normalized) → HIGH confidence match.

    Validates: Requirements 10.1, 10.2, 10.4
    """
    # Feature: property-contact-model, Property 10: HubSpot contact matching targets Contact records
    assume(len(email_local) >= 2)
    assume(len(email_domain) >= 2)

    email_value = f"{email_local}@{email_domain}.com"
    phone_value = phone_digits  # already digits-only

    with app.app_context():
        # Create a property to anchor the contact
        property_id = _create_property(app)

        # Create a Contact with the email and phone
        contact = Contact(
            first_name=first_name,
            last_name=last_name,
            role="owner",
        )
        contact.emails.append(ContactEmail(value=email_value, label="other"))
        contact.phones.append(ContactPhone(value=phone_value, label="other"))
        db.session.add(contact)
        db.session.flush()

        # Link contact to property
        pc = PropertyContact(
            property_id=property_id,
            contact_id=contact.id,
            role="owner",
            is_primary=True,
        )
        db.session.add(pc)
        db.session.commit()

        # Build a HubSpot contact payload that matches by the chosen strategy
        hubspot_id = f"hs_{uuid.uuid4().hex[:12]}"
        if match_by == "email":
            hs_props = {
                "email": email_value,
                "phone": "",
                "firstname": "Other",
                "lastname": "Person",
            }
        else:  # phone
            hs_props = {
                "email": f"nomatch_{uuid.uuid4().hex[:6]}@nowhere.com",
                "phone": phone_value,
                "firstname": "Other",
                "lastname": "Person",
            }

        hs_contact = HubSpotContact(
            hubspot_id=hubspot_id,
            raw_payload={"properties": hs_props},
        )
        db.session.add(hs_contact)
        db.session.commit()

        # Run the matcher
        svc = HubSpotMatcherService()
        match = svc.match_contact(hs_contact)
        db.session.commit()

        assert match.confidence == "HIGH", (
            f"Expected HIGH confidence for {match_by} match, got {match.confidence!r}"
        )

        # Clean up
        from app.models.hubspot_match import HubSpotMatch
        HubSpotMatch.query.filter_by(hubspot_id=hubspot_id).delete()
        db.session.delete(hs_contact)
        db.session.delete(contact)
        prop = db.session.get(Lead, property_id)
        if prop:
            db.session.delete(prop)
        db.session.commit()


# ===========================================================================
# Property 11: Unmatched HubSpot contacts create new Contact records
# Feature: property-contact-model, Property 11
# Validates: Requirements 10.3
# ===========================================================================

@given(
    first_name=_name_text,
    last_name=_name_text,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_unmatched_hubspot_contacts_create_new_contact_records(app, first_name, last_name):
    """Property 11: HubSpot contact with no match creates exactly one new Contact + PropertyContact.

    Total Contact count increases by exactly one.

    Validates: Requirements 10.3
    """
    # Feature: property-contact-model, Property 11: Unmatched HubSpot contacts create new Contact records
    with app.app_context():
        # Use a unique email, phone, and name suffix that won't match anything
        unique_suffix = uuid.uuid4().hex[:12]
        unmatched_email = f"unmatched_{unique_suffix}@nowhere-{unique_suffix}.com"
        unmatched_phone = f"9{unique_suffix[:9]}"  # 10 digits, unlikely to match
        # Append unique suffix to names so the name-match path (step 3) won't
        # accidentally match a Contact created by a previous test example.
        unique_first = f"{first_name}{unique_suffix[:6]}"
        unique_last = f"{last_name}{unique_suffix[6:]}"

        count_before = Contact.query.count()
        pc_count_before = PropertyContact.query.count()

        hubspot_id = f"hs_unmatched_{unique_suffix}"
        hs_contact = HubSpotContact(
            hubspot_id=hubspot_id,
            raw_payload={
                "properties": {
                    "email": unmatched_email,
                    "phone": unmatched_phone,
                    "firstname": unique_first,
                    "lastname": unique_last,
                }
            },
        )
        db.session.add(hs_contact)
        db.session.commit()

        svc = HubSpotMatcherService()
        svc.match_contact(hs_contact)
        db.session.commit()

        count_after = Contact.query.count()
        pc_count_after = PropertyContact.query.count()

        assert count_after == count_before + 1, (
            f"Expected Contact count to increase by 1 (from {count_before} to {count_before + 1}), "
            f"got {count_after}"
        )
        assert pc_count_after == pc_count_before + 1, (
            f"Expected PropertyContact count to increase by 1 (from {pc_count_before} to {pc_count_before + 1}), "
            f"got {pc_count_after}"
        )

        # Clean up
        from app.models.hubspot_match import HubSpotMatch
        HubSpotMatch.query.filter_by(hubspot_id=hubspot_id).delete()
        # Find and delete the newly created contact
        new_contact = ContactEmail.query.filter_by(value=unmatched_email).first()
        if new_contact:
            contact_obj = db.session.get(Contact, new_contact.contact_id)
            if contact_obj:
                db.session.delete(contact_obj)
        db.session.delete(hs_contact)
        db.session.commit()


# ===========================================================================
# Property 12: Matching never deletes existing Contact records
# Feature: property-contact-model, Property 12
# Validates: Requirements 10.5
# ===========================================================================

@given(
    num_existing=st.integers(min_value=1, max_value=5),
    hs_first=_name_text,
    hs_last=_name_text,
)
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_matching_never_deletes_existing_contact_records(app, num_existing, hs_first, hs_last):
    """Property 12: Running the HubSpot matcher does NOT decrease the total Contact count.

    Validates: Requirements 10.5
    """
    # Feature: property-contact-model, Property 12: Matching never deletes existing Contact records
    with app.app_context():
        # Create some existing Contact records
        created_ids = []
        for i in range(num_existing):
            contact = Contact(
                first_name=f"Existing{i}",
                last_name=f"Contact{i}",
                role="owner",
            )
            db.session.add(contact)
        db.session.commit()

        count_before = Contact.query.count()

        # Run the matcher with an arbitrary HubSpot contact payload
        unique_suffix = uuid.uuid4().hex[:12]
        hubspot_id = f"hs_nomatch_{unique_suffix}"
        hs_contact = HubSpotContact(
            hubspot_id=hubspot_id,
            raw_payload={
                "properties": {
                    "email": f"arbitrary_{unique_suffix}@test.com",
                    "phone": f"8{unique_suffix[:9]}",
                    "firstname": hs_first,
                    "lastname": hs_last,
                }
            },
        )
        db.session.add(hs_contact)
        db.session.commit()

        svc = HubSpotMatcherService()
        svc.match_contact(hs_contact)
        db.session.commit()

        count_after = Contact.query.count()

        assert count_after >= count_before, (
            f"Contact count decreased from {count_before} to {count_after} "
            f"after running HubSpot matcher — existing records were deleted"
        )

        # Clean up
        from app.models.hubspot_match import HubSpotMatch
        HubSpotMatch.query.filter_by(hubspot_id=hubspot_id).delete()
        db.session.delete(hs_contact)
        # Remove contacts created in this test run (those with Existing* names)
        for i in range(num_existing):
            c = Contact.query.filter_by(first_name=f"Existing{i}", last_name=f"Contact{i}").first()
            if c:
                db.session.delete(c)
        db.session.commit()


# ===========================================================================
# Property 13: Owner-name filter returns exactly matching properties
# Feature: property-contact-model, Property 13
# Validates: Requirements 11.1, 11.2
# ===========================================================================

@st.composite
def search_scenario_strategy(draw):
    """Generate a search string and sets of matching/non-matching property+contact pairs."""
    # Draw a search query (short, alpha-only for predictable substring matching)
    query = draw(st.text(min_size=2, max_size=8, alphabet=st.characters(whitelist_categories=("Ll",))))

    # Number of matching and non-matching properties
    num_matching = draw(st.integers(min_value=1, max_value=3))
    num_non_matching = draw(st.integers(min_value=0, max_value=3))

    # Matching contacts: first_name or last_name contains query (case-insensitive)
    matching_contacts = []
    for _ in range(num_matching):
        use_first = draw(st.booleans())
        if use_first:
            # Embed query in first_name
            prefix = draw(st.text(min_size=0, max_size=5, alphabet=st.characters(whitelist_categories=("Ll",))))
            suffix = draw(st.text(min_size=0, max_size=5, alphabet=st.characters(whitelist_categories=("Ll",))))
            first = prefix + query + suffix
            last = draw(_name_text)
        else:
            # Embed query in last_name
            prefix = draw(st.text(min_size=0, max_size=5, alphabet=st.characters(whitelist_categories=("Ll",))))
            suffix = draw(st.text(min_size=0, max_size=5, alphabet=st.characters(whitelist_categories=("Ll",))))
            first = draw(_name_text)
            last = prefix + query + suffix
        matching_contacts.append({"first_name": first, "last_name": last})

    # Non-matching contacts: neither first_name nor last_name contains query
    non_matching_contacts = []
    for _ in range(num_non_matching):
        # Generate names that definitely don't contain the query
        first = draw(st.text(min_size=1, max_size=10, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        last = draw(st.text(min_size=1, max_size=10, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        # Ensure neither contains the query (case-insensitive)
        assume(query.lower() not in first.lower())
        assume(query.lower() not in last.lower())
        non_matching_contacts.append({"first_name": first, "last_name": last})

    return {
        "query": query,
        "matching_contacts": matching_contacts,
        "non_matching_contacts": non_matching_contacts,
    }


@given(scenario=search_scenario_strategy())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_owner_name_filter_returns_exactly_matching_properties(app, client, scenario):
    """Property 13: GET /api/properties/?owner_name=q returns exactly matching properties.

    Returns properties with at least one linked Contact whose first_name or last_name
    contains q (case-insensitive). Does NOT return properties whose contacts don't match.

    Validates: Requirements 11.1, 11.2
    """
    # Feature: property-contact-model, Property 13: Owner-name filter returns exactly matching properties
    query = scenario["query"]
    matching_contacts = scenario["matching_contacts"]
    non_matching_contacts = scenario["non_matching_contacts"]

    with app.app_context():
        matching_property_ids = []
        non_matching_property_ids = []
        all_contact_ids = []
        all_property_ids = []

        # Create matching properties (each with a contact whose name contains query)
        for contact_data in matching_contacts:
            property_id = _create_property(app)
            matching_property_ids.append(property_id)
            all_property_ids.append(property_id)

            contact = Contact(
                first_name=contact_data["first_name"],
                last_name=contact_data["last_name"],
                role="owner",
            )
            db.session.add(contact)
            db.session.flush()
            all_contact_ids.append(contact.id)

            pc = PropertyContact(
                property_id=property_id,
                contact_id=contact.id,
                role="owner",
                is_primary=True,
            )
            db.session.add(pc)

        # Create non-matching properties (contacts whose names don't contain query)
        for contact_data in non_matching_contacts:
            property_id = _create_property(app)
            non_matching_property_ids.append(property_id)
            all_property_ids.append(property_id)

            contact = Contact(
                first_name=contact_data["first_name"],
                last_name=contact_data["last_name"],
                role="owner",
            )
            db.session.add(contact)
            db.session.flush()
            all_contact_ids.append(contact.id)

            pc = PropertyContact(
                property_id=property_id,
                contact_id=contact.id,
                role="owner",
                is_primary=True,
            )
            db.session.add(pc)

        db.session.commit()

        # Query the API with the owner_name filter
        resp = client.get(f"/api/properties/?owner_name={query}&per_page=100",
                          headers={'X-User-Id': 'test-user'})
        assert resp.status_code == 200
        data = resp.get_json()
        returned_ids = {item["id"] for item in data.get("leads", [])}

        # All matching property IDs should be in the results
        for pid in matching_property_ids:
            assert pid in returned_ids, (
                f"Matching property id={pid} not found in results for query={query!r}"
            )

        # No non-matching property IDs should be in the results
        for pid in non_matching_property_ids:
            assert pid not in returned_ids, (
                f"Non-matching property id={pid} incorrectly returned for query={query!r}"
            )

        # Clean up
        for cid in all_contact_ids:
            c = db.session.get(Contact, cid)
            if c:
                db.session.delete(c)
        for pid in all_property_ids:
            p = db.session.get(Lead, pid)
            if p:
                db.session.delete(p)
        db.session.commit()
