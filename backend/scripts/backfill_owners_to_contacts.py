"""Sync flat owner/owner_2/phones/emails into PropertyContacts.

Usage:
    cd backend
    python scripts/backfill_owners_to_contacts.py --dry-run
    python scripts/backfill_owners_to_contacts.py --apply
    python scripts/backfill_owners_to_contacts.py --apply --lead-id 123
"""
from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description='Backfill flat owners into contacts')
    parser.add_argument('--dry-run', action='store_true', help='Report only (default)')
    parser.add_argument('--apply', action='store_true', help='Write changes')
    parser.add_argument('--lead-id', type=int, action='append', dest='lead_ids')
    args = parser.parse_args()
    apply = bool(args.apply)
    if not apply:
        args.dry_run = True

    from app import create_app, db
    from app.models.lead import Lead
    from app.services.contact_service import ContactService

    app = create_app()
    with app.app_context():
        q = Lead.query
        if args.lead_ids:
            q = q.filter(Lead.id.in_(args.lead_ids))
        else:
            q = q.filter(
                db.or_(
                    Lead.owner_first_name.isnot(None),
                    Lead.owner_last_name.isnot(None),
                    Lead.owner_2_first_name.isnot(None),
                    Lead.owner_2_last_name.isnot(None),
                    Lead.phone_1.isnot(None),
                    Lead.email_1.isnot(None),
                )
            )
        leads = q.order_by(Lead.id).all()
        logger.info('Candidates: %d (apply=%s)', len(leads), apply)
        svc = ContactService()
        processed = 0
        for lead in leads:
            if args.dry_run and not apply:
                logger.info(
                    'would upsert lead_id=%s owners=%s %s / %s %s',
                    lead.id,
                    lead.owner_first_name,
                    lead.owner_last_name,
                    lead.owner_2_first_name,
                    lead.owner_2_last_name,
                )
                processed += 1
                continue
            try:
                svc.upsert_owners_from_lead(lead, commit=True, refresh_scoring=False)
                processed += 1
            except Exception as exc:
                db.session.rollback()
                logger.warning('lead_id=%s failed: %s', lead.id, exc)
        logger.info('Done. processed=%d', processed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
