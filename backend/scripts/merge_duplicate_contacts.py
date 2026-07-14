"""Merge Contact rows that share phone/email across a user's properties.

Reuses ContactService identity rules: phone digits or lowercased email within
the same owner_user_id scope, gated by owner_names_equivalent.

Union-find runs **per user** so phone/email edges cannot transitively merge
contacts across CRM user boundaries.

Run from backend/:
    python scripts/merge_duplicate_contacts.py --dry-run
    python scripts/merge_duplicate_contacts.py --apply
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def _phone_key(value: str | None) -> str:
    from app.services.contact_backfill import phone_digits
    return phone_digits(value or '')


def _email_key(value: str | None) -> str:
    return (value or '').strip().lower()


def _union_compatible_ids(
    contact_ids: set[int],
    contacts_by_id: dict,
    email_to_contacts: dict[str, set[int]],
    phone_to_contacts: dict[str, set[int]],
) -> list[list[int]]:
    """Union-find among *contact_ids*, only linking name-compatible pairs."""
    from app.services.plugins.owner_name_utils import owner_names_equivalent

    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if ra < rb:
            parent[rb] = ra
        else:
            parent[ra] = rb

    def _names_ok(a: int, b: int) -> bool:
        ca, cb = contacts_by_id.get(a), contacts_by_id.get(b)
        if ca is None or cb is None:
            return False
        return owner_names_equivalent(
            ca.first_name, ca.last_name, cb.first_name, cb.last_name,
        )

    touched: set[int] = set()
    for ids in (*email_to_contacts.values(), *phone_to_contacts.values()):
        scoped = sorted(ids & contact_ids)
        for a, b in combinations(scoped, 2):
            if not _names_ok(a, b):
                continue
            union(a, b)
            touched.add(a)
            touched.add(b)

    groups: dict[int, list[int]] = defaultdict(list)
    for cid in touched:
        groups[find(cid)].append(cid)

    return [sorted(set(members)) for members in groups.values() if len(set(members)) >= 2]


def find_merge_groups(session):
    """Return lists of contact_ids that should collapse (winner = lowest id).

    Each group is confined to a single ``owner_user_id`` (including both-null).
    """
    from app.models.contact import Contact
    from app.models.contact_email import ContactEmail
    from app.models.contact_phone import ContactPhone
    from app.models.lead import Property
    from app.models.property_contact import PropertyContact

    rows = (
        session.query(Contact.id, Property.owner_user_id)
        .join(PropertyContact, PropertyContact.contact_id == Contact.id)
        .join(Property, Property.id == PropertyContact.property_id)
        .all()
    )
    user_to_contacts: dict = defaultdict(set)
    for contact_id, owner_user_id in rows:
        user_to_contacts[owner_user_id].add(contact_id)

    all_contact_ids = {cid for cids in user_to_contacts.values() for cid in cids}
    if not all_contact_ids:
        return []

    contacts_by_id = {
        c.id: c for c in Contact.query.filter(Contact.id.in_(all_contact_ids)).all()
    }

    email_rows = (
        session.query(ContactEmail.contact_id, ContactEmail.value)
        .filter(ContactEmail.contact_id.in_(all_contact_ids))
        .all()
    )
    phone_rows = (
        session.query(ContactPhone.contact_id, ContactPhone.value)
        .filter(ContactPhone.contact_id.in_(all_contact_ids))
        .all()
    )

    all_groups: list[list[int]] = []
    for _user_id, contact_ids in user_to_contacts.items():
        email_to_contacts: dict[str, set[int]] = defaultdict(set)
        phone_to_contacts: dict[str, set[int]] = defaultdict(set)
        for contact_id, value in email_rows:
            if contact_id not in contact_ids:
                continue
            key = _email_key(value)
            if key:
                email_to_contacts[key].add(contact_id)
        for contact_id, value in phone_rows:
            if contact_id not in contact_ids:
                continue
            key = _phone_key(value)
            if key:
                phone_to_contacts[key].add(contact_id)

        all_groups.extend(
            _union_compatible_ids(
                contact_ids, contacts_by_id, email_to_contacts, phone_to_contacts,
            )
        )
    return all_groups


def _merge_link_metadata(exists, link) -> None:
    """Preserve primary / prefer owner role when winner already linked."""
    if link.is_primary and not exists.is_primary:
        exists.is_primary = True
    if link.role == 'owner' and exists.role != 'owner':
        exists.role = 'owner'
    elif exists.role in (None, 'other') and link.role and link.role != 'other':
        exists.role = link.role


def merge_contact_group(session, contact_ids: list[int], *, apply: bool) -> dict:
    """Repoint property_contacts / phones / emails onto the lowest contact id."""
    from app.models.contact import Contact
    from app.models.property_contact import PropertyContact
    from app.services.contact_backfill import phone_digits

    winner_id = min(contact_ids)
    losers = [c for c in contact_ids if c != winner_id]
    summary = {'winner': winner_id, 'losers': losers, 'links_moved': 0, 'deleted': 0}

    if not apply:
        return summary

    winner = Contact.query.get(winner_id)
    if winner is None:
        return summary

    existing_phones = {
        phone_digits(p.value) for p in (winner.phones or []) if phone_digits(p.value)
    }
    existing_emails = {
        (e.value or '').strip().lower() for e in (winner.emails or []) if (e.value or '').strip()
    }

    for loser_id in losers:
        loser = Contact.query.get(loser_id)
        if loser is None:
            continue

        links = PropertyContact.query.filter_by(contact_id=loser_id).all()
        for link in links:
            exists = (
                PropertyContact.query
                .filter_by(property_id=link.property_id, contact_id=winner_id)
                .first()
            )
            if exists:
                _merge_link_metadata(exists, link)
                session.delete(link)
            else:
                link.contact_id = winner_id
                summary['links_moved'] += 1

        for phone in list(loser.phones or []):
            digits = phone_digits(phone.value)
            if digits and digits not in existing_phones:
                phone.contact_id = winner_id
                existing_phones.add(digits)
            else:
                session.delete(phone)

        for email in list(loser.emails or []):
            key = (email.value or '').strip().lower()
            if key and key not in existing_emails:
                email.contact_id = winner_id
                existing_emails.add(key)
            else:
                session.delete(email)

        session.flush()
        session.delete(loser)
        summary['deleted'] += 1

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true')
    group.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    from app import create_app, db

    app = create_app()
    with app.app_context():
        groups = find_merge_groups(db.session)
        logger.info('Found %d contact merge group(s)', len(groups))
        for members in groups:
            summary = merge_contact_group(db.session, members, apply=args.apply)
            logger.info(
                '%s contact group winner=%s losers=%s links_moved=%s deleted=%s',
                'APPLY' if args.apply else 'DRY-RUN',
                summary['winner'],
                summary['losers'],
                summary['links_moved'],
                summary['deleted'],
            )
        if args.apply and groups:
            db.session.commit()
            logger.info('Committed contact merges')
        elif args.dry_run:
            logger.info('Dry run only — no changes written')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
