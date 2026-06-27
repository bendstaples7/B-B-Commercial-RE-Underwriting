#!/usr/bin/env python3
"""Backfill HubSpot phone annotations into contact_phones.confidence_score.

Usage:
    cd backend
    python scripts/sync_phone_confidence_from_hubspot.py --dry-run
    python scripts/sync_phone_confidence_from_hubspot.py --apply
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def _collect_contact_lead_pairs():
    """Return unique (hubspot_contact_id, lead_id) pairs to sync."""
    from app.models.hubspot_contact import HubSpotContact
    from app.models.hubspot_deal import HubSpotDeal
    from app.models.hubspot_match import HubSpotMatch

    pairs: set[tuple[str, int]] = set()

    confirmed_contacts = (
        HubSpotMatch.query
        .filter_by(hubspot_record_type='contact', status='confirmed', internal_record_type='lead')
        .filter(HubSpotMatch.internal_record_id.isnot(None))
        .all()
    )
    for match in confirmed_contacts:
        pairs.add((match.hubspot_id, match.internal_record_id))

    deal_matches = (
        HubSpotMatch.query
        .filter_by(hubspot_record_type='deal', status='confirmed', internal_record_type='lead')
        .filter(HubSpotMatch.internal_record_id.isnot(None))
        .all()
    )
    for match in deal_matches:
        lead_id = match.internal_record_id
        deal = HubSpotDeal.query.filter_by(hubspot_id=match.hubspot_id).first()
        if deal is None:
            continue
        assoc = (deal.raw_payload or {}).get('associations', {})
        contact_ids = (
            assoc.get('contacts', {}).get('results', [])
            if isinstance(assoc.get('contacts'), dict)
            else []
        )
        for entry in contact_ids:
            cid = str(entry.get('id', ''))
            if cid:
                pairs.add((cid, lead_id))

    return sorted(pairs)


def _refresh_with_retry(contact_sync, hubspot_id: str, *, max_attempts: int = 8):
    """Refresh a contact from HubSpot, backing off on 429 rate limits."""
    from app.exceptions import HubSpotRateLimitError

    for attempt in range(1, max_attempts + 1):
        try:
            return contact_sync.refresh_contact_from_api(hubspot_id)
        except HubSpotRateLimitError as exc:
            wait = (exc.payload or {}).get('retry_after') or min(10 * attempt, 60)
            if attempt == max_attempts:
                raise
            logger.warning(
                'Rate limited on contact %s (attempt %d/%d) — sleeping %ds',
                hubspot_id, attempt, max_attempts, wait,
            )
            time.sleep(wait)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description='Sync HubSpot phone confidence to contact_phones')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true', help='Report only; no API or DB writes')
    group.add_argument('--apply', action='store_true', help='Refresh contacts and update confidence')
    parser.add_argument(
        '--delay',
        type=float,
        default=0.2,
        help='Seconds to sleep between API refreshes (default: 0.2)',
    )
    args = parser.parse_args()

    from app import create_app, db
    from app.models import Lead
    from app.models.hubspot_contact import HubSpotContact
    from app.services.hubspot_contact_sync_service import HubSpotContactSyncService
    from app.services.hubspot_matcher_service import HubSpotMatcherService
    from app.services.phone_confidence_service import PhoneConfidenceService

    app = create_app()
    with app.app_context():
        pairs = _collect_contact_lead_pairs()
        logger.info('Found %d contact/lead pair(s) to process', len(pairs))

        contact_sync = None
        if args.apply:
            try:
                contact_sync = HubSpotContactSyncService()
            except Exception as exc:
                logger.error('Could not init HubSpot client: %s', exc)
                return 1

        matcher = HubSpotMatcherService()
        total_phones = 0
        total_leads = 0

        for hubspot_id, lead_id in pairs:
            lead = Lead.query.get(lead_id)
            if lead is None:
                logger.warning('Lead %s not found — skip contact %s', lead_id, hubspot_id)
                continue

            contact = HubSpotContact.query.filter_by(hubspot_id=hubspot_id).first()
            if args.apply and contact_sync is not None:
                contact = _refresh_with_retry(contact_sync, hubspot_id)
                if args.delay > 0:
                    time.sleep(args.delay)
            if contact is None:
                logger.warning('HubSpot contact %s not found — skip lead %s', hubspot_id, lead_id)
                continue

            props = (contact.raw_payload or {}).get('properties', {})
            parsed = PhoneConfidenceService.parse_phones_from_hubspot_props(props)
            annotated = [p for p in parsed if p[1]]
            owner = f'{lead.owner_first_name or ""} {lead.owner_last_name or ""}'.strip() or f'lead {lead_id}'

            if args.dry_run:
                logger.info(
                    '[dry-run] lead=%s (%s) contact=%s phones=%d annotated=%d',
                    lead_id, owner, hubspot_id, len(parsed), len(annotated),
                )
                for val, notes, _label in parsed:
                    score = PhoneConfidenceService.confidence_from_annotation(notes)
                    logger.info('  %s -> %s%% notes=%r', val, score, notes)
                total_phones += len(parsed)
                total_leads += 1
                continue

            enriched = matcher.enrich_lead_from_contact(lead, contact)
            synced = PhoneConfidenceService.sync_phones_from_hubspot_contact(lead.id, contact)
            db.session.commit()
            total_phones += synced
            total_leads += 1
            logger.info(
                'lead=%s (%s) contact=%s enriched=%s phones_updated=%d annotated_in_hs=%d',
                lead_id, owner, hubspot_id, enriched, synced, len(annotated),
            )

        logger.info('Done: %d lead(s), %d phone row update(s)', total_leads, total_phones)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
