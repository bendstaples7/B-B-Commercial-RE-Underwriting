"""Promote entity-shaped owners to Organization + property link (no Contact)."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func

from app import db
from app.models.contact import Contact
from app.models.organization import Organization
from app.models.property_contact import PropertyContact
from app.models.property_organization_link import PropertyOrganizationLink
from app.services.plugins.owner_name_utils import (
    contact_display_name,
    is_address_like_contact,
    is_definite_institutional_name,
    is_entity_contact,
    is_entity_name,
    is_property_management_name,
)

logger = logging.getLogger(__name__)


def ensure_owner_organization(
    property_id: int,
    name: str,
    *,
    source: str = "owner_import",
    org_type: Optional[str] = None,
) -> Organization:
    """Get-or-create Organization by name and link as property owner.

    Does not commit — caller controls the transaction.
    """
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ValueError("Organization name is required")

    org = (
        Organization.query
        .filter(func.lower(Organization.name) == cleaned.lower())
        .order_by(Organization.id.asc())
        .first()
    )
    if org is None:
        if org_type:
            resolved_type = org_type
        elif is_definite_institutional_name(cleaned):
            resolved_type = "nonprofit"
        elif is_property_management_name(cleaned):
            resolved_type = "property_management"
        elif is_entity_name(cleaned):
            resolved_type = "llc"
        else:
            resolved_type = "unknown"
        org = Organization(
            name=cleaned,
            org_type=resolved_type,
            status="unknown",
            source=source,
        )
        db.session.add(org)
        db.session.flush()
    elif not org.source:
        org.source = source

    existing = (
        PropertyOrganizationLink.query
        .filter_by(property_id=property_id, organization_id=org.id, role="owner")
        .first()
    )
    if existing is None:
        db.session.add(PropertyOrganizationLink(
            property_id=property_id,
            organization_id=org.id,
            role="owner",
        ))
        db.session.flush()
        logger.info(
            "Linked org_id=%d name=%r as owner on property_id=%d",
            org.id, org.name, property_id,
        )
    return org


def unlink_matching_entity_property_contact(
    property_id: int,
    org_name: str,
) -> int:
    """Remove PropertyContact links whose display name matches *org_name*.

    Leaves the Contact row intact (may be used elsewhere). Returns unlink count.
    """
    target = " ".join((org_name or "").split()).lower()
    if not target:
        return 0

    rows = (
        db.session.query(Contact, PropertyContact)
        .join(PropertyContact, PropertyContact.contact_id == Contact.id)
        .filter(PropertyContact.property_id == property_id)
        .all()
    )
    removed = 0
    for contact, link in rows:
        display = contact_display_name(contact.first_name, contact.last_name).lower()
        if display != target:
            continue
        if not is_entity_contact(contact.first_name, contact.last_name):
            continue
        if is_address_like_contact(contact.first_name, contact.last_name):
            continue
        db.session.delete(link)
        removed += 1
    if removed:
        db.session.flush()
    return removed


def promote_named_owner_to_organization(
    property_id: int,
    first_name: str | None,
    last_name: str | None,
    *,
    source: str = "owner_import",
    unlink_contact: bool = False,
) -> Organization | None:
    """If name is entity-shaped (and not address-like), ensure Organization link.

    Returns the Organization when promoted, else None (caller should use Contact).
    """
    if is_address_like_contact(first_name, last_name):
        return None
    if not is_entity_contact(first_name, last_name):
        return None
    display = contact_display_name(first_name, last_name)
    org = ensure_owner_organization(property_id, display, source=source)
    if unlink_contact:
        unlink_matching_entity_property_contact(property_id, display)
    return org
