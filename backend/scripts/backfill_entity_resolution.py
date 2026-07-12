#!/usr/bin/env python
"""Backfill Illinois LLC entity resolution for leads with entity primary contacts.

Usage (from backend/)::

    python scripts/backfill_entity_resolution.py --dry-run
    python scripts/backfill_entity_resolution.py --apply --limit 50

Requires free Illinois SOS bulk data loaded via::

    python scripts/import_il_sos_llc_bulk.py --apply
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger('backfill_entity_resolution')


def _iter_candidate_lead_ids(limit: int | None):
    from app import db
    from app.models.contact import Contact
    from app.models.property_contact import PropertyContact
    from app.services.plugins.owner_name_utils import is_entity_contact

    q = (
        db.session.query(PropertyContact.property_id, Contact.first_name, Contact.last_name)
        .join(Contact, Contact.id == PropertyContact.contact_id)
        .filter(PropertyContact.is_primary.is_(True))
        .order_by(PropertyContact.property_id.asc())
    )
    seen = set()
    count = 0
    for lead_id, first, last in q.yield_per(200):
        if lead_id in seen:
            continue
        if not is_entity_contact(first, last):
            continue
        seen.add(lead_id)
        yield lead_id
        count += 1
        if limit is not None and count >= limit:
            break


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='Preview without DB writes')
    mode.add_argument('--apply', action='store_true', help='Run live entity resolution')
    parser.add_argument('--limit', type=int, default=None, help='Max leads to process')
    args = parser.parse_args()

    from app import create_app
    from app.services.entity_resolution_service import EntityResolutionService

    app = create_app()
    with app.app_context():
        service = EntityResolutionService()
        lead_ids = list(_iter_candidate_lead_ids(args.limit))
        logger.info('Found %d entity-primary candidate leads', len(lead_ids))

        ok = err = skipped = 0
        for lead_id in lead_ids:
            try:
                result = service.resolve_lead(lead_id, dry_run=args.dry_run)
            except Exception as exc:  # noqa: BLE001
                err += 1
                logger.error('lead %s failed: %s', lead_id, exc)
                continue
            status = result.status
            if status == 'skipped':
                skipped += 1
            elif status in ('error',):
                err += 1
            else:
                ok += 1
            logger.info(
                'lead=%s status=%s person_found=%s org=%s %s',
                lead_id,
                result.status,
                result.person_found,
                result.organization_id,
                result.message or '',
            )

        logger.info(
            'Done. ok=%s skipped=%s err=%s dry_run=%s',
            ok, skipped, err, args.dry_run,
        )
    return 0 if err == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
