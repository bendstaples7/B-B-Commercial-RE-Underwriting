"""Owner-type policy for cold-mail deprioritization.

Canonical helper used by LeadScoringEngine and mail candidate queues.
Does not write lead_score / recommended_action — callers apply the reason.
"""
from __future__ import annotations

from typing import Optional

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
            PropertyContact.is_primary.is_(True),
        )
        .first()
    )


def _linked_owner_org(lead_id: int) -> Optional[Organization]:
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


def _has_natural_person_primary(primary: Optional[Contact]) -> bool:
    if primary is None:
        return False
    if is_entity_contact(primary.first_name, primary.last_name):
        return False
    return bool(contact_display_name(primary.first_name, primary.last_name))


def cold_mail_block_reason(lead: Lead) -> Optional[str]:
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

    lead_id = getattr(lead, "id", None)
    primary: Optional[Contact] = None
    org: Optional[Organization] = None
    if isinstance(lead_id, int):
        try:
            primary = _primary_contact(lead_id)
            org = _linked_owner_org(lead_id)
        except Exception:  # noqa: BLE001 — scoring unit tests may use MagicMock
            primary = None
            org = None

    if org is not None and (org.org_type or "") == "nonprofit":
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

    if entity_shaped and not _has_natural_person_primary(primary):
        return "unresolved_entity_owner"

    return None


def is_cold_mail_blocked(lead: Lead) -> bool:
    """True when cold mail should be deprioritized for this owner."""
    return cold_mail_block_reason(lead) is not None
