"""Backfill structured city/state/zip from one-line mailing or property addresses.

Dry-run by default. Pass --apply to mutate the database.

Run from backend/:
    python scripts/backfill_parsed_mailing_addresses.py [--apply] [--limit N]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from env_loader import load_project_env

load_project_env()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('backfill_parsed_mailing_addresses')

from app import create_app, db
from app.models.lead import Lead
from app.services.open_letter_contact_mapper import (
    is_mailable_lead,
    persist_embedded_address_fields,
    validate_lead_mail_address,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist parsed fields (default is dry-run)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Max leads to scan',
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        query = Lead.query.filter(Lead.recommended_action == 'mail_ready').order_by(Lead.id)
        if args.limit is not None:
            query = query.limit(args.limit)

        updated = 0
        still_invalid = 0
        scanned = 0

        for lead in query.all():
            if validate_lead_mail_address(lead) is None:
                continue
            scanned += 1

            changed = persist_embedded_address_fields(lead)
            if changed and is_mailable_lead(lead):
                updated += 1
                logger.info(
                    'lead %s parsed: property=%r, %s %s %s',
                    lead.id,
                    lead.property_street,
                    lead.property_city,
                    lead.property_state,
                    lead.property_zip,
                )
            elif changed:
                still_invalid += 1
                logger.info(
                    'lead %s parse incomplete: street=%r',
                    lead.id,
                    lead.property_street or lead.mailing_address,
                )
            else:
                still_invalid += 1

            if not args.apply:
                db.session.rollback()

        if args.apply:
            db.session.commit()
            logger.info(
                'Committed %s updated leads (scanned %s, %s still invalid)',
                updated,
                scanned,
                still_invalid,
            )
        else:
            db.session.rollback()
            logger.info(
                'Dry run: would update %s of %s scanned leads (%s still invalid). Re-run with --apply.',
                updated,
                scanned,
                still_invalid,
            )


if __name__ == '__main__':
    main()
