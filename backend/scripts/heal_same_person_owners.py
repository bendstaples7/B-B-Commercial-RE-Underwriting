#!/usr/bin/env python3
"""Consolidate same-person owner fragments on a lead (e.g. Sam name variants).

Keeps the outreach contact that owns the confirmed dialed phone, merges other
phones onto it, demotes duplicate owner links to former_owner, refreshes scoring.

Usage:
  python scripts/heal_same_person_owners.py --lead-id 4490 --dry-run
  python scripts/heal_same_person_owners.py --lead-id 4490 --apply
  python scripts/heal_same_person_owners.py --lead-id 4490 --apply --keep-phone-digits 7732715525
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

_SCRIPT_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = _SCRIPT_BACKEND if os.path.isdir(os.path.join(_SCRIPT_BACKEND, 'app')) else os.getcwd()
sys.path.insert(0, BACKEND_DIR)

from env_loader import load_project_env

load_project_env()


def heal_same_person_owners(
    lead_id: int,
    *,
    apply: bool,
    keep_phone_digits: str | None = None,
) -> dict:
    from app import create_app, db
    from app.models.contact import Contact
    from app.models.contact_phone import ContactPhone
    from app.models.lead import Lead
    from app.models.property_contact import PropertyContact
    from app.services.contact_backfill import phone_digits
    from app.services.contact_service import ContactService
    from app.services.lead_refresh import refresh_lead_scoring
    from app.services.phone_confidence_service import PhoneConfidenceService
    from app.services.plugins.owner_name_utils import same_person_name_alias

    app = create_app()
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        if lead is None:
            raise SystemExit(f'Lead {lead_id} not found')

        rows = (
            db.session.query(Contact, PropertyContact)
            .join(PropertyContact, PropertyContact.contact_id == Contact.id)
            .filter(PropertyContact.property_id == lead_id)
            .filter(PropertyContact.role.in_(('owner', 'former_owner')))
            .all()
        )
        if not rows:
            print('No owner/former_owner contacts')
            return {'kept': None, 'demoted': []}

        wanted = phone_digits(keep_phone_digits) if keep_phone_digits else ''
        if wanted.startswith('1') and len(wanted) == 11:
            wanted = wanted[1:]

        def _digits_for(contact: Contact) -> set[str]:
            out: set[str] = set()
            for p in ContactPhone.query.filter_by(contact_id=contact.id).all():
                d = phone_digits(p.value)
                if d.startswith('1') and len(d) == 11:
                    d = d[1:]
                if d:
                    out.add(d)
            return out

        def _identity_match(a: Contact, b: Contact) -> bool:
            if same_person_name_alias(
                a.first_name, a.last_name, b.first_name, b.last_name,
            ):
                return True
            return bool(_digits_for(a) & _digits_for(b))

        scored: list[tuple[int, Contact, PropertyContact]] = []
        for contact, link in rows:
            phones = ContactPhone.query.filter_by(contact_id=contact.id).all()
            score = 0
            for p in phones:
                d = phone_digits(p.value)
                if d.startswith('1') and len(d) == 11:
                    d = d[1:]
                if wanted and d == wanted:
                    score += 1000
                if p.last_called_at:
                    score += 100
                if p.confidence_score:
                    score += int(p.confidence_score)
                if 'hubspot primary' in (p.notes or '').lower():
                    score += 50
            if link.role == 'owner':
                score += 5
            if link.is_primary:
                score += 2
            scored.append((score, contact, link))

        scored.sort(key=lambda t: (-t[0], t[1].id))

        if wanted:
            keep_score, keep_contact, keep_link = scored[0]
            if keep_score < 1000:
                print(
                    'No contact owns --keep-phone-digits; refusing to pick by '
                    'activity score alone'
                )
                return {'kept': None, 'demoted': []}
        else:
            # Without an explicit phone, only heal a verified same-person cluster.
            cluster = [scored[0]]
            seed = scored[0][1]
            for item in scored[1:]:
                if _identity_match(seed, item[1]):
                    cluster.append(item)
            if len(cluster) < 2:
                print(
                    'No verified same-person cluster (name alias or shared phone); '
                    'no-op without --keep-phone-digits'
                )
                return {'kept': None, 'demoted': []}
            cluster.sort(key=lambda t: (-t[0], t[1].id))
            keep_score, keep_contact, keep_link = cluster[0]
            scored = cluster

        print(
            f'Keep contact {keep_contact.id} '
            f'{keep_contact.first_name!r} {keep_contact.last_name!r} '
            f'score={keep_score} role={keep_link.role}'
        )

        demote: list[tuple[Contact, PropertyContact]] = []
        for score, contact, link in scored[1:]:
            if not _identity_match(keep_contact, contact):
                print(
                    f'  skip non-identity contact {contact.id} '
                    f'{contact.first_name!r} {contact.last_name!r} score={score}'
                )
                continue
            demote.append((contact, link))
            print(
                f'  demote candidate {contact.id} '
                f'{contact.first_name!r} {contact.last_name!r} score={score}'
            )

        if not apply:
            print('Dry-run only — pass --apply to write')
            return {
                'kept': keep_contact.id,
                'demoted': [c.id for c, _ in demote],
            }

        svc = ContactService()
        now = datetime.now(timezone.utc)
        for contact, link in demote:
            svc._migrate_outreach_phones_to_contact(contact.id, keep_contact.id)
            if link.role == 'owner':
                link.role = 'former_owner'
                link.is_primary = False
                link.superseded_at = now

        PropertyContact.query.filter_by(property_id=lead_id, is_primary=True).update(
            {'is_primary': False},
        )
        keep_link.role = 'owner'
        keep_link.is_primary = True
        keep_link.superseded_at = None
        db.session.commit()

        PhoneConfidenceService.recompute_for_lead(lead_id)
        from app.services.mail_task_lifecycle_service import ensure_due_today_call_task
        ensure_due_today_call_task(lead, actor='heal_same_person_owners')
        refresh_lead_scoring(lead_id)
        print('Applied + recomputed phone confidence + scoring + call-task due bump')
        return {
            'kept': keep_contact.id,
            'demoted': [c.id for c, _ in demote],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lead-id', type=int, required=True)
    parser.add_argument('--keep-phone-digits', default=None)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true')
    group.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    heal_same_person_owners(
        args.lead_id,
        apply=bool(args.apply),
        keep_phone_digits=args.keep_phone_digits,
    )


if __name__ == '__main__':
    main()
