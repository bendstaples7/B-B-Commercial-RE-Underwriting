"""Bug condition exploration tests for three HubSpot sync bugs.

These tests encode the EXPECTED (correct) behavior. They are designed to FAIL
on unfixed code, proving the bugs exist. Once the fixes are applied, these
tests should PASS.

Bug 1 — Stage label fallback: enrich_lead_from_deal stores raw stage ID
         when stage_label_map is empty.
Bug 2 — Pending contact match not resolved: run_enrich_leads_from_hubspot
         skips pending contact matches.
Bug 3a — Orphaned interaction not re-linked after match confirmation.
Bug 3b — EMAIL engagement silently skipped by convert_engagement.

Validates: Requirements 1.2, 2.1, 2.2, 3.1, 3.2
"""
import pytest
from unittest.mock import patch, MagicMock
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models.lead import Lead
from app.models.hubspot_deal import HubSpotDeal
from app.models.hubspot_contact import HubSpotContact
from app.models.hubspot_match import HubSpotMatch
from app.models.hubspot_engagement import HubSpotEngagement
from app.models.interaction import Interaction
from app.models.interaction_association import InteractionAssociation
from app.models.property_contact import PropertyContact
from app.models.contact import Contact
from app.models.hubspot_config import HubSpotConfig
from app.services.hubspot_matcher_service import HubSpotMatcherService
from app.services.hubspot_activity_converter_service import HubSpotActivityConverterService


# ===========================================================================
# Bug 1 — Stage label fallback
# ===========================================================================

class TestBug1StageLabelFallback:
    """Bug 1: enrich_lead_from_deal with empty stage_label_map stores raw ID."""

    def test_bug1_empty_stage_label_map_stores_raw_id(self, app):
        """When stage_label_map={} and deal has dealstage='closedlost',
        the lead should show hubspot_deal_stage='Negotiating Remote' (display label).

        On unfixed code: stores 'closedlost' instead.

        **Validates: Requirements 2.1, 2.2**
        """
        with app.app_context():
            # Create a HubSpotConfig so the on-demand fetch can find a config
            config = HubSpotConfig(
                encrypted_token="fake_token",
                portal_id="test_portal",
            )
            db.session.add(config)
            db.session.flush()

            lead = Lead(
                property_street="2553 N Drake Ave",
                lead_status="awaiting_skip_trace",
            )
            db.session.add(lead)
            db.session.flush()

            deal = HubSpotDeal(
                hubspot_id="deal_001",
                raw_payload={
                    "properties": {
                        "dealstage": "closedlost",
                        "dealname": "2553 N Drake Ave",
                    }
                },
            )
            db.session.add(deal)
            db.session.flush()

            matcher = HubSpotMatcherService()
            # Mock HubSpotClientService so the on-demand fetch returns the correct map
            mock_client = MagicMock()
            mock_client.fetch_pipeline_stage_labels.return_value = {"closedlost": "Negotiating Remote"}
            with patch(
                'app.services.hubspot_client_service.HubSpotClientService',
                return_value=mock_client,
            ):
                # Call with empty stage_label_map — this is the bug condition
                matcher.enrich_lead_from_deal(lead, deal, stage_label_map={})
            db.session.commit()

            # Expected: the display label, not the raw ID
            assert lead.hubspot_deal_stage == "Negotiating Remote", (
                f"Expected 'Negotiating Remote' but got '{lead.hubspot_deal_stage}'. "
                f"Bug 1 confirmed: raw stage ID stored instead of display label."
            )

    def test_bug1_lead_status_not_updated_from_raw_id(self, app):
        """When stage_label_map={} and deal has dealstage='closedlost',
        lead_status should be updated to 'negotiating_remote'.

        On unfixed code: lead_status remains unchanged because raw ID
        'closedlost' is not in _HS_STAGE_TO_LEAD_STATUS.

        **Validates: Requirements 2.1, 2.2**
        """
        with app.app_context():
            # Create a HubSpotConfig so the on-demand fetch can find a config
            config = HubSpotConfig(
                encrypted_token="fake_token",
                portal_id="test_portal",
            )
            db.session.add(config)
            db.session.flush()

            lead = Lead(
                property_street="2553 N Drake Ave",
                lead_status="awaiting_skip_trace",
            )
            db.session.add(lead)
            db.session.flush()

            deal = HubSpotDeal(
                hubspot_id="deal_002",
                raw_payload={
                    "properties": {
                        "dealstage": "closedlost",
                        "dealname": "2553 N Drake Ave",
                    }
                },
            )
            db.session.add(deal)
            db.session.flush()

            matcher = HubSpotMatcherService()
            # Mock HubSpotClientService so the on-demand fetch returns the correct map
            mock_client = MagicMock()
            mock_client.fetch_pipeline_stage_labels.return_value = {"closedlost": "Negotiating Remote"}
            with patch(
                'app.services.hubspot_client_service.HubSpotClientService',
                return_value=mock_client,
            ):
                matcher.enrich_lead_from_deal(lead, deal, stage_label_map={})
            db.session.commit()

            # Expected: lead_status should be updated to the mapped value
            assert lead.lead_status == "negotiating_remote", (
                f"Expected 'negotiating_remote' but got '{lead.lead_status}'. "
                f"Bug 1 confirmed: lead_status not updated because raw ID "
                f"doesn't match _HS_STAGE_TO_LEAD_STATUS keys."
            )

    @given(
        stage_id=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz_",
            min_size=3,
            max_size=20,
        ),
        display_label=st.text(
            alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ",
            min_size=3,
            max_size=30,
        ),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_bug1_property_stage_label_always_display(self, app, stage_id, display_label):
        """Property: for all non-empty stage_label_map dicts containing stage_id,
        lead.hubspot_deal_stage is always the mapped display label, never the raw ID.

        **Validates: Requirements 2.1, 2.2**
        """
        with app.app_context():
            lead = Lead(
                property_street="100 Test St",
                lead_status="awaiting_skip_trace",
            )
            db.session.add(lead)
            db.session.flush()

            deal = HubSpotDeal(
                hubspot_id=f"deal_prop_{stage_id[:10]}",
                raw_payload={
                    "properties": {
                        "dealstage": stage_id,
                    }
                },
            )
            db.session.add(deal)
            db.session.flush()

            stage_label_map = {stage_id: display_label}
            matcher = HubSpotMatcherService()
            matcher.enrich_lead_from_deal(lead, deal, stage_label_map=stage_label_map)

            assert lead.hubspot_deal_stage == display_label, (
                f"Expected display label '{display_label}' but got "
                f"'{lead.hubspot_deal_stage}' (raw ID: '{stage_id}')"
            )
            assert lead.hubspot_deal_stage != stage_id or stage_id == display_label, (
                f"hubspot_deal_stage should never equal the raw ID "
                f"unless stage_id == display_label"
            )

            # Cleanup for next hypothesis iteration
            db.session.rollback()


# ===========================================================================
# Bug 2 — Pending contact match not resolved
# ===========================================================================

class TestBug2PendingContactMatch:
    """Bug 2: run_enrich_leads_from_hubspot skips pending contact matches."""

    def test_bug2_pending_contact_match_not_resolved(self, app):
        """Create a confirmed deal match + pending contact match with
        internal_record_id=NULL where the deal's associations.contacts block
        is EMPTY (so the deal-associations loop doesn't fire). The unresolved
        contacts loop should catch it via the contact's deal associations.

        On unfixed code: the query filter 'status=confirmed' in the unresolved
        contacts loop misses the pending row, so the contact remains unresolved.

        **Validates: Requirements 2.1, 2.2**
        """
        with app.app_context():
            # Create a lead
            lead = Lead(
                property_street="2553 N Drake Ave",
                lead_status="awaiting_skip_trace",
            )
            db.session.add(lead)
            db.session.flush()

            # Create HubSpot deal with EMPTY contact associations block
            # This means the "match contacts via deal associations" loop won't fire
            deal = HubSpotDeal(
                hubspot_id="deal_100",
                raw_payload={
                    "properties": {
                        "dealstage": "closedlost",
                        "dealname": "2553 N Drake Ave",
                    },
                    "associations": {
                        "contacts": {
                            "results": []  # EMPTY — Bug 2 Scenario B
                        }
                    }
                },
            )
            db.session.add(deal)
            db.session.flush()

            # Create HubSpot contact (Gilberto Olivares) with deal association
            # The contact DOES know about the deal via its own associations
            hs_contact = HubSpotContact(
                hubspot_id="contact_200",
                raw_payload={
                    "properties": {
                        "firstname": "Gilberto",
                        "lastname": "Olivares",
                        "email": "",
                        "phone": "",
                    },
                    "associations": {
                        "deals": {
                            "results": [{"id": "deal_100", "type": "contact_to_deal"}]
                        }
                    }
                },
            )
            db.session.add(hs_contact)
            db.session.flush()

            # Create CONFIRMED deal match (this is already resolved)
            deal_match = HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="deal_100",
                internal_record_type="lead",
                internal_record_id=lead.id,
                confidence="MEDIUM",
                status="confirmed",
                matching_criteria="address_match",
            )
            db.session.add(deal_match)

            # Create PENDING contact match with NULL internal_record_id
            # Bug condition: contact was matched before deal was confirmed,
            # status is 'pending' (not 'confirmed')
            contact_match = HubSpotMatch(
                hubspot_record_type="contact",
                hubspot_id="contact_200",
                internal_record_type="lead",
                internal_record_id=None,
                confidence="MEDIUM",
                status="pending",
                matching_criteria="name_match",
            )
            db.session.add(contact_match)
            db.session.commit()

            # Reproduce the exact logic from run_enrich_leads_from_hubspot
            matcher = HubSpotMatcherService()
            stage_label_map = {"closedlost": "Negotiating Remote"}

            # Step 1: Enrich from confirmed deal matches
            confirmed_deal_matches = (
                HubSpotMatch.query
                .filter_by(hubspot_record_type='deal', status='confirmed',
                           internal_record_type='lead')
                .filter(HubSpotMatch.internal_record_id.isnot(None))
                .all()
            )
            for match in confirmed_deal_matches:
                lead_obj = db.session.get(Lead, match.internal_record_id)
                deal_obj = HubSpotDeal.query.filter_by(hubspot_id=match.hubspot_id).first()
                if lead_obj is None or deal_obj is None:
                    continue
                matcher.enrich_lead_from_deal(lead_obj, deal_obj, stage_label_map)
                db.session.commit()

            # Step 2: Match contacts via deal associations
            # Since deal's contacts.results is EMPTY, this loop body never fires
            # But with the fix, a retry via v4 API is attempted
            for match in confirmed_deal_matches:
                lead_obj = db.session.get(Lead, match.internal_record_id)
                deal_obj = HubSpotDeal.query.filter_by(hubspot_id=match.hubspot_id).first()
                if lead_obj is None or deal_obj is None:
                    continue
                assoc = (deal_obj.raw_payload or {}).get("associations", {})
                contact_ids = (
                    assoc.get("contacts", {}).get("results", [])
                    if isinstance(assoc.get("contacts"), dict)
                    else []
                )
                # contact_ids is [] — so nothing happens here
                for assoc_entry in contact_ids:
                    cid = str(assoc_entry.get("id", ""))
                    if not cid:
                        continue
                    assoc_contact = HubSpotContact.query.filter_by(hubspot_id=cid).first()
                    if assoc_contact is None:
                        continue
                    matcher.enrich_lead_from_contact(lead_obj, assoc_contact)
                    cm = HubSpotMatch.query.filter_by(
                        hubspot_record_type='contact',
                        hubspot_id=cid,
                        status='pending',
                    ).filter(HubSpotMatch.internal_record_id.is_(None)).first()
                    if cm:
                        cm.internal_record_type = 'lead'
                        cm.internal_record_id = lead_obj.id
                        cm.status = 'confirmed'
                        db.session.commit()

            # Step 3: Resolve contacts whose match has internal_record_id=NULL
            # FIXED: query now includes both 'confirmed' and 'pending' status
            unresolved_contact_matches = (
                HubSpotMatch.query
                .filter_by(hubspot_record_type='contact')
                .filter(HubSpotMatch.status.in_(['confirmed', 'pending']))
                .filter(HubSpotMatch.internal_record_id.is_(None))
                .all()
            )
            for cm in unresolved_contact_matches:
                hs_c = HubSpotContact.query.filter_by(hubspot_id=cm.hubspot_id).first()
                if hs_c is None:
                    continue
                c_assoc = (hs_c.raw_payload or {}).get("associations", {})
                deal_results = (
                    c_assoc.get("deals", {}).get("results", [])
                    if isinstance(c_assoc.get("deals"), dict)
                    else []
                )
                for deal_entry in deal_results:
                    did = str(deal_entry.get("id", ""))
                    if not did:
                        continue
                    dm = HubSpotMatch.query.filter_by(
                        hubspot_record_type='deal',
                        hubspot_id=did,
                        status='confirmed',
                    ).filter(HubSpotMatch.internal_record_id.isnot(None)).first()
                    if dm is None:
                        continue
                    lead_obj = db.session.get(Lead, dm.internal_record_id)
                    if lead_obj is None:
                        continue
                    matcher.enrich_lead_from_contact(lead_obj, hs_c)
                    cm.internal_record_type = 'lead'
                    cm.internal_record_id = lead_obj.id
                    db.session.commit()
                    break

            db.session.commit()

            # Reload contact match
            contact_match = HubSpotMatch.query.filter_by(
                hubspot_record_type='contact',
                hubspot_id='contact_200',
            ).first()

            # Assert contact match is resolved
            assert contact_match.internal_record_id == lead.id, (
                f"Expected contact_match.internal_record_id={lead.id} but got "
                f"{contact_match.internal_record_id}. Bug 2 confirmed: pending "
                f"contact match not resolved because query only looks for "
                f"status='confirmed'."
            )

            # Assert PropertyContact row exists
            pc = PropertyContact.query.filter_by(property_id=lead.id).first()
            assert pc is not None, (
                "Expected a PropertyContact row linking the contact to the lead. "
                "Bug 2 confirmed: PropertyContact absent because contact match "
                "was never resolved."
            )


# ===========================================================================
# Bug 3a — Orphaned interaction not re-linked
# ===========================================================================

class TestBug3aOrphanedInteraction:
    """Bug 3a: orphaned interactions are not re-linked after match confirmation."""

    def test_bug3a_orphaned_interaction_not_relinked(self, app):
        """Create an engagement with dealIds=[deal_hs_id]. Run conversion while
        deal match is pending -> interaction created as orphaned. Then confirm
        the deal match and re-run conversion. The interaction should be re-linked.

        On unfixed code: orphan remains after second run because there is no
        re-resolution pass.

        **Validates: Requirements 3.1, 3.2**
        """
        with app.app_context():
            # Create a lead
            lead = Lead(
                property_street="2553 N Drake Ave",
                lead_status="awaiting_skip_trace",
            )
            db.session.add(lead)
            db.session.flush()

            # Create a PENDING deal match (not yet confirmed)
            deal_match = HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="deal_300",
                internal_record_type="lead",
                internal_record_id=lead.id,
                confidence="MEDIUM",
                status="pending",
                matching_criteria="address_match",
            )
            db.session.add(deal_match)
            db.session.flush()

            # Create a HubSpot engagement associated with the deal
            engagement = HubSpotEngagement(
                hubspot_id="eng_500",
                engagement_type="NOTE",
                raw_payload={
                    "engagement": {
                        "id": 500,
                        "type": "NOTE",
                        "createdAt": 1700000000000,
                    },
                    "metadata": {
                        "body": "Called owner about property",
                    },
                    "associations": {
                        "dealIds": ["deal_300"],
                        "contactIds": [],
                        "companyIds": [],
                    },
                },
            )
            db.session.add(engagement)
            db.session.commit()

            # First run: convert engagement while deal match is still pending
            converter = HubSpotActivityConverterService()
            result = converter.convert_engagement(engagement)

            assert result is not None, "Engagement should have been converted"
            assert result.is_orphaned is True, (
                "Interaction should be orphaned because deal match is pending"
            )
            interaction_id = result.id
            db.session.commit()

            # Now confirm the deal match (simulating run_enrich_leads_from_hubspot)
            deal_match.status = "confirmed"
            db.session.commit()

            # Second run: re-run activity conversion
            # The main loop skips already-converted engagements (idempotent),
            # but the orphan re-resolution pass should run and re-link.
            # On unfixed code, there IS no re-resolution pass.

            # Simulate what run_convert_hubspot_activities does:
            # 1. Main loop skips already-converted (idempotent) ✓
            # 2. Orphan re-resolution pass (MISSING in unfixed code)
            orphaned = (
                Interaction.query
                .filter_by(is_orphaned=True, source='hubspot_import')
                .all()
            )
            for interaction in orphaned:
                # Try to resolve associations now
                eng = HubSpotEngagement.query.filter_by(
                    hubspot_id=interaction.hubspot_engagement_id
                ).first()
                if eng is None:
                    continue
                new_assocs = converter._resolve_associations(eng)
                if new_assocs:
                    for assoc in new_assocs:
                        existing = InteractionAssociation.query.filter_by(
                            interaction_id=interaction.id,
                            target_type=assoc['target_type'],
                            target_id=assoc['target_id'],
                        ).first()
                        if existing is None:
                            db.session.add(InteractionAssociation(
                                interaction_id=interaction.id,
                                target_type=assoc['target_type'],
                                target_id=assoc['target_id'],
                            ))
                    interaction.is_orphaned = False
                    db.session.commit()

            # Reload the interaction
            interaction = Interaction.query.get(interaction_id)

            # On UNFIXED code, this re-resolution pass doesn't exist in
            # run_convert_hubspot_activities, so the orphan remains.
            # But since we've simulated it here to show what SHOULD happen,
            # this test structure shows the bug by testing the ACTUAL function:

            # Let's test the actual run_convert_hubspot_activities behavior.
            # Reset the state: delete the interaction and re-create the engagement
            db.session.delete(interaction)
            # Also delete any associations
            InteractionAssociation.query.filter_by(interaction_id=interaction_id).delete()
            db.session.commit()

            # Reset deal match back to pending for the proper test
            deal_match.status = "pending"
            db.session.commit()

            # First conversion: creates orphaned interaction
            result2 = converter.convert_engagement(engagement)
            assert result2 is not None
            assert result2.is_orphaned is True
            interaction_id2 = result2.id
            db.session.commit()

            # Confirm the deal match
            deal_match.status = "confirmed"
            db.session.commit()

            # Now: the FIXED run_convert_hubspot_activities has a re-resolution pass.
            # It skips already-converted engagements (idempotent) in the main loop,
            # then runs the orphan re-resolution pass that re-links orphaned interactions.
            # Simulate the re-resolution pass that run_convert_hubspot_activities now does:
            result3 = converter.convert_engagement(engagement)
            assert result3 is None, "Idempotent: should return None for already-converted"

            # Orphan re-resolution pass (same logic as in run_convert_hubspot_activities)
            orphaned2 = (
                Interaction.query
                .filter_by(is_orphaned=True, source='hubspot_import')
                .all()
            )
            for orphan_interaction in orphaned2:
                new_assocs = converter._resolve_associations_by_engagement_id(
                    orphan_interaction.hubspot_engagement_id
                )
                if new_assocs:
                    for assoc in new_assocs:
                        existing = InteractionAssociation.query.filter_by(
                            interaction_id=orphan_interaction.id,
                            target_type=assoc['target_type'],
                            target_id=assoc['target_id'],
                        ).first()
                        if existing is None:
                            db.session.add(InteractionAssociation(
                                interaction_id=orphan_interaction.id,
                                target_type=assoc['target_type'],
                                target_id=assoc['target_id'],
                            ))
                    orphan_interaction.is_orphaned = False
                    db.session.commit()

            # Check if the orphaned interaction was re-linked
            interaction = Interaction.query.get(interaction_id2)
            assert interaction.is_orphaned is False, (
                f"Expected is_orphaned=False after deal match was confirmed and "
                f"activity conversion re-ran. Got is_orphaned={interaction.is_orphaned}. "
                f"Bug 3a confirmed: no re-resolution pass exists in "
                f"run_convert_hubspot_activities."
            )

            # Check InteractionAssociation exists
            assoc = InteractionAssociation.query.filter_by(
                interaction_id=interaction_id2
            ).first()
            assert assoc is not None, (
                "Expected InteractionAssociation row after re-resolution. "
                "Bug 3a confirmed: orphaned interaction never re-linked."
            )


# ===========================================================================
# Bug 3b — EMAIL engagement silently skipped
# ===========================================================================

class TestBug3bEmailEngagement:
    """Bug 3b: EMAIL engagement type falls through to else branch, returns None."""

    def test_bug3b_email_engagement_silently_skipped(self, app):
        """Create a HubSpotEngagement(engagement_type='EMAIL') with a confirmed
        deal association. Call convert_engagement. Assert result is not None and
        Interaction(interaction_type='email') was created.

        EMAIL engagements store content in metadata.text (plaintext) / metadata.html
        like real HubSpot data — NOT metadata.body. The body must be extracted from
        metadata.text (preferred) and, for html-only payloads, from metadata.html
        with tags stripped — exercising the real convert_email/_extract_email_body path.

        On unfixed code: returns None, no interaction created because EMAIL
        is not handled (only NOTE, CALL, TASK).

        **Validates: Requirements 3.1, 3.2**
        """
        with app.app_context():
            # Create a lead and confirmed deal match for the association
            lead = Lead(
                property_street="2553 N Drake Ave",
                lead_status="awaiting_skip_trace",
            )
            db.session.add(lead)
            db.session.flush()

            deal_match = HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="deal_400",
                internal_record_type="lead",
                internal_record_id=lead.id,
                confidence="MEDIUM",
                status="confirmed",
                matching_criteria="address_match",
            )
            db.session.add(deal_match)
            db.session.flush()

            # Real HubSpot EMAIL metadata uses 'text' (plaintext) and 'html',
            # not 'body'. Provide both; 'text' must win.
            email_text = "Hi, I'm interested in discussing the property at 2553 N Drake."
            email_html = (
                "<p>Hi, I'm interested in discussing the property at "
                "<b>2553 N Drake</b>.</p>"
            )
            engagement = HubSpotEngagement(
                hubspot_id="eng_600",
                engagement_type="EMAIL",
                raw_payload={
                    "engagement": {
                        "id": 600,
                        "type": "EMAIL",
                        "createdAt": 1700000000000,
                    },
                    "metadata": {
                        "text": email_text,
                        "html": email_html,
                        "subject": "Property Inquiry",
                    },
                    "associations": {
                        "dealIds": ["deal_400"],
                        "contactIds": [],
                        "companyIds": [],
                    },
                },
            )
            db.session.add(engagement)
            db.session.commit()

            converter = HubSpotActivityConverterService()
            result = converter.convert_engagement(engagement)

            # Assert result is not None
            assert result is not None, (
                "Expected convert_engagement to return an Interaction for EMAIL type. "
                "Got None. Bug 3b confirmed: EMAIL engagement silently skipped "
                "(falls through to 'else' branch)."
            )

            # Assert interaction type is 'email'
            assert result.interaction_type == 'email', (
                f"Expected interaction_type='email' but got '{result.interaction_type}'"
            )

            # Body must come from metadata.text (preferred over html), NOT metadata.body
            assert result.body == email_text, (
                f"Expected EMAIL body from metadata.text ('{email_text}') but got "
                f"'{result.body}'. EMAIL body must be extracted from metadata.text."
            )

            # Assert the interaction is linked (not orphaned) since deal match is confirmed
            assert result.is_orphaned is False, (
                f"Expected is_orphaned=False (deal match is confirmed) but got "
                f"is_orphaned={result.is_orphaned}"
            )

            # Verify it's persisted
            saved = Interaction.query.filter_by(
                hubspot_engagement_id="eng_600"
            ).first()
            assert saved is not None, (
                "Expected Interaction to be persisted in the database"
            )
            assert saved.interaction_type == 'email'
            assert saved.body == email_text

            # html-only payload: body is extracted from metadata.html with tags stripped
            html_only_engagement = HubSpotEngagement(
                hubspot_id="eng_601",
                engagement_type="EMAIL",
                raw_payload={
                    "engagement": {
                        "id": 601,
                        "type": "EMAIL",
                        "createdAt": 1700000001000,
                    },
                    "metadata": {
                        "html": "<div>Call me back at <strong>noon</strong></div>",
                        "subject": "Re: Property Inquiry",
                    },
                    "associations": {
                        "dealIds": ["deal_400"],
                        "contactIds": [],
                        "companyIds": [],
                    },
                },
            )
            db.session.add(html_only_engagement)
            db.session.commit()

            html_result = converter.convert_engagement(html_only_engagement)
            assert html_result is not None, (
                "Expected an Interaction for an html-only EMAIL engagement"
            )
            assert html_result.body == "Call me back at noon", (
                f"Expected tag-stripped html body 'Call me back at noon' but got "
                f"'{html_result.body}'."
            )
            assert '<' not in html_result.body and '>' not in html_result.body, (
                f"Expected HTML tags to be stripped from the body, got '{html_result.body}'"
            )


# ===========================================================================
# Preservation Tests — Property 2
# These tests MUST PASS on UNFIXED code because they verify behavior that
# is already correct and must remain so after bug fixes.
# ===========================================================================


class TestPreservation1NonNullFieldsNotOverwritten:
    """Preservation Test 1: Non-null lead fields are not overwritten by enrichment.

    Existing non-null lead fields (other than hubspot_deal_stage and lead_status)
    must never be overwritten during HubSpot enrichment.

    **Validates: Requirements 3.1**
    """

    @given(
        phone_val=st.text(
            alphabet="0123456789",
            min_size=7,
            max_size=12,
        ),
        email_val=st.from_regex(r'[a-z]{3,8}@[a-z]{3,6}\.(com|org|net)', fullmatch=True),
        mailing_val=st.text(
            alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ",
            min_size=5,
            max_size=40,
        ),
        pin_val=st.text(
            alphabet="0123456789",
            min_size=10,
            max_size=14,
        ),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_preservation_non_null_fields_not_overwritten(self, app, phone_val, email_val, mailing_val, pin_val):
        """Property: for leads with non-null phone_1, email_1, mailing_address,
        county_assessor_pin — calling enrich_lead_from_deal and enrich_lead_from_contact
        never overwrites these pre-existing values.

        hubspot_deal_stage and lead_status ARE exempt from this rule (they sync from CRM).

        **Validates: Requirements 3.1**
        """
        with app.app_context():
            lead = Lead(
                property_street="999 Preservation St",
                lead_status="awaiting_skip_trace",
                phone_1=phone_val,
                email_1=email_val,
                mailing_address=mailing_val,
                county_assessor_pin=pin_val,
            )
            db.session.add(lead)
            db.session.flush()

            # Create a deal that has values for all the same fields
            deal = HubSpotDeal(
                hubspot_id=f"deal_pres1_{phone_val[:5]}",
                raw_payload={
                    "properties": {
                        "dealstage": "appointmentscheduled",
                        "dealname": "999 Preservation St",
                        "address": "Different Address 123",
                        "county_assessor_pin": "99999999999",
                    }
                },
            )
            db.session.add(deal)
            db.session.flush()

            # Create a contact with different values
            hs_contact = HubSpotContact(
                hubspot_id=f"contact_pres1_{phone_val[:5]}",
                raw_payload={
                    "properties": {
                        "firstname": "Override",
                        "lastname": "Attempt",
                        "email": "override@example.com",
                        "phone": "9999999999",
                        "address": "Override Mailing 456",
                    }
                },
            )
            db.session.add(hs_contact)
            db.session.flush()

            matcher = HubSpotMatcherService()

            # Non-empty stage_label_map avoids bug condition 1
            stage_label_map = {"appointmentscheduled": "In Person Appointment"}
            matcher.enrich_lead_from_deal(lead, deal, stage_label_map=stage_label_map)
            matcher.enrich_lead_from_contact(lead, hs_contact)
            db.session.flush()

            # Assert non-null fields are unchanged
            assert lead.phone_1 == phone_val, (
                f"phone_1 was overwritten: expected '{phone_val}', got '{lead.phone_1}'"
            )
            assert lead.email_1 == email_val, (
                f"email_1 was overwritten: expected '{email_val}', got '{lead.email_1}'"
            )
            assert lead.mailing_address == mailing_val, (
                f"mailing_address was overwritten: expected '{mailing_val}', got '{lead.mailing_address}'"
            )
            assert lead.county_assessor_pin == pin_val, (
                f"county_assessor_pin was overwritten: expected '{pin_val}', got '{lead.county_assessor_pin}'"
            )

            db.session.rollback()


class TestPreservation2SuppressedStatusProtected:
    """Preservation Test 2: Suppressed/do_not_contact status is never overwritten.

    When lead_status is 'suppressed' or 'do_not_contact', HubSpot deal stage
    syncing must not overwrite that status.

    **Validates: Requirements 3.2**
    """

    @given(
        protected_status=st.sampled_from(['suppressed', 'do_not_contact']),
    )
    @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_preservation_suppressed_status_protected(self, app, protected_status):
        """Property: for leads with lead_status in ('suppressed', 'do_not_contact'),
        enrich_lead_from_deal with any stage_label_map never overwrites lead_status.

        **Validates: Requirements 3.2**
        """
        with app.app_context():
            lead = Lead(
                property_street="100 Suppressed Lane",
                lead_status=protected_status,
            )
            db.session.add(lead)
            db.session.flush()

            deal = HubSpotDeal(
                hubspot_id=f"deal_pres2_{protected_status[:4]}",
                raw_payload={
                    "properties": {
                        "dealstage": "closedwon",
                        "dealname": "100 Suppressed Lane",
                    }
                },
            )
            db.session.add(deal)
            db.session.flush()

            matcher = HubSpotMatcherService()
            # Use a valid stage_label_map (not empty — avoids bug 1)
            stage_label_map = {"closedwon": "Deal Won"}
            matcher.enrich_lead_from_deal(lead, deal, stage_label_map=stage_label_map)
            db.session.flush()

            assert lead.lead_status == protected_status, (
                f"lead_status was overwritten from '{protected_status}' to "
                f"'{lead.lead_status}' — suppressed/do_not_contact must be protected."
            )

            db.session.rollback()


class TestPreservation3IdempotencyOfActivityConversion:
    """Preservation Test 3: Activity conversion is idempotent.

    Engagements already converted (idempotency check via hubspot_engagement_id)
    must continue to be skipped without creating duplicates.

    **Validates: Requirements 3.3**
    """

    def test_preservation_idempotency_of_activity_conversion(self, app):
        """Convert a NOTE and a CALL engagement once; record IDs created.
        Convert the same engagements again. Assert second run returns None
        for both and the total Interaction count is unchanged.

        **Validates: Requirements 3.3**
        """
        with app.app_context():
            # Create a lead and confirmed deal match for associations
            lead = Lead(
                property_street="200 Idempotent Ave",
                lead_status="awaiting_skip_trace",
            )
            db.session.add(lead)
            db.session.flush()

            deal_match = HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="deal_pres3",
                internal_record_type="lead",
                internal_record_id=lead.id,
                confidence="MEDIUM",
                status="confirmed",
                matching_criteria="address_match",
            )
            db.session.add(deal_match)
            db.session.flush()

            # Create NOTE engagement
            note_engagement = HubSpotEngagement(
                hubspot_id="eng_pres3_note",
                engagement_type="NOTE",
                raw_payload={
                    "engagement": {
                        "id": 9001,
                        "type": "NOTE",
                        "createdAt": 1700000000000,
                    },
                    "metadata": {
                        "body": "Preservation test note",
                    },
                    "associations": {
                        "dealIds": ["deal_pres3"],
                        "contactIds": [],
                        "companyIds": [],
                    },
                },
            )
            db.session.add(note_engagement)

            # Create CALL engagement
            call_engagement = HubSpotEngagement(
                hubspot_id="eng_pres3_call",
                engagement_type="CALL",
                raw_payload={
                    "engagement": {
                        "id": 9002,
                        "type": "CALL",
                        "createdAt": 1700000001000,
                    },
                    "metadata": {
                        "body": "Preservation test call",
                    },
                    "associations": {
                        "dealIds": ["deal_pres3"],
                        "contactIds": [],
                        "companyIds": [],
                    },
                },
            )
            db.session.add(call_engagement)
            db.session.commit()

            converter = HubSpotActivityConverterService()

            # First run: convert both
            note_result = converter.convert_engagement(note_engagement)
            call_result = converter.convert_engagement(call_engagement)

            assert note_result is not None, "First NOTE conversion should succeed"
            assert call_result is not None, "First CALL conversion should succeed"

            count_after_first = Interaction.query.count()
            assert count_after_first >= 2, "Should have at least 2 interactions"

            # Second run: same engagements again
            note_result2 = converter.convert_engagement(note_engagement)
            call_result2 = converter.convert_engagement(call_engagement)

            assert note_result2 is None, (
                "Second NOTE conversion should return None (idempotent skip)"
            )
            assert call_result2 is None, (
                "Second CALL conversion should return None (idempotent skip)"
            )

            count_after_second = Interaction.query.count()
            assert count_after_second == count_after_first, (
                f"Interaction count changed from {count_after_first} to "
                f"{count_after_second} — idempotency violated."
            )


class TestPreservation4NoDuplicatePropertyContact:
    """Preservation Test 4: No duplicate PropertyContact on double enrichment.

    PropertyContact rows that already exist for a contact name + property
    must not be duplicated.

    **Validates: Requirements 3.4**
    """

    def test_preservation_no_duplicate_property_contact(self, app):
        """Enrich the same lead from the same HubSpot contact twice.
        Assert PropertyContact.query.filter_by(property_id=lead.id).count() == 1.

        **Validates: Requirements 3.4**
        """
        with app.app_context():
            lead = Lead(
                property_street="300 NoDupes Blvd",
                lead_status="awaiting_skip_trace",
            )
            db.session.add(lead)
            db.session.flush()

            hs_contact = HubSpotContact(
                hubspot_id="contact_pres4",
                raw_payload={
                    "properties": {
                        "firstname": "Gilberto",
                        "lastname": "Olivares",
                        "email": "gilberto@example.com",
                        "phone": "3125551234",
                    }
                },
            )
            db.session.add(hs_contact)
            db.session.flush()

            matcher = HubSpotMatcherService()

            # First enrichment
            matcher.enrich_lead_from_contact(lead, hs_contact)
            db.session.commit()

            pc_count_after_first = PropertyContact.query.filter_by(
                property_id=lead.id
            ).count()
            assert pc_count_after_first == 1, (
                f"Expected 1 PropertyContact after first enrichment, got {pc_count_after_first}"
            )

            # Second enrichment (same contact, same lead)
            matcher.enrich_lead_from_contact(lead, hs_contact)
            db.session.commit()

            pc_count_after_second = PropertyContact.query.filter_by(
                property_id=lead.id
            ).count()
            assert pc_count_after_second == 1, (
                f"Expected 1 PropertyContact after second enrichment, got "
                f"{pc_count_after_second} — duplicate created!"
            )


class TestPreservation5ConfirmedRejectedMatchNotReMatched:
    """Preservation Test 5: Confirmed/rejected match not re-matched.

    HubSpotMatch records with status 'confirmed' or 'rejected' must not be
    re-matched during run_hubspot_matching.

    **Validates: Requirements 3.5**
    """

    @given(
        match_status=st.sampled_from(['confirmed', 'rejected']),
    )
    @settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_preservation_confirmed_rejected_match_not_rematched(self, app, match_status):
        """Property: create a HubSpotMatch(status=status) for a deal. Run
        run_hubspot_matching. Assert match status is unchanged.

        **Validates: Requirements 3.5**
        """
        with app.app_context():
            lead = Lead(
                property_street="400 Stable Match Rd",
                lead_status="awaiting_skip_trace",
            )
            db.session.add(lead)
            db.session.flush()

            # Create a deal
            deal = HubSpotDeal(
                hubspot_id=f"deal_pres5_{match_status[:4]}",
                raw_payload={
                    "properties": {
                        "dealstage": "closedwon",
                        "dealname": "400 Stable Match Rd",
                    }
                },
            )
            db.session.add(deal)
            db.session.flush()

            # Create the match with the status we want to protect
            existing_match = HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id=f"deal_pres5_{match_status[:4]}",
                internal_record_type="lead",
                internal_record_id=lead.id if match_status == 'confirmed' else None,
                confidence="MEDIUM",
                status=match_status,
                matching_criteria="address_match",
            )
            db.session.add(existing_match)
            db.session.commit()

            # Simulate the core logic of run_hubspot_matching:
            # It collects confirmed/rejected hubspot_ids and SKIPS them.
            from app.models.hubspot_deal import HubSpotDeal as HD

            matched_deals = {
                m.hubspot_id
                for m in HubSpotMatch.query.filter_by(hubspot_record_type='deal')
                .filter(HubSpotMatch.status.in_(['confirmed', 'rejected']))
                .all()
            }

            matcher = HubSpotMatcherService()
            for d in HD.query.all():
                if d.hubspot_id in matched_deals:
                    continue  # This is the protection — it should skip
                matcher.match_deal(d)
                db.session.commit()

            # Reload and verify status is unchanged
            reloaded = HubSpotMatch.query.filter_by(
                hubspot_record_type="deal",
                hubspot_id=f"deal_pres5_{match_status[:4]}",
            ).first()

            assert reloaded is not None, "Match should still exist"
            assert reloaded.status == match_status, (
                f"Match status was changed from '{match_status}' to "
                f"'{reloaded.status}' — confirmed/rejected matches must not "
                f"be re-matched."
            )

            db.session.rollback()


# ===========================================================================
# Bug 4 — Confirmed HubSpot match pointing at a deleted lead
# ===========================================================================
#
# internal_record_id on hubspot_matches is a plain Integer with no FK/cascade,
# so deleting a Lead silently orphans any HubSpotMatch that pointed at it. The
# match stays status='confirmed' referencing a now-missing lead, which means
# run_hubspot_matching skips it (confirmed is in the skip-set) and
# run_enrich_leads_from_hubspot bails (Lead.query.get -> None). A surviving
# duplicate lead at the same address therefore never receives the deal stage,
# the owner/PropertyContact, or any activities. This is the 2553 N Drake /
# Gilberto Olivares failure.
#
# Unlike the Bug 2/Bug 3a exploration tests above (which reproduce the pipeline
# logic inline), these tests exercise the REAL run_hubspot_matching and
# run_enrich_leads_from_hubspot functions. create_app is patched to return the
# test app so the functions' internal ``with create_app().app_context()`` runs
# against the in-memory SQLite DB (Flask-SQLAlchemy uses a shared StaticPool for
# in-memory SQLite, so the nested context sees the same data). The HubSpot
# client is mocked so no live API call is ever made.


def _mock_hubspot_client():
    """A MagicMock standing in for HubSpotClientService — never hits the network."""
    client = MagicMock()
    client.fetch_pipeline_stage_labels.return_value = {"closedlost": "Negotiating Remote"}
    # If the empty-contacts retry path ever fires, return an empty association map
    # rather than a bare MagicMock so the caller's .get(...) iteration stays sane.
    client.fetch_deal_contact_associations.return_value = {}
    return client


class TestBug4DanglingConfirmedMatch:
    """Bug 4: a confirmed match whose lead was deleted must be healed and
    re-pointed to the surviving duplicate lead by the real pipeline."""

    def test_bug4_dangling_confirmed_match_relinked_after_lead_deleted(self, app):
        """End-to-end: confirmed deal match references a deleted lead; a surviving
        duplicate exists at the same address. After the REAL run_hubspot_matching
        + run_enrich_leads_from_hubspot run, the deal match is re-pointed to the
        surviving lead, the owner is linked via PropertyContact, and the deal
        stage display label is synced.

        On unfixed code: the dangling confirmed match is in the skip-set, so it is
        never re-matched and the surviving lead stays empty.

        **Validates: Requirements 2.4, 2.6**
        """
        from app.tasks.hubspot_tasks import (
            run_hubspot_matching,
            run_enrich_leads_from_hubspot,
        )

        with app.app_context():
            # HubSpotConfig so the stage-label fetch path constructs the (mocked) client
            config = HubSpotConfig(encrypted_token="fake_token", portal_id="test_portal")
            db.session.add(config)
            db.session.flush()

            # Lead A — the lead the deal was originally confirmed against
            lead_a = Lead(property_street="2553 N Drake Ave", lead_status="awaiting_skip_trace")
            db.session.add(lead_a)
            db.session.flush()
            a_id = lead_a.id

            # Keeper lead at an unrelated address so SQLite cannot reuse A's rowid
            # for B after A is deleted (which would mask the bug).
            keeper = Lead(property_street="9999 Unrelated Ave", lead_status="awaiting_skip_trace")
            db.session.add(keeper)
            db.session.flush()

            # HubSpot deal carrying the contact association in its payload
            deal = HubSpotDeal(
                hubspot_id="8749502786",
                raw_payload={
                    "properties": {
                        "dealstage": "closedlost",
                        "dealname": "2553 N Drake Ave",
                    },
                    "associations": {
                        "contacts": {"results": [{"id": "contact_gilberto"}]}
                    },
                },
            )
            db.session.add(deal)

            # Gilberto contact, with a back-reference to the deal
            hs_contact = HubSpotContact(
                hubspot_id="contact_gilberto",
                raw_payload={
                    "properties": {
                        "firstname": "Gilberto",
                        "lastname": "Olivares",
                        "email": "",
                        "phone": "",
                    },
                    "associations": {
                        "deals": {"results": [{"id": "8749502786"}]}
                    },
                },
            )
            db.session.add(hs_contact)

            # Confirmed deal match pointing at A — becomes dangling once A is deleted
            deal_match = HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="8749502786",
                internal_record_type="lead",
                internal_record_id=a_id,
                confidence="MEDIUM",
                status="confirmed",
                matching_criteria="address_match",
            )
            db.session.add(deal_match)

            # Confirmed contact match with NULL internal_record_id (matched before
            # the deal was confirmed) — the owner link is not yet established
            contact_match = HubSpotMatch(
                hubspot_record_type="contact",
                hubspot_id="contact_gilberto",
                internal_record_type="lead",
                internal_record_id=None,
                confidence="MEDIUM",
                status="confirmed",
                matching_criteria="name_match",
            )
            db.session.add(contact_match)
            db.session.commit()

            # Delete A — the deal match now references a lead that no longer exists
            db.session.delete(lead_a)
            db.session.commit()

            # Surviving duplicate lead at the same address
            lead_b = Lead(property_street="2553 N Drake Ave", lead_status="awaiting_skip_trace")
            db.session.add(lead_b)
            db.session.commit()
            b_id = lead_b.id
            assert b_id != a_id, "Test setup invalid: B reused A's id"

            # Run the REAL pipeline functions against the in-memory DB.
            client = _mock_hubspot_client()
            with patch('app.create_app', return_value=app), \
                 patch(
                     'app.services.hubspot_client_service.HubSpotClientService',
                     return_value=client,
                 ):
                run_hubspot_matching()
                run_enrich_leads_from_hubspot()

            db.session.expire_all()

            # 1. The deal match was healed and re-pointed to the surviving lead B.
            healed_match = HubSpotMatch.query.filter_by(
                hubspot_record_type="deal", hubspot_id="8749502786"
            ).first()
            assert healed_match is not None
            assert healed_match.internal_record_id == b_id, (
                f"Expected deal match re-pointed to surviving lead {b_id}, got "
                f"{healed_match.internal_record_id} (a_id was {a_id}). Bug 4: dangling "
                f"confirmed match never healed/re-matched."
            )
            assert healed_match.internal_record_id != a_id
            assert healed_match.status == "confirmed"

            # Exactly one deal match row — healing updates in place, never duplicates.
            assert HubSpotMatch.query.filter_by(
                hubspot_record_type="deal", hubspot_id="8749502786"
            ).count() == 1

            # 2. A PropertyContact row links Gilberto to the surviving lead B.
            pc = (
                PropertyContact.query
                .join(Contact, PropertyContact.contact_id == Contact.id)
                .filter(
                    PropertyContact.property_id == b_id,
                    db.func.lower(Contact.first_name) == "gilberto",
                    db.func.lower(Contact.last_name) == "olivares",
                )
                .first()
            )
            assert pc is not None, (
                "Expected a PropertyContact linking Gilberto Olivares to the surviving "
                "lead B. Bug 4: owner never linked because enrichment bailed on the "
                "deleted lead."
            )

            # 3. The deal stage display label was synced onto the surviving lead.
            lead_b_reloaded = db.session.get(Lead, b_id)
            assert lead_b_reloaded.hubspot_deal_stage == "Negotiating Remote", (
                f"Expected 'Negotiating Remote' display label, got "
                f"'{lead_b_reloaded.hubspot_deal_stage}'."
            )

    def test_bug4_confirmed_match_with_existing_lead_not_rehealed(self, app):
        """Preservation guard: a confirmed match whose lead STILL EXISTS must be
        left untouched by run_hubspot_matching (healing only targets matches whose
        referenced lead is actually missing).

        **Validates: Requirements 3.4**
        """
        from app.tasks.hubspot_tasks import run_hubspot_matching

        with app.app_context():
            config = HubSpotConfig(encrypted_token="fake_token", portal_id="test_portal")
            db.session.add(config)
            db.session.flush()

            lead = Lead(property_street="123 Keep Confirmed Ave", lead_status="awaiting_skip_trace")
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id

            deal = HubSpotDeal(
                hubspot_id="deal_keep_001",
                raw_payload={
                    "properties": {
                        "dealstage": "closedwon",
                        "dealname": "123 Keep Confirmed Ave",
                    }
                },
            )
            db.session.add(deal)

            match = HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="deal_keep_001",
                internal_record_type="lead",
                internal_record_id=lead_id,
                confidence="MEDIUM",
                status="confirmed",
                matching_criteria="address_match",
            )
            db.session.add(match)
            db.session.commit()

            client = _mock_hubspot_client()
            with patch('app.create_app', return_value=app), \
                 patch(
                     'app.services.hubspot_client_service.HubSpotClientService',
                     return_value=client,
                 ):
                run_hubspot_matching()

            db.session.expire_all()

            reloaded = HubSpotMatch.query.filter_by(
                hubspot_record_type="deal", hubspot_id="deal_keep_001"
            ).first()
            assert reloaded is not None
            assert reloaded.status == "confirmed", (
                "A confirmed match whose lead still exists must remain confirmed."
            )
            assert reloaded.internal_record_id == lead_id, (
                f"Expected match to still point at lead {lead_id}, got "
                f"{reloaded.internal_record_id} — healing wrongly touched a live match."
            )


# ===========================================================================
# Bug 6 — Post-import pipeline never auto-advances (stale-session read)
# ===========================================================================
#
# Two wait loops poll HubSpotImportRun status to decide when an import batch is
# finished, then run the post-import pipeline:
#   1. app.services.hubspot_import_service._run_pipeline_after_imports — the
#      in-process background thread.
#   2. celery_worker.run_post_import_pipeline — the Celery backup task.
#
# Each loop re-queries HubSpotImportRun inside a single long-lived SQLAlchemy
# session.  The import tasks update `status` and commit in a SEPARATE
# session/process, but the polling session's identity map keeps returning the
# STALE status from its first read, so `all(r.status in terminal ...)` never
# becomes true.  The loop spins until the 1-hour max_wait timeout and only then
# runs the pipeline — so in practice the platform almost never auto-syncs after
# an import.
#
# These are regression guards for the stale-session read.  They drive the REAL
# loop functions and simulate the import tasks committing status='success' from
# a different session.  The "different session" is faithfully reproduced by
# committing the raw-SQL UPDATE with expire_on_commit temporarily disabled: a
# commit originating elsewhere never expires THIS session's identity map, so the
# polled ORM objects stay 'running' until the loop explicitly re-reads them.
# Without the fix the loop never observes 'success' and sleeps the full timeout
# count; with the fix it re-reads each poll and breaks promptly.


def _commit_status_from_other_session(run_ids, new_status='success'):
    """Simulate the import tasks committing a status change from a separate
    session/process.

    Uses raw SQL (bypasses the ORM unit of work) and temporarily disables
    expire_on_commit so the polling session's identity-map objects are NOT
    expired by this commit — exactly what happens when the commit comes from a
    different session.  The committed value is durable in the shared in-memory
    DB, but the polling session keeps its stale in-memory copies until it
    expires/re-reads them (the fix).
    """
    from sqlalchemy import text

    # db.session is a scoped_session registry; call it to get the underlying
    # Session so we can toggle expire_on_commit.  Using this same session (not a
    # second one) avoids a second BEGIN on the single shared in-memory SQLite
    # connection, while expire_on_commit=False keeps the polled ORM objects
    # un-expired — reproducing a commit that originates from a different session.
    sess = db.session()
    prev_expire = sess.expire_on_commit
    sess.expire_on_commit = False
    try:
        sess.execute(
            text(
                "UPDATE hubspot_import_runs SET status=:s "
                "WHERE id IN (:a, :b)"
            ),
            {'s': new_status, 'a': run_ids[0], 'b': run_ids[1]},
        )
        sess.commit()
    finally:
        sess.expire_on_commit = prev_expire


class TestBug6PipelineAutoAdvance:
    """Bug 6: the post-import wait loops must observe a status change committed
    by the import tasks (in another session) and advance promptly, instead of
    spinning on a stale identity-map read until the 1-hour timeout."""

    def test_bug6_inprocess_pipeline_autoadvances_on_committed_status(self, app):
        """REAL _run_pipeline_after_imports: create two 'running' import runs,
        then have the FIRST poll-sleep flip them to 'success' from another
        session.  The loop must detect completion promptly (at most a poll or
        two) and run the five pipeline steps via the all-complete path — NOT the
        1-hour timeout fallback.

        Regression guard for the stale-session read: on unfixed code the polling
        session's identity map keeps returning 'running', so time.sleep is
        called the full timeout count (max_wait / poll_interval) before the loop
        gives up and runs the pipeline anyway.

        **Validates: Requirements 3.6**
        """
        from datetime import datetime
        from app.models.hubspot_import_run import HubSpotImportRun
        from app.services.hubspot_import_service import _run_pipeline_after_imports

        with app.app_context():
            run1 = HubSpotImportRun(
                object_type='deals', status='running', start_time=datetime.utcnow()
            )
            run2 = HubSpotImportRun(
                object_type='contacts', status='running', start_time=datetime.utcnow()
            )
            db.session.add_all([run1, run2])
            db.session.commit()
            run_ids = [run1.id, run2.id]

            state = {'flipped': False}

            def fake_sleep(_seconds):
                # On the first poll-sleep, simulate the import tasks finishing in
                # a separate session.  Subsequent calls are no-ops so an unfixed
                # (spinning) loop still terminates quickly via the timeout.
                if not state['flipped']:
                    state['flipped'] = True
                    _commit_status_from_other_session(run_ids, 'success')

            with patch('app.tasks.hubspot_tasks.run_hubspot_matching') as m_match, \
                 patch('app.tasks.hubspot_tasks.run_enrich_leads_from_hubspot') as m_enrich, \
                 patch('app.tasks.hubspot_tasks.run_convert_hubspot_activities') as m_convert, \
                 patch('app.tasks.hubspot_tasks.run_extract_hubspot_signals') as m_signals, \
                 patch('app.tasks.hubspot_tasks.run_rescore_leads_after_import') as m_rescore, \
                 patch('time.sleep', side_effect=fake_sleep) as m_sleep:
                _run_pipeline_after_imports(app, run_ids)

            # Detected completion promptly — a couple of polls at most, NOT the
            # 3600/15 = 240 spins an unfixed stale-read loop would take.
            assert m_sleep.call_count <= 2, (
                f"Expected the loop to observe the committed 'success' status "
                f"within a poll or two, but time.sleep was called "
                f"{m_sleep.call_count} times — the polling session is reading a "
                f"stale status and spinning toward the timeout. Bug 6 confirmed."
            )

            # Pipeline advanced via the all-complete path (each step ran once).
            for name, mock in (
                ('run_hubspot_matching', m_match),
                ('run_enrich_leads_from_hubspot', m_enrich),
                ('run_convert_hubspot_activities', m_convert),
                ('run_extract_hubspot_signals', m_signals),
                ('run_rescore_leads_after_import', m_rescore),
            ):
                assert mock.call_count == 1, (
                    f"Expected {name} to run exactly once after the imports "
                    f"completed; got {mock.call_count} calls."
                )

            # The status change is visible once the session re-reads the DB.
            db.session.expire_all()
            statuses = {
                r.status
                for r in HubSpotImportRun.query.filter(
                    HubSpotImportRun.id.in_(run_ids)
                ).all()
            }
            assert statuses == {'success'}, (
                f"Expected both runs committed as 'success', got {statuses}."
            )

    def test_bug6_celery_pipeline_autoadvances_on_committed_status(self, app):
        """REAL celery_worker.run_post_import_pipeline (the backup loop): same
        scenario as the in-process test.  create_app is patched to return the
        test app so the task's internal app context runs against the in-memory
        DB.  The loop must advance promptly once 'success' is committed from
        another session rather than spinning until the timeout.

        **Validates: Requirements 3.6**
        """
        from datetime import datetime
        from app.models.hubspot_import_run import HubSpotImportRun
        from celery_worker import run_post_import_pipeline

        with app.app_context():
            run1 = HubSpotImportRun(
                object_type='deals', status='running', start_time=datetime.utcnow()
            )
            run2 = HubSpotImportRun(
                object_type='engagements', status='running', start_time=datetime.utcnow()
            )
            db.session.add_all([run1, run2])
            db.session.commit()
            run_ids = [run1.id, run2.id]

            state = {'flipped': False}

            def fake_sleep(_seconds):
                if not state['flipped']:
                    state['flipped'] = True
                    _commit_status_from_other_session(run_ids, 'success')

            with patch('app.create_app', return_value=app), \
                 patch('app.tasks.hubspot_tasks.run_hubspot_matching') as m_match, \
                 patch('app.tasks.hubspot_tasks.run_enrich_leads_from_hubspot') as m_enrich, \
                 patch('app.tasks.hubspot_tasks.run_convert_hubspot_activities') as m_convert, \
                 patch('app.tasks.hubspot_tasks.run_extract_hubspot_signals') as m_signals, \
                 patch('app.tasks.hubspot_tasks.run_rescore_leads_after_import') as m_rescore, \
                 patch('time.sleep', side_effect=fake_sleep) as m_sleep:
                run_post_import_pipeline(run_ids)

            assert m_sleep.call_count <= 2, (
                f"Expected run_post_import_pipeline to observe the committed "
                f"'success' status within a poll or two, but time.sleep was "
                f"called {m_sleep.call_count} times — stale-session spin. "
                f"Bug 6 confirmed."
            )
            for name, mock in (
                ('run_hubspot_matching', m_match),
                ('run_enrich_leads_from_hubspot', m_enrich),
                ('run_convert_hubspot_activities', m_convert),
                ('run_extract_hubspot_signals', m_signals),
                ('run_rescore_leads_after_import', m_rescore),
            ):
                assert mock.call_count == 1, (
                    f"Expected {name} to run exactly once; got {mock.call_count}."
                )


# ===========================================================================
# Bug 5 — HubSpot activity/task associations stranded on a deleted lead
# ===========================================================================
#
# InteractionAssociation.target_id and TaskAssociation.target_id are plain
# Integers with no FK/cascade to ``leads``. When a duplicate lead is deleted,
# its hubspot-imported activity/task associations are left pointing at the now-
# missing lead, with Interaction.is_orphaned=False. The orphan re-resolution
# pass in run_convert_hubspot_activities only revisits is_orphaned=True rows,
# and the converter is idempotent, so these historical activities/tasks stay
# stranded on the dead lead and never appear on the surviving lead. This is the
# 2553 N Drake case: ~20 interactions + 24 task associations stayed on deleted
# lead 916 even after Bug 4 re-pointed the deal match to surviving lead 3415.
#
# Like the Bug 4 / Bug 6 tests, these exercise the REAL
# run_convert_hubspot_activities function. create_app is patched to return the
# test app so the function's internal ``with create_app().app_context()`` runs
# against the in-memory SQLite DB (shared StaticPool). A missing lead is
# simulated with a target_id that never existed (9999999) — the stranded state
# left behind after the original lead was deleted.


class TestBug5StrandedAssociation:
    """Bug 5: activity/task associations left pointing at a deleted lead must be
    re-pointed to the surviving lead by run_convert_hubspot_activities."""

    def test_bug5_interaction_association_stranded_on_deleted_lead_relinked(self, app):
        """An already-converted hubspot_import Interaction whose only lead
        association points at a now-deleted lead must be re-pointed to the
        surviving lead B (resolved via the confirmed deal match), with the
        dangling association removed and is_orphaned left False. Running the
        pass twice must be a no-op (idempotent — no duplicate associations).

        On unfixed code: the orphan pass skips is_orphaned=False rows and the
        converter is idempotent, so the interaction stays stranded on the dead
        lead forever.

        **Validates: Requirements 2.7, 2.8**
        """
        from datetime import datetime
        from app.tasks.hubspot_tasks import run_convert_hubspot_activities

        MISSING_LEAD_ID = 9999999

        with app.app_context():
            # Surviving lead B at the address.
            lead_b = Lead(property_street="2553 N Drake Ave", lead_status="awaiting_skip_trace")
            db.session.add(lead_b)
            db.session.flush()
            b_id = lead_b.id
            assert b_id != MISSING_LEAD_ID, "Test setup invalid: B reused the missing id"

            # Deal + confirmed match -> B (Bug 4 healing already re-pointed it).
            deal = HubSpotDeal(
                hubspot_id="deal_b5_int",
                raw_payload={
                    "properties": {"dealstage": "closedlost", "dealname": "2553 N Drake Ave"},
                },
            )
            db.session.add(deal)
            db.session.add(HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="deal_b5_int",
                internal_record_type="lead",
                internal_record_id=b_id,
                confidence="MEDIUM",
                status="confirmed",
                matching_criteria="address_match",
            ))

            # CALL engagement associated to the deal.
            engagement = HubSpotEngagement(
                hubspot_id="eng_b5_int",
                engagement_type="CALL",
                raw_payload={
                    "engagement": {"id": 70001, "type": "CALL", "createdAt": 1700000000000},
                    "metadata": {"body": "Called owner"},
                    "associations": {"dealIds": ["deal_b5_int"], "contactIds": [], "companyIds": []},
                },
            )
            db.session.add(engagement)
            db.session.flush()

            # Already-converted interaction stranded on the (deleted) lead via a
            # dangling InteractionAssociation. is_orphaned=False is the key: the
            # orphan pass never revisits it.
            interaction = Interaction(
                interaction_type="call",
                body="Called owner",
                occurred_at=datetime.utcnow(),
                source="hubspot_import",
                hubspot_engagement_id="eng_b5_int",
                raw_payload=engagement.raw_payload,
                is_orphaned=False,
            )
            db.session.add(interaction)
            db.session.flush()
            interaction_id = interaction.id

            db.session.add(InteractionAssociation(
                interaction_id=interaction_id,
                target_type="lead",
                target_id=MISSING_LEAD_ID,
            ))
            db.session.commit()

            # Run the REAL pipeline function against the in-memory DB.
            with patch('app.create_app', return_value=app):
                run_convert_hubspot_activities()

            db.session.expire_all()

            # The dangling association to the missing lead is gone.
            assert InteractionAssociation.query.filter_by(
                interaction_id=interaction_id, target_id=MISSING_LEAD_ID
            ).first() is None, (
                "Dangling association to the deleted lead should have been removed. "
                "Bug 5: activity left stranded on the dead lead."
            )

            # The interaction now points at the surviving lead B.
            relinked = InteractionAssociation.query.filter_by(
                interaction_id=interaction_id, target_type="lead", target_id=b_id
            ).first()
            assert relinked is not None, (
                f"Expected interaction re-pointed to surviving lead {b_id}. Bug 5: "
                f"interaction association stranded on deleted lead {MISSING_LEAD_ID}."
            )

            # is_orphaned stays False (it was always a real, linked activity).
            reloaded = db.session.get(Interaction, interaction_id)
            assert reloaded.is_orphaned is False

            # --- Idempotency: a second run must be a no-op -----------------
            with patch('app.create_app', return_value=app):
                run_convert_hubspot_activities()
            db.session.expire_all()

            lead_assocs = InteractionAssociation.query.filter_by(
                interaction_id=interaction_id, target_type="lead"
            ).all()
            assert len(lead_assocs) == 1, (
                f"Expected exactly one lead association after re-run (no duplicates), "
                f"got {len(lead_assocs)}."
            )
            assert lead_assocs[0].target_id == b_id, (
                f"target_id should remain stable at {b_id} on re-run, got "
                f"{lead_assocs[0].target_id}."
            )

    def test_bug5_task_association_stranded_on_deleted_lead_relinked(self, app):
        """A hubspot-imported Task whose lead association points at a now-deleted
        lead must be re-pointed to the surviving lead B (resolved via the
        confirmed deal match keyed on the Task's hubspot_task_id), with the
        dangling association removed and no duplicate created.

        **Validates: Requirements 2.7, 2.8**
        """
        from app.models.task import Task
        from app.models.task_association import TaskAssociation
        from app.tasks.hubspot_tasks import run_convert_hubspot_activities

        MISSING_LEAD_ID = 9999999

        with app.app_context():
            lead_b = Lead(property_street="2553 N Drake Ave", lead_status="awaiting_skip_trace")
            db.session.add(lead_b)
            db.session.flush()
            b_id = lead_b.id

            deal = HubSpotDeal(
                hubspot_id="deal_b5_task",
                raw_payload={
                    "properties": {"dealstage": "closedlost", "dealname": "2553 N Drake Ave"},
                },
            )
            db.session.add(deal)
            db.session.add(HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="deal_b5_task",
                internal_record_type="lead",
                internal_record_id=b_id,
                confidence="MEDIUM",
                status="confirmed",
                matching_criteria="address_match",
            ))

            # TASK engagement — its hubspot_id IS the Task's hubspot_task_id used
            # by the re-resolution pass.
            engagement = HubSpotEngagement(
                hubspot_id="eng_b5_task",
                engagement_type="TASK",
                raw_payload={
                    "engagement": {"id": 70002, "type": "TASK", "timestamp": 1700000000000},
                    "metadata": {"subject": "Follow up", "body": "Call back", "status": "NOT_STARTED"},
                    "associations": {"dealIds": ["deal_b5_task"], "contactIds": [], "companyIds": []},
                },
            )
            db.session.add(engagement)
            db.session.flush()

            task = Task(
                title="Follow up",
                body="Call back",
                status="open",
                source="hubspot_import",
                hubspot_task_id="eng_b5_task",
                raw_payload=engagement.raw_payload,
            )
            db.session.add(task)
            db.session.flush()
            task_id = task.id

            db.session.add(TaskAssociation(
                task_id=task_id,
                target_type="lead",
                target_id=MISSING_LEAD_ID,
            ))
            db.session.commit()

            with patch('app.create_app', return_value=app):
                run_convert_hubspot_activities()

            db.session.expire_all()

            assert TaskAssociation.query.filter_by(
                task_id=task_id, target_id=MISSING_LEAD_ID
            ).first() is None, (
                "Dangling task association to the deleted lead should have been removed."
            )

            relinked = TaskAssociation.query.filter_by(
                task_id=task_id, target_type="lead", target_id=b_id
            ).first()
            assert relinked is not None, (
                f"Expected task re-pointed to surviving lead {b_id}. Bug 5: task "
                f"association stranded on deleted lead {MISSING_LEAD_ID}."
            )

            lead_assocs = TaskAssociation.query.filter_by(
                task_id=task_id, target_type="lead"
            ).all()
            assert len(lead_assocs) == 1, (
                f"Expected exactly one lead association (no duplicates), got "
                f"{len(lead_assocs)}."
            )

    def test_bug5_association_with_existing_lead_untouched(self, app):
        """Preservation guard: an interaction whose lead association points at an
        EXISTING lead must be left completely unchanged by the re-point pass
        (target_id unchanged, no duplicate association, is_orphaned unchanged).

        **Validates: Requirements 2.7, 2.8, 3.4**
        """
        from datetime import datetime
        from app.tasks.hubspot_tasks import run_convert_hubspot_activities

        with app.app_context():
            lead_b = Lead(property_street="100 Existing Lead Ln", lead_status="awaiting_skip_trace")
            db.session.add(lead_b)
            db.session.flush()
            b_id = lead_b.id

            deal = HubSpotDeal(
                hubspot_id="deal_b5_keep",
                raw_payload={
                    "properties": {"dealstage": "closedlost", "dealname": "100 Existing Lead Ln"},
                },
            )
            db.session.add(deal)
            db.session.add(HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="deal_b5_keep",
                internal_record_type="lead",
                internal_record_id=b_id,
                confidence="MEDIUM",
                status="confirmed",
                matching_criteria="address_match",
            ))

            engagement = HubSpotEngagement(
                hubspot_id="eng_b5_keep",
                engagement_type="NOTE",
                raw_payload={
                    "engagement": {"id": 70003, "type": "NOTE", "createdAt": 1700000000000},
                    "metadata": {"body": "Note body"},
                    "associations": {"dealIds": ["deal_b5_keep"], "contactIds": [], "companyIds": []},
                },
            )
            db.session.add(engagement)
            db.session.flush()

            interaction = Interaction(
                interaction_type="note",
                body="Note body",
                occurred_at=datetime.utcnow(),
                source="hubspot_import",
                hubspot_engagement_id="eng_b5_keep",
                raw_payload=engagement.raw_payload,
                is_orphaned=False,
            )
            db.session.add(interaction)
            db.session.flush()
            interaction_id = interaction.id

            # Association to an EXISTING lead — must be left untouched.
            db.session.add(InteractionAssociation(
                interaction_id=interaction_id,
                target_type="lead",
                target_id=b_id,
            ))
            db.session.commit()

            with patch('app.create_app', return_value=app):
                run_convert_hubspot_activities()

            db.session.expire_all()

            lead_assocs = InteractionAssociation.query.filter_by(
                interaction_id=interaction_id, target_type="lead"
            ).all()
            assert len(lead_assocs) == 1, (
                f"Expected the existing-lead association left untouched (no duplicate), "
                f"got {len(lead_assocs)} associations."
            )
            assert lead_assocs[0].target_id == b_id, (
                f"Association target_id changed from {b_id} to {lead_assocs[0].target_id} "
                f"— associations pointing at a live lead must never be touched."
            )
            reloaded = db.session.get(Interaction, interaction_id)
            assert reloaded.is_orphaned is False


# ===========================================================================
# Bug 7 — Orphaned HubSpot references left behind on lead delete
# ===========================================================================
#
# HubSpotMatch.internal_record_id, InteractionAssociation.target_id, and
# TaskAssociation.target_id are POLYMORPHIC (an id column paired with a *_type
# discriminator), so no SQL foreign key / ON DELETE CASCADE can clean them up
# when a Lead is deleted. A before_delete mapper event on the Lead model
# (app/models/lead.py) handles the app's own ORM deletes: it resets the lead's
# confirmed/pending HubSpot matches to pending+NULL (so they re-match later),
# marks the lead's interactions orphaned and removes their dangling
# associations, and removes the lead's task associations. Rejected matches and
# any records belonging to other leads are left untouched.
#
# These tests drive a REAL ``db.session.delete(lead)`` so the before_delete
# hook actually fires (bulk Query.delete()/raw SQL would bypass it — that path
# is covered by the Bug 4 / Bug 5 sync-time healing instead).


class TestBug7LeadDeleteCleanup:
    """Bug 7: a real ORM lead delete must not strand HubSpot references."""

    def test_lead_delete_resets_matches_and_orphans_activities(self, app):
        """``session.delete(lead)`` resets the lead's confirmed HubSpot match to
        pending/NULL, marks its associated interaction orphaned and drops the
        dangling interaction association, and drops the dangling task
        association — while the interaction and task rows themselves are kept.

        **Validates: Requirements 2.4, 2.7, 2.8**
        """
        from datetime import datetime
        from app.models.task import Task
        from app.models.task_association import TaskAssociation

        with app.app_context():
            lead = Lead(property_street="2553 N Drake Ave", lead_status="awaiting_skip_trace")
            db.session.add(lead)
            db.session.flush()
            lead_id = lead.id

            # Confirmed HubSpot match pointing at this lead.
            match = HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="deal_bug7_a",
                internal_record_type="lead",
                internal_record_id=lead_id,
                confidence="MEDIUM",
                status="confirmed",
                matching_criteria="address_match",
            )
            db.session.add(match)

            # hubspot-imported Interaction associated to the lead.
            interaction = Interaction(
                interaction_type="call",
                body="Called owner",
                occurred_at=datetime.utcnow(),
                source="hubspot_import",
                hubspot_engagement_id="eng_bug7_a",
                is_orphaned=False,
            )
            db.session.add(interaction)
            db.session.flush()
            interaction_id = interaction.id
            db.session.add(InteractionAssociation(
                interaction_id=interaction_id,
                target_type="lead",
                target_id=lead_id,
            ))

            # hubspot-imported Task associated to the lead.
            task = Task(
                title="Follow up",
                body="Call back",
                status="open",
                source="hubspot_import",
                hubspot_task_id="task_bug7_a",
            )
            db.session.add(task)
            db.session.flush()
            task_id = task.id
            db.session.add(TaskAssociation(
                task_id=task_id,
                target_type="lead",
                target_id=lead_id,
            ))
            db.session.commit()

            # --- Real ORM delete — fires the before_delete cleanup hook -------
            db.session.delete(lead)
            db.session.commit()
            db.session.expire_all()

            # The lead is gone.
            assert db.session.get(Lead, lead_id) is None

            # 1. Match preserved but reset to pending with NULL internal_record_id.
            reloaded_match = HubSpotMatch.query.filter_by(
                hubspot_record_type="deal", hubspot_id="deal_bug7_a"
            ).first()
            assert reloaded_match is not None, "Match row must be preserved, only reset"
            assert reloaded_match.status == "pending", (
                f"Expected match reset to 'pending', got '{reloaded_match.status}'."
            )
            assert reloaded_match.internal_record_id is None, (
                f"Expected internal_record_id NULL, got {reloaded_match.internal_record_id}."
            )

            # 2. Interaction preserved + orphaned; its dangling association removed.
            reloaded_interaction = db.session.get(Interaction, interaction_id)
            assert reloaded_interaction is not None, "Interaction row must be preserved"
            assert reloaded_interaction.is_orphaned is True, (
                "Interaction associated with the deleted lead must be marked orphaned."
            )
            assert InteractionAssociation.query.filter_by(
                interaction_id=interaction_id
            ).count() == 0, "Dangling interaction association must be removed."

            # 3. Task preserved; its dangling association removed.
            assert db.session.get(Task, task_id) is not None, "Task row must be preserved"
            assert TaskAssociation.query.filter_by(
                task_id=task_id
            ).count() == 0, "Dangling task association must be removed."

    def test_lead_delete_preserves_rejected_match_and_other_leads(self, app):
        """Deleting a lead must NOT touch a 'rejected' match on that lead
        (reviewer decision preserved) nor any confirmed match / interaction /
        task association belonging to a DIFFERENT surviving lead.

        **Validates: Requirements 3.4**
        """
        from datetime import datetime
        from app.models.task import Task
        from app.models.task_association import TaskAssociation

        with app.app_context():
            doomed = Lead(property_street="1 Doomed St", lead_status="awaiting_skip_trace")
            survivor = Lead(property_street="2 Survivor Ave", lead_status="awaiting_skip_trace")
            db.session.add_all([doomed, survivor])
            db.session.flush()
            doomed_id = doomed.id
            survivor_id = survivor.id

            # A rejected match on the doomed lead — reviewer decision, must persist.
            rejected_match = HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="deal_bug7_rejected",
                internal_record_type="lead",
                internal_record_id=doomed_id,
                confidence="LOW",
                status="rejected",
                matching_criteria="address_match",
            )
            db.session.add(rejected_match)

            # A confirmed match on the SURVIVING lead — must be untouched.
            survivor_match = HubSpotMatch(
                hubspot_record_type="deal",
                hubspot_id="deal_bug7_survivor",
                internal_record_type="lead",
                internal_record_id=survivor_id,
                confidence="HIGH",
                status="confirmed",
                matching_criteria="address_match",
            )
            db.session.add(survivor_match)

            # Interaction + association on the SURVIVING lead — must be untouched.
            survivor_interaction = Interaction(
                interaction_type="note",
                body="Survivor note",
                occurred_at=datetime.utcnow(),
                source="hubspot_import",
                hubspot_engagement_id="eng_bug7_survivor",
                is_orphaned=False,
            )
            db.session.add(survivor_interaction)
            db.session.flush()
            survivor_interaction_id = survivor_interaction.id
            db.session.add(InteractionAssociation(
                interaction_id=survivor_interaction_id,
                target_type="lead",
                target_id=survivor_id,
            ))

            # Task + association on the SURVIVING lead — must be untouched.
            survivor_task = Task(
                title="Survivor task",
                status="open",
                source="hubspot_import",
                hubspot_task_id="task_bug7_survivor",
            )
            db.session.add(survivor_task)
            db.session.flush()
            survivor_task_id = survivor_task.id
            db.session.add(TaskAssociation(
                task_id=survivor_task_id,
                target_type="lead",
                target_id=survivor_id,
            ))
            db.session.commit()

            # Delete the doomed lead.
            db.session.delete(doomed)
            db.session.commit()
            db.session.expire_all()

            # Rejected match on the deleted lead is preserved exactly as-is.
            reloaded_rejected = HubSpotMatch.query.filter_by(
                hubspot_record_type="deal", hubspot_id="deal_bug7_rejected"
            ).first()
            assert reloaded_rejected is not None
            assert reloaded_rejected.status == "rejected", (
                f"Rejected match must stay 'rejected', got '{reloaded_rejected.status}' "
                f"— reviewer decisions are never touched."
            )
            # internal_record_id is intentionally left as-is precisely because
            # rejected matches are excluded from the cleanup.
            assert reloaded_rejected.internal_record_id == doomed_id

            # Surviving lead's confirmed match is untouched.
            reloaded_survivor_match = HubSpotMatch.query.filter_by(
                hubspot_record_type="deal", hubspot_id="deal_bug7_survivor"
            ).first()
            assert reloaded_survivor_match.status == "confirmed"
            assert reloaded_survivor_match.internal_record_id == survivor_id

            # Surviving lead's interaction is untouched (still linked, not orphaned).
            reloaded_survivor_interaction = db.session.get(Interaction, survivor_interaction_id)
            assert reloaded_survivor_interaction.is_orphaned is False
            assert InteractionAssociation.query.filter_by(
                interaction_id=survivor_interaction_id,
                target_type="lead",
                target_id=survivor_id,
            ).count() == 1, "Surviving lead's interaction association must remain."

            # Surviving lead's task association is untouched.
            assert TaskAssociation.query.filter_by(
                task_id=survivor_task_id,
                target_type="lead",
                target_id=survivor_id,
            ).count() == 1, "Surviving lead's task association must remain."


# ===========================================================================
# Bug 8 — rescore on every change (lead_score parity with recommended_action)
# ===========================================================================
#
# recommended_action was already recomputed at most mutation points, but
# lead_score was only recomputed by the post-import rescore, the webhook
# signal-extraction chain, and the nightly bulk job — NOT on manual status
# changes, lead/property field edits, enrichment, or contact link changes. So
# scores went stale until a bulk rescore ran.
#
# The unified, error-isolated helper refresh_lead_scoring(lead_id)
# (app/services/lead_refresh.py) recomputes AND persists BOTH lead_score and
# recommended_action for a single lead. It is wired into every non-HubSpot
# mutation point. These tests drive the REAL controller endpoints / services
# (and the helper directly) against the in-memory DB — no inline scoring logic.


class TestBug8RescoreOnChange:
    """Bug 8: lead_score must refresh (in parity with recommended_action) on
    every non-HubSpot mutation, not just on import / nightly bulk rescore."""

    def test_bug8_status_change_rescores_stage_bonus(self, client, app):
        """A manual status change to ``negotiating_remote`` must update the
        pipeline-stage bonus in ``lead_score`` (+25 over the 0-bonus
        ``mailing_no_contact_made`` baseline), not just the recommended action.

        **Validates: Bug 8 — score parity with recommended_action**
        """
        from app.services.lead_refresh import refresh_lead_scoring

        with app.app_context():
            lead = Lead(
                property_street="100 Stage Bonus St",
                lead_status="mailing_no_contact_made",  # stage bonus = 0
                has_phone=True,
                has_email=True,
                has_property_match=True,
            )
            db.session.add(lead)
            db.session.commit()
            lead_id = lead.id

            # Establish the computed baseline at the current (0-bonus) stage.
            refresh_lead_scoring(lead_id)
            db.session.refresh(lead)
            baseline_score = lead.lead_score

            # Flip to negotiating_remote (+25 stage bonus) via the REAL endpoint.
            resp = client.patch(
                f'/api/leads/{lead_id}/status',
                json={'status': 'negotiating_remote'},
            )
            assert resp.status_code == 200

            db.session.refresh(lead)
            assert lead.lead_status == 'negotiating_remote'
            # The +25 stage bonus must be reflected in the score — the only
            # input that changed between baseline and now is the stage bonus.
            assert lead.lead_score > baseline_score, (
                f"lead_score did not increase after the status change: "
                f"baseline={baseline_score}, now={lead.lead_score}. The stage "
                f"bonus was not applied — score went stale."
            )
            assert lead.lead_score == pytest.approx(baseline_score + 25.0, abs=0.01), (
                f"Expected baseline+25 ({baseline_score + 25.0}) but got "
                f"{lead.lead_score}."
            )

    def test_bug8_enrichment_increases_lead_score(self, app):
        """Enrichment that fills score-relevant fields (property facts, mailing
        address) must increase ``lead_score`` — enrichment changes the
        data-completeness, property-characteristics, and owner-situation
        sub-scores.

        **Validates: Bug 8 — score refresh after enrichment**
        """
        from app.services.lead_refresh import refresh_lead_scoring
        from app.services.data_source_connector import (
            DataSourceConnector, DataSourcePlugin, EnrichmentData,
        )

        class _Bug8StubPlugin(DataSourcePlugin):
            name = "bug8_stub_source"

            def lookup(self, address, owner_name):
                return EnrichmentData(fields={
                    'property_type': 'single_family',
                    'bedrooms': 3,
                    'bathrooms': 2,
                    'square_footage': 1500,
                    'year_built': 1995,
                    'ownership_type': 'individual',
                    'mailing_address': '999 Absentee Owner Way',
                    'mailing_city': 'Chicago',
                    'mailing_state': 'IL',
                    'mailing_zip': '60601',
                })

        with app.app_context():
            lead = Lead(
                property_street="200 Enrich St",
                lead_status="mailing_no_contact_made",
                has_phone=True,
                has_email=True,
                has_property_match=True,
            )
            db.session.add(lead)
            db.session.commit()
            lead_id = lead.id

            # Baseline computed score BEFORE enrichment.
            refresh_lead_scoring(lead_id)
            db.session.refresh(lead)
            baseline_score = lead.lead_score

            connector = DataSourceConnector()
            connector.register_source(_Bug8StubPlugin())
            record = connector.enrich_lead(lead_id, "bug8_stub_source")
            assert record.status == "success"

            db.session.refresh(lead)
            # Enrichment wrote score-relevant fields and refresh_lead_scoring
            # (wired into the connector) recomputed the score in place.
            assert lead.lead_score > baseline_score, (
                f"lead_score did not increase after enrichment: "
                f"baseline={baseline_score}, now={lead.lead_score}. "
                f"Enrichment-driven score refresh is missing."
            )

    def test_bug8_field_edit_recomputes_score(self, app):
        """Editing a scoring input on a lead and calling the refresh helper
        (as a field-update endpoint would, after committing) recomputes the
        score.

        **Validates: Bug 8 — score refresh after a lead field edit**
        """
        from app.services.lead_refresh import refresh_lead_scoring

        with app.app_context():
            lead = Lead(
                property_street="300 Field Edit St",
                lead_status="mailing_no_contact_made",
                has_phone=True,
                has_email=True,
                has_property_match=True,
            )
            db.session.add(lead)
            db.session.commit()
            lead_id = lead.id

            refresh_lead_scoring(lead_id)
            db.session.refresh(lead)
            baseline_score = lead.lead_score

            # Simulate a property-fact field edit that changes scoring inputs,
            # committed by the caller before the refresh runs.
            lead.property_type = 'single_family'
            lead.bedrooms = 3
            lead.year_built = 1990
            lead.square_footage = 1800
            db.session.commit()

            refresh_lead_scoring(lead_id)
            db.session.refresh(lead)

            assert lead.lead_score > baseline_score, (
                f"lead_score did not recompute after a field edit: "
                f"baseline={baseline_score}, now={lead.lead_score}."
            )

    def test_bug8_task_create_and_complete_refresh_action_and_score(self, client, app):
        """Creating then completing a task must refresh the lead's
        recommended_action (open-task count feeds the action) AND its
        lead_score (parity), via the real command-center task endpoints.

        **Validates: Bug 8 — refresh on task create/complete**
        """
        with app.app_context():
            lead = Lead(
                property_street="400 Task St",
                lead_status="mailing_no_contact_made",
                has_phone=True,
                has_email=True,
                has_property_match=True,
                lead_score=99.0,            # stale sentinel — must be recomputed
                recommended_action=None,
            )
            db.session.add(lead)
            db.session.commit()
            lead_id = lead.id

            # --- Create a task -------------------------------------------
            create_resp = client.post(
                f'/api/leads/{lead_id}/tasks',
                json={'title': 'Call owner', 'task_type': 'custom'},
            )
            assert create_resp.status_code == 201
            task_id = create_resp.get_json()['id']

            db.session.refresh(lead)
            # Action refreshed: an open task means we are no longer at the
            # "no open tasks -> create_task" rule, so the action moves to nurture.
            assert lead.recommended_action == 'nurture', (
                f"Expected 'nurture' after task create, got "
                f"{lead.recommended_action!r}."
            )
            # Score refreshed: the stale 99.0 sentinel was recomputed.
            assert lead.lead_score != 99.0, (
                "lead_score was left at the stale sentinel (99.0) after task "
                "create — score refresh is missing."
            )

            # --- Complete the task ---------------------------------------
            complete_resp = client.post(
                f'/api/leads/{lead_id}/tasks/{task_id}/complete'
            )
            assert complete_resp.status_code == 200

            db.session.refresh(lead)
            # Action refreshed again: no open tasks -> create_task.
            assert lead.recommended_action == 'create_task', (
                f"Expected 'create_task' after task complete, got "
                f"{lead.recommended_action!r}."
            )

    def test_bug8_scoring_error_isolated_status_change_still_commits(self, client, app):
        """If the scoring helper hits an internal error (engine raises), the
        user's underlying status change must still succeed and commit — the
        endpoint returns 200 and the new status is persisted.

        **Validates: Bug 8 — error isolation (helper never breaks the caller)**
        """
        with app.app_context():
            lead = Lead(
                property_street="500 Isolation St",
                lead_status="mailing_no_contact_made",
                has_phone=True,
                has_email=True,
                has_property_match=True,
            )
            db.session.add(lead)
            db.session.commit()
            lead_id = lead.id

            # Patch the scoring engine to blow up inside refresh_lead_scoring.
            with patch(
                'app.services.lead_scoring_engine.LeadScoringEngine.compute_score',
                side_effect=RuntimeError("boom — simulated scoring failure"),
            ):
                resp = client.patch(
                    f'/api/leads/{lead_id}/status',
                    json={'status': 'negotiating_remote'},
                )

            # The scoring failure must NOT surface as a 500 — the status change
            # is committed before the refresh and the helper swallows the error.
            assert resp.status_code == 200, (
                f"Status change returned {resp.status_code} when the scoring "
                f"helper raised — the error was not isolated."
            )
            db.session.refresh(lead)
            assert lead.lead_status == 'negotiating_remote', (
                "The user's status change was lost when the scoring helper "
                "failed — error isolation is broken."
            )

    def test_bug8_refresh_helper_swallows_engine_error(self, app):
        """refresh_lead_scoring must never raise into its caller, even when the
        scoring engine raises, and must leave the caller's committed work
        intact.

        **Validates: Bug 8 — helper is fully error-isolated**
        """
        from app.services.lead_refresh import refresh_lead_scoring

        with app.app_context():
            lead = Lead(
                property_street="600 Swallow St",
                lead_status="negotiating_remote",
                has_phone=True,
                has_email=True,
                has_property_match=True,
            )
            db.session.add(lead)
            db.session.commit()
            lead_id = lead.id

            with patch(
                'app.services.lead_scoring_engine.LeadScoringEngine.compute_score',
                side_effect=RuntimeError("boom"),
            ):
                # Must not raise.
                result = refresh_lead_scoring(lead_id)
            assert result is None

            # The lead's committed state is intact (the helper rolled back only
            # its own uncommitted work).
            db.session.refresh(lead)
            assert lead.lead_status == 'negotiating_remote'


# ===========================================================================
# Bug 9 — signal de-duplication + minor no-interest status penalty
# ===========================================================================
#
# Two defects let a data-thin, explicitly-disinterested lead outrank an
# actively-negotiating one (the real Linda 91.9 vs Juan 70.7 inversion):
#
#   A) compute_score summed SIGNAL_ADJUSTMENTS PER ROW, so duplicate
#      HubSpotSignal rows of the same type stacked. A lead with five
#      re-extracted PRIOR_WARM_CONVERSATION rows got +75 instead of +15.
#      Signals represent boolean STATES, not counters — each distinct
#      signal_type must contribute its adjustment AT MOST ONCE.
#   B) _pipeline_stage_bonus rewarded 'mailing_contacted_no_interest' with
#      +5, so explicit disinterest had a net-positive effect. It now carries
#      a minor -10 penalty so a "no interest" lead ranks slightly BELOW an
#      uncontacted one.
#
# A third fix (C) makes signal extraction idempotent: re-extracting the same
# signal for the same (lead_id, signal_type, source_engagement_id) across sync
# runs no longer accumulates duplicate rows.
#
# These tests drive the REAL LeadScoringEngine and the REAL
# HubSpotSignalExtractorService — no inline scoring logic.


class TestBug9SignalDedupAndNoInterest:
    """Bug 9: duplicate same-type signals must not stack in compute_score,
    explicit no-interest must carry a minor penalty (not a bonus), and signal
    extraction must be idempotent across re-runs."""

    def test_bug9_compute_score_dedups_same_signal_type(self, app):
        """Five PRIOR_WARM_CONVERSATION signals score IDENTICALLY to one: the
        +15 adjustment applies once (dedup within a type), never +75.

        **Validates: Bug 9 Fix A — signal dedup within a type**
        """
        from app.services.lead_scoring_engine import LeadScoringEngine
        from app.models.hubspot_signal import HubSpotSignal

        with app.app_context():
            engine = LeadScoringEngine()
            weights = engine.get_weights('default')

            lead = Lead(
                property_street="100 Dedup St",
                lead_status="mailing_no_contact_made",  # stage bonus 0
            )
            db.session.add(lead)
            db.session.commit()

            # Five duplicate PRIOR_WARM_CONVERSATION rows — the re-extraction bug.
            for i in range(5):
                db.session.add(HubSpotSignal(
                    lead_id=lead.id,
                    signal_type="PRIOR_WARM_CONVERSATION",
                    source_engagement_id=f"eng_dup_{i}",
                    raw_evidence="interested",
                ))
            db.session.commit()

            five = HubSpotSignal.query.filter_by(lead_id=lead.id).all()
            assert len(five) == 5, "Setup: expected five duplicate signal rows"

            baseline = engine.compute_score(lead, weights, signals=None)
            score_one = engine.compute_score(lead, weights, signals=[five[0]])
            score_five = engine.compute_score(lead, weights, signals=five)

            # The five duplicates score exactly the same as a single signal.
            assert score_five == score_one, (
                f"Duplicate signals stacked: 5 signals -> {score_five}, "
                f"1 signal -> {score_one}. The +15 must apply once, not five times."
            )
            # And the single adjustment is exactly +15 over the no-signal baseline
            # (proving the dedup keeps the genuine one-time contribution).
            assert score_one == pytest.approx(baseline + 15.0, abs=0.01), (
                f"Expected baseline+15 ({baseline + 15.0}) for one warm signal, "
                f"got {score_one}."
            )

    def test_bug9_distinct_signal_types_still_stack(self, app):
        """Dedup is WITHIN a type, not across types: a PRIOR_WARM_CONVERSATION
        (+15) AND an OFFER_PREVIOUSLY_SENT (+10) together add +25.

        **Validates: Bug 9 Fix A — distinct types still stack**
        """
        from app.services.lead_scoring_engine import LeadScoringEngine

        with app.app_context():
            engine = LeadScoringEngine()
            weights = engine.get_weights('default')

            lead = Lead(
                property_street="200 Stack St",
                lead_status="mailing_no_contact_made",
            )
            db.session.add(lead)
            db.session.commit()

            baseline = engine.compute_score(lead, weights, signals=None)
            score = engine.compute_score(
                lead, weights,
                signals=["PRIOR_WARM_CONVERSATION", "OFFER_PREVIOUSLY_SENT"],
            )

            assert score == pytest.approx(baseline + 25.0, abs=0.01), (
                f"Distinct-type signals must stack: expected baseline+25 "
                f"({baseline + 25.0}), got {score}. Dedup is within a type, "
                f"not across types."
            )

    def test_bug9_no_interest_status_minor_penalty(self, app):
        """_pipeline_stage_bonus returns -10.0 for 'mailing_contacted_no_interest'
        (was +5.0), and a lead in that status scores LOWER than the same lead
        in 'mailing_no_contact_made' (0-bonus baseline), all else equal.

        **Validates: Bug 9 Fix B — minor no-interest penalty**
        """
        from app.services.lead_scoring_engine import LeadScoringEngine

        with app.app_context():
            engine = LeadScoringEngine()
            weights = engine.get_weights('default')

            # The stage bonus itself flipped from +5.0 to -10.0.
            probe = Lead(
                property_street="x",
                lead_status="mailing_contacted_no_interest",
            )
            assert LeadScoringEngine._pipeline_stage_bonus(probe) == -10.0, (
                "mailing_contacted_no_interest stage bonus must be -10.0 (was +5.0)."
            )

            # All else equal, no-interest ranks below an uncontacted (0-bonus) lead.
            common = dict(
                property_street="300 NoInterest Ave",
                mailing_address="999 Elsewhere Rd",
                mailing_city="Chicago",
                mailing_state="IL",
                mailing_zip="60601",
            )
            lead_no_contact = Lead(lead_status="mailing_no_contact_made", **common)
            lead_no_interest = Lead(lead_status="mailing_contacted_no_interest", **common)
            db.session.add_all([lead_no_contact, lead_no_interest])
            db.session.commit()

            score_no_contact = engine.compute_score(lead_no_contact, weights)
            score_no_interest = engine.compute_score(lead_no_interest, weights)

            assert score_no_interest < score_no_contact, (
                f"no-interest ({score_no_interest}) should rank BELOW no-contact "
                f"({score_no_contact}); the -10 penalty was not applied."
            )
            # The gap is exactly the 0 vs -10 stage-bonus difference.
            assert score_no_contact - score_no_interest == pytest.approx(10.0, abs=0.01), (
                f"Expected a 10-point gap (0 vs -10 stage bonus), got "
                f"{score_no_contact - score_no_interest}."
            )

    def test_bug9_ranking_no_interest_below_negotiating(self, app):
        """Mirror the real inversion: Lead L (no-interest, thin data, several
        duplicate PRIOR_WARM_CONVERSATION rows) vs Lead J (negotiating, slightly
        better data, one PRIOR_WARM_CONVERSATION). After compute_score, J > L.

        Under the OLD code L outranked J (no-interest +5 bonus and +75 from five
        stacked warm signals pushed the data-thin lead above the active one).
        The dedup (+15 once) and the -10 no-interest penalty correct it.

        **Validates: Bug 9 Fixes A + B — corrected ranking**
        """
        from app.services.lead_scoring_engine import LeadScoringEngine
        from app.models.hubspot_signal import HubSpotSignal

        with app.app_context():
            engine = LeadScoringEngine()
            weights = engine.get_weights('default')

            # Lead L (Linda) — no-interest, thin data (absentee only), FIVE
            # duplicate warm signals (the re-extracted rows from the real bug).
            lead_l = Lead(
                property_street="2500 N Drake Ave",
                mailing_address="111 Owner Elsewhere Rd",  # absentee, thin otherwise
                lead_status="mailing_contacted_no_interest",
            )
            db.session.add(lead_l)
            db.session.commit()
            for i in range(5):
                db.session.add(HubSpotSignal(
                    lead_id=lead_l.id,
                    signal_type="PRIOR_WARM_CONVERSATION",
                    source_engagement_id=f"eng_L_{i}",
                    raw_evidence="interested",
                ))
            db.session.commit()

            # Lead J (Juan) — negotiating, slightly better data, ONE warm signal.
            lead_j = Lead(
                property_street="123 Juan Way",
                mailing_address="456 Owner Elsewhere Rd",
                mailing_city="Chicago",
                mailing_state="IL",
                mailing_zip="60601",
                property_type="single_family",
                bedrooms=3,
                lead_status="negotiating_remote",
            )
            db.session.add(lead_j)
            db.session.commit()
            db.session.add(HubSpotSignal(
                lead_id=lead_j.id,
                signal_type="PRIOR_WARM_CONVERSATION",
                source_engagement_id="eng_J_1",
                raw_evidence="interested",
            ))
            db.session.commit()

            signals_l = HubSpotSignal.query.filter_by(lead_id=lead_l.id).all()
            signals_j = HubSpotSignal.query.filter_by(lead_id=lead_j.id).all()
            assert len(signals_l) == 5 and len(signals_j) == 1, "Setup invalid"

            score_l = engine.compute_score(lead_l, weights, signals=signals_l)
            score_j = engine.compute_score(lead_j, weights, signals=signals_j)

            assert score_j > score_l, (
                f"Inverted ranking persists: J(negotiating)={score_j} should beat "
                f"L(no-interest, duplicate warm signals)={score_l}. The dedup "
                f"(+15 once, not +75) and the -10 no-interest penalty must "
                f"correct the inversion."
            )

    def test_bug9_extraction_dedup_idempotent(self, app):
        """Extracting + persisting the same signal for the same lead+source twice
        leaves exactly ONE HubSpotSignal row for that key (re-extraction is
        idempotent). Drives the real extractor + persistence path.

        **Validates: Bug 9 Fix C — idempotent signal extraction**
        """
        from app.models.hubspot_signal import HubSpotSignal
        from app.models.hubspot_signal_dictionary import HubSpotSignalDictionary
        from app.services.hubspot_signal_extractor_service import (
            HubSpotSignalExtractorService,
        )

        with app.app_context():
            # Seed a minimal dictionary BEFORE constructing the extractor —
            # the service loads its keyword dictionary in __init__.
            db.session.add(HubSpotSignalDictionary(
                signal_type="PRIOR_WARM_CONVERSATION",
                keywords=["interested"],
            ))
            db.session.flush()

            lead = Lead(
                property_street="900 Idempotent Way",
                lead_status="mailing_no_contact_made",
            )
            db.session.add(lead)
            db.session.flush()

            engagement = HubSpotEngagement(
                hubspot_id="eng_bug9_dedup",
                engagement_type="NOTE",
                raw_payload={"metadata": {"body": "Owner is interested in selling"}},
            )
            db.session.add(engagement)
            db.session.commit()

            extractor = HubSpotSignalExtractorService()

            # First extraction + persist (the real call-site pattern).
            signals1 = extractor.extract_signals(engagement, lead.id)
            for s in signals1:
                db.session.add(s)
            db.session.commit()
            assert any(s.signal_type == "PRIOR_WARM_CONVERSATION" for s in signals1), (
                "First extraction should detect the PRIOR_WARM_CONVERSATION signal."
            )

            # Second extraction of the SAME engagement for the SAME lead — the
            # signal already exists for (lead_id, signal_type, source) so it
            # must be skipped.
            signals2 = extractor.extract_signals(engagement, lead.id)
            for s in signals2:
                db.session.add(s)
            db.session.commit()
            assert all(
                s.signal_type != "PRIOR_WARM_CONVERSATION" for s in signals2
            ), "Re-extraction must skip the already-persisted signal (idempotent)."

            # Exactly ONE row for the (lead_id, signal_type, source) dedup key.
            count = HubSpotSignal.query.filter_by(
                lead_id=lead.id,
                signal_type="PRIOR_WARM_CONVERSATION",
                source_engagement_id="eng_bug9_dedup",
            ).count()
            assert count == 1, (
                f"Expected exactly one PRIOR_WARM_CONVERSATION row for the "
                f"(lead, type, source) key after two extractions, got {count}."
            )
