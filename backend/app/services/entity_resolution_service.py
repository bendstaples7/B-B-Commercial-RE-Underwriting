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
from app.services.entity_lookup.irs_eo import (
    IrsEoNonprofitProvider,
    NonprofitLookupResult,
)
from app.services.plugins.owner_name_utils import (
    contact_display_name,
    is_definite_institutional_name,
    is_entity_contact,
    is_entity_name,
    is_institutional_name,
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
    "IRS EO BMF research confirms tax-exempt orgs before LLC person resolution.",
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
        nonprofit_provider: Optional[IrsEoNonprofitProvider] = None,
        contact_service: Optional[ContactService] = None,
        skip_trace: Optional[SkipTraceEnqueue] = None,
    ) -> None:
        self._provider = provider
        self._nonprofit_provider = nonprofit_provider
        self._contacts = contact_service or ContactService()
        self._skip_trace = skip_trace or SkipTraceEnqueue()

    def _get_provider(self) -> EntityLookupProvider:
        if self._provider is not None:
            return self._provider
        return get_entity_lookup_provider()

    def _get_nonprofit_provider(self) -> IrsEoNonprofitProvider:
        if self._nonprofit_provider is not None:
            return self._nonprofit_provider
        return IrsEoNonprofitProvider()

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
        primary_is_entity = False
        if primary is not None:
            primary_is_entity = is_entity_contact(primary.first_name, primary.last_name)

        entity_name = self._resolve_entity_name(lead_id, primary=primary)
        org = self._get_linked_owner_org(lead_id)
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

        nonprofit_provider = self._get_nonprofit_provider()
        nonprofit_configured = False
        nonprofit_dataset_imported_at = None
        try:
            nonprofit_configured = bool(nonprofit_provider.is_configured())
            nonprofit_dataset_imported_at = nonprofit_provider.dataset_imported_at()
        except Exception:  # noqa: BLE001
            nonprofit_configured = False

        is_institutional = bool(
            entity_name and is_institutional_name(entity_name)
        )
        is_definite_institutional = bool(
            entity_name and is_definite_institutional_name(entity_name)
        )
        org_is_nonprofit = bool(org and (org.org_type or "") == "nonprofit")
        can_mark_nonprofit = bool(entity_name) and not org_is_nonprofit
        can_research = bool(
            entity_name and jurisdiction_ok and nonprofit_configured and not org_is_nonprofit
        )
        resolved_person_name, resolved_person_role = self.resolved_person_for_org(org)

        return {
            "lead_id": lead_id,
            "primary_is_entity": primary_is_entity,
            "entity_name": entity_name,
            "is_institutional": is_institutional,
            "is_definite_institutional": is_definite_institutional,
            "jurisdiction_supported": jurisdiction_ok,
            "supported_jurisdiction": SUPPORTED_JURISDICTION,
            "organization_id": org.id if org else None,
            "organization_name": org.name if org else None,
            "organization_org_type": org.org_type if org else None,
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
            "registered_office_address": (
                org.registered_office_address if org else None
            ),
            "registered_agent_name": (
                org.registered_agent_name if org else None
            ),
            "file_number": org.file_number if org else None,
            "resolved_person_name": resolved_person_name,
            "resolved_person_role": resolved_person_role,
            "provider": provider_name,
            "provider_configured": provider_configured,
            "dataset_imported_at": dataset_imported_at,
            "nonprofit_provider": nonprofit_provider.name,
            "nonprofit_provider_configured": nonprofit_configured,
            "nonprofit_dataset_imported_at": nonprofit_dataset_imported_at,
            "is_nonprofit": org_is_nonprofit,
            "can_mark_nonprofit": can_mark_nonprofit,
            "can_research": can_research,
            "limitations": list(FREE_BULK_LIMITATIONS),
            "can_resolve": bool(
                entity_name
                and jurisdiction_ok
                and provider_configured
                and not org_is_nonprofit
                and not is_definite_institutional
            ),
        }

    @staticmethod
    def resolved_person_for_org(
        org: Optional[Organization],
    ) -> tuple[Optional[str], Optional[str]]:
        """Return (display_name, party_type) for the best natural-person party."""
        if org is None:
            return None, None
        parties = (
            OrganizationParty.query
            .filter_by(organization_id=org.id, is_company=False)
            .all()
        )
        for party_type in _PERSON_PARTY_PRIORITY:
            for party in parties:
                if party.party_type != party_type:
                    continue
                name = contact_display_name(party.first_name, party.last_name).strip()
                if not name:
                    # SOS often stores "LAST, FIRST" in full_name
                    raw = (party.full_name or "").strip()
                    if "," in raw:
                        last, _, first = raw.partition(",")
                        name = contact_display_name(first.strip(), last.strip()).strip() or raw
                    else:
                        name = raw
                if name:
                    return name, party_type
        return None, None

    @staticmethod
    def owner_org_needs_research(org: Optional[Organization]) -> bool:
        """True when a linked owner org has never been successfully researched."""
        if org is None:
            return False
        status = (org.entity_lookup_status or "").strip()
        if not status:
            return True
        return status in ("pending", "error")

    def ensure_researched(
        self,
        lead_id: int,
        *,
        actor: str = "owner_import",
        sync: bool = False,
    ) -> dict:
        """Queue (or sync-run) entity resolution when an owner org still needs research.

        Never raises for missing SOS data — marks ``pending`` and returns so
        imports / company promotion stay non-blocking.
        """
        org = self._get_linked_owner_org(lead_id)
        if org is None:
            return {
                "queued": False,
                "skipped": True,
                "reason": "no_owner_org",
            }
        if not self.owner_org_needs_research(org):
            return {
                "queued": False,
                "skipped": True,
                "reason": "already_researched",
                "organization_id": org.id,
                "entity_lookup_status": org.entity_lookup_status,
            }

        entity_name = self._resolve_entity_name(lead_id)
        if not entity_name:
            return {
                "queued": False,
                "skipped": True,
                "reason": "no_entity_name",
                "organization_id": org.id if org else None,
            }

        if not sync:
            try:
                from celery_worker import entity_resolution_resolve_lead_task
                entity_resolution_resolve_lead_task.apply_async(
                    args=[lead_id],
                    kwargs={"actor": actor},
                )
                logger.info(
                    "Queued entity resolution for lead_id=%s actor=%s",
                    lead_id, actor,
                )
                return {
                    "queued": True,
                    "skipped": False,
                    "organization_id": org.id if org else None,
                    "entity_name": entity_name,
                }
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "Celery unavailable for entity resolution lead %s: %s — running sync",
                    lead_id, exc,
                )

        try:
            result = self.resolve_lead(lead_id, actor=actor)
            return {
                "queued": False,
                "skipped": False,
                "sync": True,
                "status": result.status,
                "organization_id": result.organization_id,
                "entity_name": result.entity_name,
            }
        except EntityLookupProviderNotConfiguredError as exc:
            if org is not None:
                org.entity_lookup_status = "pending"
                org.entity_lookup_error = str(exc)
                org.entity_lookup_checked_at = None
                db.session.commit()
            logger.warning(
                "Entity resolution pending for lead_id=%s — SOS data not loaded: %s",
                lead_id, exc,
            )
            return {
                "queued": False,
                "skipped": False,
                "pending": True,
                "organization_id": org.id if org else None,
                "message": str(exc),
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
        entity_name = self._resolve_entity_name(lead_id, primary=primary)
        if not entity_name:
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

        # High-confidence institutional names → nonprofit; soft markers still
        # go through IRS research then LLC resolve.
        if is_definite_institutional_name(entity_name or ""):
            return self._mark_nonprofit_result(
                lead_id=lead_id,
                entity_name=entity_name,
                reason="institutional_name",
                dry_run=dry_run,
                actor=actor,
            )

        # Ambiguous Inc/Corp: research IRS EO before LLC manager lookup.
        nonprofit_hit = self._research_nonprofit(
            entity_name or "",
            state=self._preferred_state(lead),
        )
        if nonprofit_hit.found:
            return self._mark_nonprofit_result(
                lead_id=lead_id,
                entity_name=nonprofit_hit.name or entity_name,
                reason="irs_eo_match",
                dry_run=dry_run,
                actor=actor,
                ein=nonprofit_hit.ein,
                provider_name=nonprofit_hit.provider_name,
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

    def mark_as_nonprofit(
        self,
        lead_id: int,
        *,
        actor: str = "entity_resolution",
        dry_run: bool = False,
    ) -> EntityResolutionResult:
        """Manually confirm an entity owner is a nonprofit (deprioritize mail)."""
        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ResourceNotFoundError(
                f"Lead id={lead_id} not found.",
                payload={"lead_id": lead_id},
            )
        entity_name = self._resolve_entity_name(lead_id)
        if not entity_name:
            return EntityResolutionResult(
                lead_id=lead_id,
                status="skipped",
                message="No entity-shaped owner name to mark as nonprofit",
                dry_run=dry_run,
            )
        return self._mark_nonprofit_result(
            lead_id=lead_id,
            entity_name=entity_name,
            reason="manual_confirm",
            dry_run=dry_run,
            actor=actor,
        )

    def research_nonprofit(
        self,
        lead_id: int,
        *,
        actor: str = "entity_resolution",
        dry_run: bool = False,
    ) -> EntityResolutionResult:
        """IRS EO research only — does not fall through to LLC resolution."""
        lead = Lead.query.get(lead_id)
        if lead is None:
            raise ResourceNotFoundError(
                f"Lead id={lead_id} not found.",
                payload={"lead_id": lead_id},
            )
        entity_name = self._resolve_entity_name(lead_id)
        if not entity_name:
            return EntityResolutionResult(
                lead_id=lead_id,
                status="skipped",
                message="No entity-shaped owner name to research",
                dry_run=dry_run,
            )
        if is_definite_institutional_name(entity_name):
            return self._mark_nonprofit_result(
                lead_id=lead_id,
                entity_name=entity_name,
                reason="institutional_name",
                dry_run=dry_run,
                actor=actor,
            )
        hit = self._research_nonprofit(
            entity_name,
            state=self._preferred_state(lead),
        )
        if hit.found:
            return self._mark_nonprofit_result(
                lead_id=lead_id,
                entity_name=hit.name or entity_name,
                reason="irs_eo_match",
                dry_run=dry_run,
                actor=actor,
                ein=hit.ein,
                provider_name=hit.provider_name,
            )
        if dry_run:
            return EntityResolutionResult(
                lead_id=lead_id,
                status="no_match",
                entity_name=entity_name,
                message=hit.error or "No IRS EO match — treat as for-profit entity",
                dry_run=True,
            )

        # Do not demote nonprofit or clobber a successful LLC person resolve.
        existing = self._get_linked_owner_org(lead_id)
        if existing is not None and (
            (existing.org_type or "") == "nonprofit"
            or bool(existing.entity_lookup_person_found)
            or (existing.entity_lookup_status or "") == "resolved"
        ):
            return EntityResolutionResult(
                lead_id=lead_id,
                status="no_match",
                entity_name=entity_name,
                organization_id=existing.id,
                message=hit.error or (
                    "No IRS EO match — existing organization resolution left unchanged"
                ),
            )

        org = self._upsert_organization(
            entity_name,
            status="no_match",
            error=hit.error or "No IRS EO nonprofit match",
            provider_name=hit.provider_name,
            # Leave org_type unchanged on research no-match.
            org_type=None,
        )
        self._ensure_property_org_link(lead_id, org.id)
        db.session.commit()
        return EntityResolutionResult(
            lead_id=lead_id,
            status="no_match",
            entity_name=entity_name,
            organization_id=org.id,
            message=hit.error or "No IRS EO match — use Resolve Illinois LLC for person lookup",
        )

    def _resolve_entity_name(
        self,
        lead_id: int,
        *,
        primary: Optional[Contact] = None,
    ) -> Optional[str]:
        if primary is None:
            primary = self._get_primary_contact(lead_id)
        if primary is not None and is_entity_contact(primary.first_name, primary.last_name):
            return contact_display_name(primary.first_name, primary.last_name)
        entity_contact = self._find_entity_contact(lead_id)
        if entity_contact is not None:
            return contact_display_name(
                entity_contact.first_name, entity_contact.last_name,
            )
        org = self._get_linked_owner_org(lead_id)
        if org is not None and is_entity_name(org.name or ""):
            return org.name
        return None

    def _preferred_state(self, lead: Lead) -> str:
        """State for IRS EO lookup — prefer property state; IL wins if either is IL."""
        prop = self._normalize_state(getattr(lead, "property_state", None))
        mail = self._normalize_state(getattr(lead, "mailing_state", None))
        for code in (prop, mail):
            if code in _IL_STATE_CODES or code == "IL":
                return "IL"
        if len(prop) == 2:
            return prop
        if len(mail) == 2:
            return mail
        return "IL"

    def _research_nonprofit(
        self,
        entity_name: str,
        *,
        state: str = "IL",
    ) -> NonprofitLookupResult:
        provider = self._get_nonprofit_provider()
        if not provider.is_configured():
            return NonprofitLookupResult(
                found=False,
                error="IRS EO BMF data not loaded",
                provider_name=provider.name,
            )
        return provider.lookup_nonprofit(entity_name, state=state)

    def _mark_nonprofit_result(
        self,
        *,
        lead_id: int,
        entity_name: Optional[str],
        reason: str,
        dry_run: bool,
        actor: str,
        ein: Optional[str] = None,
        provider_name: Optional[str] = None,
    ) -> EntityResolutionResult:
        message = {
            "institutional_name": "Institutional / nonprofit name — deprioritize cold mail",
            "irs_eo_match": (
                f"IRS EO match (EIN {ein}) — marked nonprofit, skip LLC person resolve"
                if ein else "IRS EO match — marked nonprofit, skip LLC person resolve"
            ),
            "manual_confirm": "Manually confirmed nonprofit — deprioritize cold mail",
        }.get(reason, "Marked nonprofit — deprioritize cold mail")

        if dry_run:
            return EntityResolutionResult(
                lead_id=lead_id,
                status="nonprofit",
                entity_name=entity_name,
                message=message,
                dry_run=True,
            )

        org = self._upsert_organization(
            entity_name or "Unknown organization",
            status="resolved",
            error=None,
            provider_name=provider_name or reason,
            org_type="nonprofit",
            org_status="active",
            person_found=False,
        )
        if ein and not org.file_number:
            org.file_number = ein
        self._ensure_property_org_link(lead_id, org.id)
        db.session.commit()

        try:
            from app.services.lead_refresh import refresh_lead_scoring
            refresh_lead_scoring(lead_id)
        except Exception:  # noqa: BLE001 — scoring refresh is best-effort
            logger.exception(
                "refresh_lead_scoring failed after nonprofit mark lead=%s", lead_id,
            )

        return EntityResolutionResult(
            lead_id=lead_id,
            status="nonprofit",
            entity_name=entity_name,
            organization_id=org.id,
            person_found=False,
            message=message,
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
            # LLC lives on Organization now — drop the entity-shaped Contact link.
            from app.services.helpers.owner_organization import (
                unlink_matching_entity_property_contact,
            )
            unlink_matching_entity_property_contact(
                lead_id,
                lookup.name or entity_name,
            )
            # Collapse Joseph / JOSEPH A style duplicates created by import + SOS.
            self._contacts.unlink_duplicate_person_owners(lead_id)
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
                PropertyContact.role == "owner",
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
            .filter(
                PropertyContact.property_id == lead_id,
                PropertyContact.role == "owner",
            )
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
        org_type: Optional[str] = None,
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
            if is_definite_institutional_name(cleaned):
                default_type = "nonprofit"
            elif is_entity_name(cleaned):
                default_type = "llc"
            else:
                default_type = "unknown"
            org = Organization(
                name=cleaned,
                org_type=org_type or default_type,
                status="unknown",
                source="entity_resolution",
            )
            db.session.add(org)
            db.session.flush()
        elif org_type:
            # Never demote a confirmed nonprofit without an explicit nonprofit write.
            if (org.org_type or "") == "nonprofit" and org_type != "nonprofit":
                pass
            else:
                org.org_type = org_type

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
