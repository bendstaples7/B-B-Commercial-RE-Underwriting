"""Rescore residential skip-trace leads that have a mailing address.

Promotes them to mailing_no_contact_made via LeadScoringEngine and refreshes
recommended_action.

Usage:
    cd backend
    python scripts/rescore_skip_trace_with_mailing.py --dry-run
    python scripts/rescore_skip_trace_with_mailing.py --apply
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Report only (default)')
    parser.add_argument('--apply', action='store_true', help='Write changes')
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error('--dry-run and --apply are mutually exclusive')
    apply = bool(args.apply)

    from app import create_app, db
    from app.models.lead import Lead
    from app.services.lead_scoring_engine import LeadScoringEngine

    app = create_app()
    failures = 0
    with app.app_context():
        leads = (
            Lead.query
            .filter(Lead.lead_status.in_(['skip_trace', 'awaiting_skip_trace']))
            .filter(Lead.mailing_address.isnot(None))
            .filter(db.func.btrim(Lead.mailing_address) != '')
            .filter(db.or_(Lead.lead_category.is_(None), Lead.lead_category != 'commercial'))
            .order_by(Lead.id)
            .all()
        )
        logger.info('Found %d residential skip-trace leads with mailing_address', len(leads))
        for lead in leads:
            if not apply:
                logger.info('would rescore lead_id=%s status=%s', lead.id, lead.lead_status)
                continue
            try:
                LeadScoringEngine.score_and_persist(lead.id)
                db.session.refresh(lead)
                logger.info(
                    'rescored lead_id=%s status=%s action=%s',
                    lead.id, lead.lead_status, lead.recommended_action,
                )
            except Exception as exc:
                failures += 1
                db.session.rollback()
                logger.error('rescore failed lead_id=%s: %s', lead.id, exc)
        logger.info('Done apply=%s count=%d failures=%d', apply, len(leads), failures)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
