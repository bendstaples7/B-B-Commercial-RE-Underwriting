"""Tests for IRS EO nonprofit lookup and entity mail deprioritization."""
from unittest.mock import MagicMock

import pytest

from app.services.entity_lookup.irs_eo import (
    IrsEoNonprofitProvider,
    normalize_eo_name,
    upsert_eo_row,
)
from app.services.entity_owner_policy import cold_mail_block_reason
from app.services.lead_scoring_engine import LeadScoringEngine


class TestNormalizeEoName:
    def test_strips_inc_and_punctuation(self):
        assert normalize_eo_name("Voice of the People in Uptown, Inc.") == (
            "VOICE OF THE PEOPLE IN UPTOWN"
        )

    def test_ampersand(self):
        assert "AND" in normalize_eo_name("Cats & Dogs Foundation")


@pytest.mark.usefixtures("app")
class TestIrsEoLookup:
    def test_lookup_match_by_name_and_state(self, app):
        with app.app_context():
            from app import db

            upsert_eo_row(
                ein="123456789",
                name="Voice of the People in Uptown Inc",
                city="Chicago",
                state="IL",
                subsection="03",
            )
            db.session.commit()

            result = IrsEoNonprofitProvider().lookup_nonprofit(
                "Voice of the People in Uptown, Inc.",
                state="IL",
            )
            assert result.found is True
            assert result.ein == "123456789"

    def test_lookup_no_match(self, app):
        with app.app_context():
            from app import db

            upsert_eo_row(
                ein="987654321",
                name="Some Other Charity",
                state="IL",
            )
            db.session.commit()

            result = IrsEoNonprofitProvider().lookup_nonprofit(
                "North Lockwood Jazz Inc",
                state="IL",
            )
            assert result.found is False

    def test_ambiguous_name_rejected(self, app):
        with app.app_context():
            from app import db

            upsert_eo_row(ein="111111111", name="Shared Charity Name Inc", state="IL")
            upsert_eo_row(ein="222222222", name="Shared Charity Name Inc", state="IL")
            db.session.commit()

            result = IrsEoNonprofitProvider().lookup_nonprofit(
                "Shared Charity Name Inc",
                state="IL",
            )
            assert result.found is False
            assert "Ambiguous" in (result.error or "")

    def test_prefers_single_active_among_ambiguous(self, app):
        with app.app_context():
            from app import db

            upsert_eo_row(
                ein="111111111",
                name="Shared Charity Name Inc",
                state="IL",
                status="02",
            )
            upsert_eo_row(
                ein="222222222",
                name="Shared Charity Name Inc",
                state="IL",
                status="01",
            )
            db.session.commit()

            result = IrsEoNonprofitProvider().lookup_nonprofit(
                "Shared Charity Name Inc",
                state="IL",
            )
            assert result.found is True
            assert result.ein == "222222222"

    def test_upsert_truncates_wide_fields(self, app):
        with app.app_context():
            from app import db

            row = upsert_eo_row(
                ein="444444444",
                name="Wide Fields Org",
                city="C" * 80,
                state="IL",
                ntee_cd="NTEECODETOO_LONG",
                subsection="12345",
                status="ABCD",
            )
            db.session.commit()
            assert len(row.city or "") <= 64
            assert len(row.ntee_cd or "") <= 10
            assert len(row.subsection or "") <= 4
            assert len(row.status or "") <= 2

    def test_no_national_fallback(self, app):
        with app.app_context():
            from app import db

            upsert_eo_row(
                ein="333333333",
                name="Out Of State Org Inc",
                state="CA",
            )
            db.session.commit()

            result = IrsEoNonprofitProvider().lookup_nonprofit(
                "Out Of State Org Inc",
                state="IL",
            )
            assert result.found is False

    def test_rejects_overlong_ein(self, app):
        with app.app_context():
            with pytest.raises(ValueError):
                upsert_eo_row(ein="12-34567890", name="Bad EIN Charity", state="IL")


@pytest.mark.usefixtures("app")
class TestColdMailBlockReason:
    def test_institutional_owner(self, app):
        with app.app_context():
            from app.models.lead import Lead
            from app import db

            lead = Lead(
                property_street="100 Main",
                property_city="Chicago",
                property_state="IL",
                property_zip="60601",
                owner_last_name="First Baptist Church",
                ownership_type="entity",
                lead_status="mailing_no_contact_made",
            )
            db.session.add(lead)
            db.session.commit()
            assert cold_mail_block_reason(lead) == "institutional_owner"

    def test_tax_exempt_owner(self, app):
        with app.app_context():
            from app.models.lead import Lead
            from app import db

            lead = Lead(
                property_street="100 Main",
                property_city="Chicago",
                property_state="IL",
                property_zip="60601",
                owner_last_name="Some Org",
                ownership_type="tax_exempt",
                lead_status="mailing_no_contact_made",
            )
            db.session.add(lead)
            db.session.commit()
            assert cold_mail_block_reason(lead) == "tax_exempt_owner"

    def test_unresolved_entity(self, app):
        with app.app_context():
            from app.models.lead import Lead
            from app import db

            lead = Lead(
                property_street="100 Main",
                property_city="Chicago",
                property_state="IL",
                property_zip="60601",
                owner_last_name="North Lockwood Jazz Inc",
                ownership_type="entity",
                lead_status="mailing_no_contact_made",
            )
            db.session.add(lead)
            db.session.commit()
            assert cold_mail_block_reason(lead) == "unresolved_entity_owner"

    def test_ignores_non_owner_primary_contact(self, app):
        with app.app_context():
            from app import db
            from app.models.contact import Contact
            from app.models.lead import Lead
            from app.models.property_contact import PropertyContact

            lead = Lead(
                property_street="100 Main",
                property_city="Chicago",
                property_state="IL",
                property_zip="60601",
                owner_first_name="Jane",
                owner_last_name="Doe",
                ownership_type="person",
                lead_status="mailing_no_contact_made",
            )
            db.session.add(lead)
            db.session.flush()
            manager = Contact(first_name=None, last_name="North Lockwood LLC")
            db.session.add(manager)
            db.session.flush()
            db.session.add(PropertyContact(
                property_id=lead.id,
                contact_id=manager.id,
                role="property_manager",
                is_primary=True,
            ))
            db.session.commit()

            assert cold_mail_block_reason(lead) is None

    def test_any_nonprofit_owner_org_blocks_mail(self, app):
        with app.app_context():
            from app import db
            from app.models.lead import Lead
            from app.models.organization import Organization
            from app.models.property_organization_link import PropertyOrganizationLink

            lead = Lead(
                property_street="100 Main",
                property_city="Chicago",
                property_state="IL",
                property_zip="60601",
                owner_last_name="North Lockwood LLC",
                ownership_type="entity",
                lead_status="mailing_no_contact_made",
            )
            nonprofit = Organization(name="Neighborhood Foundation", org_type="nonprofit")
            llc = Organization(name="North Lockwood LLC", org_type="llc")
            db.session.add_all([lead, nonprofit, llc])
            db.session.flush()
            db.session.add_all([
                PropertyOrganizationLink(
                    property_id=lead.id,
                    organization_id=nonprofit.id,
                    role="owner",
                ),
                PropertyOrganizationLink(
                    property_id=lead.id,
                    organization_id=llc.id,
                    role="owner",
                ),
            ])
            db.session.commit()

            assert cold_mail_block_reason(lead) == "nonprofit_organization"


class TestScoringMailGate:
    def test_commercial_needs_review_with_mail_in_flight_is_nurture(self, monkeypatch):
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._mail_work_in_flight',
            lambda lead_id: True,
        )

        lead = MagicMock()
        lead.lead_status = 'mailing_no_contact_made'
        lead.lead_category = 'commercial'
        lead.condo_risk_status = 'needs_review'
        lead.do_not_contact = False
        lead.id = 4860

        action, reason, meta = LeadScoringEngine.evaluate_recommended_action(
            lead, total_score=60.0, data_quality_score=50.0, score_tier='C',
        )
        assert action == 'nurture'
        assert reason == 'mail_work_in_flight'
        assert meta.get('condo_risk_status') == 'needs_review'

    def test_commercial_likely_condo_still_suppress_with_mail_in_flight(self, monkeypatch):
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._mail_work_in_flight',
            lambda lead_id: True,
        )

        lead = MagicMock()
        lead.lead_status = 'mailing_no_contact_made'
        lead.lead_category = 'commercial'
        lead.condo_risk_status = 'likely_condo'
        lead.do_not_contact = False
        lead.id = 4861

        action, reason, meta = LeadScoringEngine.evaluate_recommended_action(
            lead, total_score=60.0, data_quality_score=50.0, score_tier='C',
        )
        assert action == 'suppress'
        assert reason == 'likely_condo'
        assert meta.get('condo_risk_status') == 'likely_condo'

    def test_commercial_needs_review_without_mail_still_nmr(self, monkeypatch):
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._mail_work_in_flight',
            lambda lead_id: False,
        )

        lead = MagicMock()
        lead.lead_status = 'mailing_no_contact_made'
        lead.lead_category = 'commercial'
        lead.condo_risk_status = 'needs_review'
        lead.do_not_contact = False
        lead.id = 4862

        action, reason, _meta = LeadScoringEngine.evaluate_recommended_action(
            lead, total_score=60.0, data_quality_score=50.0, score_tier='C',
        )
        assert action == 'needs_manual_review'
        assert reason == 'condo_needs_review'

    def test_institutional_nurture_instead_of_mail_ready(self, monkeypatch):
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._resolve_crm_flags',
            lambda lead: (False, False, True),
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine.cold_mail_block_reason',
            lambda lead: 'institutional_owner',
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine.is_mailable_lead',
            lambda lead: True,
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._mail_work_in_flight',
            lambda lead_id: False,
        )
        monkeypatch.setattr(
            'app.services.scoring_rubric.is_recently_sold',
            lambda lead: False,
        )

        lead = MagicMock()
        lead.lead_status = 'mailing_no_contact_made'
        lead.lead_category = 'residential'
        lead.do_not_contact = False
        lead.follow_up_overdue = False
        lead.is_warm = False
        lead.id = 99

        action, reason, meta = LeadScoringEngine.evaluate_recommended_action(
            lead, total_score=80.0, data_quality_score=80.0, score_tier='A',
        )
        assert action == 'nurture'
        assert reason == 'institutional_owner'
        assert meta.get('cold_mail_blocked') is True

    def test_warm_institutional_still_follow_up(self, monkeypatch):
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._resolve_crm_flags',
            lambda lead: (True, False, True),
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine.cold_mail_block_reason',
            lambda lead: 'institutional_owner',
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._mail_work_in_flight',
            lambda lead_id: False,
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._has_overdue_lead_task',
            lambda lead_id: False,
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._count_open_tasks',
            lambda lead_id: 0,
        )

        lead = MagicMock()
        lead.lead_status = 'contacted'
        lead.lead_category = 'residential'
        lead.do_not_contact = False
        lead.follow_up_overdue = False
        lead.is_warm = True
        lead.id = 98
        lead.property_street = '1 Main'

        action, reason, _meta = LeadScoringEngine.evaluate_recommended_action(
            lead, total_score=80.0, data_quality_score=80.0, score_tier='A',
        )
        assert action == 'follow_up_now'
        assert reason == 'is_warm'

    def test_unresolved_entity_enrich(self, monkeypatch):
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._resolve_crm_flags',
            lambda lead: (False, False, True),
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine.cold_mail_block_reason',
            lambda lead: 'unresolved_entity_owner',
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine.is_mailable_lead',
            lambda lead: True,
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._mail_work_in_flight',
            lambda lead_id: False,
        )
        monkeypatch.setattr(
            'app.services.scoring_rubric.is_recently_sold',
            lambda lead: False,
        )

        lead = MagicMock()
        lead.lead_status = 'mailing_no_contact_made'
        lead.lead_category = 'residential'
        lead.do_not_contact = False
        lead.follow_up_overdue = False
        lead.is_warm = False
        lead.id = 100

        action, reason, meta = LeadScoringEngine.evaluate_recommended_action(
            lead, total_score=80.0, data_quality_score=80.0, score_tier='A',
        )
        assert action == 'enrich_data'
        assert reason == 'research_entity_owner'
        assert meta.get('requires_entity_research') is True

    def test_person_owner_still_mail_ready(self, monkeypatch):
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._resolve_crm_flags',
            lambda lead: (False, False, True),
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine.cold_mail_block_reason',
            lambda lead: None,
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine.is_mailable_lead',
            lambda lead: True,
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._mail_work_in_flight',
            lambda lead_id: False,
        )
        monkeypatch.setattr(
            'app.services.scoring_rubric.is_recently_sold',
            lambda lead: False,
        )

        lead = MagicMock()
        lead.lead_status = 'mailing_no_contact_made'
        lead.lead_category = 'residential'
        lead.do_not_contact = False
        lead.follow_up_overdue = False
        lead.is_warm = False
        lead.id = 101
        lead.owner_first_name = 'Jane'
        lead.owner_last_name = 'Doe'

        action, reason, _meta = LeadScoringEngine.evaluate_recommended_action(
            lead, total_score=50.0, data_quality_score=50.0, score_tier='C',
        )
        assert action == 'mail_ready'
        assert reason == 'mailable_no_digital_contact'

    def test_post_refinement_mail_ready_is_blocked(self, monkeypatch):
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._resolve_crm_flags',
            lambda lead: (True, False, True),
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine.cold_mail_block_reason',
            lambda lead: 'institutional_owner',
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._mail_work_in_flight',
            lambda lead_id: False,
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._has_overdue_lead_task',
            lambda lead_id: False,
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine._count_open_tasks',
            lambda lead_id: 0,
        )
        monkeypatch.setattr(
            LeadScoringEngine,
            '_has_recent_email',
            staticmethod(lambda lead_id: False),
        )
        monkeypatch.setattr(
            'app.services.scoring_rubric.is_recently_sold',
            lambda lead: False,
        )

        lead = MagicMock()
        lead.id = 102
        lead.lead_score = 75.0
        lead.data_completeness_score = 50.0
        lead.motivation_score = 0.0
        lead.lead_status = 'mailing_no_contact_made'
        lead.lead_category = 'residential'
        lead.do_not_contact = False
        lead.follow_up_overdue = False
        lead.is_warm = False
        lead.property_street = '1 Main'
        lead.mailing_address = '1 Main'
        lead.mailing_city = 'Chicago'
        lead.mailing_state = 'IL'
        lead.mailing_zip = '60601'
        lead.returned_addresses = None
        lead.unanswered_call_count = 0

        assert LeadScoringEngine.compute_recommended_action(lead) == 'nurture'

    def test_ready_for_outreach_refined_to_mail_is_still_blocked(
        self,
        monkeypatch,
    ):
        lead = MagicMock()
        lead.id = 103
        lead.lead_score = 75.0
        lead.data_completeness_score = 50.0
        lead.motivation_score = 0.0
        lead.mailing_address = '1 Main'
        lead.mailing_city = 'Chicago'
        lead.mailing_state = 'IL'
        lead.mailing_zip = '60601'
        lead.returned_addresses = None
        monkeypatch.setattr(
            LeadScoringEngine,
            'evaluate_recommended_action',
            staticmethod(lambda *_args, **_kwargs: (
                'ready_for_outreach',
                'high_score_outreach',
                {},
            )),
        )
        monkeypatch.setattr(
            LeadScoringEngine,
            '_apply_outreach_method',
            lambda *_args, **_kwargs: ('mail_ready', 'direct_mail'),
        )
        monkeypatch.setattr(
            'app.services.lead_scoring_engine.cold_mail_block_reason',
            lambda _lead: 'institutional_owner',
        )

        assert LeadScoringEngine.compute_recommended_action(lead) == 'nurture'


@pytest.mark.usefixtures("app")
class TestEntityResolutionNonprofitPath:
    def test_institutional_resolve_marks_nonprofit(self, app):
        with app.app_context():
            from app import db
            from app.models.lead import Lead
            from app.models.contact import Contact
            from app.models.property_contact import PropertyContact
            from app.services.entity_resolution_service import EntityResolutionService
            from app.services.entity_lookup.irs_eo import IrsEoNonprofitProvider

            lead = Lead(
                property_street="200 Oak",
                property_city="Chicago",
                property_state="IL",
                property_zip="60614",
                owner_last_name="First Baptist Church",
                ownership_type="entity",
                lead_status="mailing_no_contact_made",
            )
            db.session.add(lead)
            db.session.flush()
            contact = Contact(first_name=None, last_name="First Baptist Church")
            db.session.add(contact)
            db.session.flush()
            db.session.add(PropertyContact(
                property_id=lead.id,
                contact_id=contact.id,
                role="owner",
                is_primary=True,
            ))
            db.session.commit()

            # Avoid requiring SOS bulk for this path.
            class _NoSos:
                name = "stub"
                def is_configured(self):
                    return False
                def lookup_llc(self, *args, **kwargs):
                    raise AssertionError("SOS should not be called for institutional")

            svc = EntityResolutionService(
                provider=_NoSos(),
                nonprofit_provider=IrsEoNonprofitProvider(),
            )
            result = svc.resolve_lead(lead.id)
            assert result.status == "nonprofit"
            assert result.organization_id is not None

            from app.models.organization import Organization
            org = db.session.get(Organization, result.organization_id)
            assert org is not None
            assert org.org_type == "nonprofit"

    def test_irs_match_before_llc(self, app):
        with app.app_context():
            from app import db
            from app.models.lead import Lead
            from app.models.contact import Contact
            from app.models.property_contact import PropertyContact
            from app.services.entity_resolution_service import EntityResolutionService
            from app.services.entity_lookup.irs_eo import (
                IrsEoNonprofitProvider,
                upsert_eo_row,
            )

            upsert_eo_row(
                ein="111223333",
                name="Voice of the People in Uptown Inc",
                state="IL",
            )
            lead = Lead(
                property_street="300 Pine",
                property_city="Chicago",
                property_state="IL",
                property_zip="60640",
                owner_last_name="Voice of the People in Uptown Inc",
                ownership_type="entity",
                lead_status="mailing_no_contact_made",
            )
            db.session.add(lead)
            db.session.flush()
            contact = Contact(
                first_name=None,
                last_name="Voice of the People in Uptown Inc",
            )
            db.session.add(contact)
            db.session.flush()
            db.session.add(PropertyContact(
                property_id=lead.id,
                contact_id=contact.id,
                role="owner",
                is_primary=True,
            ))
            db.session.commit()

            class _NoSos:
                name = "stub"
                def is_configured(self):
                    return True
                def lookup_llc(self, *args, **kwargs):
                    raise AssertionError("SOS should not run after IRS nonprofit match")

            svc = EntityResolutionService(
                provider=_NoSos(),
                nonprofit_provider=IrsEoNonprofitProvider(),
            )
            result = svc.resolve_lead(lead.id)
            assert result.status == "nonprofit"
            assert "IRS EO" in (result.message or "")

    def test_nonprofit_research_miss_preserves_resolved_llc(self, app):
        with app.app_context():
            from app import db
            from app.models.contact import Contact
            from app.models.lead import Lead
            from app.models.organization import Organization
            from app.models.property_contact import PropertyContact
            from app.models.property_organization_link import PropertyOrganizationLink
            from app.services.entity_lookup.irs_eo import NonprofitLookupResult
            from app.services.entity_resolution_service import EntityResolutionService

            lead = Lead(
                property_street="300 Pine",
                property_city="Chicago",
                property_state="IL",
                property_zip="60640",
                owner_last_name="North Lockwood LLC",
                ownership_type="entity",
                lead_status="mailing_no_contact_made",
            )
            db.session.add(lead)
            db.session.flush()
            contact = Contact(first_name=None, last_name="North Lockwood LLC")
            org = Organization(
                name="North Lockwood LLC",
                org_type="llc",
                entity_lookup_status="resolved",
                entity_lookup_person_found=False,
            )
            db.session.add_all([contact, org])
            db.session.flush()
            db.session.add_all([
                PropertyContact(
                    property_id=lead.id,
                    contact_id=contact.id,
                    role="owner",
                    is_primary=True,
                ),
                PropertyOrganizationLink(
                    property_id=lead.id,
                    organization_id=org.id,
                    role="owner",
                ),
            ])
            db.session.commit()

            class _NoHit:
                def is_configured(self):
                    return True

                def lookup_nonprofit(self, *args, **kwargs):
                    return NonprofitLookupResult(found=False, provider_name="stub")

            svc = EntityResolutionService(nonprofit_provider=_NoHit())
            result = svc.research_nonprofit(lead.id)
            db.session.refresh(org)

            assert result.status == "no_match"
            assert result.organization_id == org.id
            assert org.entity_lookup_status == "resolved"
