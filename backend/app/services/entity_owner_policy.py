"""Owner-type policy for cold-mail deprioritization.

Canonical helper used by LeadScoringEngine and mail candidate queues.
Does not write lead_score / recommended_action — callers apply the reason.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from app import db
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.organization import Organization
from app.models.property_contact import PropertyContact
from app.models.property_organization_link import PropertyOrganizationLink
from app.services.plugins.owner_name_utils import (
    contact_display_name,
    is_entity_contact,
    is_entity_name,
    is_institutional_contact,
    is_institutional_name,
)


def _primary_contact(lead_id: int) -> Optional[Contact]:
    return (
        db.session.query(Contact)
        .join(PropertyContact, PropertyContact.contact_id == Contact.id)
        .filter(
            PropertyContact.property_id == lead_id,
            PropertyContact.role == "owner",
            PropertyContact.is_primary.is_(True),
        )
        .first()
    )


def _owner_organizations(lead_id: int) -> list[Organization]:
    return list(
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
        .all()
    )


def _safe_name_part(value) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _owner_display_name(lead: Lead, primary: Optional[Contact]) -> str:
    if primary is not None:
        name = contact_display_name(primary.first_name, primary.last_name)
        if name:
            return name
    return contact_display_name(
        _safe_name_part(getattr(lead, "owner_first_name", None)) or None,
        _safe_name_part(getattr(lead, "owner_last_name", None)) or None,
    )


def _org_name_is_entity(org: Organization) -> bool:
    return is_entity_name(org.name or "")


def _has_natural_person_primary(primary: Optional[Contact]) -> bool:
    if primary is None:
        return False
    if is_entity_contact(primary.first_name, primary.last_name):
        return False
    return bool(contact_display_name(primary.first_name, primary.last_name))


def _cold_mail_block_reason_with_context(
    lead: Lead,
    primary: Optional[Contact],
    owner_orgs: Iterable[Organization],
) -> Optional[str]:
    """Return a reason code when this lead should not be cold-mailed, else None.

    Reasons:
      - institutional_owner: clear institution / nonprofit name markers
      - nonprofit_organization: linked org_type == nonprofit
      - tax_exempt_owner: parcel ownership_type tax_exempt
      - unresolved_entity_owner: entity primary with no natural-person primary
    """
    ownership = (getattr(lead, "ownership_type", None) or "").strip().lower()
    if ownership == "tax_exempt":
        return "tax_exempt_owner"

    permit = getattr(lead, "permit_data", None) or {}
    if isinstance(permit, dict) and permit.get("tax_exempt"):
        return "tax_exempt_owner"

    owner_orgs = list(owner_orgs)
    if any((org.org_type or "") == "nonprofit" for org in owner_orgs):
        return "nonprofit_organization"

    display = _owner_display_name(lead, primary)
    if display and is_institutional_name(display):
        return "institutional_owner"
    if primary is not None and is_institutional_contact(
        primary.first_name, primary.last_name,
    ):
        return "institutional_owner"

    # Resolve-first: entity-shaped owner without a person primary.
    entity_shaped = False
    if primary is not None and is_entity_contact(primary.first_name, primary.last_name):
        entity_shaped = True
    elif display and is_entity_name(display) and not _has_natural_person_primary(primary):
        entity_shaped = True
    elif any(_org_name_is_entity(org) for org in owner_orgs):
        entity_shaped = True

    if entity_shaped and not _has_natural_person_primary(primary):
        return "unresolved_entity_owner"

    return None


def cold_mail_block_reason(lead: Lead) -> Optional[str]:
    """Return a reason code when this lead should not be cold-mailed, else None."""
    lead_id = getattr(lead, "id", None)
    primary: Optional[Contact] = None
    orgs: list[Organization] = []
    if isinstance(lead_id, int):
        try:
            primary = _primary_contact(lead_id)
            orgs = _owner_organizations(lead_id)
        except Exception:  # noqa: BLE001 — scoring unit tests may use MagicMock
            primary = None
            orgs = []
    return _cold_mail_block_reason_with_context(lead, primary, orgs)


def cold_mail_block_reasons_for_leads(leads: Iterable[Lead]) -> dict[int, str]:
    """Batch owner-policy classification for queue filters."""
    lead_list = [
        lead for lead in leads
        if isinstance(getattr(lead, "id", None), int)
    ]
    lead_ids = [lead.id for lead in lead_list]
    if not lead_ids:
        return {}

    primary_by_lead: dict[int, Contact] = {}
    orgs_by_lead: dict[int, list[Organization]] = defaultdict(list)

    contact_rows = (
        db.session.query(PropertyContact.property_id, Contact)
        .join(Contact, PropertyContact.contact_id == Contact.id)
        .filter(
            PropertyContact.property_id.in_(lead_ids),
            PropertyContact.role == "owner",
            PropertyContact.is_primary.is_(True),
        )
        .order_by(PropertyContact.id.asc())
        .all()
    )
    for lead_id, contact in contact_rows:
        primary_by_lead.setdefault(lead_id, contact)

    org_rows = (
        db.session.query(PropertyOrganizationLink.property_id, Organization)
        .join(
            Organization,
            PropertyOrganizationLink.organization_id == Organization.id,
        )
        .filter(
            PropertyOrganizationLink.property_id.in_(lead_ids),
            PropertyOrganizationLink.role == "owner",
        )
        .order_by(Organization.id.desc())
        .all()
    )
    for lead_id, org in org_rows:
        orgs_by_lead[lead_id].append(org)

    reasons: dict[int, str] = {}
    for lead in lead_list:
        reason = _cold_mail_block_reason_with_context(
            lead,
            primary_by_lead.get(lead.id),
            orgs_by_lead.get(lead.id, []),
        )
        if reason is not None:
            reasons[lead.id] = reason
    return reasons


def is_cold_mail_blocked(lead: Lead) -> bool:
    """True when cold mail should be deprioritized for this owner."""
    return cold_mail_block_reason(lead) is not None
