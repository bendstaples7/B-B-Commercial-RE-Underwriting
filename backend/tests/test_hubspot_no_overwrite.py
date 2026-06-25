"""Property-based tests for the no-overwrite-of-protected-fields invariant.

Property verified:
  19. No Overwrite of Protected Fields Without Confirmation — for any HubSpot
      import that produces a match to an existing Lead, the Lead's
      county_assessor_pin, property_street, lead_score, and source fields
      must remain unchanged after the import unless the match has been
      explicitly confirmed in the Review Queue.

This test requires a Flask app context because it creates Lead and HubSpotDeal
records in the in-memory SQLite database and calls HubSpotMatcherService.match_deal().
"""
# Feature: hubspot-crm-migration, Property 19: No overwrite of protected fields without confirmation

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.lead import Lead
from app.models.hubspot_deal import HubSpotDeal
from app.models.hubspot_match import HubSpotMatch
from app.services.hubspot_matcher_service import HubSpotMatcherService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_ASCII_ALPHA = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ASCII_DIGITS = "0123456789"

# PIN: 5–14 digit string
_pin_st = st.text(alphabet=_ASCII_DIGITS, min_size=5, max_size=14)

# Street address: "<number> <word> St"
_street_st = st.builds(
    lambda num, name: f"{num} {name} St",
    st.integers(min_value=1, max_value=9999).map(str),
    st.text(alphabet=_ASCII_ALPHA, min_size=3, max_size=20),
)

# Lead score: float in [0.0, 100.0]
_score_st = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)

# Source strings
_source_st = st.sampled_from(["manual", "google_sheets", "direct", "referral"])

# Conflicting HubSpot deal data (different PIN, different address, different source)
_conflicting_pin_st = st.text(alphabet=_ASCII_DIGITS, min_size=5, max_size=14)
_conflicting_street_st = st.builds(
    lambda num, name: f"{num} {name} Ave",
    st.integers(min_value=10000, max_value=99999).map(str),
    st.text(alphabet=_ASCII_ALPHA, min_size=3, max_size=20),
)


# ---------------------------------------------------------------------------
# Helper: build a HubSpotDeal with given properties
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


# ---------------------------------------------------------------------------
# Property 19: No Overwrite of Protected Fields Without Confirmation
# ---------------------------------------------------------------------------


class TestProperty19NoOverwriteProtectedFields:
    """Property 19 — protected Lead fields are unchanged after unconfirmed match.

    **Validates: Requirements 22.1, 22.2, 22.3**
    """

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        pin=_pin_st,
        street=_street_st,
        score=_score_st,
        source=_source_st,
    )
    def test_pin_match_does_not_overwrite_protected_fields(
        self, app, pin, street, score, source
    ) -> None:
        """After a PIN-matched (HIGH confidence) deal import, the Lead's protected
        fields must remain unchanged because the match is still pending (unconfirmed).

        # Feature: hubspot-crm-migration, Property 19: No overwrite of protected fields without confirmation
        **Validates: Requirements 22.1, 22.2, 22.3**
        """
        with app.app_context():
            # Create a Lead with specific protected field values
            lead = Lead(
                county_assessor_pin=pin,
                property_street=street,
                lead_score=score,
                source=source,
            )
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id

            # Record the protected field values before the import
            original_pin = lead.county_assessor_pin
            original_street = lead.property_street
            original_score = lead.lead_score
            original_source = lead.source

            # Create a HubSpot deal with the same PIN (will match HIGH confidence)
            # but with conflicting address data
            deal = _make_deal(
                hubspot_id=f"nooverwrite-{pin}",
                pin=pin,
                address="99999 Conflicting Blvd",
            )
            db.session.add(deal)
            db.session.flush()

            # Run the matcher — this creates a pending HubSpotMatch
            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)
            db.session.flush()

            # The match should be pending (unconfirmed)
            assert match.status == "pending", (
                f"Expected match status='pending', got '{match.status}'"
            )

            # Re-fetch the Lead from DB to verify protected fields are unchanged
            refreshed_lead = Lead.query.get(lead_id)

            assert refreshed_lead.county_assessor_pin == original_pin, (
                f"county_assessor_pin was overwritten: "
                f"'{original_pin}' → '{refreshed_lead.county_assessor_pin}'"
            )
            assert refreshed_lead.property_street == original_street, (
                f"property_street was overwritten: "
                f"'{original_street}' → '{refreshed_lead.property_street}'"
            )
            assert refreshed_lead.lead_score == original_score, (
                f"lead_score was overwritten: "
                f"{original_score} → {refreshed_lead.lead_score}"
            )
            assert refreshed_lead.source == original_source, (
                f"source was overwritten: "
                f"'{original_source}' → '{refreshed_lead.source}'"
            )

            db.session.rollback()

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(
        street=_street_st,
        score=_score_st,
        source=_source_st,
        conflicting_pin=_conflicting_pin_st,
    )
    def test_address_match_does_not_overwrite_protected_fields(
        self, app, street, score, source, conflicting_pin
    ) -> None:
        """After an address-matched (MEDIUM confidence) deal import, the Lead's
        protected fields must remain unchanged regardless of match status.

        When exactly one lead matches the address, the match is auto-confirmed
        (no ambiguity → no human review needed). When multiple leads match, the
        match stays pending for human review. In either case, protected fields
        on the lead must not be overwritten.

        # Feature: hubspot-crm-migration, Property 19: No overwrite of protected fields without confirmation
        **Validates: Requirements 22.1, 22.2, 22.3**
        """
        with app.app_context():
            # Create a Lead with a specific address but no PIN
            lead = Lead(
                county_assessor_pin=None,
                property_street=street,
                lead_score=score,
                source=source,
            )
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id

            original_street = lead.property_street
            original_score = lead.lead_score
            original_source = lead.source

            # Create a deal with a different PIN (no PIN match) but same address
            deal = _make_deal(
                hubspot_id=f"addrnooverwrite-{street[:10]}",
                pin=conflicting_pin,  # different PIN — forces address match path
                address=street,
            )
            db.session.add(deal)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)
            db.session.flush()

            # Match should be MEDIUM confidence.
            # With exactly one lead in the fixture, auto-confirm fires deterministically.
            assert match.confidence == "MEDIUM"
            assert match.status == "confirmed"

            # Protected fields must be unchanged
            refreshed_lead = Lead.query.get(lead_id)

            assert refreshed_lead.property_street == original_street, (
                f"property_street was overwritten: "
                f"'{original_street}' → '{refreshed_lead.property_street}'"
            )
            assert refreshed_lead.lead_score == original_score, (
                f"lead_score was overwritten: "
                f"{original_score} → {refreshed_lead.lead_score}"
            )
            assert refreshed_lead.source == original_source, (
                f"source was overwritten: "
                f"'{original_source}' → '{refreshed_lead.source}'"
            )

            db.session.rollback()

    def test_address_match_disambiguates_when_multiple_leads_share_address(self, app) -> None:
        """When multiple leads share the same normalised address the matcher
        picks the best candidate (HubSpot match / stage / contact data) instead
        of leaving the deal pending and creating a placeholder.

        # Feature: hubspot-crm-migration, Property 19
        **Validates: Requirements 22.1, 22.2**
        """
        with app.app_context():
            shared_street = "555 Ambiguous St"
            lead_a = Lead(property_street=shared_street, lead_score=40.0, source="manual")
            lead_b = Lead(property_street=shared_street, lead_score=60.0, source="manual")
            db.session.add_all([lead_a, lead_b])
            db.session.flush()

            deal = _make_deal(
                hubspot_id="ambiguous-addr-deal",
                pin="XXXXXXXXXXX",  # won't match either lead's PIN
                address=shared_street,
            )
            db.session.add(deal)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)
            db.session.flush()

            assert match.confidence == "MEDIUM"
            assert match.status == "confirmed", (
                f"Expected 'confirmed' after disambiguation, got '{match.status}'"
            )
            assert match.internal_record_id == lead_a.id, (
                "Lower id wins when stage/HubSpot/contact data are tied"
            )
            assert lead_b.review_required is True

            db.session.rollback()

    def test_confirmed_match_does_not_retroactively_overwrite_fields(self, app) -> None:
        """Even after a match is confirmed, the matcher itself never overwrites
        protected fields — field updates are a separate user-driven action.

        # Feature: hubspot-crm-migration, Property 19: No overwrite of protected fields without confirmation
        **Validates: Requirements 22.1, 22.2, 22.3**
        """
        with app.app_context():
            pin = "12345678901234"
            original_street = "100 Original Street"
            original_score = 75.0
            original_source = "manual"

            lead = Lead(
                county_assessor_pin=pin,
                property_street=original_street,
                lead_score=original_score,
                source=original_source,
            )
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id

            deal = _make_deal(
                hubspot_id="confirmed-test-deal",
                pin=pin,
                address="999 Different Blvd",
            )
            db.session.add(deal)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)
            db.session.flush()

            # Simulate user confirming the match
            match.status = "confirmed"
            db.session.flush()

            # Even after confirmation, the matcher has not touched the Lead fields
            refreshed_lead = Lead.query.get(lead_id)
            assert refreshed_lead.county_assessor_pin == pin
            assert refreshed_lead.property_street == original_street
            assert refreshed_lead.lead_score == original_score
            assert refreshed_lead.source == original_source

            db.session.rollback()

    def test_unmatched_deal_creates_placeholder_not_overwriting_existing_lead(self, app) -> None:
        """When a deal is UNMATCHED, a new placeholder Lead is created rather than
        overwriting any existing Lead's protected fields.

        # Feature: hubspot-crm-migration, Property 19: No overwrite of protected fields without confirmation
        **Validates: Requirements 22.1, 22.2, 22.3**
        """
        with app.app_context():
            # Create an existing Lead with protected fields
            existing_lead = Lead(
                county_assessor_pin="99999999",
                property_street="500 Existing Street",
                lead_score=50.0,
                source="manual",
            )
            db.session.add(existing_lead)
            db.session.flush()
            existing_lead_id = existing_lead.id

            original_pin = existing_lead.county_assessor_pin
            original_street = existing_lead.property_street
            original_score = existing_lead.lead_score
            original_source = existing_lead.source

            # Deal with a completely different PIN and address — will be UNMATCHED
            deal = _make_deal(
                hubspot_id="unmatched-test-deal",
                pin="00000000",  # no match
                address="1 Nowhere Lane",  # no match
            )
            db.session.add(deal)
            db.session.flush()

            svc = HubSpotMatcherService()
            match = svc.match_deal(deal)
            db.session.flush()

            assert match.confidence == "UNMATCHED"

            # The existing Lead's protected fields must be unchanged
            refreshed_lead = Lead.query.get(existing_lead_id)
            assert refreshed_lead.county_assessor_pin == original_pin
            assert refreshed_lead.property_street == original_street
            assert refreshed_lead.lead_score == original_score
            assert refreshed_lead.source == original_source

            db.session.rollback()
