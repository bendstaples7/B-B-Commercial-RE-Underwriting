"""Tests for Illinois LLC entity resolution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from app import db
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.lead_task import LeadTask
from app.models.organization import Organization
from app.models.organization_party import OrganizationParty
from app.models.property_contact import PropertyContact
from app.models.property_organization_link import PropertyOrganizationLink
from app.services.entity_lookup import (
    EntityLookupProviderNotConfiguredError,
    EntityLookupResult,
    EntityPartyResult,
)
from app.services.entity_resolution_service import EntityResolutionService
from app.services.plugins.owner_name_utils import is_entity_contact
from app.services.skip_trace_enqueue import SkipTraceEnqueue


@dataclass
class FakeProvider:
    name: str = "fake"
    configured: bool = True
    result: Optional[EntityLookupResult] = None
    calls: list = field(default_factory=list)

    def is_configured(self) -> bool:
        return self.configured

    def lookup_llc(self, name: str, *, jurisdiction: str = "us_il") -> EntityLookupResult:
        self.calls.append({"name": name, "jurisdiction": jurisdiction})
        if self.result is not None:
            return self.result
        return EntityLookupResult(found=False, provider_name=self.name, error="no result")


def _make_lead(**kwargs) -> Lead:
    defaults = dict(
        property_street="100 Main St",
        property_city="Chicago",
        property_state="IL",
        property_zip="60601",
        ownership_type="entity",
    )
    defaults.update(kwargs)
    lead = Lead(**defaults)
    db.session.add(lead)
    db.session.flush()
    return lead


def _link_primary(lead_id: int, first: str | None, last: str | None) -> Contact:
    contact = Contact(first_name=first, last_name=last, role="owner")
    db.session.add(contact)
    db.session.flush()
    db.session.add(PropertyContact(
        property_id=lead_id,
        contact_id=contact.id,
        role="owner",
        is_primary=True,
    ))
    db.session.commit()
    return contact


class TestEntityDetection:
    def test_llc_shaped_contact(self):
        assert is_entity_contact(None, "BSD JEFFERY, LLC") is True
        assert is_entity_contact("Jane", "Smith") is False

    def test_company_suffix_with_punctuation_is_entity(self):
        assert is_entity_contact(None, "ACME Co.") is True


class TestEntityResolutionService:
    def test_skips_non_entity_primary(self, app):
        with app.app_context():
            lead = _make_lead()
            _link_primary(lead.id, "Jane", "Smith")
            provider = FakeProvider()
            result = EntityResolutionService(provider=provider).resolve_lead(lead.id)
            assert result.status == "skipped"
            assert provider.calls == []

    def test_non_illinois_unsupported_without_provider_call(self, app):
        with app.app_context():
            lead = _make_lead(property_state="DE", mailing_state="DE")
            _link_primary(lead.id, None, "ACME HOLDINGS LLC")
            provider = FakeProvider()
            result = EntityResolutionService(provider=provider).resolve_lead(lead.id)
            assert result.status == "unsupported_jurisdiction"
            assert provider.calls == []
            org = Organization.query.filter_by(name="ACME HOLDINGS LLC").first()
            assert org is not None
            assert org.entity_lookup_status == "unsupported_jurisdiction"

    def test_happy_path_promotes_manager_and_enqueues_skip_trace(self, app):
        with app.app_context():
            lead = _make_lead()
            llc = _link_primary(lead.id, None, "SUNRISE PROPERTIES LLC")
            provider = FakeProvider(result=EntityLookupResult(
                found=True,
                jurisdiction="us_il",
                name="SUNRISE PROPERTIES LLC",
                file_number="01234567",
                status="active",
                registered_agent_name="CSC AGENT LLC",
                parties=[
                    EntityPartyResult(
                        full_name="CSC AGENT LLC",
                        party_type="registered_agent",
                        is_company=True,
                    ),
                    EntityPartyResult(
                        full_name="John Manager",
                        party_type="manager",
                        is_company=False,
                        first_name="John",
                        last_name="Manager",
                    ),
                ],
                provider_name="fake",
            ))
            result = EntityResolutionService(provider=provider).resolve_lead(lead.id)
            assert result.status == "resolved"
            assert result.person_found is True
            assert result.person_contact_id is not None
            assert result.skip_trace_task_id is not None

            person = Contact.query.get(result.person_contact_id)
            assert person.first_name == "John"
            assert person.last_name == "Manager"

            person_link = PropertyContact.query.filter_by(
                property_id=lead.id, contact_id=person.id,
            ).first()
            assert person_link.is_primary is True

            llc_link = PropertyContact.query.filter_by(
                property_id=lead.id, contact_id=llc.id,
            ).first()
            assert llc_link is not None
            assert llc_link.is_primary is False

            org = Organization.query.get(result.organization_id)
            assert org.entity_lookup_status == "resolved"
            assert org.entity_lookup_person_found is True
            assert org.file_number == "01234567"
            assert OrganizationParty.query.filter_by(organization_id=org.id).count() == 2
            assert PropertyOrganizationLink.query.filter_by(
                property_id=lead.id, organization_id=org.id, role="owner",
            ).first() is not None

            task = LeadTask.query.get(result.skip_trace_task_id)
            assert task.task_type == "skip_trace_owner"
            assert task.status == "open"
            assert Lead.query.get(lead.id).needs_skip_trace is True

    def test_corporate_ra_only_does_not_promote_person(self, app):
        with app.app_context():
            lead = _make_lead()
            llc = _link_primary(lead.id, None, "RA ONLY LLC")
            provider = FakeProvider(result=EntityLookupResult(
                found=True,
                jurisdiction="us_il",
                name="RA ONLY LLC",
                parties=[
                    EntityPartyResult(
                        full_name="CORPORATE SERVICES INC",
                        party_type="registered_agent",
                        is_company=True,
                    ),
                ],
                provider_name="fake",
            ))
            result = EntityResolutionService(provider=provider).resolve_lead(lead.id)
            assert result.status == "resolved"
            assert result.person_found is False
            assert result.person_contact_id is None
            assert result.skip_trace_task_id is None

            llc_link = PropertyContact.query.filter_by(
                property_id=lead.id, contact_id=llc.id,
            ).first()
            assert llc_link.is_primary is True

            org = Organization.query.get(result.organization_id)
            assert org.entity_lookup_person_found is False

    def test_blank_party_name_is_ignored(self, app):
        with app.app_context():
            lead = _make_lead()
            _link_primary(lead.id, None, "BLANK PARTY LLC")
            provider = FakeProvider(result=EntityLookupResult(
                found=True,
                jurisdiction="us_il",
                name="BLANK PARTY LLC",
                parties=[
                    EntityPartyResult(
                        full_name="",
                        party_type="manager",
                        is_company=False,
                    ),
                ],
                provider_name="fake",
            ))
            result = EntityResolutionService(provider=provider).resolve_lead(lead.id)
            assert result.status == "resolved"
            assert result.person_found is False
            assert result.person_contact_id is None

    def test_idempotent_re_resolve(self, app):
        with app.app_context():
            lead = _make_lead()
            _link_primary(lead.id, None, "REPEAT LLC")
            parties = [
                EntityPartyResult(
                    full_name="Ada Owner",
                    party_type="member",
                    is_company=False,
                    first_name="Ada",
                    last_name="Owner",
                ),
            ]
            provider = FakeProvider(result=EntityLookupResult(
                found=True,
                jurisdiction="us_il",
                name="REPEAT LLC",
                parties=parties,
                provider_name="fake",
            ))
            svc = EntityResolutionService(provider=provider)
            first = svc.resolve_lead(lead.id)
            second = svc.resolve_lead(lead.id)
            assert first.person_contact_id == second.person_contact_id
            people = (
                db.session.query(Contact)
                .join(PropertyContact)
                .filter(
                    PropertyContact.property_id == lead.id,
                    Contact.first_name == "Ada",
                    Contact.last_name == "Owner",
                )
                .all()
            )
            assert len(people) == 1
            open_tasks = LeadTask.query.filter_by(
                lead_id=lead.id, task_type="skip_trace_owner", status="open",
            ).count()
            assert open_tasks == 1

            status = svc.get_status(lead.id)
            assert status["primary_is_entity"] is False
            assert status["entity_name"] == "REPEAT LLC"
            assert status["can_resolve"] is True

    def test_provider_not_configured_raises(self, app):
        with app.app_context():
            lead = _make_lead()
            _link_primary(lead.id, None, "NO KEY LLC")
            provider = FakeProvider(configured=False)
            with pytest.raises(EntityLookupProviderNotConfiguredError):
                EntityResolutionService(provider=provider).resolve_lead(lead.id)

    def test_get_status_reports_entity_primary(self, app):
        with app.app_context():
            lead = _make_lead()
            _link_primary(lead.id, None, "STATUS LLC")
            status = EntityResolutionService(provider=FakeProvider()).get_status(lead.id)
            assert status["primary_is_entity"] is True
            assert status["can_resolve"] is True
            assert status["entity_name"] == "STATUS LLC"

    def test_org_upsert_does_not_treat_percent_as_like_wildcard(self, app):
        with app.app_context():
            lead = _make_lead()
            _link_primary(lead.id, None, "100% RETURNS LLC")
            # Pre-existing unrelated org whose name would match ilike('100% RETURNS LLC')
            db.session.add(Organization(
                name="100 ANYTHING RETURNS LLC",
                org_type="llc",
                status="unknown",
                source="test",
            ))
            db.session.commit()
            provider = FakeProvider(result=EntityLookupResult(
                found=True,
                jurisdiction="us_il",
                name="100% RETURNS LLC",
                file_number="55555555",
                parties=[
                    EntityPartyResult(
                        full_name="Pat Percent",
                        party_type="manager",
                        is_company=False,
                        first_name="Pat",
                        last_name="Percent",
                    ),
                ],
                provider_name="fake",
            ))
            result = EntityResolutionService(provider=provider).resolve_lead(lead.id)
            assert result.status == "resolved"
            org = Organization.query.get(result.organization_id)
            assert org.name == "100% RETURNS LLC"
            assert org.file_number == "55555555"
            other = Organization.query.filter_by(name="100 ANYTHING RETURNS LLC").first()
            assert other.file_number is None
            assert other.entity_lookup_status is None


class TestSkipTraceEnqueue:
    def test_creates_task_once(self, app):
        with app.app_context():
            lead = _make_lead(ownership_type="individual")
            db.session.commit()
            enqueue = SkipTraceEnqueue()
            t1 = enqueue.enqueue(lead.id, contact_id=99)
            t2 = enqueue.enqueue(lead.id, contact_id=99)
            assert t1 is not None and t2 is not None
            assert t1.id == t2.id
            assert LeadTask.query.filter_by(
                lead_id=lead.id, task_type="skip_trace_owner", status="open",
            ).count() == 1


def test_backfill_limit_zero_yields_no_candidates(app):
    from scripts.backfill_entity_resolution import _iter_candidate_lead_ids

    with app.app_context():
        lead = _make_lead()
        _link_primary(lead.id, None, "LIMIT ZERO LLC")
        assert list(_iter_candidate_lead_ids(0)) == []
