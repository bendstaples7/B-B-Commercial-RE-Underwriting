#!/usr/bin/env python3
"""Heal HubSpot-primary phone ownership + replay call confidence for a lead.

Usage:
  python scripts/heal_lead_phone_confidence.py --lead-id 4490 --dry-run
  python scripts/heal_lead_phone_confidence.py --lead-id 4490 --apply \\
      --phone-id 12038 --move-to-contact-id 1386 --make-primary-contact-id 1386

Without --phone-id, selects the phone with notes \"HubSpot primary\" or the sole
hubspot_import phone on a non-former_owner contact. Ownership / primary changes
require explicit IDs.
"""
from __future__ import annotations

import argparse
import os
import sys

_SCRIPT_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = _SCRIPT_BACKEND if os.path.isdir(os.path.join(_SCRIPT_BACKEND, 'app')) else os.getcwd()
sys.path.insert(0, BACKEND_DIR)

from env_loader import load_project_env

load_project_env()


def _active_contact_ids(links) -> set[int]:
    return {
        pc.contact_id
        for pc in links
        if (pc.role or '') != 'former_owner'
    }


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
    active_ids = _active_contact_ids(links)
    contacts = {
        pc.contact_id: Contact.query.get(pc.contact_id)
        for pc in links
    }
    print('contacts:')
    for pc in links:
        c = contacts.get(pc.contact_id)
        print(
            '  pc=%s contact=%s name=%r %r primary=%s role=%s'
            % (
                pc.id,
                pc.contact_id,
                getattr(c, 'first_name', None),
                getattr(c, 'last_name', None),
                pc.is_primary,
                pc.role,
            )
        )

    phones = (
        ContactPhone.query
        .join(PropertyContact, PropertyContact.contact_id == ContactPhone.contact_id)
        .filter(
            PropertyContact.property_id == lead_id,
            PropertyContact.contact_id.in_(active_ids) if active_ids else False,
        )
        .all()
    ) if active_ids else []

    hs_phone = None
    if phone_id is not None:
        hs_phone = ContactPhone.query.get(phone_id)
        if hs_phone is None:
            raise SystemExit('phone-id %s not found' % phone_id)
        if hs_phone.contact_id not in active_ids:
            raise SystemExit(
                'phone-id %s is on a former_owner / inactive contact — refuse'
                % phone_id
            )
    else:
        primary_notes = [
            cp for cp in phones
            if (cp.notes or '').strip().lower() == HUBSPOT_PRIMARY_NOTE.lower()
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

    explicit = PhoneConfidenceService._explicit_annotation_score(hs_phone.notes)
    synthetic = PhoneConfidenceService._is_synthetic_hubspot_primary_notes(hs_phone.notes)

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
            synthetic = True
    elif not synthetic:
        print(
            'notes already set (%r) — leaving unchanged (not appending marker)'
            % (hs_phone.notes,)
        )

    # Floor only for synthetic HubSpot-primary marker — never override real annotations.
    if synthetic and explicit is None:
        if hs_phone.confidence_score is None or hs_phone.confidence_score < 85:
            print('boost confidence to 85 (synthetic HubSpot primary)')
            if apply:
                hs_phone.confidence_score = 85
    elif explicit is not None:
        print('preserve explicit annotation score', explicit)
        if apply:
            hs_phone.confidence_score = explicit

    if not (str(hs_phone.source) if hs_phone.source else '').lower().startswith('hubspot'):
        print('set source hubspot_import')
        if apply:
            hs_phone.source = 'hubspot_import'

    if move_to_contact_id is not None:
        if move_to_contact_id not in active_ids:
            raise SystemExit(
                'move-to-contact-id %s not an active contact on lead' % move_to_contact_id
            )
        if hs_phone.contact_id != move_to_contact_id:
            print('move phone to contact', move_to_contact_id)
            if apply:
                hs_phone.contact_id = move_to_contact_id

    if make_primary_contact_id is not None:
        if make_primary_contact_id not in active_ids:
            raise SystemExit(
                'make-primary-contact-id %s not an active contact on lead'
                % make_primary_contact_id
            )
        print('make contact primary', make_primary_contact_id)
        if apply:
            for pc in links:
                if (pc.role or '') == 'former_owner':
                    continue
                pc.is_primary = pc.contact_id == make_primary_contact_id
                db.session.add(pc)

    if apply:
        db.session.add(hs_phone)
        db.session.flush()
        if recompute and hasattr(PhoneConfidenceService, 'recompute_for_lead'):
            try:
                PhoneConfidenceService.recompute_for_lead(lead_id)
            except Exception as exc:
                db.session.rollback()
                print('recompute_for_lead failed — rolled back:', exc)
                raise SystemExit(1) from exc
        db.session.refresh(hs_phone)
        synthetic = PhoneConfidenceService._is_synthetic_hubspot_primary_notes(hs_phone.notes)
        explicit = PhoneConfidenceService._explicit_annotation_score(hs_phone.notes)
        if (
            synthetic
            and explicit is None
            and hs_phone.last_outcome != 'wrong_number'
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
