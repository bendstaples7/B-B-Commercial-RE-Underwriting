#!/usr/bin/env python3
"""Re-apply HubSpot mailing enrichment (primary + additional_addresses only).

Mailing-scoped: calls ``HubSpotMatcherService._apply_hubspot_mailing_addresses``
only — does not sync phones, emails, or contact links.

Usage:
    cd backend
    python scripts/sync_hubspot_mailing_from_contacts.py --dry-run
    python scripts/sync_hubspot_mailing_from_contacts.py --apply
    python scripts/sync_hubspot_mailing_from_contacts.py --apply --lead-id 10182
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def _pairs(lead_id: int | None):
    from app.models.hubspot_contact import HubSpotContact
    from app.models.hubspot_match import HubSpotMatch

    q = (
        HubSpotMatch.query
        .filter_by(
            hubspot_record_type='contact',
            status='confirmed',
            internal_record_type='lead',
        )
        .filter(HubSpotMatch.internal_record_id.isnot(None))
    )
    if lead_id is not None:
        q = q.filter(HubSpotMatch.internal_record_id == lead_id)

    pairs: list[tuple[HubSpotContact, int]] = []
    seen: set[tuple[str, int]] = set()
    for match in q.all():
        contact = HubSpotContact.query.filter_by(hubspot_id=match.hubspot_id).first()
        if contact is None or match.internal_record_id is None:
            continue
        key = (match.hubspot_id, match.internal_record_id)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((contact, match.internal_record_id))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Report only (default)')
    parser.add_argument('--apply', action='store_true', help='Commit mailing updates')
    parser.add_argument('--lead-id', type=int, default=None)
    args = parser.parse_args()
    if args.apply and args.dry_run:
        logger.error('Pass only one of --dry-run / --apply')
        return 2
    apply = bool(args.apply)

    from app import create_app, db
    from app.models.lead import Lead
    from app.services.hubspot_matcher_service import HubSpotMatcherService
    from app.services.lead_refresh import refresh_lead_scoring

    app = create_app()
    with app.app_context():
        pairs = _pairs(args.lead_id)
        changed = 0
        scanned = 0
        for contact, lead_id in pairs:
            props = (contact.raw_payload or {}).get('properties') or {}
            has_addr = any(
                (props.get(k) or '').strip()
                for k in ('address', 'additional_addresses')
            )
            if not has_addr:
                continue
            lead = db.session.get(Lead, lead_id)
            if lead is None:
                continue
            scanned += 1
            before = (
                lead.mailing_address,
                lead.mailing_city,
                lead.mailing_state,
                lead.mailing_zip,
                lead.address_2,
            )
            updated = HubSpotMatcherService._apply_hubspot_mailing_addresses(lead, props)
            after = (
                lead.mailing_address,
                lead.mailing_city,
                lead.mailing_state,
                lead.mailing_zip,
                lead.address_2,
            )
            if before == after or not updated:
                db.session.rollback()
                continue
            logger.info(
                'lead_id=%s hubspot_id=%s fields=%s mailing=%r / %r %r %r address_2=%r',
                lead_id,
                contact.hubspot_id,
                updated,
                lead.mailing_address,
                lead.mailing_city,
                lead.mailing_state,
                lead.mailing_zip,
                lead.address_2,
            )
            changed += 1
            if apply:
                db.session.add(lead)
                db.session.commit()
                refresh_lead_scoring(lead_id)
            else:
                db.session.rollback()

        logger.info(
            'scanned=%s changed=%s mode=%s',
            scanned,
            changed,
            'apply' if apply else 'dry-run',
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
