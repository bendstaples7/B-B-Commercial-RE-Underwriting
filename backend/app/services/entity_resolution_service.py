"""EntityResolutionService — LLC primary contact → Illinois filing → person Contact.

Canonical orchestrator for entity lookup status on Organization records.
Does not call skip-trace vendors; hands off via SkipTraceEnqueue.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func, text

from app import db
from app.exceptions import ResourceNotFoundError
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.organization import Organization
from app.models.organization_party import OrganizationParty
from app.models.property_contact import PropertyContact
from app.models.property_organization_link import PropertyOrganizationLink
from app.services.contact_service import ContactService
from app.services.entity_lookup import (
    SUPPORTED_JURISDICTION,
    EntityLookupProvider,
    EntityLookupProviderNotConfiguredError,
    EntityLookupResult,
    EntityPartyResult,
)
from app.services.entity_lookup.factory import get_entity_lookup_provider
from app.services.plugins.owner_name_utils import (
    contact_display_name,
    is_entity_contact,
    is_entity_name,
)
from app.services.skip_trace_enqueue import SkipTraceEnqueue

logger = logging.getLogger(__name__)

_PERSON_PARTY_PRIORITY = ("manager", "member", "officer")
_IL_STATE_CODES = frozenset({"IL", "ILLINOIS"})

FREE_BULK_LIMITATIONS = [
    "Free Illinois SOS bulk only — no phones or emails (skip-trace task covers that).",
    "Non-Illinois entities are not supported yet.",
    "Corporate registered agents are not promoted to primary contact.",
    "Manager list may be incomplete or stale versus a live SOS File Detail Report.",
    "Foreign home LLCs (e.g. Delaware) may not appear in the Illinois dump.",
]


@dataclass
class EntityResolutionResult:
    """Structured result of resolve_lead / dry-run."""

    lead_id: int
    status: str
    entity_name: Optional[str] = None
    organization_id: Optional[int] = None
    person_contact_id: Optional[int] = None
    person_found: bool = False
    person_name: Optional[str] = None
    skip_trace_task_id: Optional[int] = None
    message: Optional[str] = None
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {
            "lead_id": self.lead_id,
            "status": self.status,
            "entity_name": self.entity_name,
            "organization_id": self.organization_id,
            "person_contact_id": self.person_contact_id,
            "person_found": self.person_found,
            "person_name": self.person_name,
            "skip_trace_task_id": self.skip_trace_task_id,
            "message": self.message,
            "dry_run": self.dry_run,
        }


class EntityResolutionService:
    """Resolve LLC-shaped primary contacts into person contacts via entity lookup."""

    def __init__(
        self,
        provider: Optional[EntityLookupProvider] = None,
        *,
        contact_service: Optional[ContactService] = None,
        skip_trace: Optional[SkipTraceEnqueue] = None,
    ) -> None:
        self._provider = provider
        self._contacts = contact_service or ContactService()
        self._skip_trace = skip_trace or SkipTraceEnqueue()

    def _get_provider(self) -> EntityLookupProvider:
        if self._provider is not None:
            return self._provider
        return get_entity_lookup_provider()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_status(self, lead_id: int) -> dict:
        """Return entity-resolution status for a lead (for UI)."""
        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ResourceNotFoundError(
                f"Lead id={lead_id} not found.",
                payload={"lead_id": lead_id},
            )

        primary = self._get_primary_contact(lead_id)
        entity_shaped = False
        entity_name = None
        if primary is not None:
            entity_shaped = is_entity_contact(primary.first_name, primary.last_name)
            if entity_shaped:
                entity_name = contact_display_name(primary.first_name, primary.last_name)

        org = self._get_linked_owner_org(lead_id)
        if entity_name is None:
            linked_entity_contact = self._find_entity_contact(lead_id)
            if linked_entity_contact is not None:
                entity_name = contact_display_name(
                    linked_entity_contact.first_name,
                    linked_entity_contact.last_name,
                )
            elif org is not None and is_entity_name(org.name or ""):
                entity_name = org.name
        jurisdiction_ok = self._lead_looks_illinois(lead)
        provider = self._get_provider()
        provider_name = getattr(provider, "name", None)
        dataset_imported_at = None
        provider_configured = True
        if hasattr(provider, "dataset_imported_at"):
            try:
                dataset_imported_at = provider.dataset_imported_at()
            except Exception:  # noqa: BLE001
                dataset_imported_at = None
        if hasattr(provider, "is_configured"):
            try:
                provider_configured = bool(provider.is_configured())
            except Exception:  # noqa: BLE001
                provider_configured = False

        return {
            "lead_id": lead_id,
            "primary_is_entity": entity_shaped,
            "entity_name": entity_name,
            "jurisdiction_supported": jurisdiction_ok,
            "supported_jurisdiction": SUPPORTED_JURISDICTION,
            "organization_id": org.id if org else None,
            "organization_name": org.name if org else None,
            "entity_lookup_status": org.entity_lookup_status if org else None,
            "entity_lookup_person_found": (
                bool(org.entity_lookup_person_found) if org else False
            ),
            "entity_lookup_error": org.entity_lookup_error if org else None,
            "entity_lookup_checked_at": (
                org.entity_lookup_checked_at.isoformat()
                if org and org.entity_lookup_checked_at
                else None
            ),
            "entity_lookup_provider": (
                org.entity_lookup_provider if org else provider_name
            ),
            "provider": provider_name,
            "provider_configured": provider_configured,
            "dataset_imported_at": dataset_imported_at,
            "limitations": list(FREE_BULK_LIMITATIONS),
            "can_resolve": bool(
                entity_name and jurisdiction_ok and provider_configured
            ),
        }

    def resolve_lead(
        self,
        lead_id: int,
        *,
        dry_run: bool = False,
        actor: str = "entity_resolution",
    ) -> EntityResolutionResult:
        """Run Illinois entity resolution for *lead_id*."""
        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ResourceNotFoundError(
                f"Lead id={lead_id} not found.",
                payload={"lead_id": lead_id},
            )

        primary = self._get_primary_contact(lead_id)
        entity_contact = None
        if primary is not None and is_entity_contact(primary.first_name, primary.last_name):
            entity_contact = primary
        else:
            # Re-resolve after a person was already promoted: find linked LLC contact
            # or fall back to linked owner Organization name.
            entity_contact = self._find_entity_contact(lead_id)
            if entity_contact is None:
                linked_org = self._get_linked_owner_org(lead_id)
                if linked_org is not None and is_entity_name(linked_org.name or ""):
                    entity_name = linked_org.name
                else:
                    if primary is None:
                        return EntityResolutionResult(
                            lead_id=lead_id,
                            status="skipped",
                            message="No primary contact on property",
                            dry_run=dry_run,
                        )
                    return EntityResolutionResult(
                        lead_id=lead_id,
                        status="skipped",
                        message="Primary contact is not an entity/LLC name",
                        dry_run=dry_run,
                    )

        if entity_contact is not None:
            entity_name = contact_display_name(
                entity_contact.first_name, entity_contact.last_name,
            )

        if not self._lead_looks_illinois(lead):
            if dry_run:
                return EntityResolutionResult(
                    lead_id=lead_id,
                    status="unsupported_jurisdiction",
                    entity_name=entity_name,
                    message=(
                        "Non-Illinois property/mailing state — entity lookup "
                        "not supported yet"
                    ),
                    dry_run=True,
                )
            org = self._upsert_organization(
                entity_name,
                status="unsupported_jurisdiction",
                error=(
                    "Jurisdiction not supported yet (Illinois only). "
                    f"property_state={lead.property_state!r} "
                    f"mailing_state={lead.mailing_state!r}"
                ),
                provider_name=None,
            )
            self._ensure_property_org_link(lead_id, org.id)
            db.session.commit()
            return EntityResolutionResult(
                lead_id=lead_id,
                status="unsupported_jurisdiction",
                entity_name=entity_name,
                organization_id=org.id,
                message="Non-Illinois jurisdiction — not supported yet",
            )

        provider = self._get_provider()
        if not provider.is_configured() and not dry_run:
            raise EntityLookupProviderNotConfiguredError(
                "Illinois SOS bulk data not loaded. "
                "Run: python scripts/import_il_sos_llc_bulk.py --apply"
            )

        if dry_run:
            if not provider.is_configured():
                return EntityResolutionResult(
                    lead_id=lead_id,
                    status="pending",
                    entity_name=entity_name,
                    message=(
                        "Would resolve Illinois LLC after loading free SOS bulk data "
                        "(python scripts/import_il_sos_llc_bulk.py --apply)"
                    ),
                    dry_run=True,
                )
            result = provider.lookup_llc(entity_name, jurisdiction=SUPPORTED_JURISDICTION)
            return self._result_from_lookup_preview(lead_id, entity_name, result)

        try:
            lookup = provider.lookup_llc(entity_name, jurisdiction=SUPPORTED_JURISDICTION)
        except EntityLookupProviderNotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001 — persist as error status
            logger.exception("Entity lookup failed for lead %s", lead_id)
            org = self._upsert_organization(
                entity_name,
                status="error",
                error=str(exc),
                provider_name=getattr(provider, "name", None),
            )
            self._ensure_property_org_link(lead_id, org.id)
            db.session.commit()
            return EntityResolutionResult(
                lead_id=lead_id,
                status="error",
                entity_name=entity_name,
                organization_id=org.id,
                message=str(exc),
            )

        return self._apply_lookup(
            lead=lead,
            entity_name=entity_name,
            lookup=lookup,
            actor=actor,
        )

    # ------------------------------------------------------------------
    # Apply lookup
    # ------------------------------------------------------------------

    def _apply_lookup(
        self,
        *,
        lead: Lead,
        entity_name: str,
        lookup: EntityLookupResult,
        actor: str,
    ) -> EntityResolutionResult:
        lead_id = lead.id
        provider_name = lookup.provider_name or getattr(self._get_provider(), "name", None)

        if lookup.unsupported_jurisdiction:
            org = self._upsert_organization(
                entity_name,
                status="unsupported_jurisdiction",
                error=lookup.error or "Unsupported jurisdiction",
                provider_name=provider_name,
                jurisdiction=lookup.jurisdiction,
                file_number=lookup.file_number,
                registered_agent_name=lookup.registered_agent_name,
                registered_office_address=lookup.registered_office_address,
                org_status=lookup.status,
            )
            self._replace_parties(org, lookup.parties, provider_name)
            self._ensure_property_org_link(lead_id, org.id)
            db.session.commit()
            return EntityResolutionResult(
                lead_id=lead_id,
                status="unsupported_jurisdiction",
                entity_name=entity_name,
                organization_id=org.id,
                message=lookup.error or "Unsupported jurisdiction",
            )

        if not lookup.found:
            org = self._upsert_organization(
                entity_name,
                status="no_match",
                error=lookup.error or "No matching entity",
                provider_name=provider_name,
                jurisdiction=SUPPORTED_JURISDICTION,
            )
            self._ensure_property_org_link(lead_id, org.id)
            db.session.commit()
            return EntityResolutionResult(
                lead_id=lead_id,
                status="no_match",
                entity_name=entity_name,
                organization_id=org.id,
                message=lookup.error or "No matching Illinois entity found",
            )

        person = self._select_person_party(lookup.parties)
        org = self._upsert_organization(
            lookup.name or entity_name,
            status="resolved",
            error=None if person else "Resolved entity but no natural person party found",
            provider_name=provider_name,
            jurisdiction=lookup.jurisdiction or SUPPORTED_JURISDICTION,
            file_number=lookup.file_number,
            registered_agent_name=lookup.registered_agent_name,
            registered_office_address=lookup.registered_office_address,
            org_status=lookup.status,
            person_found=person is not None,
        )
        self._replace_parties(org, lookup.parties, provider_name)
        self._ensure_property_org_link(lead_id, org.id)

        person_contact_id = None
        person_name = None
        skip_task_id = None

        if person is not None:
            contact, _link = self._contacts._upsert_named_owner(  # noqa: SLF001
                lead_id,
                person.first_name,
                person.last_name or person.full_name,
                is_primary=True,
            )
            # Annotate source on notes if empty
            if not (contact.notes or "").strip():
                contact.notes = (
                    f"Resolved from Illinois entity lookup "
                    f"({provider_name}) as {person.party_type}"
                )
            person_contact_id = contact.id
            person_name = contact_display_name(contact.first_name, contact.last_name)
            db.session.flush()

            task = self._skip_trace.enqueue(
                lead_id,
                person_contact_id,
                actor=actor,
                reason=f"Skip trace manager from {entity_name}",
            )
            skip_task_id = task.id if task else None
        else:
            db.session.commit()

        # SkipTraceEnqueue / ContactService may have committed; ensure flush done
        if person is not None:
            db.session.commit()

        return EntityResolutionResult(
            lead_id=lead_id,
            status="resolved",
            entity_name=entity_name,
            organization_id=org.id,
            person_contact_id=person_contact_id,
            person_found=person is not None,
            person_name=person_name,
            skip_trace_task_id=skip_task_id,
            message=(
                None if person is not None
                else "Entity resolved but no natural person (manager/member) found"
            ),
        )

    def _result_from_lookup_preview(
        self,
        lead_id: int,
        entity_name: str,
        lookup: EntityLookupResult,
    ) -> EntityResolutionResult:
        if lookup.unsupported_jurisdiction:
            return EntityResolutionResult(
                lead_id=lead_id,
                status="unsupported_jurisdiction",
                entity_name=entity_name,
                message=lookup.error,
                dry_run=True,
            )
        if not lookup.found:
            return EntityResolutionResult(
                lead_id=lead_id,
                status="no_match",
                entity_name=entity_name,
                message=lookup.error,
                dry_run=True,
            )
        person = self._select_person_party(lookup.parties)
        return EntityResolutionResult(
            lead_id=lead_id,
            status="resolved",
            entity_name=entity_name,
            person_found=person is not None,
            person_name=person.full_name if person else None,
            message="Dry-run preview only — no DB writes",
            dry_run=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_primary_contact(self, lead_id: int) -> Optional[Contact]:
        row = (
            db.session.query(Contact)
            .join(PropertyContact, PropertyContact.contact_id == Contact.id)
            .filter(
                PropertyContact.property_id == lead_id,
                PropertyContact.is_primary.is_(True),
            )
            .first()
        )
        return row

    def _find_entity_contact(self, lead_id: int) -> Optional[Contact]:
        """Return any linked contact whose name is entity-shaped (LLC, etc.)."""
        rows = (
            db.session.query(Contact)
            .join(PropertyContact, PropertyContact.contact_id == Contact.id)
            .filter(PropertyContact.property_id == lead_id)
            .all()
        )
        for contact in rows:
            if is_entity_contact(contact.first_name, contact.last_name):
                return contact
        return None

    def _get_linked_owner_org(self, lead_id: int) -> Optional[Organization]:
        return (
            db.session.query(Organization)
            .join(
                PropertyOrganizationLink,
                PropertyOrganizationLink.organization_id == Organization.id,
            )
            .filter(
                PropertyOrganizationLink.property_id == lead_id,
                PropertyOrganizationLink.role == "owner",
            )
            .order_by(Organization.id.desc())
            .first()
        )

    @staticmethod
    def _normalize_state(value: Optional[str]) -> str:
        return re.sub(r"[^A-Z]", "", (value or "").upper())

    def _lead_looks_illinois(self, lead: Lead) -> bool:
        """True when we should attempt an Illinois entity lookup.

        Non-IL property or mailing state → unsupported.
        Missing state fields → assume IL (portfolio is Illinois-first).
        """
        prop = self._normalize_state(getattr(lead, "property_state", None))
        mail = self._normalize_state(getattr(lead, "mailing_state", None))
        states = [s for s in (prop, mail) if s]
        if not states:
            return True
        # If any known state is IL, allow; if all known states are non-IL, reject.
        return any(s in _IL_STATE_CODES or s == "IL" for s in states)

    def _upsert_organization(
        self,
        name: str,
        *,
        status: str,
        error: Optional[str],
        provider_name: Optional[str],
        jurisdiction: Optional[str] = SUPPORTED_JURISDICTION,
        file_number: Optional[str] = None,
        registered_agent_name: Optional[str] = None,
        registered_office_address: Optional[str] = None,
        org_status: Optional[str] = None,
        person_found: bool = False,
    ) -> Organization:
        cleaned = " ".join((name or "").split())
        self._serialize_organization_upsert(cleaned)
        # Case-insensitive equality — never ilike(cleaned), which treats %/_ as wildcards.
        org = (
            Organization.query
            .filter(func.lower(Organization.name) == cleaned.lower())
            .order_by(Organization.id.asc())
            .first()
        )
        if org is None:
            org = Organization(
                name=cleaned,
                org_type="llc" if is_entity_name(cleaned) else "unknown",
                status="unknown",
                source="entity_resolution",
            )
            db.session.add(org)
            db.session.flush()

        if org_status in ("active", "inactive", "unknown"):
            org.status = org_status
        org.jurisdiction = jurisdiction
        if file_number:
            org.file_number = file_number
        if registered_agent_name:
            org.registered_agent_name = registered_agent_name
        if registered_office_address:
            org.registered_office_address = registered_office_address
        org.entity_lookup_status = status
        org.entity_lookup_provider = provider_name
        org.entity_lookup_checked_at = datetime.utcnow()
        org.entity_lookup_error = error
        org.entity_lookup_person_found = person_found
        if not org.source:
            org.source = "entity_resolution"
        db.session.flush()
        return org

    @staticmethod
    def _serialize_organization_upsert(cleaned_name: str) -> None:
        """Serialize concurrent PostgreSQL get-or-create attempts for one name."""
        bind = db.session.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return
        db.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"entity_resolution_org:{cleaned_name.lower()}"},
        )

    def _ensure_property_org_link(self, lead_id: int, org_id: int) -> None:
        existing = (
            PropertyOrganizationLink.query
            .filter_by(property_id=lead_id, organization_id=org_id, role="owner")
            .first()
        )
        if existing is None:
            db.session.add(PropertyOrganizationLink(
                property_id=lead_id,
                organization_id=org_id,
                role="owner",
            ))
            db.session.flush()

    def _replace_parties(
        self,
        org: Organization,
        parties: list[EntityPartyResult],
        provider_name: Optional[str],
    ) -> None:
        OrganizationParty.query.filter_by(organization_id=org.id).delete()
        for party in parties:
            db.session.add(OrganizationParty(
                organization_id=org.id,
                full_name=party.full_name,
                first_name=party.first_name,
                last_name=party.last_name,
                party_type=party.party_type,
                is_company=bool(party.is_company),
                address=party.address,
                city=party.city,
                state=party.state,
                zip=party.zip,
                source=provider_name,
                external_id=party.external_id,
            ))
        db.session.flush()

    @staticmethod
    def _select_person_party(
        parties: list[EntityPartyResult],
    ) -> Optional[EntityPartyResult]:
        """Prefer non-company manager/member/officer; never promote corporate RA."""
        for party_type in _PERSON_PARTY_PRIORITY:
            for party in parties:
                if party.party_type != party_type:
                    continue
                if party.is_company or is_entity_name(party.full_name):
                    continue
                if not (party.full_name or "").strip():
                    continue
                return party
        # Fallback: any non-company non-RA party
        for party in parties:
            if party.party_type == "registered_agent":
                continue
            if party.is_company or is_entity_name(party.full_name):
                continue
            if (party.full_name or "").strip():
                return party
        return None
