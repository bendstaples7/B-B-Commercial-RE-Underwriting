"""Merge Contact rows that share phone/email across a user's properties.

Reuses ContactService.find_reusable_contact_for_user identity rules:
phone digits or lowercased email within the same owner_user_id scope.

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


def find_merge_groups(session):
    """Return lists of contact_ids that should collapse (winner = lowest id)."""
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
    contact_users: dict[int, set] = defaultdict(set)
    for contact_id, owner_user_id in rows:
        contact_users[contact_id].add(owner_user_id)

    # Index phones/emails → contact ids (scoped loosely; filter per user below)
    email_to_contacts: dict[tuple, set[int]] = defaultdict(set)
    phone_to_contacts: dict[tuple, set[int]] = defaultdict(set)

    for contact_id, users in contact_users.items():
        emails = ContactEmail.query.filter_by(contact_id=contact_id).all()
        phones = ContactPhone.query.filter_by(contact_id=contact_id).all()
        for user_id in users:
            for em in emails:
                key = _email_key(em.value)
                if key:
                    email_to_contacts[(user_id, key)].add(contact_id)
            for ph in phones:
                key = _phone_key(ph.value)
                if key:
                    phone_to_contacts[(user_id, key)].add(contact_id)

    # Union-find over contact ids that share a key within a user
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
        # Prefer lower id as canonical root.
        if ra < rb:
            parent[rb] = ra
        else:
            parent[ra] = rb

    for ids in email_to_contacts.values():
        ids_list = sorted(ids)
        for other in ids_list[1:]:
            union(ids_list[0], other)
    for ids in phone_to_contacts.values():
        ids_list = sorted(ids)
        for other in ids_list[1:]:
            union(ids_list[0], other)

    groups: dict[int, list[int]] = defaultdict(list)
    for cid in list(parent.keys()):
        groups[find(cid)].append(cid)

    return [sorted(members) for members in groups.values() if len(members) >= 2]


def merge_contact_group(session, contact_ids: list[int], *, apply: bool) -> dict:
    """Repoint property_contacts / phones / emails onto the lowest contact id."""
    from app.models.contact import Contact
    from app.models.contact_email import ContactEmail
    from app.models.contact_phone import ContactPhone
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

        # Move property links (skip if winner already linked to that property)
        links = PropertyContact.query.filter_by(contact_id=loser_id).all()
        for link in links:
            exists = (
                PropertyContact.query
                .filter_by(property_id=link.property_id, contact_id=winner_id)
                .first()
            )
            if exists:
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
