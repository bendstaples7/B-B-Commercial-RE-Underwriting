"""Heal jammed co-owner flat names into owner_2 + property contacts.

Used by the optional heal script and tests. Deploy applies the same class of
fix via Alembic ``joint_own_20260821`` (Core SQL + ``split_joint_person_owner_name``).

Live GIS rows often store ``A & B`` in ``owner_first_name``. Rewriting that to
``A`` can collide with ``uq_leads_owner_normalized_street``, so heals add
contacts (and fill empty ``owner_2_*``) without renaming the primary flat field.
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.property_contact import PropertyContact
from app.services.contact_service import ContactService
from app.services.plugins.owner_name_utils import (
    collect_flat_owner_people,
    owner_names_equivalent,
    split_joint_person_owner_name,
)

logger = logging.getLogger(__name__)

# Explicit restores when the loser lead was deleted before joint-name split existed.
# (winner_id, first_name, last_name)
KNOWN_MISSING_COOWNERS: tuple[tuple[int, str, str], ...] = (
    (11130, 'Edwin', 'Miller'),
)


def _owner_links(lead_id: int) -> list[PropertyContact]:
    return PropertyContact.query.filter_by(property_id=lead_id, role='owner').all()


def _owner_person_link(lead_id: int, first: str, last: str) -> PropertyContact | None:
    for link in _owner_links(lead_id):
        contact = db.session.get(Contact, link.contact_id)
        if contact is None:
            continue
        if owner_names_equivalent(first, last, contact.first_name, contact.last_name):
            return link
    return None


def _has_owner_person(lead_id: int, first: str, last: str) -> bool:
    return _owner_person_link(lead_id, first, last) is not None


def ensure_coowner_on_lead(
    lead_id: int,
    first_name: str,
    last_name: str,
    *,
    commit: bool = False,
) -> bool:
    """Ensure *first_name*/*last_name* exists as an owner on *lead_id*. Idempotent."""
    lead = db.session.get(Lead, lead_id)
    if lead is None:
        return False

    first = (first_name or '').strip()
    last = (last_name or '').strip()
    if not first and not last:
        return False

    changed = False
    o2_empty = not (
        (getattr(lead, 'owner_2_first_name', None) or '').strip()
        or (getattr(lead, 'owner_2_last_name', None) or '').strip()
    )
    if o2_empty:
        lead.owner_2_first_name = first
        lead.owner_2_last_name = last or None
        changed = True

    service = ContactService()
    if not _has_owner_person(lead_id, first, last):
        # Prefer upsert from flats when owner_2 was just filled.
        try:
            with db.session.begin_nested():
                service.upsert_owners_from_lead(
                    lead,
                    phone_source='flat_backfill',
                    commit=False,
                    refresh_scoring=False,
                )
        except IntegrityError:
            lead = db.session.get(Lead, lead_id)
        if lead is not None and not _has_owner_person(lead_id, first, last):
            service._upsert_named_owner(  # noqa: SLF001
                lead_id,
                first,
                last or None,
                is_primary=False,
                owner_user_id=getattr(lead, 'owner_user_id', None),
            )
            changed = True

    if commit:
        db.session.commit()
    return changed


def _heal_live_jammed_lead(lead: Lead, service: ContactService) -> bool:
    """Add owner_2 + contacts for joint names without renaming primary flat."""
    people = collect_flat_owner_people(lead)
    if len(people) < 2:
        # Still try split of primary alone.
        people = split_joint_person_owner_name(
            getattr(lead, 'owner_first_name', None),
            getattr(lead, 'owner_last_name', None),
        )
    if len(people) < 2:
        return False

    changed = False
    second = people[1]
    o2_empty = not (
        (getattr(lead, 'owner_2_first_name', None) or '').strip()
        or (getattr(lead, 'owner_2_last_name', None) or '').strip()
    )
    if o2_empty:
        lead.owner_2_first_name = second[0]
        lead.owner_2_last_name = second[1]
        changed = True

    for index, (first, last) in enumerate(people):
        existing_link = _owner_person_link(lead.id, first or '', last or '')
        want_primary = index == 0
        if existing_link is not None:
            if want_primary and not existing_link.is_primary:
                PropertyContact.query.filter_by(
                    property_id=lead.id,
                    is_primary=True,
                ).update({'is_primary': False})
                existing_link.is_primary = True
                changed = True
            continue
        service._upsert_named_owner(  # noqa: SLF001
            lead.id,
            first,
            last,
            is_primary=want_primary,
            owner_user_id=getattr(lead, 'owner_user_id', None),
        )
        changed = True
    return changed


def heal_joint_owner_names(
    *,
    lead_ids: Iterable[int] | None = None,
    include_known_missing: bool = True,
    heal_live_jammed: bool = False,
    commit: bool = True,
    limit: int | None = None,
) -> dict[str, int]:
    """Restore known missing co-owners; optionally heal live jammed flat names.

    Mass live GIS heals default off here; Deploy Alembic already heals the class
    with Core SQL. Pass ``heal_live_jammed=True`` for re-runs / local backfills.
    """
    stats = {
        'leads_scanned': 0,
        'leads_split': 0,
        'known_restored': 0,
        'errors': 0,
    }

    service = ContactService()
    id_list = list(lead_ids) if lead_ids is not None else None
    id_set = set(id_list) if id_list is not None else None

    if heal_live_jammed or lead_ids is not None:
        query = Lead.query.filter(
            Lead.owner_first_name.isnot(None),
            or_(
                Lead.owner_first_name.ilike('% and %'),
                Lead.owner_first_name.ilike('% & %'),
            ),
        )
        if id_list is not None:
            query = query.filter(Lead.id.in_(id_list))
        if limit is not None:
            query = query.limit(limit)

        for lead in query.order_by(Lead.id.asc()).all():
            stats['leads_scanned'] += 1
            try:
                with db.session.begin_nested():
                    if _heal_live_jammed_lead(lead, service):
                        stats['leads_split'] += 1
                    db.session.flush()
            except Exception:  # noqa: BLE001
                logger.exception('joint owner heal failed for lead_id=%s', lead.id)
                stats['errors'] += 1

    if include_known_missing:
        for winner_id, first, last in KNOWN_MISSING_COOWNERS:
            if id_set is not None and winner_id not in id_set:
                continue
            try:
                with db.session.begin_nested():
                    if ensure_coowner_on_lead(winner_id, first, last, commit=False):
                        stats['known_restored'] += 1
                    db.session.flush()
            except Exception:  # noqa: BLE001
                logger.exception(
                    'known co-owner restore failed lead_id=%s name=%s %s',
                    winner_id,
                    first,
                    last,
                )
                stats['errors'] += 1

    if commit:
        db.session.commit()
    return stats
