#!/usr/bin/env python3
"""Heal HubSpot-primary phone ownership + replay call confidence for a lead.

Usage:
  python scripts/heal_lead_phone_confidence.py --lead-id 4490 --dry-run
  python scripts/heal_lead_phone_confidence.py --lead-id 4490 --apply \\
      --phone-id 12038 --move-to-contact-id 1386 --make-primary-contact-id 1386

Without --phone-id, selects the phone with notes \"HubSpot primary\" or the sole
hubspot_import phone. Ownership / primary changes require explicit IDs.
"""
from __future__ import annotations

import argparse
import os
import sys

_SCRIPT_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = _SCRIPT_BACKEND if os.path.isdir(os.path.join(_SCRIPT_BACKEND, 'app')) else os.getcwd()
sys.path.insert(0, BACKEND_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(BACKEND_DIR, '.env'))


def _heal_lead(
    lead_id: int,
    *,
    apply: bool,
    phone_id: int | None,
    move_to_contact_id: int | None,
    make_primary_contact_id: int | None,
    recompute: bool,
) -> None:
    from app import db
    from app.models.contact import Contact
    from app.models.contact_phone import ContactPhone
    from app.models.property_contact import PropertyContact
    from app.services.phone_confidence_service import (
        HUBSPOT_PRIMARY_NOTE,
        MIN_VIABLE_CONFIDENCE,
        PhoneConfidenceService,
    )

    links = (
        PropertyContact.query
        .filter_by(property_id=lead_id)
        .order_by(PropertyContact.is_primary.desc(), PropertyContact.id.asc())
        .all()
    )
    contacts = {
        pc.contact_id: Contact.query.get(pc.contact_id)
        for pc in links
    }
    print('contacts:')
    for pc in links:
        c = contacts.get(pc.contact_id)
        print(
            '  pc=%s contact=%s name=%r %r primary=%s'
            % (
                pc.id,
                pc.contact_id,
                getattr(c, 'first_name', None),
                getattr(c, 'last_name', None),
                pc.is_primary,
            )
        )

    phones = (
        ContactPhone.query
        .join(PropertyContact, PropertyContact.contact_id == ContactPhone.contact_id)
        .filter(PropertyContact.property_id == lead_id)
        .all()
    )
    hs_phone = None
    if phone_id is not None:
        hs_phone = next((cp for cp in phones if cp.id == phone_id), None)
        if hs_phone is None:
            raise SystemExit('phone-id %s not found on lead %s' % (phone_id, lead_id))
    else:
        primary_notes = [
            cp for cp in phones
            if 'hubspot primary' in (cp.notes or '').lower()
        ]
        hubspot_src = [
            cp for cp in phones
            if (str(cp.source) if cp.source else '').lower().startswith('hubspot')
        ]
        if len(primary_notes) == 1:
            hs_phone = primary_notes[0]
        elif len(hubspot_src) == 1:
            hs_phone = hubspot_src[0]
        elif primary_notes:
            raise SystemExit(
                'multiple HubSpot-primary phones — pass --phone-id (%s)'
                % ([cp.id for cp in primary_notes],)
            )
        else:
            raise SystemExit(
                'no HubSpot-primary / sole hubspot phone — pass --phone-id'
            )

    print(
        'hubspot_phone',
        (hs_phone.id, hs_phone.value, hs_phone.notes, hs_phone.confidence_score,
         hs_phone.last_outcome),
    )

    if hs_phone.last_outcome == 'wrong_number' or (
        hs_phone.confidence_score is not None
        and hs_phone.confidence_score < MIN_VIABLE_CONFIDENCE
    ):
        print('refuse: phone is wrong_number / non-viable — not boosting')
        if apply:
            raise SystemExit(1)

    if not (hs_phone.notes or '').strip():
        print('set notes to exact HubSpot primary marker')
        if apply:
            hs_phone.notes = HUBSPOT_PRIMARY_NOTE
    elif (hs_phone.notes or '').strip().lower() != HUBSPOT_PRIMARY_NOTE.lower():
        # Do not append into real annotations — only set when empty above.
        print(
            'notes already set (%r) — leaving unchanged (not appending marker)'
            % (hs_phone.notes,)
        )

    if hs_phone.confidence_score is None or hs_phone.confidence_score < 85:
        print('boost confidence to 85')
        if apply:
            hs_phone.confidence_score = 85
    if not (str(hs_phone.source) if hs_phone.source else '').lower().startswith('hubspot'):
        print('set source hubspot_import')
        if apply:
            hs_phone.source = 'hubspot_import'

    if move_to_contact_id is not None:
        if move_to_contact_id not in contacts:
            raise SystemExit('move-to-contact-id %s not on lead' % move_to_contact_id)
        if hs_phone.contact_id != move_to_contact_id:
            print('move phone to contact', move_to_contact_id)
            if apply:
                hs_phone.contact_id = move_to_contact_id

    if make_primary_contact_id is not None:
        if make_primary_contact_id not in contacts:
            raise SystemExit(
                'make-primary-contact-id %s not on lead' % make_primary_contact_id
            )
        print('make contact primary', make_primary_contact_id)
        if apply:
            for pc in links:
                pc.is_primary = pc.contact_id == make_primary_contact_id
                db.session.add(pc)

    if apply:
        db.session.add(hs_phone)
        db.session.flush()
        if recompute and hasattr(PhoneConfidenceService, 'recompute_for_lead'):
            try:
                PhoneConfidenceService.recompute_for_lead(lead_id)
            except Exception as exc:
                print('recompute_for_lead skipped:', exc)
        db.session.refresh(hs_phone)
        if (
            hs_phone.last_outcome != 'wrong_number'
            and (hs_phone.confidence_score is None or hs_phone.confidence_score < 85)
            and (hs_phone.confidence_score is None or hs_phone.confidence_score >= MIN_VIABLE_CONFIDENCE)
        ):
            print('re-apply HubSpot primary floor 85 after recompute')
            hs_phone.confidence_score = 85
            db.session.add(hs_phone)
        db.session.commit()
        db.session.refresh(hs_phone)
        print(
            'after primary=',
            (hs_phone.id, hs_phone.value, hs_phone.confidence_score, hs_phone.notes,
             hs_phone.last_outcome),
        )
    else:
        print('dry-run — no writes')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lead-id', type=int, required=True)
    parser.add_argument('--phone-id', type=int, default=None)
    parser.add_argument('--move-to-contact-id', type=int, default=None)
    parser.add_argument('--make-primary-contact-id', type=int, default=None)
    parser.add_argument(
        '--no-recompute',
        action='store_true',
        help='Skip timeline confidence replay after ownership fixes',
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    from app import create_app

    app = create_app()
    with app.app_context():
        _heal_lead(
            args.lead_id,
            apply=args.apply,
            phone_id=args.phone_id,
            move_to_contact_id=args.move_to_contact_id,
            make_primary_contact_id=args.make_primary_contact_id,
            recompute=not args.no_recompute,
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
