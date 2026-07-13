"""Promote entity-shaped owner Contacts / flat Owner 2 fields to Organizations.

Usage:
  python scripts/promote_entity_owners_to_organizations.py
  python scripts/promote_entity_owners_to_organizations.py --apply
  python scripts/promote_entity_owners_to_organizations.py --apply --lead-id 4860
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running as ``python scripts/...`` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("promote_entity_owners")


def _iter_candidates(lead_id: int | None):
    from app.extensions import db
    from app.models.contact import Contact
    from app.models.lead import Lead
    from app.models.property_contact import PropertyContact
    from app.services.plugins.owner_name_utils import (
        contact_display_name,
        is_address_like_contact,
        is_entity_contact,
    )
    from sqlalchemy import or_

    # Entity-shaped property contacts
    q = (
        db.session.query(Lead, Contact, PropertyContact)
        .join(PropertyContact, PropertyContact.property_id == Lead.id)
        .join(Contact, Contact.id == PropertyContact.contact_id)
    )
    if lead_id is not None:
        q = q.filter(Lead.id == lead_id)

    seen_keys: set[tuple[int, str]] = set()

    for lead, contact, _link in q.yield_per(200):
        if is_address_like_contact(contact.first_name, contact.last_name):
            continue
        if not is_entity_contact(contact.first_name, contact.last_name):
            continue
        display = contact_display_name(contact.first_name, contact.last_name)
        key = (lead.id, display.lower())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        yield lead.id, display, "property_contact"

    # Flat owner / owner_2 entity names not already yielded
    flat_q = Lead.query
    if lead_id is not None:
        flat_q = flat_q.filter(Lead.id == lead_id)
    flat_q = flat_q.filter(
        or_(
            Lead.owner_first_name.isnot(None),
            Lead.owner_last_name.isnot(None),
            Lead.owner_2_first_name.isnot(None),
            Lead.owner_2_last_name.isnot(None),
        )
    )

    for lead in flat_q.yield_per(200):
        pairs = [
            (lead.owner_first_name, lead.owner_last_name),
            (lead.owner_2_first_name, lead.owner_2_last_name),
        ]
        for first, last in pairs:
            if is_address_like_contact(first, last):
                continue
            if not is_entity_contact(first, last):
                continue
            display = contact_display_name(first, last)
            key = (lead.id, display.lower())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            yield lead.id, display, "flat_owner"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist Organization links and unlink matching LLC PropertyContacts",
    )
    parser.add_argument("--lead-id", type=int, default=None, help="Limit to one lead")
    args = parser.parse_args()

    from app import create_app
    from app.extensions import db
    from app.models.property_organization_link import PropertyOrganizationLink
    from app.services.helpers.owner_organization import (
        ensure_owner_organization,
        unlink_matching_entity_property_contact,
    )
    from sqlalchemy import func
    from app.models.organization import Organization

    app = create_app()
    promoted = 0
    unlinked = 0
    skipped_existing = 0
    leads_to_research: set[int] = set()

    with app.app_context():
        candidates = list(_iter_candidates(args.lead_id))
        logger.info("Candidates: %d (apply=%s)", len(candidates), args.apply)

        for property_id, name, source_kind in candidates:
            org = (
                Organization.query
                .filter(func.lower(Organization.name) == name.lower())
                .order_by(Organization.id.asc())
                .first()
            )
            already_linked = False
            if org is not None:
                already_linked = (
                    PropertyOrganizationLink.query
                    .filter_by(
                        property_id=property_id,
                        organization_id=org.id,
                        role="owner",
                    )
                    .first()
                    is not None
                )

            if already_linked:
                skipped_existing += 1
                if args.apply:
                    unlinked += unlink_matching_entity_property_contact(property_id, name)
                    leads_to_research.add(property_id)
                else:
                    logger.info(
                        "[dry-run] already linked lead=%s org=%r (%s) — would unlink contact / research",
                        property_id, name, source_kind,
                    )
                continue

            if args.apply:
                ensure_owner_organization(
                    property_id,
                    name,
                    source="entity_owner_promotion",
                )
                unlinked += unlink_matching_entity_property_contact(property_id, name)
                leads_to_research.add(property_id)
                promoted += 1
            else:
                logger.info(
                    "[dry-run] would promote lead=%s name=%r from %s",
                    property_id, name, source_kind,
                )
                promoted += 1

        if args.apply:
            db.session.commit()
            logger.info(
                "Applied: promoted=%d unlinked_contacts=%d already_linked=%d",
                promoted, unlinked, skipped_existing,
            )
            from app.services.entity_resolution_service import EntityResolutionService
            svc = EntityResolutionService()
            researched = 0
            for lid in sorted(leads_to_research):
                try:
                    result = svc.ensure_researched(
                        lid, actor="entity_owner_promotion", sync=True,
                    )
                    logger.info("Research lead=%s → %s", lid, result)
                    if not result.get("skipped"):
                        researched += 1
                except Exception:  # noqa: BLE001
                    logger.exception("ensure_researched failed for lead %s", lid)
            logger.info(
                "Entity research attempted for %d leads (%d not skipped)",
                len(leads_to_research), researched,
            )
        else:
            logger.info(
                "Dry-run: would_promote=%d already_linked=%d (re-run with --apply)",
                promoted, skipped_existing,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
