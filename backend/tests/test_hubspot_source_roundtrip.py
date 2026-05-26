"""Property-based tests for HubSpot source fields preserved on round-trip.

Properties verified:
  10. HubSpot source fields are preserved on round-trip

Uses SQLite in-memory database via the Flask test app context (conftest.py).
"""
# Feature: hubspot-crm-migration, Property 10: HubSpot source fields are preserved on round-trip

from datetime import datetime

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models import Interaction


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid hubspot_engagement_id: non-empty string, max 50 chars, printable ASCII
hubspot_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=50,
)

# Arbitrary JSON-serialisable dict for raw_payload
json_value_strategy = st.recursive(
    base=st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-1_000_000, max_value=1_000_000),
        st.floats(allow_nan=False, allow_infinity=False, min_value=-1e9, max_value=1e9),
        st.text(max_size=50),
    ),
    extend=lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(min_size=1, max_size=20), children, max_size=5),
    ),
    max_leaves=20,
)

raw_payload_strategy = st.dictionaries(
    keys=st.text(min_size=1, max_size=20),
    values=json_value_strategy,
    max_size=10,
)


# ---------------------------------------------------------------------------
# Property 10: HubSpot Source Fields are Preserved on Round-Trip
# ---------------------------------------------------------------------------


@given(
    hubspot_engagement_id=hubspot_id_strategy,
    raw_payload=raw_payload_strategy,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_hubspot_source_fields_preserved_on_roundtrip(app, hubspot_engagement_id, raw_payload):
    """Interaction created with source='hubspot_import' must have non-null
    hubspot_engagement_id and raw_payload equal to the provided values after
    a persist-and-retrieve cycle.

    **Validates: Requirements 2.5**
    """
    with app.app_context():
        # Clean up any leftover record from a previous Hypothesis example
        Interaction.query.filter_by(
            hubspot_engagement_id=hubspot_engagement_id
        ).delete()
        db.session.commit()

        # Create an Interaction with source='hubspot_import'
        interaction = Interaction(
            interaction_type='note',
            body='HubSpot imported note body',
            occurred_at=datetime(2024, 1, 15, 10, 0, 0),
            source='hubspot_import',
            hubspot_engagement_id=hubspot_engagement_id,
            raw_payload=raw_payload,
        )
        db.session.add(interaction)
        db.session.commit()
        saved_id = interaction.id

        # Expire the session so we retrieve a fresh copy from the DB
        db.session.expire_all()

        # Retrieve from DB
        retrieved = Interaction.query.get(saved_id)

        # Assert hubspot_engagement_id is non-null and matches
        assert retrieved.hubspot_engagement_id is not None, (
            "hubspot_engagement_id must be non-null for hubspot_import source"
        )
        assert retrieved.hubspot_engagement_id == hubspot_engagement_id, (
            f"Expected hubspot_engagement_id={hubspot_engagement_id!r}, "
            f"got {retrieved.hubspot_engagement_id!r}"
        )

        # Assert raw_payload is non-null and matches
        assert retrieved.raw_payload is not None, (
            "raw_payload must be non-null for hubspot_import source"
        )
        assert retrieved.raw_payload == raw_payload, (
            f"Expected raw_payload={raw_payload!r}, got {retrieved.raw_payload!r}"
        )

        # Assert source is preserved
        assert retrieved.source == 'hubspot_import', (
            f"Expected source='hubspot_import', got {retrieved.source!r}"
        )

        # Clean up
        Interaction.query.filter_by(id=saved_id).delete()
        db.session.commit()
